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


if __name__ == "__main__":
    unittest.main()
