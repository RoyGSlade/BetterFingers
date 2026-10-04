"""Wipe vs. the leftover artifacts a versioned store leaves beside itself.

``store_migration`` writes two kinds of sibling next to every versioned store:

* ``<store>.bak-v<N>`` -- a byte-for-byte copy of the store from before a schema
  migration step (so a user who upgraded still has a v1 copy of their dictated
  examples on disk), and
* a quarantined copy of a file that would not parse (``<store>.corrupt`` or, on
  a name collision, ``<store>.<unix-ts>.corrupt``).

``data_paths`` declares both for every versioned store, so the privacy report,
the verification and the factory reset's envelope sweep all know about them.
The persona-learning and contacts wipes, however, clear through their store
APIs, and a store API only rewrites the one live file. Nothing removed the
declared siblings, which gave two failures:

* persona learning: the verification (correctly) re-read the declared
  ``.bak-v1`` / ``.corrupt*`` copies, found the user's examples, and every wipe
  mode answered an honest HTTP 500 for anyone who had been through the v1->v2
  migration -- the data could not be wiped at all;
* contacts: the verification only asked the store ``count()``, so the same
  situation answered 200 "Your data was wiped" with the contact notes still in
  ``contacts.json.corrupt*`` on disk.

These tests seed the leftovers the way the app really produces them (through
``store_migration``'s own backup/quarantine code, not by hand-naming files where
that is possible), run every wipe that covers the two stores over HTTP, and
assert both directions of the contract: the declared leftovers are gone and the
verification says so, and nothing that is NOT a declared artifact was touched.

Everything runs against throwaway directories; the conftest refuses any other
data root.
"""

import json
import os
import pathlib
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.config import store_migration
from backend.privacy import data_categories as dc
from backend.privacy import data_lifecycle as dl
from backend.privacy import data_paths
from backend.privacy import data_registry as dr
from backend.services.contacts import ContactStore
from backend.services.persona_learning import PersonaLearningStore
from backend.stores import history_store
from backend.stores.drafts import DraftStore
import server


PERSONA_SENTINEL = "zebra-persona-sentinel"
CONTACT_SENTINEL = "okapi-contact-sentinel"
DRAFT_SENTINEL = "narwhal-draft-sentinel"
STAMP = "20261004T120000Z"
CONFIRM = "DELETE EVERYTHING"


