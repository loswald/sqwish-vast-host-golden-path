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

## Before reclaim

- Reliability score:
- Verification state:
- Daemon healthy:
- Red errors:
- Contract types reviewed in Host Machines/Contracts view:
- Only outside interruptible contract present:
- GPU/disk/network within validated envelope:

## During reclaim

- Owner on-demand create succeeded:
- Owner instance reached `running`:
- Outside interruptible moved to platform-paused state:
- Pause delay:
- Daemon stayed online:
- Maximum observed temperature/power/disk use:
- Errors or failed starts:

## After release

- Destroyed owner instance only:
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
