#!/usr/bin/env python3
"""Destroy only the four exact controlled-client records retained by a pilot.

This is a deliberately narrow post-pilot cleanup tool.  It never lists a
machine, stops or destroys the reusable owner standby, or searches for records
to delete.  The caller names the one owner record and all four authorized
controlled-client records.  A restart may find any subset of those client
records already absent, but every record that is still visible must be in that
allowlist and match its exact identity.

Dry-run is the default.  Apply requires an interactive terminal, a fresh manual
Contracts review flag, exact typed confirmation, three unlisted samples, and a
fresh operator-vetted host-contract attestation.  A pending external marker
survives failed or interrupted cleanup.  Resuming it requires an explicit flag
and a second exact typed acknowledgement.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Protocol

try:
    from tools.controlled_hostjob_cycle import (
        Cli,
        CycleError,
        atomic_json,
        authenticated_account_id,
        exact_machine,
        exact_record,
        identifier,
        is_safely_stopped,
        mutation_explicitly_succeeded,
        single_instance_is_explicitly_absent,
        strict_instance_records,
        strict_offer_records,
    )
except ModuleNotFoundError:  # Direct ``python tools/...`` execution.
    from controlled_hostjob_cycle import (  # type: ignore[no-redef]
        Cli,
        CycleError,
        atomic_json,
        authenticated_account_id,
        exact_machine,
        exact_record,
        identifier,
        is_safely_stopped,
        mutation_explicitly_succeeded,
        single_instance_is_explicitly_absent,
        strict_instance_records,
        strict_offer_records,
    )


GPU_COUNT = 4
CLIENT_COUNT = 4
ATTESTATION_MAX_AGE_SECONDS = 120
SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{7,79}$")
SAFE_SOURCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/()\-]{0,119}$")
LONG_SECRETISH_RE = re.compile(r"[A-Za-z0-9_-]{32,}")
SENSITIVE_SOURCE_RE = re.compile(
    r"(?:api[_ -]?key|token|password|credential|private[_ -]?key|secret)", re.I
)
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
    host_cli: str = "vastai"
    client_cli: str = ""
    host_contract_evidence_command: str = ""
    poll_seconds: float = 2.0
    destroy_poll_attempts: int = 6
    callback_timeout_seconds: int = 30
    contracts_reviewed: bool = False
    resume_unresolved: bool = False
    apply: bool = False


class CliLike(Protocol):
    executable: str

    def run(
        self, args: list[str], *, check: bool = True
    ) -> subprocess.CompletedProcess[str]: ...

    def json(self, args: list[str], *, check: bool = True) -> Any: ...


class ContractEvidenceLike(Protocol):
    def host_contracts(
        self, present: tuple[ClientSpec, ...], phase: str
    ) -> dict[str, Any]: ...


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


def validate_config(cfg: Config) -> None:
    _positive_id(cfg.machine_id, "machine ID")
    _positive_id(cfg.owner_instance_id, "owner instance ID")
    if not SAFE_LABEL_RE.fullmatch(cfg.owner_label):
        raise CycleError("owner label must be an exact safe label of 8-80 characters")
    if len(cfg.clients) != CLIENT_COUNT:
        raise CycleError("cleanup requires exactly four authorized controlled clients")
    ids = [spec.instance_id for spec in cfg.clients]
    labels = [spec.label for spec in cfg.clients]
    if len(set(ids)) != CLIENT_COUNT or len(set(labels)) != CLIENT_COUNT:
        raise CycleError("controlled client IDs and labels must each be distinct")
    if cfg.owner_instance_id in ids:
        raise CycleError("owner instance ID may never be a controlled client ID")
    if not cfg.host_cli.strip() or not cfg.client_cli.strip():
        raise CycleError("two pre-authenticated CLI wrapper paths are required")
    if not cfg.host_contract_evidence_command.strip():
        raise CycleError("a host-contract evidence executable is required")
    if not 1 <= cfg.poll_seconds <= 5:
        raise CycleError("poll interval must be between one and five seconds")
    if not 1 <= cfg.destroy_poll_attempts <= 12:
        raise CycleError("destroy poll attempts must be between one and twelve")
    if not 1 <= cfg.callback_timeout_seconds <= 120:
        raise CycleError("callback timeout must be between one and 120 seconds")
    if cfg.apply and not cfg.contracts_reviewed:
        raise CycleError("apply requires --contracts-reviewed after a fresh Host Contracts review")


def _parse_recent_attestation(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CycleError(f"{what} must be a timezone-aware ISO timestamp")
    try:
        observed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise CycleError(f"{what} must be a timezone-aware ISO timestamp") from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise CycleError(f"{what} must include a timezone")
    observed = observed.astimezone(dt.timezone.utc)
    now = dt.datetime.now(dt.timezone.utc)
    age = (now - observed).total_seconds()
    if age < -30:
        raise CycleError(f"{what} is implausibly in the future")
    if age > ATTESTATION_MAX_AGE_SECONDS:
        raise CycleError(f"{what} is older than {ATTESTATION_MAX_AGE_SECONDS} seconds")
    return observed.isoformat()


def _strict_json_object(stdout: str, what: str) -> dict[str, Any]:
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise CycleError(f"{what} returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise CycleError(f"{what} must return one JSON object")
    return value


class ContractEvidence:
    """Execute one fixed, operator-reviewed adapter without a shell."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        resolved = shutil.which(cfg.host_contract_evidence_command)
        if not resolved:
            raise CycleError(
                "host contract evidence executable not found: "
                f"{cfg.host_contract_evidence_command}"
            )
        self.executable = resolved

    @staticmethod
    def sanitized_env() -> dict[str, str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in SAFE_CALLBACK_ENV_NAMES and isinstance(value, str)
        }
        environment["PYTHONIOENCODING"] = "utf-8"
        return environment

    def host_contracts(
        self, present: tuple[ClientSpec, ...], phase: str
    ) -> dict[str, Any]:
        args = [
            "--machine-id",
            self.cfg.machine_id,
            "--owner-instance-id",
            self.cfg.owner_instance_id,
            "--phase",
            phase,
        ]
        for spec in present:
            args.extend(["--expected-client", f"{spec.instance_id}:{spec.label}"])
        result = subprocess.run(
            [self.executable, *args],
            text=True,
            capture_output=True,
            check=False,
            timeout=self.cfg.callback_timeout_seconds,
            env=self.sanitized_env(),
        )
        if result.returncode != 0:
            raise CycleError(
                f"host contract evidence callback failed with status {result.returncode}"
            )
        return _strict_json_object(result.stdout, "host contract evidence callback")


