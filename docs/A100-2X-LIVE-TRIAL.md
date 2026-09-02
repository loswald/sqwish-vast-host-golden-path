# Two-A100 live hosting trial

This note records the reusable parts of the 2× NVIDIA A100-SXM4-40GB qualification trial run on 2 September 2026. It intentionally excludes provider resource names, zones, addresses, account and project identifiers, machine and instance IDs, SSH paths, and all credentials.

## Status at a glance

| Claim | Status | Evidence |
| --- | --- | --- |
| A fresh on-demand 2× A100 host can be installed without touching an existing research worker | **Proved** | A separate 2-GPU trial node was provisioned, both GPUs were visible, and the Vast host services remained healthy. |
| Docker storage can be physically bounded away from the root filesystem | **Proved** | `/var/lib/docker` was mounted from a dedicated 250 GB XFS disk with project quotas enabled. |
| The two GPUs and their interconnect pass Vast's workloads | **Proved diagnostically** | The relaxed self-test passed ResNet18, ECC, 2-GPU NCCL, and the simultaneous CPU/GPU burn. The run explicitly did not qualify the new host for verification. |
| One-GPU and two-GPU owner jobs can be prepared in advance | **Proved while vacant** | Both on-demand standbys booted, saw the intended GPU count, and returned to a safe stopped state with their 20 GB disks retained. |
| A genuine outside interruptible renter is paused by an owner start, resumes after owner stop, and causes no reliability penalty | **Pending** | No outside renter reclaim cycle had completed when this note was written. Do not infer this from the vacant-host tests or a same-account control. |

## Disposable on-demand host

Use a separate test VM. Do not retrofit a running research worker for a marketplace experiment.

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

The new machine reported reliability **0.5999925**, effectively Vast's 60% starting value. The ordinary self-test preflight refused to continue because it required reliability above 0.9. The diagnostic run was therefore started with:

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

## Final cheap-trial listing and price semantics

The host was sliced with `min_chunk=1`, reserved discounts disabled, volume offers disabled, and a fixed short end boundary. The final host-side settings were:

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

## Controlled follow-up evidence on the full two-GPU bundle

A same-day follow-up prepared the controlled two-account reclaim path without admitting an unknown renter. The machine stayed unlisted except for the brief owner-standby creation window, when its on-demand price was set to a deterrent and its interruptible floor was above the sampled market. No outside contract appeared.

The current official self-test again completed successfully in relaxed mode: system checks, ResNet18, ECC, two-GPU NCCL, and the simultaneous 60-second CPU/GPU burn all passed. Vast destroyed the temporary test instance and unlisted the machine. Reliability remained **0.5999925**, verification remained **unverified**, and the machine reported no error or renter report. The self-test result callback returned `Invalid User`, so the local test evidence is authoritative for hardware health but does not prove a platform verification update.

A new full-node owner on-demand instance then ran the official Vast test image with `gpu_burn 15` in a loop. Inside the container it saw both physical A100 UUIDs. Host telemetry measured both GPUs at 100% utilization, about 36.3 GB VRAM each, roughly 300 W each, and 55-58°C. The burn reported zero errors and about 17.7-19.1 TFLOP/s per GPU. The owner instance stopped to the required tuple `actual_status=exited`, `intended_status=stopped`, `cur_state=stopped`; both GPUs returned to 0% utilization and 0 MiB allocated.

That stopped owner record later disappeared before the controlled-client phase. The exact cause was not isolated: the host account had almost no client credit, the retained disk had a nonzero hourly charge, and a Host Job definition was added during the interval. Do not assume a free own-machine standby will persist. Fund the host account's client side, record the retained instance repeatedly, and prove it still exists immediately before admitting the controlled renter. If it disappears, abort rather than creating a replacement while occupied.

The low-priority Host Job produced **two independent one-GPU bid records**, one for each physical GPU, rather than one atomic two-GPU job. With the machine unlisted and the job below the stored machine floor, both records remained inert at `actual_status=loading`, `intended_status=stopped`, `cur_state=unloaded`; no job container ran. This proves the current Host Job definition fans out per GPU on this host, but it does not yet prove selective preemption or automatic resume.

The fresh comparable sample contained seven unique 2×A100-SXM4-40GB machines. Bid-offer `min_bid` values were whole-machine totals: **$0.80 minimum, $1.066667 median, and $1.20 P95/P99/maximum per 2-GPU machine-hour**. At the observed four-thirds renter surcharge, the matching host listing input is **$0.45/GPU-hour**, and a controlled client's `--bid_price` must be just above **$1.20 for the machine**. An earlier sampler mislabeled `min_bid` as per-GPU and doubled it; that calculation was wrong and has been removed from the runbook.

The controlled outside-client cycle did not start because the separate client account remained unfunded. The machine was never opened at the final P99 floor, no unknown tenant was admitted, and no reclaim or rating-immunity conclusion follows from this attempt. Future runs must complete client authentication, payment, SSH key, reviewed image, and exact create command before the host listing window opens.

## Outside-renter reclaim test still required

The trial has proved vacant-host installation, multi-GPU qualification, storage isolation, price display, and reusable owner templates. It has **not** yet proved the user-critical behavior: a genuine outside interruptible tenant being paused and resumed by the owner without damaging host reliability.

Complete the evidence in this order:

1. Wait for one or preferably two genuine outside bid contracts. Confirm in the host Contracts view that none is on-demand or reserved.
2. Let the renter run for the chosen 30-60 minute observation window. Capture reliability, verification, daemon health, contract state, GPU assignment, disk use, and network counters.
3. Start the exact pre-created 1-GPU owner standby. Measure whether one bid tenant becomes platform-paused while the other GPU continues serving.
4. Stop that owner standby, poll its safe stopped-state tuple, and measure automatic renter resume time.
5. With the 1-GPU owner safely stopped, start the exact 2-GPU standby. Measure whether both interruptible allocations pause cleanly.
6. Stop the 2-GPU owner, measure both resumes, and recheck health.
7. Record reliability and verification immediately, after the platform's delayed update, and again after a longer observation window.

Use only Vast scheduler actions on the exact owner standbys. Do not kill tenant containers, restart Docker, stop the host daemon, reboot the VM, or unlist as a substitute for reclaim. Unlisting prevents new rentals; it does not prove or trigger clean preemption of an existing renter.

A same-account bid/on-demand conflict is not accepted evidence. Prior control attempts produced a GPU-conflict response and never exercised priority over a genuine outside contract. Until the sequence above completes, the only accurate rating conclusion is **unknown**: neither “no penalty” nor “safe to evict” has been demonstrated.

## Keep for the dedicated-box golden path

- Give Docker a dedicated, quota-enabled XFS disk and set the physical size before installation.
- Reserve owner template disks while vacant; keep one exact 1-GPU and one exact full-node standby.
- Validate JSON bodies and postconditions because the CLI can exit 0 for API errors.
- Treat relaxed self-test success as hardware evidence, not verification.
- Compare host-entered and renter-visible prices after every listing change.
- Prove reclaim with an outside interruptible renter and delayed reliability checks before enabling unattended owner preemption.
