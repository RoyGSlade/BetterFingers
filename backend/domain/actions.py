"""Restricted action schema v1 — the security boundary for application
workflows (Wave 9, binding ruling D-0011).

A *workflow* is a named list of steps a user approved once and can then trigger
by voice or by button. The entire value of this feature comes from the fact that
it is **not** a scripting language:

    Store only versioned restricted actions, validate targets, show an exact
    preview, require approval, and execute through platform adapters using
    argument arrays.  -- D-0011

So this module is deliberately closed. ``ALLOWED_ACTIONS`` is a literal tuple of
ten verbs, each with a literal parameter vocabulary; anything else is refused
**with a reason** rather than dropped. The distinction matters: a dropped step
leaves the user believing the workflow they described was saved, and the first
time they run it, it silently does less than they asked. A refusal names the
step and says why BetterFingers will not do it.

WHY REFUSAL AND NOT SANITISATION. The prohibited list below (shell, delete,
kill, registry, credentials, purchases, hidden messages, generated code) is not
a list of things that need escaping — it is a list of things this product does
not do at all. There is no "safe" quoting of ``rm -rf`` that makes it acceptable
for a voice assistant to run it because a transcript sounded like it, and a
natural-language front end is exactly the kind of caller that will occasionally
produce a step nobody asked for. The only defensible answer is that the verb has
no implementation to reach.

NOTHING HERE EXECUTES. This module is pure data: normalisation, bounds, and
classification. Target existence is ``backend.services.action_validator``'s job
(a step may only name an application the user already confirmed in the registry)
and actually launching is the Electron main process's
(``app/src/main/applicationLauncher.js``, argument arrays only, never a shell
string). Keeping those three apart is what makes each one auditable.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

# Schema history:
#   v1 (current): {"schema_version": 1, "id", "name", "trigger_phrases", "steps"}
# Each stored workflow carries its own schema_version because a single workflow
# is also a document people export, hand-edit and paste at each other.
SCHEMA_VERSION = 1

# The COMPLETE field set of a workflow document. An explicit tuple rather than
# something inferred, so adding a field is a deliberate edit somebody reviews.
WORKFLOW_FIELDS = ("schema_version", "id", "name", "trigger_phrases", "steps")

# --- The allowed vocabulary --------------------------------------------------
#
# Ten verbs. Each one either opens something the user already confirmed exists,
# or flips a BetterFingers-internal setting the user could have flipped in
# Settings anyway. None of them writes to the filesystem, ends a process, sends
# a message, or spends money.

ACTION_LAUNCH_APP = "launch_app"
ACTION_FOCUS_APP = "focus_app"
ACTION_OPEN_URI = "open_uri"
ACTION_OPEN_FOLDER = "open_folder"
ACTION_WAIT_FOR_PROCESS = "wait_for_process"
ACTION_ACTIVATE_APPLICATION_PROFILE = "activate_application_profile"
ACTION_ACTIVATE_PERSONA = "activate_persona"
ACTION_ACTIVATE_WRITING_PRESET = "activate_writing_preset"
ACTION_SHOW_NOTIFICATION = "show_notification"
ACTION_SPEAK_CONFIRMATION = "speak_confirmation"

ALLOWED_ACTIONS = (
    ACTION_LAUNCH_APP,
    ACTION_FOCUS_APP,
    ACTION_OPEN_URI,
    ACTION_OPEN_FOLDER,
    ACTION_WAIT_FOR_PROCESS,
    ACTION_ACTIVATE_APPLICATION_PROFILE,
    ACTION_ACTIVATE_PERSONA,
    ACTION_ACTIVATE_WRITING_PRESET,
    ACTION_SHOW_NOTIFICATION,
    ACTION_SPEAK_CONFIRMATION,
)

# Which parameter each verb carries, and nothing else. A step is
# {"action": <verb>, <the field below>: <value>} plus, for wait_for_process
# only, an optional bounded timeout.
ACTION_PARAM = {
    ACTION_LAUNCH_APP: "app_id",
    ACTION_FOCUS_APP: "app_id",
    ACTION_OPEN_URI: "uri",
    ACTION_OPEN_FOLDER: "path",
    ACTION_WAIT_FOR_PROCESS: "app_id",
    ACTION_ACTIVATE_APPLICATION_PROFILE: "profile_id",
    ACTION_ACTIVATE_PERSONA: "persona",
    ACTION_ACTIVATE_WRITING_PRESET: "preset",
    ACTION_SHOW_NOTIFICATION: "message",
    ACTION_SPEAK_CONFIRMATION: "message",
}

# Verbs whose parameter names a registry application. The validator resolves
# every one of these against the confirmed application registry; a workflow
# cannot escape the registry because there is no other way to say "this app".
APP_TARGET_ACTIONS = (ACTION_LAUNCH_APP, ACTION_FOCUS_APP, ACTION_WAIT_FOR_PROCESS)

# --- The prohibited list -----------------------------------------------------
#
# Enforced by refusal-with-reason. Each reason is written for the person who
# just asked for it, not for a log: it says what will not happen and why, in one
# sentence, without offering a workaround. Offering one ("you could run this in
# a terminal instead") would defeat the point -- the product's answer is that it
# does not do this, not that it does it somewhere less visible.

_SHELL_REASON = (
    "BetterFingers never runs shell commands. Workflows are a fixed list of "
    "approved actions, not a script, so there is no command line for a "
    "transcript to end up on."
)
_DESTRUCTIVE_REASON = (
    "Workflows never change or remove your files. Opening a folder is the most "
    "a workflow can do with your data, so a misheard phrase cannot lose it."
)
_PROCESS_REASON = (
    "Workflows never close or kill programs. Ending the wrong process loses "
    "unsaved work, and a voice trigger is not a safe way to decide which one."
)

PROHIBITED_ACTIONS = {
    "shell": _SHELL_REASON,
    "bash": _SHELL_REASON,
    "powershell": _SHELL_REASON,
    "cmd": _SHELL_REASON,
    "delete": _DESTRUCTIVE_REASON,
    "move": _DESTRUCTIVE_REASON,
    "rename": _DESTRUCTIVE_REASON,
    "install": (
        "Workflows never install software. Installing changes the machine "
        "outside BetterFingers, and it is not something a saved phrase should "
        "be able to start."
    ),
    "close_app": _PROCESS_REASON,
    "kill_process": _PROCESS_REASON,
    "edit_registry": (
        "Workflows never edit the Windows registry. A wrong registry write can "
        "leave the machine unbootable and there is no undo."
    ),
    "type_password": (
        "Workflows never type passwords or other credentials. BetterFingers "
        "does not hold your credentials and will not synthesise them into "
        "whatever window happens to have focus."
    ),
    "purchase": (
        "Workflows never buy anything. Spending money is not something a "
        "misheard phrase may do on your behalf."
    ),
    "send_hidden_message": (
        "Workflows never send a message you did not see first. Every outgoing "
        "message goes through the normal review you can read and cancel."
    ),
    "generated_code": (
        "Workflows never run generated code. A workflow is only ever the fixed "
        "list of approved actions shown in the preview you approved."
    ),
}

# Aliases the natural-language front end plausibly emits for the same
# prohibited thing. Mapped to the SAME reason, so "run_command" is refused as
# clearly as "shell". Not an attempt at an exhaustive blocklist -- the closed
# ALLOWED_ACTIONS tuple is what makes the boundary hold, and this table only
# improves the wording of the refusal.
PROHIBITED_ALIASES = {
    "run_command": "shell",
    "run_script": "shell",
    "exec": "shell",
    "execute": "shell",
    "sh": "bash",
    "zsh": "bash",
    "pwsh": "powershell",
    "cmd_exe": "cmd",
    "terminal": "shell",
    "delete_file": "delete",
    "remove_file": "delete",
    "move_file": "move",
    "rename_file": "rename",
    "install_package": "install",
    "quit_app": "close_app",
    "close_application": "close_app",
    "kill": "kill_process",
    "taskkill": "kill_process",
    "registry": "edit_registry",
    "type_credentials": "type_password",
    "enter_password": "type_password",
    "buy": "purchase",
    "checkout": "purchase",
    "send_message_silently": "send_hidden_message",
    "eval": "generated_code",
    "run_code": "generated_code",
}

UNKNOWN_ACTION_REASON = (
    "That is not one of the actions a workflow can perform. Workflows are "
    "limited to opening applications, folders and links, switching a "
    "BetterFingers setting, and telling you what happened."
)

# --- Bounds ------------------------------------------------------------------
#
# Every one of these is a real limit, not a formality: the store re-reads the
# whole file on every mutation, the preview has to be readable in one screen,
# and a URI is handed to a platform opener.

MAX_ID_LEN = 64
MAX_NAME_LEN = 80
MAX_PHRASE_LEN = 120
MAX_PHRASES = 12
MAX_STEPS = 12
MAX_MESSAGE_LEN = 200
MAX_URI_LEN = 2048
MAX_PATH_LEN = 4096
MAX_TARGET_LEN = 120
MAX_WAIT_MS = 60_000
DEFAULT_WAIT_MS = 5_000

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_SCHEME_RE = re.compile(r"^([a-z][a-z0-9+.-]*):", re.IGNORECASE)

# Schemes any workflow may use without the registry vouching for them. Kept to
# the three that cannot reach the local filesystem or a script engine. Anything
# else (steam:, spotify:, discord:) is allowed ONLY when a confirmed registry
# entry declares that scheme -- see action_validator.
ALLOWED_URI_SCHEMES = ("http", "https", "mailto")

# Refused by name rather than by falling through the allowlist, so the reason
# can say what is actually wrong.
DANGEROUS_URI_SCHEMES = {
    "javascript": "A javascript: link runs code, which a workflow never does.",
    "data": "A data: link carries its own inline payload, which cannot be previewed honestly.",
    "vbscript": "A vbscript: link runs code, which a workflow never does.",
    "file": "Use “open folder” instead — it is bounded to a folder you picked.",
}


@dataclass
class Refusal:
    """One thing BetterFingers will not do, and why, in the user's words."""

    step_index: int
    action: str
    reason: str
    code: str = "prohibited_action"

    def to_dict(self) -> dict:
        return {
            "step_index": self.step_index,
            "action": self.action,
            "reason": self.reason,
            "code": self.code,
        }