def require_owner_identity(record: dict[str, Any], cfg: Config) -> None:
    failed = [
        name
        for name, okay in {
            "instance ID": identifier(record) == cfg.owner_instance_id,
            "machine ID": str(record.get("machine_id", "")) == cfg.machine_id,
            "label": record.get("label") == cfg.owner_label,
            "on-demand type": record.get("is_bid") is False,
            "four-GPU shape": record.get("num_gpus") == GPU_COUNT,
            "safely stopped state": is_safely_stopped(record),
        }.items()
        if not okay
    ]
    if failed:
        raise CycleError("owner standby identity/state mismatch: " + ", ".join(failed))


def require_client_identity(
    record: dict[str, Any], spec: ClientSpec, cfg: Config
) -> None:
    failed = [
        name
        for name, okay in {
            "instance ID": identifier(record) == spec.instance_id,
            "machine ID": str(record.get("machine_id", "")) == cfg.machine_id,
            "label": record.get("label") == spec.label,
            "interruptible type": record.get("is_bid") is True,
            "one-GPU shape": record.get("num_gpus") == 1,
        }.items()
        if not okay
    ]
    if failed:
        raise CycleError(
            f"controlled client {spec.instance_id} identity mismatch: " + ", ".join(failed)
        )


def validate_host_contract_evidence(
    value: Any,
    cfg: Config,
    present: tuple[ClientSpec, ...],
) -> dict[str, Any]:
    """Require a complete, fresh host-side inventory for the exact live subset."""

    if not isinstance(value, dict):
        raise CycleError("host contract evidence must be one JSON object")
    if str(value.get("machine_id", "")) != cfg.machine_id:
        raise CycleError("host contract evidence machine identity mismatch")
    observed_at = _parse_recent_attestation(
        value.get("observed_at"), "host contract evidence observed_at"
    )
    if value.get("inventory_complete") is not True:
        raise CycleError("host contract inventory must be explicitly complete")
    if value.get("outside_on_demand_or_reserved") is not False:
        raise CycleError("host contract evidence does not exclude outside priority work")
    if value.get("outside_contract_ids") != []:
        raise CycleError("host contract evidence contains an outside contract")
    if value.get("unknown_contract_ids") != []:
        raise CycleError("host contract evidence contains an unknown contract")
    source = value.get("source")
    if (
        not isinstance(source, str)
        or not SAFE_SOURCE_RE.fullmatch(source)
        or LONG_SECRETISH_RE.search(source)
        or SENSITIVE_SOURCE_RE.search(source)
    ):
        raise CycleError("host contract evidence source attestation is missing")
    owner = value.get("owner_standby")
    if not isinstance(owner, dict) or (
        str(owner.get("instance_id", "")) != cfg.owner_instance_id
        or str(owner.get("machine_id", "")) != cfg.machine_id
        or owner.get("label") != cfg.owner_label
        or owner.get("is_bid") is not False
        or owner.get("num_gpus") != GPU_COUNT
        or owner.get("safely_stopped") is not True
    ):
        raise CycleError("host contract evidence owner standby identity/state mismatch")

    expected = {spec.instance_id: spec for spec in present}
    rows = value.get("controlled_contracts")
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise CycleError("host contract evidence does not contain the exact remaining subset")
    normalized_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise CycleError("host controlled contract row must be an object")
        instance_id = str(row.get("instance_id", ""))
        spec = expected.get(instance_id)
        if spec is None or instance_id in seen:
            raise CycleError("host contract evidence has a duplicate or unauthorized client ID")
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
        raise CycleError("host contract evidence is missing a remaining controlled client")
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
            "num_gpus": GPU_COUNT,
            "safely_stopped": True,
        },
        "controlled_contracts": normalized_rows,
        "outside_on_demand_or_reserved": False,
        "outside_contract_ids": [],
        "unknown_contract_ids": [],
        "source": source,
    }


