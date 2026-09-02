#!/usr/bin/env python3
"""Fail-closed Vast interruptible-floor pricing helper.

The only mutation in this module is ``vastai set min-bid ID --price PRICE``.
All input comes from current Vast CLI JSON and every applied change is proved by
an exact post-read of the host machine record.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import secrets
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable, NoReturn, Sequence


PRICE_QUANTUM = Decimal("0.0001")
ALLOWED_VERIFICATION = {"verified", "unverified"}
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{40,}")


class PricingError(RuntimeError):
    """A condition under which no pricing mutation is safe."""


def fail(message: str) -> NoReturn:
    raise PricingError(message)


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def decimal_arg(value: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"invalid decimal: {value}") from exc
    if not result.is_finite():
        raise argparse.ArgumentTypeError(f"decimal must be finite: {value}")
    return result


def positive_int(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer: {value}") from exc
    if result <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return result


def nonnegative_float(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid number: {value}") from exc
    if not math.isfinite(result) or result < 0:
        raise argparse.ArgumentTypeError("value must be a finite nonnegative number")
    return result


def fraction_arg(value: str) -> Decimal:
    result = decimal_arg(value)
    if result < 0 or result > 1:
        raise argparse.ArgumentTypeError("fraction must be between 0 and 1")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compute a robust lower-market interruptible price from current "
            "Vast bid offers. Read-only unless --apply is supplied."
        )
    )
    parser.add_argument(
        "--machine-id", type=positive_int, default=env("VAST_MACHINE_ID")
    )
    parser.add_argument("--expected-gpu-name", default=env("VAST_GPU_NAME"))
    parser.add_argument(
        "--expected-gpu-count", type=positive_int, default=env("VAST_GPU_COUNT")
    )
    parser.add_argument(
        "--floor",
        type=decimal_arg,
        default=env("VAST_PRICE_HARD_FLOOR"),
        help="hard host-earned minimum in USD/GPU-hour; required",
    )
    parser.add_argument(
        "--ceiling",
        type=decimal_arg,
        default=env("VAST_PRICE_HARD_CEILING"),
        help="hard host-earned maximum in USD/GPU-hour; required",
    )
    parser.add_argument(
        "--min-comparables",
        type=positive_int,
        default=env("VAST_PRICE_MIN_COMPARABLES", "8"),
    )
    parser.add_argument(
        "--search-limit",
        type=positive_int,
        default=env("VAST_PRICE_SEARCH_LIMIT", "500"),
    )
    parser.add_argument(
        "--undercut-fraction",
        type=fraction_arg,
        default=env("VAST_PRICE_UNDERCUT_FRACTION", "0.02"),
    )
    parser.add_argument(
        "--vram-tolerance-fraction",
        type=fraction_arg,
        default=env("VAST_PRICE_VRAM_TOLERANCE", "0.01"),
    )
    parser.add_argument(
        "--reliability-below-tolerance",
        type=fraction_arg,
        default=env("VAST_PRICE_RELIABILITY_BELOW_TOLERANCE", "0.03"),
    )
    parser.add_argument(
        "--reliability-discount-rate",
        type=fraction_arg,
        default=env("VAST_PRICE_RELIABILITY_DISCOUNT_RATE", "0.25"),
    )
    parser.add_argument(
        "--max-reliability-discount",
        type=fraction_arg,
        default=env("VAST_PRICE_MAX_RELIABILITY_DISCOUNT", "0.15"),
    )
    parser.add_argument(
        "--iqr-multiplier",
        type=nonnegative_float,
        default=env("VAST_PRICE_IQR_MULTIPLIER", "1.5"),
    )
    parser.add_argument(
        "--verify-attempts",
        type=positive_int,
        default=env("VAST_PRICE_VERIFY_ATTEMPTS", "6"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--verify-interval",
        type=nonnegative_float,
        default=env("VAST_PRICE_VERIFY_INTERVAL", "2"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--apply", action="store_true")
    return parser


def coerce_defaults(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Argparse does not type-convert string defaults on every Python release."""

    converters = {
        "machine_id": positive_int,
        "expected_gpu_count": positive_int,
        "floor": decimal_arg,
        "ceiling": decimal_arg,
        "min_comparables": positive_int,
        "search_limit": positive_int,
        "undercut_fraction": fraction_arg,
        "vram_tolerance_fraction": fraction_arg,
        "reliability_below_tolerance": fraction_arg,
        "reliability_discount_rate": fraction_arg,
        "max_reliability_discount": fraction_arg,
        "iqr_multiplier": nonnegative_float,
        "verify_attempts": positive_int,
        "verify_interval": nonnegative_float,
    }
    for name, converter in converters.items():
        value = getattr(args, name)
        if isinstance(value, str):
            try:
                setattr(args, name, converter(value))
            except argparse.ArgumentTypeError as exc:
                parser.error(f"invalid {name.replace('_', '-')}: {exc}")


def validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    missing = []
    for name in (
        "machine_id",
        "expected_gpu_name",
        "expected_gpu_count",
        "floor",
        "ceiling",
    ):
        if getattr(args, name) in (None, ""):
            missing.append("--" + name.replace("_", "-"))
    if missing:
        parser.error(
            "required argument or environment setting missing: " + ", ".join(missing)
        )
    if args.floor <= 0:
        parser.error("--floor must be greater than zero")
    if args.ceiling < args.floor:
        parser.error("--ceiling must be greater than or equal to --floor")
    try:
        precise_bounds = args.floor == args.floor.quantize(
            PRICE_QUANTUM
        ) and args.ceiling == args.ceiling.quantize(PRICE_QUANTUM)
    except InvalidOperation:
        precise_bounds = False
    if not precise_bounds:
        parser.error("--floor and --ceiling support at most four decimal places")
    if args.search_limit < args.min_comparables:
        parser.error("--search-limit must be at least --min-comparables")
    if args.undercut_fraction > Decimal("0.10"):
        parser.error("--undercut-fraction is capped at 0.10")
    if args.max_reliability_discount > Decimal("0.25"):
        parser.error("--max-reliability-discount is capped at 0.25")


def redacted(text: str) -> str:
    return TOKEN_RE.sub("<redacted-token>", text.strip())


def run_cli(argv: Sequence[str], *, expect_json: bool) -> Any:
    command = list(argv)
    cli_override = env("VAST_CLI_BIN")
    if cli_override and command and command[0] == "vastai":
        # This is primarily useful for offline test doubles. A Windows Python
        # process cannot execute a shebang-only shell script directly, so pass
        # an explicit .sh override through bash. Normal installations continue
        # to execute the real `vastai` command from PATH.
        if os.name == "nt" and cli_override.casefold().endswith(".sh"):
            command = ["bash", cli_override, *command[1:]]
        else:
            command = [cli_override, *command[1:]]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        fail(f"Vast CLI could not run: {exc}")
    if completed.returncode != 0:
        detail = redacted(completed.stderr or completed.stdout or "no diagnostic")
        fail(f"Vast CLI failed ({completed.returncode}): {detail}")
    if not expect_json:
        return completed.stdout
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        fail(f"Vast CLI returned malformed JSON: {exc.msg}")


