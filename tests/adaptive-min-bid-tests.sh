#!/usr/bin/env bash

# Offline adaptive-pricing tests. Pass --interactive to exercise an applied
# price change in a real terminal and enter the exact confirmation shown.

set -Eeuo pipefail
IFS=$'\n\t'

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
interactive=false
[[ "${1:-}" != --interactive ]] || interactive=true

if ! command -v jq >/dev/null 2>&1; then
  printf 'SKIP adaptive min-bid tests: jq is not installed\n'
  exit 0
fi

tmp="$(mktemp -d)"
trap 'rm -rf -- "$tmp"' EXIT
subject_root="$tmp/subject"
mkdir -p "$subject_root/scripts/lib"
cp "$ROOT/scripts/adaptive-min-bid.sh" "$subject_root/scripts/adaptive-min-bid.sh"
cp "$ROOT/scripts/lib/common.sh" "$subject_root/scripts/lib/common.sh"
mkdir -p "$subject_root/tools"
cp "$ROOT/tools/adaptive_pricing.py" "$subject_root/tools/adaptive_pricing.py"
mkdir -p "$tmp/bin"
cp "$ROOT/tests/fake-adaptive-vastai.sh" "$tmp/bin/vastai"
cp "$ROOT/tests/fake-adaptive-vastai.sh" "$tmp/bin/fake-adaptive-vastai.sh"
chmod +x "$tmp/bin/vastai" "$subject_root/scripts/adaptive-min-bid.sh"
export PATH="$tmp/bin:$PATH"
export VAST_CLI_BIN="$tmp/bin/fake-adaptive-vastai.sh"
export FAKE_ADAPTIVE_LOG="$tmp/vast.log"
export FAKE_ADAPTIVE_RUNTIME_DIR="$tmp/runtime"

reset_case() {
  local name="$1" scenario="${2:-happy}" initial_price="${3:-0.4500}"
  export VAST_STATE_DIR="$tmp/state-$name"
  export FAKE_ADAPTIVE_SCENARIO="$scenario"
  rm -rf -- "$VAST_STATE_DIR" "$FAKE_ADAPTIVE_RUNTIME_DIR"
  mkdir -p -- "$FAKE_ADAPTIVE_RUNTIME_DIR"
  : >"$FAKE_ADAPTIVE_LOG"
  printf '%s\n' "$initial_price" >"$FAKE_ADAPTIVE_RUNTIME_DIR/min-bid-price"
}

assert_contains() {
  local file="$1" expected="$2"
  grep -Fq -- "$expected" "$file" || {
    printf 'FAIL expected %s in %s\n' "$expected" "$file" >&2
    cat "$file" >&2
    exit 1
  }
}

assert_file_empty() {
  local file="$1"
  [[ ! -s "$file" ]] || {
    printf 'FAIL expected empty file %s\n' "$file" >&2
    cat "$file" >&2
    exit 1
  }
}

assert_no_mutation() {
  if grep -Eq '^(set min-bid|start|stop|create|destroy|list|unlist|cleanup)( |$)' "$FAKE_ADAPTIVE_LOG"; then
    printf 'FAIL unexpected mutation in adaptive fake log\n' >&2
    cat "$FAKE_ADAPTIVE_LOG" >&2
    exit 1
  fi
}

assert_json_snapshot() {
  local snapshot
  snapshot="$(find "$VAST_STATE_DIR" -type f -name '*.json' -print -quit 2>/dev/null || true)"
  [[ -n "$snapshot" ]] || {
    printf 'FAIL expected a private JSON decision snapshot under %s\n' "$VAST_STATE_DIR" >&2
    exit 1
  }
  jq -e . "$snapshot" >/dev/null || {
    printf 'FAIL invalid JSON snapshot %s\n' "$snapshot" >&2
    exit 1
  }
}

run_helper() {
  local floor="$1" ceiling="$2"
  shift 2
  "$subject_root/scripts/adaptive-min-bid.sh" \
    --machine-id 9001 \
    --expected-gpu-name 'RTX PRO 6000 WS' \
    --expected-gpu-count 4 \
    --floor "$floor" \
    --ceiling "$ceiling" \
    --min-comparables 8 \
    --undercut-fraction 0.02 \
    --reliability-discount-rate 0.25 \
    --max-reliability-discount 0.15 \
    --verify-attempts 1 \
    --verify-interval 0 \
    "$@"
}

expect_preview() {
  local name="$1" scenario="$2" expected="$3" floor="${4:-0.3000}" ceiling="${5:-1.0000}"
  reset_case "$name" "$scenario"
  if ! run_helper "$floor" "$ceiling" >"$tmp/$name.out" 2>"$tmp/$name.err"; then
    printf 'FAIL adaptive preview %s exited unsuccessfully\n' "$name" >&2
    cat "$tmp/$name.out" "$tmp/$name.err" >&2
    exit 1
  fi
  assert_contains "$tmp/$name.out" "DRY RUN: vastai set min-bid 9001 --price $expected"
  assert_no_mutation
  assert_json_snapshot
  printf 'PASS adaptive preview %s recommends %s without mutation\n' "$name" "$expected"
}

