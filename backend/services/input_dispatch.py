"""One action id in, one existing contract out (Wave 10).

This is the gate the Wave 10 addendum names: *"Controller and Stream Deck invoke
the same action IDs through the same gate."* It is a single ``dispatch`` method
and a table of injected handlers, and it is the only thing in the codebase that
turns an input-action id into a call.

WHY A TABLE OF INJECTED CALLABLES AND NOT DIRECT IMPORTS. The functions this
dispatches to live in ``server.py`` (``emergency_stop_runtime``,
``toggle_recording_runtime``, the draft helpers). Importing server.py from a
service would drag FastAPI, torch and the audio stack into every test that wants
to check a button, and would invert the dependency the rest of this codebase
maintains. So the integration supplies the handlers in one documented diff (see
docs/release/WAVE10_INTEGRATION_DIFFS.md) and the dispatcher is testable with a
dict of lambdas.

The other half of the reason is the requirement itself. "Bound through the SAME
internal contracts voice/keyboard use" is only true if the controller literally
calls the function the keyboard calls. A handler table makes that checkable:
the integration diff binds ``toggle_dictation`` to the same
``toggle_recording_runtime`` that ``POST /runtime/recording/toggle`` calls, and
if somebody later points it at a private copy, the diff is where that shows up.

WHAT AN UNBOUND HANDLER MEANS. ``unavailable`` — not a crash and not a silent
success. A build that has not wired ``read_latest`` yet should say so to the
user's face rather than swallow the press. That is why the table is Optional
callables and why ``available_actions()`` exists.

EMERGENCY STOP IGNORES EVERY GATE IN THIS FILE. Not enabled? It still runs. Not
paired? It still runs. Suspended for the setup wizard? It still runs. There is
no state of this application in which "stop everything" should be filtered, and
every other rule here is written to have an explicit exception for it rather
than to be trusted not to apply.

WORKFLOWS ARE NOT RUN HERE. ``workflow.run`` reaches ``request_workflow``, which
does not execute anything: Python has no code path that starts a process, and
Wave 9 built the approval gate precisely so that a *button* cannot bypass it.
The integration binds ``request_workflow`` to a status broadcast; the renderer
turns that into the one typed ``workflows:execute`` channel, which carries a
workflow id and nothing else, and the Electron main process re-fetches,
re-validates through ``POST /workflows/run`` and only then performs the approved
steps. A controller press and a Stream Deck press take that identical path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

from backend.domain.input_actions import (
    ACTION_APPLICATION_PROFILE_ACTIVATE,
    ACTION_BY_ID,
    ACTION_CAPTURE_CANCEL,
    ACTION_COMMAND_BEGIN,
    ACTION_COMMAND_END,
    ACTION_DICTATION_BEGIN,
    ACTION_DICTATION_END,
    ACTION_DICTATION_TOGGLE,
    ACTION_EMERGENCY_STOP,
    ACTION_LATEST_COPY,
    ACTION_LATEST_INJECT,
    ACTION_LATEST_READ,
    ACTION_PERSONA_ACTIVATE,
    ACTION_WORKFLOW_RUN,
    ACTION_WRITING_PRESET_ACTIVATE,
    normalize_action_id,
    normalize_param,
)

logger = logging.getLogger(__name__)

#: Every outcome a dispatch can have. Codes only, and deliberately few: this
#: list is what reaches a log line and a status event, and a code cannot quote
#: a draft, a persona name or a path the way a free-text error routinely does.
DISPATCH_STATUS_CODES = (
    "ok",
    "unknown_action",      # not one of ours
    "unavailable",         # no handler wired in this build
    "suspended",           # the input layer is deliberately not listening
    "disabled",            # the user switched this device kind off
    "needs_param",         # a parameterised action arrived without its value
    "failed",              # the handler raised
)


@dataclass
class InputActionHandlers:
    """The existing contracts, by name.

    Every field is Optional and defaults to ``None`` so a partially wired build
    is a build that reports ``unavailable`` for the parts it has not wired,
    rather than one that fails to import.
    """

    begin_dictation: Optional[Callable[[], object]] = None
    end_dictation: Optional[Callable[[], object]] = None
    toggle_dictation: Optional[Callable[[], object]] = None
    begin_command: Optional[Callable[[], object]] = None
    end_command: Optional[Callable[[], object]] = None
    cancel_capture: Optional[Callable[[], object]] = None
    read_latest: Optional[Callable[[], object]] = None
    copy_latest: Optional[Callable[[], object]] = None
    inject_latest: Optional[Callable[[], object]] = None
    activate_persona: Optional[Callable[[str], object]] = None
    activate_writing_preset: Optional[Callable[[str], object]] = None
    activate_application_profile: Optional[Callable[[str], object]] = None
    request_workflow: Optional[Callable[[str], object]] = None
    emergency_stop: Optional[Callable[[], object]] = None


#: action id -> (handler attribute, takes_param)
_HANDLER_FOR = {
    ACTION_DICTATION_BEGIN: ("begin_dictation", False),
    ACTION_DICTATION_END: ("end_dictation", False),
    ACTION_DICTATION_TOGGLE: ("toggle_dictation", False),
    ACTION_COMMAND_BEGIN: ("begin_command", False),
    ACTION_COMMAND_END: ("end_command", False),
    ACTION_CAPTURE_CANCEL: ("cancel_capture", False),
    ACTION_LATEST_READ: ("read_latest", False),
    ACTION_LATEST_COPY: ("copy_latest", False),
    ACTION_LATEST_INJECT: ("inject_latest", False),
    ACTION_PERSONA_ACTIVATE: ("activate_persona", True),
    ACTION_WRITING_PRESET_ACTIVATE: ("activate_writing_preset", True),
    ACTION_APPLICATION_PROFILE_ACTIVATE: ("activate_application_profile", True),
    ACTION_WORKFLOW_RUN: ("request_workflow", True),
    ACTION_EMERGENCY_STOP: ("emergency_stop", False),
}

# Every action must have a handler slot, or a button would be silently
# undispatchable. Checked at import so adding an id without a slot is an
# immediate, loud failure rather than a press that does nothing at 2am.
assert set(_HANDLER_FOR) == set(ACTION_BY_ID), "every action id needs a handler slot"


@dataclass
class DispatchRecord:
    """One dispatch, as codes. No parameter value, ever — a persona name is a
    name, and the run history is not a place for one."""

    action_id: str
    status: str
    source: str = ""
    device_kind: str = ""


class InputActionDispatcher:
    """The single entry point for every non-voice, non-dashboard input."""

    #: Bounded, like the Wave 9 run history. The tail is what a support report
    #: needs; the head is noise that only grows.
    MAX_LOG = 200

    def __init__(
        self,
        handlers: Optional[InputActionHandlers] = None,
        *,
        enabled_kinds: Optional[dict] = None,
    ):
        self.handlers = handlers or InputActionHandlers()
        #: device kind -> bool. Absent means enabled: a device kind that nobody
        #: has switched off is on, which is what "I plugged it in and it worked"
        #: requires.
        self.enabled_kinds = dict(enabled_kinds or {})
        self._suspended = False
        self.log: list = []
        #: device_key -> {action_id} currently HELD by that device.
        #:
        #: This lives here rather than in each adapter because D-0026's rule is
        #: that device loss releases held state through the paths Wave 8 already
        #: built -- one release mechanism, not one per device kind. The
        #: controller engine has its own notion of which *buttons* are physically
        #: down (that is genuinely its business), but "which ACTION is currently
        #: held" is answered in exactly one place: here.
        self._held: dict = {}

    # --- gates ------------------------------------------------------------

    @property
    def suspended(self) -> bool:
        return self._suspended

    def suspend(self, reason: str = "") -> None:
        """Stop dispatching everything except the emergency stop.

        The setup wizard holds this while it records a binding, so the button
        the user is pressing to *choose* it does not also fire it. See the
        wizard's test-without-sending requirement: this is half of how that is
        enforced, and the other half is that the wizard never wires a send
        handler at all.
        """
        self._suspended = True
        logger.info("Input dispatch suspended (%s)", reason or "no reason given")

    def resume(self) -> None:
        self._suspended = False

    def set_kind_enabled(self, kind: str, enabled: bool) -> None:
        self.enabled_kinds[str(kind or "")] = bool(enabled)

    def available_actions(self) -> list:
        """Which ids this build can actually perform, so a setup UI can grey out
        the rest instead of offering a button that will report ``unavailable``
        the first time it is pressed."""
        return sorted(
            action_id for action_id, (attr, _p) in _HANDLER_FOR.items()
            if getattr(self.handlers, attr, None) is not None
        )

    # --- the gate ---------------------------------------------------------

    def dispatch(
        self,
        action_id,
        *,
        param: str = "",
        source: str = "",
        device_key: str = "",
        reason: str = "",
        hold: bool = False,
    ) -> dict:
        canonical = normalize_action_id(action_id)
        if not canonical:
            return self._record(str(action_id), "unknown_action", source, device_key)

        is_emergency = canonical == ACTION_EMERGENCY_STOP
        kind = str(device_key or "").split(":", 1)[0] if device_key else str(source or "")

        if not is_emergency:
            if self._suspended:
                return self._record(canonical, "suspended", source, device_key)
            if kind and self.enabled_kinds.get(kind, True) is False:
                return self._record(canonical, "disabled", source, device_key)

        attr, takes_param = _HANDLER_FOR[canonical]
        handler = getattr(self.handlers, attr, None)
        if handler is None:
            return self._record(canonical, "unavailable", source, device_key)

        args = ()
        if takes_param:
            value, refusal = normalize_param(canonical, param)
            if refusal or not value:
                return self._record(canonical, "needs_param", source, device_key)
            args = (value,)

        try:
            result = handler(*args)
        except Exception as exc:
            # A handler that throws must not take the input thread down. The
            # very next thing the user presses may be the emergency stop.
            logger.error("Input action %s failed: %s", canonical, exc)
            return self._record(canonical, "failed", source, device_key)

        self._note_hold(canonical, device_key, hold)
        record = self._record(canonical, "ok", source, device_key)
        if isinstance(result, dict):
            # Pass a handler's own payload through so a route can return it, but
            # never let it overwrite the status this dispatcher decided.
            merged = {k: v for k, v in result.items() if k not in record}
            record["result"] = merged or None
        return record

    # --- held state -------------------------------------------------------

    def _note_hold(self, action_id: str, device_key: str, hold: bool) -> None:
        key = str(device_key or "")
        action = ACTION_BY_ID.get(action_id)
        if action is None:
            return
        if hold and action.holdable and action.release_id:
            self._held.setdefault(key, set()).add(action_id)
            return
        # A release id clears whatever it releases, wherever the release came
        # from -- an ordinary button-up, an unplug, a shutdown. That is what
        # makes this registry safe to consult: it can only be stale if a release
        # never happened at all.
        for begin_id, meta in ACTION_BY_ID.items():
            if meta.release_id == action_id:
                held = self._held.get(key)
                if held:
                    held.discard(begin_id)
                    if not held:
                        self._held.pop(key, None)

    def held_actions(self, device_key: str = "") -> list:
        if device_key:
            return sorted(self._held.get(str(device_key), set()))
        out: set = set()
        for actions in self._held.values():
            out.update(actions)
        return sorted(out)

    def release_device(self, device_key: str, reason: str = "device_lost") -> list:
        """Release everything this device is holding, and nothing else.

        This is the whole answer to "a device vanished mid-sentence". It
        dispatches the release halves through ``dispatch`` -- the same call an
        ordinary button-up makes -- which is how the Wave 8 privacy lease and
        the audio broker get released without a second unplug-only code path
        that nobody exercises until it is broken.

        It releases only what THIS device held, so unplugging a Stream Deck
        cannot end a dictation the user started with the keyboard.
        """
        key = str(device_key or "")
        held = sorted(self._held.get(key, set()))
        released = []
        for action_id in held:
            action = ACTION_BY_ID.get(action_id)
            if action is None or not action.release_id:
                continue
            outcome = self.dispatch(action.release_id, source="release",
                                    device_key=key, reason=reason)
            if outcome.get("ok"):
                released.append(action.release_id)
        # Whatever the handlers said, this device is not holding anything now:
        # it is gone. Leaving a stale entry would make the NEXT unplug try to
        # release something twice.
        self._held.pop(key, None)
        return released

    def _record(self, action_id: str, status: str, source: str, device_key: str) -> dict:
        kind = str(device_key or "").split(":", 1)[0] if device_key else str(source or "")
        self.log.append(DispatchRecord(action_id, status, source or "", kind))
        if len(self.log) > self.MAX_LOG:
            del self.log[: -self.MAX_LOG]
        if status not in ("ok",):
            logger.info("Input action %s -> %s (%s)", action_id, status, kind or "unknown device")
        return {
            "ok": status == "ok",
            "action_id": action_id,
            "status": status,
            "source": source or "",
        }

    def recent(self, limit: int = 20) -> list:
        rows = self.log[-max(1, int(limit or 1)):]
        return [
            {"action_id": r.action_id, "status": r.status,
             "source": r.source, "device_kind": r.device_kind}
            for r in rows
        ]


# --- The wizard's dispatcher -------------------------------------------------


def rehearsal_dispatcher() -> InputActionDispatcher:
    """A dispatcher with NO handlers, for the game setup wizard's test step.

    The wizard's requirement is that its test can never fire a real send. The
    way this codebase makes that true is not a flag that a later edit could
    invert -- it is a dispatcher constructed with an empty handler table, so
    there is no callable to reach. Every action reports ``unavailable`` and the
    wizard renders that as "BetterFingers saw your button". A test asserts that
    every id, including the emergency stop, comes back non-ok from this object.

    ``suspend`` is not used for this, deliberately: suspension has an exception
    for the emergency stop, and during a rehearsal even the emergency stop must
    not actually stop a recording the user did not start.
    """
    return InputActionDispatcher(InputActionHandlers())
