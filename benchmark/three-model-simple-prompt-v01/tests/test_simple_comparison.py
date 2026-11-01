import importlib.util
import json
import pathlib
import unittest


BASE = pathlib.Path(__file__).resolve().parents[1]
RUNNER_PATH = BASE / "code/run_simple_comparison.py"
SPEC = importlib.util.spec_from_file_location("simple_comparison", RUNNER_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class SimpleComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packets = json.loads((BASE / "fixtures/article_packets_frozen_v01.json").read_text(encoding="utf-8"))
        cls.models = json.loads((BASE / "fixtures/model_access_manifest_v01.json").read_text(encoding="utf-8"))

    def test_exact_authorised_instruction(self):
        self.assertEqual(
            self.packets["writing_instruction"],
            "Using only the verified information below, write two short, natural sentences (maximum 50 words).\n"
            "Begin with the exact publisher name, explain the main development and its disability connection, then add one important detail. Preserve what actually happened versus what is only planned or intended. Invent nothing.",
        )

    def test_exact_two_cases_and_two_facts(self):
        self.assertEqual([row["case_id"] for row in self.packets["cases"]], ["bbc_disabled_bay", "druk_dpo_funding"])
        self.assertTrue(all(len(row["two_verified_facts"]) == 2 for row in self.packets["cases"]))

    def test_identical_packet_rendering_is_deterministic(self):
        for case in self.packets["cases"]:
            self.assertEqual(MODULE.render_packet(case), MODULE.render_packet(case))
            self.assertIn(case["source_name"], MODULE.render_packet(case))

    def test_three_intended_models_and_gemma_block(self):
        self.assertEqual([row["model_key"] for row in self.models["models"]], ["A", "B", "C"])
        gemma = self.models["models"][2]
        self.assertEqual(gemma["access_status"], "BLOCKED_MODEL_ACCESS_REQUIRES_SEPARATE_OWNER_AUTHORISATION")

    def test_deterministic_structure_validator_is_not_editorial_approval(self):
        result = MODULE.validation("BBC News reports the development. It adds a detail.", "BBC News")
        self.assertTrue(result["deterministic_structure_pass"])
        self.assertEqual(result["editorial_acceptance"], "NOT_ASSESSED_BY_DETERMINISTIC_VALIDATION")


if __name__ == "__main__":
    unittest.main()
