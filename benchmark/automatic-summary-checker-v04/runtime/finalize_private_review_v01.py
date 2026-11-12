#!/usr/bin/env python3
"""Validate the final protected recheck and close private V04 state.

This performs no model or account request. It is deliberately not exposed as a
workflow operation: the four public operations remain exactly frozen.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from private_git_state_v01 import DurablePrivateState, GitPersistence, read_json
from review_gate_v01 import evaluate_complete_recheck, evaluate_initial_review


class FinalizeStop(RuntimeError):
    pass


def finalize(private_root: Path, v04_root: Path) -> dict:
    store = DurablePrivateState(private_root, GitPersistence(private_root))
    state, ledger = store.load()
    if state.get("stage") != "WAITING_FINAL_PROTECTED_REVIEW":
        raise FinalizeStop("Final review is not eligible in the current state")
    if state.get("status") != "ACTIVE":
        raise FinalizeStop("Terminal or safety-stopped state cannot be finalised")

    initial = evaluate_initial_review(private_root, v04_root, "evaluation")
    eligible = initial["eligible_corrections"]
    if eligible:
        recheck = evaluate_complete_recheck(
            private_root,
            "evaluation_complete_recheck_review_v01.json",
            "EVALUATION_COMPLETE_RECHECK",
            eligible,
        )
        correction_gate = (
            recheck["gate_passed"]
            and recheck["cases_accepted_after_complete_recheck"] >= 2
        )
    else:
        recheck = {
            "gate_passed": True,
            "cases_reviewed": 0,
            "cases_accepted_after_complete_recheck": 0,
            "revision_performance": "NOT_TESTED",
        }
        correction_gate = True

    success = initial["gate_passed"] and correction_gate
    result = {
        "schema_version": "stories-of-us-v04-live-final-result-v01",
        "status": "BOUNDED_EXPERIMENT_PASS" if success else "BOUNDED_EXPERIMENT_FAIL",
        "checker_reliability": "BOUNDED_TEST_ONLY" if success else "NOT_ESTABLISHED",
        "evaluation_initial_gate": initial,
        "evaluation_complete_recheck_gate": recheck,
        "final_request_count": ledger["cumulative_requests"],
        "reserved_neurons": ledger["reserved_neurons"],
        "provider_usage_status": (
            "COMPLETE"
            if ledger["unknown_usage_requests"] == 0
            else "PARTIAL_UNKNOWN"
        ),
        "model_requests_made_by_this_finalizer": 0,
    }
    store.save_operation_result("final-protected-review", result)
    store.transition("COMPLETE" if success else "FAILED_FROZEN_GATE", {"status": "TERMINAL"})
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--v04-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = finalize(args.private_root.resolve(), args.v04_root.resolve())
        print(json.dumps({"status": result["status"]}, sort_keys=True))
    except Exception as exc:
        print(json.dumps({"status": "SAFETY_STOP", "reason_class": type(exc).__name__}, sort_keys=True))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
