#!/usr/bin/env python3
"""Fail-closed two-account owner-standby preemption experiment.

The controlled interruptible must already occupy the whole target machine.  A
pre-created, stopped, host-account on-demand instance must already exist on the
same machine.  The controller unlists first, proves both offer views absent,
starts only that owner standby, measures time to the exact running state, stops
it, and observes whether the controlled interruptible returns automatically.

This is an experimental diagnostic.  A successful run is not a production
readiness decision and cannot establish a zero-rating-impact guarantee.  Raw
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
import signal
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

try:
    from tools.controlled_hostjob_cycle import (
        Cli,
        CycleError,
        atomic_json as _atomic_json,
        atomic_text as _atomic_text,
        authenticated_account_id,
        exact_machine,
        exact_record,
        full_list_is_explicitly_absent,
        health_is_clear,
        identifier,
        is_running,
        is_safely_stopped,
        load_or_pin_original_reliability_baseline,
        machine_summary,
        mutation_explicitly_succeeded,
        original_reliability_assessment,
        parse_reports_output,
        rating_gate_passes,
        redact,
        single_instance_is_explicitly_absent,
        strict_instance_records,
        strict_offer_records,
        utc_now,
    )
except ModuleNotFoundError:  # Direct ``python tools/...`` execution.
    from controlled_hostjob_cycle import (  # type: ignore[no-redef]
        Cli,
        CycleError,
        atomic_json as _atomic_json,
        atomic_text as _atomic_text,
        authenticated_account_id,
        exact_machine,
        exact_record,
        full_list_is_explicitly_absent,
        health_is_clear,
        identifier,
        is_running,
        is_safely_stopped,
        load_or_pin_original_reliability_baseline,
        machine_summary,
        mutation_explicitly_succeeded,
        original_reliability_assessment,
        parse_reports_output,
        rating_gate_passes,
        redact,
        single_instance_is_explicitly_absent,
        strict_instance_records,
        strict_offer_records,
        utc_now,
    )


CLI_TIMEOUT_SECONDS = 45.0
MAX_RECLAIM_SLO_SECONDS = 900
SECRET_KEY_RE = re.compile(
    r"(?:api[_-]?key|machineapikey|token|password|credential|secret|"
    r"ssh[_-]?(?:key|public[_-]?key)|email|(?:public|external)[_-]?ip|ip[_-]?address)",
    re.I,
)
SECRET_TEXT_RE = re.compile(
    r"(?i)((?:['\"])?(?:instance[_-]?api[_-]?key|api[_-]?key|machineapikey|token|"
    r"password|credential|secret|ssh[_-]?(?:key|public[_-]?key)|email|"
    r"(?:public|external)[_-]?ip|ip[_-]?address)(?:['\"])?\s*[:=]\s*['\"]?)"
    r"[^'\",}\s]+"
)
SECRET_QUOTED_TEXT_RE = re.compile(
    r"(?i)((?:['\"])?(?:instance[_-]?api[_-]?key|api[_-]?key|machineapikey|token|"
    r"password|credential|secret|ssh[_-]?(?:key|public[_-]?key)|email|"
    r"(?:public|external)[_-]?ip|ip[_-]?address)(?:['\"])?\s*[:=]\s*)(['\"])"
    r"[^'\"]*\2"
)
EMAIL_RE = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])")
IPV4_RE = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")


def redact_evidence(value: Any) -> Any:
    """Recursively redact token-shaped strings before every evidence write."""

    if isinstance(value, str):
        sanitized = SECRET_QUOTED_TEXT_RE.sub(
            lambda match: f"{match.group(1)}{match.group(2)}<redacted>{match.group(2)}",
            value,
        )
        sanitized = SECRET_TEXT_RE.sub(r"\1<redacted>", sanitized)
        sanitized = EMAIL_RE.sub("<redacted-email>", sanitized)
        sanitized = IPV4_RE.sub("<redacted-ip>", sanitized)
        return redact(sanitized)
    if isinstance(value, list):
        return [redact_evidence(item) for item in value]
    if isinstance(value, tuple):
        return [redact_evidence(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): "<redacted>" if SECRET_KEY_RE.search(str(key)) else redact_evidence(item)
            for key, item in value.items()
        }
    return value


def atomic_json(path: Path, value: Any) -> None:
    _atomic_json(path, redact_evidence(value))


def atomic_text(path: Path, value: str) -> None:
    _atomic_text(path, redact_evidence(value))


@dataclasses.dataclass(frozen=True)
class Config:
    machine_id: str
    owner_instance_id: str
    owner_label: str
    client_instance_id: str
    client_label: str
    host_cli: str
    client_cli: str
    original_reliability_baseline: float
    gpu_count: int = 2
    poll_seconds: float = 3.0
    reclaim_slo_seconds: int = MAX_RECLAIM_SLO_SECONDS
    owner_dwell_seconds: int = 60
    owner_stop_timeout_seconds: int = 120
    auto_resume_seconds: int = 180
    delayed_seconds: int = 7200
    skip_delayed_observation: bool = False
    contracts_reviewed: bool = False
    allow_degraded_diagnostic: bool = False
    allow_controlled_client_fallback_start: bool = False
    destroy_controlled_client_on_cleanup: bool = False
    apply: bool = False


def validate_config(cfg: Config) -> None:
    for name in ("machine_id", "owner_instance_id", "client_instance_id"):
        value = getattr(cfg, name)
        if not value.isdigit() or int(value) <= 0:
            raise CycleError(f"{name} must be a positive integer")
    if cfg.owner_instance_id == cfg.client_instance_id:
        raise CycleError("owner and controlled-client instance IDs must be different")
    if cfg.gpu_count != 2:
        raise CycleError("this pilot controller is intentionally fixed to exactly two GPUs")
    for name in ("owner_label", "client_label"):
        if len(getattr(cfg, name)) < 8:
            raise CycleError(f"{name} must be an exact dedicated label of at least 8 characters")
    baseline = cfg.original_reliability_baseline
    if (
        isinstance(baseline, bool)
        or not isinstance(baseline, (int, float))
        or not math.isfinite(float(baseline))
        or not 0 <= float(baseline) <= 1
    ):
        raise CycleError("original reliability baseline must be a finite number between zero and one")
    if not math.isfinite(cfg.poll_seconds) or not 1 <= cfg.poll_seconds <= 5:
        raise CycleError("poll interval must be between 1 and 5 seconds")
    if not 1 <= cfg.reclaim_slo_seconds <= MAX_RECLAIM_SLO_SECONDS:
        raise CycleError("reclaim SLO must be between 1 and 900 seconds")
    if not 1 <= cfg.owner_dwell_seconds <= 600:
        raise CycleError("owner dwell must be between 1 and 600 seconds")
    if not 1 <= cfg.owner_stop_timeout_seconds <= 900:
        raise CycleError("owner stop timeout must be between 1 and 900 seconds")
    if not 1 <= cfg.auto_resume_seconds <= 900:
        raise CycleError("automatic-resume timeout must be between 1 and 900 seconds")
    if cfg.delayed_seconds < 7200:
        raise CycleError("delayed reliability observation must be at least 7200 seconds")
    if cfg.apply and not cfg.contracts_reviewed:
        raise CycleError(
            "apply requires --contracts-reviewed after inspecting Host Machines/Contracts for "
            "outside on-demand or reserved contracts"
        )


def require_owner_identity(record: dict[str, Any], cfg: Config) -> None:
    checks = {
        "instance ID": identifier(record) == cfg.owner_instance_id,
        "machine ID": str(record.get("machine_id", "")) == cfg.machine_id,
        "label": record.get("label") == cfg.owner_label,
        "on-demand type": record.get("is_bid") is False,
        "GPU count": record.get("num_gpus") == cfg.gpu_count,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise CycleError("owner standby identity mismatch: " + ", ".join(failed))


def require_client_identity(record: dict[str, Any], cfg: Config) -> None:
    checks = {
        "instance ID": identifier(record) == cfg.client_instance_id,
        "machine ID": str(record.get("machine_id", "")) == cfg.machine_id,
        "label": record.get("label") == cfg.client_label,
        "interruptible type": record.get("is_bid") is True,
        "GPU count": record.get("num_gpus") == cfg.gpu_count,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise CycleError("controlled client identity mismatch: " + ", ".join(failed))


def require_exact_account_inventories(
    host_instances: Any,
    client_instances: Any,
    cfg: Config,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reject every unknown target-machine record, including high-priority ones.

    Vast's host Contracts page remains a required operator check because a
    renter-account inventory is not a complete host-contract inventory.  This
    machine-readable gate is intentionally stricter than a type-only filter:
    any target-machine record other than the two exact pilot instances aborts.
    """

    host_rows = strict_instance_records(host_instances, "host account instance response")
    client_rows = strict_instance_records(client_instances, "controlled-client full instance response")
    host_target = [r for r in host_rows if str(r.get("machine_id", "")) == cfg.machine_id]
    client_target = [r for r in client_rows if str(r.get("machine_id", "")) == cfg.machine_id]
    if len(host_target) != 1 or identifier(host_target[0]) != cfg.owner_instance_id:
        unknown = [identifier(r) for r in host_target if identifier(r) != cfg.owner_instance_id]
        if any(r.get("is_bid") is False for r in host_target if identifier(r) != cfg.owner_instance_id):
            raise CycleError("outside on-demand or reserved target-machine instance detected")
        raise CycleError(f"host inventory is not the exact owner-only target set; unknown IDs: {unknown}")
    if len(client_target) != 1 or identifier(client_target[0]) != cfg.client_instance_id:
        unknown = [identifier(r) for r in client_target if identifier(r) != cfg.client_instance_id]
        if any(r.get("is_bid") is False for r in client_target if identifier(r) != cfg.client_instance_id):
            raise CycleError("outside on-demand or reserved target-machine instance detected")
        raise CycleError(f"client inventory is not the exact controlled-client target set; unknown IDs: {unknown}")
    require_owner_identity(host_target[0], cfg)
    require_client_identity(client_target[0], cfg)
    return host_target[0], client_target[0]


