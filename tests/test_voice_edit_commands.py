import unittest

from voice_edit_commands import (
    apply_inline_edits,
    capitalize_word,
    delete_last_sentence,
    delete_last_word,
    parse_edit_command,
    quote,
    replace_word,
    structural_insert,
)


class ParseEditCommandTests(unittest.TestCase):
    def test_scratch_that(self):
        self.assertEqual(parse_edit_command("scratch that").action, "scratch_that")

    def test_undo_that_maps_to_scratch_that(self):
        self.assertEqual(parse_edit_command("undo that").action, "scratch_that")

    def test_undo_last_sentence(self):
        self.assertEqual(parse_edit_command("undo last sentence").action, "delete_last_sentence")

    def test_delete_last_word(self):
        self.assertEqual(parse_edit_command("delete last word").action, "delete_last_word")

    def test_quote_that(self):
        self.assertEqual(parse_edit_command("quote that").action, "quote_that")

    def test_bullet_list(self):
        self.assertEqual(parse_edit_command("bullet list").action, "bullet_list")

    def test_numbered_list(self):
        self.assertEqual(parse_edit_command("numbered list").action, "numbered_list")

    def test_new_heading(self):
        self.assertEqual(parse_edit_command("new heading").action, "new_heading")

    def test_no_punctuation(self):
        self.assertEqual(parse_edit_command("no punctuation").action, "no_punctuation")

    def test_literal_mode(self):
        self.assertEqual(parse_edit_command("literal mode").action, "literal_mode")

    def test_replace_x_with_y(self):
        cmd = parse_edit_command("replace foo with bar")
        self.assertEqual(cmd.action, "replace")
        self.assertEqual(cmd.args, {"old": "foo", "new": "bar"})

    def test_capitalize_the_word_x(self):
        cmd = parse_edit_command("capitalize the word london")
        self.assertEqual(cmd.action, "capitalize_word")
        self.assertEqual(cmd.args, {"word": "london"})

    def test_capitalize_x_without_the_word(self):
        cmd = parse_edit_command("capitalize london")
        self.assertEqual(cmd.args, {"word": "london"})

    def test_no_command_returns_none(self):
        self.assertIsNone(parse_edit_command("the weather is nice today"))

    def test_empty_text_returns_none(self):
        self.assertIsNone(parse_edit_command(""))
        self.assertIsNone(parse_edit_command(None))


class DeleteLastWordTests(unittest.TestCase):
    def test_strips_trailing_word(self):
        self.assertEqual(delete_last_word("hello world"), "hello")

    def test_strips_trailing_punctuation_and_word(self):
        self.assertEqual(delete_last_word("hello world."), "hello")

    def test_single_word_clears(self):
        self.assertEqual(delete_last_word("hello"), "")

    def test_empty_text(self):
        self.assertEqual(delete_last_word(""), "")


class DeleteLastSentenceTests(unittest.TestCase):
    def test_strips_back_to_previous_boundary(self):
        self.assertEqual(
            delete_last_sentence("First sentence. Second sentence."),
            "First sentence.",
        )

    def test_no_earlier_boundary_clears_all(self):
        self.assertEqual(delete_last_sentence("Only one sentence here"), "")

    def test_handles_question_and_exclamation(self):
        self.assertEqual(delete_last_sentence("Are you sure? Yes!"), "Are you sure?")


class ReplaceWordTests(unittest.TestCase):
    def test_whole_word_replace(self):
        self.assertEqual(replace_word("send it to foo", "foo", "bar"), "send it to bar")

    def test_word_boundary_safe(self):
        self.assertEqual(replace_word("foobar stays", "foo", "bar"), "foobar stays")

    def test_case_insensitive_match(self):
        self.assertEqual(replace_word("Send Foo now", "foo", "bar"), "Send bar now")


class CapitalizeWordTests(unittest.TestCase):
    def test_capitalizes_all_occurrences(self):
        self.assertEqual(capitalize_word("i live in london near london bridge", "london"), "i live in London near London bridge")

    def test_word_boundary_safe(self):
        self.assertEqual(capitalize_word("londoner", "london"), "londoner")


class QuoteTests(unittest.TestCase):
    def test_wraps_in_quotes(self):
        self.assertEqual(quote("hello world"), '"hello world"')

    def test_empty_text(self):
        self.assertEqual(quote(""), "")


class StructuralInsertTests(unittest.TestCase):
    def test_known_actions(self):
        self.assertEqual(structural_insert("bullet_list"), "\n- ")
        self.assertEqual(structural_insert("numbered_list"), "\n1. ")
        self.assertEqual(structural_insert("new_heading"), "\n## ")

    def test_unknown_action_returns_none(self):
        self.assertIsNone(structural_insert("scratch_that"))


class ApplyInlineEditsTests(unittest.TestCase):
    def test_delete_last_word_removes_preceding_word_and_phrase(self):
        self.assertEqual(
            apply_inline_edits("the quick brown fox delete last word"),
            "the quick brown",
        )

    def test_undo_last_sentence_strips_back_to_boundary(self):
        self.assertEqual(
            apply_inline_edits("First sentence. Second thought undo last sentence"),
            "First sentence.",
        )

    def test_quote_that_wraps_preceding_text(self):
        self.assertEqual(apply_inline_edits("hello world quote that"), '"hello world"')

    def test_replace_x_with_y_applies_and_strips_command(self):
        self.assertEqual(
            apply_inline_edits("send it to foo replace foo with bar"),
            "send it to bar",
        )

    def test_capitalize_the_word_x_applies_and_strips_command(self):
        self.assertEqual(
            apply_inline_edits("i live in london capitalize london"),
            "i live in London",
        )

    def test_bullet_list_inserts_marker(self):
        self.assertEqual(apply_inline_edits("todo items bullet list"), "todo items\n- ")

    def test_new_heading_inserts_marker(self):
        self.assertEqual(apply_inline_edits("new heading Project Plan"), "\n## Project Plan")

    def test_no_command_returns_text_unchanged(self):
        self.assertEqual(apply_inline_edits("just plain dictation"), "just plain dictation")

    def test_empty_text(self):
        self.assertEqual(apply_inline_edits(""), "")


if __name__ == "__main__":
    unittest.main()
