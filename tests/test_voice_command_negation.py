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


@pytest.mark.parametrize("phrase", [
    "don't emergency stop", "do not emergency stop", "never emergency stop",
    "BetterFingers, don't emergency stop", "emergency stop? No, don't.", "never mind don't emergency stop",
])
def test_emergency_stop_is_checked_before_any_negation_veto(phrase):
    """A safety valve: a mis-heard negation must never be able to stop it."""
    assert parse_command(phrase).action == "emergency_stop"


# --- false refusals measured against 253a626's whole-utterance veto ----------------------
# Each of these is a plain "send it" with a benign "no"/"not"/"never" idiom around it.

@pytest.mark.parametrize("phrase", [
    "send it, no problem", "not bad, send it", "no changes, send it", "never mind, send it",
    "no, send it", "BetterFingers, send it, no worries",
])
def test_reported_false_refusals_now_resolve_to_send(phrase):
    intent = parse_command(phrase, CONTEXT)
    assert intent is not None and intent.action == "send"
    assert parse_command("BetterFingers, " + phrase.removeprefix("BetterFingers, ")).action == "send"


@pytest.mark.parametrize("action,phrase", PHRASES)
@pytest.mark.parametrize("lead", ["no,", "No.", "never mind,", "Never mind.", "no problem,", "not bad,",
                                  "no worries,", "no changes,", "nothing else,", "don't worry,",
                                  "that's not a problem,", "no rush,"])
def test_benign_lead_in_does_not_refuse_any_command(action, phrase, lead):
    assert parse_command(f"{lead} {phrase}", CONTEXT).action == action
    assert parse_command(f"BetterFingers, {lead} {phrase}").action == action


@pytest.mark.parametrize("action,phrase", PHRASES)
@pytest.mark.parametrize("tail", [", no problem", ", no worries", ", no rush", ", not bad", ", no changes",
                                  ", no need", " no problem", ", nothing else", ", don't worry"])
def test_benign_trailing_idiom_does_not_refuse_any_command(action, phrase, tail):
    assert parse_command(f"{phrase}{tail}", CONTEXT).action == action


@pytest.mark.parametrize("phrase,action", [
    ("send it with no changes", "send"),
    ("no need, send it", "send"),
    ("it's not bad, copy it", "copy"),
    ("not bad but send it", "send"),
    ("make it shorter, no problem", "rewrite_shorter"),
    ("no problem, make it clearer", "rewrite_clearer"),
    ("no, try again", "retry"),
    ("no, read that back", "read_back"),
    ("never mind, switch to formal", "switch_persona"),
    ("no, open settings", "open_settings"),
])
def test_other_benign_phrasing_still_resolves(phrase, action):
    assert parse_command(phrase, CONTEXT).action == action


# --- the veto must still hold wherever the negation really governs the command ----------

@pytest.mark.parametrize("phrase", [
    "send it, no don't", "send it. Never mind.", "send it, never mind", "send it no", "send it, don't",
    "no send it", "no, don't send it", "never mind, don't send it", "no problem, don't send it",
    "don't send it, no problem", "not bad, but don't send it", "send it, no, don't send it",
    "I said don't send it", "please don't send it", "don't ever send it", "do not send it",
    "never mind don't copy it", "no don't copy that", "BetterFingers, no don't send it",
    "don't switch to formal", "do not make it shorter", "never try again", "don't open settings",
    "send it, no wait", "send it. Actually, no.",
])
def test_negation_that_governs_the_command_still_vetoes(phrase):
    assert parse_command(phrase, CONTEXT) is None


def test_negation_only_vetoes_the_command_it_governs():
    assert parse_command("don't send it, just copy it", CONTEXT).action == "copy"
    assert parse_command("send it, don't copy it", CONTEXT).action == "send"


def test_veto_does_not_fall_back_to_a_fuzzy_match():
    # Fuzzy-only inputs (no exact phrase inside): the near-miss resolves without
    # a negation and is refused with one.
    assert parse_command("start recordin", CONTEXT).action == "start_recording"
    assert parse_command("no start recordin", CONTEXT) is None
    assert parse_command("no mak it shorter", CONTEXT) is None
    # A vetoed exact phrase must not be rescued by the fuzzy fallback either.
    assert parse_command("don't send it", CONTEXT) is None


def test_one_shared_rule_decides_parse_command(monkeypatch):
    from backend.commands import negation

    monkeypatch.setattr(negation, "is_negated", lambda *a, **k: True)
    assert parse_command("send it", CONTEXT) is None
    assert parse_command("sent it", CONTEXT) is None
    assert parse_command("switch to formal", CONTEXT) is None
    assert parse_command("emergency stop").action == "emergency_stop"

    monkeypatch.setattr(negation, "is_negated", lambda *a, **k: False)
    assert parse_command("don't send it", CONTEXT).action == "send"
