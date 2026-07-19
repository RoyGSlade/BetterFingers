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
    "cloned_voices", "personas", "dictionary", "macros", "wake_models",
    "mcp_config", "graph_data", "debug_log", "sidecar_raw_log", "support_report",
    "voice_presets", "profiles", "app_state", "overlay_position",
    "overlay_appearance", "model_runtime_metadata", "downloaded_models",
})


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
                    "overlay_appearance", "mcp_config", "graph_data", "temp_audio"):
            self.assertIn(cid, got)


class MetadataHonestyTests(unittest.TestCase):
    def setUp(self):
        self.by_id = {c.id: c for c in dc.CATEGORIES}

    def test_electron_owned_stores_declared_electron(self):
        for cid in ("sidecar_raw_log", "overlay_position", "overlay_appearance"):
            self.assertEqual(self.by_id[cid].owner, "electron", cid)

    def test_text_bearing_stores_flag_user_text(self):
        for cid in ("drafts", "history_db", "personas", "dictionary", "macros",
                    "graph_data", "debug_log", "sidecar_raw_log", "support_report"):
            self.assertTrue(self.by_id[cid].may_contain_user_text, cid)

    def test_audio_and_settings_stores_do_not_claim_user_text(self):
        for cid in ("raw_recordings", "temp_audio", "cloned_voices",
                    "profiles", "overlay_position", "downloaded_models"):
            self.assertFalse(self.by_id[cid].may_contain_user_text, cid)

    def test_conversation_data_is_cleared_by_every_mode(self):
        reg = dc.build_registry()
        conv_ids = {c.id for c in reg.in_mode(dr.WIPE_MODE_CONVERSATIONS)}
        self.assertEqual(
            conv_ids, {"raw_recordings", "drafts", "history_db", "temp_audio"})

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
