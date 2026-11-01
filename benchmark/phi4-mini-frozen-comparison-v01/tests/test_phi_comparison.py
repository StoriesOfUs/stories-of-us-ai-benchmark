import importlib.util
import json
import pathlib
import unittest


BASE = pathlib.Path(__file__).resolve().parents[1]
RUNNER_PATH = BASE / "code/run_phi_comparison.py"
SPEC = importlib.util.spec_from_file_location("simple_comparison", RUNNER_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class PhiFrozenComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packets = json.loads((BASE / "fixtures/article_packets_frozen_v01.json").read_text(encoding="utf-8"))
        cls.model = json.loads((BASE / "fixtures/phi_model_manifest_v01.json").read_text(encoding="utf-8"))
        cls.qwen = json.loads((BASE / "fixtures/archived_qwen_results_v01.json").read_text(encoding="utf-8"))

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

    def test_only_phi_is_new_and_public(self):
        model = self.model["model"]
        self.assertEqual(model["model_key"], "PHI")
        self.assertEqual(model["official_upstream"], "microsoft/Phi-4-mini-instruct")
        self.assertEqual(model["official_licence"], "MIT")
        self.assertEqual(model["access_status"], "PASS")

    def test_four_qwen_outputs_are_archived_not_regenerated(self):
        rows = [row for row in self.qwen["results"] if row["model_key"] in {"A", "B"}]
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["execution_status"] == "SUCCESS" and row["text"] for row in rows))

    def test_rendered_packet_hashes_match_prior_run(self):
        import hashlib
        expected = {
            "bbc_disabled_bay": "df497791ac2a8b79b33a7b0891e4ffbd2b2d6b7597358c381a2a0baeaa8bb194",
            "druk_dpo_funding": "fe67a4a172e2c1010400ddc2a283aefc03cb607c651a88db0ee05c3917772b40",
        }
        for case in self.packets["cases"]:
            digest = hashlib.sha256(MODULE.render_packet(case).encode()).hexdigest()
            self.assertEqual(digest, expected[case["case_id"]])

    def test_deterministic_structure_validator_is_not_editorial_approval(self):
        result = MODULE.validation("BBC News reports the development. It adds a detail.", "BBC News")
        self.assertTrue(result["deterministic_structure_pass"])
        self.assertEqual(result["editorial_acceptance"], "NOT_ASSESSED_BY_DETERMINISTIC_VALIDATION")


if __name__ == "__main__":
    unittest.main()
