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


class ProbeDummyTranscriber(DummyTranscriber):
    def __init__(self, profile_name="Default", preload=True):
        super().__init__(profile_name=profile_name, preload=preload)
        self.probe_calls = 0

    def runtime_probe(self):
        self.probe_calls += 1
        self.ensure_loaded()
        return {
            "constructed": True,
            "probe_passed": True,
            "inference_ready": True,
            "error_code": None,
            "error_state": None,
            "active_device": "cuda",
            "active_compute_type": "float16",
            "device_fallback_reason": None,
            "device_fallback_code": None,
        }

    def get_runtime_status(self):
        return {
            "constructed": self.model is not None,
            "probe_passed": self.probe_calls > 0,
            "inference_ready": self.probe_calls > 0,
            "error_code": None,
            "error_state": None,
            "active_device": "cuda" if self.model is not None else None,
            "active_compute_type": "float16" if self.model is not None else None,
            "device_fallback_reason": None,
            "device_fallback_code": None,
        }


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
        self.assertTrue(DummyTranscriber.instances[0].loaded)
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
        self.assertTrue(DummyTranscriber.instances[0].loaded)
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

    def test_stt_warmup_preserves_probe_evidence_in_response(self):
        probe = ProbeDummyTranscriber(preload=False)
        server.transcriber = probe

        result = asyncio.run(
            server.runtime_warmup(
                server.RuntimeWarmupRequest(stt=True, llm=False, hotkeys=False)
            )
        )

        self.assertEqual(probe.probe_calls, 1)
        self.assertTrue(result["stt"]["initialized"])
        self.assertTrue(result["stt"]["loaded"])
        self.assertTrue(result["stt"]["ok"])
        self.assertTrue(result["stt"]["probe_passed"])
        self.assertTrue(result["stt"]["inference_ready"])
        self.assertEqual(result["stt"]["active_device"], "cuda")

    def test_apply_residency_warms_enabled_missing_resources_and_reports_failure(self):
        snapshot = {
            "ledger": {"llm": None, "stt": {"model_id": "small"}, "tts": None},
            "pinned": {"llm": False, "stt": False, "tts": False},
        }
        with patch.object(server.model_runtime, "resources_snapshot", return_value=snapshot), patch.object(
            server.model_runtime, "set_pinned"
        ) as pinned, patch.object(
            server, "warm_start_resident_models", return_value={"llm": {"ok": False, "error": "missing model"}}
        ) as warm:
            result = server.apply_model_residency_preferences(
                {"llm": True, "stt": True, "tts": False}, warm_enabled=True
            )

        self.assertEqual(pinned.call_count, 3)
        warm.assert_called_once_with({"llm": True, "stt": False, "tts": False})
        self.assertFalse(result["llm"]["ok"])
        self.assertEqual(result["llm"]["error"], "missing model")
        self.assertTrue(result["llm"]["keep_loaded"])

    def test_disabling_tts_syncs_concrete_idle_policy_without_forced_unload(self):
        class DummyTts:
            def __init__(self):
                self.values = []

            def set_keep_loaded(self, value):
                self.values.append(value)

        dummy = DummyTts()
        server.tts_engine = dummy
        snapshot = {
            "ledger": {"llm": None, "stt": None, "tts": {"model_id": "kokoro"}},
            "pinned": {"llm": False, "stt": False, "tts": True},
        }
        try:
            with patch.object(server.model_runtime, "resources_snapshot", return_value=snapshot), patch.object(
                server.model_runtime, "set_pinned"
            ), patch.object(server, "warm_start_resident_models") as warm:
                result = server.apply_model_residency_preferences(
                    {"llm": False, "stt": False, "tts": False}, warm_enabled=True
                )
            self.assertEqual(dummy.values, [False])
            warm.assert_not_called()
            self.assertFalse(result["tts"]["keep_loaded"])
            self.assertTrue(result["tts"]["loaded"], "resident now, eligible for safe idle cleanup")
        finally:
            server.tts_engine = None


if __name__ == "__main__":
    unittest.main()