def degraded_gate(
    cfg: Config,
    summary: dict[str, Any],
    *,
    what: str,
) -> dict[str, Any]:
    assessment = original_reliability_assessment(cfg.original_reliability_baseline, summary)
    assessment["allow_degraded_diagnostic"] = cfg.allow_degraded_diagnostic
    assessment["experimental_only"] = True
    if not assessment["at_or_above_original"] and not cfg.allow_degraded_diagnostic:
        raise CycleError(
            f"{what} reliability {assessment['observed_reliability']} is below immutable original "
            f"baseline {cfg.original_reliability_baseline}; refusing every mutation without "
            "--allow-degraded-diagnostic"
        )
    return assessment


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


class StandbyCycle:
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
        self.state_root = (
            run_dir.parent.parent
            if run_dir.parent.name == "controlled-owner-standby-cycles"
            else run_dir
        )
        self.sleep = sleep
        self.monotonic = monotonic
        self.sequence = 0
        self.cycle_started = False
        self.unlist_touched = False
        self.unlisted_proved = False
        self.owner_start_touched = False
        self.owner_stop_authorized = False
        self.fallback_start_authorized = False
        self.destroy_client_authorized = False
        self.cleanup_errors: list[str] = []
        self.baseline: dict[str, Any] | None = None
        self.immediate: dict[str, Any] | None = None
        self.post_cleanup: dict[str, Any] | None = None
        self.delayed: dict[str, Any] | None = None
        self.owner_running_observed = False
        self.owner_running_elapsed_seconds: float | None = None
        self.owner_stopped_observed = False
        self.auto_resume_observed = False
        self.fallback_start_used = False
        self.controlled_client_destroyed = False
        self.decision_started: float | None = None

    def require_qualification_hold_absent(self, action: str) -> None:
        try:
            require_qualification_mode_inactive(
                self.state_root,
                machine_id=self.cfg.machine_id,
                action=action,
            )
        except QualificationGuardError as exc:
            raise CycleError(str(exc)) from exc

    def query_machine(self) -> dict[str, Any]:
        return exact_machine(
            self.host.json(["show", "machine", self.cfg.machine_id, "--raw"]),
            self.cfg.machine_id,
        )

    def query_owner(self) -> dict[str, Any]:
        value = self.host.json(["show", "instance", self.cfg.owner_instance_id, "--raw"])
        record = exact_record(value, self.cfg.owner_instance_id, "owner standby")
        require_owner_identity(record, self.cfg)
        return record

    def query_client(self) -> dict[str, Any]:
        value = self.client.json(["show", "instance", self.cfg.client_instance_id, "--raw"])
        record = exact_record(value, self.cfg.client_instance_id, "controlled client")
        require_client_identity(record, self.cfg)
        return record

    def query_host_instances(self) -> list[dict[str, Any]]:
        return strict_instance_records(
            self.host.json(["show", "instances", "--raw"]),
            "host account instance response",
        )

    def query_client_instances(self) -> list[dict[str, Any]]:
        return strict_instance_records(
            self.client.json(["show", "instances", "--raw"]),
            "controlled-client full instance response",
        )

    def query_offers(self, offer_type: str) -> list[dict[str, Any]]:
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
            raise CycleError("host/owner and controlled-client CLIs authenticate as the same Vast account")
        atomic_json(
            self.run_dir / "authenticated-accounts.json",
            {"at": utc_now(), "host_owner_account_id": host_id, "controlled_client_account_id": client_id},
        )

    def require_exact_inventories(self) -> tuple[dict[str, Any], dict[str, Any]]:
        return require_exact_account_inventories(
            self.query_host_instances(),
            self.query_client_instances(),
            self.cfg,
        )

    def prove_unlisted(self, *, samples: int) -> None:
        self.unlisted_proved = False
        for sample in range(1, samples + 1):
            payload: dict[str, Any] = {"at": utc_now(), "sample": sample}
            for offer_type in ("bid", "on-demand"):
                rows = self.query_offers(offer_type)
                payload[offer_type] = rows
                if rows:
                    raise CycleError(f"machine still exposes an exact {offer_type} offer")
            atomic_json(self.run_dir / "offer-absence" / f"{sample:02d}.json", payload)
            if sample < samples:
                self.sleep(self.cfg.poll_seconds)
        self.unlisted_proved = True

    def snapshot(self, phase: str) -> dict[str, Any]:
        self.sequence += 1
        payload = {
            "at": utc_now(),
            "phase": phase,
            "machine": self.query_machine(),
            "owner": self.query_owner(),
            "client": self.query_client(),
            "host_instances": self.query_host_instances(),
            "client_instances": self.query_client_instances(),
            "bid_offers": self.query_offers("bid"),
            "on_demand_offers": self.query_offers("on-demand"),
        }
        if payload["bid_offers"] or payload["on_demand_offers"]:
            raise CycleError("a public offer reappeared during the unlisted owner-standby cycle")
        require_exact_account_inventories(payload["host_instances"], payload["client_instances"], self.cfg)
        atomic_json(self.run_dir / "snapshots" / f"{self.sequence:05d}-{phase}.json", payload)
        return payload

    def preflight(self, *, require_running_client: bool = True) -> dict[str, Any]:
        self.prove_distinct_accounts()
        owner = self.query_owner()
        client = self.query_client()
        if not is_safely_stopped(owner):
            raise CycleError("owner standby must be exactly safely stopped before the pilot")
        if require_running_client and not is_running(client):
            raise CycleError("controlled interruptible must initially be running/running/running")
        machine = self.query_machine()
        if machine.get("num_gpus") != self.cfg.gpu_count:
            raise CycleError("host does not expose the exact configured whole-machine GPU count")
        self.require_exact_inventories()
        summary = machine_summary(machine, self.query_reports())
        if not health_is_clear(summary):
            raise CycleError("machine reports or health fields are not clean")
        assessment = degraded_gate(self.cfg, summary, what="pre-mutation")
        atomic_json(self.run_dir / "reliability-baseline.json", summary)
        atomic_json(self.run_dir / "original-reliability-baseline-gate.json", assessment)
        return summary

    def unlist_then_prove(self) -> None:
        self.unlist_touched = True
        result = self.host.run(["unlist", "machine", self.cfg.machine_id], check=False)
        atomic_text(
            self.run_dir / "unlist-output.txt",
            f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}\n",
        )
        self.prove_unlisted(samples=3)
        self.require_exact_inventories()

    def wait_for_owner_takeover(self) -> None:
        if self.decision_started is None:
            raise CycleError("reclaim decision clock is absent")
        deadline = self.decision_started + self.cfg.reclaim_slo_seconds
        consecutive = 0
        while self.monotonic() <= deadline:
            snap = self.snapshot("owner-start-poll")
            owner = snap["owner"]
            client = snap["client"]
            if is_running(owner) and is_running(client):
                raise CycleError("owner and controlled client reported simultaneous running states")
            if is_running(owner) and is_safely_stopped(client):
                consecutive += 1
                if consecutive >= 2:
                    self.owner_running_observed = True
                    self.owner_running_elapsed_seconds = self.monotonic() - self.decision_started
                    atomic_json(
                        self.run_dir / "owner-takeover.json",
                        {
                            "at": utc_now(),
                            "experimental": True,
                            "owner_running": True,
                            "controlled_client_safely_stopped": True,
                            "elapsed_from_decision_seconds": self.owner_running_elapsed_seconds,
                            "reclaim_slo_seconds": self.cfg.reclaim_slo_seconds,
                            "consecutive_samples": consecutive,
                        },
                    )
                    return
            else:
                consecutive = 0
            self.sleep(self.cfg.poll_seconds)
        raise CycleError("owner standby did not reach clean takeover within the configured 15-minute-or-less SLO")

    def monitor_owner_dwell(self) -> None:
        deadline = self.monotonic() + self.cfg.owner_dwell_seconds
        while self.monotonic() < deadline:
            snap = self.snapshot("owner-dwell")
            if not is_running(snap["owner"]) or not is_safely_stopped(snap["client"]):
                raise CycleError("owner/client state changed during the bounded owner dwell")
            self.sleep(min(self.cfg.poll_seconds, max(0.0, deadline - self.monotonic())))

    def stop_owner_and_prove(self, *, phase: str) -> None:
        if not self.owner_stop_authorized:
            raise CycleError("owner stop was not explicitly authorized")
        owner = self.query_owner()
        if is_safely_stopped(owner):
            self.owner_stopped_observed = True
            return
        result = self.host.run(["stop", "instance", self.cfg.owner_instance_id, "--raw"], check=False)
        atomic_text(
            self.run_dir / f"{phase}-owner-stop-output.txt",
            f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}\n",
        )
        deadline = self.monotonic() + self.cfg.owner_stop_timeout_seconds
        consecutive = 0
        while self.monotonic() <= deadline:
            record = self.query_owner()
            if is_safely_stopped(record):
                consecutive += 1
                if consecutive >= 2:
                    self.owner_stopped_observed = True
                    atomic_json(
                        self.run_dir / f"{phase}-owner-stop-confirmed.json",
                        {"at": utc_now(), "owner_instance_id": self.cfg.owner_instance_id, "samples": consecutive},
                    )
                    return
            else:
                consecutive = 0
            self.sleep(self.cfg.poll_seconds)
        raise CycleError("could not prove the exact owner standby returned to safely stopped")

    def wait_for_auto_resume(self) -> bool:
        deadline = self.monotonic() + self.cfg.auto_resume_seconds
        consecutive = 0
        while self.monotonic() <= deadline:
            snap = self.snapshot("auto-resume-poll")
            if not is_safely_stopped(snap["owner"]):
                raise CycleError("owner standby ceased to be safely stopped during renter return")
            if is_running(snap["client"]):
                consecutive += 1
                if consecutive >= 2:
                    self.auto_resume_observed = True
                    atomic_json(
                        self.run_dir / "auto-resume-confirmed.json",
                        {"at": utc_now(), "automatic": True, "consecutive_samples": consecutive},
                    )
                    return True
            else:
                consecutive = 0
            self.sleep(self.cfg.poll_seconds)
        atomic_json(
            self.run_dir / "auto-resume-failure.json",
            {
                "at": utc_now(),
                "automatic_resume_observed": False,
                "waited_seconds": self.cfg.auto_resume_seconds,
                "owner_safely_stopped": is_safely_stopped(self.query_owner()),
                "controlled_client_safely_stopped": is_safely_stopped(self.query_client()),
            },
        )
        return False

    def guarded_fallback_start(self) -> None:
        if not self.fallback_start_authorized or not self.cfg.allow_controlled_client_fallback_start:
            raise CycleError("controlled-client fallback Start was not explicitly authorized")
        evidence_path = self.run_dir / "auto-resume-failure.json"
        if not evidence_path.is_file():
            raise CycleError("fallback Start refused: fsynced automatic-resume failure evidence is absent")
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CycleError("fallback Start refused: automatic-resume evidence is malformed") from exc
        if (
            evidence.get("automatic_resume_observed") is not False
            or evidence.get("owner_safely_stopped") is not True
            or evidence.get("controlled_client_safely_stopped") is not True
        ):
            raise CycleError("fallback Start refused: automatic-resume evidence lacks exact stopped-state proof")
        self.prove_unlisted(samples=3)
        owner, client = self.require_exact_inventories()
        if not is_safely_stopped(owner) or not is_safely_stopped(client):
            raise CycleError("fallback Start refused: current exact owner/client stopped states are not safe")
        result = self.client.run(["start", "instance", self.cfg.client_instance_id, "--raw"], check=False)
        atomic_text(
            self.run_dir / "fallback-start-output.txt",
            f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}\n",
        )
        self.fallback_start_used = True
        deadline = self.monotonic() + self.cfg.owner_stop_timeout_seconds
        consecutive = 0
        while self.monotonic() <= deadline:
            snap = self.snapshot("fallback-start-poll")
            if not is_safely_stopped(snap["owner"]):
                raise CycleError("fallback Start detected an active owner standby")
            if is_running(snap["client"]):
                consecutive += 1
                if consecutive >= 2:
                    atomic_json(
                        self.run_dir / "fallback-start-confirmed.json",
                        {"at": utc_now(), "automatic": False, "consecutive_samples": consecutive},
                    )
                    return
            else:
                consecutive = 0
            self.sleep(self.cfg.poll_seconds)
        raise CycleError("fallback Start did not restore the exact controlled client")

    def destroy_controlled_client(self) -> None:
        if not self.destroy_client_authorized or not self.cfg.destroy_controlled_client_on_cleanup:
            raise CycleError("controlled-client destruction was not explicitly authorized")
        if not self.unlisted_proved or not self.owner_stopped_observed:
            raise CycleError("controlled-client destroy requires fresh unlisting and owner-stop proof")
        single_before = self.client.json(["show", "instance", self.cfg.client_instance_id, "--raw"])
        list_before = self.client.json(["show", "instances", "--raw"])
        if single_instance_is_explicitly_absent(single_before, self.cfg.client_instance_id) and full_list_is_explicitly_absent(
            list_before, self.cfg.client_instance_id
        ):
            self.controlled_client_destroyed = True
            atomic_json(self.run_dir / "destroy-verification.json", {"confirmed": True, "method": "already-absent"})
            return
        single_record = exact_record(single_before, self.cfg.client_instance_id, "controlled client before destroy")
        listed_record = exact_record(
            strict_instance_records(list_before, "controlled-client full instance response"),
            self.cfg.client_instance_id,
            "controlled client list before destroy",
        )
        require_client_identity(single_record, self.cfg)
        require_client_identity(listed_record, self.cfg)
        result = self.client.run(["destroy", "instance", self.cfg.client_instance_id, "--yes", "--raw"])
        atomic_text(self.run_dir / "destroy-output.txt", result.stdout)
        confirmed = mutation_explicitly_succeeded(result.stdout)
        method = "explicit-json-success" if confirmed else ""
        if not confirmed:
            for attempt in range(1, 7):
                single_after = self.client.json(
                    ["show", "instance", self.cfg.client_instance_id, "--raw"], check=False
                )
                list_after = self.client.json(["show", "instances", "--raw"], check=False)
                atomic_json(
                    self.run_dir / "destroy-polls" / f"{attempt:02d}.json",
                    {"single": single_after, "list": list_after},
                )
                if single_instance_is_explicitly_absent(
                    single_after, self.cfg.client_instance_id
                ) and full_list_is_explicitly_absent(list_after, self.cfg.client_instance_id):
                    confirmed = True
                    method = "absent-from-single-and-full-list"
                    break
                if attempt < 6:
                    self.sleep(5)
        if not confirmed:
            raise CycleError("controlled-client destroy lacked explicit success and exact absence proof")
        self.controlled_client_destroyed = True
        atomic_json(self.run_dir / "destroy-verification.json", {"confirmed": True, "method": method})

    def run(self) -> None:
        self.baseline = self.preflight()
        # Guard the direct-library entry point before the first mutation.
        self.require_qualification_hold_absent("owner standby preemption cycle")
        self.decision_started = self.monotonic()
        self.cycle_started = True
        self.unlist_then_prove()
        # Recheck the score after the first mutation and before starting either
        # workload.  The explicit diagnostic flag is the only degraded escape.
        after_unlist = machine_summary(self.query_machine(), self.query_reports())
        atomic_json(
            self.run_dir / "reliability-after-unlist-gate.json",
            degraded_gate(self.cfg, after_unlist, what="post-unlist/pre-start"),
        )
        owner, client = self.require_exact_inventories()
        if not is_safely_stopped(owner) or not is_running(client):
            raise CycleError("exact owner/client states changed after unlisting and before takeover")
        # Keep qualification enable excluded from the final inactive check
        # through the remote Start request.  Cleanup remains free to stop an
        # already-running owner for safety.
        try:
            with qualification_owner_mutation_interlock(
                self.state_root,
                action=f"start owner standby {self.cfg.owner_instance_id}",
            ):
                self.require_qualification_hold_absent("owner standby start")
                self.owner_start_touched = True
                result = self.host.run(
                    ["start", "instance", self.cfg.owner_instance_id, "--raw"],
                    check=False,
                )
        except QualificationGuardError as exc:
            raise CycleError(str(exc)) from exc
        atomic_text(
            self.run_dir / "owner-start-output.txt",
            f"returncode={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}\n",
        )
        self.wait_for_owner_takeover()
        self.monitor_owner_dwell()
        self.stop_owner_and_prove(phase="normal")
        if not self.wait_for_auto_resume():
            self.guarded_fallback_start()
        self.immediate = machine_summary(self.query_machine(), self.query_reports())
        atomic_json(self.run_dir / "reliability-immediate.json", self.immediate)

    def cleanup(self) -> None:
        if not self.cycle_started:
            atomic_json(
                self.run_dir / "cleanup.json",
                {"at": utc_now(), "complete": True, "errors": [], "mutations_attempted": False},
            )
            return
        self.unlisted_proved = False
        try:
            self.unlist_then_prove()
        except Exception as exc:  # noqa: BLE001
            self.cleanup_errors.append(f"unlist/prove absence: {exc}")
        if self.owner_stop_authorized:
            try:
                self.stop_owner_and_prove(phase="cleanup")
            except Exception as exc:  # noqa: BLE001
                self.cleanup_errors.append(f"stop exact owner standby: {exc}")
        else:
            self.cleanup_errors.append("stop exact owner standby: explicit authorization absent")
        if self.destroy_client_authorized:
            if self.cleanup_errors:
                self.cleanup_errors.append("destroy controlled client: skipped because an earlier cleanup proof failed")
            else:
                try:
                    self.destroy_controlled_client()
                except Exception as exc:  # noqa: BLE001
                    self.cleanup_errors.append(f"destroy controlled client: {exc}")
        atomic_json(
            self.run_dir / "cleanup.json",
            {
                "at": utc_now(),
                "complete": not self.cleanup_errors,
                "errors": self.cleanup_errors,
                "owner_standby_retained": True,
                "controlled_client_destroyed": self.controlled_client_destroyed,
            },
        )


