#!/usr/bin/env python3
"""Validate protected CODEX_ASSISTED V06 stage-review submissions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class ReviewStop(RuntimeError):
    pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def evaluate_stage_review(private_root: Path, scientific_root: Path, stage: str) -> dict[str, Any]:
    if stage not in {"regression", "fresh"}:
        raise ReviewStop("Unknown V06 review stage")
    expected_count = 4 if stage == "regression" else 8
    review_path = private_root / f"live_v06/reviews/{stage}_protected_review_v01.json"
    if not review_path.is_file():
        raise ReviewStop("Protected stage review is absent")
    review = read_json(review_path)
    required_top = {
        "schema_version", "stage", "scientific_freeze_sha256", "review_method",
        "cases", "review_complete", "gate_passed",
    }
    if not isinstance(review, dict) or set(review) != required_top:
        raise ReviewStop("Protected stage review has missing or unknown fields")
    freeze = (scientific_root / "recovery/freeze_manifest_sha256_v06.txt").read_text(encoding="utf-8").strip()
    if review["stage"] != stage or review["scientific_freeze_sha256"] != freeze:
        raise ReviewStop("Protected review identity mismatch")
    if review["review_method"] != "CODEX_ASSISTED" or review["review_complete"] is not True:
        raise ReviewStop("Complete CODEX_ASSISTED review is required")
    key_name = "regression_answer_key_v06.json" if stage == "regression" else "fresh_answer_key_v06.json"
    key = read_json(scientific_root / "private/answer_keys" / key_name)
    expected = {row["case_id"]: row for row in key["cases"]}
    cases = review["cases"]
    if not isinstance(cases, list) or len(cases) != expected_count:
        raise ReviewStop("Protected review case count is incomplete")
    seen: set[str] = set()
    all_pass = True
    for row in cases:
        required_row = {
            "case_id", "candidate_response_sha256", "contract_valid",
            "decision_matches_key", "attribution_matches_key", "scope_matches_key",
            "category_matches_key", "correction_matches_key",
            "evidence_references_valid_and_relevant", "unsafe_approval",
        }
        if not isinstance(row, dict) or set(row) != required_row:
            raise ReviewStop("Protected review row has missing or unknown fields")
        case_id = row["case_id"]
        if case_id not in expected or case_id in seen:
            raise ReviewStop("Protected review contains an unknown or duplicate case")
        seen.add(case_id)
        slot = ("REGRESSION__" if stage == "regression" else "FRESH__") + case_id
        parsed_path = private_root / f"live_v06/results/parsed/{slot}.json"
        if not parsed_path.is_file():
            raise ReviewStop("Parsed response required by protected review is absent")
        parsed = read_json(parsed_path)
        if row["candidate_response_sha256"] != parsed.get("candidate_response_sha256"):
            raise ReviewStop("Protected review is not bound to the saved response")
        authoritative = parsed.get("authoritative") or {}
        comparisons = authoritative.get("structured_comparisons") or {}
        automatically_matches = (
            authoritative.get("contract_valid") is True
            and authoritative.get("authoritative_decision") == expected[case_id]["expected_decision"]
            and (comparisons.get("attribution") or {}).get("verdict") == expected[case_id]["attribution_verdict"]
            and (comparisons.get("scope") or {}).get("verdict") == expected[case_id]["scope_verdict"]
            and (comparisons.get("category") or {}).get("centrality") == expected[case_id]["category_centrality"]
            and (comparisons.get("category") or {}).get("verdict") == expected[case_id]["category_verdict"]
            and bool(authoritative.get("correction_guidance")) == expected[case_id]["correction_eligible"]
        )
        protected_matches = all(
            row[field] is True
            for field in (
                "contract_valid", "decision_matches_key", "attribution_matches_key",
                "scope_matches_key", "category_matches_key", "correction_matches_key",
                "evidence_references_valid_and_relevant",
            )
        )
        row_pass = automatically_matches and protected_matches and row["unsafe_approval"] is False
        all_pass = all_pass and row_pass
    if seen != set(expected):
        raise ReviewStop("Protected review does not cover every frozen case")
    if review["gate_passed"] is not all_pass:
        raise ReviewStop("Protected review gate result contradicts its case results")
    return {
        "stage": stage,
        "gate_passed": all_pass,
        "review_sha256": canonical_hash(review),
        "case_count": expected_count,
    }
