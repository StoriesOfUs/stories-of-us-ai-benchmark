#!/usr/bin/env python3
"""Consume the one-use smoke-test authority before any installation."""
from __future__ import annotations

import datetime as dt
import os

from smoke_controls_v01 import AUTHORITY, LOCK, freeze_hash, preinstallation_authority_state, verify_freeze, write_json


def stop(message: str) -> None:
    raise SystemExit(f"SAFETY_STOP: {message}")


if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
    stop("manual workflow_dispatch required")
if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
    stop("repeat workflow attempt refused")
if os.environ.get("GITHUB_RUN_NUMBER") != "1":
    stop("repeat workflow execution refused")

verify_freeze()
current_freeze = freeze_hash()
decision = preinstallation_authority_state(AUTHORITY, LOCK, current_freeze)
if decision["state"] != "APPROVED":
    stop(f"{decision['state']}: {decision['reason']}")

write_json(LOCK, {
    "schema_version": "stories-of-us-cpu-smoke-one-use-lock-v01",
    "status": "CONSUMED_RESERVED_BEFORE_INSTALLATION",
    "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    "freeze_manifest_sha256": current_freeze,
    "github_run_id": os.environ.get("GITHUB_RUN_ID"),
    "github_run_number": os.environ.get("GITHUB_RUN_NUMBER"),
    "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
    "installation_attempts_reserved": 1,
    "retries_permitted": 0,
    "model_downloads_permitted": 0,
    "model_computations_permitted": 0
})
print("ONE_USE_AUTHORITY_CONSUMED")
