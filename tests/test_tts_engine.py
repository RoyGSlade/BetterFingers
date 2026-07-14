import threading
import unittest
import time
import numpy as np
from unittest.mock import Mock, patch

from job_manager import JOBS, JobState
from model_runtime_coordinator import ModelRuntimeCoordinator, RuntimeBusyError
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
        onnx_mock.assert_called_once_with(voice_hint="english", prefer_gpu=False, quantization="fp32")
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

    def test_chunked_playback_resolves_voice_spec_once_and_reuses_it(self):
        engine = ReviewTTSEngine()
        text = " ".join(["rotate"] * 240)
        fake_sounddevice = Mock()
        fake_audio = np.zeros(320, dtype=np.float32)

        with patch.dict("sys.modules", {"sounddevice": fake_sounddevice}), patch.object(
            engine, "_resolve_voice_spec", return_value="blended_spec_marker"
        ) as resolve_mock, patch.object(
            engine, "_generate_kokoro_audio", return_value=(fake_audio, 24000)
        ) as generate_mock:
            engine._speak_kokoro_chunked(
                text=text, speed=1.0, voice_hint="af_heart", blend={"am_adam": 0.3},
            )

        resolve_mock.assert_called_once_with("af_heart", {"am_adam": 0.3})
        for call in generate_mock.call_args_list:
            self.assertEqual(call.kwargs.get("voice_spec"), "blended_spec_marker")


class RuntimeLeaseCoverageTests(unittest.TestCase):
    """P0 regression: the runtime read lease must be held by the WORKER across
    generation + playback + callbacks — not just while speak() enqueues — so
    /models/unload/tts cannot free models under an in-flight utterance."""

    def setUp(self):
        self.coordinator = ModelRuntimeCoordinator()
        self.engine = ReviewTTSEngine()
        self.engine.set_runtime_lease_factory(
            lambda: self.coordinator.read_lease("tts", timeout=0.5)
        )
        self.engine._loaded = True
        self.engine._backend = "sapi"

    def tearDown(self):
        self.engine._stop_worker()

    def _speak_and_wait(self, playback_started, release_playback):
        def fake_sapi(text, speed, voice_hint):
            playback_started.set()
            release_playback.wait(timeout=5.0)

        patcher = patch.object(self.engine, "_speak_sapi", side_effect=fake_sapi)
        patcher.start()
        self.addCleanup(patcher.stop)
        result = self.engine.speak("hello there")
        self.assertTrue(result["ok"])
        self.assertTrue(playback_started.wait(timeout=5.0))
        return result

    def test_unload_write_lease_blocked_while_worker_is_playing(self):
        playback_started = threading.Event()
        release_playback = threading.Event()
        result = self._speak_and_wait(playback_started, release_playback)

        # Playback is in flight on the worker: a non-forced exclusive op must
        # fail fast instead of freeing the models mid-utterance.
        with self.assertRaises(RuntimeBusyError):
            with self.coordinator.write_lease("tts", wait=False):
                pass

        release_playback.set()
        deadline = time.time() + 5.0
        while time.time() < deadline and self.coordinator.is_busy("tts"):
            time.sleep(0.02)

        # Once the utterance drains, the exclusive op proceeds.
        with self.coordinator.write_lease("tts", wait=False):
            pass
        job = JOBS.get(result["job_id"])
        self.assertEqual(job.state, JobState.COMPLETED)

    def test_speak_returns_queued_job_id_not_success_claim(self):
        playback_started = threading.Event()
        release_playback = threading.Event()
        result = self._speak_and_wait(playback_started, release_playback)

        self.assertTrue(result.get("queued"))
        self.assertIn("job_id", result)
        # While audio is still playing the job must not claim completion.
        self.assertNotEqual(JOBS.get(result["job_id"]).state, JobState.COMPLETED)
        release_playback.set()

        deadline = time.time() + 5.0
        while time.time() < deadline and JOBS.get(result["job_id"]).state != JobState.COMPLETED:
            time.sleep(0.02)
        self.assertEqual(JOBS.get(result["job_id"]).state, JobState.COMPLETED)

    def test_forced_unload_cancel_interrupts_chunked_playback(self):
        self.engine._backend = "kokoro_onnx"
        text = " ".join(["rotate"] * 240)  # forces many chunks
        fake_audio = np.zeros(24000, dtype=np.float32)  # 1s per chunk

        fake_sounddevice = Mock()
        fake_sounddevice.get_stream.side_effect = Exception("no stream introspection")

        generated = []

        def fake_generate(chunk_text, *args, **kwargs):
            generated.append(chunk_text)
            return (fake_audio, 24000)

        with patch.dict("sys.modules", {"sounddevice": fake_sounddevice}), patch.object(
            self.engine, "_generate_kokoro_audio", side_effect=fake_generate
        ), patch.object(self.engine, "_resolve_voice_spec", return_value="af_heart"):
            result = self.engine.speak(text)
            self.assertTrue(result["ok"])
            deadline = time.time() + 5.0
            while time.time() < deadline and not generated:
                time.sleep(0.01)
            self.assertTrue(generated)

            # Forced unload: cancel-and-wait must drain the reader promptly.
            start = time.time()
            with self.coordinator.write_lease("tts", wait=True, timeout=10.0):
                pass
            elapsed = time.time() - start

        # Far less than full playback (~10+ chunks x 1s each).
        self.assertLess(elapsed, 5.0)
        total_chunks = len(self.engine._split_text_for_tts(text))
        self.assertLess(len(generated), total_chunks)
        job = JOBS.get(result["job_id"])
        self.assertEqual(job.state, JobState.CANCELLED)

    def test_worker_drops_item_and_fails_job_when_runtime_reconfiguring(self):
        playback = Mock()
        with patch.object(self.engine, "_speak_sapi", playback), patch.object(
            self.engine, "_runtime_guard", side_effect=RuntimeBusyError("tts busy")
        ):
            result = self.engine.speak("hello")
            self.assertTrue(result["ok"])
            deadline = time.time() + 5.0
            while time.time() < deadline and not JOBS.get(result["job_id"]).is_terminal:
                time.sleep(0.02)

        job = JOBS.get(result["job_id"])
        self.assertEqual(job.state, JobState.FAILED)
        playback.assert_not_called()

    def test_cached_playback_runs_on_worker_under_lease(self):
        self.engine._backend = "kokoro_onnx"
        audio = np.zeros(2400, dtype=np.float32)
        cache_key = ("hello", 1.5, "english", (), ())
        self.engine._audio_cache[cache_key] = (audio, 24000)

        fake_sounddevice = Mock()
        fake_sounddevice.get_stream.return_value = Mock(active=False)
        stops = []
        self.engine.on_stop = lambda: stops.append(True)

        with patch.dict("sys.modules", {"sounddevice": fake_sounddevice}), patch.object(
            self.engine, "_generate_kokoro_audio"
        ) as generate_mock:
            result = self.engine.speak("hello")
            deadline = time.time() + 5.0
            while time.time() < deadline and not JOBS.get(result["job_id"]).is_terminal:
                time.sleep(0.02)

        self.assertEqual(JOBS.get(result["job_id"]).state, JobState.COMPLETED)
        generate_mock.assert_not_called()
        self.assertTrue(fake_sounddevice.play.called)
        self.assertTrue(stops)  # on_stop ran after real (worker-side) playback

    def test_superseded_queue_item_job_is_cancelled(self):
        engine = ReviewTTSEngine()
        with patch.object(
            engine, "ensure_loaded",
            return_value={"ok": True, "backend": "sapi", "fallback": False, "message": "ready"},
        ), patch.object(engine, "_start_worker_if_needed"), patch.object(engine, "stop_current"):
            first = engine.speak("first")
            second = engine.speak("second")

        self.assertEqual(JOBS.get(first["job_id"]).state, JobState.CANCELLED)
        self.assertFalse(JOBS.get(second["job_id"]).is_terminal)