class _LeftoverRoot(unittest.TestCase):
    """A throwaway data root, pinned the way production resolves it."""

    def setUp(self):
        super().setUp()
        self._dirs = [tempfile.TemporaryDirectory() for _ in range(3)]
        for directory in self._dirs:
            self.addCleanup(directory.cleanup)
        self.root = pathlib.Path(self._dirs[0].name)
        self.electron_root = pathlib.Path(self._dirs[1].name) / "BetterFingers"
        self.electron_root.mkdir()
        self.appdata = self._dirs[2].name

        # This file deletes things. Refuse to run anywhere that is not a temp
        # directory, whatever the patches below end up resolving to.
        temp = os.path.realpath(tempfile.gettempdir())
        for path in (self.root, self.electron_root, self.appdata):
            self.assertTrue(os.path.realpath(path).startswith(temp),
                            f"{path} is not under the temp directory {temp}")

        patchers = [
            patch("backend.config.app_paths.resolve_base", return_value=self.root),
            patch("backend.config.utils.get_user_data_path", return_value=str(self.root)),
            patch("backend.stores.history_store.get_user_data_path", return_value=str(self.root)),
            patch("backend.stores.recordings.get_user_data_path", return_value=str(self.root)),
            patch("server.get_user_data_path", return_value=str(self.root)),
            patch("backend.privacy.data_paths.electron_user_data_candidates",
                  return_value=[self.electron_root]),
            # user_profile.json resolves through APPDATA on its own.
            patch.dict(os.environ, {"APPDATA": self.appdata,
                                    "BETTERFINGERS_LAZY_STARTUP": "1"}),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.assertEqual(data_paths.base(), self.root)
        self.registry = dc.build_registry()

    # --- seeding -----------------------------------------------------------

    def seed_persona_learning(self):
        """Persona-learning leftovers produced by the real store code.

        1. two truncated files, each quarantined by the store on read
           (``.corrupt``, then ``.<ts>.corrupt`` because the first name is taken);
        2. a v1 file that the first mutation migrates to v2 (``.bak-v1``).
        The ``.corrupt-<stamp>`` shape is the one the declaration documents; no
        current code writes it, so it is named by hand.
        """
        store = PersonaLearningStore()
        live = pathlib.Path(store.path)
        for n in (1, 2):
            live.write_text('{"personas": {"Coach": {"examples": [{"raw": "%s-q%d"'
                            % (PERSONA_SENTINEL, n), encoding="utf-8")
            store.list_personas()
        live.write_text(json.dumps({"personas": {"Coach": [
            {"raw": f"{PERSONA_SENTINEL}-v1-raw", "out": f"{PERSONA_SENTINEL}-v1-out"}]}}),
            encoding="utf-8")
        self.assertTrue(store.add_example("Coach", f"{PERSONA_SENTINEL} raw",
                                          f"{PERSONA_SENTINEL} out", consent=True)["ok"])
        stamped = live.with_name(live.name + f".corrupt-{STAMP}")
        stamped.write_text('{"personas": {"Coach": ' + PERSONA_SENTINEL, encoding="utf-8")
        return self._leftovers(live, stamped)

    def seed_contacts(self):
        """Contacts leftovers. Quarantine files are produced by the real store.
        ``contacts.json`` is still schema v1 with no migration, so no current
        code writes ``contacts.json.bak-v1``; the registry declares it for every
        versioned store (a future schema bump will write one), so it is named by
        hand as a plain copy of the live file."""
        store = ContactStore()
        live = pathlib.Path(store.path)
        for n in (1, 2):
            live.write_text('{"contacts": {"x": {"name": "%s-q%d"'
                            % (CONTACT_SENTINEL, n), encoding="utf-8")
            store.count()
        self.assertTrue(store.create({"name": "Priya", "notes": CONTACT_SENTINEL})["ok"])
        backup = live.with_name(live.name + ".bak-v1")
        backup.write_bytes(live.read_bytes())
        stamped = live.with_name(live.name + f".corrupt-{STAMP}")
        stamped.write_text('{"contacts": ' + CONTACT_SENTINEL, encoding="utf-8")
        return self._leftovers(live, stamped)

    def _leftovers(self, live, stamped):
        timestamped = sorted(live.parent.glob(live.name + ".*.corrupt"))
        self.assertEqual(len(timestamped), 1,
                         f"seeding should have produced one <ts>.corrupt: {timestamped}")
        leftovers = [live.with_name(live.name + ".bak-v1"),
                     live.with_name(live.name + ".corrupt"),
                     timestamped[0], stamped]
        for path in [live, *leftovers]:
            self.assertTrue(path.exists(), f"seeding did not produce {path}")
        return {"live": live, "leftovers": leftovers}

    def seed_neighbours(self):
        """Files that sit beside the stores and look a bit like their siblings
        but are not declared artifacts. The wipe has no business deleting them."""
        made = {}
        for name in ("persona_learning.json.notes", "persona_learning.json.bak",
                     "persona_learning.jsonl", "contacts.json.notes",
                     "contacts.json.bak", "contacts.jsonl"):
            path = self.root / name
            path.write_text("hand-written, not a store artifact: " + name, encoding="utf-8")
            made[path] = path.read_bytes()
        return made

    def seed_other_tiers(self):
        """Declared stores of the OTHER tiers, each with a declared sibling."""
        made = {"personal": [], "factory": []}
        for name in ("macros.json", "macros.json.bak-v1", "personas.yaml.corrupt"):
            (self.root / name).write_text("{}", encoding="utf-8")
            made["personal"].append(self.root / name)
        for name in ("voice_presets.json", "voice_presets.json.bak-v1"):
            (self.root / name).write_text("{}", encoding="utf-8")
            made["factory"].append(self.root / name)
        return made

    # --- assertions --------------------------------------------------------

    def assert_no_user_text_on_disk(self):
        leaked = []
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            blob = path.read_bytes()
            if PERSONA_SENTINEL.encode() in blob or CONTACT_SENTINEL.encode() in blob:
                leaked.append(str(path))
        self.assertEqual(leaked, [], "user text survived the wipe in: %s" % leaked)

    def assert_unchanged(self, snapshot):
        for path, blob in snapshot.items():
            self.assertTrue(path.exists(), f"{path.name} is not a declared artifact but was deleted")
            self.assertEqual(path.read_bytes(), blob, f"{path.name} was modified")

    def assert_stores_verified(self, body):
        categories = body["cleared"]["categories"]
        for cid in ("persona_learning", "contacts"):
            self.assertTrue(categories[cid]["verified"], categories[cid])
            self.assertEqual(categories[cid]["remaining"], [], categories[cid])
            self.assertTrue(body["postconditions"][f"category_{cid}_verified"])
        self.assertTrue(body["postconditions"]["persona_examples_cleared"])
        self.assertTrue(body["postconditions"]["contacts_cleared"])


class PersonaLearningWipeTests(_LeftoverRoot):
    def test_category_wipe_removes_declared_leftovers_and_verifies(self):
        persona = self.seed_persona_learning()
        contacts = self.seed_contacts()
        category = self.registry.get("persona_learning")

        wipe = category.wipe()
        verification = category.verify()

        self.assertTrue(wipe.ok, wipe)
        self.assertTrue(verification.ok, verification)
        for path in persona["leftovers"]:
            self.assertFalse(path.exists(), f"{path.name} survived the persona-learning wipe")
        # The live store is cleared through its own API, not unlinked.
        self.assertTrue(persona["live"].exists())
        self.assertEqual(PersonaLearningStore().list_personas(), [])
        # ...and the neighbouring store's artifacts are not this category's.
        for path in [contacts["live"], *contacts["leftovers"]]:
            self.assertTrue(path.exists(), f"{path.name} belongs to contacts, not persona learning")

    def test_a_leftover_that_cannot_be_removed_still_fails_the_verification(self):
        """The fix must not turn the verification into a rubber stamp: if the
        copy of the user's examples is still there, the answer is failure."""
        persona = self.seed_persona_learning()
        stuck = persona["leftovers"][0]  # .bak-v1
        real_remove = dl._remove

        def _remove(path):
            if path.name == stuck.name:
                raise OSError("device is busy")
            return real_remove(path)

        category = self.registry.get("persona_learning")
        with patch("backend.privacy.data_lifecycle._remove", _remove):
            wipe = category.wipe()
        verification = category.verify()

        self.assertFalse(wipe.ok)
        self.assertFalse(verification.ok)
        # Parsed copies are reported as "<file name>:<persona>", unparsable
        # ones as a path; either way the stuck file is named.
        self.assertTrue(any(stuck.name in entry for entry in verification.remaining),
                        verification.remaining)
        self.assertTrue(stuck.exists())
        # One stuck artifact must not stop the others from being removed.
        for path in persona["leftovers"][1:]:
            self.assertFalse(path.exists(), f"{path.name} was left behind by one stuck sibling")

    def test_delete_route_clears_persona_learning_only(self):
        persona = self.seed_persona_learning()
        contacts = self.seed_contacts()
        neighbours = self.seed_neighbours()
        with TestClient(server.app) as client:
            for path in [persona["live"], *persona["leftovers"]]:
                self.assertTrue(path.exists(), f"startup disturbed {path.name}")
            resp = client.delete("/privacy/persona-learning")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json()["ok"], resp.json())
        for path in persona["leftovers"]:
            self.assertFalse(path.exists(), f"{path.name} survived DELETE /privacy/persona-learning")
        for path in [contacts["live"], *contacts["leftovers"]]:
            self.assertTrue(path.exists(), f"{path.name} is contacts data, not persona learning")
        self.assert_unchanged(neighbours)


