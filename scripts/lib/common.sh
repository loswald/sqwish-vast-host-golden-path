#!/usr/bin/env bash

# Shared guardrails for the Vast owned-host helper scripts.

set -Eeuo pipefail
IFS=$'\n\t'
umask 077

readonly SCRIPT_LIB_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_DIR="$(cd -- "${SCRIPT_LIB_DIR}/../.." && pwd)"
readonly QUALIFICATION_INTERLOCK_DIRNAME="qualification-owner-mutation.lock"
readonly QUALIFICATION_INTERLOCK_TIMEOUT_ENV="VAST_QUALIFICATION_INTERLOCK_TIMEOUT_SECONDS"
readonly DEFAULT_QUALIFICATION_INTERLOCK_TIMEOUT_SECONDS=60
readonly MAX_QUALIFICATION_INTERLOCK_TIMEOUT_SECONDS=300

qualification_interlock_owned=false
qualification_interlock_dir=""
qualification_interlock_token=""

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

instance_status_is_safely_stopped() {
  local actual_status="${1-}" intended_status="${2-}" cur_state="${3-}"

  case "$actual_status" in
    created|exited|stopped) ;;
    *) return 1 ;;
  esac
  [[ "$intended_status" == stopped && "$cur_state" == stopped ]]
}

instance_status_is_exactly_running() {
  local actual_status="${1-}" intended_status="${2-}" cur_state="${3-}"
  [[ "$actual_status" == running \
     && "$intended_status" == running \
     && "$cur_state" == running ]]
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
  dir="$(state_dir)" || return 1
  mkdir -p -- "$dir"
  chmod 700 -- "$dir" 2>/dev/null || true
  printf '%s\n' "$dir"
}

qualification_interlock_acquire() {
  local root="$1" action="$2"
  local timeout="${VAST_QUALIFICATION_INTERLOCK_TIMEOUT_SECONDS:-$DEFAULT_QUALIFICATION_INTERLOCK_TIMEOUT_SECONDS}"
  local deadline token_tmp metadata_tmp pid

  [[ "$qualification_interlock_owned" != true ]] || {
    printf 'ERROR: this process already owns the qualification/owner interlock\n' >&2
    return 1
  }
  if [[ ! "$timeout" =~ ^(0|[1-9][0-9]*)$ ]] \
     || (( ${#timeout} > 3 )) \
     || (( timeout > MAX_QUALIFICATION_INTERLOCK_TIMEOUT_SECONDS )); then
    printf 'ERROR: %s must be an integer from 0 to %s\n' \
      "$QUALIFICATION_INTERLOCK_TIMEOUT_ENV" "$MAX_QUALIFICATION_INTERLOCK_TIMEOUT_SECONDS" >&2
    return 1
  fi
  [[ -d "$root" ]] || {
    printf 'ERROR: qualification/owner interlock state root is unavailable: %s\n' "$root" >&2
    return 1
  }

  qualification_interlock_dir="${root}/${QUALIFICATION_INTERLOCK_DIRNAME}"
  deadline=$((SECONDS + timeout))
  while ! mkdir -- "$qualification_interlock_dir" 2>/dev/null; do
    if (( SECONDS >= deadline )); then
      printf 'ERROR: timed out waiting for qualification/owner interlock at %s while trying to %s; the existing lock was retained and must never be cleared merely because it is old\n' \
        "$qualification_interlock_dir" "$action" >&2
      qualification_interlock_dir=""
      return 1
    fi
    if [[ ! -e "$qualification_interlock_dir" ]]; then
      printf 'ERROR: could not acquire qualification/owner interlock at %s while trying to %s\n' \
        "$qualification_interlock_dir" "$action" >&2
      qualification_interlock_dir=""
      return 1
    fi
    sleep 0.1
  done
  chmod 700 -- "$qualification_interlock_dir" 2>/dev/null || true

  pid="${BASHPID:-$$}"
  qualification_interlock_token="bash-${pid}-${RANDOM}-${SECONDS}"
  token_tmp="${qualification_interlock_dir}/owner-token.tmp-${pid}"
  metadata_tmp="${qualification_interlock_dir}/owner.json.tmp-${pid}"
  if ! printf '%s\n' "$qualification_interlock_token" >"$token_tmp" \
     || ! mv -- "$token_tmp" "${qualification_interlock_dir}/owner-token" \
     || ! jq -n \
       --arg action "$action" \
       --argjson pid "$pid" \
       --argjson acquired_at_process_seconds "$SECONDS" \
       '{schema:1,pid:$pid,action:$action,
         acquired_at_process_seconds:$acquired_at_process_seconds,
         implementation:"bash",automatic_stale_removal:false}' >"$metadata_tmp" \
     || ! mv -- "$metadata_tmp" "${qualification_interlock_dir}/owner.json"; then
    rm -f -- "$token_tmp" "$metadata_tmp" \
      "${qualification_interlock_dir}/owner-token" \
      "${qualification_interlock_dir}/owner.json"
    rmdir -- "$qualification_interlock_dir" 2>/dev/null || true
    qualification_interlock_dir=""
    qualification_interlock_token=""
    printf 'ERROR: could not record qualification/owner interlock ownership\n' >&2
    return 1
  fi
  chmod 600 -- "${qualification_interlock_dir}/owner-token" \
    "${qualification_interlock_dir}/owner.json" 2>/dev/null || true
  qualification_interlock_owned=true
}

qualification_interlock_release() {
  local observed
  [[ "$qualification_interlock_owned" == true ]] || return 0
  if [[ ! -f "${qualification_interlock_dir}/owner-token" ]] \
     || ! IFS= read -r observed <"${qualification_interlock_dir}/owner-token" \
     || [[ "$observed" != "$qualification_interlock_token" ]]; then
    printf 'ERROR: qualification/owner interlock ownership changed at %s; the lock was retained for manual investigation\n' \
      "$qualification_interlock_dir" >&2
    qualification_interlock_owned=false
    return 1
  fi
  if ! rm -f -- "${qualification_interlock_dir}/owner.json" \
       "${qualification_interlock_dir}/owner-token" \
     || ! rmdir -- "$qualification_interlock_dir"; then
    printf 'ERROR: qualification/owner interlock could not be released cleanly at %s; the remaining lock must be investigated and is never cleared by age\n' \
      "$qualification_interlock_dir" >&2
    qualification_interlock_owned=false
    return 1
  fi
  qualification_interlock_owned=false
  qualification_interlock_dir=""
  qualification_interlock_token=""
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
