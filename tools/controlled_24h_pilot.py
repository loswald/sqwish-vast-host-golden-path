#!/usr/bin/env python3
"""Run the guarded 24-hour, four-slice verification and handoff pilot.

This controller assumes acquisition and owner-standby preparation are already
complete.  It never provisions a host, creates an instance, changes a price,
or lists a machine.  Dry-run is the default.  Apply requires an interactive
terminal, exact typed confirmations, an active qualification HOLD, four exact
one-GPU controlled interruptibles, and one exact stopped whole-machine owner
on-demand standby.

The first arm is a qualification-trend observation.  At the recorded mode
boundary the controller explicitly disables the local HOLD; that operation is
not evidence that owner workloads are verification-safe.  The second arm runs
exactly three owner on-demand handoffs.  These are not Host Jobs/Create Job.

Evidence comes from operator-vetted workload, host-telemetry, host-contract,
and normalized billing JSON adapters.  The controller executes them without a
shell and with a small environment allowlist, then validates and normalizes
their output.  It cannot prove that an adapter is read-only; the operator must
review each executable.  Private normalized evidence is written under
VAST_STATE_DIR, outside this repo; raw billing account records are never kept.
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
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

try:
    from tools.controlled_hostjob_cycle import (
        Cli,
        CycleError,
        atomic_json as _atomic_json,
        authenticated_account_id,
        exact_machine,
        exact_record,
        health_is_clear,
        identifier,
        is_running,
        is_safely_stopped,
        machine_summary,
        parse_reports_output,
        strict_instance_records,
        strict_offer_records,
        utc_now,
        redact,
    )
    from tools.controlled_owner_standby_cycle import (
        atomic_text,
    )
    from tools.verification_guard import (
        QualificationGuardError,
        disable_qualification_mode,
        qualification_marker_path,
        qualification_owner_mutation_interlock,
        require_qualification_mode_inactive,
        sample_qualification_mode,
    )
except ModuleNotFoundError:  # Direct ``python tools/...`` execution.
    from controlled_hostjob_cycle import (  # type: ignore[no-redef]
        Cli,
        CycleError,
        atomic_json as _atomic_json,
        authenticated_account_id,
        exact_machine,
        exact_record,
        health_is_clear,
        identifier,
        is_running,
        is_safely_stopped,
        machine_summary,
        parse_reports_output,
        strict_instance_records,
        strict_offer_records,
        utc_now,
        redact,
    )
    from controlled_owner_standby_cycle import (  # type: ignore[no-redef]
        atomic_text,
    )
    from verification_guard import (  # type: ignore[no-redef]
        QualificationGuardError,
        disable_qualification_mode,
        qualification_marker_path,
        qualification_owner_mutation_interlock,
        require_qualification_mode_inactive,
        sample_qualification_mode,
    )


PILOT_SECONDS = 24 * 60 * 60
QUALIFICATION_SECONDS = 12 * 60 * 60
DEFAULT_CYCLE_OFFSETS = (12 * 60 * 60 + 30 * 60, 16 * 60 * 60, 20 * 60 * 60)
SAMPLE_SECONDS = 5 * 60
MAX_SAMPLE_GAP_SECONDS = SAMPLE_SECONDS + 60
MAX_HANDOFFS = 3
MAX_RECLAIM_SECONDS = 15 * 60
AUTO_RETURN_SECONDS = 5 * 60
SELF_TEST_MAX_AGE_SECONDS = 6 * 60 * 60
ADAPTER_ATTESTATION_MAX_AGE_SECONDS = 2 * 60
SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{7,79}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
GPU_ID_RE = re.compile(r"^(?:GPU-)?[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$")
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+:-]{0,126}$")
SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|machineapikey|token|password|credential|secret|ssh[_-]?key)", re.I
)
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)((?:api[_-]?key|machineapikey|token|password|credential|secret|ssh[_-]?key)"
    r"\s*[:=]\s*['\"]?)[^'\",\s]+"
)
SENSITIVE_JSON_TEXT_RE = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|machineapikey|token|password|credential|secret|"
    r"ssh[_-]?key)[\"']?\s*:\s*[\"']?)[^\"',}\s]+"
)
EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    r"(?![A-Za-z0-9.-])"
)
IPV4_RE = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
SAFE_CALLBACK_ENV_NAMES = {
    "PATH",
    "HOME",
    "USERPROFILE",
    "SystemRoot",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
}
SAFE_NONSECRET_FIELD_NAMES = {"ssh_keys_only", "unique_ssh_host_key"}


def _structured_redact(value: Any, *, key: str | None = None) -> Any:
    """Redact unknown token-shaped data while preserving validated evidence IDs.

    Checkpoint digests, GPU UUIDs, and exact labels are continuity evidence, not
    credentials.  They are preserved only in their validated structural slots.
    """

    if isinstance(value, dict):
        return {
            str(item_key): (
                "<redacted>"
                if SENSITIVE_KEY_RE.search(str(item_key))
                and str(item_key) not in SAFE_NONSECRET_FIELD_NAMES
                else _structured_redact(item, key=str(item_key))
            )
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        if key == "gpu_uuids" and all(
            isinstance(item, str) and GPU_ID_RE.fullmatch(item) for item in value
        ):
            return list(value)
        return [_structured_redact(item, key=key) for item in value]
    if isinstance(value, str):
        if key in {"digest", "resumed_from_digest"} and DIGEST_RE.fullmatch(value):
            return value
        if key in {"label", "owner_label"} and SAFE_LABEL_RE.fullmatch(value):
            return value
        if key == "uuid" and GPU_ID_RE.fullmatch(value):
            return value
        sanitized = SENSITIVE_JSON_TEXT_RE.sub(r"\1<redacted>", value)
        sanitized = SENSITIVE_TEXT_RE.sub(r"\1<redacted>", sanitized)
        sanitized = EMAIL_RE.sub("<redacted-email>", sanitized)
        sanitized = IPV4_RE.sub("<redacted-ip>", sanitized)
        return redact(sanitized)
    return value


def atomic_json(path: Path, value: Any) -> None:
    _atomic_json(path, _structured_redact(value))


@dataclasses.dataclass(frozen=True)
class ClientSpec:
    instance_id: str
    label: str


@dataclasses.dataclass(frozen=True)
class Config:
    machine_id: str
    owner_instance_id: str
    owner_label: str
    clients: tuple[ClientSpec, ...]
    host_cli: str
    client_cli: str
    client_evidence_command: str
    owner_evidence_command: str
    host_telemetry_command: str
    host_contract_evidence_command: str
    owner_charges_command: str
    client_charges_command: str
    host_earnings_command: str
    self_test_passed_at: str
    original_reliability_baseline: float
    expected_client_count: int = 4
    gpu_count: int = 4
    handoff_cycles: int = 3
    poll_seconds: float = 2.0
    owner_dwell_seconds: int = 120
    reclaim_slo_seconds: int = MAX_RECLAIM_SECONDS
    owner_stop_timeout_seconds: int = 120
    auto_return_seconds: int = AUTO_RETURN_SECONDS
    callback_timeout_seconds: int = 30
    contracts_reviewed: bool = False
    apply: bool = False


def _positive_id(value: Any, what: str) -> str:
    rendered = str(value)
    if isinstance(value, bool) or not rendered.isdigit() or int(rendered) <= 0:
        raise CycleError(f"{what} must be a positive integer")
    return rendered


def parse_client_spec(value: str) -> ClientSpec:
    if ":" not in value:
        raise argparse.ArgumentTypeError("--client must be INSTANCE_ID:EXACT_LABEL")
    instance_id, label = value.split(":", 1)
    try:
        instance_id = _positive_id(instance_id, "client instance ID")
    except CycleError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if not SAFE_LABEL_RE.fullmatch(label):
        raise argparse.ArgumentTypeError(
            "client label must be 8-80 safe characters and match the exact instance label"
        )
    return ClientSpec(instance_id, label)


def _parse_recent_iso_attestation(
    value: Any,
    what: str,
    *,
    max_age_seconds: int,
    now: dt.datetime | None = None,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CycleError(f"{what} must be a timezone-aware ISO timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise CycleError(f"{what} must be a timezone-aware ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CycleError(f"{what} must include a timezone")
    observed = parsed.astimezone(dt.timezone.utc)
    current = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    age = (current - observed).total_seconds()
    if age < -30:
        raise CycleError(f"{what} is implausibly in the future")
    if age > max_age_seconds:
        raise CycleError(f"{what} is older than {max_age_seconds} seconds")
    return observed.isoformat()


def validate_config(cfg: Config) -> None:
    _positive_id(cfg.machine_id, "machine ID")
    _positive_id(cfg.owner_instance_id, "owner instance ID")
    if not SAFE_LABEL_RE.fullmatch(cfg.owner_label):
        raise CycleError("owner label must be an exact safe label of 8-80 characters")
    if cfg.gpu_count != 4:
        raise CycleError("this pilot is intentionally fixed to one four-GPU dedicated host")
    if not 1 <= cfg.expected_client_count <= cfg.gpu_count:
        raise CycleError("expected client count must be between one and four")
    if len(cfg.clients) != cfg.expected_client_count:
        raise CycleError(
            f"expected exactly {cfg.expected_client_count} --client specs, got {len(cfg.clients)}"
        )
    ids = [item.instance_id for item in cfg.clients]
    labels = [item.label for item in cfg.clients]
    if len(ids) != len(set(ids)) or len(labels) != len(set(labels)):
        raise CycleError("controlled client IDs and labels must each be unique")
    if cfg.owner_instance_id in ids:
        raise CycleError("owner instance ID cannot also be a controlled client ID")
    if cfg.expected_client_count != cfg.gpu_count:
        raise CycleError("the four-GPU pilot requires exactly four one-GPU client slices")
    if cfg.handoff_cycles != MAX_HANDOFFS:
        raise CycleError("the named 24-hour pilot requires exactly three handoff cycles")
    if not math.isfinite(cfg.poll_seconds) or not 1 <= cfg.poll_seconds <= 5:
        raise CycleError("poll interval must be between one and five seconds")
    if not 1 <= cfg.owner_dwell_seconds <= 600:
        raise CycleError("owner dwell must be between one and 600 seconds")
    if not 1 <= cfg.reclaim_slo_seconds <= MAX_RECLAIM_SECONDS:
        raise CycleError("workload-ready SLO must be between one and 900 seconds")
    if not 1 <= cfg.owner_stop_timeout_seconds <= MAX_RECLAIM_SECONDS:
        raise CycleError("owner stop timeout must be between one and 900 seconds")
    if not 1 <= cfg.auto_return_seconds <= AUTO_RETURN_SECONDS:
        raise CycleError("automatic-return timeout must be between one and 300 seconds")
    if not 1 <= cfg.callback_timeout_seconds <= 120:
        raise CycleError("evidence callback timeout must be between one and 120 seconds")
    baseline = cfg.original_reliability_baseline
    if (
        isinstance(baseline, bool)
        or not isinstance(baseline, (int, float))
        or not math.isfinite(float(baseline))
        or not 0 <= float(baseline) <= 1
    ):
        raise CycleError("original reliability baseline must be between zero and one")
    if cfg.apply and not cfg.contracts_reviewed:
        raise CycleError(
            "apply requires --contracts-reviewed after inspecting Host Machines/Contracts"
        )
    _parse_recent_iso_attestation(
        cfg.self_test_passed_at,
        "--self-test-passed-at",
        max_age_seconds=SELF_TEST_MAX_AGE_SECONDS,
    )


def _strict_active_hold(root: Path, cfg: Config) -> dict[str, Any]:
    path = qualification_marker_path(root)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CycleError("an exact readable active qualification HOLD is required") from exc
    if (
        not isinstance(value, dict)
        or type(value.get("schema")) is not int
        or value.get("schema") != 1
        or value.get("active") is not True
        or str(value.get("machine_id", "")) != cfg.machine_id
    ):
        raise CycleError("qualification HOLD is malformed, inactive, or for another machine")
    allowed = value.get("allowed_stopped_owner_standbys")
    expected = {"instance_id": cfg.owner_instance_id, "label": cfg.owner_label}
    if allowed != [expected]:
        raise CycleError("qualification HOLD does not name the exact stopped owner standby")
    return value


def _strict_json_object(stdout: str, what: str) -> dict[str, Any]:
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise CycleError(f"{what} returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise CycleError(f"{what} must return one JSON object")
    return value


class EvidenceCommands:
    """Shell-free operator-vetted evidence adapters with a minimal environment."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.client_executable = shutil.which(cfg.client_evidence_command)
        self.owner_executable = shutil.which(cfg.owner_evidence_command)
        self.host_telemetry_executable = shutil.which(cfg.host_telemetry_command)
        self.host_contract_executable = shutil.which(cfg.host_contract_evidence_command)
        self.owner_charges_executable = shutil.which(cfg.owner_charges_command)
        self.client_charges_executable = shutil.which(cfg.client_charges_command)
        self.host_earnings_executable = shutil.which(cfg.host_earnings_command)
        if not self.client_executable:
            raise CycleError(
                f"client evidence executable not found: {cfg.client_evidence_command}"
            )
        if not self.owner_executable:
            raise CycleError(
                f"owner evidence executable not found: {cfg.owner_evidence_command}"
            )
        if not self.host_telemetry_executable:
            raise CycleError(
                f"host telemetry executable not found: {cfg.host_telemetry_command}"
            )
        if not self.host_contract_executable:
            raise CycleError(
                "host contract evidence executable not found: "
                f"{cfg.host_contract_evidence_command}"
            )
        if not self.owner_charges_executable:
            raise CycleError(f"owner charges executable not found: {cfg.owner_charges_command}")
        if not self.client_charges_executable:
            raise CycleError(f"client charges executable not found: {cfg.client_charges_command}")
        if not self.host_earnings_executable:
            raise CycleError(f"host earnings executable not found: {cfg.host_earnings_command}")

    @staticmethod
    def sanitized_env() -> dict[str, str]:
        environment = {
            name: value
            for name, value in os.environ.items()
            if name in SAFE_CALLBACK_ENV_NAMES and isinstance(value, str)
        }
        environment["PYTHONIOENCODING"] = "utf-8"
        return environment

    def _run(self, executable: str, args: list[str], what: str) -> dict[str, Any]:
        result = subprocess.run(
            [executable, *args],
            text=True,
            capture_output=True,
            timeout=self.cfg.callback_timeout_seconds,
            check=False,
            env=self.sanitized_env(),
        )
        if result.returncode != 0:
            raise CycleError(f"{what} failed with status {result.returncode}")
        return _strict_json_object(result.stdout, what)

    def client(self, spec: ClientSpec, phase: str, cycle: int) -> dict[str, Any]:
        return self._run(
            self.client_executable,
            [
                "--instance-id",
                spec.instance_id,
                "--label",
                spec.label,
                "--phase",
                phase,
                "--cycle",
                str(cycle),
            ],
            "client evidence callback",
        )

    def owner(self, phase: str, cycle: int) -> dict[str, Any]:
        return self._run(
            self.owner_executable,
            [
                "--instance-id",
                self.cfg.owner_instance_id,
                "--label",
                self.cfg.owner_label,
                "--machine-id",
                self.cfg.machine_id,
                "--phase",
                phase,
                "--cycle",
                str(cycle),
            ],
            "owner evidence callback",
        )

    def host_telemetry(self, phase: str, cycle: int) -> dict[str, Any]:
        return self._run(
            self.host_telemetry_executable,
            [
                "--machine-id",
                self.cfg.machine_id,
                "--phase",
                phase,
                "--cycle",
                str(cycle),
            ],
            "host telemetry evidence callback",
        )

    def host_contracts(self, phase: str, cycle: int) -> dict[str, Any]:
        return self._run(
            self.host_contract_executable,
            [
                "--machine-id",
                self.cfg.machine_id,
                "--owner-instance-id",
                self.cfg.owner_instance_id,
                "--phase",
                phase,
                "--cycle",
                str(cycle),
            ],
            "host contract evidence callback",
        )

    def billing(self, executable: str, role: str, phase: str) -> dict[str, Any]:
        args = [
            "--role",
            role,
            "--machine-id",
            self.cfg.machine_id,
            "--owner-instance-id",
            self.cfg.owner_instance_id,
            "--phase",
            phase,
        ]
        for spec in self.cfg.clients:
            args.extend(["--client-instance-id", spec.instance_id])
        return self._run(executable, args, f"{role} billing evidence callback")

    def owner_charges(self, phase: str) -> dict[str, Any]:
        return self.billing(self.owner_charges_executable, "owner-charges", phase)

    def client_charges(self, phase: str) -> dict[str, Any]:
        return self.billing(self.client_charges_executable, "controlled-client-charges", phase)

    def host_earnings(self, phase: str) -> dict[str, Any]:
        return self.billing(self.host_earnings_executable, "host-earnings", phase)


