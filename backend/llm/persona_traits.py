"""Persona traits — five user-set register dials (Stage 10).

Design: ``docs/PERSONA_TRAITS_DESIGN.md``. Owner decisions recorded there §10.

Pure: no DOM, no model, no I/O. ``llm_engine.compose_persona_system_prompt()``
imports ``render_traits_block``; everything else here exists so the band rules
are testable without composing a whole prompt.

Three things in here are load-bearing rather than incidental:

**Neutral emits nothing.** ``compose_persona_system_prompt`` already has the
property that a persona carrying only a prompt returns exactly that prompt --
every field it renders stays silent at its default. A traits block that always
emitted five sentences would break that for every persona in the app.

**The band, not the number.** A slider offers 101 values; a model acts on about
five. Warmth 63 and warmth 67 produce the same prompt, so the value is
quantized before it becomes words, and the UI shows the band so the user can
see which movements matter.

**Nothing here infers anything.** Trait values arrive from a slider the user
dragged. ``arousal``/``urgency``/``hesitation`` already exist on a similar
scale, and deriving a trait from them would be a diagnosis wearing a slider --
the behaviour ACCOMPLISH.md §3 rule 3 forbids. See the design doc §6.
"""

from __future__ import annotations

# Axis order is fixed so the same persona always composes to the same prompt.
TRAIT_KEYS = ("warmth", "directness", "detail", "formality", "confidence")

NEUTRAL_VALUE = 50

# Band boundaries. Neutral is deliberately wide (40-59): a small nudge should do
# nothing, and the UI says "Neutral" for the whole span rather than implying an
# effect it does not have.
BAND_VERY_LOW = "very_low"
BAND_LOW = "low"
BAND_NEUTRAL = "neutral"
BAND_HIGH = "high"
BAND_VERY_HIGH = "very_high"

BAND_LABELS = {
    BAND_VERY_LOW: "Very low",
    BAND_LOW: "Low",
    BAND_NEUTRAL: "Neutral",
    BAND_HIGH: "High",
    BAND_VERY_HIGH: "Very high",
}

# Phrasings. Numbers are never mentioned -- the model gets the instruction, not
# the value. Two phrasing rules run through the whole table:
#
#   * `detail` always says "the specifics the speaker gave", never "add detail".
#     An axis that invites invention breaks rule 5 by construction.
#   * `confidence` governs phrasing, never claims. Every band that could tighten
#     language says in the same breath that qualifiers stay, because turning
#     assurance up on someone else's dictation is the app making a promise they
#     did not make (design doc §4b).
TRAIT_PHRASES = {
    "warmth": {
        BAND_VERY_LOW: "Keep the tone impersonal and businesslike.",
        BAND_LOW: "Lean cool and matter-of-fact.",
        BAND_HIGH: "Lean warm and personable.",
        BAND_VERY_HIGH: "Be notably warm and encouraging.",
    },
    "directness": {
        BAND_VERY_LOW: "Soften requests and criticism; prefer indirect phrasing.",
        BAND_LOW: "Cushion direct statements a little.",
        BAND_HIGH: "Be direct; lead with the main point.",
        BAND_VERY_HIGH: (
            "Be blunt. Lead with the point and cut hedging language that carries no meaning."
        ),
    },
    "detail": {
        BAND_VERY_LOW: "Keep supporting explanation to a minimum.",
        BAND_LOW: "Explain sparingly.",
        BAND_HIGH: "Keep the supporting specifics the speaker gave.",
        BAND_VERY_HIGH: (
            "Keep every specific the speaker gave -- names, numbers, times -- in full."
        ),
    },
    "formality": {
        BAND_VERY_LOW: "Use casual, conversational language and contractions.",
        BAND_LOW: "Lean informal.",
        BAND_HIGH: "Lean formal.",
        BAND_VERY_HIGH: "Use formal language; avoid contractions and slang.",
    },
    "confidence": {
        BAND_VERY_LOW: "Keep the speaker's qualifiers, and phrase tentatively.",
        BAND_LOW: "Phrase a little more tentatively.",
        BAND_HIGH: (
            "Phrase crisply and without filler, but keep every qualifier the speaker used."
        ),
        BAND_VERY_HIGH: (
            "Phrase assertively and cut filler. Never remove or weaken a hedge "
            "(\"maybe\", \"I think\", \"probably\") -- those carry meaning."
        ),
    },
}

