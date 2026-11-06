#!/usr/bin/env python3
"""Dependency-only CPU smoke test. Never loads a model or tokenizer."""
from __future__ import annotations

import datetime as dt
import importlib.metadata
import os
import re
import resource
import subprocess
import sys
import traceback
from pathlib import Path

from smoke_controls_v01 import (
    AUTHORITY,
    LOCK,
    OUTPUTS,
    ROOT,
    account_paths,
    canonical_name,
    freeze_hash,
    load_json,
    postlock_authority_state,
    verify_freeze,
    write_json,
)


def peak_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value * 1024 if sys.platform.startswith("linux") else value)


def installed_versions() -> dict[str, str]:
    result: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            result[canonical_name(name)] = distribution.version
    return dict(sorted(result.items()))


def main() -> int:
    started = dt.datetime.now(dt.timezone.utc)
    failures: list[str] = []
    details: dict[str, object] = {}
    checked = verify_freeze()
    current_freeze = freeze_hash()
    authority = postlock_authority_state(AUTHORITY, LOCK, current_freeze)
    if authority["state"] != "APPROVED_AFTER_LOCK":
        failures.append(f"authority:{authority['reason']}")

    for variable in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        if os.environ.get(variable) != "1":
            failures.append(f"offline_flag_missing:{variable}")

    pip_check = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    details["pip_check"] = {
        "exit_code": pip_check.returncode,
        "stdout": pip_check.stdout.strip(),
        "stderr": pip_check.stderr.strip(),
    }
    if pip_check.returncode != 0:
        failures.append("pip_check_failed")

    versions = installed_versions()
    expected = load_json(ROOT / "fixtures/expected_versions_frozen_v01.json")
    expected_versions = expected["packages"]
    for name, version in expected_versions.items():
        if versions.get(name) != version:
            failures.append(f"version_mismatch:{name}:{versions.get(name)}:{version}")
    allowed = set(expected_versions) | set(expected["allowed_additional_distributions"])
    extras = sorted(set(versions) - allowed)
    if extras:
        failures.append("unexpected_distributions:" + ",".join(extras))
    forbidden = [
        name for name in versions
        if name in set(expected["forbidden_distribution_names"])
        or any(name.startswith(prefix) for prefix in expected["forbidden_distribution_prefixes"])
    ]
    if forbidden:
        failures.append("gpu_distributions_present:" + ",".join(sorted(forbidden)))

    import_results: dict[str, str] = {}
    torch_details: dict[str, object] = {}
    try:
        import torch
        import transformers
        import huggingface_hub
        import safetensors
        import sentencepiece
        import psutil
        from safetensors.torch import load_file
        from transformers import AutoConfig, AutoModelForSeq2SeqLM, AutoTokenizer, T5ForTokenClassification

        imported = {
            "torch": torch,
            "transformers": transformers,
            "huggingface_hub": huggingface_hub,
            "safetensors": safetensors,
            "sentencepiece": sentencepiece,
            "psutil": psutil,
            "safetensors.torch.load_file": load_file,
            "transformers.AutoConfig": AutoConfig,
            "transformers.AutoModelForSeq2SeqLM": AutoModelForSeq2SeqLM,
            "transformers.AutoTokenizer": AutoTokenizer,
            "transformers.T5ForTokenClassification": T5ForTokenClassification,
        }
        import_results = {name: "PASS" for name in imported}
        torch_details = {
            "version": torch.__version__,
            "version_cuda": torch.version.cuda,
            "cuda_is_available": bool(torch.cuda.is_available()),
        }
        if torch.__version__ != "2.15.0+cpu":
            failures.append(f"torch_version_not_cpu_build:{torch.__version__}")
        if torch.version.cuda is not None or torch.cuda.is_available():
            failures.append("torch_cuda_capability_detected")
    except Exception as error:  # preserve the exact bounded failure without a retry
        import_results["failure"] = f"{type(error).__name__}: {error}"
        import_results["traceback"] = traceback.format_exc()
        failures.append("required_import_failed")

    environment = Path(os.environ["SOU_ENV_ROOT"])
    pip_cache = Path(os.environ["PIP_CACHE_DIR"])
    hf_home = Path(os.environ["HF_HOME"])
    limits = load_json(ROOT / "fixtures/resource_limits_frozen_v01.json")
    resource_snapshot = {
        "environment": account_paths([environment]),
        "pip_cache": account_paths([pip_cache]),
        "huggingface_model_tokenizer_cache": account_paths([hf_home]),
        "package_checkout": account_paths([ROOT]),
        "combined_task_created": account_paths([environment, pip_cache, hf_home, ROOT]),
        "peak_rss_bytes": peak_rss_bytes(),
        "compressed_dependency_wheels_bytes_from_frozen_metadata": limits["compressed_dependency_wheels_bytes"],
    }
    write_json(OUTPUTS / "resource_snapshot_before_final_limits_v01.json", resource_snapshot)
    if resource_snapshot["environment"]["allocated_bytes_unique"] > limits["maximum_installed_environment_bytes"]:
        failures.append("installed_environment_exceeded_3_gib")
    if resource_snapshot["huggingface_model_tokenizer_cache"]["regular_file_logical_bytes_unique"] != 0:
        failures.append("model_or_tokenizer_cache_not_empty")
    if resource_snapshot["combined_task_created"]["allocated_bytes_unique"] > limits["maximum_combined_task_created_bytes"]:
        failures.append("combined_task_created_storage_exceeded")
    if resource_snapshot["peak_rss_bytes"] > limits["maximum_peak_rss_bytes"]:
        failures.append("peak_rss_exceeded")
    if limits["compressed_dependency_wheels_bytes"] > limits["maximum_compressed_dependency_wheels_bytes"]:
        failures.append("compressed_wheel_reservation_exceeded")

    (OUTPUTS / "resolved_environment_v01.txt").write_text(
        "".join(f"{name}=={version}\n" for name, version in versions.items()),
        encoding="utf-8",
    )
    finished = dt.datetime.now(dt.timezone.utc)
    result = {
        "schema_version": "stories-of-us-cpu-dependency-smoke-result-v01",
        "status": "PASS" if not failures else "FAIL",
        "started_at_utc": started.isoformat(),
        "finished_at_utc": finished.isoformat(),
        "elapsed_seconds": (finished - started).total_seconds(),
        "freeze_manifest_sha256": current_freeze,
        "frozen_files_checked": checked,
        "authority": authority,
        "pip_check": details["pip_check"],
        "installed_versions": versions,
        "unexpected_distributions": extras,
        "forbidden_gpu_distributions": sorted(forbidden),
        "imports": import_results,
        "torch": torch_details,
        "resources": resource_snapshot,
        "failures": failures,
        "model_or_tokenizer_downloads": 0,
        "model_loads": 0,
        "model_inference_computations": 0,
        "development_cases_consumed": 0,
        "evaluation_cases_consumed": 0,
        "retries": 0,
        "expenditure_gbp": 0,
    }
    write_json(OUTPUTS / "dependency_smoke_result_v01.json", result)
    print(result["status"])
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
