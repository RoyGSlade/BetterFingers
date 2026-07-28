"""Persona traits (Stage 10).

Design: ``docs/PERSONA_TRAITS_DESIGN.md``, owner decisions §10.

The tests that carry weight here are the ones protecting properties a future
change could break without any visible symptom: that neutral emits nothing (so
every persona predating the field is untouched), that the phrasings can never
invite invention, and that a trait never comes from anywhere but a slider.
"""

import pytest

import llm_engine
from persona_traits import (
    BAND_HIGH,
    BAND_LOW,
    BAND_NEUTRAL,
    BAND_VERY_HIGH,
    BAND_VERY_LOW,
    TRAIT_KEYS,
    TRAIT_PHRASES,
    band_for,
    band_label,
    neutral_traits,
    normalize_traits,
    render_traits_block,
    trait_instructions,
    trait_lint_warnings,
    traits_are_neutral,
)


# --- bands -------------------------------------------------------------------


@pytest.mark.parametrize("value,expected", [
    (0, BAND_VERY_LOW), (19, BAND_VERY_LOW),
    (20, BAND_LOW), (39, BAND_LOW),
    (40, BAND_NEUTRAL), (50, BAND_NEUTRAL), (59, BAND_NEUTRAL),
    (60, BAND_HIGH), (79, BAND_HIGH),
    (80, BAND_VERY_HIGH), (100, BAND_VERY_HIGH),
])
def test_band_boundaries(value, expected):
    assert band_for(value) == expected


def test_values_within_a_band_are_indistinguishable():
    """The point of quantizing: 101 slider values, about five the model can act
    on. 63 and 67 must produce the same prompt, and the UI says so."""
    assert band_for(63) == band_for(67)
    assert trait_instructions({"warmth": 63}) == trait_instructions({"warmth": 67})


def test_junk_reads_as_neutral_rather_than_raising():
    for junk in (None, "", "warm", [], {}, float("nan"), True):
        assert band_for(junk) == BAND_NEUTRAL


def test_out_of_range_values_clamp():
    assert band_for(-40) == BAND_VERY_LOW
    assert band_for(4000) == BAND_VERY_HIGH


def test_band_labels_are_what_the_ui_shows():
    assert band_label(50) == "Neutral"
    assert band_label(95) == "Very high"
    assert band_label(25) == "Low"


# --- neutral emits nothing ---------------------------------------------------


def test_neutral_traits_emit_no_instructions():
    assert trait_instructions(neutral_traits()) == []
    assert render_traits_block(neutral_traits(), " CLAUSE") == ""


def test_absent_null_partial_and_neutral_are_indistinguishable():
    """A persona written before this field existed must be indistinguishable
    from one whose sliders were never moved."""
    for traits in (None, {}, {"warmth": None}, {"warmth": 50}, neutral_traits()):
        assert render_traits_block(traits, " CLAUSE") == ""
        assert traits_are_neutral(traits) is True


def test_a_prompt_only_persona_composes_to_exactly_its_prompt():
    """compose_persona_system_prompt's existing property. A traits block that
    always emitted five sentences would break it for every persona in the app."""
    assert llm_engine.compose_persona_system_prompt("You are an editor.") == "You are an editor."
    persona = llm_engine.normalize_persona("You are an editor.")
    assert llm_engine.compose_persona_system_prompt(persona) == "You are an editor."


def test_a_neutral_traits_persona_matches_a_traitless_one_byte_for_byte():
    # Design doc §8 acceptance 1.
    without = llm_engine.compose_persona_system_prompt({"prompt": "Clean it up."})
    with_neutral = llm_engine.compose_persona_system_prompt(
        {"prompt": "Clean it up.", "traits": neutral_traits()}
    )
    assert without == with_neutral


# --- rendering ---------------------------------------------------------------


def test_only_non_neutral_axes_are_emitted():
    lines = trait_instructions({"warmth": 95, "directness": 50, "formality": 10})
    assert len(lines) == 2
    assert any("warm and encouraging" in line for line in lines)
    assert any("casual" in line for line in lines)


def test_axis_order_is_fixed_so_the_same_persona_composes_identically():
    forward = trait_instructions({"warmth": 95, "confidence": 95})
    reversed_input = trait_instructions({"confidence": 95, "warmth": 95})
    assert forward == reversed_input


def test_the_block_never_mentions_a_number():
    """The model gets the instruction, not the value."""
    block = render_traits_block({key: 95 for key in TRAIT_KEYS}, "")
    assert "95" not in block
    for token in ("0-100", "slider", "percent", "%"):
        assert token not in block.lower()


