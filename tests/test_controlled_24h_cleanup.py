import datetime as dt
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.controlled_24h_cleanup import (
    Cleanup,
    ClientSpec,
    Config,
    CycleError,
    _identity_payload,
    validate_config,
)


CLIENTS = tuple(
    ClientSpec(str(7001 + index), f"sqwish-client-{index + 1}") for index in range(4)
)


def config(**changes):
    values = {
        "machine_id": "9001",
        "owner_instance_id": "6001",
        "owner_label": "sqwish-owner-standby",
        "clients": CLIENTS,
        "host_cli": "host-vastai",
        "client_cli": "client-vastai",
        "host_contract_evidence_command": "host-contract-evidence",
        "poll_seconds": 1,
        "destroy_poll_attempts": 2,
        "contracts_reviewed": True,
        "apply": True,
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
        "actual_status": "stopped",
        "intended_status": "stopped",
        "cur_state": "stopped",
    }
    value.update(changes)
    return value


class FakeCli:
    def __init__(self, role, state):
        self.role = role
        self.state = state
        self.executable = f"/{role}-credential-wrapper"
        self.destroy_calls = []

    def json(self, args, *, check=True):
        if args[:2] == ["show", "user"]:
            return [{"id": 101 if self.role == "host" else 202}]
        if self.role == "host":
            if args[:2] == ["show", "machine"]:
                return [{"id": 9001, "num_gpus": 4}]
            if args[:2] == ["show", "instances"]:
                return [self.state["owner"]]
            if args[:2] == ["show", "instance"]:
                return [self.state["owner"]]
            if args[:2] == ["search", "offers"]:
                return list(self.state.get("offers", []))
        else:
            if args[:2] == ["show", "instances"]:
                return list(self.state["clients"].values())
            if args[:2] == ["show", "instance"]:
                instance_id = str(args[2])
                record = self.state["clients"].get(instance_id)
                return [] if record is None else [record]
        raise AssertionError(f"unexpected {self.role} JSON command: {args}")

    def run(self, args, *, check=True):
        if self.role != "client" or args[:2] != ["destroy", "instance"]:
            raise AssertionError(f"unexpected {self.role} mutation: {args}")
        instance_id = str(args[2])
        self.destroy_calls.append(instance_id)
        if self.state.get("uncertain_destroy") == instance_id:
            return subprocess.CompletedProcess(args, 1, "not-json", "uncertain")
        self.state["clients"].pop(instance_id, None)
        if self.state.get("absence_only_destroy") == instance_id:
            return subprocess.CompletedProcess(args, 1, "not-json", "uncertain")
        return subprocess.CompletedProcess(args, 0, json.dumps({"success": True}), "")


