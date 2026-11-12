#!/usr/bin/env python3
"""Protected four-disposition semantic scoring for the V04 experiment.

The checker never receives the protected reference units or this adjudication. A
condition-blinded CODEX_ASSISTED or human reviewer adjudicates frozen returned
claims after the response is saved. Ordinary code validates that adjudication and
calculates scores; it does not decide semantic equivalence or factual truth.

A returned claim can contain more than one semantic portion. Portion rows prevent
a mapped portion from concealing an invented, inventory-gap or uncertain portion.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping


class CoverageError(ValueError):
    pass


DISPOSITIONS = {"MAPPED", "INVENTED", "INVENTORY_GAP", "UNCERTAIN_MAPPING"}


def _results_by_id(response: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    claims = response.get("identified_claims")
    results = response.get("claim_results")
    if not isinstance(claims, list) or not isinstance(results, list):
        raise CoverageError("Checker response lacks identified claims or claim results")
    identified_ids = [item.get("claim_id") for item in claims if isinstance(item, dict)]
    if len(identified_ids) != len(claims) or len(identified_ids) != len(set(identified_ids)):
        raise CoverageError("Identified claim IDs are missing or duplicated")
    if any(not isinstance(value, str) or not value for value in identified_ids):
        raise CoverageError("Identified claim IDs must be non-empty strings")
    by_id = {item.get("claim_id"): item for item in results if isinstance(item, dict)}
    if set(by_id) != set(identified_ids) or len(by_id) != len(results):
        raise CoverageError("Every identified claim must have exactly one result")
    return by_id


def _validate_dispositions(
    adjudication: Mapping[str, Any],
    identified_ids: set[str],
    reference_ids: set[str],
    mapping_refs_by_claim: Mapping[str, set[str]],
) -> tuple[list[dict[str, Any]], dict[str, set[str]], dict[str, int]]:
    rows = adjudication.get("claim_dispositions")
    if not isinstance(rows, list):
        raise CoverageError("Claim dispositions must be a list")

    portions_by_claim: dict[str, set[str]] = defaultdict(set)
    mapped_refs_by_claim: dict[str, set[str]] = defaultdict(set)
    claim_ids_by_disposition: dict[str, set[str]] = {value: set() for value in DISPOSITIONS}
    counts = {value: 0 for value in DISPOSITIONS}
    normalised: list[dict[str, Any]] = []

    required = {
        "identified_claim_id",
        "portion_id",
        "disposition",
        "reference_claim_ids",
        "portion_text",
        "reason",
    }
    for row in rows:
        if not isinstance(row, dict) or set(row) != required:
            raise CoverageError("Claim-disposition row contains missing or unknown fields")
        claim_id = row["identified_claim_id"]
        portion_id = row["portion_id"]
        disposition = row["disposition"]
        refs = row["reference_claim_ids"]
        if claim_id not in identified_ids:
            raise CoverageError("Disposition refers to an unknown identified claim")
        if not isinstance(portion_id, str) or not portion_id:
            raise CoverageError("Disposition portion IDs must be non-empty strings")
        if portion_id in portions_by_claim[claim_id]:
            raise CoverageError("Disposition portion IDs must be unique within a returned claim")
        portions_by_claim[claim_id].add(portion_id)
        if disposition not in DISPOSITIONS:
            raise CoverageError("Unknown claim disposition")
        if not isinstance(refs, list) or len(refs) != len(set(refs)):
            raise CoverageError("Disposition reference IDs must be a unique list")
        if any(value not in reference_ids for value in refs):
            raise CoverageError("Disposition refers to an unknown protected reference unit")
        if not isinstance(row["portion_text"], str) or not row["portion_text"].strip():
            raise CoverageError("Disposition portion text must be recorded")
        if not isinstance(row["reason"], str) or not row["reason"].strip():
            raise CoverageError("Disposition reason must be recorded")
        if disposition == "MAPPED":
            if not refs:
                raise CoverageError("A MAPPED disposition requires at least one reference unit")
            mapped_refs_by_claim[claim_id].update(refs)
        elif refs:
            raise CoverageError("Only MAPPED dispositions may carry reference IDs")
        claim_ids_by_disposition[disposition].add(claim_id)
        counts[disposition] += 1
        normalised.append(dict(row))

    if set(portions_by_claim) != identified_ids:
        missing = sorted(identified_ids - set(portions_by_claim))
        raise CoverageError(f"Returned claims lack disposition adjudication: {missing}")

    # MAPPED portion rows and reference-unit mappings must describe the same
    # relationship in both directions. This preserves split/combined coverage and
    # prevents a mapped fragment from hiding a non-mapped portion.
    for claim_id in identified_ids:
        if mapped_refs_by_claim.get(claim_id, set()) != mapping_refs_by_claim.get(claim_id, set()):
            raise CoverageError(f"Mapped disposition and reference mapping disagree for {claim_id}")

    return normalised, claim_ids_by_disposition, counts


def score_claim_coverage(
    reference_units: list[Mapping[str, Any]],
    expected_verdicts: Mapping[str, str],
    response: Mapping[str, Any],
    adjudication: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate four-disposition adjudication and score protected-unit coverage.

    One returned claim may cover several reference units (combined phrasing), and
    several returned claims may cover one reference unit (split phrasing). Each
    protected reference unit remains one denominator. Factual-verdict accuracy is
    calculated separately from semantic mapping.
    """
    results = _results_by_id(response)
    identified_ids = set(results)
    reference_id_list = [item.get("reference_claim_id") for item in reference_units]
    if any(not isinstance(value, str) or not value for value in reference_id_list):
        raise CoverageError("Reference claim IDs must be non-empty strings")
    if len(reference_id_list) != len(set(reference_id_list)):
        raise CoverageError("Reference claim IDs must be unique")
    reference_ids = set(reference_id_list)
    if set(expected_verdicts) != reference_ids:
        raise CoverageError("Expected verdicts do not match the reference inventory")

    mappings = adjudication.get("mappings")
    if not isinstance(mappings, list):
        raise CoverageError("Adjudication mappings must be a list")
    mapped_reference_ids = [item.get("reference_claim_id") for item in mappings if isinstance(item, dict)]
    if len(mapped_reference_ids) != len(mappings) or set(mapped_reference_ids) != reference_ids:
        raise CoverageError("Every reference unit must be adjudicated exactly once")
    if len(mapped_reference_ids) != len(set(mapped_reference_ids)):
        raise CoverageError("Duplicate reference-unit adjudication")

    complete = partial = missing = correct = 0
    mapping_refs_by_claim: dict[str, set[str]] = defaultdict(set)
    unit_rows = []
    for item in mappings:
        if set(item) != {"reference_claim_id", "identified_claim_ids", "coverage", "reason"}:
            raise CoverageError("Mapping contains missing or unknown fields")
        reference_id = item["reference_claim_id"]
        claim_ids = item["identified_claim_ids"]
        coverage = item["coverage"]
        if not isinstance(claim_ids, list) or len(claim_ids) != len(set(claim_ids)):
            raise CoverageError("Mapped claim IDs must be a unique list")
        if any(value not in identified_ids for value in claim_ids):
            raise CoverageError("Mapping refers to an unknown identified claim")
        if coverage not in {"COMPLETE", "PARTIAL", "MISSING"}:
            raise CoverageError("Unknown coverage status")
        if coverage == "MISSING" and claim_ids:
            raise CoverageError("A missing unit cannot map identified claims")
        if coverage != "MISSING" and not claim_ids:
            raise CoverageError("A covered unit must map at least one identified claim")
        for claim_id in claim_ids:
            mapping_refs_by_claim[claim_id].add(reference_id)
        if coverage == "COMPLETE":
            complete += 1
        elif coverage == "PARTIAL":
            partial += 1
        else:
            missing += 1
        verdict_correct = coverage == "COMPLETE" and all(
            results[claim_id].get("verdict") == expected_verdicts[reference_id]
            for claim_id in claim_ids
        )
        if verdict_correct:
            correct += 1
        unit_rows.append({
            "reference_claim_id": reference_id,
            "coverage": coverage,
            "identified_claim_ids": claim_ids,
            "expected_verdict": expected_verdicts[reference_id],
            "verdict_correct": verdict_correct,
        })

    disposition_rows, claim_ids_by_disposition, disposition_counts = _validate_dispositions(
        adjudication,
        identified_ids,
        reference_ids,
        mapping_refs_by_claim,
    )

    duplicate_groups = adjudication.get("duplicate_groups")
    if not isinstance(duplicate_groups, list):
        raise CoverageError("Duplicate groups must be a list")
    for group in duplicate_groups:
        if not isinstance(group, list) or len(group) < 2 or len(group) != len(set(group)):
            raise CoverageError("Each duplicate group must contain at least two unique IDs")
        if any(value not in identified_ids for value in group):
            raise CoverageError("Duplicate group refers to an unknown identified claim")

    feedback = adjudication.get("correction_feedback")
    if not isinstance(feedback, dict) or set(feedback) != {"status", "reason"}:
        raise CoverageError("Correction-feedback adjudication is incomplete")
    if feedback["status"] not in {"ACCURATE_COMPLETE", "INACCURATE", "INCOMPLETE", "NOT_APPLICABLE"}:
        raise CoverageError("Unknown correction-feedback status")

    gap_ids = claim_ids_by_disposition["INVENTORY_GAP"]
    uncertain_ids = claim_ids_by_disposition["UNCERTAIN_MAPPING"]
    invented_ids = claim_ids_by_disposition["INVENTED"]
    unresolved_ids = sorted(gap_ids | uncertain_ids)
    adjudication_status = "UNRESOLVED" if unresolved_ids else "RESOLVED"
    adjudication_progression_permitted = not unresolved_ids
    gate_progression_permitted = (
        adjudication_progression_permitted
        and not invented_ids
        and not duplicate_groups
        and complete == len(reference_ids)
        and partial == 0
        and missing == 0
    )

    total = len(reference_ids)
    return {
        "candidate_checker_decision": response.get("overall_diagnostic"),
        "adjudication_status": adjudication_status,
        "adjudication_progression_permitted": adjudication_progression_permitted,
        "gate_progression_permitted": gate_progression_permitted,
        "reference_units": total,
        "complete_coverage_units": complete,
        "partial_coverage_units": partial,
        "missing_units": missing,
        "coverage_recall": complete / total if total else 0.0,
        "correctly_assessed_reference_units": correct,
        "assessment_accuracy": correct / total if total else 0.0,
        "mapped_claims": len(claim_ids_by_disposition["MAPPED"]),
        "invented_claims": len(invented_ids),
        "inventory_gap_claims": len(gap_ids),
        "uncertain_mapping_claims": len(uncertain_ids),
        "unresolved_claim_ids": unresolved_ids,
        "disposition_portion_counts": disposition_counts,
        "duplicate_groups": len(duplicate_groups),
        "correction_feedback_status": feedback["status"],
        "unit_rows": unit_rows,
        "claim_disposition_rows": disposition_rows,
    }

