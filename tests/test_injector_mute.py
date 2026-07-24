import unittest
from unittest.mock import patch

import injector as injector_mod
from injector import InputInjector


class InjectorMuteKeyTests(unittest.TestCase):
    """Windows path: `keyboard.press`/`keyboard.release` remain unchanged."""

    def setUp(self):
        p = patch.object(injector_mod, "IS_WINDOWS", True)
        p.start()
        self.addCleanup(p.stop)

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


class InjectorMuteKeyLinuxTests(unittest.TestCase):
    """Non-Windows: `keyboard` requires root, so hold/release must route
    through the detected external tool (xdotool/wtype/ydotool) instead of
    `keyboard.press`/`keyboard.release`, and degrade honestly with no tool."""

    def setUp(self):
        p = patch.object(injector_mod, "IS_WINDOWS", False)
        p.start()
        self.addCleanup(p.stop)

    @staticmethod
    def _make_injector(method, config=None):
        config = config if config is not None else {
            "audio_ducking": True,
            "voice_mute_key": "f10",
        }
        with patch("injector.load_profile", return_value=config):
            inj = InputInjector(profile_name="Default")
        inj.injection_method = method
        return inj

    def test_xdotool_holds_and_releases_via_keydown_keyup(self):
        inj = self._make_injector("xdotool")
        with patch("injector._run_type_tool", return_value=True) as run_tool, patch.object(
            injector_mod, "keyboard"
        ) as keyboard_mock:
            inj.hold_mute_key()
            inj.release_mute_key()
        self.assertEqual(
            [c.args[0] for c in run_tool.call_args_list],
            [
                ["xdotool", "keydown", "F10"],
                ["xdotool", "keyup", "F10"],
            ],
        )
        keyboard_mock.press.assert_not_called()
        keyboard_mock.release.assert_not_called()

    def test_wtype_holds_and_releases_via_dash_p(self):
        inj = self._make_injector("wtype")
        with patch("injector._run_type_tool", return_value=True) as run_tool, patch.object(
            injector_mod, "keyboard"
        ) as keyboard_mock:
            inj.hold_mute_key()
            inj.release_mute_key()
        self.assertEqual(
            [c.args[0] for c in run_tool.call_args_list],
            [
                ["wtype", "-P", "F10"],
                ["wtype", "-p", "F10"],
            ],
        )
        keyboard_mock.press.assert_not_called()
        keyboard_mock.release.assert_not_called()

    def test_ydotool_holds_and_releases_via_keycode(self):
        inj = self._make_injector("ydotool")
        with patch("injector._run_type_tool", return_value=True) as run_tool, patch.object(
            injector_mod, "keyboard"
        ) as keyboard_mock:
            inj.hold_mute_key()
            inj.release_mute_key()
        self.assertEqual(
            [c.args[0] for c in run_tool.call_args_list],
            [
                ["ydotool", "key", "68:1"],
                ["ydotool", "key", "68:0"],
            ],
        )
        keyboard_mock.press.assert_not_called()
        keyboard_mock.release.assert_not_called()

    def test_no_tool_available_degrades_without_keyboard(self):
        inj = self._make_injector("paste")
        with patch.object(injector_mod, "keyboard") as keyboard_mock, self.assertLogs(
            level="WARNING"
        ) as logs:
            inj.hold_mute_key()  # must not raise
            inj.release_mute_key()  # nothing was ever held, so this no-ops
        keyboard_mock.press.assert_not_called()
        keyboard_mock.release.assert_not_called()
        self.assertTrue(any("input-injection tool" in m.lower() for m in logs.output))

    def test_hold_is_idempotent_while_key_is_held(self):
        inj = self._make_injector("xdotool")
        with patch("injector._run_type_tool", return_value=True) as run_tool, patch.object(
            injector_mod, "keyboard"
        ):
            inj.hold_mute_key()
            inj.hold_mute_key()
        run_tool.assert_called_once()


if __name__ == "__main__":
    unittest.main()
