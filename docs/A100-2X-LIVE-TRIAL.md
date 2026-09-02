# Two-A100 live hosting trial

This note records the reusable parts of the 2× NVIDIA A100-SXM4-40GB qualification trial run on 2 September 2026. It intentionally excludes provider resource names, zones, addresses, account and project identifiers, machine and contract IDs, SSH paths, and all credentials.

## Status at a glance

| Claim | Status | Evidence |
| --- | --- | --- |
| A fresh on-demand 2× A100 host can be installed without touching an existing research worker | **Proved** | A separate 2-GPU trial node was provisioned, both GPUs were visible, and the Vast host services remained healthy. |
| Docker storage can be physically bounded away from the root filesystem | **Proved** | `/var/lib/docker` was mounted from a dedicated 250 GB XFS disk with project quotas enabled. |
| The two GPUs and their interconnect pass Vast's workloads | **Proved diagnostically** | The relaxed self-test passed ResNet18, ECC, 2-GPU NCCL, and the simultaneous CPU/GPU burn. The run explicitly did not qualify the new host for verification. |
| One-GPU and two-GPU owner jobs can be prepared in advance | **Proved while vacant** | Both on-demand standbys booted, saw the intended GPU count, and returned to a safe stopped state with their 20 GB disks retained. |
| A separate-account interruptible can be reclaimed and returned through an exact owner standby | **Technical path proved once; production gate failed** | The pre-created on-demand standby reached running in 82.281 seconds, safely stopped the renter, then stopped and returned it automatically without fallback. Reliability remained below its immutable original baseline and no delayed check completed. |

## Disposable on-demand host

Use a separate test VM. Do not retrofit a running research worker for a marketplace experiment.

This third-party cloud node was a disposable, operator-controlled qualification environment. It admitted only the operator's separate client account and a reviewed image; the public listing window was measured in seconds and no unknown renter appeared. Do not expose third-party cloud capacity to public tenants. Run any production hosting or unknown-tenant trial on the dedicated physical box, with the storage boundary and cleanup controls in this note.

The successful trial shape was a provider-managed on-demand 2-GPU node with:

- 2× A100-SXM4-40GB GPUs connected through the advertised NVLink topology;
- Ubuntu 22.04 and NVIDIA driver 580.173.02;
- an 80 GB balanced root disk;
- a separate 250 GB SSD data disk for Docker; and
- a fixed 100-port TCP and UDP range for Vast's direct connections (`16384-16483` in this trial).

This was standard on-demand capacity, not Spot or preemptible capacity. A first-choice region had stock exhausted in two zones; retrying the same shape in another supported region succeeded. Build regional fallback into the checklist, but do not silently downgrade the GPU shape or switch to Spot.

At the trial's quoted list rate, compute cost **$7.34677/hour**, or **$88.16 for 12 hours**. Temporary root/data disks and the external address added less than roughly $1 over 12 hours. Internet egress was separate and could exceed the small infrastructure extras. Start the 12-hour timer when the VM is created, because installation and qualification consume billable time.

## Hard Docker storage boundary

The data disk was formatted as XFS with `ftype=1`, mounted at `/var/lib/docker`, and persisted with `pquota`/`prjquota`. Docker was installed only after this mount was active. The root filesystem therefore remained outside the tenant pool, and Docker images, layers, owner standbys, and tenant writable data shared a hard 250 GB physical ceiling.

