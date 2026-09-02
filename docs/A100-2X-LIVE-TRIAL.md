# Two-A100 live hosting trial

This note records the reusable parts of the 2× NVIDIA A100-SXM4-40GB qualification trial run on 2 September 2026. It intentionally excludes provider resource names, zones, addresses, account and project identifiers, machine and contract IDs, SSH paths, and all credentials.

## Status at a glance

| Claim | Status | Evidence |
| --- | --- | --- |
| A fresh on-demand 2× A100 host can be installed without touching an existing research worker | **Proved** | A separate 2-GPU trial node was provisioned, both GPUs were visible, and the Vast host services remained healthy. |
| Docker storage can be physically bounded away from the root filesystem | **Proved** | `/var/lib/docker` was mounted from a dedicated 250 GB XFS disk with project quotas enabled. |
| The two GPUs and their interconnect pass Vast's workloads | **Proved diagnostically** | The relaxed self-test passed ResNet18, ECC, 2-GPU NCCL, and the simultaneous CPU/GPU burn. The run explicitly did not qualify the new host for verification. |
| One-GPU and two-GPU owner jobs can be prepared in advance | **Proved while vacant** | Both on-demand standbys booted, saw the intended GPU count, and returned to a safe stopped state with their 20 GB disks retained. |
| A separate-account interruptible can be reclaimed and returned without operator intervention or rating risk | **Failed the production gate** | Host Job reclaim paused the controlled client and ran owner work, but release did not auto-resume the client after more than 79 seconds. A client-side Start was required, and reliability fell after a malformed first owner launch. |

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

## Final controlled two-account reclaim test

The separate client account was funded with **$10** before the host was listed. It acquired the exact controlled two-GPU interruptible offer with a **$1.61 whole-machine hourly bid**, just above the offer's **$1.60 whole-machine `min_bid`**. The instance used the reviewed `vastai/test:self-test-cuda-13.0` image and a 10 GB disk.

The public listing existed for **13.303551 seconds**. As soon as the exact controlled contract was confirmed, the host was unlisted. No unknown renter or contract appeared. The controlled workload reached 100% utilization on both A100s and used about **36,277 MiB on each GPU**.

The final offer reported null `duration` and `end_date`, so this acquisition missed the runbook's required fixed-end listing guard. Immediate controlled acquisition and unlisting limited this run, but it is still a procedure deviation. A dedicated-hardware repeat must set and verify the fixed end before any listing becomes visible.

The corrected market sample contained seven unique 2×A100-SXM4-40GB machines. Bid-offer `min_bid` values were renter-facing whole-machine totals: **$0.80 minimum, $1.066667 median, and $1.60 P95/P99/maximum per two-GPU machine-hour**. At the observed four-thirds renter surcharge, a $1.60 renter-facing P99 maps to a host listing floor of **$0.60 per GPU-hour**:

```text
host price_min_bid per GPU-hour = renter machine-total floor * 0.75 / GPU count
                                    = $1.60 * 0.75 / 2
                                    = $0.60
```

The client's `--bid_price` is also a whole-machine hourly total. Treating search-result `min_bid` as per-GPU and multiplying it by GPU count is wrong.

### Measured Host Job behavior

The Host Job definition fanned out into **two independent one-GPU jobs**, one for each physical GPU. It did not form one atomic two-GPU owner job. The observed phases were:

| Phase | Host Job setting | Renter-facing job price | Result |
| --- | ---: | ---: | --- |
| Below controlled client | $0.65/GPU-hour | $0.866667/hour for each 1-GPU job | Did not preempt the $1.61/hour two-GPU client contract. |
| Above controlled client, malformed command | $1.30/GPU-hour | $1.733333/hour for each 1-GPU job | Once the machine was listed, both jobs displaced the client, but their containers failed because `-lc` was treated as the executable. |
| Above controlled client, corrected command | $1.30/GPU-hour | $1.733333/hour for each 1-GPU job | Both one-GPU owner containers started and each completed `gpu_burn` successfully, using about 36 GB on its card. |
| Release | $0.46/GPU-hour | Below the controlled client | Owner allocation released, but the controlled client did not auto-resume. |

In this observed scheduler path, each one-GPU Host Job had to outbid the **whole-machine** price of the two-GPU interruptible contract. Half of the renter's whole-machine bid was insufficient. Re-derive this behavior on every Vast scheduler version and GPU topology rather than assuming that one-GPU jobs compare against a per-GPU share.

