import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.prepare_owner_standby import (
    OWNER_COMMAND,
    Config,
    StandbyError,
    StandbyPreparation,
    load_or_pin_original_baseline,
    owner_command,
    owner_probe_contract,
    sanitize_text,
    validate_config,
)
from tools.verification_guard import qualification_interlock_path


IMAGE = "pytorch/pytorch:2.13.0-cuda12.6-cudnn9-runtime@sha256:" + "a" * 64


def config(**changes):
    values = dict(
        machine_id="9001",
        host_cli="host-vastai",
        gpu_count=2,
        fixed_end_epoch=50_000,
        p99_host_on_demand_price=10.0,
        p99_host_bid_floor=10.0,
        expected_renter_on_demand_price=26.66666667,
        disk_price=0.15,
        upload_price=0.03999,
        download_price=0.002,
        image=IMAGE,
        disk_gb=20.0,
        label="sqwish-owner-standby-test",
        original_reliability_baseline=0.6,
        allow_degraded_diagnostic=False,
        contracts_reviewed=True,
        offer_timeout=3.0,
        running_timeout=3.0,
        stopped_timeout=3.0,
        absence_samples=2,
        poll_seconds=1.0,
        apply=True,
    )
    values.update(changes)
    return Config(**values)


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += max(float(seconds), 0.001)


class FakeState:
    def __init__(self, cfg, scenario="happy"):
        self.cfg = cfg
        self.scenario = scenario
        self.listed = False
        self.created = False
        self.stopped = False
        self.calls = []
        self.root = None
        self.interlock_seen_during_create = False

    def machine(self):
        return [
            {
                "id": 9001,
                "num_gpus": self.cfg.gpu_count,
                "current_rentals_running": 1 if self.created and not self.stopped else 0,
                "reliability2": 0.57 if self.scenario == "degraded" else 0.6,
                "verification": "unverified",
                "error_description": "",
                "vm_error_level": 0,
                "vm_error_msg": "",
            }
        ]

    def listing_response(self):
        return {
            "success": True,
            "you_sent": {
                "machine": 9001,
                "min_chunk": self.cfg.gpu_count,
                "vol_size": 0,
                "end_date": self.cfg.fixed_end_epoch,
                "price_gpu": self.cfg.p99_host_on_demand_price,
                "price_min_bid": self.cfg.p99_host_bid_floor,
                "price_disk": self.cfg.disk_price,
                "price_inetu": self.cfg.upload_price,
                "price_inetd": self.cfg.download_price,
                "credit_discount_max": 0.0,
            },
        }

    def offer(self, kind):
        if not self.listed or self.created:
            return []
        common = {
            "id": 8102 if kind == "on-demand" else 8101,
            "machine_id": 9001,
            "host_id": 101,
            "num_gpus": self.cfg.gpu_count,
            "rentable": True,
            "rented": False,
            "end_date": self.cfg.fixed_end_epoch,
        }
        if kind == "on-demand":
            common["dph_base"] = self.cfg.expected_renter_on_demand_price
        else:
            common["min_bid"] = 26.0
        return [common]

    def instance(self):
        label = "wrong-owner-label" if self.scenario == "identity-mismatch" else self.cfg.label
        if self.stopped:
            if self.scenario == "unsafe-stop":
                statuses = ("loading", "stopped", "unloaded")
            else:
                statuses = ("exited", "stopped", "stopped")
        else:
            statuses = ("running", "running", "running")
        return {
            "id": 7001,
            "machine_id": 9001,
            "label": label,
            "is_bid": False,
            "num_gpus": self.cfg.gpu_count,
            "image_uuid": self.cfg.image,
            "image_args": ["/bin/bash", "-lc", owner_command(self.cfg.gpu_count)],
            "disk_space": self.cfg.disk_gb,
            "ask_contract_id": 8102,
            "end_date": self.cfg.fixed_end_epoch,
            "actual_status": statuses[0],
            "intended_status": statuses[1],
            "cur_state": statuses[2],
        }


