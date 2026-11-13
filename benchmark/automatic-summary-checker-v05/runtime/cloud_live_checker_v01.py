#!/usr/bin/env python3
"""Five-operation cloud orchestrator for the proposed V05 checker experiment.

The file is runnable in principle but remains inert without a separately approved
authority record whose hash matches the future GitHub environment variable.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from checker_core_v01 import (
    ContractError,
    derive_authoritative_decision,
    extract_recognised_usage,
    json_only_completion,
)
from exact_token_count_v01 import ExactTokenCounter, CountError, GEMMA_MODEL, GPT_MODEL
from execution_control_v01 import (
    CloudflareChatTransport,
    SafetyStop,
    sanitize_body,
    validate_credentials,
)
from payloads_v01 import checker_payload, revision_payload
from private_git_state_v01 import DurablePrivateState, GitPersistence, StateStop, read_json
from review_gate_v01 import (
    ReviewStop,
    canonical_hash,
    evaluate_complete_recheck,
    evaluate_focused_review,
    evaluate_initial_review,
)


V05_FREEZE = "483007f696d93f3d3900daf6f7970444fb3d9bc83a86a107a8ab13a88f5e6086"
OPERATIONS = (
    "day0-focused-diagnostics",
    "day1-development",
    "day2-d14-correction",
    "day3-evaluation-initial",
    "day3-evaluation-corrections",
)
CHECKER_NEURONS = 619.997920
GEMMA_NEURONS = 152.437888


class LiveStop(RuntimeError):
    pass


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_manifest(root: Path, manifest_path: Path) -> None:
    manifest = read_json(manifest_path)
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise LiveStop("Private immutable bundle manifest is incomplete")
    for relative, expected in files.items():
        target = root / relative
        if not target.is_file() or sha_file(target) != expected:
            raise LiveStop(f"Private immutable bundle mismatch: {relative}")


def verify_identity(
    private_root: Path,
    expected_public_commit: str,
    actual_public_commit: str,
    expected_overlay_freeze: str,
    expected_bundle_hash: str,
    expected_authority_hash: str,
) -> dict[str, Any]:
    if actual_public_commit != expected_public_commit:
        raise LiveStop("Public commit identity mismatch")
    manifest = private_root / "live_v05/bundle/live_private_bundle_manifest_v01.json"
    if not manifest.is_file() or sha_file(manifest) != expected_bundle_hash:
        raise LiveStop("Private bundle identity mismatch")
    _verify_manifest(private_root / "live_v05/bundle", manifest)
    overlay_receipt = private_root / "live_v05/bundle/live_overlay/recovery/overlay_freeze_sha256_v01.txt"
    if not overlay_receipt.is_file() or overlay_receipt.read_text(encoding="utf-8").strip() != expected_overlay_freeze:
        raise LiveStop("Overlay freeze identity mismatch")
    v05_receipt = private_root / "live_v05/bundle/v05_package/recovery/freeze_manifest_sha256_v01.txt"
    if not v05_receipt.is_file() or v05_receipt.read_text(encoding="utf-8").strip() != V05_FREEZE:
        raise LiveStop("V05 scientific freeze identity mismatch")

    authority_path = private_root / "live_v05/authority/live_execution_authority_APPROVED_v01.json"
    if not expected_authority_hash or not authority_path.is_file():
        raise LiveStop("Live execution is locked: exact authority is absent")
    if sha_file(authority_path) != expected_authority_hash:
        raise LiveStop("Live authority identity mismatch")
    authority = read_json(authority_path)
    exact = {
        "approval_scope": "ONE_BOUNDED_AUTOMATIC_SUMMARY_CHECKER_V05_SUCCESSOR_EXPERIMENT",
        "v05_freeze_sha256": V05_FREEZE,
        "live_overlay_freeze_sha256": expected_overlay_freeze,
        "public_commit_sha": expected_public_commit,
        "private_live_bundle_sha256": expected_bundle_hash,
        "maximum_requests": 44,
        "maximum_retries": 0,
        "maximum_probes": 0,
        "hard_neuron_cap": 25410,
        "maximum_additional_expenditure": "£0",
        "no_paid_fallback": True,
        "no_model_substitution": True,
        "no_account_switch": True,
    }
    for key, expected in exact.items():
        if authority.get(key) != expected:
            raise LiveStop(f"Live authority mismatch: {key}")
    return authority


def recognised_usage(body: bytes) -> dict[str, Any]:
    base = extract_recognised_usage(body)
    try:
        value = json.loads(body.decode("utf-8"))
        container = value.get("result") if isinstance(value, dict) and isinstance(value.get("result"), dict) else value
        provider = container.get("usage") if isinstance(container, dict) else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        provider = None
    if base.get("status") == "RECOGNISED" and isinstance(provider, dict):
        neurons = provider.get("neurons")
        if isinstance(neurons, (int, float)) and not isinstance(neurons, bool) and neurons >= 0:
            base["neurons"] = neurons
    return base


def text_completion(body: bytes) -> str:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("Provider body is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ContractError("Provider body must be a JSON object")
    container = value.get("result") if isinstance(value.get("result"), dict) else value
    try:
        content = container["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ContractError("Recognised choices[0].message.content is absent") from exc
    if not isinstance(content, str) or not content.strip():
        raise ContractError("Completion is empty or the wrong type")
    return content.strip()


def _evidence_text(rows: list[dict[str, str]]) -> str:
    return "\n\n".join(row["text"] for row in rows)


class LiveRunner:
    def __init__(
        self,
        private_root: Path,
        v05_root: Path,
        asset_root: Path,
        store: DurablePrivateState,
        transport: Any,
        counter: ExactTokenCounter,
        account_id: str,
        token: str,
    ):
        self.private_root = private_root
        self.v05_root = v05_root
        self.store = store
        self.transport = transport
        self.counter = counter
        self.account_id = account_id
        self.token = token
        self.checker_instruction = (v05_root / "immutable/instructions/gpt_oss_checker_v01.txt").read_text(encoding="utf-8")
        self.initial_instruction = (v05_root / "immutable/instructions/gemma_addendum_aligned_initial_v01.txt").read_text(encoding="utf-8")
        self.revision_instruction = (v05_root / "immutable/instructions/gemma_addendum_controlled_revision_v01.txt").read_text(encoding="utf-8")

    def _load_stage(self, stage: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        cases = read_json(self.v05_root / f"private/cases/{stage}_cases_model_facing_v01.json")["cases"]
        evidence = read_json(self.v05_root / f"private/evidence/{stage}_evidence_index_v01.json")["cases"]
        return cases, evidence

    def _load_focused(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        cases = read_json(self.v05_root / "private/diagnostics/focused_cases_model_facing_v01.json")["cases"]
        evidence = read_json(self.v05_root / "private/diagnostics/focused_evidence_index_v01.json")["cases"]
        return cases, evidence

    def _send(
        self,
        slot_id: str,
        execution_day: str,
        payload: dict[str, Any],
        case: dict[str, Any] | None,
        evidence: list[dict[str, str]] | None,
    ) -> dict[str, Any]:
        try:
            exact = self.counter.enforce(payload)
        except CountError as exc:
            raise LiveStop(str(exc)) from exc
        if payload["model"] == GPT_MODEL:
            conservative_input, output, neurons = 14_000, 2_560, CHECKER_NEURONS
        elif payload["model"] == GEMMA_MODEL:
            conservative_input, output, neurons = 16_000, 256, GEMMA_NEURONS
        else:
            raise LiveStop("Unexpected model ID")
        self.store.reserve_request(
            slot_id,
            execution_day,
            conservative_input,
            output,
            neurons,
            exact,
        )
        self.store.mark_transmission_started(slot_id)
        result = self.transport.send(payload, self.account_id, self.token)
        capture = {
            "schema_version": "stories-of-us-v05-bounded-private-provider-capture-v01",
            "slot_id": slot_id,
            "http_status": result.status,
            "safe_headers": result.headers,
            "transport_error": result.error,
            "uncertain": result.uncertain,
            "capture_truncated": result.truncated,
            "sanitised_bounded_body": sanitize_body(result.body, self.account_id, self.token),
            "captured_bytes": len(result.body),
        }
        usage = recognised_usage(result.body)
        self.store.save_response(slot_id, capture, usage)
        if result.uncertain or result.truncated or result.status != 200:
            raise LiveStop("Provider outcome is unusable or uncertain")
        if payload["model"] == GPT_MODEL:
            if case is None or evidence is None:
                raise LiveStop("Checker parse context is absent")
            candidate_response, _ = json_only_completion(result.body)
            authoritative = derive_authoritative_decision(case, evidence, candidate_response)
            parsed = {
                "slot_id": slot_id,
                "case_id": case["case_id"],
                "kind": "CHECKER",
                "candidate_summary_sha256": hashlib.sha256(case["candidate_summary"].encode("utf-8")).hexdigest(),
                "candidate_checker_response": candidate_response,
                "candidate_response_sha256": canonical_hash(candidate_response),
                "authoritative": authoritative,
                "provider_usage": usage,
                "exact_local_count": exact,
            }
        else:
            completion = text_completion(result.body)
            parsed = {
                "slot_id": slot_id,
                "case_id": slot_id.removeprefix("REV__"),
                "kind": "GEMMA_REVISION",
                "unedited_completion": completion,
                "completion_sha256": hashlib.sha256(completion.encode("utf-8")).hexdigest(),
                "provider_usage": usage,
                "exact_local_count": exact,
            }
        self.store.save_parsed(slot_id, parsed)
        return parsed

    def run_day0(self, utc_date: str) -> dict[str, Any]:
        state, _ = self.store.load()
        if state["stage"] != "NOT_STARTED":
            raise LiveStop("Focused diagnostics can start only from unused live state")
        cases, evidence = self._load_focused()
        for case in cases:
            rows = evidence[case["case_id"]]["paragraphs"]
            payload = checker_payload(case, rows, self.checker_instruction)
            self._send(f"FOCUS_CHECK__{case['case_id']}", "DAY_0_FOCUSED_DIAGNOSTICS", payload, case, rows)
        return {
            "operation": "day0-focused-diagnostics",
            "requests_completed": 9,
            "next_stage": "WAITING_FOCUSED_DIAGNOSTIC_REVIEW",
        }

    def run_day1(self, utc_date: str) -> dict[str, Any]:
        state, _ = self.store.load()
        if state["stage"] != "WAITING_FOCUSED_DIAGNOSTIC_REVIEW":
            raise LiveStop("Development is blocked until focused-diagnostic review")
        day0 = dt.date.fromisoformat(state["operation_dates"]["day0-focused-diagnostics"])
        if dt.date.fromisoformat(utc_date) <= day0:
            raise LiveStop("Day 1 requires a later UTC date")
        gate = evaluate_focused_review(self.private_root, self.v05_root)
        if not gate["gate_passed"]:
            raise LiveStop("Focused diagnostic gate failed; development is withheld")
        cases, evidence = self._load_stage("development")
        for case in cases:
            rows = evidence[case["case_id"]]["paragraphs"]
            payload = checker_payload(case, rows, self.checker_instruction)
            self._send(f"DEV_CHECK__{case['case_id']}", "DAY_1_DEVELOPMENT", payload, case, rows)
        return {"operation": "day1-development", "requests_completed": 15, "next_stage": "WAITING_DEVELOPMENT_REVIEW"}

    def run_day2(self, utc_date: str) -> dict[str, Any]:
        state, _ = self.store.load()
        if state["stage"] != "WAITING_DEVELOPMENT_REVIEW":
            raise LiveStop("Day 2 is blocked until the development review pause")
        day1 = dt.date.fromisoformat(state["operation_dates"]["day1-development"])
        if dt.date.fromisoformat(utc_date) <= day1:
            raise LiveStop("Day 2 requires a later UTC date")
        gate = evaluate_initial_review(self.private_root, self.v05_root, "development")
        if not gate["gate_passed"] or gate["eligible_corrections"] != ["D14"]:
            raise LiveStop("Frozen development gate failed; D14 is withheld")
        cases, evidence = self._load_stage("development")
        case = next(row for row in cases if row["case_id"] == "D14")
        rows = evidence["D14"]["paragraphs"]
        initial = read_json(self.private_root / "live_v05/results/parsed/DEV_CHECK__D14.json")
        correction = initial["candidate_checker_response"].get("correction")
        if not isinstance(correction, dict) or correction.get("eligible") is not True:
            raise LiveStop("D14 checker feedback is not eligible")
        reason = correction.get("instruction")
        if not isinstance(reason, str):
            raise LiveStop("D14 checker correction instruction is absent")
        payload = revision_payload(
            case,
            _evidence_text(rows),
            case["candidate_summary"],
            reason,
            self.initial_instruction,
            self.revision_instruction,
        )
        revised = self._send("REV__D14", "DAY_2_D14_CORRECTION", payload, None, None)
        recheck_case = copy.deepcopy(case)
        recheck_case["candidate_summary"] = revised["unedited_completion"]
        recheck_case["stage_context"] = "POST_REVISION"
        recheck_payload = checker_payload(recheck_case, rows, self.checker_instruction)
        self._send("RECHECK__D14", "DAY_2_D14_CORRECTION", recheck_payload, recheck_case, rows)
        return {"operation": "day2-d14-correction", "requests_completed": 2, "next_stage": "WAITING_D14_RECHECK_REVIEW"}

    def run_day3_initial(self, utc_date: str) -> dict[str, Any]:
        state, _ = self.store.load()
        if state["stage"] != "WAITING_D14_RECHECK_REVIEW":
            raise LiveStop("Evaluation is blocked until D14 complete-recheck review")
        day2 = dt.date.fromisoformat(state["operation_dates"]["day2-d14-correction"])
        if dt.date.fromisoformat(utc_date) <= day2:
            raise LiveStop("Day 3 requires a later UTC date")
        gate = evaluate_complete_recheck(
            self.private_root,
            "d14_complete_recheck_review_v01.json",
            "D14_COMPLETE_RECHECK",
            ["D14"],
        )
        if not gate["gate_passed"]:
            raise LiveStop("D14 complete recheck failed; evaluation is withheld")
        cases, evidence = self._load_stage("evaluation")
        for case in cases:
            rows = evidence[case["case_id"]]["paragraphs"]
            payload = checker_payload(case, rows, self.checker_instruction)
            self._send(f"EVAL_CHECK__{case['case_id']}", "DAY_3_EVALUATION", payload, case, rows)
        return {"operation": "day3-evaluation-initial", "requests_completed": 12, "next_stage": "WAITING_EVALUATION_REVIEW"}

    def run_day3_corrections(self, utc_date: str) -> dict[str, Any]:
        state, _ = self.store.load()
        if state["stage"] != "WAITING_EVALUATION_REVIEW":
            raise LiveStop("Evaluation corrections are blocked until initial review")
        if state["operation_dates"]["day3-evaluation-initial"] != utc_date:
            raise LiveStop("Evaluation corrections must use the same UTC allowance date")
        gate = evaluate_initial_review(self.private_root, self.v05_root, "evaluation")
        if not gate["gate_passed"]:
            raise LiveStop("Frozen initial evaluation gate failed; corrections are withheld")
        eligible = gate["eligible_corrections"]
        cases, evidence = self._load_stage("evaluation")
        by_id = {row["case_id"]: row for row in cases}
        requests = 0
        for case_id in eligible:
            case = by_id[case_id]
            rows = evidence[case_id]["paragraphs"]
            initial = read_json(self.private_root / f"live_v05/results/parsed/EVAL_CHECK__{case_id}.json")
            correction = initial["candidate_checker_response"].get("correction")
            if not isinstance(correction, dict) or correction.get("eligible") is not True:
                raise LiveStop(f"Checker feedback is not eligible for {case_id}")
            reason = correction.get("instruction")
            if not isinstance(reason, str):
                raise LiveStop(f"Checker correction instruction is absent for {case_id}")
            payload = revision_payload(
                case,
                _evidence_text(rows),
                case["candidate_summary"],
                reason,
                self.initial_instruction,
                self.revision_instruction,
            )
            revised = self._send(f"REV__{case_id}", "DAY_3_EVALUATION", payload, None, None)
            recheck_case = copy.deepcopy(case)
            recheck_case["candidate_summary"] = revised["unedited_completion"]
            recheck_case["stage_context"] = "POST_REVISION"
            recheck_payload = checker_payload(recheck_case, rows, self.checker_instruction)
            self._send(f"RECHECK__{case_id}", "DAY_3_EVALUATION", recheck_payload, recheck_case, rows)
            requests += 2
        return {
            "operation": "day3-evaluation-corrections",
            "eligible_case_ids": eligible,
            "requests_completed": requests,
            "next_stage": "WAITING_FINAL_PROTECTED_REVIEW",
        }


def actual_utc_date(value: str) -> None:
    try:
        supplied = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise LiveStop("UTC date must be ISO YYYY-MM-DD") from exc
    if os.environ.get("SOU_LOCAL_TEST_ONLY") != "1" and supplied != dt.datetime.now(dt.timezone.utc).date():
        raise LiveStop("Supplied UTC date differs from the runner UTC date")


def run(args: argparse.Namespace) -> dict[str, Any]:
    actual_utc_date(args.utc_date)
    account_id = os.environ.get("SOU_CLOUDFLARE_ACCOUNT_ID", "")
    token = os.environ.get("SOU_CLOUDFLARE_WORKERS_AI_TOKEN", "")
    # The workflow supplies one encrypted token value. Reusing it only for the
    # local confirmation check avoids a second stored copy and creates no state.
    validate_credentials(account_id, token, token)
    private_root = args.private_root.resolve()
    authority = verify_identity(
        private_root,
        args.expected_public_commit,
        args.actual_public_commit,
        args.expected_overlay_freeze,
        args.expected_bundle_sha256,
        args.expected_authority_sha256,
    )
    day_key = {
        "day0-focused-diagnostics": "DAY_0_FOCUSED_DIAGNOSTICS",
        "day1-development": "DAY_1_DEVELOPMENT",
        "day2-d14-correction": "DAY_2_D14_CORRECTION",
        "day3-evaluation-initial": "DAY_3_EVALUATION",
        "day3-evaluation-corrections": "DAY_3_EVALUATION",
    }[args.operation]
    if authority.get("authorised_execution_days", {}).get(day_key) is not True:
        raise LiveStop("Authority does not permit this UTC execution day")
    allowance = authority.get("allowance_status_by_day", {}).get(day_key)
    if allowance not in {"VERIFIED_SUFFICIENT", "OWNER_APPROVED_EXACT_EXPERIMENT_UNKNOWN_EXCEPTION"}:
        raise LiveStop("Daily allowance evidence or exact-experiment exception is absent")
    for field in (
        "workers_free_eligibility_currently_verified",
        "model_availability_currently_verified",
        "pricing_currently_verified",
        "interface_currently_verified",
        "private_evidence_route_currently_verified",
        "exact_tokenizer_counts_currently_verified",
    ):
        if authority.get(field) is not True:
            raise LiveStop(f"Authority prerequisite is false or absent: {field}")

    # Load every exact-count dependency before an operation lock or ledger is
    # created. A local dependency/configuration failure therefore consumes no
    # live state and cannot be confused with a transmitted request.
    counter = ExactTokenCounter(args.asset_root)
    backend = GitPersistence(private_root)
    store = DurablePrivateState(private_root, backend)
    transport = CloudflareChatTransport()
    runner = LiveRunner(
        private_root,
        args.v05_root,
        args.asset_root,
        store,
        transport,
        counter,
        account_id,
        token,
    )
    store.start_operation(args.operation, args.run_id, args.utc_date)
    try:
        if args.operation == "day0-focused-diagnostics":
            details = runner.run_day0(args.utc_date)
        elif args.operation == "day1-development":
            details = runner.run_day1(args.utc_date)
        elif args.operation == "day2-d14-correction":
            details = runner.run_day2(args.utc_date)
        elif args.operation == "day3-evaluation-initial":
            details = runner.run_day3_initial(args.utc_date)
        else:
            details = runner.run_day3_corrections(args.utc_date)
        private_result = {
            "schema_version": "stories-of-us-v05-live-operation-result-v01",
            "status": "REVIEW_REQUIRED",
            "details": details,
            "model_requests_are_real": True,
            "public_output_contains_private_content": False,
        }
        store.save_operation_result(args.operation, private_result)
        store.finish_operation(args.operation, details["next_stage"], args.utc_date)
        return {
            "status": "REVIEW_REQUIRED",
            "operation": args.operation,
            "requests_completed": details["requests_completed"],
            "next_stage": details["next_stage"],
            "private_results_persisted": True,
        }
    except (LiveStop, StateStop, SafetyStop, ReviewStop, ContractError, CountError) as exc:
        try:
            store.safety_stop(type(exc).__name__)
        except Exception:
            pass
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operation", choices=OPERATIONS, required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--v05-root", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--utc-date", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-public-commit", required=True)
    parser.add_argument("--actual-public-commit", required=True)
    parser.add_argument("--expected-overlay-freeze", required=True)
    parser.add_argument("--expected-bundle-sha256", required=True)
    parser.add_argument("--expected-authority-sha256", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = run(args)
        print(json.dumps(result, sort_keys=True))
    except Exception as exc:
        print(json.dumps({"status": "SAFETY_STOP", "reason_class": type(exc).__name__}, sort_keys=True))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
