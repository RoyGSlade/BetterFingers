import unittest
from unittest.mock import Mock, patch

from main import prefetch_runtime_assets


class MainPrefetchModelsTests(unittest.TestCase):
    @patch("model_manager.check_and_download_resources")
    @patch("main.download_whisper_model")
    @patch("main.ReviewTTSEngine")
    def test_prefetch_runtime_assets_downloads_selected_components(
        self,
        tts_engine_cls,
        download_whisper_model,
        check_and_download_resources,
    ):
        check_and_download_resources.return_value = {"ok": True, "message": "LLM ready"}
        download_whisper_model.return_value = {"ok": True, "message": "Whisper ready"}

        tts_engine = Mock()
        tts_engine.ensure_loaded.return_value = {
            "ok": True,
            "backend": "kokoro_onnx",
            "message": "TTS ready",
        }
        tts_engine_cls.return_value = tts_engine

        result = prefetch_runtime_assets(
            llm_model_ids=["gemma-3-4b-q4"],
            whisper_models=["base.en"],
            include_tts=True,
            prefer_gpu=True,
            tts_voice_hint="english",
        )

        self.assertTrue(bool(result.get("ok", False)))
        check_and_download_resources.assert_called_once_with("gemma-3-4b-q4")
        download_whisper_model.assert_called_once_with("base.en", prefer_gpu=True)
        tts_engine.ensure_loaded.assert_called_once_with(voice_hint="english")
        tts_engine.shutdown.assert_called_once()

    @patch("model_manager.check_and_download_resources")
    @patch("main.download_whisper_model")
    def test_prefetch_runtime_assets_rejects_unknown_model_ids(
        self,
        download_whisper_model,
        check_and_download_resources,
    ):
        result = prefetch_runtime_assets(
            llm_model_ids=["unknown-model"],
            whisper_models=["unknown-whisper"],
            include_tts=False,
        )

        self.assertFalse(bool(result.get("ok", True)))
        self.assertEqual(len(result.get("llm", [])), 1)
        self.assertEqual(len(result.get("whisper", [])), 1)
        check_and_download_resources.assert_not_called()
        download_whisper_model.assert_not_called()

    @patch("model_manager.check_and_download_resources")
    @patch("main.download_whisper_model")
    def test_prefetch_runtime_assets_dedupes_repeated_inputs(
        self,
        download_whisper_model,
        check_and_download_resources,
    ):
        check_and_download_resources.return_value = {"ok": True, "message": "LLM ready"}
        download_whisper_model.return_value = {"ok": True, "message": "Whisper ready"}

        result = prefetch_runtime_assets(
            llm_model_ids=["gemma-3-4b-q4", "gemma-3-4b-q4"],
            whisper_models=["base.en", "base.en"],
            include_tts=False,
        )

        self.assertTrue(bool(result.get("ok", False)))
        check_and_download_resources.assert_called_once_with("gemma-3-4b-q4")
        download_whisper_model.assert_called_once_with("base.en", prefer_gpu=True)


if __name__ == "__main__":
    unittest.main()
