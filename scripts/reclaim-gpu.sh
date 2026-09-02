#!/usr/bin/env bash

# Creates a Vast-managed owner on-demand instance on the owned machine. Vast's
# scheduler, not this script, pauses an outside interruptible renter.

set -Eeuo pipefail
IFS=$'\n\t'

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

load_env_file

apply=false
contracts_reviewed=false
machine_id="${VAST_MACHINE_ID:-}"
offer_id="${VAST_OWN_OFFER_ID:-}"
image="${VAST_OWN_IMAGE:-pytorch/pytorch:latest}"
disk_gb="${VAST_OWN_DISK_GB:-20}"
label_prefix="${VAST_OWN_LABEL_PREFIX:-owned-reclaim}"

usage() {
  cat <<'EOF'
Usage: reclaim-gpu.sh [options]

Options:
  --machine-id ID          Owned Vast machine ID (or VAST_MACHINE_ID)
  --offer-id ID            This machine's on-demand offer ID
  --image IMAGE            Owner workload image
  --disk GB                Owner instance disk size
  --contracts-reviewed     Operator reviewed Host Machines/Contracts and found
                           no outside on-demand or reserved contract
  --apply                  Create the owner on-demand instance
  -h, --help               Show help

Default mode is read-only dry run. Apply mode remains interactive and fails
closed. Do not pass --bid_price: this owner instance must be on-demand.
EOF
}

while (( $# > 0 )); do
  case "$1" in
    --machine-id) machine_id="${2:-}"; shift 2 ;;
    --offer-id) offer_id="${2:-}"; shift 2 ;;
    --image) image="${2:-}"; shift 2 ;;
    --disk) disk_gb="${2:-}"; shift 2 ;;
    --contracts-reviewed) contracts_reviewed=true; shift ;;
    --apply) apply=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

require_uint "machine ID" "$machine_id"
require_uint "on-demand offer ID" "$offer_id"
require_uint "disk GB" "$disk_gb"
[[ "$label_prefix" =~ ^[A-Za-z0-9._-]+$ ]] || die "VAST_OWN_LABEL_PREFIX contains unsupported characters"
[[ -n "$image" ]] || die "Owner image cannot be empty"
require_cmd vastai
require_cmd jq

state_root="$(state_dir)"
state_file="${state_root}/active-reclaim.json"
pending_file="${state_root}/pending-reclaim.json"
lock_dir="${state_root}/reclaim.lock"
if [[ -e "$state_file" || -e "$pending_file" ]]; then
  die "Active or pending reclaim state exists under ${state_root}. Release or investigate it before creating another owner instance."
fi

note "Reading machine and on-demand offer before any mutation..."
machine_json="$(vastai show machine "$machine_id" --raw)" || die "Could not read machine ${machine_id}"
offer_json="$(vastai search offers "machine_id=${machine_id} verified=any" --type on-demand --raw)" \
  || die "Could not search on-demand offers for machine ${machine_id}"

jq -e . >/dev/null <<<"$machine_json" || die "Machine output was not valid JSON"
jq -e . >/dev/null <<<"$offer_json" || die "Offer output was not valid JSON"

