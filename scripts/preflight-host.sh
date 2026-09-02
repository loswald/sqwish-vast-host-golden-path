#!/usr/bin/env bash

# Read-only preflight for an owned server. It deliberately does not install,
# format, mount, open ports, or change services.

set -Eeuo pipefail
IFS=$'\n\t'

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

load_env_file

warnings=0
failures=0

pass() { printf 'PASS  %s\n' "$*"; }
flag_warn() { printf 'WARN  %s\n' "$*"; warnings=$((warnings + 1)); }
fail() { printf 'FAIL  %s\n' "$*"; failures=$((failures + 1)); }

note "Vast owned-host read-only preflight"
note ""

if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  if [[ "${ID:-}" == ubuntu && ( "${VERSION_ID:-}" == 22.04 || "${VERSION_ID:-}" == 24.04 ) ]]; then
    pass "Ubuntu Server-compatible release: ${PRETTY_NAME:-Ubuntu}"
  else
    fail "Official verification requires Ubuntu Server 22.04 or 24.04; found ${PRETTY_NAME:-unknown}"
  fi
else
  fail "Cannot read /etc/os-release"
fi

case "$(uname -m)" in
  x86_64|aarch64|arm64) pass "Supported CPU architecture: $(uname -m)" ;;
  *) fail "Unsupported CPU architecture: $(uname -m)" ;;
esac

if grep -qm1 -E '(^|[[:space:]])avx([[:space:]]|$)' /proc/cpuinfo; then
  pass "AVX CPU flag present"
