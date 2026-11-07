"""Round 5, item 3 (Codex re-check 4, blocker 3), backend side: the global learned clear is an
explicit broad-scope action.

The dialog used to fall back from persona names to bare counts while the ticket bound the digest
of every example's text: a list nobody was shown. The director's decision: clearing every
persona's learned examples is a broad-scope action like the factory reset. The dialog states the
scope plainly ("All learned examples for all personas: N examples") and the ticket binds exactly
that scope: all personas, N examples. The backend verifies it under the store lock against the
count stored at that moment, so an example learned after the dialog voids the ticket.
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
from backend.services.persona_learning import PersonaLearningStore

pytestmark = pytest.mark.approvals_enforced

A = {"raw": "hey whats up", "out": "Hey, what's up?"}
B = {"raw": "ok see you", "out": "Okay, see you then."}
C = {"raw": "thanks a lot", "out": "Thank you very much."}


class GlobalLearnedClearScopeTests(unittest.TestCase):
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
        for name, item in (("Coach", A), ("Coach", B), ("Writer", C)):
            self.assertTrue(self.store.add_example(name, item["raw"], item["out"], consent=True)["ok"])

    def total(self):
        return len(self.store.list_examples("Coach")) + len(self.store.list_examples("Writer"))

    def clear(self, ticket):
        return self.client.request("DELETE", "/privacy/persona-learning", json={"approval": ticket})

    def test_the_bind_is_the_stated_scope(self):
        self.assertEqual(approvals.learned_clear_all_bind(3), {"scope": "all_personas", "example_count": "3"})

    def test_a_ticket_for_all_personas_and_the_stored_count_clears_everything(self):
        ticket = sign_ticket(approvals.PURPOSE_LEARNED_CLEAR_ALL, "all", approvals.learned_clear_all_bind(3))
        response = self.clear(ticket)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.total(), 0)

    def test_a_ticket_for_another_count_is_refused(self):
        for count in (0, 2, 4):
            ticket = sign_ticket(approvals.PURPOSE_LEARNED_CLEAR_ALL, "all", approvals.learned_clear_all_bind(count))
            with self.subTest(count=count):
                self.assertEqual(self.clear(ticket).status_code, 403)
        self.assertEqual(self.total(), 3)

    def test_an_example_learned_after_the_dialog_voids_the_ticket(self):
        ticket = sign_ticket(approvals.PURPOSE_LEARNED_CLEAR_ALL, "all", approvals.learned_clear_all_bind(3))
        self.assertTrue(self.store.add_example("Writer", A["raw"], A["out"], consent=True)["ok"])
        self.assertEqual(self.clear(ticket).status_code, 403)
        self.assertEqual(self.total(), 4)


if __name__ == "__main__":
    unittest.main()