class ContactsWipeTests(_LeftoverRoot):
    def test_category_wipe_removes_declared_leftovers_and_verifies(self):
        contacts = self.seed_contacts()
        persona = self.seed_persona_learning()
        category = self.registry.get("contacts")

        wipe = category.wipe()
        verification = category.verify()

        self.assertTrue(wipe.ok, wipe)
        self.assertTrue(verification.ok, verification)
        for path in contacts["leftovers"]:
            self.assertFalse(path.exists(), f"{path.name} survived the contacts wipe")
        self.assertTrue(contacts["live"].exists())
        self.assertEqual(ContactStore().count(), 0)
        for path in [persona["live"], *persona["leftovers"]]:
            self.assertTrue(path.exists(), f"{path.name} belongs to persona learning, not contacts")

    def test_verification_reports_a_leftover_that_is_still_on_disk(self):
        """Before the fix this category verified through the store alone, so a
        contacts copy left in ``contacts.json.corrupt`` was invisible to it and
        the wipe reported success over user text."""
        contacts = self.seed_contacts()
        ContactStore().clear_all()  # live file is empty; only the leftovers remain
        verification = self.registry.get("contacts").verify()
        self.assertFalse(verification.ok)
        for path in contacts["leftovers"]:
            self.assertIn(str(path), verification.remaining)

    def test_a_leftover_that_cannot_be_removed_fails_the_wipe_honestly(self):
        contacts = self.seed_contacts()
        stuck = contacts["leftovers"][1]  # .corrupt
        real_remove = dl._remove

        def _remove(path):
            if path.name == stuck.name:
                raise OSError("device is busy")
            return real_remove(path)

        category = self.registry.get("contacts")
        with patch("backend.privacy.data_lifecycle._remove", _remove):
            wipe = category.wipe()
        verification = category.verify()

        self.assertFalse(wipe.ok)
        self.assertFalse(verification.ok)
        self.assertEqual(verification.remaining, [str(stuck)])
        self.assertTrue(stuck.exists())