def test_the_block_says_the_personas_own_prompt_wins():
    # A slider silently overriding hand-written instructions would make the
    # prompt box feel unreliable.
    block = render_traits_block({"warmth": 95}, "")
    assert "take precedence" in block


def test_the_block_forbids_changing_meaning_facts_or_intensity():
    block = render_traits_block({"warmth": 95}, "")
    lowered = block.lower()
    assert "meaning" in lowered
    assert "facts" in lowered
    assert "intensity" in lowered


def test_the_block_carries_the_preservation_clause():
    """Rule 5 does not get a weaker version because the input is a slider."""
    block = render_traits_block({"warmth": 95}, llm_engine.PRESERVATION_CLAUSE)
    assert "PRESERVE EXACTLY" in block

    composed = llm_engine.compose_persona_system_prompt(
        {"prompt": "Clean it up.", "traits": {"warmth": 95}}, include_traits=True
    )
    assert "PRESERVE EXACTLY" in composed


def test_traits_are_not_rendered_unless_the_caller_opts_in():
    """The gate failed on a real model, so a persona whose sliders HAVE been
    moved is not proven safe. Default-off means storing traits, showing them and
    editing them are all live while the RENDERING waits for evidence."""
    persona = {"prompt": "Clean it up.", "traits": {"warmth": 95, "confidence": 100}}
    assert llm_engine.compose_persona_system_prompt(persona) == "Clean it up."
    assert "PERSONA TRAITS" in llm_engine.compose_persona_system_prompt(persona, include_traits=True)


def test_the_profile_toggle_defaults_off():
    from utils import _profile_defaults, _sanitize_profile_values

    defaults = _profile_defaults()
    assert defaults["use_persona_traits"] is False
    assert _sanitize_profile_values({"use_persona_traits": "true"}, defaults)["use_persona_traits"] is True
    assert _sanitize_profile_values({"use_persona_traits": "junk"}, defaults)["use_persona_traits"] is False


# --- the two dangerous axes --------------------------------------------------


def test_detail_never_invites_invention():
    """Every detail phrasing refers to what the SPEAKER GAVE. An axis that could
    say "add detail" would break rule 5 by construction."""
    for band, phrase in TRAIT_PHRASES["detail"].items():
        lowered = phrase.lower()
        assert "add " not in lowered, f"{band} invites invention: {phrase!r}"
        assert "invent" not in lowered
        assert "elaborate" not in lowered
    for band in (BAND_HIGH, BAND_VERY_HIGH):
        assert "speaker gave" in TRAIT_PHRASES["detail"][band]


def test_confidence_protects_hedges_at_every_band_that_could_tighten():
    """Raising assurance on someone else's dictation is the app making a promise
    they did not make. Every band that could tighten language says in the same
    breath that qualifiers stay (design doc §4b)."""
    for band in (BAND_HIGH, BAND_VERY_HIGH):
        phrase = TRAIT_PHRASES["confidence"][band].lower()
        assert "qualifier" in phrase or "hedge" in phrase, (
            f"confidence/{band} can tighten language without protecting hedges"
        )
    assert "maybe" in TRAIT_PHRASES["confidence"][BAND_VERY_HIGH]
    assert "i think" in TRAIT_PHRASES["confidence"][BAND_VERY_HIGH].lower()


def test_every_axis_has_a_phrase_for_every_non_neutral_band():
    for key in TRAIT_KEYS:
        for band in (BAND_VERY_LOW, BAND_LOW, BAND_HIGH, BAND_VERY_HIGH):
            assert TRAIT_PHRASES[key][band].strip(), f"{key}/{band} has no phrasing"


def test_no_phrase_carries_emotion_vocabulary_about_the_speaker():
    """Rule 3: a trait describes a persona the user configured, never a claim
    about the person speaking. "warm" describes the writing; "the speaker is
    upset" would be a diagnosis."""
    for key in TRAIT_KEYS:
        for phrase in TRAIT_PHRASES[key].values():
            lowered = phrase.lower()
            for word in ("frustrated", "angry", "upset", "anxious", "sad", "excited", "mood"):
                assert word not in lowered, f"{key} phrasing leaks a diagnosis: {phrase!r}"


# --- schema ------------------------------------------------------------------


def test_default_persona_carries_neutral_traits():
    assert llm_engine.default_persona("x")["traits"] == neutral_traits()


