# Vast.ai owned-host golden-path runbook

> **Scope:** A dedicated physical GPU server under full operator control that may offer explicitly released capacity to Vast. Three clean Host Job attempts left the interruptible renter running. A later exact pre-created owner on-demand standby paused the controlled renter, reached running in 82.281 seconds, stopped, and returned the renter automatically. This proves one technical scheduler cycle, but Sqwish's rating-safe production gate remains **BLOCKED** because the machine was already below its immutable original reliability baseline and the delayed observation did not complete. This runbook is not a promise of earnings or penalty-free preemption.
>
> **Source convention:** **Verified** means an official Vast document, the current Host Setup page, or the current official installer/uninstaller was checked. **Inferred** means the workflow combines separately documented features and still needs one controlled end-to-end trial.

## Future-agent entry point

The desired loop is to list idle GPUs, reclaim them when research arrives, then return them to the market. The controlled two-A100 pilot demonstrated that loop once with a pre-created own-machine **on-demand** standby: the exact interruptible paused, owner start completed inside 15 minutes, owner stop succeeded, and the renter returned automatically. Host Jobs still did not work as a reclaim mechanism. Keep the standby path diagnostic until it passes repeated dedicated-box cycles at or above the immutable original reliability baseline, including delayed observations, and Vast clarifies whether ongoing research workloads belong on this own-machine path or only its Jobs path.

Use these documents in order:

1. This runbook covers the dedicated-box prerequisites, hard storage boundary, Vast installation, listing, normal operations, and teardown.
2. [`SCAN-4X-RTX-PRO-6000-PILOT.md`](SCAN-4X-RTX-PRO-6000-PILOT.md) applies the prerequisites and staged topology tests to the intended four-GPU box.
3. [`CONTROLLED-2H-2XA100-TRIAL.md`](CONTROLLED-2H-2XA100-TRIAL.md) is the full acceptance schedule, including controlled acquisition, sliced-GPU phases, and delayed observations.
4. [`CLEAN-HOSTJOB-CYCLE.md`](CLEAN-HOSTJOB-CYCLE.md) is the narrow, fail-closed rerun of the previously confounded Host Job phase. Its controller assumes that the exact controlled renter is already running and the host is already unlisted.
5. [`A100-2X-LIVE-TRIAL.md`](A100-2X-LIVE-TRIAL.md) is historical evidence. Read its failures as constraints, not as steps to repeat.
6. [`INCIDENT-CLOUD-MINER.md`](INCIDENT-CLOUD-MINER.md) explains why marketplace hosting must not be tested on a third-party cloud VM without written provider approval.

### Current proof state

| Claim | Status | Operational consequence |
|---|---|---|
| A dedicated XFS Docker pool can bound Vast's total host storage away from `/` | **Proved on the two-A100 trial** | Recreate and verify the boundary on the delivered box before installing Vast. |
| A separate controlled account can acquire the exact full-machine interruptible and the host can immediately unlist | **Proved once** | Repeat with an exact machine, offer, label, GPU-count, and account-identity proof. |
| A Host Job can take both GPUs from a running interruptible contract | **Failed in three clean attempts** | High inputs of $1.10 for 30 seconds, $1.30 for 90 seconds, and $3.00/GPU-hour for 120 seconds left the renter running. Price is not a documented preemption control. |
| Owner reclaim completes within 15 minutes | **Proved once with an exact pre-created on-demand standby** | Decision-to-owner-running was 82.281 seconds. Vast publishes no self-preemption latency SLA; repeat on the dedicated box before scheduling around it. |
| A pre-created free own-machine on-demand standby can pause an interruptible | **Proved once diagnostically** | The exact two-GPU controlled interruptible reached the safe-stopped tuple before the owner was accepted as running. This does not authorize arbitrary host/container eviction. |
| A displaced renter returns automatically | **Proved once diagnostically** | After exact owner stop, the same controlled interruptible returned without fallback Start. Repeat and verify checkpoint integrity on the dedicated box. |
| Reclaim has no reliability or rating cost | **Not proved** | Reliability started at 0.5999925, briefly reached 0.599997, then fell to 0.5727243 during the restart/new-client sequence. The later successful standby handoff stayed flat at 0.5727243 immediately and after cleanup, but remained below the original baseline and lacked a delayed check. |
| One-, two-, and four-GPU owner jobs assemble and release four independent slices correctly | **Unproved** | Run the staged four-GPU qualification; never extrapolate the two-A100 result. |

### Production operating modes

Do not run an automated public-renter reclaim loop. Choose one of these modes:

1. **Explicit release:** researchers mark a GPU or whole node available for the full advertised contract window. List only that released capacity.
2. **Drain:** unlist to block new contracts, wait for every existing contract to reach its locked end date, prove vacancy, and then schedule research work.
3. **Reserve:** keep enough GPUs permanently unlisted for burst demand and sell only surplus capacity that the team can leave untouched.

The controlled acquisition, Host Job controller, and owner-standby controller remain diagnostic tools. They are not production reclaim automation.

## The decision gate

Do not list the machine until everyone responsible for it accepts these facts:

1. **Verified limitation:** Vast has no documented `interruptible-only` host switch. `vastai list machine` exposes both an on-demand GPU price and an optional interruptible minimum bid. A very high on-demand price can make outside on-demand rental unattractive, but cannot make it impossible.
2. **Verified contract rule:** A client rental locks the price, hardware specifications, and offer end date. Repricing, shortening the offer, or unlisting affects future rentals only. It does not end an existing contract.
3. **Verified priority rule:** On-demand and reserved instances have priority over interruptible instances. Among interruptibles, higher bids have priority. A paused interruptible retains its data and resumes when it regains priority. This rule does not say a Host Job price evicts a renter.
4. **Measured Host Job limitation:** The official `set defjob` page describes a background job and its price field; it publishes no renter-preemption behavior, latency SLA, or rating exemption. Clean Host Job inputs of $1.10/30 seconds, $1.30/90 seconds, and $3.00/GPU-hour/120 seconds did not pause the controlled renter. Keep production reclaim disabled.
5. **Measured standby result:** The exact owner on-demand standby reached running in 82.281 seconds while the exact interruptible moved to its safe-stopped tuple. Exact owner stop then returned that renter automatically without fallback. A separate post-pilot probe proved a real two-GPU PyTorch CUDA workload on the standby.
6. **Measured reliability result:** The machine began at 0.5999925, briefly reached 0.599997, and fell to 0.5727243 during a restart/new-client sequence before the clean handoff attempts. The successful standby cycle was 0.5727243 before takeover, immediately after it, and after cleanup. Flat observations below the immutable original baseline do not establish rating safety, and the delayed check was skipped at the disposable host's preconfigured automatic-deletion deadline.
7. **Verified maintenance rule:** Unlisting, taking the host offline, restarting Docker, killing a renter container, or using maintenance notice is not a reclaim mechanism. Vast says all rental contracts must be honored and machines should remain online.

Sqwish's chosen market shape is a prohibitively high reviewed outside on-demand price, zero reserved discount, and an attractive comparable-market P10 interruptible price. The 15-minute model admits only interruptible tenants. Treat any outside on-demand or reserved contract as an invariant violation: unlist, do not attempt owner takeover, and honor that contract through its locked end. The controller must check this live rather than inferring it from the configured prices.

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

For controlled qualification, keep the host and client CLI credentials in separate private configuration directories and expose them through two different wrapper executables. Each wrapper must unset inherited `VAST_API_KEY` and set its own `HOME`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, and `XDG_STATE_HOME`; changing `HOME` alone does not isolate the account. Do not accept different filenames as proof of different accounts. Query the authenticated identity through each wrapper and require two distinct positive account IDs before any listing or reclaim mutation. [`CLEAN-HOSTJOB-CYCLE.md`](CLEAN-HOSTJOB-CYCLE.md) defines the wrapper and identity checks. Never pass a persistent API key on a command line or write any credential into the repository. The official host installer currently accepts its separate one-hour installation credential as an argument; the bounded exception and its residual process-list exposure are documented below.

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

The low initial score is expected platform behavior, not a value the controller can raise. Vast says a stable new machine typically grows past 90% within a few days. Preserve continuous uptime: the trial's restart is a plausible explanation for the observed `0.5999925` to `0.5727243` movement, although the evidence cannot isolate causation. The same verification page says personal workloads can automatically fail verification, while the host-responsibility section says host work must use Jobs or `create job`. Before adopting the own-machine on-demand standby for daily research, obtain Vast's written interpretation and decide whether production owner work must use the Jobs path. A successful scheduler handoff alone does not qualify the host.

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

### Set a hard exposure cap

The reliable storage limit is the size of the dedicated filesystem mounted at `/var/lib/docker`. Keep the root filesystem, research datasets, checkpoints, and the rest of the server's capacity outside that mount. Vast's `--vol_size 0` disables a separate volume offer; it does **not** cap renter instance disks or Docker image layers.

Size the pool from the current Vast minimum plus the smallest operating margin that covers reviewed images, controlled test disks, stopped owner disks, and cleanup headroom. The two-A100 trial used 250 GB, which was the then-current 200 GB machine minimum plus 25%. The four-GPU pilot proposes 350-400 GB because it must hold more minimal disks and image/checkpoint margin. These are planning caps, not Vast guarantees; re-check the current minimum before partitioning the delivered box.

Before every listing, account for all consumers of this same pool:

- cached and unpacked image layers;
- every running, stopped, paused, expired, or deleted-but-not-yet-reconciled instance disk;
- retained owner-standby disks;
- Vast's own storage allowance and filesystem headroom.

Set the controlled client's disk explicitly to the minimum the reviewed workload needs. Refuse a new listing or reclaim when the Docker pool is above the validated threshold; the controlled trial uses below 70% used and at least 50 GB free. Do not run `vastai cleanup machine` until every affected contract is proven ended, and never delete live client paths by hand.

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

If the context was switched, hard-reload first, create a fresh one-hour command,
press **Copy**, and paste the key only into the hidden prompt in the private root
flow below.

### Standard installer

Download the installer without executing it. Obtain its expected SHA-256 through
an independent authenticated Vast channel, such as a digest supplied by support,
and compare it before granting root privileges. If Vast cannot supply a digest,
stop and resolve that trust decision rather than treating HTTPS or a second
download from the same URL as independent verification.

```bash
sudo -i
install -d -m 700 /root/vast-host-install-review
cd /root/vast-host-install-review
umask 077
curl --proto '=https' --tlsv1.2 --fail --location \
  https://console.vast.ai/install --output install
read -r -p 'Paste independently supplied installer SHA-256: ' vast_install_sha256 </dev/tty
printf '%s  %s\n' "$vast_install_sha256" install | sha256sum --check --strict
unset vast_install_sha256
python3 -m py_compile install
set +o history
read -r -s -p 'Paste one-hour Vast installation key: ' vast_install_key </dev/tty
printf '\n' >/dev/tty
python3 install "$vast_install_key" --interactive
unset vast_install_key
set -o history
```

