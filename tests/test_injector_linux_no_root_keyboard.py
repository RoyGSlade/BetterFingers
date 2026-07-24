"""On Linux/macOS the `keyboard` library requires root ("You must be root to
use this library on linux") and must never be invoked. This covers the two
paths that used to call into it on non-Windows: the Ctrl+V paste hotkey
(_send_paste_hotkey, reached via the paste fallback _paste_raw) and streaming
delta typing (type_live_delta) -- plus _paste_raw's own except-block fallback,
which used to be the exact source of the observed
"Fallback typing failed: You must be root to use this library on linux." log
line right after "Paste injection failed (...); falling back to instant type."

Windows keeps using `keyboard`/`pydirectinput` unchanged; only the non-Windows
branches are asserted here to route through the detected external tool
(xdotool/wtype/ydotool) or degrade honestly (clipboard-paste hint / debug log)
without ever touching `keyboard`.
"""

import unittest
from unittest.mock import MagicMock, patch

import injector as injector_mod
from injector import InputInjector


def _make_injector(method):
    with patch("injector.load_profile", return_value={}):
        inj = InputInjector(profile_name="Default")
    inj.injection_method = method
    return inj


class SendPasteHotkeyLinuxTests(unittest.TestCase):
    """_send_paste_hotkey on non-Windows must route through the external tool,
    never `keyboard.press_and_release`."""

    def setUp(self):
        p = patch.object(injector_mod, "IS_WINDOWS", False)
        p.start()
        self.addCleanup(p.stop)

    def test_xdotool_sends_ctrl_v_via_tool(self):
        inj = _make_injector("xdotool")
        with patch("injector._run_type_tool", return_value=True) as run_tool, patch.object(
            injector_mod, "keyboard"
        ) as keyboard_mock:
            inj._send_paste_hotkey()
        run_tool.assert_called_once()
        (argv,) = run_tool.call_args.args
        self.assertEqual(argv, ["xdotool", "key", "--clearmodifiers", "ctrl+v"])
        keyboard_mock.press_and_release.assert_not_called()
        keyboard_mock.write.assert_not_called()

    def test_wtype_sends_ctrl_v_via_modifiers(self):
        inj = _make_injector("wtype")
        with patch("injector._run_type_tool", return_value=True) as run_tool, patch.object(
            injector_mod, "keyboard"
        ) as keyboard_mock:
            inj._send_paste_hotkey()
        (argv,) = run_tool.call_args.args
        self.assertEqual(argv, ["wtype", "-M", "ctrl", "v", "-m", "ctrl"])
        keyboard_mock.press_and_release.assert_not_called()

    def test_ydotool_sends_ctrl_v_via_keycodes(self):
        inj = _make_injector("ydotool")
        with patch("injector._run_type_tool", return_value=True) as run_tool, patch.object(
            injector_mod, "keyboard"
        ) as keyboard_mock:
            inj._send_paste_hotkey()
        (argv,) = run_tool.call_args.args
        self.assertEqual(argv, ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"])
        keyboard_mock.press_and_release.assert_not_called()

    def test_no_tool_available_degrades_honestly_without_keyboard(self):
        # injection_method "paste"/"none": no external tool to dispatch to.
        inj = _make_injector("paste")
        with patch.object(injector_mod, "keyboard") as keyboard_mock, self.assertLogs(
            level="WARNING"
        ) as logs:
            inj._send_paste_hotkey()  # must not raise
        keyboard_mock.press_and_release.assert_not_called()
        keyboard_mock.write.assert_not_called()
        self.assertTrue(any("clipboard" in m.lower() for m in logs.output))

    def test_tool_failure_degrades_honestly_without_keyboard(self):
        inj = _make_injector("xdotool")
        with patch("injector._run_type_tool", return_value=False), patch.object(
            injector_mod, "keyboard"
        ) as keyboard_mock, self.assertLogs(level="WARNING") as logs:
            inj._send_paste_hotkey()  # must not raise
        keyboard_mock.press_and_release.assert_not_called()
        self.assertTrue(any("clipboard" in m.lower() for m in logs.output))


class TypeLiveDeltaTests(unittest.TestCase):
    def test_linux_routes_through_external_tool(self):
        with patch.object(injector_mod, "IS_WINDOWS", False):
            inj = _make_injector("xdotool")
            with patch.object(inj, "_type_via_external_tool", return_value=True) as typed, patch.object(
                injector_mod, "keyboard"
            ) as keyboard_mock:
                inj.type_live_delta("hello")
            typed.assert_called_once_with("hello")
            keyboard_mock.write.assert_not_called()

    def test_linux_no_tool_noops_without_keyboard(self):
        with patch.object(injector_mod, "IS_WINDOWS", False):
            inj = _make_injector("none")
            with patch.object(injector_mod, "keyboard") as keyboard_mock:
                inj.type_live_delta("hello")  # must not raise
            keyboard_mock.write.assert_not_called()

    def test_windows_still_uses_keyboard_write(self):
        # Windows behavior is unchanged: keyboard.write remains the mechanism.
        with patch.object(injector_mod, "IS_WINDOWS", True):
            inj = _make_injector("pydirectinput")
            with patch.object(injector_mod, "keyboard") as keyboard_mock:
                inj.type_live_delta("hello")
            keyboard_mock.write.assert_called_once_with("hello", delay=0)


class PasteRawFallbackTests(unittest.TestCase):
    """_paste_raw's except-block fallback (when pyperclip.copy or the paste
    hotkey itself raises) must not call `keyboard` on non-Windows -- this is
    the exact code path that used to log
    'Fallback typing failed: You must be root to use this library on linux.'
    """

    def test_linux_fallback_uses_external_tool_not_keyboard(self):
        with patch.object(injector_mod, "IS_WINDOWS", False):
            inj = _make_injector("xdotool")
            with patch.object(injector_mod.pyperclip, "copy", side_effect=RuntimeError("no clipboard")), \
                 patch.object(inj, "_type_via_external_tool", return_value=True) as typed, \
                 patch.object(injector_mod, "keyboard") as keyboard_mock:
                inj._paste_raw("hello world")  # must not raise
            typed.assert_called_once_with("hello world")
            keyboard_mock.write.assert_not_called()

    def test_linux_fallback_no_tool_degrades_honestly(self):
        with patch.object(injector_mod, "IS_WINDOWS", False):
            inj = _make_injector("none")
            with patch.object(injector_mod.pyperclip, "copy", side_effect=RuntimeError("no clipboard")), \
                 patch.object(injector_mod, "keyboard") as keyboard_mock, \
                 self.assertLogs(level="WARNING") as logs:
                inj._paste_raw("hello world")  # must not raise
            keyboard_mock.write.assert_not_called()
            self.assertTrue(any("clipboard" in m.lower() for m in logs.output))

    def test_windows_fallback_still_uses_keyboard_write(self):
        with patch.object(injector_mod, "IS_WINDOWS", True):
            inj = _make_injector("pydirectinput")
            with patch.object(injector_mod.pyperclip, "copy", side_effect=RuntimeError("no clipboard")), \
                 patch.object(injector_mod, "keyboard") as keyboard_mock:
                inj._paste_raw("hello world")
            keyboard_mock.write.assert_called_once_with("hello world", delay=0)


if __name__ == "__main__":
    unittest.main()
