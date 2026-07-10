"""Job registry integration (§6.3): the dictation pipeline registers a job and
drives it to a terminal state, and the /jobs endpoints expose and cancel work."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from job_manager import JOBS, JobState


class DummyTranscriber:
    def __init__(self, *args, **kwargs):
        pass

    def transcribe(self, audio_data):
        return "raw transcript"


class DummyEngine:
    def process_fast_lane(self, text, preset, max_output_tokens=None, chunk_size=None, progress_callback=None, stitch_pass=False):
        return f"clean: {text}"


class DummyRecordingResult:
    audio_data = [0.1, 0.2, 0.3]
    sample_rate = 16000
    duration_seconds = 1.0
    frame_count = 3
    sample_count = 3
    max_amplitude = 0.2
    rms_amplitude = 0.05
    stop_reason = "manual"


class SilentRecordingResult(DummyRecordingResult):
    max_amplitude = 0.0
    rms_amplitude = 0.0
    duration_seconds = 0.05


class EmptyTranscriber(DummyTranscriber):
    def transcribe(self, audio_data):
        return ""


class DictationJobLifecycleTests(unittest.TestCase):
    def setUp(self):
        JOBS.clear()
        server._active_dictation_job_id = None
        self._lp = patch("server.load_draft_history")
        self._lp.start()
        self.addCleanup(self._lp.stop)
        self._sp = patch("server.save_draft_history")
        self._sp.start()
        self.addCleanup(self._sp.stop)

    def test_successful_dictation_completes_a_job(self):
        with patch.object(server, "Transcriber", DummyTranscriber), patch.object(
            server, "get_engine", return_value=DummyEngine()
        ), patch.object(server, "broadcast_status_threadsafe"):
            draft = server.process_recording_result(DummyRecordingResult())

        jobs = JOBS.list()
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job["kind"], "dictation")
        self.assertEqual(job["state"], JobState.COMPLETED)
        self.assertEqual(job["result_ref"], f"draft:{draft['id']}")
        self.assertIsNone(server._active_dictation_job_id)  # active pointer cleared

    def test_blocked_no_audio_still_completes_the_job(self):
        with patch.object(server, "Transcriber", EmptyTranscriber), patch.object(
            server, "get_engine", return_value=DummyEngine()
        ), patch.object(server, "broadcast_status_threadsafe"):
            draft = server.process_recording_result(SilentRecordingResult())

        self.assertEqual(draft["status"], "blocked")
        job = JOBS.list()[0]
        self.assertEqual(job["state"], JobState.COMPLETED)
        self.assertEqual(job["result_ref"], f"draft:{draft['id']}")

    def test_engine_failure_fails_the_job(self):
        class BoomEngine:
            def process_fast_lane(self, *a, **k):
                raise RuntimeError("kaboom")

        with patch.object(server, "Transcriber", DummyTranscriber), patch.object(
            server, "get_engine", return_value=BoomEngine()
        ), patch.object(server, "broadcast_status_threadsafe"), patch.object(server, "record_runtime_error"):
            server.process_recording_result(DummyRecordingResult())

        job = JOBS.list()[0]
        self.assertEqual(job["state"], JobState.FAILED)
        self.assertIn("kaboom", job["error"])


class JobEndpointTests(unittest.TestCase):
    def setUp(self):
        JOBS.clear()
        server._active_dictation_job_id = None

    def test_list_get_and_404(self):
        job = JOBS.create("tts", label="Speak")
        with TestClient(server.app) as client:
            listing = client.get("/jobs")
            self.assertEqual(listing.status_code, 200)
            self.assertEqual([j["id"] for j in listing.json()["jobs"]], [job.id])

            got = client.get(f"/jobs/{job.id}")
            self.assertEqual(got.status_code, 200)
            self.assertEqual(got.json()["job"]["kind"], "tts")

            self.assertEqual(client.get("/jobs/nope").status_code, 404)
            self.assertEqual(client.post("/jobs/nope/cancel").status_code, 404)

    def test_active_filter(self):
        a = JOBS.create("dictation")
        JOBS.complete(a.id)
        b = JOBS.create("tts")
        with TestClient(server.app) as client:
            active = client.get("/jobs", params={"active": 1}).json()["jobs"]
            self.assertEqual([j["id"] for j in active], [b.id])

    def test_cancel_active_dictation_job_trips_cancellation_event(self):
        job = JOBS.create("dictation")
        server._active_dictation_job_id = job.id
        server.cancellation_event.clear()
        try:
            with TestClient(server.app) as client:
                resp = client.post(f"/jobs/{job.id}/cancel")
            self.assertEqual(resp.status_code, 200)
            self.assertTrue(resp.json()["job"]["cancel_requested"])
            self.assertTrue(server.cancellation_event.is_set())
        finally:
            server.cancellation_event.clear()
            server._active_dictation_job_id = None

    def test_cancel_non_active_job_does_not_trip_event(self):
        job = JOBS.create("tts")
        server._active_dictation_job_id = None
        server.cancellation_event.clear()
        with TestClient(server.app) as client:
            resp = client.post(f"/jobs/{job.id}/cancel")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["job"]["cancel_requested"])
        self.assertFalse(server.cancellation_event.is_set())


if __name__ == "__main__":
    unittest.main()
