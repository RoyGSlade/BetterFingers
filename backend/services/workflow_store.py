"""Persistent store for approved launcher workflows and their run history
(Wave 9, D-0011).

Storage mirrors ``backend.stores.app_profiles``: one versioned JSON file under
the unified data root (``utils.get_user_data_path()`` →
``app_paths.resolve_base()``, so ``BETTERFINGERS_DATA_DIR`` is honoured), loaded
lazily, written atomically, every mutation re-reading from disk first so a failed
write leaves the next read seeing the last good state. Reads are migration-safe:
``load_versioned_store`` handles version drift and quarantines a corrupt file
rather than taking the feature down with it, and ``_coerce_record`` degrades a
hand-edited record field by field instead of discarding the store.

THREE PROPERTIES THIS FILE EXISTS TO GUARANTEE.

*Saving is not approving.* A workflow is written to disk with
``approved=False``, and saving a workflow that already existed clears its
approval whenever the steps changed. Editing step 3 of an approved workflow and
having it stay approved would mean the user approved a preview that no longer
describes what runs.

*Approval is bound to the exact preview.* ``approve`` records the preview lines
the user actually read, and ``can_run`` refuses when the current preview differs
from them. That covers the case nobody clicks through: the workflow is
untouched, but the application it names was re-confirmed with a different launch
method, so the approved words and the real behaviour have quietly diverged.

*Enabled and approved are separate.* A workflow can be saved disabled (the
default) and enabled later; an enabled workflow that has never been approved
still cannot run. Collapsing the two would make "save it for now" and "let a
spoken phrase launch this" the same click.

RUN HISTORY HOLDS NO SPEECH. A history entry carries the workflow id, a
timestamp, the run status and one status **code** per step — the vocabulary in
``backend.services.action_validator.STEP_STATUS_CODES`` and nothing else. Not
the phrase that triggered it, not the transcript around it, not an error string
from a launcher (which routinely quotes a path, and a path is personal). The
sanitiser below enforces that rather than trusting callers, and
``tests/test_workflow_store.py`` asserts a representative set of prose fields is
dropped.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Optional

from backend.domain.actions import (
    MAX_NAME_LEN,
    compile_workflow,
    normalize_workflow_id,
)
from backend.services.action_validator import (
    RUN_STATUS_CODES,
    STATUS_FAILED,
    STEP_STATUS_CODES,
)
from store_migration import load_versioned_store, write_atomic

# Schema history:
#   v1 (current): {"schema_version": 1, "workflows": {id: <record>},
#                  "history": [<run>]}
SCHEMA_VERSION = 1

# The COMPLETE field set of a stored record: the v1 workflow document plus the
# three pieces of state the document itself must not carry (a workflow someone
# exports and a friend imports must arrive unapproved and disabled).
RECORD_FIELDS = (
    "schema_version",
    "id",
    "name",
    "trigger_phrases",
    "steps",
    "enabled",
    "approved",
    "approved_preview",
    "updated_at",
)

# The COMPLETE field set of a history entry. No free text anywhere.
RUN_FIELDS = ("workflow_id", "at", "status", "completed", "total", "steps")

DEFAULT_CAP = 50
DEFAULT_HISTORY_CAP = 100
MAX_PREVIEW_LINE_LEN = 240


def _empty_store() -> dict:
    return {"workflows": {}, "history": []}


def _now() -> float:
    return time.time()


def _clean_preview(value) -> list:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(line)[:MAX_PREVIEW_LINE_LEN] for line in value][:64]


def _coerce_record(raw) -> Optional[dict]:
    """One stored record -> a valid record, or None if it has no usable id.

    Runs the stored body back through ``compile_workflow``: a file somebody
    hand-edited to add a ``shell`` step is not a file this store will hand to a
    runner. A record that no longer compiles is dropped entirely rather than
    partially repaired, because a partially repaired workflow still carries the
    user's approval flag for steps they never saw.
    """
    if not isinstance(raw, dict):
        return None
    result = compile_workflow({k: raw.get(k) for k in ("id", "name", "trigger_phrases", "steps")})
    if not result.ok or not (result.workflow or {}).get("id"):
        return None
    record = dict(result.workflow)
    record["enabled"] = bool(raw.get("enabled", False))
    record["approved"] = bool(raw.get("approved", False))
    record["approved_preview"] = _clean_preview(raw.get("approved_preview"))
    # An approval with no recorded preview is not an approval this store can
    # check, so it is not one it keeps.
    if not record["approved_preview"]:
        record["approved"] = False
    try:
        record["updated_at"] = float(raw.get("updated_at") or 0.0)
    except (TypeError, ValueError):
        record["updated_at"] = 0.0
    return record


def _coerce_run(raw) -> Optional[dict]:
    """One history entry, reduced to codes. Anything else is discarded."""
    if not isinstance(raw, dict):
        return None
    workflow_id = normalize_workflow_id(raw.get("workflow_id"))
    if not workflow_id:
        return None
    status = str(raw.get("status") or "").strip().lower()
    if status not in RUN_STATUS_CODES:
        return None
    steps = []
    for item in raw.get("steps") or []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("status") or "").strip().lower()
        if code not in STEP_STATUS_CODES:
            code = STATUS_FAILED
        try:
            number = int(item.get("step_number", len(steps) + 1))
        except (TypeError, ValueError):
            number = len(steps) + 1
        # action is a fixed vocabulary word; target is deliberately NOT kept --
        # it can be a folder path, and a path names a person's directories.
        action = str(item.get("action") or "")[:64]
        steps.append({"step_number": number, "action": action, "status": code})
    try:
        at = float(raw.get("at") or 0.0)
    except (TypeError, ValueError):
        at = 0.0
    try:
        completed = int(raw.get("completed") or 0)
        total = int(raw.get("total") or len(steps))
    except (TypeError, ValueError):
        completed, total = 0, len(steps)
    return {
        "workflow_id": workflow_id,
        "at": at,
        "status": status,
        "completed": max(0, completed),
        "total": max(0, total),
        "steps": steps,
    }


def _normalize_store(data, history_cap: int = DEFAULT_HISTORY_CAP) -> dict:
    workflows = {}
    raw_workflows = (data or {}).get("workflows")
    if isinstance(raw_workflows, dict):
        items = raw_workflows.values()
    elif isinstance(raw_workflows, list):
        items = raw_workflows
    else:
        items = []
    for item in items:
        record = _coerce_record(item)
        if record:
            workflows[record["id"]] = record

    history = []
    for item in (data or {}).get("history") or []:
        run = _coerce_run(item)
        if run:
            history.append(run)
    history = history[-history_cap:]

    return {"schema_version": SCHEMA_VERSION, "workflows": workflows, "history": history}


class WorkflowStore:
    """Approved launcher workflows on disk, plus their code-only run history.

    ``path`` should always be passed explicitly in tests — the default touches
    the real user profile via ``utils.get_user_data_path()``, the
    cross-test-pollution trap this repo already learned to avoid.
    """

    def __init__(self, path: Optional[str] = None, cap: int = DEFAULT_CAP,
                 history_cap: int = DEFAULT_HISTORY_CAP):
        self._path = path
        self.cap = max(1, int(cap))
        self.history_cap = max(1, int(history_cap))
        self._lock = threading.RLock()

    @property
    def path(self) -> str:
        if self._path is None:
            import os
            from utils import get_user_data_path
            self._path = os.path.join(get_user_data_path(), "launcher_workflows.json")
        return self._path

    def _load(self) -> dict:
        data, _report = load_versioned_store(
            self.path, SCHEMA_VERSION, {},
            default_factory=_empty_store, parse=json.loads,
        )
        return _normalize_store(data, self.history_cap)

    def _save(self, data: dict) -> None:
        write_atomic(self.path, json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))

    # --- inspection -------------------------------------------------------

    def list_workflows(self) -> list:
        with self._lock:
            stored = self._load()["workflows"]
        return [stored[wid] for wid in sorted(stored)]

    def get(self, workflow_id) -> Optional[dict]:
        wid = normalize_workflow_id(workflow_id)
        if not wid:
            return None
        with self._lock:
            record = self._load()["workflows"].get(wid)
        return dict(record) if record else None

    def history(self, workflow_id=None, limit: int = 20) -> list:
        wid = normalize_workflow_id(workflow_id) if workflow_id else ""
        with self._lock:
            runs = self._load()["history"]
        if wid:
            runs = [run for run in runs if run["workflow_id"] == wid]
        return list(reversed(runs[-max(1, int(limit)):]))

    def find_by_phrase(self, phrase) -> Optional[dict]:
        """Exact trigger-phrase lookup for the voice router.

        Exact, not fuzzy, and not substring: a fuzzy match here is a workflow
        launching because a sentence happened to sound like its trigger. The
        conservative-parser rule from ``voice_commands.py`` applies with more
        force to something that opens applications.
        """
        from voice_commands import normalize_workflow_phrase

        needle = normalize_workflow_phrase(phrase)
        if not needle:
            return None
        for record in self.list_workflows():
            if needle in record.get("trigger_phrases", []):
                return record
        return None

    # --- mutation ---------------------------------------------------------

    def save(self, payload, enabled: bool = False) -> dict:
        """Create or replace a workflow. Always lands **unapproved**.

        Returns the store's usual structured result. A payload that does not
        compile is refused with the refusals attached, so the caller can show
        the user exactly which step BetterFingers will not perform — an error
        code alone would leave the builder saying "invalid" about a workflow
        whose only problem is one line.
        """
        result = compile_workflow(payload)
        if not result.ok:
            return {
                "ok": False,
                "error": "refused",
                "refusals": [r.to_dict() for r in result.refusals],
                "message": "BetterFingers will not save this workflow as written.",
            }

        workflow = result.workflow
        with self._lock:
            data = self._load()
            existing = data["workflows"].get(workflow["id"])
            if existing is None and len(data["workflows"]) >= self.cap:
                return {"ok": False, "error": "cap_reached",
                        "message": f"You already have {self.cap} saved workflows."}

            # Editing the steps revokes the approval. Editing only the name or
            # the trigger phrases does not: the preview the user approved still
            # describes exactly what will run.
            keep_approval = bool(
                existing
                and existing.get("approved")
                and existing.get("steps") == workflow["steps"]
            )
            record = {
                **workflow,
                "enabled": bool(enabled),
                "approved": keep_approval,
                "approved_preview": list(existing.get("approved_preview", [])) if keep_approval else [],
                "updated_at": _now(),
            }
            data["workflows"][record["id"]] = record
            try:
                self._save(data)
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "message": str(exc)}
            return {"ok": True, "workflow": dict(record),
                    "dropped_fields": list(result.dropped_fields)}

    def approve(self, workflow_id, preview_lines) -> dict:
        """Record that the user read **these exact lines** and said yes."""
        wid = normalize_workflow_id(workflow_id)
        lines = _clean_preview(preview_lines)
        if not wid:
            return {"ok": False, "error": "invalid_id"}
        if not lines:
            return {"ok": False, "error": "empty_preview",
                    "message": "There is nothing to approve — the preview is empty."}
        with self._lock:
            data = self._load()
            record = data["workflows"].get(wid)
            if record is None:
                return {"ok": False, "error": "not_found"}
            record["approved"] = True
            record["approved_preview"] = lines
            record["updated_at"] = _now()
            try:
                self._save(data)
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "message": str(exc)}
            return {"ok": True, "workflow": dict(record)}

    def set_enabled(self, workflow_id, enabled: bool) -> dict:
        wid = normalize_workflow_id(workflow_id)
        if not wid:
            return {"ok": False, "error": "invalid_id"}
        with self._lock:
            data = self._load()
            record = data["workflows"].get(wid)
            if record is None:
                return {"ok": False, "error": "not_found"}
            record["enabled"] = bool(enabled)
            record["updated_at"] = _now()
            try:
                self._save(data)
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "message": str(exc)}
            return {"ok": True, "workflow": dict(record)}

    def delete(self, workflow_id) -> dict:
        wid = normalize_workflow_id(workflow_id)
        if not wid:
            return {"ok": False, "error": "invalid_id"}
        with self._lock:
            data = self._load()
            existed = data["workflows"].pop(wid, None) is not None
            if not existed:
                return {"ok": True, "deleted": False}
            try:
                self._save(data)
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "message": str(exc)}
            return {"ok": True, "deleted": True}

    # --- the run gate -----------------------------------------------------

    def can_run(self, workflow_id, current_preview_lines) -> dict:
        """May this workflow run *right now*? ``{"ok": bool, "reason": str}``.

        Fail closed at every branch. The last one is the interesting one: an
        approved workflow whose current preview no longer matches the approved
        text is refused, because the only honest reading of that state is that
        the user approved something else.
        """
        record = self.get(workflow_id)
        if record is None:
            return {"ok": False, "error": "not_found",
                    "reason": "That workflow no longer exists."}
        if not record.get("enabled"):
            return {"ok": False, "error": "disabled",
                    "reason": "That workflow is saved but turned off."}
        if not record.get("approved"):
            return {"ok": False, "error": "not_approved",
                    "reason": "That workflow has not been approved yet, so it cannot run."}
        current = _clean_preview(current_preview_lines)
        if current != record.get("approved_preview"):
            return {"ok": False, "error": "preview_changed",
                    "reason": "What this workflow would do has changed since you approved "
                              "it. Review the new steps and approve them before it runs."}
        return {"ok": True, "workflow": record}

    def record_run(self, workflow_id, summary) -> dict:
        """Append one run to history — status codes only, never speech."""
        wid = normalize_workflow_id(workflow_id)
        if not wid:
            return {"ok": False, "error": "invalid_id"}
        run = _coerce_run({
            "workflow_id": wid,
            "at": _now(),
            "status": (summary or {}).get("status"),
            "completed": (summary or {}).get("completed"),
            "total": (summary or {}).get("total"),
            "steps": (summary or {}).get("steps"),
        })
        if run is None:
            return {"ok": False, "error": "invalid_summary"}
        with self._lock:
            data = self._load()
            data["history"] = (data["history"] + [run])[-self.history_cap:]
            try:
                self._save(data)
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "message": str(exc)}
            return {"ok": True, "run": run}

    def clear_history(self) -> dict:
        with self._lock:
            data = self._load()
            data["history"] = []
            try:
                self._save(data)
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "message": str(exc)}
            return {"ok": True}

    def clear_all(self) -> dict:
        """Privacy clear. Both halves: the workflows name applications this
        person runs and the folders they keep work in, and the history records
        when they ran them. See the ``launcher_workflows`` data category."""
        with self._lock:
            try:
                self._save(_normalize_store(_empty_store(), self.history_cap))
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "message": str(exc)}
            return {"ok": True}
