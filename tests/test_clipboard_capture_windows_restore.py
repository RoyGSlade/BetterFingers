import unittest
from unittest.mock import patch

import clipboard_capture


class _FixedUUID:
    hex = "fixed"


class ClipboardCaptureWindowsRestoreTests(unittest.TestCase):
    def test_snapshot_signature_hashes_full_payload(self):
        first = [(13, b"prefix-" + b"a" * 32 + b"x")]
        second = [(13, b"prefix-" + b"a" * 32 + b"y")]

        self.assertNotEqual(
            clipboard_capture._snapshot_signature(first),
            clipboard_capture._snapshot_signature(second),
        )

    def test_delayed_restore_repairs_unchanged_owned_copy(self):
        original = [(13, b"old")]
        owned = [(13, b"selected")]
        with patch.object(clipboard_capture, "IS_WINDOWS", True), patch.object(
            clipboard_capture, "_capture_clipboard_snapshot_windows", return_value=owned
        ), patch.object(clipboard_capture, "_restore_clipboard_snapshot_windows") as restore, patch.object(
            clipboard_capture.threading, "Thread"
        ) as thread:
            clipboard_capture._schedule_delayed_clipboard_restore(
                original, expected_owned_snapshot=owned
            )
            thread.call_args.kwargs["target"]()

        restore.assert_called_once_with(original)

    def test_delayed_restore_preserves_fresh_user_copy(self):
        original = [(13, b"old")]
        owned = [(13, b"selected")]
        fresh = [(13, b"new-user-copy")]
        with patch.object(clipboard_capture, "IS_WINDOWS", True), patch.object(
            clipboard_capture, "_capture_clipboard_snapshot_windows", return_value=fresh
        ), patch.object(clipboard_capture, "_restore_clipboard_snapshot_windows") as restore, patch.object(
            clipboard_capture.threading, "Thread"
        ) as thread:
            clipboard_capture._schedule_delayed_clipboard_restore(
                original, expected_owned_snapshot=owned
            )
            thread.call_args.kwargs["target"]()

        restore.assert_not_called()

    # OR-13 added a live host-tooling gate at the top of
    # capture_selection_text_with_restore has a live clipboard plus copy-trigger
    # capability gate on Linux and returns "unsupported" before touching the
    # clipboard when either backend is absent. These tests fake the clipboard
    # end to end and exercise the Windows restore path, so they state both
    # preconditions explicitly.
    @patch("clipboard_capture._selection_capture_support",
           return_value={"supported": True, "tool": "native", "copy_trigger_backend": {"name": "native-keyboard", "available": True, "required": []}})
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
        _support,
    ):
        snapshot = [(13, b"original-payload")]
        detected_owned_snapshot = [(13, b"selected-payload")]
        later_user_snapshot = [(13, b"fresh-user-copy")]
        state = {"restored": False, "calls": 0}

        def capture_snapshot_side_effect():
            state["calls"] += 1
            if state["calls"] == 1:
                return snapshot
            return later_user_snapshot if state["restored"] else detected_owned_snapshot

        def restore_snapshot_side_effect(_snapshot):
            state["restored"] = True
            return True

        capture_snapshot.side_effect = capture_snapshot_side_effect
        restore_snapshot.side_effect = restore_snapshot_side_effect
        get_text.side_effect = ["https://example.com", "Rotate back post."]

        result = clipboard_capture.capture_selection_text_with_restore(timeout_ms=50, poll_ms=25)

        self.assertTrue(result["ok"])
        press_and_release.assert_called_once_with("ctrl+c")
        restore_snapshot.assert_called_once_with(snapshot)
        delayed_restore.assert_called_once()
        self.assertEqual(
            delayed_restore.call_args.kwargs["expected_owned_snapshot"], detected_owned_snapshot
        )
        self.assertEqual(capture_snapshot.call_count, 2)
        self.assertEqual(set_text.call_args_list[0].args[0], "__betterfingers_clipboard_probe_fixed__")

    @patch("clipboard_capture._selection_capture_support",
           return_value={"supported": True, "tool": "native", "copy_trigger_backend": {"name": "native-keyboard", "available": True, "required": []}})
    @patch("clipboard_capture._schedule_delayed_clipboard_restore")
    @patch("clipboard_capture._restore_clipboard_snapshot_windows", return_value=False)
    @patch("clipboard_capture._capture_clipboard_snapshot_windows")
    @patch("clipboard_capture.time.sleep", return_value=None)
    @patch("clipboard_capture.keyboard.press_and_release")
    @patch("clipboard_capture._clipboard_set_text", return_value=True)
    @patch("clipboard_capture._clipboard_get_text")
    @patch("clipboard_capture.uuid.uuid4", return_value=_FixedUUID())
    def test_windows_restore_preserves_empty_capture_when_snapshot_restore_fails(
        self,
        _uuid4,
        get_text,
        set_text,
        _press_and_release,
        _sleep,
        capture_snapshot,
        restore_snapshot,
        delayed_restore,
        _support,
    ):
        sentinel = "__betterfingers_clipboard_probe_fixed__"
        capture_snapshot.return_value = [(13, b"payload")]
        get_text.side_effect = ["Original clipboard text.", sentinel, sentinel]

        result = clipboard_capture.capture_selection_text_with_restore(timeout_ms=50, poll_ms=25)

        self.assertFalse(result["ok"])
        self.assertEqual(result["text"], "")
        self.assertFalse(result["used_fallback"])
        self.assertEqual(result["capture_status"], "empty")
        restore_snapshot.assert_called_once()
        delayed_restore.assert_not_called()
        self.assertEqual(set_text.call_args_list[-1].args[0], "Original clipboard text.")


if __name__ == "__main__":
    unittest.main()
