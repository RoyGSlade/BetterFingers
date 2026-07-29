"""Shared input-action IDs — the one vocabulary every non-voice device speaks
(Wave 10).

A controller button, a Stream Deck key and the dashboard's own buttons are three
ways of asking for the *same* thing. Wave 10's rule is that they say it in the
same words:

    Controller and Stream Deck invoke the same action IDs through the same
    gate.  -- D-0027 addendum

So this module is the closed list of those words, and nothing else. It holds no
device code, no transport, no persistence: a controller adapter turns joystick
events into an action id, the Stream Deck plugin turns a key press into an
action id, and exactly one dispatcher downstream turns an action id into the
call that voice and the keyboard already make.

WHY A SHARED VOCABULARY AND NOT PER-DEVICE HANDLERS. The failure this prevents
is the one that has already happened once in this codebase: the controller path
started a recording by calling ``hotkey_manager`` directly while the dashboard
button went through ``/runtime/recording/toggle``, and the two disagreed about
what "busy" meant. A second, parallel implementation of "begin dictation" is a
second place for the privacy lease not to be released. There is one id, so
there is one handler, so there is one release path.

WHAT IS DELIBERATELY NOT HERE. No id types text, sends a message, runs a shell
command, or names a person. ``workflow.run`` names a *saved, approved* workflow
by id and reaches execution through the Wave 9 approval gate — a button cannot
describe a new workflow, only trigger one the user already read and approved.

EMERGENCY STOP IS SPECIAL AND SAYS SO. ``emergency.stop`` is the only id marked
``always_available``. Every device that can be bound at all must be able to
reach it, it ignores device scoping, and it is dispatched even when the input
layer is otherwise suspended. A panic button that respects a filter is not a
panic button.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Schema history:
#   v1 (current): action ids below, `<noun>.<verb>` dotted form.
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class InputAction:
    """One thing a bound device may ask BetterFingers to do."""

    id: str
    label: str
    #: Which parameter the action carries, or "" when it takes none. A
    #: parameterised action is only meaningful on a device that can store the
    #: parameter with the binding (a Stream Deck key's settings, a controller
    #: binding record) -- it is never inferred from context.
    param: str = ""
    #: True when the action is one half of a held pair (press begins, release
    #: ends). Only holdable ids may be bound in `hold` mode.
    holdable: bool = False
    #: The id that ends this one when it is bound in `hold` mode.
    release_id: str = ""
    #: Dispatched regardless of device scope, profile, or a suspended engine.
    always_available: bool = False
    #: Short sentence the setup UI shows next to the binding row.
    description: str = ""


# --- Capture -----------------------------------------------------------------

ACTION_DICTATION_BEGIN = "dictation.begin"
ACTION_DICTATION_END = "dictation.end"
ACTION_DICTATION_TOGGLE = "dictation.toggle"
ACTION_COMMAND_BEGIN = "command.begin"
ACTION_COMMAND_END = "command.end"
ACTION_CAPTURE_CANCEL = "capture.cancel"

# --- The latest draft --------------------------------------------------------

ACTION_LATEST_READ = "latest.read"
ACTION_LATEST_COPY = "latest.copy"
ACTION_LATEST_INJECT = "latest.inject"

# --- Settings the user could have flipped in the app anyway ------------------

ACTION_PERSONA_ACTIVATE = "persona.activate"
ACTION_WRITING_PRESET_ACTIVATE = "writing_preset.activate"
ACTION_APPLICATION_PROFILE_ACTIVATE = "application_profile.activate"

# --- Wave 9 workflows --------------------------------------------------------

ACTION_WORKFLOW_RUN = "workflow.run"

# --- The panic button --------------------------------------------------------

ACTION_EMERGENCY_STOP = "emergency.stop"


ACTIONS: tuple = (
    InputAction(
        id=ACTION_DICTATION_BEGIN,
        label="Begin dictation",
        holdable=True,
        release_id=ACTION_DICTATION_END,
        description="Start recording what you say as text.",
    ),
    InputAction(
        id=ACTION_DICTATION_END,
        label="End dictation",
        description="Stop recording and start turning it into text.",
    ),
    InputAction(
        id=ACTION_DICTATION_TOGGLE,
        label="Start or stop dictation",
        description="One button for both: press to start, press again to stop.",
    ),
    # Command capture is a SEPARATE binding, not a mode of dictation. Deliverable
    # 1's "separate bindings at minimum" is this line: a user who has bound only
    # dictation cannot accidentally issue a command, because there is no button
    # that means both.
    InputAction(
        id=ACTION_COMMAND_BEGIN,
        label="Begin command",
        holdable=True,
        release_id=ACTION_COMMAND_END,
        description="Start listening for a BetterFingers command instead of dictation.",
    ),
    InputAction(
        id=ACTION_COMMAND_END,
        label="End command",
        description="Stop listening for a command and act on what was said.",
    ),
    InputAction(
        id=ACTION_CAPTURE_CANCEL,
        label="Cancel",
        description="Throw away what is being captured right now. Nothing is kept.",
    ),
    InputAction(
        id=ACTION_LATEST_READ,
        label="Read the latest draft aloud",
        description="Speak the most recent draft so you can hear it without looking.",
    ),
    InputAction(
        id=ACTION_LATEST_COPY,
        label="Copy the latest draft",
        description="Put the most recent draft on the clipboard.",
    ),
    InputAction(
        id=ACTION_LATEST_INJECT,
        label="Type the latest draft",
        description="Deliver the most recent draft to whatever window has focus.",
    ),
    InputAction(
        id=ACTION_PERSONA_ACTIVATE,
        label="Switch persona",
        param="persona",
        description="Switch to a persona you already made.",
    ),
    InputAction(
        id=ACTION_WRITING_PRESET_ACTIVATE,
        label="Switch writing preset",
        param="preset",
        description="Switch to a writing preset you already made.",
    ),
    InputAction(
        id=ACTION_APPLICATION_PROFILE_ACTIVATE,
        label="Switch application profile",
        param="profile_id",
        description="Use a specific application profile until you switch again.",
    ),
    InputAction(
        id=ACTION_WORKFLOW_RUN,
        label="Run a saved workflow",
        param="workflow_id",
        description="Run a workflow you already approved. A button cannot create one.",
    ),
    InputAction(
        id=ACTION_EMERGENCY_STOP,
        label="Emergency stop",
        always_available=True,
        description="Stop everything now: recording, speech, and typing.",
    ),
)

ACTION_IDS = tuple(action.id for action in ACTIONS)
ACTION_BY_ID = {action.id: action for action in ACTIONS}

#: Ids a user may bind to a button. The release halves are dispatched by the
#: engine when a held binding is let go, never bound directly -- binding "end
#: dictation" to its own button is how you get a recording nothing can stop.
BINDABLE_ACTION_IDS = tuple(
    action.id for action in ACTIONS
    if action.id not in (ACTION_DICTATION_END, ACTION_COMMAND_END)
)

#: Ids that carry a parameter, so a binding without one is incomplete rather
#: than merely useless.
PARAMETERISED_ACTION_IDS = tuple(action.id for action in ACTIONS if action.param)

#: The Wave 10 requirement list, by id. Named explicitly rather than derived so
#: that deleting one is a test failure and not a quiet regression.
REQUIRED_ACTION_IDS = (
    ACTION_DICTATION_BEGIN,
    ACTION_DICTATION_END,
    ACTION_COMMAND_BEGIN,
    ACTION_CAPTURE_CANCEL,
    ACTION_LATEST_READ,
    ACTION_LATEST_INJECT,
    ACTION_LATEST_COPY,
    ACTION_EMERGENCY_STOP,
)

#: Devices that may carry bindings. A device kind is here only when this project
#: has code for it; adding a row is adding an adapter, not a label.
DEVICE_KINDS = ("controller", "stream_deck")

# --- Parameter bounds --------------------------------------------------------
#
# A parameter is a NAME the user already owns elsewhere in the app. It is never
# free text that reaches a shell, a URL, or a message, so the bounds here exist
# to keep a hand-edited binding file from carrying something absurd -- not to
# sanitise something dangerous.

MAX_PARAM_LEN = 120

_ID_PARAM_ACTIONS = frozenset(
    {ACTION_APPLICATION_PROFILE_ACTIVATE, ACTION_WORKFLOW_RUN}
)
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")


def normalize_action_id(value) -> str:
    """``''`` for anything that is not one of the ids above.

    Deliberately exact rather than fuzzy: an action id is produced by our own
    adapters from a stored binding, never by a transcript, so there is nothing
    to be lenient about and a typo should fail visibly.
    """
    token = str(value or "").strip().lower()
    return token if token in ACTION_BY_ID else ""


def normalize_param(action_id: str, value) -> tuple[str, str]:
    """``(param, reason)`` — ``reason`` is ``''`` when the parameter is usable.

    An action that takes no parameter returns ``("", "")`` and ignores whatever
    was passed, so a Stream Deck key carrying stale settings from a re-bound
    button does not smuggle a value into an action that has no slot for it.
    """
    action = ACTION_BY_ID.get(normalize_action_id(action_id))
    if action is None:
        return "", "That is not an action BetterFingers can perform."
    if not action.param:
        return "", ""

    text = " ".join(str(value or "").split())[:MAX_PARAM_LEN]
    if not text:
        return "", f"“{action.label}” needs you to choose which one."

    if action.id in _ID_PARAM_ACTIONS:
        token = re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")[:64]
        if not _ID_RE.match(token):
            return "", f"“{action.label}” does not name anything BetterFingers knows about."
        return token, ""
    return text, ""


def describe_action(action_id: str) -> Optional[dict]:
    action = ACTION_BY_ID.get(normalize_action_id(action_id))
    if action is None:
        return None
    return {
        "id": action.id,
        "label": action.label,
        "param": action.param,
        "holdable": action.holdable,
        "release_id": action.release_id,
        "always_available": action.always_available,
        "description": action.description,
        "bindable": action.id in BINDABLE_ACTION_IDS,
    }


def vocabulary() -> dict:
    """Everything a device adapter or a setup UI needs, in one payload, so no
    adapter hard-codes a list that can drift from this module."""
    return {
        "schema_version": SCHEMA_VERSION,
        "actions": [describe_action(action_id) for action_id in ACTION_IDS],
        "bindable": list(BINDABLE_ACTION_IDS),
        "required": list(REQUIRED_ACTION_IDS),
        "parameterised": list(PARAMETERISED_ACTION_IDS),
        "device_kinds": list(DEVICE_KINDS),
        "emergency_stop": ACTION_EMERGENCY_STOP,
    }
