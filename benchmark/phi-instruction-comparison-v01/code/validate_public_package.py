#!/usr/bin/env python3
"""Validate the frozen public-safe Phi instruction-comparison package."""
from __future__ import annotations

import hashlib
import json
import pathlib


BASE = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = BASE / "fixtures"


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def main() -> int:
    instructions = load("instructions_frozen_v01.json")
    set_a = load("set_a_article_packets_frozen_v01.json")
    set_b = load("set_b_article_packets_frozen_v01.json")
    archived = load("set_a_archived_old_instruction_outputs_v01.json")
    provenance = load("archived_baseline_provenance_v01.json")
    previous = load("set_b_previous_use_check_v01.json")
    selection = load("set_b_selection_and_source_verification_v01.json")
    criteria = load("evaluation_criteria_frozen_v01.json")
    model = load("phi_model_manifest_v01.json")
    freeze = load("experiment_freeze_manifest_v01.json")
    errors: list[str] = []
    expected_old = (
        "Using only the verified information below, write two short, natural sentences (maximum 50 words).\n"
        "Begin with the exact publisher name, explain the main development and its disability connection, then add one important detail. Preserve what actually happened versus what is only planned or intended. Invent nothing."
    )
    expected_revised = (
        "Using only the verified article information, write a brief, clear summary in plain British English. Begin with the exact publisher name, explain the article’s main focus or development and its connection to disabled people. Include a supporting detail where it helps explain the story.\n\n"
        "Use natural, neutral language. Preserve who is involved, the scope of any claims, and the distinction between what has happened and what is proposed or intended. Do not invent facts or implications.\n\n"
        "Aim for about 50 words; use fewer when sufficient and no more than 70. Normally use two sentences, with a third when it improves clarity. Avoid padding and preserve important qualifications when shortening."
    )
    if instructions.get("old_instruction") != expected_old:
        errors.append("OLD instruction differs from the archived frozen baseline")
    if instructions.get("revised_instruction") != expected_revised:
        errors.append("REVISED instruction differs from owner-authorised verbatim text")
    expected_a = ["access_dns_conference_lift", "tech_abc_smart_glasses", "activism_aci_rights_rally", "arts_pg_textures_of_being", "history_ha_disability_history_month"]
    expected_b = ["access_aop_nhs_app", "tech_mit_magnetic_sensors", "activism_star_kenya_charter", "arts_dtnext_tattva", "history_manchester_alf_morris"]
    expected_categories = ["Access", "Tech", "Activism", "Arts", "History"]
    cases_a = set_a.get("cases", [])
    cases_b = set_b.get("cases", [])
    if [row.get("case_id") for row in cases_a] != expected_a:
        errors.append("Set A differs from the preceding frozen five-case packet")
    if [row.get("case_id") for row in cases_b] != expected_b:
        errors.append("Set B does not contain the five frozen new cases in order")
    if [row.get("category") for row in cases_a] != expected_categories or [row.get("category") for row in cases_b] != expected_categories:
        errors.append("Each set must cover Access, Tech, Activism, Arts and History once")
    if len({row.get("source_name") for row in cases_b}) != 5 or len({row.get("source_url") for row in cases_b}) != 5:
        errors.append("Set B must use five distinct publishers and URLs")
    for case in cases_a + cases_b:
        if len(case.get("two_verified_facts", [])) != 2:
            errors.append(f"{case.get('case_id')} lacks exactly two verified facts")
        required = ["source_name", "article_title", "source_url", "publication_date", "category", "country", "region", "disability_relevance", "category_relevance"]
        if any(not case.get(field) for field in required):
            errors.append(f"{case.get('case_id')} lacks a required evidence-packet field")
        if case.get("source_provenance", {}).get("status") != "EXACT_ORIGINAL_VERIFIED":
            errors.append(f"{case.get('case_id')} lacks exact-original verification")
    results = archived.get("results", [])
    if len(results) != 5 or [row.get("case_id") for row in results] != expected_a:
        errors.append("Archived Set A baseline does not contain the five expected outputs")
    if any(row.get("execution_status") != "SUCCESS" or not row.get("text") for row in results):
        errors.append("An archived Set A output is missing or unsuccessful")
    if archived.get("semantic_instruction") != expected_old:
        errors.append("Archived Set A semantic instruction does not match OLD")
    expected_settings = {"seed": 42, "temperature": 0.2, "top_k": 20, "top_p": 0.8, "min_p": 0, "max_output_tokens": 128, "context_size": 4096}
    if archived.get("settings") != expected_settings or freeze.get("generation_settings") != expected_settings:
        errors.append("Model generation settings differ from the successful baseline")
    if provenance.get("github_run_id") != 41464206660 or provenance.get("github_commit") != "5a0ef4689cb72a05e78fa07a957bd0787de1ec3f":
        errors.append("Archived baseline provenance differs from controlling evidence")
    if provenance.get("copied_results_sha256") != sha256(FIXTURES / "set_a_archived_old_instruction_outputs_v01.json"):
        errors.append("Archived baseline hash mismatch")
    phi = model.get("model", {})
    if sha256(FIXTURES / "phi_model_manifest_v01.json") != "e54e8161a36579ff6d5a627079ee7567f7236c2e387d24c6bada92d070215a45":
        errors.append("Phi model manifest changed from the preceding successful run")
    if phi.get("official_upstream") != "microsoft/Phi-4-mini-instruct" or phi.get("quantisation") != "Q4_K_M":
        errors.append("Phi identity or quantisation mismatch")
    if previous.get("status") != "PASS" or not all(row.get("unused_in_accessible_project_summary_experiments") for row in previous.get("cases", [])):
        errors.append("Set B previous-use exclusion did not pass")
    if previous.get("curated_records_checked") != 528 or previous.get("curated_unique_urls_checked") != 528:
        errors.append("Protected corpus exclusion did not cover 528 records and URLs")
    if selection.get("selection_status") != "PASS" or selection.get("counted_attempt_units", 61) > selection.get("fresh_http_attempt_budget", 60):
        errors.append("Selection or fresh retrieval budget validation failed")
    if selection.get("history_recovery_window_used") is not False:
        errors.append("Set B must not claim an unneeded History recovery window")
    if criteria.get("headline_boundary") is None or criteria.get("no_automatic_threshold") is not True:
        errors.append("Frozen evaluation criteria are incomplete")
    for relative, expected in freeze.get("frozen_file_sha256", {}).items():
        path = BASE / relative
        if not path.is_file() or sha256(path) != expected:
            errors.append(f"Frozen input hash mismatch: {relative}")
    if freeze.get("generation_started") is not False:
        errors.append("Freeze manifest must predate generation")
    if len(freeze.get("planned_output_slots", [])) != 15 or len(freeze.get("archived_output_slots", [])) != 5:
        errors.append("Freeze manifest does not contain 15 new plus 5 archived slots")
    package_files = [path for path in FIXTURES.glob("*.json")]
    package_text = "\n".join(path.read_text(encoding="utf-8") for path in package_files)
    if any(token in package_text for token in ["BEGIN PRIVATE KEY", "github_pat_", "ghp_", "hf_"]):
        errors.append("Possible credential material found")
    payload = {
        "schema_version": "stories-of-us-phi-instruction-comparison-package-validation-v01",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "set_a_cases": len(cases_a),
        "set_b_cases": len(cases_b),
        "new_output_slots": 15,
        "archived_output_slots": 5,
        "total_comparison_outputs": 20,
        "model_manifest_sha256": sha256(FIXTURES / "phi_model_manifest_v01.json"),
        "workflow_scope": "MANUAL_ONLY_NO_DEPLOYMENT",
    }
    print(json.dumps(payload, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
