import io
import json
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools.controlled_hostjob_cycle import (
    Config,
    Cycle,
    CycleError,
    OWNER_LOG_TAIL_LINES,
    OWNER_WORKLOAD_MAX_HEARTBEATS,
    OWNER_COMMAND,
    PYTORCH_WORKLOAD,
    atomic_json,
    authenticated_account_id,
    build_defjob_args,
    build_list_args,
    build_production_readiness_result,
    delayed_rating_skip_reason,
    exact_end_is_proved,
    ensure_client_not_configured_owner,
    full_list_is_explicitly_absent,
    health_is_clear,
    load_or_pin_original_reliability_baseline,
    machine_summary,
    mutation_explicitly_succeeded,
    original_reliability_assessment,
    parse_reports_output,
    parse_workload_log,
    rating_gate_passes,
    require_original_reliability_floor,
    require_client_identity,
    require_full_machine_capacity,
    require_no_default_job,
    single_instance_is_explicitly_absent,
    strict_offer_records,
    validate_config,
    verify_listing_postconditions,
)


def config(**changes):
    values = dict(
        machine_id="9001",
        client_instance_id="7001",
        client_label="controlled-client-clean-cycle",
        host_cli="host-vastai",
        client_cli="client-vastai",
        fixed_end_epoch=2_000_000_000,
        on_demand_price=99.0,
        listing_floor=0.6,
        expected_renter_floor=1.6,
        expected_renter_on_demand=264.0,
        disk_price=0.1,
        upload_price=0.01,
        download_price=0.02,
        host_job_low=0.4,
        host_job_high=1.3,
        expected_owner_low_renter_price=0.5333333333333333,
        expected_owner_high_renter_price=1.7333333333333334,
        owner_image="pytorch/pytorch:cuda@sha256:" + "a" * 64,
        original_reliability_baseline=0.99,
        delayed_seconds=7200,
    )
    values.update(changes)
    return Config(**values)


def client_record(**changes):
    value = dict(
        id=7001,
        machine_id=9001,
        label="controlled-client-clean-cycle",
        is_bid=True,
        num_gpus=2,
        actual_status="stopped",
        intended_status="stopped",
        cur_state="stopped",
    )
    value.update(changes)
    return value


def machine_record(**changes):
    value = dict(
        id=9001,
        num_gpus=2,
        reliability2=0.99,
        verification="verified",
        num_reports=None,
        num_recent_reports=None,
        error_description="",
        vm_error_level=0,
        vm_error_msg="",
        bid_image=None,
        bid_image_args=[],
        bid_gpu_cost=None,
    )
    value.update(changes)
    return value


def listing_state(cfg=None):
    cfg = cfg or config()
    response = {
        "success": True,
        "you_sent": {
            "machine": int(cfg.machine_id),
            "end_date": cfg.fixed_end_epoch,
            "min_chunk": 2,
            "vol_size": 0,
            "price_gpu": cfg.on_demand_price,
            "price_min_bid": cfg.listing_floor,
            "price_disk": cfg.disk_price,
            "price_inetu": cfg.upload_price,
            "price_inetd": cfg.download_price,
            "credit_discount_max": 0.0,
        },
    }
    machine = [machine_record(
        end_date=cfg.fixed_end_epoch,
        listed_min_gpu_count=2,
        listed_gpu_cost=cfg.on_demand_price,
        min_bid_price=cfg.listing_floor,
    )]
    bid = [{
        "id": 8101,
        "machine_id": 9001,
        "num_gpus": 2,
        "end_date": cfg.fixed_end_epoch,
        "min_bid": cfg.expected_renter_floor,
    }]
    on_demand = [{
        "id": 8102,
        "machine_id": 9001,
        "num_gpus": 2,
        "end_date": cfg.fixed_end_epoch,
        "dph_base": cfg.expected_renter_on_demand,
    }]
    return response, machine, bid, on_demand


def owner_job(job_id, **changes):
    value = {
        "id": job_id,
        "machine_id": 9001,
        "is_bid": True,
        "num_gpus": 1,
        "image_uuid": config().owner_image,
        "image_args": ["/bin/bash", "-lc", OWNER_COMMAND],
        "actual_status": "running",
        "intended_status": "running",
        "cur_state": "running",
        "dph_base": config().expected_owner_high_renter_price,
    }
    value.update(changes)
    return value


class FakeCli:
    def __init__(self):
        self.run_calls = []
        self.json_calls = []
        self.json_handler = lambda _args, _check=True: []
        self.run_stdout = '{"success": true}'

    def run(self, args, **_kwargs):
        self.run_calls.append(args)
        stdout = "reports: []" if args and args[0] == "reports" else self.run_stdout
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

    def json(self, args, *, check=True):
        self.json_calls.append(args)
        return self.json_handler(args, check)


