"""Wave 8A / D-0010: output ducking and voice privacy are separate settings,
and every old profile still loads with exactly its old behavior."""

import unittest

import audio_schema as schema


class OutputDuckingSanitizeTests(unittest.TestCase):
    def test_defaults_match_the_legacy_ducker_knobs(self):
        block = schema.sanitize_output_ducking({})
        self.assertEqual(
            block, {"enabled": False, "target_percent": 18.0, "restore_fallback_percent": 100.0}
        )

    def test_non_dict_collapses_to_defaults(self):
        for value in (None, "on", 3, [], True):
            self.assertEqual(schema.sanitize_output_ducking(value), schema.output_ducking_defaults())

    def test_percentages_clamp_to_the_one_to_hundred_window(self):
        block = schema.sanitize_output_ducking(
            {"target_percent": -50, "restore_fallback_percent": 900}
        )
        self.assertEqual(block["target_percent"], 1.0)
        self.assertEqual(block["restore_fallback_percent"], 100.0)

    def test_non_finite_percent_falls_back_instead_of_clamping(self):
        # A NaN would otherwise pass straight through max()/min() and reach the
        # platform volume API.
        block = schema.sanitize_output_ducking({"target_percent": float("nan")})
        self.assertEqual(block["target_percent"], 18.0)
        block = schema.sanitize_output_ducking({"target_percent": "nan"})
        self.assertEqual(block["target_percent"], 18.0)
        block = schema.sanitize_output_ducking({"restore_fallback_percent": float("inf")})
        self.assertEqual(block["restore_fallback_percent"], 100.0)

    def test_string_percent_from_a_form_field_is_coerced(self):
        block = schema.sanitize_output_ducking({"target_percent": "22.5"})
        self.assertEqual(block["target_percent"], 22.5)

    def test_garbage_percent_falls_back_to_default(self):
        block = schema.sanitize_output_ducking({"target_percent": "loud"})
        self.assertEqual(block["target_percent"], 18.0)

    def test_unknown_keys_are_dropped(self):
        block = schema.sanitize_output_ducking({"enabled": True, "fade_ms": 400})
        self.assertEqual(set(block), {"enabled", "target_percent", "restore_fallback_percent"})

    def test_checkbox_strings_are_coerced(self):
        self.assertTrue(schema.sanitize_output_ducking({"enabled": "true"})["enabled"])
        self.assertFalse(schema.sanitize_output_ducking({"enabled": "off"})["enabled"])


class VoicePrivacySanitizeTests(unittest.TestCase):
    def test_defaults(self):
        block = schema.sanitize_voice_privacy({})
        self.assertEqual(
            block,
            {"mode": "off", "mute_binding": "", "keep_unmuted_apps": [], "announce_failures": True},
        )

    def test_all_three_modes_round_trip(self):
        for mode in ("off", "push_to_mute", "isolate_capture_streams"):
            self.assertEqual(schema.sanitize_voice_privacy({"mode": mode})["mode"], mode)

    def test_isolate_capture_streams_is_reserved_but_persisted(self):
        # Wave 8B selects it; storing it now must not need another migration.
        self.assertIn("isolate_capture_streams", schema.PRIVACY_MODES)
        self.assertTrue(schema.is_reserved_mode("isolate_capture_streams"))
        self.assertFalse(schema.is_reserved_mode("push_to_mute"))

    def test_unknown_mode_fails_closed_to_off(self):
        for mode in ("mute_everything", "", None, 7, True, []):
            self.assertEqual(schema.sanitize_voice_privacy({"mode": mode})["mode"], "off")

    def test_mode_is_case_and_whitespace_tolerant(self):
        self.assertEqual(schema.sanitize_voice_privacy({"mode": " Push_To_Mute "})["mode"], "push_to_mute")

    def test_binding_is_trimmed_and_non_strings_collapse(self):
        self.assertEqual(schema.sanitize_voice_privacy({"mute_binding": "  f10 "})["mute_binding"], "f10")
        self.assertEqual(schema.sanitize_voice_privacy({"mute_binding": None})["mute_binding"], "")
        self.assertEqual(schema.sanitize_voice_privacy({"mute_binding": True})["mute_binding"], "")

    def test_keep_unmuted_apps_dedupes_trims_and_drops_blanks(self):
        block = schema.sanitize_voice_privacy(
            {"keep_unmuted_apps": ["Discord", " discord ", "", "  ", None, "OBS", True]}
        )
        self.assertEqual(block["keep_unmuted_apps"], ["Discord", "OBS"])

    def test_keep_unmuted_apps_is_capped(self):
        block = schema.sanitize_voice_privacy(
            {"keep_unmuted_apps": [f"app{i}" for i in range(schema.MAX_KEEP_UNMUTED_APPS + 25)]}
        )
        self.assertEqual(len(block["keep_unmuted_apps"]), schema.MAX_KEEP_UNMUTED_APPS)

    def test_keep_unmuted_app_names_are_length_capped(self):
        block = schema.sanitize_voice_privacy({"keep_unmuted_apps": ["x" * 5000]})
        self.assertEqual(len(block["keep_unmuted_apps"][0]), schema.MAX_APP_NAME_CHARS)

    def test_non_list_app_allowlist_collapses_to_empty(self):
        self.assertEqual(schema.sanitize_voice_privacy({"keep_unmuted_apps": "Discord"})["keep_unmuted_apps"], [])

    def test_defaults_are_not_shared_between_calls(self):
        a = schema.sanitize_voice_privacy({})
        a["keep_unmuted_apps"].append("leak")
        self.assertEqual(schema.sanitize_voice_privacy({})["keep_unmuted_apps"], [])
        self.assertEqual(schema.VOICE_PRIVACY_DEFAULTS["keep_unmuted_apps"], [])


