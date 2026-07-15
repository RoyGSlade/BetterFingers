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


class _TempAppdataMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._orig
        self._tmp.cleanup()


class ProfileQuarantineTests(_TempAppdataMixin, unittest.TestCase):
    def test_corrupt_profile_is_quarantined_and_recreated_with_defaults(self):
        profiles_dir = utils.get_profiles_dir()
        path = os.path.join(profiles_dir, "Broken.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(":::not valid yaml:::[[[")

        with self.assertLogs(level="WARNING") as log_ctx:
            loaded = utils.load_profile("Broken")

        self.assertEqual(loaded.get("send_mode"), utils._profile_defaults()["send_mode"])
        self.assertTrue(os.path.exists(f"{path}.corrupt"))
        self.assertTrue(any("Broken.yaml" in msg for msg in log_ctx.output))
        # Recreated on disk with defaults, same as a never-existed profile —
        # not left running on in-memory-only settings.
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as f:
            on_disk = yaml.safe_load(f)
        self.assertEqual(on_disk.get("schema_version"), utils._PROFILE_SCHEMA_VERSION)

    def test_quarantine_happens_before_the_recreate_save_can_clobber_evidence(self):
        profiles_dir = utils.get_profiles_dir()
        path = os.path.join(profiles_dir, "Broken2.yaml")
        original_content = ":::not valid yaml:::[[["
        with open(path, "w", encoding="utf-8") as f:
            f.write(original_content)

        utils.load_profile("Broken2")  # quarantines, then recreates the file

        with open(f"{path}.corrupt", "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), original_content)


class ProfileDowngradeRefusalTests(_TempAppdataMixin, unittest.TestCase):
    def test_future_schema_version_is_never_touched(self):
        profiles_dir = utils.get_profiles_dir()
        path = os.path.join(profiles_dir, "Future.yaml")
        future_payload = {
            "schema_version": utils._PROFILE_SCHEMA_VERSION + 1,
            "send_mode": "some_future_mode",
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(future_payload, f)

        with self.assertLogs(level="WARNING"):
            loaded = utils.load_profile("Future")

        # In-memory: bare defaults, not a mangled interpretation of unknown
        # future fields.
        self.assertEqual(loaded.get("send_mode"), utils._profile_defaults()["send_mode"])

        # On disk: byte-for-byte untouched.
        with open(path, "r", encoding="utf-8") as f:
            on_disk = yaml.safe_load(f)
        self.assertEqual(on_disk, future_payload)
        self.assertFalse(os.path.exists(f"{path}.corrupt"))


class AppStateQuarantineTests(_TempAppdataMixin, unittest.TestCase):
    def test_corrupt_app_state_is_quarantined_not_silently_dropped(self):
        path = utils._app_state_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(":::not valid:::[[[")

        state = utils.load_app_state()

        self.assertEqual(state, utils._app_state_defaults())
        self.assertTrue(os.path.exists(f"{path}.corrupt"))
        self.assertFalse(os.path.exists(path))

    def test_save_then_load_round_trips_with_schema_version_stamped(self):
        utils.save_app_state({"launch_count": 3, "donation_prompt_shown": True, "last_active_profile": "Work"})
        with open(utils._app_state_path(), "r", encoding="utf-8") as f:
            on_disk = yaml.safe_load(f)
        self.assertEqual(on_disk["schema_version"], utils._APP_STATE_SCHEMA_VERSION)

        state = utils.load_app_state()
        self.assertEqual(state["launch_count"], 3)
        self.assertTrue(state["donation_prompt_shown"])
        self.assertEqual(state["last_active_profile"], "Work")
        # schema_version is a persistence-layer concern, not exposed to callers.
        self.assertNotIn("schema_version", state)

    def test_save_leaves_no_temp_file_behind(self):
        utils.save_app_state({"launch_count": 1})
        directory = os.path.dirname(utils._app_state_path())
        leftovers = [f for f in os.listdir(directory) if f != os.path.basename(utils._app_state_path())]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
