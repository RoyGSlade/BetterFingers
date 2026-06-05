import os
import sys
import unittest
import tempfile
import shutil
from unittest.mock import MagicMock, patch

# Headless mock of pynput and sounddevice to prevent X11 display/audio errors
sys.modules["pynput"] = MagicMock()
sys.modules["pynput.keyboard"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

from fastapi.testclient import TestClient
import utils
import server


class SettingsRedesignTests(unittest.TestCase):
    def setUp(self):
        # Clean up any runtime instances in the server
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

    def test_validation_ranges(self):
        # Valid settings payload
        valid_data = {
            "output_token_limit": 1000,
            "llm_chunk_size": 250,
            "whisper_chunk_size": 100,
            "review_tts_speed": 1.5,
            "no_audio_min_duration_sec": 5.0,
            "no_audio_min_rms": 0.05,
            "no_audio_min_peak": 0.1,
            "hotkey": "ctrl+alt+r",
            "force_stop_key": "ctrl+alt+s",
        }
        # Should not raise exception
        utils.validate_profile_settings(valid_data)

        # Invalid Token Limit (<900)
        invalid_data = valid_data.copy()
        invalid_data["output_token_limit"] = 800
        with self.assertRaises(ValueError) as ctx:
            utils.validate_profile_settings(invalid_data)
        self.assertIn("Limit must be between 900 and 1200", str(ctx.exception))

        # Invalid LLM Chunk Size (>5000)
        invalid_data = valid_data.copy()
        invalid_data["llm_chunk_size"] = 6000
        with self.assertRaises(ValueError) as ctx:
            utils.validate_profile_settings(invalid_data)
        self.assertIn("LLM Chunk Size must be between 50 and 5000", str(ctx.exception))

        # Invalid TTS Speed (>3.0)
        invalid_data = valid_data.copy()
        invalid_data["review_tts_speed"] = 4.0
        with self.assertRaises(ValueError) as ctx:
            utils.validate_profile_settings(invalid_data)
        self.assertIn("TTS Speed must be between 0.5 and 3.0", str(ctx.exception))

    def test_hotkey_collision_detection(self):
        colliding_data = {
            "hotkey": "ctrl+alt+r",
            "force_stop_key": "ctrl+alt+r", # Colliding
            "manual_send_hotkey": "ctrl+alt+s",
        }
        with self.assertRaises(ValueError) as ctx:
            utils.validate_profile_settings(colliding_data)
        self.assertIn("Duplicate hotkey detected", str(ctx.exception))

    def test_atomic_save_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("utils.get_profiles_dir", return_value=tmp):
                profile_name = "test_atomic_profile"
                file_path = os.path.join(tmp, f"{profile_name}.yaml")
                
                # First write a dummy file
                with open(file_path, "w") as f:
                    f.write("dummy: data")

                # Save new data
                new_data = {
                    "output_token_limit": 1050,
                    "hotkey": "ctrl+alt+k",
                    "force_stop_key": "ctrl+alt+p"
                }
                utils.save_profile(profile_name, new_data)

                # Verify backup was created
                backup_path = file_path + ".bak"
                self.assertTrue(os.path.exists(backup_path))
                with open(backup_path, "r") as f:
                    self.assertEqual(f.read(), "dummy: data")

                # Verify final saved file exists and matches the new data
                self.assertTrue(os.path.exists(file_path))
                loaded = utils.load_profile(profile_name)
                self.assertEqual(loaded["output_token_limit"], 1050)
                self.assertEqual(loaded["hotkey"], "ctrl+alt+k")

    def test_api_rename_duplicate_export_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("utils.get_profiles_dir", return_value=tmp), patch.object(
                server, "get_profiles_dir", return_value=tmp
            ), patch("utils._app_state_path", return_value=os.path.join(tmp, "app_state.yaml")):
                with TestClient(server.app) as client:
                    # 1. Create a profile
                    create_res = client.post("/settings/profiles", json={
                        "name": "CustomDev",
                        "settings": {
                            "output_token_limit": 1100,
                            "hotkey": "ctrl+alt+x",
                            "force_stop_key": "ctrl+alt+z"
                        }
                    })
                    self.assertEqual(create_res.status_code, 200)

                    # 2. Duplicate profile
                    dup_res = client.post("/settings/profiles/CustomDev/duplicate", json={
                        "new_name": "CustomDev_Copy"
                    })
                    self.assertEqual(dup_res.status_code, 200)
                    self.assertIn("CustomDev_Copy", dup_res.json()["profiles"])

                    # Activate CustomDev before renaming to verify active profile renaming works
                    act_res = client.post("/settings/profiles/CustomDev/activate")
                    self.assertEqual(act_res.status_code, 200)
                    self.assertEqual(act_res.json()["active_profile"], "CustomDev")

                    # 3. Rename profile
                    rename_res = client.post("/settings/profiles/CustomDev/rename", json={
                        "new_name": "CustomDev_Renamed"
                    })
                    self.assertEqual(rename_res.status_code, 200)
                    self.assertEqual(rename_res.json()["active_profile"], "CustomDev_Renamed")
                    
                    # Verify CustomDev is gone, CustomDev_Renamed exists
                    self.assertNotIn("CustomDev", rename_res.json()["profiles"])
                    self.assertIn("CustomDev_Renamed", rename_res.json()["profiles"])

                    # 4. Export profile
                    export_res = client.get("/settings/profiles/CustomDev_Renamed/export")
                    self.assertEqual(export_res.status_code, 200)
                    exported_data = export_res.json()
                    self.assertEqual(exported_data["kind"], "betterfingers_profile")
                    self.assertEqual(exported_data["schema_version"], 1)
                    self.assertEqual(exported_data["name"], "CustomDev_Renamed")
                    self.assertEqual(exported_data["settings"]["output_token_limit"], 1100)

                    # 5. Import profile
                    import_body = {
                        "kind": "betterfingers_profile",
                        "schema_version": 1,
                        "name": "ImportedProfile",
                        "settings": exported_data["settings"]
                    }
                    import_res = client.post("/settings/profiles/import", json=import_body)
                    self.assertEqual(import_res.status_code, 200)
                    self.assertIn("ImportedProfile", import_res.json()["profiles"])

                    # Try importing invalid kind
                    invalid_kind_body = import_body.copy()
                    invalid_kind_body["kind"] = "invalid_kind"
                    bad_kind_res = client.post("/settings/profiles/import", json=invalid_kind_body)
                    self.assertEqual(bad_kind_res.status_code, 400)

                    # Try importing invalid schema version
                    invalid_version_body = import_body.copy()
                    invalid_version_body["schema_version"] = 999
                    bad_version_res = client.post("/settings/profiles/import", json=invalid_version_body)
                    self.assertEqual(bad_version_res.status_code, 400)

                    # 6. Safe Delete and Protection
                    # Try to delete Default profile
                    delete_default = client.delete("/settings/profiles/Default")
                    self.assertEqual(delete_default.status_code, 400) # Blocked

                    # Delete active profile, which should fallback to "Default"
                    active_name = client.get("/settings/profiles").json()["active_profile"]
                    delete_active = client.delete(f"/settings/profiles/{active_name}")
                    self.assertEqual(delete_active.status_code, 200)
                    self.assertEqual(delete_active.json()["active_profile"], "Default")


if __name__ == "__main__":
    unittest.main()
