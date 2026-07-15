import glob
import os
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from wake_word import (
    DEFAULT_THRESHOLD,
    FakeWakeDetector,
    OpenWakeWordDetector,
    WakeListener,
    WakeWordService,
    build_openwakeword_detector,
)


class WakeWordServiceTests(unittest.TestCase):
    def _service(self, scores=None, **kwargs):
        detector = FakeWakeDetector(scores=scores)
        calls = []
        service = WakeWordService(detector, on_detect=lambda: calls.append(1), **kwargs)
        return service, calls

    def test_below_threshold_does_not_trigger(self):
        service, calls = self._service(scores=[0.2], threshold=0.55)
        triggered = service.process_chunk(None, 16000, now=0.0)
        self.assertFalse(triggered)
        self.assertEqual(calls, [])

    def test_at_or_above_threshold_triggers(self):
        service, calls = self._service(scores=[0.9], threshold=0.55)
        triggered = service.process_chunk(None, 16000, now=0.0)
        self.assertTrue(triggered)
        self.assertEqual(calls, [1])

    def test_cooldown_blocks_repeat_trigger(self):
        service, calls = self._service(scores=[0.9, 0.9], threshold=0.55, cooldown_ms=2500)
        self.assertTrue(service.process_chunk(None, 16000, now=0.0))
        self.assertFalse(service.process_chunk(None, 16000, now=1.0))
        self.assertEqual(calls, [1])

    def test_trigger_allowed_again_after_cooldown_elapses(self):
        service, calls = self._service(scores=[0.9, 0.9], threshold=0.55, cooldown_ms=2500)
        self.assertTrue(service.process_chunk(None, 16000, now=0.0))
        self.assertTrue(service.process_chunk(None, 16000, now=3.0))
        self.assertEqual(calls, [1, 1])

    def test_requires_vad_blocks_trigger_without_speech(self):
        service, calls = self._service(scores=[0.9], threshold=0.55, requires_vad=True)
        triggered = service.process_chunk(None, 16000, has_speech=False, now=0.0)
        self.assertFalse(triggered)
        self.assertEqual(calls, [])

    def test_requires_vad_false_ignores_speech_flag(self):
        service, calls = self._service(scores=[0.9], threshold=0.55, requires_vad=False)
        triggered = service.process_chunk(None, 16000, has_speech=False, now=0.0)
        self.assertTrue(triggered)
        self.assertEqual(calls, [1])

    def test_score_log_records_every_chunk(self):
        service, _ = self._service(scores=[0.1, 0.9], threshold=0.55)
        service.process_chunk(None, 16000, now=0.0)
        service.process_chunk(None, 16000, now=1.0)
        self.assertEqual(len(service.score_log), 2)
        self.assertFalse(service.score_log[0]["triggered"])
        self.assertTrue(service.score_log[1]["triggered"])

    def test_status_reports_config_and_recent_scores(self):
        service, _ = self._service(scores=[0.9], threshold=0.55, cooldown_ms=2500)
        service.process_chunk(None, 16000, now=0.0)
        status = service.status(now=1.0)
        self.assertEqual(status["threshold"], 0.55)
        self.assertEqual(status["cooldown_ms"], 2500)
        self.assertTrue(status["in_cooldown"])
        self.assertEqual(len(status["recent_scores"]), 1)

    def test_no_scores_queued_defaults_to_zero_never_triggers(self):
        service, calls = self._service(scores=[], threshold=0.55)
        triggered = service.process_chunk(None, 16000, now=0.0)
        self.assertFalse(triggered)
        self.assertEqual(calls, [])


class _StubMelspecSession:
    """ONNX-session-shaped stub: input (1, N) samples -> one 32-bin frame per
    call, independent of content (matches the real model's per-call frame
    count, which depends only on N, not on the audio itself)."""

    def get_inputs(self):
        return [SimpleNamespace(name="input")]

    def run(self, output_names, input_feed):
        del output_names
        return [np.full((1, 1, 1, 32), 0.3, dtype=np.float32)]


