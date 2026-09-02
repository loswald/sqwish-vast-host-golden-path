#!/usr/bin/env bash

set -Eeuo pipefail
IFS=$'\n\t'

readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

required=(
  README.md
  AGENTS.md
  docs/RUNBOOK.md
  docs/TRIAL-NOTES.md
  scripts/lib/common.sh
  scripts/preflight-host.sh
  scripts/reclaim-gpu.sh
  scripts/release-gpu.sh
  scripts/monitor-machine.sh
  scripts/unlist-and-cleanup.sh
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

mapfile -t bash_files < <(find "$ROOT" -type f -name '*.sh' -print | sort)
for path in "${bash_files[@]}"; do
  if bash -n "$path"; then
    printf 'PASS bash -n %s\n' "${path#${ROOT}/}"
  else
    failed=1
  fi
done

for script in reclaim-gpu.sh release-gpu.sh unlist-and-cleanup.sh; do
  path="${ROOT}/scripts/${script}"
  grep -q -- '--apply' "$path" || { printf 'FAIL %s lacks --apply gate\n' "$script" >&2; failed=1; }
  grep -q -- 'DRY RUN\|run_or_preview' "$path" || { printf 'FAIL %s lacks dry-run path\n' "$script" >&2; failed=1; }
  grep -q -- 'read -r' "$path" || { printf 'FAIL %s lacks interactive confirmation\n' "$script" >&2; failed=1; }
done

if grep -RInE --exclude='.gitignore' --exclude='validate.sh' \
  '(VAST_API_KEY|machineApiKey|Authorization:[[:space:]]*Bearer)[[:space:]]*[:=]?[[:space:]]*[A-Za-z0-9_-]{20,}' \
  "$ROOT"; then
  printf 'FAIL possible embedded credential found\n' >&2
  failed=1
else
  printf 'PASS no obvious embedded Vast credential\n'
fi

if grep -RInE --exclude='validate.sh' '(GCP|Google Cloud|compute\.googleapis\.com)' "$ROOT"; then
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
