"""Unit tests for the shared negation rule (backend/commands/negation.py).

The parsers' behaviour tables live in test_voice_command_negation.py and
test_voice_edit_command_negation.py; these pin the rule's own edges so a change
to it is a visible, deliberate one.
"""
import pytest

from backend.commands.negation import MAX_GAP_WORDS, is_negated


def span(text, phrase):
    start = text.lower().index(phrase.lower())
    return start, start + len(phrase)


def negated(text, phrase):
    return is_negated(text, *span(text, phrase))


@pytest.mark.parametrize("text", [
    "don't send it", "do not send it", "never send it", "no send it", "cannot send it",
    "can't send it", "won't send it", "shouldn't send it", "dont send it", "don’t send it",
    "DON'T SEND IT", "nope send it", "nah send it",
    "no don't send it", "never mind don't send it", "please don't send it",
    "don't ever send it", "i told you not to send it",
])
def test_negation_before_the_command_governs_it(text):
    assert negated(text, "send it")


@pytest.mark.parametrize("text", [
    "no, send it", "No. Send it", "never mind, send it", "never mind send it", "nope, send it",
    "I can't make it. Send it", "that's not what I meant, send it", "don't worry, send it",
    "not bad, send it", "no problem send it", "no changes, send it", "send it", "please send it",
    "i said send it", "no need, send it",
])
def test_harmless_neighbours_do_not_negate_the_command(text):
    assert not negated(text, "send it")


def test_the_gap_between_negation_and_command_is_bounded():
    # Literal on purpose: a test written in terms of MAX_GAP_WORDS cannot notice
    # the constant being changed.
    assert MAX_GAP_WORDS == 3
    assert negated("don't want you to send it", "send it")            # three words in between
    assert not negated("don't really want you to send it", "send it")  # four


@pytest.mark.parametrize("text", [
    "don't, send it",              # a comma ends the clause: negation is not in the command's clause
    "don't. Send it",
    "do not; send it",
])
def test_a_clause_break_separates_a_negation_from_the_command(text):
    assert not negated(text, "send it")


@pytest.mark.parametrize("text", [
    "send it? No, don't.", "send it, no don't", "send it. Never mind.", "send it, never mind",
    "send it no", "send it, don't", "send it. Nope.", "send it, no, no, no", "send it, no don't please",
    "send it, no wait", "send it. Actually, no.",
])
def test_a_retraction_right_after_the_command_negates_it(text):
    assert negated(text, "send it")


@pytest.mark.parametrize("text", [
    "send it, no problem", "send it, no worries", "send it, not bad", "send it, no changes",
    "send it please", "send it, thanks", "send it now", "send it, wait",
    "send it, I said no",            # negation word, but not right behind the command
    "send it, not later",            # not a pure retraction
    "send it with no changes",
])
def test_a_harmless_tail_does_not_negate_the_command(text):
    assert not negated(text, "send it")


def test_negation_words_inside_the_command_phrase_or_argument_are_ignored():
    assert not negated("no punctuation", "no punctuation")
    assert not negated("please no punctuation", "no punctuation")
    assert not negated("replace yes with no", "replace yes with no")
    assert not negated("replace no with yes", "replace no with yes")
    assert not negated("replace don't with do not", "replace don't with do not")
    # ...but a negation in front of, or retracting, an argument command still counts.
    assert negated("don't replace yes with no", "replace yes with no")
    assert negated("replace yes with no, no don't", "replace yes with no, no don't")


@pytest.mark.parametrize("text,phrase,expected", [
    ("no need to send it", "send it", True),     # "no need to X" really is a negation
    ("no need, send it", "send it", False),      # "no need," is an idiom
    ("send it, no need", "send it", False),
    ("don't send it, no problem", "send it", True),   # an idiom never cancels a real negation
    ("no problem, don't send it", "send it", True),
])
def test_idioms_are_blanked_but_never_cancel_a_real_negation(text, phrase, expected):
    assert negated(text, phrase) is expected


def test_offsets_survive_apostrophe_and_case_folding():
    text = "Don’t SEND it"
    assert negated(text, "SEND it")
    # A character whose lower-case form is longer ("İ" -> "i̇") must not shift the span.
    text = "İ don't send it"
    assert negated(text, "send it")
    assert not negated("İ no, send it", "send it")


def test_no_span_means_the_whole_utterance_is_the_command():
    assert is_negated("no send it")
    assert is_negated("sent it, don't")
    assert not is_negated("sent it")
    assert not is_negated("no, sent it")           # leading interjection
    assert not is_negated("never mind sent it")
    assert not is_negated("sent it, no problem")
    assert not is_negated("")
    assert not is_negated(None)


def test_empty_text_is_never_negated():
    assert not is_negated("", 0, 0)
    assert not is_negated(None, 0, 0)
