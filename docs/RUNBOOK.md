# Vast.ai owned-host golden-path runbook

> **Scope:** A dedicated physical GPU server under full operator control that may be offered cheaply to interruptible bidders, then reclaimed through Vast's documented Host Job scheduler path. The measured two-A100 cycle failed automatic renter return and the rating-safety gate. Owner-created on-demand reclaim remains experimental. This runbook is not a promise of earnings or safe preemption.
>
> **Source convention:** **Verified** means an official Vast document, the current Host Setup page, or the current official installer/uninstaller was checked. **Inferred** means the workflow combines separately documented features and still needs one controlled end-to-end trial.

## The decision gate

Do not list the machine until everyone responsible for it accepts these facts:

1. **Verified limitation:** Vast has no documented `interruptible-only` host switch. `vastai list machine` exposes both an on-demand GPU price and an optional interruptible minimum bid. A very high on-demand price can make outside on-demand rental unattractive, but cannot make it impossible.
2. **Verified contract rule:** A client rental locks the price, hardware specifications, and offer end date. Repricing, shortening the offer, or unlisting affects future rentals only. It does not end an existing contract.
3. **Verified priority rule:** On-demand and reserved instances have priority over interruptible instances. An interruptible instance may be paused when on-demand is requested; its data remains, and it resumes when it regains priority.
4. **Measured Host Job limitation:** A controlled two-A100 Host Job reclaimed both GPUs through Vast's scheduler, but the interruptible client did not auto-resume within more than 79 seconds after release and needed its own Start action. A separate owner on-demand reclaim remains experimental. Vast does not publish a host-specific "reclaim with no rating effect" guarantee, and the measured cycle included a confounded reliability decrease. Keep production reclaim disabled until a clean dedicated-hardware trial passes every acceptance criterion below.
5. **Verified maintenance rule:** Unlisting, taking the host offline, restarting Docker, killing a renter container, or using maintenance notice is not the reclaim mechanism. Vast says all rental contracts must be honored and machines should remain online.

If strictly preventing all outside on-demand or reserved rentals is a hard requirement, stop here. The current documented host controls cannot guarantee it.

## Roles, account, and access

Use a dedicated **Team Host Account** for a multi-user owned server. Do not mix client and host use in one individual account; Vast says separate client and hosting accounts are required. The active Individual or Team context owns any machine registered from that context.

Recommended role split:

| Role | Human responsibility | Vast permission groups |
|---|---|---|
| Team owner | Agreement, team membership, payout configuration, emergency recovery | Owner role; keep daily API keys out of this account |
| Host administrator | Install, list/unlist, pricing, maintenance, cleanup | `machine_read`, `machine_write`; add `team_read` only if operationally useful |
| Reclaim operator | Observe host, start/stop the exact reusable owner instance, or create/destroy only a recorded fresh owner instance | `machine_read`, `misc`, `instance_read`, `instance_write` |
| Observer | Health and earnings review without mutations | `machine_read`; optionally `instance_read` and `billing_read` |

Keep `billing_write`, `team_write`, and `user_write` away from routine operator keys. Team owners/managers can create custom roles in the Team dashboard. Use one API key per operator or automation, name it for its purpose, grant the smallest permission set, and revoke it when unused.

Before generating the installation command:

1. Switch the console to the intended Team Host context.
2. Hard-reload the Host Setup page after switching. The current page can retain an already-loaded installation key in memory across a context switch.
3. Confirm the hosting agreement is accepted in that context and **Machines** is visible in navigation.
4. Confirm the operator doing the install has `machine_read` and `machine_write` in that context.

## Hardware and operating-system preflight

Run these checks on a vacant dedicated server before installing Vast software.

### Published verification minimums

- NVIDIA Maxwell-or-newer GPU, more than 7 GB VRAM, and identical GPU models in one machine.
- CUDA 11.8 or newer; ARM64 requires CUDA 12.6 or newer.
- x86_64 or ARM64 CPU with AVX and at least two physical CPU cores per GPU.
- System RAM at least 95% of aggregate GPU VRAM.
- More than 2.85 GiB/s PCIe bandwidth per GPU.
- Ubuntu Server 22.04 LTS or 24.04 LTS. Desktop editions are unsupported.
- Current security-patched LTS kernel and a currently supported NVIDIA driver.
- Secure Boot disabled.
- SSH key authentication only, password authentication disabled, and a unique SSH key pair for this machine.
- Wired public IPv4 service with at least 500 Mbps upload and download. CGNAT/shared ISP IP is unsupported.
- At least five forwarded ports per GPU; Vast recommends 100 per GPU. A different Host Setup screen has historically shown three as a minimum, but use the stricter current Verification Stages requirement of five.
- SSD storage, at least 200 GB dedicated to Docker container storage, and at least 20 GB free on `/`.
- Reliability over 90% for verification. New machines start lower and grow with stable uptime.

Basic inspection:

```bash
set -o pipefail
cat /etc/os-release
uname -m
lscpu
free -h
nvidia-smi -q
nvidia-smi --query-gpu=index,name,uuid,memory.total,driver_version,temperature.gpu,power.limit --format=csv
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS,MODEL,SERIAL
df -hT / /var/lib/docker 2>/dev/null || true
findmnt /var/lib/docker 2>/dev/null || true
sshd -T | grep -E '^(passwordauthentication|pubkeyauthentication) '
```

Record the GPU count, model, UUIDs, driver, memory, disk device/serial, public port range, and normal idle/load temperatures in a private operations record. Do not commit addresses, serials, keys, or account identifiers to this repository.

### Reliability baseline before any trial

Capture screenshots or private notes for:

