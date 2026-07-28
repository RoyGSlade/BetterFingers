"""Contact interview tests (Stage 11b).

Pure-Python: navigation is deterministic and needs no model, which is the whole
reason the design's "must work without a model loaded" constraint is satisfiable
at all. The compile tests inject a fake ``generate`` rather than touching a real
engine.
"""

import pytest

from backend.services.contact_interview import (
    CONTACT_QUESTIONS,
    PUSHBACK_NAME_REQUIRED,
    build_compile_prompt,
    compile_contact,
    compile_without_model,
    new_session,
    next_prompt,
    parse_compile_response,
    submit_answer,
)


def run_interview(answers):
    """Drive a session through the given answers, in question order."""
    session = new_session()
    for answer in answers:
        submit_answer(session, answer)
    return session


# --- navigation --------------------------------------------------------------


def test_the_first_question_asks_for_a_name():
    """Name first so an interview abandoned after one answer still produces
    something saveable."""
    assert CONTACT_QUESTIONS[0]["id"] == "name"
    assert next_prompt(new_session())["id"] == "name"


def test_questions_carry_their_position():
    question = next_prompt(new_session())
    assert question["index"] == 0
    assert question["total"] == len(CONTACT_QUESTIONS)


def test_a_blank_name_is_pushed_back_on():
    session = new_session()
    result = submit_answer(session, "   ")
    assert result["pushback"] == PUSHBACK_NAME_REQUIRED
    assert result["done"] is False
    assert next_prompt(session)["id"] == "name", "the interview must not advance past it"


def test_every_other_question_accepts_a_blank_answer():
    """Rule 2's friction budget: a user with nothing to say will just press send
    on an empty box, so there is no skip verb to discover."""
    session = new_session()
    submit_answer(session, "Priya")
    for _ in range(len(CONTACT_QUESTIONS) - 1):
        result = submit_answer(session, "")
        assert result["pushback"] is None
    assert session["done"] is True


def test_vague_answers_are_not_challenged():
    """Deliberately lighter than the Persona Foundry. A vague persona is
    useless; "my brother" is a complete answer about a person."""
    session = new_session()
    submit_answer(session, "Sam")
    result = submit_answer(session, "idk")
    assert result["pushback"] is None
    assert session["answers"]["relationship"] == "idk"


def test_the_interview_completes_and_stops_serving_questions():
    session = run_interview(["Priya", "my manager", "direct", "no jargon", "Formal"])
    assert session["done"] is True
    assert next_prompt(session) is None


def test_answering_past_the_end_is_harmless():
    session = run_interview(["Priya", "", "", "", ""])
    assert submit_answer(session, "extra") == {"pushback": None, "done": True}


def test_next_prompt_tolerates_junk_sessions():
    assert next_prompt(None) is None
    assert next_prompt({}) is not None  # an empty dict is a fresh session
    assert submit_answer(None, "x") == {"pushback": None, "done": False}


# --- compile prompt ----------------------------------------------------------


def test_the_compile_prompt_never_carries_the_name():
    """The model turns "how do I talk to them" into prose about register. It
    can do that without being told who they are, so the name never enters a
    prompt and therefore never enters what the model layer logs or caches."""
    session = run_interview(["Priya Raman", "my manager", "direct", "no jargon", ""])
    prompt = build_compile_prompt(session["answers"])
    assert "Priya" not in prompt
    assert "Raman" not in prompt
    assert "my manager" in prompt
    assert "no jargon" in prompt


def test_the_compile_prompt_handles_a_name_only_interview():
    prompt = build_compile_prompt({"name": "Sam"})
    assert "nothing beyond a name" in prompt
    assert "Sam" not in prompt


# --- response parsing --------------------------------------------------------


def test_parse_pulls_both_sections():
    parsed = parse_compile_response("TONE: Warm and brief.\nNOTES: Prefers numbers.")
    assert parsed["tone_guidance"] == "Warm and brief."
    assert parsed["notes"] == "Prefers numbers."


