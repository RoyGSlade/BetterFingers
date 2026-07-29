"""Controller bindings — the global and per-device layers, and the resolver
that folds them together with Wave 7's per-application layer (Wave 10).

THREE LAYERS, MOST SPECIFIC WINS:

    application profile  (Wave 7: profile["bindings"], NOT stored here)
        beats
    device               (this store: bindings.devices[<device_key>])
        beats
    global               (this store: bindings.global_)

The application layer deliberately lives somewhere else. Wave 7's profile
schema already reserved a ``bindings`` slot for exactly this, and a profile is
the thing a user opens when they think "behave differently in this game" — a
second per-application binding table in a second file would be two places to
look and two places to disagree. Wave 10 widens ``BINDING_SLOTS`` to the shared
action ids and consumes that slot; it does not fork it.

The device layer, by contrast, has no home in a profile and needs one: "the
left bumper on my flight stick" is a fact about the stick, not about Rocket
League, and it must survive switching profiles.

WHAT A DEVICE KEY IS. A stable, boring string the adapter derives from the
device's own name (``controller:xbox_wireless_controller``). NOT the pygame
instance id, which is a counter that changes on every reconnect — a binding
keyed by instance id would silently stop applying the second time you plug the
same controller in, which is the exact bug reconnect handling exists to prevent.

STORAGE mirrors AppProfileStore and WorkflowStore: one versioned JSON file under
the unified data root, loaded lazily, written atomically, every mutation
re-reading from disk first. A corrupt file degrades to "no bindings" rather than
taking the input layer down — and "no bindings" is a safe answer, because a
button that does nothing is better than a button that does something nobody
chose.
"""

from __future__ import annotations

import json
import re
import threading
from typing import Optional

from backend.domain.input_actions import (
    ACTION_EMERGENCY_STOP,
    BINDABLE_ACTION_IDS,
    DEVICE_KINDS,
    normalize_action_id,
    normalize_param,
)
from input_binding import InputBinding
from store_migration import load_versioned_store, write_atomic

# Schema history:
#   v1 (current): {"schema_version": 1, "enabled", "debounce_ms",
#                  "global": {action_id: binding}, "devices": {key: {…}}}
SCHEMA_VERSION = 1

STORE_FILENAME = "controller_bindings.json"

# How a binding fires.
#   press  -- fires once when the binding becomes satisfied
#   hold   -- fires the action on press and its release_id on release
TRIGGER_MODES = ("press", "hold")

# Contact bounce on a cheap controller is real: a single physical press can
# report two JOYBUTTONDOWN events a few milliseconds apart. 40ms is longer than
# any bounce this project has observed and far shorter than a deliberate
# double-press, which is why it is a default rather than a constant -- a user
# with a worse pad can raise it.
DEFAULT_DEBOUNCE_MS = 40
MIN_DEBOUNCE_MS = 0
MAX_DEBOUNCE_MS = 500

MAX_DEVICES = 16
MAX_DEVICE_KEY_LEN = 96

_DEVICE_KEY_RE = re.compile(r"^(?:%s):[a-z0-9][a-z0-9_]{0,63}$" % "|".join(DEVICE_KINDS))


def _empty_store() -> dict:
    return {"enabled": True, "debounce_ms": DEFAULT_DEBOUNCE_MS, "global": {}, "devices": {}}


def normalize_device_key(value) -> str:
    """``'controller:xbox_wireless_controller'`` — or ``''`` if unusable.

    The kind prefix is required. Without it a Stream Deck and a gamepad that
    happened to report the same name would share bindings, and the first time
    that happens the user has no way to tell which device they are editing.
    """
    text = str(value or "").strip().lower()
    if ":" not in text:
        return ""
    kind, _, name = text.partition(":")
    kind = kind.strip()
    if kind not in DEVICE_KINDS:
        return ""
    token = re.sub(r"[^a-z0-9_]+", "_", name).strip("_")[:64]
    key = f"{kind}:{token}"
    return key if _DEVICE_KEY_RE.match(key) else ""


def device_key_for(kind: str, device_name) -> str:
    """The key an adapter should use for a device it just saw."""
    return normalize_device_key(f"{kind}:{device_name}")


def normalize_trigger_mode(value, action_id: str = "") -> str:
    mode = str(value or "press").strip().lower()
    if mode not in TRIGGER_MODES:
        mode = "press"
    if mode == "hold":
        from backend.domain.input_actions import ACTION_BY_ID

        action = ACTION_BY_ID.get(normalize_action_id(action_id))
        # An action with no release half cannot be held: "hold to run a
        # workflow" would either run it once and lie about the mode, or run it
        # repeatedly. Downgrading to press is the honest reading of the intent.
        if action is None or not action.holdable:
            mode = "press"
    return mode


