# Vast.ai owned-host golden-path runbook

> **Scope:** A dedicated, physically owned GPU server that may be offered cheaply to interruptible bidders while the owner is idle, then reclaimed through Vast's scheduler for the owner's own on-demand instance. This is an operations runbook, not a promise of earnings or a promise that preemption has zero rating impact.
>
> **Source convention:** **Verified** means an official Vast document, the current Host Setup page, or the current official installer/uninstaller was checked. **Inferred** means the workflow combines separately documented features and still needs one controlled end-to-end trial.

## The decision gate

Do not list the machine until everyone responsible for it accepts these facts:

1. **Verified limitation:** Vast has no documented `interruptible-only` host switch. `vastai list machine` exposes both an on-demand GPU price and an optional interruptible minimum bid. A very high on-demand price can make outside on-demand rental unattractive, but cannot make it impossible.
2. **Verified contract rule:** A client rental locks the price, hardware specifications, and offer end date. Repricing, shortening the offer, or unlisting affects future rentals only. It does not end an existing contract.
3. **Verified priority rule:** On-demand and reserved instances have priority over interruptible instances. An interruptible instance may be paused when on-demand is requested; its data remains, and it resumes when it regains priority.
4. **Inferred reclaim workflow:** A free, owner-created on-demand instance on the same machine should pause an outside interruptible instance. Destroying only the owner's instance should return priority, after which the bidder should resume automatically if it is still the winning bid. Vast documents each component, but does not explicitly publish a host-specific "reclaim with no rating effect" guarantee. Validate this once under controlled conditions before relying on it.
5. **Verified maintenance rule:** Unlisting, taking the host offline, restarting Docker, killing a renter container, or using maintenance notice is not the reclaim mechanism. Vast says all rental contracts must be honored and machines should remain online.

If strictly preventing all outside on-demand or reserved rentals is a hard requirement, stop here. The current documented host controls cannot guarantee it.

## Roles, account, and access

Use a dedicated **Team Host Account** for a multi-user owned server. Do not mix client and host use in one individual account; Vast says separate client and hosting accounts are required. The active Individual or Team context owns any machine registered from that context.

Recommended role split:

| Role | Human responsibility | Vast permission groups |
|---|---|---|
| Team owner | Agreement, team membership, payout configuration, emergency recovery | Owner role; keep daily API keys out of this account |
| Host administrator | Install, list/unlist, pricing, maintenance, cleanup | `machine_read`, `machine_write`; add `team_read` only if operationally useful |
| Reclaim operator | Observe host, find own offer, create and destroy only the owner's reclaim instance | `machine_read`, `misc`, `instance_read`, `instance_write` |
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

## Safe owner reclaim

### What platform preemption means

The supported behavior is:

```text
outside interruptible running
        │
        │ owner creates on-demand on same offer/machine
        ▼
outside interruptible paused; its disk retained
        │
        │ owner destroys only owner on-demand instance
        ▼
outside interruptible resumes automatically if it again has priority
```

This differs from:

- **unlisting**, which only blocks new contracts;
- **changing price/minimum bid**, which does not rewrite an existing contract;
- **maintenance notice**, which tells clients to save work for unavoidable maintenance;
- **host shutdown, Docker restart, daemon stop, or container kill**, which creates downtime and can lower reliability.

### Fail-closed prechecks

Before reclaiming:

1. Capture the current reliability score, verification state, daemon status, errors, metrics, and all contracts.
2. Confirm the intended machine ID from `vastai show machines`.
3. Search the machine's offers and select its on-demand offer ID.
4. Confirm no outside on-demand or reserved contract exists. If one exists, **abort**. It has high priority and its contract must be honored.
5. Confirm any outside contract you expect to pause is explicitly interruptible/bid.
6. Confirm the owner workload will fit the currently offered GPU grouping and disk.
7. Record the owner-instance label. Before create, write a private pending marker; after a confirmed response, atomically write the returned owner contract ID to the active state file.

The helper uses `pending-reclaim.json` and an atomic `reclaim.lock/` under `VAST_STATE_DIR` to prevent a second owner create when a process crashes or a network response is uncertain. If either remains, check whether a helper process is still running, then inspect Vast Instances for the recorded label. Destroy a found owner instance through the guarded release override. Clear a stale marker only after the label is absent and no create can still be in flight.

The official CLI only shows the current account's instances. A host operator must also inspect the host's Machines/Contracts view; do not assume `vastai show instances` reveals outside clients.

### Create the owner on-demand instance

```bash
vastai search offers 'machine_id=<MACHINE_ID> verified=any' --type on-demand --raw

vastai create instance <OWN_ON_DEMAND_OFFER_ID> \
  --image <OWNER_WORKLOAD_IMAGE> \
  --disk <OWNER_DISK_GB> \
  --ssh --direct \
  --label owned-reclaim-<CHANGE_ID> \
  --cancel-unavail
```

Again, do not pass `--bid_price`. Parse the returned `new_contract` value and store it as `OWN_INSTANCE_ID`. Wait until:

- the owner instance is `running`;
- the intended outside bid instance is shown as paused by Vast;
- daemon heartbeat, thermals, power, disk, and network remain healthy.

If the outside bid does not transition cleanly, the owner instance does not start, the daemon becomes unknown/offline, or a red error appears, stop the owner attempt by destroying only `OWN_INSTANCE_ID`. Do not touch the outside container.

### Release to the bidder

```bash
vastai show instance <OWN_INSTANCE_ID> --raw
vastai destroy instance <OWN_INSTANCE_ID> -y --raw
```

Before running destroy, match all three: instance ID, machine ID, and owner label. Destroy is irreversible. The `-y` above is appropriate only after that independent check; `release-gpu.sh` performs a stronger typed confirmation first. Never select an ID from host-side Docker output. Treat the operation as complete only when the raw response contains `"success": true`.

Then observe the outside interruptible instance. Vast documents automatic resume when priority returns, but timing is not guaranteed. Capture:

- time owner instance was destroyed;
- time outside bid changes from paused to running;
- reliability/verification before and after;
- any error or failed-start event;
- GPU utilization and direct-port health after resume.

### Trial acceptance criteria

Call the controlled trial successful only if:

- owner on-demand starts without manual host/container intervention;
- outside bid is platform-paused with data retained;
- outside bid auto-resumes after owner instance destruction;
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
| During | owner create response/ID, bidder pause time, owner running time, daemon heartbeat, health extrema |
| After release | owner destroy response/time, bidder resume time, failed starts/errors, health |
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
| Self-test fails ports | Range not reachable end-to-end, TCP/UDP mismatch, CGNAT, or too few ports | Fix router and host firewall; test externally; provide at least five/GPU (100/GPU recommended). |
| Machine does not appear in normal search | Search results show only a subset | Use `vastai search offers 'machine_id=<MACHINE_ID> verified=any'`. |
| On-demand outside rental appears | High price discouraged but did not prohibit it | Abort owner reclaim and honor the contract through its end date. Current docs have no strict interruptible-only switch. |
| Bid renter remains running after owner create | Wrong offer/machine, owner creation stopped, or scheduler did not allocate it | Do not touch renter. Inspect owner create result/status and machine contracts; destroy only a failed owner instance and investigate. |
| Bid renter does not resume after owner release | Priority/bid changed, owner instance still exists, scheduler delay, or client state issue | Confirm owner instance is destroyed and machine/daemon healthy; observe before escalating. Never manually start/kill the renter container. |
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
