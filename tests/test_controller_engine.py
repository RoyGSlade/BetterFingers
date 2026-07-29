"""Controller timing, bounce, pre-emption and device loss (Wave 10, deliverable 5).

pygame is never imported. The engine takes its clock and its events from the
test, which is what makes millisecond assertions possible with no hardware — the
requirement in deliverable 7.
"""

import types

import pytest

from backend.services.controller_engine import (
    DEFAULT_CHORD_WINDOW_MS,
    ControllerEngine,
    PygameEventSource,
)
from backend.stores.controller_bindings import sanitize_binding


def binding(action_id, events, style="single", mode="press", window_ms=None, scope=None, param=""):
    spec = {"mode": mode, "param": param, "input": {"style": style, "events": events}}
    if window_ms is not None:
        spec["input"]["sequence_window_ms"] = window_ms
    if scope is not None:
        spec["input"]["device_scope"] = scope
    row, reason = sanitize_binding(action_id, spec)
    assert row is not None, reason
    return row


class Recorder:
    """Stands in for the InputActionDispatcher."""

    def __init__(self):
        self.calls = []

    def __call__(self, action_id, **kwargs):
        self.calls.append((action_id, kwargs))
        return {"ok": True}

    @property
    def ids(self):
        return [call[0] for call in self.calls]


def engine_for(bindings, dispatch=None, debounce_ms=40):
    dispatch = dispatch or Recorder()
    engine = ControllerEngine(
        dispatch,
        lambda _key: {row["action_id"]: row for row in bindings},
        debounce_ms=debounce_ms,
        clock=lambda: 0.0,
    )
    engine.device_added("controller:pad", name="Pad")
    return engine, dispatch


# --- bounce ------------------------------------------------------------------


def test_contact_bounce_does_not_double_trigger():
    engine, rec = engine_for([binding("dictation.toggle", ["button:4"])], debounce_ms=40)
    assert engine.token_down("controller:pad", "button:4", now=0.000) == ["dictation.toggle"]
    # The bounce: same token, 5ms later, with no intervening up event.
    assert engine.token_down("controller:pad", "button:4", now=0.005) == []
    assert rec.ids == ["dictation.toggle"]


def test_a_deliberate_second_press_after_the_window_still_fires():
    engine, rec = engine_for([binding("dictation.toggle", ["button:4"])], debounce_ms=40)
    engine.token_down("controller:pad", "button:4", now=0.000)
    engine.token_up("controller:pad", "button:4", now=0.020)
    engine.token_down("controller:pad", "button:4", now=0.041)
    assert rec.ids == ["dictation.toggle", "dictation.toggle"]


def test_debounce_is_per_token_so_a_chord_is_not_mistaken_for_a_bounce():
    engine, rec = engine_for(
        [binding("dictation.toggle", ["button:4", "button:5"], style="chord")], debounce_ms=40,
    )
    engine.token_down("controller:pad", "button:4", now=0.000)
    engine.token_down("controller:pad", "button:5", now=0.005)
    assert rec.ids == ["dictation.toggle"]


# --- chords ------------------------------------------------------------------


def test_a_chord_fires_once_per_press_and_rearms_on_release():
    engine, rec = engine_for(
        [binding("dictation.toggle", ["button:4", "button:5"], style="chord")],
    )
    engine.token_down("controller:pad", "button:4", now=0.0)
    engine.token_down("controller:pad", "button:5", now=0.01)
    assert rec.ids == ["dictation.toggle"]

    # Still held: no repeat.
    engine.token_down("controller:pad", "button:4", now=0.5)
    assert rec.ids == ["dictation.toggle"]

    engine.token_up("controller:pad", "button:5", now=0.6)
    engine.token_up("controller:pad", "button:4", now=0.61)
    engine.token_down("controller:pad", "button:4", now=0.7)
    engine.token_down("controller:pad", "button:5", now=0.71)
    assert rec.ids == ["dictation.toggle", "dictation.toggle"]


def test_a_partial_chord_never_fires():
    engine, rec = engine_for(
        [binding("dictation.toggle", ["button:4", "button:5"], style="chord")],
    )
    engine.token_down("controller:pad", "button:4", now=0.0)
    engine.tick(now=1.0)
    assert rec.ids == []


# --- sequences ---------------------------------------------------------------


