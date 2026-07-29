"""Stream Deck configuration store and protocol mapping (Wave 10, deliverables 4 and 6).

No Stream Deck hardware exists on this project's machines. These tests cover the
protocol translation and the store; they are explicitly NOT a hardware
qualification, and ``test_qualification_is_honest`` exists to keep that written
down in the code rather than only in a release note.
"""

import json
import os

import pytest

from backend.domain import input_actions as ia
from backend.stores import stream_deck_config as sd


@pytest.fixture
def store(tmp_path):
    return sd.StreamDeckConfigStore(path=str(tmp_path / "stream_deck_config.json"))


def key_payload(action_id, **extra):
    payload = {
        "action": sd.plugin_action_uuid(action_id),
        "device": "DEV1",
        "title": "Talk",
        "coordinates": {"column": 2, "row": 1},
        "settings": {},
    }
    payload.update(extra)
    return payload


# --- the action namespace ----------------------------------------------------


def test_the_plugin_exposes_exactly_the_bindable_actions():
    """Deliverable 4's list. A key that could name an arbitrary id would be a way
    to reach an id we deliberately did not put on a button."""
    for action_id in ia.BINDABLE_ACTION_IDS:
        assert sd.plugin_action_uuid(action_id) == f"{sd.PLUGIN_UUID}.{action_id}"
    for action_id in (ia.ACTION_DICTATION_END, ia.ACTION_COMMAND_END, "nonsense"):
        assert sd.plugin_action_uuid(action_id) == ""


def test_the_deliverable_4_actions_are_all_reachable_from_a_key():
    """dictate, command, persona, writing preset, application profile, saved
    workflow, copy latest, read latest, emergency stop."""
    for action_id in (
        "dictation.begin", "command.begin", "persona.activate",
        "writing_preset.activate", "application_profile.activate",
        "workflow.run", "latest.copy", "latest.read", "emergency.stop",
    ):
        assert sd.plugin_action_uuid(action_id)


def test_the_action_comes_from_the_plugin_uuid_not_from_settings():
    """A key cannot be made to mean something other than the action it was
    created as, because the id is read out of the action UUID the Stream Deck
    itself sends."""
    assert sd.action_id_from_plugin_action(f"{sd.PLUGIN_UUID}.latest.copy") == "latest.copy"
    assert sd.action_id_from_plugin_action("com.someoneelse.plugin.latest.copy") == ""
    assert sd.action_id_from_plugin_action(f"{sd.PLUGIN_UUID}.dictation.end") == ""
    assert sd.action_id_from_plugin_action(None) == ""


def test_a_key_whose_uuid_is_ours_wins_over_a_forged_action_id_field():
    payload = key_payload("latest.copy")
    payload["action_id"] = "emergency.stop"
    row, _ = sd.sanitize_key("ctx1", payload)
    assert row["action_id"] == "latest.copy"


# --- key sanitisation --------------------------------------------------------


def test_a_key_with_no_recognised_action_is_refused():
    row, reason = sd.sanitize_key("ctx1", {"action": "com.other.thing"})
    assert row is None
    assert reason


def test_a_stale_settings_blob_cannot_smuggle_a_value_into_a_new_action():
    row, _ = sd.sanitize_key("ctx1", key_payload("capture.cancel", settings={"param": "Priya"}))
    assert row["param"] == ""


def test_a_parameterised_key_without_its_parameter_is_refused():
    row, reason = sd.sanitize_key("ctx1", key_payload("persona.activate"))
    assert row is None
    assert reason


def test_a_workflow_key_carries_only_an_id_shaped_parameter():
    row, _ = sd.sanitize_key(
        "ctx1", key_payload("workflow.run", settings={"param": "Start Work Day"}),
    )
    assert row["param"] == "start_work_day"


def test_an_unusable_context_is_refused():
    assert sd.sanitize_key("", key_payload("latest.copy"))[0] is None
    assert sd.sanitize_key("../../etc/passwd", key_payload("latest.copy"))[0] is None


def test_a_key_row_survives_a_round_trip_through_the_sanitiser(store):
    """The sanitiser runs on every load. One that cannot read its own output
    would silently erase a field on the first reload."""
    store.record_key("ctx1", key_payload("latest.copy"))
    first = store.read()["keys"]["ctx1"]
    reloaded = sd.StreamDeckConfigStore(path=store.path).read()["keys"]["ctx1"]
    assert first == reloaded
    assert reloaded["device_id"] == "DEV1"
    assert reloaded["coordinates"] == {"column": 2, "row": 1}
    assert reloaded["title"] == "Talk"


# --- devices -----------------------------------------------------------------


def test_a_device_row_survives_a_round_trip(store):
    store.record_device("DEV1", {"name": "Stream Deck XL", "size": {"columns": 8, "rows": 4}})
    reloaded = sd.StreamDeckConfigStore(path=store.path).read()["devices"]["DEV1"]
    assert reloaded["columns"] == 8
    assert reloaded["rows"] == 4
    assert reloaded["name"] == "Stream Deck XL"


