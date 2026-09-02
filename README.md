# Vast owned-host golden path

This folder is a conservative operating kit for a **dedicated, physically owned** Vast.ai host. Its specific experiment is to sell idle GPU time to interruptible bidders, reclaim the GPU with a free owner-created on-demand Vast instance, and release it so the bidder can resume through Vast's scheduler.

Read [`docs/RUNBOOK.md`](docs/RUNBOOK.md) before touching a host.

For the SCAN 4x RTX PRO 6000 candidate, use the staged technical checklist in [`docs/SCAN-4X-RTX-PRO-6000-PILOT.md`](docs/SCAN-4X-RTX-PRO-6000-PILOT.md) before installation or listing.

## Hard limitation

Vast has no documented host switch that makes a listing strictly interruptible-only. A high on-demand price can discourage outside on-demand rental but cannot prevent it. If an outside on-demand or reserved contract appears, the owner workload must wait and the locked contract must be honored.

Normal reclaim is a Vast-managed priority change:

1. Outside interruptible runs.
2. Owner creates an on-demand instance on the same owned machine.
3. Vast pauses the interruptible and retains its disk.
4. Owner destroys only the owner instance after saving its outputs.
5. Vast documents that the interruptible resumes when it regains priority.

Unlisting, stopping the daemon, restarting Docker, powering off, killing containers, changing the minimum bid, and maintenance notice are not reclaim controls. Vast does not explicitly guarantee zero rating impact for owner reclaim, so the trial notes measure reliability before, during, and after.

## Files

- `docs/RUNBOOK.md` — complete setup, listing, reclaim, maintenance, payout, cleanup, and troubleshooting guide.
- `docs/TRIAL-NOTES.md` — sanitized trial record template.
- `docs/SCAN-4X-RTX-PRO-6000-PILOT.md` — one-week technical qualification and staged 4-GPU reclaim plan for the published SCAN candidate.
- `scripts/preflight-host.sh` — read-only local requirement checks.
- `scripts/monitor-machine.sh` — read-only Vast/local health snapshots.
- `scripts/reclaim-gpu.sh` — guarded owner on-demand creation.
- `scripts/release-gpu.sh` — verifies the owner instance triple, destroys only that instance, and captures post-release health.
- `scripts/unlist-and-cleanup.sh` — guarded unlist plus optional Vast reconciliation of expired/deleted storage.
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

After the host is installed, vacant, VM mode is `off`, self-test passes, and the listing is reviewed:

```bash
./scripts/monitor-machine.sh --snapshot
./scripts/reclaim-gpu.sh
```

The second command previews the exact creation. After reviewing Host Machines/Contracts and confirming there is no outside on-demand or reserved contract, one guarded invocation performs the reclaim:

```bash
./scripts/reclaim-gpu.sh --contracts-reviewed --apply
```

It asks the operator to type `RECLAIM <machine-id>` and records the returned owner instance ID outside the repository.
Before calling Vast, it also writes a private pending marker. If creation is interrupted or its response cannot be parsed, do not rerun reclaim: inspect Vast Instances for the marker's label and resolve that attempt first. A lock also prevents two local helpers from creating owner instances concurrently.

After owner outputs are saved:

```bash
./scripts/release-gpu.sh
./scripts/release-gpu.sh --apply
```

Release requires a matching instance ID, machine ID, and owner label before it offers to destroy anything. It then captures read-only health snapshots while the operator verifies the outside interruptible resumes in Host Machines/Contracts.
The helper passes the CLI's noninteractive `--yes` only after its own stronger typed confirmation, and it archives active state only after Vast returns JSON with `success: true`.

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
