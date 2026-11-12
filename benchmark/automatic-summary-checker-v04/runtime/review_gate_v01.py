#!/usr/bin/env python3
"""Protected review-submission validation for the V04 live overlay.

The checker never receives these submissions, inventories or answer keys. The
semantic mappings remain CODEX_ASSISTED unless a human reviewer is recorded.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from checker_core_v01 import derive_authoritative_decision
from claim_coverage_scoring_v02 import score_claim_coverage


class ReviewStop(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _maps(v04_root: Path, stage: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    cases = load_json(v04_root / f"private/cases/{stage}_cases_model_facing_v01.json")["cases"]
    evidence = load_json(v04_root / f"private/evidence/{stage}_evidence_index_v01.json")["cases"]
    keys = load_json(v04_root / f"private/answer_keys/{stage}_answer_key_v01.json")["cases"]
    inventory = load_json(v04_root / f"private/claim_inventories/{stage}_material_claim_inventory_v01.json")["cases"]
    return (
        {row["case_id"]: row for row in cases},
        evidence,
        {row["case_id"]: row for row in keys},
        {row["case_id"]: row for row in inventory},
    )


def _submission(private_root: Path, name: str, expected_stage: str) -> dict[str, Any]:
    path = private_root / "live_v04/reviews" / name
    if not path.is_file():
        raise ReviewStop(f"Required protected review submission is absent: {name}")
    value = load_json(path)
    if value.get("stage") != expected_stage:
        raise ReviewStop("Protected review stage does not match")
    if value.get("reviewer_status") not in {"CODEX_ASSISTED", "HUMAN_VERIFIED"}:
        raise ReviewStop("Protected reviewer status is absent or invalid")
    if value.get("answer_key_excluded_from_model_inputs") is not True:
        raise ReviewStop("Review submission does not attest answer-key isolation")
    return value


def _parsed(private_root: Path, slot_id: str) -> dict[str, Any]:
    path = private_root / "live_v04/results/parsed" / f"{slot_id}.json"
    if not path.is_file():
        raise ReviewStop(f"Saved parsed result is absent: {slot_id}")
    return load_json(path)


def evaluate_initial_review(private_root: Path, v04_root: Path, stage: str) -> dict[str, Any]:
    if stage not in {"development", "evaluation"}:
        raise ValueError("Initial review stage must be development or evaluation")
    review_name = f"{stage}_initial_review_v01.json"
    review = _submission(private_root, review_name, f"{stage.upper()}_INITIAL")
    cases, evidence, keys, inventory = _maps(v04_root, stage)
    entries = review.get("cases")
    if not isinstance(entries, list) or {row.get("case_id") for row in entries if isinstance(row, dict)} != set(cases):
        raise ReviewStop("Protected review does not contain the exact frozen case set")

    results = []
    exact_decisions = 0
    correct_units = 0
    acceptable_controls = 0
    acceptable_controls_accepted = 0
    unsafe_false_approvals = 0
    eligible_corrections = []
    prefix = "DEV_CHECK__" if stage == "development" else "EVAL_CHECK__"
    for entry in entries:
        case_id = entry["case_id"]
        saved = _parsed(private_root, prefix + case_id)
        response = saved.get("candidate_checker_response")
        if canonical_hash(response) != entry.get("candidate_response_sha256"):
            raise ReviewStop(f"Review response identity mismatch for {case_id}")
        if entry.get("evidence_references_substantively_relevant") is not True:
            raise ReviewStop(f"Unverified substantive evidence references block {case_id}")
        if entry.get("no_answer_key_or_manual_feedback_leakage") is not True:
            raise ReviewStop(f"Leakage attestation is absent for {case_id}")

        key = keys[case_id]
        units = inventory[case_id]["reference_claim_units"]
        score = score_claim_coverage(
            units,
            key["claim_verdicts"],
            response,
            entry.get("adjudication"),
        )
        decision = derive_authoritative_decision(
            cases[case_id], evidence[case_id]["paragraphs"], response
        )
        if not decision["contract_valid"]:
            raise ReviewStop(f"Invalid checker contract blocks {case_id}")
        exact = decision["authoritative_decision"] == key["expected_decision"]
        exact_decisions += int(exact)
        correct_units += score["correctly_assessed_reference_units"]
        if key["expected_decision"] == "ACCEPT":
            acceptable_controls += 1
            acceptable_controls_accepted += int(decision["authoritative_decision"] == "ACCEPT")
        elif decision["authoritative_decision"] == "ACCEPT":
            unsafe_false_approvals += 1
        if (
            stage == "evaluation"
            and case_id in {"E02", "E06", "E12"}
            and decision["authoritative_decision"] == "REVISE"
            and score["correction_feedback_status"] == "ACCURATE_COMPLETE"
        ):
            eligible_corrections.append(case_id)
        results.append(
            {
                "case_id": case_id,
                "score": score,
                "authoritative_decision": decision["authoritative_decision"],
                "expected_decision": key["expected_decision"],
                "exact_decision": exact,
            }
        )

    all_safe_coverage = all(row["score"]["gate_progression_permitted"] for row in results)
    all_resolved = all(row["score"]["adjudication_status"] == "RESOLVED" for row in results)
    if stage == "development":
        d14 = next(row for row in results if row["case_id"] == "D14")
        gate_passed = (
            len(results) == 15
            and all_safe_coverage
            and all_resolved
            and exact_decisions == 15
            and correct_units == 45
            and unsafe_false_approvals == 0
            and acceptable_controls_accepted == acceptable_controls
            and d14["score"]["correction_feedback_status"] == "ACCURATE_COMPLETE"
            and d14["authoritative_decision"] == "REVISE"
        )
        eligible_corrections = ["D14"] if gate_passed else []
    else:
        gate_passed = (
            len(results) == 12
            and all_safe_coverage
            and all_resolved
            and correct_units >= 35
            and exact_decisions >= 11
            and unsafe_false_approvals == 0
            and acceptable_controls_accepted >= 5
        )

    return {
        "stage": stage,
        "gate_passed": gate_passed,
        "case_count": len(results),
        "exact_decisions": exact_decisions,
        "correct_reference_units": correct_units,
        "acceptable_controls": acceptable_controls,
        "acceptable_controls_accepted": acceptable_controls_accepted,
        "unsafe_false_approvals": unsafe_false_approvals,
        "eligible_corrections": eligible_corrections,
        "case_results": results,
        "reviewer_status": review["reviewer_status"],
    }


def evaluate_complete_recheck(
    private_root: Path,
    name: str,
    expected_stage: str,
    case_ids: list[str],
) -> dict[str, Any]:
    review = _submission(private_root, name, expected_stage)
    entries = review.get("cases")
    if not isinstance(entries, list) or [row.get("case_id") for row in entries] != case_ids:
        raise ReviewStop("Complete-recheck review does not contain the exact eligible cases")
    passed = 0
    for entry in entries:
        case_id = entry["case_id"]
        saved = _parsed(private_root, f"RECHECK__{case_id}")
        response = saved.get("candidate_checker_response")
        if canonical_hash(response) != entry.get("candidate_response_sha256"):
            raise ReviewStop(f"Recheck response identity mismatch for {case_id}")
        if saved.get("authoritative", {}).get("contract_valid") is not True:
            raise ReviewStop(f"Invalid recheck contract blocks {case_id}")
        checks = entry.get("whole_summary_checks")
        required = {
            "all_material_claims_identified",
            "factual_support_and_relationships_pass",
            "event_status_and_scope_pass",
            "material_qualifications_pass",
            "disability_category_and_terminology_pass",
            "all_mandatory_structure_pass",
            "no_new_mandatory_failure",
            "no_unresolved_uncertainty",
            "checker_feedback_only_revision",
        }
        if not isinstance(checks, dict) or set(checks) != required:
            raise ReviewStop(f"Complete-recheck assertions are incomplete for {case_id}")
        if entry.get("evidence_references_substantively_relevant") is not True:
            raise ReviewStop(f"Recheck evidence relevance is unverified for {case_id}")
        case_pass = (
            all(checks.values())
            and saved["authoritative"]["authoritative_decision"] == "ACCEPT"
        )
        passed += int(case_pass)
    return {
        "gate_passed": passed == len(case_ids),
        "cases_reviewed": len(case_ids),
        "cases_accepted_after_complete_recheck": passed,
        "reviewer_status": review["reviewer_status"],
    }
