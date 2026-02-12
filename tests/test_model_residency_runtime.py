import unittest
from unittest.mock import Mock, patch

from main import App


class _ImmediateThread:
    started_targets = []

    def __init__(self, target=None, daemon=None):
        del daemon
        self.target = target
        _ImmediateThread.started_targets.append(target)

    def start(self):
        if callable(self.target):
            self.target()


class ModelResidencyRuntimeTests(unittest.TestCase):
    def _build_app(self):
        app = App()
        app.injector = Mock()
        app.transcriber = Mock()
        app.tts_engine = Mock()
        app.overlay = None
        app.notification_overlay = None
        app.preview_overlay = None
        return app

    @patch("main.get_engine")
    @patch("main.threading.Thread", _ImmediateThread)
    @patch("main.load_profile")
    def test_apply_runtime_settings_warm_loads_when_keep_enabled(self, load_profile, get_engine):
        _ImmediateThread.started_targets = []
        cfg = {
            "model_keep_llm_loaded": True,
            "model_keep_stt_loaded": True,
            "model_keep_tts_loaded": True,
            "use_gpu": True,
            "review_tts_voice_hint": "english",
        }
        load_profile.return_value = cfg

        app = self._build_app()
        app._apply_runtime_settings("Default")

        self.assertTrue(callable(_ImmediateThread.started_targets[0]))
        self.assertGreaterEqual(len(_ImmediateThread.started_targets), 3)
        get_engine.assert_called_once()
        app.transcriber.ensure_loaded.assert_called_once()
        app.tts_engine.ensure_loaded.assert_called_once_with(voice_hint="english")
        app.transcriber.unload.assert_not_called()
        app.tts_engine.unload.assert_not_called()

    @patch("main.get_engine_if_initialized")
    @patch("main.threading.Thread")
    @patch("main.load_profile")
    def test_apply_runtime_settings_unloads_when_keep_disabled(
        self,
        load_profile,
        thread_cls,
        get_engine_if_initialized,
    ):
        cfg = {
            "model_keep_llm_loaded": False,
            "model_keep_stt_loaded": False,
            "model_keep_tts_loaded": False,
            "use_gpu": False,
            "review_tts_voice_hint": "english",
        }
        load_profile.return_value = cfg

        engine = Mock()
        get_engine_if_initialized.return_value = engine

        app = self._build_app()
        app._apply_runtime_settings("Default")

        app.transcriber.unload.assert_called_once()
        app.tts_engine.unload.assert_called_once()
        engine.shutdown.assert_called_once()
        warm_targets = {app._warm_load_llm, app._warm_load_stt, app._warm_load_tts}
        for call in thread_cls.call_args_list:
            target = call.kwargs.get("target")
            if target is None and call.args:
                target = call.args[0]
            self.assertNotIn(target, warm_targets)

    @patch("main.get_engine_if_initialized")
    def test_release_transient_models_unloads_when_flags_disabled(self, get_engine_if_initialized):
        engine = Mock()
        get_engine_if_initialized.return_value = engine

        app = self._build_app()
        app.model_keep_stt_loaded = False
        app.model_keep_llm_loaded = False
        app.model_keep_tts_loaded = False

        app._release_transient_models(include_tts=True)

        app.transcriber.unload.assert_called_once()
        app.tts_engine.unload.assert_called_once()
        engine.shutdown.assert_called_once()

    @patch("main.get_engine_if_initialized")
    def test_release_transient_models_keeps_models_when_flags_enabled(self, get_engine_if_initialized):
        engine = Mock()
        get_engine_if_initialized.return_value = engine

        app = self._build_app()
        app.model_keep_stt_loaded = True
        app.model_keep_llm_loaded = True
        app.model_keep_tts_loaded = True

        app._release_transient_models(include_tts=True)

        app.transcriber.unload.assert_not_called()
        app.tts_engine.unload.assert_not_called()
        engine.shutdown.assert_not_called()


if __name__ == "__main__":
    unittest.main()
