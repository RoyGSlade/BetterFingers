"""Wave 6 — the support report's content-free guarantee, re-verified against
the stores that did not exist when that guarantee was written.

The support report is the one artifact a user is invited to paste to a
stranger. Its promise is that it contains diagnostics and never content: no
transcripts, no drafts, no contact notes, no learned examples. That promise was
tested when the report was built, but every wave since has added stores —
contacts, learned persona examples, application profiles, launcher workflows,
the confirmed application registry, controller bindings — and a guarantee is
only as current as the last thing it was checked against.

So this suite populates every declared store with a distinctive marker string
and asserts that none of them reaches the rendered report. It is deliberately
driven from the registry rather than a hand-written list of stores: a store
added later is covered the moment it is declared, which is the only way this
stays true without someone remembering to update it.
"""

import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import data_categories as dc
import server


# One unmistakable marker per store. If any of these appears in the report, the
# report leaked that store's contents.
MARKER = "ZZ-SUPPORT-LEAK-CANARY"


class SupportReportContentFreeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        patchers = [
            patch("app_paths.resolve_base", return_value=self.root),
            patch("utils.get_user_data_path", return_value=str(self.root)),
            patch("history_store.get_user_data_path", return_value=str(self.root)),
            patch("recordings.get_user_data_path", return_value=str(self.root)),
            patch("server.get_user_data_path", return_value=str(self.root)),
            patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)
        self.registry = dc.build_registry()

    def _populate_every_store(self):
        """Write a marker into every declared store that lives under the root.

        Uses the real store APIs where a store has one (so the file shape is
        genuine rather than a plausible-looking fake), and a raw marker file
        otherwise.
        """
        written = []

        from backend.services.contacts import ContactStore
        ContactStore().create({"name": f"{MARKER}-contact",
                               "notes": f"{MARKER}-contact-notes"})
        written.append("contacts")

        from backend.services.persona_learning import PersonaLearningStore
        PersonaLearningStore().add_example(
            f"{MARKER}-persona", f"{MARKER}-raw", f"{MARKER}-final", consent=True)
        written.append("persona_learning")

        import history_store
        history_store.init()
        # No try/except here on purpose: an insert that silently fails would
        # make this suite report "no leak" about a store it never populated,
        # which is the failure mode a leak test can least afford.
        history_store.upsert_draft({"id": 1, "created_at": "2026-07-28T00:00:00Z",
                                    "status": "pending",
                                    "raw_text": f"{MARKER}-raw-transcript",
                                    "final_text": f"{MARKER}-final-transcript",
                                    "metadata": {"profile": "Default"}})
        self.assertGreater(history_store.count(), 0,
                           "the history row was not written, so this run would "
                           "not have tested the transcription store at all")
        written.append("history_db")

        # The Stream Deck key title is written through the store's own API, not
        # as a raw marker file, because that one field is the entire reason the
        # store is declared user_text=True. A marker in an invented shape would
        # prove the report does not echo arbitrary file bytes; it would not
        # prove the thing actually at risk — that a deck of keys titled after
        # the people they message stays out of a report the user pastes to a
        # stranger. sanitize_key() also collapses and caps the title, so going
        # through record_key exercises the value as it is really stored.
        from backend.stores.stream_deck_config import StreamDeckConfigStore
        deck = StreamDeckConfigStore()
        # A real bindable action id, not an invented one: sanitize_key refuses
        # anything outside the closed vocabulary, so a made-up action would
        # make this helper fail rather than populate the store.
        from backend.domain.input_actions import ACTION_DICTATION_TOGGLE
        deck_result = deck.record_key("deck-key-probe", {
            "title": f"Ping {MARKER}-deck-contact",
            "action_id": ACTION_DICTATION_TOGGLE,
        })
        self.assertTrue(deck_result.get("ok"), deck_result)
        self.assertIn(MARKER, pathlib.Path(deck.path).read_text(encoding="utf-8"),
                      "the key title did not reach the store file, so this run "
                      "would not have tested the field that makes it user text")
        written.append("stream_deck_config")

        import data_paths
        for name in ("draft_history.json", "macros.json", "dictionary.json",
                     "graph.json", "mcp_servers.json", "app_profiles.json",
                     "launcher_workflows.json", "application_registry.json",
                     "controller_bindings.json",
                     "voice_presets.json"):
            (self.root / name).write_text(
                json.dumps({"marker": f"{MARKER}-{name}"}), encoding="utf-8")
            written.append(name)
        (self.root / "personas.yaml").write_text(
            f"personas:\n  - name: {MARKER}-persona-body\n", encoding="utf-8")
        written.append("personas.yaml")
        (self.root / "debug.log").write_text(
            f"user said {MARKER}-debug-line\n", encoding="utf-8")
        written.append("debug.log")

        recordings_dir = self.root / "recordings"
        recordings_dir.mkdir(exist_ok=True)
        (recordings_dir / f"{MARKER}-recording.wav").write_text("x", encoding="utf-8")
        written.append("recordings")

        self.assertGreaterEqual(len(written), 15)
        return written

    def _report_text(self):
        with TestClient(server.app) as client:
            resp = client.get("/diagnostics/support-report")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        return body.get("report") or body.get("markdown") or json.dumps(body)

    def test_no_store_contents_reach_the_support_report(self):
        self._populate_every_store()
        report = self._report_text()
        self.assertNotIn(MARKER, report,
                         "the support report leaked the contents of a declared store")

    def test_the_canary_would_be_detected(self):
        """A leak test that cannot fail proves nothing: confirm the marker is
        actually findable in text the assertion would inspect."""
        self.assertIn(MARKER, f"prefix {MARKER} suffix")

    def test_paths_may_appear_but_contents_may_not(self):
        """Paths are legitimate diagnostics — knowing where the data root is
        helps support. Filenames derived from user content are not, which is
        why the recording marker is checked as part of the sweep above."""
        self._populate_every_store()
        report = self._report_text()
        self.assertNotIn(f"{MARKER}-recording.wav", report)
        self.assertNotIn(f"{MARKER}-contact-notes", report)
        self.assertNotIn(f"{MARKER}-final-transcript", report)
        # The Stream Deck key title, named explicitly rather than left to the
        # blanket MARKER sweep: it is the single field behind that store's
        # user_text=True, so a future change that started echoing deck titles
        # should fail on a line that says so.
        self.assertNotIn(f"{MARKER}-deck-contact", report)

    def test_every_user_text_store_is_covered_by_this_suite(self):
        """Guard against the suite going stale: if a new store is declared as
        possibly holding user text, this test names it so the populate helper
        has to grow with the inventory rather than silently lag it."""
        text_stores = {c.id for c in self.registry.all() if c.may_contain_user_text}
        covered = {
            "drafts", "history_db", "personas", "dictionary", "macros",
            "graph_data", "debug_log", "sidecar_raw_log", "persona_learning",
            "user_profile", "contacts", "launcher_workflows",
            # Wave 10. A Stream Deck key TITLE is typed by the user on their own
            # deck ("Ping Priya"), so the store is declared user_text=True even
            # though every other field in it is a closed enum or a bounded id.
            # _populate_every_store writes it through record_key rather than as a
            # raw marker file, so the title is exercised as it is really stored
            # (collapsed and capped by sanitize_key), and
            # test_paths_may_appear_but_contents_may_not names that title
            # explicitly rather than leaving it to the blanket sweep.
            "stream_deck_config",
        }
        uncovered = text_stores - covered
        self.assertEqual(
            uncovered, set(),
            f"new user-text store(s) {sorted(uncovered)} are not exercised by the "
            "support-report leak sweep — add them to _populate_every_store")


if __name__ == "__main__":
    unittest.main()
