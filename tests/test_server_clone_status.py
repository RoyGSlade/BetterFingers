"""Route-behavior tests for GET /tts/clone/status.

The route just reshapes voice_clone_engine.availability() +
is_clone_runtime_provisioned() for the models/settings UI -- both are
mocked here, so no real torch/kanade_tokenizer import or filesystem probe
ever runs. Mirrors tests/test_server_wake_routes.py's minimal TestClient
pattern (no per-test APPDATA isolation needed: this route touches no
on-disk store of its own).
"""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server


class CloneStatusRouteTests(unittest.TestCase):
    def _client(self):
        return TestClient(server.app)

    def test_available_in_process_mechanism(self):
        with patch(
            "voice_clone_engine.availability",
            return_value={"available": True, "reason": "", "setup_hint": "", "mechanism": "in-process"},
        ), patch("voice_clone_engine.is_clone_runtime_provisioned", return_value=False):
            with self._client() as client:
                r = client.get("/tts/clone/status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["available"])
        self.assertEqual(body["mechanism"], "in-process")
        self.assertEqual(body["reason"], "")
        # In-process availability doesn't imply the side-runtime was ever
        # provisioned -- these are independent facts the UI needs both of.
        self.assertFalse(body["provisioned"])

    def test_unavailable_reports_reason_and_setup_hint(self):
        with patch(
            "voice_clone_engine.availability",
            return_value={
                "available": False,
                "reason": "voice-cloning dependencies not installed (kanade_tokenizer)",
                "setup_hint": "Install the voice-cloning runtime from the models page.",
                "mechanism": None,
            },
        ), patch("voice_clone_engine.is_clone_runtime_provisioned", return_value=False):
            with self._client() as client:
                r = client.get("/tts/clone/status")
        body = r.json()
        self.assertTrue(body["ok"])  # the route itself succeeded
        self.assertFalse(body["available"])
        self.assertIn("kanade_tokenizer", body["reason"])
        self.assertIn("models page", body["setup_hint"])
        self.assertIsNone(body["mechanism"])
        self.assertFalse(body["provisioned"])

    def test_side_runtime_provisioned_and_available(self):
        with patch(
            "voice_clone_engine.availability",
            return_value={"available": True, "reason": "", "setup_hint": "", "mechanism": "side-runtime"},
        ), patch("voice_clone_engine.is_clone_runtime_provisioned", return_value=True):
            with self._client() as client:
                r = client.get("/tts/clone/status")
        body = r.json()
        self.assertTrue(body["available"])
        self.assertEqual(body["mechanism"], "side-runtime")
        self.assertTrue(body["provisioned"])

    def test_provisioned_but_currently_unavailable(self):
        # A provisioned side-runtime that's since become unusable (e.g. the
        # extracted interpreter was deleted by hand) is a real, distinct
        # state the UI must be able to show -- provisioned=True doesn't
        # have to imply available=True.
        with patch(
            "voice_clone_engine.availability",
            return_value={
                "available": False,
                "reason": "side-runtime interpreter missing",
                "setup_hint": "Re-run provisioning from the models page.",
                "mechanism": None,
            },
        ), patch("voice_clone_engine.is_clone_runtime_provisioned", return_value=True):
            with self._client() as client:
                r = client.get("/tts/clone/status")
        body = r.json()
        self.assertFalse(body["available"])
        self.assertTrue(body["provisioned"])


if __name__ == "__main__":
    unittest.main()
