#!/usr/bin/env bash

# Releases the recorded owner reclaim. A pre-created owner instance is stopped
# and retained with its disk; a fresh-created owner instance is destroyed.

set -Eeuo pipefail
IFS=$'\n\t'

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

load_env_file

apply=false
wait_seconds=180
override_mode=""
override_instance_id=""
override_machine_id=""
override_label=""

usage() {
  cat <<'EOF'
Usage: release-gpu.sh [options]

Options:
  --apply                    Apply the mode-specific release
  --wait-seconds N           Read-only post-release observation (default 180)
  --mode MODE                Recovery mode: precreated or fresh-created
  --instance-id ID           Recovery override if private state was lost
  --machine-id ID            Required with recovery override
  --expected-label LABEL     Required with recovery override
  -h, --help                 Show help

The state file normally selects the safe action. Precreated mode stops the
exact instance and retains its disk. Fresh-created mode destroys the exact
instance and its data. Recovery requires all four override options so a lost
precreated state cannot accidentally select destroy.
EOF
}

while (( $# > 0 )); do
  case "$1" in
    --apply) apply=true; shift ;;
    --wait-seconds) wait_seconds="${2:-}"; shift 2 ;;
    --mode) override_mode="${2:-}"; shift 2 ;;
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
lock_dir="${state_root}/reclaim.lock"
using_state_file=false
expected_gpu_count=""
expected_offer_id=""

if [[ -n "$override_mode" || -n "$override_instance_id" || -n "$override_machine_id" || -n "$override_label" ]]; then
  [[ "$override_mode" == precreated || "$override_mode" == fresh-created ]] \
    || die "--mode must be precreated or fresh-created for recovery"
  require_uint "override instance ID" "$override_instance_id"
  require_uint "override machine ID" "$override_machine_id"
  [[ -n "$override_label" ]] || die "--expected-label is required for recovery"
  mode="$override_mode"
  own_instance_id="$override_instance_id"
  machine_id="$override_machine_id"
  expected_label="$override_label"
  expected_gpu_count="${VAST_GPU_COUNT:-}"
  expected_offer_id="${VAST_OWN_OFFER_ID:-}"
else
  [[ -f "$state_file" ]] \
    || die "No active reclaim state at ${state_file}; recovery requires --mode, --instance-id, --machine-id, and --expected-label"
  jq -e . >/dev/null <"$state_file" || die "Active reclaim state is invalid JSON"
  mode="$(jq -r '.mode // "fresh-created"' "$state_file")"
  own_instance_id="$(jq -er '.instance_id | tostring' "$state_file")"
  machine_id="$(jq -er '.machine_id | tostring' "$state_file")"
  expected_label="$(jq -er '.label' "$state_file")"
  expected_gpu_count="$(jq -r '(.gpu_count // "") | tostring' "$state_file")"
  expected_offer_id="$(jq -r '(.offer_id // "") | tostring' "$state_file")"
  using_state_file=true
fi

[[ "$mode" == precreated || "$mode" == fresh-created ]] \
  || die "Unknown reclaim mode '${mode}'; refusing to choose a release action"
require_uint "owner instance ID" "$own_instance_id"
require_uint "owner machine ID" "$machine_id"
[[ -n "$expected_label" ]] || die "Expected owner label is empty"
configured_owner_instance_id="${VAST_OWN_INSTANCE_ID:-}"
if [[ -n "$configured_owner_instance_id" ]]; then
  require_uint "configured reusable owner instance ID" "$configured_owner_instance_id"
  if [[ "$mode" == precreated && "$configured_owner_instance_id" != "$own_instance_id" ]]; then
    die "Precreated state instance ${own_instance_id} conflicts with configured reusable instance ${configured_owner_instance_id}"
  fi
  if [[ "$mode" == fresh-created && "$configured_owner_instance_id" == "$own_instance_id" ]]; then
    die "Fresh-created state targets configured reusable instance ${own_instance_id}; refusing destroy"
  fi
fi
if [[ -n "$expected_gpu_count" ]]; then
  require_uint "expected GPU count" "$expected_gpu_count"
