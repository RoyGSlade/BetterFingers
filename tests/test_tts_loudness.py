"""Read-aloud loudness envelope for the overlay face's lip-sync.

backend/tts/loudness.py turns an audio buffer into a 30 fps 0..1 envelope;
ReviewTTSEngine reports it through on_audio_level just before each buffer
plays (server.py broadcasts it as draft_tts_level).
"""

import unittest
from unittest.mock import patch

import numpy as np

from backend.tts.loudness import ENVELOPE_FPS, loudness_envelope
from backend.tts.tts_engine import ReviewTTSEngine

SR = 24000


def tone(seconds, amp, sr=SR, freq=220.0):
    t = np.arange(int(seconds * sr)) / sr
    return amp * np.sin(2 * np.pi * freq * t)


class LoudnessEnvelopeTests(unittest.TestCase):
    def test_frame_count_matches_duration(self):
        env = loudness_envelope(tone(1.0, 0.5), SR)
        self.assertEqual(env["fps"], ENVELOPE_FPS)
        self.assertEqual(len(env["envelope"]), 30)
        self.assertAlmostEqual(env["duration"], 1.0, places=3)

    def test_loud_then_silent_then_loud(self):
        audio = np.concatenate([tone(0.5, 0.6), np.zeros(int(0.5 * SR)), tone(0.5, 0.6)])
        env = loudness_envelope(audio, SR)["envelope"]
        self.assertGreater(min(env[2:13]), 0.8)       # speech is open
        self.assertEqual(max(env[17:28]), 0.0)        # the pause is shut, not amplified noise
        self.assertGreater(min(env[32:43]), 0.8)

    def test_quiet_voice_moves_the_mouth_as_much_as_a_loud_one(self):
        quiet = loudness_envelope(tone(0.5, 0.05), SR)["envelope"]
        loud = loudness_envelope(tone(0.5, 0.8), SR)["envelope"]
        self.assertAlmostEqual(max(quiet), max(loud), places=1)

    def test_values_are_bounded_and_compact(self):
        rng = np.random.default_rng(1)
        env = loudness_envelope(rng.standard_normal(SR * 2) * 0.3, SR)["envelope"]
        self.assertTrue(all(0.0 <= v <= 1.0 for v in env))
        self.assertTrue(all(round(v, 2) == v for v in env))

    def test_degenerate_input(self):
        self.assertEqual(loudness_envelope([], SR)["envelope"], [])
        self.assertEqual(loudness_envelope(tone(0.2, 0.5), 0)["envelope"], [])
        self.assertEqual(set(loudness_envelope(np.zeros(SR), SR)["envelope"]), {0.0})

    def test_stereo_is_mixed_down(self):
        stereo = np.stack([tone(0.5, 0.5), tone(0.5, 0.5)], axis=1)
        self.assertEqual(len(loudness_envelope(stereo, SR)["envelope"]), 15)


class EngineReportsLevelTests(unittest.TestCase):
    def test_level_is_reported_before_each_buffer_plays(self):
        engine = ReviewTTSEngine()
        events = []
        engine.on_audio_level = lambda env: events.append(("level", len(env["envelope"])))
        with patch.object(engine, "_play_audio", side_effect=lambda *a, **k: events.append(("play",))):
            engine._play_with_level(tone(1.0, 0.5), SR)
            engine._play_with_level(tone(0.5, 0.5), SR)
        self.assertEqual(events, [("level", 30), ("play",), ("level", 15), ("play",)])

    def test_no_listener_and_failing_listener_never_block_playback(self):
        engine = ReviewTTSEngine()
        with patch.object(engine, "_play_audio") as play:
            engine._play_with_level(tone(0.2, 0.5), SR)  # no listener
            engine.on_audio_level = lambda env: (_ for _ in ()).throw(RuntimeError("boom"))
            engine._play_with_level(tone(0.2, 0.5), SR)  # listener raises
        self.assertEqual(play.call_count, 2)


if __name__ == "__main__":
    unittest.main()
