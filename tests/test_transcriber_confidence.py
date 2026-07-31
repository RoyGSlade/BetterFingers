"""Confidence provenance and live-path gate coverage for OR-05.

These tests use synthetic faster-whisper segment statistics and the real
dictation finalization path; no Whisper model is loaded.
"""

import unittest
from unittest.mock import patch

import numpy as np

import server
import utils
from transcriber import Transcriber


class _Segment:
    def __init__(self, avg_logprob, no_speech_prob, start=0.0, end=1.0):
        self.avg_logprob = avg_logprob
        self.no_speech_prob = no_speech_prob
        self.start = start
        self.end = end
        self.text = "synthetic transcript"


class _StreamingRecording:
    audio_data = np.ones(1600, dtype=np.float32)
    sample_rate = 16000
    duration_seconds = 1.0
    frame_count = 1600
    sample_count = 1600
    max_amplitude = 1.0
    rms_amplitude = 1.0
    stop_reason = "manual"


class _DummyEngine:
    def process_fast_lane(self, text, preset, **kwargs):
        del kwargs
        return f"{preset}: {text}"


class ConfidenceProvenanceTests(unittest.TestCase):
    def test_score_is_exp_of_mean_logprob_times_worst_no_speech_penalty(self):
        confidence = Transcriber._compute_confidence([
            _Segment(avg_logprob=-1.0, no_speech_prob=0.2),
        ])

        # exp(-1) is the model's rough token-probability proxy; the score is
        # then penalized by (1 - no_speech_prob), not interpreted as a log-prob.
        self.assertEqual(confidence, {
            "score": 0.294,
            "avg_logprob": -1.0,
            "no_speech_prob": 0.2,
        })

    def test_zero_logprob_is_a_real_high_confidence_value(self):
        confidence = Transcriber._compute_confidence([
            _Segment(avg_logprob=0.0, no_speech_prob=0.0),
        ])

        self.assertEqual(confidence["avg_logprob"], 0.0)
        self.assertEqual(confidence["score"], 1.0)


class LiveConfidenceGateTests(unittest.TestCase):
    def setUp(self):
        self._draft_queue = list(server.draft_queue)
        self._draft_recordings = dict(server.draft_recordings)
        self._pending_ids = list(server.pending_manual_send_ids)
        self._next_draft_id = server.next_draft_id
        server.draft_queue.clear()
        server.draft_recordings.clear()
        server.pending_manual_send_ids.clear()
        server.next_draft_id = 1
        server.cancellation_event.clear()

    def tearDown(self):
        server.draft_queue.clear()
        server.draft_queue.extend(self._draft_queue)
        server.draft_recordings.clear()
        server.draft_recordings.update(self._draft_recordings)
        server.pending_manual_send_ids.clear()
        server.pending_manual_send_ids.extend(self._pending_ids)
        server.next_draft_id = self._next_draft_id
        server.cancellation_event.clear()

    def test_live_streamed_confidence_reaches_draft_send_gate(self):
        statuses = []
        config = utils._profile_defaults()
        with patch.object(server, "get_engine", return_value=_DummyEngine()), \
             patch.object(server, "load_profile", return_value=config), \
             patch.object(
                 server,
                 "broadcast_status_threadsafe",
                 side_effect=lambda status, data=None: statuses.append((status, data or {})),
             ):
            draft = server.process_recording_result(
                _StreamingRecording(),
                streamed_text="feeding",
                streamed_confidence={
                    "score": 0.35,
                    "avg_logprob": -1.0,
                    "no_speech_prob": 0.0,
                },
                streamed_stt_ms=1.0,
            )

        self.assertEqual(draft["raw_text"], "feeding")
        self.assertEqual(draft["confidence"]["score"], 0.35)
        self.assertTrue(draft["force_review"])
        self.assertFalse(draft["auto_send_ok"])
        self.assertEqual(draft["force_review_reason"], "low_confidence")
        preview = next(data for status, data in statuses if status == "preview_ready")
        self.assertTrue(preview["force_review"])
        self.assertFalse(preview["auto_send_ok"])


if __name__ == "__main__":
    unittest.main()
