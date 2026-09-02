# Controlled 24-hour verification and handoff pilot

This pilot answers two different questions on the delivered dedicated host:

1. Does a clean, continuously online Vast host show a healthy reliability and
   verification trend while controlled interruptible workloads run?
2. Can an exact owner on-demand standby take all GPUs within 15 minutes, run a
   real research workload, stop cleanly, and return every interrupted workload
   with its checkpoint intact?

The same 24-hour observation can collect evidence for both questions, but it
cannot make the second question part of the first. Vast's verification guidance
says to keep an unverified machine stable and clean, use Jobs/Create Job for
host work, and avoid unrelated workloads. The successful 82.281-second A100
handoff used an **owner on-demand instance**, not a Host Job. Three genuine Host
Job attempts did not take over a running interruptible. Treat the two halves
below as separate experimental modes and preserve the boundary in the evidence.
The first half is a qualification-trend observation rather than proof of a
pure verification control because the combined pilot keeps one fully stopped
owner standby record. Vast does not say whether a stopped record alone affects
verification. A strict control must contain no owner instance at all.

The controlled client's marketplace charges are an intentional pilot expense.
They are not treated as proof of outside demand or hidden inside host revenue.
Record the client charge, host earnings, owner-side charge, and net leakage as
four separate facts, and fund only the reviewed fixed-end test window.

Official sources:

- [Verification Stages](https://docs.vast.ai/host/verification-stages)
- [Understanding Verification](https://docs.vast.ai/host/understanding-verification)
- [Hosting Overview](https://docs.vast.ai/host/hosting-overview)
- [Instance types and priority](https://docs.vast.ai/guides/instances/choosing/instance-types)
- [Host optimization guide](https://docs.vast.ai/host/optimization-guide)
- [`set defjob` / background Host Job](https://docs.vast.ai/cli/reference/set-defjob)
- [Instance charges](https://docs.vast.ai/api-reference/billing/show-charges)
- [Host earnings](https://docs.vast.ai/api-reference/billing/show-earnings)

## Scope and prerequisites

Run this only on the dedicated physical SCAN host after the provider confirms
the delivered topology and permits marketplace hosting. Do not recreate this
pilot on a general-purpose third-party cloud VM. The host must have:

- four identical RTX PRO 6000 Blackwell GPUs visible by stable UUID;
- enough physical CPU, RAM, PCIe bandwidth, SSD storage, power, and cooling for
  the published Vast verification requirements;
- at least 500 Mbps symmetric measured networking, a public IPv4 address, and
  the required forwarded port range;
- supported Ubuntu Server, current stable NVIDIA driver/CUDA, SSH keys only,
  Secure Boot disabled, and a dedicated Docker data drive;
- a passing ordinary Self-Test without `--ignore-requirements`;
- no red machine error, report, Xid, uncorrectable ECC error, storage warning,
  thermal throttle, daemon disconnect, or unexplained contract;
- one host account and one separately authenticated controlled client account;
- one exact, pre-created four-GPU owner on-demand standby, fully stopped and
  explicitly allowlisted in the qualification HOLD before the pilot begins;
- an exact fixed offer end, reserved discount zero, no volume offer, and a hard
  10 GB disk allocation for each controlled interruptible instance;
- a private `VAST_STATE_DIR` shared by every controller on the operator host.

Never place API keys, emails, IP addresses, account IDs, machine IDs, instance
IDs, or private workload data in this repository. All raw evidence stays under
the private state directory.

## Experimental shape

Use the delivered four-GPU host as four one-GPU slices during the renter phase.
One controlled client account may own all four exact interruptible instances;
this tests multi-instance scheduling and checkpoint return, not independent
customer identities. Each worker runs a queue of short CUDA tasks and writes a
monotonic checkpoint plus a content digest to its own 10 GB allocation every 15
seconds.

Prepare one exact four-GPU owner on-demand standby while the host is vacant,
before enabling the qualification HOLD or acquiring the four controlled
interruptibles. Its image is pinned by digest, its retained disk is allocated,
and the instance must remain in the exact safe stopped tuple throughout the
first arm. Enable the HOLD with that one exact ID and label allowlisted; every
other owner record aborts. Its research probe must use all four GPUs through
`torchrun`, perform repeated bounded matrix work and an NCCL collective, write
an atomic owner checkpoint every 15 seconds, and expose a machine-readable
ready sentinel. Container state labels alone do not satisfy research readiness.

Prepare both contract sets with one reviewed end about 30 hours away. The
helpers hard-stop any fixed-end horizon beyond 48 hours; 30 hours leaves room
for preparation, the 24-hour clock, and the controller's 10-minute end buffer.
Resolve the image tag to a reviewed `@sha256:` digest first as described in the
runbook. Run this command once without mutation flags, inspect its private plan
and the exact Host Machines/Contracts view, then repeat it with
`--contracts-reviewed --apply` and satisfy the exact typed confirmation.

```bash
export VAST_STATE_DIR=/srv/sqwish-private/vast-state
END_EPOCH="$(( $(date +%s) + 30 * 60 * 60 ))"

python3 tools/prepare_owner_standby.py \
  --machine-id "$VAST_MACHINE_ID" \
  --host-cli /usr/local/bin/vast-host-cli \
  --gpu-count 4 \
  --fixed-end-epoch "$END_EPOCH" \
  --p99-host-on-demand-price "$HOST_ON_DEMAND_P99_PER_GPU" \
  --p99-host-bid-floor "$HOST_BID_P99_PER_GPU" \
  --expected-renter-on-demand-price "$RENTER_ON_DEMAND_FOUR_GPU_TOTAL" \
  --disk-price "$DISK_PRICE" \
  --upload-price "$UPLOAD_PRICE" \
  --download-price "$DOWNLOAD_PRICE" \
  --image "$REVIEWED_DIGEST_PINNED_IMAGE" \
  --disk-gb 20 \
  --label "$VAST_OWN_LABEL" \
  --original-reliability-baseline "$ORIGINAL_RELIABILITY"
```

The preparation proves the exact owner identity, starts it once, stops it into
the strict safe tuple, and records the digest-pinned command that will launch
the four-GPU probe. It cannot inspect the container's private checkpoint and
therefore does not claim that NCCL ran successfully during preparation. During
each handoff the owner-evidence adapter must prove the actual four-GPU
`torchrun`/NCCL result, the ready event, and checkpoint advancement. Read the
standby's ID only from the private result, set `VAST_OWN_INSTANCE_ID`, and then
enable the qualification HOLD:

```bash
python3 tools/verification_guard.py \
  --enable-qualification-mode \
  --machine-id "$VAST_MACHINE_ID" \
  --allowed-owner-standby "$VAST_OWN_INSTANCE_ID:$VAST_OWN_LABEL"
```

The listing is visible only during a bounded controlled-acquisition window.
Set the outside on-demand price at the reviewed unattractive ceiling and the
interruptible floor at a deliberately unattractive test price, then bid just
above that floor from the controlled account. Poll both host and client views at
two-second intervals, accept only the four exact labels and GPU slices, and
unlist immediately after all four are proven. Price reduces the acquisition
race; it is not access control. Any unknown contract aborts the pilot.

Acquire all four exact one-GPU slices with that same fixed end. The helper
searches `num_gpus=1` again before every create, gives each label exactly one
create attempt, proves the accumulated client inventory and machine rental
count after every acceptance, and unlists as soon as all four are running. An
uncertain call stops the sequence, so an uncertain third create never permits a
fourth. Its three-sample unlist proof searches without a GPU-size filter, so no
one-, two-, or four-GPU public row may remain. Run this command first as shown,
inspect its private plan and the exact current contracts, then repeat it with
`--contracts-reviewed --apply` and its
exact typed confirmation.

```bash
python3 tools/controlled_acquisition.py \
  --machine-id "$VAST_MACHINE_ID" \
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

Export the four returned IDs and labels from the private acquisition result for
the controller invocation below. Do not copy raw create responses; they may
contain instance credentials.

## Timeline

| Time | Mode | Activity |
|---|---|---|
| Before 00:00 | Guarded preparation | While vacant, pass the ordinary Self-Test, prepare and fully stop the exact owner standby, enable qualification HOLD with that one standby allowlisted, acquire the four exact controlled one-GPU interruptibles, unlist, prove both public offer views absent, start all four checkpointing task queues, and pass the controller's non-mutating preflight. Preparation time is not part of the 24-hour clock. |
| 00:00-12:00 | Qualification HOLD | Pin the immutable machine/rating/workload baseline. Run all four task queues and take five-minute host-health, contract, score, verification, and checkpoint samples. Rotate tasks inside each existing instance without destroying or reacquiring contracts. A rating decrease, error, failed task, lost checkpoint, or daemon/network event ends this arm before owner work. Flat reliability is inconclusive; an increase is useful observation, not proof of causation. |
| 12:00-12:30 | Mode transition | Stop sampling the qualification-trend arm, explicitly disable qualification HOLD, re-prove the exact standby and four renter states, and record that disabling the local guard does not certify owner workloads as verification-safe. |
| 12:30-13:00 | Research-first cycle 1 | Capture all four client checkpoints, request owner capacity, start the exact owner standby, require four-GPU workload readiness within 15 minutes, run for two minutes, checkpoint, stop safely, and prove all four clients resume automatically. |
| 13:00-16:00 | Research-first observation | Continue client queues and sample rating/health. Do not re-enable qualification HOLD while the owner standby exists. |
| 16:00-16:30 | Research-first cycle 2 | Repeat the exact handoff and automatic-return proof without changing images, bids, prices, hardware, daemon, Docker, or driver. |
| 16:30-20:00 | Research-first observation | Continue client queues and capture the two-hour delayed rating checkpoint for cycle 2. |
| 20:00-20:30 | Research-first cycle 3 | Repeat once more. Stop further takeovers on the first anomaly. |
| 20:30-23:30 | Delayed observation | Run all four client queues continuously and capture the delayed score, errors, reports, checkpoints, and hardware state. |
| 23:30-24:00 | Guarded safety cleanup | Unlist and prove offer absence; stop and prove the exact owner standby safe; prove all four named controlled-client instances running and healthy; capture the final rating/health snapshot. The reusable records remain. A separately reviewed exact-ID cleanup must retire them later, so the controller reports `full_pilot_cleanup_complete=false`. |

If the team wants an uncontaminated verification result, use a separate run
with no owner instance, omit the takeover arm, and extend Qualification HOLD to
at least 72 hours. Vast says a stable new machine typically reaches 90% within
a few days, so a 24-hour flat score is not a failure by itself. Never repeatedly
self-test, reboot, change drivers, or create artificial traffic to try to force
the score upward.

## Controller

The controller observes pre-existing workloads; it does not create accounts,
instances, offers, prices, or containers. Prepare the reviewed workload images,
the exact stopped standby, all four running one-GPU interruptibles, two
credential-isolated CLI wrappers, and seven operator-vetted shell-free evidence
adapters first. The controller strips unrelated environment variables and
validates each JSON response, but it cannot prove an executable is read-only;
review the adapters themselves. Run the non-mutating preflight before the
interactive apply:

```bash
python3 tools/controlled_24h_pilot.py \
  --machine-id "$VAST_MACHINE_ID" \
  --owner-instance-id "$VAST_OWN_INSTANCE_ID" \
  --owner-label "$VAST_OWN_LABEL" \
  --client "$CLIENT_1_ID:$CLIENT_1_LABEL" \
  --client "$CLIENT_2_ID:$CLIENT_2_LABEL" \
  --client "$CLIENT_3_ID:$CLIENT_3_LABEL" \
  --client "$CLIENT_4_ID:$CLIENT_4_LABEL" \
  --host-cli vast-host \
  --client-cli vast-controlled-client \
  --client-evidence-command sqwish-client-evidence \
  --owner-evidence-command sqwish-owner-evidence \
  --host-telemetry-command sqwish-host-telemetry \
  --host-contract-evidence-command sqwish-host-contract-evidence \
  --owner-charges-command sqwish-owner-charges \
  --client-charges-command sqwish-client-charges \
  --host-earnings-command sqwish-host-earnings \
  --self-test-passed-at "$SELF_TEST_PASSED_AT_ISO" \
  --original-reliability-baseline "$ORIGINAL_RELIABILITY"
```

After inspecting the private plan and Host Machines/Contracts view, repeat with
`--contracts-reviewed --apply`. Apply requires three exact typed confirmations.
It returns an attention-required nonzero status even after a technically clean
day because it deliberately retains the reusable records. Judge the structured
`result.json` fields rather than treating that status as a failed handoff.

The named pilot always runs exactly three handoffs; a smaller handoff count is
rejected rather than reported as a complete 24-hour result. The Self-Test
timestamp must be timezone-aware, no more than six hours old at
preflight, and refer to an ordinary pass performed while vacant without
`--ignore-requirements`. Host telemetry, host-contract, and billing adapters
must provide fresh evidence no more than two minutes old. Workload adapters are
invoked live and must prove checkpoint progression:

- each client adapter names its exact instance/label, running state, one GPU
  UUID, advancing checkpoint sequence and SHA-256 digest, and last completed
  task; post-handoff evidence also names the digest it resumed from;
- the owner adapter names its exact instance/machine/label, all four GPU UUIDs,
  readiness state, and advancing checkpoint. It reads
  `/root/sqwish-owner-probe/checkpoint.json` from the exact owner container,
  recomputes the SHA-256 over the canonical JSON without the `digest` member,
  and rejects a stale, malformed, or nonmatching checkpoint;
- host telemetry names the exact machine and four GPU UUIDs; daemon health;
  temperature, power/limit, throttle, ECC, and Xid state; root and dedicated
  Docker SSD health/capacity; at least 500 Mbps in both directions; public IPv4,
  wired networking, forwarded/reachable ports; and the reviewed OS, kernel,
  driver, CUDA, Secure Boot, SSH, physical-core, AVX, PCIe, RAM, background
  service, and VM-mode attestations; and
- host-contract evidence comes from a complete host-side Contracts source,
  names the exact stopped owner record and four exact active controlled bids,
  and explicitly reports no unknown or outside on-demand/reserved contract; and
- the three billing adapters expose only cumulative nonnegative USD totals for
  GPU, storage, and bandwidth: the exact owner instance charges, the exact four
  controlled-client charges, and host earnings for those four contracts.

Each billing adapter returns this normalized shape. Use role
`owner-charges` with the one owner ID, or `controlled-client-charges` /
`host-earnings` with the four controlled-client IDs:

```json
{
  "role": "controlled-client-charges",
  "machine_id": "<exact-machine-id>",
  "instance_ids": ["<client-1>", "<client-2>", "<client-3>", "<client-4>"],
  "currency": "USD",
  "cumulative": true,
  "observed_at": "<timezone-aware-ISO-timestamp>",
  "totals": {
    "gpu_usd": 0.0,
    "storage_usd": 0.0,
    "bandwidth_usd": 0.0
  },
  "source": "<reviewed-private-billing-source>"
}
```

The ordinary Vast CLI instance views cover only their authenticated accounts;
they do not replace the host-contract adapter or the fresh manual
Host Machines/Contracts review required by `--contracts-reviewed`.

## Measurements

The controller captures contract, host-health, score, and four-client checkpoint
evidence every five minutes in both observation arms and at every transition.
Every evidence file has its own monotonically numbered timestamped path. A gap
over six minutes aborts the arm, and completion requires the expected periodic
streams in both modes. During each handoff, instance state is sampled every two
seconds from the research scheduler decision until every client has returned.
Store:

- raw reliability, verification state, expected reliability when exposed,
  machine error fields, and reports;
- exact host and controlled-client instance state tuples, GPU allocations,
  labels, contract types, bids, and locked end dates;
- daemon reachability plus GPU UUID, utilization, temperature, power, clocks,
  throttle reasons, ECC, Xid, PCIe link, CPU, RAM, disk, and network counters;
- each client worker's checkpoint sequence, timestamp, digest, CUDA device UUID,
  and last completed task;
- owner request-to-ready elapsed time, platform state polls, four-GPU
  ready-sentinel evidence, owner checkpoint progress, stop proof, and the point
  at which all four clients have automatically returned;
- public bid and on-demand offer absence immediately after every unlist;
- platform charges and host earnings separately, without assuming self-rental is
  free.

The controller takes normalized baseline/final snapshots through the three
credential-isolated billing adapters and refuses cumulative totals that fall.
Vast exposes per-instance GPU, storage, and bandwidth charges through `vastai
show invoices-v1 --charges`, and host-side earnings through `vastai show
earnings`; both need `billing_read`. Adapter implementations may keep reviewed
raw responses in the private state directory, but they must return only the
normalized exact-instance totals and the controller never persists raw account
records. The generated billing report contains these five deltas separately:

1. owner own-machine GPU charge;
2. owner standby storage and bandwidth charge;
3. controlled-renter GPU, storage, and bandwidth charge;
4. host GPU, storage, and bandwidth earnings; and
5. net controlled-test leakage: controlled-renter charges minus host earnings.

The live two-A100 trial observed a zero owner GPU line and a nonzero retained
disk line. Vast calls the own-machine test instance free, while its general
billing guide says stopped instances continue to accrue storage. Re-measure
both rather than treating the public offer sticker price as the owner rate.

The reliability graph must show three vertical bands: qualification-trend soak,
explicit mode transition, and research-first handoffs. Do not draw one trendline
through all three as if they were the same operating condition.

## Acceptance gates

The **qualification-trend arm** passes its 12-hour observation only if:

- ordinary Self-Test passes and all published minimums are met;
- the daemon and host remain continuously reachable with no reboot or restart;
- no error/report or hardware, storage, thermal, power, port, or network anomaly
  appears;
- all four controlled interruptibles stay healthy and their checkpoints advance;
- reliability never falls below the immutable start-of-machine baseline or the
  start-of-arm value; and
- verification does not regress.

The arm is incomplete if any five-minute contract, telemetry, score, or
four-client checkpoint sample is absent or the evidence gap exceeds six minutes.

An observed reliability increase is encouraging. It cannot establish that the
workload caused the increase because Vast's automated algorithm also considers
elapsed uptime, hardware, performance, supply, and demand.

Each **research-first handoff** passes functionally only if:

- the host unlists and both public offer views are absent before takeover;
- inventory contains exactly the named owner standby and four named controlled
  interruptibles, with no on-demand/reserved outside contract;
- the exact four-GPU owner workload is ready within 900 seconds of the research
  scheduler's request;
- every renter pauses through platform scheduling, with no service/container
  kill, Docker restart, daemon stop, reboot, or machine shutdown;
- the owner job uses all four expected GPU UUIDs and writes a valid checkpoint;
- the owner reaches the fail-closed stopped tuple after release;
- all four original client instances return automatically within five minutes;
- every client checkpoint digest survives and its sequence resumes advancing;
- no immediate or two-hour-delayed reliability decrease, verification regression,
  report, or machine error is observed.

The full day is technically complete only after all three handoffs, all three
delayed samples, the final contract/health evidence, and the baseline-to-final
three-view billing report pass their gates.

Three passing handoffs still mean only “no observed rating change in this
controlled day.” Production use remains blocked unless the dedicated host also
accumulates a stable longer-term history and Vast confirms how routine owner
on-demand research instances affect verification.

## Abort and cleanup rules

Abort before owner start on any unknown instance, outside on-demand/reserved
contract, missing field, non-fixed end, offer still visible, reliability below
the immutable baseline, active qualification marker, red error/report, unhealthy
GPU, checkpoint lag, or ambiguous CLI response. Never weaken the guard with a
diagnostic override on the dedicated machine.

On an uncertain start or stop, preserve the state marker and resolve only the
exact instance through both single-instance and full-list views. Never issue a
broad destroy, kill a renter container, or restart platform services. Cleanup is
safe when the owner is exactly stopped, all four controlled renters have
returned, the machine is unlisted, both offer searches are empty, and local
health remains clean. The controller deliberately retains all five records so
its billing final can be captured before deletion. End the controlled-renter
charges with the separate exact-ID cleanup below; it always retains the owner
standby and its continuing storage charge.

The host-contract adapter used for cleanup receives the remaining exact clients
as repeated `--expected-client INSTANCE_ID:LABEL` arguments. It must return a
fresh, complete object with the exact stopped owner, the exact remaining client
subset, `outside_on_demand_or_reserved: false`, `outside_contract_ids: []`, and
`unknown_contract_ids: []`. Each controlled row must identify one active,
one-GPU interruptible; the final callback returns an empty controlled list and
the same stopped owner. Its normalized shape is:

```json
{
  "machine_id": "<exact-machine-id>",
  "observed_at": "<timezone-aware-ISO-timestamp>",
  "inventory_complete": true,
  "owner_standby": {
    "instance_id": "<owner-id>",
    "machine_id": "<exact-machine-id>",
    "label": "<exact-owner-label>",
    "is_bid": false,
    "num_gpus": 4,
    "safely_stopped": true
  },
  "controlled_contracts": [],
  "outside_on_demand_or_reserved": false,
  "outside_contract_ids": [],
  "unknown_contract_ids": [],
  "source": "operator reviewed Host Contracts inventory"
}
```

Run the cleanup first without mutation flags. It validates the two isolated
accounts, the stopped four-GPU owner, every remaining exact one-GPU client,
three bid/on-demand offer-absence samples, and the complete host-contract
adapter:

```bash
python3 tools/controlled_24h_cleanup.py \
  --machine-id "$VAST_MACHINE_ID" \
  --owner-instance-id "$VAST_OWN_INSTANCE_ID" \
  --owner-label "$VAST_OWN_LABEL" \
  --client "$CLIENT_1_ID:$CLIENT_1_LABEL" \
  --client "$CLIENT_2_ID:$CLIENT_2_LABEL" \
  --client "$CLIENT_3_ID:$CLIENT_3_LABEL" \
  --client "$CLIENT_4_ID:$CLIENT_4_LABEL" \
  --host-cli /usr/local/bin/vast-host-cli \
  --client-cli /usr/local/bin/vast-controlled-client-cli \
  --host-contract-evidence-command /usr/local/bin/sqwish-host-contract-evidence
```

After a fresh manual Host Contracts review, repeat the same command with
`--contracts-reviewed --apply` and type the exact confirmation it prints. The
tool revalidates inventory, offer absence, and fresh host-contract evidence
immediately before destroying each named client one at a time. It accepts a
destroy only after explicit success plus absence, or after both the exact
single-instance and complete client-list views prove absence. Completion means
the controlled-client inventory is empty and the host adapter sees only the
stopped owner.

If a response is uncertain, the external pending marker remains and no later
ID is touched. Inspect that marker and both account views, then rerun the same
command with `--resume-unresolved --contracts-reviewed --apply`; the tool
requires an additional exact acknowledgement and permits only the marker's
remaining authorized subset. Never delete its pending marker or lock merely to
make a retry proceed.

## Result language

Report the two questions separately:

- “During the qualification-trend soak, reliability changed from X to Y with no
  observed health or platform errors.”
- “During three research-first owner on-demand handoffs, readiness was A/B/C
  seconds; N of 12 client returns were automatic; immediate and delayed rating
  deltas were ...”
- “Owner GPU charge was X; owner disk/bandwidth was Y; controlled-renter spend
  was Z; host earnings were W; net test leakage was Z-W.”

Do not say the owner takeover ran through Host Jobs, improved verification, or
is rating-safe unless Vast's documentation changes or Vast supplies that
guarantee in writing.