class ResolveVoiceSpecTests(unittest.TestCase):
    def setUp(self):
        self.engine = ReviewTTSEngine()
        self.engine._kokoro_runtime = "onnx"
        self.fake_onnx = Mock()
        self.fake_onnx.voices = {
            "af_heart": np.full((2, 1, 3), 1.0, dtype=np.float32),
            "am_adam": np.full((2, 1, 3), 5.0, dtype=np.float32),
        }
        self.engine._kokoro_onnx = self.fake_onnx

    def test_no_blend_returns_plain_string(self):
        spec = self.engine._resolve_voice_spec("af_heart", None)
        self.assertEqual(spec, "af_heart")

    def test_empty_blend_returns_plain_string(self):
        spec = self.engine._resolve_voice_spec("af_heart", {})
        self.assertEqual(spec, "af_heart")

    def test_valid_blend_returns_weighted_tensor(self):
        spec = self.engine._resolve_voice_spec("af_heart", {"am_adam": 0.5})
        self.assertIsInstance(spec, np.ndarray)
        # base implicit weight 1.0, am_adam 0.5 -> normalized [2/3, 1/3]
        expected = (1.0 * (1 / 1.5)) + (5.0 * (0.5 / 1.5))
        np.testing.assert_allclose(np.mean(spec), expected, rtol=1e-5)

    def test_unknown_blend_voice_falls_back_to_base(self):
        spec = self.engine._resolve_voice_spec("af_heart", {"not_a_real_voice": 0.5})
        self.assertEqual(spec, "af_heart")

    def test_native_backend_falls_back_to_base(self):
        self.engine._kokoro_runtime = "native"
        spec = self.engine._resolve_voice_spec("af_heart", {"am_adam": 0.5})
        self.assertEqual(spec, "af_heart")

    def test_alias_resolved_before_blending(self):
        # "english" aliases to af_heart; blending should still work.
        spec = self.engine._resolve_voice_spec("english", {"am_adam": 0.5})
        self.assertIsInstance(spec, np.ndarray)


