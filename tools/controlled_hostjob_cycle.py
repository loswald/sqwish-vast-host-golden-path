#!/usr/bin/env python3
"""Fail-closed two-account Host Job scheduler-transition experiment.

This controller is intentionally narrow.  The controlled interruptible must
already exist, occupy the whole machine, and be running while the host is
unlisted.  A stopped-client/running-owner transition is recorded as one
experimental observation; it is not treated as a Host Job price guarantee or
as production-readiness proof.  Raw evidence is written under VAST_STATE_DIR,
outside this repo.
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
import threading
import time
from pathlib import Path
from typing import Any, Callable


TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{40,}")
SAFE_STOPPED_ACTUAL = {"created", "exited", "stopped"}
SAFE_OWNER_INACTIVE_ACTUAL = {None, "created", "exited", "stopped", "loading"}
PINNED_PYTORCH_IMAGE_RE = re.compile(
    r"^(?:docker\.io/)?pytorch/pytorch:[A-Za-z0-9_.-]*cuda[A-Za-z0-9_.-]*@sha256:[0-9a-f]{64}$"
)
OWNER_WORKLOAD_SECONDS = 180
OWNER_WORKLOAD_HEARTBEAT_SECONDS = 30
OWNER_WORKLOAD_MAX_HEARTBEATS = 8
OWNER_LOG_TAIL_LINES = 5000
CLI_TIMEOUT_SECONDS = 45.0
PYTORCH_WORKLOAD = f"""import json
import subprocess
import time
import torch

smi = subprocess.run(
    ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
    check=True,
    capture_output=True,
    text=True,
)
smi_count = len([line for line in smi.stdout.splitlines() if line.strip()])
if smi_count != 1:
    raise RuntimeError(f"expected nvidia-smi to expose exactly one GPU, got {{smi_count}}")
print(json.dumps({{"event": "nvidia_smi_ready", "device_count": smi_count}}), flush=True)

count = torch.cuda.device_count()
if count != 1:
    raise RuntimeError(f"expected exactly one assigned CUDA device, got {{count}}")
device = torch.device("cuda:0")
torch.cuda.set_device(device)
properties = torch.cuda.get_device_properties(device)
print(json.dumps({{"event": "cuda_ready", "device_count": count, "name": properties.name}}), flush=True)
a = torch.randn((8192, 8192), device=device, dtype=torch.float16)
b = torch.randn((8192, 8192), device=device, dtype=torch.float16)
deadline = time.monotonic() + {OWNER_WORKLOAD_SECONDS}
next_heartbeat = time.monotonic()
iterations = 0
heartbeats_emitted = 0
while time.monotonic() < deadline:
    result = torch.mm(a, b)
    torch.cuda.synchronize(device)
    if not torch.isfinite(result[0, 0]).item():
        raise RuntimeError("matrix multiply produced a non-finite sentinel")
    iterations += 1
    now = time.monotonic()
    if heartbeats_emitted < {OWNER_WORKLOAD_MAX_HEARTBEATS} and (
        iterations == 1 or now >= next_heartbeat
    ):
        print(json.dumps({{"event": "matmul_ok", "iteration": iterations, "device_count": count}}), flush=True)
        heartbeats_emitted += 1
        next_heartbeat = now + {OWNER_WORKLOAD_HEARTBEAT_SECONDS}