def preview(cfg: Config, host: Cli, client: Cli, run_dir: Path) -> None:
    cycle = StandbyCycle(cfg, host, client, run_dir)
    summary = cycle.preflight()
    # Preview proves current absence if already unlisted but never requires it:
    # apply always issues unlist as its first mutation and then proves absence.
    current_offers = {kind: cycle.query_offers(kind) for kind in ("bid", "on-demand")}
    plan = {
        "at": utc_now(),
        "experimental": True,
        "production_ready": False,
        "original_reliability_baseline": cfg.original_reliability_baseline,
        "observed_reliability": summary["reliability"],
        "allow_degraded_diagnostic": cfg.allow_degraded_diagnostic,
        "first_mutation": ["unlist", "machine", cfg.machine_id],
        "offer_absence_proof_samples": 3,
        "owner_start": ["start", "instance", cfg.owner_instance_id, "--raw"],
        "reclaim_slo_seconds": cfg.reclaim_slo_seconds,
        "owner_stop": ["stop", "instance", cfg.owner_instance_id, "--raw"],
        "automatic_resume_wait_seconds": cfg.auto_resume_seconds,
        "fallback_start_enabled": cfg.allow_controlled_client_fallback_start,
        "destroy_controlled_client_on_cleanup": cfg.destroy_controlled_client_on_cleanup,
        "current_exact_offer_views": current_offers,
        "outside_contract_gate": (
            "apply also requires --contracts-reviewed; any unknown target-machine account record aborts"
        ),
    }
    atomic_json(run_dir / "dry-run-plan.json", plan)
    print(f"DRY RUN passed exact read-only preflight. Private plan: {run_dir / 'dry-run-plan.json'}")


