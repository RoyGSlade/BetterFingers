"""Contact CRUD + interview route tests (Stage 11b).

The route-shaped assertions are ordinary. The ones worth reading are the two
that encode design decisions the HTTP layer could quietly undo:

  * nothing persists until the user approves a compiled result, and
  * a compile with no model loaded returns the user's own answers rather than
    failing the request.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from backend.api.routes import contacts as contacts_routes
from backend.services.contacts import ContactStore


class DummyTranscriber:
    def __init__(self, profile_name="Default", preload=True):
        self.profile_name = profile_name
        self.preload = preload
        self.model = None


class ContactRoutesTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name
        server.transcriber = None
        contacts_routes._interview_sessions.clear()

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._orig
        self._tmp.cleanup()
        server.transcriber = None
        contacts_routes._interview_sessions.clear()

    def _client(self):
        return TestClient(server.app)

    def _lazy(self):
        return patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False)

    def _ctx(self):
        return self._lazy(), patch.object(server, "Transcriber", DummyTranscriber)

    # --- CRUD ---------------------------------------------------------------

    def test_create_list_get_patch_delete_round_trip(self):
        lazy, transcriber = self._ctx()
        with lazy, transcriber, self._client() as client:
            created = client.post("/contacts", json={"name": "Priya", "relationship": "my manager"})
            self.assertEqual(created.status_code, 200, created.text)
            contact = created.json()["contact"]
            cid = contact["id"]

            listed = client.get("/contacts").json()
            self.assertEqual([c["id"] for c in listed["contacts"]], [cid])

            fetched = client.get(f"/contacts/{cid}").json()
            self.assertEqual(fetched["contact"]["name"], "Priya")

            patched = client.patch(f"/contacts/{cid}", json={"tone_guidance": "Direct."})
            self.assertEqual(patched.status_code, 200, patched.text)
            self.assertEqual(patched.json()["contact"]["tone_guidance"], "Direct.")
            self.assertEqual(
                patched.json()["contact"]["relationship"], "my manager",
                "a patch must not blank fields it did not mention",
            )

            self.assertTrue(client.delete(f"/contacts/{cid}").json()["deleted"])
            self.assertEqual(client.get("/contacts").json()["contacts"], [])

    def test_update_is_reachable_by_post_as_well_as_patch(self):
        """The Electron proxy's allowlist is keyed by method and carries only
        GET/POST/DELETE, so a PATCH-only update route would be unreachable from
        the renderer."""
        lazy, transcriber = self._ctx()
        with lazy, transcriber, self._client() as client:
            cid = client.post("/contacts", json={"name": "Sam"}).json()["contact"]["id"]
            resp = client.post(f"/contacts/{cid}", json={"notes": "via post"})
            self.assertEqual(resp.status_code, 200, resp.text)
            self.assertEqual(resp.json()["contact"]["notes"], "via post")

    def test_literal_routes_are_not_shadowed_by_the_id_route(self):
        """FastAPI matches in registration order. Adding the POST alias for
        update put /contacts/{contact_id} ahead of /contacts/compile, so a
        compile request arrived as an attempt to update a contact whose id was
        the string "compile" -- and presented as a 404."""
        lazy, transcriber = self._ctx()
        with lazy, transcriber, self._client() as client:
            for literal in ("compile", "interview/start", "interview/answer", "active"):
                resp = client.post(f"/contacts/{literal}", json={"session_id": "nope"})
                self.assertNotEqual(
                    resp.json().get("detail"), "not_found",
                    f"/contacts/{literal} was swallowed by the id route",
                )

    def test_a_name_alone_creates_a_contact(self):
        lazy, transcriber = self._ctx()
        with lazy, transcriber, self._client() as client:
            resp = client.post("/contacts", json={"name": "Sam"})
            self.assertEqual(resp.status_code, 200, resp.text)

    def test_create_without_a_name_is_a_400(self):
        lazy, transcriber = self._ctx()
        with lazy, transcriber, self._client() as client:
            resp = client.post("/contacts", json={"relationship": "manager"})
            self.assertEqual(resp.status_code, 400, resp.text)

    def test_routing_details_are_dropped_and_reported(self):
        """The store has no phone/email/handle field and the route does not add
        one. A client that sends them is told, not silently obliged."""
        lazy, transcriber = self._ctx()
        with lazy, transcriber, self._client() as client:
            resp = client.post("/contacts", json={
                "name": "Sam", "email": "sam@example.com", "phone": "555",
            })
            body = resp.json()
            self.assertEqual(resp.status_code, 200, resp.text)
            self.assertEqual(body["dropped_fields"], ["email", "phone"])
            self.assertNotIn("email", body["contact"])

    def test_missing_contact_is_a_404_on_get_patch_and_delete(self):
        lazy, transcriber = self._ctx()
        with lazy, transcriber, self._client() as client:
            self.assertEqual(client.get("/contacts/nope").status_code, 404)
            self.assertEqual(client.patch("/contacts/nope", json={"notes": "x"}).status_code, 404)
            # Delete is idempotent by design, so a missing id is a success.
            self.assertEqual(client.delete("/contacts/nope").status_code, 200)

    # --- sticky selection ---------------------------------------------------

    def test_the_active_selection_round_trips(self):
        lazy, transcriber = self._ctx()
        with lazy, transcriber, self._client() as client:
            cid = client.post("/contacts", json={"name": "Priya"}).json()["contact"]["id"]

            self.assertIsNone(client.get("/contacts/active").json()["contact_id"])
            self.assertTrue(client.post("/contacts/active", json={"contact_id": cid}).json()["ok"])

            active = client.get("/contacts/active").json()
            self.assertEqual(active["contact_id"], cid)
            self.assertEqual(active["contact"]["name"], "Priya")

    def test_the_selection_can_be_cleared(self):
        """"No one in particular" is a first-class state, so clearing has to be
        as easy as choosing."""
        lazy, transcriber = self._ctx()
        with lazy, transcriber, self._client() as client:
            cid = client.post("/contacts", json={"name": "Priya"}).json()["contact"]["id"]
            client.post("/contacts/active", json={"contact_id": cid})

            client.post("/contacts/active", json={"contact_id": ""})
            self.assertIsNone(client.get("/contacts/active").json()["contact_id"])

    def test_selecting_an_unknown_contact_is_a_404(self):
        lazy, transcriber = self._ctx()
        with lazy, transcriber, self._client() as client:
            resp = client.post("/contacts/active", json={"contact_id": "nope"})
            self.assertEqual(resp.status_code, 404, resp.text)

    def test_setting_the_selection_does_not_reset_other_settings(self):
        """save_profile REPLACES the profile with what it is given, which is
        exactly why this is a route rather than a one-key write from the
        renderer: doing it client-side would reset every other setting."""
        from utils import get_last_active_profile, load_profile, save_profile

        lazy, transcriber = self._ctx()
        with lazy, transcriber, self._client() as client:
            cid = client.post("/contacts", json={"name": "Priya"}).json()["contact"]["id"]

            name = get_last_active_profile()
            profile = load_profile(name)
            profile["draft_history_limit"] = 42
            profile["instant_typing"] = True
            save_profile(name, profile)

            client.post("/contacts/active", json={"contact_id": cid})

            after = load_profile(name)
            self.assertEqual(after["draft_history_limit"], 42)
            self.assertIs(after["instant_typing"], True)
            self.assertEqual(after["active_contact_id"], cid)

    def test_a_deleted_contact_reports_as_nothing_selected(self):
        """A dangling id must not present as a broken reference: drafts that
        recorded it keep it, and the picker simply shows none."""
        lazy, transcriber = self._ctx()
        with lazy, transcriber, self._client() as client:
            cid = client.post("/contacts", json={"name": "Priya"}).json()["contact"]["id"]
            client.post("/contacts/active", json={"contact_id": cid})
            client.delete(f"/contacts/{cid}")

            active = client.get("/contacts/active").json()
            self.assertIsNone(active["contact_id"])
            self.assertIsNone(active["contact"])

    # --- interview ----------------------------------------------------------

    def test_interview_runs_to_completion_without_any_model(self):
        """Navigation is deterministic, so an interview works with nothing
        loaded -- which is what makes the design's "must not block contact
        creation" constraint satisfiable."""
        lazy, transcriber = self._ctx()
        with lazy, transcriber, self._client() as client:
            started = client.post("/contacts/interview/start").json()
            session_id = started["session_id"]
            self.assertEqual(started["question"]["id"], "name")

            answers = ["Priya", "my manager", "Direct, no filler.", "Never guess numbers.", ""]
            done = False
            for answer in answers:
                body = client.post(
                    "/contacts/interview/answer",
                    json={"session_id": session_id, "answer": answer},
                ).json()
                done = body["done"]
                self.assertIsNone(body["pushback"])
            self.assertTrue(done)
            self.assertIsNone(body["question"])

    def test_a_blank_name_is_pushed_back_on_over_http(self):
        lazy, transcriber = self._ctx()
        with lazy, transcriber, self._client() as client:
            session_id = client.post("/contacts/interview/start").json()["session_id"]
            body = client.post(
                "/contacts/interview/answer",
                json={"session_id": session_id, "answer": "  "},
            ).json()
            self.assertTrue(body["pushback"])
            self.assertEqual(body["question"]["id"], "name")

    def test_unknown_session_is_a_404(self):
        lazy, transcriber = self._ctx()
        with lazy, transcriber, self._client() as client:
            resp = client.post(
                "/contacts/interview/answer",
                json={"session_id": "nope", "answer": "x"},
            )
            self.assertEqual(resp.status_code, 404, resp.text)

    def test_compiling_an_unfinished_interview_is_a_400(self):
        lazy, transcriber = self._ctx()
        with lazy, transcriber, self._client() as client:
            session_id = client.post("/contacts/interview/start").json()["session_id"]
            resp = client.post("/contacts/compile", json={"session_id": session_id})
            self.assertEqual(resp.status_code, 400, resp.text)

    def _finish_interview(self, client):
        session_id = client.post("/contacts/interview/start").json()["session_id"]
        for answer in ["Priya", "my manager", "Direct, no filler.", "Never guess numbers.", ""]:
            client.post(
                "/contacts/interview/answer",
                json={"session_id": session_id, "answer": answer},
            )
        return session_id

    def test_compile_without_a_model_returns_the_users_own_answers(self):
        """A compile that could not reach a model must not fail the request --
        that would throw away an interview the user just sat through."""
        lazy, transcriber = self._ctx()
        with lazy, transcriber, patch.object(
            contacts_routes, "_resolve_generator", lambda _wait: None
        ), self._client() as client:
            session_id = self._finish_interview(client)
            resp = client.post("/contacts/compile", json={"session_id": session_id})

            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertFalse(body["used_model"])
            self.assertEqual(body["contact"]["name"], "Priya")
            self.assertEqual(body["contact"]["tone_guidance"], "Direct, no filler.")
            self.assertEqual(body["contact"]["notes"], "Never guess numbers.")

    def test_compile_uses_the_model_when_one_is_available(self):
        lazy, transcriber = self._ctx()
        generator = lambda _wait: (lambda _p: "TONE: Crisp and direct.\nNOTES: No guessing.")
        with lazy, transcriber, patch.object(
            contacts_routes, "_resolve_generator", generator
        ), self._client() as client:
            session_id = self._finish_interview(client)
            body = client.post("/contacts/compile", json={"session_id": session_id}).json()

            self.assertTrue(body["used_model"])
            self.assertEqual(body["contact"]["tone_guidance"], "Crisp and direct.")

    def test_compile_saves_nothing(self):
        """The interview is a conversation, not a recording. Only POST /contacts
        writes, and only with fields the user reviewed."""
        lazy, transcriber = self._ctx()
        with lazy, transcriber, patch.object(
            contacts_routes, "_resolve_generator", lambda _wait: None
        ), self._client() as client:
            session_id = self._finish_interview(client)
            client.post("/contacts/compile", json={"session_id": session_id})

            self.assertEqual(client.get("/contacts").json()["contacts"], [])
            self.assertEqual(ContactStore().count(), 0)

    def test_the_reviewed_result_is_what_gets_saved(self):
        """Every field stays editable: a wizard the user cannot overrule is a
        wizard that guesses wrong permanently."""
        lazy, transcriber = self._ctx()
        with lazy, transcriber, patch.object(
            contacts_routes, "_resolve_generator", lambda _wait: None
        ), self._client() as client:
            session_id = self._finish_interview(client)
            compiled = client.post("/contacts/compile", json={"session_id": session_id}).json()

            edited = dict(compiled["contact"])
            edited["tone_guidance"] = "Actually, warmer than that."
            saved = client.post("/contacts", json=edited).json()

            self.assertEqual(saved["contact"]["tone_guidance"], "Actually, warmer than that.")

    def test_sessions_are_capped_and_evict_oldest(self):
        lazy, transcriber = self._ctx()
        with lazy, transcriber, self._client() as client:
            first = client.post("/contacts/interview/start").json()["session_id"]
            for _ in range(contacts_routes._SESSION_CAP):
                client.post("/contacts/interview/start")

            self.assertLessEqual(
                len(contacts_routes._interview_sessions), contacts_routes._SESSION_CAP
            )
            resp = client.post(
                "/contacts/interview/answer", json={"session_id": first, "answer": "x"}
            )
            self.assertEqual(resp.status_code, 404, "the oldest session should have been evicted")