expect_failure() {
  local name="$1" scenario="$2"
  reset_case "$name" "$scenario"
  if run_helper 0.3000 1.0000 >"$tmp/$name.out" 2>"$tmp/$name.err"; then
    printf 'FAIL adaptive pricing accepted unsafe scenario %s\n' "$scenario" >&2
    exit 1
  fi
  assert_no_mutation
  printf 'PASS adaptive pricing rejects %s without mutation\n' "$scenario"
}

# Factor 0.75; host-price P10 0.3705; reliability discount 7.5%; two-percent
# undercut. 0.3705 * 0.98 * 0.925 = 0.33585825, rounded half-up to 0.3359.
expect_preview formula happy 0.3359
assert_contains "$FAKE_ADAPTIVE_LOG" 'gpu_ram>=97.32096 gpu_ram<=99.28704'
assert_contains "$FAKE_ADAPTIVE_LOG" 'gpu_name=RTX_PRO_6000_WS num_gpus=1'
assert_contains "$FAKE_ADAPTIVE_LOG" 'machine_id!=9001 external=false rentable=true rented=false'
assert_contains "$FAKE_ADAPTIVE_LOG" '--type bid --no-default --storage 0 --raw'
assert_contains "$FAKE_ADAPTIVE_LOG" '--limit 500 --order min_bid'
printf 'PASS adaptive search converts raw VRAM MiB to CLI decimal-GB filters\n'

# The bounds are operator hard limits, applied after the market and reliability
# calculation.
expect_preview floor-clamp happy 0.3500 0.3500 1.0000
expect_preview ceiling-clamp happy 0.3300 0.3000 0.3300

# Reliability adjustments are one-sided and capped.
expect_preview reliability-cap reliability-cap 0.3086
expect_preview reliability-no-discount reliability-no-discount 0.3631

# The market result is stable under order, per-machine duplicates, an obvious
# lower Tukey outlier, and ineligible low-price contamination.
expect_preview duplicate-offers duplicate-offers-per-machine 0.3359
expect_preview lower-outlier lower-outlier 0.3359
expect_preview filtered-contaminants ineligible-low-contaminants 0.3359

reset_case already-at-target happy 0.3359
run_helper 0.3000 1.0000 >"$tmp/already-at-target.out" 2>"$tmp/already-at-target.err"
assert_contains "$tmp/already-at-target.out" 'No mutation needed; the exact machine already reports the guarded target.'
assert_no_mutation
assert_json_snapshot
printf 'PASS exact target is an idempotent no-op\n'

for scenario in \
  invalid-machine-json machine-object-envelope wrong-machine-id duplicate-machine \
  missing-machine-id missing-machine-gpu-name missing-machine-gpu-count \
  missing-machine-reliability missing-machine-verification missing-machine-price \
  wrong-machine-model wrong-machine-gpu-count invalid-machine-reliability deverified-machine \
  invalid-own-json own-object-envelope no-own-offers own-wrong-machine own-wrong-model \
  own-wrong-gpu-count own-wrong-vram own-deverified own-missing-price own-zero-price \
  factor-too-low factor-too-high invalid-market-json market-object-envelope \
  seven-comparables duplicate-comparable-machines lower-outlier-leaves-seven \
  malformed-relevant-comparable; do
  expect_failure "reject-$scenario" "$scenario"
done

# min-comparables is enforced after filtering, per-machine aggregation, and
# lower-outlier removal.
reset_case min-count-nine happy
if run_helper 0.3000 1.0000 --min-comparables 9 >"$tmp/min-count-nine.out" 2>"$tmp/min-count-nine.err"; then
  printf 'FAIL adaptive pricing ignored --min-comparables 9\n' >&2
  exit 1
fi
assert_no_mutation
printf 'PASS min-comparables applies to the final comparable sample\n'

reset_case market-limit happy
if run_helper 0.3000 1.0000 --search-limit 8 >"$tmp/market-limit.out" 2>"$tmp/market-limit.err"; then
  printf 'FAIL adaptive pricing accepted a possibly truncated market sample\n' >&2
  exit 1
fi
assert_contains "$tmp/market-limit.err" 'the comparable sample may be truncated'
assert_no_mutation
printf 'PASS search-limit saturation fails closed before pricing\n'

python3 - "$ROOT/tools/adaptive_pricing.py" <<'PY'
import argparse
import importlib.util
import sys
from decimal import Decimal

