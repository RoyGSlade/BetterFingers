import os
import tempfile
import time
import types
import unittest
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

import history_store
import recordings
import server


class DummyTranscriber:
    def __init__(self, profile_name="Default", preload=True):
        self.profile_name = profile_name
        self.preload = preload
        self.model = None


class PrivacyWipeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name
        server.transcriber = None
        history_store._initialized_path = None
        # Keep the startup warmup thread from loading (and on a fresh data
        # dir, DOWNLOADING) real models: an in-flight .gguf.part download
        # holds an open handle that breaks TemporaryDirectory cleanup on
        # Windows (WinError 32) and wastes CI bandwidth.
        residency_patcher = patch.object(
            server,
            "get_model_residency_settings",
            return_value={"llm": False, "stt": False, "tts": False},
        )
        residency_patcher.start()
        self.addCleanup(residency_patcher.stop)

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._orig
        self._tmp.cleanup()
        server.transcriber = None
        history_store._initialized_path = None

    def _client(self):
        return TestClient(server.app)

    def _seed_history(self):
        history_store.upsert_draft(
            {
                "id": 1,
                "created_at": "2026-01-01T00:00:00",
                "status": "sent",
                "profile": "Default",
                "raw_text": "hello world",
                "final_text": "Hello world.",
            }
        )

    def _seed_recording(self):
        audio = np.zeros(1600, dtype=np.float32)
        recording_result = types.SimpleNamespace(
            audio_data=audio,
            sample_rate=16000,
            duration_seconds=0.1,
            stop_reason="manual",
        )
        recordings.save_recording(recording_result, rec_id=str(int(time.time() * 1000)))

    def test_wipe_clears_history_db_and_recordings(self):
        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            self._seed_history()
            self._seed_recording()

            self.assertTrue(history_store.search("hello"))
            self.assertTrue(recordings.list_recordings())

            with self._client() as client:
                resp = client.post("/privacy/wipe", json={})

            self.assertEqual(resp.status_code, 200, resp.text)
            payload = resp.json()
            self.assertTrue(payload["ok"], payload)
            cleared = payload["cleared"]
            self.assertTrue(cleared["history_db_wiped"]["ok"])
            self.assertGreaterEqual(cleared["recordings_files_removed"], 1)
            self.assertTrue(payload["postconditions"]["recordings_dir_empty"])

            self.assertEqual(history_store.search("hello"), [])
            self.assertEqual(recordings.list_recordings(), [])

    def test_wipe_with_nothing_to_clear_still_ok(self):
        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with self._client() as client:
                resp = client.post("/privacy/wipe", json={})

            self.assertEqual(resp.status_code, 200, resp.text)
            payload = resp.json()
            self.assertTrue(payload["ok"], payload)
            cleared = payload["cleared"]
            self.assertTrue(cleared["history_db_wiped"]["ok"])
            self.assertEqual(cleared["recordings_files_removed"], 0)

    def test_privacy_report_lists_history_db_and_recordings(self):
        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with self._client() as client:
                resp = client.get("/privacy")

            self.assertEqual(resp.status_code, 200, resp.text)
            data = resp.json()
            names = {loc["name"] for loc in data["data_locations"]}
            self.assertIn("Searchable history (database)", names)
            self.assertIn("Raw audio recordings", names)
            self.assertTrue(data["retention"]["recordings_persisted_to_disk"])


if __name__ == "__main__":
    unittest.main()
