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
        self.assertEqual(entry["voice"], {
            "preset": "", "base": "", "blend": {}, "speed": 1.0, "pitch": 0.0,
            "energy": 0.5, "warmth": 0.0, "brightness": 0.0,
            "pause_style": "natural", "stability": 0.5,
        })
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


class VoiceSubSchemaTests(unittest.TestCase):
    def test_dict_blend_round_trips(self):
        entry = llm_engine.normalize_persona({
            "prompt": "P", "voice": {"base": "af_heart", "blend": {"am_adam": 0.2}},
        })
        self.assertEqual(entry["voice"]["blend"], {"am_adam": 0.2})
        self.assertEqual(entry["voice"]["base"], "af_heart")

    def test_legacy_string_blend_migrates_to_empty_dict(self):
        # The legacy schema's bare string was never wired to real playback,
        # so there's no reliable voice name to preserve — safer to discard.
        entry = llm_engine.normalize_persona({"prompt": "P", "voice": {"blend": "af_bella"}})
        self.assertEqual(entry["voice"]["blend"], {})

    def test_invalid_blend_entries_dropped(self):
        entry = llm_engine.normalize_persona({
            "prompt": "P",
            "voice": {"blend": {"am_adam": "0.3", "bad": "nope", "negative": -1, "": 0.5, "zero": 0}},
        })
        self.assertEqual(entry["voice"]["blend"], {"am_adam": 0.3})

    def test_modulation_fields_coerced_with_defaults(self):
        entry = llm_engine.normalize_persona({
            "prompt": "P",
            "voice": {"pitch": "2", "energy": "0.9", "warmth": "bad", "pause_style": "dramatic"},
        })
        self.assertEqual(entry["voice"]["pitch"], 2.0)
        self.assertEqual(entry["voice"]["energy"], 0.9)
        self.assertEqual(entry["voice"]["warmth"], 0.0)  # bad value -> default
        self.assertEqual(entry["voice"]["pause_style"], "dramatic")
        self.assertEqual(entry["voice"]["brightness"], 0.0)  # unset -> default

    def test_stability_is_stored_only(self):
        # No runtime effect (see voice_modulation.py) — just confirm it
        # round-trips like any other stored field.
        entry = llm_engine.normalize_persona({"prompt": "P", "voice": {"stability": 0.8}})
        self.assertEqual(entry["voice"]["stability"], 0.8)

    def test_preset_field_stored_as_authored_string(self):
        entry = llm_engine.normalize_persona({"prompt": "P", "voice": {"preset": "Warm Assistant"}})
        self.assertEqual(entry["voice"]["preset"], "Warm Assistant")

    def test_base_not_alias_resolved_at_normalize_time(self):
        # Alias resolution (e.g. "english" -> "af_heart") happens at
        # consumption time in tts_engine._resolve_voice_spec, not here.
        entry = llm_engine.normalize_persona({"prompt": "P", "voice": {"base": "english"}})
        self.assertEqual(entry["voice"]["base"], "english")

    def test_non_dict_voice_falls_back_to_full_default(self):
        entry = llm_engine.normalize_persona({"prompt": "P", "voice": "not a dict"})
        self.assertEqual(entry["voice"]["blend"], {})
        self.assertEqual(entry["voice"]["base"], "")


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


