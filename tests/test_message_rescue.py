"""Tests for backend.services.message_rescue (Phase 2 Wave 2B, F2.7).

All transcript/context text below is hand-authored synthetic office-style
text written for this repository, matching docs/TEST_DATA_POLICY.md's
provenance rule for Message Rescue fixtures — no real person's speech, no
PII-shaped strings. No FastAPI, model, or network dependency: every model
call is a plain injected function.
"""

import json

import pytest

from backend.domain.contracts import MessageRescueResult, SpeechSignals
from backend.services.message_rescue import (
    MAX_RAW_RESPONSE_CHARS,
    build_rescue_prompt,
    check_preservation,
    parse_rescue_response,
    rescue_message,
)

TRANSCRIPT = (
    "I can meet on Monday at 3 PM near Chicago, but I won't bring the report. "
    "I'll send it by 2026-07-20 or check https://example.com/notes. "
    "My friend Maria said this isn't final yet."
)

FAITHFUL_OK = TRANSCRIPT

CLEARER_OK = (
    "I can meet Monday at 3 PM near Chicago, though I won't have the report ready yet. "
    "I'll still send it by 2026-07-20 — see https://example.com/notes. "
    "My friend Maria says this isn't final yet."
)

ALTERNATE_OK = (
    "Monday at 3 PM works — I can meet near Chicago, but I won't bring the report yet. "
    "I'll send it by 2026-07-20; check https://example.com/notes. "
    "My friend Maria says this isn't final yet."
)


def _valid_payload(faithful=FAITHFUL_OK, clearer=CLEARER_OK, alternate=ALTERNATE_OK, **assessment_overrides):
    assessment = {
        "intent": "confirm a meeting and set expectations about the report",
        "ambiguity_risk": "low",
        "missing_details": [],
        "clarification_question": "",
    }
    assessment.update(assessment_overrides)
    return json.dumps({"assessment": assessment, "variants": {"faithful": faithful, "clearer": clearer, "alternate": alternate}})


def _signals(confidence=0.8, arousal=0.4, urgency=0.5, hesitation=0.2, pause_count=1, filler_count=0, self_correction_count=0):
    return SpeechSignals(
        words_per_minute=140.0,
        speaking_ratio=0.8,
        pause_count=pause_count,
        pause_ratio=0.1,
        mean_pause_s=0.6,
        longest_pause_s=0.6,
        filler_count=filler_count,
        self_correction_count=self_correction_count,
        energy_mean=0.02,
        energy_variation=0.1,
        delivery_axes={"arousal": arousal, "urgency": urgency, "hesitation": hesitation},
        evidence=["140 wpm across 30 words over 12.9s"],
        confidence=confidence,
    )


class _CallCounter:
    def __init__(self, fn):
        self.fn = fn
        self.calls = 0

    def __call__(self, messages):
        self.calls += 1
        return self.fn(messages)


def _fixed(text):
    return _CallCounter(lambda messages: text)


def _raiser(exc):
    def fn(messages):
        raise exc

    return _CallCounter(fn)


# --- build_rescue_prompt -----------------------------------------------------


def test_build_rescue_prompt_includes_transcript():
    messages = build_rescue_prompt(TRANSCRIPT, _signals())
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
    assert "TRANSCRIPT:" in messages[-1]["content"]
    assert TRANSCRIPT in messages[-1]["content"]


def test_build_rescue_prompt_no_context_omits_context_block():
    messages = build_rescue_prompt(TRANSCRIPT, _signals(), context_text=None)
    assert "CONTEXT" not in messages[-1]["content"]


def test_build_rescue_prompt_context_present_and_truncated():
    long_context = "z" * 5000
    messages = build_rescue_prompt(TRANSCRIPT, _signals(), context_text=long_context)
    content = messages[-1]["content"]
    assert "CONTEXT (for interpretation only" in content
    assert "do not copy into your output" in content
    assert content.count("z") == 2000


def test_build_rescue_prompt_persona_voice_included():
    messages = build_rescue_prompt(TRANSCRIPT, _signals(), persona={"prompt": "Be warm and concise."})
    assert "VOICE: Be warm and concise." in messages[0]["content"]


