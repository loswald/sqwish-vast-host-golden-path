# Vast owned-host golden path

This folder is a conservative operating kit for a **dedicated physical GPU host under the operator's full control**. Its experiment is to sell idle GPU time to interruptible bidders without compromising research access or host reliability. Three clean Host Job attempts could not reclaim a running renter. A later exact pre-created owner on-demand standby **did** pause the controlled two-GPU interruptible, reach `running/running/running` in **82.281 seconds**, stop cleanly, and return the renter automatically without fallback Start. That is a useful scheduler result, but near-instant, rating-safe production handoff remains **BLOCKED**: reliability was already below its immutable original baseline and no delayed observation completed.

Read [`docs/RUNBOOK.md`](docs/RUNBOOK.md) before touching a host.

The completed two-A100 setup, hard storage cap, controlled acquisition, failed Host Job reclaim, successful diagnostic owner-standby handoff, and reliability gate are recorded in [`docs/A100-2X-LIVE-TRIAL.md`](docs/A100-2X-LIVE-TRIAL.md). Sanitized measurements are in [`evidence/2026-09-02-a100-reclaim/`](evidence/2026-09-02-a100-reclaim/).

Use [`docs/CONTROLLED-2H-2XA100-TRIAL.md`](docs/CONTROLLED-2H-2XA100-TRIAL.md) only as a two-hour diagnostic qualification plan for controlled-client scheduling, slicing, rating observation, and cleanup.

Use [`docs/CLEAN-HOSTJOB-CYCLE.md`](docs/CLEAN-HOSTJOB-CYCLE.md) and
`tools/controlled_hostjob_cycle.py` to repeat the previously confounded Host Job
phase with corrected shell arguments, fixed-end verification, poll-boundary
private snapshots, delayed reliability measurement, guarded client recovery,
and guarded cleanup proofs.

Use `tools/controlled_owner_standby_cycle.py` for the narrower, fail-closed
two-account standby pilot. It accepts only one exact safely stopped host-account
on-demand standby and one exact full-machine controlled interruptible, unlists
and proves both offer views absent before takeover, measures the 15-minute SLO,
stops and retains the standby, and distinguishes automatic return from an
evidence-gated fallback Start. Its degraded diagnostic override never marks a
run production-ready.

Use `tools/verification_guard.py` while a new dedicated host is earning
verification. It installs a persistent local qualification HOLD before its
first read, samples the platform score, verification, reports, machine errors,
and the official observable hardware/network prerequisites, and records the
reliability trend without changing Vast state. While that HOLD exists, the
owner-standby preparation, owner-standby cycle, and Bash reclaim paths refuse
owner workload mutations. The guard cannot manufacture verification: it keeps
the machine in the stable operating condition Vast asks for and makes the
remaining manual checks explicit.

The extended controlled procedure is in
[`docs/CONTROLLED-24H-VERIFICATION-AND-HANDOFF-PILOT.md`](docs/CONTROLLED-24H-VERIFICATION-AND-HANDOFF-PILOT.md).
It separates a qualification-trend soak from later research-first owner
on-demand handoffs. The combined test allowlists one fully stopped owner
standby, so it is not the uncontaminated verification control; that stricter
test has no owner instance and no takeover arm. The successful 82-second path
is not a Host Job/Create Job, so evidence from the two modes must never be
combined into one verification claim.

Use `tools/prepare_owner_standby.py` to create and safely stop the one exact
digest-pinned four-GPU owner standby while the host is vacant. Its bounded
`torchrun` probe performs repeated matrix work plus NCCL all-reduce and writes
an atomic checkpoint every 15 seconds; the live owner-evidence adapter, rather
than container state alone, must prove that work during every handoff.

Use `tools/controlled_acquisition.py` for the bounded four-slice controlled
acquisition window, then `tools/controlled_24h_cleanup.py` after final billing
capture to retire only the four named controlled-client records. Cleanup
rechecks complete host contracts before each exact deletion, proves absence in
both client views, retains the owner standby, and can resume only from its
external pending marker.

