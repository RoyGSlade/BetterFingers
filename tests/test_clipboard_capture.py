import unittest
from unittest.mock import patch

import clipboard_capture
import server


class _FixedUUID:
    hex = "fixed"


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

        with patch.object(clipboard_capture, "_selection_capture_support", return_value={"supported": True, "tool": "test"}):
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
    def test_unchanged_capture_uses_guarded_fallback(
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

        with patch.object(clipboard_capture, "_selection_capture_support", return_value={"supported": True, "tool": "test"}):
            result = clipboard_capture.capture_selection_text_with_restore(timeout_ms=50, poll_ms=25)

        self.assertTrue(result["ok"])
        self.assertTrue(result["used_fallback"])
        self.assertEqual(result["text"], original)

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

        with patch.object(clipboard_capture, "_selection_capture_support", return_value={"supported": True, "tool": "test"}):
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

        with patch.object(clipboard_capture, "_selection_capture_support", return_value={"supported": True, "tool": "test"}):
            result = clipboard_capture.capture_selection_text_with_restore(timeout_ms=50, poll_ms=25)

        self.assertTrue(result["ok"])
        self.assertTrue(result["used_fallback"])
        self.assertEqual(set_text.call_args_list[-1].args[0], original)

    @patch("clipboard_capture.shutil.which", return_value=None)
    def test_missing_x11_clipboard_tool_is_explicit_and_actionable(self, which):
        with patch.object(clipboard_capture.platform_capabilities, "is_wayland", False), patch.object(
            clipboard_capture.platform_capabilities, "is_x11", True
        ):
            result = clipboard_capture.capture_selection_text_with_restore()

        self.assertFalse(result["ok"])
        self.assertEqual(result["capture_status"], "unsupported")
        self.assertEqual(result["missing_tool"], "xclip or xsel")
        self.assertIn("Install xclip", result["message"])
        which.assert_any_call("xclip")
        which.assert_any_call("xsel")

    @patch("clipboard_capture.shutil.which")
    def test_clipboard_tool_detection_is_live_per_capture_attempt(self, which):
        which.side_effect = [None, None, "/usr/bin/xclip"]
        with patch.object(clipboard_capture.platform_capabilities, "is_wayland", False), patch.object(
            clipboard_capture.platform_capabilities, "is_x11", True
        ):
            first = clipboard_capture._selection_capture_support()
            second = clipboard_capture._selection_capture_support()

        self.assertFalse(first["supported"])
        self.assertEqual(first["missing_tool"], "xclip or xsel")
        self.assertEqual(second, {"supported": True, "tool": "xclip"})

    @patch("clipboard_capture.subprocess.run")
    @patch("clipboard_capture.shutil.which", return_value="/usr/bin/xclip")
    def test_live_xclip_read_bypasses_cached_pyperclip_backend(self, _which, run):
        run.return_value = type("Completed", (), {"returncode": 0, "stdout": b"selected text"})()
        with patch.object(clipboard_capture.platform_capabilities, "is_wayland", False), patch.object(
            clipboard_capture.platform_capabilities, "is_x11", True
        ), patch.object(clipboard_capture.pyperclip, "paste", side_effect=AssertionError("stale pyperclip backend")):
            result = clipboard_capture._clipboard_get_text()

        self.assertEqual(result, "selected text")
        run.assert_called_once_with(
            ["xclip", "-selection", "clipboard", "-o"], check=False, capture_output=True, timeout=5
        )

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
