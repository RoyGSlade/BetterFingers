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


def signals_leaked(candidate: str) -> bool:
    lowered = str(candidate or "").lower()
    return any(token in lowered for token in _LEAK_TOKENS)


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


def run_delivery_probe(
    process_fn: Callable[..., str],
    *,
    probe: dict[str, Any],
    calm_summary: str = CALM_SUMMARY,
    agitated_summary: str = AGITATED_SUMMARY,
) -> dict[str, Any]:
    """Clean one transcript three ways and compare. Never raises.

    Status:
      CALL_FAILED  the model call itself raised — distinct from, and more
                   actionable than, a preservation failure.
      FAIL         an output was empty, dropped a stated-intensity marker or a
                   preserved fact, leaked the measurements, or the calm and
                   agitated renderings diverged in length beyond threshold.
      PASS         all three outputs preserve intensity and facts, leak
                   nothing, and agree in magnitude.
    """
    transcript = probe["transcript"]
    markers = probe["markers"]
    started = time.monotonic()

    outputs: dict[str, str] = {}
    raised: str | None = None
    for label, summary in (("baseline", None), ("calm", calm_summary), ("agitated", agitated_summary)):
        try:
            outputs[label] = str(process_fn(transcript, delivery_summary=summary) or "")
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

    leaked = sorted(label for label, text in outputs.items() if signals_leaked(text))
    ratio = _length_ratio(outputs.get("calm", ""), outputs.get("agitated", ""))
    diverged = ratio > MAX_LENGTH_RATIO

    passed = not empty and not lost_intensity and not fact_failures and not leaked and not diverged

    # The whole point of cleaning the transcript three ways: separate "the
    # model does this anyway" from "the delivery summary made it do this".
    # A failure the baseline shares is pre-existing cleanup behaviour and is
    # NOT evidence against delivery signals -- reporting it as such would send
    # someone hunting a regression that predates the feature. Only a failure
    # the baseline does not share is attributable here.
    def _failed(label: str) -> bool:
        return (
            label in empty
            or bool(dropped_markers.get(label))
            or label in fact_failures
            or label in leaked
        )

    baseline_failed = _failed("baseline")
    attributable = (not baseline_failed and (_failed("calm") or _failed("agitated"))) or diverged

    return {
        "probe": probe["name"],
        "status": "PASS" if passed else "FAIL",
        "baseline_also_failed": baseline_failed,
        "failure_attributable_to_delivery": bool(not passed and attributable),
        "empty_outputs": empty,
        "lost_intensity_markers": lost_intensity,
        "fact_preservation_failures": fact_failures,
        # Surfaced so a reader can see the fact check had something to check.
        "fact_categories_checked": probe_fact_categories(probe),
        "signal_leak_detected": leaked,
        "calm_vs_agitated_length_ratio": round(ratio, 2),
        "length_ratio_exceeded": diverged,
        # Character counts only -- never the text itself.
        "output_char_counts": {label: len(text) for label, text in outputs.items()},
        "elapsed_s": elapsed_s,
    }


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
