# SCAN 4x RTX PRO 6000 technical pilot

This note assesses the published **3XS SC PB4-32T** configuration as a Docker-only Vast host and owner-reclaim test. It is a technical gate, not proof that the delivered service exposes the required host controls.

## Recommendation

Use the one-week option as a measured pilot. The published CPU, RAM, GPU count, VRAM, operating system, and nominal SSD capacity clear Vast's basic thresholds. Do not start the Vast install until the provisioned system also passes the physical-host, root access, networking, storage-layout, PCIe, driver, and topology gates below.

Begin with `min_chunk=4`, which produces one full-machine renter contract and the simplest reclaim test. Move to `min_chunk=1` only after the full-machine path works and a controlled test proves that one owner 4-GPU on-demand instance pauses and later releases four independent 1-GPU bids cleanly.

## Published configuration

| Resource | Published value | Vast fit |
| --- | ---: | --- |
| GPUs | 4x NVIDIA RTX PRO 6000 Blackwell Workstation Edition, 96 GB each | Vast model `RTX PRO 6000 WS`; confirm four 600 W cards at provisioning |
| CPU | AMD EPYC 9354P, 32 cores / 64 threads | 8 physical cores per GPU, above Vast's 2-per-GPU minimum |
| RAM | 512 GB DDR5 ECC | Above `0.95 x 4 x 96 GB = 364.8 GB` |
| Storage | One 2 TB PCIe NVMe system drive | Enough raw capacity for a pilot; the separate Docker-storage layout is not published |
| OS | Ubuntu 24.04 LTS available | Vast recommends Ubuntu Server 22.04 or 24.04 |
| Network | “Uncontended network ports” | Link speed, symmetry, public IPv4, and inbound port range are not published |

