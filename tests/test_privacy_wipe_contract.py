"""Phase 1.1 remediation — the /privacy/wipe HTTP contract.

`_perform_privacy_wipe` already returns a truthful structured result. These
tests pin the *route* behavior: a wipe that did not fully succeed must never
return HTTP 200, and the structured payload must be preserved unchanged.

Definition of done (Phase 1.3): no backend-declared wipe failure can produce a
success at the HTTP layer.
"""

import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server


class WipeStatusMappingTests(unittest.TestCase):
    """The pure result->status mapping, in isolation."""

    def test_ok_is_200(self):
        self.assertEqual(server._wipe_status_code({"ok": True}), 200)

    def test_already_running_is_409(self):
        self.assertEqual(
            server._wipe_status_code({"ok": False, "error": "wipe_already_running"}), 409)

    def test_pipeline_stall_is_409(self):
        self.assertEqual(
            server._wipe_status_code({"ok": False, "error": "pipeline_did_not_quiesce"}), 409)

    def test_output_stall_is_503(self):
        self.assertEqual(
            server._wipe_status_code({"ok": False, "error": "output_did_not_quiesce"}), 503)

    def test_postcondition_failure_is_500(self):
        # ok False with no recognized pre-deletion abort code == deletion ran
        # but a postcondition did not hold.
        self.assertEqual(
            server._wipe_status_code({"ok": False, "postconditions": {"x": False}}), 500)
        self.assertEqual(
            server._wipe_status_code({"ok": False, "error": "unrecognized"}), 500)


class WipeRouteContractTests(unittest.TestCase):
    """The route wires the mapping in and preserves the payload."""

    def setUp(self):
        self.client = TestClient(server.app)

    def _post_with_result(self, canned):
        with patch.object(server, "_perform_privacy_wipe", return_value=canned):
            return self.client.post("/privacy/wipe", json={"wipe_voices": False})

    def test_success_returns_200_and_payload(self):
        canned = {"ok": True, "cleared": {"drafts": 0}, "postconditions": {"draft_queue_empty": True},
                  "message": "Your data was wiped."}
        resp = self._post_with_result(canned)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), canned)

    def test_already_running_returns_409(self):
        resp = self._post_with_result(
            {"ok": False, "error": "wipe_already_running", "message": "A privacy wipe is already in progress."})
        self.assertEqual(resp.status_code, 409)
        self.assertFalse(resp.json()["ok"])
        self.assertEqual(resp.json()["error"], "wipe_already_running")

    def test_pipeline_did_not_quiesce_returns_409(self):
        resp = self._post_with_result(
            {"ok": False, "error": "pipeline_did_not_quiesce", "cleared": {}, "postconditions": {}})
        self.assertEqual(resp.status_code, 409)

    def test_output_did_not_quiesce_returns_503(self):
        resp = self._post_with_result(
            {"ok": False, "error": "output_did_not_quiesce", "cleared": {}, "postconditions": {},
             "stuck_sends": ["s1"]})
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["stuck_sends"], ["s1"])

    def test_postcondition_failure_returns_500(self):
        resp = self._post_with_result(
            {"ok": False, "cleared": {"drafts": 1},
             "postconditions": {"recordings_dir_empty": False, "leftover_recordings": ["stubborn.wav"]},
             "message": "Wipe finished with leftovers — see postconditions. Data may remain."})
        self.assertEqual(resp.status_code, 500)
        self.assertIn("stubborn.wav", resp.json()["postconditions"]["leftover_recordings"])

    def test_no_failure_ever_returns_200(self):
        # The core guarantee: iterate every failing shape, none may be 200.
        for canned in (
            {"ok": False, "error": "wipe_already_running"},
            {"ok": False, "error": "pipeline_did_not_quiesce"},
            {"ok": False, "error": "output_did_not_quiesce"},
            {"ok": False, "postconditions": {"history_db_wiped": False}},
        ):
            with self.subTest(canned=canned):
                self.assertNotEqual(self._post_with_result(canned).status_code, 200)


class WipeRouteIntegrationTests(unittest.TestCase):
    """A real wipe against a throwaway data dir returns 200 through the route."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        patchers = [
            patch("recordings.get_user_data_path", return_value=self._tmp.name),
            patch("history_store.get_user_data_path", return_value=self._tmp.name),
            patch("server.get_user_data_path", return_value=self._tmp.name),
            # PersonaLearningStore resolves its path via utils.get_user_data_path
            # directly, not a server.py-bound copy -- see test_privacy_wipe_verified.py.
            patch("utils.get_user_data_path", return_value=self._tmp.name),
            patch.object(server, "save_draft_history"),
            patch.object(server, "broadcast_status_threadsafe"),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)
        server.draft_queue.clear()
        server.draft_recordings.clear()
        server.pending_manual_send_ids.clear()
        self.addCleanup(server.draft_queue.clear)
        self.client = TestClient(server.app)

    def test_empty_wipe_is_200_and_ok(self):
        import history_store
        history_store.init()
        resp = self.client.post("/privacy/wipe", json={"wipe_voices": False})
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertTrue(resp.json()["ok"])

    def test_populated_wipe_is_200_and_ok(self):
        import os
        import history_store
        history_store.init()
        directory = server.recordings.get_recordings_dir()
        with open(os.path.join(directory, "orphan.wav"), "w") as fh:
            fh.write("x")
        with server.draft_lock:
            server.draft_queue.append({"id": 1, "final_text": "secret"})
        resp = self.client.post("/privacy/wipe", json={"wipe_voices": False})
        self.assertEqual(resp.status_code, 200, resp.json())
        self.assertTrue(resp.json()["ok"])
        self.assertTrue(resp.json()["postconditions"]["recordings_dir_empty"])

    def test_history_db_recreation_failure_returns_500(self):
        # Failure injection (Phase 1.3): the DB could not be wiped/recreated.
        import history_store
        history_store.init()
        with patch.object(server.history_store, "wipe_database",
                          return_value={"ok": False, "recreated": False, "removed": []}):
            resp = self.client.post("/privacy/wipe", json={"wipe_voices": False})
        self.assertEqual(resp.status_code, 500, resp.json())
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertFalse(body["postconditions"]["history_db_recreated"])

    def test_voice_deletion_failure_returns_500(self):
        # Failure injection (Phase 1.3): rmtree silently no-ops, so the voices
        # dir remains and the voices_absent postcondition cannot hold.
        import os
        import history_store
        history_store.init()
        voices_dir = server.ensure_voices_dir()
        with open(os.path.join(str(voices_dir), "cloned_Me.wav"), "w") as fh:
            fh.write("x")
        with patch.object(server.shutil, "rmtree", lambda *a, **k: None):
            resp = self.client.post("/privacy/wipe", json={"wipe_voices": True})
        self.assertEqual(resp.status_code, 500, resp.json())
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertFalse(body["postconditions"]["voices_absent"])


if __name__ == "__main__":
    unittest.main()
