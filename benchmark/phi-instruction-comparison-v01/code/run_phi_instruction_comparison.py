#!/usr/bin/env python3
"""Generate the 15 authorised Phi instruction-comparison outputs exactly once."""
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
SET_A_PUNCTUATED_NAMES = {
    "activism_aci_rights_rally": ["Our Pride. Our Power. Our Community"],
}


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


def sentence_counts(text: str, case_id: str) -> tuple[int, int, list[str]]:
    naive = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    protected = text
    corrections: list[str] = []
    for span in SET_A_PUNCTUATED_NAMES.get(case_id, []):
        if span in protected:
            protected = protected.replace(span, span.replace(".", "<DOT>"))
            corrections.append(f"Protected punctuated name: {span}")
    contextual = [part.strip() for part in re.split(r"(?<=[.!?])\s+", protected) if part.strip()]
    return len(naive), len(contextual), corrections


def validation(text: str, source_name: str, case_id: str) -> dict[str, Any]:
    words = re.findall(r"\b[\w£'-]+\b", text, flags=re.UNICODE)
    naive_count, contextual_count, corrections = sentence_counts(text, case_id)
    base = bool(text) and text.startswith(source_name)
    return {
        "nonempty": bool(text),
        "begins_with_exact_source_name": text.startswith(source_name),
        "word_count": len(words),
        "naive_sentence_count": naive_count,
        "contextual_sentence_count": contextual_count,
        "sentence_count_corrections": corrections,
        "existing_v04_mechanical": {
            "within_50_words": len(words) <= 50,
            "exactly_two_sentences": contextual_count == 2,
            "mechanical_structure_pass": base and len(words) <= 50 and contextual_count == 2,
        },
        "experimental_specification_mechanical": {
            "within_70_words": len(words) <= 70,
            "normally_two_or_three_sentences": contextual_count in (2, 3),
            "mechanical_structure_pass": base and len(words) <= 70 and contextual_count in (2, 3),
            "about_50_words_is_preference_not_threshold": True,
        },
        "editorial_acceptance": "NOT_ASSESSED_BY_DETERMINISTIC_VALIDATION",
    }


def run_one(binary: pathlib.Path, model: pathlib.Path, prompt: str, *, timeout: int,
            seed: int, temperature: float, max_tokens: int, context_size: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="stories-of-us-phi-instruction-") as temporary:
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
    parser.add_argument("--instructions", required=True)
    parser.add_argument("--set-a-packets", required=True)
    parser.add_argument("--set-b-packets", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=240)
    args = parser.parse_args()
    model_manifest_path = pathlib.Path(args.model_manifest)
    instructions_path = pathlib.Path(args.instructions)
    set_a_path = pathlib.Path(args.set_a_packets)
    set_b_path = pathlib.Path(args.set_b_packets)
    model_manifest = load_json(model_manifest_path)
    instructions = load_json(instructions_path)
    set_a = load_json(set_a_path)
    set_b = load_json(set_b_path)
    model = model_manifest["model"]
    model_path = pathlib.Path(args.model_file)
    actual_hash = sha256(model_path)
    if actual_hash != model["sha256"]:
        raise ValueError(f"Model SHA-256 mismatch: {actual_hash}")
    settings = {"seed": 42, "temperature": 0.2, "top_k": 20, "top_p": 0.8, "min_p": 0,
                "max_output_tokens": 128, "context_size": 4096}
    plan: list[tuple[str, dict[str, Any], str, str]] = []
    for case in set_a["cases"]:
        plan.append(("A_FAMILIAR", case, "REVISED", instructions["revised_instruction"]))
    for case in set_b["cases"]:
        plan.append(("B_NEW", case, "OLD", instructions["old_instruction"]))
        plan.append(("B_NEW", case, "REVISED", instructions["revised_instruction"]))
    if len(plan) != 15:
        raise ValueError(f"Expected exactly 15 new output slots, found {len(plan)}")
    results = []
    overall_started = time.monotonic()
    for set_id, case, condition, instruction in plan:
        packet_text = render_packet(case)
        prompt = instruction + "\n\nVERIFIED ARTICLE EVIDENCE\n" + packet_text
        result = run_one(
            pathlib.Path(args.llama_binary), model_path, prompt,
            timeout=args.timeout_seconds, seed=settings["seed"], temperature=settings["temperature"],
            max_tokens=settings["max_output_tokens"], context_size=settings["context_size"],
        )
        result.update({
            "set_id": set_id,
            "case_id": case["case_id"],
            "category": case["category"],
            "source_name": case["source_name"],
            "condition": condition,
            "model_key": "PHI",
            "model_display_name": model["display_name"],
            "instruction_sha256": hashlib.sha256(instruction.encode()).hexdigest(),
            "semantic_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "runtime_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "input_packet_sha256": hashlib.sha256(packet_text.encode()).hexdigest(),
            "compatibility_prefix": "NONE",
            "deterministic_validation": validation(result.get("text", ""), case["source_name"], case["case_id"]),
        })
        results.append(result)
    payload = {
        "schema_version": "stories-of-us-phi-instruction-comparison-results-v01",
        "public_label": PUBLIC_LABEL,
        "model": model,
        "model_file_sha256_verified": actual_hash,
        "llama_cpp_revision": model_manifest["llama_cpp_revision"],
        "settings": settings,
        "instructions": {
            "old_sha256": hashlib.sha256(instructions["old_instruction"].encode()).hexdigest(),
            "revised_sha256": hashlib.sha256(instructions["revised_instruction"].encode()).hexdigest(),
        },
        "input_files": {
            "instructions_sha256": sha256(instructions_path),
            "set_a_packets_sha256": sha256(set_a_path),
            "set_b_packets_sha256": sha256(set_b_path),
            "model_manifest_sha256": sha256(model_manifest_path),
        },
        "planned_new_outputs": 15,
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
