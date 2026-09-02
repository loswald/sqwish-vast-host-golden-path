# SCAN 4x / 8x RTX PRO 6000 quote call sheet

Use this for a call about a **24-calendar-month business service, invoiced monthly**, for Sqwish Labs. The initial option is one dedicated 4-GPU machine. Ask SCAN to quote both ways of reaching eight GPUs: **two independent 4-GPU machines** and **one 8-GPU machine**.

Do not treat a verbal answer as part of the deal. SCAN's business terms say website descriptions are approximate and do not form part of the contract, while the Supplier's Proposal and Service Specification define what SCAN must supply. Ask for every accepted point below in the written proposal.

## Sixty-second opening

> We are an AI research team looking for a dedicated Ubuntu machine for 24 calendar months, paid monthly rather than prepaid or financed. Our starting configuration is four full 96 GB RTX PRO 6000 Blackwell Workstation Edition GPUs, but we want side-by-side pricing for one four-GPU node, two identical four-GPU nodes, and one eight-GPU node. We need bare-metal exclusivity, full sudo/root control, Docker and system-service control, direct public networking, and written permission to use idle capacity as interruptible third-party GPU compute. Could we walk through the technical configuration first, then fixed monthly pricing, support, and contract terms?

## First five questions: stop if any answer is no

- [ ] **Is this one customer-exclusive physical bare-metal host?** It must not be a VM, vGPU guest, shared OS, or time-sliced GPU service.
- [ ] **Do we receive unrestricted SSH plus root/passwordless sudo?** We must be able to install and operate Docker, NVIDIA Container Toolkit, NVIDIA drivers, kernel packages, the Vast host manager, and our own `systemd` services; bind inbound TCP and UDP ports; and reboot the host.
- [ ] **Will SCAN give written permission for the idle-capacity workflow?** Describe it accurately: Sqwish runs its own R&D first and may offer otherwise-idle GPU slices through Vast.ai as interruptible container compute. Third-party users can run isolated Docker workloads and receive direct TCP/UDP ports. Sqwish will cap their storage, disable volume offers, prohibit cryptocurrency mining in its policy, monitor the host, and respond to abuse notices. Ask SCAN to state in the proposal that this third-party compute hosting/resale use is permitted and identify every applicable acceptable-use restriction.
- [ ] **Can SCAN provide a stable public IPv4 address with direct inbound TCP and UDP reachability?** No CGNAT. We want at least 400 contiguous ports reserved for the host, preferably `20000-20399`, with no surprise per-port or traffic fee.
- [ ] **Will the quote identify the exact GPU edition and power configuration?** Require four or eight identical, full 96 GB RTX PRO 6000 Blackwell **Workstation Edition** boards, their manufacturer part number, and 600 W maximum/default power limit. Max-Q is not an equivalent substitution.

If any answer is uncertain, ask who owns that decision and get that person's written answer before ordering.

## Commercial quote and discount

Ask SCAN to provide three comparable proposals, all ex VAT:

1. **One 4-GPU node:** 4x96 GB GPU, 512 GB ECC RAM, 24 months, invoiced monthly.
2. **Two independent 4-GPU nodes:** 8 GPUs total, 512 GB ECC RAM per node, independent public IPs and fault domains, 24 months, invoiced monthly.
3. **One 8-GPU node:** 8x96 GB GPU, 1 TB ECC RAM, 24 months, invoiced monthly.

The public prices checked on 2 September 2026 were **£1,666.65 ex VAT per 30 days** for the 4-GPU machine and **£3,333.32 ex VAT per 30 days** for the 8-GPU machine. The 8-GPU list price is effectively exactly twice the 4-GPU price, so the website shows no volume discount. These provide a comparison point, not the requested 24-month quote.

Ask:

- What is the fixed **calendar-month price ex VAT**, the total 24-month commitment, and the effective discount from current monthly list price?
- What additional discount applies at eight GPUs? Quote two 4-GPU nodes and one 8-GPU node separately rather than saying merely “8x”.
- Can Sqwish begin with one 4-GPU node and hold a contractual option to add a second identical node within 3, 6, or 12 months at the same or better per-GPU rate?
- Is there a larger discount for committing to the second node now, even if its service commencement is deferred?
- Is billing monthly in advance or arrears? Is there any deposit, setup fee, credit check, personal guarantee, or upfront hardware contribution? This is a business cloud-service invoice, not consumer finance.
- Does billing start only after delivery, our acceptance tests, and working remote access?
- Is the monthly price fixed for all 24 months? SCAN's standard business terms otherwise permit an annual CPI increase. Ask for **no CPI, FX, energy, hardware, or datacentre escalator during the initial term**.
- Are power, cooling, internet ingress/egress, the public IPv4, port forwarding, remote access, ordinary support, and the quoted NVMe capacity fully included?
- List every possible metered or one-off charge: bandwidth/egress, DDoS, extra IPs, storage, IOPS, backup/snapshots, reimages, remote hands, after-hours support, replacement hardware, data export, secure erasure, software licences, and onboarding.
- Can the one-week pilot be free or credited against the 24-month contract? Require a 7-day technical acceptance window with repair, replacement, or cancellation if the agreed gates fail.
- What is the hardware reservation/provisioning lead time, and what remedy applies if delivery is late?

