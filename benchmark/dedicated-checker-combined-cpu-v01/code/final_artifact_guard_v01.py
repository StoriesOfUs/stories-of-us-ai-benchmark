#!/usr/bin/env python3
"""Enforce the concise-output limit without touching model/runtime caches."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
import storage_and_lock_controls_v01 as controls  # noqa: E402

limits = controls.load_json(ROOT / "fixtures/resource_limits_frozen_v01.json")["storage"]
measured = controls.account_paths([ROOT / "outputs"])
controls.write_json(ROOT / "outputs/artifact_storage_v01.json", measured)
if measured["allocated_bytes_unique"] > limits["maximum_saved_artifacts_bytes"]:
    raise SystemExit("SAFETY_STOP: saved artifact limit exceeded")
print("PASS")