def build_result(cycle: StandbyCycle, cycle_error: str | None, rating_gate: bool) -> dict[str, Any]:
    baseline_at_original = bool(
        cycle.baseline
        and original_reliability_assessment(
            cycle.cfg.original_reliability_baseline, cycle.baseline
        )["at_or_above_original"]
    )
    return {
        "at": utc_now(),
        "experimental": True,
        "diagnostic_mode": (
            "degraded-disposable" if cycle.cfg.allow_degraded_diagnostic else "baseline-protected"
        ),
        "production_ready": False,
        "cycle_error": cycle_error,
        "owner_running_within_slo": bool(
            cycle.owner_running_observed
            and cycle.owner_running_elapsed_seconds is not None
            and cycle.owner_running_elapsed_seconds <= cycle.cfg.reclaim_slo_seconds
        ),
        "owner_running_elapsed_seconds": cycle.owner_running_elapsed_seconds,
        "owner_stopped_observed": cycle.owner_stopped_observed,
        "automatic_resume_observed": cycle.auto_resume_observed,
        "fallback_start_used": cycle.fallback_start_used,
        "controlled_client_destroyed": cycle.controlled_client_destroyed,
        "cleanup_complete": not cycle.cleanup_errors,
        "original_reliability_baseline": cycle.cfg.original_reliability_baseline,
        "pre_mutation_at_or_above_original": baseline_at_original,
        "rating_gate": rating_gate,
        "blocking_reasons": [
            "one experimental cycle never establishes production readiness",
            *(
                ["degraded diagnostic bypass was used; this run can never establish readiness"]
                if cycle.cfg.allow_degraded_diagnostic
                else []
            ),
            *(["automatic renter return was not observed"] if not cycle.auto_resume_observed else []),
            *(["immutable-original reliability gate did not pass"] if not rating_gate else []),
        ],
        "baseline": cycle.baseline or {},
        "immediate": cycle.immediate or {},
        "post_cleanup": cycle.post_cleanup or {},
        "delayed": cycle.delayed or {},
    }