- machine reliability score and verification state;
- daemon online state and any red error banner;
- offer state and fixed offer end date;
- every active contract/instance, rental type, status, client end date, and GPU allocation;
- GPU temperatures, power, memory, and utilization;
- free space on `/` and `/var/lib/docker`;
- upload/download measurements and direct-port test result.

This baseline is the evidence needed to assess whether scheduler preemption changes reliability. Vast does not explicitly guarantee zero rating impact.

## Disk layout

Preferred layout: a dedicated SSD/NVMe formatted XFS with project quotas, mounted at `/var/lib/docker`. Do not format a device merely because it looks unused. Match its model, serial, size, partitions, mounts, and filesystem, and confirm it contains no data that must be retained.

### Option A: prepare the dedicated device yourself

The `mkfs` step is destructive. Substitute a verified empty partition, never a whole device by guesswork.

```bash
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS,MODEL,SERIAL
sudo wipefs --no-act /dev/<VERIFIED_EMPTY_PARTITION>

# DESTRUCTIVE after an independent device check:
sudo mkfs.xfs -f /dev/<VERIFIED_EMPTY_PARTITION>
sudo blkid /dev/<VERIFIED_EMPTY_PARTITION>
sudo mkdir -p /var/lib/docker
```

Add a single `/etc/fstab` entry using the UUID returned by `blkid`:

```text
UUID=<UUID> /var/lib/docker xfs rw,auto,pquota 0 0
```

Then mount and verify:

```bash
sudo mount /var/lib/docker
sudo systemctl daemon-reload
findmnt -no SOURCE,FSTYPE,OPTIONS /var/lib/docker
df -hT /var/lib/docker
```

The result should report XFS and a project-quota option (`pquota` or its equivalent). If Docker already has data, stop and use a planned migration; do not mount over it.

### Option B: installer-managed free space

Leave the largest intended area unpartitioned and let the current official installer create its XFS storage. Confirm the intended device in the interactive prompts.

### Option C: loopback storage

Use the installer loopback fallback only for a disposable trial when a dedicated partition is unavailable. It is slower and is not the preferred owned-box layout.

## Network and firewall

Reserve one contiguous direct-port range. Size it at **at least five TCP and five UDP ports per GPU**, with 100 per GPU recommended. The range must reach the host end-to-end through every router and firewall.

1. Give the server a stable LAN address or reservation.
2. Forward the same contiguous range for both TCP and UDP to the host.
3. Allow that range in the host firewall.
4. Keep the administrative SSH port separate. Restrict its source addresses when practical.
5. Test from a genuinely external network, not from the server or the same LAN.
6. Enter the exact start and end values when the installer prompts for the direct-port range.

Do not expose Docker's daemon socket or broad management ports. A public IPv4 address is required; do not proceed behind CGNAT.

## NVIDIA driver and Docker

1. Install a currently supported stable NVIDIA driver for the GPU and Ubuntu LTS release.
2. Reboot before listing, then verify every expected GPU with `nvidia-smi -q`.
3. Stress-test power, cooling, memory, and PCIe before any client rental.
4. Prefer a fresh host and let the official Vast installer configure Docker and NVIDIA Container Toolkit.
5. If Docker is already installed, use the standard installer unless the machine already has the exact Vast-required Docker/XFS setup. `--no-docker` is a recovery path for a correctly configured existing Docker installation, not the default.
6. Disable automatic reboots and unattended driver/kernel changes while rentals can exist. Apply security maintenance only after unlisting and waiting for every contract to end.

## Install the Vast host manager

### Installation-key trap

The Host Setup page generates a temporary, account-context-specific installation key valid for one hour. It is different from a persistent API key.

**Always use the page's Copy button.** The visible command intentionally shows only the first seven characters followed by the literal text `...`; manually selecting the visible line copies the truncated value. A truncated key reaches the identify endpoint and fails with:

```text
auth_error: Invalid user key
```

The Copy button currently supplies the full 64-character key. Never paste either key into chat, a repository, an issue, a screenshot, or command output. Do not substitute a Manage Keys API key.

If the context was switched, hard-reload first, create a fresh one-hour command, press **Copy**, and paste it directly into a private root shell.

### Standard installer

Use the exact command copied from Host Setup. Its current shape is:

```bash
wget https://console.vast.ai/install -O install
sudo python3 install <FULL_ONE_HOUR_INSTALL_KEY_FROM_COPY_BUTTON> --interactive
history -d $((HISTCMD-1))
```

The interactive flow asks for the first and last direct ports. Read every disk and networking prompt before answering. The default installer log is `vast_host_install.log` in the working directory.

### Guided installer

The current guided flow is:

```bash
wget https://s3.amazonaws.com/public.vast.ai/host-installer-wizard-linux-x86_64 -O install-wizard
sudo chmod +x ./install-wizard
wget https://console.vast.ai/install -O install
sudo ./install-wizard --installer-path ./install --api-key <FULL_ONE_HOUR_INSTALL_KEY_FROM_COPY_BUTTON>
history -d $((HISTCMD-1))
```

### Existing-Docker recovery only

```bash
wget https://console.vast.ai/install -O install
sudo python3 install <FULL_ONE_HOUR_INSTALL_KEY_FROM_COPY_BUTTON> --no-docker
history -d $((HISTCMD-1))
```

Do not use `--no-docker` to bypass a failed Docker setup. Fix the host or rerun the standard installer.

## Verify the installation before listing

The official manager lives under `/var/lib/vastai_kaalia`. Do not edit managed files.

