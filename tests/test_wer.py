import unittest

from wer import compare_transcripts, normalize, tokenize, word_error_rate


class NormalizeTokenizeTests(unittest.TestCase):
    def test_normalize_lowercases_and_strips_punctuation(self):
        self.assertEqual(normalize("Hello, World!"), "hello world")

    def test_normalize_keeps_apostrophes(self):
        self.assertEqual(normalize("It's don't"), "it's don't")

    def test_normalize_collapses_whitespace(self):
        self.assertEqual(normalize("a\t b\n  c"), "a b c")

    def test_tokenize_empty(self):
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize("   "), [])


class WerTests(unittest.TestCase):
    def test_identical_is_zero(self):
        self.assertEqual(word_error_rate("the quick brown fox", "the quick brown fox"), 0.0)

    def test_case_and_punctuation_insensitive(self):
        self.assertEqual(word_error_rate("The, Quick Brown FOX.", "the quick brown fox"), 0.0)

    def test_all_wrong_is_one(self):
        self.assertEqual(word_error_rate("alpha beta gamma", "one two three"), 1.0)

    def test_single_substitution(self):
        r = compare_transcripts("the quick brown fox", "the quick red fox")
        self.assertEqual(r["substitutions"], 1)
        self.assertEqual(r["deletions"], 0)
        self.assertEqual(r["insertions"], 0)
        self.assertEqual(r["hits"], 3)
        self.assertAlmostEqual(r["wer"], 1 / 4)

    def test_single_deletion(self):
        r = compare_transcripts("the quick brown fox", "the quick fox")
        self.assertEqual(r["deletions"], 1)
        self.assertEqual(r["substitutions"], 0)
        self.assertEqual(r["insertions"], 0)
        self.assertAlmostEqual(r["wer"], 1 / 4)

    def test_single_insertion(self):
        r = compare_transcripts("the quick fox", "the quick brown fox")
        self.assertEqual(r["insertions"], 1)
        self.assertEqual(r["deletions"], 0)
        self.assertEqual(r["substitutions"], 0)
        self.assertAlmostEqual(r["wer"], 1 / 3)

    def test_mixed_errors(self):
        # ref: a b c d   hyp: a x c d e  -> 1 sub (b->x), 1 ins (e)
        r = compare_transcripts("a b c d", "a x c d e")
        self.assertEqual(r["substitutions"], 1)
        self.assertEqual(r["insertions"], 1)
        self.assertEqual(r["deletions"], 0)
        self.assertEqual(r["ref_words"], 4)
        self.assertAlmostEqual(r["wer"], 2 / 4)

    def test_empty_ref_empty_hyp(self):
        r = compare_transcripts("", "")
        self.assertEqual(r["wer"], 0.0)
        self.assertEqual(r["ref_words"], 0)

    def test_empty_ref_nonempty_hyp(self):
        r = compare_transcripts("", "surprise words")
        self.assertEqual(r["wer"], 1.0)
        self.assertEqual(r["insertions"], 2)

    def test_nonempty_ref_empty_hyp_all_deletions(self):
        r = compare_transcripts("one two three", "")
        self.assertEqual(r["deletions"], 3)
        self.assertEqual(r["wer"], 1.0)

    def test_wer_can_exceed_one_with_many_insertions(self):
        # ref has 1 word, hyp adds 3 extra -> 3 insertions / 1 ref word = 3.0
        r = compare_transcripts("go", "go go go go")
        self.assertEqual(r["insertions"], 3)
        self.assertAlmostEqual(r["wer"], 3.0)


if __name__ == "__main__":
    unittest.main()
