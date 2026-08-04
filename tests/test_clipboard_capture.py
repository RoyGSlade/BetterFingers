import os
import subprocess
import unittest
from unittest.mock import patch

import clipboard_capture
import server


class _FixedUUID:
    hex = "fixed"


def _supported_test_backend():
    return {
        "supported": True,
        "tool": "test",
        "clipboard_backend": {"name": "test", "available": True, "required": []},
        "copy_trigger_backend": {"name": "native-keyboard", "available": True, "required": []},
    }


class ClipboardCaptureTests(unittest.TestCase):
    @patch("clipboard_capture._schedule_delayed_clipboard_restore")
    @patch("clipboard_capture._restore_clipboard_snapshot_windows", return_value=False)
    @patch("clipboard_capture._capture_clipboard_snapshot_windows", return_value=None)
    @patch("clipboard_capture.time.sleep", return_value=None)
    @patch("clipboard_capture.keyboard.press_and_release")
    @patch("clipboard_capture._clipboard_set_text", return_value=True)
    @patch("clipboard_capture._clipboard_get_text")
    @patch("clipboard_capture.uuid.uuid4", return_value=_FixedUUID())
    def test_capture_selection_and_restore(
        self,
        _uuid4,
        get_text,
        set_text,
        press_and_release,
        _sleep,
        _capture_snapshot,
        _restore_snapshot,
        _delayed_restore,
    ):
        sentinel = "__betterfingers_clipboard_probe_fixed__"
        get_text.side_effect = ["https://example.com", "Rotate back post and clear."]

        with patch.object(clipboard_capture, "_selection_capture_support", side_effect=_supported_test_backend):
            result = clipboard_capture.capture_selection_text_with_restore(timeout_ms=50, poll_ms=25)

        self.assertTrue(result["ok"])
        self.assertFalse(result["used_fallback"])
        self.assertEqual(result["text"], "Rotate back post and clear.")
        press_and_release.assert_called_once_with("ctrl+c")
        self.assertEqual(set_text.call_args_list[0].args[0], sentinel)
        self.assertEqual(set_text.call_args_list[-1].args[0], "https://example.com")

    @patch("clipboard_capture._schedule_delayed_clipboard_restore")
    @patch("clipboard_capture._restore_clipboard_snapshot_windows", return_value=False)
    @patch("clipboard_capture._capture_clipboard_snapshot_windows", return_value=None)
    @patch("clipboard_capture.time.sleep", return_value=None)
    @patch("clipboard_capture.keyboard.press_and_release")
    @patch("clipboard_capture._clipboard_set_text", return_value=True)
    @patch("clipboard_capture._clipboard_get_text")
    @patch("clipboard_capture.uuid.uuid4", return_value=_FixedUUID())
    def test_successful_trigger_with_unchanged_clipboard_fails_closed(
        self,
        _uuid4,
        get_text,
        _set_text,
        _press_and_release,
        _sleep,
        _capture_snapshot,
        _restore_snapshot,
        _delayed_restore,
    ):
        sentinel = "__betterfingers_clipboard_probe_fixed__"
        original = "This clipboard sentence is readable fallback text."
        get_text.side_effect = [original, sentinel, sentinel]

        with patch.object(clipboard_capture, "_selection_capture_support", side_effect=_supported_test_backend):
            result = clipboard_capture.capture_selection_text_with_restore(timeout_ms=50, poll_ms=25)

        self.assertFalse(result["ok"])
        self.assertFalse(result["used_fallback"])
        self.assertEqual(result["text"], "")
        self.assertEqual(result["capture_status"], "empty")
        self.assertEqual(_set_text.call_args_list[-1].args[0], original)

    @patch("clipboard_capture._schedule_delayed_clipboard_restore")
    @patch("clipboard_capture._restore_clipboard_snapshot_windows", return_value=False)
    @patch("clipboard_capture._capture_clipboard_snapshot_windows", return_value=None)
    @patch("clipboard_capture.time.sleep", return_value=None)
    @patch("clipboard_capture.keyboard.press_and_release")
    @patch("clipboard_capture._clipboard_set_text", return_value=True)
    @patch("clipboard_capture._clipboard_get_text")
    @patch("clipboard_capture.uuid.uuid4", return_value=_FixedUUID())
    def test_url_only_fallback_is_rejected(
        self,
        _uuid4,
        get_text,
        _set_text,
        _press_and_release,
        _sleep,
        _capture_snapshot,
        _restore_snapshot,
        _delayed_restore,
    ):
        sentinel = "__betterfingers_clipboard_probe_fixed__"
        get_text.side_effect = ["https://google.com", sentinel, sentinel]

        with patch.object(clipboard_capture, "_selection_capture_support", side_effect=_supported_test_backend):
            result = clipboard_capture.capture_selection_text_with_restore(timeout_ms=50, poll_ms=25)

        self.assertFalse(result["ok"])
        self.assertEqual(result["text"], "")
        self.assertEqual(result["capture_status"], "empty")

    @patch("clipboard_capture._schedule_delayed_clipboard_restore")
    @patch("clipboard_capture._restore_clipboard_snapshot_windows", return_value=False)
    @patch("clipboard_capture._capture_clipboard_snapshot_windows", return_value=None)
    @patch("clipboard_capture.time.sleep", return_value=None)
    @patch("clipboard_capture.keyboard.press_and_release", side_effect=RuntimeError("copy failed"))
    @patch("clipboard_capture._clipboard_set_text", return_value=True)
    @patch("clipboard_capture._clipboard_get_text")
    @patch("clipboard_capture.uuid.uuid4", return_value=_FixedUUID())
    def test_restore_happens_even_on_copy_error(
        self,
        _uuid4,
        get_text,
        set_text,
        _press_and_release,
        _sleep,
        _capture_snapshot,
        _restore_snapshot,
        _delayed_restore,
    ):
        sentinel = "__betterfingers_clipboard_probe_fixed__"
        original = "Original clipboard text."
        get_text.side_effect = [original, sentinel, sentinel]

        with patch.object(clipboard_capture, "_selection_capture_support", side_effect=_supported_test_backend):
            result = clipboard_capture.capture_selection_text_with_restore(timeout_ms=50, poll_ms=25)

        self.assertFalse(result["ok"])
        self.assertEqual(result["text"], "")
        self.assertFalse(result["used_fallback"])
        self.assertEqual(result["capture_status"], "trigger_failed")
        self.assertEqual(set_text.call_args_list[-1].args[0], original)

    @patch("clipboard_capture.shutil.which", return_value=None)
    def test_missing_x11_clipboard_tool_is_explicit_and_actionable(self, which):
        with patch.object(clipboard_capture.platform_capabilities, "is_wayland", False), patch.object(
            clipboard_capture.platform_capabilities, "is_x11", True
        ), patch.dict(os.environ, {"DISPLAY": "", "WAYLAND_DISPLAY": ""}, clear=False):
            result = clipboard_capture.capture_selection_text_with_restore()

        self.assertFalse(result["ok"])
        self.assertEqual(result["capture_status"], "unsupported")
        self.assertEqual(result["missing_tool"], "DISPLAY")
        self.assertIn("DISPLAY is not set", result["message"])
        which.assert_any_call("xclip")
        which.assert_any_call("xsel")

    @patch("clipboard_capture.shutil.which")
    def test_clipboard_tool_detection_is_live_per_capture_attempt(self, which):
        which.side_effect = [None, None, None, "/usr/bin/xclip", None, "/usr/bin/xdotool"]
        with patch.object(clipboard_capture.platform_capabilities, "is_wayland", False), patch.object(
            clipboard_capture.platform_capabilities, "is_x11", True
        ), patch.dict(os.environ, {"DISPLAY": ":99"}, clear=False):
            first = clipboard_capture._selection_capture_support()
            second = clipboard_capture._selection_capture_support()

        self.assertFalse(first["supported"])
        self.assertEqual(first["missing_tool"], "xclip or xsel")
        self.assertTrue(second["supported"])
        self.assertEqual(second["tool"], "xclip")
        self.assertEqual(second["clipboard_backend"]["name"], "xclip")
        self.assertEqual(second["copy_trigger_backend"]["name"], "xdotool")

    @patch("clipboard_capture.subprocess.run")
    @patch("clipboard_capture.shutil.which", return_value="/usr/bin/xclip")
    def test_live_xclip_read_bypasses_cached_pyperclip_backend(self, _which, run):
        run.return_value = type("Completed", (), {"returncode": 0, "stdout": b"selected text"})()
        with patch.object(clipboard_capture.platform_capabilities, "is_wayland", False), patch.object(
            clipboard_capture.platform_capabilities, "is_x11", True
        ), patch.object(clipboard_capture.pyperclip, "paste", side_effect=AssertionError("stale pyperclip backend")), patch.dict(
            os.environ, {"DISPLAY": ":99"}, clear=False
        ):
            result = clipboard_capture._clipboard_get_text()

        self.assertEqual(result, "selected text")
        run.assert_called_once_with(
            ["xclip", "-selection", "clipboard", "-o"], check=False, capture_output=True, timeout=5
        )

    @patch("clipboard_capture.subprocess.run")
    def test_linux_clipboard_writer_detaches_child_output_pipes(self, run):
        run.return_value = type("Completed", (), {"returncode": 0})()

        self.assertTrue(clipboard_capture._linux_clipboard_set_text("xclip", "probe text"))

        run.assert_called_once_with(
            ["xclip", "-selection", "clipboard"],
            input=b"probe text",
            check=False,
            stdout=clipboard_capture.subprocess.DEVNULL,
            stderr=clipboard_capture.subprocess.DEVNULL,
            timeout=5,
        )
        self.assertNotIn("capture_output", run.call_args.kwargs)
        self.assertNotIn("shell", run.call_args.kwargs)

    @patch("clipboard_capture.subprocess.run")
    def test_linux_clipboard_writer_fails_closed_on_missing_or_failed_writer(self, run):
        self.assertFalse(clipboard_capture._linux_clipboard_set_text("missing", "probe text"))
        run.assert_not_called()

        run.return_value = type("Completed", (), {"returncode": 1})()
        self.assertFalse(clipboard_capture._linux_clipboard_set_text("xsel", "probe text"))

        run.side_effect = subprocess.TimeoutExpired(["wl-copy"], 5)
        self.assertFalse(clipboard_capture._linux_clipboard_set_text("wl-clipboard", "probe text"))

    @patch("clipboard_capture.subprocess.run")
    def test_x11_copy_trigger_uses_argv_and_bounded_timeout(self, run):
        run.return_value = type("Completed", (), {"returncode": 0})()

        result = clipboard_capture._trigger_selection_copy({"name": "xdotool"})

        self.assertTrue(result["ok"])
        run.assert_called_once_with(
            ["xdotool", "key", "--clearmodifiers", "ctrl+c"],
            check=False,
            capture_output=True,
            timeout=2,
        )
        self.assertNotIn("shell", run.call_args.kwargs)

    @patch("clipboard_capture.subprocess.run")
    def test_wayland_copy_triggers_use_explicit_argv(self, run):
        run.return_value = type("Completed", (), {"returncode": 0})()

        expected = {
            "wtype": ["wtype", "-M", "ctrl", "-k", "c", "-m", "ctrl"],
            "ydotool": ["ydotool", "key", "29:1", "46:1", "46:0", "29:0"],
        }
        for tool, argv in expected.items():
            with self.subTest(tool=tool):
                self.assertTrue(clipboard_capture._trigger_selection_copy({"name": tool})["ok"])
                self.assertEqual(run.call_args.args[0], argv)
                self.assertEqual(run.call_args.kwargs["timeout"], 2)

    @patch("clipboard_capture.shutil.which")
    def test_x11_support_requires_clipboard_and_copy_trigger(self, which):
        which.side_effect = lambda name: "/usr/bin/" + name if name in {"xclip", "xdotool"} else None
        with patch.object(clipboard_capture.platform_capabilities, "is_wayland", False), patch.object(
            clipboard_capture.platform_capabilities, "is_x11", True
        ), patch.dict(os.environ, {"DISPLAY": ":99"}, clear=False):
            result = clipboard_capture._selection_capture_support()

        self.assertTrue(result["supported"])
        self.assertEqual(result["clipboard_backend"]["name"], "xclip")
        self.assertEqual(result["copy_trigger_backend"]["name"], "xdotool")

    @patch("clipboard_capture.shutil.which", side_effect=lambda name: "/usr/bin/" + name)
    def test_wayland_requires_live_display_even_when_tools_exist(self, _which):
        with patch.object(clipboard_capture.platform_capabilities, "is_wayland", True), patch.object(
            clipboard_capture.platform_capabilities, "is_x11", False
        ), patch.dict(os.environ, {"WAYLAND_DISPLAY": "", "DISPLAY": ""}, clear=False):
            result = clipboard_capture._selection_capture_support()

        self.assertFalse(result["supported"])
        self.assertEqual(result["missing_tool"], "WAYLAND_DISPLAY")
        self.assertEqual(result["clipboard_backend"]["required"], ["WAYLAND_DISPLAY"])
        self.assertIn("WAYLAND_DISPLAY is not set", clipboard_capture._unsupported_capture_result(result)["message"])

    @patch("clipboard_capture.shutil.which", side_effect=lambda name: "/usr/bin/" + name)
    def test_x11_requires_live_display_even_when_tools_exist(self, _which):
        with patch.object(clipboard_capture.platform_capabilities, "is_wayland", False), patch.object(
            clipboard_capture.platform_capabilities, "is_x11", True
        ), patch.dict(os.environ, {"WAYLAND_DISPLAY": "", "DISPLAY": ""}, clear=False):
            result = clipboard_capture._selection_capture_support()

        self.assertFalse(result["supported"])
        self.assertEqual(result["missing_tool"], "DISPLAY")
        self.assertEqual(result["clipboard_backend"]["required"], ["DISPLAY"])
        self.assertIn("DISPLAY is not set", clipboard_capture._unsupported_capture_result(result)["message"])

    @patch("clipboard_capture.shutil.which", return_value=None)
    def test_wayland_without_copy_trigger_is_actionable(self, _which):
        with patch.object(clipboard_capture.platform_capabilities, "is_wayland", True), patch.object(
            clipboard_capture.platform_capabilities, "is_x11", False
        ):
            result = clipboard_capture._selection_capture_support()

        self.assertFalse(result["supported"])
        self.assertEqual(result["copy_trigger_backend"]["required"], ["wtype or ydotool"])

    def test_macos_selection_capture_remains_explicitly_unsupported(self):
        with patch.object(clipboard_capture.platform_capabilities, "is_macos", True), patch.object(
            clipboard_capture.platform_capabilities, "is_wayland", False
        ), patch.object(clipboard_capture.platform_capabilities, "is_x11", False):
            result = clipboard_capture._selection_capture_support()

        self.assertFalse(result["supported"])
        self.assertFalse(result["copy_trigger_backend"]["available"])
        self.assertIn("macOS selection capture support", result["copy_trigger_backend"]["required"])

    def test_trigger_failure_does_not_return_stale_clipboard(self):
        support = _supported_test_backend()
        support["copy_trigger_backend"] = {"name": "xdotool", "available": True, "required": []}
        with patch.object(clipboard_capture, "_selection_capture_support", return_value=support), patch.object(
            clipboard_capture, "_clipboard_get_text", side_effect=["OLD CLIPBOARD"]
        ), patch.object(clipboard_capture, "_clipboard_set_text", return_value=True) as set_text, patch.object(
            clipboard_capture, "_trigger_selection_copy", return_value={"ok": False, "error": "exit status 1"}
        ):
            result = clipboard_capture.capture_selection_text_with_restore()

        self.assertFalse(result["ok"])
        self.assertEqual(result["capture_status"], "trigger_failed")
        self.assertFalse(result["used_fallback"])
        self.assertEqual(set_text.call_args_list[-1].args[0], "OLD CLIPBOARD")

    def test_server_broadcasts_and_returns_unsupported_capture(self):
        capture_result = {
            "ok": False,
            "text": "",
            "capture_status": "unsupported",
            "missing_tool": "xclip or xsel",
            "message": "Can't read selected text — xclip or xsel is not installed. Install xclip to enable this.",
        }
        with patch.object(server, "broadcast_status_threadsafe") as broadcast, patch.object(
            clipboard_capture, "capture_selection_text_with_restore", return_value=capture_result
        ):
            result = server.handle_review_tts_shortcut()

        self.assertEqual(result, capture_result)
        broadcast.assert_called_once_with("selection_capture_failed", capture_result)

    def test_server_returns_capture_exception_as_failure(self):
        with patch.object(server, "broadcast_status_threadsafe") as broadcast, patch.object(
            clipboard_capture, "capture_selection_text_with_restore", side_effect=RuntimeError("clipboard probe failed")
        ):
            result = server.handle_review_tts_shortcut()

        self.assertFalse(result["ok"])
        self.assertEqual(result["capture_status"], "exception")
        self.assertIn("Try selecting text again", result["message"])
        broadcast.assert_called_once_with("selection_capture_failed", result)


if __name__ == "__main__":
    unittest.main()
