#!/usr/bin/env python3
"""Create the one-use execution lock before any installation or download."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
OUTPUTS = ROOT / "outputs"
MANIFEST = FIXTURES / "freeze_manifest_v02.json"
AUTHORITY = FIXTURES / "execution_authority_APPROVED_v02.json"
LOCK = OUTPUTS / "execution_consumed_lock_v02.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stop(message: str) -> None:
    print(f"SAFETY_STOP: {message}", file=sys.stderr)
    raise SystemExit(2)


if not MANIFEST.is_file() or not AUTHORITY.is_file():
    stop("execution authority or freeze manifest is absent")
if LOCK.exists():
    stop("repeat execution refused")
if os.environ.get("GITHUB_ACTIONS") != "true":
    stop("live execution is restricted to the frozen manual GitHub workflow")
if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
    stop("only the manual workflow_dispatch event is authorised")
if os.environ.get("GITHUB_WORKFLOW") != "Dedicated checker comparison V02 (manual, one use)":
    stop("unexpected workflow identity")
if os.environ.get("GITHUB_RUN_NUMBER") != "1" or os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
    stop("only the first run and first attempt of the new frozen workflow are authorised")

authority = json.loads(AUTHORITY.read_text(encoding="utf-8"))
manifest_hash = sha256(MANIFEST)
required = (
    "execution_authorised",
    "owner_approved_installation",
    "owner_approved_model_and_tokenizer_downloads",
    "owner_approved_bounded_inference",
    "owner_approved_public_github_workflow_commit_and_single_dispatch",
    "owner_confirmed_standard_public_runner_eligible_and_zero_cost",
)
if not all(authority.get(key) is True for key in required):
    stop("owner authority record is incomplete")
if authority.get("approved_freeze_manifest_sha256") != manifest_hash:
    stop("owner-approved freeze hash does not match")

OUTPUTS.mkdir(parents=True, exist_ok=True)
record = {
    "schema_version": "stories-of-us-dedicated-checker-one-use-lock-v02",
    "status": "CONSUMED_RESERVED_BEFORE_INSTALLATION",
    "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    "freeze_manifest_sha256": manifest_hash,
    "github_run_id": os.environ.get("GITHUB_RUN_ID"),
    "github_run_number": os.environ.get("GITHUB_RUN_NUMBER"),
    "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
}
temporary = LOCK.with_suffix(".tmp")
temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
os.chmod(temporary, 0o600)
temporary.replace(LOCK)
print("EXECUTION_LOCK_CONSUMED")
