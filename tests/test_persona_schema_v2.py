import os
import tempfile
import unittest

import yaml

import llm_engine


class NormalizePersonaTests(unittest.TestCase):
    def test_flat_string_upgrades_to_v2(self):
        entry = llm_engine.normalize_persona("Rewrite only.")
        self.assertEqual(entry["prompt"], "Rewrite only.")
        self.assertIsNone(entry["temperature"])
        self.assertEqual(entry["few_shot"], [])
        self.assertEqual(entry["voice"], {"base": "", "blend": "", "speed": 1.0})
        self.assertEqual(entry["format"], {"caps": "none", "punctuation": True, "signoff": ""})
        self.assertEqual(entry["dictionary_scope"], "global")
        self.assertEqual(entry["model_hint"], "")

    def test_none_and_bad_types_are_defensive(self):
        self.assertEqual(llm_engine.normalize_persona(None)["prompt"], "")
        self.assertEqual(llm_engine.normalize_persona(123)["prompt"], "123")

    def test_partial_dict_fills_defaults(self):
        entry = llm_engine.normalize_persona({"prompt": "Hi", "temperature": 0.7})
        self.assertEqual(entry["prompt"], "Hi")
        self.assertEqual(entry["temperature"], 0.7)
        self.assertEqual(entry["few_shot"], [])

    def test_full_dict_round_trips_and_coerces(self):
        raw = {
            "prompt": "P",
            "temperature": "0.4",
            "few_shot": [{"raw": "u", "out": "c"}, "junk", {"raw": "x"}],
            "voice": {"base": "af", "blend": "af_bella", "speed": "1.25"},
            "format": {"caps": "sentence", "punctuation": False, "signoff": "-J"},
            "dictionary_scope": "persona",
            "model_hint": "gemma-4b",
        }
        entry = llm_engine.normalize_persona(raw)
        self.assertEqual(entry["temperature"], 0.4)
        self.assertEqual(entry["few_shot"], [{"raw": "u", "out": "c"}, {"raw": "x", "out": ""}])
        self.assertEqual(entry["voice"]["speed"], 1.25)
        self.assertFalse(entry["format"]["punctuation"])
        self.assertEqual(entry["dictionary_scope"], "persona")
        self.assertEqual(entry["model_hint"], "gemma-4b")

    def test_bad_temperature_becomes_none(self):
        self.assertIsNone(llm_engine.normalize_persona({"prompt": "P", "temperature": "hot"})["temperature"])


class ValidatePersonaTests(unittest.TestCase):
    def test_missing_prompt_rejected(self):
        ok, msg = llm_engine.validate_persona({"prompt": "  "})
        self.assertFalse(ok)
        self.assertIn("prompt", msg.lower())

    def test_temperature_range_enforced(self):
        ok, _ = llm_engine.validate_persona({"prompt": "P", "temperature": 3.0})
        self.assertFalse(ok)
        ok, _ = llm_engine.validate_persona({"prompt": "P", "temperature": 1.0})
        self.assertTrue(ok)

    def test_string_is_validated_after_normalize(self):
        ok, _ = llm_engine.validate_persona("Rewrite only.")
        self.assertTrue(ok)


class _TempAppdataMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name
        llm_engine._personas_cache = None
        llm_engine._personas_v2_cache = None

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._orig
        self._tmp.cleanup()
        llm_engine._personas_cache = None
        llm_engine._personas_v2_cache = None

    def _path(self):
        return llm_engine._get_personas_path()


class LoadLegacyFormatTests(_TempAppdataMixin, unittest.TestCase):
    def test_legacy_flat_file_loads_and_migrates_in_memory(self):
        # Hand-write a v1 file: flat {name: promptstring}, no schema_version.
        os.makedirs(os.path.dirname(self._path()), exist_ok=True)
        with open(self._path(), "w", encoding="utf-8") as f:
            yaml.safe_dump({"personas": {"Legacy": "Clean it up."}}, f)

        legacy_view = llm_engine.load_personas(force_reload=True)
        self.assertEqual(legacy_view["Legacy"], "Clean it up.")

        v2 = llm_engine.load_personas_v2(force_reload=True)
        self.assertEqual(v2["Legacy"]["prompt"], "Clean it up.")
        self.assertEqual(v2["Legacy"]["voice"]["speed"], 1.0)

    def test_get_persona_prompt_still_returns_string(self):
        os.makedirs(os.path.dirname(self._path()), exist_ok=True)
        with open(self._path(), "w", encoding="utf-8") as f:
            yaml.safe_dump({"personas": {"Legacy": "Clean it up."}}, f)
        self.assertEqual(llm_engine.get_persona_prompt("Legacy"), "Clean it up.")


