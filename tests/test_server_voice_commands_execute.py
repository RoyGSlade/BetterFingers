import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import server

OVERLAY_CTX = {"review_overlay_open": True}


class ExecuteVoiceCommandTests(unittest.TestCase):
    def setUp(self):
        self._load_draft_patcher = patch("server.load_draft_history")
        self._load_draft_patcher.start()
        self._save_draft_patcher = patch("server.save_draft_history")
        self._save_draft_patcher.start()
        server.draft_queue.clear()
        server.draft_recordings.clear()
        server.pending_manual_send_ids.clear()
        server.next_draft_id = 1

    def tearDown(self):
        self._load_draft_patcher.stop()
        self._save_draft_patcher.stop()
        server.draft_queue.clear()
        server.draft_recordings.clear()
        server.pending_manual_send_ids.clear()
        server.next_draft_id = 1

    def _post(self, client, **payload):
        return client.post("/voice-commands/execute", json=payload)

    def test_no_command_recognized(self):
        with patch.object(server, "broadcast_status_threadsafe"):
            with TestClient(server.app) as client:
                response = self._post(client, text="just plain dictation", context=OVERLAY_CTX)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": False, "reason": "no_command_recognized"})

    def test_disabled_flag_short_circuits(self):
        with patch.object(server, "load_profile", return_value={"app_commands_enabled": False}):
            with TestClient(server.app) as client:
                response = self._post(client, text="send it", context=OVERLAY_CTX)
        self.assertEqual(response.json(), {"ok": False, "reason": "disabled"})

    def test_emergency_stop_executes_without_draft_or_context(self):
        statuses = []
        with patch.object(server, "emergency_stop_runtime", return_value={"ok": True}) as stop_mock, patch.object(
            server, "broadcast_status_threadsafe", side_effect=lambda status, data=None: statuses.append((status, data or {})),
        ):
            with TestClient(server.app) as client:
                response = self._post(client, text="emergency stop")
        stop_mock.assert_called_once()
        self.assertTrue(response.json()["ok"])
        self.assertEqual(statuses[0], ("command_detected", {"action": "emergency_stop", "kind": "app_action", "confidence": 1.0}))

    def test_send_requires_confirmation_before_executing(self):
        draft = server.create_draft("raw", "final")
        statuses = []
        with patch.object(server, "send_draft_by_id") as send_mock, patch.object(
            server, "broadcast_status_threadsafe", side_effect=lambda status, data=None: statuses.append((status, data or {})),
        ):
            with TestClient(server.app) as client:
                response = self._post(client, text="send it", context=OVERLAY_CTX, draft_id=draft["id"])
        send_mock.assert_not_called()
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["reason"], "needs_confirmation")
        self.assertIn("command_needs_confirmation", [s for s, _ in statuses])

    def test_send_executes_when_confirmed(self):
        draft = server.create_draft("raw", "final")
        with patch.object(server, "send_draft_by_id", return_value={"ok": True}) as send_mock, patch.object(
            server, "broadcast_status_threadsafe",
        ):
            with TestClient(server.app) as client:
                response = self._post(
                    client, text="send it", context=OVERLAY_CTX, draft_id=draft["id"], confirm=True,
                )
        send_mock.assert_called_once_with(draft["id"])
        self.assertTrue(response.json()["ok"])

    def test_cancel_declines_the_draft(self):
        draft = server.create_draft("raw", "final")
        with patch.object(server, "broadcast_status_threadsafe"):
            with TestClient(server.app) as client:
                response = self._post(client, text="cancel that", context=OVERLAY_CTX, draft_id=draft["id"])
        self.assertTrue(response.json()["ok"])
        self.assertEqual(server.get_draft_by_id(draft["id"])["status"], "declined")

    def test_copy_calls_clipboard_with_final_text(self):
        draft = server.create_draft("raw", "final text here")
        with patch.object(server, "copy_text_to_clipboard") as copy_mock, patch.object(
            server, "broadcast_status_threadsafe",
        ):
            with TestClient(server.app) as client:
                response = self._post(client, text="copy it", context=OVERLAY_CTX, draft_id=draft["id"])
        copy_mock.assert_called_once_with("final text here")
        self.assertTrue(response.json()["ok"])

    def test_read_back_calls_speak_text_aloud(self):
        draft = server.create_draft("raw", "read this aloud")
        with patch.object(server, "speak_text_aloud") as speak_mock, patch.object(
            server, "broadcast_status_threadsafe",
        ):
            with TestClient(server.app) as client:
                response = self._post(client, text="read that back", context=OVERLAY_CTX, draft_id=draft["id"])
        speak_mock.assert_called_once_with("read this aloud")
        self.assertTrue(response.json()["ok"])

    def test_rewrite_shorter_maps_to_rewrite_draft_with_shorter_action(self):
        draft = server.create_draft("raw", "final")
        with patch.object(server, "rewrite_draft", new_callable=AsyncMock, return_value={"ok": True}) as rewrite_mock, patch.object(
            server, "broadcast_status_threadsafe",
        ):
            with TestClient(server.app) as client:
                response = self._post(client, text="make it shorter", context=OVERLAY_CTX, draft_id=draft["id"])
        self.assertEqual(rewrite_mock.await_args.args[0], draft["id"])
        self.assertEqual(rewrite_mock.await_args.args[1].action, "shorter")
        self.assertTrue(response.json()["ok"])

    def test_retry_calls_retry_draft(self):
        draft = server.create_draft("raw", "final")
        with patch.object(server, "retry_draft", new_callable=AsyncMock, return_value={"ok": True}) as retry_mock, patch.object(
            server, "broadcast_status_threadsafe",
        ):
            with TestClient(server.app) as client:
                response = self._post(client, text="try again", context=OVERLAY_CTX, draft_id=draft["id"])
        retry_mock.assert_awaited_once_with(draft["id"])
        self.assertTrue(response.json()["ok"])

    def test_start_and_stop_recording_call_runtime_functions(self):
        with patch.object(server, "start_recording_runtime", return_value={"ok": True}) as start_mock, patch.object(
            server, "stop_recording_runtime", return_value={"ok": True},
        ) as stop_mock, patch.object(server, "broadcast_status_threadsafe"):
            with TestClient(server.app) as client:
                self._post(client, text="start recording", context={"command_mode_on": True})
                self._post(client, text="stop recording", context={"command_mode_on": True})
        start_mock.assert_called_once()
        stop_mock.assert_called_once()

    def test_missing_draft_id_returns_no_draft_reason(self):
        with patch.object(server, "broadcast_status_threadsafe"):
            with TestClient(server.app) as client:
                response = self._post(client, text="cancel that", context=OVERLAY_CTX)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["reason"], "no_draft")

    def test_switch_persona_not_yet_implemented(self):
        with patch.object(server, "broadcast_status_threadsafe"):
            with TestClient(server.app) as client:
                response = self._post(client, text="switch to formal", context=OVERLAY_CTX)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["reason"], "not_implemented")


if __name__ == "__main__":
    unittest.main()
