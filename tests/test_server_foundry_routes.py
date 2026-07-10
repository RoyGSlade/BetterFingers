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


class DummyFoundryEngine:
    """Deterministic stand-in for LLMEngine's Foundry methods — no real LLM."""

    def compile_foundry_persona(self, session):
        persona = llm_engine.normalize_persona({
            "prompt": "You are terse. Return only the rewritten text.",
            "few_shot": [{"raw": e.get("raw", ""), "out": e.get("desired", "")} for e in session.get("examples", [])],
        })
        return {"persona": persona, "warnings": []}

    def run_foundry_stress_suite(self, persona):
        return [{"category": "rambling", "input": "seed", "output": f"OUT[{persona['prompt'][:5]}]"}]


class FoundryRoutesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name
        llm_engine._personas_cache = None
        llm_engine._personas_v2_cache = None
        server.transcriber = None
        server._foundry_sessions.clear()

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._orig
        self._tmp.cleanup()
        llm_engine._personas_cache = None
        llm_engine._personas_v2_cache = None
        server.transcriber = None
        server._foundry_sessions.clear()

    def _client(self):
        return TestClient(server.app)

    def _lazy(self):
        return patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        )

    def _complete_interview(self, client, session_id):
        answers = [
            ("An executive editor for terse business emails.", None),
            ("Clarity and getting to the point fast.", None),
            ("Hedging and filler words.", None),
            ("Short declarative sentences.", None),
            ("Sharp and a little severe.", None),
            ("Never add a smiley.", None),
            ("rewrite_only", None),
            ("flexible_length", None),
            ("stay_literal", None),
            ("Just cleaner, no personality injection.", None),
            ("clean_profanity", None),
            ("sanitize", None),
        ]
        for answer, _ in answers:
            r = client.post("/personas/interview/answer", json={"session_id": session_id, "answer": answer})
            self.assertEqual(r.status_code, 200, r.text)
        for raw, desired in [("a", "b"), ("c", "d"), ("e", "f")]:
            r = client.post("/personas/interview/answer",
                             json={"session_id": session_id, "answer": {"raw": raw, "desired": desired}})
            self.assertEqual(r.status_code, 200, r.text)
        r = client.post("/personas/interview/answer", json={"session_id": session_id, "answer": {"next": True}})
        self.assertEqual(r.status_code, 200, r.text)
        r = client.post("/personas/interview/answer",
                         json={"session_id": session_id, "answer": "Would never say 'per my last email'."})
        self.assertEqual(r.status_code, 200, r.text)
        r = client.post("/personas/interview/answer", json={"session_id": session_id, "answer": {"next": True}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["done"])

    def test_start_returns_first_question(self):
        env_patch, transcriber_patch = self._lazy()
        with env_patch, transcriber_patch:
            with self._client() as client:
                resp = client.post("/personas/interview/start")
                self.assertEqual(resp.status_code, 200, resp.text)
                body = resp.json()
                self.assertIn("session_id", body)
                self.assertEqual(body["question"]["id"], "role")
                self.assertFalse(body["done"])

    def test_answer_unknown_session_404s(self):
        env_patch, transcriber_patch = self._lazy()
        with env_patch, transcriber_patch:
            with self._client() as client:
                resp = client.post("/personas/interview/answer", json={"session_id": "nope", "answer": "x"})
                self.assertEqual(resp.status_code, 404)

    def test_vague_answer_returns_pushback_and_same_question(self):
        env_patch, transcriber_patch = self._lazy()
        with env_patch, transcriber_patch:
            with self._client() as client:
                session_id = client.post("/personas/interview/start").json()["session_id"]
                resp = client.post("/personas/interview/answer", json={"session_id": session_id, "answer": "good"})
                body = resp.json()
                self.assertIsNotNone(body["pushback"])
                self.assertEqual(body["question"]["id"], "role")

    def test_full_interview_reaches_done(self):
        env_patch, transcriber_patch = self._lazy()
        with env_patch, transcriber_patch:
            with self._client() as client:
                session_id = client.post("/personas/interview/start").json()["session_id"]
                self._complete_interview(client, session_id)

    def test_compile_rejects_incomplete_session(self):
        env_patch, transcriber_patch = self._lazy()
        with env_patch, transcriber_patch:
            with self._client() as client:
                session_id = client.post("/personas/interview/start").json()["session_id"]
                resp = client.post("/personas/compile", json={"session_id": session_id})
                self.assertEqual(resp.status_code, 400)

    def test_compile_unknown_session_404s(self):
        env_patch, transcriber_patch = self._lazy()
        with env_patch, transcriber_patch:
            with self._client() as client:
                resp = client.post("/personas/compile", json={"session_id": "nope"})
                self.assertEqual(resp.status_code, 404)

    def test_compile_happy_path_returns_persona_and_warnings(self):
        env_patch, transcriber_patch = self._lazy()
        with env_patch, transcriber_patch, patch.object(
            server, "get_selected_llm_engine", return_value=DummyFoundryEngine()
        ):
            with self._client() as client:
                session_id = client.post("/personas/interview/start").json()["session_id"]
                self._complete_interview(client, session_id)
                resp = client.post("/personas/compile", json={"session_id": session_id})
                self.assertEqual(resp.status_code, 200, resp.text)
                body = resp.json()
                self.assertIn("persona", body)
                self.assertIn("warnings", body)
                self.assertEqual(len(body["persona"]["few_shot"]), 3)

    def test_compile_then_save_round_trips_through_existing_persona_route(self):
        env_patch, transcriber_patch = self._lazy()
        with env_patch, transcriber_patch, patch.object(
            server, "get_selected_llm_engine", return_value=DummyFoundryEngine()
        ):
            with self._client() as client:
                session_id = client.post("/personas/interview/start").json()["session_id"]
                self._complete_interview(client, session_id)
                compiled = client.post("/personas/compile", json={"session_id": session_id}).json()["persona"]
                save_resp = client.post("/personas", json={"name": "Foundry Test", **compiled})
                self.assertEqual(save_resp.status_code, 200, save_resp.text)
                get_resp = client.get("/personas/Foundry Test")
                self.assertEqual(get_resp.status_code, 200)
                self.assertEqual(get_resp.json()["persona_card"]["reliability_score"], compiled["persona_card"]["reliability_score"])

    def test_stress_suite_with_explicit_persona(self):
        env_patch, transcriber_patch = self._lazy()
        with env_patch, transcriber_patch, patch.object(
            server, "get_selected_llm_engine", return_value=DummyFoundryEngine()
        ):
            with self._client() as client:
                resp = client.post("/personas/test-suite/run", json={"persona": {"prompt": "Rewrite."}})
                self.assertEqual(resp.status_code, 200, resp.text)
                self.assertEqual(len(resp.json()["cases"]), 1)

    def test_stress_suite_with_session_id_compiles_first(self):
        env_patch, transcriber_patch = self._lazy()
        with env_patch, transcriber_patch, patch.object(
            server, "get_selected_llm_engine", return_value=DummyFoundryEngine()
        ):
            with self._client() as client:
                session_id = client.post("/personas/interview/start").json()["session_id"]
                self._complete_interview(client, session_id)
                resp = client.post("/personas/test-suite/run", json={"session_id": session_id})
                self.assertEqual(resp.status_code, 200, resp.text)
                self.assertEqual(len(resp.json()["cases"]), 1)

    def test_stress_suite_requires_session_id_or_persona(self):
        env_patch, transcriber_patch = self._lazy()
        with env_patch, transcriber_patch:
            with self._client() as client:
                resp = client.post("/personas/test-suite/run", json={})
                self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
