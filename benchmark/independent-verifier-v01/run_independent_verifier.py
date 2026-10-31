#!/usr/bin/env python3
"""Run the frozen Stories Of Us independent NLI claim-verifier benchmark."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import pathlib
import platform
import resource
import sys
import time
from typing import Any


PUBLIC_LABEL = "EXPERIMENTAL VERIFICATION RESULT — NOT EDITORIALLY APPROVED — NOT FOR PUBLICATION"
EXPECTED_LABEL_ORDER = ["contradiction", "entailment", "neutral"]
DEVELOPMENT_GROUPS = {"known_historical_failures", "known_supported_controls"}
HOLDOUT_GROUP = "frozen_unseen_holdout"
ENTAILMENT_THRESHOLDS = [0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 0.98]
ENTAILMENT_MARGINS = [0.00, 0.05, 0.10, 0.15, 0.20, 0.30]


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def article_map(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {article["article_id"]: article for article in data["articles"]}


def evidence_map(article: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {row["evidence_id"]: row for row in article["evidence"]}


def compose_premise(claim: dict[str, Any], articles: dict[str, dict[str, Any]]) -> tuple[str, list[dict[str, str]]]:
    article = articles[claim["article_id"]]
    available = evidence_map(article)
    selected: list[dict[str, str]] = []
    for evidence_id in claim["evidence_ids"]:
        if evidence_id not in available:
            raise ValueError(f"{claim['claim_id']}: missing evidence {evidence_id}")
        selected.append(available[evidence_id])
    premise = " ".join(row["text"].strip() for row in selected)
    return premise, selected


def safety_decision(probabilities: dict[str, float], threshold: float, margin: float) -> str:
    entailment = probabilities["entailment"]
    strongest_other = max(probabilities["contradiction"], probabilities["neutral"])
    if entailment >= threshold and entailment - strongest_other >= margin:
        return "SUPPORTED"
    label = max(EXPECTED_LABEL_ORDER, key=lambda name: probabilities[name])
    if label == "contradiction":
        return "CONTRADICTED"
    if label == "neutral":
        return "NOT_ESTABLISHED"
    return "REQUIRES_EDITORIAL_REVIEW"


def score_threshold(rows: list[dict[str, Any]], threshold: float, margin: float) -> dict[str, Any]:
    false_passes = 0
    false_rejections = 0
    correct_safety = 0
    correct_raw_labels = 0
    for row in rows:
        decision = safety_decision(row["probabilities"], threshold, margin)
        expected_supported = row["reference_safety_verdict"] == "SUPPORTED"
        predicted_supported = decision == "SUPPORTED"
        false_passes += int(not expected_supported and predicted_supported)
        false_rejections += int(expected_supported and not predicted_supported)
        correct_safety += int(expected_supported == predicted_supported)
        correct_raw_labels += int(row["raw_nli_label"] == row["reference_nli_label"])
    return {
        "entailment_threshold": threshold,
        "entailment_margin": margin,
        "false_passes": false_passes,
        "false_rejections": false_rejections,
        "correct_safety": correct_safety,
        "correct_raw_labels": correct_raw_labels,
        "cases": len(rows),
    }


def calibrate(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidates = [score_threshold(rows, threshold, margin)
                  for threshold in ENTAILMENT_THRESHOLDS for margin in ENTAILMENT_MARGINS]
    candidates.sort(key=lambda item: (
        item["false_passes"],
        item["false_rejections"],
        -item["correct_safety"],
        -item["correct_raw_labels"],
        -item["entailment_threshold"],
        -item["entailment_margin"],
    ))
    selected = dict(candidates[0])
    selected["selection_rule"] = (
        "Development data only: minimise unsafe false passes first, then supported false rejections, "
        "then maximise correct safety and raw-label decisions; conservative thresholds break ties."
    )
    return selected, candidates


def group_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    false_passes: list[str] = []
    false_rejections: list[str] = []
    correct_flags: list[str] = []
    correct_acceptances: list[str] = []
    uncertain: list[str] = []
    raw_correct: list[str] = []
    for row in rows:
        expected_supported = row["reference_safety_verdict"] == "SUPPORTED"
        predicted_supported = row["decision"] == "SUPPORTED"
        if not expected_supported and predicted_supported:
            false_passes.append(row["claim_id"])
        elif expected_supported and not predicted_supported:
            false_rejections.append(row["claim_id"])
        elif expected_supported:
            correct_acceptances.append(row["claim_id"])
        else:
            correct_flags.append(row["claim_id"])
        if row["decision"] in {"NOT_ESTABLISHED", "REQUIRES_EDITORIAL_REVIEW"}:
            uncertain.append(row["claim_id"])
        if row["raw_nli_label"] == row["reference_nli_label"]:
            raw_correct.append(row["claim_id"])
    return {
        "total": len(rows),
        "false_pass_count": len(false_passes),
        "false_pass_claim_ids": false_passes,
        "false_rejection_count": len(false_rejections),
        "false_rejection_claim_ids": false_rejections,
        "correct_flag_count": len(correct_flags),
        "correct_flag_claim_ids": correct_flags,
        "correct_acceptance_count": len(correct_acceptances),
        "correct_acceptance_claim_ids": correct_acceptances,
        "uncertain_count": len(uncertain),
        "uncertain_claim_ids": uncertain,
        "raw_nli_label_correct": len(raw_correct),
        "raw_nli_label_accuracy": round(len(raw_correct) / len(rows), 4) if rows else None,
    }


def known_case_detection(rows: list[dict[str, Any]], data: dict[str, Any]) -> dict[str, Any]:
    by_claim = {row["claim_id"]: row for row in rows}
    cases = []
    for historical in data["historical_summaries"]:
        unsafe = historical["unsafe_claim_ids"]
        if not unsafe:
            continue
        missing = [claim_id for claim_id in unsafe if claim_id not in by_claim]
        accepted = [claim_id for claim_id in unsafe if claim_id in by_claim and by_claim[claim_id]["decision"] == "SUPPORTED"]
        cases.append({
            "historical_case_id": historical["historical_case_id"],
            "prior_output_id": historical["prior_output_id"],
            "unsafe_claim_ids": unsafe,
            "missing_claim_ids": missing,
            "unsafe_claims_incorrectly_accepted": accepted,
            "case_flagged": not missing and not accepted,
        })
    return {
        "known_false_pass_cases": len(cases),
        "cases_flagged": sum(1 for row in cases if row["case_flagged"]),
        "all_five_flagged": len(cases) == 5 and all(row["case_flagged"] for row in cases),
        "cases": cases,
    }


def package_versions() -> dict[str, str]:
    versions = {"python": platform.python_version()}
    for package in ["torch", "transformers", "tokenizers", "safetensors", "sentencepiece"]:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "NOT_INSTALLED"
    return versions


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    cases_path = pathlib.Path(args.cases).resolve()
    manifest_path = pathlib.Path(args.manifest).resolve()
    model_dir = pathlib.Path(args.model_dir).resolve()
    data = load_json(cases_path)
    manifest = load_json(manifest_path)
    articles = article_map(data)

    if args.repetitions != 3:
        raise ValueError("This frozen benchmark requires exactly three repeatability passes.")
    if manifest["model_card_label_order"] != EXPECTED_LABEL_ORDER:
        raise ValueError("Frozen model-card label order does not match the expected mapping.")

    for entry in manifest["files"]:
        local = model_dir / entry["path"]
        if not local.is_file():
            raise FileNotFoundError(f"Model file missing: {entry['path']}")
        if entry.get("sha256") and sha256(local) != entry["sha256"]:
            raise ValueError(f"SHA-256 mismatch for {entry['path']}")

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    torch.manual_seed(42)
    torch.set_num_threads(max(1, min(2, os.cpu_count() or 1)))
    torch.use_deterministic_algorithms(True)
    tokenizer = AutoTokenizer.from_pretrained(
        model_dir,
        local_files_only=True,
        trust_remote_code=False,
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        model_dir,
        local_files_only=True,
        trust_remote_code=False,
        use_safetensors=True,
    )
    model.eval()

    actual_mapping = [str(model.config.id2label[index]).lower() for index in range(model.config.num_labels)]
    if actual_mapping != EXPECTED_LABEL_ORDER:
        raise ValueError(f"Unexpected model label mapping: {actual_mapping}")
    model_limit = min(int(tokenizer.model_max_length), int(model.config.max_position_embeddings))
    if model_limit != int(manifest["max_position_embeddings"]):
        raise ValueError(f"Unexpected effective input limit: {model_limit}")

    results: list[dict[str, Any]] = []
    for claim in data["claims"]:
        premise, selected_evidence = compose_premise(claim, articles)
        encoded = tokenizer(premise, claim["claim"], return_tensors="pt", truncation=False)
        token_count = int(encoded["input_ids"].shape[1])
        row: dict[str, Any] = {
            "claim_id": claim["claim_id"],
            "group": claim["group"],
            "historical_case_id": claim.get("historical_case_id"),
            "article_id": claim["article_id"],
            "category": articles[claim["article_id"]]["category"],
            "source_name": articles[claim["article_id"]]["source_name"],
            "source_url": articles[claim["article_id"]]["url"],
            "evidence_ids": claim["evidence_ids"],
            "evidence_statuses": [item["status"] for item in selected_evidence],
            "premise": premise,
            "hypothesis": claim["claim"],
            "input_order": "premise=evidence; hypothesis=claim",
            "input_tokens": token_count,
            "model_input_limit": model_limit,
            "truncated": False,
            "reference_nli_label": claim["reference_nli_label"],
            "reference_safety_verdict": claim["reference_safety_verdict"],
            "reference_reason": claim["reference_reason"],
        }
        if token_count > model_limit:
            row.update({
                "execution_status": "REVIEW_REQUIRED",
                "failure_reason": "EVIDENCE_PAIR_EXCEEDS_MODEL_LIMIT",
                "raw_nli_label": None,
                "probabilities": None,
                "repeatability": {"passes": 0, "consistent": False},
            })
            results.append(row)
            continue

        repetitions: list[dict[str, Any]] = []
        for repetition in range(args.repetitions):
            infer_started = time.monotonic()
            with torch.no_grad():
                logits = model(**encoded).logits[0]
                probabilities = torch.softmax(logits, dim=-1).cpu().tolist()
            repetitions.append({
                "repetition": repetition + 1,
                "logits": [round(float(value), 8) for value in logits.cpu().tolist()],
                "probabilities": {
                    name: round(float(probabilities[index]), 8)
                    for index, name in enumerate(EXPECTED_LABEL_ORDER)
                },
                "duration_seconds": round(time.monotonic() - infer_started, 6),
            })
        first = repetitions[0]["probabilities"]
        raw_label = max(EXPECTED_LABEL_ORDER, key=lambda name: first[name])
        max_probability_difference = max(
            abs(run_row["probabilities"][name] - first[name])
            for run_row in repetitions for name in EXPECTED_LABEL_ORDER
        )
        row.update({
            "execution_status": "SUCCESS",
            "failure_reason": None,
            "raw_nli_label": raw_label,
            "probabilities": first,
            "repetitions": repetitions,
            "repeatability": {
                "passes": args.repetitions,
                "max_probability_difference": round(max_probability_difference, 10),
                "consistent": max_probability_difference <= 1e-7,
            },
        })
        results.append(row)

    successful = [row for row in results if row["execution_status"] == "SUCCESS"]
    failed = [row for row in results if row["execution_status"] != "SUCCESS"]
    development = [row for row in successful if row["group"] in DEVELOPMENT_GROUPS]
    calibration, calibration_grid = calibrate(development)
    for row in successful:
        row["decision"] = safety_decision(
            row["probabilities"],
            calibration["entailment_threshold"],
            calibration["entailment_margin"],
        )
        row["prediction_is_editorial_approval"] = False
    for row in failed:
        row["decision"] = "REQUIRES_EDITORIAL_REVIEW"
        row["prediction_is_editorial_approval"] = False

    grouped = {
        group: group_metrics([row for row in results if row["group"] == group])
        for group in ["known_historical_failures", "known_supported_controls", HOLDOUT_GROUP]
    }
    holdout = grouped[HOLDOUT_GROUP]
    known = known_case_detection(results, data)
    repeated = all(row.get("repeatability", {}).get("consistent") for row in successful) and not failed
    claim_verification_preliminary_pass = (
        known["all_five_flagged"]
        and grouped["known_supported_controls"]["correct_acceptance_count"] >= 2
        and holdout["false_pass_count"] == 0
        and not failed
        and repeated
    )

    file_manifest = []
    for entry in manifest["files"]:
        local = model_dir / entry["path"]
        file_manifest.append({
            "path": entry["path"],
            "sha256": sha256(local),
            "size_bytes": local.stat().st_size,
            "expected_sha256": entry.get("sha256"),
            "integrity_verified": not entry.get("sha256") or sha256(local) == entry["sha256"],
        })

    return {
        "schema_version": "stories-of-us-independent-evidence-verifier-result-v01",
        "status": "SUCCESS",
        "public_label": PUBLIC_LABEL,
        "operational_readiness": "NOT_AUTHORISED",
        "automatic_claim_extraction": "NOT_IMPLEMENTED — manually verified atomic claim inventories used",
        "model": {
            "id": manifest["model_id"],
            "revision": manifest["revision"],
            "license": manifest["license"],
            "format": manifest["selected_format"],
            "label_order": actual_mapping,
            "effective_input_limit": model_limit,
            "remote_code_executed": False,
            "files": file_manifest,
        },
        "runtime": {
            "platform": platform.platform(),
            "processor_count": os.cpu_count(),
            "versions": package_versions(),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "peak_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "model_directory_bytes": sum(path.stat().st_size for path in model_dir.rglob("*") if path.is_file()),
        },
        "frozen_inputs": {
            "cases_sha256": sha256(cases_path),
            "manifest_sha256": sha256(manifest_path),
            "frozen_at_utc": data["frozen_at_utc"],
            "holdout_used_for_calibration": False,
            "complete_articles_uploaded": False,
            "protected_curated_records_uploaded": False,
        },
        "calibration": calibration,
        "calibration_grid": calibration_grid,
        "metrics": {
            "technical_execution": "PASS" if not failed else "PARTIAL",
            "claim_verification": "PASS_EXPERIMENTALLY" if claim_verification_preliminary_pass else "PARTIAL",
            "editorial_evaluation": "PENDING_INDEPENDENT_REVIEW",
            "reproducibility": "PASS" if repeated else "FAIL",
            "groups": grouped,
            "known_false_pass_case_detection": known,
        },
        "results": results,
        "limitations": [
            "NLI predictions are model classifications, not verified facts or publication approval.",
            "Confidence scores are not calibrated probabilities of factual correctness.",
            "Manual atomic claim inventories avoid silent omissions in this benchmark; automatic extraction is not implemented.",
            "The model was trained on general NLI data rather than Stories Of Us editorial verification.",
            "Style, terminology, omissions and wider editorial quality remain outside an NLI verdict.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    output = pathlib.Path(args.output).resolve()
    try:
        payload = run(args)
        atomic_write_json(output, payload)
        print(json.dumps({
            "status": payload["status"],
            "technical_execution": payload["metrics"]["technical_execution"],
            "claim_verification": payload["metrics"]["claim_verification"],
            "holdout_false_passes": payload["metrics"]["groups"][HOLDOUT_GROUP]["false_pass_count"],
        }))
        return 0
    except Exception as exc:  # Preserve bounded failure evidence for GitHub artifacts.
        failure = {
            "schema_version": "stories-of-us-independent-evidence-verifier-result-v01",
            "status": "FAILURE",
            "public_label": PUBLIC_LABEL,
            "error_type": type(exc).__name__,
            "error": str(exc)[:2000],
            "runtime_versions": package_versions(),
            "operational_readiness": "NOT_AUTHORISED",
        }
        atomic_write_json(output, failure)
        print(json.dumps({"status": "FAILURE", "error_type": type(exc).__name__, "error": str(exc)[:500]}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
