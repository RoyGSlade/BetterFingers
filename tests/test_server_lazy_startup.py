import os
import unittest
import asyncio
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
import llm_engine


class DummyTranscriber:
    instances = []

    def __init__(self, profile_name="Default", preload=True):
        self.profile_name = profile_name
        self.preload = preload
        self.loaded = False
        self.model = None
        DummyTranscriber.instances.append(self)

    def ensure_loaded(self):
        self.loaded = True
        self.model = object()
        return True


class DummyEngine:
    def __init__(self):
        self._ready = True


class DummyHotkeyManager:
    def __init__(self):
        self.started = False

    def start(self):
        self.started = True


class ServerLazyStartupTests(unittest.TestCase):
    def setUp(self):
        self._llm_engine_state = {
            "_instance": llm_engine.LLMEngine._instance,
            "_initialized": llm_engine.LLMEngine._initialized,
            "_process": llm_engine.LLMEngine._process,
            "_process_pid": llm_engine.LLMEngine._process_pid,
            "_owns_process": llm_engine.LLMEngine._owns_process,
            "_ready": llm_engine.LLMEngine._ready,
            "_engine_instance": llm_engine._engine_instance,
        }
        llm_engine.LLMEngine._instance = None
        llm_engine.LLMEngine._initialized = False
        llm_engine.LLMEngine._process = None
        llm_engine.LLMEngine._process_pid = None
        llm_engine.LLMEngine._owns_process = False
        llm_engine.LLMEngine._ready = False
        llm_engine._engine_instance = None
        server.transcriber = None
        server.hotkey_manager = None
        server.hotkey_recorder = None
        server.hotkey_manager_started = False
        server.loop = None
        DummyTranscriber.instances = []

    def tearDown(self):
        llm_engine.LLMEngine._instance = self._llm_engine_state["_instance"]
        llm_engine.LLMEngine._initialized = self._llm_engine_state["_initialized"]
        llm_engine.LLMEngine._process = self._llm_engine_state["_process"]
        llm_engine.LLMEngine._process_pid = self._llm_engine_state["_process_pid"]
        llm_engine.LLMEngine._owns_process = self._llm_engine_state["_owns_process"]
        llm_engine.LLMEngine._ready = self._llm_engine_state["_ready"]
        llm_engine._engine_instance = self._llm_engine_state["_engine_instance"]
        server.transcriber = None
        server.hotkey_manager = None
        server.hotkey_recorder = None
        server.hotkey_manager_started = False
        server.loop = None

    def _run_startup(self):
        # startup_event() warms models on a background thread; join it so
        # assertions about the transcriber/engine are deterministic.
        asyncio.run(server.startup_event())
        thread = getattr(server, "_warmup_thread", None)
        if thread is not None:
            thread.join(timeout=5)

    def test_lazy_startup_skips_llm_and_hotkeys(self):
        profile = {
            "model_keep_llm_loaded": False,
            "model_keep_stt_loaded": False,
            "model_keep_tts_loaded": False,
        }
        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ), patch.object(server, "load_profile", return_value=profile), patch.object(
            server, "get_engine", side_effect=AssertionError("get_engine should not run")
        ), patch.object(
            server, "HotkeyManager", side_effect=AssertionError("HotkeyManager should not start")
        ):
            self._run_startup()

        self.assertEqual(len(DummyTranscriber.instances), 1)
        self.assertFalse(DummyTranscriber.instances[0].preload)
        self.assertIsNotNone(server.transcriber)
        self.assertFalse(server.hotkey_manager_started)

    def test_default_startup_keeps_eager_behavior(self):
        started = DummyHotkeyManager()

        def _start_hotkey_manager():
            server.hotkey_manager_started = True
            server.hotkey_manager = started
            return started

        # Keep-loaded on so the background warmup preloads STT and warms the LLM.
        profile = {
            "model_keep_llm_loaded": True,
            "model_keep_stt_loaded": True,
            "model_keep_tts_loaded": False,
        }

        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": ""}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ), patch.object(server, "load_profile", return_value=profile), patch.object(
            server, "get_engine", return_value=DummyEngine()
        ) as engine_mock, patch.object(
            server, "start_hotkey_manager", side_effect=_start_hotkey_manager
        ) as hotkey_mock:
            self._run_startup()

        self.assertEqual(len(DummyTranscriber.instances), 1)
        self.assertTrue(DummyTranscriber.instances[0].preload)
        self.assertTrue(engine_mock.called)
        self.assertTrue(hotkey_mock.called)
        self.assertTrue(server.hotkey_manager_started)
        self.assertIs(server.hotkey_manager, started)
        self.assertFalse(started.started)

    def test_startup_respects_keep_loaded_flags_when_disabled(self):
        started = DummyHotkeyManager()

        def _start_hotkey_manager():
            server.hotkey_manager_started = True
            server.hotkey_manager = started
            return started

        profile = {
            "model_keep_llm_loaded": False,
            "model_keep_stt_loaded": False,
            "model_keep_tts_loaded": False,
        }

        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": ""}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ), patch.object(server, "load_profile", return_value=profile), patch.object(
            server, "get_engine", side_effect=AssertionError("LLM should not warm when keep-loaded is off")
        ), patch.object(
            server, "ensure_tts_initialized", side_effect=AssertionError("TTS should not warm when keep-loaded is off")
        ), patch.object(
            server, "start_hotkey_manager", side_effect=_start_hotkey_manager
        ):
            self._run_startup()

        self.assertEqual(len(DummyTranscriber.instances), 1)
        self.assertFalse(DummyTranscriber.instances[0].preload)
        self.assertFalse(DummyTranscriber.instances[0].loaded)
        self.assertTrue(server.hotkey_manager_started)

    def test_lazy_startup_still_warms_keep_loaded_models(self):
        profile = {
            "model_keep_llm_loaded": True,
            "model_keep_stt_loaded": True,
            "model_keep_tts_loaded": False,
        }

        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ), patch.object(server, "load_profile", return_value=profile), patch.object(
            server, "get_engine", return_value=DummyEngine()
        ) as engine_mock, patch.object(
            server, "HotkeyManager", side_effect=AssertionError("HotkeyManager should not start in lazy startup")
        ):
            self._run_startup()

        self.assertEqual(len(DummyTranscriber.instances), 1)
        self.assertTrue(DummyTranscriber.instances[0].preload)
        self.assertTrue(DummyTranscriber.instances[0].loaded)
        self.assertTrue(engine_mock.called)
        self.assertFalse(server.hotkey_manager_started)

    def test_lazy_health_runtime_and_warmup(self):
        engine_holder = {}
        profile = {
            "model_keep_llm_loaded": False,
            "model_keep_stt_loaded": False,
            "model_keep_tts_loaded": False,
        }

        def _get_engine(model_id=None):
            engine_holder["engine"] = DummyEngine()
            if model_id and hasattr(engine_holder["engine"], "set_model_id"):
                engine_holder["engine"].set_model_id(model_id)
            return engine_holder["engine"]

        def _get_engine_if_initialized():
            return engine_holder.get("engine")

        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ), patch.object(server, "load_profile", return_value=profile), patch.object(
            server, "get_engine", side_effect=_get_engine
        ), patch.object(
            server, "get_engine_if_initialized", side_effect=_get_engine_if_initialized
        ):
            asyncio.run(server.startup_event())

            with TestClient(server.app) as client:
                health = client.get("/health")
                self.assertEqual(health.status_code, 200)
                self.assertEqual(health.json()["status"], "active")
                self.assertTrue(health.json()["transcriber"])
                self.assertFalse(health.json()["llm_engine"])

                status = client.get("/runtime/status")
                self.assertEqual(status.status_code, 200)
                self.assertTrue(status.json()["transcriber_initialized"])
                self.assertFalse(status.json()["llm_initialized"])
                self.assertFalse(status.json()["hotkey_manager_started"])

                warmup = client.post(
                    "/runtime/warmup",
                    json={"stt": True, "llm": True, "hotkeys": False},
                )
                self.assertEqual(warmup.status_code, 200)
                warmup_json = warmup.json()
                self.assertTrue(warmup_json["transcriber_initialized"])
                self.assertTrue(warmup_json["llm_initialized"])
                self.assertTrue(warmup_json["stt"]["initialized"])
                self.assertTrue(warmup_json["stt"]["loaded"])
                self.assertTrue(warmup_json["llm"]["initialized"])
                self.assertTrue(warmup_json["llm"]["ready"])
                self.assertFalse(warmup_json["hotkey_manager_started"])

                status_after = client.get("/runtime/status")
                self.assertTrue(status_after.json()["transcriber_initialized"])
                self.assertTrue(status_after.json()["llm_initialized"])
                self.assertFalse(status_after.json()["hotkey_manager_started"])

    def test_warmup_returns_200_with_structured_llm_failure(self):
        with TestClient(server.app) as client, patch.object(
            server, "get_engine", side_effect=RuntimeError("llama-server missing")
        ), patch.object(server, "get_engine_if_initialized", return_value=None):
            warmup = client.post(
                "/runtime/warmup",
                json={"stt": False, "llm": True, "hotkeys": False},
            )

        self.assertEqual(warmup.status_code, 200)
        payload = warmup.json()
        self.assertFalse(payload["llm"]["ok"])
        self.assertFalse(payload["llm"]["initialized"])
        self.assertFalse(payload["llm"]["ready"])
        self.assertIn("llama-server missing", payload["llm"]["error"])


if __name__ == "__main__":
    unittest.main()
