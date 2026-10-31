#!/usr/bin/env python3
"""Fail closed if the public Qwen claim-verification package crosses its boundary."""
from __future__ import annotations

import json
import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[2]
BENCH = ROOT / "benchmark/qwen-claim-verification-v01"
WORKFLOW_PATH = ROOT / ".github/workflows/manual-qwen-claim-verification-v01.yml"
cases_data = json.loads((BENCH / "cases.json").read_text(encoding="utf-8"))
methods_data = json.loads((BENCH / "methods.json").read_text(encoding="utf-8"))
workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
runner = (BENCH / "run_claim_benchmark.py").read_text(encoding="utf-8")
cases = cases_data["cases"]
final = [row for row in cases if row["evaluation_group"] == "frozen_final"]
diagnostic = [row for row in cases if row["evaluation_group"] == "diagnostic"]
allowed_statuses = {"VERIFIED FACT", "VERIFIED INTENTION", "PLANNED OR PROPOSED", "ATTRIBUTED VIEW OR CONCERN", "UNSUPPORTED OR UNCERTAIN"}

checks = {
    "freeze_recorded": bool(cases_data.get("frozen_at_utc")),
    "six_total_cases": len(cases) == 6,
    "two_diagnostic_cases": len(diagnostic) == 2,
    "four_frozen_final_cases": len(final) == 4,
    "final_multiple_specialist_categories": len({row["category"] for row in final}) >= 2 and "General" not in {row["category"] for row in final},
    "final_simple_and_complex": {row["complexity"] for row in final} == {"simple", "complex"},
    "direct_publisher_urls": all(row["url"].startswith("https://") and "news.google.com" not in row["url"] for row in cases),
    "two_main_points_each": all(len(row["two_main_points"]) == 2 for row in cases),
    "at_least_three_facts_each": all(len(row["verified_facts"]) >= 3 for row in cases),
    "fact_ids_unique_per_case": all(len({fact["fact_id"] for fact in row["verified_facts"]}) == len(row["verified_facts"]) for row in cases),
    "fact_statuses_valid": all(fact["status"] in allowed_statuses for row in cases for fact in row["verified_facts"]),
    "fact_provenance": all(fact.get("evidence_ref") for row in cases for fact in row["verified_facts"]),
    "point_references_valid": all(set(point["fact_ids"]).issubset({fact["fact_id"] for fact in row["verified_facts"]}) for row in cases for point in row["two_main_points"]),
    "qualification_references_valid": all(set(row["essential_qualification_fact_ids"]).issubset({fact["fact_id"] for fact in row["verified_facts"]}) for row in cases),
    "methods_a_and_b": [row["method_id"] for row in methods_data["methods"]] == ["A", "B"],
    "method_a_baseline": methods_data["methods"][0]["two_main_points"] is False and methods_data["methods"][0]["claim_check"] is False,
    "method_b_safeguards": methods_data["methods"][1]["two_main_points"] is True and methods_data["methods"][1]["claim_check"] is True,
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
    "semantic_statuses_present": all(status in runner for status in allowed_statuses),
    "one_rewrite_path": "method_b_single_rewrite" in runner and "rewrite_performed" in runner,
    "fail_safe_hold": '"fail_safe_status": "HOLD"' in runner,
    "same_model_checker_disclosed": "same Qwen model in a separate context" in runner,
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
