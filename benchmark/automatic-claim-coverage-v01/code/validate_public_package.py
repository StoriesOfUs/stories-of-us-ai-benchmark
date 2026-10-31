#!/usr/bin/env python3
"""Validate the frozen public package and write a machine-readable result."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = pathlib.Path(args.root).resolve()
    errors: list[str] = []
    required = [
        "code/run_automatic_claim_coverage.py", "code/evidence_preparer.py",
        "code/requirements-v01.txt", "tests/test_claim_coverage.py",
        "fixtures/public_cases_frozen_v01.json", "fixtures/freeze_manifest_v01.json",
        "fixtures/experiment_config_v01.json", "fixtures/deberta_model_manifest_v01.json",
        "README.md",
    ]
    for name in required:
        if not (root / name).is_file():
            errors.append(f"Missing required file: {name}")
    cases_path = root / "fixtures/public_cases_frozen_v01.json"
    freeze_path = root / "fixtures/freeze_manifest_v01.json"
    config_path = root / "fixtures/experiment_config_v01.json"
    if cases_path.is_file() and freeze_path.is_file():
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        if sha256(cases_path) != freeze["cases_sha256"]:
            errors.append("Frozen cases SHA-256 does not match freeze manifest")
        if len(cases.get("cases", [])) != 8:
            errors.append("Expected 8 total cases")
        if sum(row.get("evaluation_group") == "new_frozen_holdout" for row in cases.get("cases", [])) != 5:
            errors.append("Expected 5 frozen holdout cases")
        for case in cases.get("cases", []):
            if not re.match(r"^https://", case.get("url", "")):
                errors.append(f"Non-HTTPS public source URL: {case.get('case_id')}")
            for evidence in case.get("evidence", []):
                if len(evidence.get("text", "")) > 700:
                    errors.append(f"Evidence passage exceeds public-safe bound: {case.get('case_id')}")
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config["deberta"]["entailment_threshold"] != 0.5 or config["deberta"]["entailment_margin"] != 0.3:
            errors.append("DeBERTa thresholds changed")
        if config["single_controlled_rewrite_maximum"] != 1:
            errors.append("Rewrite limit is not one")
        if config["additional_cost_limit_gbp"] != 0:
            errors.append("Cost limit is not zero")
    # Assemble signatures so the validator does not flag its own source text.
    forbidden_fragments = [
        "BEGIN" + " PRIVATE KEY", "gh" + "p_", "github" + "_pat_", "NETLIFY" + "_AUTH_TOKEN"
    ]
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".py", ".json", ".md", ".txt", ".yml", ".yaml"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            for fragment in forbidden_fragments:
                if fragment in text:
                    errors.append(f"Forbidden sensitive fragment in {path.relative_to(root)}")
    payload = {
        "schema_version": "stories-of-us-automatic-claim-coverage-package-validation-v01",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "files_checked": sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()),
        "public_repository_safe_review": "PASS" if not errors else "FAIL",
        "operational_readiness": "NOT_AUTHORISED",
    }
    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "errors": len(errors)}))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
