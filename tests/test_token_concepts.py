"""Phase 1 + 2: separate the LLM completion cap from the long-draft warning, and
make sure the completion cap actually reaches the engine for initial dictation."""

import os
import tempfile
import unittest
from unittest.mock import patch

import yaml

import utils
import server


class TokenConceptDefaultsTest(unittest.TestCase):
    def _tmp_appdata(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        original = os.environ.get("APPDATA")
        os.environ["APPDATA"] = tmp.name
        if original is None:
            self.addCleanup(lambda: os.environ.pop("APPDATA", None))
        else:
            self.addCleanup(lambda: os.environ.__setitem__("APPDATA", original))
        return tmp.name

    def test_new_defaults_present(self):
        self._tmp_appdata()
        loaded = utils.load_profile("Default")
        self.assertEqual(int(loaded["max_completion_tokens"]), 1600)
        self.assertEqual(int(loaded["long_draft_warning_words"]), 1200)

    def test_legacy_output_token_limit_aliases_to_max_completion(self):
        self._tmp_appdata()
        profiles_dir = utils.get_profiles_dir()
        with open(os.path.join(profiles_dir, "Legacy.yaml"), "w", encoding="utf-8") as f:
            yaml.safe_dump({"output_token_limit": 1150}, f)
        loaded = utils.load_profile("Legacy")
        # The stored legacy value carries over to the new completion cap...
        self.assertEqual(int(loaded["max_completion_tokens"]), 1150)
        # ...while output_token_limit itself remains valid for back-compat.
        self.assertEqual(int(loaded["output_token_limit"]), 1150)

    def test_sanitize_clamps_new_fields(self):
        self._tmp_appdata()
        profiles_dir = utils.get_profiles_dir()
        with open(os.path.join(profiles_dir, "Wild.yaml"), "w", encoding="utf-8") as f:
            yaml.safe_dump(
                {"max_completion_tokens": 999999, "long_draft_warning_words": 5},
                f,
            )
        loaded = utils.load_profile("Wild")
        self.assertEqual(int(loaded["max_completion_tokens"]), 4096)
        self.assertEqual(int(loaded["long_draft_warning_words"]), 300)

    def test_validation_accepts_and_rejects(self):
        # Accepts a value well above the old 1200 ceiling.
        utils.validate_profile_settings({"max_completion_tokens": 2048})
        utils.validate_profile_settings({"long_draft_warning_words": 4000})
        with self.assertRaises(ValueError):
            utils.validate_profile_settings({"max_completion_tokens": 8000})
        with self.assertRaises(ValueError):
            utils.validate_profile_settings({"long_draft_warning_words": 100})


class ActiveHelperTest(unittest.TestCase):
    def _tmp_appdata(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        original = os.environ.get("APPDATA")
        os.environ["APPDATA"] = tmp.name
        if original is None:
            self.addCleanup(lambda: os.environ.pop("APPDATA", None))
        else:
            self.addCleanup(lambda: os.environ.__setitem__("APPDATA", original))
        return tmp.name

    def test_active_helpers_read_split_fields(self):
        self._tmp_appdata()
        profile = utils._profile_defaults()
        profile["max_completion_tokens"] = 2048
        profile["long_draft_warning_words"] = 800
        utils.save_profile("Split", profile)
        utils.set_last_active_profile("Split")
        self.assertEqual(server.get_active_completion_tokens(), 2048)
        self.assertEqual(server.get_active_long_draft_warning_words(), 800)

    def test_long_text_warning_uses_warning_words_not_completion_cap(self):
        self._tmp_appdata()
        profile = utils._profile_defaults()
        profile["max_completion_tokens"] = 4096
        profile["long_draft_warning_words"] = 300
        utils.save_profile("Warn", profile)
        utils.set_last_active_profile("Warn")
        long_draft = {"final_text": " ".join(["word"] * 400)}
        server.update_draft_review_fields(long_draft)
        # 400 words > 300 warning threshold, regardless of the 4096 completion cap.
        self.assertTrue(long_draft["long_text"])
        self.assertEqual(long_draft["token_limit"], 300)


class _DummyTranscriber:
    def __init__(self, preload=False, profile_name=None, *args, **kwargs):
        pass

    def transcribe(self, audio_data):
        return "hello world"


class _DummyRecordingResult:
    audio_data = [0.1, 0.2, 0.3]
    sample_rate = 16000
    duration_seconds = 1.0
    frame_count = 3
    sample_count = 3
    max_amplitude = 0.2
    rms_amplitude = 0.05
    stop_reason = "manual"


class Phase2PassThroughTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        original = os.environ.get("APPDATA")
        os.environ["APPDATA"] = tmp.name
        if original is None:
            self.addCleanup(lambda: os.environ.pop("APPDATA", None))
        else:
            self.addCleanup(lambda: os.environ.__setitem__("APPDATA", original))
        self._load_patch = patch("server.load_draft_history")
        self._load_patch.start()
        self.addCleanup(self._load_patch.stop)
        self._save_patch = patch("server.save_draft_history")
        self._save_patch.start()
        self.addCleanup(self._save_patch.stop)

    def test_completion_cap_reaches_engine(self):
        captured = {}

        class RecordingEngine:
            def process_fast_lane(self, text, preset, max_output_tokens=None, chunk_size=None, progress_callback=None):
                captured["max_output_tokens"] = max_output_tokens
                captured["chunk_size"] = chunk_size
                return f"clean: {text}"

        profile = utils._profile_defaults()
        profile["max_completion_tokens"] = 2222
        profile["llm_chunk_size"] = 640
        utils.save_profile("Cap", profile)
        utils.set_last_active_profile("Cap")

        with patch.object(server, "Transcriber", _DummyTranscriber), patch.object(
            server, "get_engine", return_value=RecordingEngine()
        ), patch.object(server, "broadcast_status_threadsafe"):
            draft = server.process_recording_result(_DummyRecordingResult())

        self.assertEqual(draft["final_text"], "clean: hello world")
        self.assertEqual(captured["max_output_tokens"], 2222)
        self.assertEqual(captured["chunk_size"], 640)


if __name__ == "__main__":
    unittest.main()
