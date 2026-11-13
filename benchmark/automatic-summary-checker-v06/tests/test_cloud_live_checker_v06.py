#!/usr/bin/env python3
"""Public-safe smoke tests for the V06 runtime modules."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


RUNTIME = Path(__file__).resolve().parents[1] / "runtime"
sys.path.insert(0, str(RUNTIME))

from cloudflare_transport_v06 import TransportStop, sanitize_body, validate_credentials  # noqa: E402
from private_git_state_v06 import DurablePrivateState, StateStop, read_json  # noqa: E402


class MemoryPersistence:
    def persist(self, paths, message):
        return "a" * 64


class PublicRuntimeSmokeTests(unittest.TestCase):
    def test_credentials_and_redaction(self):
        account, token = "a" * 32, "synthetic-token"
        validate_credentials(account, token)
        self.assertNotIn(token, sanitize_body(token.encode(), account, token))
        with self.assertRaises(TransportStop):
            validate_credentials("bad", token)

    def test_reservation_precedes_transmission(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DurablePrivateState(Path(directory), MemoryPersistence(), "freeze")
            store.start_operation(
                "day0-regressions",
                "run",
                "2026-11-13",
                {
                    "operation": "day0-regressions",
                    "utc_date": "2026-11-13",
                    "receipt_sha256": "b" * 64,
                },
            )
            store.reserve_request("REGRESSION__TEST", "DAY_0_REGRESSIONS", {"exact": 1})
            _, ledger = store.load()
            self.assertEqual("CONSUMED_BEFORE_TRANSMISSION", ledger["requests"][0]["status"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