class WipeModeLeftoverTests(_LeftoverRoot):
    """Every wipe that covers persona learning and contacts, over HTTP."""

    def _wipe_over_http(self, mode):
        persona = self.seed_persona_learning()
        contacts = self.seed_contacts()
        neighbours = self.seed_neighbours()
        tiers = self.seed_other_tiers()
        with TestClient(server.app) as client:
            for path in [persona["live"], contacts["live"],
                         *persona["leftovers"], *contacts["leftovers"], *neighbours]:
                self.assertTrue(path.exists(), f"startup disturbed {path.name}")
            resp = client.post("/privacy/wipe", json={"mode": mode})
        return resp, persona, contacts, neighbours, tiers

    def _assert_conversation_data_gone(self, resp, persona, contacts):
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(body["ok"], body)
        self.assert_stores_verified(body)
        for path in [*persona["leftovers"], *contacts["leftovers"]]:
            self.assertFalse(path.exists(), f"declared leftover {path.name} survived the wipe")
        # The live files remain as the stores' own empty envelopes.
        self.assertEqual(PersonaLearningStore().list_personas(), [])
        self.assertEqual(ContactStore().count(), 0)
        self.assert_no_user_text_on_disk()

    def test_clear_conversations_removes_leftovers_and_nothing_else(self):
        resp, persona, contacts, neighbours, tiers = self._wipe_over_http(
            dr.WIPE_MODE_CONVERSATIONS)
        self._assert_conversation_data_gone(resp, persona, contacts)
        self.assert_unchanged(neighbours)
        # Personal- and factory-tier stores, and THEIR declared siblings, are
        # outside this mode and must survive it.
        for path in [*tiers["personal"], *tiers["factory"]]:
            self.assertTrue(path.exists(), f"{path.name} is not conversation data")

    def test_clear_personal_data_removes_leftovers_and_nothing_else(self):
        resp, persona, contacts, neighbours, tiers = self._wipe_over_http(
            dr.WIPE_MODE_PERSONAL)
        self._assert_conversation_data_gone(resp, persona, contacts)
        self.assert_unchanged(neighbours)
        for path in tiers["personal"]:
            self.assertFalse(path.exists(), f"{path.name} is personal data and should be gone")
        for path in tiers["factory"]:
            self.assertTrue(path.exists(), f"{path.name} is settings, not personal data")

    def test_a_leftover_that_cannot_be_removed_makes_the_wipe_report_failure(self):
        persona = self.seed_persona_learning()
        contacts = self.seed_contacts()
        stuck = [persona["leftovers"][0], contacts["leftovers"][1]]  # persona .bak-v1, contacts .corrupt
        stuck_names = {p.name for p in stuck}
        real_remove = dl._remove

        def _remove(path):
            if path.name in stuck_names:
                raise OSError("device is busy")
            return real_remove(path)

        with patch("backend.privacy.data_lifecycle._remove", _remove), \
                TestClient(server.app) as client:
            resp = client.post("/privacy/wipe", json={"mode": dr.WIPE_MODE_CONVERSATIONS})
        self.assertEqual(resp.status_code, 500, resp.text)
        body = resp.json()
        self.assertFalse(body["ok"])
        categories = body["cleared"]["categories"]
        self.assertFalse(categories["persona_learning"]["verified"])
        self.assertFalse(categories["contacts"]["verified"])
        for path in stuck:
            self.assertTrue(path.exists())


