"""Application-profile schema v1 and its store (Wave 7).

Three things carry the weight here:

  * the field list is CLOSED -- a payload carrying a recipient, a contact id or
    a conversation summary is rejected and the caller is told, which is the
    schema half of the Wave 7 no-inference rule;
  * built-in match rules are HONEST -- every process name is lowercase and
    class-level, and the two profiles that deliberately match nothing (Default
    and the generic game) still match nothing;
  * reads survive a hand-edited or corrupt file rather than taking the feature
    down with it.
"""

import json
import os
import tempfile
import unittest

from backend.stores import app_profiles as ap


class SchemaTests(unittest.TestCase):
    def test_builtin_ids_are_the_required_set(self):
        self.assertEqual(
            set(ap.BUILTIN_PROFILE_IDS),
            {"default", "discord", "email", "game_generic", "rocket_league",
             "world_of_warcraft", "writing_app"},
        )

    def test_every_builtin_is_a_complete_v1_document(self):
        for profile in ap.builtin_profiles():
            self.assertEqual(set(profile), set(ap.PROFILE_FIELDS), profile.get("id"))
            self.assertEqual(profile["schema_version"], ap.SCHEMA_VERSION)
            self.assertEqual(set(profile["match"]), set(ap.MATCH_FIELDS))
            self.assertEqual(set(profile["tts"]), set(ap.TTS_FIELDS))
            self.assertIn(profile["performance_preset"], ap.PERFORMANCE_PRESETS)
            self.assertIn(profile["injection_policy"], ap.INJECTION_POLICIES)

    def test_default_and_generic_game_match_nothing(self):
        by_id = {p["id"]: p for p in ap.builtin_profiles()}
        for pid in ("default", "game_generic"):
            self.assertEqual(by_id[pid]["match"]["process_names"], [], pid)
            self.assertEqual(by_id[pid]["match"]["window_patterns"], [], pid)

    def test_match_rules_are_lowercase_class_level_names(self):
        for profile in ap.builtin_profiles():
            for name in profile["match"]["process_names"]:
                self.assertEqual(name, name.lower(), name)
                # A path or an argv string is not a window class / process name.
                self.assertNotIn("/", name)
                self.assertNotIn(" ", name)

    def test_window_patterns_all_compile(self):
        import re
        for profile in ap.builtin_profiles():
            for pattern in profile["match"]["window_patterns"]:
                re.compile(pattern)  # raises on failure

    def test_gaming_profiles_never_auto_deliver(self):
        by_id = {p["id"]: p for p in ap.builtin_profiles()}
        for pid in ("game_generic", "rocket_league", "world_of_warcraft"):
            self.assertEqual(by_id[pid]["performance_preset"], "minimal", pid)
            self.assertEqual(by_id[pid]["injection_policy"], "review_only", pid)

    def test_writing_app_pastes_matching_the_measured_pacing_policy(self):
        # injection_pacing.DEFAULT_PACING forces a paste for LibreOffice because
        # the M2 probe caught fast synthetic typing mangling text there.
        by_id = {p["id"]: p for p in ap.builtin_profiles()}
        self.assertEqual(by_id["writing_app"]["injection_policy"], "paste")

    def test_builtin_copies_are_independent(self):
        first = ap.builtin_profiles()[0]
        first["match"]["process_names"].append("mutated")
        self.assertEqual(ap.builtin_profiles()[0]["match"]["process_names"], [])


