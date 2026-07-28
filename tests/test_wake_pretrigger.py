"""Wave 8A package F: the pre-trigger ring is bounded, in-memory only, and
wiped at every moment privacy requires."""

import unittest

import wake_pretrigger
from wake_pretrigger import PreTriggerRing, WakeHandoff, build_command_capture_detector

try:
    import numpy as np
except Exception:  # pragma: no cover - bare interpreter
    np = None

SR = 16000


def block(frames=1600, value=0.5):
    """One 100 ms block at 16 kHz. A plain list stands in for the ndarray so
    the bounding/lifecycle logic is testable without numpy."""
    return [value] * frames


class RingBoundsTests(unittest.TestCase):
    def test_empty_ring(self):
        ring = PreTriggerRing()
        self.assertEqual(ring.frame_count(), 0)
        self.assertEqual(ring.byte_size(), 0)
        self.assertEqual(ring.duration_ms(), 0.0)
        self.assertIsNone(ring.drain())

    def test_push_accumulates_until_the_window_is_full(self):
        ring = PreTriggerRing(max_ms=500, sample_rate=SR)
        ring.push(block(1600))  # 100 ms
        ring.push(block(1600))  # 200 ms
        self.assertEqual(ring.frame_count(), 3200)
        self.assertAlmostEqual(ring.duration_ms(), 200.0)

    def test_the_window_is_a_hard_time_bound(self):
        ring = PreTriggerRing(max_ms=300, sample_rate=SR)
        for _ in range(20):  # 2 s of audio into a 300 ms window
            ring.push(block(1600))
        self.assertLessEqual(ring.duration_ms(), 300.0)
        self.assertLessEqual(ring.frame_count(), int(0.3 * SR))

    def test_it_keeps_the_newest_audio_not_the_oldest(self):
        ring = PreTriggerRing(max_ms=200, sample_rate=SR)
        ring.push(block(1600, value=0.1))
        ring.push(block(1600, value=0.2))
        ring.push(block(1600, value=0.3))
        remaining = {c[0] for c in ring._chunks}
        self.assertNotIn(0.1, remaining)
        self.assertIn(0.3, remaining)

    def test_the_byte_ceiling_bounds_a_wrong_sample_rate(self):
        # A window computed against the wrong rate would otherwise let the
        # buffer grow far past its intended size.
        ring = PreTriggerRing(max_ms=60_000, sample_rate=SR, max_bytes=32 * 1024)
        for _ in range(200):
            ring.push(block(1600))
        self.assertLessEqual(ring.byte_size(), 32 * 1024 + 1600 * 4)

    def test_a_zero_length_window_retains_nothing(self):
        ring = PreTriggerRing(max_ms=0, sample_rate=SR)
        self.assertFalse(ring.push(block()))
        self.assertEqual(ring.frame_count(), 0)

    def test_a_zero_byte_ceiling_retains_nothing(self):
        ring = PreTriggerRing(max_bytes=0)
        self.assertFalse(ring.push(block()))
        self.assertEqual(ring.frame_count(), 0)

    def test_empty_chunks_are_ignored(self):
        ring = PreTriggerRing()
        self.assertFalse(ring.push([]))
        self.assertEqual(ring.frame_count(), 0)

    def test_a_single_oversized_chunk_is_kept_rather_than_silently_dropped(self):
        ring = PreTriggerRing(max_ms=100, sample_rate=SR, max_bytes=1024)
        self.assertTrue(ring.push(block(16000)))
        self.assertEqual(ring.frame_count(), 16000)

    def test_negative_bounds_are_clamped_not_trusted(self):
        ring = PreTriggerRing(max_ms=-5, sample_rate=-1, max_bytes=-10)
        self.assertEqual(ring.max_ms, 0.0)
        self.assertEqual(ring.sample_rate, 1)
        self.assertEqual(ring.max_bytes, 0)

    def test_stats_report_sizes_and_never_audio(self):
        ring = PreTriggerRing(max_ms=500, sample_rate=SR)
        ring.push(block(1600))
        stats = ring.stats()
        self.assertEqual(
            set(stats), {"chunks", "frames", "bytes", "duration_ms", "max_ms", "max_bytes"}
        )
        self.assertEqual(stats["chunks"], 1)
        self.assertEqual(stats["frames"], 1600)


class RingWipeTests(unittest.TestCase):
    def test_clear_empties_the_ring(self):
        ring = PreTriggerRing()
        ring.push(block())
        self.assertTrue(ring.clear())
        self.assertEqual(ring.frame_count(), 0)
        self.assertEqual(ring.byte_size(), 0)
        self.assertIsNone(ring.drain())

    def test_clear_is_idempotent(self):
        ring = PreTriggerRing()
        ring.push(block())
        ring.clear()
        self.assertFalse(ring.clear())

    def test_drain_also_clears_so_audio_lives_in_one_place(self):
        ring = PreTriggerRing()
        ring.push(block())
        ring.drain()
        self.assertEqual(ring.frame_count(), 0)
        self.assertIsNone(ring.drain())

    def test_the_ring_never_writes_anything_to_disk(self):
        # Structural guard: this module must stay free of persistence.
        import inspect

        source = inspect.getsource(wake_pretrigger)
        for forbidden in ("open(", "json.dump", "pickle", "np.save", "shutil"):
            self.assertNotIn(forbidden, source, f"{forbidden} would persist pre-trigger audio")


