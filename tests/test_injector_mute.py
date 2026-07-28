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


class InjectorVoicePrivacyModeTests(unittest.TestCase):
    """Wave 8A / D-0010: the hold is driven by voice_privacy.mode, and every
    legacy profile still behaves exactly as it did before the split."""

    def setUp(self):
        p = patch.object(injector_mod, "IS_WINDOWS", True)
        p.start()
        self.addCleanup(p.stop)

    def _injector(self, config):
        with patch("injector.load_profile", return_value=config):
            return InputInjector(profile_name="Default")

    def _binding_for(self, config):
        return self._injector(config)._push_to_mute_binding()

    # -- new schema --------------------------------------------------

    def test_push_to_mute_mode_holds_the_configured_binding(self):
        self.assertEqual(
            self._binding_for({"voice_privacy": {"mode": "push_to_mute", "mute_binding": "f10"}}),
            "f10",
        )

    def test_mode_off_holds_nothing_even_with_a_binding_saved(self):
        self.assertEqual(
            self._binding_for({"voice_privacy": {"mode": "off", "mute_binding": "f10"}}),
            "",
        )

    def test_push_to_mute_without_a_binding_holds_nothing(self):
        self.assertEqual(
            self._binding_for({"voice_privacy": {"mode": "push_to_mute", "mute_binding": ""}}),
            "",
        )

    def test_reserved_isolation_mode_falls_back_to_the_mute_key(self):
        # No capture-isolation adapter exists yet (Wave 8B), so a profile that
        # selected it must still get push-to-mute rather than silently nothing.
        self.assertEqual(
            self._binding_for(
                {"voice_privacy": {"mode": "isolate_capture_streams", "mute_binding": "f9"}}
            ),
            "f9",
        )

    def test_output_ducking_alone_never_holds_a_key(self):
        # The split's whole point: ducking the speakers is not a privacy action.
        self.assertEqual(
            self._binding_for({
                "output_ducking": {"enabled": True},
                "voice_privacy": {"mode": "off", "mute_binding": "f10"},
            }),
            "",
        )

    # -- unmigrated legacy profiles ----------------------------------

    def test_legacy_ducking_on_with_a_key_still_holds_it(self):
        self.assertEqual(self._binding_for({"audio_ducking": True, "voice_mute_key": "f10"}), "f10")

    def test_legacy_ducking_off_still_holds_nothing(self):
        self.assertEqual(self._binding_for({"audio_ducking": False, "voice_mute_key": "f10"}), "")

    def test_legacy_ducking_on_without_a_key_still_holds_nothing(self):
        self.assertEqual(self._binding_for({"audio_ducking": True, "voice_mute_key": ""}), "")

    def test_an_empty_profile_holds_nothing(self):
        self.assertEqual(self._binding_for({}), "")

    # -- end to end --------------------------------------------------

    @patch("injector.keyboard.release")
    @patch("injector.keyboard.press")
    def test_switching_privacy_off_releases_a_held_key_on_reload(self, press_key, release_key):
        configs = [
            {"voice_privacy": {"mode": "push_to_mute", "mute_binding": "f10"}},
            {"voice_privacy": {"mode": "off", "mute_binding": "f10"}},
        ]
        with patch("injector.load_profile", side_effect=configs):
            injector = InputInjector(profile_name="Default")
            injector.hold_mute_key()
            injector.reload_config(profile_name="Default")
        press_key.assert_called_once_with("f10")
        release_key.assert_called_once_with("f10")


if __name__ == "__main__":
    unittest.main()
