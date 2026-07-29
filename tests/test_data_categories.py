"""Phase 2.1b (remediation) — the concrete data-category inventory.

The completeness guard is the point: the expected id set is hard-coded here (not
derived from the inventory), so removing, renaming, or forgetting a persistent
store fails CI. Reviewer flagged the easy-to-forget ones — debug log, sidecar
raw log, overlay position/appearance, MCP config, graph data, temp/conversion
artifacts — so those get explicit assertions too.
"""

import unittest

import data_categories as dc
import data_registry as dr


# Hard-coded on purpose. Update this set (and the changelog) deliberately when a
# real persistent store is added or removed — never auto-derive it from CATEGORIES.
EXPECTED_IDS = frozenset({
    "raw_recordings", "drafts", "history_db", "temp_audio",
    "cloned_voices", "personas", "persona_learning", "dictionary", "macros",
    "contacts", "user_profile", "wake_models",
    "mcp_config", "graph_data", "debug_log", "sidecar_raw_log",
    "voice_presets", "profiles", "app_state", "overlay_position",
    "overlay_appearance", "onboarding_consent", "app_profiles",
    "launcher_workflows", "application_registry", "audio_privacy_journal",
    "model_runtime_metadata", "downloaded_models",
    # Wave 10 input stores. Shapes were supplied by the lane that owns them and
    # verified against backend/stores/controller_bindings.py before declaring,
    # rather than guessed from the id.
    "controller_bindings", "stream_deck_config",
})

# Wave 6 reconciled the inventory against the modules in BOTH directions. These
# ids must NOT come back without a store landing first — the note beside each is
# the evidence that was checked, so a future reader re-adding one has to refute
# a specific fact rather than an absence.
CUT_IDS = {
    # server.gather_support_report renders Markdown in memory and returns it
    # over HTTP; nothing writes it to disk. Size always 0, wipe a no-op, verify
    # vacuous. If the user saves it themselves it lands outside our roots.
    "support_report": "generated on demand, never persisted",
    # Nothing in the tree writes a voice-profile version store.
    "voice_profile_versions": "no store exists",
    # wake_training_data builds windows purely in memory (no writer).
    "wake_training_samples": "no store exists",
    # The only wake manifest is imported_models.json INSIDE the wake-models
    # directory, already covered by the wake_models category.
    "wake_classifier_metadata": "covered by wake_models",
}