class PersonaCardTests(unittest.TestCase):
    def test_default_persona_has_empty_card(self):
        entry = llm_engine.default_persona("P")
        self.assertEqual(entry["persona_card"], llm_engine.default_persona_card())

    def test_legacy_string_and_none_get_empty_card(self):
        self.assertEqual(llm_engine.normalize_persona("Rewrite only.")["persona_card"]["reliability_score"], 0)
        self.assertEqual(llm_engine.normalize_persona(None)["persona_card"], llm_engine.default_persona_card())

    def test_full_card_round_trips_and_coerces(self):
        raw = {
            "prompt": "P",
            "persona_card": {
                "display_name": "Vivian Glass",
                "archetype": "executive editor",
                "temperament": ["precise", "dry", 7, None],
                "favorite_phrases": ["Cut the hedging."],
                "forbidden": ["do not apologize"],
                "signature_moves": ["tighten verbs"],
                "best_use_cases": ["email", "proposals"],
                "anti_examples": ["sounds fake if too warm"],
                "eval_cases": [{"category": "angry", "input": "ugh", "output": "Understood.", "verdict": "approved"}, "junk"],
                "reliability_score": "85",
            },
        }
        entry = llm_engine.normalize_persona(raw)
        card = entry["persona_card"]
        self.assertEqual(card["display_name"], "Vivian Glass")
        self.assertEqual(card["archetype"], "executive editor")
        self.assertEqual(card["temperament"], ["precise", "dry", "7"])
        self.assertEqual(card["favorite_phrases"], ["Cut the hedging."])
        self.assertEqual(len(card["eval_cases"]), 1)
        self.assertEqual(card["eval_cases"][0]["category"], "angry")
        self.assertEqual(card["reliability_score"], 85)

    def test_malformed_card_is_defensive(self):
        self.assertEqual(llm_engine.normalize_persona({"prompt": "P", "persona_card": "junk"})["persona_card"], llm_engine.default_persona_card())
        self.assertEqual(llm_engine.normalize_persona({"prompt": "P", "persona_card": {"reliability_score": "not a number"}})["persona_card"]["reliability_score"], 0)
        self.assertEqual(llm_engine.normalize_persona({"prompt": "P", "persona_card": {"reliability_score": 999}})["persona_card"]["reliability_score"], 100)

    def test_validate_rejects_non_dict_card_only_when_present(self):
        ok, _ = llm_engine.validate_persona({"prompt": "P"})
        self.assertTrue(ok)
        entry = llm_engine.normalize_persona({"prompt": "P"})
        entry["persona_card"] = "not a dict"
        ok, msg = llm_engine.validate_persona(entry)
        self.assertFalse(ok)
        self.assertIn("persona_card", msg.lower())


class ReliabilityScoreTests(unittest.TestCase):
    def test_base_score_with_no_examples_and_a_contradiction(self):
        self.assertEqual(llm_engine.compute_reliability_score({}, num_examples=0, had_contradiction=True), 40)

    def test_examples_cap_at_three(self):
        self.assertEqual(llm_engine.compute_reliability_score({}, num_examples=3, had_contradiction=True), 70)
        self.assertEqual(llm_engine.compute_reliability_score({}, num_examples=10, had_contradiction=True), 70)

    def test_no_contradiction_bonus(self):
        self.assertEqual(llm_engine.compute_reliability_score({}, num_examples=0, had_contradiction=False), 50)

    def test_stress_approval_ratio_contributes_up_to_twenty(self):
        full = llm_engine.compute_reliability_score({}, num_examples=3, had_contradiction=False, stress_approval_ratio=1.0)
        self.assertEqual(full, 100)
        half = llm_engine.compute_reliability_score({}, num_examples=0, had_contradiction=True, stress_approval_ratio=0.5)
        self.assertEqual(half, 50)

    def test_score_clamped_to_0_100(self):
        self.assertEqual(llm_engine.compute_reliability_score({}, num_examples=-5, had_contradiction=True), 40)


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


class TrueV1FlatFileMigrationTests(_TempAppdataMixin, unittest.TestCase):
    """A TRUE v1 file has no "personas"/"schema_version" wrapper at all — the
    whole top-level mapping IS {name: prompt-string}, per the module's own
    "v1 == flat {name: promptstring}" comment. Before store_migration.py
    adoption, _read_personas_v2 always did data.get("personas", {})
    unconditionally, which silently discarded a real v1 file's contents
    (found while wiring up migration discipline, not previously covered by
    any test — LoadLegacyFormatTests above tests a v2-wrapper-shape file
    with v1-style string VALUES, a different thing)."""

    def test_true_v1_flat_file_migrates_and_keeps_its_personas(self):
        os.makedirs(os.path.dirname(self._path()), exist_ok=True)
        with open(self._path(), "w", encoding="utf-8") as f:
            yaml.safe_dump({"Assistant": "Be helpful.", "Coder": "Write clean code."}, f)

        v2 = llm_engine.load_personas_v2(force_reload=True)
        self.assertEqual(v2["Assistant"]["prompt"], "Be helpful.")
        self.assertEqual(v2["Coder"]["prompt"], "Write clean code.")

    def test_migrated_file_is_saved_as_v2_on_next_write(self):
        os.makedirs(os.path.dirname(self._path()), exist_ok=True)
        with open(self._path(), "w", encoding="utf-8") as f:
            yaml.safe_dump({"Assistant": "Be helpful."}, f)

        llm_engine.load_personas_v2(force_reload=True)
        llm_engine.upsert_persona("New", "Another one.")

        with open(self._path(), "r", encoding="utf-8") as f:
            on_disk = yaml.safe_load(f)
        self.assertEqual(on_disk["schema_version"], llm_engine.PERSONA_SCHEMA_VERSION)
        self.assertIn("Assistant", on_disk["personas"])
        self.assertIn("New", on_disk["personas"])


