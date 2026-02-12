"""Tests for the Whisper hallucination guard in transcriber.py."""
import unittest

from transcriber import _is_hallucination


class HallucinationGuardTests(unittest.TestCase):
    # --- Should be detected as hallucinations ---

    def test_single_known_phrase(self):
        self.assertTrue(_is_hallucination("Thank you."))

    def test_repeated_known_phrase(self):
        self.assertTrue(_is_hallucination("Thank you. Thank you. Thank you."))

    def test_repeated_unknown_phrase_three_times(self):
        self.assertTrue(_is_hallucination("Hello. Hello. Hello."))

    def test_known_phrase_majority(self):
        self.assertTrue(_is_hallucination("Thank you. Thank you. Okay."))

    def test_case_insensitive(self):
        self.assertTrue(_is_hallucination("THANK YOU."))

    def test_subscribe_hallucination(self):
        self.assertTrue(_is_hallucination("Subscribe. Subscribe. Subscribe."))

    # --- Should NOT be detected as hallucinations ---

    def test_normal_sentence(self):
        self.assertFalse(_is_hallucination("I need to fix the settings page."))

    def test_two_different_sentences(self):
        self.assertFalse(_is_hallucination("Hello there. How are you doing today?"))

    def test_empty_string(self):
        self.assertFalse(_is_hallucination(""))

    def test_short_legitimate_text(self):
        self.assertFalse(_is_hallucination("Yes"))

    def test_repeated_word_in_normal_context(self):
        self.assertFalse(_is_hallucination("I really really want to go there."))


if __name__ == "__main__":
    unittest.main()
