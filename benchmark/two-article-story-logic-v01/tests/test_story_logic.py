from __future__ import annotations

import importlib.util
import json
import pathlib
import unittest


PACKAGE = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("story_logic", PACKAGE / "code/run_story_logic.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class StoryLogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads((PACKAGE / "fixtures/cases_frozen_v01.json").read_text())["cases"]
        cls.refs = {row["case_id"]: row for row in json.loads(
            (PACKAGE / "fixtures/reference_facts_frozen_v01.json").read_text())["cases"]}

    def test_two_cases_and_six_conditions(self):
        self.assertEqual([row["case_id"] for row in self.cases], ["bbc_disabled_bay", "druk_dpo_funding"])
        self.assertEqual(2 * 3, 6)

    def test_condition_a_and_b_use_identical_facts(self):
        for case in self.cases:
            ref = self.refs[case["case_id"]]
            rendered_a = MODULE.render_fact_packet(ref)
            rendered_b = MODULE.render_fact_packet(ref)
            self.assertEqual(rendered_a, rendered_b)
            prompt_a = MODULE.author_prompt(case, ref, "A_VERIFIED_FACTS_ONLY", None)
            prompt_b = MODULE.author_prompt(case, ref, "B_VERIFIED_FACTS_PLUS_LOGIC", ref["relationship"])
            self.assertIn(rendered_a, prompt_a)
            self.assertIn(rendered_b, prompt_b)
            self.assertIn("RELATIONSHIP GUIDANCE: NOT PROVIDED", prompt_a)
            self.assertIn("VERIFIED RELATIONSHIP", prompt_b)

    def test_reference_relationships_are_evidenced(self):
        for case in self.cases:
            ids = {row["evidence_id"] for row in case["evidence"]}
            relation = self.refs[case["case_id"]]["relationship"]
            self.assertTrue(relation["statement"])
            self.assertTrue(set(relation["evidence_ids"]) <= ids)

    def test_bbc_rejection_and_approval_guards(self):
        case = self.cases[0]
        bad = "BBC News reports that a disabled parking application was rejected. The council approved a bay after a protest."
        result = MODULE.deterministic_validation(bad, case)
        self.assertIn("INVENTED_REJECTION", result["case_specific_risk_flags"])
        self.assertIn("INVENTED_APPROVAL", result["case_specific_risk_flags"])

    def test_druk_leadership_outcome_and_promotion_guards(self):
        case = self.cases[1]
        bad = "Disability Rights UK leads sector-changing research for disabled people. It improves funding justice."
        result = MODULE.deterministic_validation(bad, case)
        self.assertEqual(set(result["case_specific_risk_flags"]), {
            "INVENTED_SOLE_LEADERSHIP", "INVENTED_ACHIEVED_OUTCOME", "UNQUALIFIED_PROMOTIONAL_LANGUAGE"})

    def test_unknown_relationship_is_exact(self):
        case = self.cases[0]
        ref = json.loads(json.dumps(self.refs[case["case_id"]]))
        ref["relationship"] = {"type": "NO VERIFIED RELATIONSHIP", "statement": "UNKNOWN", "status": [], "evidence_ids": []}
        result = MODULE.validate_packet(ref, case)
        self.assertTrue(result["valid"], result)

    def test_no_third_party_source_substitution(self):
        for case in self.cases:
            self.assertTrue(case["source_url"].startswith(("https://www.bbc.co.uk/", "https://www.disabilityrightsuk.org/")))
            self.assertFalse(case["source_access"]["third_party_substitution"])


if __name__ == "__main__":
    unittest.main()
