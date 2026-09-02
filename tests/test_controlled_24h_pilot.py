import datetime as dt
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.controlled_24h_pilot import (
    MAX_RECLAIM_SECONDS,
    MAX_SAMPLE_GAP_SECONDS,
    AUTO_RETURN_SECONDS,
    ClientSpec,
    Config,
    CycleError,
    EvidenceCommands,
    Pilot,
    atomic_json,
    build_billing_report,
    build_plan,
    parse_client_spec,
    require_client_identity,
    require_exact_inventories,
    require_owner_identity,
    validate_client_evidence,
    validate_config,
    validate_host_contract_evidence,
    validate_host_telemetry,
    validate_billing_evidence,
    validate_owner_evidence,
)
from tools.verification_guard import qualification_interlock_path


CLIENTS = tuple(ClientSpec(str(7001 + index), f"sqwish-client-{index + 1}") for index in range(4))
GPU_IDS = [f"GPU-controlled-{index:02d}" for index in range(4)]
DIGESTS = [f"{index + 1:064x}" for index in range(8)]


def config(**changes):
    values = {
        "machine_id": "9001",
        "owner_instance_id": "6001",
        "owner_label": "sqwish-owner-standby",
        "clients": CLIENTS,
        "host_cli": "host-vastai",
        "client_cli": "client-vastai",
        "client_evidence_command": "client-evidence",
        "owner_evidence_command": "owner-evidence",
        "host_telemetry_command": "host-telemetry",
        "host_contract_evidence_command": "host-contract-evidence",
        "owner_charges_command": "owner-charges",
        "client_charges_command": "client-charges",
        "host_earnings_command": "host-earnings",
        "self_test_passed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "original_reliability_baseline": 0.91,
    }
    values.update(changes)
    return Config(**values)


def owner_record(**changes):
    value = {
        "id": 6001,
        "machine_id": 9001,
        "label": "sqwish-owner-standby",
        "is_bid": False,
        "num_gpus": 4,
        "actual_status": "stopped",
        "intended_status": "stopped",
        "cur_state": "stopped",
    }
    value.update(changes)
    return value


def client_record(index, **changes):
    value = {
        "id": 7001 + index,
        "machine_id": 9001,
        "label": f"sqwish-client-{index + 1}",
        "is_bid": True,
        "num_gpus": 1,
        "actual_status": "running",
        "intended_status": "running",
        "cur_state": "running",
        "end_date": 9_999_999_999,
    }
    value.update(changes)
    return value


def client_evidence(index, sequence=10, **changes):
    value = {
        "instance_id": str(7001 + index),
        "label": f"sqwish-client-{index + 1}",
        "running": True,
        "gpu_uuids": [GPU_IDS[index]],
        "checkpoint": {"sequence": sequence, "digest": DIGESTS[index]},
        "last_completed_task": f"task-{sequence}",
    }
    value.update(changes)
    return value


def owner_evidence(ready=True, sequence=10, **changes):
    value = {
        "owner_instance_id": "6001",
        "machine_id": "9001",
        "label": "sqwish-owner-standby",
        "ready": ready,
        "gpu_count": 4,
        "gpu_uuids": GPU_IDS,
        "checkpoint": {"sequence": sequence, "digest": DIGESTS[7]},
    }
    value.update(changes)
    return value


def host_telemetry(**changes):
    value = {
        "machine_id": "9001",
        "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "daemon_healthy": True,
        "gpus": [
            {
                "uuid": GPU_IDS[index],
                "temperature_c": 55 + index,
                "power_w": 200,
                "power_limit_w": 600,
                "throttled": False,
                "throttle_reasons": [],
                "ecc_uncorrectable": 0,
                "xid_errors": 0,
            }
            for index in range(4)
        ],
        "storage": {
            "root_healthy": True,
            "root_free_gb": 40,
            "docker_healthy": True,
            "docker_total_gb": 1500,
            "docker_free_gb": 500,
            "docker_dedicated_drive": True,
            "docker_ssd": True,
        },
        "network": {
            "download_mbps": 1000,
            "upload_mbps": 1000,
            "public_ipv4": True,
            "wired": True,
        },
        "ports": {"forwarded_count": 400, "reachable_count": 400},
        "platform": {
            "driver_version": "580.65.06",
            "cuda_version": "13.0",
            "kernel_version": "6.8.0-79-generic",
            "kernel_security_patched": True,
            "ubuntu_server": True,
            "ubuntu_version": "24.04.3",
            "secure_boot_disabled": True,
            "ssh_keys_only": True,
            "unique_ssh_host_key": True,
            "physical_cpu_cores": 32,
            "cpu_avx": True,
            "identical_supported_gpus": True,
            "pcie_healthy": True,
            "cpu_healthy": True,
            "ram_healthy": True,
            "no_unrelated_background_services": True,
            "vm_support_enabled": False,
        },
    }
    value.update(changes)
    return value


def host_contract_evidence(**changes):
    value = {
        "machine_id": "9001",
        "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "inventory_complete": True,
        "owner_standby": {
            "instance_id": "6001",
            "machine_id": "9001",
            "label": "sqwish-owner-standby",
            "is_bid": False,
            "num_gpus": 4,
            "safely_stopped": True,
        },
        "controlled_contracts": [
            {
                "instance_id": spec.instance_id,
                "machine_id": "9001",
                "label": spec.label,
                "is_bid": True,
                "num_gpus": 1,
                "active": True,
            }
            for spec in CLIENTS
        ],
        "outside_on_demand_or_reserved": False,
        "unknown_contract_ids": [],
        "source": "operator-vetted-host-contract-adapter",
    }
    value.update(changes)
    return value


