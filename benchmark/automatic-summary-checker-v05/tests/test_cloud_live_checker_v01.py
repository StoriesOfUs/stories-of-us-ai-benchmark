#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest


OVERLAY = Path(__file__).resolve().parents[1]
AUDIT = OVERLAY.parent
V05 = AUDIT / "option_c_automatic_summary_checker_test_package_v05"
sys.path[:0] = [str(OVERLAY / "code"), str(V05 / "code")]

from cloud_live_checker_v01 import LiveStop, recognised_usage, text_completion  # noqa: E402
from exact_token_count_v01 import ExactTokenCounter  # noqa: E402
from execution_control_v01 import SafetyStop, validate_credentials  # noqa: E402
from payloads_v01 import checker_payload, revision_payload  # noqa: E402
from private_git_state_v01 import (  # noqa: E402
    DurablePrivateState,
    StateStop,
    read_json,
)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class MemoryPersistence:
    def __init__(self, fail_on: int | None = None):
        self.calls = 0
        self.fail_on = fail_on

    def persist(self, paths, message):
        self.calls += 1
        if self.fail_on == self.calls:
            raise StateStop("simulated durable persistence failure")
        return f"{'a' * 60}{self.calls:04d}"


class LiveOverlayTests(unittest.TestCase):
    def test_credentials_are_locally_validated(self):
        validate_credentials("a" * 32, "synthetic-token", "synthetic-token")
        with self.assertRaises(SafetyStop):
            validate_credentials("not-an-account", "synthetic-token", "synthetic-token")
        with self.assertRaises(SafetyStop):
            validate_credentials("a" * 32, "one", "two")

    def test_persistence_failure_prevents_usable_operation_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DurablePrivateState(Path(directory), MemoryPersistence(fail_on=1))
            with self.assertRaises(StateStop):
                store.start_operation("day1-development", "run-1", "2026-11-12")
            self.assertEqual(0, len(read_json(store.ledger_path)["requests"]))

    def test_concurrent_and_repeat_operations_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DurablePrivateState(Path(directory), MemoryPersistence())
            store.start_operation("day1-development", "run-1", "2026-11-12")
            with self.assertRaises(StateStop):
                store.start_operation("day1-development", "run-2", "2026-11-12")
            store.finish_operation("day1-development", "WAITING_DEVELOPMENT_REVIEW", "2026-11-12")
            with self.assertRaises(StateStop):
                store.start_operation("day1-development", "run-3", "2026-11-12")

    def test_full_maximum_accounting_is_exactly_44_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DurablePrivateState(Path(directory), MemoryPersistence())
            store.start_operation("day0-focused-diagnostics", "run-0", "2026-11-12")
            exact = {"exact_local_input_tokens": 1, "hosted_format_equivalence": "UNVERIFIED"}
            for index in range(9):
                store.reserve_request(f"FOCUS_CHECK__{index}", "DAY_0_FOCUSED_DIAGNOSTICS", 14000, 2560, 619.997920, exact)
            store.finish_operation("day0-focused-diagnostics", "WAITING_FOCUSED_DIAGNOSTIC_REVIEW", "2026-11-12")
            store.start_operation("day1-development", "run-1", "2026-11-12")
            for index in range(15):
                store.reserve_request(f"DEV_CHECK__{index}", "DAY_1_DEVELOPMENT", 14000, 2560, 619.997920, exact)
            store.finish_operation("day1-development", "WAITING_DEVELOPMENT_REVIEW", "2026-11-12")
            store.start_operation("day2-d14-correction", "run-2", "2026-11-13")
            store.reserve_request("REV__D14", "DAY_2_D14_CORRECTION", 16000, 256, 152.437888, exact)
            store.reserve_request("RECHECK__D14", "DAY_2_D14_CORRECTION", 14000, 2560, 619.997920, exact)
            store.finish_operation("day2-d14-correction", "WAITING_D14_RECHECK_REVIEW", "2026-11-13")
            store.start_operation("day3-evaluation-initial", "run-3", "2026-11-14")
            for index in range(12):
                store.reserve_request(f"EVAL_CHECK__{index}", "DAY_3_EVALUATION", 14000, 2560, 619.997920, exact)
            store.finish_operation("day3-evaluation-initial", "WAITING_EVALUATION_REVIEW", "2026-11-14")
            store.start_operation("day3-evaluation-corrections", "run-4", "2026-11-14")
            for case_id in ("E02", "E06", "E12"):
                store.reserve_request(f"REV__{case_id}", "DAY_3_EVALUATION", 16000, 256, 152.437888, exact)
                store.reserve_request(f"RECHECK__{case_id}", "DAY_3_EVALUATION", 14000, 2560, 619.997920, exact)
            ledger = read_json(store.ledger_path)
            self.assertEqual(44, ledger["cumulative_requests"])
            self.assertEqual(624000, ledger["reserved_input_tokens"])
            self.assertEqual(103424, ledger["reserved_output_tokens"])
            self.assertAlmostEqual(25409.668352, ledger["reserved_neurons"], places=6)

    def test_second_revision_and_cap_breach_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DurablePrivateState(Path(directory), MemoryPersistence())
            store.start_operation("day2-d14-correction", "run", "2026-11-13")
            exact = {"exact_local_input_tokens": 1}
            store.reserve_request("REV__D14", "DAY_2_D14_CORRECTION", 16000, 256, 152.437888, exact)
            with self.assertRaises(StateStop):
                store.reserve_request("REV__D14", "DAY_2_D14_CORRECTION", 16000, 256, 152.437888, exact)

    def test_safety_stop_retains_lock_and_consumed_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DurablePrivateState(Path(directory), MemoryPersistence())
            store.start_operation("day1-development", "run", "2026-11-12")
            store.reserve_request("DEV_CHECK__D01", "DAY_1_DEVELOPMENT", 14000, 1536, 550.179552, {"exact": 1})
            store.mark_transmission_started("DEV_CHECK__D01")
            store.safety_stop("NETWORK_ERROR")
            state, ledger = store.load()
            self.assertEqual("SAFETY_STOP", state["status"])
            self.assertTrue(store.lock_path.exists())
            self.assertEqual("TRANSMISSION_STARTED", ledger["requests"][0]["status"])

    def test_completion_and_usage_parsing_are_strict_and_independent(self):
        body = json.dumps({"result": {"choices": [{"message": {"content": " usable "}}], "usage": {"prompt_tokens": 3, "completion_tokens": 4, "neurons": 0.5}}}).encode()
        self.assertEqual("usable", text_completion(body))
        self.assertEqual("RECOGNISED", recognised_usage(body)["status"])
        self.assertEqual(0.5, recognised_usage(body)["neurons"])
        malformed = b'{"result":{"usage":{"prompt_tokens":3,"completion_tokens":4}}}'
        self.assertEqual("RECOGNISED", recognised_usage(malformed)["status"])
        with self.assertRaises(Exception):
            text_completion(malformed)

    def test_retained_real_gemma_provider_form_uses_actual_processing_path(self):
        capture = load(OVERLAY / "tests/fixtures/retained_real_gemma_provider_capture_v01.json")
        body = capture["sanitised_bounded_body"].encode("utf-8")
        self.assertTrue(text_completion(body).startswith("European Disability Forum reports"))
        usage = recognised_usage(body)
        self.assertEqual("RECOGNISED", usage["status"])
        self.assertEqual(13.218181610107422, usage["neurons"])

    def test_real_fixed_checker_payload_counts_and_context_limits(self):
        # The package count utility uses the pinned Harmony 0.0.8 assets. The
        # cloud-only Linux wheel set is deliberately not installed on this Mac.
        counts = load(V05 / "reports/exact_tokenizer_counts_v01.json")
        summary = counts["summary"]
        self.assertEqual(36, summary["requests_counted_exactly_locally"])
        self.assertEqual(22805, summary["focused_diagnostic_input_tokens"])
        self.assertEqual(46118, summary["development_input_tokens"])
        self.assertEqual(28110, summary["evaluation_input_tokens"])
        self.assertTrue(summary["all_fixed_requests_below_14000"])

    def test_realised_revision_is_counted_without_truncation(self):
        cases = load(V05 / "private/cases/development_cases_model_facing_v01.json")["cases"]
        case = next(row for row in cases if row["case_id"] == "D14")
        evidence = load(V05 / "private/evidence/development_evidence_index_v01.json")["cases"]["D14"]["paragraphs"]
        payload = revision_payload(
            case,
            "\n\n".join(row["text"] for row in evidence),
            case["candidate_summary"],
            "Correct every cited mandatory problem using only the supplied evidence.",
            (V05 / "immutable/instructions/gemma_addendum_aligned_initial_v01.txt").read_text(encoding="utf-8"),
            (V05 / "immutable/instructions/gemma_addendum_controlled_revision_v01.txt").read_text(encoding="utf-8"),
        )
        self.assertEqual("@cf/google/gemma-4-26b-a4b-it", payload["model"])
        self.assertEqual(256, payload["max_tokens"])
        self.assertIn(evidence[-1]["text"], payload["messages"][0]["content"])
        self.assertIn("Correct every cited mandatory problem", payload["messages"][0]["content"])

    def test_no_credential_values_or_approved_live_authority_are_packaged(self):
        forbidden = ("SOU_CLOUDFLARE" + "_ACCOUNT_ID=", "Bearer " + "ey")
        for path in OVERLAY.rglob("*"):
            if path.is_file() and "wheels" not in path.parts:
                text = path.read_text(encoding="utf-8", errors="ignore")
                for marker in forbidden:
                    self.assertNotIn(marker, text, str(path))
        self.assertFalse((OVERLAY / "authority/live_execution_authority_APPROVED_v01.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