class ManualStartCycle(Cycle):
    def __init__(self, cfg, run_dir, fake_client):
        super().__init__(cfg, object(), fake_client, run_dir, sleep=lambda _: None, monotonic=lambda: 0)
        self._record = client_record()
        self._host_instances = [
            owner_job(
                6001,
                actual_status="loading",
                intended_status="stopped",
                cur_state="unloaded",
                dph_base=cfg.expected_owner_low_renter_price,
            ),
            owner_job(
                6002,
                actual_status="loading",
                intended_status="stopped",
                cur_state="unloaded",
                dph_base=cfg.expected_owner_low_renter_price,
            ),
        ]
        self.owner_job_ids = ("6001", "6002")
        self.overlap_on_snapshot = False

    def query_client(self):
        require_client_identity(self._record, self.cfg)
        return self._record

    def query_host_instances(self):
        return self._host_instances

    def snapshot(self, phase):
        self.sequence += 1
        self._record = client_record(actual_status="running", intended_status="running", cur_state="running")
        if self.overlap_on_snapshot:
            self._host_instances[0] = owner_job(
                6001,
                actual_status="running",
                intended_status="running",
                cur_state="running",
                dph_base=self.cfg.expected_owner_low_renter_price,
            )
        return {"client_instance": self._record, "host_instances": self._host_instances}


class InitialListingFailureCycle(Cycle):
    def query_offers(self, _offer_type):
        return [{"id": 8101, "machine_id": int(self.cfg.machine_id)}]


class PrelistStageFailureCycle(Cycle):
    cleanup_offer_visible = False

    def prove_distinct_accounts(self):
        self.account_ids = {"host": "123", "client": "456"}

    def query_offers(self, _offer_type):
        if self.cleanup_offer_visible:
            return [{"id": 8101, "machine_id": int(self.cfg.machine_id)}]
        return []

    def query_client(self):
        return client_record(actual_status="running", intended_status="running", cur_state="running")

    def query_machine(self):
        return machine_record(bid_image=None, bid_image_args=[], bid_gpu_cost=None)

    def query_host_instances(self):
        return []

    def wait_for_staged_owner_jobs(self):
        raise CycleError("synthetic staging failure")

    def prove_defjob_removed(self):
        return None


class RelistBeforeStageCycle(PrelistStageFailureCycle):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order = []

    def wait_for_listing_postconditions(self, _listing_response):
        self.order.append("listing-proved")

    def wait_for_staged_owner_jobs(self):
        self.order.append("owner-records-awaited")
        raise CycleError("stop after ordering proof")


class ExistingDefjobCycle(PrelistStageFailureCycle):
    def query_machine(self):
        return machine_record(
            bid_image=config().owner_image,
            bid_image_args=["/bin/bash", "-lc", OWNER_COMMAND],
            bid_gpu_cost=config().host_job_low,
        )


class LowGateCycle(PrelistStageFailureCycle):
    def wait_for_listing_postconditions(self, _listing_response):
        return None

    def wait_for_staged_owner_jobs(self):
        return None

    def prove_low_phase(self):
        raise CycleError("synthetic low phase failure")


class DegradedBaselineCycle(PrelistStageFailureCycle):
    def query_machine(self):
        return machine_record(
            reliability2=0.98,
            bid_image=None,
            bid_image_args=[],
            bid_gpu_cost=None,
        )


class MalformedOfferCycle(Cycle):
    def __init__(self, *args, malformed, **kwargs):
        super().__init__(*args, **kwargs)
        self.malformed = malformed

    def query_offers(self, _offer_type):
        return self.malformed