def test_build_rescue_prompt_examples_become_turns():
    examples = [{"raw": "raw one", "out": "out one"}, {"raw": "raw two", "out": "out two"}]
    messages = build_rescue_prompt(TRANSCRIPT, _signals(), examples=examples)
    roles = [m["role"] for m in messages]
    assert roles[1:5] == ["user", "assistant", "user", "assistant"]
    assert messages[1]["content"] == "raw one"
    assert messages[2]["content"] == "out one"


def test_build_rescue_prompt_examples_capped():
    examples = [{"raw": f"r{i}", "out": f"o{i}"} for i in range(20)]
    messages = build_rescue_prompt(TRANSCRIPT, _signals(), examples=examples, max_examples=2)
    # system + 2*2 example turns + final user turn = 6
    assert len(messages) == 6


def test_build_rescue_prompt_persona_few_shot_used_when_examples_omitted():
    persona = {"prompt": "", "few_shot": [{"raw": "hi", "out": "hello"}]}
    messages = build_rescue_prompt(TRANSCRIPT, _signals(), persona=persona)
    assert messages[1]["content"] == "hi"
    assert messages[2]["content"] == "hello"


def test_build_rescue_prompt_signal_summary_never_echoes_transcript_text():
    messages = build_rescue_prompt(TRANSCRIPT, _signals())
    signal_line = next(part for part in messages[-1]["content"].split("\n\n") if part.startswith("DELIVERY SIGNAL SUMMARY"))
    assert "Chicago" not in signal_line
    assert "Maria" not in signal_line


# --- parse_rescue_response ---------------------------------------------------


def test_parse_valid_bare_json():
    parsed = parse_rescue_response(json.dumps({"variants": {"faithful": "hi"}}))
    assert parsed == {"variants": {"faithful": "hi"}}


def test_parse_fenced_json():
    raw = "```json\n" + json.dumps({"a": 1}) + "\n```"
    assert parse_rescue_response(raw) == {"a": 1}


def test_parse_fenced_json_no_language_tag():
    raw = "```\n" + json.dumps({"a": 1}) + "\n```"
    assert parse_rescue_response(raw) == {"a": 1}


def test_parse_noisy_wrapped_json():
    raw = "Sure, here is the result:\n" + json.dumps({"a": 1}) + "\nHope that helps!"
    assert parse_rescue_response(raw) == {"a": 1}


def test_parse_malformed_returns_none():
    assert parse_rescue_response("not json at all {{{") is None


def test_parse_empty_returns_none():
    assert parse_rescue_response("") is None
    assert parse_rescue_response("   ") is None
    assert parse_rescue_response(None) is None


def test_parse_oversize_returns_none():
    raw = '{"a": "' + ("x" * (MAX_RAW_RESPONSE_CHARS + 10)) + '"}'
    assert parse_rescue_response(raw) is None


def test_parse_non_dict_top_level_returns_none():
    assert parse_rescue_response(json.dumps([1, 2, 3])) is None
    assert parse_rescue_response(json.dumps("just a string")) is None


def test_parse_too_deep_returns_none():
    nested = 1
    for _ in range(9):
        nested = {"n": nested}
    assert parse_rescue_response(json.dumps(nested)) is None


def test_parse_within_depth_limit_accepted():
    nested = 1
    for _ in range(3):
        nested = {"n": nested}
    assert parse_rescue_response(json.dumps(nested)) is not None


# --- check_preservation -------------------------------------------------------


def test_preservation_numbers_pass():
    checks = check_preservation("Bring 3 copies.", "Please bring 3 copies today.")
    assert any(c["name"].endswith("/numbers") and c["passed"] for c in checks)


def test_preservation_numbers_fail():
    checks = check_preservation("Bring 3 copies.", "Please bring some copies.")
    numbers_check = next(c for c in checks if c["name"].endswith("/numbers"))
    assert numbers_check["passed"] is False
    assert "3" in numbers_check["detail"]


def test_preservation_dates_fail():
    checks = check_preservation("See you Monday.", "See you soon.")
    dates_check = next(c for c in checks if c["name"].endswith("/dates"))
    assert dates_check["passed"] is False


def test_preservation_dates_pass():
    checks = check_preservation("See you Monday.", "Monday works for me.")
    dates_check = next(c for c in checks if c["name"].endswith("/dates"))
    assert dates_check["passed"] is True


