"""Blocking model work must not starve the event loop (review finding #2).

A model call that blocks the FastAPI event loop makes /health unresponsive;
Electron's supervisor then restarts a backend that was merely busy, destroying
the in-flight operation. These tests prove the loop stays responsive while a
slow model call runs, and that /health reports active-job progress so the
supervisor can tell busy from dead.
"""

import threading
import time
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


if __name__ == "__main__":
    unittest.main()
