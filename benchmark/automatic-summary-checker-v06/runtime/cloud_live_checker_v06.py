#!/usr/bin/env python3
"""Two-operation cloud runner for the execution-locked V06 diagnostic."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from case_loader_v06 import case_sets, evidence_for
from checker_core_v06 import ContractError, derive_authoritative_decision, extract_recognised_usage, json_only_completion
from payloads_v06 import checker_payload
from cloudflare_transport_v06 import CloudflareChatTransport, TransportStop, sanitize_body, validate_credentials
from exact_token_count_v06 import CountError, ExactTokenCounter
from private_git_state_v06 import DurablePrivateState, GitPersistence, StateStop, read_json
from review_gate_v06 import ReviewStop, canonical_hash, evaluate_stage_review


SCIENTIFIC_FREEZE = "6590545bfbfec58cb07317aa31ee471009dfe36d0c68be34ca49b29ad26655e0"
OPERATIONS = ("day0-regressions", "day1-fresh")
OPERATION_PREFLIGHTS = {
    "day0-regressions": ("DAY_0_REGRESSIONS", 2619.628416),
    "day1-fresh": ("DAY_1_FRESH", 5239.256832),
}


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
    manifest = private_root / "live_v06/bundle/live_private_bundle_manifest_v06.json"
    if not manifest.is_file() or sha_file(manifest) != expected_bundle_hash:
        raise LiveStop("Private bundle identity mismatch")
    _verify_manifest(private_root / "live_v06/bundle", manifest)
    overlay_receipt = private_root / "live_v06/bundle/live_overlay/recovery/overlay_freeze_sha256_v06.txt"
    if not overlay_receipt.is_file() or overlay_receipt.read_text(encoding="utf-8").strip() != expected_overlay_freeze:
        raise LiveStop("Overlay freeze identity mismatch")
    scientific_receipt = private_root / "live_v06/bundle/scientific_package/recovery/freeze_manifest_sha256_v06.txt"
    if not scientific_receipt.is_file() or scientific_receipt.read_text(encoding="utf-8").strip() != SCIENTIFIC_FREEZE:
        raise LiveStop("V06 scientific freeze identity mismatch")
    authority_path = private_root / "live_v06/authority/live_execution_authority_APPROVED_v01.json"
    if not expected_authority_hash or not authority_path.is_file():
        raise LiveStop("Live execution is locked: exact authority is absent")
    if sha_file(authority_path) != expected_authority_hash:
        raise LiveStop("Live authority identity mismatch")
    authority = read_json(authority_path)
    exact = {
        "approval_scope": "ONE_BOUNDED_AUTOMATIC_SUMMARY_CHECKER_V06_FOCUSED_DIAGNOSTIC_EXPERIMENT",
        "scientific_freeze_sha256": SCIENTIFIC_FREEZE,
        "live_overlay_freeze_sha256": expected_overlay_freeze,
        "public_commit_sha": expected_public_commit,
        "private_live_bundle_sha256": expected_bundle_hash,
        "maximum_requests": 12,
        "maximum_retries": 0,
        "maximum_probes": 0,
        "maximum_input_tokens": 168000,
        "maximum_output_and_reasoning_tokens": 36864,
        "hard_neuron_cap": 7859,
        "maximum_additional_expenditure": "£0",
        "allowance_policy": "OPTION_A_VERIFIED_SUFFICIENT_REQUIRED",
        "no_paid_fallback": True,
        "no_model_substitution": True,
        "no_account_switch": True,
    }
    for key, expected in exact.items():
        if authority.get(key) != expected:
            raise LiveStop(f"Live authority mismatch: {key}")
    return authority


def verify_allowance_preflight(
    private_root: Path,
    operation: str,
    utc_date: str,
    account_id: str,
) -> dict[str, Any]:
    """Require a fresh, account-bound Option A receipt for this operation."""
    day_key, required = OPERATION_PREFLIGHTS[operation]
    path = private_root / f"live_v06/preflight/{operation}_allowance_v01.json"
    if not path.is_file():
        raise LiveStop("Fresh Option A allowance evidence is absent")
    value = read_json(path)
    exact = {
        "schema_version": "stories-of-us-v06-option-a-allowance-preflight-v01",
        "status": "VERIFIED_SUFFICIENT",
        "operation": operation,
        "execution_day": day_key,
        "utc_date": utc_date,
        "workers_plan": "Workers Free",
        "direct_workers_ai_route_verified": True,
        "paid_or_credit_fallback_absent": True,
        "sufficient_remaining_allowance": True,
        "required_reserved_neurons": required,
        "account_id_sha256": hashlib.sha256(account_id.encode("utf-8")).hexdigest(),
    }
    for key, expected in exact.items():
        if value.get(key) != expected:
            raise LiveStop(f"Option A allowance evidence mismatch: {key}")
    observed = value.get("observed_at_utc")
    try:
        observed_at = dt.datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise LiveStop("Option A observation time is invalid") from exc
    if observed_at.tzinfo is None or observed_at.utcoffset() != dt.timedelta(0):
        raise LiveStop("Option A observation time is not UTC")
    if observed_at.date() != dt.date.fromisoformat(utc_date):
        raise LiveStop("Option A allowance evidence is stale")
    daily = value.get("daily_free_allowance_neurons")
    used = value.get("used_today_neurons")
    remaining = value.get("remaining_neurons")
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in (daily, used, remaining)):
        raise LiveStop("Option A allowance quantities are invalid")
    if min(daily, used, remaining) < 0 or abs((daily - used) - remaining) > 1e-6:
        raise LiveStop("Option A allowance quantities are inconsistent")
    if remaining + 1e-9 < required:
        raise LiveStop("Workers Free allowance is insufficient for this operation")
    if not isinstance(value.get("private_evidence_reference"), str) or not value["private_evidence_reference"].strip():
        raise LiveStop("Option A private evidence reference is absent")
    return {
        "schema_version": value["schema_version"],
        "operation": operation,
        "execution_day": day_key,
        "utc_date": utc_date,
        "observed_at_utc": observed,
        "receipt_sha256": sha_file(path),
        "remaining_neurons": remaining,
        "required_reserved_neurons": required,
    }


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


class LiveRunner:
    def __init__(self, private_root: Path, scientific_root: Path, store: DurablePrivateState, transport: Any, counter: ExactTokenCounter, account_id: str, token: str):
        self.private_root = private_root
        self.scientific_root = scientific_root
        self.store = store
        self.transport = transport
        self.counter = counter
        self.account_id = account_id
        self.token = token
        self.instruction = (scientific_root / "immutable/instructions/gpt_oss_checker_v06.txt").read_text(encoding="utf-8")

    def _send(self, slot_id: str, execution_day: str, case: dict[str, Any], evidence: list[dict[str, str]]) -> None:
        payload = checker_payload(case, evidence, self.instruction)
        exact = self.counter.enforce(payload)
        self.store.reserve_request(slot_id, execution_day, exact)
        self.store.mark_transmission_started(slot_id)
        result = self.transport.send(payload, self.account_id, self.token)
        capture = {
            "schema_version": "stories-of-us-v06-bounded-private-provider-capture-v01",
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
        self.store.save_parsed(slot_id, parsed)

    def run_regressions(self) -> dict[str, Any]:
        state, _ = self.store.load()
        if state["stage"] != "NOT_STARTED":
            raise LiveStop("Regression stage can start only from unused V06 state")
        cases = case_sets()["regression"]
        if len(cases) != 4:
            raise LiveStop("Frozen regression allocation mismatch")
        for case in cases:
            self._send(f"REGRESSION__{case['case_id']}", "DAY_0_REGRESSIONS", case, evidence_for(case))
        return {"operation": "day0-regressions", "requests_completed": 4, "next_stage": "WAITING_REGRESSION_REVIEW"}

    def run_fresh(self, utc_date: str) -> dict[str, Any]:
        state, _ = self.store.load()
        if state["stage"] != "WAITING_REGRESSION_REVIEW":
            raise LiveStop("Fresh diagnostics are blocked until regression review")
        day0 = dt.date.fromisoformat(state["operation_dates"]["day0-regressions"])
        if dt.date.fromisoformat(utc_date) <= day0:
            raise LiveStop("Fresh diagnostics require a later UTC date")
        gate = evaluate_stage_review(self.private_root, self.scientific_root, "regression")
        if not gate["gate_passed"]:
            raise LiveStop("Regression gate failed; fresh diagnostics are withheld")
        cases = case_sets()["fresh"]
        if len(cases) != 8:
            raise LiveStop("Frozen fresh allocation mismatch")
        for case in cases:
            self._send(f"FRESH__{case['case_id']}", "DAY_1_FRESH", case, evidence_for(case))
        return {"operation": "day1-fresh", "requests_completed": 8, "next_stage": "WAITING_FRESH_REVIEW"}


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
    validate_credentials(account_id, token)
    private_root = args.private_root.resolve()
    authority = verify_identity(
        private_root,
        args.expected_public_commit,
        args.actual_public_commit,
        args.expected_overlay_freeze,
        args.expected_bundle_sha256,
        args.expected_authority_sha256,
    )
    day_key = OPERATION_PREFLIGHTS[args.operation][0]
    if authority.get("authorised_execution_days", {}).get(day_key) is not True:
        raise LiveStop("Authority does not permit this execution day")
    for field in (
        "workers_free_eligibility_currently_verified", "model_availability_currently_verified",
        "pricing_currently_verified", "interface_currently_verified",
        "private_evidence_route_currently_verified", "exact_tokenizer_counts_currently_verified",
    ):
        if authority.get(field) is not True:
            raise LiveStop(f"Authority prerequisite is false or absent: {field}")
    allowance_preflight = verify_allowance_preflight(
        private_root, args.operation, args.utc_date, account_id
    )
    counter = ExactTokenCounter(args.asset_root)
    backend = GitPersistence(private_root)
    store = DurablePrivateState(private_root, backend, SCIENTIFIC_FREEZE)
    runner = LiveRunner(
        private_root, args.scientific_root, store, CloudflareChatTransport(), counter, account_id, token
    )
    store.start_operation(
        args.operation, args.run_id, args.utc_date, allowance_preflight
    )
    try:
        details = runner.run_regressions() if args.operation == "day0-regressions" else runner.run_fresh(args.utc_date)
        result = {
            "schema_version": "stories-of-us-v06-live-operation-result-v01",
            "status": "REVIEW_REQUIRED",
            "details": details,
            "model_requests_are_real": True,
            "public_output_contains_private_content": False,
        }
        store.save_operation_result(args.operation, result)
        store.finish_operation(args.operation, details["next_stage"], args.utc_date)
        return {
            "status": "REVIEW_REQUIRED",
            "operation": args.operation,
            "requests_completed": details["requests_completed"],
            "next_stage": details["next_stage"],
            "private_results_persisted": True,
        }
    except (LiveStop, StateStop, TransportStop, ReviewStop, ContractError, CountError) as exc:
        try:
            store.safety_stop(type(exc).__name__)
        except Exception:
            pass
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--operation", choices=OPERATIONS, required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--scientific-root", type=Path, required=True)
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
    try:
        print(json.dumps(run(parse_args()), sort_keys=True))
    except Exception as exc:
        print(json.dumps({"status": "SAFETY_STOP", "reason_class": type(exc).__name__}, sort_keys=True))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