def sanitize_binding(action_id, spec) -> tuple[Optional[dict], str]:
    """``(binding, reason)``. ``binding`` is None when the row is unusable.

    A binding row is ``{action_id, mode, param, input}`` where ``input`` is the
    existing Wave 2 ``InputBinding`` document — style, events, timing window,
    axis threshold and device scope. Reusing it rather than inventing a second
    event grammar is the point: chords, sequences and axis thresholds already
    work and are already tested.
    """
    canonical = normalize_action_id(action_id)
    if not canonical:
        return None, "That is not an action BetterFingers can perform."
    if canonical not in BINDABLE_ACTION_IDS:
        return None, "That action is the release half of a held binding and cannot be bound on its own."

    spec = spec if isinstance(spec, dict) else {}
    param, reason = normalize_param(canonical, spec.get("param"))
    if reason:
        return None, reason

    raw_input = spec.get("input")
    if raw_input is None and ("style" in spec or "events" in spec):
        # Tolerate the flat shape a hand-edited file or an older adapter emits
        # -- notably a Wave 7 profile's ``bindings.record_toggle``, which is a
        # bare InputBinding document.
        raw_input = spec
    if not isinstance(raw_input, dict):
        # REFUSE rather than default. ``InputBinding.from_dict(None)`` returns a
        # binding on button:4, which is a sensible default for the one hard-coded
        # record button Wave 2 shipped and a genuinely dangerous one here: a row
        # that merely names an action would silently claim the user's button 4,
        # and a Stream Deck row (which has no controller tokens at all) would
        # grow a phantom gamepad binding nobody chose. An incomplete row is
        # incomplete; saying so is the whole job of this function.
        return None, "That binding does not say which button to press."
    binding = InputBinding.from_dict(raw_input)

    return {
        "action_id": canonical,
        "mode": normalize_trigger_mode(spec.get("mode"), canonical),
        "param": param,
        "input": binding.to_dict(),
    }, ""


def sanitize_binding_map(value) -> tuple[dict, list]:
    """``({action_id: binding}, dropped)`` for one layer."""
    if not isinstance(value, dict):
        return {}, []
    out, dropped = {}, []
    for action_id, spec in value.items():
        binding, reason = sanitize_binding(action_id, spec)
        if binding is None:
            dropped.append(str(action_id))
            continue
        out[binding["action_id"]] = binding
    return out, sorted(set(dropped))


def _normalize_store(data) -> dict:
    data = data if isinstance(data, dict) else {}

    try:
        debounce = int(data.get("debounce_ms", DEFAULT_DEBOUNCE_MS))
    except (TypeError, ValueError):
        debounce = DEFAULT_DEBOUNCE_MS
    debounce = max(MIN_DEBOUNCE_MS, min(MAX_DEBOUNCE_MS, debounce))

    global_map, _ = sanitize_binding_map(data.get("global"))

    devices = {}
    raw_devices = data.get("devices")
    if isinstance(raw_devices, dict):
        for raw_key, raw_map in raw_devices.items():
            key = normalize_device_key(raw_key)
            if not key:
                continue
            layer, _ = sanitize_binding_map(raw_map)
            if layer:
                devices[key] = layer
            if len(devices) >= MAX_DEVICES:
                break

    return {
        "schema_version": SCHEMA_VERSION,
        "enabled": bool(data.get("enabled", True)),
        "debounce_ms": debounce,
        "global": global_map,
        "devices": devices,
    }


# --- Resolution --------------------------------------------------------------


def resolve_bindings(store_data, device_key: str = "", profile_bindings=None) -> dict:
    """The bindings in force for one device under one application profile.

    Layering is per ACTION, not per layer: a profile that rebinds only
    ``dictation.begin`` leaves the user's device-level emergency stop exactly
    where it was. Replacing whole layers would mean pinning one action in a game
    profile silently unbinds every other button, which is how a panic button
    disappears.
    """
    data = _normalize_store(store_data)
    resolved = dict(data["global"])

    key = normalize_device_key(device_key)
    if key:
        resolved.update(data["devices"].get(key, {}))

    profile_layer, _ = sanitize_binding_map(profile_bindings)
    resolved.update(profile_layer)
    return resolved


def emergency_stop_binding(resolved: dict) -> Optional[dict]:
    """The emergency-stop row, if the user bound one.

    Split out because every adapter has to answer "can this device stop
    everything?" and the answer must not depend on remembering the id.
    """
    return resolved.get(ACTION_EMERGENCY_STOP)


