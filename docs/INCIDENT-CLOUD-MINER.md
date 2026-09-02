# Cloud-VM miner incident: sanitized postmortem

## Outcome

A temporary cloud L4 host was publicly listed at a very low interruptible price to attract a short test rental. The infrastructure provider detected cryptocurrency-mining behavior from that VM for approximately four minutes. The workload had ended before the next detailed inspection, so the host appeared vacant and had no running containers when checked.

The trial was contained immediately after the notice: both Vast hosts were unlisted, all owner instances were destroyed, both trial VMs and their trial disks and addresses were deleted, the Vast-only firewall was deleted, the automation was removed, and the two offline machine records were deleted from Vast. Unrelated cloud workloads were left running.

This test did not reach the planned interrupt/reclaim/resume experiment. Its useful result is that unrestricted public hosting creates an abuse path that polling and interruptible scheduling do not control.

## Evidence

These are the verified, sanitized facts:

- The provider's structured abuse event identified one four-minute `CRYPTO_MINING` window on the L4 host.
- Hypervisor metrics showed CPU rising from an idle baseline to roughly 80 percent during the same window, then returning to idle.
- The VM downloaded roughly 136 MB immediately before detection and contacted a known mining-pool endpoint.
- The later host inspection found the cached tag `spacepirateman/giga-cpu-miner:latest`, but no running or retained container.
- The current public image behind that tag contains XMRig and is configured to use about 80 percent of available CPU threads. Its current registry digest was not proven to be the deleted local digest, so it is corroborating evidence rather than an exact artifact match.
- Vast recorded GPU rental earnings on the incident date and attributed them to the L4. The known owner self-test and standby contracts were free and did not produce those earnings, supporting a separate paid rental. Rounded earnings are not used to infer an exact duration.
- No unknown cloud principal, new service-account key, IAM change, or control-plane action was found. The affected VM had no attached cloud service account.
- The official Vast self-test had run about 2.5 hours earlier with a different `vastai/test` image. It was not the immediate trigger.

The best-supported explanation is a short-lived outside rental that pulled and ran the miner image, then exited or was destroyed before the next poll. No historical Vast contract ID or exact local image digest was captured, so that actor attribution remains a strong inference.

## Why monitoring failed

The monitor sampled current host and instance state every five minutes. The workload lasted about four minutes. A point-in-time result of `clients=[]`, zero current rentals, and empty occupancy therefore described only the instant of the query. It did not prove that the preceding interval was vacant.

The same limitation applies to the Host Machines card and `show machine`: current rental counters are not an event history. Rounded `$0.00` earnings can also hide a small completed rental. Historical contract events, unrounded earnings, Docker events, and network egress must be retained separately.

## Rules for future dedicated-host work

1. Use only operator-owned physical hardware or a provider that has given prior written approval for third-party hosting and the workloads tenants may run. Do not repeat this experiment on an unapproved cloud VM.
2. Treat a public raw-compute renter as untrusted code execution. Interruptibility controls scheduling; it does not control what the renter executes.
3. Never use a very cheap public listing merely to obtain a fast test renter. Vast officially documents testing through a separate client account on a different email. Pre-authenticate and fund that controlled account, stage an exact-machine create, list at a high reviewed price, acquire every exposed GPU immediately, and unlist as soon as the controlled contract exists. This minimizes but does not eliminate the race before acquisition.
4. Record event-level rental history. Polling must not be the sole evidence of vacancy. If event streaming is unavailable, poll materially faster than the shortest possible contract and reconcile every earnings delta.
5. Enable network-flow, firewall, container-event, and guest logs before exposure. Retain exact image digests and container create/start/destroy events outside the host.
6. Apply egress controls appropriate to the host policy. If arbitrary tenant networking is required, accept that mining and other prohibited workloads cannot be reliably prevented at the infrastructure layer.
7. Keep trial networking and storage isolated and exactly deletable. Preserve a tested kill switch that unlists first, clears retained storage, deletes the host, and verifies absence.
8. Do not describe a later vacant card as proof that no renter ever ran. State the observation time and the history source used.

## Incident-response wording

Be precise about intent and observed behavior:

- The operator intentionally evaluated third-party GPU-host software.
- Cryptocurrency mining was neither requested nor authorized.
- The evidence shows that a short-lived unauthorized mining workload ran through the host software.
- State verified containment, IAM findings, and logging limits. Do not call the provider alert a false positive.
- Do not claim the official self-test caused the event; the timelines and images differ.