For the SCAN 4x RTX PRO 6000 candidate, use the staged technical checklist in [`docs/SCAN-4X-RTX-PRO-6000-PILOT.md`](docs/SCAN-4X-RTX-PRO-6000-PILOT.md) before installation or listing.

Use [`docs/ECONOMICS.md`](docs/ECONOMICS.md) for the current ex-VAT 18-period model, exact `RTX PRO 6000 WS` comparables, and transparent three-researcher usage patterns. Recalculate rather than preserving its dated market snapshot.

## Hard limitation

Vast has no documented host switch that makes a listing strictly interruptible-only. A high on-demand price can discourage outside on-demand rental but cannot prevent it. If an outside on-demand or reserved contract appears, the owner workload must wait and the locked contract must be honored.

Sqwish's operating policy is therefore to set the outside on-demand price at the deliberately unattractive reviewed ceiling, set the reserved discount to zero, and price interruptible capacity at the comparable-market P10 so it fills readily. Only interruptible tenants enter the reclaim model. Every reclaim preflight must still inspect the live contracts and abort if an outside on-demand or reserved contract appears; pricing is a market guard, not an access-control bit.

Vast requires host workloads to use its Jobs path, and [`set defjob`](https://docs.vast.ai/cli/reference/set-defjob) creates a background job. The official Host Job reference does **not** promise that its price can preempt a running interruptible, publish a reclaim-latency SLA, or guarantee no reliability effect. Vast's documented [instance priority rule](https://docs.vast.ai/guides/instances/choosing/instance-types) is narrower: interruptibles may pause when outbid by another interruptible or when an on-demand instance is requested, then resume when priority returns. Do not infer an owner eviction right from the renter being interruptible.

The clean two-A100 attempts used high Host Job inputs of **$1.10/GPU-hour for 30 seconds**, **$1.30/GPU-hour for 90 seconds**, and **$3.00/GPU-hour for 120 seconds**. None paused the controlled renter or started the owner work. The final corrected attempt held the immediate score flat at **0.5727243**, but a flat score during a failed reclaim does not prove rating-safe handoff. Across the complete experiment, reliability began at **0.5999925** (briefly **0.599997**) and fell to **0.5727243** during the restart/new-client sequence before the clean attempts.

For production, use one of the operating modes that does not depend on forced handoff:

1. List only GPUs the research team explicitly releases for the whole offer/contract window.
2. Unlist to stop new contracts, then drain existing contracts according to their locked end dates before owner use.
3. Keep enough GPU capacity reserved for immediate research demand and sell only the surplus.

The stopped owner on-demand path remains a controlled experiment until Vast confirms it is acceptable for ongoing team workloads. The two-A100 pilot proved the scheduler sequence once, but it did not pass the original-reliability or delayed-observation gates. It reserves the owner's disk before any tenant arrives, but it is not a production recommendation:

1. While the host is vacant, the owner creates one on-demand instance, gives it a dedicated owner label, and stops it after setup.
2. Outside interruptible runs; the stopped owner instance keeps its disk but does not reserve a GPU.
3. Owner starts that exact instance. In the controlled pilot, Vast safely stopped the exact interruptible and the owner reached running in 82.281 seconds.
4. Owner stops that exact instance after saving outputs, retaining the owner's disk for the next experiment.
5. In the controlled pilot, the same interruptible resumed automatically; the fallback Start was not used.

This is the credible **15-minute candidate**. The pilot passed its technical timing and automatic-return checks, and a separate post-pilot probe proved a real two-GPU PyTorch CUDA workload on the owner standby. Final cleanup proved no contracts and no bid/on-demand offers. Reliability was **0.5727243** before takeover, immediately after it, and after cleanup, versus the immutable original **0.5999925**. A later read-only sample reported **0.5727207** and only **161.9 Mbps upload**, below Vast's current 500 Mbps verification minimum, so this host could not qualify independently of the handoff. The run was therefore an explicitly degraded diagnostic, not a rating-safe qualification. The mandatory delayed check was skipped when the disposable host reached its preconfigured automatic-deletion deadline. Vast publishes no self-preemption latency or rating SLA and says new-machine reliability starts low and grows with stable uptime. Its verification guide also says personal workloads can fail verification, while its host guidance directs host work through the Jobs path. Obtain written clarification on the supported ongoing team-workload/account topology before production use.

The successful diagnostic sampled 17 comparable offers. Their renter-facing P10 for the whole two-GPU machine was **$0.7466667/hour**, which mapped to a **$0.28/GPU-hour** host interruptible floor under the observed surcharge. The outside on-demand deterrent remained **$5.84/GPU-hour** host-side, or **$15.5733/hour** for the renter-visible pair, with reserved discount zero. These values are a dated test snapshot, not permanent defaults. Standby preparation first rejected a `10/10` listing with HTTP 422; the known accepted `5.84/3` preparation shape worked. Creating the own-machine standby with `--cancel-unavail` also hit the false-ownership bug, so the vacant-host-only retry omitted that flag after proving no instance was created.

Fresh create/destroy remains available when `VAST_OWN_INSTANCE_ID` is blank. It cannot protect against host disk exhaustion because its disk allocation happens at reclaim time.

Unlisting, stopping the daemon, restarting Docker, powering off, killing containers, changing the minimum bid, and maintenance notice are not reclaim controls. Vast does not explicitly guarantee zero rating impact for owner reclaim, so the trial notes measure reliability before, during, and after.

## Files

- `docs/RUNBOOK.md` — complete setup, listing, reclaim, maintenance, payout, cleanup, and troubleshooting guide.
- `docs/TRIAL-NOTES.md` — sanitized trial record template.
- `docs/A100-2X-LIVE-TRIAL.md` — evidence from the live two-A100 storage, pricing, acquisition, failed clean reclaim, reliability, cost, and teardown trial.
- `evidence/2026-09-02-a100-reclaim/` — sanitized state-transition and pricing measurements from that controlled trial.
- `docs/CONTROLLED-2H-2XA100-TRIAL.md` — diagnostic two-hour controlled-client plan for Host Job and owner on-demand experiments, slicing, rating observation, and cleanup.
- `docs/CONTROLLED-24H-VERIFICATION-AND-HANDOFF-PILOT.md` — dedicated-host 24-hour qualification-trend, four-slice workload, three-handoff, checkpoint, score-trend, and guarded-cleanup plan.
- `docs/SCAN-4X-RTX-PRO-6000-PILOT.md` — one-week technical qualification and released-capacity plan for the published SCAN candidate.
- `docs/ECONOMICS.md` — SCAN commitment, Vast price/fill, and research-team allocation scenarios with primary sources.
- `docs/ADAPTIVE-PRICING.md` — guarded P10 interruptible-floor sampling, reliability adjustment, hard bounds, and exact-machine apply checks.
- `docs/INFERENCE-ALTERNATIVES.md` — researched comparison of raw rentals with inference-worker networks.
- `docs/INCIDENT-CLOUD-MINER.md` — sanitized postmortem for the short-lived miner workload missed by polling during the cloud-VM trial.
- `scripts/preflight-host.sh` — read-only local requirement checks.
- `scripts/monitor-machine.sh` — read-only Vast/local health snapshots.
- `scripts/reclaim-gpu.sh` — verifies and starts a reusable stopped owner instance, or guardedly creates a fresh one when no reusable ID is configured.
- `scripts/release-gpu.sh` — stops and retains a reusable owner instance, or guardedly destroys a fresh-created one, then captures post-release health.
- `scripts/unlist-and-cleanup.sh` — guarded unlist plus optional Vast reconciliation of expired/deleted storage.
- `tools/economics_model.py` — dependency-free 18-period ex-VAT calculator.
- `tools/usage_patterns.py` — auditable light/normal/campaign/deadline workload calendars.
- `tools/adaptive_pricing.py` — dry-run-first market sampler and guarded interruptible minimum updater.
- `tools/controlled_hostjob_cycle.py` — exact two-account clean Host Job cycle with fixed-end and cleanup proofs.
- `tools/controlled_owner_standby_cycle.py` — exact two-account pre-created owner on-demand standby cycle with a 15-minute SLO, automatic-return proof, immutable reliability baseline, and guarded cleanup.
- `tools/controlled_24h_pilot.py` — exact four-slice, 24-hour observer/controller with qualification HOLD, six-minute maximum evidence gaps, continuous contract/checkpoint proof, exactly three owner on-demand handoffs, delayed rating samples, three-view billing reconciliation, and retained-record cleanup semantics.
- `tools/prepare_owner_standby.py` — vacant-host, one-shot preparation of the exact retained owner standby with a digest-pinned, bounded `torchrun`/NCCL checkpointing probe.
- `tools/controlled_acquisition.py` — bounded, fail-closed acquisition of four exact one-GPU controlled interruptibles, with an exact offer re-query before every one-shot create.
- `tools/controlled_24h_cleanup.py` — restartable exact-ID retirement of the four controlled-client records after billing capture; it never destroys the owner standby.
- `tools/verification_guard.py` — read-only qualification observer plus persistent owner-workload HOLD shared by the reclaim controllers.
- `tests/fake-cli-tests.sh` — offline lifecycle guardrail checks using a fake Vast CLI.
- `site/` — source for the [public interactive economics, workload, and spare-capacity operating-loop dashboard](https://sqwish-gpu-slack-lab.poonami.chatgpt.site/).
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

For a strict qualification run on a new dedicated host, enable the
score-protection mode before any owner standby is prepared:

```bash
python3 tools/verification_guard.py --enable-qualification-mode --machine-id "$VAST_MACHINE_ID"
python3 tools/verification_guard.py --sample --machine-id "$VAST_MACHINE_ID"
```

Run the ordinary Self-Test once through Vast and keep the machine continuously
online. Schedule repeated read-only samples; do not repeatedly self-test or
change drivers, Docker, networking, or power state to chase the score. The
output separates observed passes, observed blockers, and requirements that
still need manual proof. Vast currently requires reliability strictly over 90%
and says a stable new machine typically takes a few days.

Disable the HOLD only when deliberately leaving the clean qualification mode:

```bash
python3 tools/verification_guard.py --disable-qualification-mode --machine-id "$VAST_MACHINE_ID"
```

That command records the transition; it does not certify that an owner
on-demand workload is verification-safe.

The combined 24-hour pilot is the explicit exception: prepare its one exact
standby while vacant, prove it fully stopped, then enable the HOLD with
`--allowed-owner-standby INSTANCE_ID:LABEL`. This permits only that stopped
record and does not turn the first arm into an uncontaminated verification
control.

The remaining helper examples are for a controlled qualification in which every renter account is operated by the test team. They are not approved for reclaiming from a public renter. After the host is installed, vacant, VM mode is `off`, self-test passes, and the diagnostic listing is reviewed, prepare a reusable owner instance using the runbook. Set its exact ID as `VAST_OWN_INSTANCE_ID`, its dedicated label prefix as `VAST_OWN_LABEL_PREFIX`, and the reviewed GPU count/offer where available. The instance must report `is_bid=false` and the safe stopped-state tuple: `actual_status` is explicitly `created`, `exited`, or `stopped`, and both `intended_status` and `cur_state` are `stopped`. Missing fields or any other actual state are rejected.

Then preview reclaim:

```bash
./scripts/monitor-machine.sh --snapshot
./scripts/reclaim-gpu.sh
```

The second command previews `start instance <VAST_OWN_INSTANCE_ID>`. It validates the exact ID, machine, owner label prefix, on-demand type, GPU count/offer where exposed, and stopped state. Any failure aborts; pre-created mode never falls back to a fresh create. After reviewing Host Machines/Contracts and confirming every renter is the exact controlled test account and no unknown contract exists, one guarded invocation performs the experiment:

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
