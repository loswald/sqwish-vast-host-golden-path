# Controlled two-hour 2xA100 qualification plan

> **Result:** Three clean Host Job attempts did not preempt the controlled
> renter. A later exact pre-created owner on-demand standby did: owner running
> in 82.281 seconds, controlled interruptible safely stopped, exact owner stop,
> and automatic renter return without fallback. The near-instant,
> rating-safe-production gate is still **BLOCKED** because the run began below
> its immutable original reliability baseline and its delayed observation was
> skipped. Keep this schedule as diagnostic qualification, not production
> reclaim automation.

This is the first end-to-end acceptance test for a dedicated physical Vast host. It exercises a real client contract while keeping the workload, client account, timing, and data under operator control.

It must not run on infrastructure whose provider has not expressly approved third-party hosting. Vast exposes no documented private or account-allowlisted offer. The listing is public between publication and controlled acquisition, even at a very high price.

## Questions the trial answers

The trial measures, on one exact machine and current Vast scheduler version:

- whether a separate controlled client can acquire all GPUs as one interruptible contract;
- whether the official Host Job mechanism can outbid that interruptible, run owner work, and release it again;
- whether a two-GPU owner on-demand self-test pauses the controlled client atomically;
- whether the client resumes automatically with its checkpoint and disk intact;
- whether two independent one-GPU clients can be reclaimed selectively and together;
- reclaim, release, and resume latency;
- host CPU, RAM, storage, network, thermal, and GPU overhead;
- immediate and delayed observed reliability, verification, and report changes.

It does not prove a universal reliability exemption, a scheduler SLA, safety for arbitrary tenant images, zero acquisition risk, or behavior on a different GPU topology. Repeat the relevant phases on the delivered 4x RTX PRO 6000 machine.

## Official behavior and remaining gaps

Vast documents two supported ways to test an operator's own machine: a separate client account for the full client experience, and a free own-machine instance from the host account. It documents that on-demand instances outrank interruptibles, that higher client interruptible bids have priority, and that paused interruptibles resume when priority returns.

Vast's Verification Stages guide says host workloads must use the Jobs path. The current host CLI exposes `vastai set defjob`, whose reference describes a background job and a per-GPU price. It does not document that the price can preempt a renter, publish a reclaim-latency SLA, or promise no rating effect. The Host Job API also exposes no explicit GPU-count parameter. Pass a shell workload as `--args /bin/bash -lc '<OWNER_COMMAND>'`; `--args` consumes the rest of the command and must remain last.

An earlier mixed sequence appeared to fan out two one-GPU records and pause the renter, but it included a malformed owner launch and other state changes. Three later clean attempts used `$1.10/GPU-hour` for 30 seconds, `$1.30/GPU-hour` for 90 seconds, and `$3.00/GPU-hour` for 120 seconds. None paused the renter. There is therefore no usable Host Job-versus-renter price formula and no clean release/resume result.

A host-account, own-machine on-demand instance is documented for testing and outranks interruptibles. The final diagnostic proved this exact end-to-end path once, including automatic renter return. Until Vast confirms that ongoing team work may use that route and a dedicated box passes repeated original-baseline and delayed-rating checks, treat it as a reclaim experiment rather than production policy.

Sources:

