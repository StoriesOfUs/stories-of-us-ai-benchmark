#!/usr/bin/env python3
"""Record dependency installation state and exact sizes before guards."""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
import storage_and_lock_controls_v01 as controls  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--pip-exit-code", required=True, type=int)
args = parser.parse_args()

environment = Path(os.environ["SOU_ENV_ROOT"])
runtime_root = Path(os.environ["SOU_RUNTIME_ROOT"])
limits = controls.load_json(ROOT / "fixtures/resource_limits_frozen_v01.json")["storage"]
environment_size = controls.account_paths([environment])
runtime_size = controls.account_paths([runtime_root])
combined_size = controls.account_paths([environment, runtime_root, ROOT / "outputs"])
violations: list[str] = []
if args.pip_exit_code != 0:
    violations.append("dependency_installation_failed")
if environment_size["allocated_bytes_unique"] > limits["maximum_installed_environment_bytes"]:
    violations.append("installed_environment_exceeded_3_gib")
if combined_size["allocated_bytes_unique"] > limits["maximum_combined_task_created_bytes"]:
    violations.append("combined_task_created_storage_exceeded")

payload = {
    "schema_version": "stories-of-us-combined-cpu-checker-installation-snapshot-v01",
    "recorded_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    "status": "PASS" if not violations else "FAIL",
    "pip_exit_code": args.pip_exit_code,
    "environment_before_guard": environment_size,
    "runtime_before_model_download": runtime_size,
    "combined_before_guard": combined_size,
    "filesystem": {"total_bytes": shutil.disk_usage(ROOT).total, "used_bytes": shutil.disk_usage(ROOT).used, "free_bytes": shutil.disk_usage(ROOT).free},
    "limits": limits,
    "violations": violations,
    "accounting_note": "Allocated bytes count each inode once; hard links and snapshot symlinks do not double-count stored blobs. Symlink target size is diagnostic only."
}
controls.write_json(ROOT / "outputs/installation_snapshot_v01.json", payload)
print(payload["status"])
if violations:
    raise SystemExit(1)