path = sys.argv[1]
spec = importlib.util.spec_from_file_location("adaptive_pricing_under_test", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

args = argparse.Namespace(
    machine_id=9001,
    expected_gpu_name="RTX PRO 6000 WS",
    expected_gpu_count=4,
    verify_attempts=1,
    verify_interval=0,
)
before = module.MachineIdentity(
    9001,
    "RTX PRO 6000 WS",
    "rtx pro 6000 ws",
    4,
    Decimal("0.60"),
    "unverified",
    Decimal("0.4500"),
)

def record(*, reliability="0.60", verification="unverified"):
    return {
        "id": 9001,
        "gpu_name": "RTX PRO 6000 WS",
        "num_gpus": 4,
        "reliability2": reliability,
        "verification": verification,
        "min_bid_price": "0.3359",
    }

module.show_machine = lambda machine_id: record()
assert module.verify_applied(args, before, Decimal("0.3359")).current_floor == Decimal("0.3359")

for changed in (
    record(reliability="0.99"),
    record(verification="verified"),
):
    module.show_machine = lambda machine_id, changed=changed: changed
    try:
        module.verify_applied(args, before, Decimal("0.3359"))
    except module.PricingError as exc:
        assert "changed during apply" in str(exc)
    else:
        raise AssertionError("post-apply guard accepted rating or verification drift")
PY
printf 'PASS post-apply verification rejects rating and verification drift\n'

# Invalid operator policy is rejected before the first API read.
for argument_case in floor-over-ceiling negative-floor invalid-ceiling excessive-price-precision invalid-min-count \
  invalid-undercut invalid-discount-rate invalid-max-discount; do
  reset_case "argument-$argument_case" happy
  case "$argument_case" in
    floor-over-ceiling)
      command=(run_helper 0.5000 0.4000)
      ;;
    negative-floor)
      command=(run_helper -0.1000 1.0000)
      ;;
    invalid-ceiling)
      command=(run_helper 0.3000 NaN)
      ;;
    excessive-price-precision)
      command=(run_helper 0.30001 1.0000)
      ;;
    invalid-min-count)
      command=(run_helper 0.3000 1.0000 --min-comparables 0)
      ;;
    invalid-undercut)
      command=(run_helper 0.3000 1.0000 --undercut-fraction 1.1)
      ;;
    invalid-discount-rate)
      command=(run_helper 0.3000 1.0000 --reliability-discount-rate -0.1)
      ;;
    invalid-max-discount)
      command=(run_helper 0.3000 1.0000 --max-reliability-discount 1.1)
      ;;
  esac
  if "${command[@]}" >"$tmp/argument-$argument_case.out" 2>"$tmp/argument-$argument_case.err"; then
    printf 'FAIL adaptive pricing accepted invalid arguments: %s\n' "$argument_case" >&2
    exit 1
  fi
  assert_no_mutation
  assert_file_empty "$FAKE_ADAPTIVE_LOG"
  printf 'PASS invalid policy %s fails before API reads\n' "$argument_case"
done

# Evidence may never be written into the repository copy.
reset_case state-inside-repository happy
export VAST_STATE_DIR="$subject_root/private-state"
if run_helper 0.3000 1.0000 >"$tmp/state-inside.out" 2>"$tmp/state-inside.err"; then
  printf 'FAIL adaptive pricing accepted state inside the repository\n' >&2
  exit 1
fi
assert_file_empty "$FAKE_ADAPTIVE_LOG"
printf 'PASS repository-local state is rejected before API reads\n'

# --apply never converts redirected input into authorization.
reset_case apply-without-tty happy
if run_helper 0.3000 1.0000 --apply </dev/null >"$tmp/apply-without-tty.out" 2>"$tmp/apply-without-tty.err"; then
  printf 'FAIL --apply succeeded without an interactive terminal\n' >&2
  exit 1
fi
assert_no_mutation
printf 'PASS noninteractive apply fails closed without mutation\n'

if [[ "$interactive" == true ]]; then
  reset_case applied-price happy
  printf 'Interactive adaptive apply: enter SET MIN-BID 9001 TO 0.3359.\n'
  run_helper 0.3000 1.0000 --apply
  [[ "$(cat "$FAKE_ADAPTIVE_RUNTIME_DIR/min-bid-price")" == 0.3359 ]]
  grep -Fqx 'set min-bid 9001 --price 0.3359' "$FAKE_ADAPTIVE_LOG"
  assert_json_snapshot
  printf 'PASS applied pricing changes the exact machine and verifies 0.3359\n'

  reset_case applied-no-postcondition set-no-effect
  printf 'Interactive negative case: enter SET MIN-BID 9001 TO 0.3359; the fake will not apply it.\n'
  if run_helper 0.3000 1.0000 --apply; then
    printf 'FAIL apply trusted command success without the exact price postcondition\n' >&2
    exit 1
  fi
  [[ "$(cat "$FAKE_ADAPTIVE_RUNTIME_DIR/min-bid-price")" == 0.4500 ]]
  grep -Fqx 'set min-bid 9001 --price 0.3359' "$FAKE_ADAPTIVE_LOG"
  printf 'PASS applied pricing rejects a success response without postcondition\n'
fi

printf 'Adaptive min-bid fake CLI tests passed.\n'
