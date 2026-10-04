"""The gaming policy must judge the window that will actually receive the text.

The application-context snapshot is refreshed only when something calls
``poll()`` -- in practice the dashboard's 4 s /app-context/status timer, which
Chromium throttles when the window is hidden. Delivery used to read that cached
snapshot, so alt-tabbing into a game and dictating (or dictating with the
dashboard minimised) decided against the PREVIOUS window and could type into
the game. Delivery now detects the foreground app at send time.

Every external effect is faked: no real clipboard, no real keystrokes.
"""

import unittest
from unittest.mock import patch

import server

_INACTIVE = {"gaming_policy": {"active": False}}
_ACTIVE = {"gaming_policy": {"active": True}}


class _StaleThenGameService:
    """Cached snapshot says "not a game"; detecting now says "game"."""

    def __init__(self, poll_result=_ACTIVE, poll_error=None):
        self.poll_calls = 0
        self._poll_result = poll_result
        self._poll_error = poll_error

    def current(self):
        return _INACTIVE

    def poll(self):
        self.poll_calls += 1
        if self._poll_error is not None:
            raise self._poll_error
        return self._poll_result


class _RecordingInjector:
    typed = []

    def __init__(self, profile_name=None):
        pass

    def reload_config(self, profile_name=None):
        pass

    def open_chat(self):
        _RecordingInjector.typed.append("<open chat>")

    def send_output(self, text, auto_submit=False, close_action="none"):
        _RecordingInjector.typed.append(text)

    def type_text(self, text):
        _RecordingInjector.typed.append(text)


class GamingDeliveryTests(unittest.TestCase):
    def setUp(self):
        _RecordingInjector.typed = []
        self.copied = []
        prior = server.output_injector
        server.output_injector = None
        self.addCleanup(lambda: setattr(server, "output_injector", prior))
        caps = {"supports_input_injection": True, "platform": "windows", "session_type": "desktop"}
        for target in (
            patch("backend.output.injector.InputInjector", _RecordingInjector),
            patch.object(server, "get_capabilities", return_value=caps),
            patch.object(server, "get_profile_output_settings",
                         return_value={"auto_submit": False, "chat_close_action": "none",
                                       "send_mode": "manual"}),
            patch.object(server, "get_last_active_profile", return_value="Default"),
            patch.object(server, "copy_text_to_clipboard", side_effect=self._fake_copy),
        ):
            target.start()
            self.addCleanup(target.stop)

    def _fake_copy(self, text):
        self.copied.append(text)
        return {"ok": True, "action": "copy_only", "actual_action": "copy_only", "message": "copied"}

    def _deliver(self, service, action):
        with patch("backend.services.app_context.get_service", return_value=service):
            return server.perform_output_action("hello from the lobby", action)

    def test_switching_into_a_game_after_the_last_poll_still_blocks_keystrokes(self):
        for action in ("paste", "type", "open_chat_then_send"):
            with self.subTest(action=action):
                _RecordingInjector.typed = []
                self.copied = []
                service = _StaleThenGameService()
                payload = self._deliver(service, action)
                self.assertEqual(service.poll_calls, 1)
                self.assertEqual(payload["requested_action"], "copy_only")
                self.assertEqual(_RecordingInjector.typed, [])
                self.assertEqual(self.copied, ["hello from the lobby"])

    def test_detection_failure_copies_instead_of_trusting_stale_non_game_snapshot(self):
        service = _StaleThenGameService(poll_error=OSError("foreground query failed"))
        payload = self._deliver(service, "paste")
        self.assertEqual(service.poll_calls, 1)
        self.assertEqual(payload["requested_action"], "copy_only")
        self.assertEqual(_RecordingInjector.typed, [])
        self.assertEqual(self.copied, ["hello from the lobby"])


if __name__ == "__main__":
    unittest.main()
