# Instructions for future agents

This repository covers a dedicated physical Vast.ai GPU host under full operator control. Treat the supported goal as selling only capacity the research scheduler has explicitly released, then draining it before owner use. Near-instant owner reclaim is blocked until Vast documents and a controlled trial proves a rating-safe mechanism.

## Non-negotiable facts

0. This kit is for a dedicated physical machine whose provider expressly permits third-party hosting. Do not install or list a Vast host on a third-party cloud VM without the provider's prior written approval. A cheap public listing can admit a miner for only a few minutes, trigger a provider abuse event, and disappear between polling intervals.
1. Current official documentation exposes no strictly interruptible-only host switch. A high on-demand price is a deterrent, not a guarantee.
2. An outside on-demand or reserved contract has high priority and must be honored through its locked end date.
   Sqwish prices outside on-demand prohibitively high, sets the reserved discount to zero, and prices interruptible capacity at comparable-market P10. Every reclaim must still query contracts and abort if an outside on-demand or reserved contract appears.
3. Unlisting blocks new contracts only. It never changes an existing contract.
4. Vast documents Host Jobs (`set defjob`) as low-priority fallback work. The documentation does not say their price can preempt a live renter, and three controlled attempts at progressively higher prices did not do so. Never treat Host Job price as an owner-reclaim control.
5. Never reclaim by stopping Vast/Docker, rebooting, powering off, killing a container, changing minimum bid, or scheduling maintenance.
6. Vast documents that interruptible instances may pause when outbid or displaced by on-demand work and may later resume. It does not document owner Host Jobs as that higher-priority work or promise a resume deadline. Because no clean Host Job takeover occurred, automatic return was not testable in the final cycle.
7. Vast does not explicitly guarantee zero rating impact. The trial score fell from the original 0.5999925 to 0.5727243. Pin the original baseline per machine, refuse mutations below it, and measure reliability/verification before, during, immediately after, and after a delayed platform update.
8. A same-account interruptible instance cannot validate outside-renter preemption. The observed owner on-demand attempt was rejected with HTTP 400/error 3763 (`GPU conflict`). Vast officially documents testing through a separate client account on another email. Use that controlled account for the first reclaim trial: pre-authenticate and fund it, acquire the exact full-machine interruptible offer immediately, then unlist before testing owner preemption. A high price reduces the acquisition race but is not access control.
9. A vacant current-state card does not prove that no rental occurred. The cloud-VM incident in `docs/INCIDENT-CLOUD-MINER.md` involved an approximately four-minute workload that a five-minute monitor missed. Preserve event-level contract and egress logs, and treat any unexplained earnings as evidence requiring investigation.
10. Future qualification evidence must follow `docs/CONTROLLED-2H-2XA100-TRIAL.md`: one host account, one separate controlled client account, a guarded acquisition window, immediate unlisting after the exact full-machine contract is proven, and delayed rating checks. The 2026-09-02 Host Job attempts failed to reclaim at $1.10/30 seconds, $1.30/90 seconds, and $3.00/120 seconds; the near-instant, rating-safe owner-reclaim production gate is blocked.
11. The next legitimate 15-minute experiment combines two things Vast documents separately: a free own-machine test instance and on-demand priority over interruptibles. Vast does not document the retained, pre-created standby workflow as a routine owner-reclaim product. Treat it as a measured hypothesis, not a production promise: require two sub-15-minute end-to-end cycles, renter pause/resume, and no immediate or delayed reliability observation below the immutable original baseline. Clarify the supported separate-account topology and charges with Vast first.
12. Keep Vast's bid units explicit. Host `price_min_bid` is host-earned $/GPU-hour; bid-offer `min_bid` and client `--bid_price` are renter-facing $/machine-hour for the whole GPU bundle. For the currently observed four-thirds renter surcharge, convert with `host floor = renter machine total * 0.75 / GPU count`, then verify the exact relisted offer. Never multiply offer `min_bid` by GPU count.
13. Vast verification is automated and cannot be forced with pricing, synthetic rentals, or repeated Self-Tests. Current official requirements include reliability strictly over 90%; Vast says it normally grows over a few days of stable uptime and favors sustained uptime of at least 99.99%. Keep the machine stable, clean, cool, correctly provisioned, and reachable; use Jobs/Create Job for host work.
14. The successful 82.281-second handoff was an owner on-demand instance, not a Host Job/Create Job. It must never be described as running research within the verification-safe Jobs framework. The three genuine Host Job attempts did not preempt the interruptible.
15. For a strict clean qualification run, enable `tools/verification_guard.py` before preparing any owner standby. Its external marker blocks `prepare_owner_standby.py`, `controlled_owner_standby_cycle.py`, and `scripts/reclaim-gpu.sh`. Never bypass, delete, rename, or move that marker. The combined 24-hour pilot is a narrower exception: while vacant, prepare one exact standby first, prove it fully stopped, and name that exact ID/label with `--allowed-owner-standby` when enabling the HOLD. This stopped record makes the first arm a qualification-trend observation rather than an uncontaminated verification control.
16. Keep qualification-trend and owner on-demand handoff evidence separate. Follow `docs/CONTROLLED-24H-VERIFICATION-AND-HANDOFF-PILOT.md`; a combined 24-hour chart must mark the mode boundary and cannot attribute any score rise to owner handoffs. Use a separate no-owner, no-takeover soak for a strict verification control.
17. The controlled client's ordinary marketplace fees are a deliberate pilot expense. Capture final billing before cleanup, then run `tools/controlled_24h_cleanup.py`. Charges for retained client records are not considered bounded until its external marker says `status=complete`, the complete client inventory is empty, and the host-contract adapter sees only the stopped owner. Never clear a pending cleanup marker or lock blindly.

## Before acting

- Read `docs/RUNBOOK.md` and the current official pages linked at its end.
- Confirm the machine is a dedicated physical host rather than a vGPU guest, exposes full root/driver/Docker/storage/network control, and is in the intended Team Host context.
- Read `docs/ECONOMICS.md` before changing market or team-use defaults. Keep allocation occupancy separate from chip activity, state which inputs are measured versus assumed, and use ex-VAT costs for Sqwish planning.
- Do not include IPs, emails, account names, machine/instance IDs, serials, API keys, or private workload details in committed files.
- Never read or print `~/.config/vastai/vast_api_key`. Let the CLI consume it.
- The Host Setup one-hour installation key must come from the page's Copy button. The visible command contains a literal truncated `...`. Never paste the full key into a file or transcript.
- Download privileged Vast installers before execution and verify an exact SHA-256 supplied through an independent authenticated Vast channel. Never pipe a network response directly into a shell. The current host installer still exposes its one-hour credential briefly in process arguments; use only the private root procedure in the runbook and never substitute a persistent API key.
- Put persistent scoped CLI keys directly into the mode-0600 Vast config file from a hidden, non-exported prompt. Do not pass them through `vastai set api-key ...` arguments.
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
