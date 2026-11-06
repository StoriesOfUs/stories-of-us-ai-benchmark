#!/usr/bin/env python3
"""Execution-locked HHEM/MiniCheck comparison runner.

Imports of ML libraries occur only after the separate authority and one-use
lock checks. Offline preflight uses only the Python standard library.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gc
import importlib.metadata
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "code"
FIXTURES = ROOT / "fixtures"
OUTPUTS = ROOT / "outputs"
GENUINE = OUTPUTS / "genuine_model"
MANIFEST = FIXTURES / "freeze_manifest_v01.json"
AUTHORITY = FIXTURES / "execution_authority_APPROVED_v01.json"
LOCK = OUTPUTS / "execution_consumed_lock_v01.json"
LEDGER = OUTPUTS / "execution_ledger_v01.json"
SUMMARY = OUTPUTS / "execution_summary_v01.json"

sys.path.insert(0, str(CODE))
import dedicated_checker_contract_v01 as contract  # noqa: E402


class SafetyStop(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    return contract.load_json(path)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_case_material() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[str], list[str]]:
    development = load_json(FIXTURES / "development_cases_model_facing_frozen_v01.json")
    evaluation = load_json(FIXTURES / "evaluation_cases_model_facing_frozen_v01.json")
    development_key = load_json(FIXTURES / "development_answer_key_frozen_v01.json")
    evaluation_key = load_json(FIXTURES / "evaluation_answer_key_frozen_v01.json")
    cases = contract.cases_by_id([development, evaluation])
    keys = contract.keys_by_id([development_key, evaluation_key])
    contract.validate_case_key_membership(cases, keys)
    dev_ids = [row["case_id"] for row in development["cases"]]
    eval_ids = [row["case_id"] for row in evaluation["cases"]]
    return cases, keys, dev_ids, eval_ids


def freeze_hash() -> str:
    if not MANIFEST.is_file():
        raise SafetyStop("freeze manifest absent")
    return contract.sha256_file(MANIFEST)


def verify_freeze() -> int:
    manifest = load_json(MANIFEST)
    checked = 0
    for relative, expected in manifest["frozen_files"].items():
        path = ROOT / relative
        if not path.is_file() or contract.sha256_file(path) != expected:
            raise SafetyStop(f"frozen file mismatch: {relative}")
        checked += 1
    return checked


def direct_dependency_versions() -> dict[str, str]:
    required = {
        "torch": "2.15.0",
        "transformers": "5.22.0",
        "huggingface-hub": "2.4.0",
        "safetensors": "0.8.0",
        "sentencepiece": "0.2.1",
        "psutil": "7.2.2",
    }
    actual: dict[str, str] = {}
    for name, expected in required.items():
        try:
            actual[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as error:
            raise SafetyStop(f"required dependency absent: {name}") from error
        if actual[name] != expected:
            raise SafetyStop(f"dependency version mismatch: {name} {actual[name]} != {expected}")
    return actual


def require_live_authority() -> dict[str, Any]:
    if not AUTHORITY.is_file():
        raise SafetyStop("execution remains locked: approved authority file absent")
    if not LOCK.is_file():
        raise SafetyStop("one-use lock was not consumed before installation")
    authority = load_json(AUTHORITY)
    required = (
        "execution_authorised",
        "owner_approved_installation",
        "owner_approved_model_and_tokenizer_downloads",
        "owner_approved_bounded_inference",
        "owner_approved_public_github_workflow_commit_and_single_dispatch",
        "owner_confirmed_standard_public_runner_eligible_and_zero_cost",
    )
    if not all(authority.get(key) is True for key in required):
        raise SafetyStop("execution authority is incomplete")
    if authority.get("approved_freeze_manifest_sha256") != freeze_hash():
        raise SafetyStop("approved freeze hash mismatch")
    lock = load_json(LOCK)
    if lock.get("status") != "CONSUMED_RESERVED_BEFORE_INSTALLATION":
        raise SafetyStop("invalid or already completed one-use lock")
    if lock.get("freeze_manifest_sha256") != freeze_hash():
        raise SafetyStop("one-use lock freeze mismatch")
    return authority


def elapsed_seconds() -> float:
    lock = load_json(LOCK)
    started = dt.datetime.fromisoformat(lock["created_at_utc"])
    return (dt.datetime.now(dt.timezone.utc) - started).total_seconds()


def directory_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def peak_rss_bytes() -> int:
    import psutil
    return int(psutil.Process(os.getpid()).memory_info().rss)


def resource_check(cache_dir: Path, environment_dir: Path | None = None) -> dict[str, Any]:
    limits = load_json(FIXTURES / "resource_limits_frozen_v01.json")
    if elapsed_seconds() > limits["elapsed"]["maximum_minutes"] * 60:
        raise SafetyStop("45-minute elapsed cap reached")
    rss = peak_rss_bytes()
    if rss > limits["memory"]["maximum_peak_task_rss_gb"] * 1_000_000_000:
        raise SafetyStop("12 GB task RSS cap reached")
    cache_size = directory_bytes(cache_dir)
    if cache_size > int(limits["storage"]["model_and_tokenizer_download_maximum_gb"] * 1_000_000_000):
        raise SafetyStop("4.0 GB model/tokenizer download cap reached")
    environment_size = directory_bytes(environment_dir) if environment_dir else 0
    if environment_size > int(limits["storage"]["dependency_environment_maximum_gb"] * 1_000_000_000):
        raise SafetyStop("3.0 GB dependency-environment cap reached")
    combined = cache_size + environment_size + directory_bytes(ROOT)
    if combined > int(limits["storage"]["combined_task_created_maximum_gb"] * 1_000_000_000):
        raise SafetyStop("8.0 GB combined task-created storage cap reached")
    return {
        "elapsed_seconds": elapsed_seconds(),
        "rss_bytes": rss,
        "model_cache_bytes": cache_size,
        "dependency_environment_bytes": environment_size,
        "combined_measured_bytes": combined,
    }


def offline_preflight() -> dict[str, Any]:
    checked = verify_freeze()
    cases, keys, dev_ids, eval_ids = load_case_material()
    issues: list[str] = []
    if len(dev_ids) != 4 or sum(len(cases[value]["atomic_claims"]) for value in dev_ids) != 10:
        issues.append("development_count_failure")
    if len(eval_ids) != 12 or sum(len(cases[value]["atomic_claims"]) for value in eval_ids) != 29:
        issues.append("evaluation_count_failure")
    if load_json(FIXTURES / "case_answer_review_and_correction_v01.json")["correction"]["case_id"] != "fresh02_aapd_revup_profile":
        issues.append("aapd_correction_record_missing")
    bounds: dict[str, dict[str, int]] = {}
    for case_id, case in cases.items():
        for claim in case["atomic_claims"]:
            hhem = contract.hhem_input(case, claim)
            mini = contract.minicheck_input(case, claim)
            key = f"{case_id}:{claim['claim_id']}"
            bounds[key] = {
                "hhem_utf8_bytes": len(hhem.encode("utf-8")),
                "hhem_conservative_token_upper_bound": contract.conservative_token_upper_bound(hhem),
                "minicheck_utf8_bytes": len(mini.encode("utf-8")),
                "minicheck_conservative_token_upper_bound": contract.conservative_token_upper_bound(mini),
            }
            if contract.input_has_answer_leakage(hhem) or contract.input_has_answer_leakage(mini):
                issues.append(f"{key}:answer_leakage")
            if max(bounds[key].values()) > 1024:
                issues.append(f"{key}:conservative_bound_exceeds_1024")
    distribution = {contract.LABEL_SUPPORTED: 0, contract.LABEL_UNSUPPORTED: 0, contract.LABEL_INSUFFICIENT: 0}
    for case_id in dev_ids:
        for label in keys[case_id]["claim_verdicts"].values():
            distribution[label] += 1
    if distribution != {contract.LABEL_SUPPORTED: 7, contract.LABEL_UNSUPPORTED: 2, contract.LABEL_INSUFFICIENT: 1}:
        issues.append("development_distribution_failure")
    return {
        "schema_version": "stories-of-us-dedicated-checker-offline-preflight-v01",
        "checked_at_utc": now_utc(),
        "status": "PASS" if not issues else "FAIL",
        "execution": "LOCKED_NOT_AUTHORISED" if not AUTHORITY.exists() else "AUTHORITY_FILE_PRESENT_NOT_EXECUTED",
        "frozen_files_checked": checked,
        "issues": issues,
        "case_counts": {"development": len(dev_ids), "evaluation": len(eval_ids)},
        "claim_counts": {"development": 10, "evaluation": 29},
        "largest_hhem_conservative_bound": max(row["hhem_conservative_token_upper_bound"] for row in bounds.values()),
        "largest_minicheck_conservative_bound": max(row["minicheck_conservative_token_upper_bound"] for row in bounds.values()),
        "bound_note": "UTF-8 byte-based conservative bounds, not exact tokenizer counts. Exact pinned-tokenizer counts remain a mandatory execution preflight.",
        "model_requests": 0,
        "account_requests": 0,
        "installations": 0,
        "model_downloads": 0,
    }


class HHEMAdapter:
    name = "hhem_2_1_open"

    def __init__(self, cache_dir: Path):
        import torch
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file
        from transformers import AutoConfig, AutoTokenizer, T5ForTokenClassification

        registry = load_json(FIXTURES / "model_registry_frozen_v01.json")["models"][self.name]
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(
            registry["foundation_model_id"], revision=registry["foundation_revision"], cache_dir=cache_dir
        )
        configuration = AutoConfig.from_pretrained(
            registry["foundation_model_id"], revision=registry["foundation_revision"], cache_dir=cache_dir, num_labels=2
        )
        self.model = T5ForTokenClassification(configuration)
        weight_path = Path(hf_hub_download(
            registry["model_id"], filename=registry["weight_file"], revision=registry["revision"], cache_dir=cache_dir
        ))
        if contract.sha256_file(weight_path) != registry["weight_sha256"]:
            raise SafetyStop("HHEM weight checksum mismatch")
        state = load_file(str(weight_path))
        state = {key[3:] if key.startswith("t5.") else key: value for key, value in state.items()}
        missing, unexpected = self.model.load_state_dict(state, strict=False)
        missing = [key for key in missing if "embed_tokens" not in key]
        if missing or unexpected:
            raise SafetyStop(f"HHEM weight load mismatch: missing={missing}, unexpected={unexpected}")
        self.model.eval()

    def formatted_input(self, case: dict[str, Any], claim: dict[str, Any]) -> str:
        return contract.hhem_input(case, claim)

    def token_count(self, text: str) -> int:
        return len(self.tokenizer(text, truncation=False, add_special_tokens=True)["input_ids"])

    def score(self, text: str) -> float:
        inputs = self.tokenizer(text, return_tensors="pt", truncation=False)
        with self.torch.no_grad():
            logits = self.model(**inputs).logits[:, 0, :]
            return float(self.torch.softmax(logits, dim=-1)[:, 1].item())


class MiniCheckAdapter:
    name = "minicheck_flan_t5_large"

    def __init__(self, cache_dir: Path):
        import torch
        from huggingface_hub import hf_hub_download
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        registry = load_json(FIXTURES / "model_registry_frozen_v01.json")["models"][self.name]
        self.torch = torch
        weight_path = Path(hf_hub_download(
            registry["model_id"], filename=registry["weight_file"], revision=registry["revision"], cache_dir=cache_dir
        ))
        if contract.sha256_file(weight_path) != registry["weight_sha256"]:
            raise SafetyStop("MiniCheck weight checksum mismatch")
        self.tokenizer = AutoTokenizer.from_pretrained(registry["model_id"], revision=registry["revision"], cache_dir=cache_dir)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            registry["model_id"], revision=registry["revision"], cache_dir=cache_dir
        )
        self.model.eval()
        if self.tokenizer.eos_token is None:
            raise SafetyStop("MiniCheck tokenizer has no EOS token")

    def formatted_input(self, case: dict[str, Any], claim: dict[str, Any]) -> str:
        return contract.minicheck_input(case, claim, self.tokenizer.eos_token)

    def token_count(self, text: str) -> int:
        return len(self.tokenizer(text, truncation=False, add_special_tokens=True)["input_ids"])

    def score(self, text: str) -> float:
        inputs = self.tokenizer(text, return_tensors="pt", truncation=False)
        decoder = self.torch.zeros((1, 1), dtype=self.torch.long)
        with self.torch.no_grad():
            logits = self.model(
                input_ids=inputs["input_ids"], attention_mask=inputs["attention_mask"], decoder_input_ids=decoder
            ).logits.squeeze(1)
            label_logits = logits[:, self.torch.tensor([3, 209])]
            return float(self.torch.softmax(label_logits, dim=-1)[:, 1].item())


def reference_claims(keys: dict[str, dict[str, Any]], case_ids: list[str]) -> dict[str, str]:
    return {
        f"{case_id}:{claim_id}": verdict
        for case_id in case_ids
        for claim_id, verdict in keys[case_id]["claim_verdicts"].items()
    }


def scorecard(
    candidate: str,
    rows: list[dict[str, Any]],
    cases: dict[str, dict[str, Any]],
    keys: dict[str, dict[str, Any]],
    case_ids: list[str],
    threshold: float,
) -> dict[str, Any]:
    row_map = {(row["case_id"], row["claim_id"]): row for row in rows}
    claim_totals = {"supported": 0, "non_supported": 0, "supported_correct": 0, "non_supported_false_approvals": 0}
    summaries: dict[str, Any] = {}
    for case_id in case_ids:
        case = cases[case_id]
        decisions: dict[str, str] = {}
        for claim in case["atomic_claims"]:
            claim_id = claim["claim_id"]
            row = row_map[(case_id, claim_id)]
            decision = contract.score_to_decision(row["score"], threshold)
            decisions[claim_id] = decision
            expected = keys[case_id]["claim_verdicts"][claim_id]
            if expected == contract.LABEL_SUPPORTED:
                claim_totals["supported"] += 1
                claim_totals["supported_correct"] += decision == contract.CANDIDATE_SUPPORTED
            else:
                claim_totals["non_supported"] += 1
                claim_totals["non_supported_false_approvals"] += decision == contract.CANDIDATE_SUPPORTED
        summaries[case_id] = {
            "decision": contract.aggregate_summary([row["claim_id"] for row in case["atomic_claims"]], decisions),
            "reference": keys[case_id]["expected_whole_summary"],
            "claim_decisions": decisions,
        }
    return {"candidate": candidate, "threshold": threshold, "claim_totals": claim_totals, "summaries": summaries}


def evaluation_gate(card: dict[str, Any], keys: dict[str, dict[str, Any]], repeatability: dict[str, Any]) -> dict[str, Any]:
    summaries = card["summaries"]
    supported_case_ids = [case_id for case_id in summaries if keys[case_id]["group"] == "fully_supported"]
    unsafe_case_ids = [case_id for case_id in summaries if keys[case_id]["group"] == "subtly_unsafe"]
    insufficient_case_ids = [case_id for case_id in summaries if keys[case_id]["group"] == "genuinely_insufficient_evidence"]
    criteria = {
        "twenty_nine_valid_primary_scores": card["claim_totals"]["supported"] + card["claim_totals"]["non_supported"] == 29,
        "zero_non_supported_claim_false_approvals": card["claim_totals"]["non_supported_false_approvals"] == 0,
        "supported_claims_recognised_at_least_18_of_21": card["claim_totals"]["supported_correct"] >= 18,
        "zero_unsafe_summaries_supported": all(summaries[value]["decision"] == contract.WITHHOLD for value in unsafe_case_ids),
        "zero_insufficient_summaries_supported": all(summaries[value]["decision"] == contract.WITHHOLD for value in insufficient_case_ids),
        "supported_summaries_at_least_3_of_4": sum(summaries[value]["decision"] == contract.CANDIDATE_SUPPORTED for value in supported_case_ids) >= 3,
        "not_reject_everything": any(row["decision"] == contract.CANDIDATE_SUPPORTED for row in summaries.values()),
        "repeatability": repeatability["status"] == "PASS",
    }
    return {"status": "PASS" if all(criteria.values()) else "FAIL", "criteria": criteria}


def run_live() -> dict[str, Any]:
    verify_freeze()
    require_live_authority()
    dependencies = direct_dependency_versions()
    cases, keys, dev_ids, eval_ids = load_case_material()
    resources = load_json(FIXTURES / "resource_limits_frozen_v01.json")
    scoring = load_json(FIXTURES / "scoring_rules_frozen_v01.json")
    cache_dir = Path(os.environ.get("SOU_HF_CACHE", str(ROOT / ".runtime_cache/huggingface")))
    environment_dir = Path(os.environ["SOU_ENV_ROOT"]) if os.environ.get("SOU_ENV_ROOT") else None
    free_disk = shutil.disk_usage(ROOT).free
    if free_disk < int(resources["storage"]["minimum_free_disk_preflight_gb"] * 1_000_000_000):
        raise SafetyStop("less than 10 GB free disk at preflight")
    ledger: dict[str, Any] = {
        "schema_version": "stories-of-us-dedicated-checker-live-ledger-v01",
        "started_at_utc": now_utc(),
        "freeze_manifest_sha256": freeze_hash(),
        "logical_evaluations_attempted": 0,
        "logical_evaluations_completed": 0,
        "passage_forward_computations_attempted": 0,
        "retries": 0,
        "candidates": {},
        "dependencies": dependencies,
        "resource_snapshots": [],
    }
    write_json(LEDGER, ledger)

    def infer(adapter: Any, case_id: str, claim: dict[str, Any], threshold: float | None = None) -> dict[str, Any]:
        try:
            reserved_count = contract.reserve_logical_evaluation(
                ledger["logical_evaluations_attempted"], resources["logical_evaluations"]["total_maximum"]
            )
        except contract.ContractError as error:
            raise SafetyStop("90-evaluation cap reached") from error
        text = adapter.formatted_input(cases[case_id], claim)
        count = adapter.token_count(text)
        if count > resources["input"]["maximum_complete_formatted_tokens"]:
            raise SafetyStop(f"{adapter.name}:{case_id}:{claim['claim_id']} tokenizer overflow")
        ledger["logical_evaluations_attempted"] = reserved_count
        ledger["passage_forward_computations_attempted"] += 1
        write_json(LEDGER, ledger)
        value = adapter.score(text)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise SafetyStop("invalid model score")
        ledger["logical_evaluations_completed"] += 1
        snap = resource_check(cache_dir, environment_dir)
        ledger["resource_snapshots"].append(snap)
        write_json(LEDGER, ledger)
        return {
            "candidate": adapter.name,
            "case_id": case_id,
            "claim_id": claim["claim_id"],
            "evidence_ids": [row["evidence_id"] for row in cases[case_id]["verified_evidence"]],
            "formatted_input_sha256": contract.sha256_text(text),
            "exact_token_count": count,
            "truncated": False,
            "passage_computations": 1,
            "score": value,
            "threshold": threshold,
        }

    all_cases = [cases[value] for value in dev_ids + eval_ids]
    outcomes: dict[str, Any] = {}
    for adapter_class in (HHEMAdapter, MiniCheckAdapter):
        adapter = adapter_class(cache_dir)
        candidate = adapter.name
        # Exact tokenizer coverage is checked for all frozen claims before this candidate's first inference.
        token_counts: dict[str, int] = {}
        for case in all_cases:
            for claim in case["atomic_claims"]:
                text = adapter.formatted_input(case, claim)
                count = adapter.token_count(text)
                token_counts[f"{case['case_id']}:{claim['claim_id']}"] = count
                if count > resources["input"]["maximum_complete_formatted_tokens"]:
                    raise SafetyStop(f"{candidate}: frozen input exceeds 1024 tokens")
        dev_rows: list[dict[str, Any]] = []
        for case_id in dev_ids:
            for claim in cases[case_id]["atomic_claims"]:
                dev_rows.append(infer(adapter, case_id, claim))
                write_json(GENUINE / f"{candidate}_development_partial_v01.json", dev_rows)
        dev_reference = reference_claims(keys, dev_ids)
        dev_scores = {f"{row['case_id']}:{row['claim_id']}": row["score"] for row in dev_rows}
        threshold_result = contract.select_threshold(dev_scores, dev_reference, scoring["threshold_grid"])
        candidate_outcome: dict[str, Any] = {
            "token_counts": token_counts,
            "development_rows": dev_rows,
            "threshold_result": threshold_result,
            "evaluation_attempted": False,
        }
        if not contract.development_allows_evaluation(threshold_result):
            candidate_outcome["status"] = "DEVELOPMENT_GATE_FAIL"
            outcomes[candidate] = candidate_outcome
            ledger["candidates"][candidate] = candidate_outcome["status"]
            write_json(LEDGER, ledger)
            del adapter
            gc.collect()
            continue
        threshold = float(threshold_result["threshold"])
        for row in dev_rows:
            row["threshold"] = threshold
        development_card = scorecard(candidate, dev_rows, cases, keys, dev_ids, threshold)
        candidate_outcome["development_scorecard"] = development_card
        eval_rows: list[dict[str, Any]] = []
        candidate_outcome["evaluation_attempted"] = True
        for case_id in eval_ids:
            for claim in cases[case_id]["atomic_claims"]:
                eval_rows.append(infer(adapter, case_id, claim, threshold))
                write_json(GENUINE / f"{candidate}_evaluation_partial_v01.json", eval_rows)
        contract.validate_result_rows({value: cases[value] for value in eval_ids}, eval_rows, candidate)
        evaluation_card = scorecard(candidate, eval_rows, cases, keys, eval_ids, threshold)
        row_map = {(row["case_id"], row["claim_id"]): row for row in eval_rows}
        repeat_rows = []
        maximum_drift = 0.0
        classifications_identical = True
        for claim_id in scoring["reserved_evaluation_per_candidate"]["repeatability_claim_ids"]:
            case_id = next(value for value in eval_ids if any(row["claim_id"] == claim_id for row in cases[value]["atomic_claims"]))
            claim = next(row for row in cases[case_id]["atomic_claims"] if row["claim_id"] == claim_id)
            repeated = infer(adapter, case_id, claim, threshold)
            original = row_map[(case_id, claim_id)]
            drift = abs(repeated["score"] - original["score"])
            maximum_drift = max(maximum_drift, drift)
            classifications_identical = classifications_identical and (
                contract.score_to_decision(repeated["score"], threshold) == contract.score_to_decision(original["score"], threshold)
            )
            repeat_rows.append({**repeated, "primary_score": original["score"], "absolute_drift": drift})
        repeatability = {
            "status": "PASS" if classifications_identical and maximum_drift <= 0.00001 else "FAIL",
            "classifications_identical": classifications_identical,
            "maximum_absolute_score_drift": maximum_drift,
            "rows": repeat_rows,
        }
        candidate_outcome.update({
            "status": "COMPLETE",
            "evaluation_rows": eval_rows,
            "evaluation_scorecard": evaluation_card,
            "repeatability": repeatability,
            "evaluation_gate": evaluation_gate(evaluation_card, keys, repeatability),
        })
        outcomes[candidate] = candidate_outcome
        ledger["candidates"][candidate] = candidate_outcome["evaluation_gate"]["status"]
        write_json(GENUINE / f"{candidate}_complete_v01.json", candidate_outcome)
        write_json(LEDGER, ledger)
        del adapter
        gc.collect()

    overall = "PASS" if all(
        row.get("evaluation_gate", {}).get("status") == "PASS" for row in outcomes.values()
    ) and len(outcomes) == 2 else "PARTIAL"
    result = {
        "schema_version": "stories-of-us-dedicated-checker-execution-summary-v01",
        "completed_at_utc": now_utc(),
        "overall": overall,
        "interpretation": "A PASS supports further investigation only and is not production approval.",
        "outcomes": outcomes,
        "ledger": ledger,
        "maximum_expenditure_gbp": 0,
    }
    write_json(SUMMARY, result)
    lock = load_json(LOCK)
    lock["status"] = "CONSUMED_COMPLETED"
    lock["completed_at_utc"] = now_utc()
    write_json(LOCK, lock)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline-preflight", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.offline_preflight == args.execute:
        print("SAFETY_STOP: choose exactly one of --offline-preflight or --execute", file=sys.stderr)
        return 2
    try:
        result = run_live() if args.execute else offline_preflight()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("status", result.get("overall")) in {"PASS", "PARTIAL"} else 2
    except SafetyStop as error:
        print(f"SAFETY_STOP: {error}", file=sys.stderr)
        return 2
    except contract.ContractError as error:
        print(f"SAFETY_STOP: contract failure: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
