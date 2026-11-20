#!/usr/bin/env python3
"""Pinned pre-transmission token counting for both frozen V08 models."""
from __future__ import annotations

import heapq
import json
import os
from pathlib import Path
import re
from typing import Any


GPT_MODEL = "@cf/openai/gpt-oss-120b"
GEMMA_MODEL = "@cf/google/gemma-4-26b-a4b-it"
GPT_INPUT_LIMIT = 14_000
GPT_OUTPUT_LIMIT = 3_072
GPT_CONTEXT_LIMIT = 128_000
GEMMA_INPUT_LIMIT = 16_000
GEMMA_OUTPUT_LIMIT = 256
GEMMA_CONTEXT_LIMIT = 256_000


class CountError(RuntimeError):
    pass


class GemmaPinnedBPE:
    def __init__(self, tokenizer_path: Path):
        document = json.loads(tokenizer_path.read_text(encoding="utf-8"))
        self.vocab = document["model"]["vocab"]
        self.ranks = {tuple(pair): rank for rank, pair in enumerate(document["model"]["merges"])}
        self.specials = sorted(
            (row["content"] for row in document["added_tokens"] if row.get("special")),
            key=len,
            reverse=True,
        )
        self.special_pattern = re.compile("(" + "|".join(re.escape(value) for value in self.specials) + ")")

    def _initial(self, text: str) -> list[str]:
        normalised = text.replace(" ", "▁")
        output: list[str] = []
        for char in normalised:
            if char in self.vocab:
                output.append(char)
            else:
                output.extend(f"<0x{byte:02X}>" for byte in char.encode("utf-8"))
        return output

    def _bpe_count(self, text: str) -> int:
        tokens = self._initial(text)
        if not tokens:
            return 0
        previous = [index - 1 for index in range(len(tokens))]
        following = [index + 1 for index in range(len(tokens))]
        following[-1] = -1
        alive = [True] * len(tokens)
        version = [0] * len(tokens)
        heap: list[tuple[int, int, int, int, int]] = []

        def offer(left: int, right: int) -> None:
            if left < 0 or right < 0 or not alive[left] or not alive[right] or following[left] != right:
                return
            rank = self.ranks.get((tokens[left], tokens[right]))
            if rank is not None:
                heapq.heappush(heap, (rank, left, right, version[left], version[right]))

        for index in range(len(tokens) - 1):
            offer(index, index + 1)
        remaining = len(tokens)
        while heap:
            _rank, left, right, left_version, right_version = heapq.heappop(heap)
            if (
                not alive[left] or not alive[right] or following[left] != right
                or version[left] != left_version or version[right] != right_version
            ):
                continue
            merged = tokens[left] + tokens[right]
            if merged not in self.vocab:
                continue
            tokens[left] = merged
            version[left] += 1
            alive[right] = False
            version[right] += 1
            next_index = following[right]
            following[left] = next_index
            if next_index >= 0:
                previous[next_index] = left
            remaining -= 1
            offer(previous[left], left)
            offer(left, next_index)
        return remaining

    def count(self, rendered: str) -> int:
        total = 0
        for part in self.special_pattern.split(rendered):
            if not part:
                continue
            total += 1 if part in self.vocab and part in self.specials else self._bpe_count(part)
        return total


def gemma_render_user(prompt: str) -> str:
    return (
        "<bos><|turn>user\n" + prompt.strip() + "<turn|>\n"
        "<|turn>model\n<|channel>thought\n<channel|>"
    )


class ExactTokenCounter:
    def __init__(self, asset_root: Path):
        harmony_assets = asset_root / "gpt_oss_tokenizer"
        vocabulary = harmony_assets / "o200k_base.tiktoken"
        gemma_tokenizer = asset_root / "gemma_tokenizer/tokenizer.json"
        if not vocabulary.is_file() or not gemma_tokenizer.is_file():
            raise CountError("Pinned tokenizer assets are incomplete")
        os.environ["TIKTOKEN_ENCODINGS_BASE"] = str(harmony_assets)
        try:
            import openai_harmony as harmony
        except ImportError as exc:
            raise CountError("Pinned OpenAI Harmony runtime is unavailable") from exc
        self.harmony = harmony
        self.encoding = harmony.load_harmony_encoding(harmony.HarmonyEncodingName.HARMONY_GPT_OSS)
        self.gemma = GemmaPinnedBPE(gemma_tokenizer)

    def _count_gpt(self, payload: dict[str, Any]) -> int:
        messages = payload.get("messages")
        if not isinstance(messages, list) or len(messages) != 2 or [row.get("role") for row in messages] != ["system", "user"]:
            raise CountError("GPT-OSS payload must contain exactly system and user messages")
        harmony = self.harmony
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
        return len(self.encoding.render_conversation_for_completion(conversation, harmony.Role.ASSISTANT))

    def _count_gemma(self, payload: dict[str, Any]) -> int:
        messages = payload.get("messages")
        if not isinstance(messages, list) or len(messages) != 1 or messages[0].get("role") != "user":
            raise CountError("Gemma payload must contain exactly one user message")
        if payload.get("chat_template_kwargs") != {"enable_thinking": False}:
            raise CountError("Gemma thinking must remain disabled")
        content = messages[0].get("content")
        if not isinstance(content, str):
            raise CountError("Gemma user message is invalid")
        return self.gemma.count(gemma_render_user(content))

    def enforce(self, payload: dict[str, Any]) -> dict[str, Any]:
        model = payload.get("model")
        output = payload.get("max_tokens")
        if not isinstance(output, int) or isinstance(output, bool):
            raise CountError("Output allowance is absent or invalid")
        if model == GPT_MODEL:
            count = self._count_gpt(payload)
            if count > GPT_INPUT_LIMIT or output > GPT_OUTPUT_LIMIT or count + output > GPT_CONTEXT_LIMIT:
                raise CountError("GPT-OSS request exceeds a frozen token or context limit")
            return {
                "model": model,
                "exact_local_input_tokens": count,
                "output_allowance_tokens": output,
                "input_limit_tokens": GPT_INPUT_LIMIT,
                "context_limit_tokens": GPT_CONTEXT_LIMIT,
                "count_method": "OPENAI_HARMONY_0_0_8_PINNED_LOCAL",
                "hosted_format_equivalence": "UNVERIFIED",
            }
        if model == GEMMA_MODEL:
            count = self._count_gemma(payload)
            if count > GEMMA_INPUT_LIMIT or output > GEMMA_OUTPUT_LIMIT or count + output > GEMMA_CONTEXT_LIMIT:
                raise CountError("Gemma request exceeds a frozen token or context limit")
            return {
                "model": model,
                "exact_local_input_tokens": count,
                "output_allowance_tokens": output,
                "input_limit_tokens": GEMMA_INPUT_LIMIT,
                "context_limit_tokens": GEMMA_CONTEXT_LIMIT,
                "count_method": "PINNED_GEMMA_BPE_AND_FROZEN_USER_TEMPLATE",
                "hosted_format_equivalence": "UNVERIFIED",
            }
        raise CountError("Payload model differs from the frozen V08 models")
