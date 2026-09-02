#!/usr/bin/env bash

# Read-only snapshots for the machine, offers, owner-visible instances, daemon,
# GPU health, and disks. Host-side outside contract type must still be reviewed
# in Vast's Machines/Contracts view.

set -Eeuo pipefail
IFS=$'\n\t'

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

load_env_file

machine_id="${VAST_MACHINE_ID:-}"
snapshot=false

usage() {
  cat <<'EOF'
Usage: monitor-machine.sh [--machine-id ID] [--snapshot]

Read-only. --snapshot writes private raw output under VAST_STATE_DIR, outside
the repository. It may contain machine/network identifiers.
EOF
}

while (( $# > 0 )); do
  case "$1" in
    --machine-id) machine_id="${2:-}"; shift 2 ;;
    --snapshot) snapshot=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

require_uint "machine ID" "$machine_id"
require_cmd vastai

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ "$snapshot" == true ]]; then
  out_dir="$(ensure_state_dir)/snapshots/${timestamp}"
  mkdir -p -- "$out_dir"
  chmod 700 -- "$out_dir" 2>/dev/null || true
else
  out_dir=""
fi

capture() {
  local name="$1"
  shift
  note ""
  note "== ${name} =="
  if [[ -n "$out_dir" ]]; then
    "$@" 2>&1 | tee "${out_dir}/${name}.txt"
  else
    "$@"
  fi
}

capture machine vastai show machine "$machine_id" --raw
capture offers-on-demand vastai search offers "machine_id=${machine_id} verified=any" --type on-demand --raw
capture offers-bid vastai search offers "machine_id=${machine_id} verified=any" --type bid --raw
capture owner-visible-instances vastai show instances --raw

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files vastai.service >/dev/null 2>&1; then
  capture daemon systemctl status vastai --no-pager
else
  warn "Local Vast service unavailable; run this on the host for daemon health"
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  capture gpu nvidia-smi --query-gpu=index,name,temperature.gpu,power.draw,power.limit,memory.used,memory.total,utilization.gpu --format=csv
fi

if command -v df >/dev/null 2>&1; then
  capture disks df -hT / /var/lib/docker
fi

if [[ -n "$out_dir" ]]; then
  note ""
  note "Private snapshot: ${out_dir}"
fi

note "Review the Host Machines/Contracts view separately. The CLI's 'show instances' lists the current account's instances and must not be treated as a complete outside-renter inventory."
