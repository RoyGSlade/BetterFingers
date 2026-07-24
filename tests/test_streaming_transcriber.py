"""Streaming batch transcription: cutter segmentation + session ordering.

Model-free by construction: BatchCutter is pure numpy logic and
StreamingTranscriptionSession takes an injected transcribe_fn, so nothing here
touches Whisper. Sample rate 1000 Hz keeps the math readable (100 samples ==
100 ms).
"""

import threading
import time
import unittest

import numpy as np

from streaming_transcriber import (
    BatchCutter,
    StreamingTranscriptionSession,
    aggregate_confidence,
)

SR = 1000  # samples per second, so 100 samples == 100 ms


def speech(ms, amplitude=1.0):
    return np.full(int(ms), float(amplitude), dtype=np.float32)


def silence(ms):
    return np.zeros(int(ms), dtype=np.float32)


def make_cutter(**overrides):
    kwargs = dict(
        sample_rate=SR,
        min_batch_seconds=1.0,
        max_batch_seconds=3.0,
        silence_ms=300,
        rms_threshold=0.003,
        peak_threshold=0.015,
    )
    kwargs.update(overrides)
    return BatchCutter(**kwargs)


class BatchCutterTests(unittest.TestCase):
    def test_no_cut_before_min_duration(self):
        cutter = make_cutter()
        batches = []
        for _ in range(7):
            batches.extend(cutter.feed(speech(100)))
        self.assertEqual(batches, [])

    def test_cuts_at_trailing_silence_after_min_duration(self):
        cutter = make_cutter()
        batches = []
        for _ in range(7):
            batches.extend(cutter.feed(speech(100)))
        for _ in range(3):
            batches.extend(cutter.feed(silence(100)))
        # 1000 ms pending, 300 ms trailing silence -> exactly one cut of it all.
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].size, 1000)
        self.assertIsNone(cutter.flush())

    def test_silence_alone_never_triggers_the_pause_cut(self):
        cutter = make_cutter()
        batches = []
        for _ in range(15):  # 1.5 s of pure silence: past min, all trailing-silent
            batches.extend(cutter.feed(silence(100)))
        self.assertEqual(batches, [])

    def test_forced_cut_at_max_duration(self):
        cutter = make_cutter()
        batches = []
        for _ in range(30):
            batches.extend(cutter.feed(speech(100)))
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].size, 3000)
        self.assertIsNone(cutter.flush())

    def test_forced_cut_lands_on_quietest_tail_chunk(self):
        cutter = make_cutter()
        batches = []
        for i in range(30):
            # Index 26 is the quietest chunk in the trailing search window but
            # still loud enough to not count as silence.
            amp = 0.5 if i == 26 else 1.0
            batches.extend(cutter.feed(speech(100, amplitude=amp)))
        self.assertEqual(len(batches), 1)
        # Cut lands after index 26 -> 27 chunks in the batch, 3 remain pending.
        self.assertEqual(batches[0].size, 2700)
        tail = cutter.flush()
        self.assertIsNotNone(tail)
        self.assertEqual(tail.size, 300)

    def test_forced_cut_of_pure_silence_is_dropped(self):
        cutter = make_cutter()
        batches = []
        for _ in range(30):
            batches.extend(cutter.feed(silence(100)))
        self.assertEqual(batches, [])          # dropped, not returned
        self.assertIsNone(cutter.flush())      # and not still pending either

    def test_flush_returns_pending_tail_once(self):
        cutter = make_cutter()
        cutter.feed(speech(500))
        tail = cutter.flush()
        self.assertIsNotNone(tail)
        self.assertEqual(tail.size, 500)
        self.assertIsNone(cutter.flush())

    def test_empty_chunk_is_ignored(self):
        cutter = make_cutter()
        self.assertEqual(cutter.feed(np.array([], dtype=np.float32)), [])
        self.assertIsNone(cutter.flush())