def parse_args(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--machine-id", required=True)
    parser.add_argument("--owner-instance-id", required=True)
    parser.add_argument("--owner-label", required=True)
    parser.add_argument("--client-instance-id", required=True)
    parser.add_argument("--client-label", required=True)
    parser.add_argument("--host-cli", default="vastai")
    parser.add_argument("--client-cli", required=True, help="separately authenticated executable/wrapper")
    parser.add_argument("--original-reliability-baseline", type=float, required=True)
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    parser.add_argument("--reclaim-slo-seconds", type=int, default=MAX_RECLAIM_SLO_SECONDS)
    parser.add_argument("--owner-dwell-seconds", type=int, default=60)
    parser.add_argument("--owner-stop-timeout-seconds", type=int, default=120)
    parser.add_argument("--auto-resume-seconds", type=int, default=180)
    parser.add_argument("--delayed-seconds", type=int, default=7200)
    parser.add_argument(
        "--skip-delayed-observation",
        action="store_true",
        help=(
            "record delayed reliability as unavailable when a documented infrastructure "
            "deadline makes the two-hour observation impossible"
        ),
    )
    parser.add_argument("--contracts-reviewed", action="store_true")
    parser.add_argument(
        "--allow-degraded-diagnostic",
        action="store_true",
        help="explicitly permit an already-degraded disposable-host diagnostic; never establishes readiness",
    )
    parser.add_argument("--allow-controlled-client-fallback-start", action="store_true")
    parser.add_argument("--destroy-controlled-client-on-cleanup", action="store_true")
    parser.add_argument("--apply", action="store_true")
    return Config(**vars(parser.parse_args(argv)))


def run_locked(cfg: Config, root: Path) -> int:
    run_dir = root / "controlled-owner-standby-cycles" / dt.datetime.now(dt.timezone.utc).strftime(
        "%Y%m%dT%H%M%S.%fZ"
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        run_dir.chmod(0o700)
    except OSError:
        pass
    atomic_json(run_dir / "config.json", dataclasses.asdict(cfg) | {"experimental": True})
    atomic_json(
        run_dir / "original-reliability-baseline-source.json",
        load_or_pin_original_reliability_baseline(root, cfg),
    )
    host = Cli(cfg.host_cli, "host/owner")
    client = Cli(cfg.client_cli, "controlled client")
    if Path(host.executable).resolve() == Path(client.executable).resolve():
        raise CycleError("host/owner and client must use distinct pre-authenticated CLI executables")
    cycle = StandbyCycle(cfg, host, client, run_dir)
    if not cfg.apply:
        preview(cfg, host, client, run_dir)
        return 0
    try:
        require_qualification_mode_inactive(
            root,
            machine_id=cfg.machine_id,
            action="owner standby preemption cycle",
        )
    except QualificationGuardError as exc:
        raise CycleError(str(exc)) from exc
    if not sys.stdin.isatty():
        raise CycleError("refusing mutations without an interactive terminal")
    for signal_name in ("SIGINT", "SIGTERM", "SIGHUP"):
        if hasattr(signal, signal_name):
            signal.signal(getattr(signal, signal_name), lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    expected = (
        f"CYCLE OWNER {cfg.owner_instance_id} CLIENT {cfg.client_instance_id} ON {cfg.machine_id}"
    )
    if input(f"Type {expected}: ") != expected:
        raise CycleError("cycle confirmation did not match")
    stop_expected = f"STOP OWNER {cfg.owner_instance_id}"
    if input(f"Type {stop_expected}: ") != stop_expected:
        raise CycleError("owner cleanup confirmation did not match")
    cycle.owner_stop_authorized = True
    if cfg.allow_controlled_client_fallback_start:
        fallback_expected = f"FALLBACK START CONTROLLED {cfg.client_instance_id}"
        if input(f"Type {fallback_expected}: ") != fallback_expected:
            raise CycleError("controlled-client fallback confirmation did not match")
        cycle.fallback_start_authorized = True
    if cfg.destroy_controlled_client_on_cleanup:
        destroy_expected = f"DESTROY CONTROLLED {cfg.client_instance_id}"
        if input(f"Type {destroy_expected}: ") != destroy_expected:
            raise CycleError("controlled-client destroy confirmation did not match")
        cycle.destroy_client_authorized = True

    cycle_error: str | None = None
    try:
        cycle.run()
    except Exception as exc:  # noqa: BLE001 - every failure enters guarded cleanup
        cycle_error = str(exc)
    finally:
        cycle.cleanup()

    if cycle.cycle_started and not cycle.cleanup_errors:
        try:
            cycle.post_cleanup = machine_summary(cycle.query_machine(), cycle.query_reports())
            atomic_json(run_dir / "reliability-post-cleanup.json", cycle.post_cleanup)
            # Delayed evidence is meaningful only after an observed takeover and
            # cleanup.  Degraded diagnostics still record it, but can never pass
            # the immutable-original gate.
            if cycle.owner_running_observed and not cfg.skip_delayed_observation:
                time.sleep(cfg.delayed_seconds)
                cycle.delayed = machine_summary(cycle.query_machine(), cycle.query_reports())
                atomic_json(run_dir / "reliability-delayed.json", cycle.delayed)
            elif cycle.owner_running_observed:
                atomic_json(
                    run_dir / "reliability-delayed-skipped.json",
                    {
                        "at": utc_now(),
                        "skipped": True,
                        "reason": "explicit infrastructure runtime deadline before two-hour observation",
                    },
                )
            else:
                atomic_json(
                    run_dir / "reliability-delayed-skipped.json",
                    {"at": utc_now(), "skipped": True, "reason": "owner takeover was not observed"},
                )
        except Exception as exc:  # noqa: BLE001
            cycle_error = cycle_error or f"reliability observation failed: {exc}"

    rating_gate = rating_gate_passes(
        cfg.original_reliability_baseline,
        cycle.baseline or {},
        cycle.immediate or {},
        cycle.post_cleanup or {},
        cycle.delayed or {},
    )
    result = build_result(cycle, cycle_error, rating_gate)
    atomic_json(run_dir / "result.json", result)
    print(f"Private experimental result: {run_dir / 'result.json'}")
    technical_success = bool(
        cycle_error is None
        and not cycle.cleanup_errors
        and result["owner_running_within_slo"]
        and cycle.auto_resume_observed
        and not cycle.fallback_start_used
    )
    return 0 if technical_success else 1


def main(argv: list[str] | None = None) -> int:
    project = Path(__file__).resolve().parents[1]
    cfg = parse_args(argv)
    validate_config(cfg)
    root = state_root(project)
    lock = root / "controlled-owner-standby-cycle.lock"
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise CycleError(f"another owner-standby cycle may be active: {lock}") from exc
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
