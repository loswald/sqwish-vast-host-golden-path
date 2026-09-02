#!/usr/bin/env bash

# Reclaims the owned GPUs with an owner on-demand instance. If
# VAST_OWN_INSTANCE_ID is configured, the script starts that exact stopped
# instance and never falls back to creating a replacement.

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
owner_instance_id="${VAST_OWN_INSTANCE_ID:-}"
expected_gpu_count="${VAST_GPU_COUNT:-}"
image="${VAST_OWN_IMAGE:-pytorch/pytorch:latest}"
disk_gb="${VAST_OWN_DISK_GB:-20}"
label_prefix="${VAST_OWN_LABEL_PREFIX:-owned-reclaim}"

usage() {
  cat <<'EOF'
Usage: reclaim-gpu.sh [options]

Options:
  --machine-id ID          Owned Vast machine ID (or VAST_MACHINE_ID)
  --offer-id ID            This machine's expected on-demand offer ID
  --owner-instance-id ID   Start this exact pre-created stopped owner instance
  --image IMAGE            Fresh-created owner workload image
  --disk GB                Fresh-created owner instance disk size
  --contracts-reviewed     Operator reviewed Host Machines/Contracts and found
                           no outside on-demand or reserved contract
  --apply                  Start or create the verified owner instance
  -h, --help               Show help

Default mode is read-only. Setting VAST_OWN_INSTANCE_ID selects pre-created
mode; validation failure aborts and cannot fall back to a fresh create. Apply
mode remains interactive. Owner instances must be on-demand.
EOF
}

while (( $# > 0 )); do
  case "$1" in
    --machine-id) machine_id="${2:-}"; shift 2 ;;
    --offer-id) offer_id="${2:-}"; shift 2 ;;
    --owner-instance-id) owner_instance_id="${2:-}"; shift 2 ;;
    --image) image="${2:-}"; shift 2 ;;
    --disk) disk_gb="${2:-}"; shift 2 ;;
    --contracts-reviewed) contracts_reviewed=true; shift ;;
    --apply) apply=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

require_uint "machine ID" "$machine_id"
[[ "$label_prefix" =~ ^[A-Za-z0-9._-]+$ ]] || die "VAST_OWN_LABEL_PREFIX contains unsupported characters"
[[ -n "$label_prefix" ]] || die "VAST_OWN_LABEL_PREFIX cannot be empty"
if [[ -n "$offer_id" ]]; then
  require_uint "on-demand offer ID" "$offer_id"
fi
if [[ -n "$expected_gpu_count" ]]; then
  require_uint "expected GPU count" "$expected_gpu_count"
fi
require_cmd vastai
require_cmd jq

state_root="$(state_dir)"
state_file="${state_root}/active-reclaim.json"
pending_file="${state_root}/pending-reclaim.json"
lock_dir="${state_root}/reclaim.lock"
if [[ -e "$state_file" || -e "$pending_file" ]]; then
  die "Active or pending reclaim state exists under ${state_root}. Release or investigate it before reclaiming again."
fi

instance_record=""
validated_label=""
validated_actual_status=""
validated_intended_status=""
validated_cur_state=""
validated_gpu_count=""
validated_instance_offer=""