Do not volunteer a minimum acceptable discount first. Ask for SCAN's best 24-month and eight-GPU pricing. If they demand a target, the current planning model tests **20%, 25%, and 30%** discounts and treats 25% as the working case.

## Two 4-GPU nodes versus one 8-GPU node

Ask SCAN's engineer to address these trade-offs rather than choosing on price alone:

- Two 4-GPU nodes give independent maintenance and failure domains, let two researchers or jobs use full nodes concurrently, and let Sqwish keep one node private while offering spare capacity on the other.
- One 8-GPU node is useful only if Sqwish needs single jobs spanning all eight GPUs and its measured GPU topology supports them well.
- SCAN's published 8-GPU system has the **same 32-core EPYC 9354P and 2 TB NVMe capacity** as the 4-GPU system. That halves CPU cores and raw storage per GPU. Ask whether a higher-core CPU and additional NVMe are available and what they cost.
- Ask for expected 4-GPU and 8-GPU NCCL results. If an eight-GPU job cannot communicate efficiently inside the PB8, two four-GPU nodes may be the better research system.
- Ask whether two nodes can receive a private high-speed link. Record NIC model, speed, topology, RDMA/RoCE support, switch service, and added monthly cost. Ordinary internet connectivity is not a substitute for a training fabric.

## Exact hardware and GPU topology

Have the quote/build sheet state:

- [ ] SCAN product/service code and unique node configuration.
- [ ] Exact GPU manufacturer and part number; full Workstation Edition; 96 GB GDDR7 ECC each; permitted power limit and whether SCAN imposes any power cap.
- [ ] No unapproved substitution with Max-Q, Server Edition, a different GPU, or a vGPU. Define the remedy if the named part becomes unavailable.
- [ ] Exact CPU, physical cores/threads, socket count, NUMA layout, and whether CPU/RAM is entirely dedicated.
- [ ] RAM capacity, DIMM population, speed, ECC mode, and upgrade path.
- [ ] Motherboard/chassis, power supplies and redundancy, cooling design, and sustained simultaneous-GPU power envelope.
- [ ] Every GPU's PCIe generation and electrical link width under load; any PCIe switches, oversubscription, ACS isolation, or shared uplinks.
- [ ] Whether GPU peer-to-peer DMA is enabled and supported. Ask for `nvidia-smi topo -m`, `lspci -tv`, per-GPU PCIe bandwidth, and a current 4-GPU/8-GPU NCCL test from the proposed build.
- [ ] Whether the GPUs have any NVLink/NVSwitch connection. Do not infer this from “multi-GPU”.
- [ ] Exact NVMe model(s), number of drives, raw and usable capacity, endurance rating, RAID arrangement, filesystem, and expected sequential/random performance under concurrent GPU load.
- [ ] Exact NIC model, link speed, physical redundancy, and whether the internet port itself is dedicated or only the logical port is “uncontended”.

Ask SCAN to run or allow Sqwish to run a simultaneous all-GPU, storage, and network acceptance test. Passing `nvidia-smi` alone is insufficient.

## Storage layout and data handling

The public configuration says one 2 TB NVMe system drive; it does not establish the layout Sqwish needs.

- Can SCAN install a separate endurance-rated NVMe drive for `/var/lib/docker`? Ask for 2 TB and 4 TB options and their one-off/monthly prices.
- If there is only one drive, can Sqwish repartition it and create a hard **300-400 GB XFS project-quota Docker pool**, keeping the rest inaccessible to public workloads?
- How much of the advertised 2 TB is usable after OS/recovery partitions?
- Can Sqwish replace/repartition filesystems and mount its own encrypted volumes without voiding support?
- Are snapshots or backups included? If so, specify frequency, retention, restore time, location, encryption, and cost. If not, confirm that clearly.
- What happens to disks during a GPU, motherboard, or whole-node replacement? Can SCAN attach the old data drive to the replacement host?
- At expiry, failure, or cancellation, how long can Sqwish export data and how does SCAN certify secure erasure?
- Who can access the host or disks, how is support access authorised and logged, and can Sqwish require approval except for emergencies?

## Root, operating system, and recovery controls

Ask for Ubuntu 24.04 LTS and confirm all of the following in writing:

