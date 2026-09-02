# Guarded adaptive interruptible pricing

`scripts/adaptive-min-bid.sh` calculates a lower-market minimum for future
**interruptible** rentals. It is read-only by default. It does not change the
on-demand price, reserved pricing, offer end date, or any renter's bid, and it
does not stop, destroy, pause, or evict a contract.

Changing a minimum bid is not a timed reclaim mechanism. Existing contracts
remain contracts and must be honored. Use the separately guarded owner-reclaim
trial only after manually establishing that an outside contract is genuinely
interruptible. Never use host, Docker, power, or price changes to force a
renter off after 30 or 60 minutes.

Vast CLI 1.5.6 has no host-contract inventory command. `show instances` covers
the authenticated account's rentals, not outside contracts on a hosted
machine. Continue to inspect Host Machines/Contracts manually before any owner
reclaim; this pricing helper does not claim that the machine is vacant.

## Required local settings

The helper accepts arguments or the corresponding private environment values:

| Argument | Environment | Purpose |
|---|---|---|
| `--machine-id` | `VAST_MACHINE_ID` | Exact hosted machine to read and, only with `--apply`, change |
| `--expected-gpu-name` | `VAST_GPU_NAME` | Independent exact-model identity guard, with spaces or underscores treated equally |
| `--expected-gpu-count` | `VAST_GPU_COUNT` | Independent physical GPU-count identity guard |
| `--floor` | `VAST_PRICE_HARD_FLOOR` | Lowest host-earned USD/GPU-hour the calculation may select |
| `--ceiling` | `VAST_PRICE_HARD_CEILING` | Highest host-earned USD/GPU-hour the calculation may select |

Do not copy machine IDs into committed files. Keep them in the existing private
`.env` or pass them at runtime. Both floor and ceiling are deliberately required
because an old default is unsafe in a changing market. Bounds accept at most
four decimal places.

Example dry run with explicitly reviewed bounds:

```bash
./scripts/adaptive-min-bid.sh \
  --expected-gpu-name 'RTX PRO 6000 WS' \
  --floor 0.30 \
  --ceiling 1.50
```

The result prints an evidence table, the calculation, the exact dry-run
command, and the path of a private JSON record. Review the comparable count,
P10, reliability adjustment, clamp result, and target before considering a
change.

Apply only the already-reviewed result in an interactive terminal:

```bash
./scripts/adaptive-min-bid.sh \
  --expected-gpu-name 'RTX PRO 6000 WS' \
  --floor 0.30 \
  --ceiling 1.50 \
  --apply
```

Apply mode repeats the exact machine read under a private lock. It aborts if
the machine ID, model, GPU count, rating, verification, or current minimum
changed after calculation. It then requires this typed confirmation, using the
calculated four-decimal target:

```text
SET MIN-BID <MACHINE_ID> TO <TARGET>
```

The only mutation is:

```bash
vastai set min-bid <MACHINE_ID> --price <TARGET>
```

The current official CLI sends `PUT /machines/<id>/minbid/`, but its command
wrapper prints a human message instead of returning the API response under
`--raw`. The helper therefore treats command output as diagnostic and accepts
success only after `vastai show machine <MACHINE_ID> --raw` returns exactly one
record with the guarded identity and the target `min_bid_price`. An unproved
postcondition is reported as uncertain and is never retried automatically.

## Comparable selection and calculation

The helper obtains the owned machine record and its own 1-GPU bid offer first.
Both offer searches explicitly use `--type bid --storage 0`; no on-demand or
reserved search result enters the calculation. It derives the live
marketplace-price to host-earned-price factor from:

```text
current machine min_bid_price / own bid offer min_bid
```

This avoids assuming that the marketplace surcharge relationship is fixed. A
factor outside `0.50..1.05`, missing fields, conflicting owned slices, malformed
JSON, or an empty response aborts the run.

The market search asks only for currently available 1-GPU interruptible offers
with the same normalized GPU model, VRAM within 1%, and reliability no more
than three percentage points below this machine. The local checks repeat every
server-side filter. Raw offer JSON reports VRAM in MB, while Vast CLI's
`gpu_ram` query input is decimal GB; the helper converts by 1,000 for the query
and compares the original raw MB values locally. It excludes:

- the owned machine;
- unavailable or rented offers;
- deverified machines;
- unverified comparables when this machine is already verified; and
- any row with missing, non-finite, nonpositive, or inconsistent evidence.

Multiple offers from one machine collapse to one median observation so one
large host cannot dominate the price distribution. The helper removes prices
outside a 1.5-times Tukey interquartile fence and requires at least eight unique
machines both before and after that step. These settings can be tightened with
`--min-comparables`, `--vram-tolerance-fraction`,
`--reliability-below-tolerance`, and `--iqr-multiplier`.

Offer searches request up to 500 rows ordered by `min_bid`. If the response
reaches that limit, the helper refuses to price because the low-price sample may
be truncated. Raise `--search-limit` or add pagination before using the helper
in a larger market.

These are available asking floors, not a history of prices that won rentals.
Treat the target as a reversible fill experiment and measure actual rental
time, earnings, and reliability before changing the reviewed bounds.

The default calculation is:

```text
P10 = linearly interpolated 10th percentile of retained host-earned prices
rating gap = max(0, median comparable reliability - our reliability)
rating discount = min(15%, rating gap * 25%)
raw target = P10 * (1 - 2% undercut) * (1 - rating discount)
target = raw target clamped to the reviewed hard floor and ceiling
```

The target is rounded to four decimal places. The undercut is capped at 10%
and the rating discount is capped at 25% even when the corresponding options
are changed. A new host therefore receives a bounded price adjustment rather
than an unlimited discount based on a low initial score.

## Private evidence and failure handling

Every successful calculation writes a mode-0600 JSON record below:

```text
${VAST_STATE_DIR}/adaptive-pricing/
```

`VAST_STATE_DIR` must resolve outside this repository. The record includes the
exact policy values, owned-machine evidence, de-duplicated comparable rows,
outlier decisions, calculation, planned command, and apply postcondition. It
can contain marketplace machine IDs, so do not commit or share it.

Apply uses `${VAST_STATE_DIR}/adaptive-min-bid.lock/`. If that directory remains
after an interrupted run, first confirm that no pricing helper process is still
running and inspect the latest snapshot before removing the empty stale lock.

The helper fails closed when the minimum sample is unavailable. Do not lower
`--min-comparables` merely to force a price. Broaden a tolerance only after
checking that the resulting hardware and reliability group is still a real
substitute for this machine. A dry run can be repeated later when the market
has more offers.

The API key used for this workflow needs only `machine_read` for the exact
machine read, `misc` for offer search, and `machine_write` for an applied
minimum-bid change. Do not add user, billing, or team write permissions.

Run the offline fake-CLI coverage after changing the helper:

```bash
bash tests/adaptive-min-bid-tests.sh
```

## Current official references

- [Vast set-min-bid API and CLI usage](https://docs.vast.ai/api-reference/machines/set-min-bid)
- [Vast search-offers fields and bid type](https://docs.vast.ai/api-reference/search/search-offers)
- [Vast hosting offers and contract obligations](https://docs.vast.ai/host/hosting-overview)
- [Current official CLI machine command source](https://github.com/vast-ai/vast-cli/blob/master/vastai/cli/commands/machines.py)

The command surface was checked against official CLI source commit
`c26d8a8dfc908b0315f0070c187f5bf23abe5d68` on 2 September 2026. Recheck it
before relying on the helper after a CLI or platform update.
