#!/usr/bin/env python3
"""Private freeze/review gates for the V08 staged comparison."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCIENTIFIC_FREEZE = "7352086798e065f8ed662b9c42c89c0e9ca59a201104895432f07a334e8d107a"
ORDINARY_IDS = (
    "V02_ACTIVISM_PERU", "V04_ARTS_MCLEAN", "V05_ACCESS_RAIL",
    "V06_ACCESS_CROATIA", "V07_TECH_WORK", "V08_TECH_ROMANIA",
    "V09_HISTORY_AUSTRALIA", "V10_HISTORY_T4", "V11_GENERAL_BRAZIL",
    "V12_GENERAL_ROMANIA",
)
ERROR_TYPES = {"scope_broadening", "status_change", "attribution_change", "numeric_alteration", "removed_qualification"}


class ReviewStop(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _parsed(private_root: Path, slot_id: str) -> dict[str, Any]:
    path = private_root / "live_v08/results/parsed" / f"{slot_id}.json"
    if not path.is_file():
        raise ReviewStop(f"Saved V08 result is absent: {slot_id}")
    value = load_json(path)
    if not isinstance(value, dict):
        raise ReviewStop(f"Saved V08 result is invalid: {slot_id}")
    return value


def challenge_contract_gate(private_root: Path) -> dict[str, Any]:
    cases = ("V06R01", "V06R02", "V06R03", "V06R04")
    results = []
    for case_id in cases:
        for arm in ("A", "B"):
            saved = _parsed(private_root, f"CHALLENGE__{case_id}__{arm}")
            valid = saved.get("validation", {}).get("valid") is True
            results.append({"case_id": case_id, "arm": arm, "contract_valid": valid})
    return {
        "gate_passed": len(results) == 8 and all(row["contract_valid"] for row in results),
        "responses": results,
    }


def load_reference_freeze(private_root: Path) -> dict[str, Any]:
    path = private_root / "live_v08/reviews/reference_freeze_v01.json"
    if not path.is_file():
        raise ReviewStop("Frozen draft/reference/variant record is absent")
    value = load_json(path)
    exact = {
        "schema_version": "stories-of-us-v08-reference-freeze-v01",
        "status": "COMPLETE_FROZEN",
        "scientific_freeze_sha256": SCIENTIFIC_FREEZE,
        "checker_results_visible_to_reviewer": False,
        "answer_keys_excluded_from_model_inputs": True,
    }
    for key, expected in exact.items():
        if value.get(key) != expected:
            raise ReviewStop(f"Reference freeze mismatch: {key}")
    if value.get("reviewer_status") not in {"HUMAN_VERIFIED", "CODEX_ASSISTED"}:
        raise ReviewStop("Reference reviewer status is invalid")
    rows = value.get("ordinary_cases")
    if not isinstance(rows, list) or [row.get("case_id") for row in rows if isinstance(row, dict)] != list(ORDINARY_IDS):
        raise ReviewStop("Reference freeze lacks the exact ordered ordinary cohort")
    for row in rows:
        saved = _parsed(private_root, f"WRITER__{row['case_id']}")
        summary = saved.get("unedited_completion")
        if not isinstance(summary, str) or row.get("draft_sha256") != text_hash(summary):
            raise ReviewStop(f"Writer draft identity mismatch: {row['case_id']}")
        if row.get("reference_label") not in {"ACCEPTABLE", "CORRECTABLE", "HOLD", "DISPUTED"}:
            raise ReviewStop(f"Invalid reference label: {row['case_id']}")
        if row.get("expected_system_decision") not in {"ACCEPT", "REVISE", "HOLD", "DISPUTED"}:
            raise ReviewStop(f"Invalid expected decision: {row['case_id']}")
        if not isinstance(row.get("revision_eligible"), bool) or not isinstance(row.get("defects"), list):
            raise ReviewStop(f"Incomplete reference record: {row['case_id']}")
        if row["revision_eligible"] != (row["reference_label"] == "CORRECTABLE"):
            raise ReviewStop(f"Revision eligibility contradicts reference label: {row['case_id']}")
    variants = value.get("introduced_error_variants")
    if not isinstance(variants, list) or len(variants) != 5:
        raise ReviewStop("Reference freeze must contain exactly five introduced-error variants")
    if {row.get("defect_type") for row in variants if isinstance(row, dict)} != ERROR_TYPES:
        raise ReviewStop("Introduced-error types do not match the frozen five-type plan")
    variant_ids: set[str] = set()
    for row in variants:
        variant_id = row.get("variant_id")
        summary = row.get("candidate_summary")
        if not isinstance(variant_id, str) or variant_id in variant_ids:
            raise ReviewStop("Introduced-error variant IDs are invalid or duplicated")
        variant_ids.add(variant_id)
        if row.get("base_case_id") not in ORDINARY_IDS or not isinstance(summary, str) or not summary.strip():
            raise ReviewStop(f"Introduced-error variant is incomplete: {variant_id}")
        if row.get("summary_sha256") != text_hash(summary) or row.get("verified_single_defect") is not True:
            raise ReviewStop(f"Introduced-error identity or isolation is invalid: {variant_id}")
        if row.get("expected_system_decision") not in {"REVISE", "HOLD"}:
            raise ReviewStop(f"Introduced-error expected decision is invalid: {variant_id}")
    return value


def eligible_revisions(private_root: Path) -> list[str]:
    reference = load_reference_freeze(private_root)
    eligible: list[str] = []
    for row in reference["ordinary_cases"]:
        case_id = row["case_id"]
        if not row["revision_eligible"]:
            continue
        path = private_root / "live_v08/results/parsed" / f"ORDINARY__{case_id}__B.json"
        if not path.is_file():
            continue
        saved = load_json(path)
        if not isinstance(saved, dict):
            continue
        if saved.get("validation", {}).get("valid") is not True:
            continue
        if saved.get("authoritative_decision") == "REVISE":
            eligible.append(case_id)
    return eligible


def load_revision_reference_freeze(private_root: Path, expected_case_ids: list[str]) -> dict[str, Any]:
    path = private_root / "live_v08/reviews/revision_reference_freeze_v01.json"
    if not path.is_file():
        raise ReviewStop("Frozen revised-summary reference record is absent")
    value = load_json(path)
    exact = {
        "schema_version": "stories-of-us-v08-revision-reference-freeze-v01",
        "status": "COMPLETE_FROZEN",
        "scientific_freeze_sha256": SCIENTIFIC_FREEZE,
        "checker_results_visible_to_reviewer": False,
        "answer_keys_excluded_from_model_inputs": True,
    }
    for key, expected in exact.items():
        if value.get(key) != expected:
            raise ReviewStop(f"Revision reference freeze mismatch: {key}")
    if value.get("reviewer_status") not in {"HUMAN_VERIFIED", "CODEX_ASSISTED"}:
        raise ReviewStop("Revision reference reviewer status is invalid")
    rows = value.get("revised_cases")
    if not isinstance(rows, list) or [row.get("case_id") for row in rows if isinstance(row, dict)] != expected_case_ids:
        raise ReviewStop("Revision reference freeze does not match realised revisions")
    for row in rows:
        case_id = row["case_id"]
        saved = _parsed(private_root, f"REV__{case_id}")
        summary = saved.get("unedited_completion")
        if not isinstance(summary, str) or row.get("revised_summary_sha256") != text_hash(summary):
            raise ReviewStop(f"Revised summary identity mismatch: {case_id}")
        if row.get("reference_label") not in {"ACCEPTABLE", "HOLD", "DISPUTED"}:
            raise ReviewStop(f"Invalid revised-summary reference label: {case_id}")
        if not isinstance(row.get("defects"), list):
            raise ReviewStop(f"Revised-summary defects are absent: {case_id}")
    return value
