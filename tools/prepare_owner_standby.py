#!/usr/bin/env python3
"""Prepare one reusable own-machine on-demand standby while a host is vacant.

The tool temporarily publishes only an exact full-machine offer at deliberately
unattractive prices, creates one owner on-demand instance, and unlists in a
``finally`` block.  It never retries ``create instance`` and has no destroy
path.  Success requires exact owner identity, a proved running tuple, one stop
call, and a fail-closed stopped tuple.  Private redacted evidence is written
under ``VAST_STATE_DIR`` outside the repository.
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
import time
from pathlib import Path
from typing import Any, Callable

try:
    from tools.verification_guard import (
        QualificationGuardError,
        qualification_owner_mutation_interlock,
        require_qualification_mode_inactive,
    )
except ModuleNotFoundError:  # Direct ``python tools/...`` execution.
    from verification_guard import (  # type: ignore[no-redef]
        QualificationGuardError,
        qualification_owner_mutation_interlock,
        require_qualification_mode_inactive,
    )


SAFE_STOPPED_ACTUAL = {"created", "exited", "stopped"}
RUNNING_TUPLE = ("running", "running", "running")
TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?<!sha256:)[A-Za-z0-9_-]{40,}(?![A-Za-z0-9_-])"
)
SENSITIVE_KEY_RE = re.compile(
    r"(?:api.?key|token|secret|password|credential|jupyter|"
    r"ssh.?(?:key|public.?key)|email|(?:public|external).?ip|ip.?address)",
    re.IGNORECASE,
)
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)((?:['\"])?(?:instance.?api.?key|api.?key|token|secret|password|credential|"
    r"jupyter|ssh.?(?:key|public.?key)|email|(?:public|external).?ip|ip.?address)"
    r"(?:['\"])?\s*[:=]\s*['\"]?)[^'\",}\s]+"
)
SENSITIVE_QUOTED_TEXT_RE = re.compile(
    r"(?i)((?:['\"])?(?:instance.?api.?key|api.?key|token|secret|password|credential|"
    r"jupyter|ssh.?(?:key|public.?key)|email|(?:public|external).?ip|ip.?address)"
    r"(?:['\"])?\s*[:=]\s*)(['\"])[^'\"]*\2"
)
EMAIL_RE = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])")
IPV4_RE = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
PINNED_PYTORCH_IMAGE_RE = re.compile(
    r"^(?:docker\.io/)?pytorch/pytorch:[A-Za-z0-9_.-]*cuda[A-Za-z0-9_.-]*"
    r"@sha256:[0-9a-f]{64}$"
)
SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{7,79}$")
CLI_TIMEOUT_SECONDS = 45.0
GPU_PROBE_SECONDS = 21_600
GPU_PROBE_CHECKPOINT_SECONDS = 15
GPU_PROBE_MATRIX_DIMENSION = 2048
GPU_PROBE_CHECKPOINT_PATH = "/root/sqwish-owner-probe/checkpoint.json"
GPU_PROBE_MAX_CHECKPOINTS = GPU_PROBE_SECONDS // GPU_PROBE_CHECKPOINT_SECONDS
MAX_FIXED_END_SECONDS = 48 * 60 * 60


def owner_probe_contract(gpu_count: int) -> dict[str, Any]:
    """Return the evidence contract configured into the retained standby."""
    return {
        "runner": "torchrun",
        "backend": "nccl",
        "gpu_count": gpu_count,
        "checkpoint_path": GPU_PROBE_CHECKPOINT_PATH,
        "checkpoint_interval_seconds": GPU_PROBE_CHECKPOINT_SECONDS,
        "configured_active_window_seconds": GPU_PROBE_SECONDS,
        "maximum_checkpoint_cycles": GPU_PROBE_MAX_CHECKPOINTS,
        "matrix_dimension": GPU_PROBE_MATRIX_DIMENSION,
        "checkpoint_digest": "sha256-canonical-json-without-digest-member",
        "execution_proved_during_preparation": False,
        "execution_proof_required_during_each_handoff": True,
    }


def owner_command(gpu_count: int) -> str:
    """Build a bounded, checkpointing distributed probe for an exact GPU shape."""
    if gpu_count not in {1, 2, 4, 8}:
        raise StandbyError("owner probe GPU count must be exactly 1, 2, 4, or 8")
    template = """set -euo pipefail
gpu_count="$(nvidia-smi --query-gpu=index --format=csv,noheader | sed '/^[[:space:]]*$/d' | wc -l)"
test "$gpu_count" -eq __GPU_COUNT__
cat > /tmp/sqwish-owner-distributed-probe.py <<'PY'
import datetime as dt
import hashlib
import json
import math
import os
import time
from pathlib import Path

import torch
import torch.distributed as dist


EXPECTED_GPU_COUNT = __GPU_COUNT__
CHECKPOINT_SECONDS = __CHECKPOINT_SECONDS__
MAX_CHECKPOINTS = __MAX_CHECKPOINTS__
MATRIX_DIMENSION = __MATRIX_DIMENSION__
CHECKPOINT_DIRECTORY = Path("/root/sqwish-owner-probe")
CHECKPOINT_PATH = Path("__CHECKPOINT_PATH__")


