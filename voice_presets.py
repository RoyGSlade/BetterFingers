"""Voice presets (Voice Studio) — named, reusable voice configurations.

A preset bundles a base Kokoro voice, an optional blend recipe, and
modulation settings into one named, saved unit ("Warm Assistant", "Crisp
editor") so a user picks a voice once instead of re-tuning sliders every
time. Persistence discipline (quarantine-on-corrupt, atomic writes, schema
versioning) comes from store_migration.py (DESIGN §9.5, Tier-3 M4 B2) — same
guarantees as personas/profiles instead of a hand-rolled copy. Existing
on-disk files with no schema_version key are treated as v1 (implicit,
zero-disruption for current users); no migrations are registered yet.

The store also carries one extra top-level key, "default": <name|None> — the
preset a user has designated to apply automatically to ordinary read-aloud
(no explicit preset_name in the request; see server.py's
_resolve_voice_and_modulation). It lives in the SAME json file/schema_version
as "presets" rather than a separate store so there is exactly one place that
can go corrupt/quarantine and one atomic write per change. Stores written
before this key existed simply lack it — load_versioned_store hands back
whatever dict was on disk, and `.get("default")` on a dict missing the key is
None, so old stores load with "no default set" for free.
"""
import json
import logging
import os
import threading
import time

from store_migration import load_versioned_store, write_atomic
from utils import get_user_data_path

_lock = threading.RLock()

_SCHEMA_VERSION = 1
_MIGRATIONS = {}  # {from_version: fn(data) -> data}, empty until v2 exists

# Field -> default value. Every preset dict always has exactly these keys
# (plus name/created_at/updated_at), fully defaulted and type-coerced.
_DEFAULTS = {
    "base": "",
    "blend": {},
    "speed": 1.0,
    "pitch": 0.0,
    "energy": 0.5,
    "warmth": 0.0,
    "brightness": 0.0,
    "pause_style": "natural",
    "stability": 0.5,
    "source": "manual",
}


def _presets_path():
    return os.path.join(get_user_data_path(), "voice_presets.json")


def _default_store():
    return {"presets": [], "default": None}


def _coerce_blend(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for name, weight in value.items():
        key = str(name or "").strip()
        if not key:
            continue
        try:
            w = float(weight)
        except (TypeError, ValueError):
            continue
        if w <= 0:
            continue
        result[key] = w
    return result


def _normalize(entry):
    """Fully-defaulted, type-coerced preset dict from a raw stored entry, or
    None if it has no usable name."""
    if not isinstance(entry, dict):
        return None
    name = str(entry.get("name", "")).strip()
    if not name:
        return None

    result = {"name": name}
    for key, default in _DEFAULTS.items():
        value = entry.get(key, default)
        if key == "blend":
            result[key] = _coerce_blend(value)
        elif key in ("pause_style", "source", "base"):
            result[key] = str(value or default)
        else:
            try:
                result[key] = float(value)
            except (TypeError, ValueError):
                result[key] = default

    result["created_at"] = entry.get("created_at") or time.time()
    result["updated_at"] = entry.get("updated_at") or result["created_at"]
    return result


def _load_data():
    """(presets, raw_default) straight off disk under the store discipline.

    presets: fully-defaulted/deduped preset dicts, in save order (same as
    get_presets()). raw_default: whatever the store's "default" key holds,
    trimmed to a non-empty string or None — NOT validated against presets
    (a stale/dangling name is returned as-is; get_default_preset() is the
    layer that resolves that). Kept internal since callers need the raw
    value (e.g. delete_preset comparing against the name being removed)
    rather than the resolved one.
    """
    path = _presets_path()
    with _lock:
        data, _report = load_versioned_store(
            path, _SCHEMA_VERSION, _MIGRATIONS, default_factory=_default_store, parse=json.loads,
        )

    presets_field = data.get("presets", []) if isinstance(data, dict) else []
    presets = []
    seen = set()
    for item in presets_field or []:
        normalized = _normalize(item)
        if normalized is None:
            continue
        key = normalized["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        presets.append(normalized)

    raw_default = data.get("default") if isinstance(data, dict) else None
    raw_default = str(raw_default).strip() if raw_default else None
    return presets, raw_default


def get_presets():
    """List of fully-defaulted preset dicts, in save order."""
    presets, _raw_default = _load_data()
    return presets


def _save(presets, default):
    with _lock:
        try:
            write_atomic(
                _presets_path(),
                json.dumps(
                    {"presets": presets, "schema_version": _SCHEMA_VERSION, "default": default},
                    indent=2,
                ),
            )
        except OSError as exc:
            logging.warning(f"Failed to save voice presets: {exc}")


def save_preset(name, **fields):
    """Upsert a preset by name (case-insensitive). Unspecified fields keep
    their prior value on update, or the schema default on create. Returns
    the full updated preset list."""
    name = str(name or "").strip()
    if not name:
        return get_presets()

    with _lock:
        existing, raw_default = _load_data()
        prior = next((p for p in existing if p["name"].lower() == name.lower()), None)
        base_entry = dict(prior) if prior else {"name": name, **_DEFAULTS}
        base_entry["name"] = name
        for key in _DEFAULTS:
            if key in fields and fields[key] is not None:
                base_entry[key] = fields[key]
        base_entry["updated_at"] = time.time()
        if prior is None:
            base_entry["created_at"] = base_entry["updated_at"]

        normalized = _normalize(base_entry)
        presets = [p for p in existing if p["name"].lower() != name.lower()]
        presets.append(normalized)
        # The default pointer is untouched by an unrelated save — carry the
        # on-disk value straight through instead of dropping it (a raw
        # `_save(presets, None)` here would silently clear the user's choice
        # every time they touch any preset).
        _save(presets, raw_default)
        return presets


def delete_preset(name):
    """Remove a preset by name (case-insensitive). Returns the remaining list.

    If the deleted preset was the default, the default is cleared too — a
    dangling pointer would otherwise resolve invisibly to "no default" via
    get_default_preset()'s validation, without ever telling the user their
    choice was quietly unset.
    """
    key = str(name or "").strip().lower()
    with _lock:
        presets, raw_default = _load_data()
        remaining = [p for p in presets if p["name"].lower() != key]
        new_default = None if (raw_default and raw_default.lower() == key) else raw_default
        _save(remaining, new_default)
        return remaining


def get_default_preset():
    """Name of the default preset, in its stored casing — or None if unset,
    or if it names a preset that no longer exists (dangling; e.g. the store
    was hand-edited, or a preset was removed by some path other than
    delete_preset). Never writes — a dangling reference is reported as None
    here but left on disk for delete_preset/set_default_preset to reconcile
    on their next write, keeping this a pure read."""
    presets, raw_default = _load_data()
    if not raw_default:
        return None
    for preset in presets:
        if preset["name"].lower() == raw_default.lower():
            return preset["name"]
    return None


def set_default_preset(name):
    """Mark an existing preset (case-insensitive match) as the default.
    Returns True on success; False if no preset with that name exists (the
    caller — routes_user_config.py — turns that into a 404) without writing
    anything."""
    key = str(name or "").strip().lower()
    if not key:
        return False
    with _lock:
        presets, _raw_default = _load_data()
        match = next((p for p in presets if p["name"].lower() == key), None)
        if match is None:
            return False
        _save(presets, match["name"])
        return True


def clear_default_preset():
    """Unset the default preset, if any. Idempotent; never errors."""
    with _lock:
        presets, _raw_default = _load_data()
        _save(presets, None)