class InventoryCompletenessTests(unittest.TestCase):
    def test_every_category_validates_and_registers(self):
        reg = dc.build_registry()  # register() validates each; raises on any gap
        self.assertEqual(len(reg), len(dc.CATEGORIES))

    def test_id_set_matches_expected(self):
        got = frozenset(c.id for c in dc.CATEGORIES)
        missing = EXPECTED_IDS - got
        extra = got - EXPECTED_IDS
        self.assertEqual(missing, frozenset(), f"forgotten stores: {sorted(missing)}")
        self.assertEqual(extra, frozenset(), f"unexpected stores: {sorted(extra)}")

    def test_no_duplicate_ids(self):
        ids = [c.id for c in dc.CATEGORIES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_easy_to_forget_stores_present(self):
        got = {c.id for c in dc.CATEGORIES}
        for cid in ("debug_log", "sidecar_raw_log", "overlay_position",
                    "overlay_appearance", "mcp_config", "graph_data", "temp_audio",
                    # Wave 6: both had real stores and no category. persona_learning
                    # holds the user's own words on both sides of a rewrite pair;
                    # user_profile resolves its own root outside app_paths, so it
                    # was invisible to the report AND survived factory reset.
                    "persona_learning", "user_profile"):
            self.assertIn(cid, got)

    def test_cut_ids_stay_cut(self):
        got = {c.id for c in dc.CATEGORIES}
        for cid, why in CUT_IDS.items():
            self.assertNotIn(cid, got, f"{cid} was cut in Wave 6: {why}")

    def test_no_category_uses_a_stub_callable(self):
        """The 2.1c/2.1d stubs are gone. A category whose paths() is the old
        _no_paths (or whose wipe reports not_implemented) would render in the
        privacy report as a store that is always empty and always wipes clean —
        strictly worse than not declaring it, because it reassures."""
        for c in dc.CATEGORIES:
            self.assertIsInstance(c.paths(), list, c.id)
            self.assertNotIn("not_implemented", str(c.wipe.__doc__ or ""), c.id)
        # And the stub names themselves must no longer exist in the module.
        for stub in ("_no_paths", "_no_size", "_unimpl_wipe", "_unimpl_verify"):
            self.assertFalse(hasattr(dc, stub), f"stub {stub} still present")


class MetadataHonestyTests(unittest.TestCase):
    def setUp(self):
        self.by_id = {c.id: c for c in dc.CATEGORIES}

    def test_electron_owned_stores_declared_electron(self):
        for cid in ("sidecar_raw_log", "overlay_position", "overlay_appearance"):
            self.assertEqual(self.by_id[cid].owner, "electron", cid)

    def test_text_bearing_stores_flag_user_text(self):
        for cid in ("drafts", "history_db", "personas", "dictionary", "macros",
                    "graph_data", "debug_log", "sidecar_raw_log",
                    # Approved raw-to-final example pairs are the user's own
                    # words on both sides; "hobbies" is free prose.
                    "persona_learning", "user_profile"):
            self.assertTrue(self.by_id[cid].may_contain_user_text, cid)

    def test_audio_and_settings_stores_do_not_claim_user_text(self):
        for cid in ("raw_recordings", "temp_audio", "cloned_voices",
                    "profiles", "overlay_position", "downloaded_models"):
            self.assertFalse(self.by_id[cid].may_contain_user_text, cid)

    def test_conversation_data_is_cleared_by_every_mode(self):
        """The lightest mode's membership is not a matter of taste: it is the
        exact set POST /privacy/wipe deletes by default.

        Wave 6 added persona_learning and contacts here rather than leaving
        them in the personal tier. Both were already being deleted by the
        shipped endpoint's hand-rolled sweep, so declaring them one tier higher
        would have made the registry disagree with the code it now drives —
        and narrowing the endpoint to match the old declaration would have
        silently STOPPED clearing two stores of user text that "delete my
        data" has always cleared. A learned example is a verbatim dictation
        plus its rewrite; contacts are prose about a person that drafts
        reference by id.
        """
        reg = dc.build_registry()
        conv_ids = {c.id for c in reg.in_mode(dr.WIPE_MODE_CONVERSATIONS)}
        self.assertEqual(
            conv_ids, {"raw_recordings", "drafts", "history_db", "temp_audio",
                       "persona_learning", "contacts"})

    def test_settings_only_cleared_by_factory_reset(self):
        reg = dc.build_registry()
        # Profiles/overlay/app-state are absent from the two lighter modes.
        for mode in (dr.WIPE_MODE_CONVERSATIONS, dr.WIPE_MODE_PERSONAL):
            ids = {c.id for c in reg.in_mode(mode)}
            self.assertNotIn("profiles", ids)
            self.assertNotIn("overlay_position", ids)
        factory_ids = {c.id for c in reg.in_mode(dr.WIPE_MODE_FACTORY_RESET)}
        self.assertIn("profiles", factory_ids)

    def test_downloaded_models_are_opt_in_only(self):
        # Not removed by any standard wipe mode.
        reg = dc.build_registry()
        for mode in dr.WIPE_MODES:
            self.assertNotIn(
                "downloaded_models", {c.id for c in reg.in_mode(mode)})

    def test_every_sensitivity_and_owner_in_vocabulary(self):
        for c in dc.CATEGORIES:
            self.assertIn(c.sensitivity, dr.SENSITIVITIES, c.id)
            self.assertIn(c.owner, dr.OWNERS, c.id)


if __name__ == "__main__":
    unittest.main()
