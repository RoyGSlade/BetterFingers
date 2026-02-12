import unittest

import numpy as np

from audio_gate import should_block_for_no_audio
from recorder import RecordingResult


class AudioGateTests(unittest.TestCase):
    def _result(self, duration=1.0, peak=0.2, rms=0.05, samples=16000):
        return RecordingResult(
            audio_data=np.zeros(samples, dtype=np.float32),
            sample_rate=16000,
            duration_seconds=duration,
            frame_count=10,
            sample_count=samples,
            max_amplitude=peak,
            rms_amplitude=rms,
            stop_reason="manual",
        )

    def test_blocks_short_clip(self):
        result = self._result(duration=0.1, peak=0.1, rms=0.02)
        blocked, reasons = should_block_for_no_audio(result, "hello", {})
        self.assertTrue(blocked)
        self.assertTrue(any("clip_too_short" in r for r in reasons))

    def test_blocks_silent_clip(self):
        result = self._result(duration=1.0, peak=0.001, rms=0.0002)
        blocked, reasons = should_block_for_no_audio(result, "something", {})
        self.assertTrue(blocked)
        self.assertTrue(any("near_silent" in r for r in reasons))

    def test_blocks_empty_transcript(self):
        result = self._result(duration=1.0, peak=0.2, rms=0.05)
        blocked, reasons = should_block_for_no_audio(result, "   ", {})
        self.assertTrue(blocked)
        self.assertIn("empty_transcript", reasons)

    def test_allows_good_audio_and_text(self):
        result = self._result(duration=1.5, peak=0.4, rms=0.08)
        blocked, reasons = should_block_for_no_audio(result, "Valid sentence", {})
        self.assertFalse(blocked)
        self.assertEqual(reasons, [])


if __name__ == "__main__":
    unittest.main()

