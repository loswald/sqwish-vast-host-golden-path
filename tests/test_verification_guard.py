import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.verification_guard import (
    QualificationGuardError,
    disable_qualification_mode,
    enable_qualification_mode,
    evaluate_verification,
    qualification_interlock_path,
    qualification_marker_path,
    qualification_owner_mutation_interlock,
    require_qualification_mode_inactive,
    sample_qualification_mode,
)


def eligible_machine(**changes):
    machine = {
        "id": 9001,
        "num_gpus": 2,
        "reliability2": 0.91,
        "verification": "unverified",
        "cuda_max_good": 12.6,
        "gpu_ram": 40_960,
        "pcie_bw": 20.0,
        "cpu_cores": 16,
        "cpu_ram": 131_072,
        "inet_down": 1_000,
        "inet_up": 1_000,
        "direct_port_count": 20,
        "ubuntu_version": "22.04",
        "disk_space": 250,
        "error_description": "",
        "vm_error_level": 0,
        "vm_error_msg": "",
    }
    machine.update(changes)
    return machine


def prior_sample(reliability):
    return {"checks": {"reliability": {"actual": reliability}}}


def active_marker(**changes):
    marker = {
        "schema": 1,
        "active": True,
        "machine_id": "9001",
        "enabled_at": "2026-09-02T12:00:00+00:00",
        "allowed_stopped_owner_standbys": [],
        "latest_sample_at": "2026-09-02T12:00:00+00:00",
        "latest_observable_prerequisites_pass": False,
        "latest_platform_verification": "unverified",
        "sample_count": 1,
        "reliability_trend": [
            {"observed_at": "2026-09-02T12:00:00+00:00", "reliability": 0.6}
        ],
        "owner_workloads_verification_safe": False,
    }
    marker.update(changes)
    return marker


def stopped_owner(**changes):
    record = {
        "id": 6001,
        "machine_id": 9001,
        "label": "sqwish-owner-standby",
        "is_bid": False,
        "num_gpus": 2,
        "actual_status": "stopped",
        "intended_status": "stopped",
        "cur_state": "stopped",
    }
    record.update(changes)
    return record