class LoadNewFormatTests(_TempAppdataMixin, unittest.TestCase):
    def test_defaults_file_is_v2_on_disk(self):
        llm_engine.load_personas_v2(force_reload=True)  # triggers ensure_default_personas
        with open(self._path(), "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.assertEqual(data["schema_version"], llm_engine.PERSONA_SCHEMA_VERSION)
        self.assertIn("True Janitor", data["personas"])
        self.assertIn("prompt", data["personas"]["True Janitor"])

    def test_v2_file_loads_rich_fields(self):
        os.makedirs(os.path.dirname(self._path()), exist_ok=True)
        payload = {
            "schema_version": 2,
            "personas": {"Rich": llm_engine.normalize_persona({"prompt": "P", "temperature": 0.5})},
        }
        with open(self._path(), "w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f)
        v2 = llm_engine.load_personas_v2(force_reload=True)
        self.assertEqual(v2["Rich"]["temperature"], 0.5)


class UpsertV2Tests(_TempAppdataMixin, unittest.TestCase):
    def test_upsert_plain_string_persists_v2(self):
        ok, _ = llm_engine.upsert_persona("Simple", "Just clean.")
        self.assertTrue(ok)
        with open(self._path(), "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.assertEqual(data["schema_version"], 2)
        self.assertEqual(data["personas"]["Simple"]["prompt"], "Just clean.")

    def test_upsert_rich_dict_round_trips(self):
        ok, _ = llm_engine.upsert_persona(
            "Fancy",
            {"prompt": "Rewrite.", "temperature": 0.9, "model_hint": "gemma-4b"},
        )
        self.assertTrue(ok)
        entry = llm_engine.get_persona("Fancy")
        self.assertEqual(entry["temperature"], 0.9)
        self.assertEqual(entry["model_hint"], "gemma-4b")
        # Legacy view still exposes the prompt string.
        self.assertEqual(llm_engine.get_persona_prompt("Fancy"), "Rewrite.")

    def test_partial_update_preserves_rich_fields(self):
        llm_engine.upsert_persona("Keep", {"prompt": "One", "temperature": 0.3})
        llm_engine.upsert_persona("Keep", "Two")  # prompt-only update
        entry = llm_engine.get_persona("Keep")
        self.assertEqual(entry["prompt"], "Two")
        self.assertEqual(entry["temperature"], 0.3)

    def test_upsert_invalid_temperature_rejected(self):
        ok, msg = llm_engine.upsert_persona("Bad", {"prompt": "P", "temperature": 9})
        self.assertFalse(ok)
        self.assertIn("temperature", msg.lower())

    def test_empty_prompt_rejected(self):
        ok, _ = llm_engine.upsert_persona("Empty", "   ")
        self.assertFalse(ok)


class GetPersonaCopyTests(_TempAppdataMixin, unittest.TestCase):
    """get_persona() must return an isolated copy — mutating nested fields
    (voice/format/few_shot) must never corrupt the shared in-memory cache."""

    def test_mutating_nested_dict_does_not_corrupt_cache(self):
        llm_engine.upsert_persona("Mutable", {"prompt": "P", "voice": {"base": "af_heart", "speed": 1.0}})

        entry = llm_engine.get_persona("Mutable")
        entry["voice"]["speed"] = 99.0
        entry["format"]["signoff"] = "-hacked"

        fresh = llm_engine.get_persona("Mutable")
        self.assertEqual(fresh["voice"]["speed"], 1.0)
        self.assertEqual(fresh["format"]["signoff"], "")

    def test_mutating_few_shot_list_does_not_corrupt_cache(self):
        llm_engine.upsert_persona("Mutable2", {"prompt": "P", "few_shot": [{"raw": "hi", "out": "Hello."}]})

        entry = llm_engine.get_persona("Mutable2")
        entry["few_shot"].append({"raw": "bye", "out": "Goodbye."})

        fresh = llm_engine.get_persona("Mutable2")
        self.assertEqual(len(fresh["few_shot"]), 1)


class DeleteV2Tests(_TempAppdataMixin, unittest.TestCase):
    def test_delete_custom_persona(self):
        llm_engine.upsert_persona("Temp", "x")
        ok, _ = llm_engine.delete_persona("Temp")
        self.assertTrue(ok)
        self.assertIsNone(llm_engine.get_persona("Temp"))

    def test_delete_all_restores_v2_defaults(self):
        llm_engine.load_personas_v2(force_reload=True)
        v2 = llm_engine.load_personas_v2()
        for name in [n for n in v2 if n.lower() != "true janitor"]:
            llm_engine.delete_persona(name, allow_builtin=True)
        # Deleting the last non-janitor leaves janitor; deleting everything else is blocked on janitor.
        remaining = llm_engine.load_personas_v2(force_reload=True)
        self.assertIn("True Janitor", remaining)
        self.assertIn("prompt", remaining["True Janitor"])


if __name__ == "__main__":
    unittest.main()
