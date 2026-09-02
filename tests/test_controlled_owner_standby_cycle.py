import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tools.controlled_owner_standby_cycle import (
    Config,
    CycleError,
    StandbyCycle,
    build_result,
    degraded_gate,
    redact_evidence,
    require_client_identity,
    require_exact_account_inventories,
    require_owner_identity,
    validate_config,
)
from tools.verification_guard import qualification_interlock_path


def config(**changes):
    values = {
        "machine_id": "9001",
        "owner_instance_id": "6001",
        "owner_label": "sqwish-owner-standby",
        "client_instance_id": "7001",
        "client_label": "sqwish-controlled-client",
        "host_cli": "host-vastai",
        "client_cli": "client-vastai",
        "original_reliability_baseline": 0.99,
        "delayed_seconds": 7200,
    }
    values.update(changes)
    return Config(**values)


def owner_record(**changes):
    value = {
        "id": 6001,
        "machine_id": 9001,
        "label": "sqwish-owner-standby",
        "is_bid": False,
        "num_gpus": 2,
        "actual_status": "stopped",
        "intended_status": "stopped",
        "cur_state": "stopped",
    }
    value.update(changes)
    return value


def client_record(**changes):
    value = {
        "id": 7001,
        "machine_id": 9001,
        "label": "sqwish-controlled-client",
        "is_bid": True,
        "num_gpus": 2,
        "actual_status": "running",
        "intended_status": "running",
        "cur_state": "running",
    }
    value.update(changes)
    return value


def machine_summary(reliability=0.99):
    return {
        "at": "2026-09-02T00:00:00+00:00",
        "reliability": reliability,
        "verification": "verified",
        "reports": 0,
        "report_records": [],
        "machine_report_counters": {"num_reports": None, "num_recent_reports": None},
        "health": {"error_description": "", "vm_error_level": 0.0, "vm_error_msg": ""},
    }


class FakeCli:
    def __init__(self, interlock_root=None):
        self.run_calls = []
        self.json_calls = []
        self.run_stdout = '{"success": true}'
        self.interlock_root = interlock_root
        self.interlock_seen_during_owner_start = False

    def run(self, args, **_kwargs):
        self.run_calls.append(args)
        if args[:3] == ["start", "instance", "6001"]:
            self.interlock_seen_during_owner_start = bool(
                self.interlock_root
                and qualification_interlock_path(self.interlock_root).is_dir()
            )
        return SimpleNamespace(returncode=0, stdout=self.run_stdout, stderr="")

    def json(self, args, **_kwargs):
        self.json_calls.append(args)
        return []


class OrderedRunCycle(StandbyCycle):
    def __init__(self, cfg, run_dir):
        super().__init__(
            cfg,
            FakeCli(interlock_root=run_dir),
            FakeCli(),
            run_dir,
            sleep=lambda _seconds: None,
        )
        self.events = []

    def preflight(self, **_kwargs):
        self.events.append("preflight")
        return machine_summary()

    def unlist_then_prove(self):
        self.events.append("unlist-proved")
        self.unlisted_proved = True

    def query_machine(self):
        return {
            "id": 9001,
            "reliability2": 0.99,
            "verification": "verified",
            "num_reports": None,
            "num_recent_reports": None,
            "error_description": "",
            "vm_error_level": 0,
            "vm_error_msg": "",
        }

    def query_reports(self):
        return []

    def require_exact_inventories(self):
        self.events.append("inventories")
        return owner_record(), client_record()

    def wait_for_owner_takeover(self):
        self.events.append("takeover")
        self.owner_running_observed = True
        self.owner_running_elapsed_seconds = 10

    def monitor_owner_dwell(self):
        self.events.append("dwell")

    def stop_owner_and_prove(self, *, phase):
        self.events.append(f"stop:{phase}")
        self.owner_stopped_observed = True

    def wait_for_auto_resume(self):
        self.events.append("auto-resume")
        self.auto_resume_observed = True
        return True


class FallbackCycle(StandbyCycle):
    def __init__(self, cfg, run_dir, fake_client):
        super().__init__(cfg, FakeCli(), fake_client, run_dir, sleep=lambda _seconds: None)
        self.snapshots = 0

    def prove_unlisted(self, *, samples):
        self.unlisted_proved = True

    def require_exact_inventories(self):
        return owner_record(), client_record(
            actual_status="stopped", intended_status="stopped", cur_state="stopped"
        )

    def snapshot(self, _phase):
        self.snapshots += 1
        return {"owner": owner_record(), "client": client_record()}