def test_a_disconnect_marks_the_device_but_keeps_the_keys(store):
    """An unplugged deck is the same deck. Forgetting the mirror would make the
    dashboard claim the user's deck is empty while it is merely asleep."""
    store.record_device("DEV1", {"name": "Stream Deck XL"})
    store.record_key("ctx1", key_payload("latest.copy"))
    store.device_disconnected("DEV1")
    data = store.read()
    assert data["devices"]["DEV1"]["connected"] is False
    assert "ctx1" in data["keys"]


def test_forgetting_a_key_removes_only_that_key(store):
    store.record_key("ctx1", key_payload("latest.copy"))
    store.record_key("ctx2", key_payload("latest.read"))
    assert store.forget_key("ctx1")["removed"] is True
    assert sorted(store.read()["keys"]) == ["ctx2"]


# --- pairing -----------------------------------------------------------------


def test_pairing_stores_a_fingerprint_and_never_the_token(store):
    store.pair("s3cret-loopback-token")
    on_disk = open(store.path, encoding="utf-8").read()
    assert "s3cret-loopback-token" not in on_disk
    assert json.loads(on_disk)["pairing"]["paired"] is True
    assert len(json.loads(on_disk)["pairing"]["fingerprint"]) == sd.FINGERPRINT_LEN


def test_verify_pairing_accepts_only_the_paired_token(store):
    assert store.verify_pairing("anything") is False
    store.pair("s3cret")
    assert store.verify_pairing("s3cret") is True
    assert store.verify_pairing("s3cret ") is False


def test_unpairing_forgets_the_keys_too(store):
    store.pair("s3cret")
    store.record_key("ctx1", key_payload("latest.copy"))
    store.unpair()
    data = store.read()
    assert data["pairing"] == {"paired": False, "fingerprint": ""}
    assert data["keys"] == {}


def test_an_empty_token_does_not_pair(store):
    assert store.pair("")["ok"] is False
    assert store.read()["pairing"]["paired"] is False


def test_a_forged_fingerprint_in_a_hand_edited_file_is_dropped(store):
    with open(store.path, "w", encoding="utf-8") as handle:
        json.dump({"schema_version": 1, "pairing": {"paired": True, "fingerprint": "hello"}}, handle)
    assert store.read()["pairing"] == {"paired": False, "fingerprint": ""}


# --- store hygiene -----------------------------------------------------------


def test_the_adapter_is_off_until_the_user_turns_it_on(store):
    assert store.read()["enabled"] is False
    assert store.set_enabled(True)["enabled"] is True


def test_a_corrupt_file_degrades_to_an_empty_config(store):
    with open(store.path, "w", encoding="utf-8") as handle:
        handle.write("{{{ not json")
    data = store.read()
    assert data["keys"] == {}
    assert data["pairing"]["paired"] is False
    assert store.set_enabled(True)["ok"]


def test_clear_all_removes_the_pairing_and_the_user_typed_titles(store):
    store.pair("s3cret")
    store.record_key("ctx1", key_payload("latest.copy", title="Ping Priya"))
    store.clear_all()
    on_disk = open(store.path, encoding="utf-8").read()
    assert "Priya" not in on_disk
    assert json.loads(on_disk)["pairing"]["paired"] is False


def test_the_store_filename_is_the_one_declared_to_data_categories():
    assert sd.STORE_FILENAME == "stream_deck_config.json"


def test_default_path_lands_under_the_unified_root(monkeypatch, tmp_path):
    import utils

    monkeypatch.setattr(utils, "get_user_data_path", lambda: str(tmp_path))
    assert sd.StreamDeckConfigStore().path == os.path.join(str(tmp_path), sd.STORE_FILENAME)


def test_coverage_answers_the_same_question_the_controller_answers(store):
    store.record_key("ctx1", key_payload("emergency.stop"))
    summary = store.summary()
    assert summary["coverage"]["has_emergency_stop"] is True
    assert summary["coverage"]["key_count"] == 1


def test_the_manifest_declares_exactly_our_actions():
    """The two halves of the plugin live in different languages and different
    directories. This is the assertion that keeps them one thing: add an action
    id without adding a manifest entry (or the reverse) and this goes red.
    The JS suite asserts the same equality from its end."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    manifest_path = os.path.join(root, "integrations", "streamdeck", "manifest.json")
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)

    declared = sorted(action["UUID"] for action in manifest["Actions"])
    assert declared == sorted(sd.PLUGIN_ACTION_UUIDS)


def test_the_plugin_release_table_matches_the_action_vocabulary():
    """The plugin hard-codes which actions are holdable (it cannot import
    Python). This asserts the hard-coded table is the right one."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source = open(os.path.join(root, "integrations", "streamdeck", "src", "plugin.js"),
                  encoding="utf-8").read()
    for action in ia.ACTIONS:
        pair = f"'{action.id}': '{action.release_id}'"
        if action.holdable and action.id in ia.BINDABLE_ACTION_IDS:
            assert pair in source, f"plugin.js is missing the hold pair for {action.id}"
        else:
            assert f"'{action.id}':" not in source.split("RELEASE_FOR = {")[1].split("}")[0]


def test_qualification_is_honest():
    """No deck exists here. The status travels with the payload so a UI cannot
    show Stream Deck support without also being able to show that it is
    unverified."""
    status = sd.qualification()
    assert status["qualified"] is False
    assert status["protocol_tested"] is True
    assert "QUALIFICATION.md" in status["manual_steps"]
    assert status["reason"].strip()
