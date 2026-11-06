"""Round 5, item 2 (Codex re-check 4, blocker 2): renaming a persona moved its examples unseen.

``POST /personas/{name}/rename`` saved the whole source entry (its approved few-shot list
included) under the new name and deleted the source, with no ticket and no native preview; the
learned examples, keyed by persona name, were neither moved nor approved, and a destination
name could already hold learned examples of its own.

Director's decision for Phase 0: renaming is OFF. The route answers 403 with one plain sentence
and changes nothing; main's approval broker and the preload expose no rename; the Studio's
rename control is hidden (app/tests/round5Approvals.test.mjs covers the app side).
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
from backend.services.persona_learning import PersonaLearningStore

pytestmark = pytest.mark.approvals_enforced

RENAME_OFF = "Renaming is turned off for now; create a new persona and copy the voice."
A = {"raw": "hey whats up", "out": "Hey, what's up?"}
B = {"raw": "ok see you", "out": "Okay, see you then."}
C = {"raw": "thanks a lot", "out": "Thank you very much."}


def pairs(items):
    return [(item["raw"], item["out"]) for item in items]


class PersonaRenameOffTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.dict(os.environ, {"APPDATA": self._tmp.name, "BETTERFINGERS_LAZY_STARTUP": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        llm_engine._personas_cache = None
        llm_engine._personas_v2_cache = None
        self.addCleanup(setattr, llm_engine, "_personas_cache", None)
        self.addCleanup(setattr, llm_engine, "_personas_v2_cache", None)
        self.client = TestClient(server.app)
        ok, msg = persona_service.save_persona("Sample", {"prompt": "You are a sample.", "few_shot": [A, B]})
        self.assertTrue(ok, msg)
        self.store = PersonaLearningStore()
        self.assertTrue(self.store.add_example("Sample", A["raw"], A["out"], consent=True)["ok"])
        # A destination name can already hold learned examples (learned routes need no persona).
        self.assertTrue(self.store.add_example("Fresh", C["raw"], C["out"], consent=True)["ok"])

    def snapshot(self):
        sample = persona_service.get_persona("Sample")
        return {
            "Sample": (sample or {}).get("few_shot"),
            "Fresh": persona_service.get_persona("Fresh"),
            "learned Sample": pairs(self.store.list_examples("Sample")),
            "learned Fresh": pairs(self.store.list_examples("Fresh")),
        }

    def test_the_codex_sequence_is_refused_and_changes_nothing(self):
        before = self.snapshot()
        self.assertEqual(before["Sample"], [A, B])
        response = self.client.post("/personas/Sample/rename", json={"new_name": "Fresh"})
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["detail"], RENAME_OFF)
        self.assertEqual(self.snapshot(), before, "the stored and learned examples are untouched")

    def test_no_ticket_of_any_purpose_turns_it_back_on(self):
        before = self.snapshot()
        for purpose in sorted(approvals.PURPOSES):
            ticket = sign_ticket(purpose, "Sample", {"to": "Fresh"})
            with self.subTest(purpose=purpose):
                response = self.client.post("/personas/Sample/rename", json={"new_name": "Fresh", "approval": ticket})
                self.assertEqual(response.status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_every_shape_of_request_is_refused_before_anything_is_read(self):
        before = self.snapshot()
        with patch.object(persona_service, "get_persona", side_effect=AssertionError("read")), \
             patch.object(persona_service, "save_persona", side_effect=AssertionError("write")), \
             patch.object(persona_service, "delete_persona", side_effect=AssertionError("delete")):
            for source, body in (("Sample", {"new_name": "Fresh"}), ("Sample", {"new_name": "Brand New"}),
                                 ("Sam!ple", {"new_name": "Fine"}), ("Missing", {"new_name": "X"}),
                                 ("True Janitor", {"new_name": "Mine"}), ("Sample", {"new_name": ""}), ("Sample", {})):
                with self.subTest(source=source, body=body):
                    response = self.client.post(f"/personas/{source}/rename", json=body)
                    self.assertEqual(response.status_code, 403, response.text)
                    self.assertEqual(response.json()["detail"], RENAME_OFF)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
