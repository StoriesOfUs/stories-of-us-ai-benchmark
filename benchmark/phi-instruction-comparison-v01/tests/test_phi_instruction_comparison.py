from __future__ import annotations

import importlib.util
import json
import pathlib
import unittest


BASE = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("runner", BASE / "code/run_phi_instruction_comparison.py")
RUNNER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(RUNNER)


class PhiInstructionComparisonTests(unittest.TestCase):
    def test_frozen_case_counts(self) -> None:
        a = json.loads((BASE / "fixtures/set_a_article_packets_frozen_v01.json").read_text())
        b = json.loads((BASE / "fixtures/set_b_article_packets_frozen_v01.json").read_text())
        self.assertEqual(len(a["cases"]), 5)
        self.assertEqual(len(b["cases"]), 5)
        self.assertEqual([row["category"] for row in a["cases"]], ["Access", "Tech", "Activism", "Arts", "History"])
        self.assertEqual([row["category"] for row in b["cases"]], ["Access", "Tech", "Activism", "Arts", "History"])

    def test_instruction_slots(self) -> None:
        freeze = json.loads((BASE / "fixtures/experiment_freeze_manifest_v01.json").read_text())
        self.assertEqual(len(freeze["planned_output_slots"]), 15)
        self.assertEqual(len(freeze["archived_output_slots"]), 5)
        self.assertEqual(freeze["planned_new_output_count"], 15)
        self.assertEqual(freeze["planned_total_comparison_output_count"], 20)

    def test_contextual_sentence_count_protects_event_name(self) -> None:
        text = "Alliance Center for Independence reports the rally Our Pride. Our Power. Our Community. Disabled advocates sought stronger rights."
        naive, contextual, corrections = RUNNER.sentence_counts(text, "activism_aci_rights_rally")
        self.assertEqual(naive, 4)
        self.assertEqual(contextual, 2)
        self.assertTrue(corrections)

    def test_render_packet_is_condition_independent(self) -> None:
        b = json.loads((BASE / "fixtures/set_b_article_packets_frozen_v01.json").read_text())
        rendered_one = RUNNER.render_packet(b["cases"][0])
        rendered_two = RUNNER.render_packet(b["cases"][0])
        self.assertEqual(rendered_one, rendered_two)
        self.assertIn("SOURCE_NAME: Optometry Today", rendered_one)
        self.assertIn("VERIFIED FACT 1", rendered_one)
        self.assertIn("VERIFIED FACT 2", rendered_one)

    def test_archived_baseline_is_not_regenerated(self) -> None:
        provenance = json.loads((BASE / "fixtures/archived_baseline_provenance_v01.json").read_text())
        self.assertFalse(provenance["regeneration_permitted"])
        self.assertEqual(provenance["successful_output_count"], 5)


if __name__ == "__main__":
    unittest.main()
