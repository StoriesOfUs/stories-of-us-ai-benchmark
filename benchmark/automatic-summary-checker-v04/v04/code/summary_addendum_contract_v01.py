#!/usr/bin/env python3
"""Offline experimental contract for V04 plus approved Addendum V01.

This module deliberately separates mechanical observations from semantic review.
It does not call a model, fetch a source, or establish factual accuracy.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping


WORD_PATTERN = re.compile(r"\b[\w’'-]+\b", flags=re.UNICODE)
SENTENCE_END_PATTERN = re.compile(r"[.!?]+(?:[\"'’\)\]]*)?(?=\s+|$)")
MANDATORY_SEMANTIC_CHECKS = (
    "material_claims_supported",
    "main_development_accurate_sentence_one",
    "disability_relevance_supported_sentence_one",
    "category_relevance_clear_sentence_one",
    "following_sentences_distinct_useful_supported",
    "event_status_accurate",
    "terminology_compliant_in_context",
    "grammar_and_clarity_pass",
    "originality_pass",
)


def count_words(text: str) -> int:
    """Use the established Stories Of Us Unicode word-token convention."""
    return len(WORD_PATTERN.findall(text))


def _protect_declared_spans(text: str, protected_spans: Iterable[str]) -> tuple[str, list[str]]:
    """Protect punctuation in explicitly supplied names/titles from sentence counting.

    This follows the earlier contextual-count approach: punctuation is protected only
    when the calling fixture declares the exact official name or title. It does not
    guess whether an arbitrary abbreviation is a sentence boundary.
    """
    protected = text
    applied: list[str] = []
    for span in protected_spans:
        if span and span in protected:
            replacement = span.replace(".", "<DOT>").replace("!", "<BANG>").replace("?", "<QMARK>")
            protected = protected.replace(span, replacement)
            applied.append(span)
    return protected, applied


def count_sentences(text: str, protected_spans: Iterable[str] = ()) -> dict[str, Any]:
    """Count prose sentences while recording any contextual punctuation protection."""
    stripped = text.strip()
    if not stripped:
        return {"count": 0, "protected_spans_applied": [], "terminal_punctuation_complete": False}
    protected, applied = _protect_declared_spans(stripped, protected_spans)
    boundaries = list(SENTENCE_END_PATTERN.finditer(protected))
    complete = bool(boundaries and boundaries[-1].end() == len(protected))
    count = len(boundaries) if complete else len(boundaries) + 1
    return {
        "count": count,
        "protected_spans_applied": applied,
        "terminal_punctuation_complete": complete,
    }


def begins_with_exact_source_name(text: str, source_name: str) -> bool:
    """Require the exact source name at character zero, with a real boundary."""
    if not source_name or not text.startswith(source_name):
        return False
    if len(text) == len(source_name):
        return True
    return not text[len(source_name)].isalnum()


def deterministic_review(
    summary: str,
    source_name: str,
    *,
    protected_spans: Iterable[str] = (),
) -> dict[str, Any]:
    """Return mechanical observations only; never infer factual/editorial meaning."""
    word_count = count_words(summary)
    sentence_observation = count_sentences(summary, protected_spans)
    mandatory = {
        "nonempty": bool(summary.strip()),
        "within_absolute_60_word_maximum": word_count <= 60,
        "two_or_three_sentences": sentence_observation["count"] in (2, 3),
        "begins_with_exact_source_name": begins_with_exact_source_name(summary, source_name),
        "terminal_punctuation_complete": sentence_observation["terminal_punctuation_complete"],
    }
    return {
        "word_count": word_count,
        "target_word_count_preference_only": 50,
        "distance_from_50_word_target": abs(word_count - 50),
        "shorter_than_50_is_not_automatic_failure": word_count < 50,
        "sentence_observation": sentence_observation,
        "mandatory_checks": mandatory,
        "mandatory_failures": [name for name, passed in mandatory.items() if not passed],
        "semantic_assessment_status": "NOT_ESTABLISHED_BY_DETERMINISTIC_REVIEW",
    }


def semantic_review_failures(review: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """Return mandatory semantic failures and missing/unresolved checks."""
    failed: list[str] = []
    missing: list[str] = []
    for name in MANDATORY_SEMANTIC_CHECKS:
        value = review.get(name)
        if value is True:
            continue
        if value is False:
            failed.append(name)
        else:
            missing.append(name)
    return failed, missing


@dataclass(frozen=True)
class Assessment:
    outcome: str
    revision_number: int
    deterministic: dict[str, Any]
    semantic_failures: list[str]
    semantic_unresolved: list[str]
    preference_observations: dict[str, Any]
    reason: str


def assess_summary(
    summary: str,
    source_name: str,
    semantic_review: Mapping[str, Any],
    *,
    revision_number: int = 0,
    correctable: bool = True,
    protected_spans: Iterable[str] = (),
) -> Assessment:
    """Apply the one-revision fail-closed decision rule.

    revision_number is 0 for the first draft and 1 for the sole revised draft.
    """
    if revision_number not in (0, 1):
        raise ValueError("Only the first draft (0) and one controlled revision (1) are permitted")
    mechanical = deterministic_review(summary, source_name, protected_spans=protected_spans)
    semantic_failed, semantic_missing = semantic_review_failures(semantic_review)
    failures = mechanical["mandatory_failures"] + semantic_failed
    preferences = {
        "target_word_count": mechanical["target_word_count_preference_only"],
        "distance_from_50_word_target": mechanical["distance_from_50_word_target"],
        "publication_time_present_voice": semantic_review.get("publication_time_present_voice_preference"),
    }
    if semantic_missing:
        return Assessment(
            "HOLD",
            revision_number,
            mechanical,
            semantic_failed,
            semantic_missing,
            preferences,
            "Mandatory semantic review is incomplete or unresolved.",
        )
    if not failures:
        return Assessment(
            "ACCEPT",
            revision_number,
            mechanical,
            [],
            [],
            preferences,
            "All mandatory mechanical and semantic requirements passed.",
        )
    if revision_number == 0 and correctable:
        return Assessment(
            "REVISE",
            revision_number,
            mechanical,
            semantic_failed,
            [],
            preferences,
            "A specific correctable mandatory failure permits one controlled revision.",
        )
    return Assessment(
        "HOLD",
        revision_number,
        mechanical,
        semantic_failed,
        [],
        preferences,
        "A mandatory failure remains after the permitted revision, or is not correctable.",
    )


def revision_allowed(previous: Assessment) -> bool:
    """Permit a revision only from the first-draft REVISE state."""
    return previous.revision_number == 0 and previous.outcome == "REVISE"