class ContactGeneratorResolutionTests(unittest.TestCase):
    """_resolve_generator decides whether a multi-gigabyte model gets booted to
    write two sentences. That decision is worth pinning."""

    def test_no_engine_means_no_generator_rather_than_an_error(self):
        with patch.object(server, "get_selected_llm_engine", side_effect=RuntimeError("nope")):
            self.assertIsNone(contacts_routes._resolve_generator(False))

    def test_an_idle_engine_is_not_booted_by_default(self):
        class _Engine:
            _ready = False

            def ensure_ready(self):
                raise AssertionError("compile must not boot the model by default")

        with patch.object(server, "get_selected_llm_engine", return_value=_Engine()), \
                patch("llm_engine.is_server_running", return_value=False):
            self.assertIsNone(contacts_routes._resolve_generator(False))

    def test_wait_for_model_boots_it(self):
        booted = []

        class _Engine:
            _ready = False

            def ensure_ready(self):
                booted.append(True)
                return True

            def process_custom_prompt(self, *_a, **_k):
                return "TONE: ok"

        with patch.object(server, "get_selected_llm_engine", return_value=_Engine()):
            generate = contacts_routes._resolve_generator(True)

        self.assertTrue(booted)
        self.assertIsNotNone(generate)

    def test_an_already_ready_engine_is_used_without_waiting(self):
        class _Engine:
            _ready = True

            def ensure_ready(self):
                raise AssertionError("an already-ready engine must not be re-booted")

            def process_custom_prompt(self, *_a, **_k):
                return "TONE: ok"

        with patch.object(server, "get_selected_llm_engine", return_value=_Engine()):
            generate = contacts_routes._resolve_generator(False)

        self.assertIsNotNone(generate)
        self.assertEqual(generate("prompt"), "TONE: ok")


if __name__ == "__main__":
    unittest.main()
