#!/usr/bin/env python3
"""Validate frozen public-safe inputs and access decisions before cloud execution."""
from __future__ import annotations

import hashlib
import json
import pathlib


BASE = pathlib.Path(__file__).resolve().parents[1]
PACKETS = BASE / "fixtures/article_packets_frozen_v01.json"
MODEL = BASE / "fixtures/phi_model_manifest_v01.json"
SOURCE_FREEZE = BASE / "fixtures/source_freeze_manifest_v01.json"
QWEN_RESULTS = BASE / "fixtures/archived_qwen_results_v01.json"
QWEN_REVIEW = BASE / "fixtures/archived_qwen_editorial_review_v01.json"
FREEZE = BASE / "fixtures/experiment_freeze_manifest_v01.json"


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    packets = json.loads(PACKETS.read_text(encoding="utf-8"))
    model = json.loads(MODEL.read_text(encoding="utf-8"))
    source_freeze = json.loads(SOURCE_FREEZE.read_text(encoding="utf-8"))
    qwen_results = json.loads(QWEN_RESULTS.read_text(encoding="utf-8"))
    qwen_review = json.loads(QWEN_REVIEW.read_text(encoding="utf-8"))
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
    phi = model.get("model", {})
    if phi.get("official_upstream") != "microsoft/Phi-4-mini-instruct" or phi.get("official_licence") != "MIT":
        errors.append("Phi official identity or licence mismatch")
    if phi.get("access_status") != "PASS" or phi.get("quantisation") != "Q4_K_M":
        errors.append("Phi access or selected quantisation is not approved by the frozen preflight")
    if source_freeze.get("frozen_file_sha256", {}).get("fixtures/article_packets_frozen_v01.json") != sha256(PACKETS):
        errors.append("Copied article packets do not match the prior source freeze")
    qwen_success = [row for row in qwen_results.get("results", []) if row.get("model_key") in {"A", "B"} and row.get("execution_status") == "SUCCESS"]
    if len(qwen_success) != 4 or any(not row.get("text") for row in qwen_success):
        errors.append("Exactly four preserved successful Qwen outputs are required")
    if qwen_review.get("totals", {}).get("outputs_reviewed") != 4 or qwen_review.get("totals", {}).get("REVISE") != 4:
        errors.append("Preserved Qwen editorial review does not match the historical 0 ACCEPT / 4 REVISE result")
    actual = {
        str(PACKETS.relative_to(BASE)): sha256(PACKETS),
        str(MODEL.relative_to(BASE)): sha256(MODEL),
        str(QWEN_RESULTS.relative_to(BASE)): sha256(QWEN_RESULTS),
        str(QWEN_REVIEW.relative_to(BASE)): sha256(QWEN_REVIEW),
    }
    if actual != freeze.get("frozen_file_sha256"):
        errors.append("Frozen input hash mismatch")
    forbidden = ["BEGIN PRIVATE KEY", "hf_", "github_pat_", "ghp_"]
    package_text = PACKETS.read_text(encoding="utf-8") + MODEL.read_text(encoding="utf-8")
    if any(token in package_text for token in forbidden):
        errors.append("Possible credential material found")
    result = {
        "schema_version": "stories-of-us-phi4-mini-frozen-comparison-validation-v01",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "frozen_file_sha256": actual,
        "cases": len(packets.get("cases", [])),
        "new_models": 1,
        "new_summaries_authorised": 2,
        "archived_qwen_outputs": len(qwen_success),
        "phi_access": phi["access_status"],
        "workflow_scope": "MANUAL_ONLY_NO_DEPLOYMENT",
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