class FactoryResetLeftoverTests(_LeftoverRoot):
    def _models(self):
        models = self.root / "models"
        models.mkdir()
        blob = models / "weights.gguf"
        blob.write_text("weights", encoding="utf-8")
        # Same names as sibling artifacts but in the wrong directory: not
        # siblings of anything, and inside the opt-in models directory.
        decoy = models / "persona_learning.json.bak-v1"
        decoy.write_text("not ours", encoding="utf-8")
        return {blob: blob.read_bytes(), decoy: decoy.read_bytes()}

    def test_factory_reset_route_removes_leftovers(self):
        persona = self.seed_persona_learning()
        contacts = self.seed_contacts()
        tiers = self.seed_other_tiers()
        models = self._models()
        with TestClient(server.app) as client:
            resp = client.post("/privacy/factory-reset", json={"confirm": CONFIRM})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(body["ok"], body)
        self.assertTrue(body["wipe"]["ok"], body["wipe"])
        self.assert_stores_verified(body["wipe"])
        self.assertTrue(body["verified"])
        self.assertEqual(body["residual_files"], [])
        for path in [persona["live"], *persona["leftovers"],
                     contacts["live"], *contacts["leftovers"],
                     *tiers["personal"], *tiers["factory"]]:
            self.assertFalse(path.exists(), f"{path.name} survived the factory reset")
        self.assert_no_user_text_on_disk()
        self.assert_unchanged(models)  # opt-in models are not part of a reset

    def test_factory_reset_does_not_widen_to_undeclared_neighbours(self):
        """A file that is not a declared artifact is left alone, and the reset
        says so (residual_files) rather than deleting it or claiming success."""
        persona = self.seed_persona_learning()
        contacts = self.seed_contacts()
        neighbours = self.seed_neighbours()
        with TestClient(server.app) as client:
            resp = client.post("/privacy/factory-reset", json={"confirm": CONFIRM})
        body = resp.json()
        self.assertEqual(resp.status_code, 500, resp.text)
        self.assertFalse(body["ok"])
        # The only reason for the failure is the undeclared files themselves.
        self.assertTrue(body["wipe"]["ok"], body["wipe"])
        self.assertEqual(body["reset"]["failed"], [])
        self.assertEqual({pathlib.Path(p).resolve() for p in body["residual_files"]},
                         {p.resolve() for p in neighbours})
        self.assert_unchanged(neighbours)
        for path in [*persona["leftovers"], *contacts["leftovers"]]:
            self.assertFalse(path.exists(), f"declared leftover {path.name} survived")

    def test_lifecycle_factory_reset_leaves_nothing_unaccounted(self):
        """The registry-level reset, without the server's quiescence layer."""
        self.seed_persona_learning()
        self.seed_contacts()
        result = dl.factory_reset(self.registry)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["residual_files"], [])
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), [])


