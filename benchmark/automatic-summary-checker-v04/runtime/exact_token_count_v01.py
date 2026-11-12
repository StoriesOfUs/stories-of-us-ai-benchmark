#!/usr/bin/env python3
"""Pinned local token counting for the V04 live overlay.

This module performs no network access. GPT-OSS requests are rendered through
OpenAI Harmony 0.0.8. Gemma requests are rendered with the exact pinned Gemma 4
chat template and tokenizer assets used by the earlier successful writer run.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


GPT_MODEL = "@cf/openai/gpt-oss-120b"
GEMMA_MODEL = "@cf/google/gemma-4-26b-a4b-it"
GPT_INPUT_LIMIT = 14_000
GPT_OUTPUT_LIMIT = 1_536
GPT_CONTEXT_LIMIT = 128_000
GEMMA_INPUT_LIMIT = 16_000
GEMMA_OUTPUT_LIMIT = 256
GEMMA_CONTEXT_LIMIT = 256_000


class CountError(RuntimeError):
    pass


def _raise_template_error(message: str) -> None:
    raise CountError(f"Gemma chat-template error: {message}")


class ExactTokenCounter:
    def __init__(self, asset_root: Path):
        self.asset_root = asset_root
        harmony_assets = asset_root / "gpt_oss_tokenizer"
        gemma_assets = asset_root / "gemma_tokenizer"
        required = (
            harmony_assets / "o200k_base.tiktoken",
            gemma_assets / "tokenizer.json",
            gemma_assets / "tokenizer_config.json",
            gemma_assets / "chat_template.jinja",
        )
        if any(not path.is_file() for path in required):
            raise CountError("Pinned tokenizer asset is absent")

        os.environ["TIKTOKEN_ENCODINGS_BASE"] = str(harmony_assets)
        try:
            import openai_harmony as harmony
            from jinja2 import StrictUndefined
            from jinja2.sandbox import ImmutableSandboxedEnvironment
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise CountError("Pinned tokenizer runtime is unavailable") from exc

        self.harmony = harmony
        self.harmony_encoding = harmony.load_harmony_encoding(
            harmony.HarmonyEncodingName.HARMONY_GPT_OSS
        )
        self.gemma_tokenizer = Tokenizer.from_file(str(gemma_assets / "tokenizer.json"))
        environment = ImmutableSandboxedEnvironment(undefined=StrictUndefined)
        environment.globals["raise_exception"] = _raise_template_error
        self.gemma_template = environment.from_string(
            (gemma_assets / "chat_template.jinja").read_text(encoding="utf-8")
        )
        self.gemma_config = json.loads(
            (gemma_assets / "tokenizer_config.json").read_text(encoding="utf-8")
        )

    def count_gpt_oss(self, payload: dict[str, Any]) -> int:
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
            self.harmony_encoding.render_conversation_for_completion(
                conversation, harmony.Role.ASSISTANT
            )
        )

    def count_gemma(self, payload: dict[str, Any]) -> int:
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise CountError("Gemma payload messages are absent")
        kwargs = payload.get("chat_template_kwargs") or {}
        if kwargs != {"enable_thinking": False}:
            raise CountError("Gemma chat-template mode differs from the frozen mode")
        rendered = self.gemma_template.render(
            messages=messages,
            tools=None,
            add_generation_prompt=True,
            enable_thinking=False,
            preserve_thinking=True,
            **self.gemma_config,
        )
        return len(self.gemma_tokenizer.encode(rendered, add_special_tokens=False).ids)

    def enforce(self, payload: dict[str, Any]) -> dict[str, Any]:
        model = payload.get("model")
        if model == GPT_MODEL:
            input_tokens = self.count_gpt_oss(payload)
            output_tokens = payload.get("max_tokens")
            input_limit, output_limit, context_limit = (
                GPT_INPUT_LIMIT,
                GPT_OUTPUT_LIMIT,
                GPT_CONTEXT_LIMIT,
            )
            method = "OPENAI_HARMONY_0_0_8_PINNED_LOCAL"
        elif model == GEMMA_MODEL:
            input_tokens = self.count_gemma(payload)
            output_tokens = payload.get("max_tokens")
            input_limit, output_limit, context_limit = (
                GEMMA_INPUT_LIMIT,
                GEMMA_OUTPUT_LIMIT,
                GEMMA_CONTEXT_LIMIT,
            )
            method = "GEMMA_4_PINNED_TOKENIZER_AND_CHAT_TEMPLATE_LOCAL"
        else:
            raise CountError("Payload model differs from the frozen model IDs")
        if not isinstance(output_tokens, int) or isinstance(output_tokens, bool):
            raise CountError("Output allowance is absent or invalid")
        if input_tokens > input_limit:
            raise CountError("Exact local input count exceeds the frozen per-request limit")
        if output_tokens > output_limit:
            raise CountError("Output allowance exceeds the frozen per-request limit")
        if input_tokens + output_tokens > context_limit:
            raise CountError("Complete request plus output allowance exceeds hosted context")
        return {
            "model": model,
            "exact_local_input_tokens": input_tokens,
            "output_allowance_tokens": output_tokens,
            "input_limit_tokens": input_limit,
            "context_limit_tokens": context_limit,
            "count_method": method,
            "hosted_format_equivalence": "UNVERIFIED",
        }
