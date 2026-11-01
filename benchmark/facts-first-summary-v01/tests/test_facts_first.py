#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
spec = importlib.util.spec_from_file_location("facts_first", ROOT / "code" / "run_facts_first.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FactsFirstTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads((ROOT / "fixtures" / "cases_frozen_v01.json").read_text())["cases"]
        cls.refs = json.loads((ROOT / "fixtures" / "reference_facts_frozen_v01.json").read_text())

    def test_selection_prompt_excludes_reference_answers(self):
        case = self.cases[0]
        prompt = module.selection_prompt(case)
        reference_statement = self.refs["cases"][0]["reference_facts"][0]["statement"]
        self.assertNotIn(reference_statement, prompt)
        self.assertIn("Select exactly TWO", prompt)

    def test_valid_selection_preserves_provenance(self):
        case = self.cases[0]
        payload = {"facts": [
            {"fact_id": "f1", "statement": case["evidence"][0]["text"], "actor": "XBOX Wire",
             "action": "reports", "object": "toggle hold", "factual_status": ["FUTURE_EXPECTED"],
             "attribution": "XBOX Wire", "time_context": "forthcoming", "evidence_ids": ["x1"],
             "supporting_excerpt": case["evidence"][0]["text"], "source_location": "Xbox Accessories"},
            {"fact_id": "f2", "statement": case["evidence"][1]["text"], "actor": "toggle hold",
             "action": "keeps", "object": "button held", "factual_status": ["FUTURE_EXPECTED", "FUNCTION_DESCRIBED"],
             "attribution": "NONE", "time_context": "when enabled", "evidence_ids": ["x2"],
             "supporting_excerpt": case["evidence"][1]["text"], "source_location": "toggle hold explanation"}
        ]}
        self.assertTrue(module.validate_selection(payload, case)["valid"])

    def test_invalid_excerpt_is_rejected(self):
        case = self.cases[0]
        payload = {"facts": [{"fact_id": f"f{i}", "statement": "statement", "actor": "actor", "action": "action",
                               "object": "object", "factual_status": ["FUTURE_EXPECTED"], "attribution": "NONE",
                               "time_context": "future", "evidence_ids": ["x1"], "supporting_excerpt": "invented",
                               "source_location": "location"} for i in (1, 2)]}
        self.assertFalse(module.validate_selection(payload, case)["valid"])

    def test_v04_structure_and_disability_guard(self):
        case = self.cases[0]
        good = ("XBOX Wire reports a forthcoming controller option presented as useful for accessibility. "
                "Toggle hold will let one button remain held after a single press.")
        self.assertTrue(module.deterministic_validation(good, case)["deterministic_structure_pass"])
        no_disability = "XBOX Wire reports a forthcoming controller option. It will hold a button after one press."
        self.assertFalse(module.deterministic_validation(no_disability, case)["deterministic_structure_pass"])

    def test_unsupported_number_guard(self):
        case = self.cases[2]
        summary = ("Australian Museum reports an Arts exhibition about disabled First Nations people. "
                   "It presents stories from 300 participants.")
        result = module.deterministic_validation(summary, case)
        self.assertEqual(result["unsupported_numeric_literals"], ["300"])
        self.assertFalse(result["deterministic_structure_pass"])

    def test_clause_guard_is_bounded_not_universal_claim_extraction(self):
        units = module.clauses("Publisher reports a plan and attributes its purpose to the organiser. It includes one feature.")
        self.assertGreaterEqual(len(units), 2)
        source = (ROOT / "code" / "run_facts_first.py").read_text()
        self.assertNotIn("automatic_complete_coverage_status", source)

    def test_negative_probes_are_frozen(self):
        self.assertEqual(sum(len(case["negative_probes"]) for case in self.cases), 6)
        self.assertTrue(all(probe["reference"] == "FLAG" for case in self.cases for probe in case["negative_probes"]))


if __name__ == "__main__":
    unittest.main()
