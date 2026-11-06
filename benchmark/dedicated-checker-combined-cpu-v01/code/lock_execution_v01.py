#!/usr/bin/env python3
"""Consume the separately approved one-use authority before installation."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
import storage_and_lock_controls_v01 as controls  # noqa: E402


def main() -> int:
    try:
        checked = controls.verify_freeze()
        expected = controls.freeze_hash()
        if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
            raise controls.SafetyStop("manual workflow_dispatch required")
        if os.environ.get("GITHUB_RUN_NUMBER") != "1" or os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
            raise controls.SafetyStop("one-use workflow/run-attempt restriction failed")
        state = controls.authority_state(controls.AUTHORITY, controls.LOCK, expected)
        if state["state"] == "REPEAT_REFUSED":
            raise controls.SafetyStop("repeat execution refused")
        if state["state"] != "APPROVED":
            raise controls.SafetyStop(state["reason"])
        controls.write_json(controls.LOCK, {
            "schema_version": "stories-of-us-combined-cpu-checker-consumed-lock-v01",
            "status": "CONSUMED_RESERVED_BEFORE_INSTALLATION",
            "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "freeze_manifest_sha256": expected,
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_run_number": os.environ.get("GITHUB_RUN_NUMBER"),
            "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "maximum_retries": 0,
        })
        print(json.dumps({"status": "PASS", "frozen_files_checked": checked, "one_use_lock": str(controls.LOCK)}))
        return 0
    except controls.SafetyStop as error:
        print(f"SAFETY_STOP: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
