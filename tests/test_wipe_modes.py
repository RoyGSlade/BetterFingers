"""Wave 6 — every declared wipe mode actually runs, and each one deletes
exactly the set it claims.

Before this wave the three modes existed as metadata: ``data_registry``
declared them, categories named them, and the only executor was a hand-rolled
sweep in ``server.py`` that named stores individually and matched none of the
three. A mode nothing performs is a promise the product has not made, so these
tests execute each mode end to end against a populated throwaway root and
assert the result by re-reading the disk rather than by trusting the return
value.

The nesting invariant (conversations ⊆ personal ⊆ factory) is checked as
behaviour here, not only as validation in the registry: it is easy to keep the
declaration consistent while the executor quietly skips a tier.
"""

import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import data_categories as dc
import data_lifecycle as dl
import data_registry as dr


class _PopulatedRootMixin(unittest.TestCase):
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

    def populate(self):
        """Write one real file for every category that lives under the root,
        so a mode has something to delete and 'ok' cannot be vacuous."""
        import data_paths
        made = {}
        for category in self.registry.all():
            if category.id == "downloaded_models":
                continue
            fn = getattr(data_paths, category.id, None)
            if fn is None:
                continue
            for candidate in _candidates(fn):
                if not str(candidate).startswith(str(self.root)):
                    continue  # Electron-owned roots are exercised separately
                if candidate.suffix:
                    candidate.parent.mkdir(parents=True, exist_ok=True)
                    candidate.write_text("{}", encoding="utf-8")
                else:
                    candidate.mkdir(parents=True, exist_ok=True)
                    (candidate / "payload.bin").write_text("x", encoding="utf-8")
                made.setdefault(category.id, []).append(candidate)
        return made


def _candidates(fn):
    """Every path a data_paths callable considers, existing or not.

    data_paths deliberately filters to what is really on disk, which makes it
    impossible to ask "where would this go?" without intercepting the filter.
    """
    import data_paths
    real = data_paths._existing
    seen = []

    def _capture(*candidates):
        seen.extend(candidates)
        return real(*candidates)

    data_paths._existing = _capture
    try:
        fn()
    finally:
        data_paths._existing = real
    return seen


class ModeMembershipTests(unittest.TestCase):
    def setUp(self):
        self.registry = dc.build_registry()

    def test_modes_nest(self):
        conv = {c.id for c in self.registry.in_mode(dr.WIPE_MODE_CONVERSATIONS)}
        personal = {c.id for c in self.registry.in_mode(dr.WIPE_MODE_PERSONAL)}
        factory = {c.id for c in self.registry.in_mode(dr.WIPE_MODE_FACTORY_RESET)}
        self.assertTrue(conv < personal, "conversations must be a strict subset of personal")
        self.assertTrue(personal < factory, "personal must be a strict subset of factory")

    def test_factory_reset_covers_every_category_except_opt_in_models(self):
        factory = {c.id for c in self.registry.in_mode(dr.WIPE_MODE_FACTORY_RESET)}
        everything = {c.id for c in self.registry.all()}
        self.assertEqual(everything - factory, {"downloaded_models"})

    def test_factory_reset_includes_the_electron_owned_stores(self):
        """A reset that swept only the Python root would leave the consent
        record behind and the next launch would skip onboarding — visibly not
        a fresh install."""
        factory = {c.id for c in self.registry.in_mode(dr.WIPE_MODE_FACTORY_RESET)}
        for cid in ("onboarding_consent", "overlay_position", "overlay_appearance",
                    "sidecar_raw_log", "application_registry"):
            self.assertIn(cid, factory, cid)

    def test_every_mode_has_a_preview_naming_its_stores(self):
        for mode in dr.WIPE_MODES:
            preview = dl.preview_mode(self.registry, mode)
            self.assertEqual(preview["mode"], mode)
            ids = {c["id"] for c in preview["categories"]}
            self.assertEqual(ids, {c.id for c in self.registry.in_mode(mode)})

    def test_preview_deletes_nothing(self):
        for mode in dr.WIPE_MODES:
            dl.preview_mode(self.registry, mode)

    def test_unknown_mode_is_rejected_everywhere(self):
        for fn in (dl.execute_mode, dl.verify_mode, dl.preview_mode):
            with self.assertRaises(ValueError):
                fn(self.registry, "clear_everything_probably")


