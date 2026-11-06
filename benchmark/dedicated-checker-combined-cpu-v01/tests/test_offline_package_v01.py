#!/usr/bin/env python3
"""Offline-only tests: no installations, downloads, model loads or inference."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "code"


def import_file(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


contract = import_file("contract", CODE / "dedicated_checker_contract_v01.py")
controls = import_file("controls", CODE / "storage_and_lock_controls_v01.py")
runner = import_file("runner", CODE / "combined_checker_runner_v01.py")


class CombinedPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases, cls.keys, cls.dev_ids, cls.eval_ids = runner.load_case_material()

    def test_freeze_preflight_and_lock(self) -> None:
        self.assertGreater(runner.controls.verify_freeze(), 25)
        result = runner.offline_preflight()
        self.assertEqual(result["status"], "PASS", result["issues"])
        self.assertEqual(result["execution"], "LOCKED_NOT_AUTHORISED")
        self.assertEqual(result["preparation_activity"], {"installations": 0, "model_downloads": 0, "model_loads": 0, "inference": 0, "account_requests": 0})

    def test_preserved_case_counts_and_aapd_correction(self) -> None:
        self.assertEqual((len(self.dev_ids), len(self.eval_ids)), (4, 12))
        self.assertEqual(sum(len(self.cases[value]["atomic_claims"]) for value in self.dev_ids), 10)
        self.assertEqual(sum(len(self.cases[value]["atomic_claims"]) for value in self.eval_ids), 29)
        evidence = " ".join(row["text"] for row in self.cases["fresh02_aapd_revup_profile"]["verified_evidence"])
        self.assertIn("launched her into advocating for an accessible democracy", evidence)

    def test_identical_evidence_claims_and_no_answer_leakage(self) -> None:
        for case in self.cases.values():
            document = contract.evidence_document(case)
            for claim in case["atomic_claims"]:
                for text in (contract.hhem_input(case, claim), contract.minicheck_input(case, claim)):
                    self.assertIn(document, text)
                    self.assertIn(claim["claim"], text)
                    self.assertFalse(contract.input_has_answer_leakage(text))
                    self.assertLessEqual(contract.conservative_token_upper_bound(text), 1024)

    def test_threshold_gate_and_reject_everything_failure(self) -> None:
        labels = runner.reference_claims(self.keys, self.dev_ids)
        good = {key: (0.9 if value == "SUPPORTED" else 0.1) for key, value in labels.items()}
        selected = contract.select_threshold(good, labels, [value / 100 for value in range(5, 100, 5)])
        self.assertEqual((selected["status"], selected["threshold"]), ("PASS", 0.9))
        reject_everything = {key: 0.1 for key in labels}
        self.assertEqual(contract.select_threshold(reject_everything, labels, [value / 100 for value in range(5, 100, 5)])["status"], "FAIL")

    def test_aggregation_and_invalid_results_fail_closed(self) -> None:
        self.assertEqual(contract.aggregate_summary(["a", "b"], {"a": "CANDIDATE_SUPPORTED", "b": "WITHHOLD"}), "WITHHOLD")
        for expected, actual in (([], {}), (["a", "a"], {"a": "CANDIDATE_SUPPORTED"}), (["a", "b"], {"a": "CANDIDATE_SUPPORTED"})):
            with self.assertRaises(contract.ContractError):
                contract.aggregate_summary(expected, actual)

    def test_budget_is_exactly_90_and_zero_retry(self) -> None:
        limits = json.loads((ROOT / "fixtures/resource_limits_frozen_v01.json").read_text())
        logical = limits["logical_evaluations"]
        self.assertEqual(logical["development"] + logical["reserved_evaluation_maximum"] + logical["repeatability_maximum"], 90)
        self.assertEqual(limits["model_computations"]["maximum"], 90)
        self.assertEqual((limits["maximum_retries"], limits["maximum_expenditure_gbp"]), (0, 0))

    def test_complete_cpu_wheel_lock_is_reused_exactly(self) -> None:
        rows = controls.parse_wheel_lock(ROOT / "fixtures/requirements_cpu_wheels_frozen_v01.txt")
        self.assertEqual(len(rows), 36)
        torch = next(row for row in rows if row["name"] == "torch")
        self.assertIn("download.pytorch.org/whl/cpu/torch-2.15.0%2Bcpu", torch["url"])
        self.assertEqual(torch["sha256"], "0955c7e3446326293f48af18fad67872fa31dee5a36a87690eb9e5be8b465be3")

    def test_model_allowlists_sizes_and_integrity_types(self) -> None:
        candidates = json.loads((ROOT / "fixtures/model_download_manifest_frozen_v01.json").read_text())["candidates"]
        self.assertEqual(candidates["hhem_2_1_open"]["candidate_bytes"], 441757214)
        self.assertEqual(candidates["minicheck_flan_t5_large"]["candidate_bytes"], 3136026916)
        for candidate in candidates.values():
            self.assertLess(candidate["candidate_bytes"], 4000000000)
            for repository in candidate["repositories"]:
                self.assertEqual(len(repository["revision"]), 40)
                for row in repository["files"]:
                    self.assertIn(row["hash_type"], {"sha256", "git_blob_sha1"})
                    self.assertEqual(len(row["hash"]), 64 if row["hash_type"] == "sha256" else 40)

    def test_inode_accounting_does_not_double_count_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "blob"
            original.write_bytes(b"x" * 4096)
            os.link(original, root / "hard")
            (root / "snapshot").symlink_to(original)
            measured = controls.account_paths([root])
            self.assertEqual(measured["regular_file_logical_bytes_unique"], 4096)
            self.assertEqual(measured["hardlink_repeats_not_double_counted"], 1)
            self.assertEqual(measured["symlink_count"], 1)

    def test_mock_authority_states(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            authority = root / "authority.json"
            lock = root / "lock.json"
            expected = "a" * 64
            self.assertEqual(controls.authority_state(authority, lock, expected)["state"], "LOCKED_NOT_AUTHORISED")
            document = json.loads((ROOT / "fixtures/execution_authority_GATE_TEMPLATE_v01.json").read_text())
            for key in list(document):
                if key.startswith("owner_") or key == "execution_authorised":
                    document[key] = True
            document["approved_freeze_manifest_sha256"] = expected
            authority.write_text(json.dumps(document))
            self.assertEqual(controls.authority_state(authority, lock, expected)["state"], "APPROVED")
            lock.write_text("{}")
            self.assertEqual(controls.authority_state(authority, lock, expected)["state"], "REPEAT_REFUSED")

    def test_runner_uses_sequential_candidate_subprocesses_and_gates(self) -> None:
        source = (CODE / "combined_checker_runner_v01.py").read_text()
        self.assertIn('for candidate in ("hhem_2_1_open", "minicheck_flan_t5_large")', source)
        self.assertIn("subprocess.Popen", source)
        self.assertIn("if not contract.development_allows_evaluation", source)
        self.assertIn("local_files_only=True", source)
        self.assertIn("shutil.rmtree(runtime_root / candidate", source)
        self.assertNotIn("trust_remote_code=True", source)

    def test_workflow_is_manual_read_only_bounded_and_not_authorised(self) -> None:
        text = (ROOT / "workflow_draft/dedicated_checker_combined_cpu_manual_v01.yml").read_text()
        for required in ("workflow_dispatch:", "contents: read", "timeout-minutes: 45", "--retries 0", "--require-hashes", "lock_execution_v01.py"):
            self.assertIn(required, text)
        for forbidden in ("schedule:", "pull_request:", "push:", "${{ runner.temp }}"):
            self.assertNotIn(forbidden, text)
        self.assertFalse((ROOT / "fixtures/execution_authority_APPROVED_v01.json").exists())

    def test_candidate_failure_policy_separates_candidate_and_global_stops(self) -> None:
        policy = json.loads((ROOT / "fixtures/resource_limits_frozen_v01.json").read_text())["candidate_failure_policy"]
        self.assertIn("candidate development gate failure", policy["affected_candidate_only"])
        self.assertIn("computation cap", " ".join(policy["whole_job_stop"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