def normalize_model(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        fail("GPU model is missing or not a string")
    return " ".join(value.replace("_", " ").split()).casefold()


def string_field(record: dict[str, Any], name: str) -> str:
    value = record.get(name)
    if not isinstance(value, str) or not value.strip():
        fail(f"field {name} is missing or malformed")
    return value.strip()


def int_field(record: dict[str, Any], name: str) -> int:
    value = record.get(name)
    if isinstance(value, bool):
        fail(f"field {name} is malformed")
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail(f"field {name} is missing or malformed")
    if not numeric.is_finite() or numeric != numeric.to_integral_value():
        fail(f"field {name} is not an integer")
    return int(numeric)


def number_field(
    record: dict[str, Any], name: str, *, positive: bool = False
) -> Decimal:
    value = record.get(name)
    if isinstance(value, bool):
        fail(f"field {name} is malformed")
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail(f"field {name} is missing or malformed")
    if not numeric.is_finite() or (positive and numeric <= 0):
        fail(f"field {name} is outside its valid range")
    return numeric


def reliability_field(record: dict[str, Any], name: str) -> Decimal:
    value = number_field(record, name)
    if value < 0 or value > 1:
        fail(f"field {name} must be between 0 and 1")
    return value


def verification_field(record: dict[str, Any]) -> str:
    value = string_field(record, "verification").casefold()
    if value not in ALLOWED_VERIFICATION and value != "deverified":
        fail("field verification has an unrecognized value")
    return value


def exact_machine_record(payload: Any, machine_id: int) -> dict[str, Any]:
    if not isinstance(payload, list):
        fail("show machine JSON must be an array")
    if any(not isinstance(row, dict) for row in payload):
        fail("show machine JSON contains a non-object row")
    matches = [row for row in payload if int_field(row, "id") == machine_id]
    if len(matches) != 1 or len(payload) != 1:
        fail("show machine did not return exactly the requested machine")
    return matches[0]


@dataclass(frozen=True)
class MachineIdentity:
    machine_id: int
    gpu_name: str
    gpu_name_normalized: str
    gpu_count: int
    reliability: Decimal
    verification: str
    current_floor: Decimal


def parse_machine(record: dict[str, Any], args: argparse.Namespace) -> MachineIdentity:
    machine_id = int_field(record, "id")
    if machine_id != args.machine_id:
        fail("machine identity changed")
    gpu_name = string_field(record, "gpu_name")
    normalized = normalize_model(gpu_name)
    if normalized != normalize_model(args.expected_gpu_name):
        fail("machine GPU model does not match --expected-gpu-name")
    gpu_count = int_field(record, "num_gpus")
    if gpu_count != args.expected_gpu_count:
        fail("machine GPU count does not match --expected-gpu-count")
    reliability = reliability_field(record, "reliability2")
    verification = verification_field(record)
    if verification not in ALLOWED_VERIFICATION:
        fail("refusing to price a deverified machine")
    current_floor = number_field(record, "min_bid_price", positive=True)
    return MachineIdentity(
        machine_id,
        gpu_name,
        normalized,
        gpu_count,
        reliability,
        verification,
        current_floor,
    )


@dataclass(frozen=True)
class Offer:
    offer_id: int
    machine_id: int
    gpu_name: str
    gpu_name_normalized: str
    gpu_ram_mib: Decimal
    reliability: Decimal
    verification: str
    market_min_bid: Decimal
    rentable: bool | None
    rented: bool | None


def bool_or_none(record: dict[str, Any], name: str) -> bool | None:
    if name not in record or record[name] is None:
        return None
    if not isinstance(record[name], bool):
        fail(f"field {name} is malformed")
    return record[name]


def parse_offer(record: Any) -> Offer:
    if not isinstance(record, dict):
        fail("offer JSON contains a non-object row")
    num_gpus = int_field(record, "num_gpus")
    if num_gpus != 1:
        fail("bid search returned a non-1-GPU bundle")
    gpu_name = string_field(record, "gpu_name")
    return Offer(
        offer_id=int_field(record, "id"),
        machine_id=int_field(record, "machine_id"),
        gpu_name=gpu_name,
        gpu_name_normalized=normalize_model(gpu_name),
        gpu_ram_mib=number_field(record, "gpu_ram", positive=True),
        reliability=reliability_field(record, "reliability"),
        verification=verification_field(record),
        market_min_bid=number_field(record, "min_bid", positive=True),
        rentable=bool_or_none(record, "rentable"),
        rented=bool_or_none(record, "rented"),
    )


def parse_offer_array(payload: Any) -> list[Offer]:
    if not isinstance(payload, list) or not payload:
        fail("bid search returned an empty or malformed offer array")
    return [parse_offer(row) for row in payload]


def dec_median(values: Iterable[Decimal]) -> Decimal:
    ordered = sorted(values)
    if not ordered:
        fail("cannot calculate a median from no values")
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def quantile(values: Iterable[Decimal], q: Decimal) -> Decimal:
    ordered = sorted(values)
    if not ordered:
        fail("cannot calculate a quantile from no values")
    if len(ordered) == 1:
        return ordered[0]
    position = Decimal(len(ordered) - 1) * q
    lower = int(position.to_integral_value(rounding="ROUND_FLOOR"))
    upper = int(position.to_integral_value(rounding="ROUND_CEILING"))
    if lower == upper:
        return ordered[lower]
    fraction = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def consistent(values: Iterable[Decimal], tolerance: Decimal) -> bool:
    ordered = sorted(values)
    return bool(ordered) and ordered[-1] - ordered[0] <= tolerance


@dataclass(frozen=True)
class Comparable:
    machine_id: int
    offer_count: int
    host_price: Decimal
    market_price: Decimal
    reliability: Decimal
    verification: str
    gpu_ram_mib: Decimal


def shell_query_model(model: str) -> str:
    normalized = "_".join(model.strip().split())
    if not re.fullmatch(r"[A-Za-z0-9_.+:-]+", normalized):
        fail("GPU model cannot be represented safely in a Vast CLI query")
    return normalized


def show_machine(machine_id: int) -> dict[str, Any]:
    payload = run_cli(
        ["vastai", "show", "machine", str(machine_id), "--raw"], expect_json=True
    )
    return exact_machine_record(payload, machine_id)


def search_own_offers(args: argparse.Namespace) -> list[Offer]:
    query = (
        f"machine_id={args.machine_id} num_gpus=1 verified=any rentable=any rented=any"
    )
    payload = run_cli(
        [
            "vastai",
            "search",
            "offers",
            query,
            "--type",
            "bid",
            "--no-default",
            "--storage",
            "0",
            "--raw",
            "--limit",
            str(args.search_limit),
            "--order",
            "min_bid",
        ],
        expect_json=True,
    )
    return parse_offer_array(payload)


def search_market_offers(
    args: argparse.Namespace, machine: MachineIdentity, own_vram: Decimal
) -> list[Offer]:
    reliability_floor = max(
        Decimal("0"), machine.reliability - args.reliability_below_tolerance
    )
    vram_low = own_vram * (Decimal("1") - args.vram_tolerance_fraction)
    vram_high = own_vram * (Decimal("1") + args.vram_tolerance_fraction)
    # Raw offer JSON reports MB, while the CLI query grammar applies a 1000x
    # multiplier to gpu_ram values documented and entered as decimal GB.
    query_vram_low = vram_low / Decimal("1000")
    query_vram_high = vram_high / Decimal("1000")
    query = (
        f"gpu_name={shell_query_model(machine.gpu_name)} num_gpus=1 "
        f"gpu_ram>={query_vram_low:f} gpu_ram<={query_vram_high:f} "
        f"reliability>={reliability_floor:f} verified=any "
        f"machine_id!={machine.machine_id} external=false "
        "rentable=true rented=false"
    )
    payload = run_cli(
        [
            "vastai",
            "search",
            "offers",
            query,
            "--type",
            "bid",
            "--no-default",
            "--storage",
            "0",
            "--raw",
            "--limit",
            str(args.search_limit),
            "--order",
            "min_bid",
        ],
        expect_json=True,
    )
    return parse_offer_array(payload)


def derive_market_factor(
    machine: MachineIdentity, own_offers: list[Offer], args: argparse.Namespace
) -> tuple[Decimal, Decimal, Decimal]:
    for offer in own_offers:
        if offer.machine_id != machine.machine_id:
            fail("own-machine bid search returned another machine")
        if offer.gpu_name_normalized != machine.gpu_name_normalized:
            fail("own-machine offer GPU model differs from machine identity")
        if abs(offer.reliability - machine.reliability) > Decimal("0.01"):
            fail("own-machine offer reliability differs from machine identity")
        if offer.verification != machine.verification:
            fail("own-machine offer verification differs from machine identity")
    own_vram = dec_median(o.gpu_ram_mib for o in own_offers)
    if not consistent(
        (o.gpu_ram_mib for o in own_offers),
        own_vram * args.vram_tolerance_fraction,
    ):
        fail("own-machine 1-GPU offers disagree on VRAM")
    own_market_min_bid = dec_median(o.market_min_bid for o in own_offers)
    if not consistent(
        (o.market_min_bid for o in own_offers),
        max(Decimal("0.0001"), own_market_min_bid * Decimal("0.005")),
    ):
        fail("own-machine 1-GPU offers disagree on interruptible price")
    factor = machine.current_floor / own_market_min_bid
    if factor < Decimal("0.50") or factor > Decimal("1.05"):
        fail("derived marketplace-to-host price factor is outside 0.50..1.05")
    return own_vram, own_market_min_bid, factor


def build_comparables(
    offers: list[Offer],
    machine: MachineIdentity,
    own_vram: Decimal,
    factor: Decimal,
    args: argparse.Namespace,
) -> list[Comparable]:
    groups: dict[int, list[Offer]] = defaultdict(list)
    low_vram = own_vram * (Decimal("1") - args.vram_tolerance_fraction)
    high_vram = own_vram * (Decimal("1") + args.vram_tolerance_fraction)
    rel_floor = max(
        Decimal("0"), machine.reliability - args.reliability_below_tolerance
    )
    for offer in offers:
        if offer.machine_id == machine.machine_id:
            continue
        if offer.gpu_name_normalized != machine.gpu_name_normalized:
            continue
        if not low_vram <= offer.gpu_ram_mib <= high_vram:
            continue
        if offer.reliability < rel_floor:
            continue
        if offer.verification == "deverified":
            continue
        if machine.verification == "verified" and offer.verification != "verified":
            continue
        if offer.rentable is None or offer.rented is None:
            fail("market offer availability fields are missing")
        if offer.rentable is not True or offer.rented is not False:
            continue
        groups[offer.machine_id].append(offer)

    result: list[Comparable] = []
    for machine_id, rows in groups.items():
        if not consistent((r.reliability for r in rows), Decimal("0.005")):
            fail(f"offers for comparable machine {machine_id} disagree on reliability")
        verification_values = {r.verification for r in rows}
        if len(verification_values) != 1:
            fail(f"offers for comparable machine {machine_id} disagree on verification")
        market_price = dec_median(r.market_min_bid for r in rows)
        result.append(
            Comparable(
                machine_id=machine_id,
                offer_count=len(rows),
                host_price=market_price * factor,
                market_price=market_price,
                reliability=dec_median(r.reliability for r in rows),
                verification=rows[0].verification,
                gpu_ram_mib=dec_median(r.gpu_ram_mib for r in rows),
            )
        )
    return sorted(result, key=lambda row: (row.host_price, row.machine_id))


def reject_outliers(
    comparables: list[Comparable], multiplier: float
) -> tuple[list[Comparable], Decimal, Decimal]:
    prices = [row.host_price for row in comparables]
    q1 = quantile(prices, Decimal("0.25"))
    q3 = quantile(prices, Decimal("0.75"))
    width = q3 - q1
    multiplier_decimal = Decimal(str(multiplier))
    low = q1 - multiplier_decimal * width
    high = q3 + multiplier_decimal * width
    retained = [row for row in comparables if low <= row.host_price <= high]
    return retained, low, high


def quantized_price(value: Decimal, floor: Decimal, ceiling: Decimal) -> Decimal:
    clamped = min(ceiling, max(floor, value))
    rounded = clamped.quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)
    return min(ceiling, max(floor, rounded))


