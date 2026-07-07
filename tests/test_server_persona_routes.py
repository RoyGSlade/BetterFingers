import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
import llm_engine


class DummyTranscriber:
    def __init__(self, profile_name="Default", preload=True):
        self.profile_name = profile_name
        self.preload = preload
        self.model = None


class PersonaRoutesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name
        llm_engine._personas_cache = None
        llm_engine._personas_v2_cache = None
        server.transcriber = None

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._orig
        self._tmp.cleanup()
        llm_engine._personas_cache = None
        llm_engine._personas_v2_cache = None
        server.transcriber = None

    def _client(self):
        return TestClient(server.app)

    def test_legacy_prompt_only_post_still_works(self):
        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with self._client() as client:
                resp = client.post("/personas", json={"name": "Legacy", "prompt": "Clean it."})
                self.assertEqual(resp.status_code, 200, resp.text)

                # GET single persona returns the full v2 shape with defaults.
                got = client.get("/personas/Legacy")
                self.assertEqual(got.status_code, 200, got.text)
                data = got.json()
                self.assertEqual(data["prompt"], "Clean it.")
                self.assertIsNone(data["temperature"])
                self.assertEqual(data["voice"], {"base": "", "blend": "", "speed": 1.0})

    def test_rich_post_round_trips_through_get(self):
        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with self._client() as client:
                body = {
                    "name": "Fancy",
                    "prompt": "Rewrite.",
                    "temperature": 0.8,
                    "model_hint": "gemma-4b",
                    "format": {"caps": "sentence", "punctuation": False, "signoff": "-J"},
                    "few_shot": [{"raw": "hi", "out": "Hello."}],
                }
                resp = client.post("/personas", json=body)
                self.assertEqual(resp.status_code, 200, resp.text)

                data = client.get("/personas/Fancy").json()
                self.assertEqual(data["temperature"], 0.8)
                self.assertEqual(data["model_hint"], "gemma-4b")
                self.assertEqual(data["format"]["signoff"], "-J")
                self.assertEqual(data["few_shot"], [{"raw": "hi", "out": "Hello."}])

                # Legacy list view still returns the prompt string.
                listed = client.get("/personas").json()
                self.assertEqual(listed["Fancy"], "Rewrite.")

    def test_partial_update_preserves_rich_fields(self):
        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with self._client() as client:
                client.post("/personas", json={"name": "Keep", "prompt": "One", "temperature": 0.3})
                # Prompt-only update must not wipe the temperature.
                client.post("/personas", json={"name": "Keep", "prompt": "Two"})
                data = client.get("/personas/Keep").json()
                self.assertEqual(data["prompt"], "Two")
                self.assertEqual(data["temperature"], 0.3)

    def test_invalid_temperature_rejected(self):
        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with self._client() as client:
                resp = client.post("/personas", json={"name": "Bad", "prompt": "P", "temperature": 9})
                self.assertEqual(resp.status_code, 400)

    def test_get_missing_persona_404(self):
        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with self._client() as client:
                resp = client.get("/personas/DoesNotExist")
                self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