The interactive flow asks for the first and last direct ports. Read every disk
and networking prompt before answering. The default installer log is
`vast_host_install.log` in the working directory. The one-hour key is not placed
in shell history or a file, but the installer's required argument can be visible
briefly in the process list. Run it only in a private root session on the
dedicated host with no untrusted local users. Ask Vast for an stdin/file-based
credential path before using the installer on a shared system.

### Guided installer

The guided installer is a native binary. Do not execute it as root until its
exact digest has been independently supplied and verified. Prefer the
inspectable standard Python installer above. If the guided flow is required:

```bash
sudo -i
install -d -m 700 /root/vast-host-install-review
cd /root/vast-host-install-review
umask 077
curl --proto '=https' --tlsv1.2 --fail --location \
  https://s3.amazonaws.com/public.vast.ai/host-installer-wizard-linux-x86_64 \
  --output install-wizard
read -r -p 'Paste independently supplied wizard SHA-256: ' vast_wizard_sha256 </dev/tty
printf '%s  %s\n' "$vast_wizard_sha256" install-wizard | sha256sum --check --strict
unset vast_wizard_sha256
chmod 700 ./install-wizard
curl --proto '=https' --tlsv1.2 --fail --location \
  https://console.vast.ai/install --output install
read -r -p 'Paste independently supplied installer SHA-256: ' vast_install_sha256 </dev/tty
printf '%s  %s\n' "$vast_install_sha256" install | sha256sum --check --strict
unset vast_install_sha256
python3 -m py_compile install
set +o history
read -r -s -p 'Paste one-hour Vast installation key: ' vast_install_key </dev/tty
printf '\n' >/dev/tty
./install-wizard --installer-path ./install --api-key "$vast_install_key"
unset vast_install_key
set -o history
```

### Existing-Docker recovery only

```bash
# First download and independently verify ./install exactly as above.
sudo -i
cd /root/vast-host-install-review
set +o history
read -r -s -p 'Paste one-hour Vast installation key: ' vast_install_key </dev/tty
printf '\n' >/dev/tty
python3 install "$vast_install_key" --no-docker
unset vast_install_key
set -o history
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

Install the official CLI on a separate trusted operator machine when possible.
Do not pipe a network response directly into a shell. Download it, inspect it,
record its digest, and compare that digest with an independently authenticated
Vast value before executing it:

```bash
umask 077
curl --proto '=https' --tlsv1.2 --fail --location \
  https://vast.ai/install.sh --output vast-cli-install.sh
read -r -p 'Paste independently supplied CLI installer SHA-256: ' vast_cli_sha256 </dev/tty
printf '%s  %s\n' "$vast_cli_sha256" vast-cli-install.sh \
  | sha256sum --check --strict
unset vast_cli_sha256
less vast-cli-install.sh
bash vast-cli-install.sh
```

Create a scoped persistent API key in the intended Team context. For host listing only, grant `machine_read` and `machine_write`. For the reclaim workflow, also grant `misc`, `instance_read`, and `instance_write`.

```bash
install -d -m 700 ~/.config/vastai
umask 077
read -r -s -p 'Paste scoped Vast API key: ' vast_scoped_key </dev/tty
printf '\n' >/dev/tty
printf '%s\n' "$vast_scoped_key" > ~/.config/vastai/vast_api_key
unset vast_scoped_key
chmod 600 ~/.config/vastai/vast_api_key
vastai show user
vastai show machines
```

The CLI reads the same `~/.config/vastai/vast_api_key` file. Writing it from a
hidden, non-exported shell variable avoids exposing the persistent key through
`vastai set api-key ...` process arguments. Never copy this file into the
repository, logs, chat, or evidence.

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
PYTORCH_TAG=pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime
PYTORCH_DIGEST="$(docker buildx imagetools inspect "$PYTORCH_TAG" | awk '$1 == "Digest:" {print $2; exit}')"
[[ "$PYTORCH_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]
OWNER_IMAGE="${PYTORCH_TAG}@${PYTORCH_DIGEST}"

vastai search offers 'machine_id=<MACHINE_ID> verified=any'
vastai create instance <OWN_ON_DEMAND_OFFER_ID> \
  --image "$OWNER_IMAGE" \
  --jupyter --direct \
  --env '-e TZ=UTC -p 22:22 -p 8080:8080' \
  --cancel-unavail
```

Review the resolved manifest before use and retain the exact `tag@sha256` value in private operations state. Do **not** pass `--bid_price`; omission creates an on-demand instance. Verify direct SSH, Jupyter, GPU visibility, disk isolation, and both TCP/UDP port allocation as applicable. Then destroy only the test instance:

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

Treat the listing command's output and exit status as a request result, not proof of the live offer. Re-query the exact machine and fail closed unless **every** resulting on-demand and bid offer has the expected machine and GPU count, full-machine `min_chunk`, exact fixed end, no rolling duration, zero reserved discount, expected renter-facing prices, and no volume offer. Also prove the host machine itself reports the expected total GPU count; a two-GPU client on a machine that actually exposes more GPUs is not a full-machine controlled test. Missing or non-finite fields fail the check. The previously recorded trial silently missed its intended fixed end, so a typed command is never enough.