class SanitizeTests(unittest.TestCase):
    def test_unknown_keys_are_dropped_and_reported(self):
        fields, dropped = ap.sanitize_profile({
            "id": "discord",
            "recipient": "Priya",
            "contact_id": "a1",
            "conversation_summary": "about the trip",
            "user_intent": "apologise",
        })
        self.assertEqual(set(fields), set(ap.EDITABLE_FIELDS))
        for key in ("recipient", "contact_id", "conversation_summary", "user_intent"):
            self.assertIn(key, dropped)

    def test_nested_unknown_keys_are_dropped_and_reported(self):
        _fields, dropped = ap.sanitize_profile({
            "id": "discord",
            "match": {"process_names": ["discord"], "window_titles": ["Priya - Discord"]},
            "tts": {"announce_activation": True, "announce_recipient": True},
        })
        self.assertIn("match.window_titles", dropped)
        self.assertIn("tts.announce_recipient", dropped)

    def test_invalid_vocabulary_falls_back_to_the_safe_value(self):
        fields, _ = ap.sanitize_profile(
            {"id": "x", "performance_preset": "turbo", "injection_policy": "telepathy"}
        )
        self.assertEqual(fields["performance_preset"], "balanced")
        self.assertEqual(fields["injection_policy"], "auto")

    def test_blank_writing_preset_is_none_not_empty_string(self):
        fields, _ = ap.sanitize_profile({"id": "x", "writing_preset": "  "})
        self.assertIsNone(fields["writing_preset"])

    def test_uncompilable_window_pattern_is_dropped_not_raised(self):
        fields, _ = ap.sanitize_profile(
            {"id": "x", "match": {"window_patterns": ["(unclosed", "^ok$"]}}
        )
        self.assertEqual(fields["match"]["window_patterns"], ["^ok$"])

    def test_unknown_binding_slots_are_dropped_and_reported(self):
        fields, dropped = ap.sanitize_profile({
            "id": "x",
            "bindings": {"record_toggle": {"events": ["button:4"]}, "taunt": {}},
        })
        self.assertEqual(set(fields["bindings"]), {"record_toggle"})
        self.assertIn("bindings.taunt", dropped)

    def test_normalize_profile_id_rejects_junk(self):
        self.assertEqual(ap.normalize_profile_id("Rocket League"), "rocket_league")
        self.assertEqual(ap.normalize_profile_id("  "), "")
        self.assertEqual(ap.normalize_profile_id("../../etc/passwd"), "etc_passwd")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "app_profiles.json")
        self.store = ap.AppProfileStore(path=self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_fresh_store_lists_the_builtins_with_default_first(self):
        listed = self.store.list_profiles()
        self.assertEqual(listed[0]["id"], "default")
        self.assertEqual([p["id"] for p in listed], list(ap.BUILTIN_PROFILE_IDS))
        self.assertFalse(os.path.exists(self.path), "listing must not write")

    def test_saving_an_overlay_replaces_the_builtin_in_place(self):
        result = self.store.save({"id": "discord", "performance_preset": "quality"})
        self.assertTrue(result["ok"])
        listed = self.store.list_profiles()
        self.assertEqual([p["id"] for p in listed], list(ap.BUILTIN_PROFILE_IDS))
        self.assertEqual(self.store.get("discord")["performance_preset"], "quality")

    def test_reset_restores_the_shipped_builtin(self):
        self.store.save({"id": "discord", "performance_preset": "quality"})
        self.assertTrue(self.store.reset("discord")["reset"])
        self.assertEqual(self.store.get("discord")["performance_preset"], "low_latency")

    def test_user_created_profiles_follow_the_builtins(self):
        self.store.save({"id": "my_editor", "injection_policy": "paste"})
        listed = [p["id"] for p in self.store.list_profiles()]
        self.assertEqual(listed[:len(ap.BUILTIN_PROFILE_IDS)], list(ap.BUILTIN_PROFILE_IDS))
        self.assertIn("my_editor", listed)

    def test_pin_and_unpin_round_trip(self):
        self.assertTrue(self.store.pin("someindiegame", "game_generic")["ok"])
        self.assertEqual(self.store.pinned_for("someindiegame"), "game_generic")
        self.assertTrue(self.store.pin("someindiegame", "")["ok"])
        self.assertEqual(self.store.pinned_for("someindiegame"), "")

    def test_pin_to_a_missing_profile_is_refused(self):
        result = self.store.pin("foo", "no_such_profile")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "not_found")

    def test_pin_to_a_deleted_profile_reads_as_no_pin(self):
        self.store.save({"id": "my_editor"})
        self.store.pin("kate", "my_editor")
        self.store.reset("my_editor")
        self.assertEqual(self.store.pinned_for("kate"), "")

    def test_writes_are_atomic_and_leave_no_temp_files(self):
        self.store.save({"id": "my_editor"})
        leftovers = [n for n in os.listdir(self._tmp.name) if n.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_corrupt_file_degrades_to_the_builtins(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{not json at all")
        self.assertEqual(
            [p["id"] for p in self.store.list_profiles()], list(ap.BUILTIN_PROFILE_IDS)
        )

    def test_hand_edited_record_degrades_field_by_field(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({
                "schema_version": 1,
                "profiles": {
                    "discord": {"id": "discord", "performance_preset": "nonsense"},
                    "": {"id": "", "performance_preset": "quality"},
                },
            }, fh)
        self.assertEqual(self.store.get("discord")["performance_preset"], "balanced")
        self.assertEqual([p["id"] for p in self.store.list_profiles()],
                         list(ap.BUILTIN_PROFILE_IDS))

    def test_missing_schema_version_still_reads(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"profiles": {"discord": {"id": "discord", "injection_policy": "paste"}}}, fh)
        self.assertEqual(self.store.get("discord")["injection_policy"], "paste")

    def test_clear_all_drops_overlays_and_pins(self):
        self.store.save({"id": "my_editor"})
        self.store.pin("kate", "writing_app")
        self.assertTrue(self.store.clear_all()["ok"])
        self.assertEqual([p["id"] for p in self.store.list_profiles()],
                         list(ap.BUILTIN_PROFILE_IDS))
        self.assertEqual(self.store.pinned_map(), {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
