"""Round 4, items 3 and 5 (Codex re-check 3, findings 3 and 6): every example change needs a tap.

Finding 3: clearing one persona's learned examples took only ``?confirm=true``; the global
learning wipe took nothing at all (the renderer's boolean was checked in main, which a
compromised renderer supplies itself); deleting a custom persona removed its whole few-shot
list with no ticket; and the privacy wipes and the factory reset (which also delete learned
examples and personas) took only a renderer boolean or a typed phrase.

Finding 6: an approved learned example could silently EVICT another one when the store was at
its cap, because the ticket covered only the added pair.

Now each of these transitions needs a ticket minted by main after a native dialog that showed
its scope, bound to the complete list or collection it replaces, and verified together with the
commit under the store lock.
"""
import os
import tempfile
import unittest
from unittest.mock import patch

import pytest
from approval_support import sign_ticket
from fastapi.testclient import TestClient

import server
from backend.llm import llm_engine
from backend.services import approvals
from backend.services import personas as persona_service
from backend.services import persona_learning
from backend.services.persona_learning import PersonaLearningStore

pytestmark = pytest.mark.approvals_enforced

A = {"raw": "hey whats up", "out": "Hey, what's up?"}
B = {"raw": "ok see you", "out": "Okay, see you then."}
C = {"raw": "thanks a lot", "out": "Thank you very much."}
FORGED = {"payload": "forged", "sig": "0" * 64}


def pairs(items):
    return [(item["raw"], item["out"]) for item in items]


class _Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.dict(os.environ, {"APPDATA": self._tmp.name, "BETTERFINGERS_LAZY_STARTUP": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        llm_engine._personas_cache = None
        llm_engine._personas_v2_cache = None
        self.client = TestClient(server.app)
        self.store = PersonaLearningStore()
        for item in (A, B):
            self.assertTrue(self.store.add_example("Coach", item["raw"], item["out"], consent=True)["ok"])
        self.assertTrue(self.store.add_example("Writer", C["raw"], C["out"], consent=True)["ok"])

    def tearDown(self):
        llm_engine._personas_cache = None
        llm_engine._personas_v2_cache = None

    def learned(self, name="Coach"):
        return pairs(self.store.list_examples(name))


class ClearOnePersonaTests(_Case):
    def clear(self, approval=None, query="?confirm=true"):
        body = {"approval": approval} if approval is not None else None
        return self.client.request("DELETE", f"/personas/Coach/examples{query}", json=body)

    def ticket(self, before):
        return sign_ticket(approvals.PURPOSE_PERSONA_LEARNED_CLEAR, "Coach", approvals.learned_clear_bind("Coach", before))

    def test_a_confirm_flag_is_not_a_tap(self):
        for approval in (None, FORGED):
            self.assertEqual(self.clear(approval).status_code, 403)
        self.assertEqual(len(self.learned()), 2)

    def test_a_ticket_bound_to_the_stored_list_clears_exactly_that_persona(self):
        response = self.clear(self.ticket(self.learned()), query="")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.learned(), [])
        self.assertEqual(self.learned("Writer"), pairs([C]), "other personas are untouched")

    def test_a_ticket_against_a_list_that_changed_is_refused(self):
        ticket = self.ticket(self.learned())
        self.store.add_example("Coach", C["raw"], C["out"], consent=True)
        self.assertEqual(self.clear(ticket).status_code, 403)
        self.assertEqual(len(self.learned()), 3)


class ClearEveryPersonaTests(_Case):
    def test_the_global_learning_wipe_needs_a_ticket(self):
        for approval in (None, FORGED):
            body = {"approval": approval} if approval is not None else None
            self.assertEqual(self.client.request("DELETE", "/privacy/persona-learning", json=body).status_code, 403)
        self.assertEqual(len(self.learned()), 2)

    def test_a_ticket_bound_to_the_whole_collection_clears_it(self):
        collection = approvals.learned_collection_digest(persona_learning.snapshot(self.store))
        ticket = sign_ticket(approvals.PURPOSE_LEARNED_CLEAR_ALL, "all", approvals.learned_clear_all_bind(collection))
        response = self.client.request("DELETE", "/privacy/persona-learning", json={"approval": ticket})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.learned(), [])
        self.assertEqual(self.learned("Writer"), [])

    def test_a_collection_that_changed_since_the_dialog_voids_the_ticket(self):
        collection = approvals.learned_collection_digest(persona_learning.snapshot(self.store))
        ticket = sign_ticket(approvals.PURPOSE_LEARNED_CLEAR_ALL, "all", approvals.learned_clear_all_bind(collection))
        self.store.add_example("Writer", A["raw"], A["out"], consent=True)
        self.assertEqual(self.client.request("DELETE", "/privacy/persona-learning", json={"approval": ticket}).status_code, 403)
        self.assertEqual(len(self.learned("Writer")), 2)


class DeletePersonaTests(_Case):
    def setUp(self):
        super().setUp()
        ok, msg = persona_service.save_persona("Custom", {"prompt": "p", "few_shot": [A, B]})
        self.assertTrue(ok, msg)

    def test_deleting_a_persona_with_examples_needs_a_ticket(self):
        for approval in (None, FORGED):
            body = {"approval": approval} if approval is not None else None
            self.assertEqual(self.client.request("DELETE", "/personas/Custom", json=body).status_code, 403)
        self.assertIsNotNone(persona_service.get_persona("Custom"))

    def test_a_ticket_bound_to_its_list_deletes_it(self):
        ticket = sign_ticket(approvals.PURPOSE_PERSONA_DELETE, "Custom", approvals.persona_delete_bind("Custom", pairs([A, B])))
        response = self.client.request("DELETE", "/personas/Custom", json={"approval": ticket})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(persona_service.get_persona("Custom"))

    def test_a_ticket_for_a_different_list_does_not(self):
        ticket = sign_ticket(approvals.PURPOSE_PERSONA_DELETE, "Custom", approvals.persona_delete_bind("Custom", pairs([A])))
        self.assertEqual(self.client.request("DELETE", "/personas/Custom", json={"approval": ticket}).status_code, 403)
        self.assertIsNotNone(persona_service.get_persona("Custom"))


