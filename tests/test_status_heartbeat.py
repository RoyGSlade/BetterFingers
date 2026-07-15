"""The status heartbeat keeps a long non-chunked LLM stage from looking frozen
(Phase 8 remnant): it re-broadcasts the stage status on an interval until stopped."""

import time
import unittest
from unittest.mock import patch

import server


class StatusHeartbeatTests(unittest.TestCase):
    def _collect(self, calls):
        return lambda status, payload=None: calls.append((status, payload))

    def test_broadcasts_periodically_then_stops(self):
        calls = []
        with patch.object(server, "broadcast_status_threadsafe", self._collect(calls)):
            heartbeat = server._StatusHeartbeat("rewriting", interval_s=0.2).start()
            # Poll until 2 ticks arrive instead of sleeping a fixed window —
            # loaded CI runners (macOS especially) tick late and made a fixed
            # 1.2s window flaky.
            deadline = time.time() + 10.0
            while time.time() < deadline and len(calls) < 2:
                time.sleep(0.05)
            heartbeat.stop()
            count_at_stop = len(calls)
            time.sleep(0.5)  # nothing should fire after stop()

        self.assertGreaterEqual(count_at_stop, 2)
        self.assertEqual(len(calls), count_at_stop)  # stopped cleanly
        status, payload = calls[0]
        self.assertEqual(status, "rewriting")
        self.assertTrue(payload.get("heartbeat"))
        self.assertIn("elapsed_ms", payload)

    def test_no_broadcast_before_first_interval(self):
        calls = []
        with patch.object(server, "broadcast_status_threadsafe", self._collect(calls)):
            heartbeat = server._StatusHeartbeat("rewriting", interval_s=5.0).start()
            time.sleep(0.1)
            heartbeat.stop()
        self.assertEqual(calls, [])

    def test_stop_is_idempotent(self):
        heartbeat = server._StatusHeartbeat("rewriting", interval_s=5.0).start()
        heartbeat.stop()
        heartbeat.stop()  # must not raise


if __name__ == "__main__":
    unittest.main()
