#!/usr/bin/env python3
"""Validate and durably push a protected review submission.

This helper performs no model request. Review content stays in the private
repository and is never emitted to stdout.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from private_git_state_v01 import GitPersistence, StateStop, atomic_json, read_json


NAMES = {
    "DEVELOPMENT_INITIAL": "development_initial_review_v01.json",
    "D14_COMPLETE_RECHECK": "d14_complete_recheck_review_v01.json",
    "EVALUATION_INITIAL": "evaluation_initial_review_v01.json",
    "EVALUATION_COMPLETE_RECHECK": "evaluation_complete_recheck_review_v01.json",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--submission", type=Path, required=True)
    args = parser.parse_args()
    root = args.private_root.resolve()
    value = read_json(args.submission.resolve())
    stage = value.get("stage")
    if stage not in NAMES:
        raise StateStop("Protected review stage is absent or invalid")
    if value.get("reviewer_status") not in {"CODEX_ASSISTED", "HUMAN_VERIFIED"}:
        raise StateStop("Protected reviewer status is absent or invalid")
    if value.get("answer_key_excluded_from_model_inputs") is not True:
        raise StateStop("Protected review must attest answer-key isolation")
    cases = value.get("cases")
    if not isinstance(cases, list) or not cases:
        raise StateStop("Protected review case records are absent")
    destination = root / "live_v04/reviews" / NAMES[stage]
    if destination.exists():
        raise StateStop("Protected review submission already exists")
    atomic_json(destination, value)
    commit = GitPersistence(root).persist(
        [destination], f"v04 protected review {stage.lower()}"
    )
    print(json.dumps({"status": "REVIEW_SAVED", "stage": stage, "commit": commit}, sort_keys=True))


if __name__ == "__main__":
    main()
