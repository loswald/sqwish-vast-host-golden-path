#!/usr/bin/env python3
"""Fail-closed acquisition of controlled interruptible contracts.

The host is public only between one guarded ``list machine`` call and the
``unlist machine`` call in the acquisition ``finally`` path.  Supported shapes
are one exact two-GPU contract on a two-GPU machine, or four uniquely labelled
one-GPU contracts on an exact four-GPU machine.  The program never retries a
label's ``create instance`` call and contains no destroy operation.  Raw command
evidence is stored under VAST_STATE_DIR, outside the repository.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable


GPU_COUNT = 2  # Backward-compatible default; live checks use Config.gpu_count.
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{40,}")
SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|machineapikey|token|password|credential|secret|"
    r"ssh[_-]?(?:key|public[_-]?key)|email|(?:public|external)[_-]?ip|ip[_-]?address)",
    re.I,
)
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)((?:['\"])?(?:instance[_-]?api[_-]?key|api[_-]?key|machineapikey|token|"
    r"password|credential|secret|ssh[_-]?(?:key|public[_-]?key)|email|"
    r"(?:public|external)[_-]?ip|ip[_-]?address)(?:['\"])?\s*[:=]\s*['\"]?)"
    r"[^'\",}\s]+"
)
SENSITIVE_QUOTED_TEXT_RE = re.compile(
    r"(?i)((?:['\"])?(?:instance[_-]?api[_-]?key|api[_-]?key|machineapikey|token|"
    r"password|credential|secret|ssh[_-]?(?:key|public[_-]?key)|email|"
    r"(?:public|external)[_-]?ip|ip[_-]?address)(?:['\"])?\s*[:=]\s*)(['\"])"
    r"[^'\"]*\2"
)
EMAIL_RE = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])")
IPV4_RE = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
IMAGE_RE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{7,79}$")
SAFE_STOPPED_ACTUAL = {"created", "exited", "stopped"}
NO_SUCH_ASK_RE = re.compile(r"(?<![A-Za-z0-9_])no_such_ask(?![A-Za-z0-9_])")
RUNNING_TUPLE = ("running", "running", "running")
CLI_TIMEOUT_SECONDS = 45.0


class AcquisitionError(RuntimeError):
    pass


class UnknownContractError(AcquisitionError):
    pass


class TransientOfferAbsence(AcquisitionError):
    pass


class DefinitiveNoContractError(AcquisitionError):
    """The one create was rejected before Vast created a contract."""

    def __init__(
        self,
        message: str,
        payload: dict[str, Any],
        *,
        label: str,
        offer_id: str,
    ) -> None:
        super().__init__(message)
        self.payload = payload
        self.label = label
        self.offer_id = offer_id


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def redact(value: str) -> str:
    sanitized = SENSITIVE_QUOTED_TEXT_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>{match.group(2)}",
        value,
    )
    sanitized = SENSITIVE_TEXT_RE.sub(r"\1<redacted>", sanitized)
    sanitized = EMAIL_RE.sub("<redacted-email>", sanitized)
    sanitized = IPV4_RE.sub("<redacted-ip>", sanitized)
    return TOKEN_RE.sub("<redacted-token>", sanitized)


def sanitize_evidence(value: Any, *, key: str | None = None) -> Any:
    """Remove credentials before any private evidence write.

    Exact digest-pinned images and labels are operational identity evidence, so
    preserve them only in their validated structural slots.
    """

    if isinstance(value, dict):
        return {
            str(item_key): (
                "<redacted>"
                if SENSITIVE_KEY_RE.search(str(item_key))
                else sanitize_evidence(item, key=str(item_key))
            )
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_evidence(item, key=key) for item in value]
    if isinstance(value, str):
        if key == "image" and IMAGE_RE.fullmatch(value):
            return value
        if key == "label" and SAFE_LABEL_RE.fullmatch(value):
            return value
        return redact(value)
    return value


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(sanitize_evidence(value), handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def positive_id(value: Any, what: str) -> str:
    if isinstance(value, bool):
        raise AcquisitionError(f"{what} is not a positive ID")
    text = str(value)
    if not text.isdigit() or int(text) <= 0:
        raise AcquisitionError(f"{what} is not a positive ID")
    return text


def identifier(record: dict[str, Any]) -> str:
    for field in ("id", "contract_id", "instance_id"):
        if field in record:
            return str(record[field])
    return ""


def machine_identifier(record: dict[str, Any]) -> str:
    return str(record.get("machine_id", record.get("id", "")))


def strict_rows(value: Any, what: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise AcquisitionError(f"{what} must be an exact JSON array of objects")
    return value


def exact_machine(value: Any, machine_id: str) -> dict[str, Any]:
    rows = strict_rows(value, "machine response")
    matches = [row for row in rows if machine_identifier(row) == machine_id]
    if len(matches) != 1:
        raise AcquisitionError(f"machine response did not contain exactly one machine {machine_id}")
    return matches[0]


def exact_instance(value: Any, instance_id: str, what: str) -> dict[str, Any]:
    rows: list[dict[str, Any]]
    if isinstance(value, dict) and isinstance(value.get("instances"), list):
        rows = strict_rows(value["instances"], what)
    elif isinstance(value, dict):
        rows = [value]
    else:
        rows = strict_rows(value, what)
    matches = [row for row in rows if identifier(row) == instance_id]
    if len(matches) != 1:
        raise AcquisitionError(f"{what} did not contain exactly one instance {instance_id}")
    return matches[0]


def authenticated_account_id(value: Any, what: str) -> str:
    rows = value if isinstance(value, list) else [value]
    ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("id", row.get("user_id"))
        try:
            ids.add(positive_id(raw, what))
        except AcquisitionError:
            continue
    if len(ids) != 1:
        raise AcquisitionError(f"{what} response lacks one exact positive account ID")
    return next(iter(ids))


def number(record: dict[str, Any], names: tuple[str, ...], what: str) -> float:
    for name in names:
        value = record.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parsed = float(value)
            if math.isfinite(parsed):
                return parsed
    raise AcquisitionError(f"{what} is missing or invalid")


def require_close(actual: float, expected: float, what: str) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-8):
        raise AcquisitionError(f"{what} mismatch: expected {expected}, got {actual}")


def parse_end(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            try:
                return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                return None
    return None


def require_exact_end(record: dict[str, Any], expected: int, what: str) -> None:
    parsed = parse_end(record.get("end_date"))
    if parsed is None or abs(parsed - expected) > 1.0:
        raise AcquisitionError(f"{what} omitted or changed the fixed end")


def current_rentals(machine: dict[str, Any]) -> int:
    raw = machine.get("current_rentals_running")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not float(raw).is_integer():
        raise AcquisitionError("machine current_rentals_running is missing or invalid")
    value = int(raw)
    if value < 0:
        raise AcquisitionError("machine current_rentals_running is negative")
    return value


def exact_no_such_ask_rejection(
    result: subprocess.CompletedProcess[str],
) -> dict[str, Any] | None:
    """Recognize only the current CLI's exact machine-readable rejection shape.

    Vast CLI raw mode can exit zero after an HTTP error while emitting a JSON
    object on stderr.  A 400 ``no_such_ask`` means the selected ask vanished
    before acceptance, so no contract was created.  Every mixed, malformed, or
    differently-coded response remains unresolved.
    """

    if result.stdout.strip():
        return None
    try:
        payload = json.loads(result.stderr)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("error") is not True or payload.get("status_code") != 400:
        return None
    message = payload.get("msg")
    if not isinstance(message, str) or NO_SUCH_ASK_RE.search(message) is None:
        return None
    return payload


class Cli:
    """One pre-authenticated CLI executable; API keys are never arguments."""

    def __init__(self, executable: str, role: str) -> None:
        resolved = shutil.which(executable)
        if not resolved:
            raise AcquisitionError(f"{role} CLI executable not found: {executable}")
        self.executable = str(Path(resolved).resolve())
        self.role = role

    def run(self, args: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
        if any("api_key" in arg.lower() or "api-key" in arg.lower() for arg in args):
            raise AcquisitionError("API keys must stay inside isolated CLI wrappers")
        result = subprocess.run(
            [self.executable, *args],
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )
        if check and result.returncode != 0:
            raise AcquisitionError(
                f"{self.role} CLI failed ({' '.join(args[:3])}): {redact(result.stderr.strip())}"
            )
        return result


@dataclasses.dataclass(frozen=True)
class Config:
    machine_id: str
    host_cli: str
    client_cli: str
    fixed_end_epoch: int
    p99_host_on_demand_price: float
    p99_host_bid_floor: float
    expected_renter_on_demand_price: float
    expected_renter_bid_floor: float
    client_bid_price: float
    disk_price: float
    upload_price: float
    download_price: float
    image: str
    disk_gb: float
    label: str
    gpu_count: int = GPU_COUNT
    client_labels: tuple[str, ...] = ()
    allowed_owner_standby_id: str | None = None
    allowed_owner_standby_label: str | None = None
    contracts_reviewed: bool = False
    offer_timeout: float = 30.0
    offer_stability_seconds: float = 30.0
    running_timeout: float = 90.0
    absence_timeout: float = 30.0
    poll_seconds: float = 2.0
    max_public_seconds: int = 600
    max_fixed_end_seconds: int = 900
    apply: bool = False


def controlled_labels(cfg: Config) -> tuple[str, ...]:
    """Return the exact create labels for one supported acquisition shape."""

    return cfg.client_labels if cfg.gpu_count == 4 else (cfg.label,)


def contract_gpu_count(cfg: Config) -> int:
    """Return GPUs per controlled contract for one supported shape."""

    return 1 if cfg.gpu_count == 4 else 2


def validate_config(cfg: Config, *, now: float | None = None) -> None:
    positive_id(cfg.machine_id, "machine ID")
    if Path(cfg.host_cli).name == Path(cfg.client_cli).name and cfg.host_cli == cfg.client_cli:
        raise AcquisitionError("host and client CLI executable arguments must differ")
    current = time.time() if now is None else now
    remaining = cfg.fixed_end_epoch - current
    if type(cfg.gpu_count) is not int or cfg.gpu_count not in {2, 4}:
        raise AcquisitionError("controlled acquisition supports exactly 2 or 4 machine GPUs")
    if not isinstance(cfg.client_labels, tuple):
        raise AcquisitionError("client labels must be an immutable tuple")
    labels = controlled_labels(cfg)
    if cfg.gpu_count == 2 and cfg.client_labels:
        raise AcquisitionError("two-GPU mode uses --label and accepts no --client-label values")
    if cfg.gpu_count == 4 and len(cfg.client_labels) != 4:
        raise AcquisitionError("four-GPU mode requires exactly four --client-label values")
    if len(set(labels)) != len(labels):
        raise AcquisitionError("controlled client labels must be unique")
    for label in labels:
        if not SAFE_LABEL_RE.fullmatch(label):
            raise AcquisitionError("each controlled client label must be 8-80 safe characters")
    create_count = len(labels)
    minimum_fixed_end = create_count * (
        cfg.offer_timeout + cfg.offer_stability_seconds + CLI_TIMEOUT_SECONDS
    )
    if remaining < minimum_fixed_end:
        raise AcquisitionError(
            "fixed end must outlast every offer discovery, stability dwell, and create timeout"
        )
    if remaining > cfg.max_fixed_end_seconds:
        raise AcquisitionError("fixed end exceeds the configured fixed-end horizon")
    for name, value in (
        ("P99 host on-demand price", cfg.p99_host_on_demand_price),
        ("P99 host bid floor", cfg.p99_host_bid_floor),
        ("expected renter on-demand price", cfg.expected_renter_on_demand_price),
        ("expected renter bid floor", cfg.expected_renter_bid_floor),
        ("client bid price", cfg.client_bid_price),
    ):
        if not math.isfinite(value) or value <= 0:
            raise AcquisitionError(f"{name} must be a positive finite number")
    for name, value in (
        ("disk price", cfg.disk_price),
        ("upload price", cfg.upload_price),
        ("download price", cfg.download_price),
    ):
        if not math.isfinite(value) or value < 0:
            raise AcquisitionError(f"{name} must be a non-negative finite number")
    if cfg.client_bid_price <= cfg.expected_renter_bid_floor:
        raise AcquisitionError("client bid must be above the exact renter-facing bid floor")
    if not math.isfinite(cfg.disk_gb) or cfg.disk_gb < 10 or cfg.disk_gb > 32:
        raise AcquisitionError("controlled client disk must be between 10 and 32 GB")
    if not IMAGE_RE.fullmatch(cfg.image):
        raise AcquisitionError("controlled image must be a reviewed digest-pinned image reference")
    if not SAFE_LABEL_RE.fullmatch(cfg.label):
        raise AcquisitionError("controlled label must be 8-80 safe characters")
    standby_fields = (cfg.allowed_owner_standby_id, cfg.allowed_owner_standby_label)
    if any(value is not None for value in standby_fields) and not all(
        value is not None for value in standby_fields
    ):
        raise AcquisitionError("allowed owner standby ID and label must be supplied together")
    if cfg.allowed_owner_standby_id is not None:
        positive_id(cfg.allowed_owner_standby_id, "allowed owner standby ID")
        if not SAFE_LABEL_RE.fullmatch(str(cfg.allowed_owner_standby_label)):
            raise AcquisitionError("allowed owner standby label must be 8-80 safe characters")
    for name, value in (
        ("offer timeout", cfg.offer_timeout),
        ("offer stability seconds", cfg.offer_stability_seconds),
        ("running timeout", cfg.running_timeout),
        ("absence timeout", cfg.absence_timeout),
        ("poll seconds", cfg.poll_seconds),
    ):
        if not math.isfinite(value) or value <= 0:
            raise AcquisitionError(f"{name} must be positive")
    if cfg.max_public_seconds < 60 or cfg.max_public_seconds > 600:
        raise AcquisitionError("maximum public window must be between 60 and 600 seconds")
    if cfg.max_fixed_end_seconds < 60 or cfg.max_fixed_end_seconds > 172_800:
        raise AcquisitionError("maximum fixed-end horizon must be between 60 and 172800 seconds")
    required_public_budget = create_count * (
        cfg.offer_timeout + cfg.offer_stability_seconds + CLI_TIMEOUT_SECONDS
    )
    if required_public_budget > cfg.max_public_seconds - CLI_TIMEOUT_SECONDS:
        raise AcquisitionError(
            "all offer discovery, stability, and one-shot create budgets leave less than "
            "one CLI timeout for the public-window unlist backstop"
        )
    if cfg.apply and not cfg.contracts_reviewed:
        raise AcquisitionError("apply requires --contracts-reviewed after inspecting Host Machines/Contracts")


def state_root(project: Path) -> Path:
    configured = os.environ.get("VAST_STATE_DIR")
    root = Path(configured).expanduser() if configured else Path.home() / ".local/state/vast-host-golden-path"
    resolved = root.resolve()
    project_resolved = project.resolve()
    if resolved == project_resolved or project_resolved in resolved.parents:
        raise AcquisitionError("VAST_STATE_DIR must be outside the repository")
    resolved.mkdir(parents=True, exist_ok=True)
    try:
        resolved.chmod(0o700)
    except OSError:
        pass
    return resolved


class Acquisition:
    def __init__(
        self,
        cfg: Config,
        host: Cli,
        client: Cli,
        root: Path,
        run_dir: Path,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wall_time: Callable[[], float] = time.time,
    ) -> None:
        self.cfg = cfg
        self.host = host
        self.client = client
        self.root = root
        self.run_dir = run_dir
        self.sleep = sleep
        self.monotonic = monotonic
        self.wall_time = wall_time
        self.sequence = 0
        self.create_attempted = False
        self.attempted_labels: set[str] = set()
        self.contracts: list[dict[str, str]] = []
        self.listing_attempted = False
        self.listed_at: float | None = None
        self.account_ids: dict[str, str] = {}
        self.offer_id: str | None = None
        self.instance_id: str | None = None
        self.preflight_passed = False
        self.listing_marker = root / "controlled-acquisition-listing-unresolved.json"
        self.create_marker = root / "controlled-acquisition-create-unresolved.json"
        self.contract_marker = root / "controlled-acquisition-contract-unresolved.json"
        self.public_cutoff = threading.Event()
        self.watchdog_stop = threading.Event()
        self.watchdog_thread: threading.Thread | None = None
        self.watchdog_result: dict[str, Any] | None = None

    @property
    def labels(self) -> tuple[str, ...]:
        return controlled_labels(self.cfg)

    @property
    def slice_gpu_count(self) -> int:
        return contract_gpu_count(self.cfg)

    def public_action_deadline(self) -> float:
        if self.listed_at is None:
            raise AcquisitionError("public-window clock was not started")
        return self.listed_at + self.cfg.max_public_seconds - CLI_TIMEOUT_SECONDS

    def require_public_action_budget(self, phase: str) -> None:
        if self.public_cutoff.is_set() or self.monotonic() >= self.public_action_deadline():
            raise AcquisitionError(
                f"public acquisition action budget expired before {phase}; unlisting immediately"
            )

    def start_public_watchdog(self) -> None:
        if self.watchdog_thread is not None:
            raise AcquisitionError("public-window watchdog already exists")
        delay = max(self.cfg.max_public_seconds - CLI_TIMEOUT_SECONDS, 0.0)

        def watchdog() -> None:
            if self.watchdog_stop.wait(delay):
                return
            self.public_cutoff.set()
            payload: dict[str, Any] = {
                "at": utc_now(),
                "status": "unlist-attempted-by-public-window-watchdog",
                "machine_id": self.cfg.machine_id,
                "max_public_seconds": self.cfg.max_public_seconds,
                "unlist_timeout_reserve_seconds": CLI_TIMEOUT_SECONDS,
            }
            try:
                result = self.host.run(
                    ["unlist", "machine", self.cfg.machine_id],
                    check=False,
                )
                payload.update(
                    {
                        "returncode": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                )
            except BaseException as exc:
                payload["exception"] = redact(str(exc))
            self.watchdog_result = payload
            atomic_json(self.run_dir / "public-window-watchdog.json", payload)

        self.watchdog_thread = threading.Thread(
            target=watchdog,
            name="controlled-acquisition-unlist-watchdog",
            daemon=True,
        )
        self.watchdog_thread.start()

    def stop_public_watchdog(self) -> None:
        self.watchdog_stop.set()
        if self.watchdog_thread is not None:
            self.watchdog_thread.join(timeout=1.0)

    def capture_run(
        self,
        cli: Cli,
        role: str,
        args: list[str],
        phase: str,
    ) -> subprocess.CompletedProcess[str]:
        self.sequence += 1
        result = cli.run(args, check=False)
        atomic_json(
            self.run_dir / "commands" / f"{self.sequence:04d}-{phase}.json",
            {
                "at": utc_now(),
                "role": role,
                "args": [redact(arg) for arg in args],
                "returncode": result.returncode,
                "stdout": redact(result.stdout),
                "stderr": redact(result.stderr),
            },
        )
        return result

    def json_call(self, cli: Cli, role: str, args: list[str], phase: str) -> Any:
        result = self.capture_run(cli, role, args, phase)
        if result.returncode != 0:
            raise AcquisitionError(
                f"{role} CLI failed ({' '.join(args[:3])}): {redact(result.stderr.strip())}"
            )
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AcquisitionError(f"{role} CLI returned non-JSON for {' '.join(args[:3])}") from exc

    def query_machine(self, phase: str) -> dict[str, Any]:
        value = self.json_call(
            self.host,
            "host",
            ["show", "machine", self.cfg.machine_id, "--raw"],
            phase,
        )
        return exact_machine(value, self.cfg.machine_id)

    def query_instances(self, cli: Cli, role: str, phase: str) -> list[dict[str, Any]]:
        value = self.json_call(cli, role, ["show", "instances", "--raw"], phase)
        rows = strict_rows(value, f"{role} instance response")
        for row in rows:
            positive_id(identifier(row), f"{role} instance ID")
        return rows

    def query_offers(
        self,
        offer_type: str,
        phase: str,
        *,
        exact_slice: bool = True,
    ) -> list[dict[str, Any]]:
        gpu_filter = f" num_gpus={self.slice_gpu_count}" if exact_slice else ""
        availability = "rentable=true rented=false" if exact_slice else "rentable=any rented=any"
        query = (
            f"machine_id={self.cfg.machine_id}{gpu_filter} "
            f"verified=any {availability}"
        )
        value = self.json_call(
            self.client,
            "client",
            ["search", "offers", query, "--no-default", "--type", offer_type, "--raw"],
            phase,
        )
        rows = strict_rows(value, f"{offer_type} offer response")
        for row in rows:
            positive_id(identifier(row), f"{offer_type} offer ID")
            positive_id(row.get("machine_id"), f"{offer_type} offer machine ID")
        return rows

    def prove_distinct_accounts(self) -> None:
        host_value = self.json_call(self.host, "host", ["show", "user", "--raw"], "host-user")
        client_value = self.json_call(self.client, "client", ["show", "user", "--raw"], "client-user")
        host_id = authenticated_account_id(host_value, "host account")
        client_id = authenticated_account_id(client_value, "client account")
        if host_id == client_id:
            raise AcquisitionError("host and controlled client authenticate as the same account")
        self.account_ids = {"host": host_id, "client": client_id}
        atomic_json(self.run_dir / "authenticated-accounts.json", self.account_ids)

    def require_machine_rentals(
        self,
        machine: dict[str, Any],
        expected_rentals: int,
        what: str,
    ) -> None:
        if machine.get("num_gpus") != self.cfg.gpu_count:
            raise AcquisitionError(
                f"{what} does not expose exactly {self.cfg.gpu_count} GPUs"
            )
        actual = current_rentals(machine)
        if actual != expected_rentals:
            if expected_rentals == 0:
                raise UnknownContractError(f"{what} is not vacant")
            raise UnknownContractError(
                f"{what} reports {actual} running rentals; expected {expected_rentals}"
            )

    def require_machine_vacant(self, machine: dict[str, Any], what: str) -> None:
        self.require_machine_rentals(machine, 0, what)

    def require_no_target_host_instances(self, rows: list[dict[str, Any]], what: str) -> None:
        targets = [row for row in rows if str(row.get("machine_id", "")) == self.cfg.machine_id]
        expected_id = self.cfg.allowed_owner_standby_id
        if expected_id is None:
            if targets:
                raise UnknownContractError(
                    f"{what} found an existing host-side instance on the target machine"
                )
            return
        if len(targets) != 1:
            raise UnknownContractError(
                f"{what} expected exactly one allowed owner standby, found {len(targets)}"
            )
        standby = targets[0]
        if identifier(standby) != expected_id:
            raise UnknownContractError(f"{what} found a different host-side instance")
        if standby.get("label") != self.cfg.allowed_owner_standby_label:
            raise UnknownContractError(f"{what} owner standby label mismatch")
        if standby.get("is_bid") is not False:
            raise UnknownContractError(f"{what} owner standby is not on-demand")
        if standby.get("num_gpus") != self.cfg.gpu_count:
            raise UnknownContractError(f"{what} owner standby is not the exact full-machine size")
        actual = standby.get("actual_status")
        intended = standby.get("intended_status")
        current = standby.get("cur_state")
        if actual not in SAFE_STOPPED_ACTUAL or intended != "stopped" or current != "stopped":
            raise UnknownContractError(
                f"{what} owner standby lacks the fail-closed stopped-state tuple"
            )

    def prove_offers_absent_once(self, phase: str) -> None:
        for offer_type in ("bid", "on-demand"):
            rows = self.query_offers(
                offer_type,
                f"{phase}-{offer_type}",
                exact_slice=False,
            )
            if rows:
                if any(str(row.get("machine_id", "")) == self.cfg.machine_id for row in rows):
                    raise AcquisitionError(f"target machine still exposes a {offer_type} offer")
                raise AcquisitionError(f"exact {offer_type} query returned a non-target row")

    def preflight(self) -> None:
        self.prove_distinct_accounts()
        machine = self.query_machine("preflight-machine")
        self.require_machine_vacant(machine, "preflight machine")
        host_instances = self.query_instances(self.host, "host", "preflight-host-instances")
        self.require_no_target_host_instances(host_instances, "preflight")
        client_instances = self.query_instances(self.client, "client", "preflight-client-instances")
        if client_instances:
            raise AcquisitionError("controlled client account must have no existing instances")
        self.prove_offers_absent_once("preflight-unlisted")
        atomic_json(
            self.run_dir / "preflight.json",
            {
                "at": utc_now(),
                "machine_id": self.cfg.machine_id,
                "gpu_count": self.cfg.gpu_count,
                "contract_gpu_count": self.slice_gpu_count,
                "client_labels": list(self.labels),
                "vacant": True,
                "unlisted": True,
                "client_instances": 0,
                "host_target_instances": 1 if self.cfg.allowed_owner_standby_id else 0,
                "allowed_owner_standby_id": self.cfg.allowed_owner_standby_id,
                "allowed_owner_standby_label": self.cfg.allowed_owner_standby_label,
            },
        )
        self.preflight_passed = True

    def list_args(self) -> list[str]:
        return [
            "list",
            "machine",
            self.cfg.machine_id,
            "--price_gpu",
            f"{self.cfg.p99_host_on_demand_price:.8f}",
            "--price_min_bid",
            f"{self.cfg.p99_host_bid_floor:.8f}",
            "--price_disk",
            f"{self.cfg.disk_price:.8f}",
            "--price_inetu",
            f"{self.cfg.upload_price:.8f}",
            "--price_inetd",
            f"{self.cfg.download_price:.8f}",
            "--discount_rate",
            "0",
            "--min_chunk",
            str(self.slice_gpu_count),
            "--end_date",
            str(self.cfg.fixed_end_epoch),
            "--vol_size",
            "0",
            "--raw",
        ]

    def create_args(self, offer_id: str, label: str | None = None) -> list[str]:
        create_label = self.labels[0] if label is None else label
        return [
            "create",
            "instance",
            offer_id,
            "--image",
            self.cfg.image,
            "--disk",
            f"{self.cfg.disk_gb:g}",
            "--ssh",
            "--direct",
            "--label",
            create_label,
            "--bid_price",
            f"{self.cfg.client_bid_price:.8f}",
            "--cancel-unavail",
            "--raw",
        ]

    def verify_listing_response(self, value: Any) -> None:
        if not isinstance(value, dict) or value.get("success") is not True:
            raise AcquisitionError("list-machine response did not report explicit success")
        sent = value.get("you_sent")
        if not isinstance(sent, dict):
            raise AcquisitionError("list-machine response omitted accepted parameters")
        if str(sent.get("machine", "")) != self.cfg.machine_id:
            raise AcquisitionError("list-machine response names a different machine")
        if sent.get("min_chunk") != self.slice_gpu_count or sent.get("vol_size") != 0:
            raise AcquisitionError("list-machine response changed slice or no-volume guards")
        require_exact_end(sent, self.cfg.fixed_end_epoch, "list-machine response")
        for names, expected, what in (
            (("price_gpu",), self.cfg.p99_host_on_demand_price, "accepted host on-demand price"),
            (("price_min_bid",), self.cfg.p99_host_bid_floor, "accepted host bid floor"),
            (("price_disk",), self.cfg.disk_price, "accepted disk price"),
            (("price_inetu",), self.cfg.upload_price, "accepted upload price"),
            (("price_inetd",), self.cfg.download_price, "accepted download price"),
            (("credit_discount_max",), 0.0, "accepted reserved discount"),
        ):
            require_close(number(sent, names, what), expected, what)

    def exact_offer(self, rows: list[dict[str, Any]], offer_type: str) -> dict[str, Any]:
        matches = [row for row in rows if str(row.get("machine_id", "")) == self.cfg.machine_id]
        if len(rows) != 1 or len(matches) != 1:
            raise AcquisitionError(f"expected one exact {offer_type} offer for the target machine")
        offer = matches[0]
        if str(offer.get("host_id", "")) != self.account_ids.get("host"):
            raise AcquisitionError(f"{offer_type} offer belongs to a different host account")
        if offer.get("num_gpus") != self.slice_gpu_count:
            raise AcquisitionError(f"{offer_type} offer is not the exact requested GPU slice")
        if offer.get("rentable") is not True or offer.get("rented") is not False:
            raise UnknownContractError(f"{offer_type} offer is not exactly rentable and vacant")
        require_exact_end(offer, self.cfg.fixed_end_epoch, f"{offer_type} offer")
        return offer

    def verify_listing_snapshot(
        self,
        listing_response: Any,
        machine: dict[str, Any],
        bid_rows: list[dict[str, Any]],
        on_demand_rows: list[dict[str, Any]] | None,
        expected_rentals: int = 0,
    ) -> str:
        self.verify_listing_response(listing_response)
        self.require_machine_rentals(machine, expected_rentals, "listed machine")
        if machine.get("listed_min_gpu_count") != self.slice_gpu_count:
            raise AcquisitionError("machine record does not expose the exact requested slice")
        require_exact_end(machine, self.cfg.fixed_end_epoch, "machine record")
        require_close(
            number(machine, ("listed_gpu_cost",), "machine host on-demand price"),
            self.cfg.p99_host_on_demand_price,
            "machine host on-demand price",
        )
        require_close(
            number(machine, ("min_bid_price",), "machine host bid floor"),
            self.cfg.p99_host_bid_floor,
            "machine host bid floor",
        )
        bid = self.exact_offer(bid_rows, "bid")
        require_close(
            number(bid, ("min_bid",), "renter-facing bid floor"),
            self.cfg.expected_renter_bid_floor,
            "renter-facing bid floor",
        )
        if on_demand_rows is not None:
            on_demand = self.exact_offer(on_demand_rows, "on-demand")
            require_close(
                number(on_demand, ("dph_base", "dph_total"), "renter-facing on-demand price"),
                self.cfg.expected_renter_on_demand_price,
                "renter-facing on-demand price",
            )
        return positive_id(identifier(bid), "bid offer ID")

    def wait_for_exact_offers(
        self,
        listing_response: Any,
        expected_contracts: list[dict[str, str]] | None = None,
    ) -> str:
        expected = [] if expected_contracts is None else expected_contracts
        deadline = min(
            self.monotonic() + self.cfg.offer_timeout,
            self.public_action_deadline(),
        )
        last_error = "offers were not observable"
        while self.monotonic() <= deadline:
            self.require_public_action_budget("offer polling")
            machine = self.query_machine("listed-machine")
            host_instances = self.query_instances(
                self.host, "host", "listed-host-instances"
            )
            self.require_no_target_host_instances(host_instances, "listed offer guard")
            client_instances = self.query_instances(
                self.client, "client", "listed-client-instances"
            )
            self.require_client_contracts(
                client_instances,
                expected,
                "listed offer guard",
                require_running=True,
            )
            bid = self.query_offers("bid", "listed-bid")
            on_demand = self.query_offers("on-demand", "listed-on-demand")
            self.require_public_action_budget("offer verification")
            try:
                return self.verify_listing_snapshot(
                    listing_response,
                    machine,
                    bid,
                    on_demand,
                    expected_rentals=len(expected),
                )
            except UnknownContractError:
                raise
            except AcquisitionError as exc:
                last_error = str(exc)
            if self.listed_at is not None and self.monotonic() - self.listed_at >= self.cfg.max_public_seconds:
                break
            self.sleep(self.cfg.poll_seconds)
        raise AcquisitionError(f"listed offer verification failed: {last_error}")

    def precreate_guard(
        self,
        listing_response: Any,
        phase: str = "precreate",
        *,
        require_on_demand: bool = True,
        expected_contracts: list[dict[str, str]] | None = None,
    ) -> str:
        expected = [] if expected_contracts is None else expected_contracts
        self.require_public_action_budget("pre-create guard")
        machine = self.query_machine(f"{phase}-machine")
        host_instances = self.query_instances(self.host, "host", f"{phase}-host-instances")
        self.require_no_target_host_instances(host_instances, "pre-create guard")
        client_instances = self.query_instances(
            self.client,
            "client",
            f"{phase}-client-instances",
        )
        self.require_client_contracts(
            client_instances,
            expected,
            "pre-create guard",
            require_running=True,
        )
        bid = self.query_offers("bid", f"{phase}-bid")
        if not bid:
            raise TransientOfferAbsence("exact bid offer temporarily absent")
        on_demand = (
            self.query_offers("on-demand", f"{phase}-on-demand")
            if require_on_demand
            else None
        )
        self.require_public_action_budget("controlled create")
        return self.verify_listing_snapshot(
            listing_response,
            machine,
            bid,
            on_demand,
            expected_rentals=len(expected),
        )

    def wait_for_stable_offer(
        self,
        listing_response: Any,
        offer_id: str,
        expected_contracts: list[dict[str, str]] | None = None,
        *,
        label: str | None = None,
    ) -> None:
        """Require the same exact vacant offer to survive a deliberate dwell.

        A newly published ask can be visible briefly and then disappear.  Each
        sample repeats the complete pre-create guard, including both account
        inventories, machine vacancy, fixed end, accepted prices, and the exact
        bid offer used by create. The on-demand view is proved once during
        publication but is not a launch dependency and can lag the bid view.
        The create remains a separate final guarded action after this dwell.
        """

        started = self.monotonic()
        stable_since: float | None = None
        if started + self.cfg.offer_stability_seconds >= self.public_action_deadline():
            raise AcquisitionError(
                "offer stability dwell would exceed the guarded public action budget"
            )
        samples = 0
        interruptions = 0
        while True:
            attempt = samples + interruptions + 1
            try:
                guarded_offer_id = self.precreate_guard(
                    listing_response,
                    f"offer-stability-{attempt:02d}",
                    require_on_demand=False,
                    expected_contracts=expected_contracts,
                )
            except TransientOfferAbsence:
                interruptions += 1
                stable_since = None
                self.require_public_action_budget("offer stability recovery")
                self.sleep(self.cfg.poll_seconds)
                continue
            samples += 1
            if guarded_offer_id != offer_id:
                raise AcquisitionError("bid offer ID changed during the stability dwell")
            now = self.monotonic()
            if stable_since is None:
                stable_since = now
            if now - stable_since >= self.cfg.offer_stability_seconds:
                atomic_json(
                    self.run_dir
                    / (
                        "offer-stability.json"
                        if len(self.labels) == 1
                        else f"offer-stability-{len(self.contracts) + 1:02d}-{label}.json"
                    ),
                    {
                        "at": utc_now(),
                        "offer_id": offer_id,
                        "required_seconds": self.cfg.offer_stability_seconds,
                        "elapsed_seconds": now - started,
                        "consecutive_seconds": now - stable_since,
                        "full_guard_samples": samples,
                        "transient_absences": interruptions,
                    },
                )
                return
            remaining = self.cfg.offer_stability_seconds - (now - stable_since)
            self.sleep(min(self.cfg.poll_seconds, remaining))

    def create_once(self, offer_id: str, label: str | None = None) -> Any:
        create_label = self.labels[0] if label is None else label
        if create_label not in self.labels:
            raise AcquisitionError("refusing a create label outside the reviewed label set")
        if create_label in self.attempted_labels:
            raise AcquisitionError(f"refusing to retry create instance for label {create_label}")
        self.require_public_action_budget("controlled create call")
        self.create_attempted = True
        self.attempted_labels.add(create_label)
        atomic_json(
            self.create_marker,
            {
                "at": utc_now(),
                "status": "create-pending",
                "run_dir": str(self.run_dir),
                "machine_id": self.cfg.machine_id,
                "offer_id": offer_id,
                "label": create_label,
                "attempted_labels": sorted(self.attempted_labels),
                "created_contracts": self.contracts,
            },
        )
        create_phase = f"create-once-{len(self.attempted_labels):02d}"
        result = self.capture_run(
            self.client,
            "client",
            self.create_args(offer_id, create_label),
            create_phase,
        )
        definitive_rejection = exact_no_such_ask_rejection(result)
        if definitive_rejection is not None:
            evidence = {
                "at": utc_now(),
                "status": "definitive-no-contract-awaiting-unlist-proof",
                "classification": "definitive-no-contract",
                "basis": "empty stdout and exact structured HTTP 400 no_such_ask rejection",
                "run_dir": str(self.run_dir),
                "machine_id": self.cfg.machine_id,
                "offer_id": offer_id,
                "label": create_label,
                "attempted_labels": sorted(self.attempted_labels),
                "created_contracts": self.contracts,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "structured_stderr": definitive_rejection,
                "command_evidence": str(
                    self.run_dir / "commands" / f"{self.sequence:04d}-{create_phase}.json"
                ),
            }
            atomic_json(self.run_dir / "create-definitive-no-contract.json", evidence)
            atomic_json(self.create_marker, evidence)
            raise DefinitiveNoContractError(
                "the single create call was definitively rejected with HTTP 400 "
                "no_such_ask; Vast created no contract",
                definitive_rejection,
                label=create_label,
                offer_id=offer_id,
            )
        if result.returncode != 0:
            raise AcquisitionError(
                "the single create call returned nonzero; state is unresolved and create will not be retried"
            )
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise AcquisitionError(
                "the single create call returned non-JSON; state is unresolved and create will not be retried"
            ) from exc
        if not isinstance(value, dict) or value.get("success") is not True:
            raise AcquisitionError(
                "the single create call lacked explicit success; state is unresolved and create will not be retried"
            )
        self.instance_id = positive_id(value.get("new_contract"), "created contract ID")
        if any(item["instance_id"] == self.instance_id for item in self.contracts):
            raise AcquisitionError("create response repeated an existing contract ID")
        contract = {
            "instance_id": self.instance_id,
            "offer_id": offer_id,
            "label": create_label,
        }
        self.contracts.append(contract)
        atomic_json(
            self.create_marker,
            {
                "at": utc_now(),
                "status": "create-reported-success-awaiting-proof",
                "run_dir": str(self.run_dir),
                "machine_id": self.cfg.machine_id,
                "offer_id": offer_id,
                "instance_id": self.instance_id,
                "label": create_label,
                "attempted_labels": sorted(self.attempted_labels),
                "created_contracts": self.contracts,
            },
        )
        return value

    def unlist_and_prove_absent(self) -> None:
        command_error: BaseException | None = None
        try:
            result = self.capture_run(
                self.host,
                "host",
                ["unlist", "machine", self.cfg.machine_id],
                "unlist-finally",
            )
        except BaseException as exc:
            # A timed-out or interrupted mutation can still have succeeded.
            # Continue to the authoritative public-offer absence proof.
            command_error = exc
            result = subprocess.CompletedProcess([], -1, "", str(exc))
        atomic_json(
            self.run_dir / "unlist-command.json",
            {
                "at": utc_now(),
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exception": None if command_error is None else redact(str(command_error)),
            },
        )
        deadline = self.monotonic() + self.cfg.absence_timeout
        consecutive = 0
        samples = 0
        last_error = "no absence sample was collected"
        while self.monotonic() <= deadline:
            samples += 1
            try:
                self.prove_offers_absent_once(f"unlist-absence-{samples:02d}")
                consecutive += 1
                atomic_json(
                    self.run_dir / "offer-absence" / f"{samples:02d}.json",
                    {"at": utc_now(), "absent": True, "consecutive": consecutive},
                )
                if consecutive == 3:
                    self.listing_marker.unlink(missing_ok=True)
                    atomic_json(
                        self.run_dir / "unlisted-proved.json",
                        {"at": utc_now(), "consecutive_absence_samples": 3, "samples": samples},
                    )
                    return
            except BaseException as exc:
                consecutive = 0
                last_error = redact(str(exc))
                atomic_json(
                    self.run_dir / "offer-absence" / f"{samples:02d}.json",
                    {"at": utc_now(), "absent": False, "error": last_error, "consecutive": 0},
                )
            self.sleep(self.cfg.poll_seconds)
        raise AcquisitionError(f"unlisting was not proved by three consecutive samples: {last_error}")

    def require_contract_identity(
        self,
        record: dict[str, Any],
        offer_id: str,
        instance_id: str,
        label: str | None = None,
    ) -> None:
        expected_label = self.labels[0] if label is None else label
        checks = {
            "instance ID": identifier(record) == instance_id,
            "machine ID": str(record.get("machine_id", "")) == self.cfg.machine_id,
            "label": record.get("label") == expected_label,
            "interruptible type": record.get("is_bid") is True,
            "GPU count": record.get("num_gpus") == self.slice_gpu_count,
            "host account": str(record.get("host_id", "")) == self.account_ids.get("host"),
            "image": record.get("image_uuid", record.get("image")) == self.cfg.image,
        }
        # The current documented show-instance schema exposes host_id, image,
        # disk, end, and mode but not ask_contract_id.  Some API versions add
        # ask_contract_id; if present it must agree with the exact offer used.
        if "ask_contract_id" in record:
            checks["offer ID"] = str(record["ask_contract_id"]) == offer_id
        failed = [name for name, okay in checks.items() if not okay]
        if failed:
            raise AcquisitionError("controlled contract identity mismatch: " + ", ".join(failed))
        require_close(
            number(record, ("disk_space", "disk_gb"), "controlled contract disk"),
            self.cfg.disk_gb,
            "controlled contract disk",
        )
        require_exact_end(record, self.cfg.fixed_end_epoch, "controlled contract")
        if "bid_price" in record:
            require_close(
                number(record, ("bid_price",), "controlled contract bid"),
                self.cfg.client_bid_price,
                "controlled contract bid",
            )

    def require_client_contracts(
        self,
        rows: list[dict[str, Any]],
        expected: list[dict[str, str]],
        what: str,
        *,
        require_running: bool,
    ) -> list[dict[str, Any]]:
        expected_ids = {item["instance_id"] for item in expected}
        actual_ids = {identifier(row) for row in rows}
        if len(rows) != len(actual_ids):
            raise UnknownContractError(f"{what} contains duplicate client contract IDs")
        if actual_ids != expected_ids:
            raise UnknownContractError(
                f"{what} client inventory differs from the exact controlled contract set"
            )
        by_id = {identifier(row): row for row in rows}
        ordered: list[dict[str, Any]] = []
        for item in expected:
            record = by_id[item["instance_id"]]
            self.require_contract_identity(
                record,
                item["offer_id"],
                item["instance_id"],
                item["label"],
            )
            if require_running:
                state = (
                    record.get("actual_status"),
                    record.get("intended_status"),
                    record.get("cur_state"),
                )
                if state != RUNNING_TUPLE:
                    raise AcquisitionError(
                        f"{what} contract {item['instance_id']} is not running/running/running"
                    )
            ordered.append(record)
        return ordered

    def wait_for_running_contracts(
        self,
        expected: list[dict[str, str]],
        *,
        while_public: bool = False,
    ) -> list[dict[str, Any]]:
        if not expected:
            raise AcquisitionError("running proof requires at least one controlled contract")
        deadline = self.monotonic() + self.cfg.running_timeout
        last_states: dict[str, list[Any]] = {}
        last_single_states: dict[str, list[Any]] = {}
        while self.monotonic() <= deadline:
            if while_public:
                self.require_public_action_budget("running contract proof")
            singles: list[dict[str, Any]] = []
            for index, item in enumerate(expected, start=1):
                single = self.json_call(
                    self.client,
                    "client",
                    ["show", "instance", item["instance_id"], "--raw"],
                    f"running-single-{index:02d}",
                )
                record = exact_instance(
                    single,
                    item["instance_id"],
                    "controlled instance response",
                )
                self.require_contract_identity(
                    record,
                    item["offer_id"],
                    item["instance_id"],
                    item["label"],
                )
                singles.append(record)
            last_single_states = {
                item["instance_id"]: [
                    record.get("actual_status"),
                    record.get("intended_status"),
                    record.get("cur_state"),
                ]
                for item, record in zip(expected, singles)
            }
            full = self.query_instances(self.client, "client", "running-client-list")
            ordered = self.require_client_contracts(
                full,
                expected,
                "running proof",
                require_running=False,
            )
            host_rows = self.query_instances(self.host, "host", "running-host-instances")
            self.require_no_target_host_instances(host_rows, "running proof")
            machine = self.query_machine("running-machine")
            rentals = current_rentals(machine)
            if rentals > len(expected):
                raise UnknownContractError(
                    "target machine reports more rentals than the exact controlled set"
                )
            last_states = {
                item["instance_id"]: [
                    record.get("actual_status"),
                    record.get("intended_status"),
                    record.get("cur_state"),
                ]
                for item, record in zip(expected, ordered)
            }
            if (
                all(tuple(state) == RUNNING_TUPLE for state in last_states.values())
                and all(
                    tuple(state) == RUNNING_TUPLE
                    for state in last_single_states.values()
                )
                and rentals == len(expected)
            ):
                proof = {
                    "at": utc_now(),
                    "contracts": expected,
                    "machine_id": self.cfg.machine_id,
                    "machine_gpu_count": self.cfg.gpu_count,
                    "contract_gpu_count": self.slice_gpu_count,
                    "single_instance_states": last_single_states,
                    "full_list_states": last_states,
                    "machine_current_rentals_running": rentals,
                    "total_controlled_gpus": len(expected) * self.slice_gpu_count,
                }
                atomic_json(
                    self.run_dir / f"controlled-contracts-running-{len(expected):02d}.json",
                    proof,
                )
                if len(expected) == 1 and self.cfg.gpu_count == 2:
                    atomic_json(self.run_dir / "controlled-contract-running.json", proof)
                return singles
            self.sleep(self.cfg.poll_seconds)
        raise AcquisitionError(
            "controlled contracts did not reach the exact running set; "
            f"last single states={last_single_states}; last full-list states={last_states}"
        )

    def wait_for_running_contract(self, offer_id: str, instance_id: str) -> dict[str, Any]:
        """Backward-compatible one-contract proof used by the two-GPU path."""

        records = self.wait_for_running_contracts(
            [{"offer_id": offer_id, "instance_id": instance_id, "label": self.labels[0]}]
        )
        return records[0]

    def reconcile_after_uncertain_create(self) -> None:
        payload: dict[str, Any] = {
            "at": utc_now(),
            "create_attempted": self.create_attempted,
            "attempted_labels": sorted(self.attempted_labels),
            "created_contracts": self.contracts,
        }
        try:
            payload["client_instances"] = self.query_instances(
                self.client, "client", "uncertain-client-instances"
            )
        except AcquisitionError as exc:
            payload["client_instances_error"] = str(exc)
        try:
            payload["machine"] = self.query_machine("uncertain-machine")
        except AcquisitionError as exc:
            payload["machine_error"] = str(exc)
        atomic_json(self.run_dir / "create-uncertainty-reconciliation.json", payload)

    def acquire(self, typed_confirmation: str) -> dict[str, Any]:
        if not self.preflight_passed or not self.account_ids:
            raise AcquisitionError("read-only preflight must pass immediately before acquisition")
        validate_config(self.cfg, now=self.wall_time())
        expected = f"LIST {self.cfg.machine_id} ONCE"
        if typed_confirmation != expected:
            raise AcquisitionError("typed listing confirmation did not match")

        listing_error: BaseException | None = None
        unlist_error: BaseException | None = None
        listing_response: Any = None
        create_responses: list[Any] = []

        atomic_json(
            self.listing_marker,
            {
                "at": utc_now(),
                "status": "listing-pending",
                "run_dir": str(self.run_dir),
                "machine_id": self.cfg.machine_id,
                "fixed_end_epoch": self.cfg.fixed_end_epoch,
            },
        )
        self.listing_attempted = True
        self.listed_at = self.monotonic()
        self.start_public_watchdog()
        try:
            list_result = self.capture_run(self.host, "host", self.list_args(), "list-machine")
            if list_result.returncode != 0:
                raise AcquisitionError("list-machine call returned nonzero; unlisting immediately")
            try:
                listing_response = json.loads(list_result.stdout)
            except json.JSONDecodeError as exc:
                raise AcquisitionError("list-machine call returned non-JSON; unlisting immediately") from exc
            for label in self.labels:
                self.offer_id = self.wait_for_exact_offers(
                    listing_response,
                    self.contracts,
                )
                self.wait_for_stable_offer(
                    listing_response,
                    self.offer_id,
                    self.contracts,
                    label=label,
                )
                # The final successful stability sample is itself a complete
                # machine/account/inventory/bid guard. Create immediately so
                # another slow marketplace read does not open a new consistency
                # window, then prove the accumulated set before the next slice.
                self.require_public_action_budget("controlled create after stable guard")
                create_responses.append(self.create_once(self.offer_id, label))
                self.wait_for_running_contracts(self.contracts, while_public=True)
        except BaseException as exc:  # the finally path must also handle Ctrl-C
            listing_error = exc
        finally:
            try:
                self.unlist_and_prove_absent()
            except BaseException as exc:
                unlist_error = exc
            finally:
                self.stop_public_watchdog()

        if self.listed_at is not None:
            atomic_json(
                self.run_dir / "public-window.json",
                {
                    "listed_monotonic": self.listed_at,
                    "finished_monotonic": self.monotonic(),
                    "elapsed_seconds": self.monotonic() - self.listed_at,
                    "fixed_end_epoch": self.cfg.fixed_end_epoch,
                    "max_public_seconds": self.cfg.max_public_seconds,
                    "watchdog_fired": self.watchdog_result is not None,
                },
            )

        if isinstance(listing_error, DefinitiveNoContractError):
            evidence_path = self.run_dir / "create-definitive-no-contract.json"
            try:
                prior_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                prior_evidence = {}
            if not isinstance(prior_evidence, dict):
                prior_evidence = {}
            atomic_json(
                evidence_path,
                prior_evidence
                | {
                    "at": utc_now(),
                    "status": "definitive-no-contract",
                    "classification": "definitive-no-contract",
                    "basis": "empty stdout and exact structured HTTP 400 no_such_ask rejection",
                    "run_dir": str(self.run_dir),
                    "machine_id": self.cfg.machine_id,
                    "offer_id": listing_error.offer_id,
                    "label": listing_error.label,
                    "structured_stderr": listing_error.payload,
                    "unlist_proved": unlist_error is None,
                    "attempted_labels": sorted(self.attempted_labels),
                    "created_contracts": self.contracts,
                },
            )
            if self.contracts:
                self.reconcile_after_uncertain_create()
                atomic_json(
                    self.create_marker,
                    {
                        "at": utc_now(),
                        "status": "partial-acquisition-requires-review-no-retry",
                        "run_dir": str(self.run_dir),
                        "machine_id": self.cfg.machine_id,
                        "failed_offer_id": listing_error.offer_id,
                        "failed_label": listing_error.label,
                        "attempted_labels": sorted(self.attempted_labels),
                        "created_contracts": self.contracts,
                        "unlist_proved": unlist_error is None,
                    },
                )
            else:
                self.create_marker.unlink(missing_ok=True)
        elif self.create_attempted and listing_error is not None:
            self.reconcile_after_uncertain_create()
            atomic_json(
                self.create_marker,
                {
                    "at": utc_now(),
                    "status": "create-unresolved-no-retry",
                    "run_dir": str(self.run_dir),
                    "machine_id": self.cfg.machine_id,
                    "offer_id": self.offer_id,
                    "instance_id": self.instance_id,
                    "attempted_labels": sorted(self.attempted_labels),
                    "created_contracts": self.contracts,
                    "error": redact(str(listing_error)),
                },
            )
        if isinstance(listing_error, UnknownContractError):
            atomic_json(
                self.contract_marker,
                {
                    "at": utc_now(),
                    "status": "unexpected-contract-requires-review",
                    "run_dir": str(self.run_dir),
                    "machine_id": self.cfg.machine_id,
                    "error": str(listing_error),
                },
            )

        if listing_error is not None or unlist_error is not None:
            errors = []
            if listing_error is not None:
                errors.append(f"acquisition: {redact(str(listing_error))}")
            if unlist_error is not None:
                errors.append(f"unlist proof: {redact(str(unlist_error))}")
            raise AcquisitionError("; ".join(errors))

        if (
            len(create_responses) != len(self.labels)
            or len(self.contracts) != len(self.labels)
            or self.offer_id is None
            or self.instance_id is None
        ):
            raise AcquisitionError("create success state is internally incomplete")
        if len({item["instance_id"] for item in self.contracts}) != len(self.contracts):
            raise AcquisitionError("controlled contract IDs are not unique")
        if {item["label"] for item in self.contracts} != set(self.labels):
            raise AcquisitionError("controlled contract labels do not match the reviewed set")
        if len(self.contracts) * self.slice_gpu_count != self.cfg.gpu_count:
            raise AcquisitionError("controlled contracts do not cover the exact machine GPU count")

        records = self.wait_for_running_contracts(self.contracts)
        self.create_marker.unlink(missing_ok=True)
        self.contract_marker.unlink(missing_ok=True)
        result = {
            "at": utc_now(),
            "status": (
                "controlled-contract-running-and-machine-unlisted"
                if len(self.contracts) == 1
                else "controlled-contracts-running-and-machine-unlisted"
            ),
            "machine_id": self.cfg.machine_id,
            "instance_ids": [item["instance_id"] for item in self.contracts],
            "offer_ids": [item["offer_id"] for item in self.contracts],
            "client_labels": [item["label"] for item in self.contracts],
            "contracts": self.contracts,
            "gpu_count": self.cfg.gpu_count,
            "contract_gpu_count": self.slice_gpu_count,
            "account_ids": self.account_ids,
            "fixed_end_epoch": self.cfg.fixed_end_epoch,
            "three_offer_absence_samples": True,
            "create_calls": len(self.contracts),
            "destroy_calls": 0,
        }
        if len(self.contracts) == 1:
            result.update(
                {
                    "instance_id": self.contracts[0]["instance_id"],
                    "offer_id": self.contracts[0]["offer_id"],
                    "label": self.contracts[0]["label"],
                }
            )
        atomic_json(self.run_dir / "result.json", result)
        returned = result | {"records": records}
        if len(records) == 1:
            returned["record"] = records[0]
        return returned


def parse_args(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--machine-id", required=True)
    parser.add_argument("--host-cli", default="vastai")
    parser.add_argument("--client-cli", required=True, help="separately authenticated executable/wrapper")
    parser.add_argument("--fixed-end-epoch", type=int, required=True)
    parser.add_argument("--p99-host-on-demand-price", type=float, required=True)
    parser.add_argument("--p99-host-bid-floor", type=float, required=True)
    parser.add_argument("--expected-renter-on-demand-price", type=float, required=True)
    parser.add_argument("--expected-renter-bid-floor", type=float, required=True)
    parser.add_argument("--client-bid-price", type=float, required=True)
    parser.add_argument("--disk-price", type=float, required=True)
    parser.add_argument("--upload-price", type=float, required=True)
    parser.add_argument("--download-price", type=float, required=True)
    parser.add_argument("--image", required=True, help="reviewed image reference pinned by sha256 digest")
    parser.add_argument("--disk-gb", type=float, default=10.0)
    parser.add_argument(
        "--label",
        required=True,
        help="single contract label in two-GPU mode; acquisition run label in four-GPU mode",
    )
    parser.add_argument("--gpu-count", type=int, choices=(2, 4), default=GPU_COUNT)
    parser.add_argument(
        "--client-label",
        action="append",
        default=[],
        help="repeat exactly four times for four-GPU/one-GPU-slice mode",
    )
    parser.add_argument(
        "--allowed-owner-standby-id",
        help="one exact, safely stopped owner on-demand instance allowed during acquisition",
    )
    parser.add_argument(
        "--allowed-owner-standby-label",
        help="exact label paired with --allowed-owner-standby-id",
    )
    parser.add_argument("--contracts-reviewed", action="store_true")
    parser.add_argument("--offer-timeout", type=float, default=30.0)
    parser.add_argument("--offer-stability-seconds", type=float, default=30.0)
    parser.add_argument("--running-timeout", type=float, default=90.0)
    parser.add_argument("--absence-timeout", type=float, default=30.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--max-public-seconds", type=int, default=600)
    parser.add_argument("--max-fixed-end-seconds", type=int, default=900)
    parser.add_argument("--apply", action="store_true")
    values = vars(parser.parse_args(argv))
    values["client_labels"] = tuple(values["client_label"])
    del values["client_label"]
    return Config(**values)


def acquire_lock(root: Path) -> Path:
    for marker_name in (
        "controlled-acquisition-listing-unresolved.json",
        "controlled-acquisition-create-unresolved.json",
        "controlled-acquisition-contract-unresolved.json",
    ):
        marker = root / marker_name
        if marker.exists():
            raise AcquisitionError(f"unresolved state exists at {marker}; reconcile it before another run")
    lock = root / "controlled-acquisition.lock"
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise AcquisitionError(f"another controlled acquisition may be active: {lock}") from exc
    return lock


def main(argv: list[str] | None = None) -> int:
    cfg = parse_args(argv)
    validate_config(cfg)
    project = Path(__file__).resolve().parents[1]
    root = state_root(project)
    lock = acquire_lock(root)
    run_dir = root / "controlled-acquisitions" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        run_dir.chmod(0o700)
    except OSError:
        pass
    try:
        atomic_json(run_dir / "config.json", dataclasses.asdict(cfg))
        host = Cli(cfg.host_cli, "host")
        client = Cli(cfg.client_cli, "client")
        if Path(host.executable) == Path(client.executable):
            raise AcquisitionError("host and client must use distinct pre-authenticated CLI executables")
        acquisition = Acquisition(cfg, host, client, root, run_dir)
        acquisition.preflight()
        atomic_json(
            run_dir / "plan.json",
            {
                "listing": acquisition.list_args(),
                "create_templates": [
                    acquisition.create_args("<verified-one-shot-bid-offer-id>", label)
                    for label in acquisition.labels
                ],
                "unlist": ["unlist", "machine", cfg.machine_id],
                "machine_gpu_count": cfg.gpu_count,
                "contract_gpu_count": acquisition.slice_gpu_count,
                "create_call_limit": len(acquisition.labels),
                "one_shot_per_label": True,
                "destroy_calls": 0,
            },
        )
        if not cfg.apply:
            print(f"DRY RUN passed read-only preflight. Private plan: {run_dir / 'plan.json'}")
            return 0
        if not sys.stdin.isatty():
            raise AcquisitionError("refusing to list without an interactive terminal")
        expected = f"LIST {cfg.machine_id} ONCE"
        print(
            f"Type {expected} to publish one fixed-end {cfg.gpu_count}-GPU offer and make "
            f"{len(acquisition.labels)} one-shot controlled create call(s): ",
            end="",
            file=sys.stderr,
            flush=True,
        )
        typed = sys.stdin.readline().rstrip("\r\n")
        result = acquisition.acquire(typed)
        print(
            f"PASS {len(acquisition.labels)} controlled contract(s) cover the exact "
            f"{cfg.gpu_count}-GPU machine and are running; "
            f"three public-offer absence samples passed. Private evidence: {run_dir}"
        )
        return 0 if result else 1
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AcquisitionError as exc:
        print(f"ERROR: {redact(str(exc))}", file=sys.stderr)
        raise SystemExit(1)
