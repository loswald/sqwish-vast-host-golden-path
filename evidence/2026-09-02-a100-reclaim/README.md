# Controlled 2×A100 reclaim evidence — 2026-09-02

This directory contains sanitized API snapshots from a two-account Vast trial on an exact 2×A100 SXM4 40GB host. No unknown renter acquired the machine. The reviewed client and owner workloads used Vast's self-test image and `gpu_burn`; no cryptocurrency workload was run.

## Outcome

- The controlled client acquired both GPUs at a **$1.61/machine-hour** interruptible bid. The host's P99-derived floor was **$0.60/GPU-hour**, which appeared to the client as **$1.60/machine-hour**. The public listing window was **13.303551 seconds**, then the machine was unlisted.
- A Host Job at **$0.65/GPU-hour** created two independent one-GPU bids with renter-facing `dph_base` **$0.866667 each** and did not preempt the two-GPU contract.
- A Host Job at **$1.30/GPU-hour** created two one-GPU bids with `dph_base` **$1.733333 each**. After the host was relisted, the client was stopped and both owner jobs were scheduled in about **2.82 seconds**.
- The first owner job definition was malformed because `set defjob --args -lc ...` made `-lc` the executable. The corrected form is `set defjob ... --args /bin/bash -lc '<workload>'`.
- With the corrected definition, both owner containers ran and each completed `gpu_burn` successfully. Host Jobs were only observed to schedule while the machine had an active listing.
- Lowering the owner jobs did **not** automatically resume the client during a wait of more than **79 seconds**. The client's ordinary Start action restored the same stored contract to `cur_state=running` in about **3.37 seconds**; both GPUs later returned to 100% utilization.
- Reliability fell from **0.5999925** to **0.5727243** after the malformed owner launches and first reclaim. It remained at 0.5727243 after the corrected cycle. The failed launches confound attribution, so this test cannot establish rating-safe reclaim.
- A later read-only qualification sample reported **0.5727207**, no machine errors or reports, **4200.4 Mbps download**, and only **161.9 Mbps upload**. The current verification minimum is 500 Mbps in both directions, so this disposable host was structurally unable to qualify. The tiny score drift is observational and cannot be attributed to the later clean handoff.
- Direct client spend was **$0.10394347623**. The contract, temporary client API and SSH keys, Host Job, Vast machine record, and exact disposable cloud VM/disks/IP/firewall were removed.

## Evidence map

- `result.json` is the compact, manually checked result record.
- `controlled-acquire.json` records the listing, exact offer, contract creation, and immediate unlisting. The one-time instance API key is redacted.
- `preempt-poll.json` records the first client-to-owner transition.
- `resume-poll.json` records the lack of automatic resume and the manual Start transition.
- `resume-confirmation.json` is a manually checked, sanitized observation from the later client and host telemetry that confirmed the same contract fully running and both GPUs at 100% utilization. The raw resume poll itself ends earlier, when scheduler state had changed but `actual_status` was still `exited`.
- `baseline-market-p99.json` and `baseline-captured-at.txt` record the pre-test market and timestamp.
- `late-verification-observation.json` records the final read-only score, network, error, and report assessment without machine or account identifiers.

The bid-search response came from `search offers --type bid` but reported `is_bid: false`. Automation must trust the requested offer class plus exact machine/host/GPU checks and verify the created contract's `is_bid: true`; filtering the search response on `is_bid === true` caused two safe, failed-closed acquisition attempts.

The final acquisition offer reported null `duration` and `end_date`; this missed the runbook's fixed-end listing guard. The seconds-long controlled window and immediate unlisting limited this run, but dedicated-hardware repeats must set and verify the fixed end before exposure.

The production gate remains closed until a clean cycle on dedicated hardware shows acceptable delayed rating behavior and the team accepts that the renter may need to restart manually.
