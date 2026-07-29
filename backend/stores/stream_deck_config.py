"""Stream Deck configuration — BetterFingers' half of the plugin (Wave 10).

WHAT THIS STORE IS NOT. It is not a copy of the Stream Deck's key layout. The
Stream Deck software owns which key is where, what it looks like, and which
profile it belongs to; duplicating that here would create a second source of
truth that goes stale the first time somebody drags a key in the Stream Deck app
and never opens BetterFingers again.

WHAT IT IS. The BetterFingers-side facts about the deck:

* whether the adapter is switched on at all;
* a MIRROR of what each plugin action instance is currently set to, so the
  dashboard can answer "what does my Stream Deck do?" without talking to the
  Stream Deck software — reported by the plugin, never authored here;
* the pairing state, as a fingerprint and never a token.

WHY A MIRROR IS SAFE AND A MASTER WOULD NOT BE. A mirror row is written only
when the plugin reports one (``willAppear``) and removed when the plugin reports
it gone (``willDisappear``). If the two ever disagree, the Stream Deck wins,
because the Stream Deck is the thing with the buttons on it. Nothing in
BetterFingers reads this map to decide what a key press means — a key press
arrives carrying its own action id, and *that* is what gets dispatched. The map
exists to be shown to a human.

PAIRING. The plugin is a separate process and must present the same loopback
bearer token every other client uses; there is no second auth system here. The
user copies the pairing code out of BetterFingers and pastes it into the
plugin's property inspector. This store keeps only ``sha256(token)`` truncated
to a fingerprint, so the file can say "paired" without being a second place the
secret lives. ``verify_pairing`` compares in constant time.

HARDWARE STATUS. No Stream Deck exists on this project's machines. Everything
here is exercised by protocol tests against a fake WebSocket; the honest
qualification status travels in ``qualification()`` and in
``integrations/streamdeck/QUALIFICATION.md`` so a caller cannot lose it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
from typing import Optional

from backend.domain.input_actions import (
    ACTION_EMERGENCY_STOP,
    BINDABLE_ACTION_IDS,
    normalize_action_id,
    normalize_param,
)
from store_migration import load_versioned_store, write_atomic

# Schema history:
#   v1 (current): {"schema_version": 1, "enabled", "pairing": {...},
#                  "keys": {context: row}, "devices": {device_id: row}}
SCHEMA_VERSION = 1

STORE_FILENAME = "stream_deck_config.json"

#: The plugin's own UUID namespace, as registered in its manifest. Kept here as
#: well so a protocol test can assert the Python side and the plugin manifest
#: agree without either importing the other's file format.
PLUGIN_UUID = "com.betterfingers.streamdeck"

#: One Stream Deck action per BetterFingers action id we expose on a key. The
#: plugin manifest declares exactly these and no others -- a key that could name
#: an arbitrary action id would be a way to reach an id we deliberately did not
#: put on a button.
def plugin_action_uuid(action_id: str) -> str:
    """``com.betterfingers.streamdeck.dictation.begin`` — or ``''``."""
    canonical = normalize_action_id(action_id)
    if not canonical or canonical not in BINDABLE_ACTION_IDS:
        return ""
    return f"{PLUGIN_UUID}.{canonical}"


PLUGIN_ACTION_UUIDS = tuple(plugin_action_uuid(a) for a in BINDABLE_ACTION_IDS)

#: Stream Deck sends a key title; it is user-typed and therefore user text. It
#: is stored so the dashboard can show the same words the user sees on the deck.
MAX_TITLE_LEN = 80
MAX_KEYS = 256
MAX_DEVICES = 8

#: The truncated digest length. Long enough that a collision is not a practical
#: concern for a local pairing check, short enough that the file is not a
#: password-strength artefact if it leaks.
FINGERPRINT_LEN = 32

_CONTEXT_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_DEVICE_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _empty_store() -> dict:
    return {
        "enabled": False,
        "pairing": {"paired": False, "fingerprint": ""},
        "keys": {},
        "devices": {},
    }


def fingerprint(token) -> str:
    text = str(token or "")
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:FINGERPRINT_LEN]


def normalize_context(value) -> str:
    """The opaque per-key handle the Stream Deck software assigns.

    Opaque is the operative word: it is not derived from anything the user typed
    and it means nothing outside a running Stream Deck session, which is exactly
    why it is a safe map key.
    """
    text = str(value or "").strip()
    return text if _CONTEXT_RE.match(text) else ""


def normalize_device_id(value) -> str:
    text = str(value or "").strip()
    return text if _DEVICE_RE.match(text) else ""


def action_id_from_plugin_action(value) -> str:
    """``com.betterfingers.streamdeck.latest.copy`` -> ``latest.copy``.

    Returns ``''`` for anything outside our namespace. The plugin sends its own
    action UUID with every event; trusting the *suffix* rather than a separate
    settings field means a key cannot be made to mean something other than the
    action it was created as.
    """
    text = str(value or "").strip()
    prefix = PLUGIN_UUID + "."
    if not text.startswith(prefix):
        return ""
    candidate = normalize_action_id(text[len(prefix):])
    return candidate if candidate in BINDABLE_ACTION_IDS else ""


def sanitize_key(context, payload) -> tuple[Optional[dict], str]:
    """One mirrored key row, or ``(None, reason)``.

    The action comes from the plugin action UUID, never from free-form settings.
    The parameter goes through the same ``normalize_param`` the controller uses,
    so a hand-edited Stream Deck settings blob cannot smuggle a value into an
    action that has no slot for one.
    """
    key = normalize_context(context)
    if not key:
        return None, "That is not a Stream Deck key BetterFingers recognises."

    payload = payload if isinstance(payload, dict) else {}
    action_id = action_id_from_plugin_action(payload.get("action"))
    if not action_id:
        action_id = normalize_action_id(payload.get("action_id"))
    if not action_id or action_id not in BINDABLE_ACTION_IDS:
        return None, "That key is not set to anything BetterFingers can perform."

    settings = payload.get("settings")
    settings = settings if isinstance(settings, dict) else {}
    param, reason = normalize_param(action_id, settings.get("param", payload.get("param")))
    if reason:
        return None, reason

    coordinates = payload.get("coordinates")
    coordinates = coordinates if isinstance(coordinates, dict) else {}

    def _coord(name):
        try:
            return max(0, min(31, int(coordinates.get(name))))
        except (TypeError, ValueError):
            return None

    row = {
        "context": key,
        "action_id": action_id,
        "param": param,
        # "device" is what the Stream Deck sends; "device_id" is what we store.
        # Both are accepted because every row round-trips through this function
        # on load, and a sanitiser that cannot read its own output silently
        # erases a field on the first reload.
        "device_id": normalize_device_id(payload.get("device", payload.get("device_id"))),
        "title": " ".join(str(payload.get("title") or "").split())[:MAX_TITLE_LEN],
    }
    column, rownum = _coord("column"), _coord("row")
    if column is not None and rownum is not None:
        row["coordinates"] = {"column": column, "row": rownum}
    return row, ""


def sanitize_device(device_id, payload) -> Optional[dict]:
    key = normalize_device_id(device_id)
    if not key:
        return None
    payload = payload if isinstance(payload, dict) else {}
    # The Stream Deck nests the grid under "size"; our stored row keeps it flat.
    # Read both, for the same round-trip reason as sanitize_key's device id.
    size = payload.get("size")
    size = size if isinstance(size, dict) else {}

    def _dim(name):
        try:
            return max(1, min(32, int(size.get(name, payload.get(name)))))
        except (TypeError, ValueError):
            return 0

    return {
        "device_id": key,
        # A Stream Deck model name ("Stream Deck XL"). Hardware, not a person.
        "name": " ".join(str(payload.get("name") or "").split())[:MAX_TITLE_LEN],
        "columns": _dim("columns"),
        "rows": _dim("rows"),
        "connected": bool(payload.get("connected", True)),
    }


def _normalize_store(data) -> dict:
    data = data if isinstance(data, dict) else {}

    raw_pairing = data.get("pairing")
    raw_pairing = raw_pairing if isinstance(raw_pairing, dict) else {}
    digest = str(raw_pairing.get("fingerprint") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{%d}" % FINGERPRINT_LEN, digest or ""):
        digest = ""

    keys = {}
    raw_keys = data.get("keys")
    if isinstance(raw_keys, dict):
        for context, payload in raw_keys.items():
            row, _ = sanitize_key(context, payload)
            if row is None:
                continue
            keys[row["context"]] = row
            if len(keys) >= MAX_KEYS:
                break

    devices = {}
    raw_devices = data.get("devices")
    if isinstance(raw_devices, dict):
        for device_id, payload in raw_devices.items():
            row = sanitize_device(device_id, payload)
            if row is None:
                continue
            devices[row["device_id"]] = row
            if len(devices) >= MAX_DEVICES:
                break

    return {
        "schema_version": SCHEMA_VERSION,
        "enabled": bool(data.get("enabled", False)),
        "pairing": {"paired": bool(digest), "fingerprint": digest},
        "keys": keys,
        "devices": devices,
    }


def coverage(keys: dict) -> dict:
    """What the deck as a whole can reach — same question the controller's
    ``coverage`` answers, so the setup UI can ask it once."""
    bound = {row["action_id"] for row in (keys or {}).values()}
    return {
        "bound": sorted(bound),
        "has_emergency_stop": ACTION_EMERGENCY_STOP in bound,
        "key_count": len(keys or {}),
    }


class StreamDeckConfigStore:
    """The mirrored deck state on disk.

    ``path`` should always be passed explicitly in tests — the default touches
    the real user profile via ``utils.get_user_data_path()``.
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

    def _mutate(self, fn) -> dict:
        with self._lock:
            data = self._load()
            result = fn(data)
            if result.get("ok"):
                try:
                    self._save(_normalize_store(data))
                except OSError as exc:
                    return {"ok": False, "error": "write_failed", "reason": str(exc)}
            return result

    # --- inspection -------------------------------------------------------

    def read(self) -> dict:
        with self._lock:
            return self._load()

    def summary(self) -> dict:
        """Everything the dashboard shows, with no secret in it."""
        data = self.read()
        return {
            "enabled": data["enabled"],
            "paired": data["pairing"]["paired"],
            "devices": sorted(data["devices"].values(), key=lambda row: row["device_id"]),
            "keys": sorted(data["keys"].values(), key=lambda row: row["context"]),
            "coverage": coverage(data["keys"]),
            "qualification": qualification(),
        }

    # --- pairing ----------------------------------------------------------

    def pair(self, token) -> dict:
        digest = fingerprint(token)
        if not digest:
            return {"ok": False, "error": "refused",
                    "reason": "Paste the pairing code from BetterFingers first."}

        def apply(data):
            data["pairing"] = {"paired": True, "fingerprint": digest}
            return {"ok": True, "paired": True}

        return self._mutate(apply)

    def unpair(self) -> dict:
        def apply(data):
            data["pairing"] = {"paired": False, "fingerprint": ""}
            data["keys"] = {}
            return {"ok": True, "paired": False}

        return self._mutate(apply)

    def verify_pairing(self, token) -> bool:
        """Constant-time check that this token is the one that paired.

        Not a substitute for the HTTP bearer check — that still happens, on every
        request, in the server middleware. This answers the narrower question
        "is the deck talking to us still the deck the user paired?", which is
        what lets the UI say *paired* honestly.
        """
        stored = self.read()["pairing"]["fingerprint"]
        if not stored:
            return False
        return hmac.compare_digest(stored, fingerprint(token))

    # --- mirrored state ---------------------------------------------------

    def set_enabled(self, enabled) -> dict:
        def apply(data):
            data["enabled"] = bool(enabled)
            return {"ok": True, "enabled": data["enabled"]}

        return self._mutate(apply)

    def record_key(self, context, payload) -> dict:
        """The plugin reported a key that exists (``willAppear``/``didReceiveSettings``)."""
        row, reason = sanitize_key(context, payload)
        if row is None:
            return {"ok": False, "error": "refused", "reason": reason}

        def apply(data):
            if row["context"] not in data["keys"] and len(data["keys"]) >= MAX_KEYS:
                return {"ok": False, "error": "cap_reached",
                        "reason": f"BetterFingers tracks at most {MAX_KEYS} Stream Deck keys."}
            data["keys"][row["context"]] = row
            return {"ok": True, "key": dict(row)}

        return self._mutate(apply)

    def forget_key(self, context) -> dict:
        key = normalize_context(context)

        def apply(data):
            return {"ok": True, "removed": data["keys"].pop(key, None) is not None}

        return self._mutate(apply)

    def record_device(self, device_id, payload) -> dict:
        row = sanitize_device(device_id, payload)
        if row is None:
            return {"ok": False, "error": "refused",
                    "reason": "That is not a Stream Deck BetterFingers recognises."}

        def apply(data):
            if row["device_id"] not in data["devices"] and len(data["devices"]) >= MAX_DEVICES:
                return {"ok": False, "error": "cap_reached",
                        "reason": f"BetterFingers tracks at most {MAX_DEVICES} Stream Decks."}
            data["devices"][row["device_id"]] = row
            return {"ok": True, "device": dict(row)}

        return self._mutate(apply)

    def device_disconnected(self, device_id) -> dict:
        """A deck went away.

        The keys stay: a Stream Deck that is unplugged and plugged back in is the
        same deck with the same keys, and forgetting the mirror would make the
        dashboard claim the user's deck is empty while it is merely asleep.
        Unlike a controller, a Stream Deck key cannot be *held* across the
        disconnect -- the plugin's own ``keyUp`` is what ends a hold, and a
        disconnect is reported to the engine as a device loss so held state is
        released through the same path the controller uses.
        """
        key = normalize_device_id(device_id)

        def apply(data):
            row = data["devices"].get(key)
            if row is None:
                return {"ok": True, "known": False}
            row["connected"] = False
            return {"ok": True, "known": True}

        return self._mutate(apply)

    def clear_all(self) -> dict:
        """Privacy clear — including the pairing fingerprint and every key
        title, which is the one field on this store the user typed."""
        with self._lock:
            try:
                self._save(_normalize_store(_empty_store()))
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "reason": str(exc)}
            return {"ok": True}


# --- Honest status -----------------------------------------------------------

QUALIFICATION_REASON = (
    "No Stream Deck hardware exists on this project's machines. The plugin and "
    "this adapter are exercised end to end against a fake Stream Deck WebSocket, "
    "which proves the protocol and the action mapping and proves nothing about a "
    "real device. Treat Stream Deck support as unqualified until the manual "
    "steps in integrations/streamdeck/QUALIFICATION.md have been run on a deck."
)


def qualification() -> dict:
    return {
        "qualified": False,
        "reason": QUALIFICATION_REASON,
        "protocol_tested": True,
        "manual_steps": "integrations/streamdeck/QUALIFICATION.md",
    }
