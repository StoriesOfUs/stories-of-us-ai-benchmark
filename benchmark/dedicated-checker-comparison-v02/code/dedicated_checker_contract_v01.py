#!/usr/bin/env python3
"""Pure offline contract and scoring helpers for the dedicated-checker package."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable


LABEL_SUPPORTED = "SUPPORTED"
LABEL_UNSUPPORTED = "UNSUPPORTED"
LABEL_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
CANDIDATE_SUPPORTED = "CANDIDATE_SUPPORTED"
WITHHOLD = "WITHHOLD"


class ContractError(ValueError):
    """Raised when frozen inputs or candidate results violate the contract."""


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def evidence_document(case: dict[str, Any]) -> str:
    evidence = case.get("verified_evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ContractError("empty_evidence")
    seen: set[str] = set()
    rows = ["EVIDENCE PACKET"]
    for item in evidence:
        evidence_id = item.get("evidence_id")
        text = item.get("text")
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ContractError("invalid_evidence_id")
        if evidence_id in seen:
            raise ContractError("duplicate_evidence_id")
        if not isinstance(text, str) or not text.strip():
            raise ContractError("empty_evidence_text")
        seen.add(evidence_id)
        rows.append(f"[{evidence_id}] {text}")
    return "\n".join(rows)


def hhem_input(case: dict[str, Any], claim: dict[str, Any]) -> str:
    return (
        "<pad> Determine if the hypothesis is true given the premise?\n\n"
        f"Premise: {evidence_document(case)}\n\n"
        f"Hypothesis: {claim_text(claim)}"
    )


def minicheck_input(case: dict[str, Any], claim: dict[str, Any], eos_token: str = "</s>") -> str:
    if not isinstance(eos_token, str) or not eos_token:
        raise ContractError("invalid_eos_token")
    return f"predict: {evidence_document(case)}{eos_token}{claim_text(claim)}"


def claim_text(claim: dict[str, Any]) -> str:
    text = claim.get("claim")
    if not isinstance(text, str) or not text.strip():
        raise ContractError("empty_claim")
    return text


def conservative_token_upper_bound(text: str, special_token_allowance: int = 8) -> int:
    """Return a deliberately conservative bound, not an exact token count.

    Each non-special token must consume at least one non-empty input unit. The
    UTF-8 byte count therefore bounds ordinary token count for these frozen
    strings, while the separate allowance covers BOS/EOS/special handling.
    Exact pinned-tokenizer counts are still mandatory before inference.
    """
    if not isinstance(text, str) or not text:
        raise ContractError("empty_formatted_input")
    return len(text.encode("utf-8")) + special_token_allowance


def cases_by_id(case_documents: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for document in case_documents:
        for case in document.get("cases", []):
            case_id = case.get("case_id")
            if not isinstance(case_id, str) or not case_id:
                raise ContractError("invalid_case_id")
            if case_id in result:
                raise ContractError("duplicate_case_id")
            claims = case.get("atomic_claims")
            if not isinstance(claims, list) or not claims:
                raise ContractError(f"{case_id}:empty_claim_inventory")
            claim_ids: set[str] = set()
            for claim in claims:
                claim_id = claim.get("claim_id")
                if not isinstance(claim_id, str) or not claim_id:
                    raise ContractError(f"{case_id}:invalid_claim_id")
                if claim_id in claim_ids:
                    raise ContractError(f"{case_id}:duplicate_claim_id")
                claim_ids.add(claim_id)
                claim_text(claim)
            evidence_document(case)
            result[case_id] = case
    return result


def keys_by_id(key_documents: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for document in key_documents:
        for case_id, expected in document.get("answers", {}).items():
            if case_id in result:
                raise ContractError("duplicate_answer_case_id")
            result[case_id] = expected
    return result


def validate_case_key_membership(cases: dict[str, dict[str, Any]], keys: dict[str, dict[str, Any]]) -> None:
    if set(cases) != set(keys):
        raise ContractError("case_answer_membership_mismatch")
    for case_id, case in cases.items():
        claim_ids = {row["claim_id"] for row in case["atomic_claims"]}
        expected = keys[case_id].get("claim_verdicts")
        if not isinstance(expected, dict) or set(expected) != claim_ids:
            raise ContractError(f"{case_id}:claim_answer_membership_mismatch")
        for verdict in expected.values():
            if verdict not in {LABEL_SUPPORTED, LABEL_UNSUPPORTED, LABEL_INSUFFICIENT}:
                raise ContractError(f"{case_id}:invalid_reference_verdict")


def score_to_decision(score: float, threshold: float) -> str:
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score):
        raise ContractError("invalid_score")
    if not 0.0 <= float(score) <= 1.0:
        raise ContractError("score_out_of_range")
    if not 0.0 < float(threshold) < 1.0:
        raise ContractError("invalid_threshold")
    return CANDIDATE_SUPPORTED if float(score) >= float(threshold) else WITHHOLD


def select_threshold(
    scores: dict[str, float],
    reference_labels: dict[str, str],
    threshold_grid: Iterable[float],
    minimum_supported_accepted: int = 5,
) -> dict[str, Any]:
    if set(scores) != set(reference_labels) or len(scores) != 10:
        raise ContractError("development_score_membership_or_count_failure")
    supported_ids = [claim_id for claim_id, label in reference_labels.items() if label == LABEL_SUPPORTED]
    non_supported_ids = [claim_id for claim_id, label in reference_labels.items() if label != LABEL_SUPPORTED]
    if len(supported_ids) != 7 or len(non_supported_ids) != 3:
        raise ContractError("development_reference_distribution_failure")
    eligible: list[dict[str, Any]] = []
    for threshold in threshold_grid:
        decisions = {claim_id: score_to_decision(scores[claim_id], threshold) for claim_id in scores}
        supported_accepted = sum(decisions[claim_id] == CANDIDATE_SUPPORTED for claim_id in supported_ids)
        non_supported_accepted = sum(decisions[claim_id] == CANDIDATE_SUPPORTED for claim_id in non_supported_ids)
        if non_supported_accepted == 0 and supported_accepted >= minimum_supported_accepted:
            eligible.append({
                "threshold": float(threshold),
                "supported_accepted": supported_accepted,
                "non_supported_accepted": non_supported_accepted,
            })
    if not eligible:
        return {"status": "FAIL", "threshold": None, "eligible": []}
    selected = sorted(eligible, key=lambda row: (row["supported_accepted"], row["threshold"]), reverse=True)[0]
    return {"status": "PASS", "threshold": selected["threshold"], "eligible": eligible, "selected": selected}


def development_allows_evaluation(threshold_result: dict[str, Any]) -> bool:
    threshold = threshold_result.get("threshold")
    return bool(
        threshold_result.get("status") == "PASS"
        and isinstance(threshold, (int, float))
        and not isinstance(threshold, bool)
        and math.isfinite(float(threshold))
        and 0.0 < float(threshold) < 1.0
    )


def reserve_logical_evaluation(attempted: int, maximum: int) -> int:
    if not isinstance(attempted, int) or not isinstance(maximum, int) or attempted < 0 or maximum < 1:
        raise ContractError("invalid_evaluation_budget")
    if attempted >= maximum:
        raise ContractError("logical_evaluation_budget_exhausted")
    return attempted + 1


def aggregate_summary(expected_claim_ids: Iterable[str], decisions: dict[str, str]) -> str:
    ordered = list(expected_claim_ids)
    if not ordered or len(set(ordered)) != len(ordered):
        raise ContractError("empty_or_duplicated_expected_claim_inventory")
    if set(ordered) != set(decisions):
        raise ContractError("incomplete_or_unknown_claim_decisions")
    if any(value not in {CANDIDATE_SUPPORTED, WITHHOLD} for value in decisions.values()):
        raise ContractError("invalid_candidate_decision")
    return CANDIDATE_SUPPORTED if all(decisions[claim_id] == CANDIDATE_SUPPORTED for claim_id in ordered) else WITHHOLD


def validate_result_rows(cases: dict[str, dict[str, Any]], rows: list[dict[str, Any]], candidate: str) -> None:
    expected_pairs = {
        (case_id, claim["claim_id"])
        for case_id, case in cases.items()
        for claim in case["atomic_claims"]
    }
    actual_pairs: set[tuple[str, str]] = set()
    for row in rows:
        if row.get("candidate") != candidate:
            raise ContractError("wrong_candidate_result")
        pair = (row.get("case_id"), row.get("claim_id"))
        if pair in actual_pairs:
            raise ContractError("duplicate_result")
        actual_pairs.add(pair)
        score_to_decision(row.get("score"), row.get("threshold"))
        if row.get("truncated") is not False or row.get("passage_computations") != 1:
            raise ContractError("truncation_or_chunking_result")
        if not isinstance(row.get("formatted_input_sha256"), str) or len(row["formatted_input_sha256"]) != 64:
            raise ContractError("missing_input_hash")
    if actual_pairs != expected_pairs:
        raise ContractError("incomplete_or_unknown_results")


def input_has_answer_leakage(text: str) -> bool:
    forbidden = (
        "expected_whole_summary",
        "claim_verdicts",
        "construction_note",
        "genuinely_insufficient_evidence",
        "subtly_unsafe",
        "fully_supported",
        "CANDIDATE_SUPPORTED",
        "WITHHOLD",
    )
    return any(fragment in text for fragment in forbidden)
