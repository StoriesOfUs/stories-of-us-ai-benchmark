#!/usr/bin/env python3
"""Run a bounded public-safe Stories Of Us CPU summary benchmark."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import resource
import subprocess
import time


LABEL = "EXPERIMENTAL AI SUMMARY — NOT EDITORIALLY APPROVED — NOT FOR STORIES OF US PUBLICATION"


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
    thinking = bool(re.search(r"<think>|</think>|\bAnalysis:\b", raw, flags=re.I))
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.I | re.S)
    text = re.sub(r"^```(?:text|json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    text = re.sub(r"^(?:assistant|summary)\s*:\s*", "", text.strip(), flags=re.I)
    return text.strip(), thinking


def run_one(binary: pathlib.Path, model: pathlib.Path, prompt: str, timeout: int) -> dict:
    command = [
        str(binary), "-m", str(model), "-cnv", "--simple-io", "--no-display-prompt",
        "--temp", "0.2", "--seed", "42", "-n", "180", "-c", "8192", "-p", prompt,
    ]
    started = time.monotonic()
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raw = exc.stdout if isinstance(exc.stdout, str) else ""
        return {
            "status": "TIMEOUT",
            "duration_seconds": round(time.monotonic() - started, 3),
            "raw_response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "summary": "",
        }
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    summary, thinking = cleaned_summary(completed.stdout)
    return {
        "status": "COMPLETED" if completed.returncode == 0 else "RUNTIME_ERROR",
        "return_code": completed.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "peak_rss_kb_child_delta": max(0, usage_after - usage_before),
        "raw_response_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "raw_response_characters": len(completed.stdout),
        "reasoning_markup_detected": thinking,
        "summary": summary,
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

    cases = json.loads(args.cases.read_text(encoding="utf-8"))["cases"]
    results = []
    model_started = time.monotonic()
    for case in cases:
        prompt = build_prompt(case, args.model_id)
        result = run_one(args.binary, args.model, prompt, args.timeout_seconds)
        result.update({
            "case_id": case["case_id"],
            "source_url": case["url"],
            "condition": "v04_verified_evidence_no_curated_examples",
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "prompt_characters": len(prompt),
            "public_label": LABEL,
        })
        results.append(result)

    output = {
        "schema_version": "stories-of-us-public-llm-benchmark-results-v01",
        "public_label": LABEL,
        "model_id": args.model_id,
        "model_sha256": actual_sha256,
        "model_file_bytes": args.model.stat().st_size,
        "condition": "v04_verified_evidence_no_curated_examples",
        "curated_examples_used": false,
        "total_duration_seconds": round(time.monotonic() - model_started, 3),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if all(row["status"] == "COMPLETED" for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