def test_a_sequence_fires_inside_its_window():
    engine, rec = engine_for(
        [binding("emergency.stop", ["button:1", "button:2"], style="sequence", window_ms=400)],
    )
    engine.token_down("controller:pad", "button:1", now=0.0)
    engine.token_down("controller:pad", "button:2", now=0.3)
    assert rec.ids == ["emergency.stop"]


def test_a_sequence_that_misses_its_window_does_not_fire():
    engine, rec = engine_for(
        [binding("emergency.stop", ["button:1", "button:2"], style="sequence", window_ms=400)],
    )
    engine.token_down("controller:pad", "button:1", now=0.0)
    engine.token_down("controller:pad", "button:2", now=0.5)
    assert rec.ids == []


def test_a_repeated_first_token_restarts_the_sequence():
    """"a a b" still matches "a > b" — restarting rather than merely clearing is
    what makes a fumbled first press recoverable."""
    engine, rec = engine_for(
        [binding("emergency.stop", ["button:1", "button:2"], style="sequence", window_ms=400)],
    )
    engine.token_down("controller:pad", "button:1", now=0.0)
    engine.token_down("controller:pad", "button:1", now=0.1)
    engine.token_down("controller:pad", "button:2", now=0.2)
    assert rec.ids == ["emergency.stop"]


# --- pre-emption -------------------------------------------------------------


def test_a_longer_chord_pre_empts_the_shorter_binding_inside_it():
    engine, rec = engine_for([
        binding("dictation.toggle", ["button:4"]),
        binding("command.begin", ["button:4", "button:5"], style="chord"),
    ])
    engine.token_down("controller:pad", "button:4", now=0.0)
    # Deferred, not fired: the chord could still land.
    assert rec.ids == []
    engine.token_down("controller:pad", "button:5", now=0.05)
    assert rec.ids == ["command.begin"]


def test_a_deferred_single_fires_when_the_longer_binding_does_not_arrive():
    engine, rec = engine_for([
        binding("dictation.toggle", ["button:4"]),
        binding("command.begin", ["button:4", "button:5"], style="chord"),
    ])
    engine.token_down("controller:pad", "button:4", now=0.0)
    assert rec.ids == []
    engine.tick(now=DEFAULT_CHORD_WINDOW_MS / 1000.0 + 0.001)
    assert rec.ids == ["dictation.toggle"]


def test_an_ordinary_single_button_keeps_zero_latency():
    """Deferral is applied only when a longer binding is actually live. A user
    with no chords must not pay 120ms on every press."""
    engine, rec = engine_for([binding("dictation.toggle", ["button:4"])])
    engine.token_down("controller:pad", "button:4", now=0.0)
    assert rec.ids == ["dictation.toggle"]


def test_emergency_stop_is_never_deferred():
    """A panic button that waits for a chord that might not arrive is a panic
    button with a bug."""
    engine, rec = engine_for([
        binding("emergency.stop", ["button:9"]),
        binding("command.begin", ["button:9", "button:5"], style="chord"),
    ])
    engine.token_down("controller:pad", "button:9", now=0.0)
    assert rec.ids == ["emergency.stop"]


# --- holds and device loss ---------------------------------------------------


def test_releasing_a_held_button_dispatches_the_release_half():
    engine, rec = engine_for([binding("dictation.begin", ["button:4"], mode="hold")])
    engine.token_down("controller:pad", "button:4", now=0.0)
    assert rec.ids == ["dictation.begin"]
    engine.token_up("controller:pad", "button:4", now=0.5)
    assert rec.ids == ["dictation.begin", "dictation.end"]


def test_a_hold_is_announced_to_the_dispatcher_as_a_hold():
    """The dispatcher owns "which action is held" (D-0026), so the engine has to
    tell it. Without this flag an unplug releases nothing."""
    engine, rec = engine_for([binding("dictation.begin", ["button:4"], mode="hold")])
    engine.token_down("controller:pad", "button:4", now=0.0)
    assert rec.calls[0][1]["hold"] is True


def test_device_loss_releases_held_state():
    """Unplugging mid-sentence produces no button-up. Without this the recording
    runs until the watchdog."""
    engine, rec = engine_for([binding("dictation.begin", ["button:4"], mode="hold")])
    engine.token_down("controller:pad", "button:4", now=0.0)
    released = engine.device_lost("controller:pad")
    assert released == ["dictation.end"]
    assert rec.ids == ["dictation.begin", "dictation.end"]
    assert engine.held_actions() == []


