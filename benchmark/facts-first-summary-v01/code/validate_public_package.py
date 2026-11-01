#!/usr/bin/env python3
"""Validate the frozen public-safe facts-first benchmark package."""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name: str) -> dict:
    return json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8"))


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    cases = load("cases_frozen_v01.json")
    refs = load("reference_facts_frozen_v01.json")
    config = load("experiment_config_v01.json")
    errors: list[str] = []
    if len(cases.get("cases", [])) != config["evaluation"]["expected_case_count"]:
        errors.append("Frozen case count mismatch")
    ids = [case["case_id"] for case in cases["cases"]]
    if len(ids) != len(set(ids)):
        errors.append("Duplicate case IDs")
    if set(ids) != {row["case_id"] for row in refs["cases"]}:
        errors.append("Reference and case membership differ")
    if len({case["category"] for case in cases["cases"]}) < config["evaluation"]["minimum_specialist_categories"]:
        errors.append("Insufficient specialist Category coverage")
    if sum(len(case["negative_probes"]) for case in cases["cases"]) != config["evaluation"]["negative_probe_count"]:
        errors.append("Negative probe count mismatch")
    for case in cases["cases"]:
        if not case["source_url"].startswith("https://"):
            errors.append(f"{case['case_id']}: non-HTTPS source URL")
        evidence_ids = [row["evidence_id"] for row in case["evidence"]]
        if len(evidence_ids) != len(set(evidence_ids)):
            errors.append(f"{case['case_id']}: duplicate evidence IDs")
        for row in case["evidence"]:
            if len(row["text"].split()) > 70:
                errors.append(f"{case['case_id']}: evidence paraphrase is unexpectedly long")
    forbidden = [r"BEGIN (?:RSA|OPENSSH|EC) PRIVATE KEY", r"github_pat_", r"ghp_[A-Za-z0-9]+",
                 r"NETLIFY_AUTH_TOKEN", r"OPENAI_API_KEY"]
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix.lower() not in {".pyc", ".gguf", ".safetensors"}:
            if path.resolve() == pathlib.Path(__file__).resolve():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in forbidden:
                if re.search(pattern, text):
                    errors.append(f"Potential secret marker in {path.relative_to(ROOT)}")
    manifest_path = ROOT / "fixtures" / "freeze_manifest_v01.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for relative, expected in manifest["files"].items():
            path = ROOT / relative
            if not path.is_file() or sha256(path) != expected:
                errors.append(f"Freeze hash mismatch: {relative}")
    print(json.dumps({"status": "PASS" if not errors else "FAIL", "errors": errors,
                      "case_count": len(cases["cases"]), "category_count": len({case['category'] for case in cases['cases']}),
                      "negative_probe_count": sum(len(case["negative_probes"]) for case in cases["cases"])}, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
