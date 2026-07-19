"""Tests for Transcriber.transcribe_structured (F2.2): the additive frozen
TranscriptionResult API, verified against the legacy tuple/text callers it
sits alongside. No real model or audio dependency — WhisperModel is mocked."""
import contextlib
import unittest
from unittest.mock import patch

import numpy as np

from backend.domain.contracts import TimedSegment, TranscriptionResult, to_dict
from transcriber import Transcriber


class _DummySegment:
    def __init__(self, text, start=0.0, end=0.0, avg_logprob=-0.1, no_speech_prob=0.01):
        self.start = start
        self.end = end
        self.text = text
        self.avg_logprob = avg_logprob
        self.no_speech_prob = no_speech_prob


class _DummyWhisperModel:
    def __init__(self, segments):
        self._segments = segments

    def transcribe(self, _audio, beam_size=5, hotwords=None):
        del beam_size, hotwords
        return list(self._segments), None


@contextlib.contextmanager
def _make_transcriber(segments):
    # WhisperModel must stay patched for the whole test body, not just
    # construction: preload=False means the model isn't actually built until
    # the first transcribe() call, which happens after this helper would
    # otherwise have already returned and torn the patch down.
    with patch("transcriber.load_profile", return_value={"model_size": "base.en", "use_gpu": False}), \
         patch("transcriber.WhisperModel", return_value=_DummyWhisperModel(segments)):
        yield Transcriber(profile_name="Default", preload=False)


class StructuredResultTests(unittest.TestCase):
    def test_returns_frozen_transcription_result_with_segments(self):
        with _make_transcriber([
            _DummySegment(" Hello world", start=0.0, end=0.6, avg_logprob=-0.2, no_speech_prob=0.02),
            _DummySegment(" How are you", start=0.6, end=1.4, avg_logprob=-0.1, no_speech_prob=0.01),
        ]) as transcriber:
            audio = np.zeros(16000, dtype=np.float32)
            result = transcriber.transcribe_structured(audio)

        self.assertIsInstance(result, TranscriptionResult)
        self.assertEqual(result.text, "Hello world How are you")
        self.assertEqual(len(result.segments), 2)
        self.assertIsInstance(result.segments[0], TimedSegment)
        self.assertEqual(result.segments[0].start_s, 0.0)
        self.assertEqual(result.segments[0].end_s, 0.6)
        self.assertEqual(result.segments[0].text, "Hello world")
        self.assertEqual(result.segments[0].avg_logprob, -0.2)
        self.assertEqual(result.segments[0].no_speech_prob, 0.02)
        self.assertEqual(result.segments[1].start_s, 0.6)
        self.assertIsNotNone(result.confidence)
        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)
        self.assertAlmostEqual(result.audio_duration_s, 1.0)

    def test_frozen_dataclasses_are_immutable(self):
        with _make_transcriber([_DummySegment("Hi", start=0.0, end=0.3)]) as transcriber:
            result = transcriber.transcribe_structured(np.zeros(4800, dtype=np.float32))

        with self.assertRaises(Exception):
            result.text = "mutated"
        with self.assertRaises(Exception):
            result.segments[0].text = "mutated"

    def test_serializes_via_domain_to_dict(self):
        with _make_transcriber([_DummySegment("Hi there", start=0.0, end=0.5)]) as transcriber:
            result = transcriber.transcribe_structured(np.zeros(8000, dtype=np.float32))

        payload = to_dict(result)

        self.assertEqual(payload["text"], "Hi there")
        self.assertEqual(len(payload["segments"]), 1)
        self.assertEqual(
            set(payload["segments"][0].keys()),
            {"start_s", "end_s", "text", "avg_logprob", "no_speech_prob"},
        )
        self.assertIn("confidence", payload)
        self.assertIn("audio_duration_s", payload)

    def test_no_speech_returns_empty_result_with_duration(self):
        with _make_transcriber([]) as transcriber:
            result = transcriber.transcribe_structured(np.zeros(16000, dtype=np.float32))

        self.assertEqual(result.text, "")
        self.assertEqual(result.segments, [])
        self.assertIsNone(result.confidence)
        self.assertAlmostEqual(result.audio_duration_s, 1.0)

    def test_hallucination_guard_discards_text_and_segments(self):
        with _make_transcriber([
            _DummySegment("Thank you.", start=0.0, end=0.4),
            _DummySegment("Thank you.", start=0.4, end=0.8),
            _DummySegment("Thank you.", start=0.8, end=1.2),
        ]) as transcriber:
            result = transcriber.transcribe_structured(np.zeros(16000, dtype=np.float32))

        self.assertEqual(result.text, "")
        self.assertEqual(result.segments, [])
        self.assertIsNone(result.confidence)

    def test_admission_refused_returns_empty_result_not_crash(self):
        with _make_transcriber([_DummySegment("Hi", start=0.0, end=0.3)]) as transcriber:
            transcriber.set_admission_fn(lambda est, size: {
                "allowed": False,
                "refusal": {"message": "Not enough RAM", "resident": [], "suggested_model_id": None},
            })
            result = transcriber.transcribe_structured(np.zeros(16000, dtype=np.float32))

        self.assertEqual(result, TranscriptionResult(text="", segments=[], confidence=None, audio_duration_s=1.0))


