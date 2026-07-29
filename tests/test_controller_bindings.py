"""Binding storage and three-layer resolution (Wave 10, deliverables 2 and 6)."""

import json
import os

import pytest

from backend.stores import controller_bindings as cb


def single(token, **extra):
    """A minimal, complete binding spec."""
    spec = {"input": {"style": "single", "events": [token]}}
    spec.update(extra)
    return spec


@pytest.fixture
def store(tmp_path):
    return cb.ControllerBindingStore(path=str(tmp_path / "controller_bindings.json"))


# --- device keys -------------------------------------------------------------


def test_device_key_requires_a_known_kind_prefix():
    assert cb.normalize_device_key("controller:Xbox Wireless Controller") == \
        "controller:xbox_wireless_controller"
    assert cb.normalize_device_key("stream_deck:Stream Deck XL") == "stream_deck:stream_deck_xl"
    assert cb.normalize_device_key("xbox wireless controller") == ""
    assert cb.normalize_device_key("keyboard:foo") == ""
    assert cb.normalize_device_key("") == ""


def test_device_key_is_derived_from_the_name_not_an_instance_id():
    """The reconnect property, at the level it is actually decided.

    pygame hands out a fresh instance id on every replug. Two "connections" of
    the same pad must produce the same key or the user's bindings silently stop
    applying the second time they plug it in.
    """
    first = cb.device_key_for("controller", "8BitDo Pro 2")
    second = cb.device_key_for("controller", "8BitDo Pro 2")
    assert first == second == "controller:8bitdo_pro_2"


# --- sanitisation ------------------------------------------------------------


def test_a_binding_without_an_input_is_refused_not_defaulted():
    """InputBinding.from_dict(None) yields button:4. Silently claiming button 4
    for a row that merely named an action would be a binding nobody chose."""
    row, reason = cb.sanitize_binding("dictation.begin", {"mode": "press"})
    assert row is None
    assert "which button" in reason


def test_release_halves_cannot_be_bound_directly():
    row, reason = cb.sanitize_binding("dictation.end", single("button:1"))
    assert row is None
    assert reason


def test_hold_mode_downgrades_for_an_action_with_no_release_half():
    row, _ = cb.sanitize_binding("emergency.stop", single("button:7", mode="hold"))
    assert row["mode"] == "press"
    row, _ = cb.sanitize_binding("dictation.begin", single("button:7", mode="hold"))
    assert row["mode"] == "hold"


def test_flat_input_shape_is_tolerated():
    """What a Wave 7 profile's bindings.record_toggle looks like on disk."""
    row, _ = cb.sanitize_binding(
        "dictation.toggle", {"style": "chord", "events": ["button:4", "button:5"]},
    )
    assert row["input"]["style"] == "chord"
    assert row["input"]["events"] == ["button:4", "button:5"]


def test_a_parameterised_action_without_its_parameter_is_refused():
    row, reason = cb.sanitize_binding("persona.activate", single("button:2"))
    assert row is None
    assert reason


# --- three-layer resolution --------------------------------------------------


def test_layers_fold_per_action_not_per_layer():
    """The property that keeps a panic button from vanishing.

    A game profile that rebinds one action must not silently unbind everything
    else the user set on the device.
    """
    data = {
        "global": {"emergency.stop": cb.sanitize_binding("emergency.stop", single("button:9"))[0]},
        "devices": {
            "controller:pad": {
                "dictation.begin": cb.sanitize_binding("dictation.begin", single("button:4"))[0],
            },
        },
    }
    profile = {"dictation.begin": single("button:1")}

    resolved = cb.resolve_bindings(data, "controller:pad", profile)

    assert set(resolved) == {"emergency.stop", "dictation.begin"}
    # Most specific wins for the action it names...
    assert resolved["dictation.begin"]["input"]["events"] == ["button:1"]
    # ...and leaves the emergency stop exactly where the user put it.
    assert resolved["emergency.stop"]["input"]["events"] == ["button:9"]


def test_device_layer_only_applies_to_that_device():
    data = {
        "devices": {
            "controller:pad": {
                "dictation.begin": cb.sanitize_binding("dictation.begin", single("button:4"))[0],
            },
        },
    }
    assert cb.resolve_bindings(data, "controller:stick") == {}
    assert "dictation.begin" in cb.resolve_bindings(data, "controller:pad")