validate_precreated_instance() {
  local json="$1" required_state="$2"
  local actual_machine actual_is_bid expected_label_pattern actual_offer actual_gpu

  jq -e . >/dev/null <<<"$json" || die "Instance output was not valid JSON"
  instance_record="$(jq -c --arg iid "$owner_instance_id" '
    if type == "object"
       and (((.id? // .contract_id? // .instance_id? // "") | tostring) == $iid)
    then . else empty end
  ' <<<"$json")"
  [[ -n "$instance_record" ]] || die "Response did not identify exact owner instance ${owner_instance_id}"

  actual_machine="$(jq -er '(.machine_id // empty) | tostring' <<<"$instance_record")" \
    || die "Owner instance response did not include machine_id"
  [[ "$actual_machine" == "$machine_id" ]] \
    || die "Owner instance machine ${actual_machine} does not match expected ${machine_id}"

  validated_label="$(jq -er '.label // empty' <<<"$instance_record")" \
    || die "Owner instance response did not include a label"
  expected_label_pattern="^${label_prefix}([._-].+)?$"
  [[ "$validated_label" =~ $expected_label_pattern ]] \
    || die "Owner label '${validated_label}' does not match prefix '${label_prefix}'"

  actual_is_bid="$(jq -r 'if has("is_bid") and (.is_bid | type) == "boolean" then (.is_bid | tostring) else "missing" end' <<<"$instance_record")"
  [[ "$actual_is_bid" == false ]] \
    || die "Owner instance must explicitly report is_bid=false; got ${actual_is_bid}"

  validated_actual_status="$(jq -r '(.actual_status // "") | tostring' <<<"$instance_record")"
  validated_intended_status="$(jq -r '(.intended_status // "") | tostring' <<<"$instance_record")"
  validated_cur_state="$(jq -r '(.cur_state // "") | tostring' <<<"$instance_record")"
  case "$required_state" in
    "") ;;
    stopped)
      instance_status_is_safely_stopped \
        "$validated_actual_status" "$validated_intended_status" "$validated_cur_state" \
        || die "Owner instance ${owner_instance_id} status is actual=${validated_actual_status:-missing}, intended=${validated_intended_status:-missing}, cur_state=${validated_cur_state:-missing}; safely stopped requires actual=created|exited|stopped, intended=stopped, cur_state=stopped"
      ;;
    running)
      instance_status_is_exactly_running \
        "$validated_actual_status" "$validated_intended_status" "$validated_cur_state" \
        || die "Owner instance ${owner_instance_id} status is actual=${validated_actual_status:-missing}, intended=${validated_intended_status:-missing}, cur_state=${validated_cur_state:-missing}; running requires running/running/running"
      ;;
    *) die "Unsupported required owner instance state: ${required_state}" ;;
  esac

  actual_gpu="$(jq -r '(.num_gpus // .gpu_count // "") | tostring' <<<"$instance_record")"
  if [[ -n "$actual_gpu" ]]; then
    require_uint "owner instance GPU count" "$actual_gpu"
  fi
  if [[ -n "$expected_gpu_count" ]]; then
    [[ "$actual_gpu" == "$expected_gpu_count" ]] \
      || die "Owner instance GPU count '${actual_gpu:-missing}' does not match expected ${expected_gpu_count}"
  elif [[ -n "$actual_gpu" ]]; then
    expected_gpu_count="$actual_gpu"
  fi
  validated_gpu_count="$actual_gpu"

  actual_offer="$(jq -r '(.ask_contract_id // .offer_id // .ask_id // "") | tostring' <<<"$instance_record")"
  if [[ -n "$actual_offer" ]]; then
    require_uint "owner instance offer ID" "$actual_offer"
  fi
  if [[ -n "$offer_id" && -n "$actual_offer" && "$actual_offer" != "$offer_id" ]]; then
    die "Owner instance offer ${actual_offer} does not match expected ${offer_id}"
  fi
  validated_instance_offer="$actual_offer"
}

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"

