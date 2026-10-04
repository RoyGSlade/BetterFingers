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

Wave 9 adds a *classification* layer on top of this parser (see the second half
of the file). It does not replace anything above: ``parse_command`` keeps its
exact behaviour and remains the only thing that decides whether an app/draft
command fires. The classifier calls it, and adds the three answers it cannot
give on its own — this is ordinary dictation, this is dictation aimed at
someone, this is a saved launcher workflow — plus the one that matters most:
this is a command I do not know, and I will explain myself instead of guessing.
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


# =============================================================================
# Wave 9 — utterance classification (D-0011)
# =============================================================================
#
# Five categories, and the whole design is in which one an ambiguous utterance
# falls into:
#
#   ordinary_dictation      text to transcribe. The default, and the answer
#                           whenever there is no clear command context -- the
#                           existing conservative rule, unchanged.
#   directed_dictation      dictation the user aimed at somebody ("tell Sam
#                           I'm running late"). Still dictation: it changes
#                           where a draft is headed, never what runs.
#   betterfingers_control   an app/draft command parse_command resolved.
#   launcher_workflow       an EXACT trigger phrase of a saved workflow.
#   unknown_command         a command-shaped phrase nothing matched.
#
# THE RULE FOR unknown_command. It explains itself and offers the builder, and
# it can never execute. `executable` is False on that branch by construction and
# `tests/test_voice_commands.py` asserts it for every unknown input it can
# generate. The failure this prevents is the one that looks helpful: an
# assistant that hears "open my streaming setup", doesn't have it, and does
# something approximately like it.
#
# AND NO GENERATED COMMANDS, EVER. Nothing in this module composes a shell,
# PowerShell or CMD line, and no explanation offers one as a workaround -- "you
# could run this in a terminal instead" turns a refusal into a copy-pasteable
# instruction and moves the risk somewhere with no preview and no approval.
# `UNKNOWN_COMMAND_EXPLANATION` is a fixed sentence, asserted free of command
# syntax in the tests.

CATEGORY_ORDINARY_DICTATION = "ordinary_dictation"
CATEGORY_DIRECTED_DICTATION = "directed_dictation"
CATEGORY_BETTERFINGERS_CONTROL = "betterfingers_control"
CATEGORY_LAUNCHER_WORKFLOW = "launcher_workflow"
CATEGORY_UNKNOWN_COMMAND = "unknown_command"

CATEGORIES = (
    CATEGORY_ORDINARY_DICTATION,
    CATEGORY_DIRECTED_DICTATION,
    CATEGORY_BETTERFINGERS_CONTROL,
    CATEGORY_LAUNCHER_WORKFLOW,
    CATEGORY_UNKNOWN_COMMAND,
)

UNKNOWN_COMMAND_EXPLANATION = (
    "BetterFingers heard that as a command but has no workflow with that "
    "phrase, so it did nothing. You can build one: describe the steps, check "
    "the preview, and approve it before it can run."
)

# "Tell Sam that ...", "reply to Priya saying ...". The captured group is the
# addressee AS SPOKEN -- it is carried so the draft can be routed, and it is
# never used to look a contact up automatically or to guess a relationship.
_DIRECTED_RE = re.compile(
    r"^\s*(?:please\s+)?"
    r"(?P<verb>tell|text|message|reply\s+to|respond\s+to|write\s+to|ask|email|dm)\s+"
    # One or two name-shaped words. The negative lookahead keeps the connector
    # out of the addressee: without it "Tell Sam that I am late" addresses
    # "Sam that", which then fails to match any contact and looks like a
    # transcription problem rather than a parser one.
    r"(?P<target>[a-z][\w'-]*(?:\s+(?!that\b|about\b|saying\b|to\b)[a-z][\w'-]*)?)"
    r"(?:\s+(?:that|about|saying|to)\b|\s*[,:]|\s+)(?P<body>.+)$",
    re.IGNORECASE,
)

# Command-shaped but unresolved. Used ONLY to make the explanation specific --
# it never routes anything, and matching it is not a licence to act.
_LAUNCH_SHAPED_RE = re.compile(
    r"^\s*(?:open|launch|start|run|fire\s+up|boot\s+up)\b", re.IGNORECASE,
)


