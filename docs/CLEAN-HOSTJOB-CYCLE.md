# Clean two-A100 Host Job reclaim cycle

`tools/controlled_hostjob_cycle.py` repeats only the previously confounded
Host Job phase. It assumes the exact two-GPU interruptible has already been
acquired by the separate controlled client and the host is unlisted. It does
not create a renter, sample prices, or expose a vacant host.

## Result and production status

This controller is a diagnostic harness. It is **not** a production reclaim
script. Three clean live attempts raised the Host Job to `$1.10/GPU-hour` for
30 seconds, `$1.30/GPU-hour` for 90 seconds, and `$3.00/GPU-hour` for 120
seconds. In every attempt the exact controlled interruptible remained running
and the owner jobs did not take its GPUs. The final corrected attempt held the
immediate reliability value flat at `0.5727243`, but because no handoff occurred
it provides no evidence that a successful handoff would be rating-safe.

The official [`set defjob`](https://docs.vast.ai/cli/reference/set-defjob)
reference calls this a background job and documents its price input. It does
not define price as a preemption control, promise a reclaim latency, or promise
no reliability effect. Vast's [instance-type priority
rules](https://docs.vast.ai/guides/instances/choosing/instance-types) say an
interruptible may pause when outbid by another interruptible or displaced by
on-demand. They do not grant a Host Job an owner-only eviction priority.

Sqwish's near-instant owner-reclaim and rating-safe-handoff production gate is
therefore **BLOCKED**. Use explicit-release, contract-drain, or reserved-capacity
operations instead.

## What succeeded after the Host Job tests

The separate `tools/controlled_owner_standby_cycle.py` experiment used an exact
pre-created host-account **on-demand** standby rather than a Host Job. Its final
17-comparable market snapshot put renter whole-pair P10 at `$0.7466667/hour`,
mapped to a `$0.28/GPU-hour` host interruptible floor. The outside on-demand
deterrent was `$5.84/GPU-hour` host-side and `$15.5733/hour` renter-facing for
the pair; reserved discount was zero.

With one exact full-machine interruptible running from the separate controlled
account, the controller unlisted and proved both offer types absent, then
started only the exact safely stopped owner standby. The renter moved to the
safe-stopped tuple and the owner reached `running/running/running` in **82.281
seconds** from the research decision. Exact owner stop returned the same renter
automatically; the guarded fallback Start was not used. A separate post-pilot
probe proved real PyTorch CUDA work across both owner GPUs. Cleanup proved no
contracts and no bid/on-demand offers.

This does not rehabilitate Host Jobs as a preemption mechanism. It also does
not establish production readiness: reliability was `0.5727243` before the
successful takeover, immediately afterward, and after cleanup, below immutable
original `0.5999925`. The delayed check was skipped at the disposable host's
preconfigured automatic-deletion deadline. Vast says a new-machine score starts
low and grows with stable uptime, making the earlier restart a plausible but
unproved explanation for the drop. Vast also says personal workloads can fail
verification while directing host work through Jobs; obtain clarification
before using own-machine on-demand instances for daily research.

Preparation had three specific pitfalls: a `10/10` listing returned HTTP 422,
the known accepted `5.84/3` preparation shape worked, and
`--cancel-unavail` produced the false-ownership error on the exact own offer.
The acquisition guard must explicitly allow one exact safely stopped standby
by ID and label without admitting any other target-machine record.

Do not run this harness while trying to raise a new machine's reliability or
reach verification. Vast says reliability grows through stable uptime and
warns unverified hosts against unnecessary reboots/configuration changes. Its
verification guide also requires a dedicated machine and says personal
workloads fail verification.

Run this only on a dedicated physical host whose provider permits marketplace
hosting. Raw evidence contains private resource identifiers and stays under
`VAST_STATE_DIR`, outside this repository.

## Authentication boundary

Provide two different executables. `--host-cli` uses the host account and
`--client-cli` uses the controlled client account. Each executable must obtain
its key from its own private configuration; the controller refuses API-key
arguments and refuses to run when the executable paths resolve to the same
file. It also queries both authenticated user records and requires two distinct
positive account IDs before the first mutation. Use one wrapper per account.
Each wrapper must clear an inherited `VAST_API_KEY` and select separate home,
configuration, cache, and state directories; changing `HOME` alone is not an
account-isolation boundary:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail
account_root=/home/operator/vast-controlled-client
unset VAST_API_KEY
export HOME="$account_root"
export XDG_CONFIG_HOME="$account_root/.config"
export XDG_CACHE_HOME="$account_root/.cache"
export XDG_STATE_HOME="$account_root/.local/state"
exec /usr/local/bin/vastai "$@"
```

Create the host wrapper with a different `account_root`. Keep each account root
and wrapper mode `0700`, and each key file mode `0600`.

## Preconditions

- The host is absent from both bid and on-demand searches in two consecutive
  preflight samples.
- The controlled client is the exact ID, machine, dedicated label, bid type,
  two-GPU count, and `running/running/running` state supplied on the command.
- The machine record itself reports exactly two GPUs and the client occupies
  both. Existing owner bid records make preflight fail; the controller records
  the two new IDs created by this definition and follows only those IDs. Its
  default-job image, arguments, and price fields must also be empty. An inert
  existing definition is rejected before mutation so cleanup cannot erase it.
- Destroying the client cannot happen until a state-changing cycle actually
  began, the unlist command succeeded, and three consecutive samples proved
  both offer types absent. The initial preflight absence proof is deliberately
  cleared before the first mutation and cannot authorize destruction. If the
  post-mutation proof fails, the owner Host Jobs are retained, capacity state is
  treated as unresolved, and client destruction is skipped. A client ID
  configured as `VAST_OWN_INSTANCE_ID` is never eligible for destruction.
- Prices come from a fresh live comparison. Host Job prices are host-entered
  per GPU-hour. The controlled client's bid is renter-facing per machine-hour.
- Choose a fixed end at least long enough for the dwell and both timeouts. Bound
  it separately with `--max-fixed-end-seconds` (60-86,400 seconds). Bound actual
  public exposure with `--max-public-seconds` (60-600 seconds); a watchdog
  attempts unlisting one CLI timeout before that public cap. The controller
  aborts and cleans up if the exact end, full-machine chunk, on-demand price,
  and renter-facing floor are not visible on the exact machine and target
  offers.
- Machine reliability, verification, and all three machine-error fields must
  be present and clean before mutation. For `error_description` and
  `vm_error_msg`, either JSON null or an empty string is clear; both normalize
  to an empty string for checkpoint comparison. Missing fields, other types,
  nonempty strings, or a nonzero `vm_error_level` fail the health gate. Machine
  report counters may be null, so the controller uses the authoritative
  `vastai reports <machine> --raw` response. The current official CLI
  implementation prints that response as
  `reports: [...]` even when `--raw` is supplied; the controller accepts that
  exact prefix or a bare API array, rejects other wrappers, and requires every
  report object to be complete. The array must be empty at baseline. See the
  [`reports` implementation](https://github.com/vast-ai/vast-cli/blob/master/vast.py#L3799-L3820).

## Dry run, then apply

Resolve the reviewed PyTorch tag to an immutable registry digest before the
host is listed. For example, after independently confirming that the tag's
CUDA version matches the host driver:

```bash
PYTORCH_TAG=pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime
PYTORCH_DIGEST="$(docker buildx imagetools inspect "$PYTORCH_TAG" | awk '$1 == "Digest:" {print $2; exit}')"
[[ "$PYTORCH_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
PINNED_PYTORCH_CUDA_IMAGE_DIGEST="${PYTORCH_TAG}@${PYTORCH_DIGEST}"
```

Record the resolved digest in the private evidence. Use the exact values
captured during controlled acquisition:

Define the invocation once, run the read-only preflight with a short-lived end,
then generate a new end immediately before apply:

```bash
export VAST_STATE_DIR=/home/operator/.local/state/vast-host-golden-path
PUBLIC_WINDOW_SECONDS=900
FIXED_END_HORIZON_SECONDS=45000

run_controlled_cycle() {
  local end_epoch="$1"
  shift
  python3 tools/controlled_hostjob_cycle.py \
  --machine-id "$MACHINE_ID" \
  --client-instance-id "$CONTROLLED_CLIENT_ID" \
  --client-label "$CONTROLLED_CLIENT_LABEL" \
  --host-cli /home/operator/bin/vast-host-cli \
  --client-cli /home/operator/bin/vast-client-cli \
  --fixed-end-epoch "$end_epoch" \
  --on-demand-price "$ON_DEMAND_DETERRENT" \
  --listing-floor "$HOST_LISTING_FLOOR_PER_GPU" \
  --expected-renter-floor "$RENTER_MACHINE_FLOOR" \
  --expected-renter-on-demand "$RENTER_MACHINE_ON_DEMAND" \
  --disk-price "$DISK_PRICE" \
  --upload-price "$UPLOAD_PRICE" \
  --download-price "$DOWNLOAD_PRICE" \
  --host-job-low "$HOST_JOB_LOW_PER_GPU" \
  --host-job-high "$HOST_JOB_HIGH_PER_GPU" \
  --expected-owner-low-renter-price "$OWNER_LOW_RENTER_PRICE_EACH" \
  --expected-owner-high-renter-price "$OWNER_HIGH_RENTER_PRICE_EACH" \
  --owner-image "$PINNED_PYTORCH_CUDA_IMAGE_DIGEST" \
  --max-public-seconds "$PUBLIC_WINDOW_SECONDS" \
  --max-fixed-end-seconds "$FIXED_END_HORIZON_SECONDS" \
  "$@"
}

DRY_RUN_END_EPOCH=$(( $(date +%s) + 43200 ))
run_controlled_cycle "$DRY_RUN_END_EPOCH"
```

Inspect `dry-run-plan.json`, manually reconcile Host Machines/Contracts, then
generate a fresh end and apply immediately in the same shell. Do not reuse the
dry-run epoch:

```bash
APPLY_END_EPOCH=$(( $(date +%s) + 43200 ))
run_controlled_cycle "$APPLY_END_EPOCH" --apply
```

The two required terminal confirmations name the exact machine and controlled
instance. The controller validates the fresh end again after confirmation.
There is no noninteractive bypass. Dry run and apply create separate timestamped
run directories; compare their `config.json` files when reviewing the apply.

The owner definition always ends with these arguments:

```text
--args /bin/bash -lc <reviewed workload>
```

The owner image must be a `pytorch/pytorch` CUDA image pinned by `@sha256:`;
tags alone are rejected. The reviewed workload runs a plain PyTorch CUDA
matrix multiplication loop for at most three minutes under `set -euo
pipefail`. It installs nothing, contacts no service, and contains no
error-swallowing `|| true`. It proves that exactly one CUDA device is visible
and checks a finite result after every synchronized multiplication. Each
job also runs `nvidia-smi`, requires exactly one enumerated GPU, and emits a
machine-readable proof event before checking PyTorch's CUDA device count. Each
one-GPU Host Job must remain
`running/running/running` for the full dwell while the exact client remains in
the explicit safe-stopped tuple. Before release, logs from both exact job IDs
must independently prove one visible CUDA device and at least one successful,
synchronized matrix multiplication. Any mismatch aborts.

Before the high mutation, two consecutive snapshots must show the controlled
client still `running/running/running`, both exact owner jobs inactive, and
each job's observed renter-side `dph_base` equal to the explicit expected low
value. The high phase must show the explicit expected high renter-side value
before it can count as reclaim. Both are inputs because the previously
observed surcharge is not treated as a universal scheduler formula.

Every price argument must be finite and greater than zero. The delayed check
cannot be shortened below 7,200 seconds, the owner dwell must be positive, and
the maximum public window cannot exceed 600 seconds.

Do not interpret a higher Host Job price as a stronger documented reclaim
request. If the renter remains running at the configured timeout, stop the
experiment, preserve the snapshots, and run guarded cleanup. Increasing price
again only repeats an unsupported hypothesis.

## Resume and cleanup order

After lowering the Host Job, the controller waits 60 seconds for exact
automatic return. It cannot issue client Start until it has atomically written
and fsynced `auto-resume-failure.json`, re-read it, and proved that the same
client is safely stopped and both exact owner jobs are inactive at the low
price in two consecutive samples. It continues checking owner inactivity
through client startup and refuses to confirm any owner/client overlap. A
manual recovery still fails the automatic-resume gate.

Cleanup runs after success, failure, Ctrl-C, SIGTERM, or SIGHUP:

1. unlist and prove both offer types absent in three consecutive samples;
2. only after step 1 succeeds, remove the Host Job and prove both its machine
   definition and all owner bid records are absent; if step 1 fails, retain the
   owner jobs and treat capacity state as unresolved;
3. only after step 1, re-prove the controlled client's full identity in both
   its single-instance and full-list views, destroy that exact ID, and require
   the CLI's noninteractive `--yes` plus either explicit JSON success or exact
   absence from both views.

Every offer-absence sample must be a top-level JSON array containing only
object rows. An error object, wrapper object, null response, or malformed row
fails the proof and keeps client destruction disabled for that run.

The fixed listing end is an independent backstop if the controller itself is
killed. Do not stop Vast, Docker, the host, or any container.

## Evidence and decision fields

Dry run and apply use separate timestamped private directories. A successful
dry run contains `config.json`, `authenticated-accounts.json`,
`reliability-baseline.json`, and `dry-run-plan.json`. Apply artifacts are
stage-conditional:

- `config.json` is written when the run directory is created;
- `authenticated-accounts.json` follows the distinct-account proof, and
  `host-instances-before-defjob.json` follows the owner-record preflight;
- `snapshots/*.json` plus `timeline.ndjson` at polling boundaries through
  reclaim, owner dwell, automatic return, and guarded recovery; the configured
  1-5 second sleep is not a guaranteed capture cadence because each snapshot
  performs several CLI requests;
- `reclaim-confirmed.json` and `low-phase-confirmed.json` after those gates pass;
- `owner-jobs.json`, both `owner-logs/*.log`, and
  `owner-workload-proof.json` after the owner records and workload are proved;
- either `auto-resume-confirmed.json` or `auto-resume-failure.json` after the
  automatic-return phase is reached;
- `manual-start-confirmed.json` only when controlled recovery was necessary;
- `reliability-baseline.json`, `reliability-immediate.json`,
  `reliability-post-cleanup.json`, and `reliability-delayed.json` only as each
  checkpoint completes;
- `cleanup.json` when the cleanup attempt completes, and
  `destroy-verification.json` only after destruction is proved;
- `result.json` on a normal controller return. A failure before the first
  mutation or any cleanup failure skips delayed observation. A post-mutation
  cycle failure followed by successful cleanup still receives the post-cleanup
  and delayed checks. Any checkpoint not reached is recorded as `{}`.

The controller currently parses the `list machine` response and cleanup
offer-absence samples in memory but does not save those raw responses as
standalone evidence. It also does not guarantee a fixed sampling cadence. Do
not treat this directory as a complete production audit trail. If the process
is interrupted, cleanup still runs, but `result.json` may be absent because the
final decision was not reached.

`result.json` reports `automatic_resume_gate`, `manual_start_used`,
`rating_gate`, `cleanup_complete`, and any `cycle_error`. The process exits
nonzero if automatic return fails, reliability, verification, reports, or
machine health changes at the immediate, post-cleanup, or delayed checkpoint;
if any cleanup proof fails; or if the cycle otherwise aborts. Missing fields
fail closed. A clean immediate result is still provisional until the mandatory
two-hour delayed observation completes.
An exclusive lock under `VAST_STATE_DIR` prevents two controllers from running
at once.
