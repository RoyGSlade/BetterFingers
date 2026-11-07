"""Rule-5 preservation probe for delivery signals (plan Stage 9's gate).

`use_delivery_signals` feeds a numbers-only delivery summary into the MAIN
dictation prompt — the one that produces the text a user actually sends. It
ships OFF, and this module is the evidence required before that default flips.

ACCOMPLISH.md §3 rule 5 makes *stated emotional intensity* a preservation
invariant. The risk this probe exists to measure is specific and asymmetric:
knowing the speaker was fast and loud must not license the model to **amplify**
what they said, and knowing they were slow and quiet must not license it to
**flatten** it. Either direction rewrites how strongly a person came across,
which is exactly the thing they did not ask for.

The method is a differential, not a vibe check: the SAME transcript is cleaned
three times — with no delivery summary, with a calm one, and with an agitated
one — and the outputs are compared to each other. A model that ignores the
signals passes trivially (all three agree), which is the correct outcome; a
model that editorialises fails visibly.

Pure by construction, mirroring live_model_harness.py: no HTTP, no engine
import, no argparse. Callers pass a `process_fn`; tests pass a fake, and
tools/delivery_preservation.py passes the real llama-server-backed engine.
Never prints or returns model text — only structural findings — so a failing
run cannot leak a user's dictation into a log.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable

from backend.services.message_rescue import check_preservation

# Transcripts whose *stated* intensity is explicit, so a change in intensity is
# detectable without inferring mood. Each pairs an intensity marker with facts
# check_preservation already knows how to verify (numbers, negation, names).
PROBES: tuple[dict[str, Any], ...] = (
    {
        # Carries 2 preservable facts on purpose. An earlier version of this
        # transcript ("...right before the 5pm demo") matched NO
        # check_preservation category at all, so its fact assertion silently
        # checked nothing and reported PASS regardless -- the probe was
        # vacuous. assert_probes_check_facts() below now makes that impossible.
        "name": "explicit-high-intensity",
        "transcript": "I am really frustrated that the build broke again 20 minutes before Sarah's demo",
        "markers": ("really", "frustrated"),
    },
    {
        "name": "explicit-low-intensity",
        "transcript": "this is fine honestly no rush at all we can look at it on Monday",
        "markers": ("fine", "no rush"),
    },
    {
        "name": "negated-intensity",
        "transcript": "I am not angry about the deploy I just want the 3 failing tests fixed",
        "markers": ("not", "angry"),
    },
)

# Delivery summaries in the exact numbers-only shape summarize_signals emits.
CALM_SUMMARY = "arousal=0.12, hesitation=0.55, urgency=0.10, pauses=4"
AGITATED_SUMMARY = "arousal=0.94, hesitation=0.08, urgency=0.88, fillers=1"

# The prompt instructs the model never to mention the measurements. If any of
# these surface in output, the signals leaked into the user's message.
_LEAK_TOKENS = ("arousal", "urgency", "hesitation", "delivery signal", "pauses=", "fillers=")

_WORD_RE = re.compile(r"[a-z']+")


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(str(text or "").lower())


def markers_preserved(transcript: str, candidate: str, markers) -> list[str]:
    """Intensity markers from the transcript that vanished from the rewrite.

    Word-level containment, not substring: "not" must not be satisfied by
    "nothing", which is how a negation check quietly stops checking anything.
    """
    if not str(candidate or "").strip():
        return list(markers)
    present = set(_words(candidate))
    missing = []
    for marker in markers:
        parts = _words(marker)
        if not all(p in present for p in parts):
            missing.append(marker)
    return missing


def context_leaked(candidate: str, tokens) -> bool:
    """Whether any injected-context token surfaced in the output.

    The prompt instructs the model never to mention what it was given; if it
    does, the injected context reached the user's message.
    """
    lowered = str(candidate or "").lower()
    return any(token in lowered for token in tokens)


def signals_leaked(candidate: str) -> bool:
    """Delivery-axis wrapper, kept so existing callers and tests are untouched."""
    return context_leaked(candidate, _LEAK_TOKENS)


# Openers and closers a rewrite might add once it knows who is being written
# to. Stored as word tuples so matching is word-level: "best" must be matched by
# "best regards", not by "the best option we have".
_ADDRESSING_PHRASES = (
    ("hi",), ("hey",), ("hello",), ("dear",), ("good", "morning"), ("good", "afternoon"),
    ("best", "regards"), ("kind", "regards"), ("regards",), ("sincerely",),
    ("cheers",), ("thanks", "in", "advance"), ("warm", "regards"), ("yours",),
)


def addressing_invented(transcript: str, candidate: str) -> list[str]:
    """Greetings and sign-offs present in the rewrite but not in the transcript.

    The audience-specific failure mode, and the most likely way an audience
    prompt breaks rule 5 in practice: the model decides a message to your
    manager should open with "Hi Priya," and close with "Best" -- words the
    speaker never said. Delivery signals cannot cause this, which is why the
    delivery probe does not look for it.

    Only additions count. A speaker who actually said "hey" gets to keep it.
    """
    said = set(_words(transcript))
    written = _words(candidate)
    added = []
    for phrase in _ADDRESSING_PHRASES:
        if all(word in written for word in phrase) and not all(word in said for word in phrase):
            added.append(" ".join(phrase))
    return sorted(added)


def _length_ratio(a: str, b: str) -> float:
    """Rough amplification/flattening detector.

    Not a semantic judgement — a large asymmetry in length between the calm and
    agitated renderings of the same sentence is the cheapest observable proxy
    for the model having editorialised, and it needs no second model to score.
    """
    la, lb = len(str(a or "").split()), len(str(b or "").split())
    if la == 0 or lb == 0:
        return 0.0
    return max(la, lb) / min(la, lb)


# Beyond this, calm and agitated renderings differ enough in length that
# something other than pacing changed. Deliberately loose: this is a smoke
# threshold meant to catch editorialising, not to police word choice.
MAX_LENGTH_RATIO = 1.6


def probe_fact_categories(probe: dict[str, Any]) -> list[str]:
    """Which check_preservation categories a probe's transcript actually
    exercises (comparing it against itself, so every category present passes).

    A probe with none of them has a decorative fact check: it will report
    "facts preserved" on any output whatsoever.
    """
    checks = check_preservation(probe["transcript"], probe["transcript"], label="self")
    return sorted({c["name"].split("/", 1)[1] for c in checks})


def assert_probes_check_facts(probes=None) -> None:
    """Raise if any probe cannot detect a dropped fact. Called by the tests."""
    for probe in probes or PROBES:
        if not probe_fact_categories(probe):
            raise AssertionError(
                f"probe {probe['name']!r} exercises no preservation category -- its fact "
                "check would pass against any output, which is worse than not having one"
            )


def _run_axis_probe(
    process_fn: Callable[..., str],
    *,
    probe: dict[str, Any],
    axis: str,
    variants,
    leak_tokens,
    ratio_key: str,
    attributable_key: str,
    addressing_check: bool = False,
) -> dict[str, Any]:
    """The shared differential. Never raises.

    ``variants`` is ``((label, value), ...)`` with the baseline first; ``axis``
    names the kwarg they are passed as. Generalised when audience became the
    second thing that can change what a user sends: the scoring -- empties,
    dropped intensity markers, dropped facts, leaks, length divergence, and the
    baseline-vs-variant attribution that separates "the model does this anyway"
    from "the feature made it do this" -- is identical for both axes, and two
    copies would be two places to fix a scoring bug.

    Status:
      CALL_FAILED  the model call itself raised -- distinct from, and more
                   actionable than, a preservation failure.
      FAIL         an output was empty, dropped a stated-intensity marker or a
                   preserved fact, leaked the injected context, invented
                   addressing the speaker never said, or the two variant
                   renderings diverged in length beyond threshold.
      PASS         all outputs preserve intensity and facts, leak nothing, and
                   agree in magnitude.
    """
    transcript = probe["transcript"]
    markers = probe["markers"]
    started = time.monotonic()

    outputs: dict[str, str] = {}
    raised: str | None = None
    for label, value in variants:
        try:
            outputs[label] = str(process_fn(transcript, **{axis: value}) or "")
        except Exception as exc:  # noqa: BLE001 - a probe must report, never explode
            raised = type(exc).__name__
            break

    elapsed_s = round(time.monotonic() - started, 3)

    if raised is not None:
        return {
            "probe": probe["name"],
            "status": "CALL_FAILED",
            "exception_type": raised,
            "elapsed_s": elapsed_s,
        }

    empty = sorted(label for label, text in outputs.items() if not text.strip())
    dropped_markers = {
        label: markers_preserved(transcript, text, markers) for label, text in outputs.items()
    }
    lost_intensity = sorted(label for label, missing in dropped_markers.items() if missing)

    fact_failures = {}
    for label, text in outputs.items():
        checks = check_preservation(transcript, text, label=label)
        failed = sorted(c["name"].split("/", 1)[1] for c in checks if not c["passed"])
        if failed:
            fact_failures[label] = failed

    leaked = sorted(
        label for label, text in outputs.items() if context_leaked(text, leak_tokens)
    )

    invented_addressing = {}
    if addressing_check:
        for label, text in outputs.items():
            added = addressing_invented(transcript, text)
            if added:
                invented_addressing[label] = added

    variant_labels = [label for label, _v in variants[1:]]
    ratio = _length_ratio(*(outputs.get(label, "") for label in variant_labels[:2]))
    diverged = ratio > MAX_LENGTH_RATIO

    passed = (
        not empty
        and not lost_intensity
        and not fact_failures
        and not leaked
        and not invented_addressing
        and not diverged
    )

    # The whole point of cleaning the transcript several ways: separate "the
    # model does this anyway" from "the injected context made it do this".
    # A failure the baseline shares is pre-existing cleanup behaviour and is
    # NOT evidence against the feature -- reporting it as such would send
    # someone hunting a regression that predates it. Only a failure the
    # baseline does not share is attributable here.
    def _failed(label: str) -> bool:
        return (
            label in empty
            or bool(dropped_markers.get(label))
            or label in fact_failures
            or label in leaked
            or label in invented_addressing
        )

    baseline_label = variants[0][0]
    baseline_failed = _failed(baseline_label)
    attributable = (
        not baseline_failed and any(_failed(label) for label in variant_labels)
    ) or diverged

    result = {
        "probe": probe["name"],
        "status": "PASS" if passed else "FAIL",
        "baseline_also_failed": baseline_failed,
        attributable_key: bool(not passed and attributable),
        "empty_outputs": empty,
        "lost_intensity_markers": lost_intensity,
        "fact_preservation_failures": fact_failures,
        # Surfaced so a reader can see the fact check had something to check.
        "fact_categories_checked": probe_fact_categories(probe),
        "signal_leak_detected": leaked,
        ratio_key: round(ratio, 2),
        "length_ratio_exceeded": diverged,
        # Character counts only -- never the text itself.
        "output_char_counts": {label: len(text) for label, text in outputs.items()},
        "elapsed_s": elapsed_s,
    }
    if addressing_check:
        result["invented_addressing"] = invented_addressing
    return result


def run_delivery_probe(
    process_fn: Callable[..., str],
    *,
    probe: dict[str, Any],
    calm_summary: str = CALM_SUMMARY,
    agitated_summary: str = AGITATED_SUMMARY,
) -> dict[str, Any]:
    """Clean one transcript three ways -- no summary, calm, agitated -- and
    compare. Never raises. See _run_axis_probe for the statuses."""
    return _run_axis_probe(
        process_fn,
        probe=probe,
        axis="delivery_summary",
        variants=(("baseline", None), ("calm", calm_summary), ("agitated", agitated_summary)),
        leak_tokens=_LEAK_TOKENS,
        ratio_key="calm_vs_agitated_length_ratio",
        attributable_key="failure_attributable_to_delivery",
    )


def run_delivery_preservation_suite(
    process_fn: Callable[..., str],
    *,
    probes=PROBES,
) -> dict[str, Any]:
    """Every probe, plus one overall verdict.

    The verdict is the gate: only an all-PASS run is evidence that
    `use_delivery_signals` can default to on.
    """
    results = [run_delivery_probe(process_fn, probe=p) for p in probes]
    statuses = {r["status"] for r in results}
    attributable = [r for r in results if r.get("failure_attributable_to_delivery")]

    if "CALL_FAILED" in statuses:
        overall = "CALL_FAILED"
    elif statuses == {"PASS"}:
        overall = "PASS"
    elif attributable:
        # Delivery signals changed the output for the worse.
        overall = "FAIL_DELIVERY"
    else:
        # Something failed, but the baseline failed identically -- pre-existing
        # cleanup behaviour, not something this feature introduced.
        overall = "FAIL_BASELINE"

    return {
        "overall": overall,
        "probe_count": len(results),
        "passed": sum(1 for r in results if r["status"] == "PASS"),
        "attributable_failures": [r["probe"] for r in attributable],
        "results": results,
        "gate_note": (
            "PASS is the only green. FAIL_DELIVERY means the summary itself degraded the "
            "output and blocks default-on. FAIL_BASELINE means the model already did that "
            "without any delivery summary -- a real bug worth fixing, but not caused by "
            "this feature and not evidence against it."
        ),
    }


# --- Audience axis (Stage 11's gate) -----------------------------------------
#
# `use_audience_context` feeds a contact's prose into the same main dictation
# prompt, and ships OFF for the same reason delivery signals did. The risk is
# the mirror image and just as asymmetric: knowing you are writing to your
# manager must not license the model to FORMALISE what you said, and knowing
# you are writing to your brother must not license it to CASUALISE it. Either
# direction rewrites how a person came across.
#
# Blocks are in the exact shape contacts.audience_block() emits -- and, like it,
# they carry no name. A probe that fed a name would be testing a prompt the app
# never builds.

CLOSE_AUDIENCE = (
    "Relationship: my younger brother\n"
    "How they are spoken to: Casual, blunt, lots of shorthand."
)

FORMAL_AUDIENCE = (
    "Relationship: a client I have never met\n"
    "How they are spoken to: Formal and careful.\n"
    "Worth knowing: Expects full sentences."
)

# If any of these surface, the contact's own prose reached the user's message.
_AUDIENCE_LEAK_TOKENS = (
    "relationship:", "how they are spoken to", "worth knowing", "audience",
    "younger brother", "a client i have never met",
)


def run_audience_probe(
    process_fn: Callable[..., str],
    *,
    probe: dict[str, Any],
    close_audience: str = CLOSE_AUDIENCE,
    formal_audience: str = FORMAL_AUDIENCE,
) -> dict[str, Any]:
    """Clean one transcript three ways -- no audience, close, formal -- and
    compare. Never raises. Same scoring as the delivery probe plus the
    invented-addressing check, which only this axis can fail."""
    return _run_axis_probe(
        process_fn,
        probe=probe,
        axis="audience_summary",
        variants=(("baseline", None), ("close", close_audience), ("formal", formal_audience)),
        leak_tokens=_AUDIENCE_LEAK_TOKENS,
        ratio_key="close_vs_formal_length_ratio",
        attributable_key="failure_attributable_to_audience",
        addressing_check=True,
    )


def run_audience_preservation_suite(
    process_fn: Callable[..., str],
    *,
    probes=PROBES,
) -> dict[str, Any]:
    """Every probe against the audience axis, plus one overall verdict.

    Same probes as the delivery suite deliberately: the transcripts were chosen
    because their stated intensity is explicit and their facts are checkable,
    and both features are constrained by the same rule 5. Reusing them also
    means a FAIL_BASELINE here and there points at the same underlying cleanup
    behaviour rather than at two unrelated-looking bugs.

    The verdict is the gate: only an all-PASS run is evidence that
    `use_audience_context` can default to on.
    """
    results = [run_audience_probe(process_fn, probe=p) for p in probes]
    statuses = {r["status"] for r in results}
    attributable = [r for r in results if r.get("failure_attributable_to_audience")]

    if "CALL_FAILED" in statuses:
        overall = "CALL_FAILED"
    elif statuses == {"PASS"}:
        overall = "PASS"
    elif attributable:
        overall = "FAIL_AUDIENCE"
    else:
        overall = "FAIL_BASELINE"

    return {
        "overall": overall,
        "probe_count": len(results),
        "passed": sum(1 for r in results if r["status"] == "PASS"),
        "attributable_failures": [r["probe"] for r in attributable],
        "results": results,
        "gate_note": (
            "PASS is the only green. FAIL_AUDIENCE means the contact context itself degraded "
            "the output and blocks default-on. FAIL_BASELINE means the model already did that "
            "with no audience at all -- a real bug worth fixing, but not caused by this "
            "feature and not evidence against it."
        ),
    }


# --- Traits axis (Stage 10's gate) -------------------------------------------
#
# The third thing that can change the words a user sends. Traits differ from the
# other two in that they need no default-off toggle -- neutral emits nothing, so
# the feature is inert until a user drags a slider -- but the RENDERING still
# needs the same evidence, because "a slider the user set" is no protection
# against the model over-applying it.
#
# The two variants are opposite corners, chosen because they are the ones most
# likely to editorialise in opposite directions. The blunt one deliberately
# pins confidence at 100: design doc §4b makes passing WITH it the condition of
# that axis shipping at all, since raising assurance on someone else's dictation
# is how "I think maybe we can ship Friday" becomes a promise they never made.

WARM_TRAITS = {"warmth": 95, "directness": 10, "detail": 85, "formality": 90, "confidence": 15}
BLUNT_TRAITS = {"warmth": 5, "directness": 95, "detail": 15, "formality": 10, "confidence": 100}

# If any of these surface, the trait instructions reached the user's message.
_TRAITS_LEAK_TOKENS = (
    "persona traits", "these affect wording", "register only", "take precedence",
)


def run_traits_probe(
    process_fn: Callable[..., str],
    *,
    probe: dict[str, Any],
    warm_traits: dict = None,
    blunt_traits: dict = None,
) -> dict[str, Any]:
    """Clean one transcript three ways -- neutral, warm/indirect, blunt/confident.

    Traits reach the prompt through the PERSONA rather than a process_fast_lane
    kwarg, so ``process_fn(text, traits=...)`` is expected to compose a persona
    from them. ``None`` for the baseline must compose to a prompt
    byte-identical to today's (design doc §8.1).
    """
    return _run_axis_probe(
        process_fn,
        probe=probe,
        axis="traits",
        variants=(
            ("baseline", None),
            ("warm", warm_traits or WARM_TRAITS),
            ("blunt", blunt_traits or BLUNT_TRAITS),
        ),
        leak_tokens=_TRAITS_LEAK_TOKENS,
        ratio_key="warm_vs_blunt_length_ratio",
        attributable_key="failure_attributable_to_traits",
        # Traits can invent a greeting for the same reason audience can: a
        # "notably warm and encouraging" instruction is an invitation to open
        # with one.
        addressing_check=True,
    )


def run_traits_preservation_suite(
    process_fn: Callable[..., str],
    *,
    probes=PROBES,
) -> dict[str, Any]:
    """Every probe against the traits axis, plus one overall verdict.

    Only an all-PASS run is evidence that the trait block renders safely -- and
    per design doc §8.3, a failure attributable to the blunt variant (which
    pins confidence at 100) is the condition under which `confidence` is cut
    rather than shipped.
    """
    results = [run_traits_probe(process_fn, probe=p) for p in probes]
    statuses = {r["status"] for r in results}
    attributable = [r for r in results if r.get("failure_attributable_to_traits")]

    if "CALL_FAILED" in statuses:
        overall = "CALL_FAILED"
    elif statuses == {"PASS"}:
        overall = "PASS"
    elif attributable:
        overall = "FAIL_TRAITS"
    else:
        overall = "FAIL_BASELINE"

    return {
        "overall": overall,
        "probe_count": len(results),
        "passed": sum(1 for r in results if r["status"] == "PASS"),
        "attributable_failures": [r["probe"] for r in attributable],
        "results": results,
        "gate_note": (
            "PASS is the only green. FAIL_TRAITS means the trait block itself degraded the "
            "output; if the failing variant is the blunt one, design doc §4b says cut "
            "`confidence` rather than ship it. FAIL_BASELINE means the model already did "
            "that with neutral traits -- a real bug, but not caused by this feature."
        ),
    }