def test_normalize_fills_missing_axes_and_drops_unknown_ones():
    """A hand-edited file should degrade to "no effect" rather than failing to
    load or smuggling in an axis nobody implemented."""
    traits = normalize_traits({"warmth": 90, "sarcasm": 100})
    assert traits["warmth"] == 90
    assert "sarcasm" not in traits
    assert set(traits) == set(TRAIT_KEYS)
    assert traits["formality"] == 50


def test_normalize_survives_junk():
    for junk in (None, "traits", 5, []):
        assert normalize_traits(junk) == neutral_traits()


def test_a_persona_round_trips_its_traits():
    persona = llm_engine.normalize_persona({"prompt": "x", "traits": {"directness": 88}})
    assert persona["traits"]["directness"] == 88
    assert llm_engine.normalize_persona(persona)["traits"]["directness"] == 88


def test_a_legacy_prompt_string_normalizes_to_neutral():
    assert llm_engine.normalize_persona("just a prompt")["traits"] == neutral_traits()


# --- lint --------------------------------------------------------------------


def test_summarize_with_very_high_detail_warns():
    warnings = trait_lint_warnings({"detail": 100}, "summarize")
    assert warnings and "opposite directions" in warnings[0]


def test_expand_with_very_low_detail_warns():
    assert trait_lint_warnings({"detail": 0}, "expand")


def test_the_compatible_combination_does_not_warn():
    """tighten + high detail is "short, but keep the numbers" -- the whole
    reason the two fields were split rather than merged."""
    assert trait_lint_warnings({"detail": 75}, "tighten") == []
    assert trait_lint_warnings({"detail": 100}, "tighten") == []
    assert trait_lint_warnings(neutral_traits(), "summarize") == []


def test_lint_persona_surfaces_the_trait_warning():
    warnings = llm_engine.lint_persona({
        "prompt": "Return only the rewritten text.",
        "output_policy": "summarize",
        "traits": {"detail": 100},
    })
    assert any("opposite directions" in w for w in warnings)


def test_lint_never_blocks_saving():
    # lint_persona returns strings; it has no failure mode. Asserted so a future
    # change that starts raising is caught here rather than in a user's save.
    assert isinstance(llm_engine.lint_persona({"prompt": "x", "traits": {"detail": 100}}), list)


# --- routes -------------------------------------------------------------------


def test_the_save_route_forwards_traits():
    """Accepting a field and forwarding it are different things: a request model
    that parses `traits` while the handler's copy loop omits it would drop them
    silently, which looks exactly like a save that worked."""
    import inspect

    from backend.api.routes import personas as persona_routes

    assert "traits" in persona_routes.PersonaRequest.model_fields
    source = inspect.getsource(persona_routes.save_persona_route)
    assert '"traits"' in source, "traits is accepted but never forwarded to the store"


def test_the_lint_route_accepts_traits():
    from backend.api.routes import personas as persona_routes

    assert "traits" in persona_routes.PersonaLintRequest.model_fields


def test_the_block_protects_the_speakers_own_intensity_wording():
    """Lifted verbatim from the delivery-signal block, which passes the gate on
    a real model. Its absence was not a considered difference: the first real
    traits run failed on exactly this -- a "notably warm" persona softened
    "really frustrated", and a blunt one cut "really"."""
    block = render_traits_block({"warmth": 95}, "")
    lowered = block.lower()
    assert "neither amplifying nor softening" in lowered
    assert "the speaker's own" in lowered


def test_the_traits_and_delivery_blocks_make_the_same_promise():
    # Two blocks guarding the same invariant should not drift apart in wording;
    # the weaker one is the one that fails a gate the other passes.
    import inspect

    delivery_source = inspect.getsource(llm_engine.LLMEngine.process_fast_lane)
    shared = "neither amplifying nor softening it"
    assert shared in delivery_source
    assert shared in render_traits_block({"warmth": 95}, "")


def test_the_dictation_path_gates_traits_on_the_profile():
    """The toggle has to reach the one call that produces the text a user
    actually sends; a flag nothing reads is a flag that lies."""
    import inspect

    import server

    source = inspect.getsource(server)
    assert 'include_traits=bool(profile_config.get("use_persona_traits"))' in source


def test_process_fast_lane_accepts_the_flag_and_defaults_it_off():
    import inspect

    sig = inspect.signature(llm_engine.LLMEngine.process_fast_lane)
    assert sig.parameters["include_traits"].default is False