The 250 GB size was selected as a minimum-plus-25% trial cap against Vast's current fixed 200 GB machine-wide minimum. Vast's [current verification requirements](https://docs.vast.ai/host/verification-stages#storage) specify at least 200 GB on a dedicated Docker SSD plus 20 GB free on the root partition. Vast [replaced the former 128 GB-per-GPU text](https://github.com/vast-ai/docs/commit/1400a4d4d91cc8fff8a1854540406ff1c894d195) with this fixed requirement in August 2026, although the live Host Setup console still showed the old wording during this trial. Use the current verification requirement as the source of truth and never satisfy it by exposing the root filesystem.

Registration and listing accepted this 250 GB pool, but those actions do not prove verification eligibility. The current CLI self-test preflight also does not directly gate on disk capacity, so retain the documented 200 GB data-disk and 20 GB root-free requirements even if an undersized host can register.

Before running the installer, verify the mount rather than trusting the cloud-init log:

```bash
findmnt -no SOURCE,FSTYPE,OPTIONS /var/lib/docker
df -h / /var/lib/docker
xfs_info /var/lib/docker
```

The expected result is a distinct XFS filesystem at `/var/lib/docker`, with `ftype=1` and `pquota` or `prjquota` in the active mount options. A directory on the root disk is a failed preflight.

Two stopped owner standbys reserve 20 GB each. After those 40 GB reservations and Vast's own allowance, the live listing exposed **185 GB total tenant disk**, shown as **92.5 GB for each 1-GPU offer**. This is the practical proof that renters cannot consume the root disk or the whole 250 GB Docker pool. The cap is aggregate: image layers and owner disks also consume it, so monitor free space and keep a cleanup margin.

## Installer and vacant-host checks

Use the current standard host command copied from Vast's Host Setup page. Never save its short-lived installation credential in the repository or paste it into notes. The reusable order is:

1. Confirm both GPUs with `nvidia-smi` and the intended topology with `nvidia-smi topo -m`.
2. Mount and verify the dedicated XFS Docker disk.
3. Open the reviewed direct-port range for both TCP and UDP.
4. Run the official Vast installer and answer its port-range prompts.
5. Confirm Docker can launch a CUDA container and NVML sees both GPUs.
6. Confirm the Docker, Vast launcher, and Vast metrics services are active.
7. Confirm `/var/lib/docker` is still the quota-enabled data mount after installation.
8. Confirm both GPUs return idle before listing or self-test.

The installer completed its Docker and NVIDIA-container checks on this host, and the platform reported the intended two-GPU inventory. A successful installer is not a substitute for the Vast self-test.

## Why the self-test needed relaxed mode

The new machine reported reliability **0.5999925**, briefly **0.599997**, effectively Vast's 60% starting value. The ordinary self-test preflight refused to continue because verification requires reliability above 0.9. Vast also requires at least 500 Mbps in both directions; this host's measured upload was about 161.9 Mbps, so it did not meet that network gate. The diagnostic run was therefore started with:

```bash
vastai self-test machine <MACHINE_ID> --ignore-requirements
```

That run reported:

- system requirements passed;
- ResNet18 passed on both GPUs;
- ECC passed;
- the distributed NCCL test passed across two GPUs;
- `stress-ng` plus `gpu-burn` completed its 60-second combined load;
- `Test completed successfully` and `Test passed`;
- the temporary test instance was destroyed on the first attempt; and
- the remote result reached `DONE`.

This proves the diagnostic hardware and workload path. The command warned that relaxed mode does **not** qualify the host for verification. Record the result as a relaxed pass and keep verification pending until reliability and the ordinary requirements permit a strict run. The live Machine Reports view showed no unacknowledged reports, so there was no separate hardware or daemon error to repair. Vast's [verification process](https://docs.vast.ai/host/understanding-verification) is automated: reaching the minimum makes a host eligible but does not guarantee immediate promotion.

## Prepare owner standbys before accepting renters

Create standbys only while the host is vacant. This reserves their disk space before tenants can consume the pool and avoids allocating a new owner filesystem during a reclaim.

The trial prepared these two on-demand templates sequentially:

| Template | GPUs | Disk | Vacant-host validation | Final safe state |
| --- | ---: | ---: | --- | --- |
| Small research job | 1 | 20 GB | Container saw one A100-SXM4-40GB with 40,960 MiB | `actual_status=exited`, `intended_status=stopped`, `cur_state=stopped` |
| Full-node research job | 2 | 20 GB | Container saw GPU indices 0 and 1, both A100-SXM4-40GB with 40,960 MiB | `actual_status=exited`, `intended_status=stopped`, `cur_state=stopped` |

Both records reported `is_bid=false`. Start each template once while vacant, validate the GPU count from inside its container, then stop it and poll the exact record until all three stopped-state fields match. Do not run the 1-GPU and 2-GPU templates together. A stopped template retains disk and does not reserve its GPU.

The owner GPU charge was zero on the owner's own host, but each retained 20 GB disk cost about $0.00556/hour on the client account. The Instances page warned that the stopped records could be deleted when the client balance reached zero. Maintain explicit client-credit headroom for every standby or destroy standbys that are no longer needed; owning the host does not make retained instance storage balance-free.

Store the exact IDs, labels, machine association, GPU count, offer association, and raw state fields only in the private operations environment. The repository should contain placeholders and validation rules, never live identifiers.

The final standby preparation first attempted a `10/10` listing input pair; the API returned HTTP 422. Reusing the known accepted host-side `price_gpu=5.84` and `price_min_bid=3` preparation shape succeeded and exposed the exact on-demand offer needed for the owner record. This does not identify a documented maximum. Preserve the response body, keep the host vacant, and prove the accepted live fields instead of interpreting CLI syntax acceptance as a listing postcondition.

### `--cancel-unavail` false-ownership bug

On this host, both fresh owner on-demand creates attempted with `--cancel-unavail --raw` exited with shell status 0 while returning an error object: HTTP 400 and server error 403/3586 claimed that the offer was not the host's own. The claim was false: the offer's host identity matched the authenticated owner, and the same failure occurred for the 1-GPU and 2-GPU own offers.

Repeating each create **without** `--cancel-unavail` succeeded immediately; both instances fully booted and passed the checks above. The safe workaround is limited to vacant-host standby preparation:

1. Validate the authenticated identity and the exact on-demand offer ownership.
2. Submit the create with a unique owner label.
3. Inspect the response body as well as the process exit code. Treat `error: true` as failure even when the CLI exits 0.
4. Query instances by exact label and confirm the failed call created nothing.
5. While the host is still vacant, retry once without `--cancel-unavail`.
6. Record the returned instance immediately, validate it, and stop it to the full safe-state tuple.

Do not turn this workaround into an automatic create retry while an outside renter is active. Reclaim should start one exact, pre-created standby and fail closed on any identity or state mismatch.

## Earlier one-GPU cheap-trial listing and price semantics

During an earlier vacancy-only pricing check, the host was sliced with `min_chunk=1`, reserved discounts disabled, volume offers disabled, and a fixed short end boundary. The host-side settings were:

| Component | Host setting | Renter-visible result |
| --- | ---: | ---: |
| Interruptible minimum, per GPU-hour | **$0.225** | **$0.3000** |
| On-demand GPU, per GPU-hour | **$5.84** | **$7.7866667** |
| Storage, per GB-month | **$0.15** | **$0.20** |
| Upload bandwidth | **$39.99/TB** | **$53.32/TB** |
| Download bandwidth | **$2.00/TB** | **$2.6667/TB** |

For the CLI, the bandwidth values are per GB, so the corresponding listing arguments are `--price_inetu 0.03999` and `--price_inetd 0.002`. The core listing shape is:

```bash
vastai list machine <MACHINE_ID> \
  --price_gpu 5.84 \
  --price_min_bid 0.225 \
  --price_disk 0.15 \
  --price_inetu 0.03999 \
  --price_inetd 0.002 \
  --discount_rate 0 \
  --min_chunk 1 \
  --end_date <FIXED_SHORT_END> \
  --vol_size 0
```

The live search result confirmed the current conversion: the renter saw four-thirds of the host setting, while the host floor remained the amount the host intended to earn. Do not subtract another 25% from the host figure when modelling revenue. Always verify both the host record and renter-visible search result after listing; do not assume the conversion or unit labels will remain unchanged.

Those renter-visible figures came from **one-GPU slice offers** because this listing used `min_chunk=1`. For a multi-GPU bid offer, raw search field `min_bid` is the total for the whole offered machine per hour, not a per-GPU amount. Convert a sampled multi-GPU machine total back to host `price_min_bid` with the live surcharge factor and GPU count before relisting; do not multiply `min_bid` by GPU count.

The listing initially used a $0.26 host floor, about $0.3467 renter-facing. With the machine still vacant, it was reduced to $0.225 host-side and verified at exactly $0.3000 in renter search. These were quick-fill trial prices, not a production claim that bandwidth covers provider egress or that $0.225 is a durable market floor. Re-sample comparable A100 interruptible offers before each future listing and reprice only future acceptance; changing the minimum bid does not evict an existing contract.

For the final owner-standby pilot, the sampler found **17** comparable offers. The renter-facing whole-pair P10 was **$0.7466667/hour**, mapping to a **$0.28/GPU-hour** host interruptible floor under the observed four-thirds conversion. The outside on-demand deterrent remained **$5.84/GPU-hour** host-side and appeared as **$15.5733/hour** for the renter-visible pair; reserved discount was zero. Use these as the timestamped final-test inputs only.

## Final controlled two-account test

The final acquisition used a separate funded client account, a reviewed
digest-pinned image, a 10 GB instance disk, one exact two-GPU bid offer, and a
whole-machine bid just above the accepted floor. The host was unlisted as soon
as the exact controlled instance reached `running/running/running`. No unknown
renter was accepted.

### Acquisition behavior

The controlled acquisition work exposed several scheduler/API boundaries:

- The general no-host-instance guard had to admit the intentionally prepared owner standby. The final rule allowed exactly one configured ID and label only after proving exact machine, `is_bid=false`, two GPUs, and the safe stopped-state tuple. Any additional or malformed target record still aborted acquisition.
- Bid and on-demand search views flickered independently during propagation.
  The final helper required one exact on-demand proof, then 30 seconds of
  continuous stability for the exact bid offer immediately before one create
  call. Any empty sample reset the stability clock.
- A two-hour-plus fixed-end ask became visible, but the create returned
  structured HTTP 400 `no_such_ask`; both account inventories proved that no
  contract was created. Twelve-hour fixed-end asks later launched. Vast
  publishes no minimum launchable horizon or offer-propagation SLA, so this is
  an observation rather than a required duration.
- Once the controlled bid was active, the bid view's `min_bid` moved from the
  listing floor to the accepted active bid. The controller had to distinguish
  the original floor from that running-contract value.
- `vol_size=0` prevented a separate volume offer. The 10 GB client disk and
  hard 250 GB XFS Docker filesystem provided the actual storage limits.

### Clean Host Job attempts

An earlier mixed sequence appeared to fan the Host Job into two one-GPU records
and pause the controlled client, but it also contained a malformed container
launch and other state changes. It is not clean evidence of a supported or
repeatable handoff.

The corrected harness then ran three clean attempts:

| Attempt | High Host Job input | Reclaim timeout | Result |
| --- | ---: | ---: | --- |
| 1 | $1.10/GPU-hour | 30 seconds | Controlled renter stayed running; owner jobs did not take the GPUs. |
| 2 | $1.30/GPU-hour | 90 seconds | Controlled renter stayed running; owner jobs did not take the GPUs. |
| 3 | $3.00/GPU-hour | 120 seconds | Controlled renter stayed running; owner jobs did not take the GPUs. |

No clean attempt reached owner dwell, release, or automatic renter return. The
earlier 79-second return failure belongs to the confounded sequence and must not
be presented as though clean reclaim first succeeded.

Vast's [`set defjob`](https://docs.vast.ai/cli/reference/set-defjob) reference
describes a background job and a per-GPU price input. It does not document
price as a preemption lever, a Host Job reclaim SLA, or a rating-safe handoff.
The [instance-type guide](https://docs.vast.ai/guides/instances/choosing/instance-types)
documents that client interruptibles may pause when outbid by another
interruptible or displaced by on-demand. That does not establish an owner's
right to evict with a Host Job.

### Exact owner on-demand standby pilot

The final test used the scheduler class Vast documents as higher priority. Its sequence was:

1. While vacant, create and validate one exact host-account, own-machine, two-GPU on-demand standby; stop it to the full safe-state tuple.
2. Configure controlled acquisition to tolerate only that exact standby, then publish the P10 interruptible offer for a bounded window.
3. From the separately authenticated controlled account, acquire one exact full-machine interruptible with a reviewed image and 10 GB disk.
4. Prove the renter `running/running/running`, unlist immediately, and prove bid and on-demand offers absent.
5. Pin original reliability `0.5999925`; because the live value was already `0.5727243`, require the explicit degraded-disposable diagnostic override.
6. Unlist and prove absence again before takeover, then start only the exact on-demand standby.
7. Observe the controlled renter in the safe-stopped tuple and exact owner `running/running/running` **82.281 seconds** after the research decision.
8. Stop and retain the exact owner. The same controlled interruptible returned automatically; no fallback Start was issued.
9. Unlist and prove absence before destroying the exact controlled renter. Final reconciliation showed no contracts and no bid/on-demand offers.

There was no host service stop, Docker restart, container kill, reboot, maintenance action, or minimum-bid eviction. A separate post-pilot probe on the retained standby proved a real two-GPU PyTorch CUDA workload, then the owner returned to stopped. Keep that workload proof separate from the 82.281-second scheduler timing.

### Reliability result and production gate

Reliability began at **0.5999925**, briefly reported **0.599997**, and fell to
**0.5727243** during the restart/new-client sequence before the clean Host Job
attempts. This is an absolute drop of about **0.02727**. The exact cause cannot
be isolated from the available evidence, but the full workflow plainly did not
make reliability rise.

All three clean failed attempts were flat at **0.5727243** at their immediate
checkpoints, including the final corrected attempt. Because they did not
preempt the renter, that flat value proves only that those failed attempts
caused no further immediate measured drop. It does not prove that a successful
handoff would be rating-safe.

The later successful owner-standby handoff also measured **0.5727243**
immediately before takeover, immediately afterward, and after cleanup. That is
useful evidence that no additional immediate change was observed, but it is
still below immutable original **0.5999925**. The controller therefore labels
the run a degraded diagnostic and never production-ready. The planned delayed
checkpoint was skipped when the disposable host reached its preconfigured
automatic-deletion deadline, so delayed rating safety remains unknown.

A final post-cleanup read-only qualification sample later reported
**0.5727207**, no machine error or report, **4200.4 Mbps download**, and only
**161.9 Mbps upload**. The current verification minimum is 500 Mbps in both
directions, so this host could not qualify regardless of the handoff result.
The tiny movement from 0.5727243 is an observation, not an attributable
handoff penalty.

Reliability is computed by Vast, not written by the controller. Vast says a new
machine's score grows while it stays stable and online, typically reaching 90%
within a few days. The correction is therefore to stop rating-sensitive
mutations, keep the host healthy and connected, and let the platform observe
stable service. The script has no API to raise the score.

The official qualification path is to keep the new machine dedicated, avoid
personal background workloads during verification, run the ordinary self-test
once while vacant, satisfy the 500 Mbps symmetric network minimum, and preserve
stable service while reliability matures strictly above 90%. The relaxed test
used here could not promote the machine.
Vast says new-machine reliability starts low and grows with stable uptime, so
the restart is a plausible explanation for the earlier decrease, but this
trial cannot prove attribution. Its verification page also says personal
workloads can fail verification while host responsibilities direct work
through Jobs or `create job`. Get Vast's written interpretation before using
the own-machine standby for continuing Sqwish research work.

Sqwish's production gate for near-instant owner reclaim and rating-safe handoff
is **BLOCKED** despite the single technically successful cycle. Repeat on the
dedicated box with original-baseline and delayed observations before changing
the production modes:

1. list GPUs that researchers explicitly release for the whole contract window;
2. unlist and drain every locked contract before owner use; or
3. reserve enough capacity for research bursts and sell only surplus GPUs.

## Keep for the dedicated-box golden path

- Run marketplace hosting only on dedicated physical capacity with the required provider permission.
- Give Docker a dedicated, quota-enabled XFS disk and set its physical size before installation.
- Validate JSON bodies and postconditions because a CLI process can exit zero for an API error.
- Treat relaxed self-test success as diagnostic hardware evidence, not verification.
- Avoid reboots and address changes after registration; maintain steady uptime while reliability matures.
- Treat bid/on-demand offer visibility as eventually consistent and require continuous exact-offer stability immediately before a single create.
- Classify structured `no_such_ask` as a definite no-contract result only after both account inventories agree; never blindly retry an uncertain create.
- Keep Host Job testing bounded and diagnostic. Do not respond to a timeout by repeatedly increasing price.
- Reuse the exact pre-created on-demand standby path that completed in 82.281 seconds; never weaken its exact identity, stopped-state, unlist, outside-contract, or cleanup gates.
- Keep production owner preemption disabled until repeated dedicated-box cycles prove reclaim, automatic return, original-baseline reliability, and delayed rating behavior, and Vast clarifies personal research work versus Jobs.