```bash
sudo systemctl status vastai --no-pager
sudo journalctl -u vastai -n 100 --no-pager
sudo tail -n 100 /var/lib/vastai_kaalia/kaalia.log
docker info
nvidia-smi
```

Expected results:

- `vastai.service` is active and stays active across a reboot;
- the daemon log shows current heartbeats without repeated identify/auth errors;
- the machine appears once in the intended Team Host context;
- all GPUs, system RAM, storage, and ports are reported correctly;
- there is no persistent red host error.

If the installer created the machine in the wrong account/team context, do not list it. Stop and correct ownership through official support or a clean reinstall in the correct context; do not work around access controls.

### Keep VM mode off

This runbook uses Docker-container hosting. Vast may test and enable VM support on capable idle hosts unless it is explicitly disabled.

```bash
sudo python3 /var/lib/vastai_kaalia/enable_vms.py check
sudo python3 /var/lib/vastai_kaalia/enable_vms.py off
sudo python3 /var/lib/vastai_kaalia/enable_vms.py check
```

The final result must be `off`.

## Install and authenticate the CLI

Install the official CLI on a separate trusted operator machine when possible:

```bash
curl -fsSL https://vast.ai/install.sh | bash
# Alternative: python3 -m pip install --user vastai
```

Create a scoped persistent API key in the intended Team context. For host listing only, grant `machine_read` and `machine_write`. For the reclaim workflow, also grant `misc`, `instance_read`, and `instance_write`.

```bash
vastai set api-key <SCOPED_PERSISTENT_API_KEY>
vastai show user
vastai show machines
```

`vastai set api-key` stores the key in `~/.config/vastai/vast_api_key`. Set restrictive permissions and never copy this file into the repository:

```bash
chmod 600 ~/.config/vastai/vast_api_key
```

Use separate read-only and mutation keys where useful. `billing_read` is sufficient for earnings review. `user_write`, `billing_write`, and `team_write` are not needed by the host/reclaim scripts.

## Self-test while vacant

Vast requires the machine to be listed and have no active clients. Stop all owner jobs too; official verification requires a dedicated machine and says personal workloads cause verification failure.

```bash
vastai show machines
vastai self-test machine <MACHINE_ID>
```

The self-test covers drivers/CUDA, network stability, ports, PCIe bandwidth, VRAM, RAM/CPU, and workload reliability. If it reports `not found or not rentable`, confirm the machine has populated metrics, unlist/relist it, and retry. A diagnostic relaxed test exists:

```bash
vastai self-test machine <MACHINE_ID> --ignore-requirements
```

That flag does not make the host verification-eligible and still requires at least three open direct ports. Do not treat it as a production pass.

Test the client path on the owner account as Vast documents:

```bash
vastai search offers 'machine_id=<MACHINE_ID> verified=any'
vastai create instance <OWN_ON_DEMAND_OFFER_ID> \
  --image pytorch/pytorch:latest \
  --jupyter --direct \
  --env '-e TZ=UTC -p 22:22 -p 8080:8080' \
  --cancel-unavail
```

Do **not** pass `--bid_price`; omission creates an on-demand instance. Verify direct SSH, Jupyter, GPU visibility, disk isolation, and both TCP/UDP port allocation as applicable. Then destroy only the test instance:

```bash
vastai destroy instance <OWN_TEST_INSTANCE_ID>
```

Destroy is irreversible and deletes the instance data. Record the returned contract ID immediately after creation.

## Listing for a cheap interruptible trial

### Choose terms

- Set the on-demand GPU price deliberately unattractive, but understand it remains rentable.
- Set `price_min_bid` to the lowest interruptible price you are actually willing to accept. Vast says the minimum bid is a floor; winning bids may pay more.
- Set `discount_rate 0` to opt out of reserved discounts.
- Set `vol_size 0`; otherwise Vast lists half of available space as a volume offer by default.
- Set a short **fixed** `end_date`, expressed as a Unix timestamp or date accepted by the CLI. Do not use rolling `--duration` for this trial.
- Set `min_chunk` to the intended GPU grouping. To avoid multiple simultaneous client contracts on a multi-GPU machine, use the full GPU count.
- Price disk and bandwidth consciously. Do not use placeholders as live values.

Use current host market metrics, not stale examples:

```bash
vastai metrics gpu --raw
```

### Exact listing shape

```bash
vastai list machine <MACHINE_ID> \
  --price_gpu <UNATTRACTIVE_ON_DEMAND_PRICE_PER_GPU_HOUR> \
  --price_min_bid <MINIMUM_INTERRUPTIBLE_PRICE_PER_GPU_HOUR> \
  --price_disk <DISK_PRICE_PER_GB_MONTH> \
  --price_inetu <UPLOAD_PRICE_PER_GB> \
  --price_inetd <DOWNLOAD_PRICE_PER_GB> \
  --discount_rate 0 \
  --min_chunk <GPU_COUNT_OR_INTENDED_GROUP_SIZE> \
  --end_date <FIXED_END_EPOCH_OR_MM/DD/YYYY> \
  --vol_size 0
```

Verify both pricing views:

```bash
vastai search offers 'machine_id=<MACHINE_ID> verified=any' --type on-demand --raw
vastai search offers 'machine_id=<MACHINE_ID> verified=any' --type bid --raw
```

Confirm there is no volume offer and that the end date is correct. The end date stops the offer from accepting new rentals; existing jobs remain through their locked contract end.

Changing only the bid floor later:

```bash
vastai set min-bid <MACHINE_ID> --price <NEW_MINIMUM_BID_PER_GPU_HOUR>
```

This changes future bid acceptance. Do not use it to evict an existing renter.

### Required controlled second-account reclaim trial

