#!/usr/bin/env bash

# Offline Vast CLI double for adaptive minimum-bid tests. It never calls Vast.

set -Eeuo pipefail
IFS=$'\n\t'

: "${FAKE_ADAPTIVE_LOG:?}"
: "${FAKE_ADAPTIVE_RUNTIME_DIR:?}"

scenario="${FAKE_ADAPTIVE_SCENARIO:-happy}"
price_file="${FAKE_ADAPTIVE_RUNTIME_DIR}/min-bid-price"
set_marker="${FAKE_ADAPTIVE_RUNTIME_DIR}/set-called"
mkdir -p -- "$FAKE_ADAPTIVE_RUNTIME_DIR"
[[ -f "$price_file" ]] || printf '0.4500\n' >"$price_file"

{
  printf '%s' "${1:-}"
  for argument in "${@:2}"; do
    printf ' %s' "$argument"
  done
  printf '\n'
} >>"$FAKE_ADAPTIVE_LOG"

machine_reliability() {
  case "$scenario" in
    reliability-cap) printf '0.20\n' ;;
    reliability-no-discount) printf '0.92\n' ;;
    invalid-machine-reliability) printf '1.20\n' ;;
    *) printf '0.60\n' ;;
  esac
}

emit_machine() {
  if [[ "$scenario" == invalid-machine-json ]]; then
    printf '{not-json\n'
    return
  fi

  local id=9001 gpu_name='RTX PRO 6000 WS' num_gpus=4
  local reliability verification=unverified price machine_json
  reliability="$(machine_reliability)"
  price="$(cat -- "$price_file")"

  case "$scenario" in
    wrong-machine-id) id=9002 ;;
    wrong-machine-model) gpu_name='RTX PRO 6000 S' ;;
    wrong-machine-gpu-count) num_gpus=3 ;;
    deverified-machine) verification=deverified ;;
    post-wrong-machine-id)
      [[ -f "$set_marker" ]] && id=9002
      ;;
    post-wrong-price)
      [[ -f "$set_marker" ]] && price=0.9999
      ;;
    post-reliability-change)
      [[ -f "$set_marker" ]] && reliability=0.99
      ;;
    post-verification-change)
      [[ -f "$set_marker" ]] && verification=verified
      ;;
  esac

  machine_json="$(jq -nc \
    --argjson id "$id" \
    --arg gpu_name "$gpu_name" \
    --argjson num_gpus "$num_gpus" \
    --argjson reliability2 "$reliability" \
    --arg verification "$verification" \
    --argjson min_bid_price "$price" \
    '[{id:$id,gpu_name:$gpu_name,num_gpus:$num_gpus,reliability2:$reliability2,
       verification:$verification,min_bid_price:$min_bid_price}]')"

  case "$scenario" in
    duplicate-machine)
      machine_json="$(jq -c '.[0] as $machine | [$machine,$machine]' <<<"$machine_json")"
      ;;
    missing-machine-id) machine_json="$(jq -c '.[0] | del(.id) | [.]' <<<"$machine_json")" ;;
    missing-machine-gpu-name) machine_json="$(jq -c '.[0] | del(.gpu_name) | [.]' <<<"$machine_json")" ;;
    missing-machine-gpu-count) machine_json="$(jq -c '.[0] | del(.num_gpus) | [.]' <<<"$machine_json")" ;;
    missing-machine-reliability) machine_json="$(jq -c '.[0] | del(.reliability2) | [.]' <<<"$machine_json")" ;;
    missing-machine-verification) machine_json="$(jq -c '.[0] | del(.verification) | [.]' <<<"$machine_json")" ;;
    missing-machine-price) machine_json="$(jq -c '.[0] | del(.min_bid_price) | [.]' <<<"$machine_json")" ;;
    machine-object-envelope) machine_json="$(jq -c '.[0]' <<<"$machine_json")" ;;
  esac

  printf '%s\n' "$machine_json"
}

emit_own_offers() {
  case "$scenario" in
    invalid-own-json) printf '[not-json\n'; return ;;
    no-own-offers) printf '[]\n'; return ;;
  esac

  local reliability host_price factor renter_price own_json
  reliability="$(machine_reliability)"
  host_price="$(cat -- "$price_file")"
  factor=0.75
  case "$scenario" in
    factor-too-low) factor=0.49 ;;
    factor-too-high) factor=1.06 ;;
  esac
  renter_price="$(jq -nr --argjson host "$host_price" --argjson factor "$factor" '$host / $factor')"

  own_json="$(jq -nc \
    --arg gpu_name 'RTX PRO 6000 WS' \
    --argjson reliability "$reliability" \
    --argjson min_bid "$renter_price" '
      [range(0;4) as $i |
        {id:(8001+$i),machine_id:9001,num_gpus:1,gpu_name:$gpu_name,
         gpu_ram:98304,reliability:$reliability,verification:"unverified",
         min_bid:$min_bid}]')"

  case "$scenario" in
    own-wrong-machine) own_json="$(jq -c 'map(.machine_id=9002)' <<<"$own_json")" ;;
    own-wrong-model) own_json="$(jq -c 'map(.gpu_name="RTX PRO 6000 S")' <<<"$own_json")" ;;
    own-wrong-gpu-count) own_json="$(jq -c 'map(.num_gpus=2)' <<<"$own_json")" ;;
    own-wrong-vram) own_json="$(jq -c 'map(.gpu_ram=81920)' <<<"$own_json")" ;;
    own-deverified) own_json="$(jq -c 'map(.verification="deverified")' <<<"$own_json")" ;;
    own-missing-price) own_json="$(jq -c 'map(del(.min_bid))' <<<"$own_json")" ;;
    own-zero-price) own_json="$(jq -c 'map(.min_bid=0)' <<<"$own_json")" ;;
    own-object-envelope) own_json="$(jq -c '{offers:.}' <<<"$own_json")" ;;
  esac

  printf '%s\n' "$own_json"
}