class DraftsMigratedCopyTests(_LeftoverRoot):
    """``draft_history.json.migrated`` is the full pre-SQLite draft file.

    ``DraftStore.load_history`` renames the legacy JSON to ``.migrated`` once it
    has been copied into history.db, so after an upgrade the ONLY copy of the old
    drafts' text is that file. It was not a declared artifact of the drafts
    category: a conversations wipe never removed it and its verification (which
    re-reads the declared paths) passed over it.
    """

    def seed_migrated_drafts(self):
        """Seed through the real DraftStore migration, not by hand-naming the file."""
        live = self.root / "draft_history.json"
        live.write_text(json.dumps([{"id": 1, "raw_text": DRAFT_SENTINEL,
                                     "final_text": DRAFT_SENTINEL, "status": "pending"}]),
                        encoding="utf-8")
        with patch.object(history_store, "_initialized_path", None):
            DraftStore(lambda: str(self.root), history_store, "fake-process").load_history()
        migrated = live.with_name(live.name + ".migrated")
        self.assertTrue(migrated.exists(), "the real migration did not leave a .migrated copy")
        self.assertIn(DRAFT_SENTINEL, migrated.read_text(encoding="utf-8"))
        return migrated

    def sentinel_files(self):
        return sorted(str(p) for p in self.root.rglob("*")
                      if p.is_file() and DRAFT_SENTINEL.encode() in p.read_bytes())

    def test_migrated_copy_is_a_declared_drafts_artifact(self):
        migrated = self.seed_migrated_drafts()
        self.assertIn(migrated, data_paths.drafts())
        # The registry's category reads the same declaration, so the wipe and the
        # verification both see it.
        self.assertIn(migrated, self.registry.get("drafts").paths())

    def test_drafts_wipe_removes_migrated_copy_and_verifies(self):
        migrated = self.seed_migrated_drafts()
        category = self.registry.get("drafts")

        wipe = category.wipe()
        verification = category.verify()

        self.assertTrue(wipe.ok, wipe)
        self.assertTrue(verification.ok, verification)
        self.assertFalse(migrated.exists(), "draft_history.json.migrated survived the drafts wipe")

    def test_verification_reports_a_migrated_copy_that_is_still_on_disk(self):
        """The verification must not be a rubber stamp over the old drafts."""
        migrated = self.seed_migrated_drafts()
        real_remove = dl._remove

        def _remove(path):
            if path.name == migrated.name:
                raise OSError("device is busy")
            return real_remove(path)

        category = self.registry.get("drafts")
        with patch("backend.privacy.data_lifecycle._remove", _remove):
            wipe = category.wipe()
        verification = category.verify()

        self.assertFalse(wipe.ok)
        self.assertFalse(verification.ok)
        self.assertEqual(verification.remaining, [str(migrated)])
        self.assertTrue(migrated.exists())

    def test_verification_flags_a_migrated_copy_nothing_has_wiped(self):
        migrated = self.seed_migrated_drafts()
        verification = self.registry.get("drafts").verify()
        self.assertFalse(verification.ok)
        self.assertEqual(verification.remaining, [str(migrated)])

    def test_clear_conversations_over_http_removes_the_migrated_copy(self):
        migrated = self.seed_migrated_drafts()
        neighbour = self.root / "draft_history.json.notes"
        neighbour.write_text("hand-written, not a store artifact", encoding="utf-8")
        with TestClient(server.app) as client:
            self.assertTrue(migrated.exists(), "startup disturbed the .migrated copy")
            resp = client.post("/privacy/wipe", json={"mode": dr.WIPE_MODE_CONVERSATIONS})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(body["ok"], body)
        self.assertTrue(body["cleared"]["categories"]["drafts"]["verified"])
        self.assertTrue(body["cleared"]["history_file_removed"])
        self.assertFalse(migrated.exists(), "draft_history.json.migrated survived the wipe")
        self.assertEqual(self.sentinel_files(), [], "the old draft text survived the wipe")
        self.assertEqual(neighbour.read_text(encoding="utf-8"), "hand-written, not a store artifact")

    def test_factory_reset_leaves_no_migrated_copy(self):
        migrated = self.seed_migrated_drafts()
        result = dl.factory_reset(self.registry)
        self.assertFalse(migrated.exists(), "draft_history.json.migrated survived the factory reset")
        self.assertNotIn(str(migrated), result["residual_files"])
        self.assertEqual(self.sentinel_files(), [], "the old draft text survived the reset")

    def test_only_the_exact_migrated_name_is_declared(self):
        live = self.root / "draft_history.json"
        live.write_text("[]", encoding="utf-8")
        declared = ["draft_history.json.migrated"]
        undeclared = ["draft_history.json.migrated.txt", "draft_history.json.migrated-old",
                      "draft_history.json.premigrated", "draft_history.jsonl.migrated",
                      "draft_history.json.notes"]
        for name in declared + undeclared:
            (self.root / name).write_text("[]", encoding="utf-8")
        names = {p.name for p in data_paths.drafts()}
        for name in declared:
            self.assertIn(name, names)
        for name in undeclared:
            self.assertNotIn(name, names)


