#!/usr/bin/env python3
"""Pinned offline token counting for the V06 GPT-OSS checker requests."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


GPT_MODEL = "@cf/openai/gpt-oss-120b"
GPT_INPUT_LIMIT = 14_000
GPT_OUTPUT_LIMIT = 3_072
GPT_CONTEXT_LIMIT = 128_000


class CountError(RuntimeError):
    pass


class ExactTokenCounter:
    def __init__(self, asset_root: Path):
        harmony_assets = asset_root / "gpt_oss_tokenizer"
        vocabulary = harmony_assets / "o200k_base.tiktoken"
        if not vocabulary.is_file():
            raise CountError("Pinned GPT-OSS tokenizer asset is absent")
        os.environ["TIKTOKEN_ENCODINGS_BASE"] = str(harmony_assets)
        try:
            import openai_harmony as harmony
        except ImportError as exc:
            raise CountError("Pinned OpenAI Harmony runtime is unavailable") from exc
        self.harmony = harmony
        self.encoding = harmony.load_harmony_encoding(
            harmony.HarmonyEncodingName.HARMONY_GPT_OSS
        )

    def count(self, payload: dict[str, Any]) -> int:
        if payload.get("model") != GPT_MODEL:
            raise CountError("Payload model differs from the frozen V06 model")
        messages = payload.get("messages")
        if not isinstance(messages, list) or [row.get("role") for row in messages] != ["system", "user"]:
            raise CountError("GPT-OSS payload must contain exactly system and user messages")
        harmony = self.harmony
        conversation = harmony.Conversation.from_messages(
            [
                harmony.Message.from_role_and_content(
                    harmony.Role.SYSTEM,
                    harmony.SystemContent.new().with_reasoning_effort(
                        harmony.ReasoningEffort.LOW
                    ),
                ),
                harmony.Message.from_role_and_content(
                    harmony.Role.DEVELOPER,
                    harmony.DeveloperContent.new().with_instructions(messages[0]["content"]),
                ),
                harmony.Message.from_role_and_content(
                    harmony.Role.USER, messages[1]["content"]
                ),
            ]
        )
        return len(
            self.encoding.render_conversation_for_completion(
                conversation, harmony.Role.ASSISTANT
            )
        )

    def enforce(self, payload: dict[str, Any]) -> dict[str, Any]:
        input_tokens = self.count(payload)
        output_tokens = payload.get("max_tokens")
        if not isinstance(output_tokens, int) or isinstance(output_tokens, bool):
            raise CountError("Output allowance is absent or invalid")
        if input_tokens > GPT_INPUT_LIMIT:
            raise CountError("Exact local input count exceeds the frozen per-request limit")
        if output_tokens > GPT_OUTPUT_LIMIT:
            raise CountError("Output allowance exceeds the frozen per-request limit")
        if input_tokens + output_tokens > GPT_CONTEXT_LIMIT:
            raise CountError("Complete request plus output allowance exceeds hosted context")
        return {
            "model": GPT_MODEL,
            "exact_local_input_tokens": input_tokens,
            "output_allowance_tokens": output_tokens,
            "input_limit_tokens": GPT_INPUT_LIMIT,
            "context_limit_tokens": GPT_CONTEXT_LIMIT,
            "count_method": "OPENAI_HARMONY_0_0_8_PINNED_LOCAL",
            "hosted_format_equivalence": "UNVERIFIED",
        }
