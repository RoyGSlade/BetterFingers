"""Privacy-preserving, consent-gated persona example learning (F2.6).

A persona's few-shot examples (schema: ``{"raw": str, "out": str}``, same
shape as ``llm_engine.default_persona()["few_shot"]``) teach it a user's
preferred rewrite style. This service owns a *separate* on-disk store for
those learned examples rather than writing into personas.yaml directly, so
it never needs to touch llm_engine.py/backend/services/personas.py: persona
names are used as opaque lookup keys, compatible with any persona schema
vintage (v1 flat prompt strings or v2 dicts) without caring about their shape.

Design constraints (F2.6):
  * No background/silent learning: ``add_example`` requires the caller to
    pass ``consent=True`` on that exact call. There is no persisted "this
    persona has consent" flag to go stale or be forgotten — every add is an
    explicit, one-shot decision made by the caller (e.g. a UI confirmation).
  * Deterministic canonical dedupe: an example's id is a hash of its
    whitespace-normalized (raw, out) pair, so re-adding the same content
    (even with incidental whitespace differences) is recognized as a
    duplicate rather than stored twice.
  * A configurable hard cap per persona; once reached, the oldest example is
    evicted (FIFO) to make room for the new one.
  * Reads never touch the file more than once per call and always return
    copies, so callers can't mutate store internals by reference.
  * Persistence reuses store_migration's versioned-load + atomic-write
    discipline (corrupt files are quarantined, never silently dropped;
    writes are staged-then-renamed so a failure never corrupts the previous
    good file). Every mutation re-reads from disk first — there is no
    in-memory cache — so a write failure leaves the next read seeing exactly
    the last good on-disk state.
  * No message content is ever logged; failures are reported back to the
    caller as structured results, not printed.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Optional

from store_migration import load_versioned_store, write_atomic

# Schema history:
#   v1 (legacy/pre-service): {"personas": {name: [{"raw": .., "out": ..}, ...]}}
#     -- a bare list of few-shot-shaped dicts per persona, no ids/metadata.
#   v2 (current): {"personas": {name: {"examples": [{"id", "raw", "out",
#     "created_at"}, ...]}}}
SCHEMA_VERSION = 2
DEFAULT_CAP = 50


def _empty_store() -> dict:
    return {"personas": {}}


def _canon(text: str) -> str:
    """Whitespace-normalize for canonical comparison: strip + collapse runs."""
    return " ".join(str(text or "").split())


def _compute_id(raw: str, out: str) -> str:
    digest = hashlib.sha256()
    digest.update(_canon(raw).encode("utf-8"))
    digest.update(b"\x00")
    digest.update(_canon(out).encode("utf-8"))
    return digest.hexdigest()[:16]


def _coerce_examples(raw_list) -> list:
    """Defensively coerce any list-ish value into valid example dicts,
    dropping anything malformed rather than raising. Recomputes an id for
    any entry missing one (or carrying a blank one) so legacy/hand-edited
    data always ends up with a deterministic id."""
    examples = []
    seen_ids = set()
    if not isinstance(raw_list, list):
        return examples
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("raw", "") or "").strip()
        out = str(item.get("out", "") or "").strip()
        if not raw or not out:
            continue
        cid = str(item.get("id", "") or "").strip() or _compute_id(raw, out)
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        examples.append({
            "id": cid,
            "raw": raw,
            "out": out,
            "created_at": str(item.get("created_at", "") or ""),
        })
    return examples


def _migrate_v1_to_v2(data: dict) -> dict:
    """v1 stored a bare list of {"raw","out"} dicts per persona (matching the
    persona.few_shot schema exactly, with no wrapper/metadata). Wrap each into
    the v2 {"examples": [...]} shape, assigning deterministic ids."""
    raw_personas = data.get("personas") if isinstance(data, dict) else None
    personas = {}
    if isinstance(raw_personas, dict):
        for name, value in raw_personas.items():
            key = str(name or "").strip()
            if not key:
                continue
            personas[key] = {"examples": _coerce_examples(value)}
    return {"personas": personas}


def _normalize_store(data: dict) -> dict:
    """Final defensive pass applied after load/migration: guarantees the
    returned shape is always well-formed regardless of what was on disk."""
    raw_personas = data.get("personas") if isinstance(data, dict) else None
    personas = {}
    if isinstance(raw_personas, dict):
        for name, value in raw_personas.items():
            key = str(name or "").strip()
            if not key:
                continue
            if isinstance(value, dict):
                examples = _coerce_examples(value.get("examples"))
            elif isinstance(value, list):
                examples = _coerce_examples(value)
            else:
                examples = []
            personas[key] = {"examples": examples}
    return {"schema_version": SCHEMA_VERSION, "personas": personas}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PersonaLearningStore:
    """Consent-gated storage for learned per-persona few-shot examples.

    ``path`` should always be passed explicitly in tests (a tmp path) — the
    default touches the real user profile via ``utils.get_user_data_path()``,
    which is the OOM/cross-test-pollution trap this repo already learned to
    avoid (see tests/conftest.py).
    """

    def __init__(self, path: Optional[str] = None, cap: int = DEFAULT_CAP):
        self._path = path
        self.cap = max(1, int(cap))
        self._lock = threading.RLock()

    @property
    def path(self) -> str:
        if self._path is None:
            from utils import get_user_data_path
            import os
            self._path = os.path.join(get_user_data_path(), "persona_learning.json")
        return self._path

    def _load(self) -> dict:
        data, _report = load_versioned_store(
            self.path, SCHEMA_VERSION, {1: _migrate_v1_to_v2},
            default_factory=_empty_store, parse=json.loads,
        )
        return _normalize_store(data)

    def _save(self, data: dict) -> None:
        write_atomic(self.path, json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))

    @staticmethod
    def _key(persona_name) -> str:
        return str(persona_name or "").strip()

    # --- mutation -------------------------------------------------------

    def add_example(self, persona_name, raw, out, consent: bool = False) -> dict:
        """Add a learned example. Requires ``consent=True`` on this exact
        call — there is no persisted consent flag; every add is an explicit,
        one-shot decision by the caller. Duplicates (by canonical content) are
        recognized and reported, not stored twice. Once ``self.cap`` examples
        are stored for a persona, the oldest is evicted (FIFO) to make room."""
        name = self._key(persona_name)
        if not name:
            return {"ok": False, "error": "invalid_persona_name"}
        if not consent:
            return {"ok": False, "error": "consent_required",
                     "message": "Explicit consent is required to add a learning example."}
        raw_s = str(raw or "").strip()
        out_s = str(out or "").strip()
        if not raw_s or not out_s:
            return {"ok": False, "error": "empty_example"}

        cid = _compute_id(raw_s, out_s)
        with self._lock:
            data = self._load()
            entry = data["personas"].setdefault(name, {"examples": []})
            existing_ids = {e["id"] for e in entry["examples"]}
            if cid in existing_ids:
                return {"ok": True, "duplicate": True, "id": cid, "evicted_id": None}

            evicted_id = None
            if len(entry["examples"]) >= self.cap:
                evicted_id = entry["examples"].pop(0)["id"]  # oldest-first eviction

            entry["examples"].append({
                "id": cid, "raw": raw_s, "out": out_s, "created_at": _now_iso(),
            })
            try:
                self._save(data)
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "message": str(exc)}
            return {"ok": True, "duplicate": False, "id": cid, "evicted_id": evicted_id}

    def delete_example(self, persona_name, example_id) -> dict:
        """Delete a single learned example by id."""
        name = self._key(persona_name)
        with self._lock:
            data = self._load()
            entry = data["personas"].get(name)
            if not entry:
                return {"ok": True, "deleted": False}
            before = len(entry["examples"])
            entry["examples"] = [e for e in entry["examples"] if e["id"] != example_id]
            if len(entry["examples"]) == before:
                return {"ok": True, "deleted": False}
            try:
                self._save(data)
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "message": str(exc)}
            return {"ok": True, "deleted": True}

    def clear_persona(self, persona_name) -> dict:
        """Privacy clear: delete every learned example for one persona. The
        persona's key is dropped, not blacklisted — a later ``add_example``
        with fresh consent recreates it, so this clear is reversible."""
        name = self._key(persona_name)
        with self._lock:
            data = self._load()
            existed = bool(data["personas"].get(name, {}).get("examples"))
            data["personas"].pop(name, None)
            try:
                self._save(data)
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "message": str(exc)}
            return {"ok": True, "cleared": existed}

    def clear_all(self) -> dict:
        """Privacy clear: delete every learned example for every persona."""
        with self._lock:
            data = _normalize_store(_empty_store())
            try:
                self._save(data)
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "message": str(exc)}
            return {"ok": True}

    # --- inspection -------------------------------------------------------

    def list_personas(self) -> list:
        """Names of personas that currently have at least one learned example."""
        with self._lock:
            data = self._load()
            return sorted(name for name, entry in data["personas"].items() if entry["examples"])

    def list_examples(self, persona_name) -> list:
        """Copies of every learned example for a persona, in insertion order."""
        name = self._key(persona_name)
        with self._lock:
            data = self._load()
            entry = data["personas"].get(name)
            if not entry:
                return []
            return [dict(e) for e in entry["examples"]]

    def get_example(self, persona_name, example_id) -> Optional[dict]:
        for example in self.list_examples(persona_name):
            if example["id"] == example_id:
                return example
        return None

    def to_few_shot(self, persona_name) -> list:
        """Every learned example for a persona, projected into the exact
        ``{"raw": str, "out": str}`` shape ``llm_engine``'s persona.few_shot
        schema expects — for callers that want to feed learned examples into
        a persona's prompt construction."""
        return [{"raw": e["raw"], "out": e["out"]} for e in self.list_examples(persona_name)]