- Persistent SSH access for multiple named Sqwish administrators and full sudo/root rights.
- Freedom to install/remove Docker, containerd, NVIDIA Container Toolkit, CUDA user-space packages, monitoring agents, a job scheduler, VPN software, firewalls, and Vast's host agent.
- Freedom to select a compatible NVIDIA production driver and apply kernel/security updates.
- Self-service reboot, shutdown, and power-on; clarify whether shutdown stops billing or risks losing remote access.
- Out-of-band BMC/IPMI, serial console, or equivalent recovery access. If customer BMC access is unavailable, state SCAN's response target for power cycle, console, rescue boot, and reimage requests.
- Control or documented change service for Secure Boot, IOMMU, ACS, SR-IOV, and other BIOS settings that affect Docker, GPU P2P, or NCCL.
- A clean rescue/reimage path and its typical completion time and charge.
- The SCAN agents, endpoint protection, remote-desktop software, monitoring, firewall, or management services that must remain installed; their CPU/RAM/GPU/disk overhead and whether Sqwish can disable them.
- No mandatory Windows, vGPU, NVIDIA AI Enterprise, remote-desktop, or other licence charge unless Sqwish explicitly orders it.

## Network and abuse operations

“Uncontended network ports” does not identify usable speed or internet policy. Ask:

- What are the NIC link speed and guaranteed/sustained symmetric internet throughput per node?
- Is traffic unmetered? If a fair-use allowance exists, state it in TB/month, measurement method, overage price, and throttling rule.
- Is the public IPv4 static for the entire term? Is it directly assigned or 1:1 NAT? Can SCAN supply a second address?
- Can Sqwish accept arbitrary inbound TCP and UDP on the agreed contiguous port range? List blocked ports and protocols.
- Is outbound traffic filtered, NATed, rate-limited, or charged? What are the DDoS protections and false-positive recovery process?
- Can SCAN delegate reverse DNS? Is IPv6 available?
- What latency and packet-loss targets apply, and where is the UK datacentre/network handoff located?
- For an abuse alert, will SCAN notify the named 24/7 contacts with source IP, destination, port, and timestamp and allow a cure window? Ask SCAN to isolate the affected flow/container where feasible rather than suspending the whole research host.
- Which workload classes are prohibited even inside third-party containers? Obtain the full acceptable-use policy before signing. Sqwish will prohibit mining, but must know whether SCAN also restricts inference APIs, public HTTP services, VPNs/proxies, scanning, or other marketplace traffic.
- What logs can SCAN provide for a reported event, and how long are network/abuse logs retained?

## Support, maintenance, and SLA

- Is monitoring and incident support staffed 24/7, or only UK business hours? Record phone, email, and portal escalation routes.
- Give response, engineer-engagement, workaround, and restoration targets for a dead host, failed GPU, failed NVMe, network outage, degraded GPU, and account/access problem.
- Is there a contractual monthly uptime target? State measurement, exclusions, service credits, and the claim process.
- How much notice is given for planned maintenance? Can Sqwish defer a window around a long research run?
- Does SCAN keep compatible spare GPUs/nodes? What is the replacement target, and will replacement preserve the exact GPU edition, RAM, storage, networking, and topology?
- Does a replacement or multi-day outage extend the committed term or reduce the invoice automatically?
- Who owns driver/firmware updates, and can SCAN make changes without approval? Require notice and rollback for changes that can alter CUDA/NCCL behavior.
- Ask for the warranty/support terms specific to this cloud service. The current product page says its warranty information has not yet been updated.
- Ask for named primary and backup account managers and an escalation contact. SCAN's managed-account page says accounts spending at least £10,000 per year can receive both.

## Security, data sovereignty, and people

- Confirm the physical host and all primary data remain in a named UK datacentre for the term.
- Ask for the applicable DPA, subprocessors, security certifications, incident-notification deadline, and data-breach contact.
- Confirm tenant/network separation, physical-access controls, support-access logging, and whether any other customer can reach the BMC or management plane.
- Ask who holds disk-encryption keys. Prefer Sqwish-held keys for research data.
- Confirm Sqwish owns its code, models, datasets, outputs, and container images and SCAN acquires no right to use them beyond operating the service.
- Ask whether SCAN can support several named researchers with separate SSH accounts and whether that carries a per-user fee.

## Commitment, change, renewal, and exit

- Contract term: exactly 24 calendar months from technical acceptance, invoiced monthly.
- Quote validity and hardware reservation period.
- Cancellation/early-termination charge and whether Sqwish can transfer the remaining commitment to upgraded hardware or another SCAN GPU service.
- Remedy if the system does not meet the written acceptance specification or the permitted-use requirement changes.
- Upgrade prices and downtime for RAM, NVMe, NIC, CPU, and a second 4-GPU node.
- Whether the second-node option reserves identical GPU stock and pricing.
- Renewal notice, auto-renewal, post-term monthly price, and minimum cancellation notice. Request no automatic renewal into another fixed term.
- End-of-term export window, disk image availability, secure erasure, and any exit fee.
- Business-continuity plan if the datacentre or SCAN service becomes unavailable; whether Sqwish can receive a replacement node in another UK facility.

