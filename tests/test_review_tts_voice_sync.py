# Voice Studio blend/modulation sync (side-track: voice blending UI redesign
# + canonical TTS voice sync).
#
# Bug this closes: blend/modulation configured in Voice Studio were never
# part of the profile schema, so the canonical/automatic playback path
# (server.speak_text_aloud, behind the Review TTS hotkey and voice-command
# read-back) always called engine.speak() with only voice_id/speed, silently
# dropping blend and modulation even though engine.speak() already accepts
# them and the two manual preview paths (/tts/speak, /drafts/{id}/tts)
# already forwarded them correctly.
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import server
import utils


class ProfileDefaultsIncludeVoiceStudioFieldsTests(unittest.TestCase):
    def test_defaults_present_with_expected_values(self):
        defaults = utils._profile_defaults()
        self.assertEqual(defaults["review_tts_blend"], {})
        self.assertEqual(defaults["review_tts_pitch"], 0.0)
        self.assertEqual(defaults["review_tts_energy"], 0.5)
        self.assertEqual(defaults["review_tts_warmth"], 0.0)
        self.assertEqual(defaults["review_tts_brightness"], 0.0)
        self.assertEqual(defaults["review_tts_pause_style"], "natural")


class ProfilePersistenceRoundTripTests(unittest.TestCase):
    """A profile saved with Voice Studio fields survives a save -> load
    round trip (the "restore correctly on reload" requirement) and malformed
    input is coerced rather than corrupting the profile."""

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

    def test_round_trip_preserves_blend_and_modulation(self):
        payload = utils._profile_defaults()
        payload.update(
            {
                "review_tts_voice_hint": "af_heart",
                "review_tts_blend": {"af_nicole": 0.3, "bf_emma": 0.2},
                "review_tts_pitch": 2.5,
                "review_tts_energy": 0.7,
                "review_tts_warmth": 0.4,
                "review_tts_brightness": 0.1,
                "review_tts_pause_style": "dramatic",
            }
        )
        utils.save_profile("VoiceSyncTest", payload)
        loaded = utils.load_profile("VoiceSyncTest")

        self.assertEqual(loaded["review_tts_voice_hint"], "af_heart")
        self.assertEqual(loaded["review_tts_blend"], {"af_nicole": 0.3, "bf_emma": 0.2})
        self.assertEqual(loaded["review_tts_pitch"], 2.5)
        self.assertEqual(loaded["review_tts_energy"], 0.7)
        self.assertEqual(loaded["review_tts_warmth"], 0.4)
        self.assertEqual(loaded["review_tts_brightness"], 0.1)
        self.assertEqual(loaded["review_tts_pause_style"], "dramatic")

    def test_old_profile_missing_the_new_keys_gets_safe_defaults(self):
        # Simulates a profile saved before this feature existed.
        legacy = utils._profile_defaults()
        for key in (
            "review_tts_blend", "review_tts_pitch", "review_tts_energy",
            "review_tts_warmth", "review_tts_brightness", "review_tts_pause_style",
        ):
            legacy.pop(key, None)
        utils.save_profile("LegacyVoice", legacy)
        loaded = utils.load_profile("LegacyVoice")

        self.assertEqual(loaded["review_tts_blend"], {})
        self.assertEqual(loaded["review_tts_pitch"], 0.0)
        self.assertEqual(loaded["review_tts_pause_style"], "natural")

    def test_out_of_range_and_malformed_values_are_clamped_or_defaulted(self):
        payload = utils._profile_defaults()
        payload.update(
            {
                "review_tts_blend": "not-a-dict",
                "review_tts_pitch": 999,
                "review_tts_energy": -5,
                "review_tts_warmth": "nope",
                "review_tts_brightness": 5.0,
                "review_tts_pause_style": "shouting",
            }
        )
        utils.save_profile("MalformedVoice", payload)
        loaded = utils.load_profile("MalformedVoice")

        self.assertEqual(loaded["review_tts_blend"], {})
        self.assertEqual(loaded["review_tts_pitch"], 12.0)
        self.assertEqual(loaded["review_tts_energy"], 0.0)
        self.assertEqual(loaded["review_tts_warmth"], 0.0)  # non-numeric -> default
        self.assertEqual(loaded["review_tts_brightness"], 1.0)
        self.assertEqual(loaded["review_tts_pause_style"], "natural")


class _FakeTTSEngine:
    def __init__(self):
        self.speak = MagicMock(return_value={"ok": True, "queued": True})

    def set_keep_loaded(self, value):
        pass


class SpeakTextAloudForwardsBlendAndModulationTests(unittest.TestCase):
    """The canonical automatic playback path must use the same voice the
    user configured in Voice Studio, not just the base voice_hint."""

    def test_forwards_blend_and_modulation_from_profile(self):
        fake = _FakeTTSEngine()
        config = {
            "review_tts_enabled": True,
            "review_tts_voice_hint": "af_heart",
            "review_tts_speed": 1.2,
            "review_tts_blend": {"af_nicole": 0.3},
            "review_tts_pitch": 2.0,
            "review_tts_energy": 0.7,
            "review_tts_warmth": 0.4,
            "review_tts_brightness": 0.1,
            "review_tts_pause_style": "dramatic",
        }
        with patch.object(server, "ensure_tts_initialized", return_value=fake), \
             patch.object(server, "load_profile", return_value=config):
            server.speak_text_aloud("hello there")

        fake.speak.assert_called_once()
        _, kwargs = fake.speak.call_args
        self.assertEqual(kwargs["voice_hint"], "af_heart")
        self.assertAlmostEqual(kwargs["speed"], 1.2)
        self.assertEqual(kwargs["blend"], {"af_nicole": 0.3})
        self.assertEqual(
            kwargs["modulation"],
            {"pitch": 2.0, "energy": 0.7, "warmth": 0.4, "brightness": 0.1, "pause_style": "dramatic"},
        )

    def test_missing_voice_studio_keys_default_safely(self):
        # Old/legacy profile shape (matches the existing
        # test_speak_text_aloud_holds_tts_read_lease fixture in
        # test_privacy_wipe.py) — must not raise.
        fake = _FakeTTSEngine()
        with patch.object(server, "ensure_tts_initialized", return_value=fake), \
             patch.object(server, "load_profile", return_value={"review_tts_enabled": True}):
            server.speak_text_aloud("hello")

        fake.speak.assert_called_once()
        _, kwargs = fake.speak.call_args
        self.assertIsNone(kwargs["blend"])
        self.assertEqual(kwargs["modulation"]["pause_style"], "natural")

    def test_malformed_blend_weights_in_profile_are_dropped_not_sent_raw(self):
        fake = _FakeTTSEngine()
        config = {
            "review_tts_enabled": True,
            "review_tts_blend": {"af_nicole": "not-a-number", "bf_emma": -1, "am_michael": 0.4},
        }
        with patch.object(server, "ensure_tts_initialized", return_value=fake), \
             patch.object(server, "load_profile", return_value=config):
            server.speak_text_aloud("hello")

        _, kwargs = fake.speak.call_args
        self.assertEqual(kwargs["blend"], {"am_michael": 0.4})


if __name__ == "__main__":
    unittest.main()