def _gpu_ids(value: Any, *, expected_count: int, what: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) != expected_count:
        raise CycleError(f"{what} must contain exactly {expected_count} GPU identifiers")
    if any(not isinstance(item, str) or not GPU_ID_RE.fullmatch(item) for item in value):
        raise CycleError(f"{what} contains an invalid GPU identifier")
    if len(set(value)) != len(value):
        raise CycleError(f"{what} contains duplicate GPU identifiers")
    return tuple(value)


def _checkpoint(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CycleError(f"{what} checkpoint must be an object")
    sequence = value.get("sequence")
    digest = value.get("digest")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise CycleError(f"{what} checkpoint sequence must be a non-negative integer")
    if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
        raise CycleError(f"{what} checkpoint digest must be lowercase SHA-256")
    return {"sequence": sequence, "digest": digest}


def validate_client_evidence(
    value: Any,
    spec: ClientSpec,
    *,
    prior: dict[str, Any] | None = None,
    require_resume_digest: bool = False,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CycleError("client evidence must be a JSON object")
    checks = {
        "instance ID": str(value.get("instance_id", "")) == spec.instance_id,
        "label": value.get("label") == spec.label,
        "running": value.get("running") is True,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise CycleError("client evidence identity/state mismatch: " + ", ".join(failed))
    gpu_ids = _gpu_ids(value.get("gpu_uuids"), expected_count=1, what="client evidence")
    checkpoint = _checkpoint(value.get("checkpoint"), "client evidence")
    last_completed_task = value.get("last_completed_task")
    if not isinstance(last_completed_task, str) or not last_completed_task.strip():
        raise CycleError("client evidence last_completed_task must be a nonempty string")
    normalized = {
        "instance_id": spec.instance_id,
        "label": spec.label,
        "running": True,
        "gpu_uuids": list(gpu_ids),
        "checkpoint": checkpoint,
        "last_completed_task": last_completed_task,
    }
    if prior is not None:
        if checkpoint["sequence"] <= prior["checkpoint"]["sequence"]:
            raise CycleError("client checkpoint did not advance after automatic return")
        if gpu_ids != tuple(prior["gpu_uuids"]):
            raise CycleError("client returned on a different GPU identity")
        if require_resume_digest:
            if value.get("resumed_from_digest") != prior["checkpoint"]["digest"]:
                raise CycleError("client callback did not prove resume from the pre-handoff digest")
            normalized["resumed_from_digest"] = value["resumed_from_digest"]
    elif require_resume_digest:
        raise CycleError("resume continuity requires a pre-handoff client snapshot")
    return normalized


def validate_owner_evidence(value: Any, cfg: Config, *, require_ready: bool) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CycleError("owner evidence must be a JSON object")
    checks = {
        "instance ID": str(value.get("owner_instance_id", "")) == cfg.owner_instance_id,
        "machine ID": str(value.get("machine_id", "")) == cfg.machine_id,
        "label": value.get("label") == cfg.owner_label,
        "GPU count": value.get("gpu_count") == cfg.gpu_count,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise CycleError("owner evidence identity mismatch: " + ", ".join(failed))
    ready = value.get("ready")
    if not isinstance(ready, bool) or (require_ready and not ready):
        raise CycleError("owner evidence did not prove workload readiness")
    gpu_ids = _gpu_ids(
        value.get("gpu_uuids"), expected_count=cfg.gpu_count, what="owner evidence"
    )
    checkpoint = _checkpoint(value.get("checkpoint"), "owner evidence")
    return {
        "owner_instance_id": cfg.owner_instance_id,
        "machine_id": cfg.machine_id,
        "label": cfg.owner_label,
        "ready": ready,
        "gpu_count": cfg.gpu_count,
        "gpu_uuids": list(gpu_ids),
        "checkpoint": checkpoint,
    }


def _finite_number(value: Any, what: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CycleError(f"{what} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise CycleError(f"{what} must be a finite number")
    if minimum is not None and normalized < minimum:
        raise CycleError(f"{what} must be at least {minimum}")
    return normalized


def _nonnegative_integer(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CycleError(f"{what} must be a non-negative integer")
    return value


def _true(value: Any, what: str) -> bool:
    if value is not True:
        raise CycleError(f"{what} must be explicitly true")
    return True


def _version(value: Any, what: str) -> str:
    if not isinstance(value, str) or not VERSION_RE.fullmatch(value):
        raise CycleError(f"{what} must be a nonempty safe version string")
    return value


def _cuda_at_least_118(value: Any) -> str:
    rendered = _version(value, "CUDA version")
    match = re.match(r"^(\d+)\.(\d+)", rendered)
    if match is None or (int(match.group(1)), int(match.group(2))) < (11, 8):
        raise CycleError("CUDA version must be at least 11.8")
    return rendered


def validate_host_telemetry(
    value: Any,
    cfg: Config,
    *,
    expected_gpu_ids: set[str] | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Validate and normalize one complete host-health attestation."""

    if not isinstance(value, dict):
        raise CycleError("host telemetry evidence must be one JSON object")
    if str(value.get("machine_id", "")) != cfg.machine_id:
        raise CycleError("host telemetry machine identity mismatch")
    observed_at = _parse_recent_iso_attestation(
        value.get("observed_at"),
        "host telemetry observed_at",
        max_age_seconds=ADAPTER_ATTESTATION_MAX_AGE_SECONDS,
        now=now,
    )
    _true(value.get("daemon_healthy"), "host daemon health")
    rows = value.get("gpus")
    if not isinstance(rows, list) or len(rows) != cfg.gpu_count:
        raise CycleError("host telemetry must contain exactly four GPU rows")
    gpus: list[dict[str, Any]] = []
    gpu_ids: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise CycleError("host telemetry GPU row must be an object")
        uuid = row.get("uuid")
        if not isinstance(uuid, str) or not GPU_ID_RE.fullmatch(uuid):
            raise CycleError("host telemetry contains an invalid GPU UUID")
        temperature = _finite_number(row.get("temperature_c"), f"GPU {index} temperature", minimum=0)
        if temperature >= 90:
            raise CycleError(f"GPU {index} temperature is not safely below 90C")
        power = _finite_number(row.get("power_w"), f"GPU {index} power", minimum=0)
        power_limit = _finite_number(
            row.get("power_limit_w"), f"GPU {index} power limit", minimum=1
        )
        if power > power_limit + 1e-9:
            raise CycleError(f"GPU {index} power exceeds its reported limit")
        if row.get("throttled") is not False or row.get("throttle_reasons") != []:
            raise CycleError(f"GPU {index} reports throttling")
        ecc = _nonnegative_integer(
            row.get("ecc_uncorrectable"), f"GPU {index} uncorrectable ECC count"
        )
        xid = _nonnegative_integer(row.get("xid_errors"), f"GPU {index} Xid count")
        if ecc != 0 or xid != 0:
            raise CycleError(f"GPU {index} reports ECC or Xid errors")
        gpu_ids.append(uuid)
        gpus.append(
            {
                "uuid": uuid,
                "temperature_c": temperature,
                "power_w": power,
                "power_limit_w": power_limit,
                "throttled": False,
                "throttle_reasons": [],
                "ecc_uncorrectable": 0,
                "xid_errors": 0,
            }
        )
    if len(set(gpu_ids)) != cfg.gpu_count:
        raise CycleError("host telemetry GPU UUIDs must be unique")
    if expected_gpu_ids is not None and set(gpu_ids) != expected_gpu_ids:
        raise CycleError("host telemetry GPU identity changed")

    storage = value.get("storage")
    if not isinstance(storage, dict):
        raise CycleError("host telemetry storage evidence is missing")
    normalized_storage = {
        "root_healthy": _true(storage.get("root_healthy"), "root filesystem health"),
        "root_free_gb": _finite_number(storage.get("root_free_gb"), "root free space", minimum=20),
        "docker_healthy": _true(storage.get("docker_healthy"), "Docker storage health"),
        "docker_total_gb": _finite_number(
            storage.get("docker_total_gb"), "Docker storage capacity", minimum=200
        ),
        "docker_free_gb": _finite_number(
            storage.get("docker_free_gb"), "Docker free space", minimum=10
        ),
        "docker_dedicated_drive": _true(
            storage.get("docker_dedicated_drive"), "dedicated Docker drive attestation"
        ),
        "docker_ssd": _true(storage.get("docker_ssd"), "Docker SSD attestation"),
    }

    network = value.get("network")
    if not isinstance(network, dict):
        raise CycleError("host telemetry network evidence is missing")
    normalized_network = {
        "download_mbps": _finite_number(
            network.get("download_mbps"), "network download", minimum=500
        ),
        "upload_mbps": _finite_number(
            network.get("upload_mbps"), "network upload", minimum=500
        ),
        "public_ipv4": _true(network.get("public_ipv4"), "public IPv4 attestation"),
        "wired": _true(network.get("wired"), "wired network attestation"),
    }

    ports = value.get("ports")
    if not isinstance(ports, dict):
        raise CycleError("host telemetry port evidence is missing")
    minimum_ports = 5 * cfg.gpu_count
    forwarded = _nonnegative_integer(ports.get("forwarded_count"), "forwarded port count")
    reachable = _nonnegative_integer(ports.get("reachable_count"), "reachable port count")
    if forwarded < minimum_ports or reachable < minimum_ports:
        raise CycleError("host telemetry does not prove at least five reachable ports per GPU")

    platform = value.get("platform")
    if not isinstance(platform, dict):
        raise CycleError("host telemetry platform evidence is missing")
    physical_cores = _nonnegative_integer(
        platform.get("physical_cpu_cores"), "physical CPU core count"
    )
    if physical_cores < 2 * cfg.gpu_count:
        raise CycleError("host needs at least two physical CPU cores per GPU")
    vm_support = platform.get("vm_support_enabled")
    if not isinstance(vm_support, bool):
        raise CycleError("VM support choice must be explicitly boolean")
    ubuntu_version = _version(platform.get("ubuntu_version"), "Ubuntu version")
    if not (ubuntu_version.startswith("22.04") or ubuntu_version.startswith("24.04")):
        raise CycleError("Ubuntu Server must be version 22.04 or 24.04")
    normalized_platform = {
        "driver_version": _version(platform.get("driver_version"), "NVIDIA driver version"),
        "cuda_version": _cuda_at_least_118(platform.get("cuda_version")),
        "kernel_version": _version(platform.get("kernel_version"), "kernel version"),
        "kernel_security_patched": _true(
            platform.get("kernel_security_patched"), "kernel security patch attestation"
        ),
        "ubuntu_server": _true(platform.get("ubuntu_server"), "Ubuntu Server attestation"),
        "ubuntu_version": ubuntu_version,
        "secure_boot_disabled": _true(
            platform.get("secure_boot_disabled"), "Secure Boot disabled attestation"
        ),
        "ssh_keys_only": _true(platform.get("ssh_keys_only"), "SSH keys-only attestation"),
        "unique_ssh_host_key": _true(
            platform.get("unique_ssh_host_key"), "unique SSH host-key attestation"
        ),
        "physical_cpu_cores": physical_cores,
        "cpu_avx": _true(platform.get("cpu_avx"), "CPU AVX attestation"),
        "identical_supported_gpus": _true(
            platform.get("identical_supported_gpus"), "identical supported GPU attestation"
        ),
        "pcie_healthy": _true(platform.get("pcie_healthy"), "PCIe health attestation"),
        "cpu_healthy": _true(platform.get("cpu_healthy"), "CPU health attestation"),
        "ram_healthy": _true(platform.get("ram_healthy"), "RAM health attestation"),
        "no_unrelated_background_services": _true(
            platform.get("no_unrelated_background_services"),
            "background service cleanliness attestation",
        ),
        "vm_support_enabled": vm_support,
    }
    return {
        "machine_id": cfg.machine_id,
        "observed_at": observed_at,
        "daemon_healthy": True,
        "gpus": gpus,
        "storage": normalized_storage,
        "network": normalized_network,
        "ports": {"forwarded_count": forwarded, "reachable_count": reachable},
        "platform": normalized_platform,
    }


def validate_host_contract_evidence(
    value: Any,
    cfg: Config,
    *,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Require a fresh host-side assertion of the exact controlled contracts."""

    if not isinstance(value, dict):
        raise CycleError("host contract evidence must be one JSON object")
    if str(value.get("machine_id", "")) != cfg.machine_id:
        raise CycleError("host contract evidence machine identity mismatch")
    observed_at = _parse_recent_iso_attestation(
        value.get("observed_at"),
        "host contract evidence observed_at",
        max_age_seconds=ADAPTER_ATTESTATION_MAX_AGE_SECONDS,
        now=now,
    )
    _true(value.get("inventory_complete"), "host contract inventory completeness")
    if value.get("outside_on_demand_or_reserved") is not False:
        raise CycleError("host contract evidence does not exclude outside on-demand/reserved work")
    if value.get("unknown_contract_ids") != []:
        raise CycleError("host contract evidence contains unknown contracts")
    source = value.get("source")
    if not isinstance(source, str) or not source.strip() or len(source) > 120:
        raise CycleError("host contract evidence source attestation is missing")
    owner = value.get("owner_standby")
    if not isinstance(owner, dict) or (
        str(owner.get("instance_id", "")) != cfg.owner_instance_id
        or str(owner.get("machine_id", "")) != cfg.machine_id
        or owner.get("label") != cfg.owner_label
        or owner.get("is_bid") is not False
        or owner.get("num_gpus") != cfg.gpu_count
        or owner.get("safely_stopped") is not True
    ):
        raise CycleError("host contract evidence owner standby identity/state mismatch")
    rows = value.get("controlled_contracts")
    if not isinstance(rows, list) or len(rows) != len(cfg.clients):
        raise CycleError("host contract evidence must contain the four exact controlled contracts")
    expected = {item.instance_id: item for item in cfg.clients}
    normalized_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise CycleError("host controlled contract row must be an object")
        instance_id = str(row.get("instance_id", ""))
        spec = expected.get(instance_id)
        if spec is None or instance_id in seen:
            raise CycleError("host contract evidence has a duplicate or unknown controlled ID")
        if (
            str(row.get("machine_id", "")) != cfg.machine_id
            or row.get("label") != spec.label
            or row.get("is_bid") is not True
            or row.get("num_gpus") != 1
            or row.get("active") is not True
        ):
            raise CycleError(f"host contract {instance_id} identity/type/state mismatch")
        seen.add(instance_id)
        normalized_rows.append(
            {
                "instance_id": instance_id,
                "machine_id": cfg.machine_id,
                "label": spec.label,
                "is_bid": True,
                "num_gpus": 1,
                "active": True,
            }
        )
    if seen != set(expected):
        raise CycleError("host contract evidence is missing a controlled contract")
    normalized_rows.sort(key=lambda row: int(row["instance_id"]))
    return {
        "machine_id": cfg.machine_id,
        "observed_at": observed_at,
        "inventory_complete": True,
        "owner_standby": {
            "instance_id": cfg.owner_instance_id,
            "machine_id": cfg.machine_id,
            "label": cfg.owner_label,
            "is_bid": False,
            "num_gpus": cfg.gpu_count,
            "safely_stopped": True,
        },
        "controlled_contracts": normalized_rows,
        "outside_on_demand_or_reserved": False,
        "unknown_contract_ids": [],
        "source": source,
    }


BILLING_ROLES = {
    "owner-charges",
    "controlled-client-charges",
    "host-earnings",
}
BILLING_COMPONENTS = ("gpu_usd", "storage_usd", "bandwidth_usd")


def validate_billing_evidence(
    value: Any,
    cfg: Config,
    *,
    role: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Normalize cumulative USD totals without retaining raw account records."""

    if role not in BILLING_ROLES:
        raise CycleError(f"unknown billing evidence role: {role}")
    if not isinstance(value, dict):
        raise CycleError(f"{role} billing evidence must be one JSON object")
    if value.get("role") != role:
        raise CycleError(f"{role} billing evidence role mismatch")
    if str(value.get("machine_id", "")) != cfg.machine_id:
        raise CycleError(f"{role} billing evidence machine identity mismatch")
    if value.get("currency") != "USD" or value.get("cumulative") is not True:
        raise CycleError(f"{role} billing evidence must be cumulative USD totals")
    observed_at = _parse_recent_iso_attestation(
        value.get("observed_at"),
        f"{role} billing observed_at",
        max_age_seconds=ADAPTER_ATTESTATION_MAX_AGE_SECONDS,
        now=now,
    )
    expected_ids = (
        {cfg.owner_instance_id}
        if role == "owner-charges"
        else {item.instance_id for item in cfg.clients}
    )
    raw_ids = value.get("instance_ids")
    if not isinstance(raw_ids, list):
        raise CycleError(f"{role} billing instance_ids must be a list")
    normalized_ids = [_positive_id(item, f"{role} billing instance ID") for item in raw_ids]
    if len(normalized_ids) != len(set(normalized_ids)) or set(normalized_ids) != expected_ids:
        raise CycleError(f"{role} billing evidence does not cover the exact expected instances")
    totals = value.get("totals")
    if not isinstance(totals, dict) or set(totals) != set(BILLING_COMPONENTS):
        raise CycleError(
            f"{role} billing totals must contain exactly GPU, storage, and bandwidth USD"
        )
    normalized_totals = {
        component: _finite_number(totals.get(component), f"{role} {component}", minimum=0)
        for component in BILLING_COMPONENTS
    }
    source = value.get("source")
    if not isinstance(source, str) or not source.strip() or len(source) > 120:
        raise CycleError(f"{role} billing evidence source attestation is missing")
    return {
        "role": role,
        "machine_id": cfg.machine_id,
        "instance_ids": sorted(normalized_ids, key=int),
        "currency": "USD",
        "cumulative": True,
        "observed_at": observed_at,
        "totals": normalized_totals,
        "source": source,
    }


def build_billing_report(
    baseline: dict[str, dict[str, Any]],
    final: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Compute the five review lines from monotonic cumulative account totals."""

    if set(baseline) != BILLING_ROLES or set(final) != BILLING_ROLES:
        raise CycleError("billing snapshots do not contain all three required account views")
    deltas: dict[str, dict[str, float]] = {}
    for role in sorted(BILLING_ROLES):
        if baseline[role].get("role") != role or final[role].get("role") != role:
            raise CycleError(f"billing snapshot role mismatch for {role}")
        role_delta: dict[str, float] = {}
        for component in BILLING_COMPONENTS:
            before = _finite_number(
                baseline[role].get("totals", {}).get(component),
                f"baseline {role} {component}",
                minimum=0,
            )
            after = _finite_number(
                final[role].get("totals", {}).get(component),
                f"final {role} {component}",
                minimum=0,
            )
            if after + 1e-12 < before:
                raise CycleError(f"cumulative billing total regressed for {role} {component}")
            role_delta[component] = round(after - before, 10)
        deltas[role] = role_delta

    owner = deltas["owner-charges"]
    renter = deltas["controlled-client-charges"]
    host = deltas["host-earnings"]
    controlled_spend = math.fsum(renter.values())
    host_earnings = math.fsum(host.values())
    return {
        "currency": "USD",
        "owner_own_machine_gpu_charge_usd": owner["gpu_usd"],
        "owner_standby_storage_and_bandwidth_charge_usd": round(
            owner["storage_usd"] + owner["bandwidth_usd"], 10
        ),
        "controlled_renter_gpu_storage_bandwidth_charge_usd": round(controlled_spend, 10),
        "host_gpu_storage_bandwidth_earnings_usd": round(host_earnings, 10),
        "net_controlled_test_leakage_usd": round(controlled_spend - host_earnings, 10),
        "component_deltas": deltas,
    }


def require_owner_identity(record: dict[str, Any], cfg: Config) -> None:
    checks = {
        "instance ID": identifier(record) == cfg.owner_instance_id,
        "machine ID": str(record.get("machine_id", "")) == cfg.machine_id,
        "label": record.get("label") == cfg.owner_label,
        "on-demand type": record.get("is_bid") is False,
        "whole-machine GPU count": record.get("num_gpus") == cfg.gpu_count,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise CycleError("owner standby identity mismatch: " + ", ".join(failed))


def require_client_identity(record: dict[str, Any], spec: ClientSpec, cfg: Config) -> None:
    checks = {
        "instance ID": identifier(record) == spec.instance_id,
        "machine ID": str(record.get("machine_id", "")) == cfg.machine_id,
        "label": record.get("label") == spec.label,
        "interruptible type": record.get("is_bid") is True,
        "one-GPU slice": record.get("num_gpus") == 1,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise CycleError(
            f"controlled client {spec.instance_id} identity mismatch: " + ", ".join(failed)
        )


def require_exact_inventories(
    host_value: Any,
    client_value: Any,
    cfg: Config,
    *,
    now_epoch: float | None = None,
    required_end_epoch: float | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate the two account views without claiming host-contract completeness.

    These CLI views can reject a record they expose.  Only the separately
    required, fresh host-contract adapter asserts that no outside contract is
    hidden from the account inventories.
    """

    host_rows = strict_instance_records(host_value, "host account instance response")
    client_rows = strict_instance_records(client_value, "controlled-client instance response")
    host_target = [row for row in host_rows if str(row.get("machine_id", "")) == cfg.machine_id]
    client_target = [row for row in client_rows if str(row.get("machine_id", "")) == cfg.machine_id]
    if len(host_target) != 1 or identifier(host_target[0]) != cfg.owner_instance_id:
        if any(row.get("is_bid") is False for row in host_target if identifier(row) != cfg.owner_instance_id):
            raise CycleError("outside on-demand or reserved target-machine contract detected")
        raise CycleError("host inventory is not the exact named owner-only target set")
    expected = {item.instance_id: item for item in cfg.clients}
    actual = {identifier(row): row for row in client_target}
    if len(actual) != len(client_target) or set(actual) != set(expected):
        unknown = sorted(set(actual) - set(expected), key=lambda item: int(item))
        if any(row.get("is_bid") is False for row in client_target if identifier(row) not in expected):
            raise CycleError("outside on-demand or reserved target-machine contract detected")
        raise CycleError(f"client inventory is not the exact controlled set; unknown IDs: {unknown}")
    require_owner_identity(host_target[0], cfg)
    ordered: list[dict[str, Any]] = []
    minimum_end = (
        required_end_epoch
        if required_end_epoch is not None
        else (time.time() if now_epoch is None else now_epoch) + PILOT_SECONDS
    )
    for spec in cfg.clients:
        row = actual[spec.instance_id]
        require_client_identity(row, spec, cfg)
        end_date = row.get("end_date")
        if (
            isinstance(end_date, bool)
            or not isinstance(end_date, (int, float))
            or not math.isfinite(float(end_date))
            or float(end_date) < minimum_end
        ):
            raise CycleError(
                f"controlled client {spec.instance_id} lacks a fixed end covering the 24-hour pilot"
            )
        ordered.append(row)
    return host_target[0], ordered


def resolve_state_root(project: Path) -> Path:
    configured = os.environ.get("VAST_STATE_DIR")
    root = Path(configured).expanduser() if configured else Path.home() / ".local/state/vast-host-golden-path"
    resolved = root.resolve()
    project_resolved = project.resolve()
    if resolved == project_resolved or project_resolved in resolved.parents:
        raise CycleError("VAST_STATE_DIR must be outside the repository")
    resolved.mkdir(parents=True, exist_ok=True)
    try:
        resolved.chmod(0o700)
    except OSError:
        pass
    return resolved


class Pilot:
    def __init__(
        self,
        cfg: Config,
        host: Cli,
        client: Cli,
        evidence: EvidenceCommands,
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
        self.evidence = evidence
        self.root = root
        self.run_dir = run_dir
        self.sleep = sleep
        self.monotonic = monotonic
        self.wall_time = wall_time
        self.started_at: float | None = None
        self.sequence = 0
        self.evidence_sequence = 0
        self.mutations_started = False
        self.owner_start_attempted = False
        self.owner_stop_authorized = False
        self.mode_boundary_crossed = False
        self.cleanup_errors: list[str] = []
        self.arm_baseline: dict[str, Any] | None = None
        self.last_score: dict[str, Any] | None = None
        self.cycles: list[dict[str, Any]] = []
        self.delayed_due: list[tuple[int, float]] = []
        self.delayed_observed: set[int] = set()
        self.last_client_evidence: dict[str, dict[str, Any]] | None = None
        self.expected_host_gpu_ids: set[str] | None = None
        self.telemetry_keys: set[tuple[str, int]] = set()
        self.telemetry_events: list[tuple[str, int]] = []
        self.contract_evidence_cycles: set[int] = set()
        self.contract_evidence_events: list[tuple[str, int]] = []
        self.client_evidence_events: list[tuple[str, int]] = []
        self.periodic_segments: list[dict[str, Any]] = []
        self.billing_baseline: dict[str, dict[str, Any]] | None = None
        self.billing_final: dict[str, dict[str, Any]] | None = None
        self.billing_report: dict[str, Any] | None = None
        self.cycle_pre_scores: dict[int, dict[str, Any]] = {}
        self.apply_horizon_pinned = False
        # Pin one absolute contract horizon.  Recomputing ``now + 24h`` on each
        # inventory would incorrectly demand a 48-hour contract at pilot end.
        self.required_end_epoch = self.wall_time() + PILOT_SECONDS + 10 * 60

    def next_evidence_path(self, directory: str, phase: str, cycle: int) -> Path:
        """Allocate a unique, monotonically numbered private evidence path."""

        self.evidence_sequence += 1
        safe_phase = re.sub(r"[^A-Za-z0-9_.-]+", "-", phase).strip("-.") or "sample"
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        return (
            self.run_dir
            / directory
            / f"{self.evidence_sequence:06d}-{stamp}-{safe_phase}-cycle-{cycle}.json"
        )

    def pin_apply_horizon(self) -> None:
        """Reset the fixed-end gate once, immediately before the apply run."""

        if self.apply_horizon_pinned:
            raise CycleError("apply fixed-end horizon was already pinned")
        self.required_end_epoch = self.wall_time() + PILOT_SECONDS + 10 * 60
        self.apply_horizon_pinned = True
        # Dry-run evidence may be only seconds old.  The actual run establishes
        # a new baseline; subsequent five-minute observations must advance it.
        self.last_client_evidence = None
        atomic_json(
            self.run_dir / "apply-fixed-end-horizon.json",
            {
                "at": utc_now(),
                "required_end_epoch": self.required_end_epoch,
                "pinned_once": True,
            },
        )

    def query_machine(self) -> dict[str, Any]:
        return exact_machine(
            self.host.json(["show", "machine", self.cfg.machine_id, "--raw"]),
            self.cfg.machine_id,
        )

    def query_reports(self) -> list[dict[str, Any]]:
        return parse_reports_output(
            self.host.run(["reports", self.cfg.machine_id, "--raw"]).stdout
        )

    def query_host_instances(self) -> list[dict[str, Any]]:
        return strict_instance_records(
            self.host.json(["show", "instances", "--raw"]),
            "host account instance response",
        )

    def query_owner(self) -> dict[str, Any]:
        record = exact_record(
            self.host.json(["show", "instance", self.cfg.owner_instance_id, "--raw"]),
            self.cfg.owner_instance_id,
            "owner standby",
        )
        require_owner_identity(record, self.cfg)
        return record

    def query_client_instances(self) -> list[dict[str, Any]]:
        return strict_instance_records(
            self.client.json(["show", "instances", "--raw"]),
            "controlled-client instance response",
        )

    def query_offers(self, kind: str) -> list[dict[str, Any]]:
        query = f"machine_id={self.cfg.machine_id} verified=any rentable=any rented=any"
        return strict_offer_records(
            self.host.json(
                ["search", "offers", query, "--no-default", "--type", kind, "--raw"]
            ),
            kind,
        )

    def inventories(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        return require_exact_inventories(
            self.query_host_instances(),
            self.query_client_instances(),
            self.cfg,
            now_epoch=self.wall_time(),
            required_end_epoch=self.required_end_epoch,
        )

    def score_sample(self, phase: str) -> dict[str, Any]:
        summary = machine_summary(self.query_machine(), self.query_reports())
        if not health_is_clear(summary):
            raise CycleError(f"machine health/report gate failed during {phase}")
        observed = summary["reliability"]
        if observed + 1e-12 < self.cfg.original_reliability_baseline:
            raise CycleError(
                f"reliability {observed} fell below immutable baseline "
                f"{self.cfg.original_reliability_baseline}"
            )
        if self.arm_baseline is not None and observed + 1e-12 < self.arm_baseline["reliability"]:
            raise CycleError("reliability regressed below the qualification-trend arm starting value")
        current_verification = str(summary.get("verification", "")).strip().lower()
        rank = {
            "deverified": 0,
            "de-verified": 0,
            "unverified": 1,
            "false": 1,
            "verified": 2,
            "true": 2,
        }
        if self.arm_baseline is None and current_verification not in rank:
            raise CycleError("platform verification state is not a recognized exact stage")
        reference = self.last_score or self.arm_baseline
        reference_verification = (
            "" if reference is None else str(reference.get("verification", ""))
        ).strip().lower()
        if reference is not None and observed + 1e-12 < float(reference["reliability"]):
            raise CycleError("reliability regressed from the immediately prior observation")
        if reference is not None and rank.get(current_verification, -1) < rank.get(
            reference_verification, -1
        ):
            raise CycleError("platform verification regressed from the immediately prior observation")
        self.sequence += 1
        payload = {"sequence": self.sequence, "phase": phase, **summary}
        atomic_json(self.run_dir / "score-samples" / f"{self.sequence:05d}-{phase}.json", payload)
        self.last_score = payload
        return payload

    @staticmethod
    def require_score_not_regressed(
        reference: dict[str, Any], current: dict[str, Any], *, context: str
    ) -> None:
        rank = {
            "deverified": 0,
            "de-verified": 0,
            "unverified": 1,
            "false": 1,
            "verified": 2,
            "true": 2,
        }
        if float(current["reliability"]) + 1e-12 < float(reference["reliability"]):
            raise CycleError(f"{context} reliability regressed from its cycle pre-score")
        before = str(reference.get("verification", "")).strip().lower()
        after = str(current.get("verification", "")).strip().lower()
        if rank.get(after, -1) < rank.get(before, -1):
            raise CycleError(f"{context} verification regressed from its cycle pre-score")

    def require_distinct_accounts(self) -> None:
        host_id = authenticated_account_id(self.host.json(["show", "user", "--raw"]))
        client_id = authenticated_account_id(self.client.json(["show", "user", "--raw"]))
        if host_id == client_id:
            raise CycleError("host/owner and controlled-client CLIs use the same Vast account")
        atomic_json(
            self.run_dir / "authenticated-accounts.json",
            {"host_owner_account_id": host_id, "controlled_client_account_id": client_id},
        )

    def prove_offer_absence(self, *, samples: int = 3) -> None:
        for sample in range(1, samples + 1):
            payload = {"at": utc_now(), "sample": sample}
            for kind in ("bid", "on-demand"):
                rows = self.query_offers(kind)
                payload[kind] = rows
                if rows:
                    raise CycleError(f"machine still exposes an exact {kind} offer")
            atomic_json(self.run_dir / "offer-absence" / f"{self.sequence:05d}-{sample}.json", payload)
            if sample < samples:
                self.sleep(self.cfg.poll_seconds)

    def unlist_and_prove(self) -> None:
        self.mutations_started = True
        result = self.host.run(["unlist", "machine", self.cfg.machine_id], check=False)
        atomic_text(
            self.run_dir / "mutations" / f"{self.sequence:05d}-unlist.txt",
            f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}\n",
        )
        self.prove_offer_absence()
        self.inventories()

    def _client_record_map(self) -> dict[str, dict[str, Any]]:
        _, rows = self.inventories()
        return {identifier(row): row for row in rows}

    def collect_client_evidence(
        self,
        phase: str,
        cycle: int,
        *,
        prior: dict[str, dict[str, Any]] | None = None,
        require_resume_digest: bool = False,
    ) -> dict[str, dict[str, Any]]:
        records = self._client_record_map()
        comparison = self.last_client_evidence if prior is None else prior
        output: dict[str, dict[str, Any]] = {}
        gpu_ids: list[str] = []
        for spec in self.cfg.clients:
            if not is_running(records[spec.instance_id]):
                raise CycleError(f"controlled client {spec.instance_id} is not running")
            current = validate_client_evidence(
                self.evidence.client(spec, phase, cycle),
                spec,
                prior=None if comparison is None else comparison[spec.instance_id],
                require_resume_digest=require_resume_digest,
            )
            output[spec.instance_id] = current
            gpu_ids.extend(current["gpu_uuids"])
        if len(set(gpu_ids)) != self.cfg.gpu_count:
            raise CycleError("controlled clients do not prove four unique GPU identities")
        if self.expected_host_gpu_ids is not None and set(gpu_ids) != self.expected_host_gpu_ids:
            raise CycleError("controlled client GPU identities do not match host telemetry")
        atomic_json(self.next_evidence_path("workload-evidence", phase, cycle), output)
        # Commit the new baseline only after every exact client passed, keeping
        # a failed four-slice observation all-or-nothing.
        self.last_client_evidence = output
        self.client_evidence_events.append((phase, cycle))
        return output

    def capture_host_telemetry(self, phase: str, cycle: int) -> dict[str, Any]:
        value = validate_host_telemetry(
            self.evidence.host_telemetry(phase, cycle),
            self.cfg,
            expected_gpu_ids=self.expected_host_gpu_ids,
        )
        observed_ids = {row["uuid"] for row in value["gpus"]}
        if self.expected_host_gpu_ids is None:
            self.expected_host_gpu_ids = observed_ids
        atomic_json(self.next_evidence_path("host-telemetry", phase, cycle), value)
        self.telemetry_keys.add((phase, cycle))
        self.telemetry_events.append((phase, cycle))
        return value

    def capture_host_contract_evidence(self, phase: str, cycle: int) -> dict[str, Any]:
        value = validate_host_contract_evidence(
            self.evidence.host_contracts(phase, cycle), self.cfg
        )
        atomic_json(self.next_evidence_path("host-contract-evidence", phase, cycle), value)
        self.contract_evidence_cycles.add(cycle)
        self.contract_evidence_events.append((phase, cycle))
        return value

    def capture_billing_snapshot(self, phase: str) -> dict[str, dict[str, Any]]:
        raw = {
            "owner-charges": self.evidence.owner_charges(phase),
            "controlled-client-charges": self.evidence.client_charges(phase),
            "host-earnings": self.evidence.host_earnings(phase),
        }
        normalized = {
            role: validate_billing_evidence(value, self.cfg, role=role)
            for role, value in raw.items()
        }
        atomic_json(self.next_evidence_path("billing", phase, 0), normalized)
        return normalized

    def periodic_sample_total(self, mode: str) -> int:
        return sum(
            len(segment.get("samples", []))
            for segment in self.periodic_segments
            if segment.get("mode") == mode and segment.get("complete") is True
        )

    def periodic_completion_gate(self) -> bool:
        if not self.periodic_segments:
            return False
        modes = {str(segment.get("mode")) for segment in self.periodic_segments}
        if modes != {"qualification", "research"}:
            return False
        if any(segment.get("complete") is not True for segment in self.periodic_segments):
            return False
        return self.periodic_sample_total("qualification") > 0 and self.periodic_sample_total(
            "research"
        ) > 0

    def periodic_evidence_complete(self, events: list[tuple[str, int]]) -> bool:
        required = {
            "qualification-soak": self.periodic_sample_total("qualification"),
            "research-observation": self.periodic_sample_total("research"),
        }
        return all(
            expected > 0
            and sum(1 for phase, cycle in events if phase == label and cycle == 0)
            >= expected
            for label, expected in required.items()
        )

    def telemetry_completion_gate(self) -> bool:
        required = {("preflight", 0), ("final", 0)}
        for cycle in range(1, self.cfg.handoff_cycles + 1):
            required.update(
                {
                    ("before-handoff", cycle),
                    ("immediate-after-handoff", cycle),
                    ("two-hour-delayed", cycle),
                }
            )
        modes_observed = any(key[0] == "qualification-soak" for key in self.telemetry_keys) and any(
            key[0] == "research-observation" for key in self.telemetry_keys
        )
        return (
            required.issubset(self.telemetry_keys)
            and modes_observed
            and self.periodic_evidence_complete(self.telemetry_events)
        )

    def contract_completion_gate(self) -> bool:
        required = {("preflight", 0), ("final", 0)} | {
            ("before-handoff", cycle) for cycle in range(1, MAX_HANDOFFS + 1)
        }
        return (
            required.issubset(set(self.contract_evidence_events))
            and self.periodic_evidence_complete(self.contract_evidence_events)
        )

    def client_evidence_completion_gate(self) -> bool:
        return self.periodic_evidence_complete(self.client_evidence_events)

    def billing_completion_gate(self) -> bool:
        return (
            self.billing_baseline is not None
            and self.billing_final is not None
            and self.billing_report is not None
        )

    def preflight(self) -> dict[str, Any]:
        _strict_active_hold(self.root, self.cfg)
        self_test_at = _parse_recent_iso_attestation(
            self.cfg.self_test_passed_at,
            "--self-test-passed-at",
            max_age_seconds=SELF_TEST_MAX_AGE_SECONDS,
        )
        atomic_json(
            self.run_dir / "self-test-attestation.json",
            {
                "machine_id": self.cfg.machine_id,
                "passed_at": self_test_at,
                "ordinary_self_test_without_ignore_requirements": True,
                "source": (
                    "operator attestation supplied at preflight; ordinary Self-Test "
                    "performed while vacant before controlled-client acquisition"
                ),
                "vast_mutations_performed": 0,
            },
        )
        self.require_distinct_accounts()
        machine = self.query_machine()
        if machine.get("num_gpus") != self.cfg.gpu_count:
            raise CycleError("machine does not expose exactly four GPUs")
        owner, clients = self.inventories()
        if not is_safely_stopped(owner):
            raise CycleError("owner standby is not in the exact fail-closed stopped tuple")
        if any(not is_running(row) for row in clients):
            raise CycleError("every controlled interruptible must be running at pilot start")
        self.prove_offer_absence()
        contracts = self.capture_host_contract_evidence("preflight", 0)
        telemetry = self.capture_host_telemetry("preflight", 0)
        billing = self.capture_billing_snapshot("baseline")
        self.billing_baseline = billing
        self.arm_baseline = self.score_sample("preflight")
        workloads = self.collect_client_evidence("preflight", 0)
        if {gpu for item in workloads.values() for gpu in item["gpu_uuids"]} != self.expected_host_gpu_ids:
            raise CycleError("controlled client GPU identities do not match host telemetry")
        return {
            "machine": machine,
            "owner": owner,
            "clients": clients,
            "workloads": workloads,
            "host_telemetry": telemetry,
            "host_contract_evidence": contracts,
            "billing_baseline": billing,
        }

    def qualification_sample(self, label: str) -> None:
        _strict_active_hold(self.root, self.cfg)
        try:
            assessment = sample_qualification_mode(
                self.root, self.host, machine_id=self.cfg.machine_id
            )
        except QualificationGuardError as exc:
            raise CycleError(str(exc)) from exc
        raw_blockers = assessment.get("blockers")
        if not isinstance(raw_blockers, list) or any(
            not isinstance(item, str) for item in raw_blockers
        ):
            raise CycleError("qualification observer returned a malformed blocker set")
        blockers = set(raw_blockers)
        # A new host enters this soak precisely because reliability and its
        # local trend history are immature.  Those two observations may remain
        # pending while the score is flat or rising.  Hardware/configuration,
        # health, reports, and every other observable prerequisite still abort.
        maturity_blockers = {"reliability", "steady_uptime_history"}
        unexpected_blockers = sorted(blockers - maturity_blockers)
        trend_status = (
            assessment.get("checks", {})
            .get("steady_uptime_history", {})
            .get("actual", {})
            .get("trend_status")
        )
        if "steady_uptime_history" in blockers and trend_status != "insufficient-history":
            unexpected_blockers.append("steady_uptime_history")
        if unexpected_blockers:
            raise CycleError(
                "qualification observer reports unsafe observable blockers: "
                + ", ".join(unexpected_blockers)
            )
        guard_reliability = _finite_number(
            assessment.get("checks", {}).get("reliability", {}).get("actual"),
            "qualification observer reliability",
            minimum=0,
        )
        if guard_reliability > 1:
            raise CycleError("qualification observer reliability must not exceed one")
        guard_score = {
            "at": assessment.get("observed_at", utc_now()),
            "phase": f"{label}-guard-observation",
            "reliability": guard_reliability,
            "verification": assessment.get("platform_verification"),
        }
        if self.last_score is not None:
            self.require_score_not_regressed(
                self.last_score,
                guard_score,
                context=f"{label} qualification-guard observation",
            )
        self.sequence += 1
        guard_score["sequence"] = self.sequence
        atomic_json(
            self.run_dir
            / "score-samples"
            / f"{self.sequence:05d}-{label}-guard-observation.json",
            guard_score,
        )
        self.last_score = guard_score
        self.capture_host_contract_evidence(label, 0)
        self.capture_host_telemetry(label, 0)
        self.score_sample(label)
        self.collect_client_evidence(label, 0)

    def observe_until(self, target_elapsed: float, mode: str) -> None:
        if self.started_at is None:
            raise CycleError("pilot clock is absent")
        if mode not in {"qualification", "research"}:
            raise CycleError(f"unknown periodic observation mode: {mode}")
        # Each call is a bounded observation segment. Handoffs sit between
        # research segments and have their own two-second state polling gates.
        segment_start = self.monotonic()
        target = self.started_at + target_elapsed
        segment_number = len(self.periodic_segments) + 1
        segment = {
            "schema": 1,
            "segment": segment_number,
            "mode": mode,
            "started_monotonic": segment_start,
            "target_monotonic": target,
            "maximum_gap_seconds": MAX_SAMPLE_GAP_SECONDS,
            "samples": [],
            "complete": False,
        }
        self.periodic_segments.append(segment)
        cadence_path = self.next_evidence_path(
            "cadence", f"{mode}-segment-{segment_number}", 0
        )
        next_sample = segment_start + SAMPLE_SECONDS
        last_completed = segment_start
        try:
            while self.monotonic() < target:
                now = self.monotonic()
                if now >= next_sample:
                    if now - last_completed > MAX_SAMPLE_GAP_SECONDS:
                        raise CycleError(
                            f"{mode} evidence cadence gap exceeded {MAX_SAMPLE_GAP_SECONDS} seconds"
                        )
                    sample_started = now
                    if mode == "qualification":
                        self.qualification_sample("qualification-soak")
                    else:
                        self.capture_host_contract_evidence("research-observation", 0)
                        self.capture_host_telemetry("research-observation", 0)
                        self.score_sample("research-observation")
                        self.collect_client_evidence("research-observation", 0)
                        self.capture_due_delayed_observations()
                    sample_completed = self.monotonic()
                    if sample_completed - last_completed > MAX_SAMPLE_GAP_SECONDS:
                        raise CycleError(
                            f"{mode} completed-evidence cadence gap exceeded "
                            f"{MAX_SAMPLE_GAP_SECONDS} seconds"
                        )
                    segment["samples"].append(
                        {
                            "sample": len(segment["samples"]) + 1,
                            "started_monotonic": sample_started,
                            "completed_monotonic": sample_completed,
                        }
                    )
                    last_completed = sample_completed
                    while next_sample <= sample_completed:
                        next_sample += SAMPLE_SECONDS
                    atomic_json(cadence_path, segment)
                self.sleep(
                    min(60.0, max(0.0, min(target, next_sample) - self.monotonic()))
                )
            finished = self.monotonic()
            if finished - last_completed > MAX_SAMPLE_GAP_SECONDS:
                raise CycleError(
                    f"{mode} trailing evidence cadence gap exceeded "
                    f"{MAX_SAMPLE_GAP_SECONDS} seconds"
                )
            bounded_duration = max(0.0, min(finished, target) - segment_start)
            expected_minimum = max(0, math.ceil(bounded_duration / SAMPLE_SECONDS) - 1)
            if len(segment["samples"]) < expected_minimum:
                raise CycleError(
                    f"{mode} observation stored {len(segment['samples'])} periodic samples; "
                    f"at least {expected_minimum} were required"
                )
            segment["finished_monotonic"] = finished
            segment["complete"] = True
        finally:
            atomic_json(cadence_path, segment)

    def capture_due_delayed_observations(self) -> None:
        """Attach an explicit rating sample to every two-hour handoff deadline."""

        now = self.monotonic()
        for cycle, due in self.delayed_due:
            if cycle in self.delayed_observed or now < due:
                continue
            self.capture_host_telemetry("two-hour-delayed", cycle)
            sample = self.score_sample(f"cycle-{cycle}-two-hour-delayed")
            self.require_score_not_regressed(
                self.cycle_pre_scores[cycle], sample, context=f"cycle {cycle} delayed sample"
            )
            atomic_json(
                self.run_dir / "cycles" / f"cycle-{cycle}-two-hour-delayed.json",
                {"cycle": cycle, "due_monotonic": due, "observed_monotonic": now, "score": sample},
            )
            if 1 <= cycle <= len(self.cycles):
                self.cycles[cycle - 1]["score_two_hour_delayed"] = sample
                atomic_json(
                    self.run_dir / "cycles" / f"cycle-{cycle}-result.json",
                    self.cycles[cycle - 1],
                )
            self.delayed_observed.add(cycle)

    def cross_mode_boundary(self) -> None:
        self.qualification_sample("qualification-final")
        before = self.last_score or {}
        # HOLD removal changes the pilot's safety mode.  Mark it before the
        # attempt so even a partial/uncertain disable enters guarded cleanup.
        self.mutations_started = True
        try:
            disabled = disable_qualification_mode(self.root, machine_id=self.cfg.machine_id)
        except QualificationGuardError as exc:
            raise CycleError(str(exc)) from exc
        self.mode_boundary_crossed = True
        atomic_json(
            self.run_dir / "mode-boundary.json",
            {
                "at": utc_now(),
                "from": "qualification-hold",
                "to": "research-first-owner-on-demand",
                "qualification_final_score": before,
                "hold_disable": disabled,
                "owner_workloads_verification_safe": False,
                "host_job_or_create_job": False,
            },
        )

    def _state_snapshot(self, phase: str, cycle: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        owner, clients = self.inventories()
        self.sequence += 1
        atomic_json(
            self.run_dir / "state-snapshots" / f"{self.sequence:05d}-{phase}.json",
            {"at": utc_now(), "cycle": cycle, "phase": phase, "owner": owner, "clients": clients},
        )
        return owner, clients

    def wait_for_platform_takeover(self, cycle: int, decision: float) -> None:
        deadline = decision + self.cfg.reclaim_slo_seconds
        consecutive = 0
        while self.monotonic() <= deadline:
            owner, clients = self._state_snapshot("takeover-poll", cycle)
            owner_running = is_running(owner)
            running_clients = [row for row in clients if is_running(row)]
            stopped_clients = [row for row in clients if is_safely_stopped(row)]
            if len(running_clients) + len(stopped_clients) != len(clients):
                raise CycleError("a controlled client entered an ambiguous takeover state")
            if owner_running and running_clients:
                raise CycleError("owner and controlled client reported simultaneous running states")
            if len(stopped_clients) not in (0, len(clients)) and owner_running:
                raise CycleError("owner started before every controlled slice was safely stopped")
            if owner_running and len(stopped_clients) == len(clients):
                consecutive += 1
                if consecutive >= 2:
                    return
            else:
                consecutive = 0
            self.sleep(self.cfg.poll_seconds)
        raise CycleError("platform takeover did not complete inside the 15-minute SLO")

    def wait_for_owner_ready(
        self,
        cycle: int,
        decision: float,
        expected_gpu_ids: set[str],
    ) -> dict[str, Any]:
        deadline = decision + self.cfg.reclaim_slo_seconds
        while self.monotonic() <= deadline:
            value = validate_owner_evidence(
                self.evidence.owner("ready", cycle), self.cfg, require_ready=False
            )
            atomic_json(
                self.run_dir / "workload-evidence" / f"cycle-{cycle}-owner-ready-poll.json",
                value,
            )
            if value["ready"]:
                if set(value["gpu_uuids"]) != expected_gpu_ids:
                    raise CycleError("owner workload did not acquire the four expected GPU identities")
                return value
            self.sleep(self.cfg.poll_seconds)
        raise CycleError("owner research workload was not ready within 15 minutes")

    def owner_dwell(self, cycle: int, initial: dict[str, Any]) -> dict[str, Any]:
        deadline = self.monotonic() + self.cfg.owner_dwell_seconds
        while self.monotonic() < deadline:
            owner, clients = self._state_snapshot("owner-dwell", cycle)
            if not is_running(owner) or any(not is_safely_stopped(row) for row in clients):
                raise CycleError("owner/client state changed during bounded research dwell")
            self.sleep(min(self.cfg.poll_seconds, max(0.0, deadline - self.monotonic())))
        final = validate_owner_evidence(
            self.evidence.owner("checkpoint", cycle), self.cfg, require_ready=True
        )
        if final["checkpoint"]["sequence"] <= initial["checkpoint"]["sequence"]:
            raise CycleError("owner checkpoint did not advance during the research dwell")
        if set(final["gpu_uuids"]) != set(initial["gpu_uuids"]):
            raise CycleError("owner GPU identity changed during the research dwell")
        atomic_json(
            self.run_dir / "workload-evidence" / f"cycle-{cycle}-owner-final.json", final
        )
        return final

    def stop_owner_and_prove(self, cycle: int, *, cleanup: bool = False) -> None:
        if not self.owner_stop_authorized:
            raise CycleError("exact owner-stop cleanup was not authorized")
        owner = self.query_owner()
        if is_safely_stopped(owner):
            return
        result = self.host.run(
            ["stop", "instance", self.cfg.owner_instance_id, "--raw"], check=False
        )
        atomic_text(
            self.run_dir / "mutations" / f"cycle-{cycle}-owner-stop.txt",
            f"cleanup={cleanup}\nreturncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}\n",
        )
        deadline = self.monotonic() + self.cfg.owner_stop_timeout_seconds
        consecutive = 0
        while self.monotonic() <= deadline:
            owner = self.query_owner()
            self.sequence += 1
            atomic_json(
                self.run_dir / "state-snapshots" / f"{self.sequence:05d}-owner-stop-poll.json",
                {"at": utc_now(), "cycle": cycle, "phase": "owner-stop-poll", "owner": owner},
            )
            if is_safely_stopped(owner):
                consecutive += 1
                if consecutive >= 2:
                    return
            else:
                consecutive = 0
            self.sleep(self.cfg.poll_seconds)
        raise CycleError("exact owner standby did not reach the safe stopped tuple")

    def wait_for_all_auto_return(self, cycle: int) -> None:
        deadline = self.monotonic() + self.cfg.auto_return_seconds
        consecutive = 0
        while self.monotonic() <= deadline:
            owner, clients = self._state_snapshot("auto-return-poll", cycle)
            if not is_safely_stopped(owner):
                raise CycleError("owner ceased to be safely stopped during client return")
            if all(is_running(row) for row in clients):
                consecutive += 1
                if consecutive >= 2:
                    return
            else:
                consecutive = 0
            self.sleep(self.cfg.poll_seconds)
        raise CycleError("not every original controlled client returned automatically")

    def handoff(self, cycle: int) -> dict[str, Any]:
        if not self.mode_boundary_crossed:
            raise CycleError("owner handoff refused before the explicit HOLD boundary")
        try:
            require_qualification_mode_inactive(
                self.root,
                machine_id=self.cfg.machine_id,
                action="four-GPU owner handoff",
            )
        except QualificationGuardError as exc:
            raise CycleError(str(exc)) from exc
        # The research scheduler's decision begins the SLO.  Checkpointing,
        # unlisting, inventory proof, platform takeover, and workload readiness
        # all consume this same 15-minute budget.
        decision = self.monotonic()
        self.capture_host_telemetry("before-handoff", cycle)
        before_score = self.score_sample(f"cycle-{cycle}-before")
        self.cycle_pre_scores[cycle] = before_score
        before = self.collect_client_evidence("before-handoff", cycle)
        expected_gpu_ids = {
            gpu_id for value in before.values() for gpu_id in value["gpu_uuids"]
        }
        self.unlist_and_prove()
        owner, clients = self.inventories()
        if not is_safely_stopped(owner) or any(not is_running(row) for row in clients):
            raise CycleError("exact owner/client states changed before owner start")
        # This host-side contract assertion is deliberately the final external
        # evidence gate before the qualification interlock and owner start.
        self.capture_host_contract_evidence("before-handoff", cycle)
        try:
            with qualification_owner_mutation_interlock(
                self.root,
                action=f"start four-GPU owner standby {self.cfg.owner_instance_id}",
            ):
                require_qualification_mode_inactive(
                    self.root,
                    machine_id=self.cfg.machine_id,
                    action="four-GPU owner start",
                )
                if self.monotonic() > decision + self.cfg.reclaim_slo_seconds:
                    raise CycleError("pre-start safety gates exhausted the workload-ready SLO")
                self.owner_start_attempted = True
                result = self.host.run(
                    ["start", "instance", self.cfg.owner_instance_id, "--raw"],
                    check=False,
                )
        except QualificationGuardError as exc:
            raise CycleError(str(exc)) from exc
        atomic_text(
            self.run_dir / "mutations" / f"cycle-{cycle}-owner-start.txt",
            f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}\n",
        )
        self.wait_for_platform_takeover(cycle, decision)
        ready = self.wait_for_owner_ready(cycle, decision, expected_gpu_ids)
        ready_elapsed = self.monotonic() - decision
        if ready_elapsed > self.cfg.reclaim_slo_seconds:
            raise CycleError("owner workload-ready measurement exceeded the configured SLO")
        final = self.owner_dwell(cycle, ready)
        self.stop_owner_and_prove(cycle)
        self.wait_for_all_auto_return(cycle)
        after = self.collect_client_evidence(
            "after-return",
            cycle,
            prior=before,
            require_resume_digest=True,
        )
        self.capture_host_telemetry("immediate-after-handoff", cycle)
        after_score = self.score_sample(f"cycle-{cycle}-immediate")
        self.require_score_not_regressed(
            before_score, after_score, context=f"cycle {cycle} immediate sample"
        )
        result_value = {
            "cycle": cycle,
            "owner_workload_ready_seconds": ready_elapsed,
            "within_15_minutes": ready_elapsed <= MAX_RECLAIM_SECONDS,
            "automatic_returns": len(after),
            "expected_automatic_returns": len(self.cfg.clients),
            "client_before": before,
            "client_after": after,
            "owner_ready": ready,
            "owner_final": final,
            "score_before": before_score,
            "score_immediate": after_score,
            "host_job_or_create_job": False,
        }
        atomic_json(self.run_dir / "cycles" / f"cycle-{cycle}-result.json", result_value)
        self.cycles.append(result_value)
        self.delayed_due.append((cycle, self.monotonic() + 2 * 60 * 60))
        return result_value

    def cleanup(self) -> None:
        if not self.mutations_started and not self.owner_start_attempted:
            atomic_json(
                self.run_dir / "cleanup.json",
                {
                    "controller_safety_cleanup_complete": True,
                    "full_pilot_cleanup_complete": False,
                    "mutations_attempted": False,
                    "errors": [],
                    "manual_exact_id_cleanup_required": True,
                },
            )
            return
        try:
            self.unlist_and_prove()
        except Exception as exc:  # noqa: BLE001
            self.cleanup_errors.append(f"unlist/offer-absence proof: {exc}")
        try:
            self.stop_owner_and_prove(0, cleanup=True)
        except Exception as exc:  # noqa: BLE001
            self.cleanup_errors.append(f"stop exact owner standby: {exc}")
        if self.owner_start_attempted:
            try:
                self.wait_for_all_auto_return(0)
            except Exception as exc:  # noqa: BLE001
                self.cleanup_errors.append(f"wait for all controlled clients to return: {exc}")
        try:
            owner, clients = self.inventories()
            if not is_safely_stopped(owner):
                raise CycleError("owner not safely stopped at cleanup")
            if any(not is_running(row) for row in clients):
                raise CycleError("one or more controlled clients not running at cleanup")
        except Exception as exc:  # noqa: BLE001
            self.cleanup_errors.append(f"final exact inventory: {exc}")
        atomic_json(
            self.run_dir / "cleanup.json",
            {
                "controller_safety_cleanup_complete": not self.cleanup_errors,
                "full_pilot_cleanup_complete": False,
                "errors": self.cleanup_errors,
                "machine_unlisted": not self.cleanup_errors,
                "owner_standby_retained": True,
                "controlled_clients_retained": [item.instance_id for item in self.cfg.clients],
                "manual_cleanup_required": (
                    "The repository's reusable precreated-owner rule permits stop, not destroy. "
                    "Destroy the exact controlled clients through a separately reviewed exact-ID "
                    "cleanup, and retain or separately retire the owner according to its provenance."
                ),
            },
        )

    def run(self) -> dict[str, Any]:
        if self.cfg.apply and not self.apply_horizon_pinned:
            raise CycleError("apply run requires one fixed-end horizon pin after confirmation")
        self.preflight()
        self.started_at = self.monotonic()
        self.observe_until(QUALIFICATION_SECONDS, "qualification")
        self.cross_mode_boundary()
        offsets = DEFAULT_CYCLE_OFFSETS[: self.cfg.handoff_cycles]
        for cycle, offset in enumerate(offsets, start=1):
            self.observe_until(offset, "research")
            remaining = self.started_at + PILOT_SECONDS - self.monotonic()
            required = (
                self.cfg.reclaim_slo_seconds
                + self.cfg.owner_dwell_seconds
                + self.cfg.owner_stop_timeout_seconds
                + self.cfg.auto_return_seconds
            )
            if remaining < required:
                raise CycleError("insufficient bounded pilot time remains for another safe handoff")
            self.handoff(cycle)
        self.observe_until(PILOT_SECONDS, "research")
        self.capture_due_delayed_observations()
        self.capture_host_contract_evidence("final", 0)
        self.capture_host_telemetry("final", 0)
        final_score = self.score_sample("final")
        self.billing_final = self.capture_billing_snapshot("final")
        if self.billing_baseline is None:
            raise CycleError("billing baseline is absent at finalization")
        self.billing_report = build_billing_report(self.billing_baseline, self.billing_final)
        atomic_json(self.next_evidence_path("billing", "report", 0), self.billing_report)
        periodic_complete = self.periodic_completion_gate()
        telemetry_complete = self.telemetry_completion_gate()
        contracts_complete = self.contract_completion_gate()
        clients_complete = self.client_evidence_completion_gate()
        billing_complete = self.billing_completion_gate()
        if not all(
            (
                periodic_complete,
                telemetry_complete,
                contracts_complete,
                clients_complete,
                billing_complete,
            )
        ):
            raise CycleError(
                "required cadence, workload, host telemetry, contract, or billing evidence is incomplete"
            )
        return {
            "experimental": True,
            "production_ready": False,
            "qualification_and_research_modes_separate": True,
            "mode_boundary_crossed": self.mode_boundary_crossed,
            "completed_handoffs": len(self.cycles),
            "requested_handoffs": self.cfg.handoff_cycles,
            "cycles": self.cycles,
            "two_hour_delayed_cycles": sorted(self.delayed_observed),
            "host_telemetry_complete": telemetry_complete,
            "host_contract_evidence_complete": contracts_complete,
            "periodic_evidence_complete": periodic_complete,
            "client_evidence_complete": clients_complete,
            "billing_evidence_complete": billing_complete,
            "billing_report": self.billing_report,
            "final_score": final_score,
            "owner_workloads_verification_safe": False,
            "host_job_or_create_job": False,
        }


def build_plan(cfg: Config) -> dict[str, Any]:
    return {
        "experimental": True,
        "production_ready": False,
        "duration_seconds": PILOT_SECONDS,
        "qualification_hold_seconds": QUALIFICATION_SECONDS,
        "score_sample_seconds": SAMPLE_SECONDS,
        "maximum_periodic_evidence_gap_seconds": MAX_SAMPLE_GAP_SECONDS,
        "mode_boundary": {
            "operation": "disable local qualification HOLD",
            "owner_workloads_verification_safe": False,
        },
        "handoff_offsets_seconds": list(DEFAULT_CYCLE_OFFSETS[: cfg.handoff_cycles]),
        "machine_id": cfg.machine_id,
        "owner": {
            "instance_id": cfg.owner_instance_id,
            "label": cfg.owner_label,
            "type": "on-demand",
            "gpu_count": cfg.gpu_count,
        },
        "controlled_clients": [
            {"instance_id": item.instance_id, "label": item.label, "type": "interruptible", "gpu_count": 1}
            for item in cfg.clients
        ],
        "first_remote_mutation": ["unlist", "machine", cfg.machine_id],
        "owner_start": ["start", "instance", cfg.owner_instance_id, "--raw"],
        "owner_stop": ["stop", "instance", cfg.owner_instance_id, "--raw"],
        "workload_ready_slo_seconds": cfg.reclaim_slo_seconds,
        "automatic_return_timeout_seconds": cfg.auto_return_seconds,
        "self_test_attestation": {
            "passed_at": cfg.self_test_passed_at,
            "maximum_age_seconds_at_preflight": SELF_TEST_MAX_AGE_SECONDS,
        },
        "controlled_clients_destroyed": False,
        "host_job_or_create_job": False,
        "evidence_callback_contracts": {
            "client": {
                "required": [
                    "instance_id",
                    "label",
                    "running=true",
                    "gpu_uuids[1]",
                    "checkpoint.sequence",
                    "checkpoint.digest",
                    "nonempty last_completed_task",
                ],
                "every_periodic_sample": (
                    "checkpoint sequence advances and GPU identity remains stable"
                ),
                "after_return_also_requires": "resumed_from_digest == pre-handoff digest",
            },
            "owner": {
                "required": [
                    "owner_instance_id",
                    "machine_id",
                    "label",
                    "ready",
                    "gpu_count=4",
                    "gpu_uuids[4]",
                    "checkpoint.sequence",
                    "checkpoint.digest",
                ]
            },
            "host_telemetry": {
                "operator_vetted": True,
                "required_phases": (
                    "preflight, every five-minute phase sample, every handoff before/immediate/"
                    "two-hour-delayed, and final"
                ),
                "covers": (
                    "daemon, exact GPUs, thermal/power/throttle/ECC/Xid, storage, network, ports, "
                    "driver/CUDA/kernel/Ubuntu/Secure Boot/SSH/CPU/AVX/public IPv4/VM choice"
                ),
            },
            "host_contracts": {
                "operator_vetted": True,
                "required_phases": (
                    "preflight, every five-minute qualification/research sample, immediately "
                    "before every handoff, and final"
                ),
                "asserts": "four exact controlled bids and no outside on-demand/reserved work",
            },
            "billing": {
                "operator_vetted": True,
                "required_views": (
                    "owner cumulative charges, controlled-client cumulative charges, "
                    "and host cumulative earnings"
                ),
                "required_components": list(BILLING_COMPONENTS),
                "samples": "baseline immediately before the pilot clock and final",
            },
        },
        "cleanup_contract": {
            "controller_safety_cleanup": (
                "unlist, prove offer absence, stop exact owner, then wait boundedly for all four "
                "controlled clients after any owner-start attempt"
            ),
            "full_pilot_cleanup_complete": False,
            "reason": "reusable precreated owner and controlled clients are retained",
        },
    }


def parse_args(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--machine-id", required=True)
    parser.add_argument("--owner-instance-id", required=True)
    parser.add_argument("--owner-label", required=True)
    parser.add_argument(
        "--client",
        action="append",
        type=parse_client_spec,
        required=True,
        help="repeat exact INSTANCE_ID:LABEL; the four-GPU pilot requires four",
    )
    parser.add_argument("--expected-client-count", type=int, default=4)
    parser.add_argument("--host-cli", default="vastai")
    parser.add_argument("--client-cli", required=True)
    parser.add_argument("--client-evidence-command", required=True)
    parser.add_argument("--owner-evidence-command", required=True)
    parser.add_argument("--host-telemetry-command", required=True)
    parser.add_argument("--host-contract-evidence-command", required=True)
    parser.add_argument("--owner-charges-command", required=True)
    parser.add_argument("--client-charges-command", required=True)
    parser.add_argument("--host-earnings-command", required=True)
    parser.add_argument(
        "--self-test-passed-at",
        required=True,
        help="recent timezone-aware ISO timestamp for an ordinary Self-Test pass",
    )
    parser.add_argument("--original-reliability-baseline", type=float, required=True)
    parser.add_argument(
        "--handoff-cycles",
        type=int,
        choices=(MAX_HANDOFFS,),
        default=MAX_HANDOFFS,
        help="fixed at three for this named 24-hour pilot",
    )
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--owner-dwell-seconds", type=int, default=120)
    parser.add_argument("--reclaim-slo-seconds", type=int, default=MAX_RECLAIM_SECONDS)
    parser.add_argument("--owner-stop-timeout-seconds", type=int, default=120)
    parser.add_argument("--auto-return-seconds", type=int, default=AUTO_RETURN_SECONDS)
    parser.add_argument("--callback-timeout-seconds", type=int, default=30)
    parser.add_argument("--contracts-reviewed", action="store_true")
    parser.add_argument("--apply", action="store_true")
    values = vars(parser.parse_args(argv))
    values["clients"] = tuple(values["client"])
    del values["client"]
    return Config(**values)


def _install_signal_handlers() -> None:
    def interrupted(*_args: Any) -> None:
        raise KeyboardInterrupt()

    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), interrupted)


def run_locked(cfg: Config, root: Path) -> int:
    run_dir = root / "controlled-24h-pilots" / dt.datetime.now(dt.timezone.utc).strftime(
        "%Y%m%dT%H%M%S.%fZ"
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        run_dir.chmod(0o700)
    except OSError:
        pass
    atomic_json(run_dir / "config.json", dataclasses.asdict(cfg))
    atomic_json(run_dir / "plan.json", build_plan(cfg))
    host = Cli(cfg.host_cli, "host/owner")
    client = Cli(cfg.client_cli, "controlled client")
    if Path(host.executable).resolve() == Path(client.executable).resolve():
        raise CycleError("host and client must use distinct pre-authenticated CLI executables")
    evidence = EvidenceCommands(cfg)
    pilot = Pilot(cfg, host, client, evidence, root, run_dir)
    pilot.preflight()
    if not cfg.apply:
        print(
            "DRY RUN passed exact preflight; the controller requested no Vast mutation. "
            f"Private plan: {run_dir / 'plan.json'}"
        )
        return 0
    if not sys.stdin.isatty():
        raise CycleError("refusing the 24-hour pilot without an interactive terminal")
    clients = ",".join(item.instance_id for item in cfg.clients)
    expected = (
        f"RUN 24H MACHINE {cfg.machine_id} OWNER {cfg.owner_instance_id} CLIENTS {clients}"
    )
    if input(f"Type {expected}: ") != expected:
        raise CycleError("24-hour pilot confirmation did not match")
    boundary = f"DISABLE HOLD AT 12H FOR {cfg.machine_id}"
    if input(f"Type {boundary}: ") != boundary:
        raise CycleError("qualification HOLD boundary confirmation did not match")
    stop = f"STOP OWNER {cfg.owner_instance_id}"
    if input(f"Type {stop}: ") != stop:
        raise CycleError("owner cleanup confirmation did not match")
    pilot.owner_stop_authorized = True
    pilot.pin_apply_horizon()
    _install_signal_handlers()
    error: str | None = None
    result: dict[str, Any] | None = None
    try:
        result = pilot.run()
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    finally:
        pilot.cleanup()
    payload = result or {
        "experimental": True,
        "production_ready": False,
        "cycle_error": error,
        "completed_handoffs": len(pilot.cycles),
        "owner_workloads_verification_safe": False,
        "host_job_or_create_job": False,
        "host_telemetry_complete": False,
        "host_contract_evidence_complete": False,
        "periodic_evidence_complete": False,
        "client_evidence_complete": False,
        "billing_evidence_complete": False,
    }
    # The reusable owner is deliberately retained under the repository's
    # precreated-instance rule, so the document's destructive final cleanup is
    # incomplete even when all safety recovery actions succeed.
    payload["cleanup_complete"] = False
    payload["controller_safety_cleanup_complete"] = not pilot.cleanup_errors
    payload["full_pilot_cleanup_complete"] = False
    payload["manual_exact_id_cleanup_required"] = True
    payload["cleanup_errors"] = pilot.cleanup_errors
    payload["cycle_error"] = error
    technical_run_complete = bool(
        error is None
        and not pilot.cleanup_errors
        and result
        and cfg.handoff_cycles == MAX_HANDOFFS
        and result["completed_handoffs"] == MAX_HANDOFFS
        and set(result["two_hour_delayed_cycles"]) == set(range(1, MAX_HANDOFFS + 1))
        and result["periodic_evidence_complete"] is True
        and result["client_evidence_complete"] is True
        and result["host_telemetry_complete"] is True
        and result["host_contract_evidence_complete"] is True
        and result["billing_evidence_complete"] is True
    )
    payload["technical_run_complete"] = technical_run_complete
    # Return attention-required until an exact-ID cleanup procedure has
    # reconciled the retained records; never imply full pilot completion.
    atomic_json(run_dir / "result.json", payload)
    print(f"Private experimental result: {run_dir / 'result.json'}")
    return 1


def main(argv: list[str] | None = None) -> int:
    project = Path(__file__).resolve().parents[1]
    cfg = parse_args(argv)
    validate_config(cfg)
    root = resolve_state_root(project)
    lock = root / "controlled-24h-pilot.lock"
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise CycleError(f"another controlled 24-hour pilot may be active: {lock}") from exc
    try:
        return run_locked(cfg, root)
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CycleError, QualificationGuardError, KeyboardInterrupt) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
