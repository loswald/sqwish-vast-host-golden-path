#!/usr/bin/env bash

# Destroys only the recorded owner reclaim instance, then captures health while
# Vast gives priority back to an eligible interruptible renter.

set -Eeuo pipefail
IFS=$'\n\t'

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

load_env_file

apply=false
wait_seconds=180
override_instance_id=""
override_machine_id=""
override_label=""

usage() {
  cat <<'EOF'
Usage: release-gpu.sh [options]

Options:
  --apply                    Destroy the verified owner instance
  --wait-seconds N           Read-only post-release observation period (default 180)
  --instance-id ID           Recovery override if the private state file was lost
  --machine-id ID            Required with --instance-id
  --expected-label LABEL     Required with --instance-id
  -h, --help                 Show help

Default mode is dry run. Destroy is irreversible and deletes the owner instance
data. Persist owner outputs before applying.
EOF
}

while (( $# > 0 )); do
  case "$1" in
    --apply) apply=true; shift ;;
    --wait-seconds) wait_seconds="${2:-}"; shift 2 ;;
    --instance-id) override_instance_id="${2:-}"; shift 2 ;;
    --machine-id) override_machine_id="${2:-}"; shift 2 ;;
    --expected-label) override_label="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

[[ "$wait_seconds" =~ ^[0-9]+$ ]] || die "wait seconds must be a non-negative integer"
require_cmd vastai
require_cmd jq

state_root="$(state_dir)"
state_file="${state_root}/active-reclaim.json"
pending_file="${state_root}/pending-reclaim.json"
using_state_file=false

if [[ -n "$override_instance_id" || -n "$override_machine_id" || -n "$override_label" ]]; then
  require_uint "override instance ID" "$override_instance_id"
  require_uint "override machine ID" "$override_machine_id"
  [[ -n "$override_label" ]] || die "--expected-label is required with an override instance ID"
  own_instance_id="$override_instance_id"
  machine_id="$override_machine_id"
  expected_label="$override_label"
else
  [[ -f "$state_file" ]] || die "No active reclaim state at ${state_file}; use all three recovery override options after independent verification"
  jq -e . >/dev/null <"$state_file" || die "Active reclaim state is invalid JSON"
  own_instance_id="$(jq -er '.instance_id | tostring' "$state_file")"
  machine_id="$(jq -er '.machine_id | tostring' "$state_file")"
  expected_label="$(jq -er '.label' "$state_file")"
  require_uint "state instance ID" "$own_instance_id"
  require_uint "state machine ID" "$machine_id"
  [[ -n "$expected_label" ]] || die "State label is empty"
  using_state_file=true
fi

note "Reading owner instance ${own_instance_id} before any mutation..."
instance_json="$(vastai show instance "$own_instance_id" --raw)" \
  || die "Cannot read owner instance ${own_instance_id}; inspect the Vast Instances page"
jq -e . >/dev/null <<<"$instance_json" || die "Instance output was not valid JSON"

instance_record="$(jq -c --arg iid "$own_instance_id" '
  if type == "object"
     and (((.id? // .contract_id? // .instance_id? // "") | tostring) == $iid)
  then . else empty end
' <<<"$instance_json")"
[[ -n "$instance_record" ]] || die "Could not uniquely identify instance ${own_instance_id} in API response"

actual_machine_id="$(jq -er '(.machine_id // empty) | tostring' <<<"$instance_record")" \
  || die "Instance response did not include machine_id"
actual_label="$(jq -er '.label // empty' <<<"$instance_record")" \
  || die "Instance response did not include a label"

[[ "$actual_machine_id" == "$machine_id" ]] \
  || die "Instance machine ${actual_machine_id} does not match expected ${machine_id}"
[[ "$actual_label" == "$expected_label" ]] \
  || die "Instance label '${actual_label}' does not match expected '${expected_label}'"

destroy_cmd=(vastai destroy instance "$own_instance_id" --yes --raw)

note "Verified owner instance triple:"
printf '  instance=%s machine=%s label=%s\n' "$own_instance_id" "$machine_id" "$expected_label"

if [[ "$apply" != true ]]; then
  run_or_preview false "${destroy_cmd[@]}"
  note "No changes made. Persist owner outputs, then rerun with --apply."
  exit 0
fi

if [[ ! -t 0 ]]; then
  die "Apply mode requires an interactive terminal"
fi

printf 'Destroy deletes owner data. Type RELEASE %s to continue: ' "$own_instance_id" >&2
IFS= read -r confirmation
[[ "$confirmation" == "RELEASE ${own_instance_id}" ]] || die "Confirmation did not match"

released_at="$(date -u +%Y%m%dT%H%M%SZ)"
snapshot_dir="${state_root}/snapshots/${released_at}-after-release"
ensure_state_dir >/dev/null
mkdir -p -- "${state_root}/snapshots"
mkdir -- "$snapshot_dir"
chmod 700 -- "$snapshot_dir" 2>/dev/null || true
printf '%s\n' "$instance_json" >"${snapshot_dir}/owner-instance-before-destroy.json"
chmod 600 -- "${snapshot_dir}/owner-instance-before-destroy.json" 2>/dev/null || true

note "Destroying the verified owner instance only..."
if ! destroy_output="$("${destroy_cmd[@]}" 2> >(redact_cli_error >&2))"; then
  die "Vast destroy command failed; active state was retained"
fi
jq -e 'type == "object" and .success == true' >/dev/null <<<"$destroy_output" \
  || die "Vast did not confirm a successful destroy; active state was retained"
printf '%s\n' "$destroy_output" >"${snapshot_dir}/destroy-response.json"

if [[ "$using_state_file" == true ]]; then
  mv -- "$state_file" "${snapshot_dir}/released-reclaim-state.json"
fi

if [[ -f "$pending_file" ]]; then
  pending_matches="$(jq -r --arg mid "$machine_id" --arg label "$expected_label" '
    type == "object"
    and ((.machine_id? // "") | tostring) == $mid
    and (.label? // "") == $label
  ' "$pending_file" 2>/dev/null || true)"
  if [[ "$pending_matches" == true ]]; then
    mv -- "$pending_file" "${snapshot_dir}/resolved-pending-reclaim.json"
  else
    warn "A different or invalid pending reclaim file remains at ${pending_file}; investigate it separately"
  fi
fi

deadline=$((SECONDS + wait_seconds))
iteration=0
while (( SECONDS <= deadline )); do
  iteration=$((iteration + 1))
  vastai show machine "$machine_id" --raw \
    >"${snapshot_dir}/machine-${iteration}.json" \
    2>"${snapshot_dir}/machine-${iteration}.err" || true
  if command -v systemctl >/dev/null 2>&1; then
    systemctl is-active vastai >"${snapshot_dir}/daemon-${iteration}.txt" 2>&1 || true
  fi
  if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=index,temperature.gpu,power.draw,memory.used,utilization.gpu --format=csv \
      >"${snapshot_dir}/gpu-${iteration}.csv" 2>&1 || true
  fi
  (( SECONDS + 15 > deadline )) && break
  sleep 15
done

note "Owner instance released. Private post-release snapshots: ${snapshot_dir}"
note "Now confirm in Host Machines/Contracts that the outside interruptible automatically returns to running, and record resume delay plus reliability before/after. Do not manually start or kill its container."
