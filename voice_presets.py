"""Voice presets (Voice Studio) — named, reusable voice configurations.

A preset bundles a base Kokoro voice, an optional blend recipe, and
modulation settings into one named, saved unit ("Warm Assistant", "Crisp
editor") so a user picks a voice once instead of re-tuning sliders every
time. Persistence discipline (quarantine-on-corrupt, atomic writes, schema
versioning) comes from store_migration.py (DESIGN §9.5, Tier-3 M4 B2) — same
guarantees as personas/profiles instead of a hand-rolled copy. Existing
on-disk files with no schema_version key are treated as v1 (implicit,
zero-disruption for current users); no migrations are registered yet.
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
    return {"presets": []}


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


def get_presets():
    """List of fully-defaulted preset dicts, in save order."""
    path = _presets_path()
    with _lock:
        data, _report = load_versioned_store(
            path, _SCHEMA_VERSION, _MIGRATIONS, default_factory=_default_store, parse=json.loads,
        )

    presets_field = data.get("presets", []) if isinstance(data, dict) else []
    result = []
    seen = set()
    for item in presets_field or []:
        normalized = _normalize(item)
        if normalized is None:
            continue
        key = normalized["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def _save(presets):
    with _lock:
        try:
            write_atomic(
                _presets_path(),
                json.dumps({"presets": presets, "schema_version": _SCHEMA_VERSION}, indent=2),
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

    existing = get_presets()
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
    _save(presets)
    return presets


def delete_preset(name):
    """Remove a preset by name (case-insensitive). Returns the remaining list."""
    key = str(name or "").strip().lower()
    presets = [p for p in get_presets() if p["name"].lower() != key]
    _save(presets)
    return presets