class FakeCli:
    def __init__(self, state):
        self.state = state
        self.executable = "/host-vastai"

    def run(self, args):
        self.state.calls.append(list(args))
        command = args[:2]
        stdout = ""
        stderr = ""
        returncode = 0
        if command == ["show", "user"]:
            stdout = json.dumps({"id": 101})
        elif command == ["show", "machine"]:
            stdout = json.dumps(self.state.machine())
        elif command == ["show", "instances"]:
            stdout = json.dumps([self.state.instance()] if self.state.created else [])
        elif command == ["show", "instance"]:
            stdout = json.dumps([self.state.instance()] if self.state.created else [])
        elif command == ["search", "offers"]:
            kind = args[args.index("--type") + 1]
            stdout = json.dumps(self.state.offer(kind))
        elif command == ["list", "machine"]:
            if self.state.scenario == "structured-list-rejection":
                stderr = json.dumps(
                    {"error": True, "status_code": 422, "msg": "price outside accepted range"}
                )
            else:
                self.state.listed = True
                stdout = json.dumps(self.state.listing_response())
        elif command == ["unlist", "machine"]:
            self.state.listed = False
            stdout = "machine unlisted\n"
        elif command == ["create", "instance"]:
            self.state.interlock_seen_during_create = bool(
                self.state.root
                and qualification_interlock_path(self.state.root).is_dir()
            )
            self.state.created = True
            if self.state.scenario == "uncertain-create":
                stdout = "gateway disconnected"
            else:
                stdout = json.dumps(
                    {
                        "success": True,
                        "new_contract": 7001,
                        "instance_api_key": "T" * 48,
                    }
                )
        elif command == ["stop", "instance"]:
            self.state.stopped = True
            stdout = "stop requested\n"
        else:
            returncode = 90
            stderr = f"unexpected fake command: {args}"
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)


