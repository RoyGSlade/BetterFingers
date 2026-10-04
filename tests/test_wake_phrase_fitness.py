import json
import unittest
from unittest import mock

from backend.wake import wake_phrase_fitness as wpf


class WakePhraseFitnessTests(unittest.TestCase):
    def evaluate(self, phrase, **kwargs):
        with mock.patch.object(wpf, "_optional_pronunciation", return_value=None):
            return wpf.evaluate_wake_phrase(phrase, **kwargs)

    def test_good_candidate_is_normalized_serializable_and_deterministic(self):
        first = self.evaluate("  Hey, BetterFingers!  ")
        second = self.evaluate("  Hey, BetterFingers!  ")

        self.assertEqual(first, second)
        self.assertEqual(first["normalized_phrase"], "hey betterfingers")
        self.assertEqual(first["verdict"], "good")
        self.assertTrue(first["acoustic_test_required"])
        self.assertGreaterEqual(first["evidence"]["estimated_phonemes"], 6)
        self.assertIn("hey better fingers", first["near_confusers"])
        json.dumps(first)

    def test_empty_and_acoustically_thin_phrases_are_rejected(self):
        empty = self.evaluate("   ")
        short = self.evaluate("go")

        self.assertEqual(empty["verdict"], "reject")
        self.assertEqual(empty["normalized_phrase"], "")
        self.assertEqual(short["verdict"], "reject")
        self.assertTrue(any("too short" in reason for reason in short["reasons"]))

    def test_common_everyday_phrase_is_rejected(self):
        report = self.evaluate("hello")

        self.assertEqual(report["verdict"], "reject")
        self.assertTrue(any("common everyday speech" in reason for reason in report["reasons"]))

    def test_custom_command_collision_is_rejected(self):
        report = self.evaluate(
            "launch rocket league",
            command_vocabulary=["launch rocket league", "invite my friends"],
        )

        self.assertEqual(report["verdict"], "reject")
        self.assertTrue(any("already a command" in reason for reason in report["reasons"]))

    def test_custom_common_vocabulary_extends_built_in_checks(self):
        report = self.evaluate(
            "gaming with the boys",
            common_vocabulary=["gaming with the boys"],
        )

        self.assertEqual(report["verdict"], "reject")
        self.assertTrue(any("common everyday speech" in reason for reason in report["reasons"]))

    def test_english_only_v1_rejects_other_scripts_and_digits(self):
        non_english = self.evaluate("hola se\u00f1or")
        numbered = self.evaluate("agent 47")

        self.assertEqual(non_english["verdict"], "reject")
        self.assertEqual(non_english["evidence"]["unsupported_characters"], ["\u00f1"])
        self.assertEqual(numbered["verdict"], "reject")
        self.assertEqual(numbered["evidence"]["unsupported_characters"], ["4", "7"])

    def test_optional_pronunciation_dependency_degrades_to_heuristics(self):
        wpf._optional_pronunciation.cache_clear()
        with mock.patch.object(wpf.importlib, "import_module", side_effect=ImportError):
            self.assertIsNone(wpf._optional_pronunciation("hey betterfingers"))

        report = self.evaluate("hey betterfingers")
        self.assertEqual(report["evidence"]["pronunciation_source"], "heuristic_only")
        self.assertIsNone(report["evidence"]["pronunciation"])

    def test_near_confusers_are_stable_and_include_compound_variants(self):
        report = self.evaluate(
            "hey betterfingers",
            common_vocabulary=["better features"],
            command_vocabulary=["hey better figures"],
        )

        self.assertEqual(report["near_confusers"], self.evaluate(
            "hey betterfingers",
            common_vocabulary=["better features"],
            command_vocabulary=["hey better figures"],
        )["near_confusers"])
        self.assertIn("hey better fingers", report["near_confusers"])
        self.assertLessEqual(len(report["near_confusers"]), 10)


if __name__ == "__main__":
    unittest.main()