def test_device_loss_releases_through_the_same_dispatcher():
    """D-0026: no second release mechanism. The release must be an ordinary
    dispatch, because that is what the Wave 8 lease and the audio broker are
    hooked to."""
    engine, rec = engine_for([binding("dictation.begin", ["button:4"], mode="hold")])
    engine.token_down("controller:pad", "button:4", now=0.0)
    engine.device_lost("controller:pad")
    release_call = rec.calls[-1]
    assert release_call[0] == "dictation.end"
    assert release_call[1]["source"] == "controller"
    assert release_call[1]["device_key"] == "controller:pad"
    assert release_call[1]["reason"] == "device_lost"


def test_device_loss_drops_a_deferred_press():
    """A press deferred behind a chord must not fire later against a controller
    that is no longer plugged in."""
    engine, rec = engine_for([
        binding("dictation.toggle", ["button:4"]),
        binding("command.begin", ["button:4", "button:5"], style="chord"),
    ])
    engine.token_down("controller:pad", "button:4", now=0.0)
    engine.device_lost("controller:pad")
    engine.tick(now=5.0)
    assert rec.ids == []


def test_reconnect_clears_stale_held_state():
    engine, rec = engine_for([binding("dictation.begin", ["button:4"], mode="hold")])
    engine.token_down("controller:pad", "button:4", now=0.0)
    engine.device_added("controller:pad", name="Pad")
    assert engine.held_actions("controller:pad") == []


def test_a_reconnected_controller_keeps_the_same_bindings():
    """The reconnect property end to end: same name, same key, same bindings."""
    engine, rec = engine_for([binding("dictation.toggle", ["button:4"])])
    engine.device_lost("controller:pad")
    engine.device_added("controller:pad", name="Pad")
    assert engine.token_down("controller:pad", "button:4", now=1.0) == ["dictation.toggle"]


# --- scoping and suspension --------------------------------------------------


def test_a_device_scoped_binding_does_not_fire_on_another_device():
    engine, rec = engine_for(
        [binding("dictation.toggle", ["button:4"], scope="controller:stick")],
    )
    engine.token_down("controller:pad", "button:4", now=0.0)
    assert rec.ids == []


def test_emergency_stop_ignores_device_scope():
    engine, rec = engine_for(
        [binding("emergency.stop", ["button:9"], scope="controller:stick")],
    )
    engine.token_down("controller:pad", "button:9", now=0.0)
    assert rec.ids == ["emergency.stop"]


def test_suspension_stops_everything_except_the_emergency_stop():
    engine, rec = engine_for([
        binding("dictation.toggle", ["button:4"]),
        binding("emergency.stop", ["button:9"]),
    ])
    engine.suspend("recording a binding in the wizard")
    engine.token_down("controller:pad", "button:4", now=0.0)
    assert rec.ids == []
    engine.token_down("controller:pad", "button:9", now=0.1)
    assert rec.ids == ["emergency.stop"]


def test_a_dispatcher_that_throws_does_not_take_the_input_thread_down():
    def boom(action_id, **kwargs):
        raise RuntimeError("handler exploded")

    engine, _ = engine_for([binding("dictation.toggle", ["button:4"])], dispatch=boom)
    assert engine.token_down("controller:pad", "button:4", now=0.0) == ["dictation.toggle"]
    # And the next press still works.
    engine.token_up("controller:pad", "button:4", now=0.1)
    assert engine.token_down("controller:pad", "button:4", now=0.2) == ["dictation.toggle"]


def test_a_resolver_that_throws_yields_no_bindings_rather_than_an_exception():
    rec = Recorder()

    def bad_resolver(_key):
        raise RuntimeError("store on fire")

    engine = ControllerEngine(rec, bad_resolver, clock=lambda: 0.0)
    engine.device_added("controller:pad")
    assert engine.token_down("controller:pad", "button:4", now=0.0) == []


# --- capture: the setup wizard's "press a button now" ------------------------


