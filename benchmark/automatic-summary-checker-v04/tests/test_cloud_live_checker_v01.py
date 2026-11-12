#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "runtime"), str(ROOT / "v04/code")]

from cloud_live_checker_v01 import recognised_usage, text_completion  # noqa: E402
from private_git_state_v01 import DurablePrivateState, StateStop, read_json  # noqa: E402


class MemoryPersistence:
    def __init__(self):
        self.calls = 0

    def persist(self, paths, message):
        self.calls += 1
        return f"synthetic-{self.calls}"


class PublicSafeRuntimeTests(unittest.TestCase):
    def test_response_usage_is_retained_independently(self):
        body = json.dumps({"result": {"choices": [{"message": {"content": "text"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 2}}}).encode()
        self.assertEqual("text", text_completion(body))
        self.assertEqual("RECOGNISED", recognised_usage(body)["status"])

    def test_consumed_reservation_precedes_transmission_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DurablePrivateState(Path(directory), MemoryPersistence())
            store.start_operation("day1-development", "synthetic", "2026-11-12")
            store.reserve_request("DEV_CHECK__SYNTHETIC", "DAY_1_DEVELOPMENT", 14000, 1536, 550.179552, {"exact": 1})
            before = read_json(store.ledger_path)["requests"][0]
            self.assertEqual("CONSUMED_BEFORE_TRANSMISSION", before["status"])
            store.mark_transmission_started("DEV_CHECK__SYNTHETIC")
            after = read_json(store.ledger_path)["requests"][0]
            self.assertEqual("TRANSMISSION_STARTED", after["status"])

    def test_concurrent_launch_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DurablePrivateState(Path(directory), MemoryPersistence())
            store.start_operation("day1-development", "one", "2026-11-12")
            with self.assertRaises(StateStop):
                store.start_operation("day1-development", "two", "2026-11-12")


if __name__ == "__main__":
    unittest.main(verbosity=2)
