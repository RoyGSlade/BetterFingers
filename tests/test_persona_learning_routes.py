import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
import llm_engine
from backend.services.persona_learning import PersonaLearningStore


class DummyTranscriber:
    def __init__(self, profile_name="Default", preload=True):
        self.profile_name = profile_name
        self.preload = preload
        self.model = None


class PersonaLearningRoutesTests(unittest.TestCase):
    """I3.3: thin explicit-consent routes over the F2.6 PersonaLearningStore."""

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

    def _lazy(self):
        return patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False)

    # --- add / consent -----------------------------------------------------

    def test_add_requires_explicit_consent(self):
        with self._lazy(), patch.object(server, "Transcriber", DummyTranscriber):
            with self._client() as client:
                resp = client.post(
                    "/personas/Coach/examples",
                    json={"raw": "hey whats up", "out": "Hey, what's up?"},
                )
                self.assertEqual(resp.status_code, 400, resp.text)
                self.assertIn("consent", resp.json()["detail"])

    def test_add_false_consent_rejected(self):
        with self._lazy(), patch.object(server, "Transcriber", DummyTranscriber):
            with self._client() as client:
                resp = client.post(
                    "/personas/Coach/examples",
                    json={"raw": "hey whats up", "out": "Hey, what's up?", "consent": False},
                )
                self.assertEqual(resp.status_code, 400, resp.text)

    def test_add_list_delete_clear_round_trip(self):
        with self._lazy(), patch.object(server, "Transcriber", DummyTranscriber):
            with self._client() as client:
                added = client.post(
                    "/personas/Coach/examples",
                    json={"raw": "hey whats up", "out": "Hey, what's up?", "consent": True},
                )
                self.assertEqual(added.status_code, 200, added.text)
                body = added.json()
                self.assertTrue(body["ok"])
                self.assertFalse(body["duplicate"])
                example_id = body["id"]

                listed = client.get("/personas/Coach/examples")
                self.assertEqual(listed.status_code, 200, listed.text)
                examples = listed.json()["examples"]
                self.assertEqual(len(examples), 1)
                self.assertEqual(examples[0]["raw"], "hey whats up")
                self.assertEqual(examples[0]["out"], "Hey, what's up?")
                self.assertEqual(examples[0]["id"], example_id)

                deleted = client.delete(f"/personas/Coach/examples/{example_id}")
                self.assertEqual(deleted.status_code, 200, deleted.text)
                self.assertTrue(deleted.json()["deleted"])

                empty = client.get("/personas/Coach/examples").json()
                self.assertEqual(empty["examples"], [])

    def test_duplicate_add_reported_not_stored_twice(self):
        with self._lazy(), patch.object(server, "Transcriber", DummyTranscriber):
            with self._client() as client:
                body = {"raw": "  hey   whats up ", "out": "Hey, what's up?", "consent": True}
                first = client.post("/personas/Coach/examples", json=body).json()
                self.assertFalse(first["duplicate"])
                # Whitespace-only variation of the same content is still a dup.
                second = client.post(
                    "/personas/Coach/examples",
                    json={"raw": "hey whats up", "out": "Hey, what's up?", "consent": True},
                ).json()
                self.assertTrue(second["duplicate"])
                self.assertEqual(second["id"], first["id"])

                examples = client.get("/personas/Coach/examples").json()["examples"]
                self.assertEqual(len(examples), 1)

    def test_delete_unknown_example_404(self):
        with self._lazy(), patch.object(server, "Transcriber", DummyTranscriber):
            with self._client() as client:
                resp = client.delete("/personas/Coach/examples/doesnotexist")
                self.assertEqual(resp.status_code, 404)

    def test_clear_persona_examples(self):
        with self._lazy(), patch.object(server, "Transcriber", DummyTranscriber):
            with self._client() as client:
                client.post(
                    "/personas/Coach/examples",
                    json={"raw": "one", "out": "One.", "consent": True},
                )
                client.post(
                    "/personas/Coach/examples",
                    json={"raw": "two", "out": "Two.", "consent": True},
                )
                cleared = client.delete("/personas/Coach/examples")
                self.assertEqual(cleared.status_code, 200, cleared.text)
                self.assertTrue(cleared.json()["cleared"])

                examples = client.get("/personas/Coach/examples").json()["examples"]
                self.assertEqual(examples, [])

                # Reversible: clearing doesn't blacklist the persona.
                relearned = client.post(
                    "/personas/Coach/examples",
                    json={"raw": "three", "out": "Three.", "consent": True},
                )
                self.assertTrue(relearned.json()["ok"])

    def test_clear_unknown_persona_is_noop_not_error(self):
        with self._lazy(), patch.object(server, "Transcriber", DummyTranscriber):
            with self._client() as client:
                resp = client.delete("/personas/NoSuchPersona/examples")
                self.assertEqual(resp.status_code, 200, resp.text)
                self.assertFalse(resp.json()["cleared"])

    # --- validation / sizing ------------------------------------------------

    def test_empty_raw_or_out_rejected(self):
        with self._lazy(), patch.object(server, "Transcriber", DummyTranscriber):
            with self._client() as client:
                resp = client.post(
                    "/personas/Coach/examples",
                    json={"raw": "", "out": "Something.", "consent": True},
                )
                self.assertEqual(resp.status_code, 422, resp.text)

    def test_oversize_example_rejected(self):
        with self._lazy(), patch.object(server, "Transcriber", DummyTranscriber):
            with self._client() as client:
                too_long = "x" * 4001
                resp = client.post(
                    "/personas/Coach/examples",
                    json={"raw": too_long, "out": "Fine.", "consent": True},
                )
                self.assertEqual(resp.status_code, 422, resp.text)

    def test_malformed_body_rejected(self):
        with self._lazy(), patch.object(server, "Transcriber", DummyTranscriber):
            with self._client() as client:
                resp = client.post("/personas/Coach/examples", json={"raw": 5, "out": None})
                self.assertEqual(resp.status_code, 422, resp.text)

    # --- unknown persona policy ---------------------------------------------

    def test_unknown_persona_name_is_opaque_key_not_rejected(self):
        # persona_learning.py's design: persona_name is an opaque key into its
        # own store, independent of llm_engine's persona registry. Learning
        # against a name that isn't a saved/built-in persona must still work.
        with self._lazy(), patch.object(server, "Transcriber", DummyTranscriber):
            with self._client() as client:
                resp = client.post(
                    "/personas/TotallyMadeUpPersonaName/examples",
                    json={"raw": "hi", "out": "Hi.", "consent": True},
                )
                self.assertEqual(resp.status_code, 200, resp.text)
                self.assertTrue(resp.json()["ok"])

    def test_list_unknown_persona_returns_empty_not_404(self):
        with self._lazy(), patch.object(server, "Transcriber", DummyTranscriber):
            with self._client() as client:
                resp = client.get("/personas/NeverLearned/examples")
                self.assertEqual(resp.status_code, 200, resp.text)
                self.assertEqual(resp.json()["examples"], [])

    # --- overflow / store cap ------------------------------------------------

    def test_overflow_evicts_oldest(self):
        with self._lazy(), patch.object(server, "Transcriber", DummyTranscriber):
            with self._client() as client:
                with patch(
                    "backend.api.routes.personas.PersonaLearningStore",
                    lambda: PersonaLearningStore(
                        path=os.path.join(self._tmp.name, "persona_learning.json"), cap=2,
                    ),
                ):
                    first = client.post(
                        "/personas/Coach/examples",
                        json={"raw": "one", "out": "One.", "consent": True},
                    ).json()
                    client.post(
                        "/personas/Coach/examples",
                        json={"raw": "two", "out": "Two.", "consent": True},
                    )
                    third = client.post(
                        "/personas/Coach/examples",
                        json={"raw": "three", "out": "Three.", "consent": True},
                    ).json()
                    self.assertEqual(third["evicted_id"], first["id"])

                    examples = client.get("/personas/Coach/examples").json()["examples"]
                    self.assertEqual(len(examples), 2)
                    self.assertEqual({e["raw"] for e in examples}, {"two", "three"})

    # --- atomic failure mapping ----------------------------------------------

    def test_write_failure_maps_to_500(self):
        with self._lazy(), patch.object(server, "Transcriber", DummyTranscriber):
            with self._client() as client:
                with patch(
                    "backend.services.persona_learning.write_atomic",
                    side_effect=OSError("disk full"),
                ):
                    resp = client.post(
                        "/personas/Coach/examples",
                        json={"raw": "hi", "out": "Hi.", "consent": True},
                    )
                    self.assertEqual(resp.status_code, 500, resp.text)

    # --- reload persistence ---------------------------------------------------

    def test_persists_across_fresh_store_instances(self):
        # Every route handler builds a fresh PersonaLearningStore per request
        # (no in-memory cache), so a "server restart" is just another request.
        with self._lazy(), patch.object(server, "Transcriber", DummyTranscriber):
            with self._client() as client:
                client.post(
                    "/personas/Coach/examples",
                    json={"raw": "hi", "out": "Hi.", "consent": True},
                )
            with self._client() as client2:
                examples = client2.get("/personas/Coach/examples").json()["examples"]
                self.assertEqual(len(examples), 1)

    # --- auth ------------------------------------------------------------------

    def test_auth_required_when_token_configured(self):
        with self._lazy(), patch.object(server, "Transcriber", DummyTranscriber):
            with self._client() as client:
                with patch.dict(os.environ, {"BETTERFINGERS_AUTH_TOKEN": "secret-token"}):
                    denied = client.get("/personas/Coach/examples")
                    self.assertEqual(denied.status_code, 401)
                    allowed = client.get(
                        "/personas/Coach/examples",
                        headers={"Authorization": "Bearer secret-token"},
                    )
                    self.assertEqual(allowed.status_code, 200)

    # --- existing persona/Foundry routes untouched -----------------------------

    def test_existing_persona_crud_routes_still_work(self):
        with self._lazy(), patch.object(server, "Transcriber", DummyTranscriber):
            with self._client() as client:
                resp = client.post("/personas", json={"name": "Legacy", "prompt": "Clean it."})
                self.assertEqual(resp.status_code, 200, resp.text)
                got = client.get("/personas/Legacy")
                self.assertEqual(got.status_code, 200, got.text)
                self.assertEqual(got.json()["prompt"], "Clean it.")


if __name__ == "__main__":
    unittest.main()