- [Hosting Overview and own-machine testing](https://docs.vast.ai/host/hosting-overview)
- [Verification Stages and Host Jobs](https://docs.vast.ai/host/verification-stages)
- [Interruptible priority and automatic resume](https://docs.vast.ai/guides/instances/choosing/instance-types)
- [`set defjob`](https://docs.vast.ai/cli/reference/set-defjob)
- [`remove defjob`](https://docs.vast.ai/cli/reference/remove-defjob)
- [List-machine API fields](https://docs.vast.ai/api-reference/machines/list-machine)

## Final owner-standby pilot result

The successful acquisition sampled 17 comparable interruptible offers. The renter-facing P10 was **$0.7466667/hour for the whole two-GPU machine**, mapped to a **$0.28/GPU-hour host floor** under the live conversion. The outside on-demand price was **$5.84/GPU-hour host-side**, or **$15.5733/hour renter-facing for the pair**; reserved discount was zero.

The owner standby was an exact pre-created host-account on-demand instance, proven safely stopped before acquisition. The acquisition guard was narrowed to allow only that exact ID, label, machine, `is_bid=false` mode, two-GPU count, and stopped-state tuple; every other target-machine record remained fatal. After the separately authenticated controlled client occupied both GPUs as one interruptible, the host unlisted and proved both offer views absent.

The takeover controller unlisted and re-proved absence before starting the exact standby. The controlled interruptible reached the safe-stopped tuple and the owner reached `running/running/running` **82.281 seconds after the reclaim decision**. The exact owner then stopped, and the same controlled renter returned automatically. The evidence-gated fallback Start was not used. A separate post-pilot probe ran real PyTorch CUDA work across both owner-visible GPUs successfully.

Reliability was **0.5727243** immediately before takeover, immediately after it, and after cleanup. The immutable original observation was **0.5999925**, so the degraded diagnostic override was required and the run cannot establish production readiness. The delayed checkpoint was skipped because the disposable host reached its preconfigured automatic-deletion deadline. Final reconciliation proved no contracts and no bid/on-demand offers.

Vast's Verification Stages guide explains that new-machine reliability starts low and usually grows past 90% after days of stable uptime. The preceding restart is therefore a plausible explanation for the earlier decrease, but the evidence cannot prove attribution. The same guide warns that personal workloads can fail verification while host guidance directs work through Jobs or `create job`; obtain Vast's written interpretation before treating the own-machine standby as Sqwish's daily research path.

## Hard gates

Do not start the two-hour clock until all gates pass:

1. The host is dedicated physical hardware under operator control and hosting is permitted.
2. Docker mode is in use; VM mode is off.
3. The machine is vacant, verified as expected, self-test passes, and there are no reports or red machine errors.
4. The host and controlled client use distinct Vast accounts. The controlled client is authenticated, funded, and ready on the exact-machine search before listing.
5. The controlled client image is operator-reviewed and pinned by an exact
   `@sha256:` digest. Mutable tags are rejected. It makes no unrelated outbound
   connections.
6. The image records one-second UTC heartbeats and a monotonic sequence to persistent instance disk, fsyncs a checkpoint every five seconds, and loads every visible GPU with a bounded CUDA test.
7. The physical Docker pool is XFS with project quotas and a hard 250 GB boundary. Root has at least 20 GB free. Docker storage is below 70 percent used and has at least 50 GB free before every phase.
8. A 2-GPU owner on-demand test instance is created on the exact machine while vacant, proven to see both GPUs, then stopped. Record its exact instance ID, offer ID, label, machine ID, and safe stopped-state tuple.
9. The owner Host Job definition is staged at a value below the controlled-client bid. Its image logs `CUDA_VISIBLE_DEVICES`, `nvidia-smi -L`, heartbeat, and checkpoint state.
10. Live one-second host telemetry, 2-5 second Vast state sampling, and two-second external client health checks are already collecting.
11. Capture raw baseline reliability, expected reliability, verification, reports, offer and contract inventory, daemon status, GPU UUID/ECC/Xid/temperature/power/clocks, disk, RAM, CPU, and network counters.
12. An independent stop/cleanup backstop is active.

## Listing and controlled acquisition

For the full-machine phase, set `min_chunk=2`, `discount_rate=0`, `vol_size=0`, and a fixed end epoch at the trial deadline. `vol_size=0` prevents a separate volume offer; it does not cap instance disks. Specify a 10 GB client disk explicitly and rely on the physically bounded Docker pool for the total cap.

Use a freshly sampled **P10** interruptible floor for the intended spare-capacity market shape, with the controlled client ready before publication. This is not a private listing and does not prevent a stranger from winning the race.

Do not mix the two price units. In a `search offers --type bid` response, `min_bid` is the renter-facing **total for the whole offered machine per hour**. Host `list machine --price_min_bid` and the machine record's `min_bid_price` are host-earned **per GPU-hour**. The CLI's client `--bid_price` is again the whole-machine hourly total. With the currently observed 25% marketplace surcharge, convert a sampled renter total to the host listing input as:

```text
host price_min_bid per GPU-hour = renter machine-total P10 * 0.75 / offered GPU count
```

Derive and verify the live conversion from the exact relisted offer instead of assuming 0.75 forever. In the final 17-comparable snapshot, the 2-GPU renter-total P10 was **$0.7466667/machine-hour**, which mapped to a **$0.28/GPU-hour** host floor. Multiplying the raw `min_bid` by the GPU count double-counts the GPUs and can make the controlled bid fail to clear its own listing.

Representative listing shape:

```bash
vastai list machine "$MACHINE_ID" \
  --price_gpu "$ON_DEMAND_DETERRENT" \
  --price_min_bid "$HOST_PER_GPU_FLOOR_DERIVED_FROM_P10" \
  --price_disk "$DISK_PRICE" \
  --price_inetu "$UPLOAD_PRICE" \
  --price_inetd "$DOWNLOAD_PRICE" \
  --discount_rate 0 \
  --min_chunk 2 \
  --end_date "$FIXED_END_EPOCH" \
  --vol_size 0
```

The controlled client must query the exact machine ID, exact two-GPU bid offer, verify that its renter-facing `min_bid` equals the sampled machine-total floor, and issue exactly one create with a unique label, a 10 GB disk, and a machine-total bid that clears that value. The final snapshot exposed `min_bid=0.7466667` for the pair. Do not blindly retry an uncertain create.

As soon as the exact controlled instance is proven running on the intended machine with both GPUs, unlist the machine. Official Vast documentation says unlisting prevents new contracts while existing contracts continue under their original terms.

Abort if acquisition does not complete promptly, lands on another machine, exposes the wrong GPU count, or any unexpected contract appears. Unlist immediately. Do not interfere with an unexpected contract; honor its fixed end date.

Preparation pitfalls from the final pilot:

- A `10/10` standby-preparation listing returned HTTP 422. The known accepted `price_gpu=5.84`, `price_min_bid=3` shape was used instead and verified live; this is an observation, not a documented numeric limit.
- Own-machine create with `--cancel-unavail` returned the false-ownership error. After exact absence proved that the failed call created nothing, one vacant-host retry without the flag succeeded. Never use that retry pattern while a renter is active.
- The general acquisition guard initially rejected the intentional owner standby. Its safe exception must name one exact standby ID and label and prove same machine, `is_bid=false`, two GPUs, and safe stopped state. Unknown or additional target records still abort.

## Two-hour schedule

| Time | Action and required evidence |
|---|---|
| 00:00-00:03 | List with `min_chunk=2`; controlled client acquires the exact 2-GPU interruptible; verify client, machine, offer, bid, GPU count, image, label, and disk; unlist and prove no offer remains. |
| 00:03-00:08 | Warm the controlled workload. Prove two GPU UUIDs, bounded CUDA load, heartbeat, fsynced checkpoint, and a clean NCCL/all-reduce result. |
| 00:08-00:18 | **Host Job reclaim 1.** Relist under the same full-GPU, high-floor controls only long enough for the staged Host Jobs to schedule, watching continuously for an unexpected contract, because the live test found they remained inert while unlisted. Raise the Host Job above the client bid. Measure client pause and Host Job start; inspect how many GPUs the Host Job sees. Run five minutes, lower it below the client bid, and measure client resume and checkpoint recovery. If it does not resume within the acceptance limit, preserve evidence and use the controlled client's guarded **Start** action once. |
| 00:18-00:28 | **Host Job reclaim 2.** Repeat once. Stop if Host Job GPU allocation is ambiguous, either side overlaps on a GPU, or any state transition is uncertain. |
| 00:28-00:38 | **Atomic 2-GPU on-demand reclaim 1.** Start the exact stopped owner test instance. Measure controlled-client pause and owner running. Run the known two-GPU owner job for five minutes; stop the exact owner instance and measure client resume. |
| 00:38-00:48 | **Atomic 2-GPU on-demand reclaim 2.** Repeat once using only the exact recorded instance. Do not create a replacement while occupied. |
| 00:48-00:55 | Full-machine loaded soak. Verify checkpoint sequence, no corruption, no Xid/ECC/OOM, no daemon gap, healthy storage/network, and unchanged immediate machine status. |
| 00:55-01:00 | Export controlled-client evidence, destroy its exact contract, prove both GPUs idle, and reconcile the exact host contract view. |
| 01:00-01:05 | Relist with `min_chunk=1`. Sequentially acquire two exact one-GPU interruptible contracts from the controlled client. Re-query after the first because available offer IDs may change. Unlist only after both are proven running. |
| 01:05-01:12 | Warm both clients. Prove each sees one exclusive physical GPU, independent heartbeat/checkpoint state, and no MIG assumption. |
| 01:12-01:22 | **Selective one-GPU reclaim.** Start the exact one-GPU owner test if a separately proven standby exists. Exactly one controlled client should pause while its sibling remains healthy. Stop owner and verify resume. Otherwise record this phase as deferred rather than improvising a create. |
| 01:22-01:32 | **Full reclaim over slices.** Start the exact 2-GPU owner test instance. Both one-GPU clients should pause before owner runs. Stop owner and verify both resume, recording pause and resume skew. |
| 01:32-01:42 | Repeat full reclaim over slices once. |
| 01:42-01:50 | Final loaded soak. Capture client integrity, telemetry, reports, raw reliability, expected reliability, and verification. |
| 01:50-01:56 | Export evidence; stop any owner test instance; destroy both exact controlled-client contracts. |
| 01:56-01:59 | Prove unlisted, no volume offer, no active contract, GPUs idle, and storage healthy. Reconcile expired/deleted contracts only after vacancy is proven. |
| 01:59-02:00 | Preserve logs, revoke the temporary controlled-client API key, and leave the machine unlisted. |

## Live evidence

Collect three independent layers:

- **Host every second:** GPU utilization, VRAM, temperature, power, clocks, ECC/Xid; CPU; available RAM and swap; Docker-pool capacity and IO; NIC throughput, errors, and drops.
- **Vast every 2-5 seconds:** exact instance state tuples, host job fields, offer and contract inventory, reliability, expected reliability, verification, and reports.
- **Controlled client every two seconds:** health response, GPU UUID visibility, heartbeat sequence, checkpoint sequence, and reconnect gaps.

Vast Machine Metrics samples hardware frequently and container state at roughly 15-second intervals, but uploads can lag. Use it as corroboration rather than the live controller.

## Operational pass thresholds

Every executed cycle must satisfy:

- only the exact controlled contracts appear;
- a pre-created owner on-demand standby reaches running within 900 seconds from the research decision; Host Job diagnostics may retain a separate shorter timeout;
- no owner/client overlap occurs on a GPU;
- the controlled client automatically runs again within the configured bounded return window; if it does not, the cycle fails even if a guarded client **Start** later recovers it;
- its disk checkpoint is intact with no more than five seconds of uncheckpointed work;
- an unaffected one-GPU sibling has no health gap over five seconds;
- no daemon disconnect, host outage, Xid, uncorrectable ECC, OOM, storage exhaustion, persistent throttle, network error, report, red machine error, immediate reliability decrease, or verification change occurs.

The 15-minute owner-start target and bounded return window are internal acceptance targets. Vast publishes no reclaim or resume SLA. The final pilot measured 82.281 seconds to owner running and automatic renter return without fallback.

## Immediate aborts

Stop further mutations, unlist, and preserve evidence if:

- an unknown client or contract appears;
- an on-demand or reserved outside contract appears;
- a controlled create lands on the wrong machine or GPU count;
- all intended slices are not filled promptly;
- owner identity or stopped-state proof is incomplete;
- an owner start exceeds its configured 15-minute-or-shorter SLO;
- GPU ownership overlaps;
- the daemon or host disconnects;
- reliability, verification, reports, hardware, storage, or network health worsens;
- checkpoint integrity fails.

Never respond by killing a client container, stopping Docker/Vast, rebooting, powering off, or using maintenance as an eviction control.

## Rating observation window

Capture the same raw reliability, expected reliability, verification, reports, and notification state:

- immediately before the test;
- after every reclaim/release cycle;
- at the end of the test;
- two hours later;
- 24 hours later;
- seven days later.

The result may say “no observed change through seven days.” It must never claim a universal no-penalty guarantee unless Vast provides that guarantee in writing. In this live trial, reliability started at 0.5999925, briefly reached 0.599997, and fell to 0.5727243 during the restart/new-client sequence. The later successful owner-standby handoff was flat at 0.5727243 immediately and after cleanup. Because that score was already below the immutable original baseline and the delayed checkpoint was skipped at the disposable host's automatic-deletion deadline, the result is diagnostic rather than rating-safe evidence.

## Four-GPU adaptation

On the delivered 4x RTX PRO 6000 machine, repeat rather than extrapolate:

1. qualify driver/CUDA, topology, PCIe, four-GPU NCCL, thermals, power, storage, and network;
2. acquire one controlled four-GPU interruptible with `min_chunk=4`, unlist, and run two full-node cycles;
3. relist with `min_chunk=1`, acquire all four one-GPU slices from the controlled client, and unlist;
4. test one-GPU owner reclaim, two-GPU owner reclaim, then four-GPU owner reclaim twice;
5. record which client contracts pause, transition skew, sibling continuity, and whether a four-GPU owner request assembles the entire machine;
6. keep a 350-400 GB physically bounded Docker pool for four minimal test disks, image cache, checkpoints, and margin.

Sequentially filling four slices extends the public acquisition window. If zero unknown exposure is required, obtain a private-offer mechanism in writing from Vast before running that phase.

## Trial record

Fill this table with sanitized evidence only:

| Field | Result |
|---|---|
| Test date/time and Vast CLI version | 2 September 2026; CLI 1.5.6 |
| Hardware/topology | 2× A100-SXM4-40GB; 300 GB/s advertised NVLink; two-GPU NCCL passed |
| Baseline reliability / expected reliability / verification | 0.5999925 / unavailable / unverified; no reports or machine error |
| Final controlled listing/bid inputs | 17-comparable P10: $0.7466667 renter-visible whole pair; $0.28 host/GPU-hour floor; outside on-demand $5.84 host/GPU-hour and $15.5733 renter-visible pair; reserved discount zero. These were dated test inputs. |
| Public acquisition behavior | A visible two-hour-plus fixed ask returned `no_such_ask` and created no contract. Twelve-hour asks later launched after continuous bid-offer stability. Bid and on-demand views flickered independently; the helper unlisted immediately after its one create call. |
| Exact controlled contracts only | The observed acquisition and reclaim records contained the operator-controlled client and owner jobs |
| Host Job visible GPU count | An earlier mixed sequence produced two one-GPU records; clean attempts did not reach owner execution, so repeatable fan-out is unproved. |
| Host Job reclaim/resume timings | Clean attempts at $1.10/30 seconds, $1.30/90 seconds, and $3.00/GPU-hour/120 seconds did not preempt the controlled renter. Release/resume was not reached. |
| 2-GPU on-demand reclaim/resume timings | Exact pre-created standby reached running in 82.281 seconds; controlled interruptible safely stopped; exact owner stopped; same renter resumed automatically without fallback. |
| Selective one-GPU result | Pending |
| Full reclaim over slices result | Pending |
| Checkpoint/data integrity | Same controlled contract returned automatically. A separate post-pilot owner probe passed real two-GPU PyTorch CUDA work; full application-checkpoint qualification remains for the dedicated box. |
| Host overhead and health | Both GPUs reached 100%, ~36.3 GB VRAM and ~300 W each, 55-58°C, zero burn errors; returned idle cleanly |
| End-of-test reliability / verification / reports | Successful standby handoff was 0.5727243 immediately and after cleanup, unchanged from its degraded pre-takeover value but below immutable original 0.5999925. No rating-safety claim is supported. |
| +2h / +24h / +7d observation | Delayed observation skipped when the disposable host reached its exact automatic-deletion deadline; later windows unavailable. |
| Final cleanup | Owner stopped; exact controlled renter destroyed only after unlist proof; no contracts or bid/on-demand offers remained. |
| Final conclusion and open questions | Host Job reclaim failed, but exact owner on-demand standby preemption and automatic return worked once within 15 minutes. Production remains blocked pending repeated dedicated-box cycles, original-baseline/delayed rating evidence, and Vast clarification on personal research workloads versus Jobs. |