def billing_evidence(role, *, gpu=10.0, storage=2.0, bandwidth=1.0, **changes):
    ids = ["6001"] if role == "owner-charges" else [spec.instance_id for spec in CLIENTS]
    value = {
        "role": role,
        "machine_id": "9001",
        "instance_ids": ids,
        "currency": "USD",
        "cumulative": True,
        "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "totals": {
            "gpu_usd": gpu,
            "storage_usd": storage,
            "bandwidth_usd": bandwidth,
        },
        "source": f"operator-vetted-{role}",
    }
    value.update(changes)
    return value


class FakeCli:
    def __init__(self, interlock_root=None):
        self.run_calls = []
        self.interlock_root = interlock_root
        self.interlock_seen_during_owner_start = False

    def run(self, args, **_kwargs):
        self.run_calls.append(args)
        if args[:3] == ["start", "instance", "6001"]:
            self.interlock_seen_during_owner_start = bool(
                self.interlock_root
                and qualification_interlock_path(self.interlock_root).is_dir()
            )
        return SimpleNamespace(returncode=0, stdout='{"success": true}', stderr="")

    def json(self, _args, **_kwargs):
        return []


class FakeEvidence:
    def client(self, _spec, _phase, _cycle):
        raise AssertionError("unexpected callback")

    def owner(self, _phase, _cycle):
        raise AssertionError("unexpected callback")

    def host_telemetry(self, _phase, _cycle):
        raise AssertionError("unexpected callback")

    def host_contracts(self, _phase, _cycle):
        raise AssertionError("unexpected callback")

    def owner_charges(self, _phase):
        raise AssertionError("unexpected callback")

    def client_charges(self, _phase):
        raise AssertionError("unexpected callback")

    def host_earnings(self, _phase):
        raise AssertionError("unexpected callback")


class ProgressEvidence:
    def __init__(self):
        self.sequence = {spec.instance_id: 0 for spec in CLIENTS}
        self.frozen_id = None

    def client(self, spec, _phase, _cycle):
        index = int(spec.instance_id) - 7001
        if spec.instance_id != self.frozen_id:
            self.sequence[spec.instance_id] += 1
        sequence = self.sequence[spec.instance_id]
        return {
            "instance_id": spec.instance_id,
            "label": spec.label,
            "running": True,
            "gpu_uuids": [GPU_IDS[index]],
            "checkpoint": {
                "sequence": sequence,
                "digest": f"{100 + index * 10 + sequence:064x}",
            },
            "last_completed_task": f"task-{sequence}",
        }

    def owner(self, _phase, _cycle):
        raise AssertionError("unexpected callback")

    def host_telemetry(self, _phase, _cycle):
        raise AssertionError("unexpected callback")

    def host_contracts(self, _phase, _cycle):
        raise AssertionError("unexpected callback")

    def owner_charges(self, _phase):
        raise AssertionError("unexpected callback")

    def client_charges(self, _phase):
        raise AssertionError("unexpected callback")

    def host_earnings(self, _phase):
        raise AssertionError("unexpected callback")


class HandoffPilot(Pilot):
    def __init__(self, root, run_dir):
        self.events = []
        super().__init__(
            config(),
            FakeCli(interlock_root=root),
            FakeCli(),
            FakeEvidence(),
            root,
            run_dir,
            sleep=lambda _seconds: None,
            monotonic=self.clock,
        )
        self.now = 100.0
        self.mode_boundary_crossed = True
        self.owner_stop_authorized = True

    def clock(self):
        return self.now

    def score_sample(self, phase):
        self.events.append(f"score:{phase}")
        return {"reliability": 0.92, "verification": "unverified"}

    def collect_client_evidence(
        self, phase, cycle, *, prior=None, require_resume_digest=False
    ):
        self.events.append(f"clients:{phase}")
        self.client_evidence_events.append((phase, cycle))
        result = {}
        for index, spec in enumerate(self.cfg.clients):
            result[spec.instance_id] = {
                "instance_id": spec.instance_id,
                "label": spec.label,
                "running": True,
                "gpu_uuids": [GPU_IDS[index]],
                "checkpoint": {
                    "sequence": 11 if prior else 10,
                    "digest": DIGESTS[index],
                },
            }
        return result

    def capture_host_telemetry(self, phase, cycle):
        self.events.append(f"telemetry:{phase}:{cycle}")
        self.telemetry_keys.add((phase, cycle))
        self.telemetry_events.append((phase, cycle))
        self.expected_host_gpu_ids = set(GPU_IDS)
        return host_telemetry()

    def capture_host_contract_evidence(self, phase, cycle):
        self.events.append(f"contracts:{phase}:{cycle}")
        self.contract_evidence_cycles.add(cycle)
        self.contract_evidence_events.append((phase, cycle))
        return host_contract_evidence()

    def unlist_and_prove(self):
        self.events.append("unlist-absence")
        self.mutations_started = True

    def inventories(self):
        self.events.append("inventories")
        return owner_record(), [client_record(index) for index in range(4)]

    def wait_for_platform_takeover(self, cycle, decision):
        self.events.append("platform-takeover")

    def wait_for_owner_ready(self, cycle, decision, expected_gpu_ids):
        self.events.append("owner-ready")
        self.now += 80
        return validate_owner_evidence(owner_evidence(), self.cfg, require_ready=True)

    def owner_dwell(self, cycle, initial):
        self.events.append("owner-dwell")
        return validate_owner_evidence(owner_evidence(sequence=11), self.cfg, require_ready=True)

    def stop_owner_and_prove(self, cycle, *, cleanup=False):
        self.events.append("owner-stop")

    def wait_for_all_auto_return(self, cycle):
        self.events.append("all-auto-return")


class SlowSafetyGatesPilot(HandoffPilot):
    def unlist_and_prove(self):
        super().unlist_and_prove()
        self.now += MAX_RECLAIM_SECONDS + 0.1


