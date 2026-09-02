# SCAN 4x RTX PRO 6000 economics

This is a planning model for a SCAN 3XS SC PB4-32T used for bursty Sqwish R&D and listed as four independent 1-GPU interruptible offers while idle. It is not a revenue forecast. Replace every assumption with the delivered machine, written SCAN quote, and fresh Vast Market Stats before signing a long commitment.

## Headline

VAT is recoverable, so every decision figure below uses SCAN's **£1,666.65 ex-VAT** 30-day public price. The recommended pre-measurement mean is a deliberately rounded **20% owner allocation**. The worked normal three-researcher calendar happens to produce 19.4%, P95 owner concurrency of two GPUs, and a four-GPU peak; that calendar explains the prior rather than proving it. Use an **$0.80/GPU-hour** host floor and an 18-period rental-fill ramp of two periods at 50%, four at 70%, then twelve at 80%. The ramp averages 74.4% fill of owner-idle GPU-hours.

At a 25% commitment discount, that model earns **£1,014 per 30-day-equivalent period**, leaves an effective cost of about **£236 ex VAT**, and totals **£4,246 effective cost over 18 periods**. Once the host sustains 80% fill, the same 20% owner-use month falls to about **£160 effective cost**.

A lean five-template owner pool (three 1-GPU, one 2-GPU, one 4-GPU instance at 20 GB each) provisionally adds about **£15 per 30-day period** in stopped-disk charges, taking the base to roughly **£251 per period / £4,512 over 18 periods**. This storage line should be reconciled against the first real invoice because the owner is also the storage host.

| Commitment discount | Discounted SCAN ex VAT | Effective cost ex VAT |
| ---: | ---: | ---: |
| 20% | £1,333 | £319 |
| 25% | £1,250 | **£236** |
| 30% | £1,167 | £153 |

This is a planning case, not a median-revenue claim. The 80% interruptible fill is deliberately below current whole-market WS utilization, but that utilization includes on-demand and reserved rentals. A new unverified host can fill much more slowly. The actual machine must still prove the identity at provisioning with `nvidia-smi`; four 600 W cards are also a material power and cooling input.

## Cost inputs

Checked 2 September 2026:

| Item | Public value |
| --- | ---: |
| SCAN weekly, 7 days | £458.32 ex VAT |
| SCAN monthly, 30 days | £1,666.65 ex VAT |
| Included hardware | 4x 96 GB RTX PRO 6000, EPYC 9354P, 512 GB ECC, 2 TB NVMe |
| Published commitment choices | 1 week, 1 month, 3 months, 6 months, 1 year |
| Public long-term discount | Not stated; SCAN says longer terms receive “incentivised pricing” |
| Modelled discount | User-supplied 20-30% for a 1-2 year negotiated term |
| FX reference | EUR/USD 1.1590 and EUR/GBP 0.85655, so £1 = $1.3531 |

