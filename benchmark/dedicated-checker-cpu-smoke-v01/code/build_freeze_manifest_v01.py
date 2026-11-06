#!/usr/bin/env python3
"""Build the deterministic CPU-smoke freeze manifest."""
from __future__ import annotations

import json
from pathlib import Path

from smoke_controls_v01 import ROOT, FIXTURES, sha256_file


manifest_path = FIXTURES / "freeze_manifest_v01.json"
authority_name = "execution_authority_APPROVED_v01.json"
included: list[Path] = [ROOT / "README.md"]
for folder in (ROOT / "code", ROOT / "fixtures", ROOT / "tests", ROOT / "workflow_draft", ROOT / "evidence"):
    included.extend(path for path in folder.rglob("*") if path.is_file())
included = [
    path for path in included
    if path != manifest_path and path.name != authority_name and "__pycache__" not in path.parts
]
payload = {
    "schema_version": "stories-of-us-cpu-dependency-smoke-freeze-v01",
    "frozen_at": "2026-11-06",
    "frozen_files": {
        str(path.relative_to(ROOT)): sha256_file(path)
        for path in sorted(set(included))
    },
    "excluded_mutable_paths": [
        "fixtures/execution_authority_APPROVED_v01.json",
        "outputs/",
        "reports/",
        "recovery/"
    ]
}
manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(sha256_file(manifest_path))
