import unittest
from unittest.mock import Mock, patch

from main import App


class F9PrimaryFlowTests(unittest.TestCase):
    def _build_app(self):
        app = App()
        app.notification_overlay_enabled = True
        app.notification_overlay = Mock()
        app._dispatch_send = Mock()
        app._speak_review_text = Mock()
        return app

    def test_pending_accepted_draft_sends_first(self):
        app = self._build_app()
        app.pending_manual_send_ids = [7]
        app.draft_queue = [
            {"id": 7, "status": "awaiting_manual_send", "final_text": "Push now."}
        ]

        with patch("main.capture_selection_text_with_restore") as capture_mock:
            app._handle_manual_send_hotkey()

        app._dispatch_send.assert_called_once_with(
            {"id": 7, "status": "awaiting_manual_send", "final_text": "Push now."},
            "Push now.",
            open_chat=False,
        )
        capture_mock.assert_not_called()

    @patch(
        "main.capture_selection_text_with_restore",
        return_value={
            "ok": True,
            "text": "Rotate back post.",
            "used_fallback": False,
            "message": "Captured selected text.",
        },
    )
    def test_no_pending_capture_success_routes_to_tts(self, _capture_mock):
        app = self._build_app()
        app.pending_manual_send_ids = []
        app.draft_queue = []

        app._handle_manual_send_hotkey()

        app._speak_review_text.assert_called_once_with(
            "Rotate back post.",
            source="primary_hotkey",
        )
        app._dispatch_send.assert_not_called()

    @patch(
        "main.capture_selection_text_with_restore",
        return_value={
            "ok": True,
            "text": "Fallback clipboard sentence.",
            "used_fallback": True,
            "message": "Using existing clipboard text fallback.",
        },
    )
    def test_no_pending_readable_fallback_routes_to_tts(self, _capture_mock):
        app = self._build_app()
        app.pending_manual_send_ids = []
        app.draft_queue = []

        app._handle_manual_send_hotkey()

        app._speak_review_text.assert_called_once_with(
            "Fallback clipboard sentence.",
            source="primary_hotkey",
        )

    @patch(
        "main.capture_selection_text_with_restore",
        return_value={
            "ok": False,
            "text": "",
            "used_fallback": False,
            "message": "No readable selected/copied text found.",
        },
    )
    def test_no_pending_no_readable_text_notifies_and_skips_tts(self, _capture_mock):
        app = self._build_app()
        app.pending_manual_send_ids = []
        app.draft_queue = []

        app._handle_manual_send_hotkey()

        app._speak_review_text.assert_not_called()
        app.notification_overlay.show_message.assert_called_once_with(
            "No readable selected/copied text found.",
            1800,
        )


if __name__ == "__main__":
    unittest.main()
