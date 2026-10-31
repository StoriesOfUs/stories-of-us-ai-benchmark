#!/usr/bin/env python3
"""Fail closed when the frozen public Qwen guidance package exceeds its boundary."""
from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[2]
BENCH = ROOT / "benchmark/qwen-guidance-v01"
WORKFLOW_PATH = ROOT / ".github/workflows/manual-qwen-guidance-v01.yml"
cases_data = json.loads((BENCH / "cases.json").read_text(encoding="utf-8"))
conditions_data = json.loads((BENCH / "conditions.json").read_text(encoding="utf-8"))
examples_data = json.loads((BENCH / "style_examples.json").read_text(encoding="utf-8"))
workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
runner = (BENCH / "run_qwen_guidance.py").read_text(encoding="utf-8")
cases = cases_data["cases"]
fresh = [row for row in cases if row["evaluation_group"] == "fresh_unseen"]
diagnostic = [row for row in cases if row["evaluation_group"] == "diagnostic"]

checks = {
    "frozen_cases": cases_data["status"] == "FROZEN",
    "six_total_cases": len(cases) == 6,
    "three_diagnostic_cases": len(diagnostic) == 3,
    "three_fresh_cases": len(fresh) == 3,
    "fresh_two_specialist_categories": len({row["category"] for row in fresh}) >= 2 and "General" not in {row["category"] for row in fresh},
    "all_verified_eligible": all(row["eligibility"]["status"] == "VERIFIED_ELIGIBLE" for row in cases),
    "direct_publisher_urls": all(row["url"].startswith("https://") and "news.google.com" not in row["url"] for row in cases),
    "structured_evidence": all(row["article_facts"] and len(row["verified_facts"]) >= 3 for row in cases),
    "fact_provenance": all(all(item.get("evidence_ref") for item in row["verified_facts"]) for row in cases),
    "three_conditions": [row["condition_id"] for row in conditions_data["conditions"]] == ["A", "B", "C"],
    "condition_a_baseline": conditions_data["conditions"][0]["practical_guidance"] is False and conditions_data["conditions"][0]["illustrative_examples"] is False,
    "condition_b_guidance": conditions_data["conditions"][1]["practical_guidance"] is True and conditions_data["conditions"][1]["illustrative_examples"] is False,
    "condition_c_examples": conditions_data["conditions"][2]["practical_guidance"] is True and conditions_data["conditions"][2]["illustrative_examples"] is True,
    "two_to_four_examples": 2 <= len(examples_data["examples"]) <= 4,
    "examples_fictional_style_only": "fictional" in examples_data["notice"].lower() and "style only" in examples_data["notice"].lower(),
    "protected_examples_not_used": examples_data["protected_curated_examples_used"] is False,
    "manual_trigger_only": "workflow_dispatch:" in workflow and all(token not in workflow for token in ("push:", "pull_request:", "schedule:", "repository_dispatch:")),
    "read_only_permissions": "permissions:\n  contents: read" in workflow,
    "no_secrets": "secrets." not in workflow and "${{ secrets" not in workflow,
    "no_deployment": all(token not in workflow.lower() for token in ("netlify", "deploy", "pages")),
    "qwen_only": "Qwen3-4B-Q4_K_M.gguf" in workflow and "granite" not in workflow.lower(),
    "pinned_runtime": "792fcf4e7501972b595d3aeeb85153f9926f6aef" in workflow,
    "pinned_model": "bc640142c66e1fdd12af0bd68f40445458f3869b" in workflow,
    "verified_model_hash": "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5" in workflow,
    "bounded_job": "timeout-minutes: 45" in workflow,
    "short_artifact_retention": "retention-days: 7" in workflow,
    "single_turn_runtime": '"--single-turn"' in runner and '"--output-file"' in runner,
    "qwen_no_think": '"/no_think"' in runner,
    "all_conditions_executed": "for condition in conditions_data" in runner,
    "output_label": "NOT EDITORIALLY APPROVED" in runner and "NOT FOR PUBLICATION" in runner,
}

for path in [*BENCH.rglob("*"), WORKFLOW_PATH]:
    if path.is_file() and path.suffix.lower() in {".json", ".py", ".yml", ".md"}:
        if path.resolve() == pathlib.Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8")
        checks[f"no_local_path:{path.relative_to(ROOT)}"] = "/Applications/MAMP/" not in text and "/Users/" not in text
        checks[f"no_credentials:{path.relative_to(ROOT)}"] = all(token not in text for token in ("gho_", "github_pat_", "AKIA", "BEGIN PRIVATE KEY"))

failed = [name for name, passed in checks.items() if not passed]
result = {"status": "PASS" if not failed else "FAIL", "checks_total": len(checks), "checks_passed": len(checks) - len(failed), "failed": failed}
(BENCH / "validation_results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result))
raise SystemExit(0 if not failed else 1)