def format_decimal(value: Decimal, places: int = 4) -> str:
    quantum = Decimal(1).scaleb(-places)
    return f"{value.quantize(quantum, rounding=ROUND_HALF_UP):.{places}f}"


def state_directory() -> Path:
    project = Path(__file__).resolve().parent.parent
    configured = env(
        "VAST_STATE_DIR",
        str(Path.home() / ".local" / "state" / "vast-host-golden-path"),
    )
    state = Path(str(configured)).expanduser().resolve()
    try:
        state.relative_to(project)
    except ValueError:
        pass
    else:
        fail(f"VAST_STATE_DIR must be outside the repository: {state}")
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        state.chmod(0o700)
    except OSError:
        pass
    pricing = state / "adaptive-pricing"
    pricing.mkdir(exist_ok=True, mode=0o700)
    try:
        pricing.chmod(0o700)
    except OSError:
        pass
    return pricing


def json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


def write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(json_value(snapshot), indent=2, sort_keys=True) + "\n"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def snapshot_path(directory: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return directory / f"pricing-{timestamp}-{secrets.token_hex(3)}.json"


def print_table(comparables: list[Comparable], outliers: set[int]) -> None:
    print(
        "\nComparable  Host $/GPU-h  Market $/GPU-h  Reliability  Verification  VRAM MiB  Offers"
    )
    print(
        "----------  ------------  --------------  -----------  ------------  --------  ------"
    )
    for index, row in enumerate(comparables, start=1):
        marker = "*" if row.machine_id in outliers else " "
        print(
            f"{marker}{index:<9}  {format_decimal(row.host_price):>12}  "
            f"{format_decimal(row.market_price):>14}  "
            f"{format_decimal(row.reliability, 3):>11}  "
            f"{row.verification:>12}  {format_decimal(row.gpu_ram_mib, 0):>8}  "
            f"{row.offer_count:>6}"
        )
    if outliers:
        print("* excluded by the Tukey IQR fence")


class MutationLock:
    def __init__(self, directory: Path):
        self.path = directory.parent / "adaptive-min-bid.lock"

    def __enter__(self) -> "MutationLock":
        try:
            self.path.mkdir(mode=0o700)
        except FileExistsError:
            fail(f"another pricing apply may be active: {self.path}")
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            self.path.rmdir()
        except OSError:
            pass


def identity_unchanged(before: MachineIdentity, after: MachineIdentity) -> None:
    if before != after:
        fail(
            "machine identity, rating, verification, or current price changed before apply"
        )


def post_apply_identity_unchanged(
    before: MachineIdentity, after: MachineIdentity
) -> None:
    before_guard = (
        before.machine_id,
        before.gpu_name_normalized,
        before.gpu_count,
        before.reliability,
        before.verification,
    )
    after_guard = (
        after.machine_id,
        after.gpu_name_normalized,
        after.gpu_count,
        after.reliability,
        after.verification,
    )
    if before_guard != after_guard:
        fail(
            "machine identity, rating, or verification changed during apply; "
            "the price mutation outcome is uncertain"
        )


def verify_applied(
    args: argparse.Namespace, before: MachineIdentity, target: Decimal
) -> MachineIdentity:
    latest = before
    for attempt in range(args.verify_attempts):
        latest = parse_machine(show_machine(args.machine_id), args)
        post_apply_identity_unchanged(before, latest)
        if abs(latest.current_floor - target) <= Decimal("0.00005"):
            return latest
        if attempt + 1 < args.verify_attempts:
            time.sleep(args.verify_interval)
    fail(
        "set min-bid returned but the exact machine record did not prove the new price; "
        "inspect the private snapshot and Host Machines view before retrying"
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    coerce_defaults(args, parser)
    validate_args(args, parser)
    directory = state_directory()
    path = snapshot_path(directory)
    machine = parse_machine(show_machine(args.machine_id), args)
    own_offers = search_own_offers(args)
    own_vram, own_market_min_bid, factor = derive_market_factor(
        machine, own_offers, args
    )
    market_offers = search_market_offers(args, machine, own_vram)
    if len(market_offers) >= args.search_limit:
        fail(
            f"market search reached the {args.search_limit}-offer limit; "
            "the comparable sample may be truncated"
        )
    comparables = build_comparables(market_offers, machine, own_vram, factor, args)
    if len(comparables) < args.min_comparables:
        fail(
            f"only {len(comparables)} unique eligible machines; "
            f"need at least {args.min_comparables}"
        )
    retained, fence_low, fence_high = reject_outliers(comparables, args.iqr_multiplier)
    if len(retained) < args.min_comparables:
        fail(
            f"only {len(retained)} unique machines remain after outlier filtering; "
            f"need at least {args.min_comparables}"
        )

    p10 = quantile((row.host_price for row in retained), Decimal("0.10"))
    median_reliability = dec_median(row.reliability for row in retained)
    reliability_gap = max(Decimal("0"), median_reliability - machine.reliability)
    reliability_discount = min(
        args.max_reliability_discount,
        reliability_gap * args.reliability_discount_rate,
    )
    raw_target = (
        p10
        * (Decimal("1") - args.undercut_fraction)
        * (Decimal("1") - reliability_discount)
    )
    target = quantized_price(raw_target, args.floor, args.ceiling)
    outlier_ids = {row.machine_id for row in comparables} - {
        row.machine_id for row in retained
    }
    clamped = "none"
    if raw_target < args.floor:
        clamped = "floor"
    elif raw_target > args.ceiling:
        clamped = "ceiling"

    snapshot: dict[str, Any] = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "dry-run",
        "status": "computed",
        "mutation_scope": "interruptible-minimum-only",
        "machine": {
            "id": machine.machine_id,
            "gpu_name": machine.gpu_name,
            "gpu_count": machine.gpu_count,
            "gpu_ram_mib": own_vram,
            "reliability": machine.reliability,
            "verification": machine.verification,
            "current_host_floor": machine.current_floor,
            "own_market_min_bid": own_market_min_bid,
            "market_to_host_factor": factor,
        },
        "policy": {
            "hard_floor": args.floor,
            "hard_ceiling": args.ceiling,
            "minimum_comparables": args.min_comparables,
            "undercut_fraction": args.undercut_fraction,
            "vram_tolerance_fraction": args.vram_tolerance_fraction,
            "reliability_below_tolerance": args.reliability_below_tolerance,
            "reliability_discount_rate": args.reliability_discount_rate,
            "maximum_reliability_discount": args.max_reliability_discount,
            "iqr_multiplier": args.iqr_multiplier,
        },
        "calculation": {
            "raw_offer_count": len(market_offers),
            "unique_comparable_count": len(comparables),
            "retained_comparable_count": len(retained),
            "iqr_fence_low": fence_low,
            "iqr_fence_high": fence_high,
            "p10_host_price": p10,
            "median_comparable_reliability": median_reliability,
            "reliability_gap": reliability_gap,
            "reliability_discount": reliability_discount,
            "raw_target": raw_target,
            "clamped_by": clamped,
            "target_host_floor": target,
        },
        "comparables": [
            {
                "machine_id": row.machine_id,
                "offer_count": row.offer_count,
                "host_price": row.host_price,
                "market_price": row.market_price,
                "reliability": row.reliability,
                "verification": row.verification,
                "gpu_ram_mib": row.gpu_ram_mib,
                "outlier_excluded": row.machine_id in outlier_ids,
            }
            for row in comparables
        ],
        "planned_command": [
            "vastai",
            "set",
            "min-bid",
            str(machine.machine_id),
            "--price",
            format_decimal(target),
        ],
    }
    write_snapshot(path, snapshot)

    print_table(comparables, outlier_ids)
    print(
        f"\nUnique comparables:         {len(retained)} retained of "
        f"{len(comparables)} ({len(market_offers)} raw offers)"
    )
    print(
        f"Market-to-host factor:      {format_decimal(factor)} (derived from own listing)"
    )
    print(f"Machine reliability:       {format_decimal(machine.reliability, 3)}")
    print(f"Comparable reliability:    {format_decimal(median_reliability, 3)} median")
    print(f"Robust host-price P10:      ${format_decimal(p10)}/GPU-hour")
    print(
        f"Reliability discount:       {format_decimal(reliability_discount * 100, 2)}%"
    )
    print(f"Unclamped target:           ${format_decimal(raw_target)}/GPU-hour")
    print(f"Guarded target:             ${format_decimal(target)}/GPU-hour ({clamped})")
    print(
        f"Current interruptible floor: ${format_decimal(machine.current_floor)}/GPU-hour"
    )
    print(f"Private evidence snapshot:  {path}")

    if abs(machine.current_floor - target) <= Decimal("0.00005"):
        snapshot["status"] = "no-change"
        write_snapshot(path, snapshot)
        print(
            "No mutation needed; the exact machine already reports the guarded target."
        )
        return 0

    command = [
        "vastai",
        "set",
        "min-bid",
        str(machine.machine_id),
        "--price",
        format_decimal(target),
    ]
    if not args.apply:
        print("DRY RUN: " + " ".join(command))
        print(
            "This changes only the minimum for future interruptible bids; it does not change on-demand/reserved pricing or end a contract."
        )
        snapshot["status"] = "dry-run-complete"
        write_snapshot(path, snapshot)
        return 0

    if not sys.stdin.isatty():
        fail("refusing a mutation without an interactive terminal")

    with MutationLock(directory):
        latest = parse_machine(show_machine(args.machine_id), args)
        identity_unchanged(machine, latest)
        confirmation = f"SET MIN-BID {machine.machine_id} TO {format_decimal(target)}"
        typed = input(f"Type {confirmation} to change only the interruptible floor: ")
        if typed != confirmation:
            fail("typed confirmation did not match")
        confirmed = parse_machine(show_machine(args.machine_id), args)
        identity_unchanged(latest, confirmed)
        try:
            mutation_output = run_cli(command, expect_json=False)
        except PricingError as exc:
            snapshot["status"] = "mutation-command-failed-or-uncertain"
            snapshot["mutation_diagnostic"] = redacted(str(exc))
            write_snapshot(path, snapshot)
            raise
        snapshot["mutation_diagnostic"] = redacted(str(mutation_output))
        snapshot["status"] = "mutation-returned-verifying"
        write_snapshot(path, snapshot)
        try:
            verified = verify_applied(args, confirmed, target)
        except PricingError:
            snapshot["status"] = "mutation-postcondition-unproved"
            write_snapshot(path, snapshot)
            raise
        snapshot["status"] = "applied-and-verified"
        snapshot["verified_at"] = datetime.now(timezone.utc).isoformat()
        snapshot["verified_host_floor"] = verified.current_floor
        write_snapshot(path, snapshot)
    print(
        f"Applied and verified exact machine {machine.machine_id} at "
        f"${format_decimal(target)}/GPU-hour interruptible minimum."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PricingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
