#!/usr/bin/env python3
"""Validate the frozen public-safe unseen-evaluation package."""
from __future__ import annotations

import hashlib
import json
import pathlib


BASE = pathlib.Path(__file__).resolve().parents[1]
PACKETS = BASE / "fixtures/article_packets_frozen_v01.json"
MODEL = BASE / "fixtures/phi_model_manifest_v01.json"
PREVIOUS_USE = BASE / "fixtures/previous_use_check_v01.json"
SELECTION = BASE / "fixtures/article_selection_and_source_verification_v01.json"
CRITERIA = BASE / "fixtures/evaluation_criteria_v01.json"
FREEZE = BASE / "fixtures/experiment_freeze_manifest_v01.json"


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    packets = json.loads(PACKETS.read_text(encoding="utf-8"))
    model = json.loads(MODEL.read_text(encoding="utf-8"))
    previous = json.loads(PREVIOUS_USE.read_text(encoding="utf-8"))
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    criteria = json.loads(CRITERIA.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    errors: list[str] = []
    expected_instruction = (
        "Using only the verified information below, write two short, natural sentences (maximum 50 words).\n"
        "Begin with the exact publisher name, explain the main development and its disability connection, then add one important detail. Preserve what actually happened versus what is only planned or intended. Invent nothing."
    )
    expected_cases = [
        "access_dns_conference_lift",
        "tech_abc_smart_glasses",
        "activism_aci_rights_rally",
        "arts_pg_textures_of_being",
        "history_ha_disability_history_month",
    ]
    expected_categories = ["Access", "Tech", "Activism", "Arts", "History"]
    if packets.get("writing_instruction") != expected_instruction:
        errors.append("Writing instruction differs from the frozen preceding Phi experiment")
    cases = packets.get("cases", [])
    if [row.get("case_id") for row in cases] != expected_cases:
        errors.append("Exactly the five authorised unseen cases are required in frozen order")
    if [row.get("category") for row in cases] != expected_categories:
        errors.append("Exactly one case from each requested specialist Category is required")
    if len({row.get("source_url") for row in cases}) != 5 or len({row.get("source_name") for row in cases}) != 5:
        errors.append("Five distinct URLs and publishers are required")
    for case in cases:
        if len(case.get("two_verified_facts", [])) != 2:
            errors.append(f"{case.get('case_id')} does not contain exactly two verified facts")
        required = ["source_name", "source_url", "publication_date", "category", "country", "region", "disability_relevance", "category_relevance"]
        if any(not case.get(field) for field in required):
            errors.append(f"{case.get('case_id')} is missing a required evidence-packet field")
        if case.get("source_provenance", {}).get("status") != "EXACT_ORIGINAL_VERIFIED":
            errors.append(f"{case.get('case_id')} lacks exact-original verification")
    phi = model.get("model", {})
    if sha256(MODEL) != "e54e8161a36579ff6d5a627079ee7567f7236c2e387d24c6bada92d070215a45":
        errors.append("Phi model manifest differs from the previous successful frozen comparison")
    if phi.get("official_upstream") != "microsoft/Phi-4-mini-instruct" or phi.get("official_licence") != "MIT":
        errors.append("Phi official identity or licence mismatch")
    if phi.get("access_status") != "PASS" or phi.get("quantisation") != "Q4_K_M":
        errors.append("Phi access or quantisation differs from the frozen baseline")
    if previous.get("status") != "PASS" or not all(row.get("unused_in_project_summary_experiments") for row in previous.get("cases", [])):
        errors.append("Previous-use exclusion did not pass for all cases")
    if previous.get("curated_records_checked") != 528 or previous.get("curated_unique_urls_checked") != 528:
        errors.append("Protected curated-corpus exclusion did not cover 528 records and URLs")
    if selection.get("selection_status") != "PASS" or selection.get("counted_attempts", 61) > selection.get("fresh_http_attempt_budget", 60):
        errors.append("Source selection or retrieval budget validation failed")
    if criteria.get("no_automatic_threshold") is None:
        errors.append("Frozen evaluation criteria are incomplete")
    files = [PACKETS, MODEL, PREVIOUS_USE, SELECTION, CRITERIA]
    actual = {str(path.relative_to(BASE)): sha256(path) for path in files}
    if actual != freeze.get("frozen_file_sha256"):
        errors.append("Frozen input hash mismatch")
    if freeze.get("generation_started") is not False:
        errors.append("Freeze manifest must precede generation")
    forbidden = ["BEGIN PRIVATE KEY", "hf_", "github_pat_", "ghp_"]
    package_text = "\n".join(path.read_text(encoding="utf-8") for path in files)
    if any(token in package_text for token in forbidden):
        errors.append("Possible credential material found")
    result = {
        "schema_version": "stories-of-us-phi4-mini-unseen-package-validation-v01",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "frozen_file_sha256": actual,
        "cases": len(cases),
        "categories": [row.get("category") for row in cases],
        "new_models": 0,
        "new_summaries_authorised": 5,
        "phi_access": phi.get("access_status"),
        "workflow_scope": "MANUAL_ONLY_NO_DEPLOYMENT",
    }
    print(json.dumps(result, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