class LegacyProfileMigrationTests(unittest.TestCase):
    """The exact one-shot rule from the release plan."""

    def test_ducking_on_with_binding_becomes_ducking_plus_push_to_mute(self):
        cfg = schema.migrate_audio_settings({"audio_ducking": True, "voice_mute_key": "f10"})
        self.assertTrue(cfg["output_ducking"]["enabled"])
        self.assertEqual(cfg["voice_privacy"]["mode"], "push_to_mute")
        self.assertEqual(cfg["voice_privacy"]["mute_binding"], "f10")

    def test_ducking_on_without_binding_leaves_privacy_off(self):
        cfg = schema.migrate_audio_settings({"audio_ducking": True, "voice_mute_key": ""})
        self.assertTrue(cfg["output_ducking"]["enabled"])
        self.assertEqual(cfg["voice_privacy"]["mode"], "off")

    def test_ducking_off_with_binding_stays_off_but_preserves_the_key(self):
        # injector.hold_mute_key() has always returned early when ducking was
        # off, so the old behavior was "no mute hold" — carry that forward
        # exactly, without throwing away the user's configured key.
        cfg = schema.migrate_audio_settings({"audio_ducking": False, "voice_mute_key": "f11"})
        self.assertFalse(cfg["output_ducking"]["enabled"])
        self.assertEqual(cfg["voice_privacy"]["mode"], "off")
        self.assertEqual(cfg["voice_privacy"]["mute_binding"], "f11")

    def test_legacy_levels_carry_into_the_new_block(self):
        cfg = schema.migrate_audio_settings({
            "audio_ducking": True,
            "audio_ducking_level_percent": 30.0,
            "audio_ducking_fallback_return_percent": 85.0,
        })
        self.assertEqual(cfg["output_ducking"]["target_percent"], 30.0)
        self.assertEqual(cfg["output_ducking"]["restore_fallback_percent"], 85.0)

    def test_profile_with_no_audio_keys_at_all_gets_safe_defaults(self):
        cfg = schema.migrate_audio_settings({})
        self.assertEqual(cfg["output_ducking"], schema.output_ducking_defaults())
        self.assertEqual(cfg["voice_privacy"], schema.voice_privacy_defaults())

    def test_migration_is_idempotent(self):
        first = schema.migrate_audio_settings({"audio_ducking": True, "voice_mute_key": "f10"})
        snapshot = {"output_ducking": dict(first["output_ducking"]), "voice_privacy": dict(first["voice_privacy"])}
        second = schema.migrate_audio_settings(first)
        self.assertEqual(second["output_ducking"], snapshot["output_ducking"])
        self.assertEqual(second["voice_privacy"], snapshot["voice_privacy"])

    def test_existing_blocks_win_over_stale_legacy_keys(self):
        # Once migrated, the blocks are authoritative: a stale legacy flag left
        # behind by an older build must not flip a user's setting back.
        cfg = schema.migrate_audio_settings({
            "audio_ducking": False,
            "voice_mute_key": "",
            "output_ducking": {"enabled": True, "target_percent": 25.0},
            "voice_privacy": {"mode": "push_to_mute", "mute_binding": "f9"},
        })
        self.assertTrue(cfg["output_ducking"]["enabled"])
        self.assertEqual(cfg["voice_privacy"]["mute_binding"], "f9")

    def test_corrupt_blocks_are_sanitized_not_trusted(self):
        cfg = schema.migrate_audio_settings({
            "output_ducking": {"enabled": "yes", "target_percent": "nope"},
            "voice_privacy": {"mode": "hack", "keep_unmuted_apps": {"a": 1}},
        })
        self.assertTrue(cfg["output_ducking"]["enabled"])
        self.assertEqual(cfg["output_ducking"]["target_percent"], 18.0)
        self.assertEqual(cfg["voice_privacy"]["mode"], "off")
        self.assertEqual(cfg["voice_privacy"]["keep_unmuted_apps"], [])

    def test_non_dict_config_is_returned_untouched(self):
        self.assertIsNone(schema.migrate_audio_settings(None))
        self.assertEqual(schema.migrate_audio_settings("cfg"), "cfg")