Do not wait for an unknown public renter to validate reclaim. Vast's official hosting guide documents a separate client account on a different email as a supported way to test the full client experience. Prepare that account before exposing the offer:

1. Keep the machine in the dedicated host account. Stage an official Host Job below the planned client bid, and create the stopped owner on-demand test standby while vacant.
2. Create and authenticate a separate operator-controlled client account, add enough credit for the short test, and prepare its exact-machine CLI search/create commands.
3. For the first test, set `min_chunk` to the full GPU count and have the controlled client request every exposed GPU. Sample P99 from bid-offer `min_bid`, which is the renter-facing whole-machine hourly total. Convert that total to host `price_min_bid` per GPU before listing: at the currently observed four-thirds renter surcharge, `host floor = renter P99 * 0.75 / GPU count`. Re-derive the live factor from the exact offer. The recorded two-A100 snapshot was `$1.60/machine-hour`, so its two-GPU host floor was `$0.60/GPU-hour`. A percentile price is a deterrent, not an allowlist.
4. List only when the client command is ready. Search by exact machine ID, verify the exact offer's machine-total `min_bid`, create the controlled interruptible instance immediately with a whole-machine `--bid_price` above it, and verify the returned instance belongs to the intended machine and has the full GPU allocation. The recorded test used `--bid_price 1.61` against `min_bid=1.60`. Never multiply the offer's `min_bid` by GPU count.
5. Unlist the machine as soon as that controlled contract is proven running. Unlisting now blocks any further contracts while preserving the controlled test contract.
6. The live two-A100 test found that Host Jobs remained inert while the machine was unlisted and scheduled only after relisting. Under the same guarded full-GPU listing, relisting produced two one-GPU jobs. A host input of `$1.30/GPU-hour` appeared as `dph_base=$1.733333` on each and preempted the `$1.61/machine-hour` two-GPU client; `$0.65/GPU-hour` appeared as `$0.866667` each and did not. Treat this only as measured behavior, not a scheduler formula. Watch continuously for unexpected contracts during the required relist window.
7. After reclaim, lower the Host Job and measure resume. In the live test the client did not auto-resume within more than 79 seconds and required the controlled client's **Start** action. Record this as a failed automatic-resume threshold even when guarded Start recovers it.
8. Separately start the exact pre-created owner on-demand test standby, measure platform pause/reclaim, stop it, and measure controlled-client resume with the same guarded Start fallback.
9. Destroy the controlled client instance, clear its storage, and keep the host unlisted while reviewing the evidence. If reliability changes during failed-container and reclaim events, preserve both timelines and make no rating-safety claim because the causes are confounded.

There remains a short race between listing and controlled acquisition because Vast exposes no documented private or account-allowlisted offer. Abort and honor the contract if any unexpected client wins first. On a sliced multi-GPU test, fill every exposed slice from controlled client accounts before unlisting; never leave an advertised GPU available to an unknown client.

Follow the complete schedule, metrics, aborts, pass thresholds, delayed rating checks, and four-GPU adaptation in [`CONTROLLED-2H-2XA100-TRIAL.md`](CONTROLLED-2H-2XA100-TRIAL.md).

## Safe owner reclaim

### Owner-workload policy status

Vast's Verification Stages guide says hosts must run their own workloads through Host **Jobs**. The current CLI command is `set defjob`; the console calls this Create Job. A Host Job is a persistent low-priority background bid. It does not have an owner-only priority class:

```text
controlled interruptible bid B running
        │
        │ set Host Job value above B
        ▼
controlled interruptible paused; Host Job should run
        │
        │ lower Host Job value below B
        ▼
controlled interruptible resumes if it again has priority
```

Create or update the job with the image and value already reviewed for that exact machine:

```bash
vastai set defjob <MACHINE_ID> \
  --price_gpu <OWNER_VALUE_PER_GPU_HOUR> \
  --price_inetu 0 \
  --price_inetd 0 \
  --image <OWNER_WORKLOAD_IMAGE> \
  --args /bin/bash -lc '<OWNER_COMMAND>'
```

`--args` consumes the remainder of the command and must be last. Inspect `vastai show machines --raw` for the default-job fields. `remove defjob` deletes the job; it is not a pause/release control and storage persistence across deletion is undocumented.

The Host Job API has no GPU-count parameter. Do not assume one job on a multi-GPU machine gets one GPU or every GPU. The two-A100 run produced two one-GPU Host Job records, but that fan-out is not guaranteed on other topologies. It also found that Host Jobs scheduled only after the machine was relisted. The two-hour trial must measure `CUDA_VISIBLE_DEVICES` and `nvidia-smi -L`, and must abort on overlapping assignment.

The observed high/low values were asymmetric with the client's whole-machine bid: host `$1.30/GPU-hour` became renter-side `dph_base=$1.733333` on each one-GPU Host Job and preempted a two-GPU client bidding `$1.61/machine-hour`; host `$0.65/GPU-hour` became `$0.866667` per job and did not. Do not encode those observations as a general comparison formula. After lowering the owner jobs, the client remained stopped for more than 79 seconds and needed client **Start**. Until a repeat proves otherwise, the release controller must detect this state, fail the automatic-resume target, and use only the exact controlled client's guarded Start action.

Host Jobs cannot preempt outside on-demand or reserved rentals. They can only win over lower interruptible bids. Vast does not promise zero rating impact for an operator-triggered bid change, so keep the same immediate and delayed rating checks. The live run recorded a reliability decrease during a cycle that also contained a failed container launch; that confounding prevents attribution and supports no rating-safety claim.

### Experimental on-demand reclaim

