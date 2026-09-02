#!/usr/bin/env bash

# Offline lifecycle tests. Pass --interactive to exercise applied start/stop in
# a real terminal; enter the two exact confirmations printed by the scripts.

set -Eeuo pipefail
IFS=$'\n\t'

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../scripts/lib/common.sh
source "$ROOT/scripts/lib/common.sh"
interactive=false
[[ "${1:-}" != --interactive ]] || interactive=true

if ! command -v jq >/dev/null 2>&1; then
  printf 'SKIP fake CLI tests: jq is not installed\n'
  exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
subject_root="$tmp/subject"
mkdir -p "$subject_root"
cp -R "$ROOT/scripts" "$subject_root/scripts"
mkdir -p "$tmp/bin"
cp "$ROOT/tests/fake-vastai.sh" "$tmp/bin/vastai"
chmod +x "$tmp/bin/vastai"
export PATH="$tmp/bin:$PATH"
export FAKE_VAST_LOG="$tmp/vast.log"
export FAKE_VAST_RUNTIME="$tmp/runtime"
export VAST_MACHINE_ID=9001
export VAST_OWN_OFFER_ID=8001
export VAST_OWN_INSTANCE_ID=7001
export VAST_OWN_LABEL_PREFIX=owned-reclaim
export VAST_GPU_COUNT=4
export VAST_OWN_DISK_GB=20

reset_case() {
  local name="$1" status="${2:-stopped}"
  export VAST_STATE_DIR="$tmp/state-$name"
  rm -rf -- "$VAST_STATE_DIR"
  : >"$FAKE_VAST_LOG"
  printf '%s\n' "$status" >"$FAKE_VAST_RUNTIME"
}

assert_contains() {
  local file="$1" expected="$2"
  grep -Fq -- "$expected" "$file" || {
    printf 'FAIL expected %s in %s\n' "$expected" "$file" >&2
    cat "$file" >&2
    exit 1
  }
}

assert_no_mutation() {
  if grep -Eq '^(start|stop|create|destroy) instance' "$FAKE_VAST_LOG"; then
    printf 'FAIL unexpected mutation in fake log\n' >&2
    cat "$FAKE_VAST_LOG" >&2
    exit 1
  fi
}

for actual_status in created exited stopped; do
  instance_status_is_safely_stopped "$actual_status" stopped stopped || {
    printf 'FAIL safe stopped predicate rejected %s/stopped/stopped\n' "$actual_status" >&2
    exit 1
  }
done
for status_tuple in \
  loading:stopped:stopped \
  running:stopped:stopped \
  missing:stopped:stopped \
  created:running:stopped \
  created:missing:stopped \
  exited:stopped:running \
  exited:stopped:missing; do
  IFS=: read -r actual_status intended_status cur_state <<<"$status_tuple"
  [[ "$actual_status" != missing ]] || actual_status=""
  [[ "$intended_status" != missing ]] || intended_status=""
  [[ "$cur_state" != missing ]] || cur_state=""
  if instance_status_is_safely_stopped "$actual_status" "$intended_status" "$cur_state"; then
    printf 'FAIL safe stopped predicate accepted invalid tuple %s\n' "$status_tuple" >&2
    exit 1
  fi
done
instance_status_is_exactly_running running running running || {
  printf 'FAIL exact running predicate rejected running/running/running\n' >&2
  exit 1
}
if instance_status_is_exactly_running running stopped running; then
  printf 'FAIL exact running predicate accepted running/stopped/running\n' >&2
  exit 1
fi
printf 'PASS shared stopped and running predicates fail closed\n'

for scenario in safe live-created-stopped exited-stopped; do
  reset_case "preview-start-$scenario"
  FAKE_VAST_SCENARIO="$scenario" "$subject_root/scripts/reclaim-gpu.sh" \
    >"$tmp/preview-start-$scenario.out" 2>"$tmp/preview-start-$scenario.err"
  case "$scenario" in
    safe) expected_actual=stopped ;;
    live-created-stopped) expected_actual=created ;;
    exited-stopped) expected_actual=exited ;;
  esac
  assert_contains "$tmp/preview-start-$scenario.out" \
    "instance=7001 machine=9001 label=owned-reclaim-safe gpu_count=4 offer=8001 status=${expected_actual}/stopped/stopped"
  assert_contains "$tmp/preview-start-$scenario.out" 'DRY RUN: vastai start instance 7001 --raw'
  assert_no_mutation
  printf 'PASS precreated reclaim accepts safely stopped tuple %s/stopped/stopped\n' "$expected_actual"
done

for scenario in \
  wrong-id wrong-machine wrong-label wrong-gpu wrong-offer bid-instance \
  wrong-status contradictory-status loading-stopped running-stopped \
  missing-actual-status missing-intended-status missing-cur-state; do
  reset_case "mismatch-$scenario"
  if FAKE_VAST_SCENARIO="$scenario" "$subject_root/scripts/reclaim-gpu.sh" >"$tmp/$scenario.out" 2>"$tmp/$scenario.err"; then
    printf 'FAIL reclaim accepted mismatch scenario %s\n' "$scenario" >&2
    exit 1
  fi
  assert_no_mutation
  if grep -Eq '^create instance' "$FAKE_VAST_LOG"; then
    printf 'FAIL mismatch scenario %s fell back to create\n' "$scenario" >&2
    exit 1
  fi
  printf 'PASS reclaim rejects %s without mutation or create fallback\n' "$scenario"
