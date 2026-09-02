# Inference alternatives for the 4x RTX PRO 6000 host

**Source review date:** 2 September 2026

**Hardware in scope:** one physical Linux host with four NVIDIA RTX PRO 6000 Blackwell Workstation Edition GPUs, 96 GB each
**Decision scope:** whether selling API inference is a cheaper, more flexible use of idle capacity than the Vast interruptible-rental path in this repository

## Decision

Selling inference is technically credible, but no reviewed marketplace offers all of the properties required for frictionless research sharing:

1. accept this third-party workstation;
2. bring paid demand rather than requiring the operator to find customers;
3. pay for short requests or jobs;
4. let the supplier reclaim any GPU immediately; and
5. impose no lost payment, qualification, availability, or reputation cost.

The central misconception is that **request-level inference automatically creates supplier-level preemptibility**. It does not. A model server may accept short HTTP requests, but the marketplace still sells a dependable worker or lease to its customers. It may keep that worker warm between requests, require it to finish long generations, score its latency and availability over an epoch, or withhold payment when it disappears during a job.

For this host, fixed separation is the lowest-risk inference experiment: expose one physical GPU to a paid service and keep three for research. Expand only after a 30-day pilot measures paid utilization, net payout, platform consequences, and interference with research. Rapidly cycling all four GPUs between public serving and private work is not yet an evidence-backed operating model.

This note uses public primary sources maintained by the platform or protocol operator. Eligibility, price, demand, emissions, and terms can change. A public price is not evidence of fill, and none of the reviewed sources provides a defensible occupancy forecast for this exact host.

## Request, worker, and supplier are different layers

```text
buyer request -> public endpoint/queue -> model worker -> supplier capacity contract
```

- A request may finish quickly, but a long output, tool call, batch, or stream may run for minutes.
- An endpoint can stop routing new work while the current worker remains committed to finish accepted work.
- A serverless control plane can scale workers per request while still paying the underlying supplier by GPU time.
- A protocol can route requests per token while scoring the supplier over a week and zeroing rewards after an availability failure.

An operator-controlled admission gate is useful only when the marketplace contract also permits the worker to leave. The platform evidence below determines whether that is true.

## Comparison

| Platform | Can an outside owner earn with this box? | Supplier payment | Reclaim and interruption semantics | Per-GPU offering | Fit as of 2 September 2026 |
| --- | --- | --- | --- | --- | --- |
| Vast marketplace | Yes, subject to host setup and verification | Host-set GPU-hour, storage, and bandwidth rates | Existing contracts remain binding after unlisting; offline service lowers reliability. Vast interruptible is buyer bidding, not a supplier right to preempt. | Yes, physical GPU granularity with `min_gpu=1` | Practical capacity market; not request-paid inference |
| Vast Serverless | Only through an ordinary Vast host listing underneath the service | Underlying instances are billed by time while Loading and Ready | Endpoint owner controls autoscaling; host obligations remain those of the underlying marketplace contract | Deployment can select GPU type/count; host allocation still follows marketplace instances | Buyer-side autoscaler, not a separate queue-worker supplier programme |
| RunPod | No for a new Community Cloud supplier | Not applicable to a new outside host | RunPod Everywhere manages private owned inventory, but its public page describes serverless on that inventory as roadmap | Customer endpoints can request a GPU count; that does not enroll the local workstation | Not an available monetisation route |
| Salad | Possibly, if the client accepts the card and demand exists | Variable Salad Balance from assigned workloads | The desktop client can pause all jobs and free hardware; job supply and earnings are not guaranteed | Separate paid container work per physical GPU is not documented | Easiest pause UX; exact-card and four-GPU economics unconfirmed |
| Nosana | Not for this four-GPU topology under current requirements | NOS for GPU-use time/jobs | A host need not stay online while waiting, but more availability yields more jobs; completion is the documented reward point | No: docs say one GPU per PC and one private key per GPU | Current topology and supported-device mismatch |
| Akash | Yes; the provider market is open and permissionless | Provider-set ACT price per block, settled from lease escrow; AKT funds bids and fees | Closing a lease permanently terminates the tenant workload. Optional reclamation uses a negotiated grace period with a current one-hour minimum. | Yes, manifests can request one or more physical GPUs | Open capacity market with substantial Kubernetes/network operations; not subsecond reclaim |
| TensorDock | Yes after supplier vetting | Supplier-set resource prices less the contract fee | Supplier standard is 99.99% uptime with advance maintenance; no owner-preemption mechanism is documented | Customer VMs are GPU-granular; independent owner reclaim is not promised | Exact card has appeared in the live market, but normal VM rental is inflexible |
| Bittensor, especially engy SN53 | Potentially after subnet-specific registration and qualification | Normalised on-chain emissions influenced by paid token volume, not a fixed cash pass-through per request | SN53 applies weekly success, latency, and proof gates; a failed gate can zero that miner-model score and require requalification | Multiple workers/serve URLs can be pooled; there is no simple public price/listing for each card | Closest reviewed API-inference market; high operational, qualification, and token risk |
| io.net | Not currently: the supported list omits the exact workstation card | IO rewards, with worker fee, staking, and slashing mechanics | An available high-end worker must remain below the utilisation ceiling; loss of availability during a job can forfeit payment | Independent reclaim/listing of four GPUs on one workstation is not established | Current eligibility and co-use rules make it a poor fit |
| Petals | It can contribute compute, but there is no commercial supplier programme | No cash or priority-credit payment documented | Peer churn is part of the design, but it is a volunteer research network | Hosts model blocks rather than paid GPU units | Not a monetisation option |