Changing only the bid floor later:

```bash
vastai set min-bid <MACHINE_ID> --price <NEW_MINIMUM_BID_PER_GPU_HOUR>
```

This changes future bid acceptance. Do not use it to evict an existing renter.

### Required controlled second-account reclaim trial

Do not wait for an unknown public renter to validate reclaim. Vast's official hosting guide documents a separate client account on a different email as a supported way to test the full client experience. Prepare that account before exposing the offer:

1. Keep the machine in the dedicated host account. Stage a diagnostic Host Job while vacant, and create any stopped owner on-demand test standby only for a separately approved experiment.
2. Create and authenticate a separate operator-controlled client account, add enough credit for the short test, and prepare its exact-machine CLI search/create commands.
3. For the owner-standby pilot, set `min_chunk` to the full GPU count and have the controlled client request every exposed GPU. Sample P10 from comparable bid-offer `min_bid` values, which are renter-facing whole-machine hourly totals. Convert that total to host `price_min_bid` per GPU before listing: at the observed four-thirds renter surcharge, `host floor = renter P10 * 0.75 / GPU count`. Re-derive the factor from the exact offer. The final 17-comparable snapshot produced `$0.7466667/machine-hour` P10 and a `$0.28/GPU-hour` host floor. A percentile price is a market setting, not an allowlist.
4. List only when the client command is ready. Search by exact machine ID, verify the exact offer's machine-total `min_bid`, create the controlled interruptible instance once with a unique label and a whole-machine `--bid_price` that clears it, and verify the returned instance belongs to the intended machine and has the full GPU allocation. Never multiply the offer's `min_bid` by GPU count. The final outside on-demand deterrent was `$5.84/GPU-hour` host-side, or `$15.5733/hour` for the renter-visible pair; reserved discount was zero.
5. Unlist the machine as soon as that controlled contract is proven running. Unlisting now blocks any further contracts while preserving the controlled test contract.
6. The clean live attempts relisted under the same guarded full-GPU terms and raised the Host Job to `$1.10/GPU-hour` for 30 seconds, `$1.30/GPU-hour` for 90 seconds, and `$3.00/GPU-hour` for 120 seconds. None preempted the controlled renter. An earlier mixed sequence appeared to fan out two one-GPU owner records and pause the renter, but it included a malformed owner launch and other confounding state changes; do not use it as proof of a supported handoff.
7. End the Host Job test after its bounded timeout. Do not keep raising its price in search of an undocumented threshold.
8. Separately start the exact pre-created owner on-demand test standby. The final diagnostic reached clean owner running and safely stopped the controlled interruptible in 82.281 seconds. Stop the exact owner, then measure controlled-client return; the same renter returned automatically and no guarded Start was used.
9. Destroy the controlled client instance only after unlisting and exact absence proofs, retain or remove the standby according to its explicit cleanup authorization, and keep the host unlisted while reviewing the evidence. The final cleanup left no contracts or offers.

There remains a short race between listing and controlled acquisition because Vast exposes no documented private or account-allowlisted offer. Abort and honor the contract if any unexpected client wins first. On a sliced multi-GPU test, fill every exposed slice from controlled client accounts before unlisting; never leave an advertised GPU available to an unknown client.

Observed acquisition pitfalls:

- A standby-preparation listing with `10/10` host price inputs returned HTTP 422. The previously accepted `price_gpu=5.84` and `price_min_bid=3` preparation shape was used instead, then every live offer field was re-read. Treat accepted numeric ranges as API behavior to verify, not a documented limit.
- Creating the own-machine standby with `--cancel-unavail` returned the false-ownership error even though the authenticated account owned the exact offer. Only while vacant, prove that the failed response created no instance, then retry once without `--cancel-unavail`; never automate this retry during a rental.
- The acquisition preflight normally rejects every host-account target-machine instance. When a pre-created standby exists, allow exactly one configured ID and label only after proving exact machine, `is_bid=false`, full GPU count, and the safe stopped tuple. Any extra or malformed target record still aborts. This exact standby allowance prevents the safety check from rejecting the intended preparation without weakening it for unknown instances.
- Bid and on-demand search views can appear and disappear independently while a listing propagates. Prove both exact offer types once, then require the exact bid offer to remain continuously stable for at least 30 seconds immediately before the single create call. Reset the stability clock on any empty or mismatched response.
- A published fixed-end ask can still return structured HTTP 400 `no_such_ask` at create time. Treat that response as a definite no-contract result, unlist, and reconcile both account inventories; do not retry the non-idempotent create blindly.
- The two-hour-plus fixed ask became searchable but produced `no_such_ask`. Twelve-hour asks were launchable. Vast publishes no minimum offer horizon or propagation SLA, so do not encode the observed boundary as a platform rule.
- When the controlled renter became active, the exact bid view's `min_bid` reflected its active bid rather than the original listing floor. Capture both values and do not fail cleanup or cycle preflight merely because that live field moved from the floor to the accepted bid.
- `vol_size=0` disables the separate volume offer; it does not cap an instance disk or the total Docker pool. Specify the controlled disk explicitly (10 GB in this trial) and enforce a separate physical XFS Docker boundary.
- Ordinary self-test requires the machine to be listed and vacant. Verification additionally requires reliability above 90% and 500 Mbps symmetric networking. `--ignore-requirements` is diagnostic only. This can make strict self-test unavailable to a fresh low-reliability host; it is not a reason to keep restarting or relisting it.
- Avoid reboots and public-IP changes after registration. Vast tells unverified hosts to maintain steady uptime and avoid unnecessary reboots, and says lost connectivity can reduce reliability. The trial's score drop occurred during a restart/new-client sequence, so treat restart as a production gate event rather than routine setup.