class CorruptPersonasQuarantineTests(_TempAppdataMixin, unittest.TestCase):
    def test_corrupt_yaml_is_quarantined_not_silently_discarded(self):
        os.makedirs(os.path.dirname(self._path()), exist_ok=True)
        with open(self._path(), "w", encoding="utf-8") as f:
            f.write("personas: [unterminated\n  - broken: yaml: :::")

        with self.assertLogs(level="WARNING") as log_ctx:
            v2 = llm_engine.load_personas_v2(force_reload=True)

        # Falls back to built-in defaults rather than crashing.
        self.assertIn("True Janitor", v2)
        # The corrupt file is preserved (quarantined), not deleted outright.
        self.assertFalse(os.path.exists(self._path()))
        self.assertTrue(os.path.exists(f"{self._path()}.corrupt"))
        self.assertTrue(any("personas.yaml" in msg for msg in log_ctx.output))

    def test_quarantine_happens_before_any_save_can_overwrite_evidence(self):
        # The ordering this test pins: load (quarantines) THEN save (writes
        # a fresh file) must never happen in the other order, or the
        # original corrupt content would be silently clobbered with no trace
        # it ever existed — the exact risk the plan flagged.
        os.makedirs(os.path.dirname(self._path()), exist_ok=True)
        with open(self._path(), "w", encoding="utf-8") as f:
            f.write(":::not valid yaml:::[[[")

        llm_engine.load_personas_v2(force_reload=True)  # quarantines
        self.assertTrue(os.path.exists(f"{self._path()}.corrupt"))
        with open(f"{self._path()}.corrupt", "r", encoding="utf-8") as f:
            preserved = f.read()
        self.assertEqual(preserved, ":::not valid yaml:::[[[")

        llm_engine.upsert_persona("Fresh", "Start clean.")  # writes a NEW file
        # The quarantined original is untouched by the subsequent save.
        with open(f"{self._path()}.corrupt", "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), preserved)


class PersonaDowngradeRefusalTests(_TempAppdataMixin, unittest.TestCase):
    def test_future_schema_version_is_never_touched(self):
        os.makedirs(os.path.dirname(self._path()), exist_ok=True)
        future_payload = {
            "schema_version": llm_engine.PERSONA_SCHEMA_VERSION + 1,
            "personas": {"FromTheFuture": {"prompt": "unknown fields ahead"}},
        }
        with open(self._path(), "w", encoding="utf-8") as f:
            yaml.safe_dump(future_payload, f)

        with self.assertLogs(level="WARNING"):
            v2 = llm_engine.load_personas_v2(force_reload=True)

        # In-memory: falls back to defaults rather than misinterpreting
        # future fields it doesn't understand.
        self.assertNotIn("FromTheFuture", v2)
        self.assertIn("True Janitor", v2)

        # On disk: byte-for-byte untouched.
        with open(self._path(), "r", encoding="utf-8") as f:
            on_disk = yaml.safe_load(f)
        self.assertEqual(on_disk, future_payload)
        self.assertFalse(os.path.exists(f"{self._path()}.corrupt"))
        self.assertFalse(os.path.exists(f"{self._path()}.bak-v{llm_engine.PERSONA_SCHEMA_VERSION + 1}"))


if __name__ == "__main__":
    unittest.main()
