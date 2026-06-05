import unittest
import time
import numpy as np
from unittest.mock import Mock, patch

from tts_engine import ReviewTTSEngine


class TTSEngineTests(unittest.TestCase):
    def test_falls_back_to_sapi_when_kokoro_unavailable(self):
        engine = ReviewTTSEngine()
        with patch.object(engine, "_load_kokoro_backend", return_value=(False, "kokoro unavailable")), patch.object(
            engine, "_load_sapi_backend", return_value=(True, "sapi loaded")
        ):
            status = engine.ensure_loaded(voice_hint="english")
            self.assertTrue(status["ok"])
            self.assertEqual(status["backend"], "sapi")
            self.assertTrue(status["fallback"])

    def test_repeated_speak_replaces_pending_queue_item(self):
        engine = ReviewTTSEngine()
        with patch.object(
            engine,
            "ensure_loaded",
            return_value={"ok": True, "backend": "sapi", "fallback": False, "message": "ready"},
        ), patch.object(engine, "_start_worker_if_needed"), patch.object(engine, "stop_current") as stop_mock:
            engine.speak("first")
            engine.speak("second")
            self.assertGreaterEqual(stop_mock.call_count, 2)

            item = engine._queue.get_nowait()
            self.assertEqual(item["text"], "second")

    def test_set_prefer_gpu_unloads_active_onnx_backend(self):
        engine = ReviewTTSEngine()
        engine._backend = "kokoro_onnx"
        engine._loaded = True
        with patch.object(engine, "unload") as unload_mock:
            engine.set_prefer_gpu(False)
            unload_mock.assert_called_once()

    def test_kokoro_loader_prefers_onnx_even_when_gpu_disabled(self):
        engine = ReviewTTSEngine()
        with patch.object(
            engine,
            "_load_kokoro_onnx_backend",
            return_value=(True, "onnx ready"),
        ) as onnx_mock, patch("tts_engine.importlib.import_module") as import_mock:
            ok, message = engine._load_kokoro_backend(voice_hint="english", prefer_gpu=False)

        self.assertTrue(ok)
        self.assertEqual(message, "onnx ready")
        onnx_mock.assert_called_once_with(voice_hint="english", prefer_gpu=False)
        import_mock.assert_not_called()

    @patch("tts_engine.importlib.import_module")
    def test_resolve_onnx_providers_prefers_cuda_when_available(self, import_module):
        fake_ort = Mock()
        fake_ort.get_available_providers.return_value = [
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ]
        import_module.return_value = fake_ort

        providers, _msg = ReviewTTSEngine._resolve_onnx_providers(prefer_gpu=True)
        self.assertEqual(providers[0], "CUDAExecutionProvider")

    def test_auto_unloads_after_playback_when_keep_loaded_disabled(self):
        engine = ReviewTTSEngine()
        engine._loaded = True
        engine._backend = "sapi"
        engine.set_keep_loaded(False)

        with patch.object(engine, "_speak_sapi", return_value=None):
            engine._start_worker_if_needed()
            engine._queue.put_nowait({"text": "hello", "speed": 1.0, "voice_hint": "english"})

            deadline = time.time() + 1.0
            while time.time() < deadline:
                if engine.backend() == "none":
                    break
                time.sleep(0.02)

        try:
            self.assertEqual(engine.backend(), "none")
            self.assertFalse(engine.is_loaded())
        finally:
            engine._stop_worker()

    def test_worker_recovers_backend_when_unloaded_between_enqueue_and_playback(self):
        engine = ReviewTTSEngine()
        engine._loaded = True
        engine._backend = "sapi"

        with patch.object(
            engine,
            "ensure_loaded",
            return_value={"ok": True, "backend": "sapi", "fallback": False, "message": "ready"},
        ) as ensure_mock, patch.object(engine, "_speak_sapi", return_value=None) as speak_mock:
            # Simulate race: backend reports none at dequeue time, then recovers.
            with patch.object(engine, "backend", side_effect=["none", "sapi"]):
                engine._start_worker_if_needed()
                engine._queue.put_nowait({"text": "hello", "speed": 1.0, "voice_hint": "english"})

                deadline = time.time() + 1.0
                while time.time() < deadline and not speak_mock.called:
                    time.sleep(0.01)

                engine._stop_worker()

            ensure_mock.assert_called_with(voice_hint="english")
            self.assertTrue(speak_mock.called)

    def test_split_text_for_tts_respects_max_chars(self):
        text = (
            "This is a long transcript sentence designed to force chunking for playback. "
            "It includes multiple clauses, commas, and punctuation so boundaries are natural. "
            "Read aloud should still include every word from the original message."
        )
        chunks = ReviewTTSEngine._split_text_for_tts(text, max_chars=80)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(1 <= len(chunk) <= 80 for chunk in chunks))
        self.assertEqual(" ".join(chunks).split(), text.split())

    def test_kokoro_chunked_playback_calls_backend_for_each_chunk(self):
        engine = ReviewTTSEngine()
        text = " ".join(["rotate"] * 240)

        fake_sounddevice = Mock()
        fake_sounddevice.stop = Mock()
        fake_sounddevice.play = Mock()
        fake_audio = np.zeros(320, dtype=np.float32)

        with patch.dict("sys.modules", {"sounddevice": fake_sounddevice}), patch.object(
            engine,
            "_generate_kokoro_audio",
            return_value=(fake_audio, 24000),
        ) as generate_mock:
            engine._speak_kokoro_chunked(text=text, speed=1.3, voice_hint="english")

        self.assertGreater(generate_mock.call_count, 1)
        self.assertGreater(fake_sounddevice.play.call_count, 1)


if __name__ == "__main__":
    unittest.main()