def test_capture_swallows_everything_including_the_emergency_stop():
    """Capture is not suspension. While the user is choosing which button their
    emergency stop should be, pressing the candidate must not fire the real
    one — so capture dispatches nothing at all."""
    engine, rec = engine_for([
        binding("dictation.toggle", ["button:4"]),
        binding("emergency.stop", ["button:9"]),
    ])
    engine.begin_capture()
    engine.token_down("controller:pad", "button:4", now=0.0)
    engine.token_down("controller:pad", "button:9", now=0.1)
    engine.tick(now=5.0)
    assert rec.ids == []


def test_capture_reports_nothing_until_the_button_is_released():
    """Answering mid-press would turn the first token of a two-button chord into
    a single binding, and the user has no way to see that happen."""
    engine, _ = engine_for([])
    engine.begin_capture()
    engine.token_down("controller:pad", "button:4", now=0.0)
    assert engine.capture_result() is None
    engine.token_up("controller:pad", "button:4", now=0.2)
    assert engine.capture_result() == {
        "device_key": "controller:pad", "style": "single", "events": ["button:4"],
    }


def test_capture_records_a_chord_as_a_chord():
    engine, _ = engine_for([])
    engine.begin_capture()
    engine.token_down("controller:pad", "button:4", now=0.0)
    engine.token_down("controller:pad", "button:5", now=0.05)
    assert engine.capture_result() is None
    engine.token_up("controller:pad", "button:5", now=0.3)
    engine.token_up("controller:pad", "button:4", now=0.31)
    assert engine.capture_result() == {
        "device_key": "controller:pad", "style": "chord",
        "events": ["button:4", "button:5"],
    }


def test_capture_takes_the_largest_simultaneous_set_not_the_last_token():
    """A user rolling off a chord releases one button before the other. The
    binding they meant is what was down at the same moment, not what happened to
    still be down at the end."""
    engine, _ = engine_for([])
    engine.begin_capture()
    engine.token_down("controller:pad", "button:4", now=0.0)
    engine.token_down("controller:pad", "button:5", now=0.05)
    engine.token_up("controller:pad", "button:4", now=0.2)
    engine.token_up("controller:pad", "button:5", now=0.4)
    assert engine.capture_result()["events"] == ["button:4", "button:5"]


def test_cancelling_capture_restores_ordinary_dispatch():
    engine, rec = engine_for([binding("dictation.toggle", ["button:4"])])
    engine.begin_capture()
    engine.token_down("controller:pad", "button:4", now=0.0)
    engine.token_up("controller:pad", "button:4", now=0.1)
    assert rec.ids == []
    engine.cancel_capture()
    assert engine.capturing is False
    engine.token_down("controller:pad", "button:4", now=1.0)
    assert rec.ids == ["dictation.toggle"]


# --- the pygame adapter, with pygame faked ----------------------------------


class FakePygame:
    JOYDEVICEADDED = 1
    JOYDEVICEREMOVED = 2
    JOYBUTTONDOWN = 3
    JOYBUTTONUP = 4
    JOYHATMOTION = 5
    JOYAXISMOTION = 6

    class joystick:
        instances = []

        @classmethod
        def get_count(cls):
            return len(cls.instances)

        @classmethod
        def Joystick(cls, index):
            return cls.instances[index]


class FakeJoystick:
    def __init__(self, instance_id, name):
        self._id = instance_id
        self._name = name

    def init(self):
        return None

    def get_instance_id(self):
        return self._id

    def get_name(self):
        return self._name


@pytest.fixture
def source():
    """A source over a fresh engine — no pre-added device, and no debounce.

    Debounce is off here on purpose: these tests use a frozen clock to keep the
    adapter's translation assertions exact, and a frozen clock plus a real bounce
    window would make every second press look like a bounce. Bounce itself is
    covered above, against the engine, where the clock is the thing under test.
    """
    rec = Recorder()
    rows = [
        binding("dictation.begin", ["button:4"], mode="hold"),
        binding("emergency.stop", ["hat:0:up"]),
        binding("latest.read", ["axis:2:pos"]),
    ]
    engine = ControllerEngine(
        rec,
        lambda _key: {row["action_id"]: row for row in rows},
        debounce_ms=0,
        clock=lambda: 0.0,
    )
    FakePygame.joystick.instances = [FakeJoystick(7, "Xbox Wireless Controller")]
    src = PygameEventSource(engine, FakePygame)
    src.refresh_devices()
    return src, rec


def test_the_adapter_derives_a_stable_key_from_the_device_name(source):
    src, _ = source
    assert src.engine.known_devices() == ["controller:xbox_wireless_controller"]