@dataclass
class CompileResult:
    ok: bool
    workflow: Optional[dict] = None
    refusals: list = field(default_factory=list)
    dropped_fields: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "workflow": self.workflow,
            "refusals": [r.to_dict() for r in self.refusals],
            "dropped_fields": list(self.dropped_fields),
        }


# --- Normalisation -----------------------------------------------------------


def _strip_controls(value) -> str:
    """Drop C0/C1 control characters and normalise to NFC.

    Newlines and NULs are the interesting ones: a target carrying a newline is
    how a single value turns into two when something downstream splits on it,
    and this project's rule is that such a value never gets that far.
    """
    text = unicodedata.normalize("NFC", str(value if value is not None else ""))
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cc")


def _clean_text(value, limit: int) -> str:
    return _strip_controls(value).strip()[:limit]


def normalize_workflow_id(value) -> str:
    """Lowercase, underscore-separated, ascii. ``''`` if unusable.

    Ids appear in run history and in status codes, so they stay opaque and
    boring: they are never derived from anything the user said out loud.
    """
    token = re.sub(r"[^a-z0-9_]+", "_", _strip_controls(value).strip().lower()).strip("_")
    token = token[:MAX_ID_LEN]
    return token if _ID_RE.match(token) else ""


def normalize_trigger_phrase(value) -> str:
    """A trigger phrase is matched, never executed: collapse whitespace, lower,
    and bound it. Punctuation is kept out so "open my studio." and "open my
    studio" are the same trigger rather than two the user has to guess between.
    """
    text = _clean_text(value, MAX_PHRASE_LEN).lower()
    text = re.sub(r"[^\w\s'-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_uri(value) -> tuple[str, str]:
    """``(uri, reason)`` — reason is ``''`` when the URI is usable.

    Bounded, control-free, and scheme-checked. The scheme allowlist here is the
    *unconditional* one; a registry-declared scheme is accepted later by the
    validator, which is the only layer that knows what the user confirmed.
    """
    text = _clean_text(value, MAX_URI_LEN + 1)
    if not text:
        return "", "That step has no link to open."
    if len(text) > MAX_URI_LEN:
        return "", f"That link is longer than {MAX_URI_LEN} characters."
    if " " in text:
        # Not escaped for the user: a link with a space in it is virtually
        # always a transcription artefact, and silently percent-encoding it
        # would open a subtly different address than the preview showed.
        return "", "That link contains a space, so it is not a single address."
    match = _SCHEME_RE.match(text)
    if not match:
        return "", "That link has no scheme (it should start with https:// or similar)."
    scheme = match.group(1).lower()
    if scheme in DANGEROUS_URI_SCHEMES:
        return "", DANGEROUS_URI_SCHEMES[scheme]
    return text, ""


def normalize_folder_path(value) -> tuple[str, str]:
    """``(path, reason)`` for an *existing-shaped* absolute folder path.

    ``~`` is expanded, ``..`` is refused outright rather than resolved: a
    workflow preview that reads ``~/Documents/../..`` and a workflow that opens
    the filesystem root are the same workflow, and only one of them looks like
    it. Whether the folder exists is the validator's question, not this one's.
    """
    import os

    text = _clean_text(value, MAX_PATH_LEN + 1)
    if not text:
        return "", "That step has no folder to open."
    if len(text) > MAX_PATH_LEN:
        return "", "That folder path is too long."
    if "\x00" in text:  # pragma: no cover - _strip_controls already removes it
        return "", "That folder path is not a valid path."
    expanded = os.path.expanduser(text)
    parts = re.split(r"[\\/]+", expanded)
    if any(part == ".." for part in parts):
        return "", "A folder path may not contain “..”; give the folder directly."
    if not os.path.isabs(expanded):
        return "", "Give the full path to the folder, starting from your home folder or the drive root."
    return os.path.normpath(expanded), ""


def _normalize_wait_ms(value) -> int:
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return DEFAULT_WAIT_MS
    return max(0, min(MAX_WAIT_MS, ms))


# --- Step compilation --------------------------------------------------------


def classify_action(raw_action) -> tuple[str, str]:
    """``(kind, canonical)`` where kind is ``allowed`` | ``prohibited`` | ``unknown``.

    Canonicalises loosely: the natural-language front end produces
    ``"Launch App"`` and ``"launch-app"`` about as often as ``"launch_app"``,
    and a refusal that fired only on the exact spelling would be a boundary in
    name only.
    """
    token = re.sub(r"[^a-z0-9]+", "_", _strip_controls(raw_action).strip().lower()).strip("_")
    if not token:
        return "unknown", ""
    if token in ALLOWED_ACTIONS:
        return "allowed", token
    if token in PROHIBITED_ACTIONS:
        return "prohibited", token
    alias = PROHIBITED_ALIASES.get(token)
    if alias:
        return "prohibited", alias
    return "unknown", token


def refusal_reason(action) -> str:
    """The sentence shown to the user for a verb a workflow will not perform."""
    kind, canonical = classify_action(action)
    if kind == "prohibited":
        return PROHIBITED_ACTIONS[canonical]
    return UNKNOWN_ACTION_REASON


def compile_step(raw, index: int) -> tuple[Optional[dict], Optional[Refusal]]:
    """One step in, either a normalised step or a refusal out. Never both."""
    if not isinstance(raw, dict):
        return None, Refusal(index, "", UNKNOWN_ACTION_REASON, code="malformed_step")

    kind, canonical = classify_action(raw.get("action"))
    if kind == "prohibited":
        return None, Refusal(index, canonical, PROHIBITED_ACTIONS[canonical])
    if kind == "unknown":
        return None, Refusal(
            index,
            canonical or "",
            UNKNOWN_ACTION_REASON,
            code="unknown_action",
        )

    param = ACTION_PARAM[canonical]
    value = raw.get(param)

    if param == "uri":
        uri, reason = normalize_uri(value)
        if reason:
            return None, Refusal(index, canonical, reason, code="invalid_target")
        return {"action": canonical, "uri": uri}, None

    if param == "path":
        path, reason = normalize_folder_path(value)
        if reason:
            return None, Refusal(index, canonical, reason, code="invalid_target")
        return {"action": canonical, "path": path}, None

    if param == "message":
        message = _clean_text(value, MAX_MESSAGE_LEN)
        if not message:
            return None, Refusal(
                index, canonical,
                "That step has nothing to say.", code="invalid_target",
            )
        return {"action": canonical, "message": message}, None

    if param in ("app_id", "profile_id"):
        target = normalize_workflow_id(value)
        if not target:
            noun = "application" if param == "app_id" else "application profile"
            return None, Refusal(
                index, canonical,
                f"That step does not name an {noun} BetterFingers knows about.",
                code="invalid_target",
            )
        step = {"action": canonical, param: target}
        if canonical == ACTION_WAIT_FOR_PROCESS:
            step["timeout_ms"] = _normalize_wait_ms(raw.get("timeout_ms", DEFAULT_WAIT_MS))
        return step, None

    # persona / writing preset: free-form names the user already owns
    # elsewhere in the app, so they keep their spelling, bounded.
    target = _clean_text(value, MAX_TARGET_LEN)
    if not target:
        noun = "persona" if param == "persona" else "writing preset"
        return None, Refusal(
            index, canonical, f"That step does not name a {noun}.", code="invalid_target",
        )
    return {"action": canonical, param: target}, None


def compile_workflow(payload) -> CompileResult:
    """Arbitrary input -> a v1 workflow document, or refusals explaining why not.

    ``ok`` is False if **any** step was refused, and the surviving steps are
    still returned so the builder can show the user exactly which line it will
    not do. Partial saving is not offered: a workflow that quietly lost its
    third step is a workflow that lies about what it does every time it runs.
    """
    if not isinstance(payload, dict):
        return CompileResult(ok=False, refusals=[
            Refusal(0, "", "There is nothing here to build a workflow from.", code="malformed_workflow"),
        ])

    dropped = sorted(key for key in payload if key not in WORKFLOW_FIELDS)

    workflow_id = normalize_workflow_id(payload.get("id"))
    name = _clean_text(payload.get("name"), MAX_NAME_LEN)
    if not workflow_id:
        workflow_id = normalize_workflow_id(name)

    phrases, seen = [], set()
    raw_phrases = payload.get("trigger_phrases")
    if isinstance(raw_phrases, str):
        raw_phrases = [raw_phrases]
    if isinstance(raw_phrases, (list, tuple)):
        for item in raw_phrases:
            phrase = normalize_trigger_phrase(item)
            if phrase and phrase not in seen:
                seen.add(phrase)
                phrases.append(phrase)
            if len(phrases) >= MAX_PHRASES:
                break

    raw_steps = payload.get("steps")
    raw_steps = list(raw_steps) if isinstance(raw_steps, (list, tuple)) else []

    refusals = []
    if len(raw_steps) > MAX_STEPS:
        refusals.append(Refusal(
            MAX_STEPS, "",
            f"A workflow can have at most {MAX_STEPS} steps; this one has {len(raw_steps)}.",
            code="too_many_steps",
        ))
        raw_steps = raw_steps[:MAX_STEPS]

    steps = []
    for index, raw_step in enumerate(raw_steps):
        step, refusal = compile_step(raw_step, index)
        if refusal is not None:
            refusals.append(refusal)
        else:
            steps.append(step)

    if not workflow_id:
        refusals.append(Refusal(0, "", "Give the workflow a name.", code="invalid_id"))
    if not steps and not refusals:
        refusals.append(Refusal(0, "", "A workflow needs at least one step.", code="empty_workflow"))

    workflow = {
        "schema_version": SCHEMA_VERSION,
        "id": workflow_id,
        "name": name or workflow_id,
        "trigger_phrases": phrases,
        "steps": steps,
    }
    return CompileResult(
        ok=not refusals,
        workflow=workflow,
        refusals=refusals,
        dropped_fields=dropped,
    )


def step_target(step) -> str:
    """The one value a step acts on, for previews and status lines."""
    if not isinstance(step, dict):
        return ""
    param = ACTION_PARAM.get(step.get("action"), "")
    return str(step.get(param, "")) if param else ""
