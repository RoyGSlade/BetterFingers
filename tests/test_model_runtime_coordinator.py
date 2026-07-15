"""Read/write lease coordinator for model runtimes (P0 runtime concurrency).

A destructive op (unload/reload/select/delete) must not drop a runtime out
from under an active inference. Inference holds a read lease; destructive ops
hold an exclusive write lease that fails fast (→ 409) while readers are active,
with an opt-in cancel-and-wait.
"""

import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import model_runtime_coordinator as mrc
import server


class CoordinatorUnitTests(unittest.TestCase):
    def test_multiple_readers_allowed(self):
        c = mrc.ModelRuntimeCoordinator()
        with c.read_lease("llm"):
            with c.read_lease("llm"):
                self.assertTrue(c.is_busy("llm"))
        self.assertFalse(c.is_busy("llm"))

    def test_write_fails_fast_while_reader_active(self):
        c = mrc.ModelRuntimeCoordinator()
        with c.read_lease("stt"):
            with self.assertRaises(mrc.RuntimeBusyError):
                with c.write_lease("stt"):  # non-blocking default
                    pass

    def test_write_succeeds_when_idle(self):
        c = mrc.ModelRuntimeCoordinator()
        with c.write_lease("tts") as rt:
            self.assertEqual(rt.state, mrc.UNLOADING)
        self.assertEqual(c._runtime("tts").state, mrc.UNLOADED)

    def test_reader_blocks_while_writer_holds(self):
        c = mrc.ModelRuntimeCoordinator()
        started = threading.Event()
        acquired = threading.Event()

        def reader():
            started.set()
            with c.read_lease("llm", timeout=2.0):
                acquired.set()

        with c.write_lease("llm"):
            t = threading.Thread(target=reader)
            t.start()
            started.wait(1)
            time.sleep(0.2)
            self.assertFalse(acquired.is_set())  # blocked by the writer
        t.join(2)
        self.assertTrue(acquired.is_set())  # proceeds once writer releases

    def test_cancel_and_wait_drains_readers(self):
        c = mrc.ModelRuntimeCoordinator()
        release = threading.Event()

        def reader():
            with c.read_lease("stt") as rt:
                while not rt.cancel_requested and not release.is_set():
                    time.sleep(0.02)

        t = threading.Thread(target=reader)
        t.start()
        time.sleep(0.1)
        # wait=True signals cancel and waits for the reader to drain.
        with c.write_lease("stt", wait=True, timeout=3.0):
            self.assertFalse(c._runtime("stt")._readers)
        t.join(2)

    def test_write_lease_failure_marks_failed_state(self):
        c = mrc.ModelRuntimeCoordinator()
        with self.assertRaises(ValueError):
            with c.write_lease("llm"):
                raise ValueError("unload blew up")
        self.assertEqual(c._runtime("llm").state, mrc.FAILED)

    def test_active_leases_reports_work(self):
        c = mrc.ModelRuntimeCoordinator()
        self.assertEqual(c.active_leases(), [])
        with c.read_lease("tts"):
            leases = c.active_leases()
            self.assertEqual(len(leases), 1)
            self.assertEqual(leases[0]["runtime"], "tts")
            self.assertEqual(leases[0]["readers"], 1)

    def test_unknown_runtime_raises(self):
        c = mrc.ModelRuntimeCoordinator()
        with self.assertRaises(KeyError):
            with c.read_lease("nope"):
                pass


class UnloadEndpoint409Tests(unittest.TestCase):
    def test_unload_returns_409_while_inference_active(self):
        client = TestClient(server.app)
        # Hold an STT read lease to simulate an in-flight transcription.
        with server.model_runtime.read_lease("stt"):
            resp = client.post("/models/unload/stt")
        self.assertEqual(resp.status_code, 409)

    def test_unload_succeeds_when_runtime_idle(self):
        client = TestClient(server.app)
        with patch.object(server, "_unload_model_component_locked",
                          return_value={"ok": True, "component": "stt", "unloaded": False}):
            resp = client.post("/models/unload/stt")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])

    def test_health_reports_runtime_leases(self):
        client = TestClient(server.app)
        with server.model_runtime.read_lease("llm"):
            payload = client.get("/health").json()
        self.assertIn("runtime_leases", payload)


class ModelResourcesEndpointTests(unittest.TestCase):
    def test_resources_endpoint_reports_ledger_and_headroom(self):
        client = TestClient(server.app)
        resp = client.get("/models/resources")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload["ok"])
        self.assertIn("ledger", payload)
        self.assertIn("pinned", payload)
        self.assertIn("available_mb", payload)
        self.assertIn("ram_floor_mb", payload)
        for component in ("stt", "llm", "tts"):
            self.assertIn(component, payload["ledger"])
            self.assertIn(component, payload["pinned"])

    def test_evictors_are_registered_for_all_components(self):
        for component in ("stt", "llm", "tts"):
            self.assertIn(component, server.model_runtime._evictors)

    def test_unload_endpoint_clears_ledger_entry(self):
        # A direct manual unload (not eviction-driven) must ALSO clear the
        # ledger — otherwise admission control would keep treating an
        # already-freed component as resident.
        client = TestClient(server.app)
        server.model_runtime.note_loaded("stt", "base.en", 300)
        self.assertIsNotNone(server.model_runtime.resources_snapshot()["ledger"]["stt"])
        try:
            resp = client.post("/models/unload/stt")
            self.assertEqual(resp.status_code, 200)
            self.assertIsNone(server.model_runtime.resources_snapshot()["ledger"]["stt"])
        finally:
            server.model_runtime.note_unloaded("stt")  # cleanup regardless of outcome


if __name__ == "__main__":
    unittest.main()
