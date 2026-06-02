import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server


class DummyTranscriber:
    def __init__(self, preload=False):
        self.preload = preload
        self.calls = []

    def transcribe(self, audio_data):
        self.calls.append(audio_data)
        return "raw transcript"


class EmptyTranscriber(DummyTranscriber):
    def transcribe(self, audio_data):
        self.calls.append(audio_data)
        return ""


class DummyEngine:
    def process_fast_lane(self, text, preset):
        return f"{preset}: {text}"


class DummyRewriteEngine:
    def rewrite_text(self, text, action="clearer", custom_instruction="", max_output_tokens=None):
        suffix = f" {custom_instruction}" if custom_instruction else ""
        return f"{action}: {text}{suffix}"


class DummyRecordingResult:
    audio_data = [0.1, 0.2, 0.3]
    sample_rate = 16000
    duration_seconds = 1.0
    frame_count = 3
    sample_count = 3
    max_amplitude = 0.2
    rms_amplitude = 0.05
    stop_reason = "manual"


class SilentRecordingResult:
    audio_data = []
    sample_rate = 16000
    duration_seconds = 0.1
    frame_count = 0
    sample_count = 0
    max_amplitude = 0.0
    rms_amplitude = 0.0
    stop_reason = "manual"


class ImmediateThread:
    def __init__(self, target, daemon=False, name=None):
        self.target = target
        self.daemon = daemon
        self.name = name

    def start(self):
        self.target()


class DummyOutputInjector:
    def __init__(self):
        self.stopped = False
        self.released = False

    def stop_typing(self):
        self.stopped = True

    def release_mute_key(self):
        self.released = True


class DummyRecordingManager:
    def __init__(self):
        self.stop_reason = None

    def request_stop(self, reason="manual"):
        self.stop_reason = reason


