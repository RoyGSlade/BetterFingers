"""Versioned, atomic persona draft persistence separate from confirmed personas."""

from __future__ import annotations

import copy
import json
import os
import threading
import time
from typing import Any

from store_migration import load_versioned_store, write_atomic
from utils import get_user_data_path


SCHEMA_VERSION = 1
_lock = threading.RLock()


def _path() -> str:
    return os.path.join(get_user_data_path(), "persona_drafts.json")


def _default() -> dict[str, Any]:
    return {"drafts": {}}


def _load() -> dict[str, Any]:
    data, _report = load_versioned_store(
        _path(), SCHEMA_VERSION, {}, default_factory=_default, parse=json.loads,
    )
    drafts = data.get("drafts", {}) if isinstance(data, dict) else {}
    return drafts if isinstance(drafts, dict) else {}


def _save(drafts: dict[str, Any]) -> None:
    write_atomic(_path(), json.dumps({"schema_version": SCHEMA_VERSION, "drafts": drafts}, indent=2))


def get_draft(persona_id: str) -> dict[str, Any] | None:
    with _lock:
        value = _load().get(str(persona_id or "").strip())
        return copy.deepcopy(value) if isinstance(value, dict) else None


def save_draft(persona_id: str, structured: dict[str, Any], *, base_version: int = 1) -> dict[str, Any]:
    key = str(persona_id or "").strip()
    if not key:
        raise ValueError("A persona id is required.")
    with _lock:
        drafts = _load()
        prior = drafts.get(key) if isinstance(drafts.get(key), dict) else {}
        revision = int(prior.get("draft_version", 0) or 0) + 1
        value = {
            "persona_id": key,
            "schema_version": SCHEMA_VERSION,
            "base_confirmed_version": max(1, int(base_version or 1)),
            "draft_version": revision,
            "structured": copy.deepcopy(structured),
            "updated_at": time.time(),
        }
        drafts[key] = value
        _save(drafts)
        return copy.deepcopy(value)


def delete_draft(persona_id: str) -> bool:
    key = str(persona_id or "").strip()
    with _lock:
        drafts = _load()
        existed = key in drafts
        drafts.pop(key, None)
        if existed:
            _save(drafts)
        return existed
