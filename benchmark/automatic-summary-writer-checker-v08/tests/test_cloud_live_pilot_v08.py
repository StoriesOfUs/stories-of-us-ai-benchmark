#!/usr/bin/env python3
"""Public-safe static and offline boundary tests for the V08 runtime."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from cloud_live_pilot_v08 import LiveStop, recognised_usage, verify_allowance_preflight  # noqa: E402
from exact_token_count_v08_runtime import GEMMA_MODEL, GPT_MODEL  # noqa: E402
from private_git_state_v08 import DurablePrivateState, StateStop  # noqa: E402


class MemoryPersistence:
    def persist(self, paths: list[Path], message: str) -> str:
        return hashlib.sha256(message.encode()).hexdigest()


class PublicRuntimeTests(unittest.TestCase):
    def test_models_and_limits_are_version_specific(self) -> None:
        self.assertEqual(GPT_MODEL, "@cf/openai/gpt-oss-120b")
        self.assertEqual(GEMMA_MODEL, "@cf/google/gemma-4-26b-a4b-it")

    def test_missing_v08_state_does_not_reuse_v07_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "live_v07/state").mkdir(parents=True)
            (root / "live_v07/state/experiment_state_v01.json").write_text("{}")
            store = DurablePrivateState(root, MemoryPersistence(), "freeze")
            with self.assertRaises(StateStop):
                store.load()

    def test_allowance_is_bound_to_account_and_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "live_v08/preflight/stage0-challenges_allowance_v01.json"
            target.parent.mkdir(parents=True)
            account = "account"
            target.write_text(json.dumps({
                "schema_version": "stories-of-us-v08-option-a-allowance-preflight-v01",
                "status": "VERIFIED_SUFFICIENT",
                "operation": "stage0-challenges",
                "execution_day": "DAY_0_CHALLENGES",
                "utc_date": "2026-11-20",
                "observed_at_utc": "2026-11-20T10:00:00+00:00",
                "workers_plan": "Workers Free",
                "direct_workers_ai_route_verified": True,
                "paid_or_credit_fallback_absent": True,
                "daily_free_allowance_neurons": 10000,
                "used_today_neurons": 0,
                "remaining_neurons": 10000,
                "required_reserved_neurons": 5239.256832,
                "sufficient_remaining_allowance": True,
                "account_id_sha256": hashlib.sha256(account.encode()).hexdigest(),
                "private_evidence_reference": "private receipt",
            }))
            self.assertEqual(verify_allowance_preflight(root, "stage0-challenges", "2026-11-20", account)["remaining_neurons"], 10000)
            with self.assertRaises(LiveStop):
                verify_allowance_preflight(root, "stage0-challenges", "2026-11-20", "different")

    def test_unrecognised_usage_stays_unknown(self) -> None:
        self.assertEqual(recognised_usage(b'{"choices":[]}')["status"], "UNKNOWN_MISSING")


if __name__ == "__main__":
    unittest.main()