class FakeReadOnlyCli:
    def __init__(self, *, machine=None, reports=None, instances=None, fail_show_machine=False):
        self.machine = machine or eligible_machine()
        self.reports = [] if reports is None else reports
        self.instances = [] if instances is None else instances
        self.fail_show_machine = fail_show_machine
        self.calls = []

    def json(self, args):
        self.calls.append(list(args))
        if args[:2] == ["show", "machine"]:
            if self.fail_show_machine:
                raise QualificationGuardError("synthetic read failure")
            return self.machine
        if args == ["show", "instances", "--raw"]:
            return self.instances
        raise AssertionError(f"unexpected JSON command: {args}")

    def run(self, args):
        self.calls.append(list(args))
        if args[:1] == ["reports"]:
            return SimpleNamespace(
                returncode=0,
                stdout="reports: " + json.dumps(self.reports),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {args}")


def assert_read_only_calls(testcase, calls):
    allowed = {
        ("show", "machine", "9001", "--raw"),
        ("reports", "9001", "--raw"),
        ("show", "instances", "--raw"),
    }
    testcase.assertTrue(calls)
    testcase.assertTrue(all(tuple(call) in allowed for call in calls), calls)


class VerificationAssessmentTests(unittest.TestCase):
    def test_reliability_requirement_is_strictly_over_ninety_percent(self):
        at_threshold = evaluate_verification(
            eligible_machine(reliability2=0.90),
            [],
            [prior_sample(0.90)],
            observed_at="2026-09-02T12:00:00+00:00",
        )
        just_over = evaluate_verification(
            eligible_machine(reliability2=0.9000001),
            [],
            [prior_sample(0.90)],
            observed_at="2026-09-02T12:01:00+00:00",
        )

        self.assertIs(at_threshold["checks"]["reliability"]["pass"], False)
        self.assertIn("reliability", at_threshold["blockers"])
        self.assertIs(just_over["checks"]["reliability"]["pass"], True)
        self.assertNotIn("reliability", just_over["blockers"])

    def test_first_sample_records_insufficient_history_without_claiming_readiness(self):
        result = evaluate_verification(
            eligible_machine(verification="verified"),
            [],
            observed_at="2026-09-02T12:00:00+00:00",
        )

        trend = result["checks"]["steady_uptime_history"]
        self.assertIsNone(trend["pass"])
        self.assertEqual(trend["actual"]["trend_status"], "insufficient-history")
        self.assertIn("steady_uptime_history", result["blockers"])
        self.assertFalse(result["observable_prerequisites_pass"])
        self.assertTrue(result["platform_verified"])
        self.assertFalse(result["owner_workloads_verification_safe"])
        self.assertFalse(result["qualification_guaranteed"])

    def test_reliability_trend_records_non_decreasing_and_regression(self):
        improved = evaluate_verification(
            eligible_machine(reliability2=0.93),
            [],
            [prior_sample(0.91)],
        )
        flat = evaluate_verification(
            eligible_machine(reliability2=0.91),
            [],
            [prior_sample(0.91)],
        )
        regressed = evaluate_verification(
            eligible_machine(reliability2=0.91),
            [],
            [prior_sample(0.93)],
        )

        improved_trend = improved["checks"]["steady_uptime_history"]
        flat_trend = flat["checks"]["steady_uptime_history"]
        regressed_trend = regressed["checks"]["steady_uptime_history"]
        self.assertIs(improved_trend["pass"], True)
        self.assertEqual(improved_trend["actual"]["previous_reliability"], 0.91)
        self.assertEqual(improved_trend["actual"]["current_reliability"], 0.93)
        self.assertEqual(improved_trend["actual"]["trend_status"], "observed-nondecreasing")
        self.assertIs(flat_trend["pass"], True)
        self.assertEqual(flat_trend["actual"]["trend_status"], "observed-nondecreasing")
        self.assertIs(regressed_trend["pass"], False)
        self.assertEqual(regressed_trend["actual"]["trend_status"], "observed-regression")
        self.assertIn("steady_uptime_history", regressed["blockers"])

    def test_platform_state_is_observed_but_never_authorizes_owner_workloads(self):
        for state, expected_verified in (
            ("verified", True),
            ("unverified", False),
            ("deverified", False),
            ("unexpected-new-state", False),
        ):
            with self.subTest(state=state):
                result = evaluate_verification(
                    eligible_machine(verification=state),
                    [],
                    [prior_sample(0.91)],
                )
                self.assertEqual(result["platform_verification"], state)
                self.assertIs(result["platform_verified"], expected_verified)
                self.assertFalse(result["owner_workloads_verification_safe"])
                self.assertFalse(result["qualification_guaranteed"])

    def test_missing_or_invalid_reliability_never_passes(self):
        cases = (
            {"reliability2": None},
            {"reliability2": True},
            {"reliability2": "not-a-number"},
            {"reliability2": float("nan")},
            {"reliability2": -0.01},
            {"reliability2": 1.01},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                machine = eligible_machine(**changes)
                machine.pop("reliability", None)
                result = evaluate_verification(machine, [], [prior_sample(0.91)])
                self.assertIsNot(result["checks"]["reliability"]["pass"], True)
                self.assertIn("reliability", result["blockers"])
                self.assertFalse(result["observable_prerequisites_pass"])

    def test_reports_and_machine_errors_are_fail_closed(self):
        with_report = evaluate_verification(
            eligible_machine(),
            [{"problem": "container", "message": "failed", "created_at": "now"}],
            [prior_sample(0.91)],
        )
        with_error = evaluate_verification(
            eligible_machine(vm_error_level=1),
            [],
            [prior_sample(0.91)],
        )

        self.assertIs(with_report["checks"]["reports"]["pass"], False)
        self.assertIn("reports", with_report["blockers"])
        self.assertIs(with_error["checks"]["machine_errors"]["pass"], False)
        self.assertIn("machine_errors", with_error["blockers"])

    def test_partial_health_tuple_is_unknown_not_clear(self):
        for missing in ("error_description", "vm_error_level", "vm_error_msg"):
            with self.subTest(missing=missing):
                machine = eligible_machine()
                machine.pop(missing)
                result = evaluate_verification(machine, [], [prior_sample(0.91)])
                self.assertIsNot(result["checks"]["machine_errors"]["pass"], True)
                self.assertIn("machine_errors", result["blockers"])

    def test_malformed_top_level_inputs_raise(self):
        with self.assertRaises(QualificationGuardError):
            evaluate_verification([], [])
        with self.assertRaises(QualificationGuardError):
            evaluate_verification(eligible_machine(), {})
        with self.assertRaises(QualificationGuardError):
            evaluate_verification(eligible_machine(), ["bad-row"])


class QualificationMarkerTests(unittest.TestCase):
    def write_marker(self, root: Path, value) -> Path:
        path = qualification_marker_path(root)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_absent_marker_allows_caller_to_continue(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(
                require_qualification_mode_inactive(Path(tmp), machine_id="9001")
            )

    def test_active_marker_always_blocks_and_names_the_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_marker(root, active_marker())
            with self.assertRaisesRegex(
                QualificationGuardError, "refusing prepare owner standby"
            ):
                require_qualification_mode_inactive(
                    root,
                    machine_id="9001",
                    action="prepare owner standby",
                )
            with self.assertRaisesRegex(QualificationGuardError, "not evidence"):
                require_qualification_mode_inactive(root)

    def test_marker_for_another_machine_is_an_unresolved_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_marker(root, active_marker(machine_id="9002"))
            with self.assertRaisesRegex(QualificationGuardError, "state-root mismatch"):
                require_qualification_mode_inactive(root, machine_id="9001")

    def test_malformed_or_unknown_marker_never_silently_unblocks(self):
        malformed_values = (
            ("not-json", "unreadable or malformed"),
            ([], "invalid shape"),
            ({}, "unknown state"),
            (active_marker(schema=2), "unknown state"),
            (active_marker(schema=True), "unknown state"),
            (active_marker(active=False), "unknown state"),
            (active_marker(active="true"), "unknown state"),
            (active_marker(machine_id=""), "no valid machine identity"),
            (active_marker(machine_id="0"), "no valid machine identity"),
        )
        for value, expected_error in malformed_values:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = qualification_marker_path(root)
                if value == "not-json":
                    path.write_text(value, encoding="utf-8")
                else:
                    self.write_marker(root, value)
                with self.assertRaisesRegex(QualificationGuardError, expected_error):
                    require_qualification_mode_inactive(root, machine_id="9001")

    def test_directory_at_marker_path_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            qualification_marker_path(root).mkdir()
            with self.assertRaises(QualificationGuardError):
                require_qualification_mode_inactive(root, machine_id="9001")


class QualificationInterlockTests(unittest.TestCase):
    def test_owner_request_wins_before_enable_without_marker_interleaving(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            owner_acquired = threading.Event()
            contended = threading.Event()
            allow_owner_request = threading.Event()
            sequence = []
            errors = []

            class SequencedCli(FakeReadOnlyCli):
                def json(inner_self, args):
                    if args[:2] == ["show", "machine"]:
                        sequence.append("qualification-inventory")
                    return super().json(args)

            def owner_path():
                try:
                    with qualification_owner_mutation_interlock(
                        root, action="fake owner Start", timeout_seconds=2
                    ):
                        require_qualification_mode_inactive(root, machine_id="9001")
                        owner_acquired.set()
                        if not contended.wait(2):
                            raise AssertionError("qualification enable never contended")
                        self.assertFalse(qualification_marker_path(root).exists())
                        sequence.append("owner-start-request")
                        allow_owner_request.set()
                except BaseException as exc:  # preserve thread failures for the test
                    errors.append(exc)

            def enable_path():
                try:
                    enable_qualification_mode(
                        root, SequencedCli(), machine_id="9001", allowed=[]
                    )
                except BaseException as exc:  # preserve thread failures for the test
                    errors.append(exc)

            def contention_sleep(_seconds):
                contended.set()
                if not allow_owner_request.wait(2):
                    raise AssertionError("owner request was not released")

            with patch(
                "tools.verification_guard.time.sleep", side_effect=contention_sleep
            ):
                owner = threading.Thread(target=owner_path)
                owner.start()
                self.assertTrue(owner_acquired.wait(2))
                self.assertTrue(qualification_interlock_path(root).is_dir())
                enable = threading.Thread(target=enable_path)
                enable.start()
                owner.join(3)
                enable.join(3)

            self.assertFalse(owner.is_alive())
            self.assertFalse(enable.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(sequence[0], "owner-start-request")
            self.assertEqual(sequence[1], "qualification-inventory")
            self.assertTrue(qualification_marker_path(root).is_file())

    def test_lock_excludes_a_separate_process_and_only_owner_releases_it(self):
        child = """
import sys
from pathlib import Path
from tools.verification_guard import QualificationGuardError, qualification_owner_mutation_interlock

try:
    with qualification_owner_mutation_interlock(
        Path(sys.argv[1]), action="child owner mutation", timeout_seconds=0
    ):
        pass
except QualificationGuardError:
    raise SystemExit(23)
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with qualification_owner_mutation_interlock(
                root, action="parent qualification enable", timeout_seconds=0
            ):
                blocked = subprocess.run(
                    [sys.executable, "-c", child, str(root)],
                    cwd=Path(__file__).resolve().parents[1],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(blocked.returncode, 23, blocked.stderr)
                self.assertTrue(qualification_interlock_path(root).is_dir())

            acquired = subprocess.run(
                [sys.executable, "-c", child, str(root)],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(acquired.returncode, 0, acquired.stderr)
            self.assertFalse(qualification_interlock_path(root).exists())

    def test_preexisting_old_lock_is_never_automatically_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock = qualification_interlock_path(root)
            lock.mkdir()
            (lock / "owner-token").write_text("abandoned-owner\n", encoding="utf-8")
            (lock / "owner.json").write_text('{"schema":1}\n', encoding="utf-8")
            os.utime(lock, (1, 1))

            with self.assertRaisesRegex(QualificationGuardError, "never be cleared"):
                with qualification_owner_mutation_interlock(
                    root, action="test stale safety", timeout_seconds=0
                ):
                    self.fail("an existing lock must not be entered")

            self.assertEqual(
                (lock / "owner-token").read_text(encoding="utf-8"),
                "abandoned-owner\n",
            )

    def test_enable_writes_hold_before_inventory_and_keeps_interlock_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            class OrderingCli(FakeReadOnlyCli):
                def json(inner_self, args):
                    if args[:2] == ["show", "machine"]:
                        self.assertTrue(qualification_marker_path(root).is_file())
                        self.assertTrue(qualification_interlock_path(root).is_dir())
                    return super().json(args)

            enable_qualification_mode(root, OrderingCli(), machine_id="9001", allowed=[])
            self.assertFalse(qualification_interlock_path(root).exists())

    def test_disable_archives_and_removes_marker_while_interlock_is_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = qualification_marker_path(root)
            marker.write_text(json.dumps(active_marker()), encoding="utf-8")
            real_unlink = Path.unlink
            marker_removed_under_lock = []

            def checked_unlink(path, *args, **kwargs):
                if path == marker:
                    marker_removed_under_lock.append(
                        qualification_interlock_path(root).is_dir()
                    )
                return real_unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", new=checked_unlink):
                result = disable_qualification_mode(root, machine_id="9001")

            self.assertEqual(marker_removed_under_lock, [True])
            self.assertTrue(Path(result["archive_path"]).is_file())
            self.assertFalse(qualification_interlock_path(root).exists())

class QualificationLifecycleTests(unittest.TestCase):
    def test_enable_installs_hold_before_failed_read_and_leaves_it_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli = FakeReadOnlyCli(fail_show_machine=True)

            with self.assertRaisesRegex(QualificationGuardError, "synthetic read failure"):
                enable_qualification_mode(root, cli, machine_id="9001", allowed=[])

            marker_path = qualification_marker_path(root)
            self.assertTrue(marker_path.is_file())
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            self.assertIs(marker["active"], True)
            self.assertEqual(marker["machine_id"], "9001")
            self.assertEqual(marker["status"], "observation-pending")
            self.assertEqual(marker["sample_count"], 0)
            self.assertFalse(marker["owner_workloads_verification_safe"])
            with self.assertRaisesRegex(QualificationGuardError, "qualification mode is active"):
                require_qualification_mode_inactive(root, machine_id="9001")
            assert_read_only_calls(self, cli.calls)

    def test_happy_enable_sample_disable_records_trend_without_vast_mutations(self):
        timestamps = [
            "2026-09-02T12:00:00+00:00",
            "2026-09-02T12:05:00+00:00",
            "2026-09-02T12:06:00+00:00",
        ]
        with tempfile.TemporaryDirectory() as tmp, patch(
            "tools.verification_guard.utc_now", side_effect=timestamps
        ):
            root = Path(tmp)
            cli = FakeReadOnlyCli(machine=eligible_machine(reliability2=0.91))

            first = enable_qualification_mode(root, cli, machine_id="9001", allowed=[])
            cli.machine = eligible_machine(reliability2=0.93, verification="verified")
            second = sample_qualification_mode(root, cli, machine_id="9001")
            disabled = disable_qualification_mode(root, machine_id="9001")

            self.assertEqual(first["checks"]["reliability"]["actual"], 0.91)
            self.assertEqual(second["checks"]["reliability"]["actual"], 0.93)
            self.assertEqual(
                second["checks"]["steady_uptime_history"]["actual"]["trend_status"],
                "observed-nondecreasing",
            )
            self.assertEqual(
                second["checks"]["steady_uptime_history"]["actual"]["previous_reliability"],
                0.91,
            )
            self.assertFalse(qualification_marker_path(root).exists())
            archive = json.loads(Path(disabled["archive_path"]).read_text(encoding="utf-8"))
            self.assertIs(archive["active"], False)
            self.assertEqual(archive["sample_count"], 2)
            self.assertEqual(
                [item["reliability"] for item in archive["reliability_trend"]],
                [0.91, 0.93],
            )
            self.assertFalse(archive["owner_workloads_verification_safe"])
            self.assertFalse(disabled["owner_workloads_verification_safe"])
            self.assertEqual(disabled["vast_mutations_performed"], 0)
            assert_read_only_calls(self, cli.calls)
            self.assertEqual(len(cli.calls), 6)

    def test_unknown_target_owner_refuses_enable_and_hold_remains_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli = FakeReadOnlyCli(instances=[stopped_owner(id=6999, label="unknown-owner")])

            with self.assertRaisesRegex(
                QualificationGuardError, "unknown personal owner instance 6999"
            ):
                enable_qualification_mode(root, cli, machine_id="9001", allowed=[])

            marker = json.loads(
                qualification_marker_path(root).read_text(encoding="utf-8")
            )
            self.assertIs(marker["active"], True)
            self.assertEqual(marker["status"], "observation-pending")
            self.assertEqual(marker["sample_count"], 0)
            with self.assertRaises(QualificationGuardError):
                require_qualification_mode_inactive(root, machine_id="9001")
            assert_read_only_calls(self, cli.calls)

    def test_exact_allowed_safely_stopped_owner_can_be_observed(self):
        allowed = [{"instance_id": "6001", "label": "sqwish-owner-standby"}]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli = FakeReadOnlyCli(instances=[stopped_owner()])

            result = enable_qualification_mode(
                root,
                cli,
                machine_id="9001",
                allowed=allowed,
            )

            self.assertEqual(
                result["allowed_stopped_owner_standbys_observed"],
                [
                    {
                        "instance_id": "6001",
                        "label": "sqwish-owner-standby",
                        "is_bid": False,
                        "num_gpus": 2,
                        "stopped_tuple": ["stopped", "stopped", "stopped"],
                    }
                ],
            )
            marker = json.loads(
                qualification_marker_path(root).read_text(encoding="utf-8")
            )
            self.assertEqual(marker["allowed_stopped_owner_standbys"], allowed)
            self.assertEqual(marker["sample_count"], 1)
            self.assertFalse(marker["owner_workloads_verification_safe"])
            assert_read_only_calls(self, cli.calls)

    def test_missing_allowlisted_owner_standby_aborts_observation(self):
        allowed = [{"instance_id": "6001", "label": "sqwish-owner-standby"}]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cli = FakeReadOnlyCli(instances=[])
            with self.assertRaisesRegex(QualificationGuardError, "missing exact IDs: 6001"):
                enable_qualification_mode(root, cli, machine_id="9001", allowed=allowed)
            marker = json.loads(
                qualification_marker_path(root).read_text(encoding="utf-8")
            )
            self.assertTrue(marker["active"])

    def test_validated_long_owner_label_is_preserved_in_marker_and_sample(self):
        label = "sqwish-" + "a" * 45
        allowed = [{"instance_id": "6001", "label": label}]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = enable_qualification_mode(
                root,
                FakeReadOnlyCli(instances=[stopped_owner(label=label)]),
                machine_id="9001",
                allowed=allowed,
            )
            marker = json.loads(
                qualification_marker_path(root).read_text(encoding="utf-8")
            )
            sample = json.loads(Path(marker["latest_sample_path"]).read_text(encoding="utf-8"))
            self.assertEqual(marker["allowed_stopped_owner_standbys"][0]["label"], label)
            self.assertEqual(
                sample["allowed_stopped_owner_standbys_observed"][0]["label"], label
            )
            self.assertEqual(
                result["allowed_stopped_owner_standbys_observed"][0]["label"], label
            )

    def test_allowed_stopped_owner_may_be_one_slice_of_a_multi_gpu_host(self):
        allowed = [{"instance_id": "6001", "label": "sqwish-owner-standby"}]
        with tempfile.TemporaryDirectory() as tmp:
            result = enable_qualification_mode(
                Path(tmp),
                FakeReadOnlyCli(
                    machine=eligible_machine(num_gpus=4, cpu_cores=16, cpu_ram=200_000),
                    instances=[stopped_owner(num_gpus=1)],
                ),
                machine_id="9001",
                allowed=allowed,
            )

            self.assertEqual(
                result["allowed_stopped_owner_standbys_observed"][0]["num_gpus"], 1
            )


if __name__ == "__main__":
    unittest.main()
