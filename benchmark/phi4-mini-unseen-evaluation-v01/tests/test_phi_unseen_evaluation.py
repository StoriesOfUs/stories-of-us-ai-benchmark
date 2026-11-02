import hashlib
import importlib.util
import json
import pathlib
import unittest


BASE = pathlib.Path(__file__).resolve().parents[1]
RUNNER_PATH = BASE / "code/run_phi_unseen_evaluation.py"
SPEC = importlib.util.spec_from_file_location("phi_unseen", RUNNER_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class PhiUnseenEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packets = json.loads((BASE / "fixtures/article_packets_frozen_v01.json").read_text(encoding="utf-8"))
        cls.model = json.loads((BASE / "fixtures/phi_model_manifest_v01.json").read_text(encoding="utf-8"))
        cls.previous = json.loads((BASE / "fixtures/previous_use_check_v01.json").read_text(encoding="utf-8"))

    def test_exact_unchanged_instruction(self):
        self.assertEqual(
            self.packets["writing_instruction"],
            "Using only the verified information below, write two short, natural sentences (maximum 50 words).\n"
            "Begin with the exact publisher name, explain the main development and its disability connection, then add one important detail. Preserve what actually happened versus what is only planned or intended. Invent nothing.",
        )

    def test_five_categories_once_each(self):
        self.assertEqual([row["category"] for row in self.packets["cases"]], ["Access", "Tech", "Activism", "Arts", "History"])
        self.assertEqual(len({row["source_name"] for row in self.packets["cases"]}), 5)
        self.assertEqual(len({row["source_url"] for row in self.packets["cases"]}), 5)

    def test_two_verified_facts_and_original_provenance(self):
        self.assertTrue(all(len(row["two_verified_facts"]) == 2 for row in self.packets["cases"]))
        self.assertTrue(all(row["source_provenance"]["status"] == "EXACT_ORIGINAL_VERIFIED" for row in self.packets["cases"]))

    def test_previous_use_and_curated_exclusions(self):
        self.assertEqual(self.previous["status"], "PASS")
        self.assertEqual(self.previous["curated_records_checked"], 528)
        self.assertEqual(self.previous["curated_unique_urls_checked"], 528)
        self.assertTrue(all(row["unused_in_project_summary_experiments"] for row in self.previous["cases"]))

    def test_model_manifest_is_byte_identical_baseline(self):
        digest = hashlib.sha256((BASE / "fixtures/phi_model_manifest_v01.json").read_bytes()).hexdigest()
        self.assertEqual(digest, "e54e8161a36579ff6d5a627079ee7567f7236c2e387d24c6bada92d070215a45")

    def test_packet_rendering_is_deterministic(self):
        for case in self.packets["cases"]:
            self.assertEqual(MODULE.render_packet(case), MODULE.render_packet(case))
            self.assertIn(case["source_name"], MODULE.render_packet(case))

    def test_deterministic_structure_is_not_editorial_approval(self):
        result = MODULE.validation("ABC News reports the development. It adds a detail.", "ABC News")
        self.assertTrue(result["deterministic_structure_pass"])
        self.assertEqual(result["editorial_acceptance"], "NOT_ASSESSED_BY_DETERMINISTIC_VALIDATION")


if __name__ == "__main__":
    unittest.main()
