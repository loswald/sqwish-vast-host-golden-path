# Sanitized trial notes

Keep this file free of IP addresses, account names, machine IDs, instance IDs, API keys, serial numbers, emails, and private workload details. Put sensitive identifiers in the private change record outside this repository.

## Trial metadata

- Date/time (UTC):
- Operator role:
- Hardware class (generic):
- GPU count:
- Vast CLI version:
- Offer end boundary (relative description only):
- Interruptible floor rationale:
- On-demand deterrent rationale:
- Interruptible renter: genuine outside contract / same-account invalid control:

## Vacant-host self-test

- First-run image pull/build duration:
- System requirements passed:
- ResNet/ECC/NCCL markers passed:
- CPU/GPU stress reached `DONE`:
- Peak temperature/power/VRAM:
- Test container removed and GPU returned idle:
- Transient log-poll message, if any:

## Before reclaim

- Reliability score:
- Verification state:
- Daemon healthy:
- Red errors:
- Contract types reviewed in Host Machines/Contracts view:
- Only outside interruptible contract present:
- GPU/disk/network within validated envelope:

## During reclaim

- Reclaim mode: precreated start/stop / fresh create/destroy
- Precreated owner exact ID/machine/label/type/GPU/offer validation passed:
- Pre-reclaim status fields (`actual_status` / `intended_status` / `cur_state`):
- Owner start/create command issued:
- Owner running proof (`running` / `running` / `running`):
- Owner billing object GPU cost / disk cost (do not confuse with public search price):
- Outside interruptible moved to platform-paused state:
- Pause delay:
- Daemon stayed online:
- Maximum observed temperature/power/disk use:
- Errors or failed starts:

## After release

- Release action: precreated stop / fresh destroy
- Precreated post-release status fields (`actual_status` / `intended_status` / `cur_state`) and disk retained:
- Fresh destroy confirmation: explicit `success: true` / absent from both CLI views / not applicable
- Outside interruptible automatically resumed:
- Resume delay:
- Daemon stayed online:
- Reliability immediately after:
- Reliability after delayed platform update:
- Verification after delayed platform update:
- Storage/direct ports healthy:

## Result

- Accepted / rejected:
- Reason:
- Follow-up change:
- Gross rental earnings for trial interval:
- Utilization hours:
- Rating-impact conclusion: unknown / no observed change / observed change

Do not convert “no observed change” into a general guarantee. Vast does not explicitly document zero rating impact for a host reclaim through scheduler preemption.

A same-account interruptible rental followed by a same-account owner on-demand create is not an accepted reclaim trial. The observed platform response was HTTP 400 / error 3763 (`GPU conflict`), so this setup does not test priority over an outside interruptible renter.