## Platform evidence

### Vast marketplace and Vast Serverless

Vast accepts third-party physical hosts. Its [hosting overview](https://docs.vast.ai/host/hosting-overview) says hosts set GPU, storage, and bandwidth pricing, should plan for 100% uptime during a rental, may not use rented hardware for another purpose, and must honour the locked terms through each rental end date. Unlisting prevents new contracts but leaves existing ones unchanged. A multi-GPU host can set `min_gpu=1`, allowing clients to rent individual physical GPUs under independent contracts.

Vast interruptible instances do not give the supplier an arbitrary pause button. They use a bidding system in which only the highest interruptible bid runs, and a higher-priority on-demand instance stops an interruptible. The controlled owner-reclaim experiment elsewhere in this repository uses that scheduler hierarchy; it is not a general contractual right to take a rented worker offline.

[Vast Serverless](https://docs.vast.ai/guides/serverless) is an endpoint and autoscaling product for the buyer. The [serverless pricing documentation](https://docs.vast.ai/guides/serverless/pricing) says the endpoint account pays the underlying instances, including workers in Loading and Ready states. A Vast host may supply one of those marketplace instances, but the host is still paid under the ordinary capacity contract. There is no documented programme in which a local daemon polls a request queue and receives a per-token or per-job supplier payout.

The current public Vast sources are inconsistent about platform fees: the [June 2024 product update](https://vast.ai/article/june-2024-product-update) describes 0% hosting fees with a buyer-side surcharge, while an [older public FAQ](https://console.vast.ai/faq/) still contains 75/25 host-share language. Use the live hosting agreement and actual payout record before putting a fee into a forecast.

**Uncertainty:** Serverless may improve demand for the underlying market, but public sources do not disclose exact-card worker fill or the probability that this host is selected.

### RunPod

RunPod's current [Pod documentation](https://docs.runpod.io/pods/choose-a-pod) says it is no longer accepting new Community Cloud hosts. RunPod Serverless is therefore not an enrollment route for this workstation. The [endpoint API](https://docs.runpod.io/api-reference/endpoints/POST/endpoints) may offer RTX PRO 6000 Workstation Edition capacity to customers, but that inventory is supplied by RunPod's available cloud rather than a newly attached local worker.

[RunPod Everywhere](https://www.runpod.io/everywhere) is a control plane for an organisation's owned infrastructure. Its public page describes serverless workloads on that inventory as roadmap functionality, and its pricing is paid by the infrastructure owner. It does not create third-party revenue.

**Conclusion:** the proposed “RunPod worker stops polling, frees VRAM, then resumes earning” model is not currently available to a new supplier.

### Salad

Salad is the closest reviewed product to a consumer-style opportunistic worker. Its [pause guidance](https://support.salad.com/guides/getting-jobs/close-games-and-other-programs/) says Pause Temporarily or indefinite pause stops all jobs and frees the hardware. The supplier receives Salad Balance, but [earnings vary by assigned workloads](https://support.salad.com/faq/jobs/how-does-my-machine-earn-salad-balance/), and the platform says [container jobs are not guaranteed](https://support.salad.com/faq/jobs/how-do-i-get-container-jobs/). Reliability, hardware suitability, and demand affect job assignment.

The exact RTX PRO 6000 Workstation Edition is not named in Salad's current public customer GPU catalogue. The [multi-GPU documentation](https://support.salad.com/faq/salad-app/how-salad-selects-coins-to-mine/) reviewed covers mining: Salad selects one native GPU, while same or similar cards may participate in a single miner process. It does not document four independently paid container workers on one workstation.

**Uncertainty:** the client must be installed to establish whether this exact card and Linux/Windows configuration is accepted, whether paid container work uses all four GPUs, and what the net cash-equivalent payout is. Treat it as a compatibility experiment, not an ROI assumption.

### Nosana

Nosana's [host requirements](https://learn.nosana.com/hosts/grid.html) list supported NVIDIA GPUs but do not list the RTX PRO 6000 Blackwell Workstation Edition. They also state **one private key per GPU and one GPU per PC**, which conflicts directly with this four-card workstation.

The [provider page](https://nosana.com/gpu-providers/) describes NOS payment for each second a GPU is used. The [host queue documentation](https://learn.nosana.com/hosts/grid-run.html) says a node does not need to stay online continuously, but more uptime increases the chance of receiving work and market demand may be insufficient. The [job lifecycle](https://learn.nosana.com/deployments/jobs/job_execution_flow) reaches reward after successful execution.

**Uncertainty:** the reviewed official docs do not specify a separate rating or slashing rule for an abruptly abandoned active job. They also provide no exception to the one-GPU-per-PC rule. Nosana should be excluded unless its published requirements change.

### Akash

Akash explicitly describes an [open, permissionless provider marketplace](https://akash.network/docs/providers/getting-started/should-i-run-a-provider/). Providers set prices and receive ACT for active leases. Current setup guidance also calls for AKT bid escrow, bid fees, lease deposits, a reliable 100+ Mbps connection, and ongoing Kubernetes/provider maintenance.

The [provider and lease model](https://akash.network/docs/learn/core-concepts/providers-leases/) pays per block, approximately every six seconds, while a lease is active. Providers compete on price, performance, reliability, and location. GPU capabilities are advertised as provider attributes. The [GPU deployment format](https://akash.network/docs/learn/core-concepts/gpu-deployments/) permits `gpu.units: 1` or a larger count, so the four physical cards can be allocated individually.

A provider may [close a lease](https://akash.network/docs/providers/operations/lease-management/), but closure is a permanent tenant termination rather than pause/resume. Optional [capacity reclamation](https://akash.network/docs/providers/setup-and-installation/kubespray/reclamation/) requires tenant and provider policy agreement and currently uses a one-hour minimum grace period.

**Uncertainty:** a provider can advertise this exact GPU model without waiting for a central allowlist, but public sources do not show buyer demand for the new attribute or a fill rate. Closing leases for private research would damage the provider's practical reputation even where an automatic slash is not documented.

### TensorDock

TensorDock accepts vetted third-party suppliers. Its [supplier FAQ](https://console.tensordock.com/faq) describes provider application, resource pricing, and monthly bank payout mechanics. TensorDock's [public site](https://www.tensordock.com/) states a 99.99% supplier uptime standard and advance maintenance expectations.

The official [live dashboard](https://dashboard.tensordock.com/) showed RTX PRO 6000 96 GB inventory from approximately **$1.10 per GPU-hour on 2 September 2026**. This is a dated customer retail floor, not supplier payout or evidence that a newly listed host will fill. The [supplier agreement](https://docs.tensordock.com/legal-information/supplier-hosting-agreement) contains an internal wording mismatch—“twenty percent (25%)”—so the numeric 25% should be treated as provisional until the executed agreement confirms it.

At the displayed retail floor, four fully occupied cards would gross $4.40 per host-hour to the marketplace and approximately $3.30 after a 25% supplier fee, before electricity, cooling, CPU/RAM/storage/network, tax, support, and downtime. Do not use that illustration as an occupancy forecast.

**Conclusion:** TensorDock proves that the exact card can have a market price, but it is ordinary VM capacity with a stringent availability expectation, not bursty API inference.

### Bittensor

Bittensor is a protocol for subnet-specific work rather than one uniform inference market. The general [mining guide](https://www.bittensor.com/docs/guides/mining) says miners register under subnet rules, compete for emissions, and can be deregistered when a full subnet replaces low-emission participants. Registration may require burn or collateral, and scoring, hardware, latency, and availability rules differ by subnet.

The subnet examples often cited for inference are now stale:

- [SN1](https://bittensor.ai/subnets/1) is Apex solution competition rather than a general LLM API.
- [SN2](https://github.com/inference-labs-inc/subnet-2) is Proof of Inference infrastructure, not an arbitrary prompt-serving market.
- [SN19](https://bittensor.ai/subnets/19) is Blockmachine RPC/archive infrastructure.

The closest current match is [engy SN53](https://github.com/hanlinai/engy/blob/main/docs/SN53_ONE_PAGER.md). Buyers use an OpenAI/Anthropic-compatible endpoint, permissionless miners serve a committed model and attach proofs, validators verify samples, and on-chain weights become emissions. Paid token volume influences scoring, but the miner does not receive a fixed cash pass-through for each request.

SN53's documented weekly hard gates include at least 99% successful responses, p99 time-to-first-token and time-per-output-token limits, and proof compliance. A failed gate can zero the full miner-model score for the epoch. A degraded worker may be removed from routing and must requalify. The [miner guide](https://github.com/hanlinai/engy/blob/main/docs/MINER.md) supports multiple serving URLs but requires the pinned model, proof stack, meaningful concurrency, and long context/output limits. Its request deadline can reach 1,800 seconds, which also disproves a universal one-to-three-second drain assumption.

The current SN53 hardware examples do not name RTX PRO 6000 Blackwell Workstation Edition. The 96 GB card is likely technically capable of relevant inference, but eligibility, proof correctness, p99 latency, and competitive emissions must be demonstrated.

**Conclusion:** SN53 is a real API inference supply market, but it is less preemptible than a raw interruptible Vast bid because a short outage can affect an entire weekly score.

### io.net

io.net's [supported-device list](https://io.net/docs/guides/workers/supported-devices) currently includes several professional and consumer NVIDIA cards but omits RTX PRO 6000 Blackwell Workstation Edition. Unsupported hardware cannot be assumed eligible.

For supported professional/high-end workers, the [device utilisation threshold](https://io.net/docs/guides/workers/device-utilization-threshold) requires very low use while the device is offered. Concurrent private research would violate the intended available state. The [earnings rules](https://io.net/docs/guides/workers/earnings-rewards) pay in IO and distinguish completed same-day and multi-day jobs; a worker unavailable during a job can lose payment for the affected period or entire job. The [reward-wallet documentation](https://io.net/docs/guides/workers/rewards-wallets) adds worker fees and staking considerations.

**Conclusion:** current exact-card eligibility fails, and even future eligibility would not make local co-use or abrupt supplier reclaim safe.

### Petals

The official [Petals repository](https://github.com/bigscience-workshop/petals) describes a community-run network that relies on people sharing GPUs. It publicly recognises operators who host many model blocks, but documents no cash payout or “swarm priority credits.” The proposal for a [distributed API with paid miners](https://github.com/bigscience-workshop/petals/issues/556) remains an open feature request.

Petals is useful evidence that pipeline inference can tolerate some peer churn. It is not evidence that this workstation can earn revenue, and protocol-level rerouting should not be treated as a guarantee that an in-flight request survives a disappearing node.

## MIG does not make full-card reclaim instantaneous

NVIDIA now officially supports MIG on RTX PRO 6000 Blackwell Workstation Edition. The [supported-GPU table](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/supported-gpus.html) allows up to four instances per card, and the [profile table](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/supported-mig-profiles.html) lists 4x24 GB, 2x48 GB, or 1x96 GB profiles. The [setup guide](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/getting-started-with-mig.html) requires a qualifying R575-or-newer driver, compatible vBIOS, Linux CUDA support, and compute display mode for this workstation card.

MIG is useful when the operator can reserve fixed 24 GB or 48 GB slices for public serving and keep other slices for private work. It does not allow a private 96 GB job to reclaim the full card while a public slice remains allocated. Reaching the full 96 GB profile requires removing/reconfiguring the smaller instances.

MIG is also different from vGPU. NVIDIA's [feature matrix](https://docs.nvidia.com/knowledge-base/latest/vgpu-features.html) lists vGPU on the Server Edition, not the Workstation Edition. None of the marketplace sources reviewed promises that a Workstation Edition MIG slice can be listed as an independent public GPU. Prove runtime and marketplace support before including MIG capacity in revenue.

## Model eviction and reload timings must be measured

The generic estimates of three-to-five seconds to evict and 15-to-30 seconds to reload a 70B model are not portable facts. They depend on:

- model architecture and quantisation;
- tensor parallelism versus four independent replicas;
- active request length and whether work is drained or aborted;
- CPU RAM available for offload;
- cold NVMe reads versus warm operating-system page cache;
- shared NVMe/PCIe bandwidth when all four workers wake together;
- runtime initialisation, kernel loading, compilation, and CUDA graph capture; and
- the amount of KV cache and other process state that must be discarded.

The weight size alone changes the problem. A dense 70B model is roughly 140 GB at BF16, 70 GB at FP8/INT8, or 35 GB at four bits before runtime overhead. “Load a 70B model into 96 GB” is therefore incomplete unless precision and serving topology are named.

Current [vLLM Sleep Mode](https://docs.vllm.ai/en/v0.21.0/features/sleep_mode/) provides materially different paths:

- level 0 pauses request scheduling;
- level 1 offloads model weights to CPU and discards KV cache; and
- level 2 discards all GPU allocations.

It also supports policies to abort, wait for, or retain existing requests. CPU-offloaded wake can avoid a cold NVMe read but requires sufficient host RAM and still competes for host-memory and PCIe bandwidth. No vLLM source promises a universal resume time.

Measure both warm and cold cases. Report p50 and p95 from stop-admitting to zero live requests, from stop to sufficient free VRAM for research, from research start to first valid result, and from public-worker wake to health check and first token. Run the same sequence on one card and on all four concurrently.

## Economics boundary

Use allocation occupancy, not chip activity, in the revenue model:

```text
net idle contribution per hour
  = paid allocation or token utilisation * net supplier rate
  - wall power * electricity tariff
  - cooling, network, storage, platform, token, tax, and operations costs
  - expected cost of failed public jobs and interrupted research
```

For a directly sold API:

```text
gross revenue per hour
  = 3,600 * ((paid input tokens/s * net input price)
             + (paid output tokens/s * net output price))
```

Peak throughput cannot substitute for paid demand. At one per cent paid utilisation, a high per-token list price can still earn less than a modest GPU-hour lease.

Each Workstation Edition card has up to 600 W board power on [NVIDIA's product page](https://www.nvidia.com/en-us/products/workstations/professional-desktop-gpus/rtx-pro-6000/), so the four GPUs alone can reach 2.4 kW before CPU, RAM, disks, networking, conversion loss, and cooling. Continue to use [`ECONOMICS.md`](ECONOMICS.md) for the complete ex-VAT model and replace its price/fill inputs with pilot measurements.

Research teams do not universally subsidise compute this way because unpredictable local demand conflicts with public availability commitments, paid occupancy is uncertain, one workstation has no serving redundancy, untrusted workloads add security and support work, and model/KV/compiler state has real restoration cost. The hardware may be idle while still being operationally valuable as immediately available research capacity.

## Recommendation

1. **Keep the current Vast interruptible path as the primary experiment.** It has a concrete owner-reclaim mechanism in this repository, although it still needs the outside-renter trial and does not guarantee zero rating impact.
2. **Run any inference alternative on one physical GPU first.** Keep the other three unlisted and immediately available to research. Do not use MIG in the first market test because marketplace recognition of the slices is unproven.
3. **Use engy SN53 only as a high-risk API pilot.** First prove exact-card support, the pinned model, proof validity, concurrency, and p99 service gates. Measure emissions over at least one complete scoring epoch; do not value paid token volume as direct cash revenue.
4. **Use Salad only as a low-cost compatibility probe.** Confirm that the client recognises the card, assigns container work, uses the intended GPUs, and provides a redeemable net payout before forecasting.
5. **Treat Akash and TensorDock as capacity-rental comparisons.** They may sell individual cards, but their lease and uptime obligations do not solve urgent reclaim.
6. **Exclude RunPod, Nosana, and io.net for the current decision.** New RunPod suppliers are closed, Nosana's topology rule conflicts, and io.net omits the exact card and disallows meaningful co-use while available.
7. **Exclude Petals from the financial comparison.** It is a volunteer research network, not paid capacity.

## Pilot test matrix

| Question | Test | Record | Gate before expansion |
| --- | --- | --- | --- |
| Does the platform accept the exact hardware? | Register one GPU; run the official qualification and one paid workload | Reported model name, driver/CUDA, proof or benchmark result, support response | Exact card and topology accepted without masquerading as another SKU |
| Is there real demand? | Leave one GPU eligible for 30 days | Queue time, allocated hours, paid requests/tokens, time-of-day distribution | Measured paid utilisation supports the economics model |
| What is actually paid? | Reconcile platform ledger to wallet/bank receipt | Gross reward, fees, slashes, token conversion, withdrawal cost, tax basis | Positive net contribution after all variable costs |
| Are physical GPUs independent? | Serve on GPU 0 while running representative research on GPUs 1-3 | Throughput, latency, CPU/RAM/NVMe/network contention, power | No material research regression or cross-GPU allocation failure |
| Can work drain safely? | Stop admission during short, long, streaming, and maximum-output requests | p50/p95 drain time, abort count, customer-visible errors | Bounded behavior compatible with the team's reclaim objective |
| How fast is local readiness? | Exercise vLLM pause, sleep level 1, sleep level 2, and process exit | Time to free VRAM and first valid private result | Measured p95 meets the research workflow requirement |
| How fast is return to service? | Wake from warm CPU-offload, warm page cache, and cold cache; repeat on all four GPUs | Health-ready time, first-token time, compilation/reload errors | Service meets the platform p99 gate after every supported transition |
| What does failure cost? | In a controlled non-customer qualification window, interrupt process/network and reboot once | Lost reward, score/reliability change, requalification time | Consequence is understood and acceptable; no hidden multi-day lockout |
| Is isolation adequate? | Review container privileges, ports, secrets, storage residue, and tenant access | Sanitised security checklist and cleanup evidence | Public work cannot reach private datasets, credentials, or research state |
| Does the result beat Vast? | Compare measured net contribution and research interruption cost with the same 30-day Vast scenario | Ex-VAT contribution, operator hours, failed-work cost, uncertainty range | Inference wins on measured contribution or a separately valued strategic goal |

Add the pilot evidence to [`TRIAL-NOTES.md`](TRIAL-NOTES.md). Do not generalise a successful single-card month to four simultaneous workers until the four-card cold-start, shared-I/O, power, and failure tests also pass.
