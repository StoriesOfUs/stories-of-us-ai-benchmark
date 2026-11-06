#!/usr/bin/env python3
"""Record installation and storage evidence before enforcing limits."""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
from pathlib import Path

from smoke_controls_v01 import ROOT, OUTPUTS, account_paths, load_json, write_json


parser = argparse.ArgumentParser()
parser.add_argument("--pip-exit-code", required=True, type=int)
args = parser.parse_args()

environment = Path(os.environ["SOU_ENV_ROOT"])
pip_cache = Path(os.environ["PIP_CACHE_DIR"])
hf_home = Path(os.environ["HF_HOME"])
limits = load_json(ROOT / "fixtures/resource_limits_frozen_v01.json")

environment_size = account_paths([environment])
pip_cache_size = account_paths([pip_cache])
hf_size = account_paths([hf_home])
package_size = account_paths([ROOT])
combined_size = account_paths([environment, pip_cache, hf_home, ROOT])
violations: list[str] = []
if args.pip_exit_code != 0:
    violations.append("dependency_installation_failed")
if environment_size["allocated_bytes_unique"] > limits["maximum_installed_environment_bytes"]:
    violations.append("installed_environment_exceeded_3_gib")
if hf_size["regular_file_logical_bytes_unique"] != 0:
    violations.append("model_or_tokenizer_cache_not_empty")
if combined_size["allocated_bytes_unique"] > limits["maximum_combined_task_created_bytes"]:
    violations.append("combined_task_created_storage_exceeded")

payload = {
    "schema_version": "stories-of-us-cpu-smoke-installation-snapshot-v01",
    "recorded_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    "status": "PASS" if not violations else "FAIL",
    "pip_exit_code": args.pip_exit_code,
    "compressed_dependency_wheels_bytes_from_frozen_metadata": limits["compressed_dependency_wheels_bytes"],
    "environment": environment_size,
    "pip_cache": pip_cache_size,
    "huggingface_model_tokenizer_cache": hf_size,
    "package_checkout": package_size,
    "combined_task_created": combined_size,
    "filesystem": {
        "total_bytes": shutil.disk_usage(ROOT).total,
        "used_bytes": shutil.disk_usage(ROOT).used,
        "free_bytes": shutil.disk_usage(ROOT).free
    },
    "limits": {
        "installed_environment_bytes": limits["maximum_installed_environment_bytes"],
        "model_tokenizer_download_bytes": limits["maximum_model_tokenizer_download_bytes"],
        "combined_task_created_bytes": limits["maximum_combined_task_created_bytes"]
    },
    "violations": violations,
    "accounting_note": "Allocated bytes count each inode once and do not follow snapshot symlinks; symlink target size is diagnostic only."
}
write_json(OUTPUTS / "installation_snapshot_v01.json", payload)
print(payload["status"])
if violations:
    raise SystemExit(1)