Sources: [SCAN monthly system](https://www.scan.co.uk/products/3xs-sc-pb4-32t-1-month-4x-96gb-nvidia-rtx-pro-6000-512gb-ddr5-ecc-amd-epyc-9354p), [SCAN weekly system](https://www.scan.co.uk/products/3xs-sc-pb4-32t-1-week-4x-96gb-nvidia-rtx-pro-6000-512gb-ddr5-ecc-amd-epyc-9354p), and the [ECB 1 September 2026 reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html).

Applying the hypothetical discount to the current public monthly price:

| Discount | 30-day ex VAT | 18 x 30-day ex VAT | 24 x 30-day ex VAT |
| ---: | ---: | ---: | ---: |
| 20% | £1,333.32 | £23,999.76 | £31,999.68 |
| 25% | £1,249.99 | £22,499.78 | £29,999.70 |
| 30% | £1,166.66 | £20,999.79 | £27,999.72 |

These totals use 18 or 24 30-day periods. A written calendar-term quote will differ.

## 18-month committed-use envelope

SCAN publishes the available term lengths and says longer contracts receive incentivised pricing, but it does not publish the 18-month discount. The table therefore couples three negotiated-discount assumptions with the corresponding rental case. This avoids applying the best discount to a downside rental outcome and calling the combination a median.

| Combined case | SCAN discount | Host rate | Mean fill of idle GPU-hours | 30-day-equivalent effective ex VAT | 18-period SCAN charge ex VAT | 18-period Vast revenue | 18-period effective ex VAT |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Downside: weak quote + low demand | 20% | $0.61 | 40% | £918 | £24,000 | £7,478 | **£16,521** |
| Base: target quote + explicit ramp | 25% | $0.80 | 74.4% | **£236** | £22,500 | £18,254 | **£4,246** |
| Upside: strong quote + mature host | 30% | $0.90 | 90% | -£213 | £21,000 | £24,826 | **-£3,826** |

All three cases hold team use at 20% so the rental market and commitment quote can be compared cleanly. The base case says an 18-period commitment costs about **£22,500 ex VAT**, earns about **£18,254** of Vast compute revenue, and leaves about **£4,246 effective cost** across the term. The upside result is not a promise of profit; it means the modelled compute income exceeds only the discounted SCAN subscription before the excluded costs below.

These are 18 copies of a 30-day public price, or 540 days. An actual 18-calendar-month quote is slightly longer and may use a different billing cadence or discount tier; replace the proxy with SCAN's written quote.

## Vast market evidence

### Exact SCAN variant

The individual SCAN subscription title omits the edition suffix, but the surrounding official evidence identifies it with high confidence as the full **Workstation Edition**, not Max-Q or Server:

- the exact LN160420/LN160437 systems sit in SCAN's RTX PRO 6000 Cloud Workstations category, which says the systems use the flagship *workstation* RTX PRO 6000 Blackwell card;
- SCAN advertises the cloud line at 4,000 AI TOPS and 125 FP32 TFLOPS, matching the full Workstation Edition rather than Max-Q's 3,511 TOPS/110 TFLOPS or Server Edition's 120 TFLOPS;
- SCAN separately labels and sells the full card as PNY `VCNRTXPRO6000-PB`, 600 W, double-flow-through and “cloud ready”; its Max-Q and passive Server products have distinct names and part numbers; and
- SCAN's RTX PRO Server systems explicitly say “Server Edition” and use a different server platform.

Sources: [SCAN RTX PRO 6000 Cloud Workstations category](https://www.scan.co.uk/shop/computer-hardware/cloud-solutions-ai-vgpu/3xs-cloud-workstations-rtx-pro-6000), [SCAN full Workstation Edition card](https://www.scan.co.uk/products/96gb-pny-nvidia-rtx-pro-6000-blackwell-24064-cuda-752-tensor-188-rt-gddr7-w-ecc-pcie-50x16-4x-dp-21), and [NVIDIA's three-variant comparison](https://www.nvidia.com/en-us/products/workstations/professional-desktop-gpus/rtx-pro-6000-family/).

The provisioning acceptance check is still mandatory because the subscription page has inconsistent generic copy and does not print a board part number. Request `VCNRTXPRO6000-PB` or `VCNRTXPRO6000-SB`, then verify four GPUs and a 600 W power limit. If SCAN delivers `VCNRTXPRO6000MQ-*`, rerun the model as `RTX PRO 6000 Max-Q` and reject the assumption used here.

The signed-in Vast Market Stats view was read on 2 September 2026 with a 30-day price window and `# GPUs = 4`. It showed the following current occupancy and host listing-price distributions. Vast states on that page that displayed prices are host listing prices.

| Exact Vast GPU family | GPUs represented | Current utilization | Rented host price P10 | Median | P90 |
| --- | ---: | ---: | ---: | ---: | ---: |
| RTX PRO 6000 WS | 108 | 86.1% | $0.780 | $0.995 | $1.727 |
| RTX PRO 6000 S | 32 | 90.6% | $0.750 | $0.950 | $1.109 |
| RTX PRO 6000 Max-Q | 72 | 91.7% | $0.820 | $1.038 | $1.150 |

Those utilization figures include all rental types, so they are an optimistic proxy for an interruptible-only listing. A separate live API/CLI snapshot at 00:17-00:18 UTC on 2 September 2026 searched currently available 1-GPU interruptible offers with at least 32 GB of disk. After converting renter-facing bid prices to host earnings using the live 75% relationship, it found:

| Exact Vast family | Available offers | Host earnings P25 | Median | P75 | P10-P90 |
| --- | ---: | ---: | ---: | ---: | ---: |
| RTX PRO 6000 WS | 22 | $0.613 | **$0.740** | $0.900 | $0.505-$1.031 |
| RTX PRO 6000 S | 14 | $0.460 | $0.637 | $0.948 | $0.375-$0.967 |
| RTX PRO 6000 Max-Q | 8 | $0.492 | $0.600 | $0.674 | $0.311-$0.749 |

The tighter comparison—1-GPU slices specifically from 4-GPU WS hosts—had only five available offers, with **$0.850/GPU-hour median host earnings**. That small sample is the best topology match but is too thin to treat as a durable market median. An opening floor of **$0.80 host-earned per GPU-hour** is a practical quick-fill experiment: slightly below that exact-host median while still close to the broader WS market. Reprice against a fresh snapshot rather than preserving $0.80 indefinitely.

The planning model therefore uses:

- **40% downside fill** of owner-idle GPU-hours for a new, unverified host or weak interruptible demand;
- an explicit **50% / 70% / 80% ramp** averaging 74.4% across 18 periods, then 80% mature fill, below current WS whole-market utilization of 86.1%;
- **90% upside fill** after verification with a competitive price and stable history.

Refresh both sources before relying on the numbers: [Vast Market Stats](https://cloud.vast.ai/host/market/) and `vastai search offers ... --type bid`. New Vast hosts start at 60% reliability and can be hidden by common verified/reliability filters, so the first weeks can underperform the mature-market figures.

### Price semantics

Since June 2024 Vast describes the host fee as 0%: the price a host sets is the amount the host earns, and Vast applies its surcharge internally. The renter-facing search price can therefore be higher than the host floor. The one-GPU qualification trial confirmed the current conversion empirically: a $0.040 host floor appeared as a $0.053333 client minimum bid. This model always uses the **host-earned rate** and does not subtract a second 25% fee. See Vast's [June 2024 pricing-semantics update](https://vast.ai/article/june-2024-product-update).

### Owner self-rent and standby storage

The qualification host also resolved the “paying for our own machine” question. After a real owner on-demand standby was created, fully started, and stopped, its instance billing object reported:

- `gpuCostPerHour = 0`: the owner was not charged its own public GPU deterrent price;
- `diskHour = totalHour = $0.005555...` for a 20 GB disk, equivalent to **$4 per 30 days** at the listing's $0.20/GB-month storage price; and
- the separate search/listing object still displayed the public $12.11/hour sticker price, which was not the owner billing rate.

At the model FX rate, one 20 GB stopped standby is about £2.96 per 30 days. Five such templates reserve 100 GB of the Vast Docker pool and display about **$20 / £14.78 per 30 days** in aggregate storage charges. Treat that as a conservative cost until Host Earnings and the owner invoice show whether self-hosted storage is internally offset. GPU compute cost is confirmed zero for this trial; stopped storage is not.

## Downside, planning, and upside

All three cases below assume four GPUs, a 30-day period, and the rounded **20% / 576 GPU-hour Sqwish allocation**. Rental fill applies only to the remaining GPU-hours. Storage and bandwidth income are excluded.

| Case | Host earnings / GPU-hour | Fill of owner-idle hours | Vast compute revenue |
| --- | ---: | ---: | ---: |
| Downside / weak demand | $0.61 | 40% | £415/month |
| Planning case / 18-period ramp mean | $0.80 | 74.4% | **£1,014/month** |
| Upside / established host | $0.90 | 90% | £1,379/month |

Effective 30-day cost ex VAT:

| SCAN discount | Downside | Planning median | Upside |
| ---: | ---: | ---: | ---: |
| 20% | £918 | £319 | -£46 |
| 25% | £835 | £236 | -£129 |
| 30% | £751 | £153 | -£213 |

A negative value means modelled Vast compute revenue exceeds the ex-VAT lease cost before payout conversion costs, tax, failed starts, downtime, or operational labour. Do not treat it as guaranteed profit.

## WS price sensitivity

At the rounded 20% owner allocation and mature 80% idle fill:

| Host-earned interruptible rate | Approximate monthly revenue | 25%-discount effective cost ex VAT |
| ---: | ---: | ---: |
| $0.61, current WS available-offer P25 | £831 | £419 |
| $0.74, current broad WS median | £1,008 | £242 |
| $0.80, quick-fill opening floor | **£1,090** | **£160** |
| $0.85, current 4-GPU-host slice median | £1,158 | £92 |
| $0.90, current WS available-offer P75 | £1,226 | £24 |

The market can move between purchase and delivery. The opening price should be generated from a fresh comparable-offer snapshot, then raised after the host earns verification and reliability history if fill remains strong.

## Owner-use sensitivity

At the $0.80 quick-fill floor and 80% fill of the time Sqwish is idle:

| Sqwish GPU use | Vast revenue | Effective cost at 25% SCAN discount, ex VAT |
| ---: | ---: | ---: |
| 10% | £1,226 | £24 |
| 20%, rounded default | **£1,090** | **£160** |
| 40% | £817 | £433 |

Owner use must be measured in aggregate GPU-hours. Using all four GPUs for six hours consumes 24 GPU-hours; using one GPU for six hours consumes six. Individual 1-GPU offers preserve revenue from the other free GPUs until an owner job needs the whole node.

## Research-team usage patterns

Average use is not enough to size the reclaim path. The data supports the *shape* of the default, while Sqwish's own schedule supplies its mean:

- Microsoft's Philly production trace covered 96,260 training jobs. A later comparison reports that more than 82% used one GPU, while Philly measured only 52.32% average chip activity on GPUs already allocated to jobs. The one- and four-GPU means were 52.38% and 45.18%. This is why allocation occupancy, rather than `nvidia-smi` utilization, drives rental availability. [Philly trace analysis](https://www.usenix.org/system/files/atc19-jeon.pdf)
- Alibaba's two-month PAI trace covered 6,742 GPUs and 7.5 million task instances. Median runtime was 23 minutes and P90 was 4.5 hours; the corresponding Philly figures were 26 minutes and 25 hours. Requests and use followed weekday/diurnal patterns, and the resource distributions were heavy-tailed. [Alibaba PAI analysis](https://www.usenix.org/system/files/nsdi22-paper-weng.pdf)
- Microsoft's hyperparameter-tuning study found a median 75 jobs per application, a 3.75 GPU-hour median task, and 11.5 GPU-days per median application, with bursty aggregate demand. It supports batching many tiny trials inside a smaller number of owner reservation windows. [Themis trace analysis](https://www.usenix.org/system/files/nsdi20-paper-mahajan.pdf)
- A six-month 4,704-A100 LLM-development trace found that the majority of jobs were single-GPU while a tiny number of pretraining jobs dominated GPU-hours: 0.9%/3.2% of jobs consumed 69.5%/94.0% of GPU time in its two clusters. That supports many small experiments plus occasional capacity-dominating campaigns. [Acme LLM workload analysis](https://www.usenix.org/system/files/nsdi24-hu.pdf)

These are large-cluster directional priors; they do not establish utilization for three people. The **19.4% normal mean** below is a transparent pre-measurement schedule: each researcher gets fifteen six-hour 1-GPU reservation windows, the team gets eight 12-hour 2-GPU windows, and two 12-hour full-node runs. That is `270 + 192 + 96 = 558` GPU-hours out of 2,880. Its illustrative concurrency calendar is 370 hours at zero GPUs, 190 at one, 136 at two, and 24 at four. Replace it with scheduler telemetry after the first month.

The following steady-state table uses a $0.80 host floor, 80% fill of owner-idle GPU-hours, and the 25%-discount SCAN cost. `P50` and `P95` include zero-use wall-clock hours.

| Pattern | Owner GPU-hours / mean allocation | P50 / P95 / peak GPUs | Owner reservation starts | Starts likely to need reclaim | Expected tenant pauses | Vast revenue | Effective cost ex VAT |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Light prototyping | 224 / 7.8% | 0 / 2 / 4 | 42 | 35 | 42 | **£1,256** | -£6 |
| Normal mixed R&D | 558 / **19.4%** | 0 / **2** / **4** | 55 | 46 | 55 | **£1,098** | £152 |
| Active training campaign | 1,300 / 45.1% | 2 / 4 / 4 | 45 | 39 | 56 | **£747** | £503 |
| Deadline month | 2,300 / 79.9% | 4 / 4 / 4 | 23 | 21 | 34 | **£274** | £976 |

The normal case has a zero-GPU monthly median, two-GPU P95, and four-GPU peak. Peak demand is therefore a reclaim-latency and atomic-allocation problem, while allocated GPU-hours drive revenue. A notebook that holds one GPU for eight hours consumes eight owner GPU-hours even if the chip is active for only minutes; Vast cannot sell that GPU simultaneously. Automatically stop abandoned notebooks and finished jobs.

The reclaim counts assume each requested GPU is independently rented with 80% probability when an owner window starts. Chaining trials within one reservation window reduces disruption. Frequent short gaps may also cause renters to leave rather than resume, lowering realised fill. Use 60% fill as a fragmentation/churn stress test; the four patterns then earn approximately £942, £824, £560, and £206.

Generate and edit the assumptions with:

```bash
python3 tools/usage_patterns.py
python3 tools/usage_patterns.py --idle-fill-percent 60
```

### Reclaim shapes for a three-person team

Do not reclaim the full node for every job. Keep the public machine at `min_chunk=1` and prepare stopped owner instances for the workload shapes the team actually launches:

- three small **1-GPU** owner instances, one per current researcher, for independent notebooks and single-GPU runs;
- one **2-GPU** owner instance for jobs that need two GPUs inside one container; and
- one **4-GPU** owner instance for NCCL or full-node training.

Starting a 1-GPU owner instance should pause only one interruptible tenant and leave three GPUs earning. Before a 4-GPU job, stop any running 1/2-GPU owner instances, then start the pre-created 4-GPU instance. Each stopped template retains its disk, so budget their combined small disks inside the 300-400 GB Vast pool and keep durable datasets/results elsewhere.

This template pool is an intended design, not yet a proved Vast guarantee. The pilot still needs to demonstrate that one 4-GPU owner start can atomically pause four independent 1-GPU interruptible renters, that the correct bids resume after release, and that repeated priority pauses do not degrade host status. Until that test passes, schedule full-node jobs with a short reclaim lead time rather than promising immediate launch.

## Excluded income and costs

- Storage and bandwidth are usage-dependent and small relative to GPU compute in this model. Comparable offers showed roughly $0.20/GB/month storage and a few dollars per TB transfer. Count them only after real invoices show both renter usage and host earnings.
- SCAN's page says the system includes NVMe storage and uncontended network ports with no hidden fees, but the written long-term quote must confirm power, traffic, public IPv4, port forwarding, and any excess-use charges.
- Payout conversion fees, foreign-exchange movement, downtime, failed instance starts, and operational time are zero in the table.
- The revenue model must not assume forced owner reclaim. Three clean two-A100 Host Job attempts at progressively higher prices did not preempt the controlled renter, and reliability fell earlier in the complete setup sequence from 0.5999925 to 0.5727243. Model only GPUs that researchers release for the full contract window, capacity that can drain before use, or GPUs reserved from sale. Revenue and near-instant owner access cannot currently be counted on the same GPU-hours.

## Formula and calculator

For a 30-day period:

```text
rental_revenue_USD = 4 GPUs x 720 hours x (1 - owner_use) x idle_fill x host_rate_USD
rental_revenue_GBP = rental_revenue_USD / USD_per_GBP
effective_cost_GBP = discounted_SCAN_cost_GBP - rental_revenue_GBP
```

Recalculate with the dependency-free helper:

```bash
python3 tools/economics_model.py

# Mature-host sensitivity after the assumed fill ramp:
python3 tools/economics_model.py --idle-fill-percent 80
```

The helper also prints the total for 18 identical 30-day periods by default. Set `--commitment-periods 24` for the two-year proxy.

Update the SCAN price, FX rate, exact GPU rate, and measured occupancy rather than preserving old defaults.