class OwnerStandbyCycleTests(unittest.TestCase):
    def test_validate_requires_original_baseline_and_15_minute_or_less_slo(self):
        for bad in (-0.01, 1.01, float("nan"), True):
            with self.subTest(bad=bad), self.assertRaises(CycleError):
                validate_config(config(original_reliability_baseline=bad))
        with self.assertRaisesRegex(CycleError, "between 1 and 900"):
            validate_config(config(reclaim_slo_seconds=901))

    def test_apply_requires_contract_page_review(self):
        with self.assertRaisesRegex(CycleError, "contracts-reviewed"):
            validate_config(config(apply=True))
        validate_config(config(apply=True, contracts_reviewed=True))

    def test_owner_must_be_exact_on_demand_full_machine_standby(self):
        require_owner_identity(owner_record(), config())
        for changes in (
            {"id": 9999},
            {"machine_id": 9999},
            {"label": "wrong-owner"},
            {"is_bid": True},
            {"num_gpus": 1},
        ):
            with self.subTest(changes=changes), self.assertRaises(CycleError):
                require_owner_identity(owner_record(**changes), config())

    def test_client_must_be_exact_interruptible_full_machine_instance(self):
        require_client_identity(client_record(), config())
        with self.assertRaisesRegex(CycleError, "interruptible type"):
            require_client_identity(client_record(is_bid=False), config())

    def test_inventory_rejects_outside_on_demand_or_reserved_instance(self):
        outside = owner_record(id=6111, label="outside-contract", is_bid=False)
        with self.assertRaisesRegex(CycleError, "outside on-demand or reserved"):
            require_exact_account_inventories(
                [owner_record(), outside], [client_record()], config()
            )

    def test_inventory_rejects_unknown_interruptible_or_host_job_too(self):
        unknown = owner_record(id=6111, label="unknown-record", is_bid=True)
        with self.assertRaisesRegex(CycleError, "owner-only target set"):
            require_exact_account_inventories(
                [owner_record(), unknown], [client_record()], config()
            )

    def test_inventory_ignores_other_machines_but_requires_exact_target_sets(self):
        other_host = owner_record(id=6200, machine_id=9200, label="other-machine")
        other_client = client_record(id=7200, machine_id=9200, label="other-machine")
        owner, client = require_exact_account_inventories(
            [owner_record(), other_host], [client_record(), other_client], config()
        )
        self.assertEqual(owner["id"], 6001)
        self.assertEqual(client["id"], 7001)

    def test_degraded_score_aborts_without_explicit_diagnostic_override(self):
        with self.assertRaisesRegex(CycleError, "refusing every mutation"):
            degraded_gate(config(), machine_summary(0.98), what="pre-mutation")

    def test_degraded_override_is_explicitly_experimental(self):
        result = degraded_gate(
            config(allow_degraded_diagnostic=True), machine_summary(0.98), what="pre-mutation"
        )
        self.assertFalse(result["at_or_above_original"])
        self.assertTrue(result["allow_degraded_diagnostic"])
        self.assertTrue(result["experimental_only"])

    def test_run_unlists_and_proves_before_owner_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            cycle = OrderedRunCycle(config(), Path(tmp))
            cycle.owner_stop_authorized = True
            cycle.run()
            self.assertTrue(cycle.host.interlock_seen_during_owner_start)
            self.assertFalse(qualification_interlock_path(Path(tmp)).exists())
        self.assertEqual(cycle.events[:3], ["preflight", "unlist-proved", "inventories"])
        self.assertEqual(cycle.host.run_calls[0][:3], ["start", "instance", "6001"])
        self.assertGreater(cycle.events.index("takeover"), cycle.events.index("unlist-proved"))

    def test_active_qualification_mode_blocks_before_first_cycle_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "qualification-mode.json").write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "active": True,
                        "machine_id": "9001",
                        "enabled_at": "2026-09-02T12:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            cycle = OrderedRunCycle(config(), root)
            cycle.owner_stop_authorized = True
            with self.assertRaisesRegex(CycleError, "qualification mode is active"):
                cycle.run()
            self.assertEqual(cycle.host.run_calls, [])
            self.assertNotIn("unlist-proved", cycle.events)

    def test_unlisting_proof_rejects_any_exact_offer_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            cycle = StandbyCycle(config(), FakeCli(), FakeCli(), Path(tmp), sleep=lambda _: None)
            cycle.query_offers = lambda _kind: [{"id": 8101, "machine_id": 9001}]
            with self.assertRaisesRegex(CycleError, "still exposes"):
                cycle.prove_unlisted(samples=1)

    def test_fallback_start_requires_fsynced_failure_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_client = FakeCli()
            cycle = FallbackCycle(
                config(allow_controlled_client_fallback_start=True), Path(tmp), fake_client
            )
            cycle.fallback_start_authorized = True
            with self.assertRaisesRegex(CycleError, "evidence is absent"):
                cycle.guarded_fallback_start()
            self.assertEqual(fake_client.run_calls, [])

    def test_fallback_start_requires_exact_stopped_evidence_and_current_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_client = FakeCli()
            cycle = FallbackCycle(
                config(allow_controlled_client_fallback_start=True), Path(tmp), fake_client
            )
            cycle.fallback_start_authorized = True
            evidence = {
                "automatic_resume_observed": False,
                "owner_safely_stopped": True,
                "controlled_client_safely_stopped": True,
            }
            (Path(tmp) / "auto-resume-failure.json").write_text(json.dumps(evidence))
            cycle.guarded_fallback_start()
            self.assertEqual(fake_client.run_calls, [["start", "instance", "7001", "--raw"]])
            self.assertTrue(cycle.fallback_start_used)

    def test_cleanup_retains_owner_and_client_without_destroy_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            cycle = OrderedRunCycle(config(), Path(tmp))
            cycle.cycle_started = True
            cycle.owner_stop_authorized = True
            cycle.cleanup()
            cleanup = json.loads((Path(tmp) / "cleanup.json").read_text())
        self.assertTrue(cleanup["owner_standby_retained"])
        self.assertFalse(cleanup["controlled_client_destroyed"])
        self.assertFalse(any(call[:2] == ["destroy", "instance"] for call in cycle.client.run_calls))

    def test_result_is_never_production_ready_even_on_technical_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            cycle = OrderedRunCycle(config(), Path(tmp))
            cycle.baseline = machine_summary()
            cycle.owner_running_observed = True
            cycle.owner_running_elapsed_seconds = 10
            cycle.owner_stopped_observed = True
            cycle.auto_resume_observed = True
            result = build_result(cycle, None, True)
        self.assertTrue(result["experimental"])
        self.assertFalse(result["production_ready"])

    def test_degraded_diagnostic_result_can_never_establish_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            cycle = OrderedRunCycle(config(allow_degraded_diagnostic=True), Path(tmp))
            cycle.baseline = machine_summary(0.57)
            result = build_result(cycle, None, False)
        self.assertEqual(result["diagnostic_mode"], "degraded-disposable")
        self.assertFalse(result["production_ready"])
        self.assertTrue(any("degraded diagnostic bypass" in reason for reason in result["blocking_reasons"]))

    def test_evidence_redaction_covers_secret_fields_and_cli_text(self):
        value = redact_evidence(
            {
                "instance_api_key": "short-secret",
                "nested": {"token": "tiny", "message": "password=also-short safe"},
                "email": "operator@example.test",
                "public_ip": "203.0.113.9",
                "ssh_public_key": "ssh-ed25519 short-key",
            }
        )
        self.assertEqual(value["instance_api_key"], "<redacted>")
        self.assertEqual(value["nested"]["token"], "<redacted>")
        self.assertNotIn("also-short", value["nested"]["message"])
        self.assertEqual(value["email"], "<redacted>")
        self.assertEqual(value["public_ip"], "<redacted>")
        self.assertEqual(value["ssh_public_key"], "<redacted>")
        raw = redact_evidence(
            'stdout={"instance_api_key":"short-json-secret","password":"tiny",'
            '"email":"operator@example.test","public_ip":"203.0.113.9",'
            '"ssh_public_key":"ssh-ed25519 short-key"}'
        )
        self.assertNotIn("short-json-secret", raw)
        self.assertNotIn('"tiny"', raw)
        self.assertNotIn("operator@example.test", raw)
        self.assertNotIn("203.0.113.9", raw)
        self.assertNotIn("short-key", raw)
        self.assertGreaterEqual(raw.count("<redacted>"), 3)


if __name__ == "__main__":
    unittest.main()
