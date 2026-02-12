import unittest
from unittest.mock import patch

import pytest

from settings import SettingsWindow
from settings_controls_mixin import SettingsControlsMixin

pytestmark = pytest.mark.smoke


class SettingsExperiencePresetTests(unittest.TestCase):
    def test_infer_plus_preset_from_profile_values(self):
        cfg = {
            "llm_enabled": True,
            "model_size": "base.en",
            "llm_model_id": "gemma-3-4b-q4",
            "quantization": "int4",
        }
        self.assertEqual(SettingsControlsMixin._infer_experience_preset(cfg), "plus")

    @patch("settings_controls_mixin.get_fast_lane_preset_names", return_value=["True Janitor", "Formal"])
    def test_apply_simple_preset_updates_related_controls(self, _names):
        window = SettingsWindow(
            root=None,
            hotkey_manager=None,
            on_save_callback=lambda: None,
        )
        window._build_controls()

        window._apply_experience_preset("simple")

        self.assertEqual(window._controls["experience_preset"].value, "simple")
        self.assertFalse(bool(window._controls["llm_enabled"].value))
        self.assertEqual(window._controls["model_size"].value, "tiny.en")
        self.assertEqual(window._controls["llm_model_id"].value, "gemma-3-4b-q4")
        self.assertEqual(window._controls["quantization"].value, "int4")
        self.assertEqual(window._controls["persona"].value, "True Janitor")

    @patch("settings_controls_mixin.get_fast_lane_preset_names", return_value=["True Janitor", "Formal"])
    def test_manual_change_marks_preset_as_custom(self, _names):
        window = SettingsWindow(
            root=None,
            hotkey_manager=None,
            on_save_callback=lambda: None,
        )
        window._build_controls()
        window._apply_experience_preset("plus")
        self.assertEqual(window._controls["experience_preset"].value, "plus")

        window._controls["model_size"].value = "small.en"
        window._on_preset_related_setting_changed()

        self.assertEqual(window._controls["experience_preset"].value, "custom")

    @patch("settings_controls_mixin.get_fast_lane_preset_names", return_value=["True Janitor", "Formal"])
    def test_hardware_estimate_contains_vram_guidance(self, _names):
        window = SettingsWindow(
            root=None,
            hotkey_manager=None,
            on_save_callback=lambda: None,
        )
        window._build_controls()
        window._controls["llm_enabled"].value = True
        window._controls["llm_model_id"].value = "gemma-3-4b-q8"
        window._controls["model_size"].value = "small.en"
        window._controls["use_gpu"].value = True

        estimate = window._estimate_hardware_requirements_text()

        self.assertIn("Current VRAM estimate", estimate)
        self.assertIn("Recommended GPU VRAM", estimate)

    @patch("settings_controls_mixin.get_fast_lane_preset_names", return_value=["True Janitor", "Formal"])
    def test_preset_switch_shows_inline_actions_and_applies_on_confirm(self, _names):
        class _Event:
            def __init__(self, control):
                self.control = control

        window = SettingsWindow(
            root=None,
            hotkey_manager=None,
            on_save_callback=lambda: None,
        )
        window._build_controls()
        window._apply_experience_preset("plus")

        window._controls["experience_preset"].value = "pro"
        window._on_experience_preset_changed(_Event(window._controls["experience_preset"]))

        self.assertTrue(bool(window._controls["preset_pending_actions"].visible))
        self.assertIn("Pending switch to Pro Mode", window._controls["hardware_change_preview"].value)
        self.assertEqual(window._controls["llm_model_id"].value, "gemma-3-4b-q4")

        # Confirm applies the pending target preset.
        window._on_apply_pending_experience_preset()
        self.assertEqual(window._controls["experience_preset"].value, "pro")
        self.assertEqual(window._controls["llm_model_id"].value, "gemma-3-4b-q8")
        self.assertFalse(bool(window._controls["preset_pending_actions"].visible))

    @patch("settings_controls_mixin.get_fast_lane_preset_names", return_value=["True Janitor", "Formal"])
    def test_preset_switch_detects_selection_from_event_data(self, _names):
        class _Event:
            def __init__(self, control, data):
                self.control = control
                self.data = data

        window = SettingsWindow(
            root=None,
            hotkey_manager=None,
            on_save_callback=lambda: None,
        )
        window._build_controls()
        window._apply_experience_preset("plus")

        # Simulate dropdown events that carry selected value in event.data.
        window._controls["experience_preset"].value = "plus"
        window._on_experience_preset_changed(_Event(window._controls["experience_preset"], "pro"))

        self.assertEqual(window._controls["experience_preset"].value, "pro")
        self.assertTrue(bool(window._controls["preset_pending_actions"].visible))
        self.assertEqual(window._selected_preset_pending, "pro")
        self.assertIn("Pending switch to Pro Mode", window._controls["hardware_change_preview"].value)

    @patch("settings_controls_mixin.get_fast_lane_preset_names", return_value=["True Janitor", "Formal"])
    def test_preset_switch_cancel_reverts_dropdown(self, _names):
        class _Event:
            def __init__(self, control):
                self.control = control

        window = SettingsWindow(
            root=None,
            hotkey_manager=None,
            on_save_callback=lambda: None,
        )
        window._build_controls()
        window._apply_experience_preset("plus")

        window._controls["experience_preset"].value = "dont_use"
        window._on_experience_preset_changed(_Event(window._controls["experience_preset"]))

        self.assertTrue(bool(window._controls["preset_pending_actions"].visible))
        window._on_cancel_pending_experience_preset()
        self.assertEqual(window._controls["experience_preset"].value, "plus")
        self.assertFalse(bool(window._controls["preset_pending_actions"].visible))

    @patch("settings_controls_mixin.get_fast_lane_preset_names", return_value=["True Janitor", "Formal"])
    def test_preset_interaction_does_not_clear_tab_content(self, _names):
        class _Event:
            def __init__(self, control):
                self.control = control

        window = SettingsWindow(
            root=None,
            hotkey_manager=None,
            on_save_callback=lambda: None,
        )
        window._build_controls()
        self.assertIsNotNone(window._tab_content_host)
        self.assertIsNotNone(window._tab_content_host.content)

        window._apply_experience_preset("plus")
        window._controls["experience_preset"].value = "pro"
        window._on_experience_preset_changed(_Event(window._controls["experience_preset"]))
        self.assertIsNotNone(window._tab_content_host.content)

        window._on_cancel_pending_experience_preset()
        self.assertIsNotNone(window._tab_content_host.content)

    @patch("settings_controls_mixin.get_fast_lane_preset_names", return_value=["True Janitor", "Formal"])
    @patch("settings_persistence_mixin.set_last_active_profile")
    @patch("settings_persistence_mixin.save_profile")
    @patch("settings_persistence_mixin.load_profile", return_value={})
    def test_pending_preset_is_not_persisted_until_apply(self, _load_profile, save_profile_mock, _set_last_active, _names):
        class _Event:
            def __init__(self, control):
                self.control = control

        window = SettingsWindow(
            root=None,
            hotkey_manager=None,
            on_save_callback=lambda: None,
        )
        window._build_controls()
        window._apply_experience_preset("plus")

        window._controls["experience_preset"].value = "pro"
        window._on_experience_preset_changed(_Event(window._controls["experience_preset"]))
        self.assertEqual(window._controls["llm_model_id"].value, "gemma-3-4b-q4")

        window._save_settings()
        saved_cfg = save_profile_mock.call_args[0][1]
        self.assertEqual(saved_cfg["experience_preset"], "plus")
        self.assertEqual(saved_cfg["llm_model_id"], "gemma-3-4b-q4")


if __name__ == "__main__":
    unittest.main()
