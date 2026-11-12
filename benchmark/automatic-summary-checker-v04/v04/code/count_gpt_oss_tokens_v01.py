#!/usr/bin/env python3
"""Count V03 fixed checker prompts with the pinned published Harmony renderer."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys


PACKAGE = Path(__file__).resolve().parents[1]
PROJECT_ROOT = next(parent for parent in PACKAGE.parents if (parent / "AGENTS.md").is_file())
TOKENIZER = PROJECT_ROOT / (
    "mission_based_ai_discovery_news_desk/output/ai_agent_governance_autonomy_audit_v01/"
    "option_c_automatic_summary_checker_readiness_resolution_v01/assets/tokenizer"
)
os.environ["TIKTOKEN_ENCODINGS_BASE"] = str(TOKENIZER)
sys.path.insert(0, str(TOKENIZER / "vendor"))
sys.path.insert(0, str(PACKAGE / "code"))

import openai_harmony as harmony  # noqa: E402
from payloads_v01 import checker_payload  # noqa: E402


ENCODING = harmony.load_harmony_encoding(harmony.HarmonyEncodingName.HARMONY_GPT_OSS)


def load(relative: str):
    return json.loads((PACKAGE / relative).read_text(encoding="utf-8"))


def render_count(messages: list[dict[str, str]]) -> int:
    if [item["role"] for item in messages] != ["system", "user"]:
        raise ValueError("Checker messages are no longer exactly system plus user")
    conversation = harmony.Conversation.from_messages([
        harmony.Message.from_role_and_content(
            harmony.Role.SYSTEM,
            harmony.SystemContent.new().with_reasoning_effort(harmony.ReasoningEffort.LOW),
        ),
        harmony.Message.from_role_and_content(
            harmony.Role.DEVELOPER,
            harmony.DeveloperContent.new().with_instructions(messages[0]["content"]),
        ),
        harmony.Message.from_role_and_content(harmony.Role.USER, messages[1]["content"]),
    ])
    return len(ENCODING.render_conversation_for_completion(conversation, harmony.Role.ASSISTANT))


def main() -> None:
    instruction = (PACKAGE / "immutable/instructions/gpt_oss_checker_v01.txt").read_text(encoding="utf-8")
    rows = []
    for stage in ("development", "evaluation"):
        cases = load(f"private/cases/{stage}_cases_model_facing_v01.json")["cases"]
        evidence = load(f"private/evidence/{stage}_evidence_index_v01.json")["cases"]
        for case in cases:
            payload = checker_payload(case, evidence[case["case_id"]]["paragraphs"], instruction)
            rows.append({
                "case_id": case["case_id"],
                "stage": stage,
                "stage_context": case["stage_context"],
                "exact_local_harmony_input_tokens": render_count(payload["messages"]),
                "output_and_reasoning_allowance_tokens": payload["max_tokens"],
                "frozen_input_ceiling_tokens": 14000,
                "compact_json_utf8_bytes": len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
            })

    wheel = TOKENIZER / "openai_harmony-0.0.8-cp38-abi3-macosx_11_0_arm64.whl"
    vocab = TOKENIZER / "o200k_base.tiktoken"
    result = {
        "schema_version": "stories-of-us-gpt-oss-claim-identification-harmony-token-count-v01",
        "status": "LOCAL_EXACT_UNDER_PINNED_PUBLISHED_OPENAI_HARMONY_FORMAT",
        "tokenizer": {
            "encoding": "o200k_harmony",
            "renderer": "openai-harmony 0.0.8",
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "vocabulary": "o200k_base.tiktoken",
            "vocabulary_sha256": hashlib.sha256(vocab.read_bytes()).hexdigest(),
            "message_mapping": "generated Harmony system with reasoning LOW; API system prompt mapped to Harmony developer; API user prompt mapped to Harmony user; assistant generation prefill included",
        },
        "hosted_format_status": "UNVERIFIED: Cloudflare does not publish the exact deployed Harmony renderer/version or token-count endpoint.",
        "fixed_initial_requests": rows,
        "summary": {
            "requests_counted_exactly_locally": len(rows),
            "development_input_tokens": sum(row["exact_local_harmony_input_tokens"] for row in rows if row["stage"] == "development"),
            "evaluation_input_tokens": sum(row["exact_local_harmony_input_tokens"] for row in rows if row["stage"] == "evaluation"),
            "largest_case_id": max(rows, key=lambda row: row["exact_local_harmony_input_tokens"])["case_id"],
            "largest_exact_local_harmony_input_tokens": max(row["exact_local_harmony_input_tokens"] for row in rows),
            "all_fixed_requests_below_14000": all(row["exact_local_harmony_input_tokens"] <= 14000 for row in rows),
        },
        "content_dependent_requests": {
            "gemma_revisions": "Four possible future requests (D14 plus three evaluation cases) contain checker feedback and revised text that are unknown; enforce the 16000-token ceiling and exact-count every realised request before transmission.",
            "gpt_oss_rechecks": "Four possible future revised summaries are unknown; enforce the 14000-token ceiling and exact-count every realised Harmony request before transmission.",
            "no_truncation_splitting_or_substitution": True
        },
        "reservation": {
            "aggregate_input_ceiling": 498000,
            "aggregate_output_and_reasoning_ceiling": 48640,
            "reservation_neurons": 17665.317664,
            "hard_cap_neurons": 17666,
            "day_1_neurons": 8252.693280,
            "day_2_neurons": 702.617440,
            "day_3_neurons": 8710.006944,
        },
    }
    destination = PACKAGE / "reports/exact_tokenizer_counts_v01.json"
    destination.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
