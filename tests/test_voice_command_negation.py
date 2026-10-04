"""Negation must suppress both contained matches and fuzzy command fallback."""
import pytest
from backend.commands.voice_commands import parse_command, _VOCABULARY

CONTEXT = {"command_mode_on": True}
RISKY = {"send", "delete_history", "cancel", "copy"}
PHRASES = [(action, phrase) for action, _, phrases, _ in _VOCABULARY
           if action in RISKY for phrase in phrases]


@pytest.mark.parametrize("action,phrase", PHRASES)
def test_positive_commands_still_resolve(action, phrase):
    assert parse_command(phrase, CONTEXT).action == action


@pytest.mark.parametrize("action,phrase", PHRASES)
@pytest.mark.parametrize("negation", ["don't", "do not", "never", "no", "dont", "don’t",
                                     "can't", "cannot", "won't", "shouldn't", "couldn’t"])
def test_negated_commands_are_inert(action, phrase, negation):
    assert parse_command(f"{negation} {phrase}", CONTEXT) is None
    assert parse_command(f"BetterFingers, {negation} {phrase}") is None


@pytest.mark.parametrize("phrase", [
    "don't send it", "do not send", "don't delete that", "never mind don't send",
    "no don't press enter", "don't delete history", "don't submit", "don't clear that",
    "do not undo", "don't discard it", "not send that", "send it? No, don't.",
])
def test_reported_negations_do_not_fire(phrase):
    assert parse_command(phrase, CONTEXT) is None


@pytest.mark.parametrize("phrase", ["submit", "press enter", "delete that", "clear that", "undo"])
def test_unsupported_positive_actions_are_not_added(phrase):
    assert parse_command(phrase, CONTEXT) is None


def test_emergency_stop_remains_unconditional():
    assert parse_command("no, emergency stop").action == "emergency_stop"
