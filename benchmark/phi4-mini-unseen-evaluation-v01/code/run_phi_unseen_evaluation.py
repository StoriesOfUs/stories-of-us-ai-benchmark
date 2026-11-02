#!/usr/bin/env python3
"""Generate exactly five bounded Phi summaries from frozen unseen packets."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import platform
import re
import resource
import subprocess
import tempfile
import time
from typing import Any


PUBLIC_LABEL = "EXPERIMENTAL AI OUTPUT — NOT EDITORIALLY APPROVED — NOT FOR PUBLICATION"
MAX_CAPTURE = 20000


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def bounded(value: str) -> tuple[str, bool]:
    value = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", value)
    truncated = len(value) > MAX_CAPTURE
    return (value[:MAX_CAPTURE] + "\n[TRUNCATED]" if truncated else value), truncated


def clean_response(value: str) -> tuple[str, bool]:
    thinking = bool(re.search(r"<think>|</think>|\[Start thinking\]|\[End thinking\]", value, re.I))
    value = re.sub(r"<think>.*?</think>", "", value, flags=re.I | re.S)
    value = re.sub(r"\[Start thinking\].*?\[End thinking\]", "", value, flags=re.I | re.S)
    value = re.sub(r"^```(?:text)?\s*|\s*```$", "", value.strip(), flags=re.I)
    value = re.sub(r"^(?:assistant|summary)\s*:\s*", "", value.strip(), flags=re.I)
    value = re.sub(r"\n*Exiting\.\.\.\s*$", "", value.strip(), flags=re.I)
    return value.strip(), thinking


def render_packet(case: dict[str, Any]) -> str:
    facts = []
    for index, fact in enumerate(case["two_verified_facts"], 1):
        facts.append(
            f"VERIFIED FACT {index}: {fact['statement']}\n"
            f"ACTOR: {fact['actor']}\n"
            f"FACTUAL STATUS: {', '.join(fact['factual_status'])}\n"
            f"QUALIFICATION: {'; '.join(fact['qualifications'])}\n"
            f"EVIDENCE REFERENCES: {', '.join(fact['evidence_refs'])}"
        )
    evidence = "\n".join(
        f"- [{row['evidence_id']}] {row['text']} ({row['source_location']})"
        for row in case["concise_supporting_evidence"]
    )
    qualifications = "\n".join(f"- {item}" for item in case["relevant_qualifications"])
    return (
        f"SOURCE_NAME: {case['source_name']}\n"
        f"ORIGINAL ARTICLE TITLE: {case['article_title']}\n"
        f"ORIGINAL SOURCE URL: {case['source_url']}\n"
        f"ARTICLE PUBLICATION DATE: {case['publication_date']}\n"
        f"ASSIGNED CATEGORY: {case['category']}\n"
        f"COUNTRY: {case['country']}\n"
        f"REGION: {case['region']}\n\n"
        + "\n\n".join(facts)
        + f"\n\nACTOR AND COLLABORATOR IDENTITY: {case['actor_and_collaborator_identity']}\n"
        f"DISABILITY RELEVANCE: {case['disability_relevance']}\n"
        f"CATEGORY RELEVANCE: {case['category_relevance']}\n"
        f"RELEVANT QUALIFICATIONS:\n{qualifications}\n"
        f"CONCISE SUPPORTING SOURCE EVIDENCE:\n{evidence}"
    )


def validation(text: str, source_name: str) -> dict[str, Any]:
    words = re.findall(r"\b[\w£'-]+\b", text, flags=re.UNICODE)
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    return {
        "nonempty": bool(text),
        "begins_with_exact_source_name": text.startswith(source_name),
        "word_count": len(words),
        "within_50_words": len(words) <= 50,
        "sentence_count": len(sentences),
        "exactly_two_sentences": len(sentences) == 2,
        "deterministic_structure_pass": bool(text) and text.startswith(source_name) and len(words) <= 50 and len(sentences) == 2,
        "editorial_acceptance": "NOT_ASSESSED_BY_DETERMINISTIC_VALIDATION",
    }


def run_one(binary: pathlib.Path, model: pathlib.Path, prompt: str, *, timeout: int,
            seed: int, temperature: float, max_tokens: int, context_size: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="stories-of-us-simple-model-") as temporary:
        output = pathlib.Path(temporary) / "conversation.txt"
        command = [
            str(binary), "-m", str(model), "--single-turn", "--simple-io",
            "--no-display-prompt", "--no-show-timings", "--no-warmup", "--jinja",
            "--seed", str(seed), "-n", str(max_tokens), "-c", str(context_size),
            "--temp", str(temperature), "--top-k", "20", "--top-p", "0.8",
            "--min-p", "0", "--output-file", str(output), "-p", prompt,
        ]
        started = time.monotonic()
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            return {
                "execution_status": "FAILURE", "failure_reason": "TIMEOUT", "return_code": None,
                "duration_seconds": round(time.monotonic() - started, 3), "text": "",
                "stdout": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
                "stderr": (exc.stderr or "") if isinstance(exc.stderr, str) else "",
            }
        transcript = output.read_text(encoding="utf-8") if output.is_file() else ""
    assistant = transcript.rsplit("Assistant:\n", 1)[-1] if "Assistant:\n" in transcript else transcript
    raw, raw_truncated = bounded(assistant)
    stdout, stdout_truncated = bounded(completed.stdout)
    stderr, stderr_truncated = bounded(completed.stderr)
    text, reasoning = clean_response(raw)
    status = "SUCCESS" if completed.returncode == 0 and bool(text) else "FAILURE"
    return {
        "execution_status": status,
        "failure_reason": None if status == "SUCCESS" else ("RUNTIME_PROCESS_EXIT" if completed.returncode else "NO_OUTPUT_TEXT"),
        "return_code": completed.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "peak_rss_kb_observed": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        "raw_response": raw,
        "raw_response_sha256": hashlib.sha256(assistant.encode()).hexdigest(),
        "raw_response_truncated": raw_truncated,
        "stdout": stdout,
        "stdout_truncated": stdout_truncated,
        "stderr": stderr,
        "stderr_truncated": stderr_truncated,
        "reasoning_markup_detected": reasoning,
        "text": text,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llama-binary", required=True)
    parser.add_argument("--model-file", required=True)
    parser.add_argument("--model-manifest", required=True)
    parser.add_argument("--packets", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=240)
    args = parser.parse_args()
    model_manifest_path = pathlib.Path(args.model_manifest)
    packets_path = pathlib.Path(args.packets)
    model_manifest = load_json(model_manifest_path)
    packets = load_json(packets_path)
    model = model_manifest["model"]
    model_path = pathlib.Path(args.model_file)
    actual_hash = sha256(model_path)
    if actual_hash != model["sha256"]:
        raise ValueError(f"Model SHA-256 mismatch: {actual_hash}")
    settings = {"seed": 42, "temperature": 0.2, "top_k": 20, "top_p": 0.8, "min_p": 0,
                "max_output_tokens": 128, "context_size": 4096}
    results = []
    overall_started = time.monotonic()
    for case in packets["cases"]:
        semantic_prompt = packets["writing_instruction"] + "\n\nVERIFIED ARTICLE EVIDENCE\n" + render_packet(case)
        compatibility_prefix = ""
        runtime_prompt = semantic_prompt
        result = run_one(
            pathlib.Path(args.llama_binary), model_path, runtime_prompt,
            timeout=args.timeout_seconds, seed=settings["seed"], temperature=settings["temperature"],
            max_tokens=settings["max_output_tokens"], context_size=settings["context_size"],
        )
        result.update({
            "case_id": case["case_id"], "source_name": case["source_name"],
            "model_key": "PHI", "model_display_name": model["display_name"],
            "semantic_prompt_sha256": hashlib.sha256(semantic_prompt.encode()).hexdigest(),
            "runtime_prompt_sha256": hashlib.sha256(runtime_prompt.encode()).hexdigest(),
            "input_packet_sha256": hashlib.sha256(render_packet(case).encode()).hexdigest(),
            "compatibility_prefix": compatibility_prefix.strip() or "NONE",
            "deterministic_validation": validation(result.get("text", ""), case["source_name"]),
        })
        results.append(result)
    payload = {
        "schema_version": "stories-of-us-phi4-mini-unseen-evaluation-model-result-v01",
        "public_label": PUBLIC_LABEL,
        "model": model,
        "model_file_sha256_verified": actual_hash,
        "llama_cpp_revision": model_manifest["llama_cpp_revision"],
        "settings": settings,
        "semantic_instruction": packets["writing_instruction"],
        "semantic_instruction_sha256": hashlib.sha256(packets["writing_instruction"].encode()).hexdigest(),
        "packets_file_sha256": sha256(packets_path),
        "model_manifest_file_sha256": sha256(model_manifest_path),
        "expected_chat_template": model["chat_template"],
        "chat_template_mode": "GGUF_EMBEDDED_JINJA",
        "runner": platform.platform(),
        "elapsed_seconds": round(time.monotonic() - overall_started, 3),
        "results": results,
    }
    target = pathlib.Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if all(row["execution_status"] == "SUCCESS" for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
