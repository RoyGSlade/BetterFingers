import unittest
from unittest.mock import patch

import numpy as np

import server


class BroadcastRecordingAmplitudeTests(unittest.TestCase):
    def setUp(self):
        server._last_amplitude_broadcast = 0.0

    def test_broadcasts_rms_amplitude(self):
        calls = []
        chunk = np.array([1.0, -1.0, 1.0, -1.0], dtype=np.float32)
        with patch.object(
            server, "broadcast_status_threadsafe",
            side_effect=lambda status, data=None: calls.append((status, data)),
        ):
            server._broadcast_recording_amplitude(chunk, 16000)
        self.assertEqual(len(calls), 1)
        status, data = calls[0]
        self.assertEqual(status, "recording")
        self.assertAlmostEqual(data["amplitude"], 1.0, places=5)

    def test_throttles_rapid_calls(self):
        calls = []
        chunk = np.array([0.5, -0.5], dtype=np.float32)
        with patch.object(
            server, "broadcast_status_threadsafe",
            side_effect=lambda status, data=None: calls.append((status, data)),
        ):
            server._broadcast_recording_amplitude(chunk, 16000)
            server._broadcast_recording_amplitude(chunk, 16000)
        self.assertEqual(len(calls), 1)

    def test_broadcasts_again_after_interval_elapses(self):
        calls = []
        chunk = np.array([0.5, -0.5], dtype=np.float32)
        with patch.object(
            server, "broadcast_status_threadsafe",
            side_effect=lambda status, data=None: calls.append((status, data)),
        ):
            server._broadcast_recording_amplitude(chunk, 16000)
            server._last_amplitude_broadcast -= 1.0  # simulate elapsed time
            server._broadcast_recording_amplitude(chunk, 16000)
        self.assertEqual(len(calls), 2)

    def test_empty_chunk_reports_zero(self):
        calls = []
        chunk = np.array([], dtype=np.float32)
        with patch.object(
            server, "broadcast_status_threadsafe",
            side_effect=lambda status, data=None: calls.append((status, data)),
        ):
            server._broadcast_recording_amplitude(chunk, 16000)
        self.assertEqual(calls[0][1]["amplitude"], 0.0)


class BroadcastWatchdogTimeoutTests(unittest.TestCase):
    def test_broadcasts_warning_status(self):
        calls = []
        with patch.object(
            server, "broadcast_status_threadsafe",
            side_effect=lambda status, data=None: calls.append((status, data)),
        ):
            server._broadcast_watchdog_timeout()
        self.assertEqual(len(calls), 1)
        status, data = calls[0]
        self.assertEqual(status, "watchdog_timeout_warning")
        self.assertIn("message", data)


if __name__ == "__main__":
    unittest.main()