if [[ -n "$owner_instance_id" ]]; then
  mode="precreated"
  require_uint "owner instance ID" "$owner_instance_id"

  offer_json=""
  if [[ -n "$offer_id" ]]; then
    note "Validating configured on-demand offer ${offer_id} for machine ${machine_id}..."
    offer_json="$(vastai search offers "machine_id=${machine_id} rentable=any rented=any" --type on-demand --no-default --raw)" \
      || die "Could not search on-demand offers for machine ${machine_id}"
    jq -e . >/dev/null <<<"$offer_json" || die "Offer output was not valid JSON"
    offer_record="$(jq -c --arg oid "$offer_id" --arg mid "$machine_id" '
      [if type == "array" then .[]
       elif type == "object" and has("offers") and (.offers | type) == "array" then .offers[]
       else empty end
       | select(((.id? // .ask_contract_id? // .contract_id? // "") | tostring) == $oid)
       | select(((.machine_id? // "") | tostring) == $mid)]
      | if length == 1 then .[0] else empty end
    ' <<<"$offer_json")"
    [[ -n "$offer_record" ]] \
      || die "Offer ${offer_id} was not found exactly once as on-demand on machine ${machine_id}"
    offer_gpu_count="$(jq -r '(.num_gpus // .gpu_count // "") | tostring' <<<"$offer_record")"
    if [[ -n "$offer_gpu_count" ]]; then
      require_uint "offer GPU count" "$offer_gpu_count"
      if [[ -n "$expected_gpu_count" && "$expected_gpu_count" != "$offer_gpu_count" ]]; then
        die "Configured GPU count ${expected_gpu_count} does not match offer ${offer_id} GPU count ${offer_gpu_count}"
      fi
      expected_gpu_count="$offer_gpu_count"
    fi
  fi

  note "Reading exact pre-created owner instance ${owner_instance_id} before any mutation..."
  instance_json="$(vastai show instance "$owner_instance_id" --raw)" \
    || die "Could not read owner instance ${owner_instance_id}"
  validate_precreated_instance "$instance_json" stopped

  note "Verified pre-created owner instance:"
  printf '  instance=%s machine=%s label=%s gpu_count=%s offer=%s status=%s/%s/%s\n' \
    "$owner_instance_id" "$machine_id" "$validated_label" \
    "${validated_gpu_count:-unknown}" "${validated_instance_offer:-${offer_id:-unknown}}" \
    "${validated_actual_status:-missing}" "${validated_intended_status:-missing}" \
    "${validated_cur_state:-missing}"
  start_cmd=(vastai start instance "$owner_instance_id" --raw)

  if [[ "$apply" != true ]]; then
    run_or_preview false "${start_cmd[@]}"
    note "No changes made. Pre-created mode cannot fall back to creating an instance."
    exit 0
  fi

  [[ "$contracts_reviewed" == true ]] \
    || die "--apply requires --contracts-reviewed after checking Host Machines/Contracts"
  [[ -t 0 ]] || die "Apply mode requires an interactive terminal"

  note "Stop if any outside on-demand or reserved contract exists. It must be honored."
  printf 'Type START %s ON %s to confirm the exact owner instance: ' "$owner_instance_id" "$machine_id" >&2
  IFS= read -r confirmation
  [[ "$confirmation" == "START ${owner_instance_id} ON ${machine_id}" ]] || die "Confirmation did not match"

  ensure_state_dir >/dev/null
  if ! mkdir -- "$lock_dir" 2>/dev/null; then
    die "Another reclaim/release may be running or a prior attempt needs review: ${lock_dir}"
  fi
  cleanup_local_lock() { rmdir -- "$lock_dir" 2>/dev/null || true; }
  trap cleanup_local_lock EXIT
  [[ ! -e "$state_file" && ! -e "$pending_file" ]] \
    || die "Reclaim state appeared while waiting for the lock"

  # Re-read under the lock so the stopped-status proof immediately precedes
  # the start mutation.
  locked_instance_json="$(vastai show instance "$owner_instance_id" --raw)" \
    || die "Could not re-read owner instance ${owner_instance_id} under the lock"
  validate_precreated_instance "$locked_instance_json" stopped

  snapshot_dir="${state_root}/snapshots/${timestamp}-before-reclaim"
  mkdir -p -- "${state_root}/snapshots"
  mkdir -- "$snapshot_dir"
  chmod 700 -- "$snapshot_dir" 2>/dev/null || true
  printf '%s\n' "$locked_instance_json" >"${snapshot_dir}/owner-instance-stopped.json"
  [[ -z "$offer_json" ]] || printf '%s\n' "$offer_json" >"${snapshot_dir}/on-demand-offers.json"

  tmp_state="${state_file}.tmp"
  jq -n \
    --arg mode "$mode" --arg status "start-pending" \
    --arg machine_id "$machine_id" --arg offer_id "$offer_id" \
    --arg instance_id "$owner_instance_id" --arg label "$validated_label" \
    --arg label_prefix "$label_prefix" --arg gpu_count "$expected_gpu_count" \
    --arg created_at "$timestamp" \
    '{mode:$mode,status:$status,machine_id:$machine_id,offer_id:$offer_id,instance_id:$instance_id,label:$label,label_prefix:$label_prefix,gpu_count:$gpu_count,created_at:$created_at}' \
    >"$tmp_state"
  chmod 600 -- "$tmp_state" 2>/dev/null || true
  mv -- "$tmp_state" "$state_file"

  note "Starting exact pre-created owner instance ${owner_instance_id}..."
  if start_output="$("${start_cmd[@]}" 2> >(redact_cli_error >&2))"; then
    start_status=0
  else
    start_status=$?
    warn "Start command exited ${start_status}; its output is not authoritative, so verifying exact instance status"
  fi
  [[ -z "$start_output" ]] || printf '%s\n' "$start_output" >"${snapshot_dir}/start-output.txt"

  running_confirmed=false
  for attempt in 1 2 3 4 5 6 7; do
    poll_json=""
    if poll_json="$(vastai show instance "$owner_instance_id" --raw 2> >(redact_cli_error >&2))" \
       && jq -e . >/dev/null 2>&1 <<<"$poll_json"; then
      printf '%s\n' "$poll_json" >"${snapshot_dir}/owner-instance-after-start-${attempt}.json"
      validate_precreated_instance "$poll_json" ""
      if instance_status_is_exactly_running \
        "$validated_actual_status" "$validated_intended_status" "$validated_cur_state"; then
        running_confirmed=true
        break
      fi
      if ! instance_status_is_safely_stopped \
        "$validated_actual_status" "$validated_intended_status" "$validated_cur_state"; then
        case "$validated_actual_status:$validated_intended_status:$validated_cur_state" in
          *exited*|*unknown*|*offline*)
            die "Owner instance entered an unhealthy/terminal status; active state was retained so release can stop it"
            ;;
        esac
      fi
    else
      warn "Could not obtain valid status on start verification attempt ${attempt}"
    fi
    (( attempt < 7 )) && sleep 5
  done
  [[ "$running_confirmed" == true ]] \
    || die "Could not prove exact owner instance ${owner_instance_id} reached running within 30 seconds. Active state was retained; run release to stop/cancel it."

  updated_state="${state_file}.tmp"
  jq '.status = "running-confirmed"' "$state_file" >"$updated_state"
  chmod 600 -- "$updated_state" 2>/dev/null || true
  mv -- "$updated_state" "$state_file"
  note "Pre-created owner instance ${owner_instance_id} is confirmed running. Private state: ${state_file}"
  note "Verify the outside interruptible is platform-paused and host health remains good. Never kill its container."
  exit 0
fi

# Fresh-created mode retains the guarded create workflow.
mode="fresh-created"
require_uint "on-demand offer ID" "$offer_id"
require_uint "disk GB" "$disk_gb"
[[ -n "$image" ]] || die "Owner image cannot be empty"

note "Reading machine and on-demand offer before any mutation..."
machine_json="$(vastai show machine "$machine_id" --raw)" || die "Could not read machine ${machine_id}"
offer_json="$(vastai search offers "machine_id=${machine_id} verified=any" --type on-demand --raw)" \
  || die "Could not search on-demand offers for machine ${machine_id}"
jq -e . >/dev/null <<<"$machine_json" || die "Machine output was not valid JSON"
jq -e . >/dev/null <<<"$offer_json" || die "Offer output was not valid JSON"

machine_matches="$(jq --arg mid "$machine_id" '[if type == "array" then .[] else empty end | select(((.id? // .machine_id? // "") | tostring) == $mid)] | length' <<<"$machine_json")"
[[ "$machine_matches" == 1 ]] || die "Machine ${machine_id} was not returned exactly once"
offer_matches="$(jq --arg oid "$offer_id" --arg mid "$machine_id" '[if type == "array" then .[] else empty end | select(((.id? // .ask_contract_id? // .contract_id? // "") | tostring) == $oid) | select(((.machine_id? // "") | tostring) == $mid)] | length' <<<"$offer_json")"
[[ "$offer_matches" == 1 ]] || die "Offer ${offer_id} was not found exactly once as on-demand on machine ${machine_id}"

label="${label_prefix}-${timestamp}"
create_cmd=(vastai create instance "$offer_id" --image "$image" --disk "$disk_gb" --ssh --direct --label "$label" --cancel-unavail --raw)
note "Planned fresh-created owner instance:"
printf '  machine=%s offer=%s image=%s disk_gb=%s label=%s\n' "$machine_id" "$offer_id" "$image" "$disk_gb" "$label"
if [[ "$apply" != true ]]; then
  run_or_preview false "${create_cmd[@]}"
  note "No changes made. Before apply, confirm every outside contract is interruptible/bid."
  exit 0
fi

[[ "$contracts_reviewed" == true ]] || die "--apply requires --contracts-reviewed after checking Host Machines/Contracts"
[[ -t 0 ]] || die "Apply mode requires an interactive terminal"
printf 'Type RECLAIM %s to confirm the host contract review: ' "$machine_id" >&2
IFS= read -r confirmation
[[ "$confirmation" == "RECLAIM ${machine_id}" ]] || die "Confirmation did not match"

ensure_state_dir >/dev/null
if ! mkdir -- "$lock_dir" 2>/dev/null; then
  die "Another reclaim/release may be running or a prior attempt needs review: ${lock_dir}"
fi
pending_tmp="${pending_file}.tmp"
cleanup_local_lock() { rm -f -- "$pending_tmp"; rmdir -- "$lock_dir" 2>/dev/null || true; }
trap cleanup_local_lock EXIT
[[ ! -e "$state_file" && ! -e "$pending_file" ]] || die "Reclaim state appeared while waiting for the lock"

snapshot_dir="${state_root}/snapshots/${timestamp}-before-reclaim"
mkdir -p -- "${state_root}/snapshots"
mkdir -- "$snapshot_dir"
chmod 700 -- "$snapshot_dir" 2>/dev/null || true
printf '%s\n' "$machine_json" >"${snapshot_dir}/machine.json"
printf '%s\n' "$offer_json" >"${snapshot_dir}/on-demand-offers.json"

jq -n --arg mode "$mode" --arg machine_id "$machine_id" --arg offer_id "$offer_id" \
  --arg label "$label" --arg image "$image" --arg gpu_count "$expected_gpu_count" --arg created_at "$timestamp" \
  '{mode:$mode,status:"create-pending",machine_id:$machine_id,offer_id:$offer_id,label:$label,image:$image,gpu_count:$gpu_count,created_at:$created_at}' >"$pending_tmp"
mv -- "$pending_tmp" "$pending_file"

note "Creating owner on-demand instance..."
if ! create_output="$("${create_cmd[@]}" 2> >(redact_cli_error >&2))"; then
  die "Create outcome may be uncertain; inspect Vast Instances for label ${label}. Pending state was retained."
fi
jq -e . >/dev/null <<<"$create_output" || die "Create returned non-JSON; inspect label ${label}. Pending state was retained."
own_instance_id="$(jq -er '(.new_contract // .contract_id // .id) | select(. != null) | tostring' <<<"$create_output")" \
  || die "Create response lacked an instance ID; inspect label ${label}. Pending state was retained."
require_uint "returned owner instance ID" "$own_instance_id"

tmp_state="${state_file}.tmp"
jq -n --arg mode "$mode" --arg machine_id "$machine_id" --arg offer_id "$offer_id" \
  --arg instance_id "$own_instance_id" --arg label "$label" --arg image "$image" \
  --arg gpu_count "$expected_gpu_count" --arg created_at "$timestamp" \
  '{mode:$mode,status:"created",machine_id:$machine_id,offer_id:$offer_id,instance_id:$instance_id,label:$label,image:$image,gpu_count:$gpu_count,created_at:$created_at}' >"$tmp_state"
chmod 600 -- "$tmp_state" 2>/dev/null || true
mv -- "$tmp_state" "$state_file"
mv -- "$pending_file" "${snapshot_dir}/create-intent.json"

note "Owner instance created: ${own_instance_id}. Private state: ${state_file}"
note "Verify it reaches running, the outside interruptible is platform-paused, and host health remains good. Never kill the outside container."
