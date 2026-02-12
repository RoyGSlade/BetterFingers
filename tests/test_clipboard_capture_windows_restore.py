import unittest
from unittest.mock import patch

import clipboard_capture


class _FixedUUID:
    hex = "fixed"


class ClipboardCaptureWindowsRestoreTests(unittest.TestCase):
    @patch("clipboard_capture._schedule_delayed_clipboard_restore")
    @patch("clipboard_capture._restore_clipboard_snapshot_windows", return_value=True)
    @patch("clipboard_capture._capture_clipboard_snapshot_windows")
    @patch("clipboard_capture.time.sleep", return_value=None)
    @patch("clipboard_capture.keyboard.press_and_release")
    @patch("clipboard_capture._clipboard_set_text", return_value=True)
    @patch("clipboard_capture._clipboard_get_text")
    @patch("clipboard_capture.uuid.uuid4", return_value=_FixedUUID())
    def test_windows_snapshot_restore_used_when_available(
        self,
        _uuid4,
        get_text,
        set_text,
        press_and_release,
        _sleep,
        capture_snapshot,
        restore_snapshot,
        delayed_restore,
    ):
        snapshot = [(13, b"payload")]
        capture_snapshot.return_value = snapshot
        get_text.side_effect = ["https://example.com", "Rotate back post."]

        result = clipboard_capture.capture_selection_text_with_restore(timeout_ms=50, poll_ms=25)

        self.assertTrue(result["ok"])
        press_and_release.assert_called_once_with("ctrl+c")
        restore_snapshot.assert_called_once_with(snapshot)
        delayed_restore.assert_called_once()
        self.assertEqual(set_text.call_args_list[0].args[0], "__betterfingers_clipboard_probe_fixed__")

    @patch("clipboard_capture._schedule_delayed_clipboard_restore")
    @patch("clipboard_capture._restore_clipboard_snapshot_windows", return_value=False)
    @patch("clipboard_capture._capture_clipboard_snapshot_windows")
    @patch("clipboard_capture.time.sleep", return_value=None)
    @patch("clipboard_capture.keyboard.press_and_release")
    @patch("clipboard_capture._clipboard_set_text", return_value=True)
    @patch("clipboard_capture._clipboard_get_text")
    @patch("clipboard_capture.uuid.uuid4", return_value=_FixedUUID())
    def test_windows_restore_falls_back_to_text_restore_when_snapshot_restore_fails(
        self,
        _uuid4,
        get_text,
        set_text,
        _press_and_release,
        _sleep,
        capture_snapshot,
        restore_snapshot,
        delayed_restore,
    ):
        sentinel = "__betterfingers_clipboard_probe_fixed__"
        capture_snapshot.return_value = [(13, b"payload")]
        get_text.side_effect = ["Original clipboard text.", sentinel, sentinel]

        result = clipboard_capture.capture_selection_text_with_restore(timeout_ms=50, poll_ms=25)

        self.assertTrue(result["ok"])
        self.assertTrue(result["used_fallback"])
        restore_snapshot.assert_called_once()
        delayed_restore.assert_not_called()
        self.assertEqual(set_text.call_args_list[-1].args[0], "Original clipboard text.")


if __name__ == "__main__":
    unittest.main()
