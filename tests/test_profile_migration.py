import os
import tempfile
import unittest

import yaml

import utils


class ProfileMigrationTests(unittest.TestCase):
    def test_legacy_controller_fields_migrate_to_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = tmp
            try:
                profiles_dir = utils.get_profiles_dir()
                legacy = {
                    "hotkey": "f8",
                    "controller_ptt": True,
                    "controller_button": 9,
                }
                with open(os.path.join(profiles_dir, "Legacy.yaml"), "w", encoding="utf-8") as f:
                    yaml.safe_dump(legacy, f)

                loaded = utils.load_profile("Legacy")
                self.assertTrue(loaded.get("controller_enabled"))
                binding = loaded.get("controller_binding", {})
                self.assertEqual(binding.get("style"), "single")
                self.assertEqual(binding.get("events"), ["button:9"])
                self.assertEqual(float(loaded.get("review_tts_speed")), 1.5)
                self.assertTrue(bool(loaded.get("model_keep_llm_loaded")))
                self.assertTrue(bool(loaded.get("model_keep_stt_loaded")))
                self.assertFalse(bool(loaded.get("model_keep_tts_loaded")))
            finally:
                if original_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_appdata

    def test_legacy_queue_only_send_mode_is_coerced_and_send_method_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = tmp
            try:
                profiles_dir = utils.get_profiles_dir()
                legacy = {
                    "send_mode": "queue_only",
                    "send_method": "type",
                    "live_output_mode": "preview_and_live_type",
                    "token_cap_enabled": True,
                    "token_cap_tokens": 9999,
                    "token_cap_message": "legacy",
                    "final_transcription_pass": False,
                }
                with open(os.path.join(profiles_dir, "LegacyOutput.yaml"), "w", encoding="utf-8") as f:
                    yaml.safe_dump(legacy, f)

                loaded = utils.load_profile("LegacyOutput")
                self.assertEqual(loaded.get("send_mode"), "review_first")
                self.assertNotIn("send_method", loaded)
                self.assertNotIn("live_output_mode", loaded)
                self.assertNotIn("token_cap_enabled", loaded)
                self.assertNotIn("token_cap_tokens", loaded)
                self.assertNotIn("token_cap_message", loaded)
                self.assertNotIn("final_transcription_pass", loaded)
                self.assertEqual(int(loaded.get("output_token_limit")), 1200)
                self.assertEqual(loaded.get("long_input_message"), "legacy")
            finally:
                if original_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_appdata

    def test_invalid_profile_values_are_sanitized(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = tmp
            try:
                profiles_dir = utils.get_profiles_dir()
                broken = {
                    "recording_mode": "TOGGLE",
                    "send_mode": "not-a-real-mode",
                    "review_tts_enabled": "false",
                    "review_tts_speed": "99.9",
                    "audio_ducking_level_percent": "nan",
                    "overlay_position": "unknown",
                    "notification_overlay_alpha": "3.4",
                    "notification_overlay_bg": "not-a-color",
                    "status_indicator_enabled": "no",
                    "status_indicator_flash_enabled": "yes",
                    "status_indicator_color_idle": "not-a-color",
                    "controller_sequence_window_ms": "5",
                    "controller_axis_threshold": "2.3",
                    "output_token_limit": "99999",
                    "draft_history_limit": "99999",
                    "experience_preset": "unknown-mode",
                }
                with open(os.path.join(profiles_dir, "Broken.yaml"), "w", encoding="utf-8") as f:
                    yaml.safe_dump(broken, f)

                loaded = utils.load_profile("Broken")
                self.assertEqual(loaded.get("recording_mode"), "toggle")
                self.assertEqual(loaded.get("send_mode"), "review_first")
                self.assertFalse(bool(loaded.get("review_tts_enabled")))
                self.assertLessEqual(float(loaded.get("review_tts_speed")), 3.0)
                self.assertGreaterEqual(float(loaded.get("review_tts_speed")), 0.5)
                self.assertGreaterEqual(float(loaded.get("audio_ducking_level_percent")), 1.0)
                self.assertLessEqual(float(loaded.get("audio_ducking_level_percent")), 100.0)
                self.assertTrue(bool(loaded.get("organic_formatting_enabled")))
                self.assertEqual(loaded.get("overlay_position"), "Bottom-Right")
                self.assertLessEqual(float(loaded.get("notification_overlay_alpha")), 1.0)
                self.assertEqual(loaded.get("notification_overlay_bg"), "#161616")
                self.assertFalse(bool(loaded.get("status_indicator_enabled")))
                self.assertTrue(bool(loaded.get("status_indicator_flash_enabled")))
                self.assertEqual(loaded.get("status_indicator_color_idle"), "#808080")
                self.assertGreaterEqual(int(loaded.get("output_token_limit")), 900)
                self.assertLessEqual(int(loaded.get("output_token_limit")), 1200)
                self.assertGreaterEqual(int(loaded.get("draft_history_limit")), 10)
                self.assertLessEqual(int(loaded.get("draft_history_limit")), 500)
                self.assertGreaterEqual(int(loaded.get("controller_sequence_window_ms")), 100)
                self.assertLessEqual(float(loaded.get("controller_axis_threshold")), 1.0)
                self.assertEqual(str(loaded.get("experience_preset")), "custom")
            finally:
                if original_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_appdata


if __name__ == "__main__":
    unittest.main()
