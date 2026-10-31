#!/usr/bin/env python3
"""Bounded component tests for the automatic evidence preparer."""
from __future__ import annotations

import argparse
import json
import pathlib

from evidence_preparer import prepare_evidence


def load(path: str) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def maps(data: dict) -> tuple[dict, dict]:
    return (
        {row["article_id"]: row for row in data["articles"]},
        {row["claim_id"]: row for row in data["claims"]},
    )


def assert_prepared(data: dict, claim_id: str, expected_context_ids) -> None:
    articles, claims = maps(data)
    claim = claims[claim_id]
    ids = claim.get("baseline_evidence_ids", claim.get("evidence_ids"))
    result = prepare_evidence(articles[claim["article_id"]], claim["claim"], ids)
    assert result["status"] == "SELF_CONTAINED", (claim_id, result)
    acceptable = {expected_context_ids} if isinstance(expected_context_ids, str) else expected_context_ids
    assert acceptable & set(result["prepared_evidence_ids"]), (claim_id, result)
    assert len(result["added_context"]) <= 2
    assert result["provenance_integrity"] is True
    assert result["claim_text_inserted_as_evidence"] is False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--holdout", required=True)
    args = parser.parse_args()
    baseline = load(args.baseline)
    holdout = load(args.holdout)

    assert_prepared(baseline, "pc_bca_facility_bans", {"bca_f1", "bca_f2"})
    assert_prepared(baseline, "pc_puck_pressure", "puck_f1")
    assert_prepared(baseline, "pc_vanda_objects", "vanda_f1")
    assert_prepared(baseline, "hu_kate_identity", "kate_f1")
    assert_prepared(holdout, "new_radar_supported_context", "radar_f1")
    assert_prepared(holdout, "new_olmstead_supported_identity", "olm_f1")
    assert_prepared(holdout, "new_frame_supported_access", "frame_f1")
    assert_prepared(holdout, "new_nvda_supported_braille", "nvda_f1")
    assert_prepared(holdout, "new_glasses_supported_function", "glasses_f1")

    synthetic = {
        "article_id": "ambiguous",
        "url": "https://example.invalid/article",
        "evidence": [{"evidence_id": "e1", "status": "VERIFIED_FACT", "text": "They completed it."}],
    }
    ambiguous = prepare_evidence(synthetic, "The team completed the project.", ["e1"])
    assert ambiguous["status"] == "AMBIGUOUS_REFERENCE", ambiguous
    missing = prepare_evidence(synthetic, "The team completed the project.", ["missing"])
    assert missing["status"] == "INSUFFICIENT_EVIDENCE", missing

    for data in [baseline, holdout]:
        articles, claims = maps(data)
        for claim in claims.values():
            ids = claim.get("baseline_evidence_ids", claim.get("evidence_ids"))
            result = prepare_evidence(articles[claim["article_id"]], claim["claim"], ids)
            assert len(result["added_context"]) <= 2
            if result["prepared_evidence_ids"]:
                available = {row["evidence_id"]: row["text"] for row in articles[claim["article_id"]]["evidence"]}
                expected = " ".join(available[item].strip() for item in result["prepared_evidence_ids"])
                assert result["prepared_text"] == expected
            assert result.get("claim_text_inserted_as_evidence", False) is False

    print(json.dumps({"status": "PASS", "component_tests": 15, "provenance_sweep": "PASS"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