class PrivacyWipeTests(_Case):
    def scope(self, mode):
        registry = server.data_categories.get_registry()
        return [category.id for category in registry.in_mode(mode)]

    def test_every_wipe_mode_needs_a_ticket_bound_to_its_scope(self):
        with patch.object(server, "_perform_privacy_wipe", return_value={"ok": True}) as wipe:
            for mode in ("clear_conversations", "clear_personal_data"):
                for approval in (None, FORGED):
                    body = {"mode": mode, "wipe_voices": False}
                    if approval is not None:
                        body["approval"] = approval
                    self.assertEqual(self.client.post("/privacy/wipe", json=body).status_code, 403, mode)
            wipe.assert_not_called()

    def test_a_ticket_for_the_exact_mode_and_options_runs_it(self):
        mode = "clear_conversations"
        ticket = sign_ticket(approvals.PURPOSE_PRIVACY_WIPE, mode,
                             approvals.privacy_wipe_bind(mode, self.scope(mode), wipe_voices=False))
        wrong_voices = sign_ticket(approvals.PURPOSE_PRIVACY_WIPE, mode,
                                   approvals.privacy_wipe_bind(mode, self.scope(mode), wipe_voices=True))
        with patch.object(server, "_perform_privacy_wipe", return_value={"ok": True}) as wipe:
            self.assertEqual(self.client.post("/privacy/wipe", json={"mode": mode, "approval": wrong_voices}).status_code, 403)
            response = self.client.post("/privacy/wipe", json={"mode": mode, "approval": ticket})
            self.assertEqual(response.status_code, 200, response.text)
            wipe.assert_called_once()

    def test_the_factory_reset_needs_the_phrase_and_a_ticket(self):
        phrase = server.FACTORY_RESET_CONFIRMATION
        with patch.object(server, "_perform_factory_reset", return_value={"ok": True}) as reset:
            self.assertEqual(self.client.post("/privacy/factory-reset", json={"confirm": phrase}).status_code, 403)
            ticket = sign_ticket(approvals.PURPOSE_PRIVACY_WIPE, "factory_reset",
                                 approvals.privacy_wipe_bind("factory_reset", self.scope("factory_reset"), delete_models=False))
            self.assertEqual(self.client.post("/privacy/factory-reset", json={"confirm": "nope", "approval": ticket}).status_code, 400)
            reset.assert_not_called()
            ticket = sign_ticket(approvals.PURPOSE_PRIVACY_WIPE, "factory_reset",
                                 approvals.privacy_wipe_bind("factory_reset", self.scope("factory_reset"), delete_models=False))
            response = self.client.post("/privacy/factory-reset", json={"confirm": phrase, "approval": ticket})
            self.assertEqual(response.status_code, 200, response.text)
            reset.assert_called_once()


class LearnedEvictionTests(unittest.TestCase):
    """Finding 6: at the cap, an approved addition evicted the oldest example unseen."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = PersonaLearningStore(path=os.path.join(self._tmp.name, "learning.json"), cap=2)
        for item in (A, B):
            self.assertTrue(self.store.add_example("Coach", item["raw"], item["out"], consent=True)["ok"])

    def test_the_plan_shows_the_complete_result_including_the_evicted_example(self):
        plan = self.store.plan_add("Coach", C["raw"], C["out"])
        self.assertEqual(plan["before"], pairs([A, B]))
        self.assertEqual(plan["after"], pairs([B, C]))
        self.assertEqual([(e["raw"], e["out"]) for e in plan["evicted"]], pairs([A]))

    def test_the_commit_refuses_when_the_list_no_longer_matches_what_was_approved(self):
        plan = self.store.plan_add("Coach", C["raw"], C["out"])
        self.store.delete_example("Coach", self.store.list_examples("Coach")[1]["id"])  # changed meanwhile
        result = self.store.add_example("Coach", C["raw"], C["out"], consent=True,
                                        expect=(plan["before"], plan["after"]))
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "changed")
        self.assertEqual(pairs(self.store.list_examples("Coach")), pairs([A]))


class LearnedAddRouteTests(_Case):
    def test_a_ticket_for_only_the_added_pair_no_longer_suffices(self):
        old_style = sign_ticket(approvals.PURPOSE_PERSONA_EXAMPLE, "Coach", approvals.persona_example_bind("Coach", C["raw"], C["out"]))
        response = self.client.post("/personas/Coach/examples", json={**C, "approval": old_style})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(self.learned()), 2)

    def test_a_ticket_bound_to_the_complete_resulting_list_adds_it(self):
        preview = self.client.post("/personas/Coach/examples/preview", json=C)
        self.assertEqual(preview.status_code, 200, preview.text)
        plan = preview.json()
        before = [tuple(p) for p in plan["before"]]
        after = [tuple(p) for p in plan["after"]]
        ticket = sign_ticket(approvals.PURPOSE_PERSONA_EXAMPLE, "Coach",
                             approvals.learned_add_bind("Coach", C["raw"], C["out"], before, after))
        response = self.client.post("/personas/Coach/examples", json={**C, "approval": ticket})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.learned(), pairs([A, B, C]))


if __name__ == "__main__":
    unittest.main()
