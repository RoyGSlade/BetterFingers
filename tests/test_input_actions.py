"""The shared input-action vocabulary (Wave 10, deliverable 1)."""

import pytest

from backend.domain import input_actions as ia


def test_required_wave10_actions_all_exist():
    """Deliverable 1's list, item by item. Named explicitly so deleting one is a
    failure here rather than a button that quietly stopped existing."""
    for action_id in (
        "dictation.begin", "dictation.end", "command.begin", "capture.cancel",
        "latest.read", "latest.inject", "latest.copy", "emergency.stop",
    ):
        assert action_id in ia.ACTION_BY_ID
        assert action_id in ia.REQUIRED_ACTION_IDS


def test_dictation_and_command_capture_are_separate_bindings():
    """"Dictation and command capture must have separate bindings at minimum."

    The enforcement is structural: they are different ids, both bindable, and
    neither is reachable from the other.
    """
    assert ia.ACTION_DICTATION_BEGIN != ia.ACTION_COMMAND_BEGIN
    assert ia.ACTION_DICTATION_BEGIN in ia.BINDABLE_ACTION_IDS
    assert ia.ACTION_COMMAND_BEGIN in ia.BINDABLE_ACTION_IDS
    assert ia.ACTION_BY_ID[ia.ACTION_DICTATION_BEGIN].release_id == ia.ACTION_DICTATION_END
    assert ia.ACTION_BY_ID[ia.ACTION_COMMAND_BEGIN].release_id == ia.ACTION_COMMAND_END
    # And no id is both.
    assert ia.ACTION_BY_ID[ia.ACTION_DICTATION_BEGIN].release_id != ia.ACTION_COMMAND_END


def test_release_halves_are_not_bindable():
    """Binding "end dictation" to its own button is how a recording gets
    stranded when the begin half never fires."""
    assert ia.ACTION_DICTATION_END not in ia.BINDABLE_ACTION_IDS
    assert ia.ACTION_COMMAND_END not in ia.BINDABLE_ACTION_IDS


def test_emergency_stop_is_the_only_always_available_action():
    always = [a.id for a in ia.ACTIONS if a.always_available]
    assert always == [ia.ACTION_EMERGENCY_STOP]


def test_normalize_action_id_is_exact():
    assert ia.normalize_action_id("  DICTATION.BEGIN ") == "dictation.begin"
    assert ia.normalize_action_id("dictation.beginn") == ""
    assert ia.normalize_action_id(None) == ""
    assert ia.normalize_action_id({"id": "dictation.begin"}) == ""


def test_actions_without_a_param_ignore_whatever_is_passed():
    """A Stream Deck key re-bound from "switch persona" to "cancel" keeps its old
    settings blob; that stale value must not reach the new action."""
    param, reason = ia.normalize_param("capture.cancel", "Priya")
    assert (param, reason) == ("", "")


def test_parameterised_actions_require_a_value():
    param, reason = ia.normalize_param("persona.activate", "   ")
    assert param == ""
    assert reason


def test_id_parameters_are_squeezed_to_id_shape():
    param, reason = ia.normalize_param("workflow.run", "Start Work Day")
    assert (param, reason) == ("start_work_day", "")
    param, reason = ia.normalize_param("application_profile.activate", "///")
    assert param == ""
    assert reason


def test_name_parameters_are_bounded_but_not_mangled():
    param, reason = ia.normalize_param("persona.activate", "  True   Janitor  ")
    assert (param, reason) == ("True Janitor", "")
    long_param, _ = ia.normalize_param("persona.activate", "x" * 500)
    assert len(long_param) == ia.MAX_PARAM_LEN


def test_vocabulary_is_self_consistent():
    payload = ia.vocabulary()
    assert payload["schema_version"] == ia.SCHEMA_VERSION
    ids = [row["id"] for row in payload["actions"]]
    assert ids == list(ia.ACTION_IDS)
    assert set(payload["bindable"]) <= set(ids)
    assert set(payload["required"]) <= set(ids)
    assert payload["emergency_stop"] == ia.ACTION_EMERGENCY_STOP
    assert payload["device_kinds"] == ["controller", "stream_deck"]


@pytest.mark.parametrize("action", ia.ACTIONS)
def test_every_action_is_described_for_a_human(action):
    """A setup UI shows these strings. An empty one is a blank row in a list of
    buttons somebody is trying to choose between."""
    assert action.label.strip()
    assert action.description.strip()
    if action.holdable:
        assert action.release_id in ia.ACTION_BY_ID
