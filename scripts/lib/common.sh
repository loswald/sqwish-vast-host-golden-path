#!/usr/bin/env bash

# Shared guardrails for the Vast owned-host helper scripts.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

readonly SCRIPT_LIB_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_DIR="$(cd -- "${SCRIPT_LIB_DIR}/../.." && pwd)"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

warn() {
  printf 'WARN: %s\n' "$*" >&2
}

note() {
  printf '%s\n' "$*"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

require_uint() {
  local name="$1" value="$2"
  [[ "$value" =~ ^[1-9][0-9]*$ ]] || die "$name must be a positive integer"
}

load_env_file() {
  local path="${1:-${PROJECT_DIR}/.env}"
  if [[ -f "$path" ]]; then
    # The file is trusted local configuration. Keep it out of version control.
    # shellcheck disable=SC1090
    set -a
    source "$path"
    set +a
  fi
}

state_dir() {
  local configured resolved project
  configured="${VAST_STATE_DIR:-${XDG_STATE_HOME:-${HOME}/.local/state}/vast-host-golden-path}"
  require_cmd realpath
  resolved="$(realpath -m -- "$configured")" || die "Could not resolve VAST_STATE_DIR"
  project="$(realpath -m -- "$PROJECT_DIR")" || die "Could not resolve project directory"
  case "$resolved" in
    "$project"|"$project"/*)
      die "VAST_STATE_DIR must be outside the repository: ${resolved}"
      ;;
  esac
  printf '%s\n' "$resolved"
}

ensure_state_dir() {
  local dir
  dir="$(state_dir)"
  mkdir -p -- "$dir"
  chmod 700 -- "$dir" 2>/dev/null || true
  printf '%s\n' "$dir"
}

run_or_preview() {
  local apply="$1"
  shift
  if [[ "$apply" == true ]]; then
    "$@"
  else
    printf 'DRY RUN:'
    printf ' %q' "$@"
    printf '\n'
  fi
}

confirm_machine_id() {
  local expected="$1"
  local prompt_value=""
  if [[ ! -t 0 ]]; then
    die "Refusing a mutation without an interactive terminal"
  fi
  printf 'Type machine ID %s to continue: ' "$expected" >&2
  IFS= read -r prompt_value
  [[ "$prompt_value" == "$expected" ]] || die "Machine ID confirmation did not match"
}

json_scalar() {
  # Read JSON from stdin. The filter must emit exactly one non-empty scalar.
  local filter="$1"
  require_cmd jq
  jq -er "[
    $filter
    | select(type == \"string\" or type == \"number\" or type == \"boolean\")
    | select(tostring != \"\")
  ] | if length == 1 then .[0] else empty end"
}

redact_cli_error() {
  # Vast API keys should never be passed on the command line. This strips common
  # token-shaped values if an upstream command nevertheless echoes one.
  sed -E 's/[A-Za-z0-9_-]{40,}/<redacted-token>/g'
}