class FakeContractEvidence:
    def __init__(self, cfg, *, outside=False):
        self.cfg = cfg
        self.outside = outside
        self.calls = []

    def host_contracts(self, present, phase):
        self.calls.append((phase, tuple(spec.instance_id for spec in present)))
        outside = ["8999"] if self.outside else []
        return {
            "machine_id": self.cfg.machine_id,
            "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "inventory_complete": True,
            "outside_on_demand_or_reserved": bool(outside),
            "outside_contract_ids": outside,
            "unknown_contract_ids": [],
            "source": "operator reviewed Host Contracts inventory",
            "owner_standby": {
                "instance_id": self.cfg.owner_instance_id,
                "machine_id": self.cfg.machine_id,
                "label": self.cfg.owner_label,
                "is_bid": False,
                "num_gpus": 4,
                "safely_stopped": True,
            },
            "controlled_contracts": [
                {
                    "instance_id": spec.instance_id,
                    "machine_id": self.cfg.machine_id,
                    "label": spec.label,
                    "is_bid": True,
                    "num_gpus": 1,
                    "active": True,
                }
                for spec in present
            ],
        }


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_cleanup(self, state=None, cfg=None, evidence=None):
        cfg = cfg or config()
        state = state or {
            "owner": owner_record(),
            "clients": {str(7001 + i): client_record(i) for i in range(4)},
            "offers": [],
        }
        host = FakeCli("host", state)
        client = FakeCli("client", state)
        evidence = evidence or FakeContractEvidence(cfg)
        run_dir = self.root / "run"
        run_dir.mkdir(exist_ok=True)
        cleanup = Cleanup(
            cfg,
            host,
            client,
            evidence,
            self.root,
            run_dir,
            sleep=lambda _seconds: None,
        )
        return cleanup, host, client, evidence, state

    def test_happy_path_destroys_only_four_exact_clients_and_keeps_owner(self):
        cleanup, _host, client, evidence, state = self.make_cleanup()
        initial = cleanup.preflight()
        cleanup.begin_or_resume_marker(initial)
        result = cleanup.destroy_remaining(initial)

        self.assertEqual(client.destroy_calls, ["7001", "7002", "7003", "7004"])
        self.assertNotIn("6001", client.destroy_calls)
        self.assertEqual(state["owner"], owner_record())
        self.assertEqual(state["clients"], {})
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["final_client_inventory_empty"])
        self.assertEqual(evidence.calls[-1], ("final-owner-only", ()))

    def test_identity_mismatch_refuses_before_any_destroy(self):
        state = {
            "owner": owner_record(),
            "clients": {str(7001 + i): client_record(i) for i in range(4)},
            "offers": [],
        }
        state["clients"]["7002"] = client_record(1, label="wrong-client-label")
        cleanup, _host, client, _evidence, _state = self.make_cleanup(state=state)
        with self.assertRaisesRegex(CycleError, "identity mismatch"):
            cleanup.preflight()
        self.assertEqual(client.destroy_calls, [])

    def test_unknown_extra_client_record_refuses_broad_cleanup(self):
        state = {
            "owner": owner_record(),
            "clients": {str(7001 + i): client_record(i) for i in range(4)},
            "offers": [],
        }
        state["clients"]["7999"] = client_record(
            0, id=7999, label="unapproved-client", machine_id=9999
        )
        cleanup, _host, client, _evidence, _state = self.make_cleanup(state=state)
        with self.assertRaisesRegex(CycleError, "unauthorized record"):
            cleanup.preflight()
        self.assertEqual(client.destroy_calls, [])

    def test_visible_offer_refuses_cleanup(self):
        state = {
            "owner": owner_record(),
            "clients": {str(7001 + i): client_record(i) for i in range(4)},
            "offers": [{"id": 3333, "machine_id": 9001}],
        }
        cleanup, _host, client, _evidence, _state = self.make_cleanup(state=state)
        with self.assertRaisesRegex(CycleError, "still exposes"):
            cleanup.preflight()
        self.assertEqual(client.destroy_calls, [])

    def test_host_adapter_outside_contract_refuses_cleanup(self):
        cfg = config()
        evidence = FakeContractEvidence(cfg, outside=True)
        cleanup, _host, client, _evidence, _state = self.make_cleanup(
            cfg=cfg, evidence=evidence
        )
        with self.assertRaisesRegex(CycleError, "outside priority work"):
            cleanup.preflight()
        self.assertEqual(client.destroy_calls, [])

    def test_uncertain_destroy_stops_and_retains_pending_marker(self):
        state = {
            "owner": owner_record(),
            "clients": {str(7001 + i): client_record(i) for i in range(4)},
            "offers": [],
            "uncertain_destroy": "7001",
        }
        cleanup, _host, client, _evidence, _state = self.make_cleanup(state=state)
        initial = cleanup.preflight()
        cleanup.begin_or_resume_marker(initial)
        with self.assertRaisesRegex(CycleError, "lacked explicit success"):
            cleanup.destroy_remaining(initial)
        self.assertEqual(client.destroy_calls, ["7001"])
        marker = json.loads(cleanup.marker_path.read_text(encoding="utf-8"))
        self.assertEqual(marker["status"], "pending")
        self.assertEqual(marker["remaining_client_ids"], ["7001", "7002", "7003", "7004"])

    def test_non_success_destroy_is_accepted_only_with_two_view_absence(self):
        state = {
            "owner": owner_record(),
            "clients": {str(7001 + i): client_record(i) for i in range(4)},
            "offers": [],
            "absence_only_destroy": "7001",
        }
        cleanup, _host, client, _evidence, _state = self.make_cleanup(state=state)
        initial = cleanup.preflight()
        cleanup.begin_or_resume_marker(initial)
        result = cleanup.destroy_remaining(initial)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(client.destroy_calls, ["7001", "7002", "7003", "7004"])

    def test_partial_resume_destroys_only_remaining_authorized_subset(self):
        cfg = config(resume_unresolved=True)
        state = {
            "owner": owner_record(),
            "clients": {str(7001 + i): client_record(i) for i in (2, 3)},
            "offers": [],
        }
        cleanup, _host, client, _evidence, _state = self.make_cleanup(
            state=state, cfg=cfg
        )
        cleanup.marker_path.parent.mkdir(parents=True)
        cleanup.marker_path.write_text(
            json.dumps(
                {
                    "status": "pending",
                    "identity": _identity_payload(cfg),
                    "remaining_client_ids": ["7001", "7002", "7003", "7004"],
                    "attempts": [{"run_dir": "prior", "resumed": False}],
                    "credentials_persisted": False,
                    "owner_destroy_authorized": False,
                }
            ),
            encoding="utf-8",
        )
        initial = cleanup.preflight()
        self.assertEqual(tuple(spec.instance_id for spec in initial), ("7003", "7004"))
        cleanup.begin_or_resume_marker(initial)
        cleanup.destroy_remaining(initial)
        self.assertEqual(client.destroy_calls, ["7003", "7004"])

    def test_resume_refuses_a_client_recorded_absent_that_reappeared(self):
        cfg = config(resume_unresolved=True)
        cleanup, _host, client, _evidence, _state = self.make_cleanup(cfg=cfg)
        cleanup.marker_path.parent.mkdir(parents=True)
        cleanup.marker_path.write_text(
            json.dumps(
                {
                    "status": "pending",
                    "identity": _identity_payload(cfg),
                    "remaining_client_ids": ["7003", "7004"],
                    "attempts": [{"run_dir": "prior", "resumed": False}],
                    "credentials_persisted": False,
                    "owner_destroy_authorized": False,
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CycleError, "reappeared"):
            cleanup.preflight()
        self.assertEqual(client.destroy_calls, [])

    def test_owner_id_can_never_enter_destroy_allowlist(self):
        bad_clients = (ClientSpec("6001", "sqwish-client-owner"), *CLIENTS[1:])
        with self.assertRaisesRegex(CycleError, "Owner|owner instance ID"):
            validate_config(config(clients=bad_clients))

    def test_complete_marker_with_different_identity_is_rejected(self):
        cleanup, _host, client, _evidence, _state = self.make_cleanup()
        wrong = config(machine_id="9999")
        cleanup.marker_path.parent.mkdir(parents=True)
        cleanup.marker_path.write_text(
            json.dumps(
                {
                    "status": "complete",
                    "identity": _identity_payload(wrong),
                    "remaining_client_ids": [],
                    "attempts": [],
                    "final_client_inventory_empty": True,
                    "final_host_contracts_owner_only": True,
                    "credentials_persisted": False,
                    "owner_destroy_authorized": False,
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CycleError, "identity differs"):
            cleanup.preflight()
        self.assertEqual(client.destroy_calls, [])

    def test_marker_cannot_grant_owner_destroy_authority(self):
        cfg = config(resume_unresolved=True)
        cleanup, _host, client, _evidence, _state = self.make_cleanup(cfg=cfg)
        cleanup.marker_path.parent.mkdir(parents=True)
        cleanup.marker_path.write_text(
            json.dumps(
                {
                    "status": "pending",
                    "identity": _identity_payload(cfg),
                    "remaining_client_ids": [spec.instance_id for spec in CLIENTS],
                    "attempts": [],
                    "credentials_persisted": False,
                    "owner_destroy_authorized": True,
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CycleError, "forbidden authorization state"):
            cleanup.preflight()
        self.assertEqual(client.destroy_calls, [])

    def test_destroy_refuses_without_pending_exact_authorization(self):
        cleanup, _host, client, _evidence, _state = self.make_cleanup()
        with self.assertRaisesRegex(CycleError, "pending cleanup authorization is absent"):
            cleanup.destroy_remaining(CLIENTS)
        self.assertEqual(client.destroy_calls, [])

    def test_apply_requires_contracts_reviewed(self):
        with self.assertRaisesRegex(CycleError, "contracts-reviewed"):
            validate_config(config(contracts_reviewed=False))


if __name__ == "__main__":
    unittest.main()