Vast separately documents a free own-machine on-demand instance for testing. It has stronger deterministic priority than a Host Job because on-demand outranks every interruptible bid. The following pre-created standby workflow is therefore retained for the controlled reclaim experiment and tooling validation. Do not present it as the approved ongoing owner-workload policy until Vast confirms that use in writing.

### What platform preemption means

The preferred workflow keeps one reusable owner instance stopped between experiments:

```text
outside interruptible running
        │
        │ owner starts exact pre-created on-demand instance
        ▼
outside interruptible paused; its disk retained
        │
        │ owner stops exact owner instance; both disks retained
        ▼
outside interruptible resumes automatically if it again has priority
```

A stopped instance preserves the owner's disk and continues to incur storage charges. It does not reserve a GPU. The live trial showed the owner's GPU charge at zero on its own host while each retained 20 GB disk cost about $0.00556/hour on the client side. Keep enough client credit to cover every standby: the Instances page warns that instances may be stopped or deleted when the client balance reaches zero, even though the same account owns the host. Do not rely on future host earnings arriving before that balance is consumed.

Restart still asks the scheduler for the GPU, so this design prevents a full tenant disk from blocking owner disk allocation but does not guarantee GPU availability or host-versus-tenant preemption. Fresh create/destroy remains a secondary path when no reusable ID is configured.

This differs from:

- **unlisting**, which only blocks new contracts;
- **changing price/minimum bid**, which does not rewrite an existing contract;
- **maintenance notice**, which tells clients to save work for unavoidable maintenance;
- **host shutdown, Docker restart, daemon stop, or container kill**, which creates downtime and can lower reliability.

### Fail-closed prechecks

Before reclaiming:

1. Capture the current reliability score, verification state, daemon status, errors, metrics, and all contracts.
2. Confirm the intended machine ID from `vastai show machines`.
3. Confirm the configured reusable instance ID, or search the machine's offers and select its on-demand offer ID for a fresh create.
4. Confirm no outside on-demand or reserved contract exists. If one exists, **abort**. It has high priority and its contract must be honored.
5. Confirm any outside contract you expect to pause is explicitly interruptible/bid.
6. For a reusable instance, match its exact ID, machine ID, dedicated owner label, `is_bid=false`, GPU count and original offer where available. Require the fail-closed stopped-state proof: `actual_status` is one of `created`, `exited`, or `stopped`, while `intended_status=stopped` and `cur_state=stopped`. Reject missing fields and every other actual state.
7. Confirm the owner workload fits the reviewed GPU grouping and its fixed disk allocation.
8. Review the instance end date and replace an expiring reusable standby while the host is safely vacant.

The helpers use mode-tagged state and an atomic `reclaim.lock/` under `VAST_STATE_DIR`. Precreated mode writes active `start-pending` state before starting. Fresh mode writes `pending-reclaim.json` before creating. If state or the lock remains, check whether a helper is running and inspect the recorded exact instance and label. Use guarded release to stop a precreated attempt. Clear state manually only after independently proving the intended postcondition.

The official CLI only shows the current account's instances. A host operator must also inspect the host's Machines/Contracts view; do not assume `vastai show instances` reveals outside clients.

A same-account interruptible instance is not a valid substitute for the client side of this test. In the controlled September 2026 trial, Vast rejected an owner on-demand create on the same offer while that account's interruptible instance occupied the GPU with HTTP 400, error 3763 (`GPU conflict`). Use the separately authenticated, operator-controlled client account described above. It exercises a distinct client contract without accepting an unknown workload.

### Prepare the reusable owner standby while vacant

Do this once before accepting outside rentals, or when intentionally replacing the standby. The host must be vacant and the exact on-demand offer reviewed:

```bash
vastai create instance <OWN_ON_DEMAND_OFFER_ID> \
  --image <OWNER_WORKLOAD_IMAGE> \
  --disk <OWNER_DISK_GB> \
  --ssh --direct \
  --label owned-reclaim-standby \
  --cancel-unavail --raw

vastai show instance <OWN_INSTANCE_ID> --raw
vastai stop instance <OWN_INSTANCE_ID> --raw
vastai show instance <OWN_INSTANCE_ID> --raw
```

Do not pass `--bid_price`. Persist required owner data, then stop the exact instance. Do not trust the start/stop command's text or exit code as proof: Vast CLI 1.5.6 prints human output under `--raw` and can exit zero for unsuccessful responses. A live safely stopped instance that never fully started reported `actual_status=created`, `intended_status=stopped`, and `cur_state=stopped`; a normally stopped instance may report `actual_status=exited`. Poll `show instance` until the exact record satisfies the explicit stopped-state proof above. Also record the exact ID, machine ID, label, `is_bid=false`, GPU count, offer ID when present, disk size, image, end date, and all three raw state fields in private operations records.

Set these values in the private `.env`:

```bash
VAST_MACHINE_ID=<MACHINE_ID>
VAST_OWN_OFFER_ID=<OWN_ON_DEMAND_OFFER_ID>
VAST_OWN_INSTANCE_ID=<OWN_INSTANCE_ID>
VAST_OWN_LABEL_PREFIX=owned-reclaim
VAST_GPU_COUNT=<EXPECTED_GPU_COUNT>
```

The ID selects precreated mode. Any validation failure aborts. The helper contains no fallback from this mode to a fresh create.

### Start the reusable owner instance

Preview, review Host Machines/Contracts, then apply:

```bash
./scripts/reclaim-gpu.sh
./scripts/reclaim-gpu.sh --contracts-reviewed --apply
```

