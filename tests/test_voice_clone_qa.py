import os
import tempfile
import unittest
import wave

import numpy as np

import voice_clone_qa
from voice_clone_qa import (
    check_clipping,
    check_duration,
    check_file,
    check_noise_floor,
    check_silence_ratio,
    evaluate_sample,
)


def _tone(seconds, sample_rate=24000, amplitude=0.3, freq=220):
    t = np.linspace(0, seconds, int(seconds * sample_rate), endpoint=False)
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _write_wav(path, audio, sample_rate=24000):
    pcm16 = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm16.tobytes())


class DurationTests(unittest.TestCase):
    def test_too_short_rejected(self):
        ok, msg = check_duration(_tone(0.5), 24000)
        self.assertFalse(ok)
        self.assertIn("short", msg.lower())

    def test_too_long_rejected(self):
        ok, msg = check_duration(np.zeros(24000 * 200, dtype=np.float32), 24000)
        self.assertFalse(ok)
        self.assertIn("long", msg.lower())

    def test_valid_duration_ok(self):
        ok, msg = check_duration(_tone(5), 24000)
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_zero_sample_rate_treated_as_zero_duration(self):
        ok, _ = check_duration(_tone(5), 0)
        self.assertFalse(ok)


class NoiseFloorTests(unittest.TestCase):
    def test_silent_sample_rejected(self):
        ok, msg = check_noise_floor(np.zeros(24000 * 5, dtype=np.float32))
        self.assertFalse(ok)
        self.assertIn("silent", msg.lower())

    def test_empty_rejected(self):
        ok, msg = check_noise_floor(np.array([]))
        self.assertFalse(ok)

    def test_normal_tone_ok(self):
        ok, _ = check_noise_floor(_tone(3))
        self.assertTrue(ok)


class ClippingTests(unittest.TestCase):
    def test_heavily_clipped_rejected(self):
        arr = np.full(24000 * 3, 1.0, dtype=np.float32)
        ok, msg = check_clipping(arr)
        self.assertFalse(ok)
        self.assertIn("clip", msg.lower())

    def test_clean_tone_ok(self):
        ok, _ = check_clipping(_tone(3))
        self.assertTrue(ok)

    def test_empty_ok(self):
        ok, _ = check_clipping(np.array([]))
        self.assertTrue(ok)


class SilenceRatioTests(unittest.TestCase):
    def test_mostly_silent_rejected(self):
        arr = np.zeros(24000 * 10, dtype=np.float32)
        arr[:2400] = 0.3  # only 10% has signal
        ok, msg = check_silence_ratio(arr)
        self.assertFalse(ok)
        self.assertIn("silence", msg.lower())

    def test_continuous_tone_ok(self):
        ok, _ = check_silence_ratio(_tone(5))
        self.assertTrue(ok)

    def test_empty_ok(self):
        ok, _ = check_silence_ratio(np.array([]))
        self.assertTrue(ok)


class EvaluateSampleTests(unittest.TestCase):
    def test_valid_sample_passes_with_no_warnings(self):
        ok, warnings = evaluate_sample(_tone(5), 24000)
        self.assertTrue(ok)
        self.assertEqual(warnings, [])

    def test_too_short_is_hard_blocker(self):
        ok, warnings = evaluate_sample(_tone(0.5), 24000)
        self.assertFalse(ok)
        self.assertTrue(warnings)

    def test_clipping_is_soft_warning_not_hard_blocker(self):
        # Long enough & loud enough to pass duration/noise, but clipped.
        arr = np.full(24000 * 5, 1.0, dtype=np.float32)
        ok, warnings = evaluate_sample(arr, 24000)
        self.assertTrue(ok)
        self.assertTrue(any("clip" in w.lower() for w in warnings))

    def test_multiple_issues_all_reported(self):
        ok, warnings = evaluate_sample(_tone(0.5), 24000)
        self.assertFalse(ok)
        self.assertGreaterEqual(len(warnings), 1)


class CheckFileTests(unittest.TestCase):
    def test_valid_wav_file_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sample.wav")
            _write_wav(path, _tone(3), 24000)
            ok, warnings = check_file(path)
            self.assertTrue(ok)
            self.assertEqual(warnings, [])

    def test_stereo_wav_downmixed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "stereo.wav")
            mono = _tone(3)
            pcm16 = np.clip(mono * 32767.0, -32768, 32767).astype(np.int16)
            stereo = np.repeat(pcm16, 2)  # interleaved L/R, same signal both channels
            with wave.open(path, "wb") as handle:
                handle.setnchannels(2)
                handle.setsampwidth(2)
                handle.setframerate(24000)
                handle.writeframes(stereo.tobytes())
            ok, warnings = check_file(path)
            self.assertTrue(ok)
            self.assertEqual(warnings, [])

    def test_missing_file_fails_gracefully(self):
        ok, warnings = check_file("/nonexistent/path/does-not-exist.wav")
        self.assertFalse(ok)
        self.assertTrue(warnings)

    def test_corrupt_file_fails_gracefully(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.wav")
            with open(path, "wb") as handle:
                handle.write(b"not actually a wav file")
            ok, warnings = check_file(path)
            self.assertFalse(ok)
            self.assertTrue(warnings)


if __name__ == "__main__":
    unittest.main()