print(json.dumps({{
    "event": "bounded_workload_complete",
    "iterations": iterations,
    "device_count": count,
    "heartbeats_emitted": heartbeats_emitted,
}}), flush=True)"""
OWNER_COMMAND = """set -euo pipefail
printf 'container_start=%s\\n' "$(date -u +%FT%TZ)"
nvidia-smi -L
python - <<'PY'
""" + PYTORCH_WORKLOAD + """
PY"""


class CycleError(RuntimeError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def redact(value: str) -> str:
    return TOKEN_RE.sub("<redacted-token>", value)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


class Cli:
    """One pre-authenticated Vast CLI executable; never accepts key arguments."""

    def __init__(self, executable: str, role: str) -> None:
        resolved = shutil.which(executable)
        if not resolved:
            raise CycleError(f"{role} CLI executable not found: {executable}")
        self.executable = resolved
        self.role = role

    def run(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        if any("api_key" in arg.lower() or "api-key" in arg.lower() for arg in args):
            raise CycleError("API keys must be isolated by the CLI wrapper, never command arguments")
        result = subprocess.run(
            [self.executable, *args],
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )
        if check and result.returncode != 0:
            raise CycleError(
                f"{self.role} CLI failed ({' '.join(args[:3])}): {redact(result.stderr.strip())}"
            )
        return result

    def json(self, args: list[str], *, check: bool = True) -> Any:
        result = self.run(args, check=check)
        if result.returncode != 0:
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise CycleError(f"{self.role} CLI returned non-JSON for {' '.join(args[:3])}") from exc


def records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict) and isinstance(value.get("instances"), list):
        return [item for item in value["instances"] if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def strict_dict_list(value: Any, what: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise CycleError(f"{what} must be an exact JSON array")
    if any(not isinstance(item, dict) for item in value):
        raise CycleError(f"{what} contains a non-object row")
    return value


def strict_offer_records(value: Any, offer_type: str) -> list[dict[str, Any]]:
    rows = strict_dict_list(value, f"{offer_type} offer response")
    for row in rows:
        if not identifier(row).isdigit() or int(identifier(row)) <= 0:
            raise CycleError(f"{offer_type} offer response contains a row without a positive offer ID")
        machine_id = str(row.get("machine_id", ""))
        if not machine_id.isdigit() or int(machine_id) <= 0:
            raise CycleError(f"{offer_type} offer response contains a row without a positive machine ID")
    return rows


def strict_instance_records(value: Any, what: str) -> list[dict[str, Any]]:
    rows = strict_dict_list(value, what)
    if any(not identifier(row).isdigit() or int(identifier(row)) <= 0 for row in rows):
        raise CycleError(f"{what} contains a row without a positive instance ID")
    return rows


def parse_reports_output(stdout: str) -> list[dict[str, Any]]:
    text = stdout.strip()
    if text.startswith("reports:"):
        text = text[len("reports:") :].strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CycleError("reports command returned malformed JSON") from exc
    report_rows = strict_dict_list(value, "machine reports response")
    normalized: list[dict[str, Any]] = []
    for report in report_rows:
        if not all(isinstance(report.get(field), str) for field in ("problem", "message", "created_at")):
            raise CycleError("machine reports response contains an invalid report row")
        if not report["created_at"]:
            raise CycleError("machine reports response contains an empty creation timestamp")
        normalized.append(
            {
                "problem": report["problem"],
                "message": report["message"],
                "created_at": report["created_at"],
            }
        )
    return normalized


def identifier(record: dict[str, Any]) -> str:
    return str(record.get("id", record.get("contract_id", record.get("instance_id", ""))))


def machine_identifier(record: dict[str, Any]) -> str:
    return str(record.get("machine_id", record.get("id", "")))


def exact_record(value: Any, wanted_id: str, what: str) -> dict[str, Any]:
    matches = [record for record in records(value) if identifier(record) == wanted_id]
    if len(matches) != 1:
        raise CycleError(f"{what} response did not contain exactly one record for {wanted_id}")
    return matches[0]


def exact_machine(value: Any, machine_id: str) -> dict[str, Any]:
    matches = [record for record in records(value) if machine_identifier(record) == machine_id]
    if len(matches) != 1:
        raise CycleError(f"host response did not contain exactly one machine {machine_id}")
    return matches[0]


def authenticated_account_id(value: Any) -> str:
    candidates: list[str] = []
    for record in records(value):
        raw = record.get("id", record.get("user_id"))
        if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
            candidates.append(str(raw))
        elif isinstance(raw, str) and raw.isdigit() and int(raw) > 0:
            candidates.append(raw)
    unique = sorted(set(candidates))
    if len(unique) != 1:
        raise CycleError("authenticated account response lacks one exact positive account ID")
    return unique[0]


def require_client_identity(record: dict[str, Any], cfg: "Config") -> None:
    checks = {
        "instance ID": identifier(record) == cfg.client_instance_id,
        "machine ID": str(record.get("machine_id", "")) == cfg.machine_id,
        "label": record.get("label") == cfg.client_label,
        "interruptible type": record.get("is_bid") is True,
        "GPU count": record.get("num_gpus") == cfg.gpu_count,
    }
    failed = [name for name, okay in checks.items() if not okay]
    if failed:
        raise CycleError("controlled client identity mismatch: " + ", ".join(failed))


def require_full_machine_capacity(machine: dict[str, Any], client: dict[str, Any], cfg: "Config") -> None:
    machine_gpus = machine.get("num_gpus")
    if machine_gpus != cfg.gpu_count:
        raise CycleError(f"host must expose exactly {cfg.gpu_count} GPUs, got {machine_gpus!r}")
    if client.get("num_gpus") != machine_gpus:
        raise CycleError("controlled client does not occupy the full machine GPU count")


def ensure_client_not_configured_owner(client_instance_id: str, configured_owner_id: str) -> None:
    if configured_owner_id.strip() and configured_owner_id.strip() == client_instance_id:
        raise CycleError("controlled client ID is configured as VAST_OWN_INSTANCE_ID and may never be destroyed")


def default_job_definition_is_empty(machine: dict[str, Any]) -> bool:
    for field in ("bid_image", "bid_image_args", "bid_gpu_cost"):
        if field not in machine:
            raise CycleError(f"machine default-job field {field} is missing")
    return (
        machine["bid_image"] in (None, "")
        and machine["bid_image_args"] in (None, [], "")
        and machine["bid_gpu_cost"] in (None, 0, 0.0)
    )


def require_no_default_job(machine: dict[str, Any]) -> None:
    if not default_job_definition_is_empty(machine):
        raise CycleError("preflight found an existing machine default Host Job definition")


def is_running(record: dict[str, Any]) -> bool:
    return all(record.get(field) == "running" for field in ("actual_status", "intended_status", "cur_state"))


def is_safely_stopped(record: dict[str, Any]) -> bool:
    return (
        record.get("actual_status") in SAFE_STOPPED_ACTUAL
        and record.get("intended_status") == "stopped"
        and record.get("cur_state") == "stopped"
    )


def is_owner_inactive(record: dict[str, Any]) -> bool:
    return (
        "actual_status" in record
        and record.get("actual_status") in SAFE_OWNER_INACTIVE_ACTUAL
        and record.get("intended_status") == "stopped"
        and record.get("cur_state") in {"stopped", "unloaded"}
    )


def reliability(machine: dict[str, Any]) -> float:
    raw = machine.get("reliability2", machine.get("reliability"))
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
        raise CycleError("machine reliability is missing or invalid")
    return float(raw)


def machine_summary(machine: dict[str, Any], report_rows: Any) -> dict[str, Any]:
    verification = machine.get("verification", machine.get("verified"))
    if verification is None:
        raise CycleError("machine verification state is missing")
    reports = strict_dict_list(report_rows, "machine reports response")
    for report in reports:
        if not all(isinstance(report.get(field), str) for field in ("problem", "message", "created_at")):
            raise CycleError("machine reports response contains an invalid report row")
    normalized_messages: dict[str, str] = {}
    for field in ("error_description", "vm_error_msg"):
        if field not in machine:
            raise CycleError(f"machine {field} health field is missing or invalid")
        value = machine[field]
        if value is not None and not isinstance(value, str):
            raise CycleError(f"machine {field} health field is missing or invalid")
        normalized_messages[field] = "" if value is None else value
    if (
        "vm_error_level" not in machine
        or isinstance(machine["vm_error_level"], bool)
        or not isinstance(machine["vm_error_level"], (int, float))
        or not math.isfinite(float(machine["vm_error_level"]))
    ):
        raise CycleError("machine vm_error_level health field is missing or invalid")
    return {
        "at": utc_now(),
        "reliability": reliability(machine),
        "verification": verification,
        "reports": len(reports),
        "report_records": reports,
        "machine_report_counters": {
            "num_reports": machine.get("num_reports"),
            "num_recent_reports": machine.get("num_recent_reports"),
        },
        "health": {
            "error_description": normalized_messages["error_description"],
            "vm_error_level": float(machine["vm_error_level"]),
            "vm_error_msg": normalized_messages["vm_error_msg"],
        },
    }


def health_is_clear(summary: dict[str, Any]) -> bool:
    health = summary.get("health")
    return bool(
        isinstance(health, dict)
        and health.get("error_description") == ""
        and health.get("vm_error_level") == 0.0
        and health.get("vm_error_msg") == ""
        and summary.get("reports") == 0
    )


def summary_reliability(summary: dict[str, Any]) -> float:
    raw = summary.get("reliability")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
        raise CycleError("reliability summary is missing or invalid")
    return float(raw)


def original_reliability_assessment(
    original_reliability_baseline: float,
    summary: dict[str, Any],
) -> dict[str, Any]:
    current = summary_reliability(summary)
    return {
        "at": utc_now(),
        "original_reliability_baseline": original_reliability_baseline,
        "observed_reliability": current,
        "delta_from_original": current - original_reliability_baseline,
        "at_or_above_original": current >= original_reliability_baseline,
    }


def require_original_reliability_floor(
    original_reliability_baseline: float,
    summary: dict[str, Any],
    what: str,
) -> None:
    assessment = original_reliability_assessment(original_reliability_baseline, summary)
    if not assessment["at_or_above_original"]:
        raise CycleError(
            f"{what} reliability {assessment['observed_reliability']} is below immutable original "
            f"baseline {original_reliability_baseline}; refusing to use a degraded run-local baseline"
        )


def parse_end(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
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


def exact_end_is_proved(expected: int, record: Any) -> bool:
    if not isinstance(record, dict) or "end_date" not in record:
        return False
    parsed = parse_end(record["end_date"])
    return parsed is not None and abs(parsed - expected) <= 1.0


def numeric_field(record: dict[str, Any], names: tuple[str, ...], what: str) -> float:
    for name in names:
        value = record.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            return float(value)
    raise CycleError(f"{what} is missing or invalid")


def require_close(actual: float, expected: float, what: str) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9):
        raise CycleError(f"{what} mismatch: expected {expected}, got {actual}")


def exact_offer(value: Any, machine_id: str, offer_type: str) -> dict[str, Any]:
    rows = strict_offer_records(value, offer_type)
    if len(rows) != 1 or str(rows[0].get("machine_id", "")) != machine_id:
        raise CycleError(f"expected one exact {offer_type} response row for machine {machine_id}")
    return rows[0]


def verify_listing_postconditions(
    cfg: "Config",
    listing_response: Any,
    machine_response: Any,
    bid_response: Any,
    on_demand_response: Any,
) -> None:
    if not isinstance(listing_response, dict) or listing_response.get("success") is not True:
        raise CycleError("list-machine mutation did not return explicit JSON success")
    sent = listing_response.get("you_sent")
    if not isinstance(sent, dict):
        raise CycleError("list-machine response omitted the exact accepted listing parameters")
    if str(sent.get("machine", "")) != cfg.machine_id:
        raise CycleError("list-machine response names a different machine")
    if sent.get("min_chunk") != cfg.gpu_count or sent.get("vol_size") != 0:
        raise CycleError("list-machine response changed the full-machine chunk or volume guard")
    if not exact_end_is_proved(cfg.fixed_end_epoch, sent):
        raise CycleError("list-machine response omitted or changed the fixed end")
    for names, expected, what in (
        (("price_gpu",), cfg.on_demand_price, "accepted on-demand price"),
        (("price_min_bid",), cfg.listing_floor, "accepted host listing floor"),
        (("price_disk",), cfg.disk_price, "accepted disk price"),
        (("price_inetu",), cfg.upload_price, "accepted upload price"),
        (("price_inetd",), cfg.download_price, "accepted download price"),
        (("credit_discount_max",), 0.0, "accepted reserved discount"),
    ):
        require_close(numeric_field(sent, names, what), expected, what)

    machine = exact_machine(machine_response, cfg.machine_id)
    if machine.get("num_gpus") != cfg.gpu_count or machine.get("listed_min_gpu_count") != cfg.gpu_count:
        raise CycleError("machine postcondition does not expose one exact full-machine chunk")
    if not exact_end_is_proved(cfg.fixed_end_epoch, machine):
        raise CycleError("machine postcondition omitted or changed the fixed end")
    require_close(
        numeric_field(machine, ("listed_gpu_cost",), "machine listed on-demand price"),
        cfg.on_demand_price,
        "machine listed on-demand price",
    )
    require_close(
        numeric_field(machine, ("min_bid_price",), "machine host listing floor"),
        cfg.listing_floor,
        "machine host listing floor",
    )

    bid = exact_offer(bid_response, cfg.machine_id, "bid")
    on_demand = exact_offer(on_demand_response, cfg.machine_id, "on-demand")
    for offer_type, offer in (("bid", bid), ("on-demand", on_demand)):
        if offer.get("num_gpus") != cfg.gpu_count:
            raise CycleError(f"{offer_type} offer is not the exact full-machine GPU chunk")
        if not exact_end_is_proved(cfg.fixed_end_epoch, offer):
            raise CycleError(f"{offer_type} offer omitted or changed the fixed end")
    require_close(
        numeric_field(bid, ("min_bid",), "bid offer renter floor"),
        cfg.expected_renter_floor,
        "bid offer renter floor",
    )
    require_close(
        numeric_field(on_demand, ("dph_base", "dph_total"), "on-demand renter machine price"),
        cfg.expected_renter_on_demand,
        "on-demand renter machine price",
    )


def single_instance_is_explicitly_absent(value: Any, instance_id: str) -> bool:
    if isinstance(value, dict) and set(value) == {"instances"} and value["instances"] is None:
        return True
    if isinstance(value, list):
        return value == []
    return False


def full_list_is_explicitly_absent(value: Any, instance_id: str) -> bool:
    if isinstance(value, list):
        try:
            rows = strict_instance_records(value, "full instance response")
        except CycleError:
            return False
        return all(identifier(record) != instance_id for record in rows)
    if isinstance(value, dict) and set(value) == {"instances"} and isinstance(value.get("instances"), list):
        rows = value["instances"]
        try:
            rows = strict_instance_records(rows, "full instance response")
        except CycleError:
            return False
        return all(identifier(record) != instance_id for record in rows)
    return False


def mutation_explicitly_succeeded(stdout: str) -> bool:
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError:
        return False
    return isinstance(value, dict) and value.get("success") is True


def parse_workload_log(text: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        start, end = line.find("{"), line.rfind("}")
        if start < 0 or end < start:
            continue
        try:
            event = json.loads(line[start : end + 1])
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    nvidia_smi = [
        event for event in events
        if event.get("event") == "nvidia_smi_ready" and event.get("device_count") == 1
    ]
    cuda = [event for event in events if event.get("event") == "cuda_ready" and event.get("device_count") == 1]
    matmul = [
        event for event in events
        if event.get("event") == "matmul_ok"
        and event.get("device_count") == 1
        and isinstance(event.get("iteration"), int)
        and event["iteration"] > 0
    ]
    return {
        "nvidia_smi_ready": bool(nvidia_smi),
        "cuda_ready": bool(cuda),
        "matmul_ok": bool(matmul),
        "max_iteration": max((e["iteration"] for e in matmul), default=0),
    }


def rating_gate_passes(
    original_reliability_baseline: float,
    *summaries: dict[str, Any],
) -> bool:
    if len(summaries) != 4 or any(not summary for summary in summaries):
        return False
    if (
        isinstance(original_reliability_baseline, bool)
        or not isinstance(original_reliability_baseline, (int, float))
        or not math.isfinite(float(original_reliability_baseline))
    ):
        return False
    try:
        floor_holds = all(
            summary_reliability(summary) >= float(original_reliability_baseline)
            for summary in summaries
        )
    except CycleError:
        return False
    # Reliability improvements are allowed. Verification remains a separate,
    # conservative consistency gate because this harness does not know how to
    # order every API value Vast may return for its verification stages.
    verification_unchanged = all(
        summary.get("verification") == summaries[0].get("verification")
        for summary in summaries
    )
    return floor_holds and verification_unchanged and all(health_is_clear(summary) for summary in summaries)


def build_defjob_args(cfg: "Config", price: float) -> list[str]:
    # --args consumes the rest; /bin/bash must precede -lc and this must stay last.
    return [
        "set", "defjob", cfg.machine_id,
        "--price_gpu", f"{price:.6f}",
        "--price_inetu", f"{cfg.upload_price:.6f}",
        "--price_inetd", f"{cfg.download_price:.6f}",
        "--image", cfg.owner_image,
        "--args", "/bin/bash", "-lc", OWNER_COMMAND,
    ]


def build_list_args(cfg: "Config") -> list[str]:
    return [
        "list", "machine", cfg.machine_id,
        "--price_gpu", f"{cfg.on_demand_price:.6f}",
        "--price_min_bid", f"{cfg.listing_floor:.6f}",
        "--price_disk", f"{cfg.disk_price:.6f}",
        "--price_inetu", f"{cfg.upload_price:.6f}",
        "--price_inetd", f"{cfg.download_price:.6f}",
        "--discount_rate", "0",
        "--min_chunk", str(cfg.gpu_count),
        "--end_date", str(cfg.fixed_end_epoch),
        "--vol_size", "0",
        "--raw",
    ]


@dataclasses.dataclass(frozen=True)
class Config:
    machine_id: str
    client_instance_id: str
    client_label: str
    host_cli: str
    client_cli: str
    fixed_end_epoch: int
    on_demand_price: float
    listing_floor: float
    expected_renter_floor: float
    expected_renter_on_demand: float
    disk_price: float
    upload_price: float
    download_price: float
    host_job_low: float
    host_job_high: float
    expected_owner_low_renter_price: float
    expected_owner_high_renter_price: float
    owner_image: str
    original_reliability_baseline: float
    gpu_count: int = 2
    poll_seconds: float = 3.0
    reclaim_timeout: int = 30
    owner_run_seconds: int = 60
    auto_resume_seconds: int = 60
    delayed_seconds: int = 7200
    max_public_seconds: int = 600
    max_fixed_end_seconds: int = 900
    apply: bool = False


class Cycle:
    def __init__(
        self,
        cfg: Config,
        host: Cli,
        client: Cli,
        run_dir: Path,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg = cfg
        self.host = host
        self.client = client
        self.run_dir = run_dir
        self.sleep = sleep
        self.monotonic = monotonic
        self.sequence = 0
        self.cycle_started = False
        self.unlisted_proved = False
        self.defjob_touched = False
        self.listing_touched = False
        self.destroy_authorized = False
        self.owner_job_ids: tuple[str, ...] | None = None
        self.account_ids: dict[str, str] | None = None
        self.cleanup_errors: list[str] = []
        self.baseline: dict[str, Any] | None = None
        self.immediate: dict[str, Any] | None = None
        self.post_cleanup: dict[str, Any] | None = None
        self.delayed: dict[str, Any] | None = None
        self.auto_resume = False
        self.manual_start_used = False
        self.experimental_takeover_observed = False
        self.experimental_cycle_completed = False
        self.listed_at: float | None = None
        self.public_cutoff = threading.Event()
        self.watchdog_stop = threading.Event()
        self.watchdog_thread: threading.Thread | None = None
        self.watchdog_result: dict[str, Any] | None = None

    def public_action_deadline(self) -> float:
        if self.listed_at is None:
            raise CycleError("public-listing clock was not started")
        return self.listed_at + self.cfg.max_public_seconds - CLI_TIMEOUT_SECONDS

    def require_public_action_budget(self, phase: str) -> None:
        if self.public_cutoff.is_set() or self.monotonic() >= self.public_action_deadline():
            raise CycleError(f"public-listing action budget expired before {phase}")

    def start_public_watchdog(self) -> None:
        if self.watchdog_thread is not None:
            raise CycleError("public-listing watchdog already exists")
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
                result = self.host.run(["unlist", "machine", self.cfg.machine_id], check=False)
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
            name="controlled-hostjob-unlist-watchdog",
            daemon=True,
        )
        self.watchdog_thread.start()

    def stop_public_watchdog(self) -> None:
        self.watchdog_stop.set()
        if self.watchdog_thread is not None:
            self.watchdog_thread.join(timeout=1.0)

    def query_client(self) -> dict[str, Any]:
        value = self.client.json(["show", "instance", self.cfg.client_instance_id, "--raw"])
        record = exact_record(value, self.cfg.client_instance_id, "controlled client")
        require_client_identity(record, self.cfg)
        return record

    def query_machine(self) -> dict[str, Any]:
        return exact_machine(
            self.host.json(["show", "machine", self.cfg.machine_id, "--raw"]),
            self.cfg.machine_id,
        )

    def query_host_instances(self) -> Any:
        return strict_instance_records(
            self.host.json(["show", "instances", "--raw"]),
            "host instance response",
        )

    def query_offers(self, offer_type: str) -> Any:
        query = f"machine_id={self.cfg.machine_id} verified=any rentable=any rented=any"
        return strict_offer_records(
            self.host.json(["search", "offers", query, "--no-default", "--type", offer_type, "--raw"]),
            offer_type,
        )

    def query_reports(self) -> list[dict[str, Any]]:
        result = self.host.run(["reports", self.cfg.machine_id, "--raw"])
        return parse_reports_output(result.stdout)

    def prove_distinct_accounts(self) -> None:
        host_id = authenticated_account_id(self.host.json(["show", "user", "--raw"]))
        client_id = authenticated_account_id(self.client.json(["show", "user", "--raw"]))
        if host_id == client_id:
            raise CycleError("host and controlled client CLIs authenticate as the same Vast account")
        self.account_ids = {"host": host_id, "client": client_id}
        atomic_json(self.run_dir / "authenticated-accounts.json", self.account_ids)

    def snapshot(self, phase: str) -> dict[str, Any]:
        if self.listing_touched:
            self.require_public_action_budget(phase)
        self.sequence += 1
        payload = {
            "at": utc_now(),
            "phase": phase,
            "host_machine": self.host.json(["show", "machine", self.cfg.machine_id, "--raw"]),
            "host_instances": self.query_host_instances(),
            "client_instance": self.client.json(["show", "instance", self.cfg.client_instance_id, "--raw"]),
            "bid_offers": self.query_offers("bid"),
            "on_demand_offers": self.query_offers("on-demand"),
        }
        atomic_json(self.run_dir / "snapshots" / f"{self.sequence:05d}-{phase}.json", payload)
        with (self.run_dir / "timeline.ndjson").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": payload["at"], "phase": phase, "sequence": self.sequence}) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return payload

    def prove_unlisted(self, *, samples: int = 1) -> None:
        self.unlisted_proved = False
        for sample in range(samples):
            for offer_type in ("bid", "on-demand"):
                rows = strict_offer_records(self.query_offers(offer_type), offer_type)
                if any(str(r.get("machine_id", "")) == self.cfg.machine_id for r in rows):
                    raise CycleError(f"machine still exposes {offer_type} offers")
                if rows:
                    raise CycleError(f"exact {offer_type} search returned unexpected non-target rows")
            if sample + 1 < samples:
                self.sleep(self.cfg.poll_seconds)
        self.unlisted_proved = True

    def owner_job_matches_definition(self, record: dict[str, Any]) -> bool:
        return (
            str(record.get("machine_id", "")) == self.cfg.machine_id
            and record.get("is_bid") is True
            and record.get("num_gpus") == 1
            and record.get("image_uuid", record.get("image")) == self.cfg.owner_image
            and record.get("image_args") == ["/bin/bash", "-lc", OWNER_COMMAND]
        )

    def exact_owner_jobs(self, host_instances: Any, *, establish: bool) -> list[dict[str, Any]]:
        host_rows = strict_instance_records(host_instances, "host instance response")
        candidates = [
            record for record in host_rows
            if str(record.get("machine_id", "")) == self.cfg.machine_id and record.get("is_bid") is True
        ]
        if not candidates:
            return []
        if len(candidates) > self.cfg.gpu_count or not all(self.owner_job_matches_definition(r) for r in candidates):
            raise CycleError("owner bid records do not exactly match this two-job image/argument definition")
        job_ids = tuple(sorted(identifier(record) for record in candidates))
        if len(set(job_ids)) != len(job_ids) or any(not value.isdigit() or int(value) <= 0 for value in job_ids):
            raise CycleError("owner job records lack unique positive IDs")
        if self.owner_job_ids is not None:
            if not set(job_ids).issubset(set(self.owner_job_ids)):
                raise CycleError("an unknown owner job ID appeared during the controlled cycle")
            if len(candidates) == self.cfg.gpu_count and job_ids != self.owner_job_ids:
                raise CycleError("owner job IDs changed during the controlled cycle")
        if establish and self.owner_job_ids is None and len(candidates) == self.cfg.gpu_count:
            self.owner_job_ids = job_ids
            atomic_json(
                self.run_dir / "owner-jobs.json",
                {"at": utc_now(), "job_ids": list(job_ids), "image": self.cfg.owner_image, "args": ["/bin/bash", "-lc", OWNER_COMMAND]},
            )
        return candidates

    def require_no_owner_bid_records(self, host_instances: Any) -> None:
        existing = [
            record for record in strict_instance_records(host_instances, "host instance response")
            if str(record.get("machine_id", "")) == self.cfg.machine_id and record.get("is_bid") is True
        ]
        if existing:
            raise CycleError("preflight found existing owner bid records; remove and re-run dry preflight")

    def wait_for_staged_owner_jobs(self) -> None:
        deadline = self.monotonic() + self.cfg.reclaim_timeout
        while self.monotonic() <= deadline:
            snap = self.snapshot("stage-low-poll")
            jobs = self.exact_owner_jobs(snap["host_instances"], establish=True)
            if len(jobs) == self.cfg.gpu_count:
                return
            self.sleep(self.cfg.poll_seconds)
        raise CycleError("the exact two owner Host Job records were not created before timeout")

    def prove_low_phase(self) -> None:
        deadline = self.monotonic() + self.cfg.reclaim_timeout
        consecutive = 0
        while self.monotonic() <= deadline:
            snap = self.snapshot("low-phase-guard")
            client_record = exact_record(
                snap["client_instance"], self.cfg.client_instance_id, "controlled client"
            )
            require_client_identity(client_record, self.cfg)
            if not is_running(client_record):
                raise CycleError("low Host Job price preempted or disturbed the controlled client")
            if self.active_owner_jobs(snap["host_instances"]):
                raise CycleError("low Host Job phase unexpectedly activated an owner job")
            if self.owner_jobs_inactive_at_low(snap["host_instances"]):
                consecutive += 1
                if consecutive >= 2:
                    atomic_json(
                        self.run_dir / "low-phase-confirmed.json",
                        {"at": utc_now(), "snapshot": self.sequence, "consecutive_samples": consecutive},
                    )
                    return
            else:
                consecutive = 0
            self.sleep(self.cfg.poll_seconds)
        raise CycleError(
            "low phase never proved running client, inactive exact owner jobs, and intended renter-side price"
        )

    def wait_for_listing_postconditions(self, listing_response: Any) -> None:
        deadline = self.monotonic() + self.cfg.reclaim_timeout
        last_error = "listing postconditions were not observable"
        while self.monotonic() <= deadline:
            guard = self.snapshot("fixed-end-verify")
            try:
                verify_listing_postconditions(
                    self.cfg,
                    listing_response,
                    guard["host_machine"],
                    guard["bid_offers"],
                    guard["on_demand_offers"],
                )
                return
            except CycleError as exc:
                last_error = str(exc)
            self.sleep(self.cfg.poll_seconds)
        raise CycleError(f"listing postcondition timeout: {last_error}")

    def owner_jobs_have_price(self, jobs: list[dict[str, Any]], expected_price: float) -> bool:
        try:
            return all(
                math.isclose(
                    numeric_field(job, ("dph_base",), "owner Host Job renter-side price"),
                    expected_price,
                    rel_tol=1e-9,
                    abs_tol=1e-9,
                )
                for job in jobs
            )
        except CycleError:
            return False

    def owner_jobs_running(self, host_instances: Any) -> bool:
        jobs = self.exact_owner_jobs(host_instances, establish=True)
        return (
            self.owner_job_ids is not None
            and len(jobs) == self.cfg.gpu_count
            and all(is_running(r) for r in jobs)
            and self.owner_jobs_have_price(jobs, self.cfg.expected_owner_high_renter_price)
        )

    def owner_jobs_inactive_at_low(self, host_instances: Any) -> bool:
        jobs = self.exact_owner_jobs(host_instances, establish=True)
        return (
            self.owner_job_ids is not None
            and len(jobs) == self.cfg.gpu_count
            and all(is_owner_inactive(record) for record in jobs)
            and self.owner_jobs_have_price(jobs, self.cfg.expected_owner_low_renter_price)
        )

    def active_owner_jobs(self, host_instances: Any) -> list[dict[str, Any]]:
        return [
            r for r in strict_instance_records(host_instances, "host instance response")
            if str(r.get("machine_id", "")) == self.cfg.machine_id
            and r.get("is_bid") is True
            and any(r.get(field) == "running" for field in ("actual_status", "intended_status", "cur_state"))
        ]

    def prove_defjob_removed(self) -> None:
        for attempt in range(1, 7):
            host_instances = self.query_host_instances()
            machine = self.query_machine()
            owner_records = [
                record for record in host_instances
                if str(record.get("machine_id", "")) == self.cfg.machine_id and record.get("is_bid") is True
            ]
            definition_clear = default_job_definition_is_empty(machine)
            atomic_json(
                self.run_dir / "remove-defjob-polls" / f"{attempt:02d}.json",
                {"host_instances": host_instances, "host_machine": machine},
            )
            if not owner_records and definition_clear:
                return
            if attempt < 6:
                self.sleep(5)
        raise CycleError("default Host Job definition or owner bid records remain after removal")

    def wait_for_experimental_takeover(self) -> None:
        deadline = self.monotonic() + self.cfg.reclaim_timeout
        while self.monotonic() <= deadline:
            snap = self.snapshot("experimental-takeover-poll")
            client_record = exact_record(snap["client_instance"], self.cfg.client_instance_id, "controlled client")
            require_client_identity(client_record, self.cfg)
            if is_safely_stopped(client_record) and self.owner_jobs_running(snap["host_instances"]):
                atomic_json(
                    self.run_dir / "experimental-takeover-observed.json",
                    {
                        "at": utc_now(),
                        "snapshot": self.sequence,
                        "observed": True,
                        "scope": (
                            "one bounded experimental scheduler-transition observation only; this does not prove "
                            "that Host Job price will preempt a live renter in production"
                        ),
                    },
                )
                self.experimental_takeover_observed = True
                return
            self.sleep(self.cfg.poll_seconds)
        raise CycleError(
            "experimental scheduler transition did not reach exact stopped-client/running-owner "
            "state before timeout"
        )

    def monitor_owner(self) -> None:
        deadline = self.monotonic() + self.cfg.owner_run_seconds
        partial_since: float | None = None
        while self.monotonic() < deadline:
            snap = self.snapshot("owner-run")
            client_record = exact_record(snap["client_instance"], self.cfg.client_instance_id, "controlled client")
            require_client_identity(client_record, self.cfg)
            if not is_safely_stopped(client_record):
                raise CycleError("owner/client state changed during clean workload dwell")
            jobs = self.exact_owner_jobs(snap["host_instances"], establish=True)
            if len(jobs) < self.cfg.gpu_count:
                partial_since = partial_since if partial_since is not None else self.monotonic()
                if self.monotonic() - partial_since > self.cfg.reclaim_timeout:
                    raise CycleError("owner job view remained partial during clean workload dwell")
            else:
                partial_since = None
                if not self.owner_jobs_running(snap["host_instances"]):
                    raise CycleError("owner/client state changed during clean workload dwell")
            self.sleep(min(self.cfg.poll_seconds, max(0.0, deadline - self.monotonic())))
        if partial_since is not None:
            raise CycleError("owner job view was partial at the end of the clean workload dwell")

    def collect_owner_workload_proof(self) -> None:
        if self.owner_job_ids is None or len(self.owner_job_ids) != self.cfg.gpu_count:
            raise CycleError("cannot collect workload proof without exact owner job IDs")
        proofs: dict[str, dict[str, Any]] = {}
        for job_id in self.owner_job_ids:
            result = self.host.run(["logs", job_id, "--tail", str(OWNER_LOG_TAIL_LINES)])
            atomic_text(self.run_dir / "owner-logs" / f"{job_id}.log", result.stdout)
            proof = parse_workload_log(result.stdout)
            if not proof["nvidia_smi_ready"] or not proof["cuda_ready"] or not proof["matmul_ok"]:
                raise CycleError(
                    f"owner job {job_id} lacks exact one-GPU nvidia-smi, CUDA, and matrix-multiply proof"
                )
            proofs[job_id] = proof
        atomic_json(self.run_dir / "owner-workload-proof.json", {"at": utc_now(), "jobs": proofs})

    def wait_for_auto_resume(self) -> bool:
        deadline = self.monotonic() + self.cfg.auto_resume_seconds
        last: dict[str, Any] | None = None
        consecutive = 0
        while self.monotonic() <= deadline:
            last = self.snapshot("auto-resume-poll")
            record = exact_record(last["client_instance"], self.cfg.client_instance_id, "controlled client")
            require_client_identity(record, self.cfg)
            active = self.active_owner_jobs(last["host_instances"])
            if is_running(record):
                if active:
                    raise CycleError("owner/client overlap appeared during automatic return")
                if self.owner_jobs_inactive_at_low(last["host_instances"]):
                    consecutive += 1
                    if consecutive >= 2:
                        self.auto_resume = True
                        atomic_json(
                            self.run_dir / "auto-resume-confirmed.json",
                            {"at": utc_now(), "snapshot": self.sequence, "consecutive_samples": consecutive},
                        )
                        return True
                else:
                    consecutive = 0
            else:
                consecutive = 0
            self.sleep(self.cfg.poll_seconds)
        failure = {
            "at": utc_now(),
            "automatic_resume_observed": False,
            "waited_seconds": self.cfg.auto_resume_seconds,
            "last_snapshot": self.sequence,
        }
        atomic_json(self.run_dir / "auto-resume-failure.json", failure)
        return False

    def guarded_manual_start(self) -> None:
        failure_path = self.run_dir / "auto-resume-failure.json"
        if not failure_path.is_file():
            raise CycleError("manual Start refused: auto-resume failure evidence is absent")
        failure = json.loads(failure_path.read_text(encoding="utf-8"))
        if failure.get("automatic_resume_observed") is not False:
            raise CycleError("manual Start refused: failure evidence is invalid")
        guard_deadline = self.monotonic() + self.cfg.reclaim_timeout
        consecutive_safe = 0
        while self.monotonic() <= guard_deadline:
            record = self.query_client()
            if not is_safely_stopped(record):
                raise CycleError("manual Start refused: exact client is not safely stopped")
            host_instances = self.query_host_instances()
            if self.active_owner_jobs(host_instances):
                raise CycleError("manual Start refused: owner Host Jobs are still active")
            if self.owner_jobs_inactive_at_low(host_instances):
                consecutive_safe += 1
                if consecutive_safe >= 2:
                    break
            else:
                consecutive_safe = 0
            self.sleep(self.cfg.poll_seconds)
        else:
            raise CycleError("manual Start refused: exact inactive low owner state was not proved")
        self.client.run(["start", "instance", self.cfg.client_instance_id, "--raw"])
        self.manual_start_used = True
        deadline = self.monotonic() + self.cfg.reclaim_timeout
        consecutive_running = 0
        while self.monotonic() <= deadline:
            snap = self.snapshot("manual-start-poll")
            record = exact_record(snap["client_instance"], self.cfg.client_instance_id, "controlled client")
            require_client_identity(record, self.cfg)
            if self.active_owner_jobs(snap["host_instances"]):
                raise CycleError("manual Start detected owner/client overlap")
            if is_running(record):
                if self.owner_jobs_inactive_at_low(snap["host_instances"]):
                    consecutive_running += 1
                    if consecutive_running >= 2:
                        atomic_json(
                            self.run_dir / "manual-start-confirmed.json",
                            {"at": utc_now(), "snapshot": self.sequence, "consecutive_samples": consecutive_running},
                        )
                        return
                else:
                    consecutive_running = 0
            else:
                consecutive_running = 0
            self.sleep(self.cfg.poll_seconds)
        raise CycleError("manual Start did not restore exact running/running/running state")

    def cleanup(self) -> None:
        # Close the listing first so destroying the full-machine client cannot
        # expose newly vacant GPUs. If that cannot be proved, retain the owner
        # jobs so cleanup does not deliberately vacate the machine.
        if self.cycle_started:
            self.unlisted_proved = False
            try:
                self.host.run(["unlist", "machine", self.cfg.machine_id])
                self.prove_unlisted(samples=3)
            except Exception as exc:  # noqa: BLE001 - preserve all cleanup attempts
                self.cleanup_errors.append(f"unlist: {exc}")
        if self.defjob_touched:
            if not self.unlisted_proved:
                self.cleanup_errors.append(
                    "remove defjob: skipped because post-mutation unlisting was not proved; "
                    "owner jobs retained and capacity state remains unresolved"
                )
            else:
                try:
                    self.host.run(["remove", "defjob", self.cfg.machine_id])
                    self.prove_defjob_removed()
                except Exception as exc:  # noqa: BLE001
                    self.cleanup_errors.append(f"remove defjob: {exc}")
        if self.destroy_authorized and self.cycle_started and self.unlisted_proved and not self.cleanup_errors:
            try:
                single_before = self.client.json(["show", "instance", self.cfg.client_instance_id, "--raw"])
                list_before = self.client.json(["show", "instances", "--raw"])
                if single_instance_is_explicitly_absent(single_before, self.cfg.client_instance_id) and full_list_is_explicitly_absent(list_before, self.cfg.client_instance_id):
                    atomic_json(self.run_dir / "destroy-verification.json", {"confirmed": True, "method": "already-absent-both-views"})
                else:
                    record = exact_record(single_before, self.cfg.client_instance_id, "controlled client before destroy")
                    require_client_identity(record, self.cfg)
                    list_rows = strict_instance_records(list_before, "controlled client full instance response")
                    listed_record = exact_record(list_rows, self.cfg.client_instance_id, "controlled client list before destroy")
                    require_client_identity(listed_record, self.cfg)
                    destroy = self.client.run(
                        ["destroy", "instance", self.cfg.client_instance_id, "--yes", "--raw"]
                    )
                    atomic_text(self.run_dir / "destroy-output.txt", destroy.stdout)
                    confirmed = mutation_explicitly_succeeded(destroy.stdout)
                    method = "explicit-json-success" if confirmed else ""
                    if not confirmed:
                        for attempt in range(1, 7):
                            single_after = self.client.json(["show", "instance", self.cfg.client_instance_id, "--raw"], check=False)
                            list_after = self.client.json(["show", "instances", "--raw"], check=False)
                            atomic_json(
                                self.run_dir / "destroy-polls" / f"{attempt:02d}.json",
                                {"single": single_after, "list": list_after},
                            )
                            if single_instance_is_explicitly_absent(single_after, self.cfg.client_instance_id) and full_list_is_explicitly_absent(list_after, self.cfg.client_instance_id):
                                confirmed = True
                                method = "absent-from-single-and-full-list"
                                break
                            if attempt < 6:
                                self.sleep(5)
                    if not confirmed:
                        raise CycleError("destroy lacked explicit success and exact absence from both client views")
                    atomic_json(self.run_dir / "destroy-verification.json", {"confirmed": True, "method": method})
            except Exception as exc:  # noqa: BLE001
                self.cleanup_errors.append(f"destroy controlled client: {exc}")
        elif self.destroy_authorized and self.cycle_started:
            reason = "unlisting was not proved" if not self.unlisted_proved else "an earlier cleanup step failed"
            self.cleanup_errors.append(f"destroy controlled client: skipped because {reason}")
        atomic_json(
            self.run_dir / "cleanup.json",
            {"at": utc_now(), "errors": self.cleanup_errors, "complete": not self.cleanup_errors},
        )
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

    def run(self) -> dict[str, Any]:
        self.prove_unlisted(samples=2)
        self.prove_distinct_accounts()
        client_record = self.query_client()
        if not is_running(client_record):
            raise CycleError("controlled client must initially be running/running/running")
        machine = self.query_machine()
        require_full_machine_capacity(machine, client_record, self.cfg)
        require_no_default_job(machine)
        baseline_host_instances = self.query_host_instances()
        self.require_no_owner_bid_records(baseline_host_instances)
        atomic_json(self.run_dir / "host-instances-before-defjob.json", baseline_host_instances)
        self.baseline = machine_summary(machine, self.query_reports())
        if not health_is_clear(self.baseline):
            raise CycleError("baseline report or machine-health state is not clean")
        atomic_json(self.run_dir / "reliability-baseline.json", self.baseline)
        baseline_floor = original_reliability_assessment(
            self.cfg.original_reliability_baseline,
            self.baseline,
        )
        atomic_json(self.run_dir / "original-reliability-baseline-gate.json", baseline_floor)
        require_original_reliability_floor(
            self.cfg.original_reliability_baseline,
            self.baseline,
            "pre-mutation",
        )

        # A preflight absence proof must never authorize later client destruction.
        # Only a fresh three-sample proof after an attempted public listing may do so.
        self.unlisted_proved = False
        self.cycle_started = True
        self.defjob_touched = True
        self.host.run(build_defjob_args(self.cfg, self.cfg.host_job_low))
        self.listing_touched = True
        self.unlisted_proved = False
        self.listed_at = self.monotonic()
        self.start_public_watchdog()
        listing_result = self.host.run(build_list_args(self.cfg))
        try:
            listing_response = json.loads(listing_result.stdout)
        except json.JSONDecodeError as exc:
            raise CycleError("list-machine mutation returned non-JSON") from exc
        self.wait_for_listing_postconditions(listing_response)
        self.wait_for_staged_owner_jobs()
        self.prove_low_phase()

        self.require_public_action_budget("raise Host Job")
        self.host.run(build_defjob_args(self.cfg, self.cfg.host_job_high))
        self.wait_for_experimental_takeover()
        self.monitor_owner()
        self.collect_owner_workload_proof()
        self.require_public_action_budget("lower Host Job")
        self.host.run(build_defjob_args(self.cfg, self.cfg.host_job_low))
        if not self.wait_for_auto_resume():
            self.guarded_manual_start()

        self.immediate = machine_summary(self.query_machine(), self.query_reports())
        atomic_json(self.run_dir / "reliability-immediate.json", self.immediate)
        self.experimental_cycle_completed = True
        return {
            "experimental_cycle_completed": True,
            "experimental_takeover_observed": self.experimental_takeover_observed,
            "production_readiness_established": False,
        }


def validate_config(cfg: Config) -> None:
    for name in ("machine_id", "client_instance_id"):
        if not getattr(cfg, name).isdigit() or int(getattr(cfg, name)) <= 0:
            raise CycleError(f"{name} must be a positive integer")
    if cfg.gpu_count != 2:
        raise CycleError("this qualification harness is intentionally fixed to exactly two GPUs")
    if not cfg.client_label or len(cfg.client_label) < 8:
        raise CycleError("client label must be a dedicated, exact label of at least 8 characters")
    if cfg.host_job_low >= cfg.host_job_high:
        raise CycleError("Host Job low price must be below its high price")
    if cfg.expected_owner_low_renter_price >= cfg.expected_owner_high_renter_price:
        raise CycleError("expected renter-side Host Job low price must be below its high price")
    if not PINNED_PYTORCH_IMAGE_RE.fullmatch(cfg.owner_image):
        raise CycleError("owner image must be an allowlisted digest-pinned pytorch/pytorch CUDA image")
    if (
        isinstance(cfg.original_reliability_baseline, bool)
        or not isinstance(cfg.original_reliability_baseline, (int, float))
        or not math.isfinite(cfg.original_reliability_baseline)
        or cfg.original_reliability_baseline < 0
        or cfg.original_reliability_baseline > 1
    ):
        raise CycleError("original reliability baseline must be a finite number between zero and one")
    if cfg.owner_run_seconds <= 0 or cfg.owner_run_seconds > OWNER_WORKLOAD_SECONDS - 30:
        raise CycleError("owner dwell must be positive and end at least 30 seconds before the bounded workload exits")
    prices = (
        cfg.on_demand_price, cfg.listing_floor, cfg.expected_renter_floor,
        cfg.expected_renter_on_demand, cfg.disk_price, cfg.upload_price,
        cfg.download_price, cfg.host_job_low, cfg.host_job_high,
        cfg.expected_owner_low_renter_price, cfg.expected_owner_high_renter_price,
    )
    if any(not math.isfinite(value) or value <= 0 for value in prices):
        raise CycleError("every configured price must be finite and greater than zero")
    if not math.isfinite(cfg.poll_seconds) or cfg.poll_seconds < 1 or cfg.poll_seconds > 5:
        raise CycleError("poll interval must be between 1 and 5 seconds")
    if cfg.reclaim_timeout <= 0 or cfg.auto_resume_seconds <= 0:
        raise CycleError("reclaim and automatic-resume timeouts must be positive")
    if cfg.delayed_seconds < 7200:
        raise CycleError("delayed reliability observation must be at least 7200 seconds")
    if cfg.max_public_seconds < 60 or cfg.max_public_seconds > 600:
        raise CycleError("maximum public-listing window must be between 60 and 600 seconds")
    if cfg.max_fixed_end_seconds < 60 or cfg.max_fixed_end_seconds > 86_400:
        raise CycleError("maximum fixed-end horizon must be between 60 and 86400 seconds")
    now = int(time.time())
    minimum = now + (5 * cfg.reclaim_timeout) + cfg.owner_run_seconds + cfg.auto_resume_seconds + 60
    maximum = now + cfg.max_fixed_end_seconds
    if cfg.fixed_end_epoch < minimum or cfg.fixed_end_epoch > maximum:
        raise CycleError(
            f"fixed end must be between {minimum} and {maximum} "
            "(enough cycle time, within the separate fixed-end horizon)"
        )
    required_public_seconds = minimum - now
    if cfg.max_public_seconds < required_public_seconds + int(CLI_TIMEOUT_SECONDS):
        raise CycleError(
            "public-listing window is too short for the configured cycle plus the unlist reserve"
        )


def state_root(project: Path) -> Path:
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


def load_or_pin_original_reliability_baseline(root: Path, cfg: Config) -> dict[str, Any]:
    baseline_dir = root / "original-reliability-baselines"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    try:
        baseline_dir.chmod(0o700)
    except OSError:
        pass
    path = baseline_dir / f"machine-{cfg.machine_id}.json"
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
        raise CycleError("pinned original reliability evidence is unreadable or malformed") from exc
    if not isinstance(pinned, dict) or pinned.get("schema") != 1:
        raise CycleError("pinned original reliability evidence has an unsupported shape")
    if pinned.get("machine_id") != cfg.machine_id:
        raise CycleError("pinned original reliability evidence names a different machine")
    pinned_value = pinned.get("original_reliability_baseline")
    if (
        isinstance(pinned_value, bool)
        or not isinstance(pinned_value, (int, float))
        or not math.isfinite(float(pinned_value))
    ):
        raise CycleError("pinned original reliability evidence contains an invalid value")
    if float(pinned_value) != cfg.original_reliability_baseline:
        raise CycleError(
            "supplied original reliability baseline differs from the machine's already-pinned immutable value"
        )
    return pinned


def parse_args(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--machine-id", required=True)
    parser.add_argument("--client-instance-id", required=True)
    parser.add_argument("--client-label", required=True)
    parser.add_argument("--host-cli", default="vastai")
    parser.add_argument("--client-cli", required=True, help="separately authenticated executable/wrapper")
    parser.add_argument("--fixed-end-epoch", type=int, required=True)
    parser.add_argument("--on-demand-price", type=float, required=True)
    parser.add_argument("--listing-floor", type=float, required=True)
    parser.add_argument("--expected-renter-floor", type=float, required=True)
    parser.add_argument("--expected-renter-on-demand", type=float, required=True)
    parser.add_argument("--disk-price", type=float, required=True)
    parser.add_argument("--upload-price", type=float, required=True)
    parser.add_argument("--download-price", type=float, required=True)
    parser.add_argument("--host-job-low", type=float, required=True)
    parser.add_argument("--host-job-high", type=float, required=True)
    parser.add_argument("--expected-owner-low-renter-price", type=float, required=True)
    parser.add_argument("--expected-owner-high-renter-price", type=float, required=True)
    parser.add_argument("--owner-image", required=True, help="digest-pinned pytorch/pytorch CUDA image")
    parser.add_argument(
        "--original-reliability-baseline",
        type=float,
        required=True,
        help="immutable reliability observed before any qualification attempts; never use a run-local replacement",
    )
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    parser.add_argument("--reclaim-timeout", type=int, default=30)
    parser.add_argument("--owner-run-seconds", type=int, default=60)
    parser.add_argument("--auto-resume-seconds", type=int, default=60)
    parser.add_argument("--delayed-seconds", type=int, default=7200)
    parser.add_argument("--max-public-seconds", type=int, default=600)
    parser.add_argument("--max-fixed-end-seconds", type=int, default=900)
    parser.add_argument("--apply", action="store_true")
    return Config(**vars(parser.parse_args(argv)))


def preview(cfg: Config, host: Cli, client: Cli, run_dir: Path) -> None:
    cycle = Cycle(cfg, host, client, run_dir)
    cycle.prove_unlisted(samples=2)
    cycle.prove_distinct_accounts()
    client_record = cycle.query_client()
    if not is_running(client_record):
        raise CycleError("controlled client must initially be running/running/running")
    machine = cycle.query_machine()
    require_full_machine_capacity(machine, client_record, cfg)
    require_no_default_job(machine)
    cycle.require_no_owner_bid_records(cycle.query_host_instances())
    baseline = machine_summary(machine, cycle.query_reports())
    if not health_is_clear(baseline):
        raise CycleError("baseline report or machine-health state is not clean")
    atomic_json(run_dir / "reliability-baseline.json", baseline)
    baseline_floor = original_reliability_assessment(cfg.original_reliability_baseline, baseline)
    atomic_json(run_dir / "original-reliability-baseline-gate.json", baseline_floor)
    require_original_reliability_floor(
        cfg.original_reliability_baseline,
        baseline,
        "dry-run preflight",
    )
    plan = {
        "host_job_low": build_defjob_args(cfg, cfg.host_job_low),
        "fixed_end_listing": build_list_args(cfg),
        "experimental_high_bid_stimulus": build_defjob_args(cfg, cfg.host_job_high),
        "release_host_job_low": build_defjob_args(cfg, cfg.host_job_low),
        "takeover_interpretation": (
            "a stopped-client/running-owner state is one experimental observation, not a production guarantee"
        ),
        "production_readiness_rule": (
            "this one-cycle harness never establishes production readiness; every rating observation must also "
            "remain at or above the immutable original reliability baseline"
        ),
        "manual_start_condition": "only after auto-resume-failure.json is fsynced and exact client is safely stopped",
        "cleanup_order": [
            "unlist and prove three consecutive bid/on-demand absence samples",
            "only after unlist proof: remove defjob and prove removal",
            "only after both proofs: destroy exact controlled client with --yes and prove success or absence",
        ],
    }
    atomic_json(run_dir / "dry-run-plan.json", plan)
    print(f"DRY RUN passed exact read-only preflight. Private plan: {run_dir / 'dry-run-plan.json'}")


def delayed_rating_skip_reason(cycle: Cycle) -> str | None:
    if not cycle.experimental_takeover_observed:
        return "experimental takeover was not observed; skip the two-hour wait after immediate cleanup evidence"
    if cycle.post_cleanup is None:
        return "post-cleanup reliability observation is unavailable"
    assessment = original_reliability_assessment(
        cycle.cfg.original_reliability_baseline,
        cycle.post_cleanup,
    )
    if not assessment["at_or_above_original"]:
        return "post-cleanup reliability is already below the immutable original baseline"
    return None


def build_production_readiness_result(
    cycle: Cycle,
    cycle_error: str | None,
    rating_gate: bool,
) -> dict[str, Any]:
    checks = {
        "experimental_cycle_completed": cycle.experimental_cycle_completed,
        "experimental_takeover_observed": cycle.experimental_takeover_observed,
        "automatic_resume_observed": cycle.auto_resume,
        "manual_start_not_used": not cycle.manual_start_used,
        "cleanup_complete": not cycle.cleanup_errors,
        "no_cycle_error": cycle_error is None,
        "no_reliability_loss_vs_original": rating_gate,
    }
    technical_gates_passed = all(checks.values())
    blockers = [name for name, passed in checks.items() if not passed]
    blockers.append(
        "one experimental scheduler transition cannot establish that Host Job price will preempt a live renter in production"
    )
    return {
        "established": False,
        "status": "not-established-by-this-experiment",
        "original_reliability_baseline": cycle.cfg.original_reliability_baseline,
        "single_cycle_technical_gates_passed": technical_gates_passed,
        "checks": checks,
        "blocking_reasons": blockers,
        "takeover_evidence_scope": "single bounded experimental observation only",
    }


def run_locked(cfg: Config, root: Path) -> int:
    run_dir = root / "controlled-hostjob-cycles" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        run_dir.chmod(0o700)
    except OSError:
        pass
    atomic_json(run_dir / "config.json", dataclasses.asdict(cfg) | {"owner_command": OWNER_COMMAND})
    pinned_baseline = load_or_pin_original_reliability_baseline(root, cfg)
    atomic_json(run_dir / "original-reliability-baseline-source.json", pinned_baseline)
    host = Cli(cfg.host_cli, "host")
    client = Cli(cfg.client_cli, "client")
    if Path(host.executable).resolve() == Path(client.executable).resolve():
        raise CycleError("host and client must use distinct pre-authenticated CLI executables")
    ensure_client_not_configured_owner(
        cfg.client_instance_id,
        os.environ.get("VAST_OWN_INSTANCE_ID", ""),
    )

    if not cfg.apply:
        preview(cfg, host, client, run_dir)
        return 0
    if not sys.stdin.isatty():
        raise CycleError("refusing mutations without an interactive terminal")
    for signal_name in ("SIGINT", "SIGTERM", "SIGHUP"):
        if hasattr(signal, signal_name):
            signal.signal(getattr(signal, signal_name), lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    expected = f"CYCLE {cfg.client_instance_id} ON {cfg.machine_id}"
    if input(f"Type {expected}: ") != expected:
        raise CycleError("cycle confirmation did not match")
    destroy_expected = f"DESTROY CONTROLLED {cfg.client_instance_id}"
    if input(f"Type {destroy_expected}: ") != destroy_expected:
        raise CycleError("cleanup confirmation did not match")
    # Confirmation time counts against the short fixed-end window.
    validate_config(cfg)

    cycle = Cycle(cfg, host, client, run_dir)
    cycle.destroy_authorized = True
    cycle_error: str | None = None
    try:
        cycle.run()
    except Exception as exc:  # noqa: BLE001 - cleanup must run on every failure
        cycle_error = str(exc)
    finally:
        cycle.cleanup()

    if cycle.cycle_started and not cycle.cleanup_errors:
        try:
            cycle.post_cleanup = machine_summary(cycle.query_machine(), cycle.query_reports())
            atomic_json(run_dir / "reliability-post-cleanup.json", cycle.post_cleanup)
            skip_reason = delayed_rating_skip_reason(cycle)
            if skip_reason is None:
                time.sleep(cfg.delayed_seconds)
                cycle.delayed = machine_summary(cycle.query_machine(), cycle.query_reports())
                atomic_json(run_dir / "reliability-delayed.json", cycle.delayed)
            else:
                atomic_json(
                    run_dir / "reliability-delayed-skipped.json",
                    {
                        "at": utc_now(),
                        "skipped": True,
                        "reason": skip_reason,
                        "wait_seconds_not_performed": cfg.delayed_seconds,
                    },
                )
        except Exception as exc:  # noqa: BLE001
            cycle_error = cycle_error or f"reliability observation failed: {exc}"

    baseline = cycle.baseline or {}
    immediate = cycle.immediate or {}
    post_cleanup = cycle.post_cleanup or {}
    delayed = cycle.delayed or {}
    rating_gate = rating_gate_passes(
        cfg.original_reliability_baseline,
        baseline,
        immediate,
        post_cleanup,
        delayed,
    )
    production_readiness = build_production_readiness_result(cycle, cycle_error, rating_gate)
    reliability_against_original: dict[str, Any] = {}
    for name, summary in (
        ("pre_mutation", baseline),
        ("immediate", immediate),
        ("post_cleanup", post_cleanup),
        ("delayed", delayed),
    ):
        if summary:
            reliability_against_original[name] = original_reliability_assessment(
                cfg.original_reliability_baseline,
                summary,
            )
    result = {
        "at": utc_now(),
        "cycle_error": cycle_error,
        "experimental_cycle_completed": cycle.experimental_cycle_completed,
        "experimental_takeover_observed": cycle.experimental_takeover_observed,
        "takeover_evidence_scope": "single bounded experimental observation only; not a production guarantee",
        "automatic_resume_gate": cycle.auto_resume,
        "manual_start_used": cycle.manual_start_used,
        "rating_gate": rating_gate,
        "original_reliability_baseline": cfg.original_reliability_baseline,
        "reliability_against_original": reliability_against_original,
        "production_readiness": production_readiness,
        "cleanup_complete": not cycle.cleanup_errors,
        "baseline": baseline,
        "immediate": immediate,
        "post_cleanup": post_cleanup,
        "delayed": delayed,
    }
    atomic_json(run_dir / "result.json", result)
    print(f"Private result: {run_dir / 'result.json'}")
    if not production_readiness["established"]:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    project = Path(__file__).resolve().parents[1]
    cfg = parse_args(argv)
    validate_config(cfg)
    root = state_root(project)
    lock = root / "controlled-hostjob-cycle.lock"
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise CycleError(f"another clean cycle may be active: {lock}") from exc
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
    except (CycleError, KeyboardInterrupt) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