class StreamingSessionTests(unittest.TestCase):
    def _make_transcribe_fn(self, texts=None, fail_on_call=None, calls=None):
        lock = threading.Lock()
        counter = {"n": 0}

        def fn(audio):
            with lock:
                counter["n"] += 1
                n = counter["n"]
            if calls is not None:
                calls.append((n, int(audio.size)))
            if fail_on_call is not None and n == fail_on_call:
                raise RuntimeError("synthetic transcription failure")
            text = texts[n - 1] if texts else f"t{n}"
            return text, {"score": 0.9, "avg_logprob": -0.1, "no_speech_prob": 0.05}

        return fn

    def test_batches_transcribed_in_order_and_joined(self):
        calls = []
        session = StreamingTranscriptionSession(
            self._make_transcribe_fn(calls=calls),
            sample_rate=SR,
            cutter=make_cutter(),
        )
        # 2 forced cuts (3 s each) during "recording", then a 500 ms tail.
        for _ in range(65):
            session.feed(speech(100))
        result = session.finalize(timeout=10.0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "t1 t2 t3")
        self.assertEqual(result["batches"], 3)
        self.assertEqual([size for _, size in calls], [3000, 3000, 500])
        self.assertEqual(result["confidence"]["score"], 0.9)

    def test_partial_callback_reports_cumulative_text(self):
        partials = []
        session = StreamingTranscriptionSession(
            self._make_transcribe_fn(),
            sample_rate=SR,
            cutter=make_cutter(),
            on_partial=lambda text, batches: partials.append((text, batches)),
        )
        for _ in range(65):
            session.feed(speech(100))
        session.finalize(timeout=10.0)
        self.assertEqual(partials[-1], ("t1 t2 t3", 3))

    def test_transcribe_failure_poisons_the_session(self):
        session = StreamingTranscriptionSession(
            self._make_transcribe_fn(fail_on_call=2),
            sample_rate=SR,
            cutter=make_cutter(),
        )
        for _ in range(65):
            session.feed(speech(100))
        result = session.finalize(timeout=10.0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["text"], "")

    def test_abort_discards_everything(self):
        session = StreamingTranscriptionSession(
            self._make_transcribe_fn(),
            sample_rate=SR,
            cutter=make_cutter(),
        )
        for _ in range(35):
            session.feed(speech(100))
        session.abort()
        result = session.finalize(timeout=10.0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["text"], "")

    def test_short_recording_yields_single_tail_batch(self):
        calls = []
        session = StreamingTranscriptionSession(
            self._make_transcribe_fn(calls=calls),
            sample_rate=SR,
            cutter=make_cutter(),
        )
        session.feed(speech(600))
        result = session.finalize(timeout=10.0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "t1")
        self.assertEqual([size for _, size in calls], [600])

    def test_empty_batch_text_is_skipped_in_join(self):
        session = StreamingTranscriptionSession(
            self._make_transcribe_fn(texts=["hello", "", "world"]),
            sample_rate=SR,
            cutter=make_cutter(),
        )
        for _ in range(65):
            session.feed(speech(100))
        result = session.finalize(timeout=10.0)
        self.assertEqual(result["text"], "hello world")


class AggregateConfidenceTests(unittest.TestCase):
    def test_duration_weighted_score_and_worst_no_speech(self):
        parts = [
            ({"score": 0.8, "avg_logprob": -0.2, "no_speech_prob": 0.1}, 2.0),
            ({"score": 0.4, "avg_logprob": -0.6, "no_speech_prob": 0.3}, 1.0),
        ]
        agg = aggregate_confidence(parts)
        self.assertAlmostEqual(agg["score"], 0.667, places=3)
        self.assertAlmostEqual(agg["avg_logprob"], -0.333, places=3)
        self.assertAlmostEqual(agg["no_speech_prob"], 0.3, places=3)

    def test_empty_and_none_parts_are_none_safe(self):
        self.assertEqual(
            aggregate_confidence([]),
            {"score": None, "avg_logprob": None, "no_speech_prob": None},
        )
        agg = aggregate_confidence([({"score": None, "avg_logprob": None, "no_speech_prob": None}, 1.0)])
        self.assertIsNone(agg["score"])
        self.assertIsNone(agg["avg_logprob"])
        self.assertIsNone(agg["no_speech_prob"])


if __name__ == "__main__":
    unittest.main()
