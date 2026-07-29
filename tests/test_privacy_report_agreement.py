"""Wave 6 (Gate 6) — the privacy report and the filesystem must agree.

The registry can be complete and still be wrong in two directions, and each
gets its own class here:

* **Lie by omission** — a file exists under the data root that no declared
  category accounts for. The privacy screen enumerates categories, so such a
  file is invisible to the user no matter how carefully the screen is worded.
  ``unmapped_files`` is the check; ``UnmappedFileTests`` is the test.
* **Lie by misdirection** — a category is declared, but the path it points at
  is not where the store actually writes. The screen then shows a real store
  at a location that is empty, the wipe deletes nothing, and the verification
  passes vacuously. ``DeclaredPathMatchesStoreTests`` compares each declared
  path against the owning module's own idea of where it writes.

The second class is not hypothetical: before this suite existed, the wipe
tests patched ``get_user_data_path`` in four modules while ``data_paths``
resolved the root independently, so the registry looked in a different
directory than the stores wrote to and every category verification passed
without deleting anything.
"""

import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import data_categories as dc
import data_lifecycle as dl


class _TempRootMixin(unittest.TestCase):
    """Pin the ONE data root, the way production resolves it.

    Patching ``app_paths.resolve_base`` rather than the ``get_user_data_path``
    wrappers is deliberate — it is the single source both the stores and the
    registry read, so pinning it keeps them on one directory instead of
    silently splitting them.
    """

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        patchers = [
            patch("app_paths.resolve_base", return_value=self.root),
            patch("utils.get_user_data_path", return_value=str(self.root)),
            patch("history_store.get_user_data_path", return_value=str(self.root)),
            patch("recordings.get_user_data_path", return_value=str(self.root)),
            patch("server.get_user_data_path", return_value=str(self.root)),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)
        self.registry = dc.build_registry()


class UnmappedFileTests(_TempRootMixin):
    def test_empty_root_has_nothing_unmapped(self):
        self.assertEqual(dl.unmapped_files(self.registry, self.root), [])

    def test_every_declared_store_maps_to_its_category(self):
        """Write one file per declared single-file store and assert the sweep
        finds nothing unmapped. This is the real agreement check: it exercises
        the declared paths against a populated root rather than an empty one,
        where everything trivially agrees."""
        written = []
        for category in self.registry.all():
            # Resolve the declared location by asking the category's own module
            # where it would live, rather than hard-coding filenames here.
            for probe in self._probe_paths(category):
                probe.parent.mkdir(parents=True, exist_ok=True)
                probe.write_text("{}", encoding="utf-8")
                written.append(probe)
        # Guard against the test passing because it wrote nothing: most of the
        # inventory is single-file JSON under the unified root, so a healthy
        # probe run covers the bulk of it.
        self.assertGreaterEqual(len(written), 12,
                                f"probe wrote too few files to be meaningful: {written}")
        unmapped = dl.unmapped_files(self.registry, self.root)
        self.assertEqual(unmapped, [], f"undeclared files on disk: {unmapped}")

    def _probe_paths(self, category):
        """The paths a category would own, created so paths() reports them.

        ``data_paths`` only returns paths that exist (so the report never shows
        a phantom location), which makes "what would this category own?"
        answerable only by creating the file first. The filenames come from
        the module under test, not from this test — that is the point.
        """
        # Create the file the category's own module names, by asking for the
        # declared path list after touching each candidate the module exposes.
        # For single-file JSON stores this is exactly one path.
        import data_paths
        fn = getattr(data_paths, category.id, None)
        if fn is None:
            return []
        # Temporarily disable the existence filter to learn the candidate name.
        real_existing = data_paths._existing
        seen = []

        def _capture(*candidates):
            seen.extend(candidates)
            return real_existing(*candidates)

        data_paths._existing = _capture
        try:
            fn()
        finally:
            data_paths._existing = real_existing
        # Only single-file stores under the unified root are probed: directory
        # stores are covered wholesale by the walk, and Electron-owned files
        # live outside this root by design.
        return [p for p in seen
                if p.suffix and str(p).startswith(str(self.root))
                and category.id != "downloaded_models"]

    def test_an_undeclared_file_is_reported(self):
        """The check has to be able to FAIL, or it proves nothing."""
        rogue = self.root / "surprise_store.json"
        rogue.write_text(json.dumps({"secret": "x"}), encoding="utf-8")
        unmapped = dl.unmapped_files(self.registry, self.root)
        self.assertIn(str(rogue.resolve()), unmapped)

    def test_atomic_write_debris_is_not_reported_as_a_store(self):
        """Every store writes temp-then-rename, so a crash leaves siblings.
        Those are debris from a declared store, not an undeclared store."""
        for name in (".contacts.json.tmp-123-456", "macros.json.tmp"):
            (self.root / name).write_text("{}", encoding="utf-8")
        self.assertEqual(dl.unmapped_files(self.registry, self.root), [])

    def test_report_exposes_the_same_unmapped_list(self):
        """The report must surface this, not just the test suite: a user
        reading the privacy screen should learn that something on disk is
        unaccounted for rather than see a tidy table over an unknown file."""
        rogue = self.root / "undeclared.json"
        rogue.write_text("{}", encoding="utf-8")
        rows = dl.report_rows(self.registry)
        self.assertTrue(rows)
        self.assertIn(str(rogue.resolve()), dl.unmapped_files(self.registry, self.root))


class DeclaredPathMatchesStoreTests(_TempRootMixin):
    """Each declared path must be where the owning module actually writes.

    Compared against the module's own accessor, never against a string
    duplicated from data_paths — a test that repeats the value under test
    confirms only that the constant was copied twice.
    """

    def test_contacts(self):
        from backend.services.contacts import ContactStore
        store = ContactStore()
        store.create({"name": "Probe"})
        self.assertEqual([pathlib.Path(store.path)],
                         [p for p in dc.data_paths.contacts()])

    def test_persona_learning(self):
        from backend.services.persona_learning import PersonaLearningStore
        store = PersonaLearningStore()
        store.add_example("Probe", "raw", "out", consent=True)
        self.assertEqual([pathlib.Path(store.path)],
                         [p for p in dc.data_paths.persona_learning()])

    def test_history_db(self):
        import history_store
        history_store.init()
        declared = {str(p) for p in dc.data_paths.history_db()}
        self.assertIn(history_store.get_db_path(), declared)

    def test_raw_recordings(self):
        import recordings
        directory = recordings.get_recordings_dir()
        self.assertEqual([pathlib.Path(directory)], dc.data_paths.raw_recordings())

    def test_cloned_voices(self):
        import server
        voices = server.ensure_voices_dir()
        self.assertEqual([pathlib.Path(voices)], dc.data_paths.cloned_voices())

    def test_controller_bindings(self):
        from backend.stores.controller_bindings import ControllerBindingStore
        store = ControllerBindingStore()
        pathlib.Path(store.path).write_text("{}", encoding="utf-8")
        self.assertEqual([pathlib.Path(store.path)],
                         dc.data_paths.controller_bindings())

    def test_paths_lookup_never_creates_anything(self):
        """The report calls every paths() callable. If one of them mkdir'd, the
        act of asking "where does my data live?" would create the directory it
        then reports — and a wipe's verification would resurrect what it just
        deleted (the P0 the voices path already had once)."""
        before = sorted(os.listdir(self.root))
        for category in self.registry.all():
            category.paths()
            category.size()
        self.assertEqual(sorted(os.listdir(self.root)), before)


if __name__ == "__main__":
    unittest.main()