class DeclarationCoversWhatTheCodeWritesTests(_LeftoverRoot):
    """The declaration (data_paths) and the generators (the stores and
    store_migration) are two definitions of the same fact. This pins them
    together so a quarantine or backup name the code produces cannot go
    undeclared again -- which would leave it invisible to the report, outside
    every wipe, and flagged as an unknown file by a factory reset."""

    def test_draft_store_migration_copy_name_is_declared(self):
        live = self.root / "draft_history.json"
        live.write_text(json.dumps([{"id": 1, "raw_text": "x", "final_text": "x",
                                     "status": "pending"}]), encoding="utf-8")
        with patch.object(history_store, "_initialized_path", None):
            DraftStore(lambda: str(self.root), history_store, "fake-process").load_history()
        self._assert_all_siblings_declared(live, data_paths.drafts)

    def _assert_all_siblings_declared(self, live, declared_fn):
        written = sorted(p for p in live.parent.glob(live.name + ".*"))
        self.assertTrue(written, "the generators wrote nothing; the test is vacuous")
        declared = {p.name for p in declared_fn()}
        undeclared = [p.name for p in written if p.name not in declared]
        self.assertEqual(undeclared, [], f"written by the code but not declared: {undeclared}")

    def test_store_migration_backup_and_quarantine_names_are_declared(self):
        live = self.root / "persona_learning.json"
        live.write_text(json.dumps({"personas": {}}), encoding="utf-8")
        store_migration.load_versioned_store(
            str(live), 2, {1: lambda data: data}, default_factory=dict)   # .bak-v1
        for _ in range(2):
            live.write_text("{truncated", encoding="utf-8")
            store_migration.quarantine_corrupt_file(str(live))             # .corrupt, .<ts>.corrupt
        self._assert_all_siblings_declared(live, data_paths.persona_learning)

    def test_the_timestamped_quarantine_of_the_other_stores_is_declared(self):
        from backend.stores import dictionary, macros
        for module, name, declared_fn in (
                (dictionary, "dictionary.json", data_paths.dictionary),
                (macros, "macros.json", data_paths.macros)):
            live = self.root / name
            for _ in range(2):
                live.write_text("{truncated", encoding="utf-8")
                module._quarantine_corrupt_file(str(live))
            self._assert_all_siblings_declared(live, declared_fn)

    def test_only_the_exact_timestamped_quarantine_shape_is_added(self):
        """``<ts>.corrupt`` is declared; look-alikes that no code writes are not."""
        live = self.root / "persona_learning.json"
        live.write_text("{}", encoding="utf-8")
        stamp = str(int(time.time()))
        declared = [f"persona_learning.json.{stamp}.corrupt"]
        undeclared = [f"persona_learning.json.{stamp}.corrupt.txt",
                      f"persona_learning.json.v{stamp}.corrupt",
                      "persona_learning.json.old.corrupt",
                      "persona_learning.json..corrupt"]
        for name in declared + undeclared:
            (self.root / name).write_text("{}", encoding="utf-8")
        names = {p.name for p in data_paths.persona_learning()}
        for name in declared:
            self.assertIn(name, names)
        for name in undeclared:
            self.assertNotIn(name, names)


if __name__ == "__main__":
    unittest.main()
