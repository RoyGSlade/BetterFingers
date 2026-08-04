import unittest
import os
import tempfile
from unittest.mock import patch

import numpy as np

from transcriber import Transcriber, get_whisper_download_state, list_cached_models, _repo_id_for_model


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
    def test_distil_models_use_real_hub_repo_ids(self):
        self.assertEqual(
            _repo_id_for_model("distil-medium.en"),
            "Systran/faster-distil-whisper-medium.en",
        )
        self.assertEqual(
            _repo_id_for_model("distil-large-v3"),
            "Systran/faster-distil-whisper-large-v3",
        )

    def test_distil_cache_inventory_and_loader_share_correct_repo_id(self):
        with tempfile.TemporaryDirectory() as cache_root:
            repo_dir = os.path.join(
                cache_root,
                "models--Systran--faster-distil-whisper-medium.en",
                "snapshots",
                "fixture",
            )
            os.makedirs(repo_dir)
            for filename in ("model.bin", "tokenizer.json"):
                with open(os.path.join(repo_dir, filename), "wb") as handle:
                    handle.write(b"fixture")

            rows = list_cached_models(download_root=cache_root)
            row = next(item for item in rows if item["model_size"] == "distil-medium.en")
            self.assertTrue(row["installed"])
            self.assertEqual(row["repo_id"], "Systran/faster-distil-whisper-medium.en")

            transcriber = Transcriber.__new__(Transcriber)
            transcriber.download_root = cache_root
            self.assertTrue(transcriber._is_model_cached("distil-medium.en"))

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


class TranscriberOnDemandDownloadStateTests(unittest.TestCase):
    """QA-FR-002: the on-demand load ensure_loaded() hits from Talk's
    stop/transcribe path (server.py's ensure_transcriber_initialized ->
    _stage_transcribe) must write into the SAME tracked download-state
    dict the explicit Utilities Download button uses, so a poller (Talk's
    'downloading' capture state) can observe real progress instead of the
    load just blocking silently."""

    @patch("transcriber.load_profile", return_value={"model_size": "base.en", "use_gpu": False})
    @patch("transcriber.Transcriber._is_model_cached", return_value=False)
    @patch("transcriber.WhisperModel", return_value=_DummyWhisperModel())
    def test_uncached_load_reports_downloading_then_complete(self, whisper_model, _is_cached, _load_profile):
        del whisper_model
        transcriber = Transcriber(profile_name="Default", preload=False)

        ok = transcriber.ensure_loaded()

        self.assertTrue(ok)
        final_state = get_whisper_download_state("base.en")
        self.assertEqual(final_state["status"], "complete")
        self.assertEqual(final_state["percent"], 100.0)

    @patch("transcriber.load_profile", return_value={"model_size": "base.en", "use_gpu": False})
    @patch("transcriber.Transcriber._is_model_cached", return_value=False)
    @patch("transcriber.WhisperModel", return_value=_DummyWhisperModel())
    def test_uncached_load_passes_through_starting_and_downloading(self, whisper_model, _is_cached, _load_profile):
        del whisper_model
        transcriber = Transcriber(profile_name="Default", preload=False)

        with patch("transcriber._set_whisper_download_state") as setter:
            transcriber.ensure_loaded()

        statuses = [call.args[1]["status"] for call in setter.call_args_list]
        self.assertEqual(statuses, ["starting", "downloading", "complete"])

    @patch("transcriber.load_profile", return_value={"model_size": "base.en", "use_gpu": False})
    @patch("transcriber.Transcriber._is_model_cached", return_value=False)
    def test_uncached_load_failure_reports_error_state(self, _is_cached, _load_profile):
        transcriber = Transcriber(profile_name="Default", preload=False)
        with patch("transcriber.WhisperModel", side_effect=RuntimeError("network unreachable")):
            ok = transcriber.ensure_loaded()

        self.assertFalse(ok)
        final_state = get_whisper_download_state("base.en")
        self.assertEqual(final_state["status"], "error")
        self.assertIn("network unreachable", final_state["message"])

    @patch("transcriber.load_profile", return_value={"model_size": "base.en", "use_gpu": False})
    @patch("transcriber.Transcriber._is_model_cached", return_value=True)
    @patch("transcriber.WhisperModel", return_value=_DummyWhisperModel())
    def test_cached_load_never_touches_download_state(self, whisper_model, _is_cached, _load_profile):
        del whisper_model
        transcriber = Transcriber(profile_name="Default", preload=False)
        with patch("transcriber._set_whisper_download_state") as setter:
            ok = transcriber.ensure_loaded()

        self.assertTrue(ok)
        setter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