class LegacyCallerCompatibilityTests(unittest.TestCase):
    """transcribe() and transcribe_with_confidence() must keep their exact
    pre-F2.2 return shapes — server.py branches on hasattr(...,
    'transcribe_with_confidence') and unpacks a (text, dict) tuple."""

    def test_transcribe_still_returns_bare_text(self):
        with _make_transcriber([_DummySegment("hello world", start=0.0, end=0.5)]) as transcriber:
            audio = np.zeros(1600, dtype=np.float32)
            text = transcriber.transcribe(audio)

        self.assertIsInstance(text, str)
        self.assertEqual(text, "hello world")

    def test_transcribe_with_confidence_still_returns_tuple_of_text_and_dict(self):
        with _make_transcriber([
            _DummySegment("hello world", start=0.0, end=0.5, avg_logprob=-0.15, no_speech_prob=0.03),
        ]) as transcriber:
            audio = np.zeros(1600, dtype=np.float32)
            text, confidence = transcriber.transcribe_with_confidence(audio)

        self.assertEqual(text, "hello world")
        self.assertEqual(set(confidence.keys()), {"score", "avg_logprob", "no_speech_prob"})
        self.assertIsInstance(confidence["score"], float)

    def test_transcribe_with_confidence_hallucination_returns_empty_tuple(self):
        with _make_transcriber([
            _DummySegment("Thank you.", start=0.0, end=0.4),
            _DummySegment("Thank you.", start=0.4, end=0.8),
            _DummySegment("Thank you.", start=0.8, end=1.2),
        ]) as transcriber:
            audio = np.zeros(16000, dtype=np.float32)
            text, confidence = transcriber.transcribe_with_confidence(audio)

        self.assertEqual(text, "")
        self.assertEqual(confidence, {"score": None, "avg_logprob": None, "no_speech_prob": None})

    def test_structured_and_tuple_apis_agree_on_same_decode(self):
        """Both entry points read the same _transcribe_core output, so text and
        confidence score must match exactly regardless of which API a caller uses."""
        with _make_transcriber([
            _DummySegment("consistent text", start=0.0, end=0.9, avg_logprob=-0.3, no_speech_prob=0.05),
        ]) as transcriber:
            audio = np.zeros(16000, dtype=np.float32)
            structured = transcriber.transcribe_structured(audio)
            text, confidence = transcriber.transcribe_with_confidence(audio)

        self.assertEqual(structured.text, text)
        self.assertEqual(structured.confidence, confidence["score"])