Sources: [SCAN product page](https://www.scan.co.uk/products/3xs-sc-pb4-32t-1-week-4x-96gb-nvidia-rtx-pro-6000-512gb-ddr5-ecc-amd-epyc-9354p), its [RTX PRO 6000 Cloud Workstations category](https://www.scan.co.uk/shop/computer-hardware/cloud-solutions-ai-vgpu/3xs-cloud-workstations-rtx-pro-6000), and the [SCAN full Workstation Edition card](https://www.scan.co.uk/products/96gb-pny-nvidia-rtx-pro-6000-blackwell-24064-cuda-752-tensor-188-rt-gddr7-w-ecc-pcie-50x16-4x-dp-21).

### Variant identification

The subscription title itself omits the suffix, but SCAN's exact category says these systems use the flagship *workstation* RTX PRO 6000 Blackwell card. SCAN's published 4,000 AI TOPS and 125 FP32 TFLOPS match NVIDIA's full Workstation Edition; Max-Q is 3,511 TOPS/110 TFLOPS and Server Edition is 120 TFLOPS. SCAN also sells the full 600 W, double-flow-through PNY `VCNRTXPRO6000-PB` as “cloud ready” while separately and explicitly naming its Max-Q and Server cards.

Model the service as Vast `RTX PRO 6000 WS`. The remaining uncertainty is contractual configuration, because the individual subscription page does not print the board part number or power cap. Make acceptance conditional on a build sheet naming `VCNRTXPRO6000-PB` or `VCNRTXPRO6000-SB` and a sanitized `nvidia-smi` query showing four identical GPUs with a 600 W maximum/default power limit. Do not accept `VCNRTXPRO6000MQ-*` as equivalent.

## Confirm before provisioning

Treat any missing item as a stop condition until it is demonstrated on the actual machine.

- The operating system is a dedicated physical host rather than a vGPU guest, and `nvidia-smi` sees four complete, identical 96 GB devices. Vast defines a machine as a single physical host.
- Full root or passwordless sudo is available, including permission to install Docker, NVIDIA Container Toolkit, the Vast manager, kernel updates, and system services.
- The board part number and runtime identity confirm the full Workstation Edition. NVIDIA's variants differ sharply: Server is 400-600 W and passive, Workstation is 600 W, and Max-Q is 300 W. Vast prices all three under distinct model names.
- A stable public IPv4 address reaches the host directly. At least 20 forwarded TCP **and** UDP ports are available for four GPUs; Vast recommends 400. No CGNAT sits in the path.
- Symmetric throughput is at least 500 Mbps. For four premium 96 GB GPUs, record the actual sustained rate and contention rather than treating Vast's floor as a performance target.
- `/var/lib/docker` can use a dedicated SSD/NVMe filesystem of at least 200 GB total, preferably XFS with project quotas. Vast's current rule is 200 GB of dedicated Docker storage for the machine plus 20 GB free on the root filesystem; it is no longer 128 GB per GPU. For minimum exposure on this 2 TB system, create a hard **300-400 GB** Docker partition and keep the rest outside Vast. Disable volume offers. The published single drive does not establish the required layout.
- The motherboard, slot wiring, and PCIe switches are disclosed or measurable. The EPYC 9354P supports 128 PCIe 5.0 lanes, but that does not prove each installed slot is wired at x16 or free of a shared bottleneck.
- Boot, Secure Boot, IOMMU, and driver configuration are controllable. Keep Vast VM mode off for this Docker pilot.

## Pre-install evidence

Capture these results before installing the Vast manager:

```bash
sudo -n true
uname -a
cat /etc/os-release
lscpu
free -h
lsblk -o NAME,MODEL,SERIAL,SIZE,FSTYPE,MOUNTPOINTS
findmnt -R /
nvidia-smi -L
nvidia-smi --query-gpu=index,name,uuid,memory.total,driver_version,power.default_limit,power.max_limit,power.limit --format=csv
nvidia-smi topo -m
lspci -tv
sudo lspci -vv -d 10de:
```

Also test the public IPv4 and every proposed direct port from an external network over both TCP and UDP. Record sustained upload and download speed, packet loss, and latency. Do not infer reachability from an internal firewall rule.

The PCIe link report, `nvidia-smi topo -m`, and a four-GPU NCCL test determine whether the box is suitable for the owner's multi-GPU work. SCAN's published specification does not state NVLink, GPU peer-to-peer behavior, or slot topology.

## Idle-overhead measurement

Vast publishes no numerical idle CPU or RAM budget for its manager, Docker, containerd, or NVIDIA persistence process. Do not put an invented allowance into the capacity model. Measure the same ten-minute vacant interval immediately before and after installation:

```bash
date -u
uptime
free -h
systemd-cgtop --iterations=10 --delay=1
systemctl show vastai docker containerd \
  --property=ActiveState,SubState,MemoryCurrent,TasksCurrent,CPUUsageNSec
ps -eo pid,comm,%cpu,rss --sort=-rss | head -30
nvidia-smi --query-gpu=index,utilization.gpu,memory.used,power.draw,temperature.gpu --format=csv
```

Store the outputs in the private trial record. Use the effective CPU and RAM shown in the final Vast offer for renter-capacity calculations. On this 32-core, 512 GB configuration the control-plane load is unlikely to be the limiting resource, but that remains an inference until measured.

For scale, a 12.35-second vacant sample from the separate one-GPU qualification trial measured Vast's launcher, daemon, metrics, and support SSH at 57.3 MiB RSS plus Docker/containerd at 141.6 MiB RSS. Combined process RSS was 198.9 MiB (about 178 MiB PSS) and sampled control-plane CPU was 0.324% of one core, or about 0.0032 cores. If that mostly fixed cost carried over unchanged, it would be roughly 0.04% of this candidate's RAM and 0.01% of its 32 physical cores. Treat this only as an order-of-magnitude reference; four-GPU telemetry and the delivered environment still need the ten-minute measurement above.

The same sample showed why cgroup memory alone is misleading after qualification: Docker reported about 24.8 GiB and Vast 1.38 GiB, but almost all of it was reclaimable file cache from the freshly downloaded self-test image. Inspect anonymous versus file memory before calling cache an overhead reservation. GPU idle power is model-specific and must be measured on the delivered RTX PRO 6000 variant.

## Install and qualification sequence

1. Run `scripts/preflight-host.sh` and resolve every failure.
2. Install the current stable NVIDIA driver for the exact RTX PRO 6000 variant and verify Docker GPU access across all four devices.
3. Use CUDA 12.8 or newer for the qualification image. RTX PRO 6000 Blackwell is compute capability 12.0, and NVIDIA lists CUDA 12.8 as its first native toolkit support.
4. Run the official Vast self-test while the machine is vacant. Each GPU must exceed Vast's 2.85 GiB/s PCIe threshold, and the network and direct-port tests must pass.
5. Run simultaneous GPU load long enough to expose power, cooling, clock throttling, and driver resets. Record per-GPU temperature, power, clocks, ECC/Xid events, and host stability.
6. Run concurrent storage and symmetric network load while all four GPUs are active. A single 2 TB NVMe and an undisclosed NIC are the most likely shared bottlenecks.
7. Test a current CUDA 12.8+ PyTorch container. Older images that contain only architecture-specific cubins and no compatible PTX can fail on Blackwell even when the host driver is current.
8. With the host vacant and no owner workload running, enable `tools/verification_guard.py --enable-qualification-mode`. Keep every controller on the same private `VAST_STATE_DIR` and sample at five-minute intervals during the clean soak.

Keep VM mode off for this sequence:

```bash
sudo python3 /var/lib/vastai_kaalia/enable_vms.py off
python3 /var/lib/vastai_kaalia/enable_vms.py check
```

Vast warns that the IOMMU configuration needed for renter VMs can reduce NCCL performance on multi-GPU machines that depend on PCIe peer-to-peer communication. Its current verification guide also says VM support significantly improves verification likelihood. Record Docker-only VM-off operation as an explicit verification tradeoff, benchmark both modes before production if SCAN supports them, and never toggle IOMMU or VM mode during a clean qualification soak.

## Staged controlled qualification

### Stage 1: one 4-GPU controlled qualification

1. While vacant and before creating an owner standby, run the ordinary Self-Test once and enable qualification HOLD. Pin the immutable score, verification, reports, errors, and configuration baseline. Host work must use Vast Jobs/Create Job during this clean arm.
2. List with a fixed short end date, `discount_rate=0`, `vol_size=0`, an intentionally unattractive outside on-demand price, and `min_chunk=4`. Have the separately authenticated controlled client acquire the exact full-machine interruptible immediately, then unlist. Abort if any unknown client wins.
3. Record verification and reliability, then run at most one bounded Host Job diagnostic. The two-A100 trial's three clean attempts at $1.10/30 seconds, $1.30/90 seconds, and $3.00/GPU-hour/120 seconds did not preempt the controlled renter. Do not keep increasing price; Vast does not document it as a preemption lever.
4. If the controlled client remains running at the timeout, record the expected failed gate and clean up. If a future Vast release unexpectedly produces a clean pause, verify disk retention and owner topology before testing release. Do not stop services or touch the renter container.
5. Measure renter return only if a clean platform pause occurred. A client-side Start fallback is available only in qualification and still fails the automatic-return gate.
6. End and archive the clean arm before any owner on-demand experiment. Explicitly disable qualification HOLD, prepare the exact owner standby while vacant, then test that path separately. Starting the standby is not a Host Job/Create Job and cannot be counted as clean verification time.
7. Record verification, reliability, GPU health, disk health, and daemon state immediately and after delayed metric updates. Any material reliability decrease keeps production reclaim disabled.

### Stage 2: four 1-GPU interruptibles

Relist with `min_chunk=1`. Vast documents that this permits 1-, 2-, and 4-GPU offers and gives each running instance exclusive GPUs; CPU and RAM baselines scale with the GPU fraction. Nominally, each 1-GPU renter receives about 8 physical cores and 128 GB RAM, but the published offer values are authoritative.

Fill all four slices with separately authenticated controlled 1-GPU interruptible contracts only if a diagnostic multi-slice qualification is still useful. Vast does **not** document a Host Job atomically preempting four separate 1-GPU contracts. The production decision remains blocked unless Vast publishes that mechanism and clean testing proves every pause, return, and delayed rating checkpoint.

Use [`CONTROLLED-24H-VERIFICATION-AND-HANDOFF-PILOT.md`](CONTROLLED-24H-VERIFICATION-AND-HANDOFF-PILOT.md) for the extended combined run. It keeps a qualification-trend soak with one fully stopped allowlisted standby, four checkpointing one-GPU interruptibles, the explicit mode transition, three full-machine research-first handoffs, automatic return proofs, and score observations in separate evidence bands. Keep the no-owner strict verification soak as a separate control.

For production, list only GPU slices that researchers explicitly release for the full contract window, unlist and drain before owner use, or reserve capacity for burst demand. Do not make the purchase case depend on forced renter handoff.

Stop the trial if any outside on-demand or reserved contract appears. A high on-demand price discourages such a contract but cannot prevent it.

## Shared-resource checks

| Resource | Expected behavior | Pilot decision |
| --- | --- | --- |
| GPU | Exclusive to each running instance | Pass only if four separate containers see exactly one unique GPU each |
| CPU | Baseline proportional to GPU share; burst only when spare | Pass if four simultaneous CPU-heavy renters remain stable at their advertised baseline |
| RAM | Baseline proportional to GPU share; excess can be OOM-killed under contention | Pass if the offer leaves host headroom and four baseline allocations remain stable |
| NVMe | One shared 2 TB pool for images and renter disks | Prefer a second, larger endurance-rated Docker SSD for continued hosting |
| Network | Shared NIC, public IP, upstream, and port pool | Pass only after four concurrent transfer/direct-port tests |
| PCIe | CPU has sufficient theoretical lanes; installed topology unknown | Pass after self-test, per-GPU bandwidth, topology, and NCCL results |
| Power/cooling | Variant-dependent 300-600 W per GPU plus a 280 W CPU | Pass only with stable simultaneous four-GPU load and no throttle/reset events |

## Go/no-go outcome

Proceed beyond the week only when:

- the actual environment presents a dedicated physical host with full root control and four full GPUs;
- public IPv4, inbound TCP/UDP ports, and sustained symmetric networking pass externally;
- a dedicated Docker-storage device or compliant storage layout is available;
- Vast self-test, four-GPU load, concurrent storage/network load, and Blackwell container tests pass;
- the operating plan uses explicit release, contract drain, or reserved GPUs and does not depend on Host Job preemption; and
- the owner's real NCCL workload performs acceptably on the measured topology.

Near-instant renter handoff is a separate blocked feature gate. Enable it only
if Vast documents a supported owner-reclaim mechanism and a controlled test on
the delivered machine passes reclaim, automatic return, and delayed rating
checks.

## Primary sources

- [SCAN 3XS SC PB4-32T published specification](https://www.scan.co.uk/products/3xs-sc-pb4-32t-1-week-4x-96gb-nvidia-rtx-pro-6000-512gb-ddr5-ecc-amd-epyc-9354p)
- [Vast verification stages and current minimums](https://docs.vast.ai/host/verification-stages)
- [Vast hosting overview, min-GPU slicing, and owner self-rent](https://docs.vast.ai/host/hosting-overview)
- [Vast Docker resource allocation](https://docs.vast.ai/guides/instances/docker-environment)
- [Vast instance priority, pause, persistence, and resume](https://docs.vast.ai/guides/instances/choosing/instance-types)
- [Vast `set defjob` background-job reference](https://docs.vast.ai/cli/reference/set-defjob)
- [Vast VM/IOMMU and NCCL caveat](https://docs.vast.ai/host/vms)
- [Vast CLI GPU names, including RTX PRO 6000 Server and Workstation](https://docs.vast.ai/cli/reference/launch-instance)
- [AMD EPYC 9354P specifications](https://www.amd.com/en/products/processors/server/epyc/4th-generation-9004-and-8004-series/amd-epyc-9354p.html)
- [NVIDIA RTX PRO 6000 Blackwell variants](https://www.nvidia.com/en-us/products/workstations/professional-desktop-gpus/rtx-pro-6000-family/)
- [NVIDIA CUDA compute capabilities](https://developer.nvidia.com/cuda/gpus)
- [NVIDIA CUDA toolkit and architecture matrix](https://docs.nvidia.com/datacenter/tesla/drivers/cuda-toolkit-driver-and-architecture-matrix.html)
- [NVIDIA Blackwell application compatibility guide](https://docs.nvidia.com/cuda/archive/12.8.0/blackwell-compatibility-guide/index.html)
