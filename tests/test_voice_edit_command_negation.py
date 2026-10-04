"""Negation for the editing commands that run DURING DICTATION.

``voice_edit_commands.parse_edit_command`` (the "scratch that" check in the
dictation pipeline) and ``apply_inline_edits`` (the in-utterance edits) used to
fire on negated phrasing: "don't scratch that" scratched, "do not delete last
word" deleted a word. They now share one negation rule with ``parse_command``
(``backend/commands/negation.py``).

Two failure modes are pinned here, because a rule that fixes only the first
creates the second:

* false fire    -- a negated command still executes (the original bug)
* false refusal -- benign phrasing ("no, scratch that", "scratch that, no
  problem") is refused as if it were a negation
"""
import pytest

from backend.commands import voice_edit_commands
from backend.commands.voice_edit_commands import (
    _COMMANDS,
    apply_inline_edits,
    parse_edit_command,
)

# (spoken phrase, action, expected args). Every command parse_edit_command supports.
EDIT_COMMANDS = [
    ("scratch that", "scratch_that", {}),
    ("undo that", "scratch_that", {}),
    ("undo last sentence", "delete_last_sentence", {}),
    ("delete last word", "delete_last_word", {}),
    ("quote that", "quote_that", {}),
    ("bullet list", "bullet_list", {}),
    ("numbered list", "numbered_list", {}),
    ("new heading", "new_heading", {}),
    ("no punctuation", "no_punctuation", {}),
    ("literal mode", "literal_mode", {}),
    ("replace foo with bar", "replace", {"old": "foo", "new": "bar"}),
    ("capitalize the word london", "capitalize_word", {"word": "london"}),
    ("capitalize london", "capitalize_word", {"word": "london"}),
]
IDS = [phrase for phrase, _action, _args in EDIT_COMMANDS]

# Commands whose phrase has no free-text argument, so a trailing idiom stays a
# separate clause instead of being swallowed into the argument.
FIXED_PHRASE_COMMANDS = [c for c in EDIT_COMMANDS if not c[2]]

NEGATIONS = [
    "don't", "do not", "never", "no don't", "no, don't", "no no don't", "dont", "don’t",
    "can't", "can’t", "cannot", "won't", "won’t", "shouldn't", "couldn’t",
    "never mind don't", "never mind, don't", "please don't", "don't ever", "do not ever",
    "I said don't", "I told you not to", "nah don't",
]


def test_table_covers_every_supported_edit_command():
    """If someone adds a command to the parser, this forces the tables above to cover it."""
    supported = {action for _pattern, action in _COMMANDS} | {"replace", "capitalize_word"}
    assert supported <= {action for _phrase, action, _args in EDIT_COMMANDS}


@pytest.mark.parametrize("phrase,action,args", EDIT_COMMANDS, ids=IDS)
def test_positive_commands_still_fire(phrase, action, args):
    cmd = parse_edit_command(phrase)
    assert cmd is not None and cmd.action == action
    assert cmd.args == args


@pytest.mark.parametrize("negation", NEGATIONS)
@pytest.mark.parametrize("phrase,action,args", EDIT_COMMANDS, ids=IDS)
def test_negated_edit_commands_do_not_fire(phrase, action, args, negation):
    assert parse_edit_command(f"{negation} {phrase}") is None
    assert parse_edit_command(f"{negation.upper()} {phrase.upper()}") is None


@pytest.mark.parametrize("negation", NEGATIONS)
@pytest.mark.parametrize("phrase,action,args", EDIT_COMMANDS, ids=IDS)
def test_negated_edit_commands_leave_dictated_text_untouched(phrase, action, args, negation):
    """Falling through to normal dictation means the words survive verbatim --
    the inline pass must not execute what the first parser vetoed."""
    text = f"{negation} {phrase}"
    assert apply_inline_edits(text) == text


@pytest.mark.parametrize("phrase,text", [
    ("don't scratch that", "don't scratch that"),
    ("no don't undo that", "no don't undo that"),
    ("do not delete last word", "do not delete last word"),
    ("never mind don't scratch that", "never mind don't scratch that"),
])
def test_reported_false_fires_are_closed(phrase, text):
    assert parse_edit_command(phrase) is None
    assert apply_inline_edits(text) == text


# --- negation after the command (retraction), and negation inside a long dictation ---

@pytest.mark.parametrize("text", [
    "scratch that? No, don't.",
    "scratch that, no don't",
    "scratch that, never mind",
    "scratch that no",
    "scratch that, no wait",
    "undo that. Actually, no.",
    "undo that. Nope.",
    "delete last word, don't",
    "replace foo with bar, no don't",
    "capitalize london. No, don't.",
])
def test_retraction_after_the_command_vetoes_it(text):
    assert parse_edit_command(text) is None


