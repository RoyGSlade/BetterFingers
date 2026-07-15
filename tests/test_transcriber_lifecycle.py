import unittest
from unittest.mock import patch

import numpy as np

from transcriber import Transcriber


class _DummySegment:
    def __init__(self, text, start=0.0, end=0.0):
        self.start = start
        self.end = end
        self.text = text


class _DummyWhisperModel:
    def transcribe(self, _audio, beam_size=5):
        del beam_size
        return [_DummySegment("hello world", start=0.0, end=0.5)], None


class TranscriberLifecycleTests(unittest.TestCase):
    @patch("transcriber.load_profile", return_value={"model_size": "base.en", "use_gpu": False})
    @patch("transcriber.WhisperModel", return_value=_DummyWhisperModel())
    def test_unload_then_transcribe_reloads_model(self, whisper_model, _load_profile):
        transcriber = Transcriber(profile_name="Default", preload=False)
        self.assertIsNone(transcriber.model)

        audio = np.zeros(1600, dtype=np.float32)
        first = transcriber.transcribe(audio)
        self.assertEqual(first, "hello world")
        self.assertEqual(whisper_model.call_count, 1)

        transcriber.unload()
        self.assertIsNone(transcriber.model)

        second = transcriber.transcribe(audio)
        self.assertEqual(second, "hello world")
        self.assertEqual(whisper_model.call_count, 2)


class TranscriberAdmissionTests(unittest.TestCase):
    """Load-site seam for model_runtime_coordinator (DESIGN.md M6): ensure_loaded
    consults the injected admission_fn before constructing WhisperModel."""

    @patch("transcriber.load_profile", return_value={"model_size": "base.en", "use_gpu": False})
    @patch("transcriber.WhisperModel", return_value=_DummyWhisperModel())
    def test_refused_admission_blocks_load_without_crashing(self, whisper_model, _load_profile):
        transcriber = Transcriber(profile_name="Default", preload=False)
        transcriber.set_admission_fn(lambda est, size: {
            "allowed": False,
            "refusal": {"message": "Not enough RAM to load the speech model.",
                        "resident": [], "suggested_model_id": None},
        })

        ok = transcriber.ensure_loaded()

        self.assertFalse(ok)
        self.assertIsNone(transcriber.model)
        whisper_model.assert_not_called()
        self.assertIn("Not enough RAM", transcriber._last_error)

    @patch("transcriber.load_profile", return_value={"model_size": "base.en", "use_gpu": False})
    @patch("transcriber.WhisperModel", return_value=_DummyWhisperModel())
    def test_allowed_admission_loads_and_reports(self, whisper_model, _load_profile):
        transcriber = Transcriber(profile_name="Default", preload=False)
        transcriber.set_admission_fn(lambda est, size: {"allowed": True, "refusal": None})
        reported = []
        transcriber.set_load_reporter(lambda size, est: reported.append((size, est)))

        ok = transcriber.ensure_loaded()

        self.assertTrue(ok)
        whisper_model.assert_called_once()
        self.assertEqual(reported, [("base.en", 300)])

    @patch("transcriber.load_profile", return_value={"model_size": "base.en", "use_gpu": False})
    @patch("transcriber.WhisperModel", return_value=_DummyWhisperModel())
    def test_no_admission_fn_is_a_noop(self, whisper_model, _load_profile):
        transcriber = Transcriber(profile_name="Default", preload=False)
        ok = transcriber.ensure_loaded()
        self.assertTrue(ok)
        whisper_model.assert_called_once()


if __name__ == "__main__":
    unittest.main()
