import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.controlled_acquisition import (
    Acquisition,
    AcquisitionError,
    Config,
    exact_no_such_ask_rejection,
    parse_args,
    redact,
    sanitize_evidence,
    validate_config,
)


def config(**changes):
    values = dict(
        machine_id="9001",
        host_cli="host-vastai",
        client_cli="client-vastai",
        fixed_end_epoch=2_000_000_000,
        p99_host_on_demand_price=99.0,
        p99_host_bid_floor=0.6,
        expected_renter_on_demand_price=264.0,
        expected_renter_bid_floor=1.6,
        client_bid_price=1.61,
        disk_price=0.1,
        upload_price=0.01,
        download_price=0.02,
        image="pytorch/pytorch:cuda@sha256:" + "a" * 64,
        disk_gb=10.0,
        label="controlled-acquire-test",
        contracts_reviewed=True,
        offer_timeout=2.0,
        offer_stability_seconds=2.0,
        running_timeout=2.0,
        absence_timeout=5.0,
        poll_seconds=1.0,
        max_public_seconds=600,
        max_fixed_end_seconds=900,
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
        self.unknown_rental = False
        self.listed_machine_queries = 0
        self.listed_bid_queries = 0
        self.listed_on_demand_queries = 0
        self.calls = []

    def machine(self):
        if self.listed:
            self.listed_machine_queries += 1
            if self.scenario == "unknown-contract" and self.listed_machine_queries >= 2:
                self.unknown_rental = True
        rentals = 1 if self.created or self.unknown_rental else 0
        value = {
            "id": 9001,
            "num_gpus": 2,
            "current_rentals_running": rentals,
        }
        if self.listed:
            value.update(
                {
                    "listed_min_gpu_count": 2,
                    "listed_gpu_cost": self.cfg.p99_host_on_demand_price,
                    "min_bid_price": self.cfg.p99_host_bid_floor,
                    "end_date": self.cfg.fixed_end_epoch,
                }
            )
        return [value]

    def listing_response(self):
        return {
            "success": True,
            "you_sent": {
                "machine": 9001,
                "min_chunk": 2,
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

    def offer(self, offer_type):
        if not self.listed:
            return []
        if offer_type == "bid":
            self.listed_bid_queries += 1
            if self.scenario == "bid-flicker" and self.listed_bid_queries == 2:
                return []
        if offer_type == "on-demand":
            self.listed_on_demand_queries += 1
            if self.scenario == "on-demand-flicker" and self.listed_on_demand_queries >= 2:
                return []
        end = self.cfg.fixed_end_epoch
        if self.scenario == "fixed-end-mismatch" and offer_type == "bid":
            end += 5
        common = {
            "id": 8101 if offer_type == "bid" else 8102,
            "machine_id": 9001,
            "host_id": 101,
            "num_gpus": 2,
            "rentable": True,
            "rented": False,
            "end_date": end,
        }
        if offer_type == "bid":
            common["min_bid"] = self.cfg.expected_renter_bid_floor
        else:
            common["dph_base"] = self.cfg.expected_renter_on_demand_price
        return [common]

    def instance(self):
        return {
            "id": 7001,
            "machine_id": 9001,
            "label": self.cfg.label,
            "is_bid": True,
            "num_gpus": 2,
            "ask_contract_id": 8101,
            "host_id": 101,
            "image_uuid": self.cfg.image,
            "disk_space": self.cfg.disk_gb,
            "end_date": self.cfg.fixed_end_epoch,
            "bid_price": self.cfg.client_bid_price,
            "actual_status": "running",
            "intended_status": "running",
            "cur_state": "running",
        }


class FakeCli:
    def __init__(self, role, state):
        self.role = role
        self.state = state
        self.executable = f"/{role}-vastai"

    def run(self, args, *, check=False):
        self.state.calls.append((self.role, list(args)))
        command = args[:2]
        stdout = ""
        returncode = 0
        stderr = ""
        if command == ["show", "user"]:
            stdout = json.dumps({"id": 101 if self.role == "host" else 202})
        elif command == ["show", "machine"] and self.role == "host":
            stdout = json.dumps(self.state.machine())
        elif command == ["show", "instances"]:
            rows = [self.state.instance()] if self.role == "client" and self.state.created else []
            stdout = json.dumps(rows)
        elif command == ["show", "instance"] and self.role == "client":
            stdout = json.dumps([self.state.instance()] if self.state.created else [])
        elif command == ["search", "offers"] and self.role == "client":
            offer_type = args[args.index("--type") + 1]
            stdout = json.dumps(self.state.offer(offer_type))
        elif command == ["list", "machine"] and self.role == "host":
            self.state.listed = True
            stdout = json.dumps(self.state.listing_response())
        elif command == ["unlist", "machine"] and self.role == "host":
            self.state.listed = False
            stdout = "machine unlisted\n"
        elif command == ["create", "instance"] and self.role == "client":
            if self.state.scenario == "create-no-such-ask":
                stderr = json.dumps(
                    {
                        "error": True,
                        "status_code": 400,
                        "msg": "error 400: no_such_ask Instance type by id 8101 is not available",
                    }
                )
            elif self.state.scenario == "create-no-such-ask-410":
                stderr = json.dumps(
                    {
                        "error": True,
                        "status_code": 410,
                        "msg": "error 410: no_such_ask Instance type by id 8101 is not available",
                    }
                )
            elif self.state.scenario == "create-uncertainty":
                self.state.created = True
                stdout = "upstream response unavailable"
            else:
                self.state.created = True
                stdout = json.dumps({"success": True, "new_contract": 7001, "instance_api_key": "x" * 48})
        else:
            returncode = 90
            stderr = f"unexpected fake command: {args}"
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)


class MultiFakeState:
    def __init__(self, cfg, scenario="happy"):
        self.cfg = cfg
        self.scenario = scenario
        self.listed = False
        self.ever_unlisted = False
        self.created = []
        self.calls = []

    def machine(self):
        value = {
            "id": 9001,
            "num_gpus": 4,
            "current_rentals_running": len(self.created),
        }
        if self.listed:
            value.update(
                {
                    "listed_min_gpu_count": 1,
                    "listed_gpu_cost": self.cfg.p99_host_on_demand_price,
                    "min_bid_price": self.cfg.p99_host_bid_floor,
                    "end_date": self.cfg.fixed_end_epoch,
                }
            )
        return [value]

    def listing_response(self):
        return {
            "success": True,
            "you_sent": {
                "machine": 9001,
                "min_chunk": 1,
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

    def offer(self, offer_type, *, exact_slice=True):
        if (
            self.scenario == "residual-large-offer"
            and self.ever_unlisted
            and not exact_slice
        ):
            return [
                {
                    "id": 9901 if offer_type == "bid" else 9902,
                    "machine_id": 9001,
                    "host_id": 101,
                    "num_gpus": 2,
                    "rentable": True,
                    "rented": False,
                    "end_date": self.cfg.fixed_end_epoch,
                }
            ]
        if not self.listed or len(self.created) >= 4:
            return []
        offset = len(self.created)
        row = {
            "id": (8101 if offer_type == "bid" else 9101) + offset,
            "machine_id": 9001,
            "host_id": 101,
            "num_gpus": 1,
            "rentable": True,
            "rented": False,
            "end_date": self.cfg.fixed_end_epoch,
        }
        if offer_type == "bid":
            row["min_bid"] = self.cfg.expected_renter_bid_floor
        else:
            row["dph_base"] = self.cfg.expected_renter_on_demand_price
        return [row]

    def instance(self, item):
        return {
            "id": item["instance_id"],
            "machine_id": 9001,
            "label": item["label"],
            "is_bid": True,
            "num_gpus": 1,
            "ask_contract_id": item["offer_id"],
            "host_id": 101,
            "image_uuid": self.cfg.image,
            "disk_space": self.cfg.disk_gb,
            "end_date": self.cfg.fixed_end_epoch,
            "bid_price": self.cfg.client_bid_price,
            "actual_status": "running",
            "intended_status": "running",
            "cur_state": "running",
        }

    def owner_standby(self):
        if self.cfg.allowed_owner_standby_id is None:
            return None
        return {
            "id": int(self.cfg.allowed_owner_standby_id),
            "machine_id": 9001,
            "label": self.cfg.allowed_owner_standby_label,
            "is_bid": False,
            "num_gpus": 4,
            "actual_status": "exited",
            "intended_status": "stopped",
            "cur_state": "stopped",
        }


class MultiFakeCli:
    def __init__(self, role, state):
        self.role = role
        self.state = state
        self.executable = f"/{role}-vastai"

    def run(self, args, *, check=False):
        self.state.calls.append((self.role, list(args)))
        command = args[:2]
        stdout = ""
        returncode = 0
        stderr = ""
        if command == ["show", "user"]:
            stdout = json.dumps({"id": 101 if self.role == "host" else 202})
        elif command == ["show", "machine"] and self.role == "host":
            stdout = json.dumps(self.state.machine())
        elif command == ["show", "instances"]:
            if self.role == "client":
                rows = [self.state.instance(item) for item in self.state.created]
            else:
                owner = self.state.owner_standby()
                rows = [] if owner is None else [owner]
            stdout = json.dumps(rows)
        elif command == ["show", "instance"] and self.role == "client":
            instance_id = args[2]
            rows = [
                self.state.instance(item)
                for item in self.state.created
                if item["instance_id"] == instance_id
            ]
            if (
                self.state.scenario == "single-fourth-stopped"
                and instance_id == "7004"
                and rows
            ):
                rows[0].update(
                    {
                        "actual_status": "exited",
                        "intended_status": "stopped",
                        "cur_state": "stopped",
                    }
                )
            stdout = json.dumps(rows)
        elif command == ["search", "offers"] and self.role == "client":
            exact_slice = "num_gpus=1" in args[2]
            if self.state.listed:
                self.assert_exact_one_gpu_query(args)
            offer_type = args[args.index("--type") + 1]
            stdout = json.dumps(self.state.offer(offer_type, exact_slice=exact_slice))
        elif command == ["list", "machine"] and self.role == "host":
            self.state.listed = True
            stdout = json.dumps(self.state.listing_response())
        elif command == ["unlist", "machine"] and self.role == "host":
            self.state.listed = False
            self.state.ever_unlisted = True
            stdout = "machine unlisted\n"
        elif command == ["create", "instance"] and self.role == "client":
            label = args[args.index("--label") + 1]
            offer_id = args[2]
            item = {
                "instance_id": str(7001 + len(self.state.created)),
                "offer_id": offer_id,
                "label": label,
            }
            self.state.created.append(item)
            if self.state.scenario == "uncertain-third" and len(self.state.created) == 3:
                stdout = "upstream response unavailable"
            else:
                stdout = json.dumps(
                    {
                        "success": True,
                        "new_contract": int(item["instance_id"]),
                        "instance_api_key": "short-secret",
                    }
                )
        else:
            returncode = 90
            stderr = f"unexpected fake command: {args}"
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    @staticmethod
    def assert_exact_one_gpu_query(args):
        query = args[2]
        if (
            "machine_id=9001" not in query
            or "num_gpus=1" not in query
            or "rentable=true" not in query
            or "rented=false" not in query
        ):
            raise AssertionError(f"offer query was not the exact one-GPU machine slice: {query}")


class ControlledAcquisitionTests(unittest.TestCase):
    MULTI_LABELS = (
        "controlled-client-01",
        "controlled-client-02",
        "controlled-client-03",
        "controlled-client-04",
    )

    def controller(self, tmp, scenario="happy", **cfg_changes):
        cfg = config(**cfg_changes)
        root = Path(tmp)
        run_dir = root / "runs" / "one"
        run_dir.mkdir(parents=True)
        state = FakeState(cfg, scenario)
        clock = FakeClock()
        acquisition = Acquisition(
            cfg,
            FakeCli("host", state),
            FakeCli("client", state),
            root,
            run_dir,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            wall_time=lambda: 1_999_999_500.0,
        )
        return acquisition, state, run_dir

    def multi_controller(self, tmp, scenario="happy", **cfg_changes):
        cfg = config(
            gpu_count=4,
            client_labels=self.MULTI_LABELS,
            label="controlled-four-slice-run",
            **cfg_changes,
        )
        root = Path(tmp)
        run_dir = root / "runs" / "four"
        run_dir.mkdir(parents=True)
        state = MultiFakeState(cfg, scenario)
        clock = FakeClock()
        acquisition = Acquisition(
            cfg,
            MultiFakeCli("host", state),
            MultiFakeCli("client", state),
            root,
            run_dir,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            wall_time=lambda: 1_999_999_500.0,
        )
        return acquisition, state, run_dir

    @staticmethod
    def mutations(state, command):
        return [args for _role, args in state.calls if args[:2] == command]

    def test_allowed_owner_standby_must_supply_id_and_label_together(self):
        with self.assertRaisesRegex(AcquisitionError, "must be supplied together"):
            validate_config(
                config(allowed_owner_standby_id="6001"),
                now=1_999_999_500.0,
            )

    def test_exact_safely_stopped_owner_standby_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            acquisition, _state, _run_dir = self.controller(
                tmp,
                allowed_owner_standby_id="6001",
                allowed_owner_standby_label="owned-standby-test",
            )
            acquisition.require_no_target_host_instances(
                [
                    {
                        "id": 6001,
                        "machine_id": 9001,
                        "label": "owned-standby-test",
                        "is_bid": False,
                        "num_gpus": 2,
                        "actual_status": "exited",
                        "intended_status": "stopped",
                        "cur_state": "stopped",
                    }
                ],
                "test",
            )

    def test_owner_standby_allowance_rejects_running_or_extra_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            acquisition, _state, _run_dir = self.controller(
                tmp,
                allowed_owner_standby_id="6001",
                allowed_owner_standby_label="owned-standby-test",
            )
            allowed = {
                "id": 6001,
                "machine_id": 9001,
                "label": "owned-standby-test",
                "is_bid": False,
                "num_gpus": 2,
                "actual_status": "running",
                "intended_status": "running",
                "cur_state": "running",
            }
            with self.assertRaisesRegex(AcquisitionError, "stopped-state tuple"):
                acquisition.require_no_target_host_instances([allowed], "test")
            allowed.update(
                {
                    "actual_status": "exited",
                    "intended_status": "stopped",
                    "cur_state": "stopped",
                }
            )
            with self.assertRaisesRegex(AcquisitionError, "expected exactly one"):
                acquisition.require_no_target_host_instances(
                    [allowed, allowed | {"id": 6002, "label": "unexpected-owner"}],
                    "test",
                )

    def test_fixed_end_horizon_is_independent_from_public_window(self):
        cfg = config(
            fixed_end_epoch=2_000_000_000,
            offer_timeout=180.0,
            max_public_seconds=300,
            max_fixed_end_seconds=7_200,
        )
        validate_config(cfg, now=1_999_994_000.0)

    def test_fixed_end_horizon_still_fails_closed(self):
        cfg = config(
            fixed_end_epoch=2_000_000_000,
            offer_timeout=180.0,
            max_public_seconds=300,
            max_fixed_end_seconds=5_000,
        )
        with self.assertRaisesRegex(AcquisitionError, "fixed-end horizon"):
            validate_config(cfg, now=1_999_994_000.0)

    def test_four_gpu_shape_requires_four_unique_labels_and_bounded_48h_horizon(self):
        labels = self.MULTI_LABELS
        validate_config(
            config(
                gpu_count=4,
                client_labels=labels,
                fixed_end_epoch=2_000_108_000,
                max_fixed_end_seconds=108_000,
            ),
            now=2_000_000_000.0,
        )
        with self.assertRaisesRegex(AcquisitionError, "exactly four"):
            validate_config(
                config(gpu_count=4, client_labels=labels[:3]),
                now=1_999_999_500.0,
            )
        with self.assertRaisesRegex(AcquisitionError, "unique"):
            validate_config(
                config(gpu_count=4, client_labels=labels[:3] + (labels[0],)),
                now=1_999_999_500.0,
            )
        with self.assertRaisesRegex(AcquisitionError, "172800"):
            validate_config(
                config(
                    gpu_count=4,
                    client_labels=labels,
                    fixed_end_epoch=2_000_180_000,
                    max_fixed_end_seconds=180_000,
                ),
                now=2_000_000_000.0,
            )

    def test_four_gpu_shape_reserves_all_create_and_unlist_time(self):
        with self.assertRaisesRegex(AcquisitionError, "all offer discovery"):
            validate_config(
                config(
                    gpu_count=4,
                    client_labels=self.MULTI_LABELS,
                    max_public_seconds=200,
                ),
                now=1_999_999_500.0,
            )
        with self.assertRaisesRegex(AcquisitionError, "between 60 and 600"):
            validate_config(
                config(max_public_seconds=601),
                now=1_999_999_500.0,
            )

    def test_cli_parses_four_repeatable_client_labels_as_exact_tuple(self):
        args = [
            "--machine-id", "9001",
            "--client-cli", "client-vastai",
            "--gpu-count", "4",
            "--fixed-end-epoch", "2000000000",
            "--p99-host-on-demand-price", "99",
            "--p99-host-bid-floor", "0.6",
            "--expected-renter-on-demand-price", "132",
            "--expected-renter-bid-floor", "0.8",
            "--client-bid-price", "0.81",
            "--disk-price", "0.1",
            "--upload-price", "0.01",
            "--download-price", "0.02",
            "--image", "pytorch/pytorch:cuda@sha256:" + "a" * 64,
            "--label", "controlled-four-slice-run",
        ]
        for label in self.MULTI_LABELS:
            args.extend(["--client-label", label])
        parsed = parse_args(args)
        self.assertEqual(parsed.gpu_count, 4)
        self.assertEqual(parsed.client_labels, self.MULTI_LABELS)

    def test_create_refuses_after_reserved_unlist_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            acquisition, state, _run_dir = self.controller(
                tmp,
                max_public_seconds=60,
            )
            acquisition.listed_at = 0.0
            acquisition.sleep(15.0)
            with self.assertRaisesRegex(AcquisitionError, "action budget expired"):
                acquisition.create_once("8101")
            self.assertEqual(len(self.mutations(state, ["create", "instance"])), 0)

    def test_public_window_watchdog_attempts_exact_unlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            acquisition, state, run_dir = self.controller(
                tmp,
                max_public_seconds=1,
            )
            acquisition.start_public_watchdog()
            acquisition.watchdog_thread.join(timeout=1.0)
            acquisition.stop_public_watchdog()

            self.assertEqual(len(self.mutations(state, ["unlist", "machine"])), 1)
            self.assertTrue(acquisition.public_cutoff.is_set())
            evidence = json.loads(
                (run_dir / "public-window-watchdog.json").read_text(encoding="utf-8")
            )
            self.assertEqual(evidence["machine_id"], "9001")

    def test_happy_path_lists_creates_once_unlists_and_proves_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            acquisition, state, run_dir = self.controller(tmp)
            acquisition.preflight()
            result = acquisition.acquire("LIST 9001 ONCE")

            self.assertEqual(result["status"], "controlled-contract-running-and-machine-unlisted")
            self.assertEqual(len(self.mutations(state, ["list", "machine"])), 1)
            self.assertEqual(len(self.mutations(state, ["create", "instance"])), 1)
            self.assertEqual(len(self.mutations(state, ["unlist", "machine"])), 1)
            self.assertFalse(any(args[:2] == ["destroy", "instance"] for _role, args in state.calls))
            self.assertFalse(state.listed)
            self.assertFalse(acquisition.create_marker.exists())
            self.assertFalse(acquisition.listing_marker.exists())
            absence = json.loads((run_dir / "unlisted-proved.json").read_text(encoding="utf-8"))
            self.assertEqual(absence["consecutive_absence_samples"], 3)
            stability = json.loads((run_dir / "offer-stability.json").read_text(encoding="utf-8"))
            self.assertEqual(stability["offer_id"], "8101")
            self.assertGreaterEqual(stability["elapsed_seconds"], 2.0)
            self.assertGreaterEqual(stability["full_guard_samples"], 3)

    def test_four_one_gpu_creates_cover_exact_machine_then_unlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            acquisition, state, run_dir = self.multi_controller(
                tmp,
                allowed_owner_standby_id="6001",
                allowed_owner_standby_label="sqwish-owner-standby",
            )
            acquisition.preflight()
            result = acquisition.acquire("LIST 9001 ONCE")

            self.assertEqual(
                result["status"],
                "controlled-contracts-running-and-machine-unlisted",
            )
            creates = self.mutations(state, ["create", "instance"])
            self.assertEqual(len(creates), 4)
            self.assertEqual(
                [args[args.index("--label") + 1] for args in creates],
                list(self.MULTI_LABELS),
            )
            listing = self.mutations(state, ["list", "machine"])
            self.assertEqual(len(listing), 1)
            self.assertEqual(listing[0][listing[0].index("--min_chunk") + 1], "1")
            self.assertEqual(len(self.mutations(state, ["unlist", "machine"])), 1)
            self.assertFalse(state.listed)
            unlist_index = next(
                index
                for index, (_role, args) in enumerate(state.calls)
                if args[:2] == ["unlist", "machine"]
            )
            absence_queries = [
                args[2]
                for _role, args in state.calls[unlist_index + 1 :]
                if args[:2] == ["search", "offers"]
            ]
            self.assertTrue(absence_queries)
            self.assertTrue(all("num_gpus=" not in query for query in absence_queries))
            self.assertEqual(result["gpu_count"], 4)
            self.assertEqual(result["contract_gpu_count"], 1)
            self.assertEqual(result["create_calls"], 4)
            self.assertEqual(result["client_labels"], list(self.MULTI_LABELS))
            self.assertEqual(len(set(result["instance_ids"])), 4)
            self.assertEqual(
                {record["end_date"] for record in result["records"]},
                {acquisition.cfg.fixed_end_epoch},
            )
            self.assertTrue((run_dir / "controlled-contracts-running-04.json").exists())
            absence = json.loads((run_dir / "unlisted-proved.json").read_text())
            self.assertEqual(absence["consecutive_absence_samples"], 3)
            self.assertFalse(acquisition.create_marker.exists())
            self.assertFalse(
                any(args[:2] == ["destroy", "instance"] for _role, args in state.calls)
            )

    def test_four_gpu_unlist_proof_rejects_residual_larger_offer_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            acquisition, state, _run_dir = self.multi_controller(
                tmp,
                "residual-large-offer",
            )
            acquisition.preflight()
            with self.assertRaisesRegex(AcquisitionError, "unlist proof"):
                acquisition.acquire("LIST 9001 ONCE")

            self.assertEqual(len(self.mutations(state, ["create", "instance"])), 4)
            self.assertEqual(len(self.mutations(state, ["unlist", "machine"])), 1)
            self.assertTrue(acquisition.listing_marker.exists())
            self.assertTrue(acquisition.create_marker.exists())

    def test_four_gpu_all_contract_proof_requires_single_and_full_views_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            acquisition, state, _run_dir = self.multi_controller(
                tmp,
                "single-fourth-stopped",
            )
            acquisition.preflight()
            with self.assertRaisesRegex(AcquisitionError, "last single states"):
                acquisition.acquire("LIST 9001 ONCE")

            self.assertEqual(len(self.mutations(state, ["create", "instance"])), 4)
            self.assertEqual(len(self.mutations(state, ["unlist", "machine"])), 1)
            self.assertTrue(acquisition.create_marker.exists())

    def test_four_gpu_uncertain_third_label_fails_closed_without_fourth_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            acquisition, state, run_dir = self.multi_controller(tmp, "uncertain-third")
            acquisition.preflight()
            with self.assertRaisesRegex(AcquisitionError, "non-JSON"):
                acquisition.acquire("LIST 9001 ONCE")

            creates = self.mutations(state, ["create", "instance"])
            self.assertEqual(len(creates), 3)
            self.assertEqual(
                [args[args.index("--label") + 1] for args in creates],
                list(self.MULTI_LABELS[:3]),
            )
            self.assertFalse(state.listed)
            self.assertEqual(len(self.mutations(state, ["unlist", "machine"])), 1)
            marker = json.loads(acquisition.create_marker.read_text(encoding="utf-8"))
            self.assertEqual(marker["status"], "create-unresolved-no-retry")
            self.assertEqual(marker["attempted_labels"], list(self.MULTI_LABELS[:3]))
            self.assertEqual(len(marker["created_contracts"]), 2)
            reconciliation = json.loads(
                (run_dir / "create-uncertainty-reconciliation.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(len(reconciliation["client_instances"]), 3)
            self.assertFalse(
                any(args[:2] == ["destroy", "instance"] for _role, args in state.calls)
            )

    def test_on_demand_view_may_lag_after_initial_price_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            acquisition, state, _run_dir = self.controller(tmp, "on-demand-flicker")
            acquisition.preflight()
            result = acquisition.acquire("LIST 9001 ONCE")

            self.assertEqual(result["status"], "controlled-contract-running-and-machine-unlisted")
            self.assertEqual(len(self.mutations(state, ["create", "instance"])), 1)
            self.assertEqual(state.listed_on_demand_queries, 1)
            self.assertFalse(state.listed)

    def test_transient_bid_absence_resets_stability_without_creating_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            acquisition, state, run_dir = self.controller(tmp, "bid-flicker")
            acquisition.preflight()
            result = acquisition.acquire("LIST 9001 ONCE")

            self.assertEqual(result["status"], "controlled-contract-running-and-machine-unlisted")
            self.assertEqual(len(self.mutations(state, ["create", "instance"])), 1)
            stability = json.loads((run_dir / "offer-stability.json").read_text(encoding="utf-8"))
            self.assertEqual(stability["transient_absences"], 1)
            self.assertFalse(state.listed)

    def test_fixed_end_mismatch_unlists_without_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            acquisition, state, _run_dir = self.controller(tmp, "fixed-end-mismatch")
            acquisition.preflight()
            with self.assertRaisesRegex(AcquisitionError, "fixed end"):
                acquisition.acquire("LIST 9001 ONCE")

            self.assertEqual(len(self.mutations(state, ["create", "instance"])), 0)
            self.assertEqual(len(self.mutations(state, ["unlist", "machine"])), 1)
            self.assertFalse(state.listed)
            self.assertFalse(acquisition.listing_marker.exists())

    def test_uncertain_create_is_never_retried_or_destroyed(self):
        with tempfile.TemporaryDirectory() as tmp:
            acquisition, state, run_dir = self.controller(tmp, "create-uncertainty")
            acquisition.preflight()
            with self.assertRaisesRegex(AcquisitionError, "non-JSON"):
                acquisition.acquire("LIST 9001 ONCE")

            self.assertEqual(len(self.mutations(state, ["create", "instance"])), 1)
            self.assertEqual(len(self.mutations(state, ["unlist", "machine"])), 1)
            self.assertFalse(any(args[:2] == ["destroy", "instance"] for _role, args in state.calls))
            marker = json.loads(acquisition.create_marker.read_text(encoding="utf-8"))
            self.assertEqual(marker["status"], "create-unresolved-no-retry")
            reconciliation = json.loads(
                (run_dir / "create-uncertainty-reconciliation.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(reconciliation["client_instances"]), 1)

    def test_exact_structured_no_such_ask_is_definitive_no_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            acquisition, state, run_dir = self.controller(tmp, "create-no-such-ask")
            acquisition.preflight()
            with self.assertRaisesRegex(AcquisitionError, "definitively rejected"):
                acquisition.acquire("LIST 9001 ONCE")

            self.assertEqual(len(self.mutations(state, ["create", "instance"])), 1)
            self.assertEqual(len(self.mutations(state, ["unlist", "machine"])), 1)
            self.assertFalse(state.created)
            self.assertFalse(state.listed)
            self.assertFalse(acquisition.create_marker.exists())
            self.assertFalse((run_dir / "create-uncertainty-reconciliation.json").exists())
            evidence = json.loads(
                (run_dir / "create-definitive-no-contract.json").read_text(encoding="utf-8")
            )
            self.assertEqual(evidence["classification"], "definitive-no-contract")
            self.assertEqual(evidence["structured_stderr"]["status_code"], 400)
            self.assertTrue(evidence["unlist_proved"])

    def test_non_400_no_such_ask_remains_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            acquisition, state, run_dir = self.controller(tmp, "create-no-such-ask-410")
            acquisition.preflight()
            with self.assertRaisesRegex(AcquisitionError, "non-JSON"):
                acquisition.acquire("LIST 9001 ONCE")

            self.assertEqual(len(self.mutations(state, ["create", "instance"])), 1)
            marker = json.loads(acquisition.create_marker.read_text(encoding="utf-8"))
            self.assertEqual(marker["status"], "create-unresolved-no-retry")
            self.assertTrue((run_dir / "create-uncertainty-reconciliation.json").exists())

    def test_no_such_ask_classifier_requires_exact_shape(self):
        exact = subprocess.CompletedProcess(
            [],
            0,
            "",
            json.dumps(
                {
                    "error": True,
                    "status_code": 400,
                    "msg": "HTTP 400 no_such_ask ask 8101 vanished",
                }
            ),
        )
        self.assertEqual(exact_no_such_ask_rejection(exact)["status_code"], 400)
        near_misses = [
            subprocess.CompletedProcess([], 0, "{}", exact.stderr),
            subprocess.CompletedProcess([], 0, "", '{"error":true,"status_code":410,"msg":"no_such_ask"}'),
            subprocess.CompletedProcess([], 0, "", '{"error":true,"status_code":400,"msg":"no_such_ask_later"}'),
            subprocess.CompletedProcess([], 0, "", "not-json"),
        ]
        self.assertTrue(all(exact_no_such_ask_rejection(item) is None for item in near_misses))

    def test_redact_covers_short_secrets_in_raw_json_cli_output(self):
        value = redact(
            'stdout={"instance_api_key":"short-json-secret","password":"tiny",'
            '"email":"operator@example.test","public_ip":"203.0.113.7",'
            '"ssh_public_key":"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFake"}'
        )
        self.assertNotIn("short-json-secret", value)
        self.assertNotIn('"tiny"', value)
        self.assertNotIn("operator@example.test", value)
        self.assertNotIn("203.0.113.7", value)
        self.assertNotIn("AAAAC3Nza", value)
        self.assertGreaterEqual(value.count("<redacted>"), 3)

        structured = sanitize_evidence(
            {
                "instance_api_key": "tiny",
                "nested": {"token": "short-json-secret"},
                "email": "operator@example.test",
                "public_ip": "203.0.113.7",
                "ssh_public_key": "ssh-ed25519 short-key",
                "image": config().image,
                "label": config().label,
            }
        )
        self.assertEqual(structured["instance_api_key"], "<redacted>")
        self.assertEqual(structured["nested"]["token"], "<redacted>")
        self.assertEqual(structured["email"], "<redacted>")
        self.assertEqual(structured["public_ip"], "<redacted>")
        self.assertEqual(structured["ssh_public_key"], "<redacted>")
        self.assertEqual(structured["image"], config().image)
        self.assertEqual(structured["label"], config().label)

    def test_unknown_contract_before_create_unlists_and_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            acquisition, state, _run_dir = self.controller(tmp, "unknown-contract")
            acquisition.preflight()
            with self.assertRaisesRegex(AcquisitionError, "not vacant"):
                acquisition.acquire("LIST 9001 ONCE")

            self.assertEqual(len(self.mutations(state, ["create", "instance"])), 0)
            self.assertEqual(len(self.mutations(state, ["unlist", "machine"])), 1)
            self.assertTrue(acquisition.contract_marker.exists())
            self.assertFalse(state.listed)


if __name__ == "__main__":
    unittest.main()
