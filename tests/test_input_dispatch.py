"""The one gate every non-voice device passes through (Wave 10, deliverable 1)."""

import pytest

from backend.domain import input_actions as ia
from backend.services.input_dispatch import (
    InputActionDispatcher,
    InputActionHandlers,
    rehearsal_dispatcher,
)


class Calls(dict):
    def handler(self, name, result=None):
        def fn(*args):
            self.setdefault(name, []).append(args)
            return result
        return fn


@pytest.fixture
def calls():
    return Calls()


@pytest.fixture
def dispatcher(calls):
    return InputActionDispatcher(InputActionHandlers(
        begin_dictation=calls.handler("begin_dictation"),
        end_dictation=calls.handler("end_dictation"),
        toggle_dictation=calls.handler("toggle_dictation"),
        begin_command=calls.handler("begin_command"),
        end_command=calls.handler("end_command"),
        cancel_capture=calls.handler("cancel_capture"),
        read_latest=calls.handler("read_latest"),
        copy_latest=calls.handler("copy_latest"),
        inject_latest=calls.handler("inject_latest"),
        activate_persona=calls.handler("activate_persona"),
        activate_writing_preset=calls.handler("activate_writing_preset"),
        activate_application_profile=calls.handler("activate_application_profile"),
        request_workflow=calls.handler("request_workflow"),
        emergency_stop=calls.handler("emergency_stop"),
    ))


def test_every_action_id_has_a_handler_slot():
    """Asserted at import too; asserted here so the reason is written down. An id
    with no slot is a button that does nothing and says nothing."""
    from backend.services.input_dispatch import _HANDLER_FOR

    assert set(_HANDLER_FOR) == set(ia.ACTION_BY_ID)


def test_every_required_action_reaches_its_contract(dispatcher, calls):
    """Deliverable 1, one assertion per required action."""
    expected = {
        "dictation.begin": "begin_dictation",
        "dictation.end": "end_dictation",
        "command.begin": "begin_command",
        "capture.cancel": "cancel_capture",
        "latest.read": "read_latest",
        "latest.copy": "copy_latest",
        "latest.inject": "inject_latest",
        "emergency.stop": "emergency_stop",
    }
    assert set(expected) == set(ia.REQUIRED_ACTION_IDS)
    for action_id, handler_name in expected.items():
        result = dispatcher.dispatch(action_id, source="controller")
        assert result["ok"], (action_id, result)
        assert handler_name in calls


def test_an_unknown_id_is_reported_not_raised(dispatcher):
    result = dispatcher.dispatch("dictation.beginn")
    assert result["ok"] is False
    assert result["status"] == "unknown_action"


def test_an_unwired_handler_reports_unavailable():
    bare = InputActionDispatcher(InputActionHandlers())
    result = bare.dispatch("latest.read", source="controller")
    assert result["status"] == "unavailable"
    assert bare.available_actions() == []


def test_a_handler_that_throws_is_a_failed_status_not_a_crash():
    def boom():
        raise RuntimeError("nope")

    d = InputActionDispatcher(InputActionHandlers(emergency_stop=boom))
    assert d.dispatch("emergency.stop")["status"] == "failed"
    # And the dispatcher still works afterwards.
    assert d.dispatch("emergency.stop")["status"] == "failed"


def test_a_parameterised_action_without_its_parameter_is_refused(dispatcher, calls):
    result = dispatcher.dispatch("persona.activate", param="  ")
    assert result["status"] == "needs_param"
    assert "activate_persona" not in calls


def test_a_parameter_is_normalised_before_the_handler_sees_it(dispatcher, calls):
    dispatcher.dispatch("workflow.run", param="Start Work Day")
    assert calls["request_workflow"] == [("start_work_day",)]


# --- the gates ---------------------------------------------------------------


def test_suspension_blocks_everything_except_the_emergency_stop(dispatcher, calls):
    dispatcher.suspend("wizard is recording a binding")
    assert dispatcher.dispatch("dictation.toggle", source="controller")["status"] == "suspended"
    assert "toggle_dictation" not in calls
    assert dispatcher.dispatch("emergency.stop", source="controller")["ok"] is True


def test_a_disabled_device_kind_blocks_everything_except_the_emergency_stop(dispatcher):
    dispatcher.set_kind_enabled("stream_deck", False)
    blocked = dispatcher.dispatch("latest.copy", source="stream_deck",
                                  device_key="stream_deck:abc")
    assert blocked["status"] == "disabled"
    # The other device kind is untouched...
    assert dispatcher.dispatch("latest.copy", source="controller",
                               device_key="controller:pad")["ok"] is True
    # ...and the panic button works from the disabled one anyway.
    assert dispatcher.dispatch("emergency.stop", source="stream_deck",
                               device_key="stream_deck:abc")["ok"] is True


def test_an_unconfigured_device_kind_is_enabled(dispatcher):
    """Plugged in and it worked is the behaviour; opt-out, not opt-in."""
    assert dispatcher.dispatch("latest.copy", source="controller")["ok"] is True