@unittest.skipIf(np is None, "numpy is required to concatenate the drained pre-roll")
class RingDrainTests(unittest.TestCase):
    def test_drain_returns_one_flat_float32_array_in_capture_order(self):
        ring = PreTriggerRing(max_ms=500, sample_rate=SR)
        ring.push(np.full((100, 1), 0.1, dtype=np.float32))
        ring.push(np.full((100, 1), 0.2, dtype=np.float32))
        audio = ring.drain()
        self.assertEqual(audio.shape, (200,))
        self.assertEqual(audio.dtype, np.float32)
        self.assertAlmostEqual(float(audio[0]), 0.1, places=5)
        self.assertAlmostEqual(float(audio[-1]), 0.2, places=5)

    def test_nbytes_is_used_for_real_arrays(self):
        ring = PreTriggerRing(max_ms=10_000, sample_rate=SR)
        ring.push(np.zeros((1000,), dtype=np.float32))
        self.assertEqual(ring.byte_size(), 4000)

    def test_undrainable_content_is_dropped_not_raised(self):
        ring = PreTriggerRing()
        ring.push(["not", "audio", "at", "all"])
        self.assertIsNone(ring.drain())
        self.assertEqual(ring.frame_count(), 0)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.handoff = WakeHandoff(ring=PreTriggerRing(max_ms=500, sample_rate=SR))

    def test_disarmed_by_default_and_retains_nothing(self):
        self.assertFalse(self.handoff.is_armed())
        self.assertFalse(self.handoff.on_chunk(block()))
        self.assertEqual(self.handoff.ring.frame_count(), 0)

    def test_armed_listening_retains_audio(self):
        self.handoff.arm()
        self.assertTrue(self.handoff.on_chunk(block()))
        self.assertGreater(self.handoff.ring.frame_count(), 0)

    def test_arming_wipes_whatever_was_there(self):
        self.handoff.arm()
        self.handoff.on_chunk(block())
        self.handoff.arm()
        self.assertEqual(self.handoff.ring.frame_count(), 0)

    def test_activation_hands_off_and_wipes(self):
        self.handoff.arm()
        self.handoff.on_chunk(block())
        self.assertGreater(self.handoff.ring.frame_count(), 0)
        self.handoff.activate()
        self.assertEqual(self.handoff.ring.frame_count(), 0)
        self.assertFalse(self.handoff.is_armed())

    def test_activation_with_nothing_buffered_returns_none(self):
        self.handoff.arm()
        self.assertIsNone(self.handoff.activate())

    def test_a_late_chunk_after_activation_cannot_repopulate_the_buffer(self):
        self.handoff.arm()
        self.handoff.on_chunk(block())
        self.handoff.activate()
        self.assertFalse(self.handoff.on_chunk(block()))
        self.assertEqual(self.handoff.ring.frame_count(), 0)

    def test_disarm_wipes_on_wake_disable(self):
        self.handoff.arm()
        self.handoff.on_chunk(block())
        self.assertTrue(self.handoff.disarm())
        self.assertEqual(self.handoff.ring.frame_count(), 0)
        self.assertFalse(self.handoff.is_armed())

    def test_disarm_is_safe_when_never_armed(self):
        self.assertFalse(self.handoff.disarm())

    def test_stats_include_the_armed_flag(self):
        self.handoff.arm()
        self.assertTrue(self.handoff.stats()["armed"])


class CommandCaptureDetectorTests(unittest.TestCase):
    def test_it_is_the_existing_trailing_silence_detector(self):
        from audio_gate import TrailingSilenceDetector

        self.assertIsInstance(build_command_capture_detector(), TrailingSilenceDetector)

    def test_defaults_are_the_wake_command_timings(self):
        detector = build_command_capture_detector()
        self.assertEqual(detector.silence_ms, float(wake_pretrigger.DEFAULT_COMMAND_SILENCE_MS))
        self.assertEqual(detector.min_recording_ms, float(wake_pretrigger.DEFAULT_COMMAND_MIN_MS))

    def test_it_reuses_the_profile_silence_thresholds(self):
        detector = build_command_capture_detector({"no_audio_min_rms": 0.02, "no_audio_min_peak": 0.05})
        self.assertEqual(detector.rms_threshold, 0.02)
        self.assertEqual(detector.peak_threshold, 0.05)

    def test_auto_stop_overrides_win_over_the_no_audio_gate(self):
        detector = build_command_capture_detector(
            {"no_audio_min_rms": 0.02, "auto_stop_rms_threshold": 0.008}
        )
        self.assertEqual(detector.rms_threshold, 0.008)

    def test_profile_can_retune_the_command_window(self):
        detector = build_command_capture_detector(
            {"wake_command_silence_ms": 1200, "wake_command_min_recording_ms": 300}
        )
        self.assertEqual(detector.silence_ms, 1200.0)
        self.assertEqual(detector.min_recording_ms, 300.0)

    def test_explicit_overrides_win_over_the_profile(self):
        detector = build_command_capture_detector({"wake_command_silence_ms": 1200}, silence_ms=400)
        self.assertEqual(detector.silence_ms, 400.0)

    def test_a_non_dict_config_is_tolerated(self):
        self.assertIsNotNone(build_command_capture_detector("nope"))

    def test_it_fires_once_after_speech_then_trailing_silence(self):
        detector = build_command_capture_detector(silence_ms=200, min_recording_ms=100)
        self.assertFalse(detector.update(0.4, 0.9, 100))   # speech
        self.assertFalse(detector.update(0.0, 0.0, 100))   # 100 ms silence
        self.assertTrue(detector.update(0.0, 0.0, 100))    # 200 ms silence -> stop
        self.assertFalse(detector.update(0.0, 0.0, 100))   # only ever fires once

    def test_leading_silence_never_ends_a_command(self):
        detector = build_command_capture_detector(silence_ms=200, min_recording_ms=100)
        for _ in range(20):
            self.assertFalse(detector.update(0.0, 0.0, 100))


if __name__ == "__main__":
    unittest.main()
