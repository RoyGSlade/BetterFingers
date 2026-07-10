"""Voice command intent parser — pure text -> intent classification for
app-control voice commands ("send it", "make it shorter", "emergency stop"
...). No side effects: callers (server.py) are responsible for actually
executing the resolved action.

Conservative by construction: a command only resolves inside a "clear
command context" (review overlay open, right after the wake phrase, command
mode toggled on, or the utterance carries a command prefix like
"BetterFingers, ..."). Outside those contexts, ordinary dictation containing
a phrase like "send it" inside a paragraph must NOT be treated as a command.
The one exception is "emergency stop", which always resolves regardless of
context or confidence — it's a safety valve, not a risky action.
"""
import difflib
import re
from dataclasses import dataclass

FUZZY_THRESHOLD = 0.82

_PREFIX_RE = re.compile(r"^\s*(?:hey\s+)?betterfingers[,:]?\s+", re.IGNORECASE)
_EMERGENCY_STOP_RE = re.compile(r"\bemergency\s+stop\b", re.IGNORECASE)
_SWITCH_PERSONA_RE = re.compile(
    r"\b(?:switch\s+to|use)\s+(?:the\s+)?([a-z][a-z '-]*)", re.IGNORECASE
)


@dataclass
class VoiceCommandIntent:
    kind: str  # "draft_action" | "app_action"
    action: str
    confidence: float
    requires_confirmation: bool
    target: str = None


# (action, kind, phrases, requires_confirmation) — requires_confirmation is
# hardcoded here, not caller-configurable, for anything destructive.
_VOCABULARY = [
    ("start_recording", "app_action", ["start recording", "start dictating"], False),
    ("stop_recording", "app_action", ["stop recording", "stop dictating"], False),
    ("open_settings", "app_action", ["open settings"], False),
    ("cancel", "draft_action", ["cancel that", "cancel it", "discard that", "discard it"], False),
    ("read_back", "draft_action", ["read that back", "read it back", "read that", "read it"], False),
    ("send", "draft_action", ["send it", "send that"], True),
    ("copy", "draft_action", ["copy it", "copy that"], False),
    ("rewrite_shorter", "draft_action", ["make it shorter", "make that shorter"], False),
    ("rewrite_clearer", "draft_action", ["make it clearer", "make that clearer"], False),
    ("retry", "draft_action", ["try again", "redo that"], False),
    ("delete_history", "app_action", ["delete all history", "delete my history", "delete history"], True),
]


def _strip_prefix(text):
    stripped = _PREFIX_RE.sub("", text)
    return stripped, stripped != text


def _context_is_clear(context, had_prefix):
    context = context or {}
    return had_prefix or any(
        context.get(flag)
        for flag in ("review_overlay_open", "post_wake_word", "command_mode_on", "prefixed")
    )


def parse_command(text, context=None):
    """Classify a transcript into a VoiceCommandIntent, or return None if no
    command is recognized — including when a command phrase is present but
    there is no clear command context (see module docstring)."""
    if not text:
        return None
    raw = text.strip()
    lowered = raw.lower()

    if _EMERGENCY_STOP_RE.search(lowered):
        return VoiceCommandIntent(
            kind="app_action", action="emergency_stop", confidence=1.0, requires_confirmation=False,
        )

    stripped, had_prefix = _strip_prefix(raw)
    stripped_lower = stripped.lower().strip()

    if not _context_is_clear(context, had_prefix):
        return None

    switch_match = _SWITCH_PERSONA_RE.search(stripped_lower)
    if switch_match:
        return VoiceCommandIntent(
            kind="app_action", action="switch_persona", confidence=1.0,
            requires_confirmation=False, target=switch_match.group(1).strip(),
        )

    # Exact/contained phrase match first (longest phrase first so a more
    # specific phrase wins), then a fuzzy whole-utterance fallback for near-miss ASR.
    for action, kind, phrases, requires_confirmation in sorted(
        _VOCABULARY, key=lambda v: max(len(p) for p in v[2]), reverse=True
    ):
        for phrase in phrases:
            if re.search(r"\b" + re.escape(phrase) + r"\b", stripped_lower):
                return VoiceCommandIntent(
                    kind=kind, action=action, confidence=1.0,
                    requires_confirmation=requires_confirmation,
                )

    best = None
    for action, kind, phrases, requires_confirmation in _VOCABULARY:
        for phrase in phrases:
            score = difflib.SequenceMatcher(None, stripped_lower, phrase).ratio()
            if score >= FUZZY_THRESHOLD and (best is None or score > best[0]):
                best = (score, action, kind, requires_confirmation)

    if best:
        score, action, kind, requires_confirmation = best
        return VoiceCommandIntent(
            kind=kind, action=action, confidence=score, requires_confirmation=requires_confirmation,
        )

    return None
