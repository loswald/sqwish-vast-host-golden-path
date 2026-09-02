# Vast owned-host golden path

This folder is a conservative operating kit for a **dedicated physical GPU host under the operator's full control**. Its specific experiment is to sell idle GPU time to interruptible bidders, reclaim the GPU with an owner-created on-demand Vast instance, and release it so the bidder can resume through Vast's scheduler.

Read [`docs/RUNBOOK.md`](docs/RUNBOOK.md) before touching a host.

The completed two-A100 setup, hard storage cap, price display, vacant-host checks, and still-pending outside-renter reclaim evidence are recorded in [`docs/A100-2X-LIVE-TRIAL.md`](docs/A100-2X-LIVE-TRIAL.md).

For the SCAN 4x RTX PRO 6000 candidate, use the staged technical checklist in [`docs/SCAN-4X-RTX-PRO-6000-PILOT.md`](docs/SCAN-4X-RTX-PRO-6000-PILOT.md) before installation or listing.

Use [`docs/ECONOMICS.md`](docs/ECONOMICS.md) for the current ex-VAT 18-period model, exact `RTX PRO 6000 WS` comparables, and transparent three-researcher usage patterns. Recalculate rather than preserving its dated market snapshot.

## Hard limitation

Vast has no documented host switch that makes a listing strictly interruptible-only. A high on-demand price can discourage outside on-demand rental but cannot prevent it. If an outside on-demand or reserved contract appears, the owner workload must wait and the locked contract must be honored.

The preferred reclaim path reserves the owner's disk before any tenant arrives:

1. While the host is vacant, the owner creates one on-demand instance, gives it a dedicated owner label, and stops it after setup.
2. Outside interruptible runs; the stopped owner instance keeps its disk but does not reserve a GPU.
3. Owner starts that exact instance. Vast should pause the outside interruptible and retain its disk.
4. Owner stops that exact instance after saving outputs, retaining the owner's disk for the next experiment.
5. Vast documents that the interruptible resumes when it regains priority.

Fresh create/destroy remains available when `VAST_OWN_INSTANCE_ID` is blank. It cannot protect against host disk exhaustion because its disk allocation happens at reclaim time.

Unlisting, stopping the daemon, restarting Docker, powering off, killing containers, changing the minimum bid, and maintenance notice are not reclaim controls. Vast does not explicitly guarantee zero rating impact for owner reclaim, so the trial notes measure reliability before, during, and after.

## Files

- `docs/RUNBOOK.md` — complete setup, listing, reclaim, maintenance, payout, cleanup, and troubleshooting guide.
- `docs/TRIAL-NOTES.md` — sanitized trial record template.
- `docs/A100-2X-LIVE-TRIAL.md` — evidence from the live two-A100 storage, pricing, qualification, and standby trial, with the outside-renter reclaim result kept explicitly pending.
- `docs/SCAN-4X-RTX-PRO-6000-PILOT.md` — one-week technical qualification and staged 4-GPU reclaim plan for the published SCAN candidate.
- `docs/ECONOMICS.md` — SCAN commitment, Vast price/fill, and research-team allocation scenarios with primary sources.
- `docs/ADAPTIVE-PRICING.md` — guarded P10 interruptible-floor sampling, reliability adjustment, hard bounds, and exact-machine apply checks.
- `docs/INFERENCE-ALTERNATIVES.md` — researched comparison of raw rentals with inference-worker networks.
- `scripts/preflight-host.sh` — read-only local requirement checks.
- `scripts/monitor-machine.sh` — read-only Vast/local health snapshots.
- `scripts/reclaim-gpu.sh` — verifies and starts a reusable stopped owner instance, or guardedly creates a fresh one when no reusable ID is configured.
- `scripts/release-gpu.sh` — stops and retains a reusable owner instance, or guardedly destroys a fresh-created one, then captures post-release health.
- `scripts/unlist-and-cleanup.sh` — guarded unlist plus optional Vast reconciliation of expired/deleted storage.
- `tools/economics_model.py` — dependency-free 18-period ex-VAT calculator.
- `tools/usage_patterns.py` — auditable light/normal/campaign/deadline workload calendars.
- `tools/adaptive_pricing.py` — dry-run-first market sampler and guarded interruptible minimum updater.
- `tests/fake-cli-tests.sh` — offline lifecycle guardrail checks using a fake Vast CLI.
- `site/` — source for the private interactive economics and workload dashboard.
- `.env.example` — non-secret configuration template.
- `validate.sh` — syntax and repository hygiene checks.

