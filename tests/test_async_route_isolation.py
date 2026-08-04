"""Blocking model work must not starve the event loop (review finding #2).

A model call that blocks the FastAPI event loop makes /health unresponsive;
Electron's supervisor then restarts a backend that was merely busy, destroying
the in-flight operation. These tests prove the loop stays responsive while a
slow model call runs, and that /health reports active-job progress so the
supervisor can tell busy from dead.
"""

import threading
import time
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server


class SlowPersonaEngine:
    """Simulates CPU inference: blocks the calling thread, not the loop."""

    def __init__(self, delay=1.5):
        self.delay = delay
        self.calls = []

    def run_persona_preview(self, persona, sample, max_output_tokens=None):
        self.calls.append(sample)
        time.sleep(self.delay)
        return "previewed"


class EventLoopIsolationTests(unittest.TestCase):
    def test_health_responds_while_persona_preview_blocks(self):
        engine = SlowPersonaEngine(delay=1.5)
        client = TestClient(server.app)
        done = threading.Event()
        responses = {}

        def slow_request():
            responses["persona"] = client.post(
                "/personas/test", json={"prompt": "p", "sample": "hello"}
            )
            done.set()

        with patch.object(server, "get_selected_llm_engine", return_value=engine):
            worker = threading.Thread(target=slow_request)
            worker.start()
            # Give the slow request time to enter the engine call.
            for _ in range(50):
                if engine.calls:
                    break
                time.sleep(0.02)
            self.assertTrue(engine.calls, "slow request never reached the engine")

            t0 = time.monotonic()
            health = client.get("/health")
            elapsed = time.monotonic() - t0

            done.wait(timeout=10)
            worker.join(timeout=10)

        self.assertEqual(health.status_code, 200)
        # The loop must answer /health while inference blocks a worker thread.
        # Well under the engine delay proves it did not queue behind the call.
        self.assertLess(elapsed, 1.0)
        self.assertEqual(responses["persona"].status_code, 200)
        self.assertEqual(responses["persona"].json()["result"], "previewed")


class HealthJobVisibilityTests(unittest.TestCase):
    def test_health_reports_active_jobs_and_progress(self):
        client = TestClient(server.app)
        job = server.JOBS.create("dictation", label="Dictation")
        try:
            payload = client.get("/health").json()
            self.assertGreaterEqual(payload["active_job_count"], 1)
            ids = [j["id"] for j in payload["active_jobs"]]
            self.assertIn(job.id, ids)
            self.assertIsNotNone(payload["last_progress_at"])
        finally:
            server.JOBS.fail(job.id, "test cleanup")

    def test_health_zero_jobs_shape(self):
        client = TestClient(server.app)
        # Terminal-only registry → zero active jobs, null progress.
        payload = client.get("/health").json()
        self.assertIn("active_job_count", payload)
        self.assertIn("active_jobs", payload)
        self.assertIn("last_progress_at", payload)


class DoctorIsolationTests(unittest.TestCase):
    def test_health_responds_while_doctor_runtime_probe_blocks(self):
        entered = threading.Event()
        release = threading.Event()
        doctor_done = threading.Event()
        responses = {}

        def blocking_runtime_probe(_server_path):
            entered.set()
            self.assertTrue(release.wait(timeout=5), "probe was never released")
            return {"ok": True, "build": 1, "message": "ok"}

        with tempfile.NamedTemporaryFile() as server_file:
            with patch.object(server, "get_server_path", return_value=server_file.name), patch.object(
                server, "validate_llama_server_runtime", side_effect=blocking_runtime_probe
            ):
                client = TestClient(server.app)

                def slow_request():
                    responses["doctor"] = client.get("/doctor")
                    doctor_done.set()

                worker = threading.Thread(target=slow_request)
                worker.start()
                self.assertTrue(entered.wait(timeout=5), "doctor probe never started")

                health_started = time.monotonic()
                health = client.get("/health")
                health_elapsed = time.monotonic() - health_started

                release.set()
                self.assertTrue(doctor_done.wait(timeout=10), "doctor request did not finish")
                worker.join(timeout=10)

        self.assertEqual(health.status_code, 200)
        self.assertLess(health_elapsed, 1.0)
        self.assertEqual(responses["doctor"].status_code, 200)

    def test_doctor_never_invokes_tts_initializer(self):
        with patch.object(server, "tts_engine", None), patch.object(
            server,
            "ensure_tts_initialized",
            side_effect=AssertionError("/doctor must not initialize TTS"),
        ):
            response = TestClient(server.app).get("/doctor")

        self.assertEqual(response.status_code, 200)
        tts = response.json()["tts"]
        self.assertFalse(tts["initialized"])
        self.assertEqual(tts["status_message"], "TTS is not initialized.")

    def test_health_responds_while_doctor_tts_snapshot_blocks(self):
        entered = threading.Event()
        release = threading.Event()
        doctor_done = threading.Event()
        responses = {}

        def blocking_tts_snapshot(_engine):
            entered.set()
            self.assertTrue(release.wait(timeout=5), "TTS snapshot was never released")
            return {
                "initialized": True,
                "loaded": False,
                "backend": "none",
                "status_message": "TTS is not loaded.",
                "fallback": False,
            }

        with patch.object(server, "tts_engine", object()), patch.object(
            server, "_snapshot_tts_status", side_effect=blocking_tts_snapshot
        ):
            client = TestClient(server.app)

            def slow_request():
                responses["doctor"] = client.get("/doctor")
                doctor_done.set()

            worker = threading.Thread(target=slow_request)
            worker.start()
            self.assertTrue(entered.wait(timeout=5), "doctor TTS snapshot never started")

            health_started = time.monotonic()
            health = client.get("/health")
            health_elapsed = time.monotonic() - health_started

            release.set()
            self.assertTrue(doctor_done.wait(timeout=10), "doctor request did not finish")
            worker.join(timeout=10)

        self.assertEqual(health.status_code, 200)
        self.assertLess(health_elapsed, 1.0)
        self.assertEqual(responses["doctor"].status_code, 200)


if __name__ == "__main__":
    unittest.main()
