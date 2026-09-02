#!/usr/bin/env python3
"""Read-only Vast host qualification observer and local owner-workload hold.

Qualification mode records current machine prerequisites and their trend while
placing a local marker under ``VAST_STATE_DIR``.  Owner-workload helpers import
that marker check and refuse to mutate an owner workload while it is active.

The observer never changes Vast state.  Meeting the observable prerequisites
does not guarantee verification, and disabling qualification mode never means
that personal owner workloads are safe for verification.  Vast's current host
documentation says personal workloads can fail verification and directs host
work to Create Job.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Iterator


SCHEMA = 1
CLI_TIMEOUT_SECONDS = 45.0
SAFE_STOPPED_ACTUAL = {"created", "exited", "stopped"}
VERIFICATION_STAGES_URL = "https://docs.vast.ai/host/verification-stages"
UNDERSTANDING_VERIFICATION_URL = "https://docs.vast.ai/host/understanding-verification"
SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|machineapikey|token|password|credential|secret|ssh[_-]?key)", re.I
)
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)((?:api[_-]?key|machineapikey|token|password|credential|secret)"
    r"\s*[:=]\s*['\"]?)[^'\",\s]+"
)
TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_-])(?<!sha256:)[A-Za-z0-9_-]{40,}(?![A-Za-z0-9_-])")
SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,79}$")
QUALIFICATION_INTERLOCK_NAME = "qualification-owner-mutation.lock"
QUALIFICATION_INTERLOCK_TIMEOUT_ENV = "VAST_QUALIFICATION_INTERLOCK_TIMEOUT_SECONDS"
DEFAULT_QUALIFICATION_INTERLOCK_TIMEOUT_SECONDS = 60
MAX_QUALIFICATION_INTERLOCK_TIMEOUT_SECONDS = 300
QUALIFICATION_INTERLOCK_POLL_SECONDS = 0.1


class QualificationGuardError(RuntimeError):
    """A fail-closed qualification observation or marker error."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _redact_text(value: str) -> str:
    return TOKEN_RE.sub("<redacted-token>", SENSITIVE_TEXT_RE.sub(r"\1<redacted>", value))