def test_button_events_reach_the_engine(source):
    src, rec = source
    src.handle(types.SimpleNamespace(type=FakePygame.JOYBUTTONDOWN, instance_id=7, button=4))
    assert rec.ids == ["dictation.begin"]
    src.handle(types.SimpleNamespace(type=FakePygame.JOYBUTTONUP, instance_id=7, button=4))
    assert rec.ids == ["dictation.begin", "dictation.end"]


def test_a_removal_event_releases_held_state(source):
    src, rec = source
    src.handle(types.SimpleNamespace(type=FakePygame.JOYBUTTONDOWN, instance_id=7, button=4))
    released = src.handle(types.SimpleNamespace(type=FakePygame.JOYDEVICEREMOVED, instance_id=7))
    assert released == ["dictation.end"]


def test_hat_motion_becomes_direction_tokens(source):
    src, rec = source
    src.handle(types.SimpleNamespace(type=FakePygame.JOYHATMOTION, instance_id=7, hat=0, value=(0, 1)))
    assert rec.ids == ["emergency.stop"]
    # Centring the hat releases, and re-pushing fires again.
    src.handle(types.SimpleNamespace(type=FakePygame.JOYHATMOTION, instance_id=7, hat=0, value=(0, 0)))
    src.handle(types.SimpleNamespace(type=FakePygame.JOYHATMOTION, instance_id=7, hat=0, value=(0, 1)))
    assert rec.ids == ["emergency.stop", "emergency.stop"]


def test_an_axis_resting_near_the_threshold_does_not_chatter(source):
    """Hysteresis, not debounce: the events are genuinely far enough apart that
    no bounce window would catch them."""
    src, rec = source
    src.axis_threshold = 0.6
    for value in (0.61, 0.59, 0.61, 0.59, 0.61):
        src.handle(types.SimpleNamespace(type=FakePygame.JOYAXISMOTION, instance_id=7, axis=2, value=value))
    assert rec.ids == ["latest.read"]
    # Only a real return past the release point re-arms it.
    src.handle(types.SimpleNamespace(type=FakePygame.JOYAXISMOTION, instance_id=7, axis=2, value=0.1))
    src.handle(types.SimpleNamespace(type=FakePygame.JOYAXISMOTION, instance_id=7, axis=2, value=0.9))
    assert rec.ids == ["latest.read", "latest.read"]


# --- the live test, for the director's hardware pass -------------------------


def _real_pygame_with_a_joystick():
    """The real pygame, initialised, if and only if a controller is plugged in.

    Returns ``None`` on every machine this project has, which is the point: the
    test below skips rather than failing, and skipping is honest where a mocked
    "pass" would not be.
    """
    try:
        import pygame  # noqa: PLC0415
    except Exception:
        return None
    try:
        pygame.init()
        pygame.joystick.init()
        if pygame.joystick.get_count() < 1:
            return None
        return pygame
    except Exception:
        return None


@pytest.mark.skipif(
    _real_pygame_with_a_joystick() is None,
    reason="no controller present; run this on the director's hardware",
)
def test_live_a_real_controller_is_enumerated_with_a_stable_key():
    """The one thing no mock can prove: that a real driver reports a name we can
    derive a stable key from, twice.

    Deliberately narrow. It enumerates and does not press anything, because a
    test that waited for a human to press a button is a test that hangs in CI.
    The rest of the hardware pass is the checklist in docs/release/WAVE10_QA.md.
    """
    pygame = _real_pygame_with_a_joystick()
    engine, _rec = engine_for([])
    source = PygameEventSource(engine, pygame)

    first = source.refresh_devices()
    assert first, "a joystick was counted but none could be opened"
    for key in first:
        assert key.startswith("controller:")

    # Same devices, same keys: this is the reconnect property against a real
    # driver rather than against a fake name.
    second = PygameEventSource(ControllerEngine(_rec, lambda _k: {}), pygame)
    assert sorted(second.refresh_devices()) == sorted(first)


def test_the_engine_is_importable_and_usable_with_no_pygame_at_all():
    engine, _ = engine_for([binding("dictation.toggle", ["button:4"])])
    src = PygameEventSource(engine, pygame_module=None)
    assert src.available is False
    assert src.refresh_devices() == []
    assert src.handle(types.SimpleNamespace(type=1)) == []
