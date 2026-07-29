"""The controller event engine — timing, bounce, and held state (Wave 10).

Pure logic. No pygame, no threads, no sockets, no clock of its own: events go in
through ``token_down`` / ``token_up`` / ``device_lost``, action ids come out
through one injected ``dispatch`` callable, and time is whatever the caller
passes. That is what makes chord windows, sequence windows and contact bounce
testable to the millisecond without a controller plugged in, which is the whole
requirement in deliverable 7.

The adapter that owns pygame is ``PygameEventSource`` at the bottom — thirty
lines that translate joystick events into the tokens this engine already
understands (``button:4``, ``hat:0:up``, ``axis:2:pos``), the same token grammar
``hotkey_manager`` has used since Wave 2. Tests inject a fake module for it.

THE FOUR RELIABILITY PROPERTIES, and where each one lives:

1. **Bounce.** A cheap pad reports one physical press as two JOYBUTTONDOWNs
   milliseconds apart. ``_debounced`` drops the second. Per (device, token), so
   a genuine chord is never mistaken for a bounce.

2. **Chord and sequence timing.** A chord fires once when all its tokens are
   held and re-arms only after they are all released. A sequence fires when its
   tokens arrive in order inside the window and resets when they do not.
   Both come from Wave 2's ``InputBinding`` document, unchanged.

3. **Pre-emption.** If ``button:4`` is bound alone and ``button:4 + button:5``
   is bound to something else, pressing both must not do both. A binding that
   fires while a longer binding could still complete is DEFERRED by that
   binding's window and cancelled if the longer one lands. Deferral is applied
   only when a longer binding is actually live, so an ordinary single button
   keeps its zero-latency press — and ``emergency.stop`` is never deferred at
   all, because a panic button that waits 120ms for a chord that might not
   arrive is a panic button with a bug.

4. **Device loss releases held state.** Unplugging a controller mid-sentence
   produces no button-up event: the recording would run until the watchdog
   fired. ``device_lost`` dispatches the release half of everything that device
   was holding, THROUGH THE SAME DISPATCHER — which is how the Wave 8 privacy
   lease and the audio broker get released, per D-0026. There is no second
   release mechanism here and there must not be: a bespoke unmute path that runs
   only on unplug is a path nobody exercises until it is broken.

RECONNECT. Bindings are keyed by a stable device key derived from the device
name, never by the pygame instance id, so a controller that comes back is the
same controller. ``device_added`` clears any stale held state for that key
rather than trusting what was there before the cable moved.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from backend.domain.input_actions import (
    ACTION_BY_ID,
    ACTION_EMERGENCY_STOP,
)
from backend.stores.controller_bindings import (
    DEFAULT_DEBOUNCE_MS,
    device_key_for,
    normalize_device_key,
)

logger = logging.getLogger(__name__)

#: How long a deferred short binding waits for a longer one, when the longer
#: binding declares no window of its own (a chord has no natural window — it is
#: satisfied by simultaneity, and "simultaneous" needs a number).
DEFAULT_CHORD_WINDOW_MS = 120


class _DeviceState:
    """Everything the engine remembers about one physical device."""

    __slots__ = (
        "key", "name", "pressed", "last_down_at",
        "chord_latched", "sequence_progress", "sequence_at",
        "held", "pending",
    )

    def __init__(self, key: str, name: str = ""):
        self.key = key
        self.name = name
        self.pressed: set = set()
        self.last_down_at: dict = {}
        #: action_id -> bool, so a chord fires once per press, not once per token
        self.chord_latched: dict = {}
        #: action_id -> how many tokens of the sequence have landed
        self.sequence_progress: dict = {}
        self.sequence_at: dict = {}
        #: action_id -> the binding currently held down (mode == "hold")
        self.held: dict = {}
        #: action_id -> (fire_at, binding, tokens_at_fire)
        self.pending: dict = {}

    def reset(self) -> None:
        self.pressed.clear()
        self.last_down_at.clear()
        self.chord_latched.clear()
        self.sequence_progress.clear()
        self.sequence_at.clear()
        self.held.clear()
        self.pending.clear()


def _events(binding: dict) -> list:
    return list((binding.get("input") or {}).get("events") or [])


def _window_ms(binding: dict) -> int:
    value = (binding.get("input") or {}).get("sequence_window_ms")
    try:
        return int(value)
    except (TypeError, ValueError):
        return DEFAULT_CHORD_WINDOW_MS


def _style(binding: dict) -> str:
    return str((binding.get("input") or {}).get("style") or "single")


def _scope(binding: dict) -> str:
    return str((binding.get("input") or {}).get("device_scope") or "any_device")


class ControllerEngine:
    """Feed it device events; it dispatches action ids.

    ``resolve(device_key)`` returns the bindings in force for that device right
    now — it is a callable rather than a snapshot so that switching application
    profile mid-session takes effect on the next press without anybody
    remembering to rebuild the engine.
    """

    def __init__(
        self,
        dispatch: Callable[..., object],
        resolve: Callable[[str], dict],
        *,
        debounce_ms: int = DEFAULT_DEBOUNCE_MS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._dispatch = dispatch
        self._resolve = resolve
        self.debounce_ms = max(0, int(debounce_ms))
        self._clock = clock
        self._devices: dict = {}
        self._suspended = False
        #: Non-None while the setup wizard is recording a binding.
        self._capture = None
        #: Every action id this engine has dispatched, newest last. Bounded,
        #: codes only — the same rule the Wave 9 run history follows.
        self.log: list = []

    # --- lifecycle --------------------------------------------------------

    @property
    def suspended(self) -> bool:
        return self._suspended

    def suspend(self, reason: str = "") -> None:
        """Stop dispatching everything except ``emergency.stop``.

        For "the input layer should be quiet for a moment" — the panic button
        stays live because there is no state of a RUNNING application in which
        it should not.

        This is NOT what the setup wizard's record step uses; see
        ``begin_capture`` for why the exception that is right here is wrong
        there.
        """
        self._suspended = True
        logger.info("Controller engine suspended (%s)", reason or "no reason given")

    def resume(self) -> None:
        self._suspended = False

    # --- capture (the setup wizard's "press a button now") ----------------
    #
    # Capture is NOT suspension. Suspension still dispatches ``emergency.stop``,
    # which is correct while the app is running and wrong while the user is
    # choosing which button their emergency stop should be -- pressing the
    # candidate would fire the real one. So capture swallows EVERY token,
    # including that id's, and dispatches nothing at all.

    def begin_capture(self) -> dict:
        self._capture = {"tokens": [], "held": set(), "peak": [], "device_key": ""}
        logger.info("Controller capture started")
        return {"ok": True, "capturing": True}

    def cancel_capture(self) -> dict:
        self._capture = None
        return {"ok": True, "capturing": False}

    @property
    def capturing(self) -> bool:
        return self._capture is not None

    def capture_result(self) -> Optional[dict]:
        """The binding the user just pressed, or ``None`` if they have not
        finished pressing it.

        "Finished" means every token is back up. Reading the answer while a
        button is still down would turn the first token of a two-button chord
        into a single binding, and the user would have no way to tell that the
        wizard stopped listening halfway through their press.
        """
        capture = self._capture
        if not capture or capture["held"] or not capture["peak"]:
            return None
        peak = capture["peak"]
        return {
            "device_key": capture["device_key"],
            # Simultaneity is what distinguishes a chord from a sequence, and
            # the engine already knows which it saw: `peak` is the largest set
            # that was down at the same moment.
            "style": "chord" if len(peak) > 1 else "single",
            "events": list(peak),
        }

    def _capture_down(self, state: _DeviceState, token: str) -> None:
        capture = self._capture
        capture["device_key"] = capture["device_key"] or state.key
        capture["held"].add(token)
        if token not in capture["tokens"]:
            capture["tokens"].append(token)
        held_in_order = [t for t in capture["tokens"] if t in capture["held"]]
        if len(held_in_order) > len(capture["peak"]):
            capture["peak"] = held_in_order

    def known_devices(self) -> list:
        return sorted(self._devices)

    def held_actions(self, device_key: str = "") -> list:
        key = normalize_device_key(device_key)
        if key:
            state = self._devices.get(key)
            return sorted(state.held) if state else []
        out: set = set()
        for state in self._devices.values():
            out.update(state.held)
        return sorted(out)

    def device_added(self, device_key: str, name: str = "") -> str:
        """A device appeared — first plug or a reconnect; the engine does not
        care which, and that is deliberate. Any state left over from before the
        cable moved is stale by definition."""
        key = normalize_device_key(device_key)
        if not key:
            return ""
        state = self._devices.get(key)
        if state is None:
            state = _DeviceState(key, name)
            self._devices[key] = state
        else:
            state.reset()
            if name:
                state.name = name
        logger.info("Controller connected: %s", key)
        return key

    def device_lost(self, device_key: str, now: Optional[float] = None) -> list:
        """A device disappeared. Release everything it was holding.

        Returns the action ids it dispatched, so a caller (and a test) can see
        that an unplug during dictation ended the dictation rather than leaving
        it running until the watchdog.
        """
        key = normalize_device_key(device_key)
        state = self._devices.get(key)
        if state is None:
            return []
        released = self._release_all(state, now=now, reason="device_lost")
        state.reset()
        self._devices.pop(key, None)
        logger.info("Controller disconnected: %s (released %d held action(s))", key, len(released))
        return released

    def release_all_devices(self, reason: str = "shutdown") -> list:
        released = []
        for state in list(self._devices.values()):
            released.extend(self._release_all(state, reason=reason))
            state.reset()
        return released

    def _release_all(self, state: _DeviceState, now: Optional[float] = None, reason: str = "") -> list:
        released = []
        for action_id, binding in list(state.held.items()):
            release_id = (ACTION_BY_ID.get(action_id) or ACTION_BY_ID[ACTION_EMERGENCY_STOP]).release_id
            if not release_id:
                continue
            self._emit(release_id, binding, state, reason=reason)
            released.append(release_id)
        state.held.clear()
        # A device that vanished is holding nothing, and a deferred press whose
        # device is gone must not fire later against a controller that is no
        # longer there.
        state.pending.clear()
        return released

    # --- event intake -----------------------------------------------------

    def token_down(self, device_key: str, token: str, now: Optional[float] = None) -> list:
        """One button/hat/axis crossing went active. Returns dispatched ids."""
        now = self._now(now)
        key = normalize_device_key(device_key)
        if not key:
            return []
        state = self._devices.get(key)
        if state is None:
            self.device_added(key)
            state = self._devices[key]

        token = str(token or "").strip().lower()
        if not token:
            return []

        if self._debounced(state, token, now):
            return []
        state.last_down_at[token] = now
        state.pressed.add(token)

        if self._capture is not None:
            # Swallowed entirely -- see begin_capture. Nothing is dispatched
            # while the user is choosing a button, not even the panic button.
            self._capture_down(state, token)
            return []

        bindings = self._bindings_for(state)
        fired = []
        for binding in bindings.values():
            if self._binding_fires(state, binding, token, now):
                fired.append(binding)

        dispatched = self._commit(state, bindings, fired, now)
        dispatched.extend(self.tick(now))
        return dispatched

    def token_up(self, device_key: str, token: str, now: Optional[float] = None) -> list:
        now = self._now(now)
        key = normalize_device_key(device_key)
        state = self._devices.get(key)
        if state is None:
            return []

        token = str(token or "").strip().lower()
        state.pressed.discard(token)

        if self._capture is not None:
            self._capture["held"].discard(token)
            return []

        bindings = self._bindings_for(state)
        dispatched = []

        # Re-arm any chord that is no longer fully held. Without this a chord
        # fires once and never again until the app restarts.
        for action_id, binding in bindings.items():
            if _style(binding) == "chord" and state.chord_latched.get(action_id):
                if not set(_events(binding)).issubset(state.pressed):
                    state.chord_latched[action_id] = False

        # Release the held half of anything whose binding is no longer satisfied.
        for action_id, binding in list(state.held.items()):
            if self._binding_satisfied(state, binding):
                continue
            release_id = (ACTION_BY_ID.get(action_id) or ACTION_BY_ID[ACTION_EMERGENCY_STOP]).release_id
            state.held.pop(action_id, None)
            if release_id:
                self._emit(release_id, binding, state, reason="release")
                dispatched.append(release_id)

        dispatched.extend(self.tick(now))
        return dispatched

    def tick(self, now: Optional[float] = None) -> list:
        """Fire anything whose deferral has expired. Cheap; call it from the
        poll loop alongside the event drain."""
        now = self._now(now)
        if self._capture is not None:
            return []
        dispatched = []
        for state in self._devices.values():
            for action_id, (fire_at, binding, _tokens) in list(state.pending.items()):
                if now + 1e-9 < fire_at:
                    continue
                state.pending.pop(action_id, None)
                dispatched.extend(self._fire(state, binding, now))
        return dispatched

    # --- matching ---------------------------------------------------------

    def _now(self, now: Optional[float]) -> float:
        return self._clock() if now is None else float(now)

    def _debounced(self, state: _DeviceState, token: str, now: float) -> bool:
        if self.debounce_ms <= 0:
            return False
        previous = state.last_down_at.get(token)
        if previous is None:
            return False
        if (now - previous) * 1000.0 >= self.debounce_ms:
            return False
        logger.debug("Dropped bounced %s on %s", token, state.key)
        return True

    def _bindings_for(self, state: _DeviceState) -> dict:
        try:
            resolved = self._resolve(state.key) or {}
        except Exception as exc:  # pragma: no cover - a resolver that throws
            logger.error("Binding resolution failed for %s: %s", state.key, exc)
            return {}
        # device_scope is Wave 2's field and it means what it says: a binding
        # scoped to one device does not fire on another. emergency.stop is the
        # exception, and it is the only one -- see the module docstring.
        out = {}
        for action_id, binding in resolved.items():
            scope = _scope(binding)
            if scope in ("", "any_device") or scope == state.key or action_id == ACTION_EMERGENCY_STOP:
                out[action_id] = binding
        return out

    def _binding_fires(self, state: _DeviceState, binding: dict, token: str, now: float) -> bool:
        events = _events(binding)
        if not events:
            return False
        style = _style(binding)
        action_id = binding["action_id"]

        if style == "single":
            return token == events[0]

        if style == "chord":
            if token not in events:
                return False
            if not set(events).issubset(state.pressed):
                return False
            if state.chord_latched.get(action_id):
                return False
            state.chord_latched[action_id] = True
            return True

        # sequence
        window = max(0.05, _window_ms(binding) / 1000.0)
        progress = state.sequence_progress.get(action_id, 0)
        last_at = state.sequence_at.get(action_id, 0.0)
        if progress > 0 and (now - last_at) > window:
            progress = 0

        expected = events[progress] if progress < len(events) else events[0]
        if token == expected:
            progress += 1
            if progress >= len(events):
                state.sequence_progress[action_id] = 0
                state.sequence_at[action_id] = 0.0
                return True
            state.sequence_progress[action_id] = progress
            state.sequence_at[action_id] = now
            return False

        # A wrong token restarts the sequence rather than merely clearing it, so
        # "a a b" still matches "a > b" on the second a.
        if token == events[0]:
            state.sequence_progress[action_id] = 1
            state.sequence_at[action_id] = now
        else:
            state.sequence_progress[action_id] = 0
            state.sequence_at[action_id] = 0.0
        return False

    def _binding_satisfied(self, state: _DeviceState, binding: dict) -> bool:
        """Is this binding still physically held?"""
        events = _events(binding)
        if not events:
            return False
        style = _style(binding)
        if style == "chord":
            return set(events).issubset(state.pressed)
        # A single binding is held while its token is; a sequence is held while
        # its LAST token is, which is the only one still down when it fired.
        return events[-1] in state.pressed

    # --- pre-emption and dispatch ----------------------------------------

    def _live_longer_windows(self, state: _DeviceState, bindings: dict, fired: dict) -> int:
        """Milliseconds to wait for a longer binding that could still land.

        "Could still land" is checked against the tokens actually held, not
        against the binding table in the abstract: a chord whose other token is
        bound to a button the user is not touching is not a reason to delay
        anything.
        """
        fired_events = set(_events(fired))
        best = 0
        for action_id, binding in bindings.items():
            if action_id == fired["action_id"]:
                continue
            events = _events(binding)
            if len(events) <= len(fired_events):
                continue
            style = _style(binding)
            if style == "chord":
                if not fired_events.issubset(set(events)):
                    continue
                if not state.pressed.issubset(set(events)):
                    continue
                # A chord uses DEFAULT_CHORD_WINDOW_MS, NOT the binding's
                # sequence_window_ms. InputBinding always carries a
                # sequence_window_ms (default 400) because a sequence needs one,
                # but a chord is satisfied by simultaneity -- and 400ms of input
                # lag on an ordinary button press because some other binding
                # happens to include that button is unusable in a game. 120ms is
                # longer than any human "simultaneous" and short enough not to
                # feel like lag.
                candidate = DEFAULT_CHORD_WINDOW_MS
            elif style == "sequence":
                # Live only when the sequence has actually started and the next
                # token is still to come. Here the binding's own window IS the
                # right number: the user chose how long they get between presses.
                progress = state.sequence_progress.get(action_id, 0)
                if progress <= 0:
                    continue
                candidate = _window_ms(binding) or DEFAULT_CHORD_WINDOW_MS
            else:
                continue
            best = max(best, candidate)
        return best

    def _commit(self, state: _DeviceState, bindings: dict, fired: list, now: float) -> list:
        dispatched = []
        if not fired:
            return dispatched

        # A longer binding that just fired cancels any shorter one still waiting
        # — that is the whole point of the deferral.
        longest = max(len(_events(binding)) for binding in fired)
        for binding in fired:
            if len(_events(binding)) < longest:
                continue
            for action_id, (_at, pending_binding, _tokens) in list(state.pending.items()):
                if set(_events(pending_binding)).issubset(set(_events(binding))):
                    state.pending.pop(action_id, None)

        for binding in fired:
            action_id = binding["action_id"]
            if action_id != ACTION_EMERGENCY_STOP:
                wait_ms = self._live_longer_windows(state, bindings, binding)
                if wait_ms > 0:
                    state.pending[action_id] = (now + wait_ms / 1000.0, binding, set(state.pressed))
                    continue
            dispatched.extend(self._fire(state, binding, now))
        return dispatched

    def _fire(self, state: _DeviceState, binding: dict, now: float) -> list:
        action_id = binding["action_id"]
        action = ACTION_BY_ID.get(action_id)
        if action is None:
            return []
        if self._suspended and not action.always_available:
            return []

        held = binding.get("mode") == "hold" and action.holdable
        self._emit(action_id, binding, state, reason="press", hold=held)
        if held:
            state.held[action_id] = binding
        return [action_id]

    def _emit(self, action_id: str, binding: dict, state: _DeviceState, reason: str,
              hold: bool = False) -> None:
        self.log.append(action_id)
        if len(self.log) > 200:
            del self.log[:-200]
        try:
            self._dispatch(
                action_id,
                param=binding.get("param", ""),
                source="controller",
                device_key=state.key,
                reason=reason,
                # The dispatcher owns the answer to "which action is held", so
                # that a device loss releases through one registry rather than
                # through whichever adapter happened to notice (D-0026).
                hold=hold,
            )
        except Exception as exc:
            # A dispatcher that throws must not take the input thread with it:
            # the next button press has to keep working, and one of the buttons
            # the user might press next is the emergency stop.
            logger.error("Input action %s failed: %s", action_id, exc)


# --- The pygame adapter ------------------------------------------------------


class PygameEventSource:
    """Joystick events -> engine tokens. The only pygame-aware code in Wave 10.

    ``pygame`` is injected rather than imported at module scope so the whole
    engine is importable, and testable, on a machine with no joystick support
    compiled in — which is every CI runner this project has.
    """

    def __init__(self, engine: ControllerEngine, pygame_module=None):
        self.engine = engine
        self.pygame = pygame_module
        self._joysticks: dict = {}
        self._keys: dict = {}
        self._hat_active: dict = {}
        self._axis_active: dict = {}
        self.axis_threshold = 0.6

    @property
    def available(self) -> bool:
        return self.pygame is not None

    def refresh_devices(self) -> list:
        """Enumerate what is plugged in now. Safe to call repeatedly."""
        if not self.available:
            return []
        added = []
        for index in range(self.pygame.joystick.get_count()):
            try:
                joystick = self.pygame.joystick.Joystick(index)
                joystick.init()
                instance_id = joystick.get_instance_id()
                if instance_id in self._joysticks:
                    continue
                self._joysticks[instance_id] = joystick
                key = device_key_for("controller", joystick.get_name())
                self._keys[instance_id] = key
                self.engine.device_added(key, name=joystick.get_name())
                added.append(key)
            except Exception as exc:  # pragma: no cover - driver-specific
                logger.debug("Could not open joystick %s: %s", index, exc)
        return added

    def _instance(self, event) -> int:
        if hasattr(event, "instance_id"):
            return event.instance_id
        return getattr(event, "joy", -1)

    def handle(self, event) -> list:
        """One pygame event -> whatever the engine dispatched."""
        if not self.available:
            return []
        pg = self.pygame
        etype = event.type

        if etype == pg.JOYDEVICEADDED:
            self.refresh_devices()
            return []

        if etype == pg.JOYDEVICEREMOVED:
            instance_id = getattr(event, "instance_id", None)
            key = self._keys.pop(instance_id, "")
            self._joysticks.pop(instance_id, None)
            self._hat_active = {k: v for k, v in self._hat_active.items() if k[0] != instance_id}
            self._axis_active = {k: v for k, v in self._axis_active.items() if k[0] != instance_id}
            # Everything this device was holding is released here, through the
            # engine's normal dispatcher. See the module docstring, point 4.
            return self.engine.device_lost(key) if key else []

        key = self._keys.get(self._instance(event), "")
        if not key:
            return []

        if etype == pg.JOYBUTTONDOWN:
            return self.engine.token_down(key, f"button:{event.button}")
        if etype == pg.JOYBUTTONUP:
            return self.engine.token_up(key, f"button:{event.button}")

        if etype == pg.JOYHATMOTION:
            instance_id = self._instance(event)
            hat = int(getattr(event, "hat", 0))
            x, y = event.value
            current = set()
            if x < 0:
                current.add(f"hat:{hat}:left")
            if x > 0:
                current.add(f"hat:{hat}:right")
            if y < 0:
                current.add(f"hat:{hat}:down")
            if y > 0:
                current.add(f"hat:{hat}:up")
            previous = self._hat_active.get((instance_id, hat), set())
            out = []
            for token in sorted(current - previous):
                out.extend(self.engine.token_down(key, token))
            for token in sorted(previous - current):
                out.extend(self.engine.token_up(key, token))
            self._hat_active[(instance_id, hat)] = current
            return out

        if etype == pg.JOYAXISMOTION:
            instance_id = self._instance(event)
            axis = int(event.axis)
            value = float(event.value)
            threshold = float(self.axis_threshold)
            # Hysteresis: an axis resting near the threshold would otherwise
            # chatter down/up/down forever, which no debounce window can fix
            # because the events are genuinely that far apart.
            release = threshold * 0.75
            out = []
            for sign, token in ((1, f"axis:{axis}:pos"), (-1, f"axis:{axis}:neg")):
                state_key = (instance_id, axis, sign)
                active = self._axis_active.get(state_key, False)
                crossed = (value >= threshold) if sign > 0 else (value <= -threshold)
                back = (value < release) if sign > 0 else (value > -release)
                if crossed and not active:
                    self._axis_active[state_key] = True
                    out.extend(self.engine.token_down(key, token))
                elif back and active:
                    self._axis_active[state_key] = False
                    out.extend(self.engine.token_up(key, token))
            return out

        return []