Apply asks for `START <INSTANCE_ID> ON <MACHINE_ID>`, repeats the exact stopped-instance proof under its lock, persists `mode: precreated` and `status: start-pending`, then starts only that ID. It polls for up to 30 seconds. Success requires the same exact record to report all three status fields as `running`. An uncertain or stuck start retains active state; run the guarded release to stop/cancel that exact attempt. Never create a replacement while a tenant is active.

Vast documents that scheduling beyond roughly 30 seconds usually means the GPU is unavailable. A stopped standby protects disk allocation but has no GPU reservation. Addresses and ports can change after restart, so obtain fresh connection details after running is confirmed.

### Fresh create fallback

Leave `VAST_OWN_INSTANCE_ID` blank only when deliberately accepting a fresh disk allocation at reclaim time. The helper then previews this flow:

```bash
vastai search offers 'machine_id=<MACHINE_ID> verified=any' --type on-demand --raw

vastai create instance <OWN_ON_DEMAND_OFFER_ID> \
  --image <OWNER_WORKLOAD_IMAGE> \
  --disk <OWNER_DISK_GB> \
  --ssh --direct \
  --label owned-reclaim-<CHANGE_ID> \
  --cancel-unavail
```

Again, do not pass `--bid_price`. The helper writes a pending marker before create, parses the returned ID, persists `mode: fresh-created`, and retains uncertain state rather than repeating the call. Wait until:

- the owner instance is `running`;
- the intended outside bid instance is shown as paused by Vast;
- daemon heartbeat, thermals, power, disk, and network remain healthy.

If the outside bid does not transition cleanly, the owner instance does not start, the daemon becomes unknown/offline, or a red error appears, release only the recorded owner instance. Do not touch the outside container.

### Release to the bidder

Preview and apply through the mode-aware helper:

```bash
./scripts/release-gpu.sh
./scripts/release-gpu.sh --apply
```

For `precreated`, release matches the exact ID, machine, label, on-demand type, expected GPU count, and offer where exposed. It asks for `STOP <INSTANCE_ID>`, repeats identity validation under the lock, runs only `vastai stop instance <ID> --raw`, and polls until the exact record satisfies the stopped-state allowlist. Only then does it archive the per-reclaim active state. The instance and disk remain for the next experiment. If it already satisfies that proof, the helper reconciles state without issuing a duplicate mutation.

For `fresh-created`, release asks for `RELEASE <INSTANCE_ID>` and uses guarded destroy:

```bash
vastai show instance <OWN_INSTANCE_ID> --raw
vastai destroy instance <OWN_INSTANCE_ID> --yes --raw
```

Before running destroy, match all three: instance ID, machine ID, and owner label. Destroy is irreversible. The `--yes` above is appropriate only after that independent check; `release-gpu.sh` performs a stronger typed confirmation first. Never select an ID from host-side Docker output.

Vast CLI 1.5.6 can destroy successfully yet emit no JSON from `destroy instance ... --yes --raw`; the command wrapper does not always forward the underlying response. The helper accepts either an explicit JSON `"success": true` or a strict postcondition: `show instance <ID> --raw` must return the absent sentinel (`{"instances": null}`), and `show instances --raw` must use a recognized list shape with no matching ID. If those two checks do not agree after bounded retries, it retains active state and reports failure.

Recovery overrides require all of `--mode`, `--instance-id`, `--machine-id`, and `--expected-label`. This prevents a lost precreated state file from silently defaulting to destructive release.

Then observe the outside interruptible instance. Vast documents automatic resume when priority returns, but timing is not guaranteed. Capture:

- time owner instance was stopped or destroyed;
- time outside bid changes from paused to running;
- reliability/verification before and after;
- any error or failed-start event;
- GPU utilization and direct-port health after resume.

### Trial acceptance criteria

Call the controlled trial successful only if:

- the interruptible renter is the exact separately authenticated controlled-client contract, not a same-account self-bid or unknown public client;
- owner on-demand starts without manual host/container intervention;
- outside bid is platform-paused with data retained;
- outside bid auto-resumes after owner instance stop or destruction;
- daemon stays online throughout;
- no client-start failure or red error appears;
- reliability does not materially fall after the platform updates it;
- storage and direct ports remain healthy.

**Zero rating impact is not explicitly guaranteed by Vast documentation.** A successful single trial is evidence, not a blanket guarantee.

## Monitoring and abort criteria

Monitor at least:

```bash
vastai show machines --raw
vastai show instances --raw
vastai search offers 'machine_id=<MACHINE_ID> verified=any' --raw
sudo systemctl is-active vastai
sudo tail -n 100 /var/lib/vastai_kaalia/kaalia.log
nvidia-smi --query-gpu=index,temperature.gpu,power.draw,power.limit,memory.used,utilization.gpu --format=csv
df -hT / /var/lib/docker
```

Use alert thresholds based on the owned hardware's validated cooling and power envelope; this runbook does not invent universal temperature cutoffs.

Abort a new reclaim or listing change when:

- any contract type cannot be established confidently;
- an outside on-demand/reserved contract exists;
- the daemon is inactive, unknown, or repeatedly reconnecting;
- a red host error or failed client start appears;
- GPU, power, thermal, disk, network, or direct-port health is outside the box's validated envelope;
- the owner instance ID/label/machine triple is ambiguous;
- the offer end date or price differs from the reviewed values.

When already rented, preserving the contract takes priority. Stop only the owner's workload. Do not kill client containers, stop Docker, reboot, or power down as an automated response.

## Reliability measurement

For each reclaim test, keep a small change record:

