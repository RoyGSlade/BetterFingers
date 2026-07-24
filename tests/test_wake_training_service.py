import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import wake_models
import wake_trainer
import wake_training_service as wts


class _StubScorer:
    def __init__(self):
        self._buffer = np.zeros((0, 96), dtype=np.float32)

    def reset(self):
        self._buffer = np.zeros((0, 96), dtype=np.float32)

    def push_audio(self, chunk):
        chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)
        level = float(np.mean(chunk)) if chunk.size else 0.0
        self._buffer = np.full((20, 96), level, dtype=np.float32)

    def all_feature_windows(self, n_frames, stride=1):
        total = self._buffer.shape[0]
        if total < n_frames:
            return np.zeros((0, n_frames, 96), dtype=np.float32)
        starts = range(0, total - n_frames + 1, max(1, stride))
        return np.stack([self._buffer[s:s + n_frames] for s in starts], axis=0)


def _stub_scorer():
    return _StubScorer()


def _stub_synth(text, voice, speed):
    base = 1.0 if text == "hey fingers" else -1.0
    return np.full(4000, base + (hash((voice, round(speed, 2))) % 5) * 1e-3, dtype=np.float32)


class TrainPhraseModelTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._patch = patch.object(wake_models, "get_wake_models_dir", return_value=self._tmp.name)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_end_to_end_trains_calibrates_registers(self):
        result = wts.train_phrase_model(
            "hey fingers",
            make_scorer=_stub_scorer,
            synthesize_fn=_stub_synth,
            voices=["v1", "v2"],
        )
        self.assertTrue(result["ok"], result)
        self.assertIn(result["verdict"], ("reliable", "noisy"))
        self.assertIn("model_id", result)
        self.assertGreater(result["n_pos"], 0)
        self.assertGreater(result["n_neg"], 0)

        # Registered in the shared manifest and verifiable.
        entry = wake_models.load_imported_models()[result["model_id"]]
        self.assertEqual(entry["origin"], "trained")
        self.assertEqual(entry["license"], "self-trained")
        self.assertTrue(entry["filename"].endswith(".npz"))
        self.assertTrue(wake_models.verify_imported_model(result["model_id"])["ok"])
        # It shows up in the /wake/models listing.
        ids = {m["id"] for m in wake_models.list_wake_models()}
        self.assertIn(result["model_id"], ids)

    def test_registered_model_loads_and_scores_via_numpy_session(self):
        result = wts.train_phrase_model(
            "hey fingers", make_scorer=_stub_scorer, synthesize_fn=_stub_synth, voices=["v1"],
        )
        path = wake_models.get_imported_model_path(result["model_id"])
        session = wake_trainer.NumpyClassifierSession(wake_trainer.load_model(path))
        # A positive-cluster window should score high, negative low.
        pos = np.full((1, 16, 96), 1.0, dtype=np.float32)
        neg = np.full((1, 16, 96), -1.0, dtype=np.float32)
        pos_score = float(np.asarray(session.run(None, {"features": pos})[0]).reshape(-1)[0])
        neg_score = float(np.asarray(session.run(None, {"features": neg})[0]).reshape(-1)[0])
        self.assertGreater(pos_score, neg_score)

    def test_progress_callback_reaches_100(self):
        seen = []
        wts.train_phrase_model(
            "hey fingers", make_scorer=_stub_scorer, synthesize_fn=_stub_synth,
            voices=["v1"], progress=lambda p: seen.append(p["percent"]),
        )
        self.assertTrue(seen)
        self.assertEqual(max(seen), 100)

    def test_empty_phrase_is_clean_failure(self):
        result = wts.train_phrase_model("   ", make_scorer=_stub_scorer, synthesize_fn=_stub_synth)
        self.assertFalse(result["ok"])
        self.assertIn("phrase", result["message"].lower())

    def test_missing_backbone_is_clean_failure(self):
        def boom():
            raise RuntimeError("models not downloaded")
        result = wts.train_phrase_model("hey fingers", make_scorer=boom, synthesize_fn=_stub_synth)
        self.assertFalse(result["ok"])
        self.assertIn("backbone", result["message"].lower())

    def test_no_positive_windows_is_clean_failure(self):
        # synth returns None for everything -> no synthetic positives, no user clips.
        result = wts.train_phrase_model(
            "hey fingers", make_scorer=_stub_scorer, synthesize_fn=lambda *a: None, voices=["v1"],
        )
        self.assertFalse(result["ok"])


class _FakeEngine:
    """Minimal ReviewTTSEngine stand-in: ensure_loaded returns a canned status,
    _generate_kokoro_audio returns a fixed clip."""

    def __init__(self, status, audio=None, sample_rate=24000):
        self._status = status
        self._audio = audio
        self._sample_rate = sample_rate
        self.load_calls = 0
        self.gen_calls = 0

    def ensure_loaded(self, voice_hint="english"):
        self.load_calls += 1
        return self._status

    def _generate_kokoro_audio(self, text, speed, voice):
        self.gen_calls += 1
        if self._audio is None:
            return None
        return (self._audio, self._sample_rate)