@pytest.mark.parametrize("kind,key", [
    ("controller", "controller:pad"),
    ("stream_deck", "stream_deck:abc123"),
])
def test_emergency_stop_works_from_every_supported_input_device(dispatcher, calls, kind, key):
    """Deliverable 5's last clause, one case per device kind in DEVICE_KINDS."""
    dispatcher.suspend("everything is off")
    dispatcher.set_kind_enabled(kind, False)
    assert dispatcher.dispatch("emergency.stop", source=kind, device_key=key)["ok"] is True
    assert len(calls["emergency_stop"]) == 1


def test_device_kinds_are_all_covered_by_that_parametrisation():
    """Guards the test above: adding a device kind without adding a case would
    leave a device whose panic button nobody checked."""
    assert set(ia.DEVICE_KINDS) == {"controller", "stream_deck"}


# --- held state and release --------------------------------------------------


def test_a_hold_is_registered_and_released_by_its_release_id(dispatcher):
    dispatcher.dispatch("dictation.begin", source="controller",
                        device_key="controller:pad", hold=True)
    assert dispatcher.held_actions("controller:pad") == ["dictation.begin"]
    dispatcher.dispatch("dictation.end", source="controller", device_key="controller:pad")
    assert dispatcher.held_actions("controller:pad") == []


def test_a_press_that_is_not_a_hold_registers_nothing(dispatcher):
    dispatcher.dispatch("dictation.begin", source="controller", device_key="controller:pad")
    assert dispatcher.held_actions() == []


def test_release_device_releases_only_that_device(dispatcher, calls):
    """Unplugging a Stream Deck must not end a dictation the keyboard started."""
    dispatcher.dispatch("dictation.begin", source="controller",
                        device_key="controller:pad", hold=True)
    dispatcher.dispatch("command.begin", source="stream_deck",
                        device_key="stream_deck:abc", hold=True)

    released = dispatcher.release_device("stream_deck:abc")

    assert released == ["command.end"]
    assert calls.get("end_dictation") is None
    assert dispatcher.held_actions("controller:pad") == ["dictation.begin"]


def test_release_device_goes_through_dispatch_not_a_side_channel(dispatcher, calls):
    """D-0026: one release mechanism. The Wave 8 lease and the audio broker hang
    off the ordinary handler, so an unplug that bypassed it would strand them."""
    dispatcher.dispatch("dictation.begin", source="controller",
                        device_key="controller:pad", hold=True)
    dispatcher.release_device("controller:pad")
    assert calls["end_dictation"] == [()]
    assert [r.action_id for r in dispatcher.log][-1] == "dictation.end"


def test_release_device_clears_held_state_even_if_the_handler_fails():
    """The device is gone either way. A stale entry would make the NEXT unplug
    try to release something twice."""
    def boom():
        raise RuntimeError("audio stack already torn down")

    d = InputActionDispatcher(InputActionHandlers(
        begin_dictation=lambda: None, end_dictation=boom,
    ))
    d.dispatch("dictation.begin", device_key="controller:pad", hold=True)
    assert d.release_device("controller:pad") == []
    assert d.held_actions() == []


def test_release_device_on_a_device_holding_nothing_is_a_no_op(dispatcher, calls):
    assert dispatcher.release_device("controller:never_seen") == []
    assert calls == {}


# --- the log -----------------------------------------------------------------


def test_the_log_records_codes_and_never_a_parameter_value(dispatcher):
    dispatcher.dispatch("persona.activate", param="Priya", source="stream_deck",
                        device_key="stream_deck:abc")
    rows = dispatcher.recent(5)
    assert rows[-1]["action_id"] == "persona.activate"
    assert rows[-1]["status"] == "ok"
    assert "priya" not in repr(rows).lower()


def test_the_log_is_bounded(dispatcher):
    for _ in range(InputActionDispatcher.MAX_LOG + 50):
        dispatcher.dispatch("capture.cancel")
    assert len(dispatcher.log) == InputActionDispatcher.MAX_LOG


# --- the wizard's rehearsal dispatcher ---------------------------------------


@pytest.mark.parametrize("action_id", ia.ACTION_IDS)
def test_the_rehearsal_dispatcher_can_never_fire_anything(action_id):
    """The wizard's "test WITHOUT sending" requirement, enforced by test.

    Not a flag a later edit could invert: there is no callable to reach. Every
    id, INCLUDING the emergency stop, comes back non-ok — during a rehearsal
    even the panic button must not stop a recording the user never started.
    """
    d = rehearsal_dispatcher()
    result = d.dispatch(action_id, param="anything")
    assert result["ok"] is False
    assert result["status"] in ("unavailable", "needs_param")


def test_the_rehearsal_dispatcher_still_reports_what_it_saw():
    """It has to be useful: the wizard shows the user that their button arrived."""
    d = rehearsal_dispatcher()
    d.dispatch("dictation.begin", source="controller", device_key="controller:pad")
    assert d.recent(1) == [{
        "action_id": "dictation.begin", "status": "unavailable",
        "source": "controller", "device_kind": "controller",
    }]
