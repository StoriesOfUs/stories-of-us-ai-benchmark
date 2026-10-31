#!/usr/bin/env python3
"""Run one bounded public-safe Stories Of Us CPU summary benchmark."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import resource
import subprocess
import tempfile
import time


LABEL = "EXPERIMENTAL AI OUTPUT — NOT EDITORIALLY APPROVED — NOT FOR PUBLICATION"
MAX_CAPTURE_CHARACTERS = 16000


def bounded_public_text(text: str, replacements: dict[str, str]) -> tuple[str, bool]:
    """Remove local runner paths and cap diagnostic text retained in a public artifact."""
    for original, replacement in replacements.items():
        text = text.replace(original, replacement)
    text = re.sub(r"/home/runner/(?:work|_work)/[^\s'\"]+", "<RUNNER_PATH>", text)
    text = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", text)
    truncated = len(text) > MAX_CAPTURE_CHARACTERS
    if truncated:
        text = text[:MAX_CAPTURE_CHARACTERS] + "\n[TRUNCATED]"
    return text, truncated


def file_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_prompt(case: dict, model_id: str) -> str:
    qwen_control = "/no_think\n" if model_id.startswith("qwen") else ""
    evidence = "\n".join(f"- {item}" for item in case["evidence"])
    return (qwen_control + f"""Write one Stories Of Us preview summary using only the verified evidence below.
Return only the finished summary. Do not show reasoning, notes, labels or alternatives.

Rules:
- Exactly two succinct sentences, with no more than 50 words combined.
- Sentence one must use the exact source name \"{case['source_name']}\", publication-time present tense, explain the main subject, and make disability and {case['category']} relevance clear.
- Sentence two must add one useful, concrete, non-repetitive detail supported by the evidence.
- Use natural UK English and respectful disability terminology.
- Do not invent facts, outcomes, dates, identities or quotations.
- If the evidence cannot support a compliant summary, output exactly HOLD.

Article title: {case['title']}
Publisher: {case['source_name']}
Publication date: {case['publication_date']}
Category: {case['category']}
Country: {case['country']}
Region: {case['region']}
Disability relevance: {case['disability_relevance']}

