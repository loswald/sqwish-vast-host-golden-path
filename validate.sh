#!/usr/bin/env bash

set -Eeuo pipefail
IFS=$'\n\t'

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

required=(
  README.md
  AGENTS.md
  docs/RUNBOOK.md
  docs/TRIAL-NOTES.md
  docs/A100-2X-LIVE-TRIAL.md
  docs/CLEAN-HOSTJOB-CYCLE.md
  docs/CONTROLLED-ACQUISITION.md
  docs/CONTROLLED-24H-VERIFICATION-AND-HANDOFF-PILOT.md
  docs/SCAN-4X-RTX-PRO-6000-PILOT.md
  docs/ECONOMICS.md
  docs/ADAPTIVE-PRICING.md
  docs/INFERENCE-ALTERNATIVES.md
  scripts/lib/common.sh
  scripts/preflight-host.sh
  scripts/reclaim-gpu.sh
  scripts/release-gpu.sh
  scripts/monitor-machine.sh
  scripts/unlist-and-cleanup.sh
  scripts/adaptive-min-bid.sh
  tests/fake-vastai.sh
  tests/fake-cli-tests.sh
  tests/fake-adaptive-vastai.sh
  tests/adaptive-min-bid-tests.sh
  tools/economics_model.py
  tools/usage_patterns.py
  tools/adaptive_pricing.py
  tools/controlled_hostjob_cycle.py
  tools/controlled_acquisition.py
  tools/controlled_owner_standby_cycle.py
  tools/controlled_24h_pilot.py
  tools/controlled_24h_cleanup.py
  tools/prepare_owner_standby.py
  tools/verification_guard.py
  tests/test_controlled_hostjob_cycle.py
  tests/test_controlled_acquisition.py
  tests/test_controlled_owner_standby_cycle.py
  tests/test_controlled_24h_pilot.py
  tests/test_controlled_24h_cleanup.py
  tests/test_prepare_owner_standby.py
  tests/test_verification_guard.py
  site/app/gpu-economics-lab.tsx
  site/package.json
  .env.example
  .gitignore
)

failed=0

for path in "${required[@]}"; do
  if [[ ! -f "${ROOT}/${path}" ]]; then
    printf 'FAIL missing %s\n' "$path" >&2
    failed=1
  fi
done

if command -v python3 >/dev/null 2>&1; then
  if python3 -m py_compile "${ROOT}/tools/economics_model.py" "${ROOT}/tools/usage_patterns.py" "${ROOT}/tools/adaptive_pricing.py" "${ROOT}/tools/controlled_hostjob_cycle.py" "${ROOT}/tools/controlled_acquisition.py" "${ROOT}/tools/controlled_owner_standby_cycle.py" "${ROOT}/tools/controlled_24h_pilot.py" "${ROOT}/tools/controlled_24h_cleanup.py" "${ROOT}/tools/prepare_owner_standby.py" "${ROOT}/tools/verification_guard.py" "${ROOT}/tests/test_controlled_hostjob_cycle.py" "${ROOT}/tests/test_controlled_acquisition.py" "${ROOT}/tests/test_controlled_owner_standby_cycle.py" "${ROOT}/tests/test_controlled_24h_pilot.py" "${ROOT}/tests/test_controlled_24h_cleanup.py" "${ROOT}/tests/test_prepare_owner_standby.py" "${ROOT}/tests/test_verification_guard.py" \
     && python3 "${ROOT}/tools/economics_model.py" >/dev/null \
     && python3 "${ROOT}/tools/usage_patterns.py" >/dev/null \
     && (cd "${ROOT}" && python3 -m unittest discover -s tests -p 'test_*.py'); then
    printf 'PASS Python models, verification guard, controlled acquisition, owner standby, and clean Host Job cycle tests\n'
  else
    failed=1
  fi
else
  printf 'SKIP Python model checks: python3 not installed\n'
fi

mapfile -t bash_files < <(
  find "$ROOT" \
    \( -path "$ROOT/site/node_modules" -o -path "$ROOT/site/.next" \
       -o -path "$ROOT/site/.vinext" -o -path "$ROOT/site/.wrangler" \) -prune \
    -o -type f -name '*.sh' -print | sort
)
for path in "${bash_files[@]}"; do
  if bash -n "$path"; then
    printf 'PASS bash -n %s\n' "${path#${ROOT}/}"
  else
    failed=1
  fi
done

if bash "${ROOT}/tests/fake-cli-tests.sh"; then
  printf 'PASS fake Vast CLI lifecycle tests\n'
else
  failed=1
fi

if bash "${ROOT}/tests/adaptive-min-bid-tests.sh"; then
  printf 'PASS adaptive minimum-bid tests\n'
else
  failed=1
fi

for script in reclaim-gpu.sh release-gpu.sh unlist-and-cleanup.sh; do
  path="${ROOT}/scripts/${script}"
  grep -q -- '--apply' "$path" || { printf 'FAIL %s lacks --apply gate\n' "$script" >&2; failed=1; }
  grep -q -- 'DRY RUN\|run_or_preview' "$path" || { printf 'FAIL %s lacks dry-run path\n' "$script" >&2; failed=1; }
  grep -q -- 'read -r' "$path" || { printf 'FAIL %s lacks interactive confirmation\n' "$script" >&2; failed=1; }
done

if grep -RInE --exclude='.gitignore' --exclude='validate.sh' \
  --exclude-dir='.git' --exclude-dir='node_modules' --exclude-dir='.next' \
  --exclude-dir='.vinext' --exclude-dir='.wrangler' \
  '(VAST_API_KEY|machineApiKey|Authorization:[[:space:]]*Bearer)[[:space:]]*[:=]?[[:space:]]*[A-Za-z0-9_-]{20,}' \
  "$ROOT"; then
  printf 'FAIL possible embedded credential found\n' >&2
  failed=1
else
  printf 'PASS no obvious embedded Vast credential\n'
fi

if grep -RInE --exclude='validate.sh' \
  --exclude-dir='.git' --exclude-dir='node_modules' --exclude-dir='.next' \
  --exclude-dir='.vinext' --exclude-dir='.wrangler' \
  '(GCP|Google Cloud|compute\.googleapis\.com)' "$ROOT"; then
  printf 'FAIL provider-specific detail found\n' >&2
  failed=1
else
  printf 'PASS provider-neutral owned-hardware content\n'
fi

if command -v shellcheck >/dev/null 2>&1; then
  if shellcheck -x "${bash_files[@]}"; then
    printf 'PASS shellcheck\n'
  else
    failed=1
  fi
else
  printf 'SKIP shellcheck not installed\n'
fi

if (( failed != 0 )); then
  printf 'Validation failed.\n' >&2
  exit 1
fi

printf 'Validation passed.\n'