class ConfidenceFieldTests(unittest.TestCase):
    def test_worse_no_speech_prob_lowers_confidence_in_both_apis(self):
        with _make_transcriber([
            _DummySegment("clear speech", start=0.0, end=1.0, avg_logprob=-0.1, no_speech_prob=0.01),
        ]) as clean:
            clean_result = clean.transcribe_structured(np.zeros(16000, dtype=np.float32))
        with _make_transcriber([
            _DummySegment("clear speech", start=0.0, end=1.0, avg_logprob=-0.1, no_speech_prob=0.9),
        ]) as noisy:
            noisy_result = noisy.transcribe_structured(np.zeros(16000, dtype=np.float32))

        self.assertGreater(clean_result.confidence, noisy_result.confidence)


class CombinedStructuredAndConfidenceTests(unittest.TestCase):
    """transcribe_with_structured() (I3.1): a single-decode combined call for
    callers that need both the legacy confidence dict and the structured
    segments, so they don't have to call transcribe_with_confidence() and
    transcribe_structured() separately and decode the audio twice."""

    def test_returns_tuple_matching_separate_calls(self):
        with _make_transcriber([
            _DummySegment("combined call", start=0.0, end=0.7, avg_logprob=-0.2, no_speech_prob=0.02),
        ]) as transcriber:
            audio = np.zeros(16000, dtype=np.float32)
            raw, confidence, structured = transcriber.transcribe_with_structured(audio)

        self.assertEqual(raw, "combined call")
        self.assertEqual(set(confidence.keys()), {"score", "avg_logprob", "no_speech_prob"})
        self.assertIsInstance(structured, TranscriptionResult)
        self.assertEqual(structured.text, raw)
        self.assertEqual(structured.confidence, confidence["score"])
        self.assertEqual(len(structured.segments), 1)
        self.assertEqual(structured.segments[0].text, "combined call")

    def test_transcribe_structured_delegates_to_combined_call_unchanged(self):
        """transcribe_structured() must still return exactly a TranscriptionResult
        (not the tuple) after being refactored to share transcribe_with_structured()."""
        with _make_transcriber([_DummySegment("still just the result", start=0.0, end=0.4)]) as transcriber:
            result = transcriber.transcribe_structured(np.zeros(6400, dtype=np.float32))

        self.assertIsInstance(result, TranscriptionResult)
        self.assertEqual(result.text, "still just the result")

    def test_single_decode_not_two(self):
        """transcribe_with_structured must call the model exactly once, unlike
        calling transcribe_with_confidence() + transcribe_structured() back to
        back (two independent decodes)."""
        segment = _DummySegment("one decode", start=0.0, end=0.5)
        with _make_transcriber([segment]) as transcriber:
            transcriber.ensure_loaded()  # force model construction before wrapping
            call_count = {"n": 0}
            real_transcribe = transcriber.model.transcribe

            def counting_transcribe(*args, **kwargs):
                call_count["n"] += 1
                return real_transcribe(*args, **kwargs)

            transcriber.model.transcribe = counting_transcribe
            transcriber.transcribe_with_structured(np.zeros(8000, dtype=np.float32))

        self.assertEqual(call_count["n"], 1)

    def test_hallucination_guard_applies_to_combined_call(self):
        with _make_transcriber([
            _DummySegment("Thank you.", start=0.0, end=0.4),
            _DummySegment("Thank you.", start=0.4, end=0.8),
            _DummySegment("Thank you.", start=0.8, end=1.2),
        ]) as transcriber:
            raw, confidence, structured = transcriber.transcribe_with_structured(np.zeros(16000, dtype=np.float32))

        self.assertEqual(raw, "")
        self.assertEqual(confidence, {"score": None, "avg_logprob": None, "no_speech_prob": None})
        self.assertEqual(structured.segments, [])


if __name__ == "__main__":
    unittest.main()