def test_parse_tolerates_markdown_and_a_missing_section():
    parsed = parse_compile_response("## **TONE:** Blunt.\nStill blunt.")
    assert parsed["tone_guidance"] == "Blunt. Still blunt."
    assert parsed["notes"] == ""


def test_parse_discards_chatter_before_the_first_label():
    parsed = parse_compile_response("Sure! Here you go.\nTONE: Casual.")
    assert parsed["tone_guidance"] == "Casual."


def test_parse_of_junk_yields_empty_fields():
    for junk in (None, "", "no labels here at all"):
        assert parse_compile_response(junk) == {"tone_guidance": "", "notes": ""}


# --- compile -----------------------------------------------------------------


def test_compile_without_a_model_keeps_the_users_own_words():
    """The fallback for "the model could not help" must never be "your answers
    are gone" -- that is the whole reason this degrades instead of blocking."""
    session = run_interview(["Priya", "my manager", "Direct, no filler.", "Never guess at numbers.", ""])
    result = compile_contact(session)

    assert result["used_model"] is False
    assert result["contact"]["name"] == "Priya"
    assert result["contact"]["relationship"] == "my manager"
    assert result["contact"]["tone_guidance"] == "Direct, no filler."
    assert result["contact"]["notes"] == "Never guess at numbers."


def test_compile_with_a_model_uses_its_prose():
    session = run_interview(["Priya", "my manager", "direct", "no jargon", ""])
    result = compile_contact(session, generate=lambda _p: "TONE: Direct and unpadded.\nNOTES: Avoid jargon.")

    assert result["used_model"] is True
    assert result["contact"]["tone_guidance"] == "Direct and unpadded."
    assert result["contact"]["notes"] == "Avoid jargon."
    assert result["warnings"] == []


def test_a_failing_model_degrades_instead_of_raising():
    def explode(_prompt):
        raise RuntimeError("no model loaded")

    session = run_interview(["Priya", "my manager", "Direct.", "No jargon.", ""])
    result = compile_contact(session, generate=explode)

    assert result["used_model"] is False
    assert result["contact"]["tone_guidance"] == "Direct."
    assert result["contact"]["notes"] == "No jargon."
    assert any("no model loaded" in w for w in result["warnings"])


def test_a_blank_model_response_does_not_erase_the_answers():
    session = run_interview(["Priya", "my manager", "Direct.", "No jargon.", ""])
    result = compile_contact(session, generate=lambda _p: "   ")

    assert result["used_model"] is False
    assert result["contact"]["tone_guidance"] == "Direct."
    assert result["warnings"], "a silently-empty compile should be reported"


def test_a_half_blank_model_response_fills_only_what_it_answered():
    session = run_interview(["Priya", "my manager", "Direct.", "No jargon.", ""])
    result = compile_contact(session, generate=lambda _p: "TONE: Crisp and warm.\nNOTES:")

    assert result["contact"]["tone_guidance"] == "Crisp and warm."
    assert result["contact"]["notes"] == "No jargon.", "the user's own note must survive"


def test_a_name_only_interview_still_compiles():
    """Quitting halfway must still save something usable (design doc §10)."""
    session = new_session()
    submit_answer(session, "Sam")
    result = compile_contact(session)

    assert result["contact"]["name"] == "Sam"
    assert result["contact"]["relationship"] == ""
    assert result["contact"]["preferred_persona"] is None


def test_no_preferred_persona_compiles_to_null_not_empty_string():
    session = run_interview(["Sam", "", "", "", "   "])
    assert compile_contact(session)["contact"]["preferred_persona"] is None


def test_compile_of_a_junk_session_does_not_raise():
    for junk in (None, {}, {"answers": "nope"}):
        result = compile_contact(junk)
        assert result["contact"]["name"] == ""


def test_compile_without_model_tolerates_junk():
    assert compile_without_model(None) == {"tone_guidance": "", "notes": ""}
