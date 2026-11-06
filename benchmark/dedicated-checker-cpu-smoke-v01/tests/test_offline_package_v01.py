#!/usr/bin/env python3
"""Offline-only package tests. No package install, model or network access."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("controls", ROOT / "code/smoke_controls_v01.py")
assert spec and spec.loader
controls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controls)


class CpuSmokeOfflineTests(unittest.TestCase):
    def valid_authority(self, freeze_hash: str) -> dict[str, object]:
        return {
            "execution_authorised": True,
            "owner_approved_cpu_wheel_installation": True,
            "owner_approved_single_public_runner_dispatch": True,
            "owner_approved_zero_model_downloads_and_inference": True,
            "owner_approved_zero_retries": True,
            "owner_approved_zero_cost": True,
            "owner_approved_documentation_closeout": True,
            "approved_freeze_manifest_sha256": freeze_hash,
        }

    def test_lock_is_complete_hashed_wheel_only_and_cpu_specific(self) -> None:
        rows = controls.parse_wheel_lock(ROOT / "fixtures/requirements_cpu_wheels_frozen_v01.txt")
        self.assertEqual(len(rows), 36)
        self.assertEqual(len({row["name"] for row in rows}), 36)
        torch = next(row for row in rows if row["name"] == "torch")
        self.assertIn("2.15.0%2Bcpu", torch["url"])
        self.assertEqual(torch["sha256"], "0955c7e3446326293f48af18fad67872fa31dee5a36a87690eb9e5be8b465be3")
        for row in rows:
            self.assertTrue(row["url"].startswith("https://"))
            self.assertTrue(row["url"].endswith(".whl"))
            self.assertNotIn("nvidia", row["name"])
            self.assertNotIn("cuda", row["name"])
            self.assertNotEqual(row["name"], "triton")

    def test_freeze_manifest_matches(self) -> None:
        self.assertGreater(controls.verify_freeze(), 10)

    def test_expected_versions_match_lock_names(self) -> None:
        rows = controls.parse_wheel_lock(ROOT / "fixtures/requirements_cpu_wheels_frozen_v01.txt")
        expected = controls.load_json(ROOT / "fixtures/expected_versions_frozen_v01.json")
        self.assertEqual({row["name"] for row in rows}, set(expected["packages"]))
        self.assertEqual(expected["packages"]["torch"], "2.15.0+cpu")

    def test_isolated_authority_states(self) -> None:
        freeze = "a" * 64
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            authority = base / "authority.json"
            lock = base / "lock.json"
            self.assertEqual(
                controls.preinstallation_authority_state(authority, lock, freeze)["state"],
                "LOCKED_NOT_AUTHORISED",
            )
            authority.write_text(json.dumps(self.valid_authority(freeze)), encoding="utf-8")
            self.assertEqual(
                controls.preinstallation_authority_state(authority, lock, freeze)["state"],
                "APPROVED",
            )
            lock.write_text(json.dumps({
                "status": "CONSUMED_RESERVED_BEFORE_INSTALLATION",
                "freeze_manifest_sha256": freeze,
            }), encoding="utf-8")
            self.assertEqual(
                controls.preinstallation_authority_state(authority, lock, freeze)["state"],
                "REPEAT_REFUSED",
            )
            self.assertEqual(
                controls.postlock_authority_state(authority, lock, freeze)["state"],
                "APPROVED_AFTER_LOCK",
            )

    def test_invalid_authority_states_fail_closed(self) -> None:
        freeze = "b" * 64
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            authority = base / "authority.json"
            lock = base / "lock.json"
            authority.write_text("not json", encoding="utf-8")
            self.assertEqual(controls.preinstallation_authority_state(authority, lock, freeze)["state"], "BLOCKED_INVALID_AUTHORITY")
            authority.write_text(json.dumps(self.valid_authority("c" * 64)), encoding="utf-8")
            self.assertEqual(controls.preinstallation_authority_state(authority, lock, freeze)["state"], "BLOCKED_INVALID_AUTHORITY")

    def test_symlink_and_hardlink_accounting_does_not_duplicate_blob(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            blob = root / "blobs/model.bin"
            blob.parent.mkdir()
            blob.write_bytes(b"x" * 4096)
            snapshot = root / "snapshots/revision/model.bin"
            snapshot.parent.mkdir(parents=True)
            snapshot.symlink_to(blob)
            hardlink = root / "hardlink.bin"
            os.link(blob, hardlink)
            result = controls.account_paths([root])
            self.assertEqual(result["regular_file_logical_bytes_unique"], 4096)
            self.assertEqual(result["symlink_count"], 1)
            self.assertEqual(result["symlink_target_logical_bytes_diagnostic_only"], 4096)

    def test_resource_limits_and_zero_model_scope(self) -> None:
        limits = controls.load_json(ROOT / "fixtures/resource_limits_frozen_v01.json")
        self.assertEqual(limits["maximum_workflow_runs"], 1)
        self.assertEqual(limits["maximum_retries"], 0)
        self.assertEqual(limits["maximum_job_minutes"], 15)
        self.assertEqual(limits["maximum_installed_environment_bytes"], 3221225472)
        self.assertEqual(limits["maximum_model_tokenizer_download_bytes"], 0)
        self.assertEqual((limits["model_loads"], limits["model_inference_computations"]), (0, 0))
        self.assertEqual((limits["development_cases"], limits["evaluation_cases"]), (0, 0))

    def test_workflow_is_manual_one_use_and_zero_retry(self) -> None:
        workflow = (ROOT / "workflow_draft/dedicated_checker_cpu_smoke_manual_v01.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("push:", workflow)
        self.assertIn("timeout-minutes: 15", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn("--retries 0", workflow)
        self.assertIn("--no-deps", workflow)
        self.assertIn("--no-index", workflow)
        self.assertIn("--require-hashes", workflow)
        self.assertIn("lock_execution_v01.py", workflow)
        self.assertNotIn("from_pretrained", workflow)
        lock_code = (ROOT / "code/lock_execution_v01.py").read_text(encoding="utf-8")
        self.assertIn('GITHUB_RUN_NUMBER") != "1"', lock_code)
        self.assertIn('GITHUB_RUN_ATTEMPT") != "1"', lock_code)
        self.assertIn('GITHUB_EVENT_NAME") != "workflow_dispatch"', lock_code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
