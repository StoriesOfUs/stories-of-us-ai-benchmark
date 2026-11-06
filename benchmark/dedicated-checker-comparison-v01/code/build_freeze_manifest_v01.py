#!/usr/bin/env python3
"""Create the freeze manifest for execution-relevant package files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
included_roots = ("code", "evidence", "fixtures", "tests", "workflow_draft")
files = [ROOT / "README.md"]
for name in included_roots:
    files.extend(path for path in (ROOT / name).rglob("*") if path.is_file())
manifest_path = ROOT / "fixtures/freeze_manifest_v01.json"
files = [path for path in files if path != manifest_path and path.name != "execution_authority_APPROVED_v01.json"]
frozen = {
    str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(files)
}
result = {
    "schema_version": "stories-of-us-dedicated-checker-comparison-freeze-v01",
    "frozen_at": "2026-11-06",
    "status": "PREPARED_EXECUTION_LOCKED_CHECKER_RELIABILITY_UNTESTED",
    "package_name": "option_c_dedicated_checker_comparison_package_v01",
    "frozen_files": frozen,
    "source_fixture_hashes": {
        "development_cases": "95c3f7d120116d9cba7a3eed88fa8c161685552455201069479286d4ff4fbee7",
        "development_answer_key": "87a2c86bc2c227f022c928f3d6af60601d94af6938dab82ec382f46206ed1c75",
        "evaluation_cases": "9978613d661d9b510ec850cf874226a2806e75c012a6e34bc71f9501f7c1a014",
        "evaluation_answer_key": "4cf60dbda5fc31f3495a2c57f35f10fcb4b1fa9523bc6b7b377b8d0a4bec6ad0",
        "aapd_correction": "2b6578ea1b7706534515b7fcff38309ca820dc6fd41dc90b169ba9f3384d695e",
        "source_provenance": "4afa67e53b9ffa2fcdb540d657046273b16dfc60c0a833cb425b7dcf1244421e"
    },
    "case_counts": {
        "development_summaries": 4,
        "development_claims": 10,
        "reserved_evaluation_summaries": 12,
        "reserved_evaluation_claims": 29,
        "model_facing_input_records": 78
    },
    "execution_authorised": False,
    "execution_authority_file_in_freeze": False,
    "model_requests_during_preparation": 0,
    "installations_during_preparation": 0,
    "model_weight_downloads_during_preparation": 0,
    "permanent_documentation_changed": False
}
manifest_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(hashlib.sha256(manifest_path.read_bytes()).hexdigest())
