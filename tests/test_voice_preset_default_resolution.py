"""Layer-precedence tests for server._resolve_voice_and_modulation's new
DEFAULT PRESET layer.

Before this, a saved voice preset only ever applied to a TTS request that
explicitly passed preset_name -- which neither /tts/speak nor
/drafts/{id}/tts do for ordinary read-aloud, so a user's Voice Studio
choice was silently never used. The default preset (voice_presets.
get_default_preset(), settable via POST /voice-presets/{name}/make-default)
closes that gap as the lowest-priority PRESET layer: explicit request
fields > requested preset (preset_name) > persona voice > default preset >
profile config > hardcoded fallback.

voice_presets.get_presets()/get_default_preset() and llm_engine.get_persona
are mocked throughout -- no real store I/O, matching
tests/test_dictation_preset_resolution.py's patching style for the
neighboring (LLM persona) preset-resolution concern.
"""
import unittest
from unittest.mock import patch

import server


def _preset(name, **overrides):
    """A fully-shaped preset dict, as voice_presets.get_presets() would
    return it (see voice_presets._DEFAULTS) -- only the fields relevant to
    a given test need overriding."""
    base = {
        "name": name,
        "base": "",
        "blend": {},
        "speed": 1.0,
        "pitch": 0.0,
        "energy": 0.5,
        "warmth": 0.0,
        "brightness": 0.0,
        "pause_style": "natural",
        "stability": 0.5,
        "source": "manual",
        "created_at": 0.0,
        "updated_at": 0.0,
    }
    base.update(overrides)
    return base


class ResolveVoiceDefaultPresetLayerTests(unittest.TestCase):
    def _req(self, **kwargs):
        # TTSRequest/DraftTtsRequest are both pydantic models with the same
        # optional voice fields (voice_id/speed/pitch/blend/energy/warmth/
        # brightness/pause_style/preset_name/persona), all defaulting to
        # None -- using the real request model instead of a hand-rolled
        # double keeps this honest against either call site.
        return server.TTSRequest(text="hello", **kwargs)

    def test_no_default_falls_through_to_profile_config(self):
        with patch("voice_presets.get_presets", return_value=[]), patch(
            "voice_presets.get_default_preset", return_value=None
        ):
            voice_id, speed, blend, modulation = server._resolve_voice_and_modulation(
                self._req(), {"review_tts_voice_hint": "am_puck", "review_tts_speed": 1.3}
            )
        self.assertEqual(voice_id, server.normalize_tts_voice_id("am_puck"))
        self.assertEqual(speed, 1.3)

    def test_default_preset_beats_profile_config(self):
        default_preset = _preset("Warm Assistant", base="af_bella", speed=1.1, pitch=2.0)
        with patch("voice_presets.get_presets", return_value=[default_preset]), patch(
            "voice_presets.get_default_preset", return_value="Warm Assistant"
        ):
            voice_id, speed, blend, modulation = server._resolve_voice_and_modulation(
                self._req(), {"review_tts_voice_hint": "am_puck", "review_tts_speed": 1.3}
            )
        # The default preset's values win over profile config, not the
        # config's own review_tts_voice_hint/review_tts_speed.
        self.assertEqual(voice_id, server.normalize_tts_voice_id("af_bella"))
        self.assertEqual(speed, 1.1)
        self.assertEqual(modulation["pitch"], 2.0)

    def test_explicit_request_field_beats_default_preset(self):
        default_preset = _preset("Warm Assistant", base="af_bella", speed=1.1)
        with patch("voice_presets.get_presets", return_value=[default_preset]), patch(
            "voice_presets.get_default_preset", return_value="Warm Assistant"
        ):
            voice_id, speed, blend, modulation = server._resolve_voice_and_modulation(
                self._req(voice_id="am_michael", speed=0.8), {}
            )
        self.assertEqual(voice_id, server.normalize_tts_voice_id("am_michael"))
        self.assertEqual(speed, 0.8)

    def test_requested_preset_beats_default_preset(self):
        default_preset = _preset("Warm Assistant", base="af_bella")
        requested_preset = _preset("Crisp Editor", base="am_puck")
        with patch(
            "voice_presets.get_presets", return_value=[default_preset, requested_preset]
        ), patch("voice_presets.get_default_preset", return_value="Warm Assistant"):
            voice_id, speed, blend, modulation = server._resolve_voice_and_modulation(
                self._req(preset_name="Crisp Editor"), {}
            )
        self.assertEqual(voice_id, server.normalize_tts_voice_id("am_puck"))

    @patch("llm_engine.get_persona")
    def test_persona_with_voice_identity_beats_default_preset(self, mock_get_persona):
        mock_get_persona.return_value = {
            "voice": {"base": "bf_emma", "preset": "", "speed": 1.0, "pitch": 0.0,
                      "energy": 0.5, "warmth": 0.0, "brightness": 0.0,
                      "pause_style": "natural", "stability": 0.5, "blend": {}},
        }
        default_preset = _preset("Warm Assistant", base="af_bella")
        with patch("voice_presets.get_presets", return_value=[default_preset]), patch(
            "voice_presets.get_default_preset", return_value="Warm Assistant"
        ):
            voice_id, speed, blend, modulation = server._resolve_voice_and_modulation(
                self._req(persona="Court Reporter"), {}
            )
        self.assertEqual(voice_id, server.normalize_tts_voice_id("bf_emma"))

    def test_default_preset_blend_is_applied(self):
        # The default layer carries blend/modulation too, not just base
        # voice -- this is the whole point (a saved preset's full recipe
        # now actually reaches ordinary read-aloud).
        default_preset = _preset(
            "Warm Assistant", base="af_bella", blend={"am_adam": 0.3},
            warmth=0.4, brightness=0.2, pause_style="relaxed",
        )
        with patch("voice_presets.get_presets", return_value=[default_preset]), patch(
            "voice_presets.get_default_preset", return_value="Warm Assistant"
        ):
            voice_id, speed, blend, modulation = server._resolve_voice_and_modulation(
                self._req(), {}
            )
        self.assertEqual(blend, {"am_adam": 0.3})
        self.assertEqual(modulation["warmth"], 0.4)
        self.assertEqual(modulation["brightness"], 0.2)
        self.assertEqual(modulation["pause_style"], "relaxed")

    def test_dangling_default_name_is_skipped_safely(self):
        # get_default_preset() itself already guards against a dangling
        # name (see tests/test_voice_presets.py), but _resolve_voice_and_
        # modulation re-looks the name up against its own cached
        # get_presets() read -- if that lookup ever comes back empty
        # (e.g. a race with a delete), it must fall through cleanly rather
        # than raising or crashing on a None preset.
        with patch("voice_presets.get_presets", return_value=[]), patch(
            "voice_presets.get_default_preset", return_value="Ghost Preset"
        ):
            voice_id, speed, blend, modulation = server._resolve_voice_and_modulation(
                self._req(), {"review_tts_voice_hint": "am_puck"}
            )
        self.assertEqual(voice_id, server.normalize_tts_voice_id("am_puck"))


if __name__ == "__main__":
    unittest.main()