Verified evidence:
{evidence}
""").strip()


def cleaned_summary(raw: str) -> tuple[str, bool]:
    thinking = bool(re.search(r"<think>|</think>|\[Start thinking\]|\[End thinking\]|\bAnalysis:\b", raw, flags=re.I))
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.I | re.S)
    text = re.sub(r"\[Start thinking\].*?\[End thinking\]", "", text, flags=re.I | re.S)
    text = re.sub(r"^```(?:text|json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    text = re.sub(r"^(?:assistant|summary)\s*:\s*", "", text.strip(), flags=re.I)
    text = re.sub(r"\n*Exiting\.\.\.\s*$", "", text.strip(), flags=re.I)
    return text.strip(), thinking


def run_one(binary: pathlib.Path, model: pathlib.Path, prompt: str, timeout: int, model_id: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="stories-of-us-llama-") as temporary:
        transcript_path = pathlib.Path(temporary) / "conversation.txt"
        command = [
            str(binary), "-m", str(model), "--single-turn", "--simple-io",
            "--no-display-prompt", "--no-show-timings", "--no-warmup",
            "--seed", "42", "-n", "180", "-c", "4096",
            "--output-file", str(transcript_path),
        ]
        if model_id.startswith("qwen"):
            command.extend(["--jinja", "--temp", "0.7", "--top-k", "20", "--top-p", "0.8", "--min-p", "0", "--presence-penalty", "1.5"])
        else:
            command.extend(["--temp", "0.2"])
        command.extend(["-p", prompt])
        started = time.monotonic()
        replacements = {
            str(binary): "<LLAMA_CLI>", str(model): "<MODEL_FILE>",
            str(transcript_path): "<OUTPUT_FILE>", prompt: "<PROMPT>",
        }
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            console = exc.stdout if isinstance(exc.stdout, str) else ""
            error = exc.stderr if isinstance(exc.stderr, str) else ""
            transcript = transcript_path.read_text(encoding="utf-8") if transcript_path.is_file() else ""
            assistant = transcript.rsplit("Assistant:\n", 1)[-1] if "Assistant:\n" in transcript else ""
            safe_raw, raw_truncated = bounded_public_text(assistant, replacements)
            safe_console, console_truncated = bounded_public_text(console, replacements)
            safe_error, error_truncated = bounded_public_text(error, replacements)
            return {
                "execution_status": "FAILURE",
                "failure_reason": "TIMEOUT",
                "return_code": None,
                "duration_seconds": round(time.monotonic() - started, 3),
                "raw_response_sha256": hashlib.sha256(assistant.encode()).hexdigest(),
                "raw_response": safe_raw,
                "raw_response_truncated": raw_truncated,
                "console_stdout": safe_console,
                "console_stdout_truncated": console_truncated,
                "stderr": safe_error,
                "stderr_truncated": error_truncated,
                "summary": "",
                "output_validation": {
                    "text_present": False,
                    "model_returned_hold": False,
                    "word_count": 0,
                    "maximum_50_words": True,
                    "sentence_count": 0,
                    "exactly_two_sentences": False,
                },
            }
        transcript = transcript_path.read_text(encoding="utf-8") if transcript_path.is_file() else ""
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    assistant = transcript.rsplit("Assistant:\n", 1)[-1] if "Assistant:\n" in transcript else ""
    safe_raw, raw_truncated = bounded_public_text(assistant, replacements)
    safe_console, console_truncated = bounded_public_text(completed.stdout, replacements)
    safe_error, error_truncated = bounded_public_text(completed.stderr, replacements)
    summary, thinking = cleaned_summary(safe_raw)
    execution_status = "SUCCESS" if completed.returncode == 0 and bool(summary) else "FAILURE"
    failure_reason = None
    if completed.returncode != 0:
        failure_reason = "RUNTIME_PROCESS_EXIT"
    elif not summary:
        failure_reason = "NO_OUTPUT_TEXT"
    word_count = len(re.findall(r"\b[\w’'-]+\b", summary))
    sentence_count = len(re.findall(r"[.!?](?:[\"'’)]*)?(?:\s|$)", summary))
    return {
        "execution_status": execution_status,
        "failure_reason": failure_reason,
        "return_code": completed.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "peak_rss_kb_observed": usage_after,
        "raw_response_sha256": hashlib.sha256(assistant.encode()).hexdigest(),
        "raw_response_characters": len(assistant),
        "raw_response": safe_raw,
        "raw_response_truncated": raw_truncated,
        "console_stdout": safe_console,
        "console_stdout_truncated": console_truncated,
        "stderr": safe_error,
        "stderr_truncated": error_truncated,
        "reasoning_markup_detected": thinking,
        "summary": summary,
        "output_validation": {
            "text_present": bool(summary),
            "model_returned_hold": summary.strip().upper() == "HOLD",
            "word_count": word_count,
            "maximum_50_words": word_count <= 50,
            "sentence_count": sentence_count,
            "exactly_two_sentences": sentence_count == 2,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True, type=pathlib.Path)
    parser.add_argument("--model", required=True, type=pathlib.Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--cases", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()

    actual_sha256 = file_sha256(args.model)
    if actual_sha256 != args.expected_sha256:
        raise SystemExit(f"Model checksum mismatch: {actual_sha256}")

    version = subprocess.run([str(args.binary), "--version"], capture_output=True, text=True, timeout=30, check=False)
    runtime_version, runtime_version_truncated = bounded_public_text(
        (version.stdout + "\n" + version.stderr).strip(),
        {str(args.binary): "<LLAMA_CLI>", str(args.model): "<MODEL_FILE>"},
    )
    cases = json.loads(args.cases.read_text(encoding="utf-8"))["cases"]
    results = []
    model_started = time.monotonic()
    for case in cases:
        prompt = build_prompt(case, args.model_id)
        result = run_one(args.binary, args.model, prompt, args.timeout_seconds, args.model_id)
        result.update({
            "case_id": case["case_id"],
            "source_url": case["url"],
            "condition": "v04_verified_evidence_no_curated_examples",
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "prompt_characters": len(prompt),
            "public_label": LABEL,
        })
        result["output_validation"]["exact_source_name_present"] = case["source_name"] in result["summary"]
        results.append(result)

    output = {
        "schema_version": "stories-of-us-public-llm-benchmark-results-v01",
        "public_label": LABEL,
        "model_id": args.model_id,
        "model_sha256": actual_sha256,
        "model_file_bytes": args.model.stat().st_size,
        "runtime": {
            "name": "llama.cpp llama-cli",
            "version_output": runtime_version,
            "version_output_truncated": runtime_version_truncated,
        },
        "runner": "GitHub Actions ubuntu-24.04 standard public-repository runner",
        "condition": "v04_verified_evidence_no_curated_examples",
        "curated_examples_used": False,
        "status": "SUCCESS" if all(row["execution_status"] == "SUCCESS" for row in results) else "FAILURE",
        "total_duration_seconds": round(time.monotonic() - model_started, 3),
        "input_token_counts": None,
        "output_token_counts": None,
        "token_count_note": "The bounded llama-cli path did not expose reliable machine-readable token counts.",
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if output["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