Every state-changing helper is a dry run unless `--apply` is present. Apply mode also requires an interactive typed confirmation. The reclaim helper requires an explicit manual review of Host Machines/Contracts because `vastai show instances` only lists the current account's instances and is not a complete outside-renter inventory.

The operator machine needs Bash, the official `vastai` CLI, and `jq`. The host preflight additionally uses standard Ubuntu server tools such as `nvidia-smi`, `lscpu`, `findmnt`, `df`, `sshd`, and optionally `mokutil`.

## Initial use

```bash
cp .env.example .env
chmod 600 .env
./validate.sh
./scripts/preflight-host.sh
```

Fill only the non-secret values in `.env`. Configure the scoped Vast API key with the official CLI so it remains in `~/.config/vastai/vast_api_key`; never put a key in `.env`.

After the host is installed, vacant, VM mode is `off`, self-test passes, and the listing is reviewed, prepare a reusable owner instance using the runbook. Set its exact ID as `VAST_OWN_INSTANCE_ID`, its dedicated label prefix as `VAST_OWN_LABEL_PREFIX`, and the reviewed GPU count/offer where available. The instance must report `is_bid=false` and the safe stopped-state tuple: `actual_status` is explicitly `created`, `exited`, or `stopped`, and both `intended_status` and `cur_state` are `stopped`. Missing fields or any other actual state are rejected.

Then preview reclaim:

```bash
./scripts/monitor-machine.sh --snapshot
./scripts/reclaim-gpu.sh
```

The second command previews `start instance <VAST_OWN_INSTANCE_ID>`. It validates the exact ID, machine, owner label prefix, on-demand type, GPU count/offer where exposed, and stopped state. Any failure aborts; pre-created mode never falls back to a fresh create. After reviewing Host Machines/Contracts and confirming there is no outside on-demand or reserved contract, one guarded invocation performs the reclaim:

```bash
./scripts/reclaim-gpu.sh --contracts-reviewed --apply
```

It asks the operator to type `START <instance-id> ON <machine-id>`, writes mode-tagged private state before starting, and proves that exact instance reached the three-field running state. Vast CLI start/stop output and exit status are not authoritative, so the helper resolves the outcome through bounded `show instance` polling. If start remains uncertain, active state stays in place and release can stop or cancel the exact attempt.

When `VAST_OWN_INSTANCE_ID` is blank, the preview instead shows a fresh create. That mode asks for `RECLAIM <machine-id>`, writes a pending marker before the non-idempotent call, and records the returned ID. If its response is uncertain, inspect Vast Instances for the recorded label before doing anything else.

After owner outputs are saved:

```bash
./scripts/release-gpu.sh
./scripts/release-gpu.sh --apply
```

Release reads the recorded mode and repeats the exact ID, machine, and label checks under a lock. For `precreated`, it offers only `stop instance`, proves the same safe stopped-state tuple, keeps the instance and disk, and archives the session state. For `fresh-created`, it offers only guarded destroy and refuses any ID currently configured as `VAST_OWN_INSTANCE_ID`. It passes the CLI's noninteractive `--yes` after its own typed confirmation and archives state after either JSON `success: true` or matching absence from both `show instance` and `show instances`.

Stopped instances continue to incur client-side storage charges, their disk size cannot be changed, and they do not reserve a GPU. Keep enough client credit to prevent the platform deleting them at zero balance. Restart is still scheduler-dependent; pre-creating protects disk capacity, not GPU availability or guaranteed preemption.

To stop accepting new rentals:

```bash
./scripts/unlist-and-cleanup.sh
./scripts/unlist-and-cleanup.sh --apply
```

Run storage reconciliation only after every client contract and rented volume is confirmed ended:

```bash
./scripts/unlist-and-cleanup.sh --cleanup --contracts-ended --apply
```

## Permissions

Suggested custom Team roles/API scopes:

- Host administrator: `machine_read`, `machine_write`.
- Reclaim operator: `machine_read`, `misc`, `instance_read`, `instance_write`.
- Observer: `machine_read`, optionally `instance_read` and `billing_read`.
- Team owner: retain owner access; do not use an owner-strength key in these scripts.

The host installer uses a separate one-hour installation key from Host Setup. The visible command is intentionally truncated with literal `...`; use the page's **Copy** button to receive the full 64-character key.

## Safety boundary

These helpers do not format disks, edit firewalls, install drivers, install the Vast manager, enable VM mode, delete machines, delete client paths, uninstall services, or power down the server. Those steps require the ordered checks in the runbook.
