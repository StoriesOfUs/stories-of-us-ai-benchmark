#!/usr/bin/env python3
"""Model-free regression tests for the frozen independent verifier."""
from __future__ import annotations

import importlib.util
import json
import pathlib


HERE = pathlib.Path(__file__).resolve().parent
RUNNER = HERE / "run_independent_verifier.py"
CASES = HERE / "evaluation_cases_v01.json"
if not CASES.is_file():
    CASES = HERE.parent / "fixtures/evaluation_cases_v01.json"


spec = importlib.util.spec_from_file_location("independent_verifier", RUNNER)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
data = json.loads(CASES.read_text(encoding="utf-8"))
articles = module.article_map(data)


development_rows = [
    {
        "reference_safety_verdict": "SUPPORTED",
        "reference_nli_label": "entailment",
        "raw_nli_label": "entailment",
        "probabilities": {"contradiction": 0.02, "entailment": 0.93, "neutral": 0.05},
    },
    {
        "reference_safety_verdict": "NOT_ESTABLISHED",
        "reference_nli_label": "neutral",
        "raw_nli_label": "neutral",
        "probabilities": {"contradiction": 0.03, "entailment": 0.22, "neutral": 0.75},
    },
    {
        "reference_safety_verdict": "CONTRADICTED",
        "reference_nli_label": "contradiction",
        "raw_nli_label": "contradiction",
        "probabilities": {"contradiction": 0.90, "entailment": 0.04, "neutral": 0.06},
    },
]
selected, grid = module.calibrate(development_rows)

known_rows = []
for claim in [row for row in data["claims"] if row["group"] == "known_historical_failures"]:
    known_rows.append({
        "claim_id": claim["claim_id"],
        "decision": "NOT_ESTABLISHED",
    })
known_detection = module.known_case_detection(known_rows, data)

first_claim = data["claims"][0]
premise, selected_evidence = module.compose_premise(first_claim, articles)
holdout = [row for row in data["claims"] if row["group"] == "frozen_unseen_holdout"]

checks = {
    "label_order": module.EXPECTED_LABEL_ORDER == ["contradiction", "entailment", "neutral"],
    "neutral_is_not_supported": module.safety_decision({"contradiction": 0.01, "entailment": 0.09, "neutral": 0.90}, 0.5, 0.0) == "NOT_ESTABLISHED",
    "contradiction_is_flagged": module.safety_decision({"contradiction": 0.90, "entailment": 0.05, "neutral": 0.05}, 0.5, 0.0) == "CONTRADICTED",
    "strong_entailment_supported": module.safety_decision({"contradiction": 0.01, "entailment": 0.96, "neutral": 0.03}, 0.9, 0.1) == "SUPPORTED",
    "weak_entailment_reviewed": module.safety_decision({"contradiction": 0.20, "entailment": 0.45, "neutral": 0.35}, 0.8, 0.1) == "REQUIRES_EDITORIAL_REVIEW",
    "calibration_grid_complete": len(grid) == len(module.ENTAILMENT_THRESHOLDS) * len(module.ENTAILMENT_MARGINS),
    "calibration_zero_false_pass": selected["false_passes"] == 0,
    "calibration_accepts_supported": selected["false_rejections"] == 0,
    "premise_uses_selected_evidence": all(row["text"] in premise for row in selected_evidence),
    "claim_not_mixed_into_premise": first_claim["claim"] not in premise,
    "five_historical_cases_flagged": known_detection["all_five_flagged"] is True,
    "holdout_at_least_twelve": len(holdout) >= 12,
    "holdout_balanced": all(sum(row["reference_nli_label"] == label for row in holdout) >= 4 for label in module.EXPECTED_LABEL_ORDER),
    "holdout_multiple_categories": len({articles[row["article_id"]]["category"] for row in holdout}) >= 3,
    "manual_claim_inventory_disclosed": data["freeze_rules"]["manual_atomic_claim_inventory"] is True,
    "automatic_extraction_not_claimed": data["freeze_rules"]["automatic_claim_extraction_status"] == "NOT_IMPLEMENTED",
    "no_holdout_calibration": data["freeze_rules"]["holdout_not_used_for_calibration"] is True,
    "public_safe_label": "NOT FOR PUBLICATION" in data["public_label"],
}
failed = [name for name, passed in checks.items() if not passed]
result = {"status": "PASS" if not failed else "FAIL", "checks_total": len(checks), "checks": checks, "failed": failed}
print(json.dumps(result, indent=2))
raise SystemExit(0 if not failed else 1)