## Items that must appear in the written proposal

Before signing, check that the Supplier's Proposal/Service Specification contains:

- the exact physical 4-GPU or 8-GPU build sheet and no-substitution rule;
- dedicated bare-metal exclusivity, Ubuntu 24.04, full root/sudo, Docker/system-service/driver rights, and recovery controls;
- explicit permission for the described Vast.ai interruptible third-party compute-hosting workflow and the complete acceptable-use rules;
- public IPv4, direct TCP/UDP port range, bandwidth commitment, traffic allowance, and overage price;
- usable NVMe capacity/layout and every ordered storage upgrade;
- 24-month fixed monthly ex-VAT price, total commitment, payment timing, and **no annual CPI/energy/FX increase**;
- a complete list of included services and possible extras;
- acceptance test/window, delivery date, billing start, and failure remedy;
- uptime/support/maintenance/replacement commitments and service credits;
- expansion pricing for a second 4-GPU node and/or the 8-GPU alternative;
- termination, renewal, data export, and secure-erasure terms; and
- an order-of-precedence clause making the negotiated proposal prevail over conflicting standard terms.

Do not rely on “no hidden fees,” “same performance,” “around the clock,” “uncontended,” “customisable,” or anything said on the call unless the concrete meaning is written into the proposal.

## After-call decision record

Record these before the information fades:

| Decision input | Answer |
| --- | --- |
| SCAN contact / date | |
| Dedicated physical host confirmed by | |
| Root and software control | |
| Vast/third-party hosting written permission owner | |
| 4-GPU monthly ex VAT / 24-month total | |
| Two 4-GPU nodes monthly ex VAT / total | |
| One 8-GPU node monthly ex VAT / total | |
| Fixed price / escalation | |
| GPU part number and power limit | |
| PCIe/P2P/NCCL evidence promised | |
| Public IPv4 / ports / bandwidth / traffic | |
| Storage build and usable capacity | |
| SLA and hardware replacement target | |
| Pilot and acceptance terms | |
| Delivery date | |
| Open blockers and owners | |

## Official SCAN sources checked

Checked 2 September 2026:

- [4-GPU 3XS SC PB4-32T monthly product page](https://www.scan.co.uk/products/3xs-sc-pb4-32t-1-month-4x-96gb-nvidia-rtx-pro-6000-512gb-ddr5-ecc-amd-epyc-9354p): 4x96 GB RTX PRO 6000, EPYC 9354P, 512 GB ECC, 2 TB NVMe, Ubuntu 24.04 option, £1,999.98 inc VAT for 30 days. Its specification table says EPYC 9354P while a generic feature block incorrectly names a Threadripper PRO 7975WX, reinforcing the need for a contractual build sheet.
- [8-GPU 3XS SC PB8-32T monthly product page](https://www.scan.co.uk/products/3xs-sc-pb8-32t-1-month-8x-96gb-nvidia-rtx-pro-6000-1tb-ddr5-ecc-amd-epyc-9354p): 8x96 GB RTX PRO 6000, the same EPYC 9354P, 1 TB ECC, 2 TB NVMe, Ubuntu 24.04 option, £3,999.98 inc VAT for 30 days.
- [RTX PRO 6000 cloud-workstation range](https://www.scan.co.uk/shop/computer-hardware/cloud-solutions-ai-vgpu/3xs-cloud-workstations-rtx-pro-6000): identifies the line as the flagship workstation RTX PRO 6000 Blackwell and lists 1/2/4/8-GPU weekly and monthly products.
- [SCAN Cloud Solutions](https://www.scan.co.uk/cloud-solutions): says GPU instances include NVMe and uncontended network ports, offers custom-length reserved commitments and customisable IaaS, and markets no extra storage/networking charges. The page does not quantify bandwidth, port access, root privileges, topology, support SLA, or permitted third-party hosting.
- [SCAN business terms](https://www.scan.co.uk/terms-and-conditions/business): the Supplier's Proposal/Service Specification defines the service; website descriptions do not form part of the contract; service charges may rise annually with CPI unless varied; standard termination does not provide a general convenience exit; and the written contract is the entire agreement.
- [SCAN managed accounts](https://www.scan.co.uk/help/scan/corporate-accounts/what-corporate-accounts-do-you-offer): advertises primary and secondary account managers, pre/post-sales support, fault logging, and regular reviews for managed accounts subject to a £10,000 annual minimum spend.

Related technical acceptance procedure: [`SCAN-4X-RTX-PRO-6000-PILOT.md`](SCAN-4X-RTX-PRO-6000-PILOT.md). Cost and utilization assumptions: [`ECONOMICS.md`](ECONOMICS.md).
