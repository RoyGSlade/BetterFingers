"""
Taste memory — the studio learns what THIS user likes (§9.4, owner-requested).

The owner asked explicitly for "a separate system to understand the user's preferences." Every
Accept / Reject / Refine the user performs is a signal about their taste — what tone they reach
for, what they reject as cliché, how they want characters to sound, what pacing they prefer. This
module turns that stream of signals into a compact **taste digest** that is injected into the
Showrunner and Scriptwriter prompts, so the more the user steers, the more the output sounds like
*them* (the difference between "generic slop" and a personal story).

Storage is dead-simple on purpose: an append-only list of signals in project memory
(user preference key ``taste_signals``) plus a derived ``taste_digest`` string. No vector DB —
a digest of recent, weighted signals is enough to bend a local model, and it stays inspectable.

Public API:
    record_signal(project_name, project_id, kind, note, scene_id="")   # accept|reject|refine|like|dislike
    build_digest(project_name, project_id, max_signals=24) -> str       # compact, prompt-ready
    digest_clause(project_name, project_id) -> str                      # ready to append to a system prompt
"""

import logging

import studio_memory as memory

logger = logging.getLogger("studio_taste")

_SIGNALS_KEY = "taste_signals"
_DIGEST_KEY = "taste_digest"

# How strongly each kind of signal speaks to taste (refine/reject carry the most intent).
_WEIGHT = {"refine": 3, "reject": 2, "dislike": 2, "accept": 1, "like": 1}
_KINDS = set(_WEIGHT)


def record_signal(project_name, project_id, kind, note="", scene_id=""):
    """Append one taste signal and refresh the derived digest. Best-effort; never raises."""
    kind = (kind or "").strip().lower()
    if kind not in _KINDS:
        kind = "refine" if note else "accept"
    try:
        prefs = memory.get_user_preferences(project_name, project_id)
        signals = prefs.get(_SIGNALS_KEY)
        if not isinstance(signals, list):
            signals = []
        signals.append({
            "kind": kind,
            "note": str(note or "").strip()[:240],
            "scene_id": str(scene_id or ""),
            "at": memory.utc_now() if hasattr(memory, "utc_now") else "",
        })
        # Keep the log bounded; recency matters more than ancient history.
        signals = signals[-100:]
        memory.set_user_preference(project_name, project_id, _SIGNALS_KEY, signals)
        digest = _summarize(signals)
        memory.set_user_preference(project_name, project_id, _DIGEST_KEY, digest)
        return digest
    except Exception as e:
        logger.warning(f"Could not record taste signal: {e}")
        return ""


def build_digest(project_name, project_id, max_signals=24):
    """Return the compact taste digest string (recomputed from recent signals)."""
    try:
        prefs = memory.get_user_preferences(project_name, project_id)
        signals = prefs.get(_SIGNALS_KEY)
        if isinstance(signals, list) and signals:
            return _summarize(signals[-max_signals:])
        cached = prefs.get(_DIGEST_KEY)
        return cached if isinstance(cached, str) else ""
    except Exception:
        return ""


def digest_clause(project_name, project_id):
    """A ready-to-append system-prompt clause, or '' when there's nothing learned yet."""
    digest = build_digest(project_name, project_id)
    if not digest:
        return ""
    return (
        "\n\nUSER TASTE (learned from this user's past accept/reject/refine — honor it, it is what "
        "makes the story theirs):\n" + digest
    )


# --------------------------------------------------------------------------- #
# Summarization (deterministic, no LLM)
# --------------------------------------------------------------------------- #

def _summarize(signals):
    """Turn raw signals into a short, weighted, prompt-ready digest.

    Refine notes are the richest (the user said in words what they wanted), so they are quoted.
    Reject/accept counts give the model a sense of direction without bloating the prompt.
    """
    if not signals:
        return ""
    likes, dislikes = 0, 0
    refine_notes = []
    for s in signals:
        kind = s.get("kind")
        if kind in ("accept", "like"):
            likes += 1
        elif kind in ("reject", "dislike"):
            dislikes += 1
        note = (s.get("note") or "").strip()
        if kind in ("refine", "reject", "dislike") and note:
            refine_notes.append(note)

    lines = []
    # Most recent, distinct directions first (they reflect current intent).
    seen = set()
    recent = []
    for note in reversed(refine_notes):
        key = note.lower()
        if key in seen:
            continue
        seen.add(key)
        recent.append(note)
        if len(recent) >= 6:
            break
    if recent:
        lines.append("Directions the user has given: " + "; ".join(f'"{n}"' for n in recent) + ".")
    if likes or dislikes:
        lines.append(f"Signal balance: {likes} kept, {dislikes} rejected — "
                     "lean toward what was kept, avoid the texture of what was rejected.")
    return "\n".join(lines)