class ScorePilot(Pilot):
    def __init__(self, root):
        super().__init__(
            config(),
            FakeCli(),
            FakeCli(),
            FakeEvidence(),
            root,
            root / "run",
        )
        self.reliability = 0.92
        self.verification = "verified"

    def query_machine(self):
        return {
            "id": 9001,
            "reliability2": self.reliability,
            "verification": self.verification,
            "error_description": "",
            "vm_error_level": 0,
            "vm_error_msg": "",
            "num_reports": 0,
            "num_recent_reports": 0,
        }

    def query_reports(self):
        return []


class ProgressPilot(Pilot):
    def _client_record_map(self):
        return {str(7001 + index): client_record(index) for index in range(4)}


class CadencePilot(Pilot):
    def __init__(self, root, *, oversleep=0.0):
        self.now = 0.0
        self.oversleep = oversleep
        super().__init__(
            config(),
            FakeCli(),
            FakeCli(),
            FakeEvidence(),
            root,
            root / "run",
            sleep=self.advance,
            monotonic=lambda: self.now,
        )
        self.started_at = 0.0

    def advance(self, seconds):
        self.now += seconds + self.oversleep

    def _record_periodic_evidence(self, label):
        self.contract_evidence_events.append((label, 0))
        self.telemetry_events.append((label, 0))
        self.telemetry_keys.add((label, 0))
        self.client_evidence_events.append((label, 0))

    def qualification_sample(self, label):
        self._record_periodic_evidence(label)

    def capture_host_contract_evidence(self, phase, cycle):
        self.contract_evidence_events.append((phase, cycle))
        return host_contract_evidence()

    def capture_host_telemetry(self, phase, cycle):
        self.telemetry_events.append((phase, cycle))
        self.telemetry_keys.add((phase, cycle))
        return host_telemetry()

    def score_sample(self, _phase):
        return {"reliability": 0.92, "verification": "unverified"}

    def collect_client_evidence(self, phase, cycle, **_kwargs):
        self.client_evidence_events.append((phase, cycle))
        return {}

    def capture_due_delayed_observations(self):
        return None


class CleanupReturnFailurePilot(HandoffPilot):
    def wait_for_all_auto_return(self, cycle):
        self.events.append("all-auto-return-failed")
        raise CycleError("synthetic automatic-return failure")