def test_preservation_urls_fail():
    checks = check_preservation("Visit https://example.com/x for info.", "Visit the site for info.")
    urls_check = next(c for c in checks if c["name"].endswith("/urls"))
    assert urls_check["passed"] is False


def test_preservation_urls_pass():
    checks = check_preservation("Visit https://example.com/x for info.", "Info is at https://example.com/x.")
    urls_check = next(c for c in checks if c["name"].endswith("/urls"))
    assert urls_check["passed"] is True


def test_preservation_negation_fail():
    checks = check_preservation("I will not attend.", "I will attend.")
    negation_check = next(c for c in checks if c["name"].endswith("/negation"))
    assert negation_check["passed"] is False


def test_preservation_negation_pass():
    checks = check_preservation("I will not attend.", "I will not be able to attend.")
    negation_check = next(c for c in checks if c["name"].endswith("/negation"))
    assert negation_check["passed"] is True


def test_preservation_modality_fail():
    checks = check_preservation("You must submit it today.", "Please submit it today.")
    modality_check = next(c for c in checks if c["name"].endswith("/modality"))
    assert modality_check["passed"] is False


def test_preservation_modality_pass():
    checks = check_preservation("You must submit it today.", "You must submit it by end of day.")
    modality_check = next(c for c in checks if c["name"].endswith("/modality"))
    assert modality_check["passed"] is True


def test_preservation_commitments_fail():
    checks = check_preservation("I will call you tomorrow.", "Someone will call you tomorrow.")
    commitment_check = next(c for c in checks if c["name"].endswith("/commitments"))
    assert commitment_check["passed"] is False


def test_preservation_commitments_pass():
    checks = check_preservation("I will call you tomorrow.", "I will definitely call you tomorrow.")
    commitment_check = next(c for c in checks if c["name"].endswith("/commitments"))
    assert commitment_check["passed"] is True


def test_preservation_names_fail():
    checks = check_preservation("I heard Maria will call you.", "I heard she will call you.")
    names_check = next(c for c in checks if c["name"].endswith("/names"))
    assert names_check["passed"] is False
    assert "Maria" in names_check["detail"]


def test_preservation_names_pass():
    checks = check_preservation("I heard Maria will call you.", "You will hear from Maria soon.")
    names_check = next(c for c in checks if c["name"].endswith("/names"))
    assert names_check["passed"] is True


def test_preservation_no_category_present_yields_no_checks():
    checks = check_preservation("hello there friend", "hi there buddy")
    assert checks == []


def test_preservation_sentence_initial_word_not_treated_as_name():
    # "Please" is sentence-initial capitalization only, not a proper noun.
    checks = check_preservation("Please call Maria.", "Contact Maria please.")
    names_check = next(c for c in checks if c["name"].endswith("/names"))
    assert names_check["passed"] is True
    assert "Please" not in names_check["detail"]


# --- rescue_message: happy path ----------------------------------------------


def test_rescue_message_valid_json_all_variants_preserved():
    call_fn = _fixed(_valid_payload())
    result = rescue_message(TRANSCRIPT, _signals(), call_fn=call_fn)
    assert isinstance(result, MessageRescueResult)
    assert result.variants["faithful"] == FAITHFUL_OK
    assert result.variants["clearer"] == CLEARER_OK
    assert result.variants["alternate"] == ALTERNATE_OK
    assert result.warnings == []
    assert all(c["passed"] for c in result.preservation_checks)
    assert result.assessment["intent"]
    assert call_fn.calls == 1


def test_rescue_message_delivery_derived_from_signals_not_model():
    call_fn = _fixed(_valid_payload())
    signals = _signals(confidence=0.42, arousal=0.9, urgency=0.1, hesitation=0.05)
    result = rescue_message(TRANSCRIPT, signals, call_fn=call_fn)
    assert result.delivery["confidence"] == pytest.approx(0.42)
    assert any("high energy" in label for label in result.delivery["labels"])
    assert any("low urgency" in label for label in result.delivery["labels"])


def test_rescue_message_no_signals_yields_empty_delivery():
    call_fn = _fixed(_valid_payload())
    result = rescue_message(TRANSCRIPT, None, call_fn=call_fn)
    assert result.delivery == {"labels": [], "confidence": 0.0, "evidence": []}


