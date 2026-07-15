import json
import os
import tempfile
import unittest

import voice_presets


class VoicePresetsTests(unittest.TestCase):
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

    def _path(self):
        return voice_presets._presets_path()

    def test_missing_file_returns_empty_list_silently(self):
        self.assertEqual(voice_presets.get_presets(), [])

    def test_save_defaults_everything(self):
        presets = voice_presets.save_preset("Warm Assistant", base="af_heart")
        self.assertEqual(len(presets), 1)
        preset = presets[0]
        self.assertEqual(preset["name"], "Warm Assistant")
        self.assertEqual(preset["base"], "af_heart")
        self.assertEqual(preset["blend"], {})
        self.assertEqual(preset["speed"], 1.0)
        self.assertEqual(preset["pitch"], 0.0)
        self.assertEqual(preset["energy"], 0.5)
        self.assertEqual(preset["pause_style"], "natural")
        self.assertIn("created_at", preset)
        self.assertIn("updated_at", preset)

    def test_save_then_get_round_trips(self):
        voice_presets.save_preset(
            "Warm Assistant", base="af_heart", blend={"am_adam": 0.2}, speed=1.05,
        )
        presets = voice_presets.get_presets()
        self.assertEqual(len(presets), 1)
        self.assertEqual(presets[0]["blend"], {"am_adam": 0.2})
        self.assertEqual(presets[0]["speed"], 1.05)
        # A second read (fresh file handle) must also succeed.
        self.assertEqual(voice_presets.get_presets(), presets)

    def test_upsert_by_name_case_insensitive_preserves_unspecified_fields(self):
        voice_presets.save_preset("Warm Assistant", base="af_heart", pitch=2.0)
        presets = voice_presets.save_preset("warm assistant", speed=1.2)
        self.assertEqual(len(presets), 1)
        preset = presets[0]
        # Name casing from the update call wins (matches macros.py upsert style).
        self.assertEqual(preset["name"], "warm assistant")
        self.assertEqual(preset["speed"], 1.2)
        # Unspecified field is preserved from the prior save, not reset to default.
        self.assertEqual(preset["pitch"], 2.0)

    def test_blank_name_is_noop(self):
        voice_presets.save_preset("Warm Assistant", base="af_heart")
        result = voice_presets.save_preset("   ", base="am_puck")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Warm Assistant")

    def test_delete_by_name_case_insensitive(self):
        voice_presets.save_preset("Warm Assistant", base="af_heart")
        voice_presets.save_preset("Crisp Editor", base="am_puck")
        remaining = voice_presets.delete_preset("warm assistant")
        self.assertEqual([p["name"] for p in remaining], ["Crisp Editor"])

    def test_delete_missing_name_is_noop(self):
        voice_presets.save_preset("Warm Assistant", base="af_heart")
        remaining = voice_presets.delete_preset("does not exist")
        self.assertEqual(len(remaining), 1)

    def test_blend_weights_coerced_and_invalid_entries_dropped(self):
        voice_presets.save_preset(
            "Mix",
            base="af_heart",
            blend={"am_adam": "0.3", "bad": "nope", "negative": -1, "": 0.5},
        )
        preset = voice_presets.get_presets()[0]
        self.assertEqual(preset["blend"], {"am_adam": 0.3})

    def test_corrupted_file_is_quarantined_and_logged(self):
        path = self._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not valid json,,,")

        with self.assertLogs(level="WARNING") as log_ctx:
            result = voice_presets.get_presets()

        self.assertEqual(result, [])
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(f"{path}.corrupt"))
        self.assertTrue(any("corrupted" in msg for msg in log_ctx.output))

    def test_recovers_after_quarantine_and_can_save_again(self):
        path = self._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("not json")

        with self.assertLogs(level="WARNING"):
            voice_presets.get_presets()

        voice_presets.save_preset("Warm Assistant", base="af_heart")
        self.assertEqual(len(voice_presets.get_presets()), 1)

    def test_duplicate_names_in_raw_file_deduped_on_read(self):
        path = self._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        import json
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {"presets": [
                    {"name": "Warm Assistant", "base": "af_heart"},
                    {"name": "warm assistant", "base": "am_puck"},
                ]},
                handle,
            )
        presets = voice_presets.get_presets()
        self.assertEqual(len(presets), 1)

    def test_nameless_entry_in_raw_file_skipped(self):
        path = self._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        import json
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"presets": [{"base": "af_heart"}]}, handle)
        self.assertEqual(voice_presets.get_presets(), [])

    def test_save_stamps_schema_version(self):
        voice_presets.save_preset("Warm", base="af_heart")
        with open(self._path(), "r", encoding="utf-8") as handle:
            on_disk = json.load(handle)
        self.assertEqual(on_disk.get("schema_version"), voice_presets._SCHEMA_VERSION)

    def test_legacy_file_with_no_schema_version_loads_as_v1(self):
        path = self._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"presets": [{"name": "Legacy", "base": "af_heart"}]}, handle)
        presets = voice_presets.get_presets()
        self.assertEqual(len(presets), 1)
        self.assertEqual(presets[0]["name"], "Legacy")

    def test_save_leaves_no_temp_file_behind(self):
        voice_presets.save_preset("Warm", base="af_heart")
        directory = os.path.dirname(self._path())
        leftovers = [f for f in os.listdir(directory) if f != os.path.basename(self._path())]
        self.assertEqual(leftovers, [])

    def test_future_schema_version_is_never_touched(self):
        path = self._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        future_payload = {
            "schema_version": voice_presets._SCHEMA_VERSION + 1,
            "presets": [{"name": "FromTheFuture", "base": "af_heart"}],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(future_payload, f)

        presets = voice_presets.get_presets()

        # In-memory: bare defaults, not a misread of unknown future fields.
        self.assertEqual(presets, [])
        # On disk: byte-for-byte untouched.
        with open(path, "r", encoding="utf-8") as f:
            on_disk = json.load(f)
        self.assertEqual(on_disk, future_payload)
        self.assertFalse(os.path.exists(f"{path}.corrupt"))


if __name__ == "__main__":
    unittest.main()