def coverage(resolved: dict) -> dict:
    """What a device can and cannot do, for the setup UI and for the tests that
    assert the Wave 10 requirement list is reachable."""
    from backend.domain.input_actions import REQUIRED_ACTION_IDS

    bound = set(resolved)
    # dictation.end is reachable without its own binding: a held
    # dictation.begin dispatches it on release, and a dictation.toggle reaches
    # both halves. Reporting it as "missing" would push users to bind a button
    # whose only job is to be a second way to strand a recording.
    reachable = set(bound)
    for row in resolved.values():
        if row["action_id"] == "dictation.begin" and row["mode"] == "hold":
            reachable.add("dictation.end")
        if row["action_id"] == "dictation.toggle":
            reachable.update({"dictation.begin", "dictation.end"})
        if row["action_id"] == "command.begin" and row["mode"] == "hold":
            reachable.add("command.end")

    missing = [action_id for action_id in REQUIRED_ACTION_IDS if action_id not in reachable]
    return {
        "bound": sorted(bound),
        "reachable": sorted(reachable),
        "missing_required": missing,
        "has_emergency_stop": ACTION_EMERGENCY_STOP in bound,
        "dictation_and_command_are_separate": (
            reachable & {"dictation.begin", "dictation.toggle"} != set()
            and "command.begin" in bound
        ),
    }


# --- The store ---------------------------------------------------------------


class ControllerBindingStore:
    """Global + per-device bindings on disk.

    ``path`` should always be passed explicitly in tests — the default touches
    the real user profile via ``utils.get_user_data_path()``, the
    cross-test-pollution trap this repo already learned to avoid.
    """

    def __init__(self, path: Optional[str] = None):
        self._path = path
        self._lock = threading.RLock()

    @property
    def path(self) -> str:
        if self._path is None:
            import os
            from utils import get_user_data_path

            self._path = os.path.join(get_user_data_path(), STORE_FILENAME)
        return self._path

    def _load(self) -> dict:
        data, _report = load_versioned_store(
            self.path, SCHEMA_VERSION, {},
            default_factory=_empty_store, parse=json.loads,
        )
        return _normalize_store(data)

    def _save(self, data: dict) -> None:
        write_atomic(self.path, json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))

    # --- inspection -------------------------------------------------------

    def read(self) -> dict:
        with self._lock:
            return self._load()

    def resolve(self, device_key: str = "", profile_bindings=None) -> dict:
        return resolve_bindings(self.read(), device_key, profile_bindings)

    def devices(self) -> list:
        return sorted(self.read()["devices"])

    # --- mutation ---------------------------------------------------------

    def set_binding(self, action_id, spec, device_key: str = "") -> dict:
        """Bind one action, globally or for one device."""
        binding, reason = sanitize_binding(action_id, spec)
        if binding is None:
            return {"ok": False, "error": "refused", "reason": reason}

        key = normalize_device_key(device_key) if device_key else ""
        if device_key and not key:
            return {"ok": False, "error": "invalid_device",
                    "reason": "That is not a device BetterFingers recognises."}

        with self._lock:
            data = self._load()
            if key:
                layer = data["devices"].setdefault(key, {})
                if len(data["devices"]) > MAX_DEVICES:
                    return {"ok": False, "error": "cap_reached",
                            "reason": f"You already have bindings for {MAX_DEVICES} devices."}
                layer[binding["action_id"]] = binding
            else:
                data["global"][binding["action_id"]] = binding
            try:
                self._save(data)
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "reason": str(exc)}
            return {"ok": True, "binding": dict(binding), "device_key": key or None}

    def clear_binding(self, action_id, device_key: str = "") -> dict:
        canonical = normalize_action_id(action_id)
        if not canonical:
            return {"ok": False, "error": "refused",
                    "reason": "That is not an action BetterFingers can perform."}
        key = normalize_device_key(device_key) if device_key else ""
        with self._lock:
            data = self._load()
            layer = data["devices"].get(key, {}) if key else data["global"]
            removed = layer.pop(canonical, None) is not None
            if key and not layer:
                data["devices"].pop(key, None)
            if removed:
                try:
                    self._save(data)
                except OSError as exc:
                    return {"ok": False, "error": "write_failed", "reason": str(exc)}
            return {"ok": True, "removed": removed}

    def set_debounce_ms(self, value) -> dict:
        try:
            debounce = int(value)
        except (TypeError, ValueError):
            return {"ok": False, "error": "refused", "reason": "Give a number of milliseconds."}
        debounce = max(MIN_DEBOUNCE_MS, min(MAX_DEBOUNCE_MS, debounce))
        with self._lock:
            data = self._load()
            data["debounce_ms"] = debounce
            try:
                self._save(data)
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "reason": str(exc)}
            return {"ok": True, "debounce_ms": debounce}

    def set_enabled(self, enabled) -> dict:
        with self._lock:
            data = self._load()
            data["enabled"] = bool(enabled)
            try:
                self._save(data)
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "reason": str(exc)}
            return {"ok": True, "enabled": data["enabled"]}

    def clear_all(self) -> dict:
        """Privacy clear. The device list records which controllers this person
        owns, which is a hardware fingerprint even though a binding is a
        setting — see the data_categories entry."""
        with self._lock:
            try:
                self._save(_normalize_store(_empty_store()))
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "reason": str(exc)}
            return {"ok": True}
