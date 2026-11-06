#!/usr/bin/env python3
"""Offline-only tests. These tests import no ML package and make no requests."""
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "code"

contract_spec = importlib.util.spec_from_file_location("contract", CODE / "dedicated_checker_contract_v01.py")
assert contract_spec and contract_spec.loader
contract = importlib.util.module_from_spec(contract_spec)
contract_spec.loader.exec_module(contract)

runner_spec = importlib.util.spec_from_file_location("runner", CODE / "dedicated_checker_runner_v02.py")
assert runner_spec and runner_spec.loader
runner = importlib.util.module_from_spec(runner_spec)
runner_spec.loader.exec_module(runner)


class DedicatedCheckerPackageOfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases, cls.keys, cls.dev_ids, cls.eval_ids = runner.load_case_material()

    def test_freeze_and_offline_preflight(self) -> None:
        self.assertGreater(runner.verify_freeze(), 10)
        result = runner.offline_preflight()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["execution"], "LOCKED_NOT_AUTHORISED")
        self.assertEqual((result["model_requests"], result["account_requests"], result["installations"], result["model_downloads"]), (0, 0, 0, 0))

    def test_case_counts_distributions_and_aapd_correction(self) -> None:
        self.assertEqual((len(self.dev_ids), len(self.eval_ids)), (4, 12))
        self.assertEqual(sum(len(self.cases[value]["atomic_claims"]) for value in self.dev_ids), 10)
        self.assertEqual(sum(len(self.cases[value]["atomic_claims"]) for value in self.eval_ids), 29)
        dev_labels = runner.reference_claims(self.keys, self.dev_ids)
        self.assertEqual(list(dev_labels.values()).count("SUPPORTED"), 7)
        self.assertEqual(list(dev_labels.values()).count("UNSUPPORTED"), 2)
        self.assertEqual(list(dev_labels.values()).count("INSUFFICIENT_EVIDENCE"), 1)
        aapd = self.cases["fresh02_aapd_revup_profile"]
        evidence = " ".join(row["text"] for row in aapd["verified_evidence"])
        self.assertIn("launched her into advocating for an accessible democracy", evidence)

    def test_identical_semantic_inputs_and_conservative_bounds(self) -> None:
        for case in self.cases.values():
            document = contract.evidence_document(case)
            for claim in case["atomic_claims"]:
                hhem = contract.hhem_input(case, claim)
                mini = contract.minicheck_input(case, claim)
                self.assertIn(document, hhem)
                self.assertIn(document, mini)
                self.assertIn(claim["claim"], hhem)
                self.assertIn(claim["claim"], mini)
                self.assertLessEqual(contract.conservative_token_upper_bound(hhem), 1024)
                self.assertLessEqual(contract.conservative_token_upper_bound(mini), 1024)

    def test_answer_keys_and_reviewer_qualifications_do_not_enter_inputs(self) -> None:
        for case in self.cases.values():
            for claim in case["atomic_claims"]:
                for text in (contract.hhem_input(case, claim), contract.minicheck_input(case, claim)):
                    self.assertFalse(contract.input_has_answer_leakage(text), case["case_id"])
                    for qualification in case.get("qualifications", []):
                        self.assertNotIn(qualification, text)

    def test_threshold_selection_pass_and_fail_paths(self) -> None:
        labels = runner.reference_claims(self.keys, self.dev_ids)
        good = {claim_id: (0.90 if label == "SUPPORTED" else 0.10) for claim_id, label in labels.items()}
        selected = contract.select_threshold(good, labels, [value / 100 for value in range(5, 100, 5)])
        self.assertEqual(selected["status"], "PASS")
        self.assertEqual(selected["threshold"], 0.90)
        self.assertTrue(contract.development_allows_evaluation(selected))
        reject_all = {claim_id: 0.10 for claim_id in labels}
        rejected = contract.select_threshold(reject_all, labels, [value / 100 for value in range(5, 100, 5)])
        self.assertEqual(rejected["status"], "FAIL")
        self.assertFalse(contract.development_allows_evaluation(rejected))
        unsafe = dict(good)
        unsafe[next(claim_id for claim_id, label in labels.items() if label != "SUPPORTED")] = 0.99
        self.assertEqual(contract.select_threshold(unsafe, labels, [value / 100 for value in range(5, 100, 5)])["status"], "FAIL")

    def test_budget_reservation_stops_before_evaluation_91(self) -> None:
        attempted = 0
        for _ in range(90):
            attempted = contract.reserve_logical_evaluation(attempted, 90)
        self.assertEqual(attempted, 90)
        with self.assertRaises(contract.ContractError):
            contract.reserve_logical_evaluation(attempted, 90)

    def test_whole_summary_aggregation_is_fail_closed(self) -> None:
        claim_ids = ["A", "B"]
        self.assertEqual(contract.aggregate_summary(claim_ids, {"A": "CANDIDATE_SUPPORTED", "B": "CANDIDATE_SUPPORTED"}), "CANDIDATE_SUPPORTED")
        self.assertEqual(contract.aggregate_summary(claim_ids, {"A": "CANDIDATE_SUPPORTED", "B": "WITHHOLD"}), "WITHHOLD")
        invalid = [
            ([], {}),
            (["A", "A"], {"A": "CANDIDATE_SUPPORTED"}),
            (claim_ids, {"A": "CANDIDATE_SUPPORTED"}),
            (claim_ids, {"A": "CANDIDATE_SUPPORTED", "B": "MAYBE"}),
        ]
        for expected, actual in invalid:
            with self.assertRaises(contract.ContractError):
                contract.aggregate_summary(expected, actual)

    def test_result_validation_rejects_missing_malformed_duplicate_and_chunked(self) -> None:
        case = self.cases[self.dev_ids[0]]
        subset = {case["case_id"]: case}
        rows = []
        for claim in case["atomic_claims"]:
            text = contract.hhem_input(case, claim)
            rows.append({
                "candidate": "hhem_2_1_open",
                "case_id": case["case_id"],
                "claim_id": claim["claim_id"],
                "score": 0.8,
                "threshold": 0.5,
                "truncated": False,
                "passage_computations": 1,
                "formatted_input_sha256": contract.sha256_text(text),
            })
        contract.validate_result_rows(subset, rows, "hhem_2_1_open")
        variants = []
        variants.append(rows[:-1])
        variants.append(rows + [copy.deepcopy(rows[0])])
        value = copy.deepcopy(rows); value[0]["score"] = float("nan"); variants.append(value)
        value = copy.deepcopy(rows); value[0]["truncated"] = True; variants.append(value)
        value = copy.deepcopy(rows); value[0]["passage_computations"] = 2; variants.append(value)
        for candidate in variants:
            with self.assertRaises(contract.ContractError):
                contract.validate_result_rows(subset, candidate, "hhem_2_1_open")

    def test_budget_zero_retry_and_candidate_gate_accounting(self) -> None:
        limits = runner.load_json(ROOT / "fixtures/resource_limits_frozen_v01.json")
        logical = limits["logical_evaluations"]
        self.assertEqual(logical, {
            "development": 20,
            "reserved_evaluation_maximum": 58,
            "repeatability_maximum": 12,
            "total_maximum": 90,
            "probes": 0,
            "warmups": 0,
            "retries": 0,
        })
        self.assertEqual(20 + 58 + 12, 90)
        self.assertEqual(limits["passage_forward_computations"]["maximum"], 90)
        self.assertEqual(limits["maximum_expenditure_gbp"], 0)

    def test_execution_is_locked_and_one_use_checks_are_present(self) -> None:
        self.assertFalse(runner.AUTHORITY.exists())
        with self.assertRaises(runner.SafetyStop):
            runner.require_live_authority()
        lock_code = (CODE / "lock_execution_v02.py").read_text(encoding="utf-8")
        self.assertIn('GITHUB_RUN_NUMBER") != "1"', lock_code)
        self.assertIn('GITHUB_RUN_ATTEMPT") != "1"', lock_code)
        self.assertIn('GITHUB_EVENT_NAME") != "workflow_dispatch"', lock_code)
        self.assertIn("Dedicated checker comparison V02 (manual, one use)", lock_code)
        self.assertIn("repeat execution refused", lock_code)

    def test_workflow_draft_is_manual_read_only_and_has_no_retry(self) -> None:
        text = (ROOT / "workflow_draft/dedicated_checker_comparison_manual_v02.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("schedule:", text)
        self.assertNotIn("pull_request:", text)
        self.assertNotIn("push:", text)
        self.assertIn("contents: read", text)
        self.assertIn("timeout-minutes: 45", text)
        self.assertIn("lock_execution_v02.py", text)
        self.assertIn("dedicated_checker_runner_v02.py --execute", text)
        self.assertNotIn("${{ runner.temp }}", text)
        self.assertIn("${RUNNER_TEMP}", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