def digest_for(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def load_sequence():
    if not CHECKPOINT_PATH.exists():
        return 0
    value = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise RuntimeError("existing owner checkpoint has an invalid schema")
    sequence = value.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise RuntimeError("existing owner checkpoint has an invalid sequence")
    recorded_digest = value.get("digest")
    core = {key: item for key, item in value.items() if key != "digest"}
    if recorded_digest != digest_for(core):
        raise RuntimeError("existing owner checkpoint failed its SHA-256 integrity check")
    return sequence


def write_checkpoint(payload):
    CHECKPOINT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    os.chmod(CHECKPOINT_DIRECTORY, 0o700)
    core = dict(payload)
    core["digest"] = digest_for(core)
    temporary = CHECKPOINT_PATH.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        json.dump(core, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, CHECKPOINT_PATH)
    directory_fd = os.open(CHECKPOINT_DIRECTORY, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return core


rank = int(os.environ["RANK"])
local_rank = int(os.environ["LOCAL_RANK"])
world_size = int(os.environ["WORLD_SIZE"])
visible_count = torch.cuda.device_count()
if world_size != EXPECTED_GPU_COUNT or visible_count != EXPECTED_GPU_COUNT:
    raise RuntimeError(
        f"expected exactly {EXPECTED_GPU_COUNT} distributed CUDA workers/devices, "
        f"got world_size={world_size} and visible_count={visible_count}"
    )
if local_rank < 0 or local_rank >= EXPECTED_GPU_COUNT:
    raise RuntimeError(f"invalid local rank {local_rank}")

torch.cuda.set_device(local_rank)
dist.init_process_group(
    backend="nccl",
    timeout=dt.timedelta(seconds=120),
)
try:
    torch.manual_seed(73_000 + rank)
    device = torch.device("cuda", local_rank)
    left = torch.randn(
        (MATRIX_DIMENSION, MATRIX_DIMENSION), device=device, dtype=torch.float16
    )
    right = torch.randn(
        (MATRIX_DIMENSION, MATRIX_DIMENSION), device=device, dtype=torch.float16
    )
    sequence = load_sequence() if rank == 0 else 0
    ready_emitted = False

    for checkpoint_index in range(MAX_CHECKPOINTS):
        cycle_started = time.monotonic()
        product = torch.mm(left, right)
        local_checksum = product.float().mean()
        collective = torch.stack(
            (
                torch.tensor(float(rank + 1), device=device),
                local_checksum,
            )
        )
        dist.all_reduce(collective, op=dist.ReduceOp.SUM)
        torch.cuda.synchronize(device)

        expected_rank_sum = EXPECTED_GPU_COUNT * (EXPECTED_GPU_COUNT + 1) / 2
        rank_sum = float(collective[0].item())
        aggregate_checksum = float(collective[1].item())
        if not math.isclose(rank_sum, expected_rank_sum, rel_tol=0.0, abs_tol=0.001):
            raise RuntimeError("NCCL all-reduce produced an unexpected rank sum")
        if not math.isfinite(aggregate_checksum):
            raise RuntimeError("distributed matrix checksum is not finite")

        if rank == 0:
            sequence += 1
            checkpoint = write_checkpoint(
                {
                    "schema": 1,
                    "sequence": sequence,
                    "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "gpu_count": EXPECTED_GPU_COUNT,
                    "world_size": world_size,
                    "matrix_dimension": MATRIX_DIMENSION,
                    "collective_rank_sum": rank_sum,
                    "aggregate_matrix_checksum": aggregate_checksum,
                }
            )
            event = {
                "event": "owner_standby_ready" if not ready_emitted else "owner_checkpoint",
                "gpu_count": EXPECTED_GPU_COUNT,
                "checkpoint": {
                    "sequence": checkpoint["sequence"],
                    "digest": checkpoint["digest"],
                },
            }
            print(json.dumps(event, sort_keys=True), flush=True)
            ready_emitted = True

        if checkpoint_index + 1 < MAX_CHECKPOINTS:
            elapsed = time.monotonic() - cycle_started
            time.sleep(max(0.0, CHECKPOINT_SECONDS - elapsed))
finally:
    dist.destroy_process_group()
PY

export NCCL_ASYNC_ERROR_HANDLING=1
exec torchrun --standalone --nnodes=1 --nproc-per-node=__GPU_COUNT__ --max-restarts=0 /tmp/sqwish-owner-distributed-probe.py
"""
    return (
        template.replace("__GPU_COUNT__", str(gpu_count))
        .replace("__CHECKPOINT_SECONDS__", str(GPU_PROBE_CHECKPOINT_SECONDS))
        .replace("__MAX_CHECKPOINTS__", str(GPU_PROBE_MAX_CHECKPOINTS))
        .replace("__MATRIX_DIMENSION__", str(GPU_PROBE_MATRIX_DIMENSION))
        .replace("__CHECKPOINT_PATH__", GPU_PROBE_CHECKPOINT_PATH)
    )


# Backward-compatible name for the recorded two-A100 pilot and its fixtures.
OWNER_COMMAND = owner_command(2)


class StandbyError(RuntimeError):
    pass


class UnknownContractError(StandbyError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def positive_id(value: Any, what: str) -> str:
    if isinstance(value, bool):
        raise StandbyError(f"{what} is not a positive ID")
    text = str(value)
    if not text.isdigit() or int(text) <= 0:
        raise StandbyError(f"{what} is not a positive ID")
    return text


def identifier(record: dict[str, Any]) -> str:
    for field in ("id", "contract_id", "instance_id"):
        if field in record:
            return str(record[field])
    return ""


def machine_identifier(record: dict[str, Any]) -> str:
    return str(record.get("machine_id", record.get("id", "")))


def strict_rows(value: Any, what: str) -> list[dict[str, Any]]:
    if isinstance(value, dict) and isinstance(value.get("instances"), list):
        value = value["instances"]
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise StandbyError(f"{what} must be an exact JSON array of objects")
    return value


def exact_machine(value: Any, machine_id: str) -> dict[str, Any]:
    rows = [value] if isinstance(value, dict) and "instances" not in value else strict_rows(value, "machine response")
    matches = [row for row in rows if machine_identifier(row) == machine_id]
    if len(matches) != 1:
        raise StandbyError(f"machine response did not contain exactly one machine {machine_id}")
    return matches[0]


def exact_instance(value: Any, instance_id: str, what: str) -> dict[str, Any] | None:
    rows = [value] if isinstance(value, dict) and "instances" not in value else strict_rows(value, what)
    matches = [row for row in rows if identifier(row) == instance_id]
    if not matches:
        if rows:
            raise StandbyError(f"{what} returned non-target instance rows")
        return None
    if len(matches) != 1 or len(rows) != 1:
        raise StandbyError(f"{what} did not contain exactly one instance {instance_id}")
    return matches[0]


def authenticated_account_id(value: Any) -> str:
    rows = value if isinstance(value, list) else [value]
    ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("id", row.get("user_id"))
        try:
            ids.add(positive_id(raw, "host account ID"))
        except StandbyError:
            continue
    if len(ids) != 1:
        raise StandbyError("host identity response lacks one exact positive account ID")
    return next(iter(ids))


def finite_number(record: dict[str, Any], names: tuple[str, ...], what: str) -> float:
    for name in names:
        value = record.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parsed = float(value)
            if math.isfinite(parsed):
                return parsed
    raise StandbyError(f"{what} is missing or invalid")


def require_close(actual: float, expected: float, what: str) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-8):
        raise StandbyError(f"{what} mismatch: expected {expected}, got {actual}")


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
        raise StandbyError(f"{what} omitted or changed the fixed end")


def current_rentals(machine: dict[str, Any]) -> int:
    raw = machine.get("current_rentals_running")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not float(raw).is_integer():
        raise StandbyError("machine current_rentals_running is missing or invalid")
    value = int(raw)
    if value < 0:
        raise StandbyError("machine current_rentals_running is negative")
    return value


def reliability(machine: dict[str, Any]) -> float:
    raw = machine.get("reliability2", machine.get("reliability"))
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
        raise StandbyError("machine reliability is missing or invalid")
    value = float(raw)
    if value < 0 or value > 1:
        raise StandbyError("machine reliability is outside zero to one")
    return value


def machine_health(machine: dict[str, Any]) -> dict[str, Any]:
    verification = machine.get("verification", machine.get("verified"))
    if verification is None:
        raise StandbyError("machine verification state is missing")
    for field in ("error_description", "vm_error_msg"):
        value = machine.get(field)
        if value is not None and not isinstance(value, str):
            raise StandbyError(f"machine {field} is invalid")
    level = machine.get("vm_error_level")
    if isinstance(level, bool) or not isinstance(level, (int, float)) or not math.isfinite(float(level)):
        raise StandbyError("machine vm_error_level is missing or invalid")
    result = {
        "reliability": reliability(machine),
        "verification": verification,
        "error_description": machine.get("error_description") or "",
        "vm_error_level": float(level),
        "vm_error_msg": machine.get("vm_error_msg") or "",
    }
    if result["error_description"] or result["vm_error_level"] != 0.0 or result["vm_error_msg"]:
        raise StandbyError("machine health fields are not clear")
    return result


def redact_text(value: str) -> str:
    sanitized = SENSITIVE_QUOTED_TEXT_RE.sub(
        lambda match: (
            f"{match.group(1)}{match.group(2)}<redacted-sensitive-field>{match.group(2)}"
        ),
        value,
    )
    sanitized = SENSITIVE_TEXT_RE.sub(r"\1<redacted-sensitive-field>", sanitized)
    sanitized = EMAIL_RE.sub("<redacted-email>", sanitized)
    sanitized = IPV4_RE.sub("<redacted-ip>", sanitized)
    return TOKEN_RE.sub("<redacted-token>", sanitized)


def sanitize_value(value: Any, key: str = "") -> Any:
    if key and SENSITIVE_KEY_RE.search(key):
        return "<redacted-sensitive-field>"
    if isinstance(value, dict):
        return {str(k): sanitize_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def sanitize_text(value: str) -> str:
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return redact_text(value)
    return json.dumps(sanitize_value(parsed), sort_keys=True)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(sanitize_value(value), handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


class Cli:
    """One pre-authenticated CLI wrapper; API keys are never command arguments."""

    def __init__(self, executable: str) -> None:
        resolved = shutil.which(executable)
        if not resolved:
            raise StandbyError(f"host CLI executable not found: {executable}")
        self.executable = str(Path(resolved).resolve())

    def run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        if any("api_key" in arg.lower() or "api-key" in arg.lower() for arg in args):
            raise StandbyError("API keys must stay inside the isolated CLI wrapper")
        return subprocess.run(
            [self.executable, *args],
            text=True,
            capture_output=True,
            timeout=CLI_TIMEOUT_SECONDS,
            check=False,
        )


@dataclasses.dataclass(frozen=True)
class Config:
    machine_id: str
    host_cli: str
    gpu_count: int
    fixed_end_epoch: int
    p99_host_on_demand_price: float
    p99_host_bid_floor: float
    expected_renter_on_demand_price: float
    disk_price: float
    upload_price: float
    download_price: float
    image: str
    disk_gb: float
    label: str
    original_reliability_baseline: float
    allow_degraded_diagnostic: bool
    contracts_reviewed: bool
    offer_timeout: float
    running_timeout: float
    stopped_timeout: float
    absence_samples: int
    poll_seconds: float
    apply: bool


def validate_config(cfg: Config, *, wall_time: float | None = None) -> None:
    positive_id(cfg.machine_id, "machine ID")
    if type(cfg.gpu_count) is not int or cfg.gpu_count not in {1, 2, 4, 8}:
        raise StandbyError("GPU count must be exactly 1, 2, 4, or 8")
    now = time.time() if wall_time is None else wall_time
    if cfg.fixed_end_epoch < now + 900:
        raise StandbyError("fixed end must be at least 15 minutes in the future")
    if cfg.fixed_end_epoch > now + MAX_FIXED_END_SECONDS:
        raise StandbyError("fixed end must be no more than 48 hours in the future")
    for value, what in (
        (cfg.p99_host_on_demand_price, "host on-demand price"),
        (cfg.p99_host_bid_floor, "host bid floor"),
        (cfg.expected_renter_on_demand_price, "renter on-demand price"),
        (cfg.disk_price, "disk price"),
        (cfg.upload_price, "upload price"),
        (cfg.download_price, "download price"),
        (cfg.disk_gb, "disk size"),
    ):
        if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise StandbyError(f"{what} must be finite and positive")
    if cfg.p99_host_on_demand_price < 1 or cfg.p99_host_bid_floor < 1:
        raise StandbyError("temporary owner-preparation prices must both be at least $1/GPU-hour")
    if cfg.disk_gb < 10 or cfg.disk_gb > 100:
        raise StandbyError("owner standby disk must be between 10 and 100 GB")
    if not PINNED_PYTORCH_IMAGE_RE.fullmatch(cfg.image):
        raise StandbyError("image must be an allowlisted digest-pinned pytorch/pytorch CUDA image")
    if not SAFE_LABEL_RE.fullmatch(cfg.label) or "owner" not in cfg.label.lower():
        raise StandbyError("label must be safe, unique, and contain 'owner'")
    if (
        isinstance(cfg.original_reliability_baseline, bool)
        or not math.isfinite(cfg.original_reliability_baseline)
        or not 0 <= cfg.original_reliability_baseline <= 1
    ):
        raise StandbyError("original reliability baseline must be between zero and one")
    for value, what in (
        (cfg.offer_timeout, "offer timeout"),
        (cfg.running_timeout, "running timeout"),
        (cfg.stopped_timeout, "stopped timeout"),
        (cfg.poll_seconds, "poll seconds"),
    ):
        if not math.isfinite(value) or value <= 0:
            raise StandbyError(f"{what} must be finite and positive")
    if cfg.offer_timeout > 120 or cfg.running_timeout > 600 or cfg.stopped_timeout > 600:
        raise StandbyError("timeouts exceed the bounded preparation limits")
    if cfg.absence_samples < 1 or cfg.absence_samples > 5:
        raise StandbyError("absence samples must be between one and five")
    if not cfg.contracts_reviewed:
        raise StandbyError("review the host Machines/Contracts view and pass --contracts-reviewed")


def state_root(project: Path) -> Path:
    configured = os.environ.get("VAST_STATE_DIR")
    root = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".local/state/vast-host-golden-path"
    )
    resolved = root.resolve()
    project_resolved = project.resolve()
    if resolved == project_resolved or project_resolved in resolved.parents:
        raise StandbyError("VAST_STATE_DIR must be outside the repository")
    resolved.mkdir(parents=True, exist_ok=True)
    try:
        resolved.chmod(0o700)
    except OSError:
        pass
    return resolved


def load_or_pin_original_baseline(root: Path, cfg: Config) -> dict[str, Any]:
    directory = root / "original-reliability-baselines"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"machine-{cfg.machine_id}.json"
    if not path.exists():
        payload = {
            "schema": 1,
            "pinned_at": utc_now(),
            "machine_id": cfg.machine_id,
            "original_reliability_baseline": cfg.original_reliability_baseline,
            "source": "explicit operator-supplied pre-qualification observation",
        }
        try:
            with path.open("x", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                path.chmod(0o600)
            except OSError:
                pass
        except FileExistsError:
            pass
    try:
        pinned = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StandbyError("pinned original reliability evidence is unreadable") from exc
    if not isinstance(pinned, dict) or pinned.get("schema") != 1:
        raise StandbyError("pinned original reliability evidence has an unsupported shape")
    if pinned.get("machine_id") != cfg.machine_id:
        raise StandbyError("pinned original reliability evidence names another machine")
    value = pinned.get("original_reliability_baseline")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StandbyError("pinned original reliability value is invalid")
    if float(value) != cfg.original_reliability_baseline:
        raise StandbyError(
            "supplied original reliability differs from the machine's immutable pinned value"
        )
    return pinned


class StandbyPreparation:
    def __init__(
        self,
        cfg: Config,
        host: Cli,
        root: Path,
        run_dir: Path,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg = cfg
        self.host = host
        self.root = root
        self.run_dir = run_dir
        self.sleep = sleep
        self.monotonic = monotonic
        self.sequence = 0
        self.host_account_id = ""
        self.offer_id: str | None = None
        self.instance_id: str | None = None
        self.baseline: dict[str, Any] = {}
        self.diagnostic_only = False
        self.listing_attempted = False
        self.create_attempted = False
        self.stop_attempted = False
        self.unlisted_proved = False
        self.listing_marker = root / "owner-standby-listing-unresolved.json"
        self.create_marker = root / "owner-standby-create-unresolved.json"
        self.instance_marker = root / "owner-standby-instance-unresolved.json"
        self.prepared_state = root / "owner-standbys" / f"machine-{cfg.machine_id}.json"

    def require_qualification_hold_absent(self, action: str) -> None:
        try:
            require_qualification_mode_inactive(
                self.root,
                machine_id=self.cfg.machine_id,
                action=action,
            )
        except QualificationGuardError as exc:
            raise StandbyError(str(exc)) from exc

    def capture_run(
        self, args: list[str], phase: str
    ) -> subprocess.CompletedProcess[str]:
        self.sequence += 1
        try:
            result = self.host.run(args)
        except BaseException as exc:
            atomic_json(
                self.run_dir / "commands" / f"{self.sequence:04d}-{phase}.json",
                {"at": utc_now(), "args": args, "exception": str(exc)},
            )
            raise
        atomic_json(
            self.run_dir / "commands" / f"{self.sequence:04d}-{phase}.json",
            {
                "at": utc_now(),
                "args": args,
                "returncode": result.returncode,
                "stdout": sanitize_text(result.stdout),
                "stderr": sanitize_text(result.stderr),
            },
        )
        return result

    def json_call(self, args: list[str], phase: str) -> Any:
        result = self.capture_run(args, phase)
        if result.returncode != 0:
            raise StandbyError(
                f"host CLI failed ({' '.join(args[:3])}): {sanitize_text(result.stderr.strip())}"
            )
        if not result.stdout.strip() and result.stderr.strip():
            try:
                stderr_payload = json.loads(result.stderr)
            except json.JSONDecodeError:
                stderr_payload = None
            if isinstance(stderr_payload, dict) and stderr_payload.get("error") is True:
                status = stderr_payload.get("status_code", "unknown")
                message = stderr_payload.get("msg", stderr_payload.get("message", "unspecified error"))
                raise StandbyError(
                    f"host API rejected {' '.join(args[:3])} with status {status}: "
                    f"{sanitize_text(str(message))}"
                )
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise StandbyError(f"host CLI returned non-JSON for {' '.join(args[:3])}") from exc

    def query_machine(self, phase: str) -> dict[str, Any]:
        return exact_machine(
            self.json_call(["show", "machine", self.cfg.machine_id, "--raw"], phase),
            self.cfg.machine_id,
        )

    def query_instances(self, phase: str) -> list[dict[str, Any]]:
        rows = strict_rows(
            self.json_call(["show", "instances", "--raw"], phase),
            "host instance response",
        )
        for row in rows:
            positive_id(identifier(row), "host instance ID")
        return rows

    def query_instance(self, instance_id: str, phase: str) -> dict[str, Any] | None:
        value = self.json_call(["show", "instance", instance_id, "--raw"], phase)
        return exact_instance(value, instance_id, "owner instance response")

    def query_offers(self, phase: str) -> list[dict[str, Any]]:
        query = (
            f"machine_id={self.cfg.machine_id} verified=any rentable=any "
            f"rented=any num_gpus={self.cfg.gpu_count}"
        )
        rows = strict_rows(
            self.json_call(
                ["search", "offers", query, "--no-default", "--type", "on-demand", "--raw"],
                phase,
            ),
            "on-demand offer response",
        )
        for row in rows:
            positive_id(identifier(row), "on-demand offer ID")
            positive_id(row.get("machine_id"), "on-demand offer machine ID")
        return rows

    def query_bid_offers(self, phase: str) -> list[dict[str, Any]]:
        query = f"machine_id={self.cfg.machine_id} verified=any rentable=any rented=any"
        rows = strict_rows(
            self.json_call(
                ["search", "offers", query, "--no-default", "--type", "bid", "--raw"],
                phase,
            ),
            "bid offer response",
        )
        for row in rows:
            positive_id(identifier(row), "bid offer ID")
        return rows

    def require_no_target_instances(self, rows: list[dict[str, Any]], what: str) -> None:
        if any(str(row.get("machine_id", "")) == self.cfg.machine_id for row in rows):
            raise UnknownContractError(f"{what} found an existing instance on the target machine")

    def require_vacant(self, machine: dict[str, Any], what: str) -> None:
        if machine.get("num_gpus") != self.cfg.gpu_count:
            raise StandbyError(f"{what} does not expose exactly {self.cfg.gpu_count} GPUs")
        if current_rentals(machine) != 0:
            raise UnknownContractError(f"{what} is not vacant")

    def prove_unlisted_once(self, phase: str) -> None:
        for rows, kind in (
            (self.query_offers(f"{phase}-on-demand"), "on-demand"),
            (self.query_bid_offers(f"{phase}-bid"), "bid"),
        ):
            if rows:
                if any(str(row.get("machine_id", "")) == self.cfg.machine_id for row in rows):
                    raise StandbyError(f"target machine still exposes a {kind} offer")
                raise StandbyError(f"exact {kind} query returned a non-target row")

    def prove_unlisted(self) -> None:
        for sample in range(self.cfg.absence_samples):
            self.prove_unlisted_once(f"unlisted-{sample + 1:02d}")
            if sample + 1 < self.cfg.absence_samples:
                self.sleep(self.cfg.poll_seconds)
        self.unlisted_proved = True

    def preflight(self) -> None:
        if self.prepared_state.exists():
            raise StandbyError(
                f"prepared standby state already exists at {self.prepared_state}; reconcile it first"
            )
        host_user = self.json_call(["show", "user", "--raw"], "host-user")
        self.host_account_id = authenticated_account_id(host_user)
        machine = self.query_machine("preflight-machine")
        self.require_vacant(machine, "preflight machine")
        self.require_no_target_instances(self.query_instances("preflight-instances"), "preflight")
        self.prove_unlisted_once("preflight-unlisted")
        self.baseline = machine_health(machine)
        self.diagnostic_only = (
            self.baseline["reliability"] < self.cfg.original_reliability_baseline
        )
        if self.diagnostic_only and not self.cfg.allow_degraded_diagnostic:
            raise StandbyError(
                f"live reliability {self.baseline['reliability']} is below immutable original "
                f"baseline {self.cfg.original_reliability_baseline}; pass the explicit diagnostic "
                "override only for a non-production qualification run"
            )
        atomic_json(
            self.run_dir / "preflight.json",
            {
                "at": utc_now(),
                "machine_id": self.cfg.machine_id,
                "host_account_id": self.host_account_id,
                "vacant": True,
                "unlisted": True,
                "gpu_count": self.cfg.gpu_count,
                "baseline": self.baseline,
                "original_reliability_baseline": self.cfg.original_reliability_baseline,
                "diagnostic_only": self.diagnostic_only,
            },
        )

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
            str(self.cfg.gpu_count),
            "--end_date",
            str(self.cfg.fixed_end_epoch),
            "--vol_size",
            "0",
            "--raw",
        ]

    def create_args(self, offer_id: str) -> list[str]:
        # --args consumes the remainder and must stay last.  Deliberately no
        # --cancel-unavail: Vast rejects that switch for the own-machine path.
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
            self.cfg.label,
            "--raw",
            "--args",
            "/bin/bash",
            "-lc",
            owner_command(self.cfg.gpu_count),
        ]

    def verify_listing_response(self, value: Any) -> None:
        if not isinstance(value, dict) or value.get("success") is not True:
            raise StandbyError("list-machine response did not report explicit success")
        sent = value.get("you_sent")
        if not isinstance(sent, dict):
            raise StandbyError("list-machine response omitted accepted parameters")
        if str(sent.get("machine", "")) != self.cfg.machine_id:
            raise StandbyError("list-machine response names another machine")
        if sent.get("min_chunk") != self.cfg.gpu_count or sent.get("vol_size") != 0:
            raise StandbyError("list-machine response changed full chunk or no-volume guards")
        require_exact_end(sent, self.cfg.fixed_end_epoch, "list-machine response")
        for names, expected, what in (
            (("price_gpu",), self.cfg.p99_host_on_demand_price, "host on-demand price"),
            (("price_min_bid",), self.cfg.p99_host_bid_floor, "host bid floor"),
            (("price_disk",), self.cfg.disk_price, "disk price"),
            (("price_inetu",), self.cfg.upload_price, "upload price"),
            (("price_inetd",), self.cfg.download_price, "download price"),
            (("credit_discount_max",), 0.0, "reserved discount"),
        ):
            require_close(finite_number(sent, names, what), expected, what)

    def exact_owner_offer(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        matches = [row for row in rows if str(row.get("machine_id", "")) == self.cfg.machine_id]
        if len(rows) != 1 or len(matches) != 1:
            raise StandbyError("expected one exact full-machine on-demand offer")
        offer = matches[0]
        if str(offer.get("host_id", "")) != self.host_account_id:
            raise StandbyError("on-demand offer belongs to another host account")
        if offer.get("num_gpus") != self.cfg.gpu_count:
            raise StandbyError("on-demand offer is not the exact full-machine chunk")
        if offer.get("rentable") is not True or offer.get("rented") is not False:
            raise UnknownContractError("on-demand offer is not exactly rentable and vacant")
        require_exact_end(offer, self.cfg.fixed_end_epoch, "on-demand offer")
        require_close(
            finite_number(offer, ("dph_base", "dph_total"), "renter on-demand price"),
            self.cfg.expected_renter_on_demand_price,
            "renter on-demand price",
        )
        return offer

    def wait_for_offer(self, listing_response: Any) -> dict[str, Any]:
        deadline = self.monotonic() + self.cfg.offer_timeout
        last_error = "offer was not observable"
        while self.monotonic() <= deadline:
            machine = self.query_machine("listed-machine")
            self.require_vacant(machine, "listed machine")
            self.require_no_target_instances(
                self.query_instances("listed-instances"), "listed offer guard"
            )
            try:
                self.verify_listing_response(listing_response)
                return self.exact_owner_offer(self.query_offers("listed-on-demand"))
            except UnknownContractError:
                raise
            except StandbyError as exc:
                last_error = str(exc)
            self.sleep(self.cfg.poll_seconds)
        raise StandbyError(f"on-demand offer verification timed out: {last_error}")

    def require_owner_identity(self, record: dict[str, Any]) -> None:
        checks = {
            "instance ID": identifier(record) == self.instance_id,
            "machine ID": str(record.get("machine_id", "")) == self.cfg.machine_id,
            "label": record.get("label") == self.cfg.label,
            "on-demand type": record.get("is_bid") is False,
            "GPU count": record.get("num_gpus") == self.cfg.gpu_count,
            "image": record.get("image_uuid", record.get("image")) == self.cfg.image,
        }
        failed = [name for name, okay in checks.items() if not okay]
        if failed:
            raise StandbyError("owner standby identity mismatch: " + ", ".join(failed))
        disk = finite_number(record, ("disk_space", "disk_gb"), "owner standby disk")
        require_close(disk, self.cfg.disk_gb, "owner standby disk")
        require_exact_end(record, self.cfg.fixed_end_epoch, "owner standby")
        offer_fields = [record.get(name) for name in ("ask_contract_id", "offer_id") if name in record]
        if offer_fields and any(str(value) != self.offer_id for value in offer_fields):
            raise StandbyError("owner standby offer ID mismatch")
        image_args = record.get("image_args")
        expected_command = owner_command(self.cfg.gpu_count)
        if image_args is not None and image_args != ["/bin/bash", "-lc", expected_command]:
            raise StandbyError("owner standby launch arguments mismatch")

    @staticmethod
    def is_running(record: dict[str, Any]) -> bool:
        return tuple(
            record.get(field) for field in ("actual_status", "intended_status", "cur_state")
        ) == RUNNING_TUPLE

    @staticmethod
    def is_safely_stopped(record: dict[str, Any]) -> bool:
        return (
            record.get("actual_status") in SAFE_STOPPED_ACTUAL
            and record.get("intended_status") == "stopped"
            and record.get("cur_state") == "stopped"
        )

    def wait_for_state(
        self,
        *,
        phase: str,
        timeout: float,
        predicate: Callable[[dict[str, Any]], bool],
    ) -> dict[str, Any]:
        if self.instance_id is None:
            raise StandbyError("owner instance ID is unknown")
        deadline = self.monotonic() + timeout
        saw_identity = False
        while self.monotonic() <= deadline:
            record = self.query_instance(self.instance_id, phase)
            if record is not None:
                self.require_owner_identity(record)
                saw_identity = True
                if predicate(record):
                    return record
            self.sleep(self.cfg.poll_seconds)
        qualifier = " after exact identity was observed" if saw_identity else " before identity appeared"
        raise StandbyError(f"owner standby did not reach {phase}{qualifier}")

    def prepare(self) -> dict[str, Any]:
        # This direct-library boundary is intentional: a caller cannot bypass
        # qualification mode by invoking ``prepare()`` without ``main()``.
        self.require_qualification_hold_absent("owner standby preparation")
        listing_response: Any = None
        create_response: Any = None
        unlist_error: BaseException | None = None
        self.listing_attempted = True
        atomic_json(
            self.listing_marker,
            {"at": utc_now(), "machine_id": self.cfg.machine_id, "status": "listing-attempt-pending"},
        )
        try:
            listing_response = self.json_call(self.list_args(), "list-machine")
            self.verify_listing_response(listing_response)
            offer = self.wait_for_offer(listing_response)
            self.offer_id = positive_id(identifier(offer), "owner on-demand offer ID")
            # Keep qualification enable excluded from the final inactive check
            # through the single remote Create request.  A hold that wins the
            # lock first raises into the finally-unlist cleanup path.
            try:
                with qualification_owner_mutation_interlock(
                    self.root,
                    action=f"create owner standby on machine {self.cfg.machine_id}",
                ):
                    self.require_qualification_hold_absent("owner standby creation")
                    self.create_attempted = True
                    atomic_json(
                        self.create_marker,
                        {
                            "at": utc_now(),
                            "machine_id": self.cfg.machine_id,
                            "offer_id": self.offer_id,
                            "label": self.cfg.label,
                            "status": "single-create-outcome-unresolved",
                        },
                    )
                    create_response = self.json_call(
                        self.create_args(self.offer_id), "create-owner-standby"
                    )
            except QualificationGuardError as exc:
                raise StandbyError(str(exc)) from exc
            if not isinstance(create_response, dict) or create_response.get("success") is not True:
                raise StandbyError("create response did not report explicit success")
            self.instance_id = positive_id(
                create_response.get("new_contract", create_response.get("instance_id")),
                "created owner instance ID",
            )
            atomic_json(
                self.instance_marker,
                {
                    "at": utc_now(),
                    "machine_id": self.cfg.machine_id,
                    "offer_id": self.offer_id,
                    "instance_id": self.instance_id,
                    "label": self.cfg.label,
                    "status": "owner-instance-not-yet-proved-stopped",
                },
            )
        finally:
            if self.listing_attempted:
                try:
                    result = self.capture_run(
                        ["unlist", "machine", self.cfg.machine_id], "unlist-machine-finally"
                    )
                    if result.returncode != 0:
                        raise StandbyError(
                            "unlist failed: " + sanitize_text(result.stderr.strip())
                        )
                    self.prove_unlisted()
                    self.listing_marker.unlink(missing_ok=True)
                except BaseException as exc:
                    unlist_error = exc
        if unlist_error is not None:
            raise StandbyError(f"machine unlist proof failed: {unlist_error}")
        if self.instance_id is None or self.offer_id is None or create_response is None:
            raise StandbyError("single create outcome is unresolved; inspect private evidence")

        running = self.wait_for_state(
            phase="running", timeout=self.cfg.running_timeout, predicate=self.is_running
        )
        self.create_marker.unlink(missing_ok=True)
        atomic_json(self.run_dir / "owner-running.json", running)

        self.stop_attempted = True
        stop_result = self.capture_run(
            ["stop", "instance", self.instance_id, "--raw"], "stop-owner-standby"
        )
        atomic_json(
            self.run_dir / "stop-command-diagnostic.json",
            {
                "returncode": stop_result.returncode,
                "stdout": sanitize_text(stop_result.stdout),
                "stderr": sanitize_text(stop_result.stderr),
            },
        )
        stopped = self.wait_for_state(
            phase="safely-stopped",
            timeout=self.cfg.stopped_timeout,
            predicate=self.is_safely_stopped,
        )
        result = {
            "schema": 1,
            "prepared_at": utc_now(),
            "status": "owner-on-demand-standby-safely-stopped",
            "diagnostic_only": self.diagnostic_only,
            "machine_id": self.cfg.machine_id,
            "instance_id": self.instance_id,
            "offer_id": self.offer_id,
            "label": self.cfg.label,
            "is_bid": False,
            "gpu_count": self.cfg.gpu_count,
            "image": self.cfg.image,
            "image_args": ["/bin/bash", "-lc", owner_command(self.cfg.gpu_count)],
            "workload_probe_contract": owner_probe_contract(self.cfg.gpu_count),
            "disk_gb": self.cfg.disk_gb,
            "fixed_end_epoch": self.cfg.fixed_end_epoch,
            "original_reliability_baseline": self.cfg.original_reliability_baseline,
            "observed_preparation_reliability": self.baseline["reliability"],
            "unlisted_proved": self.unlisted_proved,
            "create_calls": 1,
            "stop_calls": 1,
            "destroy_calls": 0,
            "running_tuple": [
                running.get("actual_status"),
                running.get("intended_status"),
                running.get("cur_state"),
            ],
            "stopped_tuple": [
                stopped.get("actual_status"),
                stopped.get("intended_status"),
                stopped.get("cur_state"),
            ],
        }
        atomic_json(self.prepared_state, result)
        atomic_json(self.run_dir / "result.json", result)
        self.instance_marker.unlink(missing_ok=True)
        return result


def parse_args(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--machine-id", required=True)
    parser.add_argument("--host-cli", default="vastai")
    parser.add_argument("--gpu-count", type=int, default=2)
    parser.add_argument("--fixed-end-epoch", type=int, required=True)
    parser.add_argument("--p99-host-on-demand-price", type=float, required=True)
    parser.add_argument("--p99-host-bid-floor", type=float, required=True)
    parser.add_argument("--expected-renter-on-demand-price", type=float, required=True)
    parser.add_argument("--disk-price", type=float, required=True)
    parser.add_argument("--upload-price", type=float, required=True)
    parser.add_argument("--download-price", type=float, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--disk-gb", type=float, default=20.0)
    parser.add_argument("--label", required=True)
    parser.add_argument("--original-reliability-baseline", type=float, required=True)
    parser.add_argument("--allow-degraded-diagnostic", action="store_true")
    parser.add_argument("--contracts-reviewed", action="store_true")
    parser.add_argument("--offer-timeout", type=float, default=30.0)
    parser.add_argument("--running-timeout", type=float, default=180.0)
    parser.add_argument("--stopped-timeout", type=float, default=180.0)
    parser.add_argument("--absence-samples", type=int, default=3)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--apply", action="store_true")
    return Config(**vars(parser.parse_args(argv)))


def acquire_lock(root: Path) -> Path:
    for marker_name in (
        "owner-standby-listing-unresolved.json",
        "owner-standby-create-unresolved.json",
        "owner-standby-instance-unresolved.json",
    ):
        marker = root / marker_name
        if marker.exists():
            raise StandbyError(f"unresolved state exists at {marker}; reconcile it first")
    lock = root / "prepare-owner-standby.lock"
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise StandbyError(f"another standby preparation may be active: {lock}") from exc
    return lock


def main(argv: list[str] | None = None) -> int:
    cfg = parse_args(argv)
    validate_config(cfg)
    project = Path(__file__).resolve().parents[1]
    root = state_root(project)
    lock = acquire_lock(root)
    run_dir = (
        root
        / "owner-standby-preparations"
        / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        atomic_json(run_dir / "config.json", dataclasses.asdict(cfg))
        pinned = load_or_pin_original_baseline(root, cfg)
        atomic_json(run_dir / "original-reliability-baseline-source.json", pinned)
        preparation = StandbyPreparation(cfg, Cli(cfg.host_cli), root, run_dir)
        preparation.preflight()
        atomic_json(
            run_dir / "plan.json",
            {
                "list": preparation.list_args(),
                "create": preparation.create_args("<verified-own-on-demand-offer-id>"),
                "unlist": ["unlist", "machine", cfg.machine_id],
                "stop": ["stop", "instance", "<created-owner-instance-id>", "--raw"],
                "create_call_limit": 1,
                "stop_call_limit": 1,
                "destroy_calls": 0,
                "diagnostic_only": preparation.diagnostic_only,
                "workload_probe_contract": owner_probe_contract(cfg.gpu_count),
            },
        )
        if not cfg.apply:
            print(f"DRY RUN passed read-only preflight. Private plan: {run_dir / 'plan.json'}")
            return 0
        try:
            require_qualification_mode_inactive(
                root,
                machine_id=cfg.machine_id,
                action="owner standby preparation",
            )
        except QualificationGuardError as exc:
            raise StandbyError(str(exc)) from exc
        if not sys.stdin.isatty():
            raise StandbyError("refusing owner-standby mutation without an interactive terminal")
        prefix = "PREPARE DEGRADED OWNER" if preparation.diagnostic_only else "PREPARE OWNER"
        expected = f"{prefix} {cfg.machine_id}"
        print(
            "This will list once at the reviewed high prices, create one own-machine on-demand "
            "instance, unlist immediately, then stop that exact instance."
        )
        if preparation.diagnostic_only:
            print("This host is below its immutable original reliability; result is diagnostic only.")
        typed = input(f"Type exactly '{expected}' to continue: ")
        if typed != expected:
            raise StandbyError("confirmation did not match; no listing mutation was made")
        result = preparation.prepare()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except StandbyError as exc:
        atomic_json(run_dir / "failure.json", {"at": utc_now(), "error": str(exc)})
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
