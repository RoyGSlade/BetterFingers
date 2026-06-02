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


class DummyEngine:
    def process_fast_lane(self, text, preset):
        return f"{preset}: {text}"


class DummyRecordingResult:
    audio_data = [0.1, 0.2, 0.3]


class ImmediateThread:
    def __init__(self, target, daemon=False, name=None):
        self.target = target
        self.daemon = daemon
        self.name = name

    def start(self):
        self.target()


class ServerDraftTests(unittest.TestCase):
    def setUp(self):
        self._transcriber = server.transcriber
        server.transcriber = None
        server.draft_queue.clear()
        server.next_draft_id = 1

    def tearDown(self):
        server.transcriber = self._transcriber
        server.draft_queue.clear()
        server.next_draft_id = 1

    def test_create_draft_assigns_id_and_caps_history(self):
        first = server.create_draft("raw", "final")

        self.assertEqual(first["id"], 1)
        self.assertEqual(first["raw_text"], "raw")
        self.assertEqual(first["final_text"], "final")
        self.assertEqual(first["preset"], "True Janitor")
        self.assertEqual(first["status"], "pending")

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

            declined = client.post(f"/drafts/{draft['id']}/decline")
            self.assertEqual(declined.status_code, 200)
            self.assertEqual(declined.json()["status"], "declined")

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

    def test_on_recording_complete_processes_recording_in_background_worker(self):
        with patch.object(server.threading, "Thread", ImmediateThread), patch.object(
            server, "Transcriber", DummyTranscriber
        ), patch.object(server, "get_engine", return_value=DummyEngine()), patch.object(
            server, "broadcast_status_threadsafe"
        ):
            server.on_recording_complete(DummyRecordingResult())

        self.assertEqual(len(server.draft_queue), 1)
        self.assertEqual(server.draft_queue[0]["final_text"], "True Janitor: raw transcript")


if __name__ == "__main__":
    unittest.main()