Host Jobs also required an **active machine listing** to schedule. Raising the job while the machine was unlisted did not reclaim the GPUs. After listing at **05:06:09.757Z**, the controlled client was stopped and both owner job records were running by **05:06:12.579Z**, about **2.82 seconds** later. Relisting reopens public acquisition risk, so reconcile the exact contract inventory immediately before and after every scheduler mutation.

The first owner launch used malformed image arguments: the argument list began with `-lc`, which Docker treated as an executable. Both owner container starts failed. A Host Job command using this test image must include the shell explicitly:

```bash
vastai set defjob <MACHINE_ID> \
  --price_gpu <HOST_JOB_PRICE_PER_GPU_HOUR> \
  --image vastai/test:self-test-cuda-13.0 \
  --args /bin/bash -lc '<REVIEWED_WORKLOAD>'
```

After correcting the arguments, the machine was relisted at **05:08:27.202Z**. Both owner containers started at **05:08:49Z**, saw one A100 each, and completed the bounded burn with zero reported burn errors.

### Release and client return

The Host Job was lowered to **$0.46/GPU-hour at 05:09:51.906Z**. The controlled client remained stored/stopped and did not auto-resume after more than **79 seconds**. A normal client-side Start was submitted at **05:11:11.511Z**. Its scheduler state reached `cur_state=running` at **05:11:14.886Z**, about **3.37 seconds** later; `actual_status=running` and 100% utilization on both GPUs were confirmed by **05:12:21Z**.

Automatic return therefore failed in this tested Host Job path. A controller for a separately controlled client must include an exact-instance client-side Start fallback and verify application health, not merely scheduler state. That fallback is unavailable to the host for an unrelated renter, so unattended public hosting does not meet the research team's seamless hand-back requirement on this evidence.

### Reliability result and production gate

Reliability fell from **0.5999925** to **0.5727243**, an absolute drop of **0.0272682** and about **4.54% relative**, after the malformed first owner launch. No renter report appeared. Reliability remained at 0.5727243 through the corrected reclaim and release cycle.

The measurement does not isolate whether the drop came from the failed owner containers, preemption itself, or a delayed platform update. It does prove that this end-to-end sequence cannot be called rating-safe. Do not claim that interruptible status grants penalty-free host eviction. A dedicated-box production rollout remains blocked until a clean, correctly configured cycle preserves reliability through immediate and delayed checks and Vast confirms the intended scheduler behavior.

### Cost and teardown

Direct Vast client spend was **$0.10394347623**, leaving **$9.89605652377** of API credit. This excludes the cloud provider cost of the temporary host.

The controlled contract was destroyed; temporary client API and SSH keys were revoked; the host was unlisted; the default Host Job was removed; and the Vast machine record was deleted. The exact disposable cloud VM, attached disks, static address, and trial firewall rule were also deleted. No production or unrelated cloud machine was part of the teardown.

## Keep for the dedicated-box golden path

- Run marketplace hosting and unknown-tenant tests only on the dedicated physical box. Use disposable third-party cloud capacity only with the provider's prior written approval, for operator-controlled qualification with a reviewed workload and a seconds-long acquisition window.
- Give Docker a dedicated, quota-enabled XFS disk and set the physical size before installation.
- Reserve owner template disks while vacant, fund their retained storage, and prove each exact stopped record still exists immediately before listing.
- Validate JSON bodies and postconditions because the CLI can exit 0 for API errors.
- Treat relaxed self-test success as hardware evidence, not verification.
- Compare host-entered per-GPU prices with renter-visible whole-machine prices after every listing change.
- Pass Host Job image arguments as `/bin/bash -lc '<workload>'`; run the reviewed job while vacant before relying on it for reclaim.
- Keep the machine actively listed when testing Host Job scheduling, and treat every relist as a fresh public acquisition window.
- On the observed two-GPU shape, price each one-GPU Host Job above the renter's whole-machine bid if reclaim is intended. Re-measure this comparison on the four-GPU box.
- Require a client-side Start fallback and application-level health check after owner release. Do not assume a public renter will resume automatically.
- Keep production owner preemption disabled while the rating gate fails. Repeat a clean cycle and collect delayed reliability observations before enabling it.
