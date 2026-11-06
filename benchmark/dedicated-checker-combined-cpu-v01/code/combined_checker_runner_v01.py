#!/usr/bin/env python3
"""Locked combined CPU dependency/model-loading/checker comparison runner.

Offline preflight imports only the standard library. Live candidate execution
is isolated in one child process per model so its memory is released before the
next candidate. No model-dependent operation is reachable without a separately
approved authority file and a consumed one-use lock.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.metadata
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "code"
FIXTURES = ROOT / "fixtures"
OUTPUTS = ROOT / "outputs"
RESULTS = OUTPUTS / "genuine_model"
LEDGER = OUTPUTS / "execution_ledger_v01.json"
SUMMARY = OUTPUTS / "execution_summary_v01.json"

sys.path.insert(0, str(CODE))
import dedicated_checker_contract_v01 as contract  # noqa: E402
import storage_and_lock_controls_v01 as controls  # noqa: E402


class CandidateStop(RuntimeError):
    """A preserved failure that stops one candidate, not the global job."""


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    return controls.load_json(path)


def write_json(path: Path, value: Any) -> None:
    controls.write_json(path, value)


def load_case_material() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[str], list[str]]:
    development = load_json(FIXTURES / "development_cases_model_facing_frozen_v01.json")
    evaluation = load_json(FIXTURES / "evaluation_cases_model_facing_frozen_v01.json")
    development_key = load_json(FIXTURES / "development_answer_key_frozen_v01.json")
    evaluation_key = load_json(FIXTURES / "evaluation_answer_key_frozen_v01.json")
    cases = contract.cases_by_id([development, evaluation])
    keys = contract.keys_by_id([development_key, evaluation_key])
    contract.validate_case_key_membership(cases, keys)
    return (
        cases,
        keys,
        [row["case_id"] for row in development["cases"]],
        [row["case_id"] for row in evaluation["cases"]],
    )


def reference_claims(keys: dict[str, dict[str, Any]], case_ids: list[str]) -> dict[str, str]:
    return {
        f"{case_id}:{claim_id}": verdict
        for case_id in case_ids
        for claim_id, verdict in keys[case_id]["claim_verdicts"].items()
    }


def verify_download_file(path: Path, specification: dict[str, Any]) -> None:
    if not path.is_file() or path.stat().st_size != specification["size"]:
        raise CandidateStop(f"download size mismatch: {path.name}")
    method = specification["hash_type"]
    actual = controls.sha256_file(path) if method == "sha256" else controls.git_blob_sha1(path)
    if actual != specification["hash"]:
        raise CandidateStop(f"download {method} mismatch: {path.name}")


def download_candidate(candidate: str, candidate_dir: Path) -> dict[str, Any]:
    from huggingface_hub import hf_hub_download

    manifest = load_json(FIXTURES / "model_download_manifest_frozen_v01.json")["candidates"][candidate]
    downloaded: list[dict[str, Any]] = []
    for repository in manifest["repositories"]:
        destination = candidate_dir / repository["destination"]
        destination.mkdir(parents=True, exist_ok=True)
        for specification in repository["files"]:
            result = Path(hf_hub_download(
                repo_id=repository["repo_id"],
                filename=specification["path"],
                revision=repository["revision"],
                local_dir=destination,
            ))
            verify_download_file(result, specification)
            downloaded.append({
                "repo_id": repository["repo_id"],
                "revision": repository["revision"],
                "relative_path": result.relative_to(candidate_dir).as_posix(),
                "size": result.stat().st_size,
                "hash_type": specification["hash_type"],
                "hash": specification["hash"],
            })
    accounting = controls.account_paths([candidate_dir])
    write_json(RESULTS / f"{candidate}_download_storage_before_guard_v01.json", accounting)
    limits = load_json(FIXTURES / "resource_limits_frozen_v01.json")["storage"]
    if accounting["allocated_bytes_unique"] > limits["maximum_candidate_model_tokenizer_bytes"]:
        raise CandidateStop("candidate model/tokenizer storage cap exceeded")
    return {"files": downloaded, "storage_before_guard": accounting}


class HHEMAdapter:
    name = "hhem_2_1_open"

    def __init__(self, candidate_dir: Path):
        import torch
        from safetensors.torch import load_file
        from transformers import AutoConfig, AutoTokenizer, T5ForTokenClassification

        self.torch = torch
        foundation = candidate_dir / "flan_t5_base"
        model_dir = candidate_dir / "hhem_model"
        self.tokenizer = AutoTokenizer.from_pretrained(foundation, local_files_only=True)
        configuration = AutoConfig.from_pretrained(foundation, local_files_only=True, num_labels=2)
        self.model = T5ForTokenClassification(configuration)
        state = load_file(str(model_dir / "model.safetensors"))
        state = {key[3:] if key.startswith("t5.") else key: value for key, value in state.items()}
        missing, unexpected = self.model.load_state_dict(state, strict=False)
        missing = [key for key in missing if "embed_tokens" not in key]
        if missing or unexpected:
            raise CandidateStop(f"HHEM weight load mismatch: missing={missing}, unexpected={unexpected}")
        self.model.to("cpu").eval()

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

    def __init__(self, candidate_dir: Path):
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self.torch = torch
        model_dir = candidate_dir / "minicheck_model"
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            model_dir, local_files_only=True, use_safetensors=False, device_map=None
        )
        self.model.to("cpu").eval()
        if self.tokenizer.eos_token is None:
            raise CandidateStop("MiniCheck tokenizer has no EOS token")

    def formatted_input(self, case: dict[str, Any], claim: dict[str, Any]) -> str:
        return contract.minicheck_input(case, claim, self.tokenizer.eos_token)

    def token_count(self, text: str) -> int:
        return len(self.tokenizer(text, truncation=False, add_special_tokens=True)["input_ids"])

    def score(self, text: str) -> float:
        inputs = self.tokenizer(text, return_tensors="pt", truncation=False)
        decoder = self.torch.zeros((1, 1), dtype=self.torch.long)
        with self.torch.no_grad():
            logits = self.model(
                input_ids=inputs["input_ids"],
                attention_mask=inputs["attention_mask"],
                decoder_input_ids=decoder,
            ).logits.squeeze(1)
            label_logits = logits[:, self.torch.tensor([3, 209])]
            return float(self.torch.softmax(label_logits, dim=-1)[:, 1].item())


def scorecard(candidate: str, rows: list[dict[str, Any]], cases: dict[str, dict[str, Any]], keys: dict[str, dict[str, Any]], case_ids: list[str], threshold: float) -> dict[str, Any]:
    row_map = {(row["case_id"], row["claim_id"]): row for row in rows}
    totals = {"supported": 0, "non_supported": 0, "supported_correct": 0, "non_supported_false_approvals": 0}
    summaries: dict[str, Any] = {}
    for case_id in case_ids:
        decisions: dict[str, str] = {}
        for claim in cases[case_id]["atomic_claims"]:
            claim_id = claim["claim_id"]
            decision = contract.score_to_decision(row_map[(case_id, claim_id)]["score"], threshold)
            decisions[claim_id] = decision
            expected = keys[case_id]["claim_verdicts"][claim_id]
            if expected == contract.LABEL_SUPPORTED:
                totals["supported"] += 1
                totals["supported_correct"] += int(decision == contract.CANDIDATE_SUPPORTED)
            else:
                totals["non_supported"] += 1
                totals["non_supported_false_approvals"] += int(decision == contract.CANDIDATE_SUPPORTED)
        summaries[case_id] = {
            "decision": contract.aggregate_summary([row["claim_id"] for row in cases[case_id]["atomic_claims"]], decisions),
            "reference": keys[case_id]["expected_whole_summary"],
            "group": keys[case_id].get("group"),
            "claim_decisions": decisions,
        }
    return {"candidate": candidate, "threshold": threshold, "claim_totals": totals, "summaries": summaries}


def evaluation_gate(card: dict[str, Any], repeatability: dict[str, Any]) -> dict[str, Any]:
    summaries = card["summaries"]
    groups = {group: [case_id for case_id, row in summaries.items() if row["group"] == group] for group in ("fully_supported", "subtly_unsafe", "genuinely_insufficient_evidence")}
    criteria = {
        "twenty_nine_valid_primary_scores": card["claim_totals"]["supported"] + card["claim_totals"]["non_supported"] == 29,
        "zero_non_supported_claim_false_approvals": card["claim_totals"]["non_supported_false_approvals"] == 0,
        "supported_claims_recognised_at_least_18_of_21": card["claim_totals"]["supported_correct"] >= 18,
        "zero_unsafe_summaries_supported": all(summaries[value]["decision"] == contract.WITHHOLD for value in groups["subtly_unsafe"]),
        "zero_insufficient_summaries_supported": all(summaries[value]["decision"] == contract.WITHHOLD for value in groups["genuinely_insufficient_evidence"]),
        "supported_summaries_at_least_3_of_4": sum(summaries[value]["decision"] == contract.CANDIDATE_SUPPORTED for value in groups["fully_supported"]) >= 3,
        "not_reject_everything": any(row["decision"] == contract.CANDIDATE_SUPPORTED for row in summaries.values()),
        "repeatability": repeatability["status"] == "PASS",
    }
    return {"status": "PASS" if all(criteria.values()) else "FAIL", "criteria": criteria}


def offline_preflight() -> dict[str, Any]:
    checked = controls.verify_freeze()
    cases, keys, dev_ids, eval_ids = load_case_material()
    issues: list[str] = []
    if len(dev_ids) != 4 or sum(len(cases[value]["atomic_claims"]) for value in dev_ids) != 10:
        issues.append("development_count_failure")
    if len(eval_ids) != 12 or sum(len(cases[value]["atomic_claims"]) for value in eval_ids) != 29:
        issues.append("evaluation_count_failure")
    if load_json(FIXTURES / "case_answer_review_and_correction_v01.json")["correction"]["case_id"] != "fresh02_aapd_revup_profile":
        issues.append("approved_aapd_correction_missing")
    largest = {"hhem": 0, "minicheck": 0}
    for case in cases.values():
        for claim in case["atomic_claims"]:
            for candidate, text in (("hhem", contract.hhem_input(case, claim)), ("minicheck", contract.minicheck_input(case, claim))):
                largest[candidate] = max(largest[candidate], contract.conservative_token_upper_bound(text))
                if contract.conservative_token_upper_bound(text) > 1024:
                    issues.append(f"{case['case_id']}:{claim['claim_id']}:{candidate}:bound_overflow")
                if contract.input_has_answer_leakage(text):
                    issues.append(f"{case['case_id']}:{claim['claim_id']}:{candidate}:answer_leakage")
    development = reference_claims(keys, dev_ids)
    if list(development.values()).count("SUPPORTED") != 7 or len(development) != 10:
        issues.append("development_distribution_failure")
    lock_rows = controls.parse_wheel_lock(FIXTURES / "requirements_cpu_wheels_frozen_v01.txt")
    if len(lock_rows) != 36:
        issues.append("cpu_wheel_lock_not_36")
    model_downloads = load_json(FIXTURES / "model_download_manifest_frozen_v01.json")["candidates"]
    if model_downloads["hhem_2_1_open"]["candidate_bytes"] != 441757214:
        issues.append("hhem_download_total_failure")
    if model_downloads["minicheck_flan_t5_large"]["candidate_bytes"] != 3136026916:
        issues.append("minicheck_download_total_failure")
    limits = load_json(FIXTURES / "resource_limits_frozen_v01.json")
    if sum(limits["logical_evaluations"][value] for value in ("development", "reserved_evaluation_maximum", "repeatability_maximum")) != 90:
        issues.append("computation_budget_failure")
    authority = controls.authority_state(controls.AUTHORITY, controls.LOCK, controls.freeze_hash())
    if authority["state"] != "LOCKED_NOT_AUTHORISED":
        issues.append("package_not_locked_for_preparation")
    return {
        "schema_version": "stories-of-us-combined-cpu-checker-offline-preflight-v01",
        "status": "PASS" if not issues else "FAIL",
        "checked_at_utc": now_utc(),
        "frozen_files_checked": checked,
        "execution": authority["state"],
        "issues": issues,
        "case_counts": {"development": 4, "evaluation": 12},
        "claim_counts": {"development": 10, "evaluation": 29},
        "maximum_computations": 90,
        "largest_conservative_bounds": largest,
        "bound_note": "UTF-8-byte upper bounds, not exact token counts; pinned tokenizers must count every complete request before candidate inference.",
        "preparation_activity": {"installations": 0, "model_downloads": 0, "model_loads": 0, "inference": 0, "account_requests": 0},
    }


def direct_dependency_versions() -> dict[str, str]:
    expected = load_json(FIXTURES / "expected_versions_frozen_v01.json")
    actual: dict[str, str] = {}
    installed = {distribution.metadata["Name"].lower().replace("_", "-"): distribution.version for distribution in importlib.metadata.distributions()}
    for name, version in expected["packages"].items():
        actual_version = installed.get(name)
        if actual_version != version:
            raise controls.SafetyStop(f"dependency version mismatch: {name}={actual_version}, expected {version}")
        actual[name] = actual_version
    unexpected = set(installed) - set(expected["packages"]) - set(expected["allowed_additional_distributions"])
    if unexpected:
        raise controls.SafetyStop(f"unexpected distributions present: {sorted(unexpected)}")
    if any(name == "triton" or name.startswith(("cuda-", "nvidia-")) for name in installed):
        raise controls.SafetyStop("unexpected GPU distribution present")
    import torch
    if torch.__version__ != "2.15.0+cpu" or torch.version.cuda is not None:
        raise controls.SafetyStop("CPU-only PyTorch identity check failed")
    return actual


def require_postlock_authority() -> dict[str, Any]:
    if not controls.AUTHORITY.is_file() or not controls.LOCK.is_file():
        raise controls.SafetyStop("approved authority and consumed lock required")
    authority = load_json(controls.AUTHORITY)
    lock = load_json(controls.LOCK)
    if authority.get("approved_freeze_manifest_sha256") != controls.freeze_hash():
        raise controls.SafetyStop("approved freeze hash mismatch")
    if lock.get("status") != "CONSUMED_RESERVED_BEFORE_INSTALLATION" or lock.get("freeze_manifest_sha256") != controls.freeze_hash():
        raise controls.SafetyStop("invalid consumed lock")
    return authority


def _infer(adapter: Any, cases: dict[str, dict[str, Any]], case_id: str, claim: dict[str, Any], counters: dict[str, int], threshold: float | None) -> dict[str, Any]:
    if counters["attempted"] >= 45:
        raise controls.SafetyStop("per-candidate 45-computation cap reached")
    text = adapter.formatted_input(cases[case_id], claim)
    count = adapter.token_count(text)
    if count > 1024:
        raise CandidateStop(f"{adapter.name}:{case_id}:{claim['claim_id']}:exact token overflow")
    counters["attempted"] += 1
    value = adapter.score(text)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise CandidateStop("invalid model score")
    counters["completed"] += 1
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


def run_candidate(candidate: str) -> int:
    if os.environ.get("SOU_INTERNAL_CANDIDATE") != "1":
        raise controls.SafetyStop("candidate mode is internal only")
    require_postlock_authority()
    cases, keys, dev_ids, eval_ids = load_case_material()
    scoring = load_json(FIXTURES / "scoring_rules_frozen_v01.json")
    runtime_root = Path(os.environ["SOU_RUNTIME_ROOT"])
    candidate_dir = runtime_root / candidate
    outcome_path = RESULTS / f"{candidate}_outcome_v01.json"
    counters = {"attempted": 0, "completed": 0}
    outcome: dict[str, Any] = {"candidate": candidate, "started_at_utc": now_utc(), "status": "STARTED", "counters": counters}
    write_json(outcome_path, outcome)
    try:
        outcome["downloads"] = download_candidate(candidate, candidate_dir)
        os.environ.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"})
        adapter = HHEMAdapter(candidate_dir) if candidate == "hhem_2_1_open" else MiniCheckAdapter(candidate_dir)
        outcome["model_loaded_on"] = "cpu"
        token_counts: dict[str, int] = {}
        for case_id in dev_ids + eval_ids:
            for claim in cases[case_id]["atomic_claims"]:
                text = adapter.formatted_input(cases[case_id], claim)
                count = adapter.token_count(text)
                token_counts[f"{case_id}:{claim['claim_id']}"] = count
                if count > 1024:
                    raise CandidateStop(f"{candidate}:frozen input exceeds 1024 exact tokens")
        outcome["exact_token_counts"] = token_counts
        dev_rows: list[dict[str, Any]] = []
        for case_id in dev_ids:
            for claim in cases[case_id]["atomic_claims"]:
                dev_rows.append(_infer(adapter, cases, case_id, claim, counters, None))
                outcome.update({"development_rows": dev_rows, "counters": counters})
                write_json(outcome_path, outcome)
        labels = reference_claims(keys, dev_ids)
        scores = {f"{row['case_id']}:{row['claim_id']}": row["score"] for row in dev_rows}
        threshold_result = contract.select_threshold(scores, labels, scoring["threshold_grid"])
        outcome["threshold_result"] = threshold_result
        if not contract.development_allows_evaluation(threshold_result):
            outcome["status"] = "DEVELOPMENT_GATE_FAIL"
            outcome["evaluation_attempted"] = False
            write_json(outcome_path, outcome)
            return 0
        threshold = float(threshold_result["threshold"])
        for row in dev_rows:
            row["threshold"] = threshold
        outcome["development_scorecard"] = scorecard(candidate, dev_rows, cases, keys, dev_ids, threshold)
        eval_rows: list[dict[str, Any]] = []
        outcome["evaluation_attempted"] = True
        for case_id in eval_ids:
            for claim in cases[case_id]["atomic_claims"]:
                eval_rows.append(_infer(adapter, cases, case_id, claim, counters, threshold))
                outcome.update({"evaluation_rows": eval_rows, "counters": counters})
                write_json(outcome_path, outcome)
        contract.validate_result_rows({value: cases[value] for value in eval_ids}, eval_rows, candidate)
        evaluation_card = scorecard(candidate, eval_rows, cases, keys, eval_ids, threshold)
        row_map = {(row["case_id"], row["claim_id"]): row for row in eval_rows}
        repeats: list[dict[str, Any]] = []
        maximum_drift = 0.0
        identical = True
        for claim_id in scoring["reserved_evaluation_per_candidate"]["repeatability_claim_ids"]:
            case_id = next(value for value in eval_ids if any(row["claim_id"] == claim_id for row in cases[value]["atomic_claims"]))
            claim = next(row for row in cases[case_id]["atomic_claims"] if row["claim_id"] == claim_id)
            repeated = _infer(adapter, cases, case_id, claim, counters, threshold)
            original = row_map[(case_id, claim_id)]
            drift = abs(repeated["score"] - original["score"])
            maximum_drift = max(maximum_drift, drift)
            identical = identical and contract.score_to_decision(repeated["score"], threshold) == contract.score_to_decision(original["score"], threshold)
            repeats.append({**repeated, "primary_score": original["score"], "absolute_drift": drift})
        repeatability = {"status": "PASS" if identical and maximum_drift <= 0.00001 else "FAIL", "classifications_identical": identical, "maximum_absolute_score_drift": maximum_drift, "rows": repeats}
        outcome.update({
            "status": "COMPLETE",
            "evaluation_scorecard": evaluation_card,
            "repeatability": repeatability,
            "evaluation_gate": evaluation_gate(evaluation_card, repeatability),
            "counters": counters,
            "completed_at_utc": now_utc(),
        })
        write_json(outcome_path, outcome)
        return 0
    except CandidateStop as error:
        outcome.update({
            "status": "CANDIDATE_STOP",
            "reason": str(error),
            "counters": counters,
            "storage_at_stop": controls.account_paths([candidate_dir]),
            "completed_at_utc": now_utc(),
        })
        write_json(outcome_path, outcome)
        return 3
    except (controls.SafetyStop, contract.ContractError):
        raise
    except Exception as error:
        outcome.update({
            "status": "CANDIDATE_STOP",
            "reason": f"candidate runtime/setup failure: {type(error).__name__}",
            "counters": counters,
            "completed_at_utc": now_utc(),
        })
        write_json(outcome_path, outcome)
        return 3


def monitor_candidate(candidate: str, runtime_root: Path, deadline: float) -> dict[str, Any]:
    import psutil

    environment = dict(os.environ)
    environment["SOU_INTERNAL_CANDIDATE"] = "1"
    environment["SOU_RUNTIME_ROOT"] = str(runtime_root)
    process = subprocess.Popen([sys.executable, str(Path(__file__)), "--candidate", candidate], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    maximum_rss = 0
    stop_reason: str | None = None
    memory_limit = load_json(FIXTURES / "resource_limits_frozen_v01.json")["memory"]["maximum_peak_task_rss_bytes"]
    observed = psutil.Process(process.pid)
    while process.poll() is None:
        if time.monotonic() > deadline:
            stop_reason = "global 45-minute time cap reached"
            process.terminate()
            break
        try:
            family = [observed] + observed.children(recursive=True)
            current = sum(value.memory_info().rss for value in family if value.is_running())
            maximum_rss = max(maximum_rss, current)
            if maximum_rss > memory_limit:
                stop_reason = "12,000,000,000-byte peak RSS cap reached"
                process.terminate()
                break
        except psutil.Error:
            pass
        time.sleep(0.1)
    stdout, stderr = process.communicate(timeout=30)
    return {"candidate": candidate, "returncode": process.returncode, "maximum_observed_rss_bytes": maximum_rss, "monitor_stop_reason": stop_reason, "stdout_tail": stdout[-4000:], "stderr_tail": stderr[-4000:]}


def run_live() -> dict[str, Any]:
    controls.verify_freeze()
    require_postlock_authority()
    dependencies = direct_dependency_versions()
    limits = load_json(FIXTURES / "resource_limits_frozen_v01.json")
    environment_dir = Path(os.environ["SOU_ENV_ROOT"])
    runtime_root = Path(os.environ["SOU_RUNTIME_ROOT"])
    runtime_root.mkdir(parents=True, exist_ok=True)
    environment_before_guard = controls.account_paths([environment_dir])
    if environment_before_guard["allocated_bytes_unique"] > limits["storage"]["maximum_installed_environment_bytes"]:
        raise controls.SafetyStop("3-GiB dependency environment cap exceeded")
    if shutil.disk_usage(ROOT).free < limits["storage"]["minimum_free_disk_bytes_before_installation"]:
        raise controls.SafetyStop("less than 10 GiB free disk")
    lock_started = dt.datetime.fromisoformat(load_json(controls.LOCK)["created_at_utc"])
    already_elapsed = (dt.datetime.now(dt.timezone.utc) - lock_started).total_seconds()
    if already_elapsed >= limits["maximum_job_seconds"]:
        raise controls.SafetyStop("45-minute cap reached before model stage")
    started = time.monotonic()
    deadline = started + (limits["maximum_job_seconds"] - already_elapsed)
    ledger: dict[str, Any] = {
        "schema_version": "stories-of-us-combined-cpu-checker-ledger-v01",
        "started_at_utc": now_utc(),
        "freeze_manifest_sha256": controls.freeze_hash(),
        "dependencies": dependencies,
        "dependency_environment_storage_before_guard": environment_before_guard,
        "seconds_elapsed_since_preinstallation_lock": already_elapsed,
        "logical_evaluations_attempted": 0,
        "logical_evaluations_completed": 0,
        "model_computations_attempted": 0,
        "retries": 0,
        "candidates": {},
    }
    write_json(LEDGER, ledger)
    for candidate in ("hhem_2_1_open", "minicheck_flan_t5_large"):
        monitor = monitor_candidate(candidate, runtime_root, deadline)
        outcome_path = RESULTS / f"{candidate}_outcome_v01.json"
        outcome = load_json(outcome_path) if outcome_path.is_file() else {"status": "NO_SAVED_OUTCOME"}
        counters = outcome.get("counters", {})
        ledger["logical_evaluations_attempted"] += int(counters.get("attempted", 0))
        ledger["logical_evaluations_completed"] += int(counters.get("completed", 0))
        ledger["model_computations_attempted"] = ledger["logical_evaluations_attempted"]
        ledger["candidates"][candidate] = {"outcome": outcome.get("status"), "monitor": monitor}
        if ledger["model_computations_attempted"] > limits["model_computations"]["maximum"]:
            raise controls.SafetyStop("90-computation global cap exceeded")
        combined = controls.account_paths([environment_dir, runtime_root, OUTPUTS])
        other_temporary = controls.account_paths([OUTPUTS])
        ledger["combined_storage_before_guard"] = combined
        ledger["other_task_temporary_before_guard"] = other_temporary
        write_json(LEDGER, ledger)
        if combined["allocated_bytes_unique"] > limits["storage"]["maximum_combined_task_created_bytes"]:
            raise controls.SafetyStop("8,000,000,000-byte combined storage cap exceeded")
        if other_temporary["allocated_bytes_unique"] > limits["storage"]["maximum_other_task_temporary_bytes"]:
            raise controls.SafetyStop("1,000,000,000-byte other-task temporary cap exceeded")
        if monitor["monitor_stop_reason"]:
            raise controls.SafetyStop(monitor["monitor_stop_reason"])
        if monitor["returncode"] not in (0, 3):
            raise controls.SafetyStop(f"{candidate} child failed without a permitted candidate stop")
        shutil.rmtree(runtime_root / candidate, ignore_errors=True)
        ledger["candidates"][candidate]["post_cleanup_storage"] = controls.account_paths([runtime_root])
        write_json(LEDGER, ledger)
    outcomes = {candidate: load_json(RESULTS / f"{candidate}_outcome_v01.json") for candidate in ("hhem_2_1_open", "minicheck_flan_t5_large") if (RESULTS / f"{candidate}_outcome_v01.json").is_file()}
    overall = "PASS" if len(outcomes) == 2 and all(row.get("evaluation_gate", {}).get("status") == "PASS" for row in outcomes.values()) else "PARTIAL"
    result = {"schema_version": "stories-of-us-combined-cpu-checker-summary-v01", "overall": overall, "completed_at_utc": now_utc(), "outcomes": outcomes, "ledger": ledger, "maximum_expenditure_gbp": 0, "interpretation": "A PASS supports further investigation only; it is not adoption or production approval."}
    write_json(SUMMARY, result)
    lock = load_json(controls.LOCK)
    lock.update({"status": "CONSUMED_COMPLETED", "completed_at_utc": now_utc()})
    write_json(controls.LOCK, lock)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline-preflight", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--candidate", choices=("hhem_2_1_open", "minicheck_flan_t5_large"))
    args = parser.parse_args()
    selected = sum((args.offline_preflight, args.execute, args.candidate is not None))
    if selected != 1:
        print("SAFETY_STOP: choose exactly one mode", file=sys.stderr)
        return 2
    try:
        if args.candidate:
            return run_candidate(args.candidate)
        result = run_live() if args.execute else offline_preflight()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("status", result.get("overall")) in {"PASS", "PARTIAL"} else 2
    except (controls.SafetyStop, contract.ContractError) as error:
        print(f"SAFETY_STOP: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