_READY = {"ok": True, "backend": "kokoro", "fallback": False, "message": ""}


class PreflightTrainingTests(unittest.TestCase):
    """The preflight must return the EXACT blocker before any background work."""

    def _all_backbones(self, status):
        return patch.object(wake_models, "backbone_status", return_value=status)

    def test_backbone_not_downloaded_blocks(self):
        with self._all_backbones({"downloaded": False, "verified": False, "loadable": False, "error": "missing"}):
            result = wts.preflight_training(_FakeEngine(_READY))
        self.assertFalse(result["ok"])
        self.assertIn("not", result["message"].lower())
        self.assertIn("download", result["message"].lower())

    def test_backbone_unverified_blocks_with_reason(self):
        with self._all_backbones({"downloaded": True, "verified": False, "loadable": False, "error": "digest_mismatch"}):
            result = wts.preflight_training(_FakeEngine(_READY))
        self.assertFalse(result["ok"])
        self.assertIn("digest_mismatch", result["message"])

    def test_backbone_unloadable_blocks_with_reason(self):
        with self._all_backbones({"downloaded": True, "verified": True, "loadable": False, "error": "onnx boom"}):
            result = wts.preflight_training(_FakeEngine(_READY))
        self.assertFalse(result["ok"])
        self.assertIn("onnx boom", result["message"])

    def test_missing_engine_blocks(self):
        with self._all_backbones({"downloaded": True, "verified": True, "loadable": True, "error": None}):
            result = wts.preflight_training(None)
        self.assertFalse(result["ok"])
        self.assertIn("tts", result["message"].lower())

    def test_kokoro_not_loaded_blocks_with_its_message(self):
        status = {"ok": False, "backend": "none", "fallback": False, "message": "Not enough RAM to load the TTS model."}
        with self._all_backbones({"downloaded": True, "verified": True, "loadable": True, "error": None}):
            result = wts.preflight_training(_FakeEngine(status))
        self.assertFalse(result["ok"])
        self.assertIn("RAM", result["message"])

    def test_sapi_fallback_backend_blocks(self):
        status = {"ok": True, "backend": "sapi", "fallback": True, "message": "Using Windows SAPI fallback."}
        with self._all_backbones({"downloaded": True, "verified": True, "loadable": True, "error": None}):
            result = wts.preflight_training(_FakeEngine(status))
        self.assertFalse(result["ok"])
        self.assertIn("kokoro", result["message"].lower())

    def test_all_ready_passes(self):
        with self._all_backbones({"downloaded": True, "verified": True, "loadable": True, "error": None}):
            result = wts.preflight_training(_FakeEngine(_READY))
        self.assertTrue(result["ok"])


class KokoroSynthesizeHonestyTests(unittest.TestCase):
    """kokoro_synthesize must not silently 'succeed' when Kokoro isn't loaded."""

    def test_returns_audio_when_kokoro_ready(self):
        engine = _FakeEngine(_READY, audio=np.ones(2400, dtype=np.float32), sample_rate=24000)
        out = wts.kokoro_synthesize(engine)("hey fingers", "af_heart", 1.0)
        self.assertIsNotNone(out)
        self.assertGreater(out.size, 0)
        self.assertEqual(engine.gen_calls, 1)

    def test_does_not_generate_when_load_not_ok(self):
        status = {"ok": False, "backend": "none", "fallback": False, "message": "boom"}
        engine = _FakeEngine(status, audio=np.ones(2400, dtype=np.float32))
        out = wts.kokoro_synthesize(engine)("hey fingers", "af_heart", 1.0)
        self.assertIsNone(out)
        # Never even attempted generation on a failed load.
        self.assertEqual(engine.gen_calls, 0)

    def test_does_not_generate_on_sapi_fallback(self):
        status = {"ok": True, "backend": "sapi", "fallback": True, "message": "fallback"}
        engine = _FakeEngine(status, audio=np.ones(2400, dtype=np.float32))
        out = wts.kokoro_synthesize(engine)("hey fingers", "af_heart", 1.0)
        self.assertIsNone(out)
        self.assertEqual(engine.gen_calls, 0)


class ResampleTests(unittest.TestCase):
    def test_passthrough_at_16k(self):
        audio = np.ones(1000, dtype=np.float32)
        out = wts._resample_to_16k(audio, 16000)
        np.testing.assert_array_equal(out, audio)

    def test_downsamples_24k_to_16k(self):
        audio = np.ones(2400, dtype=np.float32)  # 0.1s @ 24k
        out = wts._resample_to_16k(audio, 24000)
        # ~0.1s @ 16k = ~1600 samples.
        self.assertAlmostEqual(out.shape[0], 1600, delta=20)


if __name__ == "__main__":
    unittest.main()
