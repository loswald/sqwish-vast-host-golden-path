#!/usr/bin/env bash

# Stops future rentals and, only after a separate vacancy review, asks Vast to
# reconcile expired/deleted contract storage. It never deletes the machine,
# live client paths, Docker data, partitions, or the host manager.

set -Eeuo pipefail
IFS=$'\n\t'

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

load_env_file

apply=false
cleanup=false
contracts_ended=false
machine_id="${VAST_MACHINE_ID:-}"

usage() {
  cat <<'EOF'
Usage: unlist-and-cleanup.sh [options]

Options:
  --machine-id ID       Owned machine ID (or VAST_MACHINE_ID)
  --cleanup             Also run Vast's expired/deleted contract cleanup
  --contracts-ended     Operator verified no active/paused client contract or
                        rented volume remains; required with --cleanup --apply
  --apply               Perform requested Vast mutations
  -h, --help            Show help

Default mode is dry run. Unlisting blocks new contracts but does not change any
existing contract or its end date.
EOF
}

while (( $# > 0 )); do
  case "$1" in
    --machine-id) machine_id="${2:-}"; shift 2 ;;
    --cleanup) cleanup=true; shift ;;
    --contracts-ended) contracts_ended=true; shift ;;
    --apply) apply=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

require_uint "machine ID" "$machine_id"
require_cmd vastai
require_cmd jq

note "Reading machine and current offers before any mutation..."
machine_json="$(vastai show machine "$machine_id" --raw)" \
  || die "Could not read machine ${machine_id}"
jq -e --arg mid "$machine_id" '
  type == "array"
  and ([.[] | select(((.id? // .machine_id? // "") | tostring) == $mid)] | length == 1)
' >/dev/null <<<"$machine_json" \
  || die "Owned-machine response did not uniquely match machine ${machine_id}"

unlist_cmd=(vastai unlist machine "$machine_id")
cleanup_cmd=(vastai cleanup machine "$machine_id" --raw)

if [[ "$apply" != true ]]; then
  run_or_preview false "${unlist_cmd[@]}"
  if [[ "$cleanup" == true ]]; then
    run_or_preview false "${cleanup_cmd[@]}"
  fi
  note "No changes made. Review every contract end date and rented volume in Host Machines/Contracts before cleanup or host shutdown."
  exit 0
fi

if [[ "$cleanup" == true && "$contracts_ended" != true ]]; then
  die "Cleanup apply requires --contracts-ended after confirming the machine is fully vacant"
fi

confirm_machine_id "$machine_id"

note "Unlisting machine ${machine_id}; existing contracts remain unchanged..."
"${unlist_cmd[@]}" 2> >(redact_cli_error >&2)

note "Verifying that no rentable machine offers remain..."
on_demand_json="$(vastai search offers "machine_id=${machine_id} verified=any rentable=any rented=any" --no-default --type on-demand --raw)" \
  || die "Could not verify on-demand offers after unlisting"
bid_json="$(vastai search offers "machine_id=${machine_id} verified=any rentable=any rented=any" --no-default --type bid --raw)" \
  || die "Could not verify interruptible offers after unlisting"
for offer_json in "$on_demand_json" "$bid_json"; do
  jq -e --arg mid "$machine_id" '
    type == "array"
    and ([.[] | select(((.machine_id? // "") | tostring) == $mid)] | length == 0)
  ' >/dev/null <<<"$offer_json" \
    || die "Machine ${machine_id} still has a rentable offer; unlisting was not verified"
done

if [[ "$cleanup" == true ]]; then
  printf 'Type VACANT %s to confirm no client contract or rented volume remains: ' "$machine_id" >&2
  IFS= read -r confirmation
  [[ "$confirmation" == "VACANT ${machine_id}" ]] || die "Vacancy confirmation did not match"
  note "Reconciling expired/deleted contract storage through Vast..."
  if ! cleanup_output="$("${cleanup_cmd[@]}" 2> >(redact_cli_error >&2))"; then
    die "Vast cleanup command failed"
  fi
  jq -e 'type == "object" and .success == true' >/dev/null <<<"$cleanup_output" \
    || die "Vast did not confirm a successful cleanup"
fi

note "Done. Do not stop the daemon, uninstall, format storage, or power down until the Host Machines/Contracts view independently confirms every locked contract has ended."