class _StubEmbeddingSession:
    def get_inputs(self):
        return [SimpleNamespace(name="input_1")]

    def run(self, output_names, input_feed):
        del output_names
        batch = input_feed["input_1"]
        return [np.full((batch.shape[0], 1, 1, 96), 0.5, dtype=np.float32)]


class _StubClassifierSession:
    def __init__(self, score=0.8):
        self.score = score
        self.calls = []

    def get_inputs(self):
        return [SimpleNamespace(name="input")]

    def run(self, output_names, input_feed):
        del output_names
        self.calls.append(input_feed["input"].shape)
        return [np.array([[self.score]], dtype=np.float32)]


# Sample counts derived from the real melspec/embedding framing (512-sample
# window, 160-sample hop, 76-frame window re-embedded every 8 frames -- see
# wake_models.py): SMALL stays well under the ~80-frame first-embedding
# threshold; PLENTY comfortably clears the 16-embedding classifier window.
_SMALL_AUDIO_SAMPLES = 12000
_PLENTY_AUDIO_SAMPLES = 40000


class OpenWakeWordDetectorTests(unittest.TestCase):
    def _detector(self, classifier_session=None):
        return OpenWakeWordDetector(
            _StubMelspecSession(), _StubEmbeddingSession(), classifier_session, label="hey_fingers"
        )

    def test_no_classifier_reports_unavailable_regardless_of_audio(self):
        detector = self._detector(classifier_session=None)
        chunk = np.zeros(_PLENTY_AUDIO_SAMPLES, dtype=np.float32)
        result = detector.predict(chunk, 16000)
        self.assertEqual(result["label"], "unavailable")
        self.assertEqual(result["score"], 0.0)

    def test_warming_up_with_insufficient_audio_yields_zero_score(self):
        classifier = _StubClassifierSession(score=0.9)
        detector = self._detector(classifier_session=classifier)
        chunk = np.zeros(_SMALL_AUDIO_SAMPLES, dtype=np.float32)
        result = detector.predict(chunk, 16000)
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["label"], "hey_fingers")
        self.assertEqual(classifier.calls, [])  # never invoked -- no full window yet

    def test_sufficient_audio_scores_via_classifier(self):
        classifier = _StubClassifierSession(score=0.87)
        detector = self._detector(classifier_session=classifier)
        chunk = np.zeros(_PLENTY_AUDIO_SAMPLES, dtype=np.float32)
        result = detector.predict(chunk, 16000)
        self.assertAlmostEqual(result["score"], 0.87)
        self.assertEqual(result["label"], "hey_fingers")
        self.assertEqual(classifier.calls[-1], (1, 16, 96))

    def test_audio_accumulates_across_multiple_predict_calls(self):
        classifier = _StubClassifierSession(score=0.7)
        detector = self._detector(classifier_session=classifier)
        chunk = np.zeros(_PLENTY_AUDIO_SAMPLES // 4, dtype=np.float32)
        results = [detector.predict(chunk, 16000) for _ in range(4)]
        self.assertTrue(any(r["score"] > 0.0 for r in results))

    def test_set_classifier_swaps_in_a_scoreable_model(self):
        detector = self._detector(classifier_session=None)
        chunk = np.zeros(_PLENTY_AUDIO_SAMPLES, dtype=np.float32)
        self.assertEqual(detector.predict(chunk, 16000)["label"], "unavailable")
        detector.set_classifier(_StubClassifierSession(score=0.6), label="hey_fingers")
        result = detector.predict(np.zeros(100, dtype=np.float32), 16000)
        self.assertEqual(result["label"], "hey_fingers")


class BuildOpenWakeWordDetectorTests(unittest.TestCase):
    def test_missing_backbone_model_reports_not_downloaded(self):
        with patch("wake_models.is_backbone_model_downloaded", return_value=False):
            detector, available, reason = build_openwakeword_detector()
        self.assertIsNone(detector)
        self.assertFalse(available)
        self.assertIn("not downloaded", reason)

    def test_corrupt_backbone_model_reports_verification_failure(self):
        with patch("wake_models.is_backbone_model_downloaded", return_value=True), patch(
            "wake_models.verify_wake_model_file", return_value={"ok": False, "reason": "digest_mismatch"}
        ):
            detector, available, reason = build_openwakeword_detector()
        self.assertIsNone(detector)
        self.assertFalse(available)
        self.assertIn("digest_mismatch", reason)

    def test_onnxruntime_failure_reports_unavailable(self):
        import wake_models

        with patch("wake_models.is_backbone_model_downloaded", return_value=True), patch(
            "wake_models.verify_wake_model_file", return_value={"ok": True, "reason": "verified"}
        ), patch(
            "wake_models.build_onnx_session",
            side_effect=wake_models.WakeEngineUnavailable("onnxruntime not available"),
        ):
            with self.assertLogs(level="ERROR") as logs:
                detector, available, reason = build_openwakeword_detector()
        self.assertIsNone(detector)
        self.assertFalse(available)
        # The client-facing reason must NOT echo internal error text
        # (py/stack-trace-exposure) — the detail goes to the server log instead.
        self.assertNotIn("onnxruntime not available", reason)
        self.assertIn("unavailable", reason)
        self.assertTrue(any("onnxruntime not available" in m for m in logs.output))

    def test_backbone_ready_with_no_classifier_is_honestly_unavailable(self):
        with patch("wake_models.is_backbone_model_downloaded", return_value=True), patch(
            "wake_models.verify_wake_model_file", return_value={"ok": True, "reason": "verified"}
        ), patch("wake_models.get_wake_model_path", return_value="/fake/path.onnx"), patch(
            "wake_models.build_onnx_session", return_value=_StubMelspecSession()
        ):
            detector, available, reason = build_openwakeword_detector()
        self.assertIsInstance(detector, OpenWakeWordDetector)
        self.assertFalse(available)
        self.assertIn("no wake-phrase classifier selected", reason)

    def test_backbone_and_classifier_ready_is_available(self):
        sessions = iter([_StubMelspecSession(), _StubEmbeddingSession(), _StubClassifierSession()])
        with patch("wake_models.is_backbone_model_downloaded", return_value=True), patch(
            "wake_models.verify_wake_model_file", return_value={"ok": True, "reason": "verified"}
        ), patch("wake_models.get_wake_model_path", return_value="/fake/path.onnx"), patch(
            "wake_models.build_onnx_session", side_effect=lambda path: next(sessions)
        ):
            detector, available, reason = build_openwakeword_detector(classifier_id="hey_fingers")
        self.assertIsInstance(detector, OpenWakeWordDetector)
        self.assertTrue(available)
        self.assertEqual(reason, "ready")

    def test_user_imported_classifier_verification_failure_is_unavailable(self):
        with patch("wake_models.is_backbone_model_downloaded", return_value=True), patch(
            "wake_models.verify_wake_model_file", return_value={"ok": True, "reason": "verified"}
        ), patch("wake_models.get_wake_model_path", return_value="/fake/path.onnx"), patch(
            "wake_models.build_onnx_session", return_value=_StubMelspecSession()
        ), patch(
            "wake_models.verify_imported_model", return_value={"ok": False, "reason": "digest_mismatch"}
        ):
            detector, available, reason = build_openwakeword_detector(
                classifier_id="user_123", classifier_origin="user-imported"
            )
        self.assertIsNone(detector)
        self.assertFalse(available)
        self.assertIn("digest_mismatch", reason)


class _StubInputStream:
    """sounddevice.InputStream-shaped stub so tests never touch real audio
    hardware. Records the callback so a test can synthesize chunks."""

    instances = []

    def __init__(self, samplerate, device, channels, dtype, blocksize, callback):
        self.samplerate = samplerate
        self.device = device
        self.channels = channels
        self.dtype = dtype
        self.blocksize = blocksize
        self.callback = callback
        self.started = False
        self.closed = False
        _StubInputStream.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True


class WakeListenerTests(unittest.TestCase):
    def setUp(self):
        _StubInputStream.instances = []
        self.detector = FakeWakeDetector(scores=[0.9])
        calls = []
        self.service = WakeWordService(self.detector, on_detect=lambda: calls.append(1))
        self.trigger_calls = calls

    def _listener(self, **kwargs):
        return WakeListener(self.service, **kwargs)

    def test_not_listening_before_start(self):
        listener = self._listener()
        self.assertFalse(listener.is_listening())

    def test_start_opens_and_starts_stream(self):
        listener = self._listener()
        with patch("sounddevice.InputStream", _StubInputStream):
            ok = listener.start()
        self.assertTrue(ok)
        self.assertTrue(listener.is_listening())
        self.assertEqual(len(_StubInputStream.instances), 1)
        self.assertTrue(_StubInputStream.instances[0].started)

    def test_start_is_idempotent(self):
        listener = self._listener()
        with patch("sounddevice.InputStream", _StubInputStream):
            listener.start()
            listener.start()
        self.assertEqual(len(_StubInputStream.instances), 1)

    def test_stop_fully_closes_stream(self):
        listener = self._listener()
        with patch("sounddevice.InputStream", _StubInputStream):
            listener.start()
            listener.stop()
        self.assertFalse(listener.is_listening())
        self.assertTrue(_StubInputStream.instances[0].closed)

    def test_stop_before_start_is_a_safe_noop(self):
        listener = self._listener()
        listener.stop()  # must not raise
        self.assertFalse(listener.is_listening())

    def test_start_failure_reports_false_and_not_listening(self):
        listener = self._listener()

        class _BoomStream(_StubInputStream):
            def __init__(self, *a, **kw):
                raise RuntimeError("device busy")

        with patch("sounddevice.InputStream", _BoomStream):
            ok = listener.start()
        self.assertFalse(ok)
        self.assertFalse(listener.is_listening())

    def test_audio_callback_feeds_service_and_can_trigger(self):
        listener = self._listener()
        with patch("sounddevice.InputStream", _StubInputStream):
            listener.start()
        stream = _StubInputStream.instances[0]
        loud_chunk = np.ones((1280, 1), dtype=np.float32) * 0.5
        stream.callback(loud_chunk, 1280, None, None)
        self.assertEqual(self.trigger_calls, [1])

    def test_silent_chunk_is_gated_by_vad_even_above_threshold_score(self):
        listener = self._listener()
        with patch("sounddevice.InputStream", _StubInputStream):
            listener.start()
        stream = _StubInputStream.instances[0]
        silent_chunk = np.zeros((1280, 1), dtype=np.float32)
        stream.callback(silent_chunk, 1280, None, None)
        self.assertEqual(self.trigger_calls, [])  # scored 0.9 but VAD-gated

    def test_status_includes_listening_flag(self):
        listener = self._listener()
        self.assertFalse(listener.status()["listening"])
        with patch("sounddevice.InputStream", _StubInputStream):
            listener.start()
        self.assertTrue(listener.status()["listening"])


def _read_wav_mono_float32(path, target_sample_rate=16000):
    """Read a 16-bit PCM WAV clip as float32 in [-1, 1], stdlib-only (no new
    pip deps). Multi-channel clips are averaged down to mono; the fixture
    format is documented on WakeFixtureAccuracyTests below."""
    with wave.open(path, "rb") as handle:
        sample_rate = handle.getframerate()
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        raw = handle.readframes(handle.getnframes())
    if sample_width != 2:
        raise ValueError(f"{path}: expected 16-bit PCM, got sample_width={sample_width}")
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if sample_rate != target_sample_rate:
        raise ValueError(f"{path}: expected {target_sample_rate} Hz, got {sample_rate} Hz")
    return audio


def _run_clip_through_service(service, audio, sample_rate=16000, chunk_samples=1280):
    """Feed a clip through in realistic mic-callback-sized chunks. Returns
    True iff any chunk triggered on_detect (has_speech=True throughout --
    fixtures are expected to be pre-trimmed to voiced audio)."""
    triggered = False
    for start in range(0, len(audio), chunk_samples):
        chunk = audio[start:start + chunk_samples]
        if service.process_chunk(chunk, sample_rate, has_speech=True):
            triggered = True
    return triggered


@unittest.skipUnless(
    os.getenv("BETTERFINGERS_WAKE_FIXTURES"),
    "requires BETTERFINGERS_WAKE_FIXTURES=<dir> with labeled positive/negative wake-phrase audio fixtures",
)
class WakeFixtureAccuracyTests(unittest.TestCase):
    """False-accept / false-reject rate check against real labeled audio
    fixtures -- structured now so fixtures can be dropped in later with no
    code changes (D1's real detector + D5's unit tests don't depend on them).

    Expected layout under $BETTERFINGERS_WAKE_FIXTURES:
      positive/*.wav  -- clips that DO contain the wake phrase (16kHz mono
                          16-bit PCM, pre-trimmed to voiced audio)
      negative/*.wav  -- clips that do NOT (other speech, silence, noise)
    Optional $BETTERFINGERS_WAKE_CLASSIFIER_ID selects a specific installed
    classifier (bundled catalog id or a user-imported model id); otherwise
    whatever the profile currently has configured is used.
    """

    FALSE_REJECT_MAX = 0.10  # at most 10% of positives may be missed
    FALSE_ACCEPT_MAX = 0.02  # at most 2% of negatives may false-trigger

    @classmethod
    def setUpClass(cls):
        classifier_id = os.getenv("BETTERFINGERS_WAKE_CLASSIFIER_ID")
        origin = os.getenv("BETTERFINGERS_WAKE_CLASSIFIER_ORIGIN", "bundled")
        detector, available, reason = build_openwakeword_detector(
            classifier_id=classifier_id, classifier_origin=origin
        )
        if not available:
            raise unittest.SkipTest(f"wake detector unavailable: {reason}")
        cls._detector = detector

    def _clips(self, label):
        fixtures_dir = os.environ["BETTERFINGERS_WAKE_FIXTURES"]
        paths = sorted(glob.glob(os.path.join(fixtures_dir, label, "*.wav")))
        if not paths:
            self.skipTest(f"no {label} fixtures found under {fixtures_dir}/{label}")
        return paths

    def _fresh_service(self):
        # A dedicated service per clip -- cooldown/score-log state must not
        # leak between fixtures.
        return WakeWordService(self._detector, on_detect=lambda: None, threshold=DEFAULT_THRESHOLD)

    def test_false_reject_rate_within_budget(self):
        positives = self._clips("positive")
        missed = 0
        for path in positives:
            audio = _read_wav_mono_float32(path)
            triggered = _run_clip_through_service(self._fresh_service(), audio)
            if not triggered:
                missed += 1
        rate = missed / len(positives)
        self.assertLessEqual(
            rate, self.FALSE_REJECT_MAX,
            f"false-reject rate {rate:.1%} ({missed}/{len(positives)}) exceeds {self.FALSE_REJECT_MAX:.0%} budget",
        )

    def test_false_accept_rate_within_budget(self):
        negatives = self._clips("negative")
        triggered_count = 0
        for path in negatives:
            audio = _read_wav_mono_float32(path)
            if _run_clip_through_service(self._fresh_service(), audio):
                triggered_count += 1
        rate = triggered_count / len(negatives)
        self.assertLessEqual(
            rate, self.FALSE_ACCEPT_MAX,
            f"false-accept rate {rate:.1%} ({triggered_count}/{len(negatives)}) exceeds {self.FALSE_ACCEPT_MAX:.0%} budget",
        )


if __name__ == "__main__":
    unittest.main()
