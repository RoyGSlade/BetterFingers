"""Gaming policy — the constants a game-focused session runs under (Wave 7).

While a game is in the foreground the cost of getting this wrong is not a worse
draft, it is a lost match. Anything that steals focus, spends seconds, or talks
over the game is a defect, so the policy is deliberately severe: short model
output, at most two short spoken sentences and never a queue of them, no
automatic submission, and minimal overlay.

This module is **data, not behaviour**. It exports the numbers and flags, plus
small pure helpers to apply them, so the pipeline can consume the policy without
this module reaching into llm_engine, the TTS engine, or the overlay. Those two
consumers (``llm_engine.py``, ``server.py``) are integration-owned; the exact
edits that make them read these constants are written out in
``docs/release/WAVE7_INTEGRATION_DIFFS.md``. Until those land the constants are
declared and tested but **not yet consumed** — stated plainly rather than
implied, because a policy that only exists in a constants file protects nobody.

Which profiles run under it is not decided here: a profile opts in through its
``performance_preset``. See ``GAMING_PERFORMANCE_PRESETS``.
"""

from __future__ import annotations

# --- The policy --------------------------------------------------------------

# Model output cap. Small enough that a generation finishes inside a lull rather
# than spanning one. This is a hard ceiling for the gaming path, not a default:
# the profile's own setting may lower it, never raise it (see clamp_completion_tokens).
MAX_COMPLETION_TOKENS = 50

# Spoken output. Two SHORT sentences is the whole budget, and nothing queues:
# a backlog of announcements arriving over a teamfight is worse than silence,
# because it keeps arriving after the moment it described has passed.
MAX_TTS_SENTENCES = 2
MAX_TTS_SENTENCE_CHARS = 90
QUEUE_TTS = False

# Delivery. Never type into a game: synthetic keystrokes reach whatever has
# focus, and in a game that is the movement keys. The user reviews, or takes the
# text from the clipboard.
AUTO_SUBMIT = False
REVIEW_ONLY = True
CLIPBOARD_FALLBACK = True

# Overlay. Present enough to show state, small enough not to cover the game.
MINIMAL_OVERLAY = True

# The performance presets that opt a profile into this policy. Kept here rather
# than in the store so the policy owns its own trigger.
GAMING_PERFORMANCE_PRESETS = ("minimal",)

# The whole policy as one dict, for the API surface and for consumers that would
# rather read a payload than import seven names.
GAMING_POLICY = {
    "max_completion_tokens": MAX_COMPLETION_TOKENS,
    "max_tts_sentences": MAX_TTS_SENTENCES,
    "max_tts_sentence_chars": MAX_TTS_SENTENCE_CHARS,
    "queue_tts": QUEUE_TTS,
    "auto_submit": AUTO_SUBMIT,
    "review_only": REVIEW_ONLY,
    "clipboard_fallback": CLIPBOARD_FALLBACK,
    "minimal_overlay": MINIMAL_OVERLAY,
}


def is_gaming_profile(profile) -> bool:
    """True when this profile's performance preset opts into the policy."""
    if not isinstance(profile, dict):
        return False
    return profile.get("performance_preset") in GAMING_PERFORMANCE_PRESETS


def clamp_completion_tokens(requested, active: bool = True) -> int:
    """The completion cap to actually use.

    A ceiling, never a floor: a caller asking for fewer tokens than the policy
    allows gets what it asked for. ``active=False`` returns the request
    unchanged, so a call site can apply this unconditionally and let the flag
    decide, rather than growing an ``if`` around every use.
    """
    try:
        value = int(requested)
    except (TypeError, ValueError):
        value = MAX_COMPLETION_TOKENS if active else 0
    if value < 1:
        value = MAX_COMPLETION_TOKENS if active else value
    return min(value, MAX_COMPLETION_TOKENS) if active else value


def trim_spoken_text(text, active: bool = True) -> str:
    """Cut spoken output down to the policy's budget.

    Splits on sentence enders, keeps at most ``MAX_TTS_SENTENCES``, and
    truncates any single sentence longer than ``MAX_TTS_SENTENCE_CHARS`` at a
    word boundary. Truncation is silent by design -- an ellipsis read aloud is
    just noise, and the full text is still on screen.
    """
    speech = str(text or "").strip()
    if not active or not speech:
        return speech

    import re

    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", speech) if p.strip()]
    kept = parts[:MAX_TTS_SENTENCES] if parts else []
    out = []
    for sentence in kept:
        if len(sentence) > MAX_TTS_SENTENCE_CHARS:
            head = sentence[:MAX_TTS_SENTENCE_CHARS]
            cut = head.rsplit(" ", 1)[0] if " " in head else head
            sentence = cut.rstrip(" ,;:")
        out.append(sentence)
    return " ".join(out)


def resolve_send_action(requested, active: bool = True) -> str:
    """The delivery action to use. Under the policy, never a keystroke.

    ``type_text`` (and anything else that synthesises input) becomes
    ``copy_only``: the clipboard fallback the policy guarantees. Anything
    already non-typing is left alone.
    """
    action = str(requested or "").strip() or "copy_only"
    if not active:
        return action
    return "copy_only" if action in ("type_text", "type", "paste", "auto_send") else action


def policy_for(profile) -> dict:
    """``{"active": bool, **GAMING_POLICY}`` for one profile.

    Always returns the full policy so a consumer reads one shape either way;
    ``active`` is the only thing that varies.
    """
    return {"active": is_gaming_profile(profile), **GAMING_POLICY}