def test_coverage_reports_reachable_not_merely_bound():
    """A held dictation.begin reaches dictation.end without its own button, and
    telling the user otherwise pushes them to bind a second way to strand a
    recording."""
    resolved = cb.resolve_bindings({
        "global": {
            "dictation.begin": cb.sanitize_binding("dictation.begin", single("button:4", mode="hold"))[0],
            "command.begin": cb.sanitize_binding("command.begin", single("button:5", mode="hold"))[0],
            "capture.cancel": cb.sanitize_binding("capture.cancel", single("button:6"))[0],
            "latest.read": cb.sanitize_binding("latest.read", single("button:1"))[0],
            "latest.copy": cb.sanitize_binding("latest.copy", single("button:2"))[0],
            "latest.inject": cb.sanitize_binding("latest.inject", single("button:3"))[0],
            "emergency.stop": cb.sanitize_binding("emergency.stop", single("button:9"))[0],
        },
    })
    report = cb.coverage(resolved)
    assert "dictation.end" in report["reachable"]
    assert "dictation.end" not in report["bound"]
    assert report["missing_required"] == []
    assert report["has_emergency_stop"] is True
    assert report["dictation_and_command_are_separate"] is True


def test_coverage_names_a_missing_emergency_stop():
    resolved = cb.resolve_bindings({"global": {
        "dictation.toggle": cb.sanitize_binding("dictation.toggle", single("button:4"))[0],
    }})
    report = cb.coverage(resolved)
    assert report["has_emergency_stop"] is False
    assert "emergency.stop" in report["missing_required"]


# --- the store ---------------------------------------------------------------


def test_set_and_resolve_round_trip(store):
    assert store.set_binding("dictation.begin", single("button:4", mode="hold"))["ok"]
    assert store.set_binding("emergency.stop", single("button:9"), "controller:pad")["ok"]

    resolved = store.resolve("controller:pad")
    assert resolved["dictation.begin"]["mode"] == "hold"
    assert resolved["emergency.stop"]["input"]["events"] == ["button:9"]
    assert store.devices() == ["controller:pad"]


def test_set_binding_rejects_an_unknown_device(store):
    result = store.set_binding("dictation.begin", single("button:4"), "keyboard:foo")
    assert result["ok"] is False
    assert result["error"] == "invalid_device"


def test_clear_binding_removes_an_empty_device_layer(store):
    store.set_binding("dictation.begin", single("button:4"), "controller:pad")
    assert store.clear_binding("dictation.begin", "controller:pad")["removed"] is True
    assert store.devices() == []


def test_debounce_is_clamped(store):
    assert store.set_debounce_ms(10_000)["debounce_ms"] == cb.MAX_DEBOUNCE_MS
    assert store.set_debounce_ms(-5)["debounce_ms"] == cb.MIN_DEBOUNCE_MS
    assert store.set_debounce_ms("nonsense")["ok"] is False


def test_a_corrupt_file_degrades_to_no_bindings_rather_than_raising(store):
    with open(store.path, "w", encoding="utf-8") as handle:
        handle.write("{not json at all")
    data = store.read()
    assert data["global"] == {}
    assert data["devices"] == {}
    # And the store is still writable afterwards.
    assert store.set_binding("emergency.stop", single("button:9"))["ok"]


def test_clear_all_removes_the_device_fingerprint(store):
    store.set_binding("dictation.begin", single("button:4"), "controller:8bitdo_pro_2")
    store.clear_all()
    on_disk = json.loads(open(store.path, encoding="utf-8").read())
    assert on_disk["devices"] == {}
    assert "8bitdo" not in json.dumps(on_disk).lower()


def test_the_store_filename_is_the_one_declared_to_data_categories():
    """Wave 6 declares this exact filename under the unified root. If it moves,
    the privacy enumeration test finds an undeclared file."""
    assert cb.STORE_FILENAME == "controller_bindings.json"


def test_default_path_lands_under_the_unified_root(monkeypatch, tmp_path):
    import utils

    monkeypatch.setattr(utils, "get_user_data_path", lambda: str(tmp_path))
    assert cb.ControllerBindingStore().path == os.path.join(str(tmp_path), cb.STORE_FILENAME)


def test_the_declared_privacy_path_is_the_path_the_stores_actually_use():
    """Wave 6 declares these two files by deriving them from
    ``app_paths.resolve_base()``; the stores derive them from
    ``utils.get_user_data_path()``. Those are the same directory today (the
    latter is the former plus a mkdir), and if they ever stop being, the privacy
    report points at a file nobody writes and the wipe misses the one that
    exists. Cheap insurance against a silent divergence."""
    import app_paths
    import utils
    from backend.stores import stream_deck_config as sd

    root = os.path.realpath(str(app_paths.resolve_base()))
    assert os.path.realpath(utils.get_user_data_path()) == root

    for module in (cb, sd):
        assert os.path.realpath(os.path.dirname(
            os.path.join(utils.get_user_data_path(), module.STORE_FILENAME),
        )) == root
