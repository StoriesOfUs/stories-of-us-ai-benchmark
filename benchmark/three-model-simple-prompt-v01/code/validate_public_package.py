#!/usr/bin/env python3
"""Validate frozen public-safe inputs and access decisions before cloud execution."""
from __future__ import annotations

import hashlib
import json
import pathlib


BASE = pathlib.Path(__file__).resolve().parents[1]
PACKETS = BASE / "fixtures/article_packets_frozen_v01.json"
MODELS = BASE / "fixtures/model_access_manifest_v01.json"
FREEZE = BASE / "fixtures/freeze_manifest_v01.json"


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    packets = json.loads(PACKETS.read_text(encoding="utf-8"))
    models = json.loads(MODELS.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    errors = []
    expected_instruction = (
        "Using only the verified information below, write two short, natural sentences (maximum 50 words).\n"
        "Begin with the exact publisher name, explain the main development and its disability connection, then add one important detail. Preserve what actually happened versus what is only planned or intended. Invent nothing."
    )
    if packets.get("writing_instruction") != expected_instruction:
        errors.append("Writing instruction differs from the owner-authorised text")
    if [row.get("case_id") for row in packets.get("cases", [])] != ["bbc_disabled_bay", "druk_dpo_funding"]:
        errors.append("Exactly the two authorised cases are required")
    for case in packets.get("cases", []):
        if len(case.get("two_verified_facts", [])) != 2:
            errors.append(f"{case.get('case_id')} does not contain exactly two verified facts")
        required = ["source_name", "source_url", "publication_date", "category", "disability_relevance", "category_relevance"]
        if any(not case.get(field) for field in required):
            errors.append(f"{case.get('case_id')} is missing a required evidence-packet field")
    if [row.get("model_key") for row in models.get("models", [])] != ["A", "B", "C"]:
        errors.append("Exactly model keys A, B and C are required")
    gemma = next(row for row in models["models"] if row["model_key"] == "C")
    if gemma.get("access_status") != "BLOCKED_MODEL_ACCESS_REQUIRES_SEPARATE_OWNER_AUTHORISATION":
        errors.append("Gemma must remain blocked while official access is manually gated")
    actual = {str(PACKETS.relative_to(BASE)): sha256(PACKETS), str(MODELS.relative_to(BASE)): sha256(MODELS)}
    if actual != freeze.get("frozen_file_sha256"):
        errors.append("Frozen input hash mismatch")
    forbidden = ["BEGIN PRIVATE KEY", "hf_", "github_pat_", "ghp_"]
    package_text = PACKETS.read_text(encoding="utf-8") + MODELS.read_text(encoding="utf-8")
    if any(token in package_text for token in forbidden):
        errors.append("Possible credential material found")
    result = {
        "schema_version": "stories-of-us-three-model-simple-prompt-validation-v01",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "frozen_file_sha256": actual,
        "cases": len(packets.get("cases", [])),
        "models": len(models.get("models", [])),
        "gemma_access": gemma["access_status"],
        "workflow_scope": "MANUAL_ONLY_NO_DEPLOYMENT",
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
