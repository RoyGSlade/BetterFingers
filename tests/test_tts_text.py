import unittest

from tts_text import normalize_for_speech


class TtsNormalizationTests(unittest.TestCase):
    def test_abbreviations(self):
        self.assertEqual(normalize_for_speech("Dr. Smith"), "Doctor Smith")
        self.assertEqual(normalize_for_speech("Mr. and Mrs. Lee"), "Mister and Missus Lee")
        self.assertEqual(normalize_for_speech("apples e.g. gala"), "apples for example gala")
        self.assertEqual(normalize_for_speech("cats i.e. felines"), "cats that is felines")
        self.assertEqual(normalize_for_speech("A vs. B"), "A versus B")

    def test_currency_singular_and_plural(self):
        self.assertEqual(normalize_for_speech("$1"), "1 dollar")
        self.assertEqual(normalize_for_speech("$5"), "5 dollars")
        self.assertEqual(normalize_for_speech("$5.50"), "5 dollars and 50 cents")
        self.assertIn("cent", normalize_for_speech("$3.01"))

    def test_percent(self):
        self.assertEqual(normalize_for_speech("20%"), "20 percent")
        self.assertEqual(normalize_for_speech("99.9%"), "99.9 percent")

    def test_symbols(self):
        self.assertEqual(normalize_for_speech("milk & eggs"), "milk and eggs")
        self.assertEqual(normalize_for_speech("me @ home"), "me at home")
        self.assertEqual(normalize_for_speech("item #7"), "item number 7")

    def test_no_change_on_plain_text(self):
        text = "This is an ordinary sentence with nothing special"
        self.assertEqual(normalize_for_speech(text), text)

    def test_empty(self):
        self.assertEqual(normalize_for_speech(""), "")
        self.assertEqual(normalize_for_speech(None), None)


class TtsSplitterTests(unittest.TestCase):
    """The chunker already splits on sentence boundaries; guard that behavior."""

    def test_splits_on_sentence_boundaries_not_midword(self):
        from tts_engine import ReviewTTSEngine

        long_text = ("This is the first sentence. " * 20).strip()
        chunks = ReviewTTSEngine._split_text_for_tts(text=long_text, max_chars=60)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 60)
            # No chunk should end mid-word (i.e. end with a letter+space split).
            self.assertFalse(chunk.endswith(" "))


if __name__ == "__main__":
    unittest.main()
