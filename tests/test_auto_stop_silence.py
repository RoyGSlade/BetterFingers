"""Hands-free auto-stop after trailing silence (Phase 10).

Off by default. A recording stops on its own once speech has been heard and then
trails into silence for the configured duration — without cutting off a slow
start or a brief mid-sentence pause.
"""

import threading
import unittest
from unittest.mock import patch

import numpy as np

import recorder as recorder_mod
import utils
from audio_gate import TrailingSilenceDetector
from hotkey_manager import HotkeyManager

SPEECH = (0.2, 0.5)   # (rms, peak) — above thresholds
SILENCE = (0.0, 0.0)  # (rms, peak) — below thresholds


def _hotkey_config():
    return {
        "hotkey": "f8",
        "force_stop_key": "",
        "manual_send_hotkey": "",
        "review_tts_hotkey": "ctrl+shift+space",
        "recording_mode": "toggle",
        "controller_enabled": False,
        "controller_binding": {
            "style": "single",
            "events": ["button:4"],
            "sequence_window_ms": 400,
            "axis_threshold": 0.6,
            "device_scope": "any_device",
        },
    }


class _DummyRecorder:
    def __init__(self):
        self.recording = False

    def start_recording(self, profile_name="Default"):
        del profile_name
        self.recording = True

    def stop_recording(self, stop_reason="manual"):
        del stop_reason
        self.recording = False
        return None


class TrailingSilenceDetectorTests(unittest.TestCase):
    def feed(self, detector, sequence, chunk_ms=100.0):
        fired_at = None
        for index, (rms, peak) in enumerate(sequence):
            if detector.update(rms, peak, chunk_ms) and fired_at is None:
                fired_at = index
        return fired_at

    def test_never_fires_without_speech(self):
        detector = TrailingSilenceDetector(silence_ms=300, min_recording_ms=0)
        self.assertIsNone(self.feed(detector, [SILENCE] * 50))

    def test_fires_after_trailing_silence(self):
        detector = TrailingSilenceDetector(
            silence_ms=300, min_recording_ms=0, rms_threshold=0.01, peak_threshold=0.02
        )
        # 200ms speech, then silence; fires when trailing silence hits 300ms.
        sequence = [SPEECH, SPEECH] + [SILENCE] * 5
        self.assertEqual(self.feed(detector, sequence, chunk_ms=100.0), 4)

    def test_short_pause_does_not_fire(self):
        detector = TrailingSilenceDetector(
            silence_ms=300, min_recording_ms=0, rms_threshold=0.01, peak_threshold=0.02
        )
        # 200ms pause (< 300ms), then speech resets it, then another 200ms pause.
        sequence = [SPEECH, SILENCE, SILENCE, SPEECH, SILENCE, SILENCE]
        self.assertIsNone(self.feed(detector, sequence, chunk_ms=100.0))

    def test_min_recording_gate_delays_fire(self):
        detector = TrailingSilenceDetector(
            silence_ms=100, min_recording_ms=1000, rms_threshold=0.01, peak_threshold=0.02
        )
        # Speech + 300ms silence: trailing silence satisfied but total < 1000ms.
        self.assertIsNone(self.feed(detector, [SPEECH] + [SILENCE] * 3, chunk_ms=100.0))
        # More silence pushes total past the minimum -> now it fires.
        self.assertIsNotNone(self.feed(detector, [SILENCE] * 10, chunk_ms=100.0))

    def test_fires_exactly_once(self):
        detector = TrailingSilenceDetector(
            silence_ms=100, min_recording_ms=0, rms_threshold=0.01, peak_threshold=0.02
        )
        hits = sum(1 for (rms, peak) in [SPEECH] + [SILENCE] * 10 if detector.update(rms, peak, 100.0))
        self.assertEqual(hits, 1)

    def test_disabled_when_silence_ms_non_positive(self):
        detector = TrailingSilenceDetector(silence_ms=0, min_recording_ms=0)
        self.assertIsNone(self.feed(detector, [SPEECH] + [SILENCE] * 20))

    def test_high_peak_counts_as_speech(self):
        # rms low but peak high -> not silent (both must be below to count as silence).
        detector = TrailingSilenceDetector(
            silence_ms=200, min_recording_ms=0, rms_threshold=0.01, peak_threshold=0.02
        )
        sequence = [SPEECH] + [(0.0, 0.5)] * 5
        self.assertIsNone(self.feed(detector, sequence, chunk_ms=100.0))

    def test_bad_input_is_ignored(self):
        detector = TrailingSilenceDetector(silence_ms=100, min_recording_ms=0)
        self.assertFalse(detector.update(None, None, 100.0))