| Phase | Capture |
|---|---|
| Before | UTC time, reliability, verification, daemon online, red errors, contracts/types/statuses, GPU/disk/network health |
| During | owner mode and exact ID, start/create response, bidder pause time, owner running time, daemon heartbeat, health extrema |
| After release | owner stop/destroy postcondition and time, bidder resume time, failed starts/errors, health |
| Delayed check | reliability/verification after platform update, earnings interval, client status |

Vast says losing host connection or a client instance failing to start lowers reliability. It does not publish a statement that intended scheduler preemption has zero rating impact. Treat unchanged reliability as something to measure, not assume.

## Maintenance and notice

Planned maintenance:

1. Set a short fixed end date for future rentals.
2. Unlist to stop new rentals.
3. Wait until **every** active contract reaches its own end date and no client instance remains.
4. Perform the work while vacant.
5. Re-run health checks and self-test before relisting.

Unlisting command:

```bash
vastai unlist machine <MACHINE_ID>
```

For genuinely unplanned/unscheduled maintenance, Vast documents:

```bash
vastai schedule maint <MACHINE_ID> \
  --sdate <UTC_EPOCH_SECONDS> \
  --duration <HOURS> \
  --maintenance_category <power|internet|disk|gpu|software|other>
```

The current CLI then asks for `y` confirmation and accepts fractional hours. The rendered CLI reference has also used `schedule maintenance` in its Usage line, but the current registered command and examples use `schedule maint`. The REST API has a maintenance-reason field; the current CLI does not document a `--maintenance_reason` option.

This notifies the client to save work. Vast's public host documentation does not publish a numeric minimum notice period. It is not a routine reclaim tool, does not end a contract, and is not documented as eliminating reliability or reputation consequences.

## Earnings and payouts

- Review current rental earnings and payout history in the Host Earnings area. `billing_read` is the read-only API permission for invoices/earnings.
- Pricing and utilization depend on hardware, price, uptime/reliability, location, and current demand. Earnings are not guaranteed.
- Vast currently supports Wise, PayPal, and Stripe payouts.
- The minimum payout threshold is USD 20; smaller balances roll forward.
- Invoices are generated weekly on Fridays when a valid payout method is connected and the balance meets the threshold.
- A first payout typically takes up to two weeks: invoice pending on one Friday, submitted the next Friday, then provider processing time.
- `Paid` means Vast submitted the payout to the provider, not that the provider has settled it.
- The current Host Setup console states that the former host fee was removed and the prices hosts set are what hosts earn; re-check the current hosting agreement and live console before making a purchase decision because fee terms can change.

For a token trial, report gross rental earnings, utilization hours, power consumed, reclaim success, resume delay, and any reliability movement. Keep owned-hardware economics separate from this technical runbook.

## Clean unlist, storage cleanup, and uninstall

### Stop accepting new rentals

```bash
vastai unlist machine <MACHINE_ID>
vastai search offers 'machine_id=<MACHINE_ID> verified=any rentable=any rented=any' --no-default --raw
```

Unlisting prevents new contracts. Wait for every existing client contract and any rented volume to end. If a volume offer was created despite `--vol_size 0`, identify its volume ID and unlist it:

```bash
vastai unlist volume <VOLUME_ID>
```

After expired/deleted contracts exist and the machine is online, ask Vast to reconcile their storage:

```bash
vastai cleanup machine <MACHINE_ID>
```

This clears expired/deleted contract state. It is not permission to delete live client data. Confirm the reclaimed free space in the console and with `df`.

### Remove the host manager

Only uninstall after all of these are true:

- machine is unlisted;
- no active or paused client contract exists;
- no rented volume exists;
- every owner test/reclaim instance is destroyed;
- required records and owner data are backed up;
- the server is no longer expected to honor an offer end date.

Download the official current script, inspect it, and keep Docker unless removal is a separate reviewed change:

```bash
wget https://s3.amazonaws.com/vast.ai/uninstall -O uninstall
less ./uninstall
sudo python3 ./uninstall --keep-docker
```

The current script stops/disables the Vast services and removes Vast-managed files. It reports that XFS and the NVIDIA driver are not removed. Its `--keep-docker` flag avoids the interactive Docker removal path. Preserve `vast_host_uninstall.log` privately for the change record.

Do not format or repurpose the client-storage disk until the unlist/contract/volume checks above are complete.

## Troubleshooting

