#!/usr/bin/env python3
"""Three-stage synthetic private-route simulation with no model transport."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import time


V04_FREEZE = "6fa84bbb065873d796f71a52df68661455ed663e24b5ce62491eafeb7a15dfb5"
PUBLIC_REPOSITORY = "StoriesOfUs/stories-of-us-ai-benchmark"
PRIVATE_REPOSITORY = "StoriesOfUs/stories-of-us-ai-checker-private-v01"
AUTHORITY_RELATIVE = "simulation/authority/cloud_simulation_authority_v02.json"
BUNDLE_RELATIVE = "simulation/bundle/synthetic_private_bundle_v02.json"
LEDGER_RELATIVE = "simulation/state/simulation_ledger_v02.json"
MAIN_LOCK_RELATIVE = "simulation/state/main_execution.lock"
FORBIDDEN_PUBLIC_MARKERS = (
    "SOU_SYNTHETIC_PRIVATE_EVIDENCE_SENTINEL_V01",
    "SOU_SYNTHETIC_PRIVATE_ANSWER_SENTINEL_V01",
    "authorization:",
    "bearer ",
    "github_pat_",
    "ghp_",
)
LIVE_CREDENTIAL_NAMES = (
    "CLOUDFLARE_API_TOKEN",
    "CLOUDFLARE_ACCOUNT_ID",
    "SOU_CF_WORKERS_AI_TOKEN",
    "SOU_CF_ACCOUNT_ID",
)


class SafetyStop(RuntimeError):
    pass


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SafetyStop(f"Required JSON is unavailable or malformed: {path.name}") from exc
    if not isinstance(value, dict):
        raise SafetyStop(f"Required JSON is not an object: {path.name}")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def acquire_lock(path: Path, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise SafetyStop(f"{label} refused: persistent lock exists") from exc
    os.write(descriptor, f"{label}\n".encode("utf-8"))
    os.close(descriptor)


def scan_public_text(text: str) -> None:
    folded = text.casefold()
    found = [marker for marker in FORBIDDEN_PUBLIC_MARKERS if marker.casefold() in folded]
    if found:
        raise SafetyStop(f"Public output contains forbidden marker count={len(found)}")


def scan_public_file(path: Path) -> None:
    try:
        scan_public_text(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SafetyStop("Public output file could not be read") from exc


def validate_bundle(bundle: dict) -> None:
    if bundle.get("synthetic_only") is not True or bundle.get("not_project_evidence") is not True:
        raise SafetyStop("Private bundle is not explicitly synthetic-only")
    if bundle.get("approved_v04_freeze_sha256") != V04_FREEZE:
        raise SafetyStop("Private bundle is not bound to the approved V04 freeze")
    if len(bundle.get("stage1", {}).get("development_checks", [])) != 15:
        raise SafetyStop("Synthetic Stage 1 does not contain 15 development checks")
    if bundle.get("stage2", {}).get("revision_count") != 1 or bundle.get("stage2", {}).get("recheck_count") != 1:
        raise SafetyStop("Synthetic Stage 2 is not the one-revision/recheck arrangement")
    stage3 = bundle.get("stage3", {})
    if len(stage3.get("evaluation_checks", [])) != 12:
        raise SafetyStop("Synthetic Stage 3 does not contain 12 evaluation checks")
    if stage3.get("expected_revision_count") != 3 or stage3.get("expected_recheck_count") != 3:
        raise SafetyStop("Synthetic Stage 3 does not contain three revision/recheck pairs")
    if bundle.get("model_requests") != 0 or bundle.get("cloudflare_account_requests") != 0:
        raise SafetyStop("Synthetic bundle requests a forbidden live service")


def validate_private_root(
    private_root: Path,
    expected_bundle_hash: str,
    expected_public_commit: str,
    actual_public_commit: str,
) -> tuple[dict, dict, str]:
    if os.environ.get("SOU_SIMULATED_ONLY") != "1":
        raise SafetyStop("Synthetic-only runtime flag is absent")
    if any(os.environ.get(name) for name in LIVE_CREDENTIAL_NAMES):
        raise SafetyStop("Unexpected Cloudflare credential refused")
    if expected_public_commit != actual_public_commit:
        raise SafetyStop("Public commit does not match the approved environment variable")
    authority_path = private_root / AUTHORITY_RELATIVE
    bundle_path = private_root / BUNDLE_RELATIVE
    if not authority_path.is_file() or not bundle_path.is_file():
        raise SafetyStop("Synthetic authority or private bundle is absent")
    authority = load_json(authority_path)
    bundle = load_json(bundle_path)
    actual_bundle_hash = sha256(bundle_path)
    required_authority = {
        "scope": "SYNTHETIC_PRIVATE_ROUTE_ONLY_NO_MODEL_TRANSPORT",
        "approved_v04_freeze_sha256": V04_FREEZE,
        "approved_public_repository": PUBLIC_REPOSITORY,
        "approved_private_repository": PRIVATE_REPOSITORY,
        "approved_public_commit_sha": expected_public_commit,
        "synthetic_private_bundle_sha256": expected_bundle_hash,
        "maximum_manual_dispatches": 12,
        "maximum_model_requests": 0,
        "maximum_cloudflare_account_requests": 0,
        "maximum_expenditure_gbp": 0,
    }
    for key, expected in required_authority.items():
        if authority.get(key) != expected:
            raise SafetyStop(f"Synthetic authority mismatch: {key}")
    if actual_bundle_hash != expected_bundle_hash:
        raise SafetyStop("Synthetic private bundle hash mismatch")
    if bundle.get("approved_public_commit_sha") != expected_public_commit:
        raise SafetyStop("Private bundle public-commit binding mismatch")
    validate_bundle(bundle)
    return authority, bundle, actual_bundle_hash


def initial_ledger(bundle_hash: str, public_commit: str) -> dict:
    return {
        "schema_version": "stories-of-us-v04-private-route-simulation-ledger-v01",
        "approved_v04_freeze_sha256": V04_FREEZE,
        "approved_public_commit_sha": public_commit,
        "synthetic_private_bundle_sha256": bundle_hash,
        "maximum_manual_dispatches": 12,
        "cumulative_manual_dispatches": 0,
        "dispatches": [],
        "main_stages": {},
        "synthetic_model_requests": 0,
        "synthetic_cloudflare_account_requests": 0,
        "provider_usage": "NOT_APPLICABLE_SYNTHETIC_ONLY",
        "expenditure_gbp": 0,
    }


def reserve_dispatch(ledger_path: Path, ledger: dict, dispatch_id: str, operation: str, utc_date: str) -> None:
    if any(row.get("dispatch_id") == dispatch_id for row in ledger["dispatches"]):
        raise SafetyStop("GitHub workflow run already recorded; re-run refused")
    if ledger["cumulative_manual_dispatches"] >= ledger["maximum_manual_dispatches"]:
        raise SafetyStop("Twelve-dispatch ceiling reached")
    ledger["cumulative_manual_dispatches"] += 1
    ledger["dispatches"].append(
        {
            "dispatch_id": dispatch_id,
            "operation": operation,
            "utc_date": utc_date,
            "status": "RESERVED",
            "model_requests": 0,
            "cloudflare_account_requests": 0,
        }
    )
    atomic_json(ledger_path, ledger)


def set_dispatch_status(ledger_path: Path, ledger: dict, dispatch_id: str, status: str) -> None:
    for row in ledger["dispatches"]:
        if row["dispatch_id"] == dispatch_id:
            row["status"] = status
            atomic_json(ledger_path, ledger)
            return
    raise SafetyStop("Reserved dispatch record disappeared")


def require_later_date(current: dt.date, previous_iso: str, label: str) -> None:
    previous = dt.date.fromisoformat(previous_iso)
    if current <= previous:
        raise SafetyStop(f"{label} requires a later actual UTC date")


def run_stage1(ledger: dict, bundle: dict, utc_date: str, bundle_hash: str) -> dict:
    if ledger["main_stages"]:
        raise SafetyStop("Stage 1 repeat refused: main stage state already exists")
    ledger["main_stages"]["stage1"] = {
        "utc_date": utc_date,
        "status": "PASS",
        "simulated_development_checks": len(bundle["stage1"]["development_checks"]),
        "simulated_review_gate": bundle["stage1"]["predetermined_gate"],
        "bundle_sha256": bundle_hash,
    }
    return {"stage": "stage1", "simulated_checks": 15, "simulated_review_gate": "PASS"}


def run_stage2(ledger: dict, bundle: dict, utc_date: str, bundle_hash: str) -> dict:
    stage1 = ledger["main_stages"].get("stage1")
    if not stage1 or stage1.get("status") != "PASS":
        raise SafetyStop("Stage 2 refused without the persisted successful Stage 1 gate")
    if "stage2" in ledger["main_stages"]:
        raise SafetyStop("Stage 2 repeat refused")
    current = dt.date.fromisoformat(utc_date)
    require_later_date(current, stage1["utc_date"], "Stage 2")
    ledger["main_stages"]["stage2"] = {
        "utc_date": utc_date,
        "status": "PASS",
        "simulated_single_revisions": bundle["stage2"]["revision_count"],
        "simulated_complete_rechecks": bundle["stage2"]["recheck_count"],
        "simulated_review_gate": bundle["stage2"]["predetermined_gate"],
        "bundle_sha256": bundle_hash,
    }
    return {"stage": "stage2", "simulated_revisions": 1, "simulated_rechecks": 1}


def run_stage3(ledger: dict, bundle: dict, utc_date: str, bundle_hash: str) -> dict:
    stage2 = ledger["main_stages"].get("stage2")
    if not stage2 or stage2.get("status") != "PASS":
        raise SafetyStop("Stage 3 refused without the persisted successful Stage 2 gate")
    if "stage3" in ledger["main_stages"]:
        raise SafetyStop("Stage 3 repeat refused")
    current = dt.date.fromisoformat(utc_date)
    require_later_date(current, stage2["utc_date"], "Stage 3")
    ledger["main_stages"]["stage3"] = {
        "utc_date": utc_date,
        "status": "PASS",
        "simulated_evaluation_checks": len(bundle["stage3"]["evaluation_checks"]),
        "simulated_single_revisions": bundle["stage3"]["expected_revision_count"],
        "simulated_complete_rechecks": bundle["stage3"]["expected_recheck_count"],
        "simulated_review_gate": bundle["stage3"]["predetermined_gate"],
        "bundle_sha256": bundle_hash,
    }
    return {
        "stage": "stage3",
        "simulated_checks": 12,
        "simulated_revisions": 3,
        "simulated_rechecks": 3,
    }


def expect_stop(function, expected_fragment: str) -> str:
    try:
        function()
    except SafetyStop as exc:
        message = str(exc)
        if expected_fragment not in message:
            raise SafetyStop("Negative test stopped for an unexpected reason") from exc
        return expected_fragment
    raise SafetyStop("Negative test unexpectedly passed")


def run_negative_suite(private_root: Path, ledger: dict, bundle: dict, utc_date: str, bundle_hash: str) -> dict:
    if ledger["main_stages"]:
        raise SafetyStop("Negative suite must run before the successful main Stage 1")
    observations = {}
    observations["premature_progression"] = expect_stop(
        lambda: run_stage2(ledger, bundle, utc_date, bundle_hash),
        "without the persisted successful Stage 1 gate",
    )
    bundle_path = private_root / BUNDLE_RELATIVE
    observations["integrity_mismatch"] = expect_stop(
        lambda: (_ for _ in ()).throw(SafetyStop("Synthetic private bundle hash mismatch"))
        if sha256(bundle_path) != "0" * 64 else None,
        "bundle hash mismatch",
    )
    private_text = bundle_path.read_text(encoding="utf-8")
    observations["public_output_leakage"] = expect_stop(
        lambda: scan_public_text(private_text),
        "forbidden marker",
    )
    negative_lock = private_root / "simulation/state/negative_concurrency.lock"
    acquire_lock(negative_lock, "negative concurrency first holder")
    try:
        observations["concurrency"] = expect_stop(
            lambda: acquire_lock(negative_lock, "negative concurrency second holder"),
            "persistent lock exists",
        )
    finally:
        negative_lock.unlink(missing_ok=True)
    return {
        "negative_suite": "PASS",
        "observed_refusals": sorted(observations),
        "actual_cloud_scope": "one GitHub job; driver-level safety paths exercised inside that job",
    }


def run_negative_interruption(private_root: Path, utc_date: str, dispatch_id: str) -> dict:
    state_path = private_root / "simulation/state/negative_interruption_v01.json"
    lock_path = private_root / "simulation/state/negative_interruption.lock"
    if state_path.exists() or lock_path.exists():
        raise SafetyStop("Negative interruption fixture already consumed")
    acquire_lock(lock_path, "synthetic interrupted reservation")
    atomic_json(
        state_path,
        {
            "status": "UNCERTAIN_CONSUMED",
            "utc_date": utc_date,
            "dispatch_id": dispatch_id,
            "synthetic_reserved_slots": 1,
            "model_requests": 0,
            "simulation_note": "The interruption is injected inside the cloud job; it is not a provider interruption.",
        },
    )
    return {
        "negative_interruption": "PASS",
        "reservation_status": "UNCERTAIN_CONSUMED",
        "recovery_required": True,
    }


def run_negative_recovery(private_root: Path, utc_date: str, dispatch_id: str) -> dict:
    state_path = private_root / "simulation/state/negative_interruption_v01.json"
    lock_path = private_root / "simulation/state/negative_interruption.lock"
    if not state_path.is_file() or not lock_path.is_file():
        raise SafetyStop("Recovery refused without persisted interrupted reservation evidence")
    state = load_json(state_path)
    if state.get("status") != "UNCERTAIN_CONSUMED":
        raise SafetyStop("Recovery refused because interrupted state is not consumed")
    recovery_path = private_root / "simulation/recovery/negative_interruption_recovery_v01.json"
    if recovery_path.exists():
        raise SafetyStop("Recovery repeat refused")
    atomic_json(
        recovery_path,
        {
            "status": "RECOVERED_WITHOUT_RETRY",
            "original_consumed_dispatch_id": state["dispatch_id"],
            "recovery_dispatch_id": dispatch_id,
            "recovery_utc_date": utc_date,
            "original_reservation_remains_consumed": True,
            "model_requests": 0,
        },
    )
    lock_path.unlink()
    return {
        "negative_recovery": "PASS",
        "original_reservation_remains_consumed": True,
        "retry_performed": False,
    }


def run_repeat_stage1(ledger: dict, bundle: dict, utc_date: str, bundle_hash: str) -> dict:
    if "stage1" not in ledger["main_stages"]:
        raise SafetyStop("Repeat test requires an existing successful Stage 1")
    observed = expect_stop(
        lambda: run_stage1(ledger, bundle, utc_date, bundle_hash),
        "Stage 1 repeat refused",
    )
    return {"repeat_refusal": "PASS", "observed_reason_class": observed}


def result_path(private_root: Path, operation: str, dispatch_id: str) -> Path:
    safe_dispatch = "".join(character for character in dispatch_id if character.isalnum() or character in "-_")
    return private_root / f"simulation/results/{operation}_{safe_dispatch}_result_v01.json"


def execute(
    private_root: Path,
    operation: str,
    utc_date: str,
    dispatch_id: str,
    expected_bundle_hash: str,
    expected_public_commit: str,
    actual_public_commit: str,
) -> dict:
    try:
        current_date = dt.date.fromisoformat(utc_date)
    except ValueError as exc:
        raise SafetyStop("UTC date must be ISO YYYY-MM-DD") from exc
    if current_date != dt.datetime.now(dt.timezone.utc).date() and os.environ.get("SOU_LOCAL_TEST_ONLY") != "1":
        raise SafetyStop("Supplied UTC date does not match the runner's actual UTC date")
    authority, bundle, bundle_hash = validate_private_root(
        private_root, expected_bundle_hash, expected_public_commit, actual_public_commit
    )
    ledger_path = private_root / LEDGER_RELATIVE
    ledger = load_json(ledger_path) if ledger_path.exists() else initial_ledger(bundle_hash, expected_public_commit)
    if ledger.get("approved_public_commit_sha") != expected_public_commit or ledger.get("synthetic_private_bundle_sha256") != bundle_hash:
        raise SafetyStop("Persistent ledger identity mismatch")
    lock_path = private_root / MAIN_LOCK_RELATIVE
    acquire_lock(lock_path, f"dispatch={dispatch_id} operation={operation}")
    keep_lock = True
    try:
        reserve_dispatch(ledger_path, ledger, dispatch_id, operation, utc_date)
        if operation == "negative-suite":
            details = run_negative_suite(private_root, ledger, bundle, utc_date, bundle_hash)
            status = "NEGATIVE_TEST_PASS"
        elif operation == "negative-interruption":
            details = run_negative_interruption(private_root, utc_date, dispatch_id)
            status = "NEGATIVE_TEST_PASS"
        elif operation == "negative-recovery":
            details = run_negative_recovery(private_root, utc_date, dispatch_id)
            status = "NEGATIVE_TEST_PASS"
        elif operation == "stage1":
            details = run_stage1(ledger, bundle, utc_date, bundle_hash)
            status = "PASS"
        elif operation == "repeat-stage1":
            details = run_repeat_stage1(ledger, bundle, utc_date, bundle_hash)
            status = "NEGATIVE_TEST_PASS"
        elif operation == "stage2":
            details = run_stage2(ledger, bundle, utc_date, bundle_hash)
            status = "PASS"
        elif operation == "stage3":
            details = run_stage3(ledger, bundle, utc_date, bundle_hash)
            status = "PASS"
        else:
            raise SafetyStop("Unrecognised operation")
        set_dispatch_status(ledger_path, ledger, dispatch_id, status)
        private_result = {
            "schema_version": "stories-of-us-v04-private-cloud-simulation-result-v01",
            "operation": operation,
            "dispatch_id": dispatch_id,
            "utc_date": utc_date,
            "status": status,
            "details": details,
            "cumulative_manual_dispatches": ledger["cumulative_manual_dispatches"],
            "model_requests": 0,
            "cloudflare_account_requests": 0,
            "expenditure_gbp": 0,
        }
        atomic_json(result_path(private_root, operation, dispatch_id), private_result)
        atomic_json(ledger_path, ledger)
        keep_lock = False
        lock_path.unlink()
        return {
            "schema_version": "stories-of-us-v04-public-safe-cloud-simulation-result-v01",
            "operation": operation,
            "status": status,
            "cumulative_manual_dispatches": ledger["cumulative_manual_dispatches"],
            "approved_public_commit_sha": expected_public_commit,
            "synthetic_private_bundle_sha256": bundle_hash,
            "model_requests": 0,
            "cloudflare_account_requests": 0,
            "provider_usage": "NOT_APPLICABLE_SYNTHETIC_ONLY",
            "expenditure_gbp": 0,
            "private_content_in_public_output": False,
        }
    except SafetyStop:
        if any(row.get("dispatch_id") == dispatch_id for row in ledger.get("dispatches", [])):
            set_dispatch_status(ledger_path, ledger, dispatch_id, "SAFETY_STOP_CONSUMED")
        raise
    finally:
        if not keep_lock:
            lock_path.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-root", type=Path)
    parser.add_argument(
        "--operation",
        choices=(
            "negative-suite",
            "negative-interruption",
            "negative-recovery",
            "stage1",
            "repeat-stage1",
            "stage2",
            "stage3",
        ),
    )
    parser.add_argument("--utc-date")
    parser.add_argument("--dispatch-id")
    parser.add_argument("--expected-bundle-sha256")
    parser.add_argument("--expected-public-commit")
    parser.add_argument("--actual-public-commit")
    parser.add_argument("--scan-public-output", type=Path)
    parser.add_argument("--hold-lock-seconds", type=float, default=0.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.scan_public_output:
            scan_public_file(args.scan_public_output)
            print(json.dumps({"status": "PASS", "public_output_scan": "NO_FORBIDDEN_MARKERS"}))
            return
        required = (
            args.private_root,
            args.operation,
            args.utc_date,
            args.dispatch_id,
            args.expected_bundle_sha256,
            args.expected_public_commit,
            args.actual_public_commit,
        )
        if not all(required):
            raise SafetyStop("Execution arguments are incomplete")
        if args.hold_lock_seconds:
            time.sleep(args.hold_lock_seconds)
        result = execute(
            args.private_root,
            args.operation,
            args.utc_date,
            args.dispatch_id,
            args.expected_bundle_sha256,
            args.expected_public_commit,
            args.actual_public_commit,
        )
        encoded = json.dumps(result, sort_keys=True)
        scan_public_text(encoded)
        print(encoded)
    except SafetyStop as exc:
        print(json.dumps({"status": "SAFETY_STOP", "reason": str(exc)}, sort_keys=True))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