def redact_evidence(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, str):
        if key == "label" and SAFE_LABEL_RE.fullmatch(value):
            return value
        return _redact_text(value)
    if isinstance(value, list):
        return [redact_evidence(item, key=key) for item in value]
    if isinstance(value, tuple):
        return [redact_evidence(item, key=key) for item in value]
    if isinstance(value, dict):
        return {
            str(item_key): (
                "<redacted>"
                if SENSITIVE_KEY_RE.search(str(item_key))
                else redact_evidence(item, key=str(item_key))
            )
            for item_key, item in value.items()
        }
    return value


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(redact_evidence(value), handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def qualification_marker_path(root: Path) -> Path:
    return Path(root) / "qualification-mode.json"


def qualification_interlock_path(root: Path) -> Path:
    return Path(root) / QUALIFICATION_INTERLOCK_NAME


def _qualification_interlock_timeout() -> int:
    raw = os.environ.get(
        QUALIFICATION_INTERLOCK_TIMEOUT_ENV,
        str(DEFAULT_QUALIFICATION_INTERLOCK_TIMEOUT_SECONDS),
    )
    if (
        re.fullmatch(r"(?:0|[1-9][0-9]*)", raw) is None
        or int(raw) > MAX_QUALIFICATION_INTERLOCK_TIMEOUT_SECONDS
    ):
        raise QualificationGuardError(
            f"{QUALIFICATION_INTERLOCK_TIMEOUT_ENV} must be an integer from 0 to "
            f"{MAX_QUALIFICATION_INTERLOCK_TIMEOUT_SECONDS}"
        )
    return int(raw)


def _remove_owned_interlock(lock: Path, token: str) -> None:
    token_path = lock / "owner-token"
    metadata_path = lock / "owner.json"
    try:
        observed = token_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise QualificationGuardError(
            f"qualification/owner interlock ownership became unreadable at {lock}; "
            "the lock was retained for manual investigation"
        ) from exc
    if observed != token:
        raise QualificationGuardError(
            f"qualification/owner interlock ownership changed at {lock}; "
            "the lock was retained for manual investigation"
        )
    try:
        metadata_path.unlink(missing_ok=True)
        token_path.unlink()
        lock.rmdir()
    except OSError as exc:
        raise QualificationGuardError(
            f"qualification/owner interlock could not be released cleanly at {lock}; "
            "the remaining lock must be investigated and is never cleared by age"
        ) from exc


@contextmanager
def qualification_owner_mutation_interlock(
    root: Path,
    *,
    action: str,
    timeout_seconds: int | None = None,
) -> Iterator[None]:
    """Serialize qualification marker transitions with final owner mutations.

    Atomic directory creation is shared with the Bash reclaim path.  Contention
    waits for a bounded interval.  An abandoned directory is never removed on
    the basis of age or an untrusted PID; it remains a fail-closed operator
    recovery condition.
    """

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    timeout = (
        _qualification_interlock_timeout() if timeout_seconds is None else timeout_seconds
    )
    if (
        type(timeout) is not int
        or timeout < 0
        or timeout > MAX_QUALIFICATION_INTERLOCK_TIMEOUT_SECONDS
    ):
        raise QualificationGuardError(
            "qualification/owner interlock timeout must be an integer from 0 to "
            f"{MAX_QUALIFICATION_INTERLOCK_TIMEOUT_SECONDS}"
        )
    lock = qualification_interlock_path(root)
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock.mkdir(mode=0o700)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise QualificationGuardError(
                    f"timed out waiting for qualification/owner interlock at {lock} while "
                    f"trying to {action}; the existing lock was retained and must never be "
                    "cleared merely because it is old"
                )
            time.sleep(QUALIFICATION_INTERLOCK_POLL_SECONDS)
        except OSError as exc:
            raise QualificationGuardError(
                f"could not acquire qualification/owner interlock at {lock} while trying "
                f"to {action}"
            ) from exc

    token = uuid.uuid4().hex
    token_path = lock / "owner-token"
    acquired_at = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        with token_path.open("x", encoding="utf-8") as handle:
            handle.write(token + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            token_path.chmod(0o600)
        except OSError:
            pass
        atomic_json(
            lock / "owner.json",
            {
                "schema": 1,
                "pid": os.getpid(),
                "action": action,
                "acquired_at": acquired_at,
                "implementation": "python",
                "automatic_stale_removal": False,
            },
        )
    except BaseException:
        # This process created the directory and no caller has entered the
        # critical section yet, so it may clean up its own incomplete acquire.
        try:
            (lock / "owner.json").unlink(missing_ok=True)
            token_path.unlink(missing_ok=True)
            lock.rmdir()
        except OSError:
            pass
        raise

    body_error: BaseException | None = None
    try:
        yield
    except BaseException as exc:
        body_error = exc
        raise
    finally:
        try:
            _remove_owned_interlock(lock, token)
        except QualificationGuardError as release_error:
            if body_error is None:
                raise
            raise release_error from body_error


def _strict_marker(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationGuardError(
            f"qualification marker exists but is unreadable or malformed: {path}; refusing mutation"
        ) from exc
    if not isinstance(value, dict):
        raise QualificationGuardError(
            f"qualification marker has an invalid shape: {path}; refusing mutation"
        )
    if (
        type(value.get("schema")) is not int
        or value.get("schema") != SCHEMA
        or value.get("active") is not True
    ):
        raise QualificationGuardError(
            f"qualification marker has unknown state: {path}; refusing mutation"
        )
    machine_id = str(value.get("machine_id", ""))
    if not machine_id.isdigit() or int(machine_id) <= 0:
        raise QualificationGuardError(
            f"qualification marker has no valid machine identity: {path}; refusing mutation"
        )
    return value


def require_qualification_mode_inactive(
    root: Path,
    *,
    machine_id: str | None = None,
    action: str = "owner workload mutation",
) -> None:
    """Refuse an owner mutation whenever the external qualification hold exists.

    A malformed marker also blocks.  A marker for another machine is treated as
    an unresolved state-root mismatch instead of being ignored.
    """

    path = qualification_marker_path(root)
    if not path.exists():
        return
    marker = _strict_marker(path)
    marked_machine = str(marker["machine_id"])
    if machine_id is not None and marked_machine != str(machine_id):
        raise QualificationGuardError(
            f"active qualification marker is for machine {marked_machine}, not {machine_id}; "
            f"refusing {action} until the state-root mismatch is reconciled"
        )
    raise QualificationGuardError(
        f"qualification mode is active for machine {marked_machine}; refusing {action}. "
        "Sample or explicitly disable qualification mode first. Disabling is not evidence that "
        "personal owner workloads are verification-safe."
    )


def resolve_state_root(project: Path) -> Path:
    configured = os.environ.get("VAST_STATE_DIR")
    root = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".local/state/vast-host-golden-path"
    )
    resolved = root.resolve()
    project_resolved = project.resolve()
    if resolved == project_resolved or project_resolved in resolved.parents:
        raise QualificationGuardError("VAST_STATE_DIR must be outside the repository")
    resolved.mkdir(parents=True, exist_ok=True)
    try:
        resolved.chmod(0o700)
    except OSError:
        pass
    return resolved


def _positive_id(value: Any, what: str) -> str:
    if isinstance(value, bool):
        raise QualificationGuardError(f"{what} is not a positive ID")
    rendered = str(value)
    if not rendered.isdigit() or int(rendered) <= 0:
        raise QualificationGuardError(f"{what} is not a positive ID")
    return rendered


def _rows(value: Any, what: str) -> list[dict[str, Any]]:
    if isinstance(value, dict) and isinstance(value.get("instances"), list):
        value = value["instances"]
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise QualificationGuardError(f"{what} must be a JSON object or array of objects")
    return value


def _record_id(record: dict[str, Any]) -> str:
    return str(record.get("id", record.get("instance_id", record.get("contract_id", ""))))


def _machine_id(record: dict[str, Any]) -> str:
    return str(record.get("machine_id", record.get("id", "")))


def exact_machine(value: Any, machine_id: str) -> dict[str, Any]:
    matches = [row for row in _rows(value, "machine response") if _machine_id(row) == machine_id]
    if len(matches) != 1:
        raise QualificationGuardError(
            f"machine response did not contain exactly one record for machine {machine_id}"
        )
    return matches[0]


def parse_reports_output(stdout: str) -> list[dict[str, Any]]:
    text = stdout.strip()
    if text.startswith("reports:"):
        text = text[len("reports:") :].strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise QualificationGuardError("reports command returned malformed JSON") from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise QualificationGuardError("reports response must be an exact JSON array of objects")
    return value


class ReadOnlyHostCli:
    """A pre-authenticated host CLI wrapper with a strict read-only allowlist."""

    def __init__(self, executable: str) -> None:
        resolved = shutil.which(executable)
        if not resolved:
            raise QualificationGuardError(f"host CLI executable not found: {executable}")
        self.executable = str(Path(resolved).resolve())

    @staticmethod
    def _validate(args: list[str]) -> None:
        allowed = (
            len(args) == 4
            and args[0:2] == ["show", "machine"]
            and args[2].isdigit()
            and args[3] == "--raw"
        ) or args == ["show", "instances", "--raw"] or (
            len(args) == 3
            and args[0] == "reports"
            and args[1].isdigit()
            and args[2] == "--raw"
        )
        if not allowed:
            raise QualificationGuardError(
                f"verification guard rejected non-read-only CLI command: {' '.join(args[:2])}"
            )
        if any("api_key" in arg.lower() or "api-key" in arg.lower() for arg in args):
            raise QualificationGuardError("API keys must remain inside the CLI wrapper")

    def run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        self._validate(args)
        result = subprocess.run(
            [self.executable, *args],
            text=True,
            capture_output=True,
            timeout=CLI_TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode != 0:
            raise QualificationGuardError(
                f"host CLI read failed ({' '.join(args[:3])}): {_redact_text(result.stderr.strip())}"
            )
        return result

    def json(self, args: list[str]) -> Any:
        result = self.run(args)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise QualificationGuardError(
                f"host CLI returned non-JSON for {' '.join(args[:3])}"
            ) from exc


def _finite_number(record: dict[str, Any], aliases: Iterable[str]) -> tuple[float | None, str | None]:
    for field in aliases:
        if field not in record or record[field] in (None, ""):
            continue
        raw = record[field]
        if isinstance(raw, bool):
            return None, field
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None, field
        if not math.isfinite(value):
            return None, field
        return value, field
    return None, None


def _check(
    *,
    actual: Any,
    source: str | None,
    requirement: str,
    passed: bool | None,
    official: bool = True,
    note: str | None = None,
) -> dict[str, Any]:
    result = {
        "status": "unknown" if passed is None else ("pass" if passed else "fail"),
        "pass": passed,
        "actual": actual,
        "source": source,
        "requirement": requirement,
        "official_requirement": official,
    }
    if note:
        result["note"] = note
    return result


def _numeric_check(
    machine: dict[str, Any],
    aliases: tuple[str, ...],
    *,
    requirement: str,
    predicate: Any,
) -> dict[str, Any]:
    value, source = _finite_number(machine, aliases)
    if value is None:
        return _check(
            actual=machine.get(source) if source else None,
            source=source,
            requirement=requirement,
            passed=None,
        )
    return _check(actual=value, source=source, requirement=requirement, passed=bool(predicate(value)))


def _health_is_clear(machine: dict[str, Any]) -> tuple[bool | None, dict[str, Any]]:
    fields = {
        "error_description": machine.get("error_description"),
        "vm_error_level": machine.get("vm_error_level"),
        "vm_error_msg": machine.get("vm_error_msg"),
    }
    if not any(field in machine for field in fields):
        return None, fields
    if not all(field in machine for field in fields):
        return None, fields
    description = str(fields["error_description"] or "").strip()
    message = str(fields["vm_error_msg"] or "").strip()
    raw_level = fields["vm_error_level"]
    if isinstance(raw_level, bool):
        return False, fields
    try:
        level = float(raw_level or 0)
    except (TypeError, ValueError):
        return False, fields
    return level == 0 and not description and not message, fields


def _ubuntu_major(value: Any) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip().lower().replace("ubuntu", "").strip()
    match = re.match(r"^(22|24)(?:\.04)?(?:\D|$)", text)
    return match.group(1) if match else None


def _previous_reliability(prior_samples: list[dict[str, Any]]) -> float | None:
    for sample in reversed(prior_samples):
        try:
            value = sample["checks"]["reliability"]["actual"]
        except (KeyError, TypeError):
            continue
        if isinstance(value, bool):
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return value
    return None


def evaluate_verification(
    machine: dict[str, Any],
    reports: list[dict[str, Any]],
    prior_samples: list[dict[str, Any]] | None = None,
    *,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Evaluate only what current Vast machine/report output can substantiate."""

    if not isinstance(machine, dict):
        raise QualificationGuardError("machine evidence must be a JSON object")
    if not isinstance(reports, list) or any(not isinstance(item, dict) for item in reports):
        raise QualificationGuardError("report evidence must be a JSON array of objects")
    history = list(prior_samples or [])
    checks: dict[str, dict[str, Any]] = {}

    num_gpus, gpu_count_source = _finite_number(machine, ("num_gpus",))
    valid_gpu_count = num_gpus is not None and num_gpus >= 1 and num_gpus.is_integer()
    checks["gpu_count_observable"] = _check(
        actual=num_gpus,
        source=gpu_count_source,
        requirement="positive integer GPU count so per-GPU requirements can be assessed",
        passed=valid_gpu_count if num_gpus is not None else None,
        official=False,
    )
    gpu_count = int(num_gpus) if valid_gpu_count else None

    checks["reliability"] = _numeric_check(
        machine,
        ("reliability2", "reliability"),
        requirement="strictly greater than 0.90",
        predicate=lambda value: 0 <= value <= 1 and value > 0.90,
    )
    checks["cuda"] = _numeric_check(
        machine,
        ("cuda_max_good", "cuda_max"),
        requirement="CUDA version at least 11.8",
        predicate=lambda value: value >= 11.8,
    )
    checks["vram_per_gpu"] = _numeric_check(
        machine,
        ("gpu_ram", "gpu_ram_mib"),
        requirement="more than 7 GiB VRAM per GPU (CLI field interpreted as MiB)",
        predicate=lambda value: value / 1024 > 7,
    )
    checks["pcie_bandwidth_per_gpu"] = _numeric_check(
        machine,
        ("pcie_bw",),
        requirement="strictly greater than 2.85 GiB/s per GPU",
        predicate=lambda value: value > 2.85,
    )

    cpu_cores, cpu_source = _finite_number(machine, ("cpu_cores", "cpu_cores_effective"))
    cpu_pass = None if cpu_cores is None or gpu_count is None else cpu_cores >= 2 * gpu_count
    checks["cpu_cores"] = _check(
        actual=cpu_cores,
        source=cpu_source,
        requirement="at least 2 CPU cores per GPU",
        passed=cpu_pass,
        note=(
            "cpu_cores_effective may be a CLI effective/vCPU field; confirm physical-core mapping manually"
            if cpu_source == "cpu_cores_effective"
            else None
        ),
    )

    cpu_ram, ram_source = _finite_number(machine, ("cpu_ram", "system_ram"))
    gpu_ram, _ = _finite_number(machine, ("gpu_ram", "gpu_ram_mib"))
    ram_pass = (
        None
        if cpu_ram is None or gpu_ram is None or gpu_count is None
        else cpu_ram >= 0.95 * gpu_ram * gpu_count
    )
    checks["system_ram"] = _check(
        actual=cpu_ram,
        source=ram_source,
        requirement="system RAM at least 95% of aggregate GPU VRAM (same CLI units)",
        passed=ram_pass,
    )
    checks["network_download"] = _numeric_check(
        machine,
        ("inet_down", "inet_down_speed"),
        requirement="at least 500 Mbps download",
        predicate=lambda value: value >= 500,
    )
    checks["network_upload"] = _numeric_check(
        machine,
        ("inet_up", "inet_up_speed"),
        requirement="at least 500 Mbps upload",
        predicate=lambda value: value >= 500,
    )

    ports, port_source = _finite_number(machine, ("direct_port_count", "ports"))
    port_pass = None if ports is None or gpu_count is None else ports >= 5 * gpu_count
    checks["direct_ports"] = _check(
        actual=ports,
        source=port_source,
        requirement="at least 5 direct ports per GPU",
        passed=port_pass,
        note=(
            None
            if ports is None or gpu_count is None
            else f"100 per GPU is recommended; observed recommendation met={ports >= 100 * gpu_count}"
        ),
    )

    ubuntu_field = next(
        (field for field in ("ubuntu_version", "os_version") if field in machine), None
    )
    ubuntu_value = machine.get(ubuntu_field) if ubuntu_field else None
    ubuntu_major = _ubuntu_major(ubuntu_value)
    checks["ubuntu_version"] = _check(
        actual=ubuntu_value,
        source=ubuntu_field,
        requirement="Ubuntu 22.04 or 24.04",
        passed=None if ubuntu_field is None else ubuntu_major in {"22", "24"},
        note="The CLI version field does not prove Server rather than Desktop edition.",
    )
    checks["docker_disk_capacity"] = _numeric_check(
        machine,
        ("disk_space", "disk_total", "storage_total"),
        requirement="at least 200 GB dedicated Docker storage capacity where exposed",
        predicate=lambda value: value >= 200,
    )

    health_clear, health_values = _health_is_clear(machine)
    checks["machine_errors"] = _check(
        actual=health_values,
        source="machine health fields",
        requirement="no current machine/VM errors",
        passed=health_clear,
    )
    checks["reports"] = _check(
        actual=len(reports),
        source="reports MACHINE_ID --raw",
        requirement="no current report records",
        passed=len(reports) == 0,
    )

    prior_reliability = _previous_reliability(history)
    current_reliability = checks["reliability"]["actual"]
    trend_pass: bool | None
    trend_status: str
    if prior_reliability is None or not isinstance(current_reliability, (int, float)):
        trend_pass = None
        trend_status = "insufficient-history"
    elif current_reliability + 1e-12 >= prior_reliability:
        trend_pass = True
        trend_status = "observed-nondecreasing"
    else:
        trend_pass = False
        trend_status = "observed-regression"
    uptime_value, uptime_source = _finite_number(
        machine, ("host_run_time", "uptime", "uptime_seconds")
    )
    checks["steady_uptime_history"] = _check(
        actual={
            "local_sample_count_including_current": len(history) + 1,
            "previous_reliability": prior_reliability,
            "current_reliability": current_reliability,
            "reported_uptime": uptime_value,
            "trend_status": trend_status,
        },
        source=uptime_source or "local qualification sample history",
        requirement=(
            "stable uptime/history; official docs say reliability grows with stable uptime and "
            "typically takes days, but publish no fixed qualification duration"
        ),
        passed=trend_pass,
        official=False,
    )

    raw_verification = machine.get("verification", machine.get("verified", "unknown"))
    if raw_verification is True:
        verification = "verified"
    elif raw_verification is False:
        verification = "unverified"
    else:
        verification = str(raw_verification).strip().lower() or "unknown"
    observable_names = [
        "gpu_count_observable",
        "reliability",
        "cuda",
        "vram_per_gpu",
        "pcie_bandwidth_per_gpu",
        "cpu_cores",
        "system_ram",
        "network_download",
        "network_upload",
        "direct_ports",
        "ubuntu_version",
        "docker_disk_capacity",
        "machine_errors",
        "reports",
    ]
    blockers = [name for name in observable_names if checks[name]["pass"] is not True]
    if trend_pass is not True:
        blockers.append("steady_uptime_history")

    manual_checks = [
        {
            "id": "ssh_keys_only_and_unique",
            "status": "manual",
            "requirement": "SSH keys only and a unique host key; password login disabled",
        },
        {
            "id": "secure_boot_disabled",
            "status": "manual",
            "requirement": "Secure Boot disabled",
        },
        {
            "id": "root_free_space",
            "status": "manual",
            "requirement": "at least 20 GB free on the root filesystem",
        },
        {
            "id": "storage_type_and_layout",
            "status": "manual",
            "requirement": "SSD and a genuinely dedicated Docker drive, not only reported capacity",
        },
        {
            "id": "ubuntu_server_edition",
            "status": "manual",
            "requirement": "Ubuntu Server edition",
        },
        {
            "id": "ordinary_self_test",
            "status": "manual/platform",
            "requirement": "ordinary Vast Self-Test passed without --ignore-requirements",
        },
        {
            "id": "cpu_arch_avx_and_physical_cores",
            "status": "manual",
            "requirement": (
                "supported CPU architecture with AVX and at least 2 physical cores per GPU; "
                "do not infer physical topology from a vCPU count"
            ),
        },
        {
            "id": "identical_supported_gpus",
            "status": "manual",
            "requirement": "all GPUs are identical supported NVIDIA models",
        },
        {
            "id": "driver_and_kernel",
            "status": "manual",
            "requirement": "currently supported NVIDIA driver and latest security-patched LTS kernel",
        },
        {
            "id": "public_ipv4_and_wired_network",
            "status": "manual",
            "requirement": "direct public IPv4 and stable wired Ethernet/fiber, not CGNAT",
        },
        {
            "id": "sustained_uptime",
            "status": "manual/trend",
            "requirement": "target sustained >=99.99% uptime; continue observing over days",
        },
        {
            "id": "vm_support",
            "status": "manual",
            "requirement": "VM support significantly improves verification likelihood",
        },
        {
            "id": "no_hidden_services_or_bottlenecks",
            "status": "manual",
            "requirement": (
                "no hidden background services and no PCIe, thermal, power, CPU, RAM, storage, "
                "or network bottleneck under sustained load"
            ),
        },
    ]

    return {
        "schema": SCHEMA,
        "observed_at": observed_at or utc_now(),
        "machine_id": _machine_id(machine),
        "platform_verification": verification,
        "platform_verified": verification == "verified",
        "checks": checks,
        "manual_checks": manual_checks,
        "observable_prerequisites_pass": not blockers,
        "blockers": blockers,
        "owner_workloads_verification_safe": False,
        "owner_workload_policy": (
            "Use Create Job for host work during qualification. Personal owner workloads can fail "
            "verification according to current official documentation."
        ),
        "qualification_guaranteed": False,
        "sources": [VERIFICATION_STAGES_URL, UNDERSTANDING_VERIFICATION_URL],
    }


def _parse_allowed_owner_specs(values: list[str]) -> list[dict[str, str]]:
    allowed: list[dict[str, str]] = []
    ids: set[str] = set()
    for value in values:
        if ":" not in value:
            raise QualificationGuardError(
                "--allowed-owner-standby must be INSTANCE_ID:LABEL"
            )
        instance_id, label = value.split(":", 1)
        instance_id = _positive_id(instance_id, "allowed owner standby ID")
        if instance_id in ids:
            raise QualificationGuardError("allowed owner standby IDs must be unique")
        if not SAFE_LABEL_RE.fullmatch(label):
            raise QualificationGuardError("allowed owner standby label is invalid")
        ids.add(instance_id)
        allowed.append({"instance_id": instance_id, "label": label})
    return sorted(allowed, key=lambda item: int(item["instance_id"]))


def _validate_allowed_owner_records(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise QualificationGuardError("allowed owner standby list is malformed")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"instance_id", "label"}:
            raise QualificationGuardError("allowed owner standby list is malformed")
        instance_id = _positive_id(item["instance_id"], "allowed owner standby ID")
        label = item["label"]
        if not isinstance(label, str) or not SAFE_LABEL_RE.fullmatch(label):
            raise QualificationGuardError("allowed owner standby label is malformed")
        if instance_id in seen:
            raise QualificationGuardError("allowed owner standby IDs must be unique")
        seen.add(instance_id)
        normalized.append({"instance_id": instance_id, "label": label})
    return sorted(normalized, key=lambda item: int(item["instance_id"]))


def validate_owner_inventory(
    value: Any,
    *,
    machine_id: str,
    machine_gpu_count: int,
    allowed: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Allow only named, exact, safely stopped own-machine OD standbys."""

    target = [
        row for row in _rows(value, "host owner instance response") if _machine_id(row) == machine_id
    ]
    allowed_by_id = {item["instance_id"]: item for item in allowed}
    observed: list[dict[str, Any]] = []
    for record in target:
        instance_id = _positive_id(_record_id(record), "host owner instance ID")
        expected = allowed_by_id.get(instance_id)
        if expected is None:
            raise QualificationGuardError(
                f"unknown personal owner instance {instance_id} exists on machine {machine_id}; "
                "refusing qualification enable/sample"
            )
        actual_status = str(record.get("actual_status", "")).lower()
        intended_status = str(record.get("intended_status", "")).lower()
        cur_state = str(record.get("cur_state", "")).lower()
        try:
            gpu_count = int(record.get("num_gpus"))
        except (TypeError, ValueError):
            gpu_count = -1
        if (
            str(record.get("label", "")) != expected["label"]
            or record.get("is_bid") is not False
            or gpu_count < 1
            or gpu_count > machine_gpu_count
            or actual_status not in SAFE_STOPPED_ACTUAL
            or intended_status != "stopped"
            or cur_state != "stopped"
        ):
            raise QualificationGuardError(
                f"allowed owner standby {instance_id} does not match its exact stopped "
                "on-demand identity; refusing qualification enable/sample"
            )
        observed.append(
            {
                "instance_id": instance_id,
                "label": expected["label"],
                "is_bid": False,
                "num_gpus": gpu_count,
                "stopped_tuple": [actual_status, intended_status, cur_state],
            }
        )
    observed_ids = {item["instance_id"] for item in observed}
    allowed_ids = set(allowed_by_id)
    if observed_ids != allowed_ids:
        missing = sorted(allowed_ids - observed_ids, key=int)
        raise QualificationGuardError(
            "allowed owner standby inventory is incomplete; missing exact IDs: "
            + ", ".join(missing)
        )
    return observed


def _load_samples(root: Path, machine_id: str) -> list[dict[str, Any]]:
    directory = root / "verification-qualification" / f"machine-{machine_id}" / "samples"
    samples: list[dict[str, Any]] = []
    if not directory.exists():
        return samples
    for path in sorted(directory.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise QualificationGuardError(
                f"qualification sample history is unreadable: {path}"
            ) from exc
        if not isinstance(value, dict) or str(value.get("machine_id")) != machine_id:
            raise QualificationGuardError(
                f"qualification sample history has an invalid machine identity: {path}"
            )
        samples.append(value)
    return samples


def _sample_path(root: Path, machine_id: str, observed_at: str) -> Path:
    parsed = dt.datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    stamp = parsed.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return root / "verification-qualification" / f"machine-{machine_id}" / "samples" / f"{stamp}.json"


def _read_observation(
    cli: ReadOnlyHostCli,
    *,
    machine_id: str,
    allowed: list[dict[str, str]],
    root: Path,
    observed_at: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    machine = exact_machine(cli.json(["show", "machine", machine_id, "--raw"]), machine_id)
    reports = parse_reports_output(cli.run(["reports", machine_id, "--raw"]).stdout)
    instances = cli.json(["show", "instances", "--raw"])
    gpu_count_raw, _ = _finite_number(machine, ("num_gpus",))
    if gpu_count_raw is None or gpu_count_raw < 1 or not gpu_count_raw.is_integer():
        raise QualificationGuardError(
            "machine GPU count is missing or invalid; refusing owner inventory assessment"
        )
    allowed_observed = validate_owner_inventory(
        instances,
        machine_id=machine_id,
        machine_gpu_count=int(gpu_count_raw),
        allowed=allowed,
    )
    prior_samples = _load_samples(root, machine_id)
    assessment = evaluate_verification(
        machine,
        reports,
        prior_samples,
        observed_at=observed_at,
    )
    assessment["machine_id"] = machine_id
    assessment["allowed_stopped_owner_standbys_observed"] = allowed_observed
    assessment["vast_mutations_performed"] = 0
    sample_path = _sample_path(root, machine_id, observed_at)
    if sample_path.exists():
        raise QualificationGuardError(f"qualification sample path already exists: {sample_path}")
    atomic_json(sample_path, assessment)
    return assessment, {"sample_path": str(sample_path), "prior_sample_count": len(prior_samples)}


def _update_marker_with_sample(
    root: Path,
    marker: dict[str, Any],
    assessment: dict[str, Any],
    sample_info: dict[str, Any],
) -> None:
    previous = marker.get("reliability_trend", [])
    if not isinstance(previous, list):
        raise QualificationGuardError("qualification marker trend is malformed")
    reliability = assessment["checks"]["reliability"]["actual"]
    trend = [*previous, {"observed_at": assessment["observed_at"], "reliability": reliability}]
    marker.update(
        {
            "latest_sample_at": assessment["observed_at"],
            "latest_sample_path": sample_info["sample_path"],
            "sample_count": sample_info["prior_sample_count"] + 1,
            "latest_observable_prerequisites_pass": assessment[
                "observable_prerequisites_pass"
            ],
            "latest_platform_verification": assessment["platform_verification"],
            "reliability_trend": trend[-128:],
            "owner_workloads_verification_safe": False,
        }
    )
    atomic_json(qualification_marker_path(root), marker)


def _record_refusal(root: Path, machine_id: str, operation: str, error: Exception) -> None:
    directory = root / "verification-qualification" / f"machine-{machine_id}" / "refusals"
    observed_at = utc_now()
    stamp = dt.datetime.fromisoformat(observed_at).strftime("%Y%m%dT%H%M%S.%fZ")
    atomic_json(
        directory / f"{stamp}.json",
        {
            "schema": SCHEMA,
            "observed_at": observed_at,
            "machine_id": machine_id,
            "operation": operation,
            "refused": True,
            "error": str(error),
            "vast_mutations_performed": 0,
        },
    )


def enable_qualification_mode(
    root: Path,
    cli: ReadOnlyHostCli,
    *,
    machine_id: str,
    allowed: list[dict[str, str]],
) -> dict[str, Any]:
    with qualification_owner_mutation_interlock(
        root,
        action=f"enable qualification mode for machine {machine_id}",
    ):
        allowed = _validate_allowed_owner_records(allowed)
        marker_path = qualification_marker_path(root)
        if marker_path.exists():
            _strict_marker(marker_path)
            raise QualificationGuardError("qualification mode is already active")
        observed_at = utc_now()
        marker = {
            "schema": SCHEMA,
            "active": True,
            "machine_id": machine_id,
            "enabled_at": observed_at,
            "allowed_stopped_owner_standbys": allowed,
            "owner_workloads_verification_safe": False,
            "disable_semantics": (
                "Removing this local hold does not establish that personal owner workloads are "
                "verification-safe."
            ),
            "sources": [VERIFICATION_STAGES_URL, UNDERSTANDING_VERIFICATION_URL],
            "status": "observation-pending",
            "sample_count": 0,
            "reliability_trend": [],
        }
        # Install the local hold while holding the cross-process interlock and
        # before every remote observation.  Inventory failure therefore leaves
        # a conspicuous active hold rather than reopening an owner mutation.
        atomic_json(marker_path, marker)
        assessment, sample_info = _read_observation(
            cli,
            machine_id=machine_id,
            allowed=allowed,
            root=root,
            observed_at=observed_at,
        )
        marker["status"] = "active"
        _update_marker_with_sample(root, marker, assessment, sample_info)
        return assessment


def sample_qualification_mode(
    root: Path,
    cli: ReadOnlyHostCli,
    *,
    machine_id: str,
) -> dict[str, Any]:
    with qualification_owner_mutation_interlock(
        root,
        action=f"sample qualification mode for machine {machine_id}",
    ):
        marker = _strict_marker(qualification_marker_path(root))
        if str(marker["machine_id"]) != machine_id:
            raise QualificationGuardError(
                "active qualification marker machine does not match --machine-id"
            )
        allowed = _validate_allowed_owner_records(
            marker.get("allowed_stopped_owner_standbys")
        )
        observed_at = utc_now()
        assessment, sample_info = _read_observation(
            cli,
            machine_id=machine_id,
            allowed=allowed,
            root=root,
            observed_at=observed_at,
        )
        _update_marker_with_sample(root, marker, assessment, sample_info)
        return assessment


def disable_qualification_mode(root: Path, *, machine_id: str) -> dict[str, Any]:
    with qualification_owner_mutation_interlock(
        root,
        action=f"disable qualification mode for machine {machine_id}",
    ):
        marker_path = qualification_marker_path(root)
        marker = _strict_marker(marker_path)
        if str(marker["machine_id"]) != machine_id:
            raise QualificationGuardError(
                "active qualification marker machine does not match --machine-id"
            )
        disabled_at = utc_now()
        archive = dict(marker)
        archive.update(
            {
                "active": False,
                "disabled_at": disabled_at,
                "owner_workloads_verification_safe": False,
                "result": (
                    "qualification observation stopped; this does not approve personal owner "
                    "workloads or guarantee continued verification"
                ),
            }
        )
        stamp = dt.datetime.fromisoformat(disabled_at).strftime("%Y%m%dT%H%M%S.%fZ")
        archive_path = (
            root
            / "verification-qualification"
            / f"machine-{machine_id}"
            / "disabled"
            / f"{stamp}.json"
        )
        atomic_json(archive_path, archive)
        try:
            marker_path.unlink()
        except OSError as exc:
            raise QualificationGuardError(
                "qualification archive was written but the active hold could not be removed: "
                f"{marker_path}"
            ) from exc
        return {
            "machine_id": machine_id,
            "disabled_at": disabled_at,
            "archive_path": str(archive_path),
            "owner_workloads_verification_safe": False,
            "vast_mutations_performed": 0,
        }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument(
        "--enable-qualification-mode",
        action="store_true",
        help="create the local owner-workload hold, then take one read-only sample",
    )
    operation.add_argument(
        "--sample",
        action="store_true",
        help="append a read-only sample while qualification mode remains active",
    )
    operation.add_argument(
        "--disable-qualification-mode",
        action="store_true",
        help="remove the local hold; this never implies owner workloads are verification-safe",
    )
    parser.add_argument("--machine-id", required=True)
    parser.add_argument("--host-cli", default="vastai", help="pre-authenticated host CLI wrapper")
    parser.add_argument(
        "--allowed-owner-standby",
        action="append",
        default=[],
        metavar="INSTANCE_ID:LABEL",
        help=(
            "permit only this exact safely stopped own-machine on-demand standby; repeat as needed "
            "when enabling"
        ),
    )
    args = parser.parse_args(argv)
    try:
        _positive_id(args.machine_id, "machine ID")
    except QualificationGuardError as exc:
        parser.error(str(exc))
    if not args.enable_qualification_mode and args.allowed_owner_standby:
        parser.error("--allowed-owner-standby is valid only with --enable-qualification-mode")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project = Path(__file__).resolve().parents[1]
    try:
        root = resolve_state_root(project)
    except QualificationGuardError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    operation = (
        "enable"
        if args.enable_qualification_mode
        else ("sample" if args.sample else "disable")
    )
    try:
        if args.disable_qualification_mode:
            result = disable_qualification_mode(root, machine_id=args.machine_id)
        else:
            cli = ReadOnlyHostCli(args.host_cli)
            if args.enable_qualification_mode:
                result = enable_qualification_mode(
                    root,
                    cli,
                    machine_id=args.machine_id,
                    allowed=_parse_allowed_owner_specs(args.allowed_owner_standby),
                )
            else:
                result = sample_qualification_mode(root, cli, machine_id=args.machine_id)
        print(json.dumps(redact_evidence(result), indent=2, sort_keys=True, allow_nan=False))
        return 0
    except QualificationGuardError as exc:
        try:
            _record_refusal(root, args.machine_id, operation, exc)
        except Exception:  # noqa: BLE001 - never hide the primary fail-closed error
            pass
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