@dataclass
class UtteranceClassification:
    """What kind of thing the user just said, and whether anything may run.

    ``executable`` is the load-bearing field. Callers must gate on it rather
    than on the category string: a future category added without an execution
    path stays inert instead of falling through a ``!= "unknown_command"``
    check somewhere.
    """

    category: str
    executable: bool = False
    confidence: float = 0.0
    intent: object = None          # VoiceCommandIntent for betterfingers_control
    workflow_id: str = ""          # for launcher_workflow
    target: str = ""               # addressee for directed_dictation
    text: str = ""                 # the dictation body, for the dictation categories
    explanation: str = ""
    offers_builder: bool = False
    matched_phrase: str = ""

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "executable": self.executable,
            "confidence": self.confidence,
            "workflow_id": self.workflow_id,
            "target": self.target,
            "explanation": self.explanation,
            "offers_builder": self.offers_builder,
            "matched_phrase": self.matched_phrase,
        }


def normalize_workflow_phrase(value):
    """The one normalisation both sides of trigger matching use.

    Shared with ``backend.domain.actions.normalize_trigger_phrase`` by having
    exactly the same body: lower, punctuation out, whitespace collapsed. Two
    slightly different normalisers on the two sides of a match is how a trigger
    the user can see in the UI turns out not to fire.
    """
    text = str(value or "").strip().lower()
    text = re.sub(r"[^\w\s'-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _match_workflow(stripped_lower, workflow_phrases):
    """Exact phrase -> workflow id. Exact, never fuzzy, never substring.

    A fuzzy match here launches applications because a sentence rhymed with a
    trigger. ``parse_command``'s fuzzy fallback is acceptable for "send it"
    because the draft is still shown; opening a program has no such backstop.
    """
    needle = normalize_workflow_phrase(stripped_lower)
    if not needle:
        return "", ""
    for phrase, workflow_id in (workflow_phrases or {}).items():
        if normalize_workflow_phrase(phrase) == needle:
            return workflow_id, needle
    return "", ""


def classify_utterance(text, context=None, workflow_phrases=None):
    """Classify one transcript into exactly one ``UtteranceClassification``.

    ``workflow_phrases`` is ``{trigger phrase: workflow id}`` for workflows that
    are saved, enabled AND approved. Passing an unapproved workflow's phrase
    here would not make it run -- ``WorkflowStore.can_run`` is the gate -- but
    it would make the UI claim a match that then refuses, so callers pass only
    runnable ones.
    """
    raw = (text or "").strip()
    if not raw:
        return UtteranceClassification(
            category=CATEGORY_ORDINARY_DICTATION, executable=False, text="",
        )

    # Emergency stop keeps its unconditional path, exactly as parse_command
    # defines it: a safety valve is not a thing to classify carefully.
    intent = parse_command(raw, context)
    if intent is not None and intent.action == "emergency_stop":
        return UtteranceClassification(
            category=CATEGORY_BETTERFINGERS_CONTROL, executable=True,
            confidence=intent.confidence, intent=intent, text=raw,
        )

    stripped, had_prefix = _strip_prefix(raw)
    stripped_lower = stripped.lower().strip()
    clear_context = _context_is_clear(context, had_prefix)

    if clear_context:
        workflow_id, phrase = _match_workflow(stripped_lower, workflow_phrases)
        if workflow_id:
            return UtteranceClassification(
                category=CATEGORY_LAUNCHER_WORKFLOW, executable=True, confidence=1.0,
                workflow_id=workflow_id, matched_phrase=phrase, text=raw,
            )

        if intent is not None:
            return UtteranceClassification(
                category=CATEGORY_BETTERFINGERS_CONTROL, executable=True,
                confidence=intent.confidence, intent=intent, text=raw,
            )

    directed = _DIRECTED_RE.match(stripped)
    if directed:
        body = directed.group("body").strip()
        return UtteranceClassification(
            category=CATEGORY_DIRECTED_DICTATION,
            # Dictation, not execution: the draft still goes through the normal
            # review before anything is sent.
            executable=False,
            confidence=1.0,
            target=directed.group("target").strip(),
            text=body,
        )

    if not clear_context:
        # The original rule, unchanged and load-bearing: outside a clear command
        # context, a paragraph containing "send it" is a paragraph.
        return UtteranceClassification(
            category=CATEGORY_ORDINARY_DICTATION, executable=False, text=raw,
        )

    explanation = UNKNOWN_COMMAND_EXPLANATION
    if _LAUNCH_SHAPED_RE.match(stripped):
        explanation = (
            "BetterFingers heard that as a request to open something, but no "
            "saved workflow uses that phrase, so it did nothing. You can build "
            "one: describe the steps, check the preview, and approve it before "
            "it can run."
        )
    return UtteranceClassification(
        category=CATEGORY_UNKNOWN_COMMAND,
        executable=False,
        confidence=0.0,
        text=raw,
        explanation=explanation,
        offers_builder=True,
    )
