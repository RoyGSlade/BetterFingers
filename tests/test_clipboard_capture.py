import unittest
from unittest.mock import patch

import clipboard_capture


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

        result = clipboard_capture.capture_selection_text_with_restore(timeout_ms=50, poll_ms=25)

        self.assertFalse(result["ok"])
        self.assertEqual(result["text"], "")

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

        result = clipboard_capture.capture_selection_text_with_restore(timeout_ms=50, poll_ms=25)

        self.assertTrue(result["ok"])
        self.assertTrue(result["used_fallback"])
        self.assertEqual(set_text.call_args_list[-1].args[0], original)


if __name__ == "__main__":
    unittest.main()
