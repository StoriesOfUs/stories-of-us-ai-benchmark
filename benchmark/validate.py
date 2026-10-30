#!/usr/bin/env python3
"""Fail closed if the public benchmark package exceeds its approved boundary."""
from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "benchmark/cases.json").read_text(encoding="utf-8"))
MODELS = json.loads((ROOT / "benchmark/model_manifest.json").read_text(encoding="utf-8"))
WORKFLOW = (ROOT / ".github/workflows/manual-ai-summary-benchmark.yml").read_text(encoding="utf-8")

checks = {
    "three_cases": len(CASES["cases"]) == 3,
    "three_categories": len({row["category"] for row in CASES["cases"]}) == 3,
    "direct_https_urls": all(row["url"].startswith("https://") and "news.google.com" not in row["url"] for row in CASES["cases"]),
    "two_models": len(MODELS["models"]) == 2,
    "manual_trigger": "workflow_dispatch:" in WORKFLOW,
    "no_automatic_triggers": all(token not in WORKFLOW for token in ("push:", "pull_request:", "schedule:", "repository_dispatch:")),
    "read_only_permissions": "permissions:\n  contents: read" in WORKFLOW,
    "no_secrets": "secrets." not in WORKFLOW and "${{ secrets" not in WORKFLOW,
    "no_deployment": all(token not in WORKFLOW.lower() for token in ("netlify", "deploy", "pages")),
    "no_curated_examples": "curated" not in (ROOT / "benchmark/cases.json").read_text(encoding="utf-8").lower(),
    "python_boolean_literal": '"curated_examples_used": False' in (ROOT / "benchmark/run_benchmark.py").read_text(encoding="utf-8"),
}

for path in ROOT.rglob("*"):
    if path.is_file() and path.suffix.lower() in {".json", ".py", ".yml", ".md"}:
        if path.resolve() == pathlib.Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8")
        checks[f"no_local_path:{path.relative_to(ROOT)}"] = "/Applications/MAMP/" not in text and "/Users/" not in text
        checks[f"no_credentials:{path.relative_to(ROOT)}"] = all(token not in text for token in ("gho_", "github_pat_", "AKIA", "BEGIN PRIVATE KEY"))

failed = [name for name, passed in checks.items() if not passed]
result = {"status": "PASS" if not failed else "FAIL", "checks_total": len(checks), "checks_passed": len(checks) - len(failed), "failed": failed}
(ROOT / "benchmark/validation_results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result))
sys.exit(0 if not failed else 1)