class LegacyProjectionTests(unittest.TestCase):
    """Consumers not yet ported keep seeing the keys they always read."""

    def test_round_trip_preserves_legacy_semantics(self):
        original = {
            "audio_ducking": True,
            "voice_mute_key": "f10",
            "audio_ducking_level_percent": 22.0,
            "audio_ducking_fallback_return_percent": 90.0,
        }
        cfg = schema.project_legacy_audio_keys(schema.migrate_audio_settings(dict(original)))
        for key, value in original.items():
            self.assertEqual(cfg[key], value, key)

    def test_ducking_off_round_trips_as_off(self):
        original = {"audio_ducking": False, "voice_mute_key": "f11"}
        cfg = schema.project_legacy_audio_keys(schema.migrate_audio_settings(dict(original)))
        self.assertFalse(cfg["audio_ducking"])
        self.assertEqual(cfg["voice_mute_key"], "f11")

    def test_privacy_only_still_sets_the_legacy_flag(self):
        # The legacy flag gated BOTH behaviors, so a user who wants only
        # push-to-mute must still get the mute key held by unported injector.py.
        cfg = schema.project_legacy_audio_keys({
            "output_ducking": {"enabled": False},
            "voice_privacy": {"mode": "push_to_mute", "mute_binding": "f10"},
        })
        self.assertTrue(cfg["audio_ducking"])
        self.assertEqual(cfg["voice_mute_key"], "f10")

    def test_ducking_only_sets_the_flag_with_no_binding(self):
        cfg = schema.project_legacy_audio_keys({
            "output_ducking": {"enabled": True},
            "voice_privacy": {"mode": "off", "mute_binding": ""},
        })
        self.assertTrue(cfg["audio_ducking"])
        self.assertEqual(cfg["voice_mute_key"], "")

    def test_both_off_clears_the_flag(self):
        cfg = schema.project_legacy_audio_keys({
            "output_ducking": {"enabled": False},
            "voice_privacy": {"mode": "off"},
        })
        self.assertFalse(cfg["audio_ducking"])

    def test_projection_is_idempotent(self):
        cfg = schema.migrate_audio_settings({"audio_ducking": True, "voice_mute_key": "f10"})
        once = dict(schema.project_legacy_audio_keys(dict(cfg)))
        twice = dict(schema.project_legacy_audio_keys(once))
        self.assertEqual(once, twice)


class ReadHelperTests(unittest.TestCase):
    def test_helpers_read_an_unmigrated_dict(self):
        cfg = {"audio_ducking": True, "voice_mute_key": "f10", "audio_ducking_level_percent": 12.0}
        self.assertTrue(schema.output_ducking_of(cfg)["enabled"])
        self.assertEqual(schema.output_ducking_of(cfg)["target_percent"], 12.0)
        self.assertEqual(schema.voice_privacy_of(cfg)["mode"], "push_to_mute")

    def test_helpers_prefer_the_new_blocks(self):
        cfg = {"audio_ducking": False, "output_ducking": {"enabled": True}}
        self.assertTrue(schema.output_ducking_of(cfg)["enabled"])

    def test_helpers_tolerate_non_dicts(self):
        self.assertEqual(schema.output_ducking_of(None), schema.output_ducking_defaults())
        self.assertEqual(schema.voice_privacy_of("nope"), schema.voice_privacy_defaults())


class EffectivePrivacyModeTests(unittest.TestCase):
    def test_push_to_mute_with_a_binding_is_active(self):
        cfg = {"voice_privacy": {"mode": "push_to_mute", "mute_binding": "f10"}}
        self.assertEqual(schema.effective_privacy_mode(cfg), "push_to_mute")

    def test_push_to_mute_without_a_binding_is_honestly_off(self):
        cfg = {"voice_privacy": {"mode": "push_to_mute", "mute_binding": ""}}
        self.assertEqual(schema.effective_privacy_mode(cfg), "off")

    def test_reserved_isolation_degrades_to_push_to_mute_while_unavailable(self):
        cfg = {"voice_privacy": {"mode": "isolate_capture_streams", "mute_binding": "f10"}}
        self.assertEqual(schema.effective_privacy_mode(cfg, isolation_available=False), "push_to_mute")

    def test_reserved_isolation_without_a_binding_degrades_to_off(self):
        cfg = {"voice_privacy": {"mode": "isolate_capture_streams", "mute_binding": ""}}
        self.assertEqual(schema.effective_privacy_mode(cfg, isolation_available=False), "off")

    def test_isolation_runs_when_an_adapter_exists(self):
        cfg = {"voice_privacy": {"mode": "isolate_capture_streams", "mute_binding": ""}}
        self.assertEqual(
            schema.effective_privacy_mode(cfg, isolation_available=True), "isolate_capture_streams"
        )

    def test_off_stays_off(self):
        cfg = {"voice_privacy": {"mode": "off", "mute_binding": "f10"}}
        self.assertEqual(schema.effective_privacy_mode(cfg), "off")


if __name__ == "__main__":
    unittest.main()