Follow the complete schedule, metrics, aborts, pass thresholds, delayed rating checks, and four-GPU adaptation in [`CONTROLLED-2H-2XA100-TRIAL.md`](CONTROLLED-2H-2XA100-TRIAL.md).

After the exact controlled client is running and two consecutive searches prove the host unlisted, use [`CLEAN-HOSTJOB-CYCLE.md`](CLEAN-HOSTJOB-CYCLE.md) for the corrected Host Job-only rerun. Do not hand-transcribe that sequence: the controller compares the two authenticated account IDs, rejects unexpected existing Host Jobs, verifies the machine and client both represent exactly two GPUs, requires a digest-pinned reviewed image, and records strict mutation postconditions.

## Owner-workload experiments — production reclaim blocked

### Owner-workload policy status

Vast's Verification Stages guide says hosts must run workloads through the Jobs tab or `create job` CLI path. The current host CLI command `set defjob` creates a background job and accepts a per-GPU price. Neither that page nor the `set defjob` reference defines the price as a renter-preemption control. The following is the hypothesis that failed in the clean two-A100 attempts:

```text
controlled interruptible bid B running
        │
        │ raise Host Job value (experimental)
        ▼
expected: controlled interruptible pauses; observed: renter kept running
        │
        │ lower Host Job value below B
        ▼
resume phase is reachable only after a clean displacement
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

For the clean qualification cycle, refuse to overwrite an unexpected existing Host Job. A zero exit code from `set defjob`, `list machine`, `unlist machine`, or `remove defjob` is not proof of success. Re-query the exact machine and exact owner-job records after every mutation. Verify all prices, including upload and download, the digest-pinned image, argument vector, fixed listing terms, and the exact new job IDs. Cleanup must prove both the machine definition and only those newly created owner records absent.

Use a reviewed CUDA image pinned by registry digest and a bounded owner command. The clean controller accepts only the reviewed `pytorch/pytorch` CUDA image form, makes no package-install or unrelated network calls, checks exactly one visible GPU per fanned-out job, performs synchronized finite matrix multiplications for at most three minutes, and preserves both job logs. Do not use a miner, GPU-burn package, open-ended stress loop, or an argument string that swallows errors. Run the exact owner definition while vacant before depending on it for reclaim; a malformed owner launch makes both scheduler and rating observations inconclusive.

The Host Job API has no GPU-count parameter. Do not assume one job on a multi-GPU machine gets one GPU or every GPU. An earlier mixed run produced two one-GPU Host Job records, but the clean attempts did not reach owner execution. Fan-out, scheduling, and preemption are not guaranteed on other topologies or even repeatable on this one.

Do not encode a Host Job-versus-renter price formula. In the clean attempts, values far above the controlled renter's bid still did nothing within 30, 90, and 120 seconds. The official docs publish no threshold or latency. Price can express the background job's value without granting it an owner-only priority class.

Vast documents on-demand/reserved as the high-priority instance types and client interruptibles as a bid-ranked low-priority class. It does not document Host Jobs as a way to evict any rental type. The full trial's reliability moved from 0.5999925 (briefly 0.599997) to 0.5727243 during the restart/new-client sequence before the clean attempts. The three clean failed attempts stayed at 0.5727243 immediately. The later successful on-demand standby handoff was also 0.5727243 before, immediately after, and after cleanup; this is limited immediate evidence, not a production rating pass, because the score was already below the original baseline and the delayed checkpoint was unavailable.

### Experimental on-demand reclaim

Vast separately documents a free own-machine on-demand instance for testing. It has stronger deterministic priority than a Host Job because on-demand outranks every interruptible bid. The following pre-created standby workflow is therefore retained for the controlled reclaim experiment and tooling validation. Do not present it as the approved ongoing owner-workload policy until Vast confirms that use in writing.

This is the only current candidate for a scheduler-native 15-minute Sqwish start without permanently reserving a GPU. One diagnostic cycle reached owner running in 82.281 seconds, paused the interruptible safely, and returned it automatically after owner stop. Its acceptance timer begins when the research scheduler requests capacity and ends only when the exact owner instance and workload are ready, not when the API accepts `start`. Production qualification still requires at least two repeated cycles within 15 minutes and every immediate and delayed reliability observation at or above the machine's immutable original baseline. The host guide also says client and host accounts should be separate while calling the own-machine test instance free; obtain Vast's written clarification on the supported account topology, retained-disk or marketplace charges, and personal research workloads versus the Jobs requirement.

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

### Measured owner-standby golden path

This is the shortest path that completed the technical handoff. It remains a qualification procedure:

1. While vacant, capture and permanently pin the machine's original reliability. Never replace it with a lower run-local baseline. Refuse mutations below it unless the operator explicitly selects the already-degraded disposable-host diagnostic override; that override can never establish production readiness.
2. List briefly for standby preparation with the exact full-machine on-demand shape. A `10/10` input pair returned HTTP 422 in the pilot; the known accepted `price_gpu=5.84`, `price_min_bid=3`, zero-reserved-discount shape worked. Re-query rather than assuming those values will remain accepted.
3. Create one exact own-machine on-demand instance with a dedicated label and minimal reviewed disk. If `--cancel-unavail` returns the observed false-ownership error, prove no instance exists, then retry once without that flag while the machine is still vacant.
4. Start the standby once while vacant, prove the expected GPUs, stop it, and require `actual_status=created|exited|stopped`, `intended_status=stopped`, and `cur_state=stopped`. Record its exact ID, label, machine, mode, GPU count, disk, image, and offer privately.
5. Sample current comparable interruptible offers. The successful snapshot used 17 records: renter whole-pair P10 `$0.7466667/hour`, host floor `$0.28/GPU-hour`, outside on-demand `$5.84/GPU-hour` host-side (`$15.5733/hour` renter pair), and reserved discount zero.
6. Open one bounded public acquisition window with `min_chunk=2`, `vol_size=0`, a fixed end, and a 10 GB controlled-client disk. Configure acquisition to allow only the exact safely stopped owner standby; every other target-machine host record aborts.
7. From the separately authenticated controlled-client account, issue one exact-machine interruptible create. Prove its ID, label, machine, bid type, two-GPU allocation, and `running/running/running` state. Unlist immediately and require three clean bid/on-demand absence samples.
8. Run `tools/controlled_owner_standby_cycle.py` without `--apply`. It must prove distinct accounts, the exact two-instance inventories, clean machine health/reports, the immutable baseline gate, exact standby stopped state, exact renter running state, and no outside on-demand/reserved contract. Inspect the private plan.
9. Apply interactively. The controller unlists again as its first mutation, re-proves absence, re-checks reliability and inventories, then starts only the exact owner standby. It never stops Vast, Docker, a service, or a renter container.
10. Count the research-start SLO from the decision before unlisting until exact owner `running/running/running` with the controlled interruptible safely stopped. The pilot took **82.281 seconds**, within the 15-minute target.
11. Stop and retain the exact owner standby. Require the full safe-stopped tuple, then observe the exact controlled renter. The pilot renter returned automatically; the evidence-gated fallback Start was not used.
12. Capture immediate reliability, unlist again, prove absence, destroy only the explicitly authorized controlled renter, prove final no-contract/no-offer state, and capture post-cleanup reliability. The pilot stayed at `0.5727243` at both checkpoints, below original `0.5999925`. Its delayed check was skipped at the disposable host's preconfigured automatic-deletion deadline, so the rating gate failed.
13. After controlled cleanup, the retained owner standby passed a real two-GPU PyTorch CUDA probe. Record that as workload-path evidence separate from the handoff timing, then stop the standby again.

Repeat at least two clean cycles on the dedicated box, with immediate and delayed scores at or above the immutable original baseline, before considering this operational. Written Vast clarification on ongoing personal research workloads versus the required Jobs path remains a separate gate.

### Prepare the reusable owner standby while vacant

Do this once before accepting outside rentals, or when intentionally replacing the standby. The host must be vacant and the exact on-demand offer reviewed:

```bash
vastai create instance <OWN_ON_DEMAND_OFFER_ID> \
  --image <OWNER_WORKLOAD_IMAGE> \
  --disk <OWNER_DISK_GB> \
  --ssh --direct \
  --label owned-reclaim-standby \
  --raw