class ServerDraftTests(unittest.TestCase):
    def setUp(self):
        self._transcriber = server.transcriber
        self._output_injector = server.output_injector
        self._hotkey_manager = server.hotkey_manager
        server.transcriber = None
        server.output_injector = None
        server.hotkey_manager = None
        server.draft_queue.clear()
        server.draft_recordings.clear()
        server.pending_manual_send_ids.clear()
        server.next_draft_id = 1

    def tearDown(self):
        server.transcriber = self._transcriber
        server.output_injector = self._output_injector
        server.hotkey_manager = self._hotkey_manager
        server.draft_queue.clear()
        server.draft_recordings.clear()
        server.pending_manual_send_ids.clear()
        server.next_draft_id = 1

    def test_create_draft_assigns_id_and_caps_history(self):
        first = server.create_draft("raw", "final")

        self.assertEqual(first["id"], 1)
        self.assertEqual(first["raw_text"], "raw")
        self.assertEqual(first["final_text"], "final")
        self.assertEqual(first["preset"], "True Janitor")
        self.assertEqual(first["status"], "pending")
        self.assertEqual(first["metadata"], {})
        self.assertEqual(first["error"], "")
        self.assertEqual(first["gate_reasons"], [])
        self.assertEqual(first["token_count"], 1)
        self.assertGreater(first["token_limit"], 0)
        self.assertFalse(first["long_text"])

        for index in range(25):
            server.create_draft(f"raw {index}", f"final {index}")

        self.assertEqual(len(server.draft_queue), server.MAX_DRAFT_HISTORY)
        self.assertEqual(server.draft_queue[0]["id"], 7)

    def test_draft_endpoints_list_latest_accept_and_decline(self):
        draft = server.create_draft("raw", "final")

        with TestClient(server.app) as client:
            drafts = client.get("/drafts")
            self.assertEqual(drafts.status_code, 200)
            self.assertEqual(drafts.json()["drafts"][0]["id"], draft["id"])

            latest = client.get("/drafts/latest")
            self.assertEqual(latest.status_code, 200)
            self.assertEqual(latest.json()["draft"]["final_text"], "final")

            accepted = client.post(f"/drafts/{draft['id']}/accept")
            self.assertEqual(accepted.status_code, 200)
            self.assertEqual(accepted.json()["status"], "accepted")
            self.assertTrue(accepted.json()["pending_send"])
            self.assertEqual(server.pending_manual_send_ids, [draft["id"]])

            declined = client.post(f"/drafts/{draft['id']}/decline")
            self.assertEqual(declined.status_code, 200)
            self.assertEqual(declined.json()["status"], "declined")
            self.assertFalse(declined.json()["pending_send"])
            self.assertEqual(server.pending_manual_send_ids, [])

            missing = client.post("/drafts/999/accept")
            self.assertEqual(missing.status_code, 404)

    def test_latest_draft_returns_null_when_empty(self):
        with TestClient(server.app) as client:
            latest = client.get("/drafts/latest")
            self.assertEqual(latest.status_code, 200)
            self.assertIsNone(latest.json()["draft"])

    def test_process_recording_result_creates_draft_and_broadcasts_preview(self):
        statuses = []

        with patch.object(server, "Transcriber", DummyTranscriber), patch.object(
            server, "get_engine", return_value=DummyEngine()
        ), patch.object(server, "broadcast_status_threadsafe", side_effect=lambda status, data=None: statuses.append((status, data or {}))):
            draft = server.process_recording_result(DummyRecordingResult())

        self.assertEqual(draft["raw_text"], "raw transcript")
        self.assertEqual(draft["final_text"], "True Janitor: raw transcript")
        self.assertEqual(draft["status"], "pending")
        self.assertEqual([status for status, _data in statuses], ["transcribing", "rewriting", "preview_ready", "idle"])
        self.assertEqual(statuses[2][1]["draft_id"], draft["id"])
        self.assertEqual(statuses[2][1]["raw_text"], "raw transcript")
        self.assertEqual(statuses[2][1]["final_text"], "True Janitor: raw transcript")
        self.assertEqual(draft["metadata"]["sample_rate"], 16000)
        self.assertEqual(draft["metadata"]["stop_reason"], "manual")

    def test_on_recording_complete_processes_recording_in_background_worker(self):
        with patch.object(server.threading, "Thread", ImmediateThread), patch.object(
            server, "Transcriber", DummyTranscriber
        ), patch.object(server, "get_engine", return_value=DummyEngine()), patch.object(
            server, "broadcast_status_threadsafe"
        ):
            server.on_recording_complete(DummyRecordingResult())

        self.assertEqual(len(server.draft_queue), 1)
        self.assertEqual(server.draft_queue[0]["final_text"], "True Janitor: raw transcript")

    def test_process_recording_result_blocks_no_audio_before_llm(self):
        statuses = []

        with patch.object(server, "Transcriber", EmptyTranscriber), patch.object(
            server, "get_engine", side_effect=AssertionError("LLM should not run for blocked audio")
        ), patch.object(server, "broadcast_status_threadsafe", side_effect=lambda status, data=None: statuses.append((status, data or {}))):
            draft = server.process_recording_result(SilentRecordingResult())

        self.assertEqual(draft["status"], "blocked")
        self.assertIn("clip_too_short", " ".join(draft["gate_reasons"]))
        self.assertIn("near_silent", " ".join(draft["gate_reasons"]))
        self.assertIn("empty_transcript", draft["gate_reasons"])
        self.assertEqual([status for status, _data in statuses], ["transcribing", "draft_blocked", "idle"])

    def test_process_recording_result_creates_error_draft_when_llm_fails(self):
        statuses = []

        with patch.object(server, "Transcriber", DummyTranscriber), patch.object(
            server, "get_engine", side_effect=RuntimeError("llm offline")
        ), patch.object(server, "broadcast_status_threadsafe", side_effect=lambda status, data=None: statuses.append((status, data or {}))):
            draft = server.process_recording_result(DummyRecordingResult())

        self.assertEqual(draft["status"], "error")
        self.assertEqual(draft["raw_text"], "raw transcript")
        self.assertIn("llm offline", draft["error"])
        self.assertEqual([status for status, _data in statuses], ["transcribing", "rewriting", "draft_error", "error", "idle"])

    def test_retry_endpoint_reprocesses_stored_recording(self):
        with patch.object(server, "Transcriber", DummyTranscriber), patch.object(
            server, "get_engine", side_effect=RuntimeError("llm offline")
        ), patch.object(server, "broadcast_status_threadsafe"):
            failed = server.process_recording_result(DummyRecordingResult())

        with patch.object(server, "Transcriber", DummyTranscriber), patch.object(
            server, "get_engine", return_value=DummyEngine()
        ), patch.object(server, "broadcast_status_threadsafe"):
            with TestClient(server.app) as client:
                retried = client.post(f"/drafts/{failed['id']}/retry")

        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.json()["status"], "pending")
        self.assertEqual(retried.json()["final_text"], "True Janitor: raw transcript")
        self.assertEqual(len(server.draft_queue), 2)

    def test_edit_draft_updates_review_fields_and_broadcasts(self):
        draft = server.create_draft("raw", "final")
        statuses = []

        with patch.object(server, "broadcast_status_threadsafe", side_effect=lambda status, data=None: statuses.append((status, data or {}))):
            with TestClient(server.app) as client:
                response = client.post(f"/drafts/{draft['id']}/edit", json={"final_text": "edited text now"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["final_text"], "edited text now")
        self.assertEqual(data["token_count"], 3)
        self.assertEqual(statuses[0][0], "draft_updated")
        self.assertEqual(statuses[0][1]["draft_id"], draft["id"])

    def test_rewrite_draft_updates_final_text_and_broadcasts(self):
        draft = server.create_draft("raw", "final")
        statuses = []

        with patch.object(server, "get_engine", return_value=DummyRewriteEngine()), patch.object(
            server, "broadcast_status_threadsafe", side_effect=lambda status, data=None: statuses.append((status, data or {}))
        ):
            with TestClient(server.app) as client:
                response = client.post(
                    f"/drafts/{draft['id']}/rewrite",
                    json={"action": "custom", "custom_instruction": "make it cozy"},
                )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["final_text"], "custom: final make it cozy")
        self.assertEqual(data["status"], "pending")
        self.assertEqual([status for status, _payload in statuses], ["draft_rewriting", "draft_rewritten"])
        self.assertEqual(statuses[1][1]["draft_id"], draft["id"])

    def test_draft_tts_uses_selected_text_payload(self):
        draft = server.create_draft("raw", "final")
        statuses = []

        with patch.object(server, "broadcast_status_threadsafe", side_effect=lambda status, data=None: statuses.append((status, data or {}))):
            with TestClient(server.app) as client:
                response = client.post(f"/drafts/{draft['id']}/tts", json={"text": "selected words"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["text_length"], len("selected words"))
        self.assertEqual(statuses[0][0], "draft_tts_requested")

    def test_send_draft_copy_only_marks_sent(self):
        draft = server.create_draft("raw", "final")

        with patch.object(server, "copy_text_to_clipboard", return_value={"ok": True, "action": "copy_only", "message": "copied"}):
            with TestClient(server.app) as client:
                response = client.post(f"/drafts/{draft['id']}/send", json={"action": "copy_only"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "sent")
        self.assertFalse(data["pending_send"])
        self.assertTrue(data["send_result"]["ok"])

    def test_send_draft_falls_back_to_copy_when_injection_unsupported(self):
        draft = server.create_draft("raw", "final")

        with patch.object(server, "get_capabilities", return_value={"supports_input_injection": False}), patch.object(
            server, "copy_text_to_clipboard", return_value={"ok": True, "action": "copy_only", "message": "copied"}
        ):
            with TestClient(server.app) as client:
                response = client.post(f"/drafts/{draft['id']}/send", json={"action": "paste"})

        self.assertEqual(response.status_code, 200)
        result = response.json()["send_result"]
        self.assertTrue(result["ok"])
        self.assertTrue(result["fallback"])
        self.assertEqual(result["requested_action"], "paste")
        self.assertEqual(result["action"], "copy_only")

    def test_primary_action_sends_pending_draft_first(self):
        draft = server.create_draft("raw", "final")
        with TestClient(server.app) as client:
            client.post(f"/drafts/{draft['id']}/accept")

        with patch.object(server, "perform_output_action", return_value={"ok": True, "action": "paste", "message": "sent"}):
            result = server.handle_primary_action()

        self.assertEqual(result["status"], "sent")
        self.assertEqual(server.pending_manual_send_ids, [])

    def test_primary_action_captures_selection_when_no_pending_draft(self):
        capture_result = {"ok": True, "text": "selected text", "message": "Captured selected text."}

        with patch("clipboard_capture.capture_selection_text_with_restore", return_value=capture_result), patch.object(
            server, "broadcast_status_threadsafe"
        ) as broadcast:
            result = server.handle_primary_action()

        self.assertEqual(result, capture_result)
        broadcast.assert_called_with("selection_captured", capture_result)

    def test_emergency_stop_stops_recording_typing_and_pending_sends(self):
        injector = DummyOutputInjector()
        manager = DummyRecordingManager()
        server.output_injector = injector
        server.hotkey_manager = manager
        server.pending_manual_send_ids.append(123)

        with patch.object(server, "broadcast_status_threadsafe"):
            result = server.emergency_stop_runtime()

        self.assertTrue(result["ok"])
        self.assertEqual(manager.stop_reason, "emergency_stop")
        self.assertTrue(injector.stopped)
        self.assertTrue(injector.released)
        self.assertEqual(server.pending_manual_send_ids, [])


if __name__ == "__main__":
    unittest.main()
