# SCAN 4x RTX PRO 6000 technical pilot

This note assesses the published **3XS SC PB4-32T** configuration as a Docker-only Vast host and owner-reclaim test. It is a technical gate, not proof that the delivered service exposes the required host controls.

## Recommendation

Use the one-week option as a measured pilot. The published CPU, RAM, GPU count, VRAM, operating system, and nominal SSD capacity clear Vast's basic thresholds. Do not start the Vast install until the provisioned system also passes the physical-host, root access, networking, storage-layout, PCIe, driver, and topology gates below.

Begin with `min_chunk=4`, which produces one full-machine renter contract and the simplest reclaim test. Move to `min_chunk=1` only after the full-machine path works and a controlled test proves that one owner 4-GPU on-demand instance pauses and later releases four independent 1-GPU bids cleanly.

## Published configuration

| Resource | Published value | Vast fit |
| --- | ---: | --- |
| GPUs | 4x NVIDIA RTX PRO 6000, 96 GB each | Identical premium GPUs; the exact Server, Workstation, or Max-Q variant is not stated |
| CPU | AMD EPYC 9354P, 32 cores / 64 threads | 8 physical cores per GPU, above Vast's 2-per-GPU minimum |
| RAM | 512 GB DDR5 ECC | Above `0.95 x 4 x 96 GB = 364.8 GB` |
| Storage | One 2 TB PCIe NVMe system drive | Enough raw capacity for a pilot; the separate Docker-storage layout is not published |
| OS | Ubuntu 24.04 LTS available | Vast recommends Ubuntu Server 22.04 or 24.04 |
| Network | “Uncontended network ports” | Link speed, symmetry, public IPv4, and inbound port range are not published |

Source: [SCAN product page](https://www.scan.co.uk/products/3xs-sc-pb4-32t-1-week-4x-96gb-nvidia-rtx-pro-6000-512gb-ddr5-ecc-amd-epyc-9354p).

## Confirm before provisioning

Treat any missing item as a stop condition until it is demonstrated on the actual machine.

- The operating system is a dedicated physical host rather than a vGPU guest, and `nvidia-smi` sees four complete, identical 96 GB devices. Vast defines a machine as a single physical host.
- Full root or passwordless sudo is available, including permission to install Docker, NVIDIA Container Toolkit, the Vast manager, kernel updates, and system services.
- The exact GPU variant is identified. NVIDIA's variants differ sharply: Server is 400-600 W and passive, Workstation is 600 W, and Max-Q is 300 W. Vast uses distinct Server and Workstation model names.
- A stable public IPv4 address reaches the host directly. At least 20 forwarded TCP **and** UDP ports are available for four GPUs; Vast recommends 400. No CGNAT sits in the path.
- Symmetric throughput is at least 500 Mbps. For four premium 96 GB GPUs, record the actual sustained rate and contention rather than treating Vast's floor as a performance target.
- `/var/lib/docker` can use a dedicated SSD/NVMe filesystem of at least 200 GB, preferably XFS with project quotas. The published single 2 TB system drive does not establish this layout; request another SSD or a demonstrated separate Docker device.
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
nvidia-smi --query-gpu=index,name,uuid,memory.total,driver_version,power.limit --format=csv
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

Keep VM mode off for this sequence:

```bash
sudo python3 /var/lib/vastai_kaalia/enable_vms.py off
python3 /var/lib/vastai_kaalia/enable_vms.py check
```

Vast warns that the IOMMU configuration needed for renter VMs can reduce NCCL performance on multi-GPU machines that depend on PCIe peer-to-peer communication. VM support may improve market visibility, so revisit it only after the Docker and owner-job measurements are complete.

## Staged listing and reclaim trial

### Stage 1: one 4-GPU interruptible

1. List with a fixed short end date, `discount_rate=0`, `vol_size=0`, an intentionally unattractive outside on-demand price, and `min_chunk=4`.
2. Confirm the only outside contract is interruptible. Record verification and reliability immediately before reclaim.
3. Configure `VAST_OWN_OFFER_ID` with this machine's 4-GPU on-demand offer. Preview `scripts/reclaim-gpu.sh`, then use its guarded apply flow.
4. Verify that Vast pauses the renter, retains its disk, and starts the owner instance with all four GPUs. Do not stop services or touch the renter's container.
5. Run a short owner workload, save its outputs, and release only the recorded owner instance with `scripts/release-gpu.sh`.
6. Time the renter's automatic resume and record verification, reliability, GPU health, disk health, and daemon state immediately and again after Vast's delayed metrics update.

### Stage 2: four 1-GPU interruptibles

Relist with `min_chunk=1`. Vast documents that this permits 1-, 2-, and 4-GPU offers and gives each running instance exclusive GPUs; CPU and RAM baselines scale with the GPU fraction. Nominally, each 1-GPU renter receives about 8 physical cores and 128 GB RAM, but the published offer values are authoritative.

Fill four controlled 1-GPU interruptible contracts, then repeat the same 4-GPU owner reclaim and release. Vast documents the priority pieces: on-demand outranks interruptible, paused data persists, and bids automatically resume when they regain priority. It does **not** explicitly document one 4-GPU owner request atomically preempting four separate 1-GPU contracts. Keep this behavior marked inferred until this test passes.

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
- both `min_chunk=4` and the controlled `min_chunk=1` pause/resume trials preserve renter state; and
- the owner's real NCCL workload performs acceptably on the measured topology.

## Primary sources

- [SCAN 3XS SC PB4-32T published specification](https://www.scan.co.uk/products/3xs-sc-pb4-32t-1-week-4x-96gb-nvidia-rtx-pro-6000-512gb-ddr5-ecc-amd-epyc-9354p)
- [Vast verification stages and current minimums](https://docs.vast.ai/host/verification-stages)
- [Vast hosting overview, min-GPU slicing, and owner self-rent](https://docs.vast.ai/host/hosting-overview)
- [Vast Docker resource allocation](https://docs.vast.ai/guides/instances/docker-environment)
- [Vast instance priority, pause, persistence, and resume](https://docs.vast.ai/guides/instances/choosing/instance-types)
- [Vast VM/IOMMU and NCCL caveat](https://docs.vast.ai/host/vms)
- [Vast CLI GPU names, including RTX PRO 6000 Server and Workstation](https://docs.vast.ai/cli/reference/launch-instance)
- [AMD EPYC 9354P specifications](https://www.amd.com/en/products/processors/server/epyc/4th-generation-9004-and-8004-series/amd-epyc-9354p.html)
- [NVIDIA RTX PRO 6000 Blackwell variants](https://www.nvidia.com/en-us/products/workstations/professional-desktop-gpus/rtx-pro-6000-family/)
- [NVIDIA CUDA compute capabilities](https://developer.nvidia.com/cuda/gpus)
- [NVIDIA CUDA toolkit and architecture matrix](https://docs.nvidia.com/datacenter/tesla/drivers/cuda-toolkit-driver-and-architecture-matrix.html)
- [NVIDIA Blackwell application compatibility guide](https://docs.nvidia.com/cuda/archive/12.8.0/blackwell-compatibility-guide/index.html)