# The persona's own free text is the more specific, more considered statement of
# intent, so it wins. A slider silently overriding hand-written instructions
# would make the prompt box feel unreliable.
TRAITS_HEADER = (
    "PERSONA TRAITS (how this persona should sound; the persona's own instructions "
    "above take precedence where they conflict):"
)

# The second sentence is lifted verbatim from the delivery-signal block, which
# passes this gate 3/3 on a real model. Its absence here was not a considered
# difference: the first real traits run failed on exactly the thing it names --
# a "notably warm" persona softened "really frustrated", and a blunt one cut
# "really". Same class of risk, so the same wording.
TRAITS_FOOTER = (
    "These affect wording and register only. They must not change the meaning, the "
    "facts, or the stated intensity of the message: preserve the speaker's own "
    "wording of how strongly they feel, neither amplifying nor softening it."
)


def neutral_traits() -> dict:
    return {key: NEUTRAL_VALUE for key in TRAIT_KEYS}


def _coerce_value(value):
    """A slider value as an int 0-100, or None if it is not a number.

    None is not the same as neutral upstream (the UI renders an empty track for
    an unknown axis), but for prompt purposes they are identical: both emit
    nothing.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return int(max(0, min(100, round(number))))


def band_for(value) -> str:
    """Quantize a 0-100 value to one of five bands. Junk reads as neutral."""
    number = _coerce_value(value)
    if number is None:
        return BAND_NEUTRAL
    if number < 20:
        return BAND_VERY_LOW
    if number < 40:
        return BAND_LOW
    if number < 60:
        return BAND_NEUTRAL
    if number < 80:
        return BAND_HIGH
    return BAND_VERY_HIGH


def band_label(value) -> str:
    """What the UI shows beside the slider."""
    return BAND_LABELS[band_for(value)]


def normalize_traits(raw) -> dict:
    """Coerce any shape into a complete traits dict.

    Unknown keys are dropped and missing ones default to neutral, so a
    hand-edited persona file degrades to "no effect" rather than failing to
    load or smuggling an axis nobody implemented.
    """
    source = raw if isinstance(raw, dict) else {}
    traits = {}
    for key in TRAIT_KEYS:
        value = _coerce_value(source.get(key))
        traits[key] = NEUTRAL_VALUE if value is None else value
    return traits


def traits_are_neutral(traits) -> bool:
    """True when nothing would be emitted. Absent, null, partial and all-neutral
    traits must all be indistinguishable in the prompt."""
    return all(band_for((traits or {}).get(key)) == BAND_NEUTRAL for key in TRAIT_KEYS)


def trait_instructions(traits) -> list:
    """The instruction lines for the non-neutral axes, in fixed axis order."""
    source = traits if isinstance(traits, dict) else {}
    lines = []
    for key in TRAIT_KEYS:
        band = band_for(source.get(key))
        if band == BAND_NEUTRAL:
            continue
        phrase = TRAIT_PHRASES[key][band]
        lines.append(f"- {phrase}")
    return lines


def render_traits_block(traits, preservation_clause: str = "") -> str:
    """The whole block, or '' when every axis is neutral.

    ``preservation_clause`` is passed in rather than imported to keep this
    module free of llm_engine (which imports it). Rule 5 does not get a weaker
    version because the input is a slider, so the caller always supplies it.
    """
    lines = trait_instructions(traits)
    if not lines:
        return ""
    body = "\n".join(lines)
    return f"{TRAITS_HEADER}\n{body}\n{TRAITS_FOOTER}{preservation_clause}"


# --- Lint ---------------------------------------------------------------------

# `detail` and `output_policy` are different questions -- output_policy governs
# LENGTH, detail governs SPECIFICITY within that length -- which makes "short,
# but keep the numbers" expressible. One corner is still genuinely
# contradictory, and lint_persona's job is exactly this: non-blocking guidance
# in the builder, never a refusal to save.
def trait_lint_warnings(traits, output_policy: str = "preserve") -> list:
    warnings = []
    band = band_for((traits or {}).get("detail"))
    policy = str(output_policy or "preserve").strip().lower()

    if policy == "summarize" and band == BAND_VERY_HIGH:
        warnings.append(
            "Output policy 'summarize' and a very high Detail pull in opposite directions: "
            "one drops supporting particulars, the other keeps all of them."
        )
    if policy == "expand" and band == BAND_VERY_LOW:
        warnings.append(
            "Output policy 'expand' and a very low Detail pull in opposite directions: "
            "one adds explanation, the other removes it."
        )
    return warnings