class ConfigAndIdentityTests(unittest.TestCase):
    def test_config_requires_exact_four_one_gpu_clients(self):
        validate_config(config())
        for changed in (
            {"clients": CLIENTS[:3]},
            {"expected_client_count": 3, "clients": CLIENTS[:3]},
            {"gpu_count": 3},
            {"handoff_cycles": 1},
            {"handoff_cycles": 2},
            {"handoff_cycles": 4},
            {"original_reliability_baseline": float("nan")},
            {"reclaim_slo_seconds": MAX_RECLAIM_SECONDS + 1},
        ):
            with self.subTest(changed=changed), self.assertRaises(CycleError):
                validate_config(config(**changed))

    def test_config_rejects_duplicate_ids_labels_and_owner_collision(self):
        duplicate_id = CLIENTS[:3] + (ClientSpec(CLIENTS[0].instance_id, "another-client"),)
        duplicate_label = CLIENTS[:3] + (ClientSpec("7999", CLIENTS[0].label),)
        owner_collision = CLIENTS[:3] + (ClientSpec("6001", "owner-collision"),)
        for clients in (duplicate_id, duplicate_label, owner_collision):
            with self.subTest(clients=clients), self.assertRaises(CycleError):
                validate_config(config(clients=clients))

    def test_client_spec_parser_is_exact_and_safe(self):
        self.assertEqual(parse_client_spec("7001:sqwish-client-1"), CLIENTS[0])
        for value in ("7001", "zero:valid-label", "0:valid-label", "7001:x"):
            with self.subTest(value=value), self.assertRaises(Exception):
                parse_client_spec(value)

    def test_owner_and_clients_require_exact_identity_type_and_gpu_count(self):
        cfg = config()
        require_owner_identity(owner_record(), cfg)
        for changed in ({"is_bid": True}, {"num_gpus": 1}, {"label": "wrong-owner"}):
            with self.subTest(changed=changed), self.assertRaises(CycleError):
                require_owner_identity(owner_record(**changed), cfg)
        require_client_identity(client_record(0), CLIENTS[0], cfg)
        for changed in ({"is_bid": False}, {"num_gpus": 2}, {"machine_id": 9999}):
            with self.subTest(changed=changed), self.assertRaises(CycleError):
                require_client_identity(client_record(0, **changed), CLIENTS[0], cfg)

    def test_exact_inventory_passes_and_orders_four_slices(self):
        owner, clients = require_exact_inventories(
            [owner_record()],
            [client_record(index) for index in reversed(range(4))],
            config(),
            now_epoch=1_000,
        )
        self.assertEqual(owner["id"], 6001)
        self.assertEqual([row["id"] for row in clients], [7001, 7002, 7003, 7004])

    def test_inventory_rejects_missing_extra_high_priority_and_short_contract(self):
        valid = [client_record(index) for index in range(4)]
        cases = (
            valid[:3],
            valid + [client_record(0, id=7999, label="unknown-bid")],
            valid + [client_record(0, id=7999, label="outside-ondemand", is_bid=False)],
            [*valid[:3], client_record(3, end_date=1_001)],
        )
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(CycleError):
                require_exact_inventories([owner_record()], rows, config(), now_epoch=1_000)

    def test_apply_requires_manual_contract_review(self):
        with self.assertRaisesRegex(CycleError, "contracts-reviewed"):
            validate_config(config(apply=True))
        validate_config(config(apply=True, contracts_reviewed=True))

    def test_self_test_attestation_must_be_recent_timezone_aware_iso(self):
        recent = dt.datetime.now(dt.timezone.utc)
        validate_config(config(self_test_passed_at=recent.isoformat()))
        invalid = (
            "not-a-date",
            recent.replace(tzinfo=None).isoformat(),
            (recent - dt.timedelta(hours=7)).isoformat(),
            (recent + dt.timedelta(minutes=2)).isoformat(),
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaisesRegex(CycleError, "self-test"):
                validate_config(config(self_test_passed_at=value))

    def test_auto_return_timeout_cannot_exceed_five_minutes(self):
        validate_config(config(auto_return_seconds=AUTO_RETURN_SECONDS))
        with self.assertRaisesRegex(CycleError, "300 seconds"):
            validate_config(config(auto_return_seconds=AUTO_RETURN_SECONDS + 1))


class WorkloadEvidenceTests(unittest.TestCase):
    def test_client_before_evidence_requires_exact_identity_running_and_one_gpu(self):
        normalized = validate_client_evidence(client_evidence(0), CLIENTS[0])
        self.assertEqual(normalized["gpu_uuids"], [GPU_IDS[0]])
        for changed in (
            {"instance_id": "9999"},
            {"label": "wrong-label"},
            {"running": False},
            {"gpu_uuids": []},
            {"gpu_uuids": [GPU_IDS[0], GPU_IDS[1]]},
        ):
            with self.subTest(changed=changed), self.assertRaises(CycleError):
                validate_client_evidence(client_evidence(0, **changed), CLIENTS[0])

    def test_client_resume_requires_sequence_digest_and_same_gpu_continuity(self):
        prior = validate_client_evidence(client_evidence(0), CLIENTS[0])
        valid = client_evidence(
            0,
            sequence=11,
            checkpoint={"sequence": 11, "digest": DIGESTS[4]},
            resumed_from_digest=DIGESTS[0],
        )
        after = validate_client_evidence(
            valid, CLIENTS[0], prior=prior, require_resume_digest=True
        )
        self.assertEqual(after["checkpoint"]["sequence"], 11)
        invalid = (
            {**valid, "checkpoint": {"sequence": 10, "digest": DIGESTS[4]}},
            {**valid, "resumed_from_digest": DIGESTS[1]},
            {**valid, "gpu_uuids": [GPU_IDS[1]]},
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(CycleError):
                validate_client_evidence(
                    value,
                    CLIENTS[0],
                    prior=prior,
                    require_resume_digest=True,
                )

    def test_periodic_progress_needs_advancement_but_not_resume_digest(self):
        prior = validate_client_evidence(client_evidence(0), CLIENTS[0])
        current = client_evidence(
            0,
            sequence=11,
            checkpoint={"sequence": 11, "digest": DIGESTS[4]},
        )
        value = validate_client_evidence(current, CLIENTS[0], prior=prior)
        self.assertNotIn("resumed_from_digest", value)

    def test_client_evidence_requires_nonempty_completed_task(self):
        for task in (None, "", "   ", 7):
            with self.subTest(task=task), self.assertRaisesRegex(
                CycleError, "last_completed_task"
            ):
                validate_client_evidence(
                    client_evidence(0, last_completed_task=task), CLIENTS[0]
                )

    def test_checkpoint_schema_rejects_bool_sequence_and_non_sha256_digest(self):
        for checkpoint in (
            {"sequence": True, "digest": DIGESTS[0]},
            {"sequence": -1, "digest": DIGESTS[0]},
            {"sequence": 1, "digest": "not-a-digest"},
        ):
            with self.subTest(checkpoint=checkpoint), self.assertRaises(CycleError):
                validate_client_evidence(
                    client_evidence(0, checkpoint=checkpoint), CLIENTS[0]
                )

    def test_owner_ready_schema_requires_exact_four_unique_gpu_set(self):
        value = validate_owner_evidence(owner_evidence(), config(), require_ready=True)
        self.assertEqual(set(value["gpu_uuids"]), set(GPU_IDS))
        for changed in (
            {"owner_instance_id": "9999"},
            {"machine_id": "9999"},
            {"ready": False},
            {"gpu_count": True},
            {"gpu_uuids": GPU_IDS[:3]},
            {"gpu_uuids": [GPU_IDS[0]] * 4},
        ):
            with self.subTest(changed=changed), self.assertRaises(CycleError):
                validate_owner_evidence(owner_evidence(**changed), config(), require_ready=True)


class HostEvidenceTests(unittest.TestCase):
    def test_host_telemetry_covers_all_strict_health_and_manual_gates(self):
        value = validate_host_telemetry(host_telemetry(), config())
        self.assertEqual({row["uuid"] for row in value["gpus"]}, set(GPU_IDS))
        self.assertTrue(value["storage"]["docker_dedicated_drive"])
        self.assertTrue(value["network"]["public_ipv4"])
        self.assertEqual(value["platform"]["physical_cpu_cores"], 32)
        self.assertIs(value["platform"]["vm_support_enabled"], False)

    def test_host_telemetry_fails_each_material_health_class(self):
        mutations = []

        def case(mutator):
            value = copy.deepcopy(host_telemetry())
            mutator(value)
            mutations.append(value)

        case(lambda value: value.update(daemon_healthy=False))
        case(lambda value: value["gpus"][0].update(temperature_c=90))
        case(lambda value: value["gpus"][0].update(throttled=True))
        case(lambda value: value["gpus"][0].update(ecc_uncorrectable=1))
        case(lambda value: value["gpus"][0].update(xid_errors=1))
        case(lambda value: value["gpus"][0].update(power_w=601))
        case(lambda value: value["storage"].update(root_free_gb=19))
        case(lambda value: value["storage"].update(docker_dedicated_drive=False))
        case(lambda value: value["network"].update(upload_mbps=499))
        case(lambda value: value["ports"].update(reachable_count=19))
        case(lambda value: value["platform"].update(cuda_version="11.7"))
        case(lambda value: value["platform"].update(physical_cpu_cores=7))
        case(lambda value: value["platform"].update(secure_boot_disabled=False))
        case(lambda value: value["platform"].update(kernel_security_patched=False))
        case(lambda value: value["platform"].update(ubuntu_server=False))
        case(lambda value: value["platform"].update(cpu_avx=False))
        case(lambda value: value["platform"].update(pcie_healthy=False))
        case(lambda value: value["platform"].update(cpu_healthy=False))
        case(lambda value: value["platform"].update(ram_healthy=False))
        case(lambda value: value["platform"].update(no_unrelated_background_services=False))
        case(lambda value: value["gpus"][1].update(uuid=GPU_IDS[0]))
        for value in mutations:
            with self.subTest(value=value), self.assertRaises(CycleError):
                validate_host_telemetry(value, config())

    def test_host_telemetry_requires_fresh_stable_exact_gpu_identity(self):
        stale = host_telemetry(
            observed_at=(dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=3)).isoformat()
        )
        with self.assertRaisesRegex(CycleError, "older"):
            validate_host_telemetry(stale, config())
        with self.assertRaisesRegex(CycleError, "identity changed"):
            validate_host_telemetry(
                host_telemetry(), config(), expected_gpu_ids={*GPU_IDS[:3], "GPU-other-99"}
            )

    def test_host_contract_adapter_requires_exact_four_and_no_outside_contract(self):
        value = validate_host_contract_evidence(host_contract_evidence(), config())
        self.assertEqual(
            [row["instance_id"] for row in value["controlled_contracts"]],
            ["7001", "7002", "7003", "7004"],
        )
        invalid = []
        outside = copy.deepcopy(host_contract_evidence())
        outside["outside_on_demand_or_reserved"] = True
        invalid.append(outside)
        unknown = copy.deepcopy(host_contract_evidence())
        unknown["unknown_contract_ids"] = ["7999"]
        invalid.append(unknown)
        missing = copy.deepcopy(host_contract_evidence())
        missing["controlled_contracts"].pop()
        invalid.append(missing)
        wrong_type = copy.deepcopy(host_contract_evidence())
        wrong_type["controlled_contracts"][0]["is_bid"] = False
        invalid.append(wrong_type)
        incomplete = copy.deepcopy(host_contract_evidence())
        incomplete["inventory_complete"] = False
        invalid.append(incomplete)
        owner_active = copy.deepcopy(host_contract_evidence())
        owner_active["owner_standby"]["safely_stopped"] = False
        invalid.append(owner_active)
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(CycleError):
                validate_host_contract_evidence(item, config())

    def test_billing_views_require_exact_scopes_and_build_five_line_report(self):
        cfg = config()
        baseline = {
            role: validate_billing_evidence(
                billing_evidence(role, raw_account_records=[{"api_key": "do-not-store"}]),
                cfg,
                role=role,
            )
            for role in (
                "owner-charges",
                "controlled-client-charges",
                "host-earnings",
            )
        }
        self.assertTrue(all("raw_account_records" not in item for item in baseline.values()))
        final = {
            "owner-charges": validate_billing_evidence(
                billing_evidence("owner-charges", gpu=10.0, storage=2.5, bandwidth=1.25),
                cfg,
                role="owner-charges",
            ),
            "controlled-client-charges": validate_billing_evidence(
                billing_evidence(
                    "controlled-client-charges", gpu=12.0, storage=3.0, bandwidth=1.5
                ),
                cfg,
                role="controlled-client-charges",
            ),
            "host-earnings": validate_billing_evidence(
                billing_evidence("host-earnings", gpu=11.5, storage=2.8, bandwidth=1.4),
                cfg,
                role="host-earnings",
            ),
        }
        report = build_billing_report(baseline, final)
        self.assertEqual(report["owner_own_machine_gpu_charge_usd"], 0.0)
        self.assertEqual(report["owner_standby_storage_and_bandwidth_charge_usd"], 0.75)
        self.assertEqual(report["controlled_renter_gpu_storage_bandwidth_charge_usd"], 3.5)
        self.assertEqual(report["host_gpu_storage_bandwidth_earnings_usd"], 2.7)
        self.assertEqual(report["net_controlled_test_leakage_usd"], 0.8)

        wrong_scope = billing_evidence("owner-charges", instance_ids=["7001"])
        with self.assertRaisesRegex(CycleError, "exact expected instances"):
            validate_billing_evidence(wrong_scope, cfg, role="owner-charges")
        regressed = copy.deepcopy(final)
        regressed["host-earnings"]["totals"]["gpu_usd"] = 9.0
        with self.assertRaisesRegex(CycleError, "regressed"):
            build_billing_report(baseline, regressed)

    def test_callback_environment_drops_credentials(self):
        with patch.dict(
            os.environ,
            {
                "PATH": "safe-path",
                "HOME": "safe-home",
                "VAST_API_KEY": "must-not-leak",
                "AWS_SECRET_ACCESS_KEY": "must-not-leak",
                "RANDOM_TOKEN": "must-not-leak",
            },
            clear=True,
        ):
            environment = EvidenceCommands.sanitized_env()
        self.assertEqual(environment["PATH"], "safe-path")
        self.assertEqual(environment["HOME"], "safe-home")
        self.assertEqual(environment["PYTHONIOENCODING"], "utf-8")
        self.assertNotIn("VAST_API_KEY", environment)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", environment)
        self.assertNotIn("RANDOM_TOKEN", environment)

    def test_every_callback_is_shell_free_and_receives_only_sanitized_env(self):
        with patch.dict(
            os.environ,
            {"PATH": "safe-path", "VAST_API_KEY": "must-not-leak"},
            clear=True,
        ), patch(
            "tools.controlled_24h_pilot.shutil.which", return_value="/safe/adapter"
        ), patch(
            "tools.controlled_24h_pilot.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout="{}", stderr=""),
        ) as run:
            adapters = EvidenceCommands(config())
            adapters.client(CLIENTS[0], "phase", 1)
            adapters.owner("phase", 1)
            adapters.host_telemetry("phase", 1)
            adapters.host_contracts("phase", 1)
            adapters.owner_charges("phase")
            adapters.client_charges("phase")
            adapters.host_earnings("phase")
        self.assertEqual(run.call_count, 7)
        callback_argv = [call.args[0] for call in run.call_args_list]
        self.assertTrue(any("owner-charges" in argv for argv in callback_argv))
        self.assertTrue(any("controlled-client-charges" in argv for argv in callback_argv))
        self.assertTrue(any("host-earnings" in argv for argv in callback_argv))
        for call in run.call_args_list:
            positional, keywords = call
            self.assertIsInstance(positional[0], list)
            self.assertNotIn("shell", keywords)
            self.assertNotIn("VAST_API_KEY", keywords["env"])
            self.assertEqual(keywords["env"]["PATH"], "safe-path")

    def test_structured_persistence_keeps_digests_gpu_ids_and_long_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evidence.json"
            long_label = "sqwish-" + "a" * 45
            atomic_json(
                path,
                {
                    "label": long_label,
                    "gpu_uuids": GPU_IDS,
                    "checkpoint": {"digest": DIGESTS[0]},
                    "resumed_from_digest": DIGESTS[1],
                    "ssh_keys_only": True,
                    "unique_ssh_host_key": True,
                    "api_key": "this-secret-must-disappear",
                    "untrusted": "x" * 64,
                    "operator_email": "operator@example.test",
                    "observed_address": "203.0.113.21",
                    "raw_json": (
                        '{"api_key":"tiny","password":"x","ssh_key":"s",'
                        '"email":"operator@example.test","ip":"203.0.113.21"}'
                    ),
                },
            )
            value = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(value["label"], long_label)
        self.assertEqual(value["gpu_uuids"], GPU_IDS)
        self.assertEqual(value["checkpoint"]["digest"], DIGESTS[0])
        self.assertEqual(value["resumed_from_digest"], DIGESTS[1])
        self.assertIs(value["ssh_keys_only"], True)
        self.assertIs(value["unique_ssh_host_key"], True)
        self.assertEqual(value["api_key"], "<redacted>")
        self.assertEqual(value["untrusted"], "<redacted-token>")
        self.assertEqual(value["operator_email"], "<redacted-email>")
        self.assertEqual(value["observed_address"], "<redacted-ip>")
        self.assertNotIn("tiny", value["raw_json"])
        self.assertNotIn('"x"', value["raw_json"])
        self.assertNotIn('"s"', value["raw_json"])
        self.assertNotIn("operator@example.test", value["raw_json"])
        self.assertNotIn("203.0.113.21", value["raw_json"])


class HoldAndOrderingTests(unittest.TestCase):
    def marker(self, root, **changes):
        value = {
            "schema": 1,
            "active": True,
            "machine_id": "9001",
            "allowed_stopped_owner_standbys": [
                {"instance_id": "6001", "label": "sqwish-owner-standby"}
            ],
        }
        value.update(changes)
        (root / "qualification-mode.json").write_text(json.dumps(value), encoding="utf-8")

    def test_preflight_requires_exact_active_hold_before_any_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pilot = Pilot(
                config(), FakeCli(), FakeCli(), FakeEvidence(), root, root / "run"
            )
            with self.assertRaisesRegex(CycleError, "qualification HOLD"):
                pilot.preflight()
            self.assertEqual(pilot.host.run_calls, [])

    def test_wrong_machine_or_unnamed_owner_hold_fails_closed(self):
        for changes in (
            {"machine_id": "9999"},
            {"allowed_stopped_owner_standbys": []},
            {"active": False},
            {"schema": True},
        ):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.marker(root, **changes)
                pilot = Pilot(
                    config(), FakeCli(), FakeCli(), FakeEvidence(), root, root / "run"
                )
                with self.assertRaises(CycleError):
                    pilot.preflight()

    def test_handoff_orders_callbacks_unlist_start_takeover_stop_and_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pilot = HandoffPilot(root, root / "run")
            result = pilot.handoff(1)
            events = pilot.events
            expected_order = [
                "telemetry:before-handoff:1",
                "score:cycle-1-before",
                "clients:before-handoff",
                "unlist-absence",
                "inventories",
                "contracts:before-handoff:1",
                "platform-takeover",
                "owner-ready",
                "owner-dwell",
                "owner-stop",
                "all-auto-return",
                "clients:after-return",
                "telemetry:immediate-after-handoff:1",
                "score:cycle-1-immediate",
            ]
            cursor = -1
            for event in expected_order:
                cursor = events.index(event, cursor + 1)
            self.assertEqual(pilot.host.run_calls[0][:3], ["start", "instance", "6001"])
            self.assertTrue(pilot.host.interlock_seen_during_owner_start)
            self.assertFalse(qualification_interlock_path(root).exists())
            self.assertTrue(result["within_15_minutes"])
            self.assertEqual(result["automatic_returns"], 4)
            self.assertFalse(result["host_job_or_create_job"])

    def test_recreated_hold_blocks_later_handoff_before_owner_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.marker(root)
            pilot = HandoffPilot(root, root / "run")
            with self.assertRaisesRegex(CycleError, "qualification mode is active"):
                pilot.handoff(2)
            self.assertEqual(pilot.host.run_calls, [])
            self.assertEqual(pilot.events, [])

    def test_scheduler_request_clock_includes_safety_gates_before_owner_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pilot = SlowSafetyGatesPilot(root, root / "run")
            with self.assertRaisesRegex(CycleError, "safety gates exhausted"):
                pilot.handoff(1)
            self.assertEqual(pilot.host.run_calls, [])
            self.assertIn("unlist-absence", pilot.events)
            self.assertNotIn("platform-takeover", pilot.events)

    def test_score_gate_rejects_reliability_and_verification_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pilot = ScorePilot(root)
            pilot.arm_baseline = pilot.score_sample("baseline")
            pilot.reliability = 0.91
            with self.assertRaisesRegex(CycleError, "qualification-trend arm starting value"):
                pilot.score_sample("rating-drop")
            pilot.reliability = 0.92
            pilot.verification = "unverified"
            with self.assertRaisesRegex(CycleError, "verification regressed"):
                pilot.score_sample("verification-drop")

    def test_score_gate_rejects_rise_then_partial_fall_from_prior_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pilot = ScorePilot(root)
            pilot.arm_baseline = pilot.score_sample("baseline")
            pilot.reliability = 0.95
            pilot.score_sample("rise")
            pilot.reliability = 0.94
            with self.assertRaisesRegex(CycleError, "immediately prior observation"):
                pilot.score_sample("partial-fall")

    def test_cycle_specific_score_gate_rejects_immediate_or_delayed_regression(self):
        reference = {"reliability": 0.95, "verification": "verified"}
        with self.assertRaisesRegex(CycleError, "cycle pre-score"):
            Pilot.require_score_not_regressed(
                reference,
                {"reliability": 0.94, "verification": "verified"},
                context="cycle 1 immediate sample",
            )
        with self.assertRaisesRegex(CycleError, "verification regressed"):
            Pilot.require_score_not_regressed(
                reference,
                {"reliability": 0.95, "verification": "unverified"},
                context="cycle 1 delayed sample",
            )

    def test_qualification_soak_allows_only_low_score_and_insufficient_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.marker(root)
            pilot = HandoffPilot(root, root / "run")
            low_new_host = {
                "observable_prerequisites_pass": False,
                "blockers": ["reliability", "steady_uptime_history"],
                "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "platform_verification": "unverified",
                "checks": {
                    "reliability": {"actual": 0.60},
                    "steady_uptime_history": {
                        "actual": {"trend_status": "insufficient-history"}
                    }
                },
            }
            with patch(
                "tools.controlled_24h_pilot.sample_qualification_mode",
                return_value=low_new_host,
            ):
                pilot.qualification_sample("qualification-soak")
            self.assertIn("score:qualification-soak", pilot.events)
            self.assertIn("clients:qualification-soak", pilot.events)

    def test_qualification_soak_aborts_health_and_actual_trend_regression(self):
        cases = (
            {
                "observable_prerequisites_pass": False,
                "blockers": ["machine_errors"],
                "checks": {},
            },
            {
                "observable_prerequisites_pass": False,
                "blockers": ["steady_uptime_history"],
                "checks": {
                    "steady_uptime_history": {
                        "actual": {"trend_status": "observed-regression"}
                    }
                },
            },
        )
        for assessment in cases:
            with self.subTest(assessment=assessment), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.marker(root)
                pilot = HandoffPilot(root, root / "run")
                with patch(
                    "tools.controlled_24h_pilot.sample_qualification_mode",
                    return_value=assessment,
                ), self.assertRaisesRegex(CycleError, "unsafe observable blockers"):
                    pilot.qualification_sample("qualification-soak")
                self.assertEqual(pilot.events, [])

    def test_qualification_guard_score_is_part_of_global_monotonic_chain(self):
        assessment = {
            "observable_prerequisites_pass": False,
            "blockers": ["reliability", "steady_uptime_history"],
            "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "platform_verification": "unverified",
            "checks": {
                "reliability": {"actual": 0.69},
                "steady_uptime_history": {
                    "actual": {"trend_status": "insufficient-history"}
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.marker(root)
            pilot = HandoffPilot(root, root / "run")
            pilot.last_score = {"reliability": 0.70, "verification": "unverified"}
            with patch(
                "tools.controlled_24h_pilot.sample_qualification_mode",
                return_value=assessment,
            ), self.assertRaisesRegex(CycleError, "cycle pre-score"):
                pilot.qualification_sample("qualification-soak")

    def test_plan_explicitly_separates_modes_and_owner_on_demand_from_host_jobs(self):
        plan = build_plan(config())
        self.assertEqual(plan["duration_seconds"], 86_400)
        self.assertEqual(plan["qualification_hold_seconds"], 43_200)
        self.assertEqual(plan["owner"]["type"], "on-demand")
        self.assertFalse(plan["host_job_or_create_job"])
        self.assertFalse(plan["mode_boundary"]["owner_workloads_verification_safe"])
        self.assertIn(
            "every five-minute",
            plan["evidence_callback_contracts"]["host_contracts"]["required_phases"],
        )
        self.assertEqual(
            plan["evidence_callback_contracts"]["billing"]["required_components"],
            ["gpu_usd", "storage_usd", "bandwidth_usd"],
        )

    def test_technical_evidence_gate_requires_every_cycle_phase_and_both_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pilot = HandoffPilot(root, root / "run")
            pilot.telemetry_keys = {
                ("preflight", 0),
                ("qualification-soak", 0),
                ("research-observation", 0),
                ("final", 0),
            }
            pilot.periodic_segments = [
                {"mode": "qualification", "complete": True, "samples": [{"sample": 1}]},
                {"mode": "research", "complete": True, "samples": [{"sample": 1}]},
            ]
            pilot.telemetry_events = [
                ("qualification-soak", 0),
                ("research-observation", 0),
            ]
            pilot.client_evidence_events = [
                ("qualification-soak", 0),
                ("research-observation", 0),
            ]
            pilot.contract_evidence_events = [
                ("preflight", 0),
                ("final", 0),
                ("qualification-soak", 0),
                ("research-observation", 0),
            ]
            for cycle in range(1, 4):
                pilot.telemetry_keys.update(
                    {
                        ("before-handoff", cycle),
                        ("immediate-after-handoff", cycle),
                        ("two-hour-delayed", cycle),
                    }
                )
                pilot.contract_evidence_events.append(("before-handoff", cycle))
            pilot.contract_evidence_cycles = {0, 1, 2, 3}
            self.assertTrue(pilot.periodic_completion_gate())
            self.assertTrue(pilot.telemetry_completion_gate())
            self.assertTrue(pilot.contract_completion_gate())
            self.assertTrue(pilot.client_evidence_completion_gate())
            pilot.telemetry_keys.remove(("two-hour-delayed", 2))
            self.assertFalse(pilot.telemetry_completion_gate())
            pilot.contract_evidence_events.remove(("before-handoff", 3))
            self.assertFalse(pilot.contract_completion_gate())

    def test_cleanup_retains_exact_records_and_never_claims_full_pilot_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pilot = HandoffPilot(root, root / "run")
            pilot.mutations_started = True
            pilot.cleanup()
            payload = json.loads((root / "run" / "cleanup.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["controller_safety_cleanup_complete"])
            self.assertFalse(payload["full_pilot_cleanup_complete"])
            self.assertTrue(payload["owner_standby_retained"])
            self.assertEqual(len(payload["controlled_clients_retained"]), 4)
            self.assertFalse(any("destroy" in " ".join(call) for call in pilot.client.run_calls))

    def test_periodic_collection_persists_all_client_progress_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = ProgressEvidence()
            pilot = ProgressPilot(
                config(),
                FakeCli(),
                FakeCli(),
                evidence,
                root,
                root / "run",
            )
            first = pilot.collect_client_evidence("qualification-soak", 0)
            second = pilot.collect_client_evidence("qualification-soak", 0)
            evidence_files = list((root / "run" / "workload-evidence").glob("*.json"))
            self.assertEqual(len(evidence_files), 2)
            self.assertNotEqual(evidence_files[0].name, evidence_files[1].name)
            self.assertTrue(
                all(
                    second[item]["checkpoint"]["sequence"]
                    > first[item]["checkpoint"]["sequence"]
                    for item in second
                )
            )
            evidence.frozen_id = "7003"
            stable_before_failure = pilot.last_client_evidence
            with self.assertRaisesRegex(CycleError, "did not advance"):
                pilot.collect_client_evidence("qualification-soak", 0)
            self.assertIs(pilot.last_client_evidence, stable_before_failure)

    def test_periodic_segments_enforce_cadence_and_all_three_evidence_streams(self):
        with tempfile.TemporaryDirectory() as tmp:
            pilot = CadencePilot(Path(tmp))
            pilot.observe_until(1_200, "qualification")
            pilot.observe_until(2_400, "research")
            self.assertEqual(pilot.periodic_sample_total("qualification"), 3)
            self.assertEqual(pilot.periodic_sample_total("research"), 3)
            self.assertTrue(pilot.periodic_completion_gate())
            self.assertTrue(pilot.periodic_evidence_complete(pilot.telemetry_events))
            self.assertTrue(pilot.periodic_evidence_complete(pilot.contract_evidence_events))
            self.assertTrue(pilot.periodic_evidence_complete(pilot.client_evidence_events))

        with tempfile.TemporaryDirectory() as tmp:
            pilot = CadencePilot(Path(tmp), oversleep=MAX_SAMPLE_GAP_SECONDS)
            with self.assertRaisesRegex(CycleError, "cadence gap"):
                pilot.observe_until(1_200, "qualification")

    def test_apply_horizon_resets_once_and_stays_fixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = [1000.0]
            pilot = Pilot(
                config(),
                FakeCli(),
                FakeCli(),
                FakeEvidence(),
                root,
                root / "run",
                wall_time=lambda: now[0],
            )
            preview_horizon = pilot.required_end_epoch
            now[0] = 5000.0
            pilot.pin_apply_horizon()
            apply_horizon = pilot.required_end_epoch
            self.assertGreater(apply_horizon, preview_horizon)
            now[0] = 9000.0
            self.assertEqual(pilot.required_end_epoch, apply_horizon)
            with self.assertRaisesRegex(CycleError, "already pinned"):
                pilot.pin_apply_horizon()

    def test_hold_disable_attempt_enters_guarded_cleanup_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pilot = HandoffPilot(root, root / "run")
            pilot.qualification_sample = lambda _label: None
            pilot.last_score = {"reliability": 0.92}
            with patch(
                "tools.controlled_24h_pilot.disable_qualification_mode",
                side_effect=CycleError("synthetic partial disable"),
            ), self.assertRaisesRegex(CycleError, "synthetic partial disable"):
                pilot.cross_mode_boundary()
            self.assertTrue(pilot.mutations_started)

    def test_cleanup_waits_for_all_clients_after_any_owner_start_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pilot = HandoffPilot(root, root / "run")
            pilot.mutations_started = True
            pilot.owner_start_attempted = True
            pilot.cleanup()
            self.assertLess(pilot.events.index("owner-stop"), pilot.events.index("all-auto-return"))
            payload = json.loads((root / "run" / "cleanup.json").read_text(encoding="utf-8"))
            self.assertTrue(payload["controller_safety_cleanup_complete"])

    def test_cleanup_return_timeout_prevents_safety_completion_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pilot = CleanupReturnFailurePilot(root, root / "run")
            pilot.mutations_started = True
            pilot.owner_start_attempted = True
            pilot.cleanup()
            payload = json.loads((root / "run" / "cleanup.json").read_text(encoding="utf-8"))
            self.assertFalse(payload["controller_safety_cleanup_complete"])
            self.assertTrue(
                any("wait for all controlled clients" in error for error in payload["errors"])
            )


if __name__ == "__main__":
    unittest.main()
