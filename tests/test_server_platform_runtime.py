import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server


class DummyTranscriber:
    def __init__(self, profile_name="Default", preload=True):
        self.profile_name = profile_name
        self.preload = preload
        self.model = None


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


if __name__ == "__main__":
    unittest.main()
