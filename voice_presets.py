"""Voice presets (Voice Studio) — named, reusable voice configurations.

A preset bundles a base Kokoro voice, an optional blend recipe, and
modulation settings into one named, saved unit ("Warm Assistant", "Crisp
editor") so a user picks a voice once instead of re-tuning sliders every
time. Mirrors macros.py's JSON-store pattern exactly (quarantine-on-corrupt,
upsert-by-name, no cross-call atomicity — same accepted tradeoff as macros).
"""
import json
import logging
import os
import threading
import time

from utils import get_user_data_path

_lock = threading.RLock()

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


def _quarantine_corrupt_file(path):
    """Move an unparseable JSON file aside instead of silently losing it, so
    the pipeline recovers cleanly and the original data isn't overwritten by
    the next save. Best-effort; failures here are non-fatal."""
    try:
        corrupt_path = f"{path}.corrupt"
        if os.path.exists(corrupt_path):
            corrupt_path = f"{path}.{int(time.time())}.corrupt"
        os.replace(path, corrupt_path)
    except OSError:
        pass


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
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return []
        except OSError as exc:
            logging.warning(f"Could not read voice_presets.json: {exc}")
            return []
        except ValueError as exc:
            logging.warning(f"voice_presets.json is corrupted ({exc}); quarantining it and starting fresh.")
            _quarantine_corrupt_file(path)
            return []

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
            with open(_presets_path(), "w", encoding="utf-8") as handle:
                json.dump({"presets": presets}, handle, indent=2)
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
