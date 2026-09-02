#!/usr/bin/env bash

# Offline Vast CLI double for lifecycle guardrail tests. It never calls Vast.

set -Eeuo pipefail
IFS=$'\n\t'

: "${FAKE_VAST_LOG:?}"
: "${FAKE_VAST_RUNTIME:?}"
scenario="${FAKE_VAST_SCENARIO:-safe}"
{
  printf '%s' "${1:-}"
  for argument in "${@:2}"; do
    printf ' %s' "$argument"
  done
  printf '\n'
} >>"$FAKE_VAST_LOG"

runtime_status() {
  if [[ -f "$FAKE_VAST_RUNTIME" ]]; then
    cat "$FAKE_VAST_RUNTIME"
  else
    printf 'stopped\n'
  fi
}

emit_instance() {
  local id=7001 machine=9001 label=owned-reclaim-safe gpu=4 offer=8001 is_bid=false
  local status intended current instance_json
  status="$(runtime_status)"
  intended="$status"
  current="$status"
  case "$scenario" in
    wrong-id) id=7002 ;;
    wrong-machine) machine=9002 ;;
    wrong-label) label=tenant-workload ;;
    wrong-gpu) gpu=3 ;;
    wrong-offer) offer=8002 ;;
    bid-instance) is_bid=true ;;
    wrong-status) status=running; intended=running; current=running ;;
    contradictory-status) status=stopped; intended=running; current=stopped ;;
    live-created-stopped)
      if [[ "$status" == stopped ]]; then
        status=created
      fi
      ;;
    exited-stopped)
      if [[ "$status" == stopped ]]; then
        status=exited
      fi
      ;;
    loading-stopped) status=loading; intended=stopped; current=stopped ;;
    running-stopped) status=running; intended=stopped; current=stopped ;;
    missing-actual-status|missing-intended-status|missing-cur-state) ;;
    safe) ;;
    *) printf 'unknown fake scenario: %s\n' "$scenario" >&2; exit 91 ;;
  esac
  instance_json="$(jq -nc \
    --argjson id "$id" --argjson machine_id "$machine" --arg label "$label" \
    --argjson num_gpus "$gpu" --argjson ask_contract_id "$offer" \
    --argjson is_bid "$is_bid" --arg actual_status "$status" \
    --arg intended_status "$intended" --arg cur_state "$current" \
    '{id:$id,machine_id:$machine_id,label:$label,num_gpus:$num_gpus,
      ask_contract_id:$ask_contract_id,is_bid:$is_bid,actual_status:$actual_status,
      intended_status:$intended_status,cur_state:$cur_state}')"
  case "$scenario" in
    missing-actual-status) instance_json="$(jq -c 'del(.actual_status)' <<<"$instance_json")" ;;
    missing-intended-status) instance_json="$(jq -c 'del(.intended_status)' <<<"$instance_json")" ;;
    missing-cur-state) instance_json="$(jq -c 'del(.cur_state)' <<<"$instance_json")" ;;
  esac
  printf '%s\n' "$instance_json"
}

case "${1:-} ${2:-}" in
  "search offers")
    printf '[{"id":8001,"machine_id":9001,"num_gpus":4}]\n'
    ;;
  "show instance")
    emit_instance
    ;;
  "show instances")
    emit_instance | jq -s .
    ;;
  "show machine")
    printf '[{"id":9001}]\n'
    ;;
  "start instance")
    [[ "${3:-}" == 7001 ]] || exit 92
    printf 'running\n' >"$FAKE_VAST_RUNTIME"
    printf 'starting instance 7001.\n'
    ;;
  "stop instance")
    [[ "${3:-}" == 7001 ]] || exit 93
    printf 'stopped\n' >"$FAKE_VAST_RUNTIME"
    printf 'stopping instance 7001.\n'
    ;;
  "create instance"|"destroy instance")
    printf 'unexpected mutating fake command: %s\n' "$*" >&2
    exit 94
    ;;
  *)
    printf 'unhandled fake command: %s\n' "$*" >&2
    exit 95
    ;;
esac
