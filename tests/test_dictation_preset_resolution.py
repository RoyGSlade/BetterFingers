"""Resolving the profile's current_preset for dictation cleanup.

The 'current preset' settings dropdown lets a user pick a dictation persona and
persists it (profile field current_preset), but the dictation pipeline used to
hardcode 'True Janitor' and ignore the choice — a dead control. resolve_dictation_preset
honors the selection while falling back to True Janitor for empty or stale
(deleted/renamed) selections, so a bad value never breaks the core loop.
"""

import unittest
from unittest.mock import patch

import llm_engine as le


class ResolveDictationPresetTests(unittest.TestCase):
    def test_empty_or_whitespace_falls_back_to_true_janitor(self):
        for empty in (None, "", "   ", "\t"):
            self.assertEqual(le.resolve_dictation_preset(empty), "True Janitor")

    def test_internal_preset_passes_through(self):
        # Plan Generator is an internal preset; honored as-is.
        self.assertEqual(le.resolve_dictation_preset("Plan Generator"), "Plan Generator")

    def test_internal_preset_check_precedes_persona_lookup(self):
        # An internal preset must resolve even if the persona store is unavailable,
        # so the internal check has to short-circuit before get_persona.
        with patch("llm_engine.get_persona", side_effect=AssertionError("must not be called")):
            self.assertEqual(le.resolve_dictation_preset("Plan Generator"), "Plan Generator")

    @patch("llm_engine.get_persona", return_value={"name": "Court Reporter"})
    def test_known_persona_is_honored(self, _gp):
        self.assertEqual(le.resolve_dictation_preset("Court Reporter"), "Court Reporter")

    @patch("llm_engine.get_persona", return_value=None)
    def test_unknown_or_deleted_persona_falls_back(self, _gp):
        self.assertEqual(le.resolve_dictation_preset("Deleted Persona"), "True Janitor")

    @patch("llm_engine.get_persona", return_value={"name": "True Janitor"})
    def test_true_janitor_selection_is_honored(self, _gp):
        self.assertEqual(le.resolve_dictation_preset("True Janitor"), "True Janitor")

    def test_surrounding_whitespace_is_trimmed(self):
        with patch("llm_engine.get_persona", return_value={"name": "Court Reporter"}) as gp:
            self.assertEqual(le.resolve_dictation_preset("  Court Reporter  "), "Court Reporter")
            # The lookup used the trimmed name, not the padded one.
            gp.assert_called_once_with("Court Reporter")


if __name__ == "__main__":
    unittest.main()