vastai show instance <OWN_INSTANCE_ID> --raw
vastai stop instance <OWN_INSTANCE_ID> --raw
vastai show instance <OWN_INSTANCE_ID> --raw
```

Do not pass `--bid_price`. The vacant-host preparation omits `--cancel-unavail` because that flag produced a false-ownership response on the exact own-machine offer; if testing the flag again, prove its failed response created nothing before one vacant-only retry. Persist required owner data, then stop the exact instance. Do not trust the start/stop command's text or exit code as proof: Vast CLI 1.5.6 prints human output under `--raw` and can exit zero for unsuccessful responses. A live safely stopped instance that never fully started reported `actual_status=created`, `intended_status=stopped`, and `cur_state=stopped`; a normally stopped instance may report `actual_status=exited`. Poll `show instance` until the exact record satisfies the explicit stopped-state proof above. Also record the exact ID, machine ID, label, `is_bid=false`, GPU count, offer ID when present, disk size, image, end date, and all three raw state fields in private operations records.

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

Apply asks for `START <INSTANCE_ID> ON <MACHINE_ID>`, repeats the exact stopped-instance proof under its lock, persists `mode: precreated` and `status: start-pending`, then starts only that ID. The basic shell helper polls for 30 seconds; the controlled standby controller measures the full configurable SLO up to 15 minutes and observed 82.281 seconds. Success requires the same exact record to report all three status fields as `running`. An uncertain or stuck start retains active state; run the guarded release to stop/cancel that exact attempt. Never create a replacement while a tenant is active.

A stopped standby protects disk allocation but has no GPU reservation. The measured takeover needed more than 30 seconds, so use the explicit 15-minute research SLO rather than treating the shell helper's short poll as a scheduler failure. Addresses and ports can change after restart, so obtain fresh connection details after running is confirmed.

### Fresh create fallback

Leave `VAST_OWN_INSTANCE_ID` blank only when deliberately accepting a fresh disk allocation at reclaim time. Set `VAST_OWN_IMAGE` to the reviewed `pytorch/pytorch` CUDA `tag@sha256` value resolved above; the helper rejects an empty value, a mutable tag, another registry/repository, and a non-CUDA image. It then previews this flow:

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

Before running destroy, match all three: instance ID, machine ID, and owner label. Destroy is irreversible. Vast CLI 1.5.6 prompts for confirmation unless `--yes` is supplied; the helpers first obtain a stronger typed confirmation, then pass `--yes` so their captured-output subprocess cannot block on an invisible prompt. Never select an ID from host-side Docker output.

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

Vast says losing host connection or a client instance failing to start lowers reliability. It does not publish a statement that intended scheduler preemption has zero rating impact. In this trial the score moved from 0.5999925 (briefly 0.599997) to 0.5727243 during the restart/new-client sequence. It then stayed at 0.5727243 across the clean failed Host Job attempts and at the before/immediate/post-cleanup checkpoints of the successful owner-standby handoff. The latter is useful immediate evidence, but it remained below the immutable original baseline and lacked the delayed checkpoint.

No local script can set or directly raise this platform score. Vast's
[Verification Stages](https://docs.vast.ai/host/verification-stages#reliability)
guide says a new machine starts low and grows as it remains online, with a
stable machine typically reaching 90% within a few days. The operational way
to improve it is steady uptime, clean client launches, healthy ports/network,
and avoiding unnecessary restarts or configuration churn.

Before the clean qualification soak, enable the shared owner-workload HOLD:

```bash
python3 tools/verification_guard.py --enable-qualification-mode --machine-id "$VAST_MACHINE_ID"
python3 tools/verification_guard.py --sample --machine-id "$VAST_MACHINE_ID"
```

The first command writes the HOLD before it contacts Vast, so a CLI, parsing,
or inventory failure remains fail-closed. The observer is read-only: it records
the platform score/state, reports, error fields, current owner inventory, the
official prerequisites exposed in the machine record, and the reliability
trend. It labels SSH policy, Secure Boot, server edition, physical-core mapping,
dedicated SSD layout, root free space, VM support, sustained uptime, and hidden
bottlenecks as manual checks when the API cannot prove them.

While the marker is active, `prepare_owner_standby.py`,
`controlled_owner_standby_cycle.py`, and `scripts/reclaim-gpu.sh` refuse the
owner mutation before listing or starting anything. Use the same private
`VAST_STATE_DIR` for every helper. Do not bypass the marker by changing the
state directory.

For the combined 24-hour pilot only, prepare one exact standby while the host
is vacant, prove the full stopped tuple, and then enable the HOLD with
`--allowed-owner-standby INSTANCE_ID:LABEL`. The guard permits only that stopped
record and still blocks its start. Because Vast does not state whether a
stopped personal instance record affects verification, label this first arm a
qualification-trend observation. A strict verification control has no owner
instance and no takeover arm.

Keep the host dedicated and free of private background workloads while it is
qualifying. Controlled Vast rental workloads may exercise it, but owner work
must follow Vast's Jobs/Create Job guidance. Run the ordinary Self-Test once
while the machine is vacant, then preserve steady uptime and configuration.
`--ignore-requirements` remains a diagnostic pressure test only. Vast's current
minimum is reliability **strictly over 90%**, 500 Mbps symmetric networking,
and the other requirements in the linked guide; eligibility does not guarantee
immediate verification.

When deliberately ending the clean soak, use:

```bash
python3 tools/verification_guard.py --disable-qualification-mode --machine-id "$VAST_MACHINE_ID"
```

This archives the mode transition and removes the local block. It does not make
the owner on-demand standby part of the Jobs framework or certify it as
verification-safe. Follow
[`CONTROLLED-24H-VERIFICATION-AND-HANDOFF-PILOT.md`](CONTROLLED-24H-VERIFICATION-AND-HANDOFF-PILOT.md)
to keep the clean soak and research-first handoffs separate.

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

For a controlled cycle, cleanup is ordered and fail-closed even after an exception, Ctrl-C, or termination signal:

1. Unlist first and require three consecutive exact-machine samples with both on-demand and bid offers absent. A preflight absence sample taken before the first mutation cannot authorize later destruction.
2. Only after step 1 succeeds, remove the Host Job definition created by the cycle, then prove its machine fields and every recorded owner bid ID absent. If step 1 fails, retain the owner jobs, treat capacity state as unresolved, and reconcile the listing immediately. If an unexpected Host Job existed before the cycle, preflight should have aborted rather than overwriting it.
3. Destroy the controlled client only if a state-changing cycle began, the post-mutation unlist proof passed, and both the single-instance and full-list views still prove the exact ID, machine, label, bid type, and GPU count. Require explicit JSON success or exact absence from both views. If unlisting or identity proof is uncertain, retain the client and state for manual reconciliation.
4. Capture immediate and post-cleanup reliability, verification, reports, and machine-error fields. Keep the result provisional until the mandatory delayed observation finishes.
5. Reconcile ended storage only after no active or paused contract or rented volume remains.

This order avoids converting a failed safety check into a public, vacant listing or deleting the only controlled renter while the machine may still be exposed.

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
| Standby-preparation listing returns HTTP 422 for `10/10` price inputs | The API rejected that numeric listing shape even though the CLI accepted the command syntax | Keep the host vacant/unlisted, inspect the response body, and use a previously live-accepted bounded preparation shape such as `5.84/3` only after revalidating every postcondition. Do not infer a universal price limit. |
| Own-machine standby create with `--cancel-unavail` claims the offer is not owned | Observed false-ownership bug on exact host-owned offers | Prove the failed call created no instance. Only while vacant, retry once without `--cancel-unavail`; never apply this retry pattern during a rental. |
| Owner on-demand create returns HTTP 400 / error 3763 `GPU conflict` during a same-account self-bid test | Vast will not use that account's on-demand instance to preempt its own interruptible instance on the occupied GPU | Destroy only the same-account test instance through its verified ID if one exists. Mark the trial invalid, then repeat only through the documented separate controlled client account; do not accept an unknown renter or alter renter containers/host services. |
| Precreated reclaim refuses to start | Exact ID/machine/label/on-demand/GPU/offer check failed, the record did not report `actual_status=created|exited|stopped` with `intended_status=stopped` and `cur_state=stopped`, or the standby expired | Do not clear the ID or fall back to create while rented. Resolve the exact mismatch; replace the standby only while safely vacant. |
| `start instance` or `stop instance` prints success-like text but state does not change | CLI 1.5.6 does not provide authoritative machine-readable start/stop results, or scheduling/stop is delayed | Trust only bounded polling of the exact `show instance` record. A start requires `running/running/running`; a stop requires the explicit non-running actual-state allowlist plus both stopped control fields. Run guarded release to stop a stuck start and retain state if the appropriate proof fails. |
| Bid renter remains running after owner create | Wrong offer/machine, owner creation stopped, or scheduler did not allocate it | Do not touch renter. Inspect owner create result/status and machine contracts; destroy only a failed owner instance and investigate. |
| Destroy exits successfully but prints no JSON with `--raw` | CLI 1.5.6 may not forward the destroy response from its command wrapper | Pass `--yes` after the helper's typed confirmation so the command cannot wait on an invisible prompt. Then verify the exact ID returns `{"instances": null}` from `show instance` and is absent from `show instances`. `release-gpu.sh` performs both checks and keeps active state unless both prove absence. |
| Bid renter does not resume after owner release | Priority/bid changed, reusable owner does not satisfy the safe stopped-state proof, fresh owner still exists, scheduler delay, or client state issue | Confirm the owner-release postcondition and machine/daemon health. In a controlled test, record and fsync the automatic-return failure before the separate client account issues one guarded Start of the same exact instance; this still fails the gate. A host cannot do that for a public renter. Never start or kill a renter container from the host. |
| Acquisition refuses because the intentionally pre-created owner standby exists | General no-host-instance guard was used without the exact standby allowance | Configure exactly one allowed standby ID and label, then prove same machine, `is_bid=false`, full GPU count, and safe stopped tuple. Any extra target record remains an abort. |
| Host Jobs do not preempt the controlled interruptible | Host Jobs are background jobs; the official docs do not define their price as a preemption lever | End the bounded test, preserve exact snapshots, unlist, and clean up. Do not keep increasing price. Use explicit-release, drain, or reserved-capacity production modes. |
| Owner jobs fail immediately or logs do not prove the expected GPUs/work | Image, `--args` ordering, CUDA compatibility, or workload error | Lower/remove only the recorded owner definition, unlist, preserve logs and rating snapshots, and do not retry while rented. Validate a digest-pinned bounded job while vacant before a new cycle. Treat that run's rating result as confounded. |
| Listing or Host Job mutation exits zero but live fields do not match | Vast CLI command output is not an authoritative postcondition | Unlist when safe, retain controlled state, and fail the cycle. Continue only after the exact machine, every exact offer, and every exact owner record agree with the requested fields. |
| Controlled cleanup cannot prove the host unlisted after a cycle began | API delay/error or wrong machine/context | Do not remove the owner Host Jobs or destroy the controlled client. Treat capacity state as unresolved; the retained jobs may be active or inactive, and the fixed end only limits new offers. Preserve state and reconcile the exact machine and both account contexts immediately. |
| Machine or client GPU count is not exactly the planned full-machine count | Wrong shape, stale offer, slicing, or extra GPUs remain exposed | Unlist and abort. Never treat a partial controlled allocation as proof that unknown acquisition is impossible. |
| Ordinary self-test refuses a new low-reliability machine | Verification requires reliability above its threshold | Keep the host stable and online until eligible. A relaxed self-test is diagnostic only and does not verify or qualify the machine. |
| Cloud provider reports marketplace-tenant abuse | Third-party hosting was not approved or an unknown workload ran | Stop accepting contracts, preserve evidence, remove only the exact disposable hosting resources, and follow [`INCIDENT-CLOUD-MINER.md`](INCIDENT-CLOUD-MINER.md). Do not resume hosting on that provider without written approval. |
| Reliability drops | Host disconnect or client start failure; other causes may exist | Compare before/during/after record, daemon logs, health and failed starts. Keep host online; stop new listings while diagnosing. |
| Disk stays allocated after expired/deleted rental | Contract cleanup out of sync | Keep host online and run `vastai cleanup machine <MACHINE_ID>`; never delete live client paths manually. |
| Need urgent host work | Unplanned maintenance | Schedule official maintenance notice, protect client data, minimize downtime. Notice is not a penalty waiver. |

## Official sources checked

- [Hosting overview](https://docs.vast.ai/host/hosting-overview)
- [Verification stages and minimums](https://docs.vast.ai/host/verification-stages)
- [How to self-test](https://docs.vast.ai/host/how-to-self-test)
- [VM configuration](https://docs.vast.ai/host/vms)
- [Instance types and interruptible priority/resume](https://docs.vast.ai/guides/instances/choosing/instance-types)
- [`set defjob` background Host Job](https://docs.vast.ai/cli/reference/set-defjob)
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