base_market_json() {
  # Deliberately shuffled. With a 0.75 renter-to-host factor, the sorted host
  # prices are 0.3600..0.4650 and linear P10 is exactly 0.3705.
  jq -nc --arg gpu_name 'RTX PRO 6000 WS' '
    [
      {id:9104,machine_id:9104,min_bid:0.54},
      {id:9101,machine_id:9101,min_bid:0.48},
      {id:9108,machine_id:9108,min_bid:0.62},
      {id:9103,machine_id:9103,min_bid:0.52},
      {id:9106,machine_id:9106,min_bid:0.58},
      {id:9102,machine_id:9102,min_bid:0.50},
      {id:9107,machine_id:9107,min_bid:0.60},
      {id:9105,machine_id:9105,min_bid:0.56}
    ]
    | map(. + {num_gpus:1,gpu_name:$gpu_name,gpu_ram:98304,
               reliability:0.90,verification:"verified",
               rentable:true,rented:false})'
}

emit_market_offers() {
  if [[ "$scenario" == invalid-market-json ]]; then
    printf '[not-json\n'
    return
  fi

  local market_json
  market_json="$(base_market_json)"
  case "$scenario" in
    seven-comparables)
      market_json="$(jq -c '.[0:7]' <<<"$market_json")"
      ;;
    duplicate-comparable-machines)
      market_json="$(jq -c 'to_entries | map(.value.machine_id=(9200+(.key%4))) | map(.value)' <<<"$market_json")"
      ;;
    lower-outlier)
      market_json="$(jq -c '. + [{id:9199,machine_id:9199,num_gpus:1,gpu_name:"RTX PRO 6000 WS",gpu_ram:98304,reliability:0.90,verification:"verified",rentable:true,rented:false,min_bid:0.05}]' <<<"$market_json")"
      ;;
    lower-outlier-leaves-seven)
      market_json="$(jq -c '.[0:7] + [{id:9199,machine_id:9199,num_gpus:1,gpu_name:"RTX PRO 6000 WS",gpu_ram:98304,reliability:0.90,verification:"verified",rentable:true,rented:false,min_bid:0.05}]' <<<"$market_json")"
      ;;
    duplicate-offers-per-machine)
      market_json="$(jq -c '. as $base | $base + ($base | map(.id += 10000 | .min_bid += 0.02)) + ($base | map(.id += 20000 | .min_bid -= 0.02))' <<<"$market_json")"
      ;;
    ineligible-low-contaminants)
      market_json="$(jq -c '. + [
        {id:9201,machine_id:9001,num_gpus:1,gpu_name:"RTX PRO 6000 WS",gpu_ram:98304,reliability:0.90,verification:"verified",rentable:true,rented:false,min_bid:0.01},
        {id:9202,machine_id:9202,num_gpus:1,gpu_name:"RTX PRO 6000 S",gpu_ram:98304,reliability:0.90,verification:"verified",rentable:true,rented:false,min_bid:0.01},
        {id:9203,machine_id:9203,num_gpus:1,gpu_name:"RTX PRO 6000 WS",gpu_ram:81920,reliability:0.90,verification:"verified",rentable:true,rented:false,min_bid:0.01},
        {id:9204,machine_id:9204,num_gpus:1,gpu_name:"RTX PRO 6000 WS",gpu_ram:98304,reliability:0.10,verification:"verified",rentable:true,rented:false,min_bid:0.01},
        {id:9205,machine_id:9205,num_gpus:1,gpu_name:"RTX PRO 6000 WS",gpu_ram:98304,reliability:0.90,verification:"deverified",rentable:true,rented:false,min_bid:0.01}
      ]' <<<"$market_json")"
      ;;
    malformed-relevant-comparable)
      market_json="$(jq -c '.[0] |= del(.min_bid)' <<<"$market_json")"
      ;;
    market-object-envelope)
      market_json="$(jq -c '{offers:.}' <<<"$market_json")"
      ;;
  esac

  printf '%s\n' "$market_json"
}

case "${1:-} ${2:-}" in
  'show machine')
    [[ "${3:-}" == 9001 && "${4:-}" == --raw ]] || exit 92
    emit_machine
    ;;
  'search offers')
    if [[ "${3:-}" == *'machine_id=9001'* ]]; then
      emit_own_offers
    else
      emit_market_offers
    fi
    ;;
  'set min-bid')
    [[ "${3:-}" == 9001 && "${4:-}" == --price && -n "${5:-}" ]] || exit 93
    printf '%s\n' "${5}" >"$set_marker"
    case "$scenario" in
      set-no-effect) ;;
      post-wrong-price) printf '%s\n' "${5}" >"$price_file" ;;
      post-wrong-machine-id) printf '%s\n' "${5}" >"$price_file" ;;
      post-reliability-change) printf '%s\n' "${5}" >"$price_file" ;;
      post-verification-change) printf '%s\n' "${5}" >"$price_file" ;;
      set-error-after-change)
        printf '%s\n' "${5}" >"$price_file"
        printf 'simulated set failure after server-side change\n' >&2
        exit 94
        ;;
      set-fails)
        printf 'simulated set failure\n' >&2
        exit 95
        ;;
      *) printf '%s\n' "${5}" >"$price_file" ;;
    esac
    printf '{"success":true}\n'
    ;;
  *)
    printf 'unhandled fake command: %s\n' "$*" >&2
    exit 96
    ;;
esac