machine_matches="$(jq --arg mid "$machine_id" '
  [if type == "array" then .[] else empty end
   | select(((.id? // .machine_id? // "") | tostring) == $mid)]
  | length
' <<<"$machine_json")"
[[ "$machine_matches" == 1 ]] \
  || die "Machine ${machine_id} was not returned exactly once by the owned-machine endpoint"

offer_matches="$(jq --arg oid "$offer_id" --arg mid "$machine_id" '
  [if type == "array" then .[] else empty end
    | select(((.id? // .ask_contract_id? // .contract_id? // "") | tostring) == $oid)
    | select(((.machine_id? // "") | tostring) == $mid)]
  | length
' <<<"$offer_json")"

if [[ "$offer_matches" != 1 ]]; then
  die "Offer ${offer_id} was not found exactly once as an on-demand offer for machine ${machine_id}. Refusing to create."
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
label="${label_prefix}-${timestamp}"
create_cmd=(
  vastai create instance "$offer_id"
  --image "$image"
  --disk "$disk_gb"
  --ssh --direct
  --label "$label"
  --cancel-unavail
  --raw
)

note ""
note "Planned owner instance:"
printf '  machine=%s offer=%s image=%s disk_gb=%s label=%s\n' \
  "$machine_id" "$offer_id" "$image" "$disk_gb" "$label"
note "This is on-demand because the command intentionally omits --bid_price."

if [[ "$apply" != true ]]; then
  run_or_preview false "${create_cmd[@]}"
  note ""
  note "No changes made. Before apply, open Host Machines/Contracts and confirm every outside contract is interruptible/bid. The CLI's owner-visible instance list is not a complete renter inventory."
  exit 0
fi

[[ "$contracts_reviewed" == true ]] \
  || die "--apply requires --contracts-reviewed after checking Host Machines/Contracts"

if [[ ! -t 0 ]]; then
  die "Apply mode requires an interactive terminal"
fi

note ""
note "Stop if any outside on-demand or reserved contract exists. It must be honored."
printf 'Type RECLAIM %s to confirm the host contract review: ' "$machine_id" >&2
IFS= read -r confirmation
[[ "$confirmation" == "RECLAIM ${machine_id}" ]] || die "Confirmation did not match"

ensure_state_dir >/dev/null
if ! mkdir -- "$lock_dir" 2>/dev/null; then
  die "Another reclaim may be running or a prior attempt needs review: ${lock_dir}"
fi
pending_tmp="${pending_file}.tmp"
cleanup_local_lock() {
  rm -f -- "$pending_tmp"
  rmdir -- "$lock_dir" 2>/dev/null || true
}
trap cleanup_local_lock EXIT

[[ ! -e "$state_file" && ! -e "$pending_file" ]] \
  || die "Reclaim state appeared while waiting for the lock; refusing to create"

snapshot_dir="${state_root}/snapshots/${timestamp}-before-reclaim"
mkdir -p -- "${state_root}/snapshots"
mkdir -- "$snapshot_dir"
chmod 700 -- "$snapshot_dir" 2>/dev/null || true
printf '%s\n' "$machine_json" >"${snapshot_dir}/machine.json"
printf '%s\n' "$offer_json" >"${snapshot_dir}/on-demand-offers.json"
chmod 600 -- "${snapshot_dir}"/*.json 2>/dev/null || true

# Persist intent before the non-idempotent create call. If the process or
# network dies at the wrong moment, this sentinel blocks a duplicate reclaim.
jq -n \
  --arg machine_id "$machine_id" \
  --arg offer_id "$offer_id" \
  --arg label "$label" \
  --arg image "$image" \
  --arg created_at "$timestamp" \
  '{status:"create-pending", machine_id:$machine_id, offer_id:$offer_id, label:$label, image:$image, created_at:$created_at}' \
  >"$pending_tmp"
mv -- "$pending_tmp" "$pending_file"

note "Creating owner on-demand instance..."
if ! create_output="$("${create_cmd[@]}" 2> >(redact_cli_error >&2))"; then
  die "Create did not complete cleanly. Its outcome may be uncertain; inspect Vast Instances for label ${label}. Pending state was retained at ${pending_file}."
fi

jq -e . >/dev/null <<<"$create_output" \
  || die "Create returned non-JSON output. Inspect Vast Instances for label ${label}; pending state was retained."

own_instance_id="$(jq -er '(.new_contract // .contract_id // .id) | select(. != null) | tostring' <<<"$create_output")" \
  || die "Create response lacked an instance ID. Inspect Vast Instances for label ${label}; pending state was retained."
require_uint "returned owner instance ID" "$own_instance_id"

tmp_state="${state_file}.tmp"
jq -n \
  --arg machine_id "$machine_id" \
  --arg offer_id "$offer_id" \
  --arg instance_id "$own_instance_id" \
  --arg label "$label" \
  --arg image "$image" \
  --arg created_at "$timestamp" \
  '{machine_id:$machine_id, offer_id:$offer_id, instance_id:$instance_id, label:$label, image:$image, created_at:$created_at}' \
  >"$tmp_state"
chmod 600 -- "$tmp_state" 2>/dev/null || true
mv -- "$tmp_state" "$state_file"
mv -- "$pending_file" "${snapshot_dir}/create-intent.json"

note "Owner instance created: ${own_instance_id}"
note "Private state: ${state_file}"
note "Now verify: owner instance reaches running; outside interruptible is platform-paused; daemon, thermals, power, disk, and network remain healthy. Never kill the outside container."
