# Clean two-A100 Host Job reclaim cycle

`tools/controlled_hostjob_cycle.py` repeats only the previously confounded
Host Job phase. It assumes the exact two-GPU interruptible has already been
acquired by the separate controlled client and the host is unlisted. It does
not create a renter, sample prices, or expose a vacant host.

Run this only on a dedicated physical host whose provider permits marketplace
hosting. Raw evidence contains private resource identifiers and stays under
`VAST_STATE_DIR`, outside this repository.

## Authentication boundary

Provide two different executables. `--host-cli` uses the host account and
`--client-cli` uses the controlled client account. Each executable must obtain
its key from its own private configuration; the controller refuses API-key
arguments and refuses to run when the executable paths resolve to the same
file. It also queries both authenticated user records and requires two distinct
positive account IDs before the first mutation. A small wrapper that selects a
separate `HOME` is sufficient:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail
export HOME=/home/operator/vast-controlled-client
exec /usr/local/bin/vastai "$@"
```

Keep the wrapper and both key files mode `0700`/`0600`.

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
  post-mutation proof fails, destruction is skipped. A client ID configured as
  `VAST_OWN_INSTANCE_ID` is never eligible for destruction.
- Prices come from a fresh live comparison. Host Job prices are host-entered
  per GPU-hour. The controlled client's bid is renter-facing per machine-hour.
- Choose a fixed end at least long enough for the dwell and both timeouts, and
  no more than 15 minutes away. The controller aborts and cleans up if that
  exact end, full-machine chunk, on-demand price, and renter-facing floor are
  not visible on the exact machine and every exact target offer.
- Machine reliability, verification, and all three machine-error fields must
  be present and clean before mutation. Machine report counters may be null,
  so the controller uses the authoritative `vastai reports <machine> --raw`
  response. The current official CLI implementation prints that response as
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

```bash
export VAST_STATE_DIR=/home/operator/.local/state/vast-host-golden-path
END_EPOCH=$(( $(date +%s) + 600 ))

python3 tools/controlled_hostjob_cycle.py \
  --machine-id "$MACHINE_ID" \
  --client-instance-id "$CONTROLLED_CLIENT_ID" \
  --client-label "$CONTROLLED_CLIENT_LABEL" \
  --host-cli /home/operator/bin/vast-host-cli \
  --client-cli /home/operator/bin/vast-client-cli \
  --fixed-end-epoch "$END_EPOCH" \
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
  --owner-image "$PINNED_PYTORCH_CUDA_IMAGE_DIGEST"
```

Inspect `dry-run-plan.json`, manually reconcile Host Machines/Contracts, then
repeat the same command with `--apply`. The two required terminal confirmations
name the exact machine and controlled instance. There is no noninteractive
bypass.

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
the maximum public window cannot exceed 900 seconds.

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
2. remove the Host Job and prove both its machine definition and all owner bid
   records are absent;
3. only after step 1, re-prove the controlled client's full identity in both
   its single-instance and full-list views, destroy that exact ID, and require
   either explicit JSON success or exact absence from both views.

Every offer-absence sample must be a top-level JSON array containing only
object rows. An error object, wrapper object, null response, or malformed row
fails the proof and keeps client destruction disabled for that run.

The fixed listing end is an independent backstop if the controller itself is
killed. Do not stop Vast, Docker, the host, or any container.

## Evidence and decision fields

The timestamped private run directory contains:

- `config.json`, `dry-run-plan.json`, `authenticated-accounts.json`, and
  `host-instances-before-defjob.json`;
- `snapshots/*.json` plus `timeline.ndjson` every 1-5 seconds through reclaim,
  owner dwell, automatic return, and guarded recovery;
- `reclaim-confirmed.json`;
- `low-phase-confirmed.json`;
- `owner-jobs.json`, both `owner-logs/*.log`, and
  `owner-workload-proof.json`;
- either `auto-resume-confirmed.json` or `auto-resume-failure.json`;
- `manual-start-confirmed.json` only when controlled recovery was necessary;
- `reliability-baseline.json`, `reliability-immediate.json`,
  `reliability-post-cleanup.json`, and `reliability-delayed.json`;
- `cleanup.json`, `destroy-verification.json`, and `result.json`.

`result.json` reports `automatic_resume_gate`, `manual_start_used`,
`rating_gate`, `cleanup_complete`, and any `cycle_error`. The process exits
nonzero if automatic return fails, reliability, verification, reports, or
machine health changes at the immediate, post-cleanup, or delayed checkpoint;
if any cleanup proof fails; or if the cycle otherwise aborts. Missing fields
fail closed. A clean immediate result is still provisional until the mandatory
two-hour delayed observation completes.
An exclusive lock under `VAST_STATE_DIR` prevents two controllers from running
at once.
