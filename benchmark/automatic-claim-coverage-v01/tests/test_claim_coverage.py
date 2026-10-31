#!/usr/bin/env python3
"""Component tests for automatic claim coverage and evidence safeguards."""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
SPEC = importlib.util.spec_from_file_location(
    "runner", ROOT / "code" / "run_automatic_claim_coverage.py"
)
RUNNER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(RUNNER)
CONFIG = json.loads((ROOT / "fixtures" / "experiment_config_v01.json").read_text(encoding="utf-8"))
CASES = json.loads((ROOT / "fixtures" / "public_cases_frozen_v01.json").read_text(encoding="utf-8"))


def claim(span: str, sentence: int = 1, statuses: list[str] | None = None) -> dict:
    return {
        "claim_id": "c1",
        "source_sentence": sentence,
        "exact_text_span": span,
        "atomic_claim": span.rstrip("."),
        "actor": "Disability Rights UK",
        "action_or_assertion": "reports",
        "object_or_affected_group": "Disabled People's Organisations",
        "factual_status": statuses or ["ONGOING"],
        "temporal_context": "at publication",
        "attribution": "NONE",
        "qualifications": [],
        "uncertainty": "NONE",
        "extraction_status": "EXTRACTED",
    }


class ClaimCoverageTests(unittest.TestCase):
    def test_frozen_fixture_membership(self) -> None:
        cases = CASES["cases"]
        self.assertEqual(len(cases), 8)
        self.assertEqual(sum(row["evaluation_group"] == "development_diagnostic" for row in cases), 3)
        self.assertEqual(sum(row["evaluation_group"] == "new_frozen_holdout" for row in cases), 5)
        self.assertEqual(
            {row["category"] for row in cases if row["evaluation_group"] == "new_frozen_holdout"},
            {"History", "Activism", "Arts", "Access", "Tech"},
        )
        self.assertEqual(sum(len(row["evidence"]) for row in cases), 33)

    def test_fixed_model_and_threshold_controls(self) -> None:
        self.assertEqual(CONFIG["qwen"]["revision"], "bc640142c66e1fdd12af0bd68f40445458f3869b")
        self.assertEqual(CONFIG["deberta"]["revision"], "fa2804872c3b4bd748f38c0185cc85775361e735")
        self.assertEqual(CONFIG["deberta"]["entailment_threshold"], 0.5)
        self.assertEqual(CONFIG["deberta"]["entailment_margin"], 0.3)
        self.assertFalse(CONFIG["deberta"]["threshold_recalibration"])
        self.assertEqual(CONFIG["single_controlled_rewrite_maximum"], 1)

    def test_compound_summary_can_hold_two_atomic_claims(self) -> None:
        summary = "Disability Rights UK is conducting research and offers DPOs payment."
        payload = {
            "claims": [
                claim("Disability Rights UK is conducting research"),
                {**claim("offers DPOs payment"), "claim_id": "c2"},
            ],
            "coverage": {"material_assertions_complete": True, "unresolved_segments": [], "coverage_note": "two claims"},
        }
        result = RUNNER.validate_inventory(payload, summary, CONFIG)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["claim_count"], 2)
        self.assertTrue(result["deterministic_complete"])

    def test_non_verbatim_span_is_rejected(self) -> None:
        summary = "Disability Rights UK reports research."
        payload = {
            "claims": [claim("Disability Rights UK leads research")],
            "coverage": {"material_assertions_complete": True, "unresolved_segments": [], "coverage_note": ""},
        }
        result = RUNNER.validate_inventory(payload, summary, CONFIG)
        self.assertFalse(result["valid"])
        self.assertTrue(any("exact_text_span" in error for error in result["errors"]))

    def test_invalid_factual_status_is_rejected(self) -> None:
        summary = "Disability Rights UK reports research."
        payload = {
            "claims": [claim(summary, statuses=["ACHIEVEMENT_ASSUMED"])],
            "coverage": {"material_assertions_complete": True, "unresolved_segments": [], "coverage_note": ""},
        }
        result = RUNNER.validate_inventory(payload, summary, CONFIG)
        self.assertFalse(result["valid"])
        self.assertTrue(any("factual_status" in error for error in result["errors"]))

    def test_every_sentence_requires_a_claim(self) -> None:
        summary = "Disability Rights UK reports research. DPOs receive payment."
        payload = {
            "claims": [claim("Disability Rights UK reports research.")],
            "coverage": {"material_assertions_complete": True, "unresolved_segments": [], "coverage_note": ""},
        }
        result = RUNNER.validate_inventory(payload, summary, CONFIG)
        self.assertFalse(result["valid"])
        self.assertEqual(result["missing_sentence_claims"], [2])

    def test_unresolved_segment_fails_complete_coverage(self) -> None:
        summary = "Disability Rights UK reports research."
        payload = {
            "claims": [claim(summary)],
            "coverage": {
                "material_assertions_complete": False,
                "unresolved_segments": ["research purpose"],
                "coverage_note": "ambiguous",
            },
        }
        result = RUNNER.validate_inventory(payload, summary, CONFIG)
        self.assertTrue(result["valid"], result["errors"])
        self.assertFalse(result["deterministic_complete"])

    def test_initial_evidence_is_selected_from_existing_facts(self) -> None:
        case = CASES["cases"][0]
        selection = RUNNER.select_initial_evidence(
            case, "Three partners collaborate on UK-wide DPO funding research", CONFIG
        )
        self.assertEqual(selection["status"], "SELECTED")
        self.assertIn(selection["selected_evidence_ids"][0], {row["evidence_id"] for row in case["evidence"]})

    def test_insufficient_evidence_fails_closed(self) -> None:
        case = CASES["cases"][0]
        selection = RUNNER.select_initial_evidence(case, "Volcanic activity on Mars", CONFIG)
        self.assertEqual(selection["status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(selection["selected_evidence_ids"], [])

    def test_nli_thresholds_are_conservative(self) -> None:
        self.assertEqual(
            RUNNER.nli_decision({"entailment": 0.80, "neutral": 0.10, "contradiction": 0.10}, 0.5, 0.3),
            "SUPPORTED",
        )
        self.assertNotEqual(
            RUNNER.nli_decision({"entailment": 0.51, "neutral": 0.40, "contradiction": 0.09}, 0.5, 0.3),
            "SUPPORTED",
        )

    def test_rewrite_prompt_reads_nested_verified_claim(self) -> None:
        case = CASES["cases"][0]
        findings = [{
            "extracted_claim": {"atomic_claim": "Disability Rights UK leads the research"},
            "decision": "FLAG",
            "reason": "Leadership is not established",
        }]
        prompt = RUNNER.rewrite_prompt(case, case["fixed_summary"], findings)
        self.assertIn("Disability Rights UK leads the research", prompt)
        self.assertIn("Leadership is not established", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