class OwnerStandbyTests(unittest.TestCase):
    def controller(self, tmp, scenario="happy", **cfg_changes):
        cfg = config(**cfg_changes)
        root = Path(tmp)
        run_dir = root / "runs" / "one"
        run_dir.mkdir(parents=True)
        state = FakeState(cfg, scenario)
        state.root = root
        clock = FakeClock()
        controller = StandbyPreparation(
            cfg,
            FakeCli(state),
            root,
            run_dir,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )
        return controller, state, cfg, root

    def test_happy_path_is_one_shot_unlisted_and_safely_stopped(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller, state, _, root = self.controller(tmp)
            controller.preflight()
            result = controller.prepare()

            verbs = [call[:2] for call in state.calls]
            self.assertEqual(verbs.count(["list", "machine"]), 1)
            self.assertEqual(verbs.count(["create", "instance"]), 1)
            self.assertEqual(verbs.count(["unlist", "machine"]), 1)
            self.assertEqual(verbs.count(["stop", "instance"]), 1)
            self.assertNotIn(["destroy", "instance"], verbs)
            self.assertTrue(state.interlock_seen_during_create)
            self.assertFalse(qualification_interlock_path(root).exists())
            create = next(call for call in state.calls if call[:2] == ["create", "instance"])
            self.assertNotIn("--cancel-unavail", create)
            marker = create.index("--args")
            self.assertEqual(create[marker + 1 : marker + 3], ["/bin/bash", "-lc"])
            self.assertEqual(create[-1], OWNER_COMMAND)
            self.assertEqual(result["stopped_tuple"], ["exited", "stopped", "stopped"])
            self.assertTrue(result["unlisted_proved"])
            self.assertFalse(state.listed)
            self.assertTrue((root / "owner-standbys" / "machine-9001.json").exists())
            evidence = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (controller.run_dir / "commands").glob("*.json")
            )
            self.assertNotIn("T" * 48, evidence)
            self.assertIn("<redacted-sensitive-field>", evidence)

    def test_active_qualification_mode_blocks_before_listing(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller, state, _, root = self.controller(tmp)
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
            with self.assertRaisesRegex(StandbyError, "qualification mode is active"):
                controller.prepare()
            self.assertNotIn(["list", "machine"], [call[:2] for call in state.calls])
            self.assertNotIn(["create", "instance"], [call[:2] for call in state.calls])

    def test_four_gpu_scan_standby_uses_exact_dynamic_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller, state, _, _ = self.controller(tmp, gpu_count=4)
            controller.preflight()
            result = controller.prepare()

            create = next(call for call in state.calls if call[:2] == ["create", "instance"])
            expected = owner_command(4)
            self.assertEqual(create[-1], expected)
            self.assertIn('test "$gpu_count" -eq 4', expected)
            self.assertIn("EXPECTED_GPU_COUNT = 4", expected)
            self.assertIn("--nproc-per-node=4", expected)
            self.assertIn('backend="nccl"', expected)
            self.assertIn("dist.all_reduce", expected)
            self.assertIn("CHECKPOINT_SECONDS = 15", expected)
            self.assertIn("MAX_CHECKPOINTS = 1440", expected)
            self.assertIn("for checkpoint_index in range(MAX_CHECKPOINTS)", expected)
            self.assertIn('"event": "owner_standby_ready"', expected)
            self.assertIn('else "owner_checkpoint"', expected)
            self.assertIn("os.replace(temporary, CHECKPOINT_PATH)", expected)
            self.assertIn("existing owner checkpoint failed its SHA-256", expected)
            self.assertNotIn("pip install", expected)
            self.assertNotIn("curl ", expected)
            self.assertEqual(result["gpu_count"], 4)
            self.assertEqual(result["image_args"], ["/bin/bash", "-lc", expected])
            self.assertEqual(result["workload_probe_contract"], owner_probe_contract(4))
            self.assertFalse(
                result["workload_probe_contract"]["execution_proved_during_preparation"]
            )
            self.assertTrue(
                result["workload_probe_contract"][
                    "execution_proof_required_during_each_handoff"
                ]
            )

    def test_embedded_distributed_probe_is_syntactically_valid_and_bounded(self):
        command = owner_command(4)
        prefix = "cat > /tmp/sqwish-owner-distributed-probe.py <<'PY'\n"
        source = command.split(prefix, 1)[1].split("\nPY\n", 1)[0]
        compile(source, "sqwish-owner-distributed-probe.py", "exec")
        self.assertIn("MAX_CHECKPOINTS = 1440", source)
        self.assertIn("MATRIX_DIMENSION = 2048", source)
        self.assertIn("timeout=dt.timedelta(seconds=120)", source)

    def test_owner_probe_rejects_unsupported_gpu_shape(self):
        with self.assertRaisesRegex(StandbyError, "exactly 1, 2, 4, or 8"):
            owner_command(3)

    def test_create_uncertainty_unlists_without_retry_or_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller, state, _, root = self.controller(tmp, "uncertain-create")
            controller.preflight()
            with self.assertRaisesRegex(StandbyError, "non-JSON"):
                controller.prepare()
            verbs = [call[:2] for call in state.calls]
            self.assertEqual(verbs.count(["create", "instance"]), 1)
            self.assertEqual(verbs.count(["unlist", "machine"]), 1)
            self.assertEqual(verbs.count(["stop", "instance"]), 0)
            self.assertEqual(verbs.count(["destroy", "instance"]), 0)
            self.assertFalse(state.listed)
            self.assertTrue((root / "owner-standby-create-unresolved.json").exists())

    def test_rc_zero_structured_api_rejection_is_reported_and_unlisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller, state, _, _ = self.controller(tmp, "structured-list-rejection")
            controller.preflight()
            with self.assertRaisesRegex(StandbyError, "status 422: price outside accepted range"):
                controller.prepare()
            verbs = [call[:2] for call in state.calls]
            self.assertEqual(verbs.count(["list", "machine"]), 1)
            self.assertEqual(verbs.count(["unlist", "machine"]), 1)
            self.assertEqual(verbs.count(["create", "instance"]), 0)
            self.assertEqual(verbs.count(["destroy", "instance"]), 0)
            self.assertFalse(state.listed)

    def test_degraded_machine_requires_explicit_diagnostic_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller, state, _, _ = self.controller(tmp, "degraded")
            with self.assertRaisesRegex(StandbyError, "below immutable original"):
                controller.preflight()
            self.assertNotIn(["list", "machine"], [call[:2] for call in state.calls])

        with tempfile.TemporaryDirectory() as tmp:
            controller, _, _, _ = self.controller(
                tmp, "degraded", allow_degraded_diagnostic=True
            )
            controller.preflight()
            result = controller.prepare()
            self.assertTrue(result["diagnostic_only"])

    def test_owner_identity_mismatch_prevents_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller, state, _, _ = self.controller(tmp, "identity-mismatch")
            controller.preflight()
            with self.assertRaisesRegex(StandbyError, "identity mismatch"):
                controller.prepare()
            verbs = [call[:2] for call in state.calls]
            self.assertEqual(verbs.count(["create", "instance"]), 1)
            self.assertEqual(verbs.count(["unlist", "machine"]), 1)
            self.assertEqual(verbs.count(["stop", "instance"]), 0)

    def test_unsafe_stopped_tuple_fails_after_one_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller, state, _, _ = self.controller(tmp, "unsafe-stop")
            controller.preflight()
            with self.assertRaisesRegex(StandbyError, "did not reach safely-stopped"):
                controller.prepare()
            verbs = [call[:2] for call in state.calls]
            self.assertEqual(verbs.count(["stop", "instance"]), 1)
            self.assertEqual(verbs.count(["destroy", "instance"]), 0)

    def test_immutable_baseline_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = config(original_reliability_baseline=0.6)
            load_or_pin_original_baseline(root, first)
            with self.assertRaisesRegex(StandbyError, "immutable pinned value"):
                load_or_pin_original_baseline(
                    root, config(original_reliability_baseline=0.57)
                )

    def test_validation_and_redaction_guards(self):
        validate_config(config(), wall_time=0)
        validate_config(config(gpu_count=4), wall_time=0)
        with self.assertRaisesRegex(StandbyError, "exactly 1, 2, 4, or 8"):
            validate_config(config(gpu_count=3), wall_time=0)
        validate_config(config(fixed_end_epoch=30 * 60 * 60), wall_time=0)
        with self.assertRaisesRegex(StandbyError, "no more than 48 hours"):
            validate_config(config(fixed_end_epoch=49 * 60 * 60), wall_time=0)
        with self.assertRaisesRegex(StandbyError, r"at least \$1"):
            validate_config(config(p99_host_bid_floor=0.5), wall_time=0)
        rendered = sanitize_text(
            json.dumps(
                {
                    "instance_api_key": "S" * 48,
                    "email": "operator@example.test",
                    "public_ip": "203.0.113.11",
                    "ssh_public_key": "ssh-ed25519 short-key",
                    "image": IMAGE,
                }
            )
        )
        self.assertNotIn("S" * 48, rendered)
        self.assertNotIn("operator@example.test", rendered)
        self.assertNotIn("203.0.113.11", rendered)
        self.assertNotIn("short-key", rendered)
        self.assertIn("sha256:" + "a" * 64, rendered)
        raw = sanitize_text(
            'error email=operator@example.test public_ip=203.0.113.11 '
            'ssh_public_key="ssh-ed25519 short-key"'
        )
        self.assertNotIn("operator@example.test", raw)
        self.assertNotIn("203.0.113.11", raw)
        self.assertNotIn("short-key", raw)


if __name__ == "__main__":
    unittest.main()