@pytest.mark.parametrize("text", [
    "I told you not to scratch that",
    "she did not want to quote that",
    "we should not replace the old pump with a new one",
    "I would not capitalize london here",
])
def test_negation_governing_the_command_inside_a_longer_sentence_vetoes_it(text):
    assert parse_edit_command(text) is None
    assert apply_inline_edits(text) == text


# --- false refusals: benign phrasing must still fire -----------------------------------

@pytest.mark.parametrize("phrase,action,args", EDIT_COMMANDS, ids=IDS)
@pytest.mark.parametrize("lead", ["no,", "No.", "never mind,", "Never mind.", "no problem,", "not bad,",
                                  "no worries,", "nothing else,", "don't worry,", "no changes,"])
def test_benign_lead_in_does_not_refuse_the_command(phrase, action, args, lead):
    cmd = parse_edit_command(f"{lead} {phrase}")
    assert cmd is not None and cmd.action == action


@pytest.mark.parametrize("phrase,action,args", FIXED_PHRASE_COMMANDS,
                         ids=[c[0] for c in FIXED_PHRASE_COMMANDS])
@pytest.mark.parametrize("tail", [", no problem", ", no worries", ", no rush", ", not bad", ", no changes",
                                  ", no need", " no problem"])
def test_benign_trailing_idiom_does_not_refuse_the_command(phrase, action, args, tail):
    cmd = parse_edit_command(f"{phrase}{tail}")
    assert cmd is not None and cmd.action == action


@pytest.mark.parametrize("text,action", [
    # The negation belongs to a different clause than the command.
    ("I can't make it tomorrow. Scratch that.", "scratch_that"),
    ("that's not what I meant, scratch that", "scratch_that"),
    ("I do not think so, scratch that", "scratch_that"),
    ("no, no, scratch that", "scratch_that"),
    ("don't worry, scratch that", "scratch_that"),
    # The command's own words contain "no".
    ("please no punctuation", "no_punctuation"),
    ("no punctuation please", "no_punctuation"),
    ("scratch that, no punctuation", "scratch_that"),
    # A negation word inside a command's argument is content, not a veto.
    ("replace yes with no", "replace"),
    ("replace no with yes", "replace"),
    ("replace don't with do not", "replace"),
])
def test_unrelated_negation_does_not_refuse_the_command(text, action):
    cmd = parse_edit_command(text)
    assert cmd is not None and cmd.action == action


def test_replace_argument_survives_a_negation_word():
    cmd = parse_edit_command("replace yes with no")
    assert cmd.args == {"old": "yes", "new": "no"}


def test_inline_edits_still_apply_when_the_negation_is_elsewhere():
    assert apply_inline_edits("I can't stay. The quick brown fox delete last word") == "I can't stay. The quick brown"
    assert apply_inline_edits("no, hello world quote that") == '"no, hello world"'
    assert apply_inline_edits("todo items bullet list, no problem").startswith("todo items\n- ")


def test_negation_only_vetoes_the_command_it_governs():
    # "scratch that" is negated; "bullet list" is a separate clause and is not.
    cmd = parse_edit_command("don't scratch that, bullet list")
    assert cmd is not None and cmd.action == "bullet_list"


def test_one_shared_rule_decides_both_edit_paths(monkeypatch):
    """parse_edit_command and apply_inline_edits must consult the SAME helper:
    forcing it to 'negated' disables every edit, forcing 'not negated' fires them."""
    from backend.commands import negation

    monkeypatch.setattr(negation, "is_negated", lambda *a, **k: True)
    assert parse_edit_command("scratch that") is None
    assert apply_inline_edits("the quick brown fox delete last word") == "the quick brown fox delete last word"

    monkeypatch.setattr(negation, "is_negated", lambda *a, **k: False)
    assert parse_edit_command("don't scratch that").action == "scratch_that"
    # "delete last word" really deletes the word before it, here "don't".
    assert apply_inline_edits("don't delete last word") == ""


def test_settings_test_panel_preview_reports_no_command_for_a_negated_phrase():
    """voice_preview feeds the Voice Control test panel from both parsers."""
    from backend.commands.voice_preview import preview

    negated = preview("don't scratch that", {"command_mode_on": True})
    assert negated["edit_command"] is None and negated["app_command"] is None
    benign = preview("no, scratch that", {"command_mode_on": True})
    assert benign["edit_command"]["action"] == "scratch_that"


def test_module_imports_the_shared_helper():
    from backend.commands import negation, voice_commands

    assert voice_edit_commands.negation is negation
    assert voice_commands.negation is negation
