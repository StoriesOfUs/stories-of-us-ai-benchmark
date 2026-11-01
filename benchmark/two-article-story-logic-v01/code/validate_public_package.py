#!/usr/bin/env python3
"""Validate the frozen public-safe story-logic package and workflow boundary."""
from __future__ import annotations

import hashlib
import json
import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "benchmark/two-article-story-logic-v01"
WORKFLOW = ROOT / ".github/workflows/manual-two-article-story-logic-v01.yml"


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    cases = json.loads((PACKAGE / "fixtures/cases_frozen_v01.json").read_text())
    refs = json.loads((PACKAGE / "fixtures/reference_facts_frozen_v01.json").read_text())
    config = json.loads((PACKAGE / "fixtures/experiment_config_v01.json").read_text())
    case_ids = [row["case_id"] for row in cases["cases"]]
    ref_ids = [row["case_id"] for row in refs["cases"]]
    assert case_ids == ["bbc_disabled_bay", "druk_dpo_funding"] == ref_ids
    assert config["evaluation"]["expected_summary_count"] == 6
    assert refs["prepared_before_qwen_generation"] is True
    for case, ref in zip(cases["cases"], refs["cases"]):
        evidence = {row["evidence_id"] for row in case["evidence"]}
        assert case["source_access"]["status"] == "EXACT_ORIGINAL_VERIFIED"
        assert case["source_access"]["third_party_substitution"] is False
        assert len(ref["facts"]) == 2
        for fact in ref["facts"]:
            assert fact["statement"] and set(fact["evidence_ids"]) <= evidence
        assert ref["relationship"]["type"] != "NO VERIFIED RELATIONSHIP"
        assert set(ref["relationship"]["evidence_ids"]) <= evidence
    text = WORKFLOW.read_text(encoding="utf-8")
    event_block = text.split("permissions:", 1)[0]
    assert re.search(r"(?m)^\s*workflow_dispatch\s*:\s*$", event_block)
    for banned in ["push:", "pull_request:", "schedule:", "repository_dispatch:", "deployment"]:
        assert banned not in event_block.lower()
    assert re.search(r"permissions:\s*\n\s+contents:\s*read", text)
    assert "secrets." not in text
    payload = {
        "schema_version": "stories-of-us-two-article-story-logic-package-validation-v01",
        "status": "PASS",
        "case_count": len(case_ids),
        "intended_summary_count": 6,
        "reference_packets_frozen": 2,
        "manual_workflow_only": True,
        "contents_permission": "read",
        "public_safe": True,
        "hashes": {str(path.relative_to(ROOT)): sha(path) for path in [
            PACKAGE / "fixtures/cases_frozen_v01.json",
            PACKAGE / "fixtures/reference_facts_frozen_v01.json",
            PACKAGE / "fixtures/experiment_config_v01.json",
            PACKAGE / "fixtures/deberta_model_manifest_v01.json",
            PACKAGE / "code/run_story_logic.py",
            WORKFLOW,
        ]},
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