def test_rescue_message_clarification_present():
    payload = _valid_payload(missing_details=["which report version"], clarification_question="Which report version do you mean?")
    call_fn = _fixed(payload)
    result = rescue_message(TRANSCRIPT, _signals(), call_fn=call_fn)
    assert result.assessment["clarification_question"] == "Which report version do you mean?"
    assert result.assessment["missing_details"] == ["which report version"]


def test_rescue_message_no_clarification():
    call_fn = _fixed(_valid_payload())
    result = rescue_message(TRANSCRIPT, _signals(), call_fn=call_fn)
    assert result.assessment["clarification_question"] == ""
    assert result.assessment["missing_details"] == []


def test_rescue_message_fenced_json_parsed():
    fenced = "```json\n" + _valid_payload() + "\n```"
    call_fn = _fixed(fenced)
    result = rescue_message(TRANSCRIPT, _signals(), call_fn=call_fn)
    assert result.variants["faithful"] == FAITHFUL_OK
    assert result.warnings == []


def test_rescue_message_noisy_wrapped_json_parsed():
    noisy = "Here is the JSON you asked for:\n" + _valid_payload() + "\nLet me know if you need anything else."
    call_fn = _fixed(noisy)
    result = rescue_message(TRANSCRIPT, _signals(), call_fn=call_fn)
    assert result.variants["faithful"] == FAITHFUL_OK
    assert result.warnings == []


# --- rescue_message: fallback paths -------------------------------------------


def test_rescue_message_empty_transcript_never_calls_model():
    call_fn = _fixed(_valid_payload())
    result = rescue_message("   ", _signals(), call_fn=call_fn)
    assert result.variants == {"faithful": "", "clearer": "", "alternate": ""}
    assert result.warnings == ["empty transcript"]
    assert call_fn.calls == 0


def test_rescue_message_malformed_output_falls_back_to_faithful():
    call_fn = _fixed("not json at all {{{")
    result = rescue_message(TRANSCRIPT, _signals(), call_fn=call_fn)
    assert result.variants["faithful"] == TRANSCRIPT
    assert result.variants["clearer"] == ""
    assert result.variants["alternate"] == ""
    assert result.warnings == ["model output was not valid JSON"]


def test_rescue_message_empty_output_falls_back():
    call_fn = _fixed("")
    result = rescue_message(TRANSCRIPT, _signals(), call_fn=call_fn)
    assert result.variants["faithful"] == TRANSCRIPT
    assert result.warnings == ["empty model output"]


def test_rescue_message_whitespace_only_output_falls_back():
    call_fn = _fixed("   \n  ")
    result = rescue_message(TRANSCRIPT, _signals(), call_fn=call_fn)
    assert result.warnings == ["empty model output"]


def test_rescue_message_oversize_output_falls_back():
    call_fn = _fixed('{"variants": {"faithful": "' + ("x" * (MAX_RAW_RESPONSE_CHARS + 10)) + '"}}')
    result = rescue_message(TRANSCRIPT, _signals(), call_fn=call_fn)
    assert result.variants["faithful"] == TRANSCRIPT
    assert result.warnings == ["model output exceeded size limit"]


def test_rescue_message_too_deep_output_falls_back():
    nested = 1
    for _ in range(9):
        nested = {"n": nested}
    call_fn = _fixed(json.dumps({"variants": {"faithful": "irrelevant"}, "deep": nested}))
    result = rescue_message(TRANSCRIPT, _signals(), call_fn=call_fn)
    assert result.variants["faithful"] == TRANSCRIPT
    assert result.warnings == ["model output was not valid JSON"]


def test_rescue_message_timeout_falls_back():
    call_fn = _raiser(TimeoutError("read timed out"))
    result = rescue_message(TRANSCRIPT, _signals(), call_fn=call_fn)
    assert result.variants["faithful"] == TRANSCRIPT
    assert result.warnings[0].startswith("model call timed out")


def test_rescue_message_generic_call_failure_falls_back():
    call_fn = _raiser(ConnectionError("boom"))
    result = rescue_message(TRANSCRIPT, _signals(), call_fn=call_fn)
    assert result.variants["faithful"] == TRANSCRIPT
    assert result.warnings[0].startswith("model call failed")


