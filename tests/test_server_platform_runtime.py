import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import server


class DummyTranscriber:
    def __init__(self, profile_name="Default", preload=True):
        self.profile_name = profile_name
        self.preload = preload
        self.model = None


class DummyTTS:
    _status_message = "ready"
    _fallback = False

    def is_loaded(self):
        return False

    def backend(self):
        return "dummy"


class DummyLlmEngine:
    _ready = False
    model_id = "gemma-4-12b-q4"
    _last_error = "llama-server exited during startup."
    _last_error_details = {"stderr": "libmtmd.so.0 missing"}


class ServerPlatformRuntimeTests(unittest.TestCase):
    def setUp(self):
        server.transcriber = None
        server.hotkey_manager = None
        server.hotkey_recorder = None
        server.hotkey_manager_started = False
        server.loop = None

    def tearDown(self):
        server.transcriber = None
        server.hotkey_manager = None
        server.hotkey_recorder = None
        server.hotkey_manager_started = False
        server.loop = None
        server.runtime_error_history.clear()

    def test_capabilities_endpoint_returns_platform_data(self):
        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with TestClient(server.app) as client:
                response = client.get("/capabilities")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("platform", data)
        self.assertIn("session_type", data)
        self.assertIn("supports_stt", data)
        self.assertIn("supports_llm", data)
        self.assertIn("supports_tts", data)

    def test_linux_tts_voices_works_without_appdata(self):
        with tempfile.TemporaryDirectory() as data_dir, tempfile.TemporaryDirectory() as config_dir:
            env = {
                "BETTERFINGERS_LAZY_STARTUP": "1",
                "XDG_DATA_HOME": data_dir,
                "XDG_CONFIG_HOME": config_dir,
            }
            with patch.dict(os.environ, env, clear=False), patch.object(
                server, "Transcriber", DummyTranscriber
            ), patch("sys.platform", "linux"):
                os.environ.pop("APPDATA", None)
                with TestClient(server.app) as client:
                    response = client.get("/tts/voices")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("defaults", data)
        self.assertIn("cloned", data)

    def test_linux_graph_save_and_load_work_without_appdata(self):
        with tempfile.TemporaryDirectory() as data_dir, tempfile.TemporaryDirectory() as config_dir:
            env = {
                "BETTERFINGERS_LAZY_STARTUP": "1",
                "XDG_DATA_HOME": data_dir,
                "XDG_CONFIG_HOME": config_dir,
            }
            with patch.dict(os.environ, env, clear=False), patch.object(
                server, "Transcriber", DummyTranscriber
            ), patch("sys.platform", "linux"):
                os.environ.pop("APPDATA", None)
                with TestClient(server.app) as client:
                    save_response = client.post(
                        "/graph/save",
                        json={
                            "nodes": [{"id": "start", "label": "Start"}],
                            "edges": [],
                        },
                    )
                    load_response = client.get("/graph/load")

        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(save_response.json()["status"], "success")
        self.assertEqual(load_response.status_code, 200)
        self.assertEqual(load_response.json()["nodes"][0]["id"], "start")

    def test_diagnostics_paths_returns_runtime_paths(self):
        with tempfile.TemporaryDirectory() as data_dir, tempfile.TemporaryDirectory() as config_dir:
            env = {
                "BETTERFINGERS_LAZY_STARTUP": "1",
                "XDG_DATA_HOME": data_dir,
                "XDG_CONFIG_HOME": config_dir,
            }
            with patch.dict(os.environ, env, clear=False), patch("sys.platform", "linux"):
                with TestClient(server.app) as client:
                    response = client.get("/diagnostics/paths")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("debug_log_path", data)
        self.assertIn("llama_server_path", data)
        self.assertIn("default_model_path", data)
        self.assertIn("BETTERFINGERS_LAZY_STARTUP", data)

    def test_runtime_errors_endpoint_returns_error_history(self):
        server.record_runtime_error("llm", "llama-server missing", {"action": "warmup"})

        with TestClient(server.app) as client:
            response = client.get("/runtime/errors")

        self.assertEqual(response.status_code, 200)
        errors = response.json()["errors"]
        self.assertEqual(errors[0]["component"], "llm")
        self.assertEqual(errors[0]["message"], "llama-server missing")
        self.assertEqual(errors[0]["details"]["action"], "warmup")

    def test_diagnostics_logs_returns_log_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "debug.log")
            with open(log_path, "w", encoding="utf-8") as handle:
                handle.write("one\n")
                handle.write("two\n")
                handle.write("three\n")

            with patch.object(server, "get_debug_log_path", return_value=Path(log_path)):
                with TestClient(server.app) as client:
                    response = client.get("/diagnostics/logs?lines=2")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["exists"])
        self.assertEqual(data["lines"], ["two", "three"])

    def test_runtime_version_endpoint(self):
        with TestClient(server.app) as client:
            response = client.get("/runtime/version")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["backend_version"], "0.1.0")
        self.assertEqual(data["expected_electron_api_version"], "0.1.0")
        self.assertEqual(data["schema_version"], 1)

    def test_doctor_endpoint(self):
        with patch("sys.platform", "linux"):
            with TestClient(server.app) as client:
                response = client.get("/doctor")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["health"], "active")
        self.assertIn("stt", data)
        self.assertIn("llm", data)
        self.assertIn("tts", data)
        self.assertIn("audio", data)
        self.assertIn("recovery", data)

    def test_doctor_reports_llm_runtime_link_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_path = os.path.join(tmp, "llama-server")
            with open(server_path, "w", encoding="utf-8") as handle:
                handle.write("#!/bin/sh\nexit 127\n")

            with patch.object(server, "get_engine_if_initialized", return_value=DummyLlmEngine()), patch.object(
                server, "get_server_path", return_value=server_path
            ), patch.object(server, "check_model_exists", return_value=True), patch.object(
                server,
                "validate_llama_server_runtime",
                return_value={"ok": False, "message": "llama-server runtime libraries are incomplete: libmtmd.so.0"},
            ), patch.object(server, "ensure_tts_initialized", return_value=DummyTTS()):
                with TestClient(server.app) as client:
                    response = client.get("/doctor")

        self.assertEqual(response.status_code, 200)
        llm = response.json()["llm"]
        self.assertFalse(llm["runtime_valid"])
        self.assertEqual(llm["runtime_status"], "runtime_link_failure")
        self.assertIn("libmtmd.so.0", llm["runtime_message"])

    def test_record_runtime_error_severity(self):
        server.record_runtime_error("stt", "failed loading model", "fatal", {"model": "base.en"})
        with TestClient(server.app) as client:
            response = client.get("/runtime/errors")
        self.assertEqual(response.status_code, 200)
        errors = response.json()["errors"]
        target = [e for e in errors if e["message"] == "failed loading model"]
        self.assertTrue(len(target) > 0)
        self.assertEqual(target[0]["severity"], "fatal")
        self.assertEqual(target[0]["details"]["model"], "base.en")

    def test_refresh_audio_devices_endpoint(self):
        with TestClient(server.app) as client:
            response = client.post("/runtime/audio-devices/refresh")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("devices", data)


if __name__ == "__main__":
    unittest.main()
