# Fail-closed controlled interruptible acquisition

`tools/controlled_acquisition.py` opens one bounded public acquisition window
for either of two reviewed shapes:

- one exact two-GPU interruptible on an exact two-GPU machine; or
- four uniquely labelled one-GPU interruptibles covering an exact four-GPU
  machine.

It uses one pre-authenticated host CLI wrapper and a different
pre-authenticated controlled-client wrapper. It never accepts an API key
argument, never retries `create instance` for a label, and has no destroy path.
Vast's official [Hosting Overview](https://docs.vast.ai/host/hosting-overview)
documents that `min_gpu=1` lets clients choose 1, 2, or 4 GPUs on a four-GPU
machine and that each accepted slice becomes a separate contract. The official
[create-instance reference](https://docs.vast.ai/api-reference/instances/create-instance)
defines the searched offer ID as the ask accepted by the create call.

Use this only after sampling current comparable machines and choosing reviewed
P99 values. The host listing inputs are host-earned dollars per GPU-hour. The
expected renter prices and controlled bid are totals for the exact searched
offer: the complete two-GPU machine in the legacy shape and one GPU in the
four-slice shape.

The read-only invocation proves:

- the wrappers authenticate as two different positive account IDs;
- the exact machine exposes the requested two or four GPUs and reports no
  running rentals;
- neither public bid nor on-demand offers exist for the machine;
- the host account has no instance on the target machine; and
- the controlled client account has no instances at all.

It writes a private plan below `VAST_STATE_DIR` and makes no mutation. Compute a
reviewed fixed end before each invocation. The fixed-end horizon and actual
public exposure are separate controls: `--max-fixed-end-seconds` bounds how far
away the marketplace backstop may be, while `--max-public-seconds` bounds this
process's live acquisition window. A watchdog attempts an exact unlist one CLI
timeout before the public cap, even if the main polling path is stuck.
The configured fixed-end horizon may never exceed 48 hours; the default remains
the short 15-minute limit and must be raised explicitly for the 24-hour pilot.

### Two-GPU single-contract mode

```bash
export VAST_STATE_DIR=/srv/sqwish-private/vast-state
END_EPOCH="$(( $(date +%s) + 600 ))"

python3 tools/controlled_acquisition.py \
  --machine-id "$MACHINE_ID" \
  --host-cli /usr/local/bin/vast-host-cli \
  --client-cli /usr/local/bin/vast-controlled-client-cli \
  --fixed-end-epoch "$END_EPOCH" \
  --p99-host-on-demand-price "$HOST_ON_DEMAND_P99_PER_GPU" \
  --p99-host-bid-floor "$HOST_BID_P99_PER_GPU" \
  --expected-renter-on-demand-price "$RENTER_ON_DEMAND_MACHINE_TOTAL" \
  --expected-renter-bid-floor "$RENTER_BID_MACHINE_TOTAL" \
  --client-bid-price "$CONTROLLED_BID_MACHINE_TOTAL" \
  --disk-price "$DISK_PRICE" \
  --upload-price "$UPLOAD_PRICE" \
  --download-price "$DOWNLOAD_PRICE" \
  --image "$REVIEWED_DIGEST_PINNED_IMAGE" \
  --disk-gb 10 \
  --label "$UNIQUE_CONTROLLED_LABEL" \
  --offer-timeout 180 \
  --max-public-seconds 300 \
  --max-fixed-end-seconds 7200
```

### Four-GPU, four one-GPU-slice mode

Use an approximately 30-hour end for the 24-hour pilot so preparation and the
10-minute controller end buffer fit inside every exact contract. Recompute it
immediately before both dry-run and apply; never reuse a stale epoch.

```bash
export VAST_STATE_DIR=/srv/sqwish-private/vast-state
END_EPOCH="$(( $(date +%s) + 30 * 60 * 60 ))"

python3 tools/controlled_acquisition.py \
  --machine-id "$MACHINE_ID" \
  --host-cli /usr/local/bin/vast-host-cli \
  --client-cli /usr/local/bin/vast-controlled-client-cli \
  --gpu-count 4 \
  --fixed-end-epoch "$END_EPOCH" \
  --p99-host-on-demand-price "$HOST_ON_DEMAND_P99_PER_GPU" \
  --p99-host-bid-floor "$HOST_BID_P99_PER_GPU" \
  --expected-renter-on-demand-price "$RENTER_ON_DEMAND_ONE_GPU_TOTAL" \
  --expected-renter-bid-floor "$RENTER_BID_ONE_GPU_TOTAL" \
  --client-bid-price "$CONTROLLED_BID_ONE_GPU_TOTAL" \
  --disk-price "$DISK_PRICE" \
  --upload-price "$UPLOAD_PRICE" \
  --download-price "$DOWNLOAD_PRICE" \
  --image "$REVIEWED_DIGEST_PINNED_IMAGE" \
  --disk-gb 10 \
  --label controlled-four-slice-acquisition \
  --client-label controlled-client-01 \
  --client-label controlled-client-02 \
  --client-label controlled-client-03 \
  --client-label controlled-client-04 \
  --allowed-owner-standby-id "$VAST_OWN_INSTANCE_ID" \
  --allowed-owner-standby-label "$VAST_OWN_LABEL" \
  --offer-timeout 30 \
  --offer-stability-seconds 30 \
  --max-public-seconds 600 \
  --max-fixed-end-seconds 108000
```

Before apply, inspect the exact machine's **Host Machines/Contracts** view. The
host CLI's instance list is not a complete outside-client inventory. Recompute
`END_EPOCH` if its reviewed safety backstop has changed, repeat the same
arguments, add `--contracts-reviewed --apply`, and type the exact prompt
`LIST <MACHINE_ID> ONCE` in the terminal.

Apply performs this sequence:

1. Repeat the read-only preflight.
2. Publish `min_chunk=2` for the two-GPU shape or `min_chunk=1` for the
   four-slice shape, always with `discount_rate=0`, `vol_size=0`, and the exact
   fixed end.
3. Prove both exact offer types once, including machine, host, GPU count,
   vacancy, fixed end, and renter-facing prices. It also proves the accepted
   host prices from both the listing response and machine record.
4. Query the exact GPU size (`num_gpus=2` or `num_gpus=1`) and require the bid
   offer to remain continuously stable for the configured interval immediately
   before each create. An empty or mismatched bid sample resets that label's
   clock. The on-demand view is not required during the final stability dwell
   because the two search indexes were observed to flicker independently.
5. Issue one create for the two-GPU shape. In four-slice mode, issue four
   sequential creates with the four exact unique labels. Before every later
   create, re-query the one-GPU offer and prove the complete accumulated client
   inventory, exact identities, running states, and machine rental count. Each
   label has a one-call lifetime budget. Every call uses the reviewed
   digest-pinned image, 10-32 GB disk, `--cancel-unavail`, SSH, and direct
   networking.
6. After the exact complete set is running, enter the `finally` path and unlist.
   Three consecutive client-visible absence samples must pass for both bid and
   on-demand offers with no GPU-size filter, so a residual two- or four-GPU row
   also fails the proof. Independently, a watchdog reserves one 45-second CLI
   timeout and attempts unlisting before the configured public cap.
7. Re-prove after unlisting that the returned IDs, machine, host account,
   labels, interruptible type, GPU sizes, image, disk, fixed end, and
   `running/running/running` states are exact. The full client inventory must
   contain only the one reviewed contract or all four reviewed contracts. The
   GPU sum must cover the exact machine and the machine rental count must match.

All command responses, including the create response, stay in a mode-0600 run
directory outside the repository. A create response can contain an instance
credential, so do not copy the raw evidence into Git or chat.

If listing, unlisting, creation, identity, or state is uncertain, the helper
leaves an unresolved marker at the root of `VAST_STATE_DIR`. It refuses another
run while a marker exists. Inspect the recorded run, the controlled client's
full instance list, the exact host contract view, and both exact offer searches
before manually reconciling a marker. Never rerun create to resolve an uncertain
response. In four-slice mode, an uncertain third call prevents the fourth call;
the marker records the first two known contracts and the reconciliation captures
the complete observed inventory. Never destroy an unexpected contract.

## Live pitfalls recorded

- There is no published minimum fixed-end horizon or offer-propagation SLA. A
  two-hour-plus ask became searchable but its create returned structured HTTP
  400 `no_such_ask`; both account inventories proved zero contract. Twelve-hour
  asks later launched. Do not promote that observed boundary into a Vast rule.
- Structured `no_such_ask` is a definite no-contract result only when the
  response is parsed as that exact server error and both inventories agree.
  Transport timeouts or malformed responses remain uncertain and must not be
  retried automatically.
- Bid and on-demand views can disappear independently during propagation. The
  final guard for each label must be the successful continuous bid-stability
  sample followed immediately by that label's one create call.
- Once an interruptible is active, the exact bid offer may report `min_bid` as
  the active accepted bid rather than the original listing floor. Preserve both
  values in private evidence and use the active value for the subsequent cycle
  preflight.
- `vol_size=0` disables a separate storage offer. It does not limit client disk
  requests or the aggregate Docker pool. The controlled create uses 10 GB, and
  the host must impose its own physical XFS boundary.
- A host restart may change the public address and disconnect the platform.
  Vast tells unverified hosts to maintain steady uptime and avoid unnecessary
  reboots; its hosting guide says connection loss can lower reliability. Do not
  reboot between acquisition and a rating-sensitive test.