else
  fail "AVX CPU flag not detected"
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  mapfile -t gpu_rows < <(nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader 2>/dev/null || true)
  if (( ${#gpu_rows[@]} > 0 )); then
    pass "NVIDIA driver sees ${#gpu_rows[@]} GPU(s)"
    printf '      %s\n' "${gpu_rows[@]}"
    gpu_names="$(nvidia-smi --query-gpu=name --format=csv,noheader | sed 's/[[:space:]]*$//' | sort -u)"
    unique_names="$(printf '%s\n' "$gpu_names" | sed '/^$/d' | wc -l | tr -d ' ')"
    if [[ "$unique_names" == 1 ]]; then
      pass "All detected GPU model names are identical"
    else
      fail "Mixed GPU models detected; official verification requires identical models"
    fi

    mapfile -t gpu_memory_mib < <(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | tr -d ' ')
    aggregate_vram_mib=0
    vram_requirement_ok=true
    for memory_mib in "${gpu_memory_mib[@]}"; do
      if [[ ! "$memory_mib" =~ ^[0-9]+$ ]] || (( memory_mib <= 7 * 1024 )); then
        vram_requirement_ok=false
      else
        aggregate_vram_mib=$((aggregate_vram_mib + memory_mib))
      fi
    done
    [[ "$vram_requirement_ok" == true ]] \
      && pass "Every GPU has more than 7 GiB VRAM" \
      || fail "At least one GPU does not meet the more-than-7-GiB VRAM requirement"

    system_ram_kib="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
    required_ram_kib=$((aggregate_vram_mib * 1024 * 95 / 100))
    if [[ "$system_ram_kib" =~ ^[0-9]+$ ]] && (( system_ram_kib >= required_ram_kib )); then
      pass "System RAM meets 95% of aggregate GPU VRAM minimum"
    else
      fail "System RAM is below 95% of aggregate GPU VRAM"
    fi
  else
    fail "nvidia-smi returned no GPUs"
  fi
else
  fail "nvidia-smi not installed"
  gpu_rows=()
fi

gpu_count="${#gpu_rows[@]}"
if [[ -n "${VAST_GPU_COUNT:-}" && "$VAST_GPU_COUNT" != "$gpu_count" ]]; then
  fail "Configured VAST_GPU_COUNT=${VAST_GPU_COUNT} differs from detected ${gpu_count}"
fi

physical_cores="$(lscpu -p=CORE,SOCKET 2>/dev/null | sed '/^#/d' | sort -u | wc -l | tr -d ' ')"
if [[ "$gpu_count" =~ ^[1-9][0-9]*$ ]] && (( physical_cores >= gpu_count * 2 )); then
  pass "Physical CPU cores (${physical_cores}) meet two-per-GPU minimum"
else
  fail "Physical CPU cores (${physical_cores}) do not meet two-per-GPU minimum or GPU count is unknown"
fi

if command -v mokutil >/dev/null 2>&1; then
  secure_boot="$(mokutil --sb-state 2>/dev/null || true)"
  if grep -qi 'disabled' <<<"$secure_boot"; then
    pass "Secure Boot is disabled"
  else
    flag_warn "Could not confirm Secure Boot disabled: ${secure_boot:-no result}"
  fi
else
  flag_warn "mokutil unavailable; confirm Secure Boot is disabled in firmware"
fi

root_free_kb="$(df -Pk / | awk 'NR==2 {print $4}')"
if [[ "$root_free_kb" =~ ^[0-9]+$ ]] && (( root_free_kb >= 20 * 1024 * 1024 )); then
  pass "Root has at least 20 GiB free"
else
  fail "Root has less than 20 GiB free"
fi

if findmnt -rn /var/lib/docker >/dev/null 2>&1; then
  docker_fs="$(findmnt -rn -o FSTYPE /var/lib/docker)"
  docker_opts="$(findmnt -rn -o OPTIONS /var/lib/docker)"
  docker_kb="$(df -Pk /var/lib/docker | awk 'NR==2 {print $2}')"
  [[ "$docker_fs" == xfs ]] && pass "/var/lib/docker is XFS" || fail "/var/lib/docker is ${docker_fs}, expected XFS"
  if grep -Eq '(^|,)(pquota|prjquota)(,|$)' <<<"$docker_opts"; then
    pass "/var/lib/docker has project quotas"
  else
    fail "/var/lib/docker lacks pquota/prjquota"
  fi
  if [[ "$docker_kb" =~ ^[0-9]+$ ]] && (( docker_kb >= 200 * 1024 * 1024 )); then
    pass "/var/lib/docker filesystem is at least 200 GiB"
  else
    fail "/var/lib/docker filesystem is smaller than 200 GiB"
  fi
else
  flag_warn "/var/lib/docker is not a separate mount; review an empty dedicated SSD/NVMe before installation"
fi

if command -v sshd >/dev/null 2>&1; then
  sshd_config="$(sshd -T 2>/dev/null || true)"
  grep -q '^passwordauthentication no$' <<<"$sshd_config" \
    && pass "SSH password authentication disabled" \
    || fail "SSH password authentication is not confirmed disabled"
  grep -q '^pubkeyauthentication yes$' <<<"$sshd_config" \
    && pass "SSH public-key authentication enabled" \
    || fail "SSH public-key authentication is not confirmed enabled"
else
  fail "sshd command unavailable"
fi

if [[ -n "${VAST_DIRECT_PORT_START:-}" && -n "${VAST_DIRECT_PORT_END:-}" ]]; then
  if [[ "$VAST_DIRECT_PORT_START" =~ ^[0-9]+$ && "$VAST_DIRECT_PORT_END" =~ ^[0-9]+$ \
        && "$gpu_count" =~ ^[1-9][0-9]*$ \
        && "$VAST_DIRECT_PORT_START" -ge 1 && "$VAST_DIRECT_PORT_END" -le 65535 \
        && "$VAST_DIRECT_PORT_END" -ge "$VAST_DIRECT_PORT_START" ]]; then
    port_count=$((VAST_DIRECT_PORT_END - VAST_DIRECT_PORT_START + 1))
    if (( port_count >= gpu_count * 5 )); then
      pass "Configured direct range has ${port_count} ports (${gpu_count} GPU(s), minimum five/GPU)"
    else
      fail "Configured direct range has ${port_count} ports; need at least $((gpu_count * 5))"
    fi
  else
    fail "Direct port range values are invalid"
  fi
else
  flag_warn "Direct port range not set in .env; confirm contiguous TCP and UDP range, five/GPU minimum and 100/GPU recommended"
fi

if command -v docker >/dev/null 2>&1; then
  docker info >/dev/null 2>&1 && pass "Docker daemon responds" || flag_warn "Docker installed but daemon did not respond"
else
  flag_warn "Docker absent; preferred fresh-host path lets the official Vast installer configure it"
fi

if [[ -f /var/lib/vastai_kaalia/enable_vms.py ]]; then
  vm_status="$(python3 /var/lib/vastai_kaalia/enable_vms.py check 2>/dev/null || true)"
  [[ "$vm_status" == *off* ]] && pass "Vast VM mode reports off" || fail "Vast VM mode is not confirmed off: ${vm_status:-no result}"
else
  flag_warn "Vast host manager not installed yet; VM-mode check will apply after installation"
fi

note ""
note "Manual checks still required: owned dedicated hardware; server edition; identical >7 GiB GPUs; RAM >=95% aggregate VRAM; PCIe >2.85 GiB/s/GPU; wired public IPv4; symmetric 500 Mbps; external TCP+UDP port test; unique SSH key; power/cooling stress test."
note ""
printf 'Result: %d failure(s), %d warning(s)\n' "$failures" "$warnings"

(( failures == 0 ))