| Symptom | Likely cause | Safe action |
|---|---|---|
| `auth_error: Invalid user key` / identify 404 before Docker setup | The visible Host Setup command was selected and its literal `...` truncation was copied; key expired; wrong account/team context | Switch to intended context, hard-reload, generate a fresh command, use **Copy**, and paste the full 64-character one-hour installation key. Do not use a persistent API key. |
| 403 when creating/copying installer command | Hosting agreement not accepted in active context, key expired, or team role lacks machine access | Accept/review agreement in that context, confirm Machines nav and `machine_read`/`machine_write`, hard-reload, create a fresh key. |
| Daemon absent or repeatedly restarts | Installer failed or host dependency/disk issue | Read `vast_host_install.log`, `journalctl -u vastai`, and `/var/lib/vastai_kaalia/kaalia.log`; keep machine unlisted while fixing. |
| Duplicate or wrong-context machine | Installer run in wrong context or repeated registration | Do not list. Verify active context and use official support/clean reinstall; do not edit daemon identity files. |
| VM status `on` or `pending` | Capable idle machine was eligible for automatic VM enablement | While safe/vacant, run `sudo python3 /var/lib/vastai_kaalia/enable_vms.py off`, then check for `off`. |
| Self-test says `not found or not rentable` | Machine not listed or metrics/ports/RAM/speeds missing | Confirm vacant, populate/fix host metrics, unlist/relist, retry. |
| Self-test briefly says `No such container: C.<id>` during its first run | The controller asked for logs before assigning/creating the test container while the large test image was still downloading or its wrapper was building | Check that image pull/build activity continues and the daemon remains healthy. Let the test proceed and trust its later `TESTED`/`DONE` markers. Do not restart services or delete the cached image for this line alone. A controller-requested stop/remove may subsequently leave exit code 137 during normal test cleanup. |
| Self-test fails ports | Range not reachable end-to-end, TCP/UDP mismatch, CGNAT, or too few ports | Fix router and host firewall; test externally; provide at least five/GPU (100/GPU recommended). |
| Machine does not appear in normal search | Search results show only a subset | Use `vastai search offers 'machine_id=<MACHINE_ID> verified=any'`. |
| On-demand outside rental appears | High price discouraged but did not prohibit it | Abort owner reclaim and honor the contract through its end date. Current docs have no strict interruptible-only switch. |
| Owner on-demand create returns HTTP 400 / error 3763 `GPU conflict` during a same-account self-bid test | Vast will not use that account's on-demand instance to preempt its own interruptible instance on the occupied GPU | Destroy only the same-account test instance through its verified ID if one exists. Mark the trial invalid, then repeat only through the documented separate controlled client account; do not accept an unknown renter or alter renter containers/host services. |
| Precreated reclaim refuses to start | Exact ID/machine/label/on-demand/GPU/offer check failed, the record did not report `actual_status=created|exited|stopped` with `intended_status=stopped` and `cur_state=stopped`, or the standby expired | Do not clear the ID or fall back to create while rented. Resolve the exact mismatch; replace the standby only while safely vacant. |
| `start instance` or `stop instance` prints success-like text but state does not change | CLI 1.5.6 does not provide authoritative machine-readable start/stop results, or scheduling/stop is delayed | Trust only bounded polling of the exact `show instance` record. A start requires `running/running/running`; a stop requires the explicit non-running actual-state allowlist plus both stopped control fields. Run guarded release to stop a stuck start and retain state if the appropriate proof fails. |
| Bid renter remains running after owner create | Wrong offer/machine, owner creation stopped, or scheduler did not allocate it | Do not touch renter. Inspect owner create result/status and machine contracts; destroy only a failed owner instance and investigate. |
| Destroy exits successfully but prints no JSON with `--raw` | CLI 1.5.6 may not forward the destroy response from its command wrapper | Verify the exact ID returns `{"instances": null}` from `show instance` and is absent from `show instances`. `release-gpu.sh` performs both checks and keeps active state unless both prove absence. |
| Bid renter does not resume after owner release | Priority/bid changed, reusable owner does not satisfy the safe stopped-state proof, fresh owner still exists, scheduler delay, or client state issue | Confirm the mode-specific release postcondition and machine/daemon health; observe before escalating. Never manually start/kill the renter container. |
| Reliability drops | Host disconnect or client start failure; other causes may exist | Compare before/during/after record, daemon logs, health and failed starts. Keep host online; stop new listings while diagnosing. |
| Disk stays allocated after expired/deleted rental | Contract cleanup out of sync | Keep host online and run `vastai cleanup machine <MACHINE_ID>`; never delete live client paths manually. |
| Need urgent host work | Unplanned maintenance | Schedule official maintenance notice, protect client data, minimize downtime. Notice is not a penalty waiver. |

## Official sources checked

- [Hosting overview](https://docs.vast.ai/host/hosting-overview)
- [Verification stages and minimums](https://docs.vast.ai/host/verification-stages)
- [How to self-test](https://docs.vast.ai/host/how-to-self-test)
- [VM configuration](https://docs.vast.ai/host/vms)
- [Instance types and interruptible priority/resume](https://docs.vast.ai/guides/instances/choosing/instance-types)
- [`list machine`](https://docs.vast.ai/cli/reference/list-machine)
- [`set min-bid`](https://docs.vast.ai/cli/reference/set-min-bid)
- [`unlist machine`](https://docs.vast.ai/cli/reference/unlist-machine)
- [`schedule maint`](https://docs.vast.ai/cli/reference/schedule-maint)
- [Current official CLI machine-command source](https://github.com/vast-ai/vast-cli/blob/master/vastai/cli/commands/machines.py)
- [`search offers`](https://docs.vast.ai/cli/reference/search-offers)
- [`create instance`](https://docs.vast.ai/cli/reference/create-instance)
- [`start instance`](https://docs.vast.ai/cli/reference/start-instance)
- [`stop instance`](https://docs.vast.ai/cli/reference/stop-instance)
- [Managing instances and stopped storage](https://docs.vast.ai/guides/instances/manage-instances)
- [`show instances`](https://docs.vast.ai/cli/reference/show-instances)
- [`destroy instance`](https://docs.vast.ai/cli/reference/destroy-instance)
- [API permission groups](https://docs.vast.ai/api-reference/permissions)
- [API keys](https://docs.vast.ai/guides/reference/api-keys)
- [CLI setup](https://docs.vast.ai/cli/hello-world)
- [Team roles](https://docs.vast.ai/guides/teams/teams-roles)
- [Managing a team](https://docs.vast.ai/guides/teams/managing-teams)
- [Host market optimization](https://docs.vast.ai/host/optimization-guide)
- [Market metrics](https://docs.vast.ai/host/market-metrics)
- [Host payouts](https://docs.vast.ai/host/payment)
- [Earnings page](https://docs.vast.ai/host/earning)
- [Official uninstall script](https://s3.amazonaws.com/vast.ai/uninstall)

Re-check the official Host Setup page, hosting agreement, CLI reference, and payout guide before each new physical host installation; these controls and terms can change.
