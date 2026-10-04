"""Voice macros (C11) — safe text-expansion subset.

A user-defined phrase ("my address", "sign off") expands to a snippet during
dictation. Text-only: keystroke/shell macros are intentionally out of scope for
now (security). Pure `apply_macros` so it is unit-testable.
"""
import json
import logging
import os
import re
import threading
import time

from utils import get_user_data_path

_lock = threading.RLock()


def _macros_path():
    return os.path.join(get_user_data_path(), "macros.json")


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


def get_macros():
    """List of {trigger, expansion} dicts."""
    path = _macros_path()
    with _lock:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return []
        except OSError as exc:
            logging.warning(f"Could not read macros.json: {exc}")
            return []
        except ValueError as exc:
            logging.warning(f"macros.json is corrupted ({exc}); quarantining it and starting fresh.")
            _quarantine_corrupt_file(path)
            return []
    if isinstance(data, dict):
        macros_field = data.get("macros", data)
        if isinstance(macros_field, dict):
            # Legacy format: {"macros": {trigger: expansion, ...}}.
            data = [{"trigger": k, "expansion": v} for k, v in macros_field.items()]
        else:
            # Current format written by _save(): {"macros": [{"trigger":.., "expansion":..}, ...]}.
            data = macros_field
    result = []
    seen = set()
    for item in data or []:
        if not isinstance(item, dict):
            continue
        trigger = str(item.get("trigger", "")).strip()
        expansion = str(item.get("expansion", "")).strip()
        key = trigger.lower()
        if trigger and expansion and key not in seen:
            seen.add(key)
            result.append({"trigger": trigger, "expansion": expansion})
    return result


def _save(macros):
    with _lock:
        try:
            with open(_macros_path(), "w", encoding="utf-8") as handle:
                json.dump({"macros": macros}, handle, indent=2)
        except OSError as exc:
            logging.warning(f"Failed to save macros: {exc}")


def add_macro(trigger, expansion):
    trigger = str(trigger or "").strip()
    expansion = str(expansion or "").strip()
    if not trigger or not expansion:
        return get_macros()
    macros = [m for m in get_macros() if m["trigger"].lower() != trigger.lower()]
    macros.append({"trigger": trigger, "expansion": expansion})
    _save(macros)
    return macros


def remove_macro(trigger):
    trigger = str(trigger or "").strip().lower()
    macros = [m for m in get_macros() if m["trigger"].lower() != trigger]
    _save(macros)
    return macros


def apply_macros(text, macros=None):
    """Expand macro triggers found as whole words/phrases. Case-insensitive
    trigger match; conservative (word-boundary, never inside a larger word)."""
    macros = macros if macros is not None else get_macros()
    if not text or not macros:
        return text
    # Longest triggers first so a more specific phrase wins over a shorter one.
    for macro in sorted(macros, key=lambda m: len(m["trigger"]), reverse=True):
        trigger = macro["trigger"]
        expansion = macro["expansion"]
        pattern = r"\b" + re.escape(trigger) + r"\b"
        text = re.sub(pattern, lambda _m: expansion, text, flags=re.IGNORECASE)
    return text