def _identity_payload(cfg: Config) -> dict[str, Any]:
    return {
        "machine_id": cfg.machine_id,
        "owner": {"instance_id": cfg.owner_instance_id, "label": cfg.owner_label},
        "clients": [dataclasses.asdict(spec) for spec in cfg.clients],
    }


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
        raise CycleError("VAST_STATE_DIR must be outside the repository")
    resolved.mkdir(parents=True, exist_ok=True)
    try:
        resolved.chmod(0o700)
    except OSError:
        pass
    return resolved


class Cleanup:
    def __init__(
        self,
        cfg: Config,
        host: CliLike,
        client: CliLike,
        evidence: ContractEvidenceLike,
        root: Path,
        run_dir: Path,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cfg = cfg
        self.host = host
        self.client = client
        self.evidence = evidence
        self.root = root
        self.run_dir = run_dir
        self.sleep = sleep
        self.spec_by_id = {spec.instance_id: spec for spec in cfg.clients}
        self.sequence = 0
        self.marker_path = (
            root / "controlled-24h-cleanup-state" / f"machine-{cfg.machine_id}.json"
        )

    def _write(self, relative: str, payload: Any) -> None:
        atomic_json(self.run_dir / relative, payload)

    def _read_marker(self) -> dict[str, Any] | None:
        if not self.marker_path.exists():
            return None
        try:
            value = json.loads(self.marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CycleError("cleanup state marker is unreadable; reconcile it manually") from exc
        if not isinstance(value, dict) or value.get("status") not in {"pending", "complete"}:
            raise CycleError("cleanup state marker is malformed; reconcile it manually")
        if value.get("identity") != _identity_payload(self.cfg):
            raise CycleError("cleanup marker identity differs from the requested exact IDs")
        if (
            value.get("credentials_persisted") is not False
            or value.get("owner_destroy_authorized") is not False
        ):
            raise CycleError("cleanup marker contains a forbidden authorization state")
        remaining = value.get("remaining_client_ids")
        authorized = set(self.spec_by_id)
        if (
            not isinstance(remaining, list)
            or any(not isinstance(item, str) for item in remaining)
            or len(remaining) != len(set(remaining))
            or not set(remaining).issubset(authorized)
        ):
            raise CycleError("cleanup marker has a malformed remaining-ID set")
        if not isinstance(value.get("attempts"), list):
            raise CycleError("cleanup marker attempts field is malformed")
        if value["status"] == "complete" and (
            remaining
            or value.get("final_client_inventory_empty") is not True
            or value.get("final_host_contracts_owner_only") is not True
        ):
            raise CycleError("complete cleanup marker lacks exact completion proof")
        return value

    def check_resume_gate(self) -> dict[str, Any] | None:
        marker = self._read_marker()
        if marker is None:
            if self.cfg.resume_unresolved:
                raise CycleError("--resume-unresolved was supplied but no cleanup marker exists")
            return None
        if marker["status"] == "complete":
            if self.cfg.resume_unresolved:
                raise CycleError("--resume-unresolved was supplied but the marker is complete")
            return marker
        if not self.cfg.resume_unresolved:
            raise CycleError(
                "an unresolved cleanup marker exists; inspect it and rerun with --resume-unresolved"
            )
        return marker

    def require_distinct_accounts(self) -> dict[str, str]:
        host_id = authenticated_account_id(self.host.json(["show", "user", "--raw"]))
        client_id = authenticated_account_id(self.client.json(["show", "user", "--raw"]))
        if host_id == client_id:
            raise CycleError("host/owner and controlled-client CLIs use the same Vast account")
        result = {"host_owner_account_id": host_id, "controlled_client_account_id": client_id}
        self._write("authenticated-accounts.json", result)
        return result

    def _query_machine(self) -> dict[str, Any]:
        machine = exact_machine(
            self.host.json(["show", "machine", self.cfg.machine_id, "--raw"]),
            self.cfg.machine_id,
        )
        if machine.get("num_gpus") != GPU_COUNT:
            raise CycleError("cleanup target must be the exact four-GPU machine")
        return machine

    def _query_offers(self, kind: str) -> list[dict[str, Any]]:
        query = f"machine_id={self.cfg.machine_id} verified=any rentable=any rented=any"
        return strict_offer_records(
            self.host.json(
                ["search", "offers", query, "--no-default", "--type", kind, "--raw"]
            ),
            kind,
        )

    def prove_offer_absence(self, *, samples: int, phase: str) -> None:
        for sample in range(1, samples + 1):
            for kind in ("bid", "on-demand"):
                if self._query_offers(kind):
                    raise CycleError(f"machine still exposes an exact {kind} offer")
            self.sequence += 1
            self._write(
                f"offer-absence/{self.sequence:04d}-{phase}-{sample}.json",
                {"sample": sample, "phase": phase, "bid": [], "on-demand": []},
            )
            if sample < samples:
                self.sleep(self.cfg.poll_seconds)

    def exact_inventory(
        self, *, expected_present: set[str] | None = None
    ) -> tuple[ClientSpec, ...]:
        """Validate all account views; return the exact authorized subset still present."""

        self._query_machine()
        host_rows = strict_instance_records(
            self.host.json(["show", "instances", "--raw"]),
            "host account instance response",
        )
        host_target = [
            row for row in host_rows if str(row.get("machine_id", "")) == self.cfg.machine_id
        ]
        if len(host_target) != 1 or identifier(host_target[0]) != self.cfg.owner_instance_id:
            raise CycleError("host inventory is not the exact stopped-owner-only target set")
        require_owner_identity(host_target[0], self.cfg)
        owner_single = exact_record(
            self.host.json(["show", "instance", self.cfg.owner_instance_id, "--raw"]),
            self.cfg.owner_instance_id,
            "owner standby",
        )
        require_owner_identity(owner_single, self.cfg)

        client_rows = strict_instance_records(
            self.client.json(["show", "instances", "--raw"]),
            "controlled-client full instance response",
        )
        actual: dict[str, dict[str, Any]] = {}
        for row in client_rows:
            instance_id = identifier(row)
            if instance_id in actual:
                raise CycleError("controlled-client full inventory contains a duplicate ID")
            spec = self.spec_by_id.get(instance_id)
            if spec is None:
                raise CycleError("controlled-client full inventory contains an unauthorized record")
            require_client_identity(row, spec, self.cfg)
            actual[instance_id] = row
        actual_ids = set(actual)
        if expected_present is not None and actual_ids != expected_present:
            raise CycleError("controlled-client inventory changed from the exact expected subset")

        # Both the single-record and complete-list views must agree for all four
        # authorized IDs, including IDs already absent during a resumed cleanup.
        for spec in self.cfg.clients:
            single = self.client.json(
                ["show", "instance", spec.instance_id, "--raw"], check=False
            )
            if spec.instance_id in actual_ids:
                single_record = exact_record(single, spec.instance_id, "controlled client")
                require_client_identity(single_record, spec, self.cfg)
            elif not single_instance_is_explicitly_absent(single, spec.instance_id):
                raise CycleError(
                    f"controlled client {spec.instance_id} absence is not explicit in its single view"
                )

        present = tuple(spec for spec in self.cfg.clients if spec.instance_id in actual_ids)
        self.sequence += 1
        self._write(
            f"inventories/{self.sequence:04d}.json",
            {
                "machine": {"machine_id": self.cfg.machine_id, "num_gpus": GPU_COUNT},
                "owner": {
                    "instance_id": self.cfg.owner_instance_id,
                    "machine_id": self.cfg.machine_id,
                    "label": self.cfg.owner_label,
                    "is_bid": False,
                    "num_gpus": GPU_COUNT,
                    "safely_stopped": True,
                },
                "present_clients": [dataclasses.asdict(spec) for spec in present],
                "full_client_inventory_exact": True,
            },
        )
        return present

    def attest_contracts(
        self, present: tuple[ClientSpec, ...], *, phase: str
    ) -> dict[str, Any]:
        normalized = validate_host_contract_evidence(
            self.evidence.host_contracts(present, phase), self.cfg, present
        )
        self.sequence += 1
        self._write(f"host-contracts/{self.sequence:04d}-{phase}.json", normalized)
        return normalized

    def preflight(self) -> tuple[ClientSpec, ...]:
        marker = self.check_resume_gate()
        self.require_distinct_accounts()
        present = self.exact_inventory()
        if marker is not None and marker.get("status") == "pending":
            marker_remaining = set(marker["remaining_client_ids"])
            actual = {spec.instance_id for spec in present}
            if not actual.issubset(marker_remaining):
                raise CycleError(
                    "a client previously recorded absent reappeared; manual reconciliation is required"
                )
        self.prove_offer_absence(samples=3, phase="preflight")
        self.attest_contracts(present, phase="preflight")
        self._write(
            "preflight.json",
            {
                "passed": True,
                "contracts_reviewed": self.cfg.contracts_reviewed,
                "present_client_ids": [spec.instance_id for spec in present],
                "already_absent_client_ids": [
                    spec.instance_id for spec in self.cfg.clients if spec not in present
                ],
            },
        )
        return present

    def begin_or_resume_marker(self, present: tuple[ClientSpec, ...]) -> None:
        marker = self._read_marker()
        prior_attempts = []
        if marker is not None and marker.get("status") == "pending":
            prior_attempts = marker.get("attempts", [])
            if not isinstance(prior_attempts, list):
                raise CycleError("pending cleanup marker attempts field is malformed")
        payload = {
            "status": "pending",
            "identity": _identity_payload(self.cfg),
            "remaining_client_ids": [spec.instance_id for spec in present],
            "attempts": [
                *prior_attempts,
                {"run_dir": str(self.run_dir), "resumed": self.cfg.resume_unresolved},
            ],
            "credentials_persisted": False,
            "owner_destroy_authorized": False,
        }
        atomic_json(self.marker_path, payload)
        self._write("marker-start.json", payload)

    def update_pending_marker(self, present: tuple[ClientSpec, ...]) -> None:
        marker = self._read_marker()
        if marker is None or marker.get("status") != "pending":
            raise CycleError("pending cleanup marker disappeared or changed during cleanup")
        marker["remaining_client_ids"] = [spec.instance_id for spec in present]
        marker["credentials_persisted"] = False
        marker["owner_destroy_authorized"] = False
        atomic_json(self.marker_path, marker)

    def _absence_from_full_view(self, value: Any, instance_id: str) -> bool:
        try:
            rows = strict_instance_records(value, "controlled-client full instance response")
        except CycleError:
            return False
        return all(identifier(row) != instance_id for row in rows)

    def destroy_one(self, spec: ClientSpec) -> str:
        if spec.instance_id == self.cfg.owner_instance_id:
            raise CycleError("owner standby may never be destroyed")
        if self.spec_by_id.get(spec.instance_id) != spec:
            raise CycleError("destroy target is not an exact authorized controlled client")
        marker = self._read_marker()
        if marker is None or marker.get("status") != "pending":
            raise CycleError("exact pending cleanup authorization is absent")
        if spec.instance_id not in marker["remaining_client_ids"]:
            raise CycleError("destroy target is absent from the pending cleanup authorization")
        result = self.client.run(
            ["destroy", "instance", spec.instance_id, "--yes", "--raw"], check=False
        )
        explicit_success = (
            result.returncode == 0 and mutation_explicitly_succeeded(result.stdout)
        )
        for attempt in range(1, self.cfg.destroy_poll_attempts + 1):
            single = self.client.json(
                ["show", "instance", spec.instance_id, "--raw"], check=False
            )
            full = self.client.json(["show", "instances", "--raw"], check=False)
            if single_instance_is_explicitly_absent(
                single, spec.instance_id
            ) and self._absence_from_full_view(full, spec.instance_id):
                method = (
                    "explicit-success-and-absence"
                    if explicit_success
                    else "absence-from-single-and-full-views"
                )
                self.sequence += 1
                self._write(
                    f"destroy-proofs/{self.sequence:04d}-{spec.instance_id}.json",
                    {
                        "instance_id": spec.instance_id,
                        "confirmed": True,
                        "method": method,
                        "poll_attempt": attempt,
                    },
                )
                return method
            if attempt < self.cfg.destroy_poll_attempts:
                self.sleep(self.cfg.poll_seconds)
        if explicit_success:
            raise CycleError(
                f"destroy for {spec.instance_id} reported success but exact absence was not proved"
            )
        raise CycleError(
            f"destroy for {spec.instance_id} lacked explicit success or exact two-view absence"
        )

    def destroy_remaining(self, initial: tuple[ClientSpec, ...]) -> dict[str, Any]:
        remaining = tuple(initial)
        marker = self._read_marker()
        if marker is None or marker.get("status") != "pending":
            raise CycleError("exact pending cleanup authorization is absent")
        if [spec.instance_id for spec in remaining] != marker["remaining_client_ids"]:
            raise CycleError("pending cleanup authorization differs from the requested remainder")
        destroyed: list[str] = []
        try:
            for spec in self.cfg.clients:
                if spec not in remaining:
                    continue
                expected = {item.instance_id for item in remaining}
                current = self.exact_inventory(expected_present=expected)
                self.prove_offer_absence(samples=1, phase=f"before-{spec.instance_id}")
                # This complete host-side attestation is deliberately the final
                # read before the exact-ID mutation.
                self.attest_contracts(current, phase=f"before-destroy-{spec.instance_id}")
                self.destroy_one(spec)
                destroyed.append(spec.instance_id)
                remaining = tuple(item for item in remaining if item != spec)
                self.update_pending_marker(remaining)

            final = self.exact_inventory(expected_present=set())
            if final:
                raise CycleError("final controlled-client inventory is not empty")
            self.prove_offer_absence(samples=3, phase="final")
            self.attest_contracts((), phase="final-owner-only")
        except Exception:
            # The pending marker is intentionally retained.  Do not guess which
            # mutation completed after an ambiguous response.
            raise

        marker = self._read_marker()
        if marker is None or marker.get("status") != "pending":
            raise CycleError("pending cleanup marker disappeared before completion")
        marker.update(
            {
                "status": "complete",
                "remaining_client_ids": [],
                "destroyed_in_this_run": destroyed,
                "final_client_inventory_empty": True,
                "final_host_contracts_owner_only": True,
                "credentials_persisted": False,
                "owner_destroy_authorized": False,
            }
        )
        atomic_json(self.marker_path, marker)
        self._write("result.json", marker)
        return marker


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
        help="repeat exact INSTANCE_ID:LABEL four times",
    )
    parser.add_argument("--host-cli", default="vastai")
    parser.add_argument("--client-cli", required=True)
    parser.add_argument("--host-contract-evidence-command", required=True)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--destroy-poll-attempts", type=int, default=6)
    parser.add_argument("--callback-timeout-seconds", type=int, default=30)
    parser.add_argument("--contracts-reviewed", action="store_true")
    parser.add_argument("--resume-unresolved", action="store_true")
    parser.add_argument("--apply", action="store_true")
    values = vars(parser.parse_args(argv))
    values["clients"] = tuple(values.pop("client"))
    return Config(**values)


def _confirmation(cfg: Config) -> str:
    ids = ",".join(spec.instance_id for spec in cfg.clients)
    return (
        f"DESTROY CLIENTS {ids} KEEP OWNER {cfg.owner_instance_id} "
        f"MACHINE {cfg.machine_id}"
    )


def _resume_confirmation(cfg: Config) -> str:
    return f"RESUME UNRESOLVED CLEANUP MACHINE {cfg.machine_id} KEEP OWNER {cfg.owner_instance_id}"


def run_locked(
    cfg: Config,
    root: Path,
    *,
    input_func: Callable[[str], str] = input,
    stdin_isatty: Callable[[], bool] = sys.stdin.isatty,
) -> int:
    run_dir = root / "controlled-24h-cleanups" / dt.datetime.now(
        dt.timezone.utc
    ).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir.mkdir(parents=True, exist_ok=False)
    try:
        run_dir.chmod(0o700)
    except OSError:
        pass
    atomic_json(run_dir / "config.json", _identity_payload(cfg))

    host = Cli(cfg.host_cli, "host/owner")
    client = Cli(cfg.client_cli, "controlled client")
    if Path(host.executable).resolve() == Path(client.executable).resolve():
        raise CycleError("host and client must use distinct credential-isolated CLI wrappers")
    cleanup = Cleanup(cfg, host, client, ContractEvidence(cfg), root, run_dir)
    present = cleanup.preflight()
    existing_marker = cleanup._read_marker()
    if existing_marker is not None and existing_marker.get("status") == "complete":
        print(
            "Exact-ID cleanup was already complete; fresh inventory, offer-absence, and "
            f"owner-only contract checks passed. Private evidence: {run_dir}"
        )
        return 0
    if not cfg.apply:
        print(
            "DRY RUN passed exact cleanup preflight; no Vast mutation was requested. "
            f"Private evidence: {run_dir}"
        )
        return 0
    if not stdin_isatty():
        raise CycleError("refusing cleanup apply without an interactive terminal")
    if input_func(f"Type {_confirmation(cfg)}: ") != _confirmation(cfg):
        raise CycleError("exact cleanup confirmation did not match")
    if cfg.resume_unresolved and input_func(
        f"Type {_resume_confirmation(cfg)}: "
    ) != _resume_confirmation(cfg):
        raise CycleError("unresolved cleanup resume acknowledgement did not match")
    cleanup.begin_or_resume_marker(present)
    try:
        result = cleanup.destroy_remaining(present)
    except Exception:
        atomic_json(
            run_dir / "result.json",
            {
                "status": "pending",
                "manual_reconcile_required": True,
                "marker": str(cleanup.marker_path),
                "credentials_persisted": False,
                "owner_destroy_authorized": False,
            },
        )
        raise
    print(
        "Exact-ID cleanup complete; all controlled-client records are absent and the "
        f"stopped owner remains. Private evidence: {run_dir / 'result.json'}"
    )
    return 0 if result.get("status") == "complete" else 1


def main(argv: list[str] | None = None) -> int:
    cfg = parse_args(argv)
    validate_config(cfg)
    project = Path(__file__).resolve().parents[1]
    root = resolve_state_root(project)
    lock = root / "controlled-24h-cleanup.lock"
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise CycleError(
            f"another cleanup may be active; reconcile the exact lock manually: {lock}"
        ) from exc
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
        raise SystemExit(1) from exc