done

reset_case preview-stop running
mkdir -p "$VAST_STATE_DIR"
jq -n '{mode:"precreated",status:"running-confirmed",machine_id:"9001",offer_id:"8001",instance_id:"7001",label:"owned-reclaim-safe",label_prefix:"owned-reclaim",gpu_count:"4"}' >"$VAST_STATE_DIR/active-reclaim.json"
FAKE_VAST_SCENARIO=safe "$subject_root/scripts/release-gpu.sh" --wait-seconds 0 >"$tmp/preview-stop.out" 2>"$tmp/preview-stop.err"
assert_contains "$tmp/preview-stop.out" 'mode=precreated instance=7001 machine=9001 label=owned-reclaim-safe status=running/running/running'
assert_contains "$tmp/preview-stop.out" 'DRY RUN: vastai stop instance 7001 --raw'
assert_no_mutation
printf 'PASS precreated release previews stop and never destroy\n'

for scenario in wrong-id wrong-machine wrong-label wrong-gpu wrong-offer bid-instance; do
  reset_case "release-mismatch-$scenario" running
  mkdir -p "$VAST_STATE_DIR"
  jq -n '{mode:"precreated",status:"running-confirmed",machine_id:"9001",offer_id:"8001",instance_id:"7001",label:"owned-reclaim-safe",label_prefix:"owned-reclaim",gpu_count:"4"}' >"$VAST_STATE_DIR/active-reclaim.json"
  if FAKE_VAST_SCENARIO="$scenario" "$subject_root/scripts/release-gpu.sh" --wait-seconds 0 >"$tmp/release-$scenario.out" 2>"$tmp/release-$scenario.err"; then
    printf 'FAIL release accepted mismatch scenario %s\n' "$scenario" >&2
    exit 1
  fi
  assert_no_mutation
  [[ -f "$VAST_STATE_DIR/active-reclaim.json" ]]
  printf 'PASS release rejects %s and retains active state\n' "$scenario"
done

reset_case preview-destroy running
mkdir -p "$VAST_STATE_DIR"
jq -n '{mode:"fresh-created",status:"created",machine_id:"9001",offer_id:"8001",instance_id:"7001",label:"owned-reclaim-safe"}' >"$VAST_STATE_DIR/active-reclaim.json"
if FAKE_VAST_SCENARIO=safe "$subject_root/scripts/release-gpu.sh" --wait-seconds 0 >"$tmp/configured-destroy.out" 2>"$tmp/configured-destroy.err"; then
  printf 'FAIL release allowed configured reusable ID to enter destroy mode\n' >&2
  exit 1
fi
assert_no_mutation
printf 'PASS release refuses destroy of configured reusable instance ID\n'
VAST_OWN_INSTANCE_ID= FAKE_VAST_SCENARIO=safe "$subject_root/scripts/release-gpu.sh" --wait-seconds 0 >"$tmp/preview-destroy.out" 2>"$tmp/preview-destroy.err"
assert_contains "$tmp/preview-destroy.out" 'DRY RUN: vastai destroy instance 7001 --yes --raw'
assert_no_mutation
printf 'PASS fresh-created release retains guarded destroy behavior\n'

reset_case recovery-mode running
if FAKE_VAST_SCENARIO=safe "$subject_root/scripts/release-gpu.sh" --instance-id 7001 --machine-id 9001 --expected-label owned-reclaim-safe >"$tmp/recovery.out" 2>"$tmp/recovery.err"; then
  printf 'FAIL recovery override accepted no explicit mode\n' >&2
  exit 1
fi
assert_no_mutation
printf 'PASS recovery override fails closed without explicit mode\n'

if [[ "$interactive" == true ]]; then
  reset_case applied-lifecycle stopped
  printf 'Interactive fake apply: enter START 7001 ON 9001, then STOP 7001.\n'
  FAKE_VAST_SCENARIO=live-created-stopped "$subject_root/scripts/reclaim-gpu.sh" --contracts-reviewed --apply
  jq -e '.mode == "precreated" and .status == "running-confirmed" and .instance_id == "7001"' \
    "$VAST_STATE_DIR/active-reclaim.json" >/dev/null
  [[ "$(cat "$FAKE_VAST_RUNTIME")" == running ]]
  grep -Fqx 'start instance 7001 --raw' "$FAKE_VAST_LOG"
  ! grep -Eq '^(create|destroy) instance' "$FAKE_VAST_LOG"
  printf 'PASS applied precreated reclaim starts exact instance and persists mode\n'

  FAKE_VAST_SCENARIO=live-created-stopped "$subject_root/scripts/release-gpu.sh" --wait-seconds 0 --apply
  [[ "$(cat "$FAKE_VAST_RUNTIME")" == stopped ]]
  [[ ! -e "$VAST_STATE_DIR/active-reclaim.json" ]]
  [[ ! -e "$VAST_STATE_DIR/reclaim.lock" ]]
  grep -Fqx 'stop instance 7001 --raw' "$FAKE_VAST_LOG"
  ! grep -Eq '^(create|destroy) instance' "$FAKE_VAST_LOG"
  printf 'PASS applied precreated release stops exact instance, retains disk mode, and archives state\n'
fi

printf 'Fake CLI tests passed.\n'
