#!/usr/bin/env python3
"""Run the fixed-threshold self-contained-evidence DeBERTa comparison."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import pathlib
import platform
import resource
import sys
import time
from typing import Any

from evidence_preparer import evidence_index, prepare_evidence


PUBLIC_LABEL = "EXPERIMENTAL AI VERIFICATION — NOT EDITORIALLY APPROVED — NOT FOR PUBLICATION"
EXPECTED_LABEL_ORDER = ["contradiction", "entailment", "neutral"]


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


def versions() -> dict[str, str]:
    output = {"python": platform.python_version()}
    for package in ["torch", "transformers", "tokenizers", "safetensors", "sentencepiece", "protobuf"]:
        try:
            output[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            output[package] = "NOT_INSTALLED"
    return output


def article_map(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["article_id"]: row for row in data["articles"]}


def selected_rows(article: dict[str, Any], ids: list[str]) -> list[dict[str, Any]]:
    available = evidence_index(article)
    missing = [item for item in ids if item not in available]
    if missing:
        raise ValueError(f"{article['article_id']}: missing evidence IDs {missing}")
    return [available[item] for item in ids]


def compose(rows: list[dict[str, Any]]) -> str:
    return " ".join(row["text"].strip() for row in rows)


def normalize_case(
    claim: dict[str, Any], article: dict[str, Any], group: str, disputed: bool
) -> dict[str, Any]:
    original_ids = list(claim.get("baseline_evidence_ids", claim.get("evidence_ids", [])))
    return {
        "claim_id": claim["claim_id"],
        "group": group,
        "article_id": article["article_id"],
        "source_name": article["source_name"],
        "title": article["title"],
        "source_url": article["url"],
        "category": article["category"],
        "claim": claim["claim"],
        "original_evidence_ids": original_ids,
        "reference_nli_label": claim["reference_nli_label"],
        "reference_safety_verdict": claim["reference_safety_verdict"],
        "reference_reason": claim["reference_reason"],
        "disputed_reference": disputed,
        "article": article,
    }


def build_cases(
    baseline: dict[str, Any], holdout: dict[str, Any], config: dict[str, Any]
) -> list[dict[str, Any]]:
    baseline_articles = article_map(baseline)
    baseline_claims = {row["claim_id"]: row for row in baseline["claims"]}
    holdout_articles = article_map(holdout)
    cases: list[dict[str, Any]] = []
    disputed = set(config["disputed_claim_ids"])
    for claim_id in config["historical_diagnostic_claim_ids"]:
        claim = baseline_claims[claim_id]
        cases.append(normalize_case(claim, baseline_articles[claim["article_id"]], "historical_diagnostic", claim_id in disputed))
    for claim_id in config["control_claim_ids"]:
        claim = baseline_claims[claim_id]
        cases.append(normalize_case(claim, baseline_articles[claim["article_id"]], "controls", claim_id in disputed))
    for claim in holdout["claims"]:
        cases.append(normalize_case(claim, holdout_articles[claim["article_id"]], "new_frozen_holdout", False))
    claim_ids = [row["claim_id"] for row in cases]
    if len(claim_ids) != len(set(claim_ids)):
        raise ValueError("Duplicate claim IDs across comparative groups")
    return cases


def condition_inputs(case: dict[str, Any], condition: str, config: dict[str, Any]) -> dict[str, Any]:
    article = case["article"]
    original_rows = selected_rows(article, case["original_evidence_ids"])
    original_text = compose(original_rows)
    base = {
        "condition": condition,
        "original_evidence_ids": case["original_evidence_ids"],
        "original_text": original_text,
        "preparation_is_automatic": condition == "B",
        "human_prepared_diagnostic_only": condition == "C",
    }
    if condition == "A":
        return {
            **base,
            "preparation_status": "ORIGINAL_BASELINE",
            "prepared_evidence_ids": case["original_evidence_ids"],
            "premise": original_text,
            "added_context": [],
            "unresolved_ambiguity": [],
            "provenance_integrity": True,
        }
    if condition == "B":
        policy = config["preparation_policy"]
        prepared = prepare_evidence(
            article,
            case["claim"],
            case["original_evidence_ids"],
            maximum_added_passages=policy["maximum_added_passages"],
            minimum_candidate_score=policy["minimum_candidate_score"],
        )
        return {
            **base,
            "preparation_status": prepared["status"],
            "prepared_evidence_ids": prepared["prepared_evidence_ids"],
            "premise": prepared["prepared_text"],
            "added_context": prepared["added_context"],
            "unresolved_ambiguity": prepared["unresolved_ambiguity"],
            "provenance_integrity": prepared["provenance_integrity"],
            "claim_text_inserted_as_evidence": prepared.get("claim_text_inserted_as_evidence", False),
        }
    if condition == "C":
        ids = config["human_diagnostic_evidence_ids"][case["claim_id"]]
        rows = selected_rows(article, ids)
        return {
            **base,
            "preparation_status": "HUMAN_DIAGNOSTIC_ONLY",
            "prepared_evidence_ids": ids,
            "premise": compose(rows),
            "added_context": [
                {
                    "evidence_id": row["evidence_id"],
                    "source_locations": list(row.get("source_locations", [])),
                    "status": row.get("status"),
                }
                for row in rows if row["evidence_id"] not in case["original_evidence_ids"]
            ],
            "unresolved_ambiguity": [],
            "provenance_integrity": True,
        }
    raise ValueError(f"Unknown condition: {condition}")


def safety_decision(probabilities: dict[str, float], threshold: float, margin: float) -> str:
    entailment = probabilities["entailment"]
    strongest_other = max(probabilities["contradiction"], probabilities["neutral"])
    if entailment >= threshold and entailment - strongest_other >= margin:
        return "SUPPORTED"
    label = max(EXPECTED_LABEL_ORDER, key=lambda name: probabilities[name])
    if label in {"contradiction", "neutral"}:
        return "FLAG"
    return "UNCERTAIN_REVIEW"


def classify_metric(row: dict[str, Any]) -> str:
    if row["disputed_reference"]:
        return "DISPUTED_EXCLUDED"
    expected = row["reference_safety_verdict"] == "SUPPORTED"
    if row["decision"] == "UNCERTAIN_REVIEW":
        return "SUPPORTED_UNCERTAIN" if expected else "UNSAFE_UNCERTAIN"
    predicted = row["decision"] == "SUPPORTED"
    if expected and predicted:
        return "CORRECT_ACCEPTANCE"
    if expected and not predicted:
        return "FALSE_REJECTION"
    if not expected and predicted:
        return "FALSE_APPROVAL"
    return "CORRECT_FLAG"


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    categories = [
        "CORRECT_ACCEPTANCE", "CORRECT_FLAG", "FALSE_APPROVAL", "FALSE_REJECTION",
        "SUPPORTED_UNCERTAIN", "UNSAFE_UNCERTAIN", "DISPUTED_EXCLUDED",
    ]
    classified = {name: [row["claim_id"] for row in rows if row["metric_class"] == name] for name in categories}
    return {
        "total": len(rows),
        **{f"{name.lower()}_count": len(ids) for name, ids in classified.items()},
        **{f"{name.lower()}_claim_ids": ids for name, ids in classified.items()},
        "uncertain_count": len(classified["SUPPORTED_UNCERTAIN"]) + len(classified["UNSAFE_UNCERTAIN"]),
        "execution_failure_count": sum(row["execution_status"] != "SUCCESS" for row in rows),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    baseline_path = pathlib.Path(args.baseline).resolve()
    holdout_path = pathlib.Path(args.holdout).resolve()
    config_path = pathlib.Path(args.config).resolve()
    manifest_path = pathlib.Path(args.manifest).resolve()
    model_dir = pathlib.Path(args.model_dir).resolve()
    baseline = load_json(baseline_path)
    holdout = load_json(holdout_path)
    config = load_json(config_path)
    manifest = load_json(manifest_path)
    cases = build_cases(baseline, holdout, config)
    settings = config["preserved_model_settings"]

    if args.repetitions != 3 or settings["repetitions"] != 3:
        raise ValueError("Exactly three deterministic repetitions are required")
    if manifest["model_card_label_order"] != EXPECTED_LABEL_ORDER:
        raise ValueError("Unexpected pinned model label order")
    if settings["entailment_threshold"] != 0.5 or settings["entailment_margin"] != 0.3:
        raise ValueError("Fixed historical thresholds changed")
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
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True, trust_remote_code=False)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_dir, local_files_only=True, trust_remote_code=False, use_safetensors=True
    )
    model.eval()
    label_order = [str(model.config.id2label[index]).lower() for index in range(model.config.num_labels)]
    if label_order != EXPECTED_LABEL_ORDER:
        raise ValueError(f"Unexpected model label mapping: {label_order}")
    model_limit = min(int(tokenizer.model_max_length), int(model.config.max_position_embeddings))
    if model_limit != settings["model_input_limit"]:
        raise ValueError(f"Unexpected model input limit: {model_limit}")

    rows: list[dict[str, Any]] = []
    for case in cases:
        conditions = ["A", "B"] + (["C"] if case["group"] == "historical_diagnostic" else [])
        for condition in conditions:
            prepared = condition_inputs(case, condition, config)
            row = {
                key: value for key, value in case.items() if key != "article"
            }
            row.update(prepared)
            row.update({
                "input_order": "premise=evidence; hypothesis=claim",
                "model_input_limit": model_limit,
                "threshold": settings["entailment_threshold"],
                "margin": settings["entailment_margin"],
                "prediction_is_editorial_approval": False,
            })
            if condition == "B" and prepared["preparation_status"] != "SELF_CONTAINED":
                row.update({
                    "execution_status": "NOT_RUN_PREPARATION_UNCERTAIN",
                    "failure_reason": prepared["preparation_status"],
                    "input_tokens": None,
                    "truncated": False,
                    "raw_nli_label": None,
                    "probabilities": None,
                    "repetitions": [],
                    "repeatability": {"passes": 0, "consistent": False},
                    "decision": "UNCERTAIN_REVIEW",
                })
                row["metric_class"] = classify_metric(row)
                rows.append(row)
                continue
            encoded = tokenizer(prepared["premise"], case["claim"], return_tensors="pt", truncation=False)
            token_count = int(encoded["input_ids"].shape[1])
            row["input_tokens"] = token_count
            row["truncated"] = False
            if token_count > model_limit:
                row.update({
                    "execution_status": "NOT_RUN_INPUT_LIMIT",
                    "failure_reason": "EVIDENCE_PAIR_EXCEEDS_MODEL_LIMIT",
                    "raw_nli_label": None,
                    "probabilities": None,
                    "repetitions": [],
                    "repeatability": {"passes": 0, "consistent": False},
                    "decision": "UNCERTAIN_REVIEW",
                })
                row["metric_class"] = classify_metric(row)
                rows.append(row)
                continue
            repetitions = []
            for index in range(args.repetitions):
                infer_started = time.monotonic()
                with torch.no_grad():
                    logits = model(**encoded).logits[0]
                    probability_values = torch.softmax(logits, dim=-1).cpu().tolist()
                repetitions.append({
                    "repetition": index + 1,
                    "logits": [round(float(value), 8) for value in logits.cpu().tolist()],
                    "probabilities": {
                        name: round(float(probability_values[position]), 8)
                        for position, name in enumerate(EXPECTED_LABEL_ORDER)
                    },
                    "duration_seconds": round(time.monotonic() - infer_started, 6),
                })
            first = repetitions[0]["probabilities"]
            max_difference = max(
                abs(repetition["probabilities"][name] - first[name])
                for repetition in repetitions for name in EXPECTED_LABEL_ORDER
            )
            raw_label = max(EXPECTED_LABEL_ORDER, key=lambda name: first[name])
            row.update({
                "execution_status": "SUCCESS",
                "failure_reason": None,
                "raw_nli_label": raw_label,
                "probabilities": first,
                "repetitions": repetitions,
                "repeatability": {
                    "passes": args.repetitions,
                    "max_probability_difference": round(max_difference, 10),
                    "consistent": max_difference <= 1e-7,
                },
                "decision": safety_decision(first, settings["entailment_threshold"], settings["entailment_margin"]),
            })
            row["metric_class"] = classify_metric(row)
            rows.append(row)

    grouped: dict[str, Any] = {}
    for group in ["historical_diagnostic", "controls", "new_frozen_holdout"]:
        grouped[group] = {}
        for condition in ["A", "B", "C"]:
            subset = [row for row in rows if row["group"] == group and row["condition"] == condition]
            if subset:
                grouped[group][condition] = metrics(subset)
    comparisons = []
    by_key = {(row["claim_id"], row["condition"]): row for row in rows}
    for case in cases:
        a = by_key[(case["claim_id"], "A")]
        b = by_key[(case["claim_id"], "B")]
        comparisons.append({
            "claim_id": case["claim_id"],
            "group": case["group"],
            "reference_disputed": case["disputed_reference"],
            "condition_a_decision": a["decision"],
            "condition_b_decision": b["decision"],
            "condition_a_metric_class": a["metric_class"],
            "condition_b_metric_class": b["metric_class"],
            "changed_decision": a["decision"] != b["decision"],
            "corrected_error": a["metric_class"] in {"FALSE_REJECTION", "FALSE_APPROVAL"} and b["metric_class"] in {"CORRECT_ACCEPTANCE", "CORRECT_FLAG"},
            "introduced_error": a["metric_class"] in {"CORRECT_ACCEPTANCE", "CORRECT_FLAG"} and b["metric_class"] in {"FALSE_REJECTION", "FALSE_APPROVAL"},
            "uncertainty_increased": b["decision"] == "UNCERTAIN_REVIEW" and a["decision"] != "UNCERTAIN_REVIEW",
        })

    automatic = [row for row in rows if row["condition"] == "B"]
    holdout_b = grouped["new_frozen_holdout"]["B"]
    holdout_a = grouped["new_frozen_holdout"]["A"]
    repeated = all(
        row["repeatability"]["consistent"]
        for row in rows if row["execution_status"] == "SUCCESS"
    )
    automatic_coverage = sum(row["preparation_status"] == "SELF_CONTAINED" for row in automatic)
    provenance_ok = all(row["provenance_integrity"] for row in automatic)
    no_hypothesis_substitution = all(not row.get("claim_text_inserted_as_evidence", False) for row in automatic)
    confirmed_historical = set(config["confirmed_false_rejection_claim_ids"])
    historical_resolved = sum(
        item["claim_id"] in confirmed_historical and item["corrected_error"]
        for item in comparisons
    )
    better_supported_recognition = (
        holdout_b["correct_acceptance_count"] > holdout_a["correct_acceptance_count"]
        or historical_resolved > 0
    )
    useful_improvement = (
        holdout_b["false_approval_count"] == 0
        and provenance_ok
        and no_hypothesis_substitution
        and repeated
        and automatic_coverage > 0
        and better_supported_recognition
    )
    file_manifest = []
    for entry in manifest["files"]:
        local = model_dir / entry["path"]
        file_manifest.append({
            "path": entry["path"], "sha256": sha256(local), "size_bytes": local.stat().st_size,
            "expected_sha256": entry.get("sha256"),
            "integrity_verified": not entry.get("sha256") or sha256(local) == entry["sha256"],
        })

    return {
        "schema_version": "stories-of-us-self-contained-evidence-result-v01",
        "status": "SUCCESS",
        "public_label": PUBLIC_LABEL,
        "operational_readiness": "NOT_AUTHORISED",
        "automatic_claim_extraction": "NOT_IMPLEMENTED — fixed manually verified atomic claims",
        "model": {
            "id": manifest["model_id"], "revision": manifest["revision"], "license": manifest["license"],
            "format": manifest["selected_format"], "label_order": label_order,
            "effective_input_limit": model_limit, "remote_code_executed": False, "files": file_manifest,
        },
        "fixed_decision_settings": {
            "entailment_threshold": settings["entailment_threshold"],
            "entailment_margin": settings["entailment_margin"],
            "recalibrated": False,
        },
        "runtime": {
            "platform": platform.platform(), "processor_count": os.cpu_count(), "versions": versions(),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "peak_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "model_directory_bytes": sum(path.stat().st_size for path in model_dir.rglob("*") if path.is_file()),
        },
        "frozen_inputs": {
            "baseline_sha256": sha256(baseline_path), "holdout_sha256": sha256(holdout_path),
            "config_sha256": sha256(config_path), "manifest_sha256": sha256(manifest_path),
            "new_holdout_frozen_at_utc": holdout["frozen_at_utc"], "holdout_used_for_tuning": False,
        },
        "metrics": {
            "technical_execution": "PASS" if all(row["execution_status"] in {"SUCCESS", "NOT_RUN_PREPARATION_UNCERTAIN", "NOT_RUN_INPUT_LIMIT"} for row in rows) else "FAIL",
            "comparative_evaluation": "PASS" if useful_improvement else "PARTIAL",
            "editorial_evaluation": "PENDING_INDEPENDENT_REVIEW",
            "repeatability": "PASS" if repeated else "FAIL",
            "automatic_preparation_coverage": {
                "self_contained": automatic_coverage, "total": len(automatic),
                "provenance_integrity": provenance_ok,
                "hypothesis_substitution_detected": not no_hypothesis_substitution,
            },
            "historical_confirmed_false_rejections_resolved": historical_resolved,
            "better_supported_recognition": better_supported_recognition,
            "groups": grouped,
            "historical_confirmed_false_rejections": config["confirmed_false_rejection_claim_ids"],
            "disputed_claim_ids": config["disputed_claim_ids"],
        },
        "comparisons": comparisons,
        "results": rows,
        "limitations": [
            "Atomic claims were fixed manually; complete automatic claim extraction is not demonstrated.",
            "Automatic preparation selects only existing public-safe verified passages; it does not perform semantic coreference generation.",
            "NLI predictions and scores are experimental classifications, not verified facts or publication approval.",
            "A small frozen benchmark cannot establish production reliability.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--holdout", required=True)
    parser.add_argument("--config", required=True)
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
            "holdout_condition_b_false_approvals": payload["metrics"]["groups"]["new_frozen_holdout"]["B"]["false_approval_count"],
        }))
        return 0
    except Exception as exc:
        failure = {
            "schema_version": "stories-of-us-self-contained-evidence-result-v01",
            "status": "FAILURE", "public_label": PUBLIC_LABEL,
            "error_type": type(exc).__name__, "error": str(exc)[:2000],
            "runtime_versions": versions(), "operational_readiness": "NOT_AUTHORISED",
        }
        atomic_write_json(output, failure)
        print(json.dumps({"status": "FAILURE", "error_type": type(exc).__name__, "error": str(exc)[:500]}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
