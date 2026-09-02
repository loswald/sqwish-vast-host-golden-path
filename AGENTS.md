# Instructions for future agents

This repository covers a dedicated physical Vast.ai GPU host under full operator control. Treat the user's goal as reversible interruptible capacity with fast owner reclaim through Vast's scheduler.

## Non-negotiable facts

0. This kit is for a dedicated physical machine whose provider expressly permits third-party hosting. Do not install or list a Vast host on a third-party cloud VM without the provider's prior written approval. A cheap public listing can admit a miner for only a few minutes, trigger a provider abuse event, and disappear between polling intervals.
1. Current official documentation exposes no strictly interruptible-only host switch. A high on-demand price is a deterrent, not a guarantee.
2. An outside on-demand or reserved contract has high priority and must be honored through its locked end date.
3. Unlisting blocks new contracts only. It never changes an existing contract.
4. Vast documents Host Jobs (`set defjob`) as the production mechanism for owner workloads. A Host Job is a background bid and can only reclaim from lower interruptible bids. The exact, pre-created, stopped on-demand instance is a stronger controlled reclaim experiment, but do not call it the production policy until Vast confirms ongoing owner use is permitted. Release stops and retains that exact test instance. Neither on-demand path uses `--bid_price`.
5. Never reclaim by stopping Vast/Docker, rebooting, powering off, killing a container, changing minimum bid, or scheduling maintenance.
6. Vast documents automatic resume when an interruptible regains priority, but the controlled two-A100 Host Job trial did not auto-resume within more than 79 seconds. The separate client recovered only after its own Start action. Treat public-renter return as unproved and keep production reclaim disabled.
7. Vast does not explicitly guarantee zero rating impact. Always measure reliability/verification before, during, immediately after, and after a delayed platform update.
8. A same-account interruptible instance cannot validate outside-renter preemption. The observed owner on-demand attempt was rejected with HTTP 400/error 3763 (`GPU conflict`). Vast officially documents testing through a separate client account on another email. Use that controlled account for the first reclaim trial: pre-authenticate and fund it, acquire the exact full-machine interruptible offer immediately, then unlist before testing owner preemption. A high price reduces the acquisition race but is not access control.
9. A vacant current-state card does not prove that no rental occurred. The cloud-VM incident in `docs/INCIDENT-CLOUD-MINER.md` involved an approximately four-minute workload that a five-minute monitor missed. Preserve event-level contract and egress logs, and treat any unexplained earnings as evidence requiring investigation.
10. Future qualification evidence must follow `docs/CONTROLLED-2H-2XA100-TRIAL.md`: one host account, one separate controlled client account, a P99 acquisition window, immediate unlisting after the exact full-machine contract is proven, corrected Host Job cycles, owner on-demand test cycles, and delayed rating checks. The 2026-09-02 Host Job cycle failed the automatic-resume and rating-safety production gates.
11. Keep Vast's bid units explicit. Host `price_min_bid` is host-earned $/GPU-hour; bid-offer `min_bid` and client `--bid_price` are renter-facing $/machine-hour for the whole GPU bundle. For the currently observed four-thirds renter surcharge, convert with `host floor = renter machine total * 0.75 / GPU count`, then verify the exact relisted offer. Never multiply offer `min_bid` by GPU count.

## Before acting

- Read `docs/RUNBOOK.md` and the current official pages linked at its end.
- Confirm the machine is a dedicated physical host rather than a vGPU guest, exposes full root/driver/Docker/storage/network control, and is in the intended Team Host context.
- Read `docs/ECONOMICS.md` before changing market or team-use defaults. Keep allocation occupancy separate from chip activity, state which inputs are measured versus assumed, and use ex-VAT costs for Sqwish planning.
- Do not include IPs, emails, account names, machine/instance IDs, serials, API keys, or private workload details in committed files.
- Never read or print `~/.config/vastai/vast_api_key`. Let the CLI consume it.
- The Host Setup one-hour installation key must come from the page's Copy button. The visible command contains a literal truncated `...`. Never paste the full key into a file or transcript.
- Confirm VM mode is `off` for this Docker-only path.
- Inspect Host Machines/Contracts manually before reclaim. Owner-side `vastai show instances` is not a complete outside-client inventory.

## Mutation policy

- Run the helper without `--apply` first.
- Keep every mutation fail-closed and interactive.
- If `VAST_OWN_INSTANCE_ID` is configured, never fall back to create. Require exact ID, machine, dedicated label, `is_bid=false`, GPU count/offer where available, and the fail-closed stopped-state proof before start: `actual_status` is one of `created`, `exited`, or `stopped`, while `intended_status=stopped` and `cur_state=stopped`.
- Treat start/stop output and exit status as diagnostic only. Prove a start with the exact `show instance` record reporting `running/running/running`. Prove a stop only with the explicit stopped-state allowlist above; missing fields and every other `actual_status` fail closed.
- Do not weaken the ID/label/machine/mode checks in `release-gpu.sh`. Precreated mode may only stop; fresh-created mode may only destroy.
- Never destroy an ID that is currently configured as `VAST_OWN_INSTANCE_ID`, even if a damaged or hand-written state file labels it fresh-created.
- Do not archive release state on empty destroy output alone. Require either explicit JSON `success: true` or exact absence from both the single-instance and full instance-list CLI views.
- Do not add a noninteractive bypass for reclaim/release.
- Do not make scripts kill Docker containers or services.
- Do not add automatic power-off. A host can have locked contracts invisible to a simplistic offer check.
- Keep private state under `VAST_STATE_DIR`, outside the repository, mode 0700/0600 where supported.
- Treat `pending-reclaim.json`, an active `start-pending` state, or `reclaim.lock/` as unresolved. Check the recorded exact instance/label and confirm no helper process is running before clearing anything. Use guarded release to stop a precreated start attempt.
- Recovery release overrides must name the mode explicitly as well as exact instance ID, machine ID, and label. A missing state file must never default a reusable instance to destroy.
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
