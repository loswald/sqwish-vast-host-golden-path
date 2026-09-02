# Instructions for future agents

This repository covers an owned, dedicated Vast.ai GPU host. Treat the user's goal as reversible interruptible capacity with fast owner reclaim through Vast's scheduler.

## Non-negotiable facts

1. Current official documentation exposes no strictly interruptible-only host switch. A high on-demand price is a deterrent, not a guarantee.
2. An outside on-demand or reserved contract has high priority and must be honored through its locked end date.
3. Unlisting blocks new contracts only. It never changes an existing contract.
4. The owner reclaim path creates an on-demand Vast instance on the owned machine without `--bid_price`. Vast then pauses the interruptible. Release destroys only the recorded owner instance.
5. Never reclaim by stopping Vast/Docker, rebooting, powering off, killing a container, changing minimum bid, or scheduling maintenance.
6. Vast documents automatic resume when an interruptible regains priority. The combined owner-reclaim behavior is an evidence-backed inference until a controlled trial passes.
7. Vast does not explicitly guarantee zero rating impact. Always measure reliability/verification before, during, immediately after, and after a delayed platform update.

## Before acting

- Read `docs/RUNBOOK.md` and the current official pages linked at its end.
- Confirm the machine is owned hardware, dedicated to hosting, and in the intended Team Host context.
- Do not include IPs, emails, account names, machine/instance IDs, serials, API keys, or private workload details in committed files.
- Never read or print `~/.config/vastai/vast_api_key`. Let the CLI consume it.
- The Host Setup one-hour installation key must come from the page's Copy button. The visible command contains a literal truncated `...`. Never paste the full key into a file or transcript.
- Confirm VM mode is `off` for this Docker-only path.
- Inspect Host Machines/Contracts manually before reclaim. Owner-side `vastai show instances` is not a complete outside-client inventory.

## Mutation policy

- Run the helper without `--apply` first.
- Keep every mutation fail-closed and interactive.
- Do not weaken the ID/label/machine checks in `release-gpu.sh`.
- Do not add a noninteractive bypass for reclaim/release.
- Do not make scripts kill Docker containers or services.
- Do not add automatic power-off. A host can have locked contracts invisible to a simplistic offer check.
- Keep private state under `VAST_STATE_DIR`, outside the repository, mode 0700/0600 where supported.
- Treat `pending-reclaim.json` or `reclaim.lock/` as an unresolved create attempt. Check Vast Instances for the recorded label and confirm no helper process is running before clearing either marker.
- A state-changing API key should use the smallest official permission groups. Do not request `user_write`, `billing_write`, or `team_write` for routine operations.

## Installation and disk work

- Disk formatting is outside the helper scripts. Verify device model, serial, size, partitions, mounts, and data independently before any destructive command.
- Preferred storage is dedicated SSD/NVMe XFS with project quotas at `/var/lib/docker`.
- Prefer the official standard installer on a fresh Ubuntu Server 22.04/24.04 host. Use `--no-docker` only when the existing Docker configuration is already correct.
- Keep the machine unlisted while repairing installer, daemon, port, disk, driver, thermal, or networking problems.

## Listing review

Use a fixed Unix `--end_date`, `--discount_rate 0`, `--vol_size 0`, a reviewed interruptible floor, and an intentionally unattractive on-demand price. Never describe this as strict enforcement. Do not use rolling `--duration` for the trial.

## Testing changes to this repository

Run:

```bash
./validate.sh
```

At minimum, all Bash files must pass `bash -n`. If ShellCheck is available, resolve its actionable findings. Preserve dry-run behavior and interactive apply confirmations in any refactor.

## Source preference

Use official Vast documentation, official current CLI source when rendered docs conflict, and live Host Setup/installer behavior. Mark any combined or undocumented behavior as inferred. Never turn a successful trial into a universal guarantee.
