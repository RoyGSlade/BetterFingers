import unittest
from unittest.mock import patch

from injector import InputInjector


class InjectorMuteKeyTests(unittest.TestCase):
    @patch("injector.keyboard.release")
    @patch("injector.keyboard.press")
    @patch(
        "injector.load_profile",
        side_effect=[
            {"audio_ducking": True, "voice_mute_key": "f10"},
            {"audio_ducking": False, "voice_mute_key": "f10"},
        ],
    )
    def test_reload_config_releases_held_key_when_ducking_disabled(
        self,
        _load_profile,
        press_key,
        release_key,
    ):
        injector = InputInjector(profile_name="Default")
        injector.hold_mute_key()
        injector.reload_config(profile_name="Default")

        press_key.assert_called_once_with("f10")
        release_key.assert_called_once_with("f10")

    @patch("injector.keyboard.release")
    @patch("injector.keyboard.press")
    @patch(
        "injector.load_profile",
        return_value={"audio_ducking": True, "voice_mute_key": "f11"},
    )
    def test_release_uses_held_state_not_current_config(
        self,
        _load_profile,
        press_key,
        release_key,
    ):
        injector = InputInjector(profile_name="Default")
        injector.hold_mute_key()
        injector.config = {"audio_ducking": False, "voice_mute_key": "unused"}
        injector.release_mute_key()

        press_key.assert_called_once_with("f11")
        release_key.assert_called_once_with("f11")

    @patch("injector.keyboard.press")
    @patch(
        "injector.load_profile",
        return_value={"audio_ducking": True, "voice_mute_key": "f12"},
    )
    def test_hold_is_idempotent_while_key_is_held(self, _load_profile, press_key):
        injector = InputInjector(profile_name="Default")
        injector.hold_mute_key()
        injector.hold_mute_key()

        press_key.assert_called_once_with("f12")


if __name__ == "__main__":
    unittest.main()
