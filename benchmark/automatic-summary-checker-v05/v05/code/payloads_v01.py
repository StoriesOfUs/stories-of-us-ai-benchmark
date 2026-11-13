#!/usr/bin/env python3
"""Frozen payload construction for the automatic-checker experiment.

This module performs no network I/O. It keeps hidden answers out of model-facing
messages and preserves complete retained evidence without truncation or splitting.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from checker_core_v01 import build_checker_messages


CHECKER_MODEL = "@cf/openai/gpt-oss-120b"
WRITER_MODEL = "@cf/google/gemma-4-26b-a4b-it"
MAX_REVIEW_REASON_CHARS = 1200


def checker_payload(case: dict[str, Any], evidence: list[dict[str, str]], instruction: str) -> dict[str, Any]:
    return {
        "model": CHECKER_MODEL,
        "messages": build_checker_messages(case, evidence, instruction),
        "reasoning_effort": "low",
        "temperature": 0,
        "seed": 42,
        "stream": False,
        "max_tokens": 2560,
        "options": {"rejectIfBusy": True},
    }


def _article_packet(case: dict[str, Any], article_text: str) -> str:
    return (
        "VERIFIED ARTICLE INFORMATION:\n"
        f"SOURCE_NAME: {case['source_name']}\n"
        f"HEADLINE: {case['title']}\n"
        f"CATEGORY: {case['category']}\n"
        f"CANONICAL URL: {case['canonical_url']}\n"
        "COMPLETE RETAINED ARTICLE BODY:\n"
        f"{article_text}"
    )


def _insert_packet(instruction: str, packet: str) -> str:
    opening, final_rule = instruction.strip().rsplit("\n\n", 1)
    return f"{opening}\n\n{packet}\n\n{final_rule}"


def revision_payload(
    case: dict[str, Any],
    article_text: str,
    failed_summary: str,
    checker_reason: str,
    initial_instruction: str,
    revision_instruction: str,
) -> dict[str, Any]:
    if not checker_reason.strip() or len(checker_reason) > MAX_REVIEW_REASON_CHARS:
        raise ValueError("Checker correction reason is empty or exceeds the frozen limit")
    revision = revision_instruction.replace("`REVIEW_REASON`", checker_reason)
    prompt = (
        _insert_packet(initial_instruction, _article_packet(case, article_text))
        + "\n\nFIRST DRAFT TO REVISE:\n"
        + failed_summary
        + "\n\n"
        + revision.strip()
    )
    return {
        "model": WRITER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "seed": 42,
        "stream": False,
        "max_tokens": 256,
        "chat_template_kwargs": {"enable_thinking": False},
        "options": {"rejectIfBusy": True},
    }


def compact_utf8_bytes(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def read_instruction(path: Path) -> str:
    return path.read_text(encoding="utf-8")