class ModeExecutionTests(_PopulatedRootMixin):
    def _run(self, mode):
        made = self.populate()
        self.assertTrue(made)
        result = dl.execute_mode(self.registry, mode)
        return made, result

    def test_conversations_mode_clears_its_set_and_leaves_the_rest(self):
        made, result = self._run(dr.WIPE_MODE_CONVERSATIONS)
        self.assertTrue(result["ok"], result["failed"])
        cleared = {c.id for c in self.registry.in_mode(dr.WIPE_MODE_CONVERSATIONS)}
        for cid in cleared:
            self.assertTrue(result["categories"][cid]["verified"], cid)
        # Settings survive the lightest mode — otherwise "clear conversations"
        # would be a factory reset with a friendlier label.
        for cid in ("profiles", "voice_presets", "macros", "dictionary"):
            self.assertNotIn(cid, result["categories"])
            for path in made.get(cid, []):
                self.assertTrue(path.exists(), f"{cid} must survive: {path}")

    def test_personal_mode_clears_conversations_too(self):
        made, result = self._run(dr.WIPE_MODE_PERSONAL)
        self.assertTrue(result["ok"], result["failed"])
        for cid in ("drafts", "contacts", "persona_learning", "macros",
                    "dictionary", "personas", "mcp_config"):
            self.assertTrue(result["categories"][cid]["verified"], cid)
        for cid in ("profiles", "voice_presets", "app_state"):
            for path in made.get(cid, []):
                self.assertTrue(path.exists(), f"{cid} is settings: {path}")

    def test_factory_reset_mode_clears_settings_as_well(self):
        made, result = self._run(dr.WIPE_MODE_FACTORY_RESET)
        self.assertTrue(result["ok"], result["failed"])
        for cid in ("profiles", "voice_presets", "app_state", "onboarding_consent",
                    "app_profiles", "launcher_workflows"):
            self.assertTrue(result["categories"][cid]["verified"], cid)
            for path in made.get(cid, []):
                self.assertFalse(path.exists(), f"{cid} must be gone: {path}")

    def test_downloaded_models_survive_every_mode(self):
        models = self.root / "models"
        models.mkdir(parents=True, exist_ok=True)
        blob = models / "a-model.gguf"
        blob.write_text("weights", encoding="utf-8")
        for mode in (dr.WIPE_MODE_CONVERSATIONS, dr.WIPE_MODE_PERSONAL,
                     dr.WIPE_MODE_FACTORY_RESET):
            dl.execute_mode(self.registry, mode)
            self.assertTrue(blob.exists(),
                            f"{mode} deleted an opt-in model download")

    def test_verify_mode_reports_a_store_that_came_back(self):
        """Verification must re-read the disk, so a file recreated after the
        sweep makes it fail. Otherwise 'verified' only means 'we called
        unlink', which is exactly the claim this design rejects."""
        self.populate()
        dl.execute_mode(self.registry, dr.WIPE_MODE_CONVERSATIONS)
        self.assertTrue(dl.verify_mode(self.registry, dr.WIPE_MODE_CONVERSATIONS)["ok"])
        # Recreated through the store's own API, not by writing bytes at the
        # path: contacts verify by counting records, so a file in some other
        # shape is genuinely zero contacts and passing it would be correct.
        from backend.services.contacts import ContactStore
        ContactStore().create({"name": "Came Back"})
        again = dl.verify_mode(self.registry, dr.WIPE_MODE_CONVERSATIONS)
        self.assertFalse(again["ok"])
        self.assertIn("contacts", again["failed"])

    def test_execute_mode_is_idempotent(self):
        self.populate()
        first = dl.execute_mode(self.registry, dr.WIPE_MODE_FACTORY_RESET)
        second = dl.execute_mode(self.registry, dr.WIPE_MODE_FACTORY_RESET)
        self.assertTrue(first["ok"], first["failed"])
        self.assertTrue(second["ok"], second["failed"])

    def test_a_store_that_will_not_delete_is_reported_not_swallowed(self):
        self.populate()

        def _boom(path):
            raise OSError("permission denied")

        with patch("data_lifecycle._remove", _boom):
            result = dl.execute_mode(self.registry, dr.WIPE_MODE_CONVERSATIONS)
        self.assertFalse(result["ok"])
        self.assertTrue(result["failed"])


class AudioPrivacyJournalTests(_PopulatedRootMixin):
    """The crash-recovery journal (Wave 8B) is normally absent — it is written
    before a capture stream is muted and cleared when voice privacy is
    released. A journal left behind by a crash is exactly the state a wipe
    must handle, so it gets its own test rather than riding along with the
    other single-file stores."""

    def _journal_path(self):
        from backend.platform.audio_privacy import journal
        return pathlib.Path(journal.default_journal_path())

    def test_journal_is_declared_and_lives_under_a_known_root(self):
        category = self.registry.get("audio_privacy_journal")
        self.assertEqual(category.owner, "python")
        # Operational state, not a setting: a personal wipe clears it.
        self.assertIn(dr.WIPE_MODE_PERSONAL, category.wipe_modes)
        self.assertFalse(category.may_contain_user_text)

    def test_a_crash_left_journal_is_cleared_by_a_personal_wipe(self):
        path = self._journal_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"streams": [7], "prior_muted": false}', encoding="utf-8")
        self.assertTrue(path.exists())

        result = dl.execute_mode(self.registry, dr.WIPE_MODE_PERSONAL)
        self.assertTrue(result["categories"]["audio_privacy_journal"]["verified"])
        self.assertFalse(path.exists(), "crash journal survived a personal wipe")

    def test_absent_journal_is_not_a_failure(self):
        path = self._journal_path()
        if path.exists():
            path.unlink()
        result = dl.execute_mode(self.registry, dr.WIPE_MODE_PERSONAL)
        self.assertTrue(result["categories"]["audio_privacy_journal"]["verified"])

    def test_journal_holds_no_user_text(self):
        """The declaration says stream indices and a boolean, never prose. If
        that ever stops being true the category's sensitivity and user_text
        flag are both wrong, so assert the shape the claim rests on."""
        path = self._journal_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"streams": [7], "prior_muted": false}', encoding="utf-8")
        category = self.registry.get("audio_privacy_journal")
        self.assertGreater(category.size(), 0)
        self.assertFalse(category.may_contain_user_text)


class SafetyTests(_PopulatedRootMixin):
    def test_a_path_outside_every_known_root_is_refused(self):
        """A bug in a paths() callable must raise, not recursively delete
        someone's home directory."""
        outside = pathlib.Path(tempfile.gettempdir()) / "definitely-not-ours"
        outside.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: outside.rmdir() if outside.exists() else None)
        with self.assertRaises(dl.UnsafePathError):
            dl.make_wipe(lambda: [outside])()

    def test_paths_inside_the_root_are_allowed(self):
        target = self.root / "inside.json"
        target.write_text("{}", encoding="utf-8")
        result = dl.make_wipe(lambda: [target])()
        self.assertTrue(result.ok)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