class ControlledHostJobCycleTests(unittest.TestCase):
    def test_defjob_uses_explicit_shell_last_and_network_prices(self):
        cfg = config()
        args = build_defjob_args(cfg, 1.3)
        marker = args.index("--args")
        self.assertEqual(args[marker + 1 : marker + 3], ["/bin/bash", "-lc"])
        self.assertEqual(args[-1], OWNER_COMMAND)
        self.assertEqual(args[args.index("--price_inetu") + 1], f"{cfg.upload_price:.6f}")
        self.assertEqual(args[args.index("--price_inetd") + 1], f"{cfg.download_price:.6f}")
        self.assertNotIn("|| true", OWNER_COMMAND)
        compile(PYTORCH_WORKLOAD, "<owner-workload>", "exec")

    def test_listing_command_has_fixed_end_full_chunk_and_no_volume_offer(self):
        cfg = config()
        args = build_list_args(cfg)
        self.assertEqual(args[args.index("--end_date") + 1], str(cfg.fixed_end_epoch))
        self.assertEqual(args[args.index("--min_chunk") + 1], "2")
        self.assertEqual(args[args.index("--vol_size") + 1], "0")
        self.assertEqual(args[args.index("--discount_rate") + 1], "0")
        self.assertEqual(args[-1], "--raw")

    def test_each_exact_offer_and_machine_must_pass_all_listing_postconditions(self):
        cfg = config()
        response, machine, bid, on_demand = listing_state(cfg)
        verify_listing_postconditions(cfg, response, machine, bid, on_demand)
        self.assertTrue(exact_end_is_proved(cfg.fixed_end_epoch, bid[0]))
        cases = [
            (
                {**response, "you_sent": {**response["you_sent"], "min_chunk": 1}},
                machine,
                bid,
                on_demand,
            ),
            (
                {**response, "you_sent": {**response["you_sent"], "end_date": cfg.fixed_end_epoch + 5}},
                machine,
                bid,
                on_demand,
            ),
            (response, machine, bid + [{**bid[0], "id": 8199}], on_demand),
            (response, machine, [{**bid[0], "end_date": cfg.fixed_end_epoch + 5}], on_demand),
            (response, [{**machine[0], "listed_min_gpu_count": 1}], bid, on_demand),
            (response, [{**machine[0], "min_bid_price": 0.1}], bid, on_demand),
            (response, machine, bid, [{**on_demand[0], "dph_base": 1.0}]),
        ]
        for state in cases:
            with self.subTest(state=state), self.assertRaises(CycleError):
                verify_listing_postconditions(cfg, *state)

    def test_offer_absence_rejects_every_malformed_raw_shape_and_never_authorizes_destroy(self):
        malformed_values = (
            None,
            {},
            {"error": "bad wrapper"},
            [None],
            [{"error": "bad row"}],
            [{"id": 1, "machine_id": 999}, "bad-row"],
        )
        for malformed in malformed_values:
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(CycleError):
                    strict_offer_records(malformed, "bid")
                host, client = FakeCli(), FakeCli()
                cycle = MalformedOfferCycle(
                    config(), host, client, Path(tmp), malformed=malformed, sleep=lambda _seconds: None
                )
                cycle.destroy_authorized = True
                cycle.cycle_started = True
                cycle.unlisted_proved = True
                cycle.cleanup()
                self.assertFalse(cycle.unlisted_proved)
                self.assertEqual(client.run_calls, [])
                self.assertTrue(any("unlist" in error for error in cycle.cleanup_errors))

    @mock.patch("tools.controlled_hostjob_cycle.time.time", return_value=1_999_999_600)
    def test_config_rejects_unsafe_time_bounds_and_zero_or_nonfinite_prices(self, _clock):
        validate_config(config())
        invalid = [
            config(max_public_seconds=601),
            config(max_public_seconds=0),
            config(delayed_seconds=0),
            config(delayed_seconds=7199),
            config(owner_run_seconds=0),
            config(on_demand_price=0),
            config(expected_renter_floor=0),
            config(disk_price=0),
            config(listing_floor=float("nan")),
            config(upload_price=float("inf")),
            config(host_job_high=float("-inf")),
            config(expected_owner_low_renter_price=0),
            config(expected_owner_low_renter_price=2.0, expected_owner_high_renter_price=1.0),
            config(original_reliability_baseline=float("nan")),
            config(original_reliability_baseline=-0.1),
            config(original_reliability_baseline=1.1),
        ]
        for cfg in invalid:
            with self.subTest(cfg=cfg), self.assertRaises(CycleError):
                validate_config(cfg)

    @mock.patch("tools.controlled_hostjob_cycle.time.time", return_value=1_999_999_600)
    def test_owner_image_uses_strict_registry_repo_cuda_tag_and_digest_allowlist(self, _clock):
        validate_config(config())
        invalid = (
            "pytorch/pytorch:cuda",
            "unreviewed/image:cuda@sha256:" + "a" * 64,
            "evil.example/pytorch/pytorch:cuda@sha256:" + "a" * 64,
            "evilpytorch/pytorch:cuda@sha256:" + "a" * 64,
            "pytorch/pytorch:cpu@sha256:" + "a" * 64,
        )
        for image in invalid:
            with self.subTest(image=image), self.assertRaisesRegex(CycleError, "allowlisted"):
                validate_config(config(owner_image=image))

    def test_exact_client_must_fill_exact_two_gpu_machine(self):
        cfg = config()
        client = client_record()
        require_client_identity(client, cfg)
        require_full_machine_capacity(machine_record(), client, cfg)
        for machine, candidate in (
            (machine_record(num_gpus=4), client),
            (machine_record(), client_record(num_gpus=1)),
        ):
            with self.assertRaises(CycleError):
                require_full_machine_capacity(machine, candidate, cfg)

    def test_configured_owner_instance_can_never_be_the_destroyed_client(self):
        ensure_client_not_configured_owner("7001", "")
        ensure_client_not_configured_owner("7001", "8001")
        with self.assertRaisesRegex(CycleError, "VAST_OWN_INSTANCE_ID"):
            ensure_client_not_configured_owner("7001", "7001")

    def test_existing_default_job_is_rejected_before_any_mutation(self):
        require_no_default_job(machine_record())
        with self.assertRaisesRegex(CycleError, "existing machine default"):
            require_no_default_job(
                machine_record(
                    bid_image=config().owner_image,
                    bid_image_args=["/bin/bash"],
                    bid_gpu_cost=config().host_job_low,
                )
            )
        with tempfile.TemporaryDirectory() as tmp:
            host, client = FakeCli(), FakeCli()
            cycle = ExistingDefjobCycle(config(), host, client, Path(tmp), sleep=lambda _seconds: None)
            with self.assertRaisesRegex(CycleError, "existing machine default"):
                cycle.run()
            mutations = [
                call for call in host.run_calls
                if call[:2] in (["set", "defjob"], ["list", "machine"], ["remove", "defjob"])
            ]
            self.assertEqual(mutations, [])

    def test_authenticated_account_ids_must_be_exact_and_distinct(self):
        self.assertEqual(authenticated_account_id({"id": 123}), "123")
        with self.assertRaises(CycleError):
            authenticated_account_id({"email": "not-an-id"})
        with tempfile.TemporaryDirectory() as tmp:
            host, client = FakeCli(), FakeCli()
            host.json_handler = lambda _args, _check=True: {"id": 123}
            client.json_handler = lambda _args, _check=True: {"id": 123}
            cycle = Cycle(config(), host, client, Path(tmp))
            with self.assertRaisesRegex(CycleError, "same Vast account"):
                cycle.prove_distinct_accounts()
            self.assertEqual(host.run_calls + client.run_calls, [])
        with tempfile.TemporaryDirectory() as tmp:
            host, client = FakeCli(), FakeCli()
            host.json_handler = lambda _args, _check=True: {"id": 123}
            client.json_handler = lambda _args, _check=True: {"id": 456}
            cycle = Cycle(config(), host, client, Path(tmp))
            cycle.prove_distinct_accounts()
            self.assertEqual(cycle.account_ids, {"host": "123", "client": "456"})
            self.assertTrue((Path(tmp) / "authenticated-accounts.json").is_file())

    def test_initial_unlisted_failure_never_mutates_or_destroys(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, client = FakeCli(), FakeCli()
            cycle = InitialListingFailureCycle(config(), host, client, Path(tmp))
            cycle.destroy_authorized = True
            with self.assertRaisesRegex(CycleError, "still exposes"):
                cycle.run()
            cycle.cleanup()
            self.assertFalse(cycle.cycle_started)
            self.assertEqual(host.run_calls, [])
            self.assertEqual(client.run_calls, [])

    def test_cleanup_refuses_stale_preflight_proof_and_reproves_unlisting(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, client = FakeCli(), FakeCli()
            cycle = InitialListingFailureCycle(config(), host, client, Path(tmp))
            cycle.destroy_authorized = True
            cycle.cycle_started = True
            cycle.unlisted_proved = True
            cycle.cleanup()
            self.assertEqual(client.run_calls, [])
            self.assertIn(["unlist", "machine", "9001"], host.run_calls)
            self.assertTrue(any("unlist" in error for error in cycle.cleanup_errors))

    def test_preflight_absence_never_authorizes_destroy_after_prelist_mutation_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, client = FakeCli(), FakeCli()
            original_run = host.run

            def fail_defjob(args, **_kwargs):
                if args[:2] == ["set", "defjob"]:
                    host.run_calls.append(args)
                    raise CycleError("synthetic defjob failure")
                return original_run(args, **_kwargs)

            host.run = fail_defjob
            cycle = PrelistStageFailureCycle(
                config(), host, client, Path(tmp), sleep=lambda _seconds: None
            )
            cycle.destroy_authorized = True
            with self.assertRaisesRegex(CycleError, "defjob failure"):
                cycle.run()
            self.assertTrue(cycle.cycle_started)
            self.assertFalse(cycle.unlisted_proved)
            cycle.cleanup_offer_visible = True
            cycle.cleanup()
            self.assertEqual(client.run_calls, [])
            self.assertTrue(any("unlist" in error for error in cycle.cleanup_errors))

    def test_owner_records_are_awaited_only_after_relisting_is_proved(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, client = FakeCli(), FakeCli()
            cycle = RelistBeforeStageCycle(
                config(), host, client, Path(tmp), sleep=lambda _seconds: None
            )
            with self.assertRaisesRegex(CycleError, "ordering proof"):
                cycle.run()
            self.assertEqual(cycle.order, ["listing-proved", "owner-records-awaited"])
            mutations = [call for call in host.run_calls if call[:2] in (["set", "defjob"], ["list", "machine"])]
            self.assertEqual(mutations[0][:2], ["set", "defjob"])
            self.assertEqual(mutations[1][:2], ["list", "machine"])

    def test_low_phase_failure_happens_before_the_high_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, client = FakeCli(), FakeCli()
            cycle = LowGateCycle(config(), host, client, Path(tmp), sleep=lambda _seconds: None)
            with self.assertRaisesRegex(CycleError, "low phase failure"):
                cycle.run()
            defjob_calls = [call for call in host.run_calls if call[:2] == ["set", "defjob"]]
            self.assertEqual(len(defjob_calls), 1)
            self.assertEqual(
                defjob_calls[0][defjob_calls[0].index("--price_gpu") + 1],
                f"{cycle.cfg.host_job_low:.6f}",
            )

    def test_degraded_run_local_baseline_refuses_every_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, client = FakeCli(), FakeCli()
            cycle = DegradedBaselineCycle(
                config(original_reliability_baseline=0.99),
                host,
                client,
                Path(tmp),
                sleep=lambda _seconds: None,
            )

            with self.assertRaisesRegex(CycleError, "below immutable original baseline"):
                cycle.run()

            mutations = [
                call
                for call in host.run_calls
                if call[:2] in (["set", "defjob"], ["list", "machine"], ["remove", "defjob"])
            ]
            self.assertEqual(mutations, [])
            gate = json.loads(
                (Path(tmp) / "original-reliability-baseline-gate.json").read_text()
            )
            self.assertEqual(gate["original_reliability_baseline"], 0.99)
            self.assertEqual(gate["observed_reliability"], 0.98)
            self.assertFalse(gate["at_or_above_original"])

    def test_original_baseline_is_pinned_once_and_cannot_be_rebased_downward(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = load_or_pin_original_reliability_baseline(
                root,
                config(original_reliability_baseline=0.99),
            )
            second = load_or_pin_original_reliability_baseline(
                root,
                config(original_reliability_baseline=0.99),
            )

            self.assertEqual(first, second)
            self.assertEqual(first["original_reliability_baseline"], 0.99)
            with self.assertRaisesRegex(CycleError, "already-pinned immutable value"):
                load_or_pin_original_reliability_baseline(
                    root,
                    config(original_reliability_baseline=0.98),
                )

            stored = json.loads(
                (
                    root
                    / "original-reliability-baselines"
                    / f"machine-{config().machine_id}.json"
                ).read_text()
            )
            self.assertEqual(stored["original_reliability_baseline"], 0.99)

    def test_takeover_is_recorded_only_as_an_experimental_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            cycle = Cycle(
                config(reclaim_timeout=1),
                FakeCli(),
                FakeCli(),
                Path(tmp),
                sleep=lambda _seconds: None,
                monotonic=lambda: 0,
            )
            cycle.snapshot = lambda _phase: {
                "client_instance": client_record(),
                "host_instances": [owner_job(6001), owner_job(6002)],
            }

            cycle.wait_for_experimental_takeover()

            self.assertTrue(cycle.experimental_takeover_observed)
            evidence = json.loads(
                (Path(tmp) / "experimental-takeover-observed.json").read_text()
            )
            self.assertTrue(evidence["observed"])
            self.assertIn("experimental scheduler-transition", evidence["scope"])
            self.assertIn("does not prove", evidence["scope"])
            self.assertFalse((Path(tmp) / "reclaim-confirmed.json").exists())

    def test_delayed_wait_is_skipped_after_failed_takeover_or_known_rating_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            cycle = Cycle(config(), FakeCli(), FakeCli(), Path(tmp))
            cycle.post_cleanup = machine_summary(machine_record(), [])
            self.assertIn("not observed", delayed_rating_skip_reason(cycle))

            cycle.experimental_takeover_observed = True
            cycle.post_cleanup = machine_summary(machine_record(reliability2=0.98), [])
            self.assertIn("below", delayed_rating_skip_reason(cycle))

            cycle.post_cleanup = machine_summary(machine_record(reliability2=0.995), [])
            self.assertIsNone(delayed_rating_skip_reason(cycle))

    def test_production_readiness_is_never_established_by_one_takeover_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            cycle = Cycle(config(), FakeCli(), FakeCli(), Path(tmp))
            cycle.experimental_cycle_completed = True
            cycle.experimental_takeover_observed = True
            cycle.auto_resume = True

            readiness = build_production_readiness_result(cycle, None, rating_gate=True)

            self.assertTrue(readiness["single_cycle_technical_gates_passed"])
            self.assertFalse(readiness["established"])
            self.assertEqual(readiness["status"], "not-established-by-this-experiment")
            self.assertIn("original_reliability_baseline", readiness)
            self.assertTrue(
                any("cannot establish" in reason for reason in readiness["blocking_reasons"])
            )

    def test_failed_post_cycle_unlist_keeps_controlled_client_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, client = FakeCli(), FakeCli()
            cycle = InitialListingFailureCycle(config(), host, client, Path(tmp))
            cycle.destroy_authorized = True
            cycle.cycle_started = True
            cycle.listing_touched = True
            cycle.cleanup()
            self.assertIn(["unlist", "machine", "9001"], host.run_calls)
            self.assertEqual(client.run_calls, [])
            self.assertFalse(cycle.unlisted_proved)

    def test_failed_unlist_retains_high_owner_jobs_while_client_is_stopped(self):
        class ThirdSampleListingFailureCycle(Cycle):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.offer_queries = 0

            def query_offers(self, offer_type):
                self.offer_queries += 1
                if self.offer_queries == 5 and offer_type == "bid":
                    return [{"id": 8101, "machine_id": int(self.cfg.machine_id)}]
                return []

        with tempfile.TemporaryDirectory() as tmp:
            host, client = FakeCli(), FakeCli()
            high_owner_jobs = [
                owner_job(
                    job_id,
                    actual_status="running",
                    intended_status="running",
                    cur_state="running",
                    dph_base=config().expected_owner_high_renter_price,
                )
                for job_id in (6001, 6002)
            ]
            host.json_handler = lambda args, _check=True: (
                high_owner_jobs if args[:2] == ["show", "instances"] else []
            )
            client.json_handler = lambda args, _check=True: (
                client_record() if args[:2] == ["show", "instance"] else [client_record()]
            )
            cycle = ThirdSampleListingFailureCycle(
                config(), host, client, Path(tmp), sleep=lambda _seconds: None
            )
            cycle.destroy_authorized = True
            cycle.cycle_started = True
            cycle.defjob_touched = True
            cycle.owner_job_ids = ("6001", "6002")
            self.assertEqual(len(cycle.active_owner_jobs(high_owner_jobs)), 2)

            cycle.cleanup()

            self.assertIn(["unlist", "machine", "9001"], host.run_calls)
            self.assertNotIn(["remove", "defjob", "9001"], host.run_calls)
            self.assertEqual(client.run_calls, [])
            self.assertEqual(cycle.offer_queries, 5)
            self.assertFalse(cycle.unlisted_proved)
            self.assertTrue(
                any("capacity state remains unresolved" in error for error in cycle.cleanup_errors)
            )

    def test_failed_unlist_command_also_retains_inactive_low_owner_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, client = FakeCli(), FakeCli()
            low_owner_jobs = [
                owner_job(
                    job_id,
                    actual_status="loading",
                    intended_status="stopped",
                    cur_state="unloaded",
                    dph_base=config().expected_owner_low_renter_price,
                )
                for job_id in (6001, 6002)
            ]
            host.json_handler = lambda args, _check=True: (
                low_owner_jobs if args[:2] == ["show", "instances"] else []
            )
            client.json_handler = lambda args, _check=True: (
                client_record() if args[:2] == ["show", "instance"] else [client_record()]
            )
            original_run = host.run

            def fail_unlist(args, **kwargs):
                if args[:2] == ["unlist", "machine"]:
                    host.run_calls.append(args)
                    raise CycleError("synthetic unlist command failure")
                return original_run(args, **kwargs)

            host.run = fail_unlist
            cycle = Cycle(config(), host, client, Path(tmp))
            cycle.destroy_authorized = True
            cycle.cycle_started = True
            cycle.defjob_touched = True
            cycle.owner_job_ids = ("6001", "6002")
            self.assertTrue(cycle.owner_jobs_inactive_at_low(low_owner_jobs))

            cycle.cleanup()

            self.assertIn(["unlist", "machine", "9001"], host.run_calls)
            self.assertNotIn(["remove", "defjob", "9001"], host.run_calls)
            self.assertEqual(client.run_calls, [])
            self.assertTrue(
                any("synthetic unlist command failure" in error for error in cycle.cleanup_errors)
            )
            self.assertTrue(
                any("capacity state remains unresolved" in error for error in cycle.cleanup_errors)
            )

    def test_failed_defjob_removal_keeps_controlled_client_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            host, client = FakeCli(), FakeCli()

            def host_state(args, _check=True):
                if args[:2] == ["show", "instances"]:
                    return [owner_job(6001, actual_status="stopped", intended_status="stopped", cur_state="unloaded")]
                if args[:2] == ["show", "machine"]:
                    return [machine_record(bid_image=config().owner_image, bid_image_args=["/bin/bash"], bid_gpu_cost=1.3)]
                return []

            host.json_handler = host_state
            cycle = Cycle(config(), host, client, Path(tmp), sleep=lambda _seconds: None)
            cycle.destroy_authorized = True
            cycle.cycle_started = True
            cycle.unlisted_proved = True
            cycle.defjob_touched = True
            cycle.cleanup()
            self.assertIn(["remove", "defjob", "9001"], host.run_calls)
            self.assertEqual(client.run_calls, [])
            self.assertTrue(any("earlier cleanup" in error for error in cycle.cleanup_errors))

    def test_destroy_is_noninteractive_and_requires_success_or_two_absence_views(self):
        self.assertTrue(mutation_explicitly_succeeded('{"success": true}'))
        self.assertFalse(mutation_explicitly_succeeded("destroying"))
        self.assertTrue(single_instance_is_explicitly_absent({"instances": None}, "7001"))
        self.assertTrue(full_list_is_explicitly_absent([], "7001"))
        self.assertFalse(full_list_is_explicitly_absent([{"id": 999}, "malformed"], "7001"))
        self.assertFalse(single_instance_is_explicitly_absent({}, "7001"))
        with tempfile.TemporaryDirectory() as tmp:
            host, client = FakeCli(), FakeCli()
            client.json_handler = lambda args, _check=True: (
                client_record() if args[:2] == ["show", "instance"] else [client_record()]
            )
            cycle = Cycle(config(), host, client, Path(tmp), sleep=lambda _seconds: None)
            cycle.destroy_authorized = True
            cycle.cycle_started = True
            cycle.unlisted_proved = True
            cycle.cleanup()
            destroy = next(call for call in client.run_calls if call[:2] == ["destroy", "instance"])
            self.assertEqual(destroy, ["destroy", "instance", "7001", "--yes", "--raw"])
            self.assertTrue((Path(tmp) / "destroy-verification.json").is_file())
        with tempfile.TemporaryDirectory() as tmp:
            host, client = FakeCli(), FakeCli()
            client.run_stdout = "destroying"

            def after_destroy(args, _check=True):
                destroyed = any(call[:2] == ["destroy", "instance"] for call in client.run_calls)
                if args[:2] == ["show", "instance"]:
                    return {"instances": None} if destroyed else client_record()
                return [] if destroyed else [client_record()]

            client.json_handler = after_destroy
            cycle = Cycle(config(), host, client, Path(tmp), sleep=lambda _seconds: None)
            cycle.destroy_authorized = True
            cycle.cycle_started = True
            cycle.unlisted_proved = True
            cycle.cleanup()
            verification = json.loads((Path(tmp) / "destroy-verification.json").read_text())
            self.assertEqual(verification["method"], "absent-from-single-and-full-list")

    def test_active_owner_predicate_includes_actual_status_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            cycle = Cycle(config(), object(), object(), Path(tmp))
            active = cycle.active_owner_jobs([
                owner_job(6001, actual_status="running", intended_status="stopped", cur_state="stopped")
            ])
            self.assertEqual(len(active), 1)

    def test_owner_jobs_are_bound_to_exact_ids_image_args_and_workload_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = FakeCli()
            host.run_stdout = (
                '{"event":"nvidia_smi_ready","device_count":1}\n'
                '{"event":"cuda_ready","device_count":1}\n'
                '{"event":"matmul_ok","iteration":3,"device_count":1}\n'
            )
            cycle = Cycle(config(), host, object(), Path(tmp))
            jobs = [owner_job(6001), owner_job(6002)]
            self.assertEqual(cycle.exact_owner_jobs([jobs[0]], establish=True), [jobs[0]])
            self.assertIsNone(cycle.owner_job_ids)
            inactive_low = [
                owner_job(
                    6001,
                    actual_status="loading",
                    intended_status="stopped",
                    cur_state="unloaded",
                    dph_base=cycle.cfg.expected_owner_low_renter_price,
                ),
                owner_job(
                    6002,
                    actual_status=None,
                    intended_status="stopped",
                    cur_state="unloaded",
                    dph_base=cycle.cfg.expected_owner_low_renter_price,
                ),
            ]
            self.assertTrue(cycle.owner_jobs_inactive_at_low(inactive_low))
            self.assertFalse(
                cycle.owner_jobs_inactive_at_low(
                    [{**record, "dph_base": 123.0} for record in inactive_low]
                )
            )
            self.assertTrue(cycle.owner_jobs_running(jobs))
            self.assertEqual(cycle.owner_job_ids, ("6001", "6002"))
            self.assertEqual(cycle.exact_owner_jobs([jobs[0]], establish=True), [jobs[0]])
            self.assertFalse(cycle.owner_jobs_running([jobs[0]]))
            with self.assertRaises(CycleError):
                cycle.owner_jobs_running([jobs[0], owner_job(6002, image_uuid="wrong/image")])
            proof = parse_workload_log(
                'prefix {"event":"nvidia_smi_ready","device_count":1}\n'
                '{"event":"cuda_ready","device_count":1}\n'
                '{"event":"matmul_ok","iteration":3,"device_count":1}\n'
            )
            self.assertEqual(
                proof,
                {
                    "nvidia_smi_ready": True,
                    "cuda_ready": True,
                    "matmul_ok": True,
                    "max_iteration": 3,
                },
            )
            self.assertFalse(
                parse_workload_log('{"event":"matmul_ok","iteration":1,"device_count":2}')["matmul_ok"]
            )
            cycle.collect_owner_workload_proof()
            self.assertEqual(
                host.run_calls,
                [["logs", "6001", "--tail", "5000"], ["logs", "6002", "--tail", "5000"]],
            )
            self.assertTrue((Path(tmp) / "owner-workload-proof.json").is_file())

    def test_owner_workload_log_is_bounded_and_retains_startup_proof(self):
        fake_torch = types.ModuleType("torch")
        fake_torch.float16 = object()
        fake_torch.device = lambda value: value
        fake_torch.cuda = SimpleNamespace(
            device_count=lambda: 1,
            set_device=lambda _device: None,
            get_device_properties=lambda _device: SimpleNamespace(name="fake A100"),
            synchronize=lambda _device: None,
        )
        fake_torch.randn = lambda *_args, **_kwargs: object()

        class FakeResult:
            def __getitem__(self, _key):
                return 1.0

        fake_torch.mm = lambda _a, _b: FakeResult()
        fake_torch.isfinite = lambda _value: SimpleNamespace(item=lambda: True)

        tick = -0.01

        def fast_clock():
            nonlocal tick
            tick += 0.01
            return tick

        output = io.StringIO()
        smi = SimpleNamespace(stdout="0\n", returncode=0)
        with (
            mock.patch.dict(sys.modules, {"torch": fake_torch}),
            mock.patch("subprocess.run", return_value=smi),
            mock.patch("time.monotonic", side_effect=fast_clock),
            redirect_stdout(output),
        ):
            exec(PYTORCH_WORKLOAD, {})

        lines = output.getvalue().splitlines()
        events = [json.loads(line) for line in lines]
        heartbeats = [event for event in events if event["event"] == "matmul_ok"]
        self.assertGreater(events[-1]["iterations"], OWNER_LOG_TAIL_LINES)
        self.assertLessEqual(len(heartbeats), OWNER_WORKLOAD_MAX_HEARTBEATS)
        self.assertEqual(heartbeats[0]["iteration"], 1)
        self.assertLess(len(lines), OWNER_LOG_TAIL_LINES)
        retained = parse_workload_log("\n".join(lines[-OWNER_LOG_TAIL_LINES:]))
        self.assertTrue(retained["nvidia_smi_ready"])
        self.assertTrue(retained["cuda_ready"])
        self.assertTrue(retained["matmul_ok"])

    def test_machine_health_fields_are_mandatory_and_post_cleanup_is_in_rating_gate(self):
        summary = machine_summary(machine_record(num_reports=None, num_recent_reports=None), [])
        assessment = original_reliability_assessment(0.98, summary)
        self.assertTrue(assessment["at_or_above_original"])
        self.assertGreater(assessment["delta_from_original"], 0)
        require_original_reliability_floor(0.98, summary, "test")
        with self.assertRaisesRegex(CycleError, "immutable original"):
            require_original_reliability_floor(1.0, summary, "test")
        self.assertTrue(rating_gate_passes(0.99, summary, dict(summary), dict(summary), dict(summary)))
        improved = json.loads(json.dumps(summary))
        improved["reliability"] = 0.995
        self.assertTrue(rating_gate_passes(0.99, summary, improved, dict(summary), dict(summary)))
        changed = json.loads(json.dumps(summary))
        changed["reliability"] = 0.98
        self.assertFalse(rating_gate_passes(0.99, summary, dict(summary), changed, dict(summary)))
        self.assertFalse(rating_gate_passes(0.99, summary, dict(summary), {}, dict(summary)))
        for missing in ("error_description", "vm_error_level", "vm_error_msg"):
            record = machine_record()
            del record[missing]
            with self.subTest(missing=missing), self.assertRaises(CycleError):
                machine_summary(record, [])
        with self.assertRaises(CycleError):
            machine_summary(machine_record(), [{"problem": "missing fields"}])

    def test_null_and_empty_machine_health_messages_normalize_as_clear(self):
        null_summary = machine_summary(
            machine_record(error_description=None, vm_error_msg=None),
            [],
        )
        empty_summary = machine_summary(
            machine_record(error_description="", vm_error_msg=""),
            [],
        )

        self.assertEqual(
            null_summary["health"],
            {"error_description": "", "vm_error_level": 0.0, "vm_error_msg": ""},
        )
        self.assertEqual(null_summary["health"], empty_summary["health"])
        self.assertTrue(health_is_clear(null_summary))
        self.assertTrue(
            rating_gate_passes(0.99, null_summary, empty_summary, null_summary, empty_summary)
        )

    def test_machine_health_messages_reject_invalid_types_and_flag_nonempty_strings(self):
        for field in ("error_description", "vm_error_msg"):
            for value in (False, 0, [], {}):
                with self.subTest(field=field, invalid=value), self.assertRaisesRegex(
                    CycleError,
                    field,
                ):
                    machine_summary(machine_record(**{field: value}), [])
            for value in ("fault", " "):
                with self.subTest(field=field, nonempty=value):
                    summary = machine_summary(machine_record(**{field: value}), [])
                    self.assertEqual(summary["health"][field], value)
                    self.assertFalse(health_is_clear(summary))

    def test_authoritative_reports_parser_accepts_real_empty_shape_and_rejects_wrappers(self):
        self.assertEqual(parse_reports_output("reports: []\n"), [])
        report = {"problem": "x", "message": "y", "created_at": "2026-09-02T00:00:00Z"}
        self.assertEqual(parse_reports_output(json.dumps([report])), [report])
        for malformed in ("", "{}", '{"reports": []}', '[{"problem":"x"}]', "reports: nope"):
            with self.subTest(malformed=malformed), self.assertRaises(CycleError):
                parse_reports_output(malformed)

    def test_manual_start_requires_fsynced_failure_and_no_active_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeCli()
            cycle = ManualStartCycle(config(reclaim_timeout=0), Path(tmp), fake)
            with self.assertRaisesRegex(CycleError, "evidence is absent"):
                cycle.guarded_manual_start()
            self.assertEqual(fake.run_calls, [])
            atomic_json(Path(tmp) / "auto-resume-failure.json", {"automatic_resume_observed": False})
            cycle._host_instances = [
                owner_job(6001, actual_status="running", intended_status="stopped", cur_state="stopped")
            ]
            with self.assertRaisesRegex(CycleError, "still active"):
                cycle.guarded_manual_start()
            self.assertEqual(fake.run_calls, [])
            cycle._host_instances = [
                owner_job(
                    6001,
                    actual_status="loading",
                    intended_status="stopped",
                    cur_state="unloaded",
                    dph_base=cycle.cfg.expected_owner_low_renter_price,
                ),
                owner_job(
                    6002,
                    actual_status="loading",
                    intended_status="stopped",
                    cur_state="unloaded",
                    dph_base=cycle.cfg.expected_owner_low_renter_price,
                ),
            ]
            cycle.guarded_manual_start()
            self.assertEqual(fake.run_calls, [["start", "instance", "7001", "--raw"]])

    def test_manual_start_never_confirms_owner_client_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeCli()
            cycle = ManualStartCycle(config(reclaim_timeout=1), Path(tmp), fake)
            atomic_json(Path(tmp) / "auto-resume-failure.json", {"automatic_resume_observed": False})
            cycle.overlap_on_snapshot = True
            with self.assertRaisesRegex(CycleError, "overlap"):
                cycle.guarded_manual_start()
            self.assertEqual(fake.run_calls, [["start", "instance", "7001", "--raw"]])
            self.assertFalse((Path(tmp) / "manual-start-confirmed.json").exists())


if __name__ == "__main__":
    unittest.main()