class RecorderAutoStopTests(unittest.TestCase):
    def test_build_detector_disabled(self):
        rec = recorder_mod.AudioRecorder()
        self.assertIsNone(rec._build_auto_stop_detector({"auto_stop_after_silence_enabled": False}))

    def test_build_detector_uses_config_and_no_audio_fallback(self):
        rec = recorder_mod.AudioRecorder()
        detector = rec._build_auto_stop_detector(
            {
                "auto_stop_after_silence_enabled": True,
                "auto_stop_silence_ms": 800,
                "auto_stop_min_recording_ms": 500,
                "no_audio_min_rms": 0.004,
                "no_audio_min_peak": 0.02,
            }
        )
        self.assertIsNotNone(detector)
        self.assertEqual(detector.silence_ms, 800.0)
        self.assertEqual(detector.min_recording_ms, 500.0)
        self.assertEqual(detector.rms_threshold, 0.004)
        self.assertEqual(detector.peak_threshold, 0.02)

    def test_feed_triggers_callback_when_detector_fires(self):
        rec = recorder_mod.AudioRecorder(sample_rate=16000)
        fired = threading.Event()
        reasons = []

        def _cb(reason):
            reasons.append(reason)
            fired.set()

        rec.on_auto_stop = _cb
        rec._auto_stop_detector = TrailingSilenceDetector(
            silence_ms=1, min_recording_ms=0, rms_threshold=1.0, peak_threshold=1.0
        )
        # A loud chunk (speech) then a silent chunk (100ms) crosses the 1ms silence bar.
        rec._feed_auto_stop_detector(np.ones(1600, dtype=np.float32))
        rec._feed_auto_stop_detector(np.zeros(1600, dtype=np.float32))
        self.assertTrue(fired.wait(timeout=2.0))
        self.assertEqual(reasons, ["trailing_silence"])
        self.assertIsNone(rec._auto_stop_detector)  # cleared so it cannot re-fire


class HotkeyAutoStopTests(unittest.TestCase):
    @patch("hotkey_manager.load_profile")
    def test_on_auto_stop_stops_when_recording(self, load_profile):
        load_profile.return_value = _hotkey_config()
        completed = []
        manager = HotkeyManager(
            recorder=_DummyRecorder(),
            on_recording_complete_callback=lambda result: completed.append(result),
            on_recording_start_callback=lambda: None,
        )
        manager.is_recording = True
        manager.recording_start_time = 0.0
        manager._on_auto_stop("trailing_silence")
        self.assertFalse(manager.is_recording)
        self.assertEqual(manager.last_stop_reason, "trailing_silence")
        self.assertEqual(len(completed), 1)

    @patch("hotkey_manager.load_profile")
    def test_on_auto_stop_noop_when_not_recording(self, load_profile):
        load_profile.return_value = _hotkey_config()
        completed = []
        manager = HotkeyManager(
            recorder=_DummyRecorder(),
            on_recording_complete_callback=lambda result: completed.append(result),
            on_recording_start_callback=lambda: None,
        )
        manager.is_recording = False
        manager._on_auto_stop("trailing_silence")
        self.assertEqual(len(completed), 0)

    @patch("hotkey_manager.load_profile")
    def test_real_recorder_gets_callback_registered(self, load_profile):
        load_profile.return_value = _hotkey_config()
        rec = recorder_mod.AudioRecorder()
        manager = HotkeyManager(
            recorder=rec,
            on_recording_complete_callback=lambda _r: None,
            on_recording_start_callback=lambda: None,
        )
        self.assertEqual(rec.on_auto_stop, manager._on_auto_stop)


class AutoStopProfileTests(unittest.TestCase):
    def test_defaults_present(self):
        defaults = utils._profile_defaults()
        self.assertFalse(defaults["auto_stop_after_silence_enabled"])
        self.assertEqual(defaults["auto_stop_silence_ms"], 900)
        self.assertEqual(defaults["auto_stop_min_recording_ms"], 700)

    def test_sanitize_clamps(self):
        defaults = utils._profile_defaults()
        cfg = utils._sanitize_profile_values(
            {"auto_stop_silence_ms": 999999, "auto_stop_min_recording_ms": -5}, defaults
        )
        self.assertEqual(cfg["auto_stop_silence_ms"], 5000)
        self.assertEqual(cfg["auto_stop_min_recording_ms"], 0)

    def test_validate_accepts_and_rejects(self):
        utils.validate_profile_settings({"auto_stop_silence_ms": 1200, "auto_stop_min_recording_ms": 500})
        with self.assertRaises(ValueError):
            utils.validate_profile_settings({"auto_stop_silence_ms": 100})
        with self.assertRaises(ValueError):
            utils.validate_profile_settings({"auto_stop_min_recording_ms": 99999})


if __name__ == "__main__":
    unittest.main()