def test_rescue_message_wrong_types_coerced_without_crashing():
    payload = json.dumps(
        {
            "assessment": ["not", "a", "dict"],
            "variants": "not a dict either",
        }
    )
    call_fn = _fixed(payload)
    result = rescue_message(TRANSCRIPT, _signals(), call_fn=call_fn)
    assert result.variants["faithful"] == TRANSCRIPT
    assert result.variants["clearer"] == ""
    assert result.assessment == {"intent": "", "ambiguity_risk": "", "missing_details": [], "clarification_question": ""}


def test_rescue_message_missing_details_wrong_type_coerced_to_empty_list():
    payload = _valid_payload(missing_details="not a list")
    call_fn = _fixed(payload)
    result = rescue_message(TRANSCRIPT, _signals(), call_fn=call_fn)
    assert result.assessment["missing_details"] == []


# --- rescue_message: preservation violations ----------------------------------


def test_rescue_message_faithful_preservation_violation_replaced_with_raw():
    payload = _valid_payload(faithful="I will meet you sometime, no promises on the report.")
    call_fn = _fixed(payload)
    result = rescue_message(TRANSCRIPT, _signals(), call_fn=call_fn)
    assert result.variants["faithful"] == TRANSCRIPT
    assert any("faithful variant failed preservation checks" in w for w in result.warnings)
    assert any(not c["passed"] for c in result.preservation_checks if c["name"].startswith("faithful/"))


def test_rescue_message_clearer_preservation_violation_dropped():
    payload = _valid_payload(clearer="I'll be around at some point, but the report might slip.")
    call_fn = _fixed(payload)
    result = rescue_message(TRANSCRIPT, _signals(), call_fn=call_fn)
    assert result.variants["faithful"] == FAITHFUL_OK
    assert result.variants["clearer"] == ""
    assert any("clearer variant dropped" in w for w in result.warnings)


def test_rescue_message_alternate_preservation_violation_dropped():
    payload = _valid_payload(alternate="Maybe we can connect eventually about that document.")
    call_fn = _fixed(payload)
    result = rescue_message(TRANSCRIPT, _signals(), call_fn=call_fn)
    assert result.variants["alternate"] == ""
    assert any("alternate variant dropped" in w for w in result.warnings)


def test_rescue_message_context_leak_drops_variant():
    context_text = "The client asked specifically about the Q3 budget shortfall and wants numbers by Friday, no exceptions."
    leaking_alternate = ALTERNATE_OK + " " + context_text
    payload = _valid_payload(alternate=leaking_alternate)
    call_fn = _fixed(payload)
    result = rescue_message(TRANSCRIPT, _signals(), call_fn=call_fn, context_text=context_text)
    assert result.variants["alternate"] == ""
    assert any("alternate variant dropped" in w for w in result.warnings)
    assert any(c["name"] == "alternate/context_not_copied" for c in result.preservation_checks)


def test_rescue_message_context_not_leaked_when_only_interpreted():
    context_text = "The client asked specifically about the Q3 budget shortfall and wants numbers by Friday, no exceptions."
    call_fn = _fixed(_valid_payload())
    result = rescue_message(TRANSCRIPT, _signals(), call_fn=call_fn, context_text=context_text)
    assert result.variants["clearer"] == CLEARER_OK
    assert not any(c["name"].endswith("/context_not_copied") for c in result.preservation_checks)


# --- rescue_message: determinism -----------------------------------------------


def test_rescue_message_deterministic_for_same_inputs():
    payload = _valid_payload()
    result_a = rescue_message(TRANSCRIPT, _signals(), call_fn=_fixed(payload), context_text="some context here")
    result_b = rescue_message(TRANSCRIPT, _signals(), call_fn=_fixed(payload), context_text="some context here")
    assert result_a == result_b


def test_rescue_message_low_confidence_signal_propagates_without_fabrication():
    signals = _signals(confidence=0.05, arousal=0.0, urgency=0.0, hesitation=0.9)
    call_fn = _fixed(_valid_payload())
    result = rescue_message(TRANSCRIPT, signals, call_fn=call_fn)
    assert result.delivery["confidence"] == pytest.approx(0.05)
    assert any("high hesitation" in label for label in result.delivery["labels"])
    assert any("low energy" in label for label in result.delivery["labels"])
