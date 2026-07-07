import unittest

from dictation_commands import apply_commands


class DictationCommandTests(unittest.TestCase):
    def test_spoken_punctuation(self):
        self.assertEqual(apply_commands("hello comma world period"), "hello, world.")
        self.assertEqual(apply_commands("really question mark"), "really?")
        self.assertEqual(apply_commands("wow exclamation point"), "wow!")
        self.assertEqual(apply_commands("note colon done"), "note: done")

    def test_full_stop_alias(self):
        self.assertEqual(apply_commands("done full stop"), "done.")

    def test_new_paragraph_and_line(self):
        self.assertEqual(apply_commands("one new paragraph two"), "one\n\ntwo")
        self.assertEqual(apply_commands("one new line two"), "one\ntwo")

    def test_new_sentence_capitalizes(self):
        self.assertEqual(
            apply_commands("first new sentence second"), "first. Second"
        )

    def test_all_caps(self):
        self.assertEqual(apply_commands("say all caps hello"), "say HELLO")

    def test_capital_word(self):
        self.assertEqual(apply_commands("meet capital john today"), "meet John today")
        self.assertEqual(apply_commands("caps apple"), "Apple")

    def test_parentheses(self):
        self.assertEqual(
            apply_commands("note open paren draft close paren here"),
            "note (draft) here",
        )

    def test_no_commands_is_unchanged(self):
        text = "this is a perfectly ordinary sentence"
        self.assertEqual(apply_commands(text), text)

    def test_does_not_match_inside_words(self):
        # 'periodic' must not become 'ic' etc.
        self.assertEqual(apply_commands("a periodic table"), "a periodic table")
        self.assertEqual(apply_commands("commander in chief"), "commander in chief")

    def test_empty_and_none(self):
        self.assertEqual(apply_commands(""), "")
        self.assertEqual(apply_commands(None), None)

    def test_multiple_punctuation(self):
        self.assertEqual(
            apply_commands("apples comma oranges comma and pears period"),
            "apples, oranges, and pears.",
        )


if __name__ == "__main__":
    unittest.main()
