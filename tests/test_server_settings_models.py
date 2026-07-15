import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server


class DummyEngine:
    def __init__(self):
        self.model_id = ""
        self.shutdown_called = False

    def set_model_id(self, model_id):
        self.model_id = model_id

    def shutdown(self):
        self.shutdown_called = True


class DummyTranscriber:
    def __init__(self, profile_name="Default", preload=False):
        self.profile_name = profile_name
        self.model_size = "base.en"
        self.unloaded = False

    def reload_profile(self, profile_name="Default", preload=None):
        self.profile_name = profile_name

    def unload(self):
        self.unloaded = True

    def ensure_loaded(self):
        return True


class ServerSettingsModelsTests(unittest.TestCase):
    def setUp(self):
        self._transcriber = server.transcriber
        self._hotkey_manager = server.hotkey_manager
        self._output_injector = server.output_injector
        self._tts_engine = server.tts_engine
        server.transcriber = None
        server.hotkey_manager = None
        server.output_injector = None
        server.tts_engine = None

    def tearDown(self):
        server.transcriber = self._transcriber
        server.hotkey_manager = self._hotkey_manager
        server.output_injector = self._output_injector
        server.tts_engine = self._tts_engine

    def test_settings_profile_create_save_and_activate(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("utils.get_profiles_dir", return_value=tmp), patch.object(
                server, "get_profiles_dir", return_value=tmp
            ), patch("utils._app_state_path", return_value=os.path.join(tmp, "app_state.yaml")):
                with TestClient(server.app) as client:
                    created = client.post("/settings/profiles", json={"name": "Linux Dev", "settings": {"hotkey": "f7"}})
                    profiles = client.get("/settings/profiles")
                    saved = client.post("/settings/profiles/Linux%20Dev", json={"settings": {"hotkey": "f6", "recording_mode": "ptt"}})
                    activated = client.post("/settings/profiles/Linux%20Dev/activate")
                    deleted = client.delete("/settings/profiles/Linux%20Dev")

        self.assertEqual(created.status_code, 200)
        self.assertIn("Linux Dev", profiles.json()["profiles"])
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["settings"]["hotkey"], "f6")
        self.assertEqual(activated.status_code, 200)
        self.assertEqual(activated.json()["active_profile"], "Linux Dev")
        self.assertEqual(deleted.status_code, 200)
        self.assertNotIn("Linux Dev", deleted.json()["profiles"])

    def test_llm_model_endpoints_select_download_delete_and_unload(self):
        engine = DummyEngine()

        with tempfile.TemporaryDirectory() as tmp:
            model_path = os.path.join(tmp, "model.gguf")
            with open(model_path, "wb") as handle:
                handle.write(b"model")
            with patch("utils.get_profiles_dir", return_value=tmp), patch("utils._app_state_path", return_value=os.path.join(tmp, "app_state.yaml")), patch.object(
                server, "get_model_path", return_value=model_path
            ), patch.object(server, "get_server_path", return_value=os.path.join(tmp, "llama-server")), patch.object(
                server, "check_and_download_resources", return_value={"ok": True, "message": "ready"}
            ), patch.object(server, "delete_model", return_value=(True, "deleted")), patch.object(
                server, "get_engine_if_initialized", return_value=engine
            ):
                with TestClient(server.app) as client:
                    listed = client.get("/models/llm")
                    selected = client.post("/models/llm/select", json={"model_id": "gemma-4-e2b-q8"})
                    downloaded = client.post("/models/llm/gemma-4-e2b-q8/download")
                    download_state = client.get("/models/llm/gemma-4-e2b-q8/download-state")
                    deleted = client.delete("/models/llm/gemma-4-e2b-q8")
                    unloaded = client.post("/models/unload/llm")

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(selected.status_code, 200)
        self.assertEqual(engine.model_id, "gemma-4-e2b-q8")
        self.assertTrue(downloaded.json()["ok"])
        self.assertEqual(download_state.status_code, 200)
        self.assertTrue(deleted.json()["ok"])
        self.assertTrue(unloaded.json()["ok"])
        self.assertTrue(engine.shutdown_called)

    def test_whisper_endpoints_list_test_delete_and_unload_stt(self):
        dummy = DummyTranscriber()
        server.transcriber = dummy

        with patch.object(server, "list_cached_models", return_value=[{"model_size": "base.en", "installed": True}]), patch.object(
            server, "get_whisper_download_state", return_value={"status": "ready"}
        ), patch.object(server, "Transcriber", DummyTranscriber), patch.object(
            server, "remove_cached_model", return_value={"ok": True, "message": "removed"}
        ):
            with TestClient(server.app) as client:
                listed = client.get("/models/whisper")
                tested = client.post("/models/whisper/test", json={"model_size": "base.en", "prefer_gpu": False})
                deleted = client.delete("/models/whisper/base.en")
                unloaded = client.post("/models/unload/stt")

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["selected_model_size"], "base.en")
        self.assertTrue(tested.json()["ok"])
        self.assertTrue(deleted.json()["ok"])
        self.assertTrue(unloaded.json()["ok"])
        self.assertTrue(dummy.unloaded)


if __name__ == "__main__":
    unittest.main()