class GenerateKokoroAudioModulationTests(unittest.TestCase):
    def test_onnx_voice_spec_ndarray_passed_directly_to_create(self):
        engine = ReviewTTSEngine()
        engine._kokoro_runtime = "onnx"
        fake_onnx = Mock()
        seen = {}

        def fake_create(text, voice, speed, lang):
            seen["voice"] = voice
            return (np.full(50, 0.2, dtype=np.float32), 24000)

        fake_onnx.create = fake_create
        engine._kokoro_onnx = fake_onnx

        tensor = np.full((2, 1, 3), 3.0, dtype=np.float32)
        engine._generate_kokoro_audio("hi", 1.0, "af_heart", voice_spec=tensor)
        self.assertIs(seen["voice"], tensor)

    def test_native_backend_ignores_ndarray_voice_spec(self):
        engine = ReviewTTSEngine()
        engine._kokoro_runtime = "native"
        seen = {}

        def fake_pipeline(text, voice, speed):
            seen["voice"] = voice
            return [(None, None, np.zeros(50, dtype=np.float32))]

        engine._kokoro_pipeline = fake_pipeline
        tensor = np.full((2, 1, 3), 3.0, dtype=np.float32)
        engine._generate_kokoro_audio("hi", 1.0, "af_heart", voice_spec=tensor)
        # Native backend can't use a raw tensor; should fall back to a resolved string.
        self.assertEqual(seen["voice"], "af_heart")

    def test_modulation_changes_output_audio(self):
        engine = ReviewTTSEngine()
        engine._kokoro_runtime = "onnx"
        fake_onnx = Mock()
        fake_onnx.voices = {"af_heart": np.zeros((2, 1, 3), dtype=np.float32)}
        fake_onnx.create = lambda text, voice, speed, lang: (np.full(2400, 0.3, dtype=np.float32), 24000)
        engine._kokoro_onnx = fake_onnx

        plain = engine._generate_kokoro_audio("hi", 1.0, "af_heart")
        modulated = engine._generate_kokoro_audio("hi", 1.0, "af_heart", modulation={"energy": 1.0})
        self.assertFalse(np.allclose(plain[0], modulated[0]))

    def test_no_modulation_is_unchanged(self):
        engine = ReviewTTSEngine()
        engine._kokoro_runtime = "onnx"
        fake_onnx = Mock()
        fake_onnx.voices = {"af_heart": np.zeros((2, 1, 3), dtype=np.float32)}
        fake_onnx.create = lambda text, voice, speed, lang: (np.full(2400, 0.3, dtype=np.float32), 24000)
        engine._kokoro_onnx = fake_onnx

        result = engine._generate_kokoro_audio("hi", 1.0, "af_heart", modulation=None)
        np.testing.assert_array_equal(result[0], np.full(2400, 0.3, dtype=np.float32))

    def test_render_prepared_chunks_unaffected_by_new_params(self):
        # Positional call with exactly 3 args (the pre-existing export path) must
        # keep working unchanged now that voice_spec/modulation were added.
        engine = ReviewTTSEngine()
        engine._kokoro_runtime = "onnx"
        fake_onnx = Mock()
        fake_onnx.voices = {"af_heart": np.zeros((2, 1, 3), dtype=np.float32)}
        fake_onnx.create = lambda text, voice, speed, lang: (np.full(50, 0.1, dtype=np.float32), 24000)
        engine._kokoro_onnx = fake_onnx

        result = engine._generate_kokoro_audio("hi", 1.0, "af_heart")
        self.assertIsNotNone(result)


class CacheSignatureTests(unittest.TestCase):
    def test_blend_signature_deterministic_and_order_independent(self):
        from tts_engine import _blend_signature

        a = _blend_signature({"x": 0.3, "y": 0.7})
        b = _blend_signature({"y": 0.7, "x": 0.3})
        self.assertEqual(a, b)

    def test_blend_signature_empty(self):
        from tts_engine import _blend_signature

        self.assertEqual(_blend_signature(None), ())
        self.assertEqual(_blend_signature({}), ())

    def test_blend_signature_differs_by_weight(self):
        from tts_engine import _blend_signature

        self.assertNotEqual(_blend_signature({"x": 0.3}), _blend_signature({"x": 0.4}))

    def test_modulation_signature_empty(self):
        from tts_engine import _modulation_signature

        self.assertEqual(_modulation_signature(None), ())
        self.assertEqual(_modulation_signature({}), ())

    def test_modulation_signature_differs_by_value(self):
        from tts_engine import _modulation_signature

        self.assertNotEqual(
            _modulation_signature({"pitch": 1.0}),
            _modulation_signature({"pitch": 2.0}),
        )

    def test_modulation_signature_includes_pause_style(self):
        from tts_engine import _modulation_signature

        self.assertNotEqual(
            _modulation_signature({"pause_style": "dramatic"}),
            _modulation_signature({"pause_style": "compact"}),
        )


if __name__ == "__main__":
    unittest.main()