fi
if [[ -n "$expected_offer_id" ]]; then
  require_uint "expected offer ID" "$expected_offer_id"
fi

instance_record=""
actual_status=""
intended_status=""
cur_state=""

validate_owner_instance() {
  local json="$1"
  local actual_machine actual_label actual_gpu actual_offer actual_is_bid

  jq -e . >/dev/null <<<"$json" || die "Instance output was not valid JSON"
  instance_record="$(jq -c --arg iid "$own_instance_id" '
    if type == "object"
       and (((.id? // .contract_id? // .instance_id? // "") | tostring) == $iid)
    then . else empty end
  ' <<<"$json")"
  [[ -n "$instance_record" ]] || die "Could not identify exact instance ${own_instance_id} in API response"

  actual_machine="$(jq -er '(.machine_id // empty) | tostring' <<<"$instance_record")" \
    || die "Instance response did not include machine_id"
  actual_label="$(jq -er '.label // empty' <<<"$instance_record")" \
    || die "Instance response did not include a label"
  [[ "$actual_machine" == "$machine_id" ]] \
    || die "Instance machine ${actual_machine} does not match expected ${machine_id}"
  [[ "$actual_label" == "$expected_label" ]] \
    || die "Instance label '${actual_label}' does not match expected '${expected_label}'"

  if [[ "$mode" == precreated ]]; then
    actual_is_bid="$(jq -r 'if has("is_bid") and (.is_bid | type) == "boolean" then (.is_bid | tostring) else "missing" end' <<<"$instance_record")"
    [[ "$actual_is_bid" == false ]] \
      || die "Pre-created owner instance must explicitly report is_bid=false; got ${actual_is_bid}"

    actual_gpu="$(jq -r '(.num_gpus // .gpu_count // "") | tostring' <<<"$instance_record")"
    if [[ -n "$expected_gpu_count" ]]; then
      [[ "$actual_gpu" == "$expected_gpu_count" ]] \
        || die "Instance GPU count '${actual_gpu:-missing}' does not match expected ${expected_gpu_count}"
    fi

    actual_offer="$(jq -r '(.ask_contract_id // .offer_id // .ask_id // "") | tostring' <<<"$instance_record")"
    if [[ -n "$expected_offer_id" && -n "$actual_offer" && "$actual_offer" != "$expected_offer_id" ]]; then
      die "Instance offer ${actual_offer} does not match expected ${expected_offer_id}"
    fi
  fi

  actual_status="$(jq -r '(.actual_status // "") | tostring' <<<"$instance_record")"
  intended_status="$(jq -r '(.intended_status // "") | tostring' <<<"$instance_record")"
  cur_state="$(jq -r '(.cur_state // "") | tostring' <<<"$instance_record")"
}

note "Reading owner instance ${own_instance_id} before any mutation..."
instance_json="$(vastai show instance "$own_instance_id" --raw)" \
  || die "Cannot read owner instance ${own_instance_id}; inspect Vast Instances"
validate_owner_instance "$instance_json"

note "Verified owner instance:"
printf '  mode=%s instance=%s machine=%s label=%s status=%s/%s/%s\n' \
  "$mode" "$own_instance_id" "$machine_id" "$expected_label" \
  "${actual_status:-missing}" "${intended_status:-missing}" "${cur_state:-missing}"

if [[ "$mode" == precreated ]]; then
  release_cmd=(vastai stop instance "$own_instance_id" --raw)
  action_word="STOP"
else
  release_cmd=(vastai destroy instance "$own_instance_id" --yes --raw)
  action_word="RELEASE"
fi

if [[ "$apply" != true ]]; then
  run_or_preview false "${release_cmd[@]}"
  if [[ "$mode" == precreated ]]; then
    note "No changes made. Apply will stop this exact instance and keep its disk reserved."
  else
    note "No changes made. Persist owner outputs before apply; destroy deletes its data."
  fi
  exit 0
fi

[[ -t 0 ]] || die "Apply mode requires an interactive terminal"
if [[ "$mode" == precreated ]]; then
  printf 'Type STOP %s to retain this owner instance and disk: ' "$own_instance_id" >&2
else
  printf 'Destroy deletes owner data. Type RELEASE %s to continue: ' "$own_instance_id" >&2
fi
IFS= read -r confirmation
[[ "$confirmation" == "${action_word} ${own_instance_id}" ]] || die "Confirmation did not match"

ensure_state_dir >/dev/null
if ! mkdir -- "$lock_dir" 2>/dev/null; then
  die "Another reclaim/release may be running or a prior attempt needs review: ${lock_dir}"
fi
cleanup_local_lock() { rmdir -- "$lock_dir" 2>/dev/null || true; }
trap cleanup_local_lock EXIT

if [[ "$using_state_file" == true ]]; then
  [[ -f "$state_file" ]] || die "Active state disappeared while waiting for the lock"
  locked_mode="$(jq -r '.mode // "fresh-created"' "$state_file" 2>/dev/null || true)"
  locked_id="$(jq -r '(.instance_id // "") | tostring' "$state_file" 2>/dev/null || true)"
  locked_machine="$(jq -r '(.machine_id // "") | tostring' "$state_file" 2>/dev/null || true)"
  locked_label="$(jq -r '.label // ""' "$state_file" 2>/dev/null || true)"
  [[ "$locked_mode" == "$mode" && "$locked_id" == "$own_instance_id" \
     && "$locked_machine" == "$machine_id" && "$locked_label" == "$expected_label" ]] \
    || die "Active state changed while waiting for the lock"
fi

# Repeat the identity proof under the lock immediately before mutation.
locked_instance_json="$(vastai show instance "$own_instance_id" --raw)" \
  || die "Cannot re-read owner instance ${own_instance_id} under the lock"
validate_owner_instance "$locked_instance_json"

released_at="$(date -u +%Y%m%dT%H%M%SZ)"
snapshot_dir="${state_root}/snapshots/${released_at}-after-release"
mkdir -p -- "${state_root}/snapshots"
mkdir -- "$snapshot_dir"
chmod 700 -- "$snapshot_dir" 2>/dev/null || true
printf '%s\n' "$locked_instance_json" >"${snapshot_dir}/owner-instance-before-release.json"

confirmation_method=""
if [[ "$mode" == precreated ]]; then
  stop_confirmed=false
  if instance_status_is_safely_stopped "$actual_status" "$intended_status" "$cur_state"; then
    stop_confirmed=true
    confirmation_method="already-safely-stopped"
    note "Instance already satisfies the safe stopped-state proof; no duplicate mutation is needed."
  else
    note "Stopping exact pre-created owner instance ${own_instance_id}; command output is diagnostic only..."
    if stop_output="$("${release_cmd[@]}" 2> >(redact_cli_error >&2))"; then
      stop_status=0
    else
      stop_status=$?
      warn "Stop command exited ${stop_status}; verifying the exact stopped postcondition"
    fi
    [[ -z "$stop_output" ]] || printf '%s\n' "$stop_output" >"${snapshot_dir}/stop-output.txt"

    for attempt in 1 2 3 4 5 6 7; do
      poll_json=""
      if poll_json="$(vastai show instance "$own_instance_id" --raw 2> >(redact_cli_error >&2))" \
         && jq -e . >/dev/null 2>&1 <<<"$poll_json"; then
        printf '%s\n' "$poll_json" >"${snapshot_dir}/owner-instance-after-stop-${attempt}.json"
        validate_owner_instance "$poll_json"
        if instance_status_is_safely_stopped "$actual_status" "$intended_status" "$cur_state"; then
          stop_confirmed=true
          confirmation_method="safe-stopped-postcondition"
          break
        fi
      else
        warn "Could not obtain valid status on stop verification attempt ${attempt}"
      fi
      (( attempt < 7 )) && sleep 5
    done
  fi
  [[ "$stop_confirmed" == true ]] \
    || die "Could not prove exact instance ${own_instance_id} reached stopped. Active state was retained."

  jq -n --arg method "$confirmation_method" \
    '{confirmed:true, action:"stop", instance_retained:true, disk_retained:true, method:$method}' \
    >"${snapshot_dir}/release-verification.json"
else
  note "Destroying the verified fresh-created owner instance only..."
  if destroy_output="$("${release_cmd[@]}" 2> >(redact_cli_error >&2))"; then
    destroy_status=0
  else
    destroy_status=$?
  fi

  destroy_confirmed=false
  if [[ "$destroy_status" == 0 ]] \
     && jq -e 'type == "object" and .success == true' >/dev/null 2>&1 <<<"$destroy_output"; then
    destroy_confirmed=true
    confirmation_method="destroy-response-success"
  elif jq -e 'type == "object" and has("success")' >/dev/null 2>&1 <<<"$destroy_output"; then
    die "Vast returned an explicit non-success destroy response; active state was retained"
  else
    warn "Destroy returned no machine-readable success confirmation; verifying exact absence"
    for attempt in 1 2 3 4 5 6; do
      single_output=""
      list_output=""
      single_ok=false
      list_ok=false
      if single_output="$(vastai show instance "$own_instance_id" --raw 2> >(redact_cli_error >&2))" \
         && jq -e 'type == "object" and has("instances") and .instances == null' >/dev/null 2>&1 <<<"$single_output"; then
        single_ok=true
      fi
      if list_output="$(vastai show instances --raw 2> >(redact_cli_error >&2))" \
         && jq -e --arg iid "$own_instance_id" '
           (if type == "array" then .
            elif type == "object" and has("instances") and (.instances | type) == "array" then .instances
            else null end) as $instances
           | $instances != null
             and ([$instances[] | select(((.id? // .contract_id? // .instance_id? // "") | tostring) == $iid)] | length == 0)
         ' >/dev/null 2>&1 <<<"$list_output"; then
        list_ok=true
      fi
      printf '%s\n' "$single_output" >"${snapshot_dir}/show-instance-after-destroy-${attempt}.json"
      printf '%s\n' "$list_output" >"${snapshot_dir}/show-instances-after-destroy-${attempt}.json"
      if [[ "$single_ok" == true && "$list_ok" == true ]]; then
        destroy_confirmed=true
        confirmation_method="instance-absent-from-single-and-list"
        break
      fi
      (( attempt < 6 )) && sleep 5
    done
  fi
  [[ "$destroy_confirmed" == true ]] \
    || die "Could not prove that instance ${own_instance_id} was destroyed; active state was retained"

  [[ -z "$destroy_output" ]] || printf '%s\n' "$destroy_output" >"${snapshot_dir}/destroy-output.txt"
  jq -n --arg method "$confirmation_method" --argjson destroy_exit_status "$destroy_status" \
    '{confirmed:true,action:"destroy",instance_retained:false,disk_retained:false,method:$method,destroy_exit_status:$destroy_exit_status}' \
    >"${snapshot_dir}/release-verification.json"
fi

if [[ "$using_state_file" == true ]]; then
  mv -- "$state_file" "${snapshot_dir}/released-reclaim-state.json"
fi

if [[ -f "$pending_file" ]]; then
  pending_matches="$(jq -r --arg mid "$machine_id" --arg label "$expected_label" '
    type == "object" and ((.machine_id? // "") | tostring) == $mid and (.label? // "") == $label
  ' "$pending_file" 2>/dev/null || true)"
  if [[ "$pending_matches" == true ]]; then
    mv -- "$pending_file" "${snapshot_dir}/resolved-pending-reclaim.json"
  else
    warn "A different or invalid pending reclaim file remains at ${pending_file}"
  fi
fi

# The mutation and state transition are complete. Do not hold the lifecycle
# lock during the optional read-only observation window.
if rmdir -- "$lock_dir" 2>/dev/null; then
  trap - EXIT
else
  warn "Could not remove lifecycle lock ${lock_dir}; it will be retried on exit"
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

if [[ "$mode" == precreated ]]; then
  note "Owner instance stopped and retained with its disk. Private snapshots: ${snapshot_dir}"
else
  note "Fresh-created owner instance destroyed. Private snapshots: ${snapshot_dir}"
fi
note "Confirm the outside interruptible automatically returns to running and record resume delay. Never manually start or kill its container."
