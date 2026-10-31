#!/usr/bin/env python3
"""Deterministic, provenance-preserving evidence preparation for the V01 experiment."""
from __future__ import annotations

import re
from typing import Any


VALID_STATUSES = {
    "SELF_CONTAINED",
    "CONTEXT_INCOMPLETE",
    "AMBIGUOUS_REFERENCE",
    "INSUFFICIENT_EVIDENCE",
    "PREPARATION_FAILED",
}

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "by", "for", "from",
    "had", "has", "have", "in", "into", "is", "it", "its", "of", "on", "or", "that",
    "the", "their", "them", "they", "this", "those", "to", "was", "were", "when", "where",
    "which", "while", "will", "with", "without", "article", "published", "says", "said",
    "reports", "reported", "source", "already", "every", "all", "no", "not",
}

CONTEXT_NOUNS = {
    "artwork", "artworks", "bill", "device", "devices", "exhibition", "glasses", "initiative",
    "key", "programme", "project", "research", "screen", "selection", "service", "services",
    "switch", "update",
}

AMBIGUOUS_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bit\b", r"\bthey\b", r"\bthem\b",
        r"\bthe devices?\b", r"\bthe update\b", r"\bthe glasses\b", r"\bthe key\b",
        r"\bthe bill\b", r"\bthe exhibition\b", r"\bthe project\b", r"\bthe initiative\b",
        r"\bthe selection\b", r"\ball artworks\b",
    ]
]


def tokenise(text: str) -> list[str]:
    """Return stable lowercase word/number tokens, splitting punctuation and hyphens."""
    return [token.lower() for token in re.findall(r"[A-Za-z0-9]+", text)]


def material_tokens(text: str) -> set[str]:
    return {token for token in tokenise(text) if token not in STOPWORDS and len(token) > 1}


def named_tokens(text: str) -> set[str]:
    raw = re.findall(r"\b(?:[A-Z][A-Za-z0-9]*|[A-Z]{2,}|[A-Za-z]+[0-9]+)\b", text)
    return {token.lower() for token in raw if token.lower() not in STOPWORDS}


def has_ambiguous_reference(text: str) -> bool:
    return any(pattern.search(text) for pattern in AMBIGUOUS_PATTERNS)


def evidence_index(article: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["evidence_id"]: row for row in article.get("evidence", [])}


def _candidate_details(
    claim_text: str,
    original_text: str,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    claim_tokens = material_tokens(claim_text)
    original_tokens = material_tokens(original_text)
    unresolved = claim_tokens - original_tokens
    candidate_tokens = material_tokens(candidate["text"])
    overlap = unresolved & candidate_tokens
    named = named_tokens(claim_text)
    score = 2 * len(overlap)
    score += 2 * len(overlap & named)
    score += len(overlap & CONTEXT_NOUNS)
    if overlap and (candidate_tokens & original_tokens):
        score += 1
    return {
        "evidence_id": candidate["evidence_id"],
        "score": score,
        "matched_unresolved_tokens": sorted(overlap),
        "matched_named_tokens": sorted(overlap & named),
        "candidate_material_tokens": sorted(candidate_tokens),
    }


def prepare_evidence(
    article: dict[str, Any],
    claim_text: str,
    original_evidence_ids: list[str],
    *,
    maximum_added_passages: int = 2,
    minimum_candidate_score: int = 2,
) -> dict[str, Any]:
    """Select existing verified passages automatically; never create new factual prose."""
    try:
        available = evidence_index(article)
        missing = [evidence_id for evidence_id in original_evidence_ids if evidence_id not in available]
        if missing or not original_evidence_ids:
            return {
                "status": "INSUFFICIENT_EVIDENCE",
                "original_evidence_ids": list(original_evidence_ids),
                "prepared_evidence_ids": [],
                "added_context": [],
                "unresolved_ambiguity": [f"Missing evidence: {item}" for item in missing],
                "prepared_text": "",
                "provenance_integrity": False,
            }

        original = [available[evidence_id] for evidence_id in original_evidence_ids]
        original_text = " ".join(row["text"].strip() for row in original)
        candidate_rows = [
            row for row in article.get("evidence", [])
            if row["evidence_id"] not in set(original_evidence_ids)
        ]
        ranked = [
            (_candidate_details(claim_text, original_text, row), row)
            for row in candidate_rows
        ]
        ranked.sort(key=lambda item: (-item[0]["score"], item[0]["evidence_id"]))

        added_rows: list[dict[str, Any]] = []
        additions: list[dict[str, Any]] = []
        already_covered = material_tokens(original_text)
        for details, row in ranked:
            if len(added_rows) >= maximum_added_passages:
                break
            if details["score"] < minimum_candidate_score:
                continue
            newly_covered = set(details["matched_unresolved_tokens"]) - already_covered
            if not newly_covered:
                continue
            added_rows.append(row)
            already_covered.update(material_tokens(row["text"]))
            additions.append({
                "evidence_id": row["evidence_id"],
                "source_locations": list(row.get("source_locations", [])),
                "status": row.get("status"),
                "selection_reason": "AUTOMATIC_UNRESOLVED_TOKEN_RELEVANCE",
                "score": details["score"],
                "matched_unresolved_tokens": sorted(newly_covered),
                "matched_named_tokens": details["matched_named_tokens"],
            })

        # Context comes first so later pronouns and definite descriptions have an antecedent.
        prepared_rows = added_rows + original
        prepared_ids = [row["evidence_id"] for row in prepared_rows]
        prepared_text = " ".join(row["text"].strip() for row in prepared_rows)
        ambiguity = has_ambiguous_reference(original_text)
        unresolved: list[str] = []
        if ambiguity and len(original) == 1 and not added_rows:
            unresolved.append("Original evidence contains a context-dependent reference with no qualifying passage selected.")

        claim_material = material_tokens(claim_text)
        prepared_material = material_tokens(prepared_text)
        meaningful_overlap = claim_material & prepared_material
        if not meaningful_overlap:
            unresolved.append("Prepared evidence shares no meaningful material tokens with the claim.")

        provenance_integrity = all(
            available[row["evidence_id"]]["text"] == row["text"] for row in prepared_rows
        ) and set(original_evidence_ids).issubset(prepared_ids)

        if not provenance_integrity:
            status = "PREPARATION_FAILED"
        elif unresolved and ambiguity:
            status = "AMBIGUOUS_REFERENCE"
        elif unresolved:
            status = "CONTEXT_INCOMPLETE"
        else:
            status = "SELF_CONTAINED"

        return {
            "status": status,
            "article_id": article.get("article_id"),
            "source_url": article.get("url"),
            "claim": claim_text,
            "original_evidence_ids": list(original_evidence_ids),
            "prepared_evidence_ids": prepared_ids,
            "original_text": original_text,
            "prepared_text": prepared_text,
            "added_context": additions,
            "unresolved_ambiguity": unresolved,
            "maximum_added_passages": maximum_added_passages,
            "minimum_candidate_score": minimum_candidate_score,
            "provenance_integrity": provenance_integrity,
            "claim_text_inserted_as_evidence": claim_text.strip() in {
                row["text"].strip() for row in added_rows
            },
        }
    except Exception as exc:  # fail closed and retain a bounded reason
        return {
            "status": "PREPARATION_FAILED",
            "original_evidence_ids": list(original_evidence_ids),
            "prepared_evidence_ids": [],
            "added_context": [],
            "unresolved_ambiguity": [f"{type(exc).__name__}: {exc}"],
            "prepared_text": "",
            "provenance_integrity": False,
        }
