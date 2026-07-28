"""Library service: orchestration for the Wave 3 Library backend (contract §4).

Every decision this file needs -- is this in flight, may I delete, what does
a duplicate/reopen/restore look like, what does a filter mean, is a clear
confirmed -- comes from ``backend.domain.library``. This module only
coordinates the stores a decision has to act on: the in-memory draft queue
(``draft_store``), the SQLite archive (``history_store_mod``), retained
audio (``recordings_mod``), and durable persistence (``save_fn``). "Now"
enters the system here; the domain layer never reads the clock, so every
``now_iso`` passed to a domain builder comes from ``now_fn`` (or its default,
a UTC ISO-8601 instant -- the same shape ``DraftStore.create_draft`` already
stamps ``created_at`` with).

All dependencies are constructor-injected so this class can be exercised
against fakes/stubs in a unit test, with no live FastAPI app, database, or
filesystem involved.
"""

from datetime import datetime, timezone

from backend.domain import library as domain


def _default_now():
    return datetime.now(timezone.utc).isoformat()


class LibraryService:
    def __init__(self, draft_store, history_store_mod, recordings_mod, save_fn,
                 in_flight_ids_fn, audit_sink=None, now_fn=None):
        self._draft_store = draft_store
        self._history_store = history_store_mod
        self._recordings = recordings_mod
        self._save_fn = save_fn
        self._in_flight_ids_fn = in_flight_ids_fn
        self._audit_sink = audit_sink
        self._now_fn = now_fn or _default_now

    def _now(self):
        return self._now_fn()

    def _audit(self, *, action, kind, identity, outcome, counts=None):
        if self._audit_sink is None:
            return
        entry = domain.audit_entry(
            action=action, kind=kind, identity=identity, outcome=outcome,
            now_iso=self._now(), counts=counts,
        )
        self._audit_sink(entry)

    # -- pin -----------------------------------------------------------------

    def set_pinned(self, draft_id, pinned):
        """Write through to BOTH the live queue and the archive.

        Reports a partial write honestly (``ok: False, error:
        "partial_write"``) rather than claiming success on a half-write, and
        ``not_found`` only when the id exists in neither store.
        """
        pinned = bool(pinned)
        now_iso = self._now()
        queue_draft = self._draft_store.set_pinned(draft_id, pinned, save_fn=self._save_fn)
        archive_ok = self._history_store.set_pinned(draft_id, pinned, now_iso if pinned else None)

        if queue_draft is None and not archive_ok:
            self._audit(action="pin", kind="draft", identity=draft_id, outcome="not_found",
                        counts={"pinned": pinned})
            return {"ok": False, "error": "not_found", "draft": None}

        if queue_draft is not None and not archive_ok:
            self._audit(action="pin", kind="draft", identity=draft_id, outcome="partial_write",
                        counts={"pinned": pinned})
            return {"ok": False, "error": "partial_write", "draft": queue_draft}

        self._audit(action="pin", kind="draft", identity=draft_id, outcome="ok",
                    counts={"pinned": pinned})
        return {"ok": True, "error": None, "draft": queue_draft}

    # -- delete ----------------------------------------------------------------

    def _fetch_history_record(self, identity):
        """Single-record lookup against the archive.

        history_store_mod.get(id) (Amendment A2) is the primary path: a
        single indexed lookup, never a scan. The fallback below exists only
        so this service isn't blocked by w3-persistence's landing order and
        this file's tests stay independent of it -- it must never become
        the routine path once get() is universally present, so it's reached
        via getattr (an AttributeError-shaped "get is missing entirely"),
        not a try/except around the call (which would also swallow a
        genuine sqlite failure inside get() and mistake it for "absent").
        """
        try:
            identity = int(identity)
        except (TypeError, ValueError):
            return None

        get_fn = getattr(self._history_store, "get", None)
        if get_fn is not None:
            return get_fn(identity)

        # Fallback: scan a full query() page. O(n), correct, temporary.
        probe = self._history_store.query({}, limit=1, offset=0)
        total = probe.get("total", 0) if isinstance(probe, dict) else 0
        if total <= 0:
            return None
        full = self._history_store.query({}, limit=total, offset=0)
        for record in full.get("results", []):
            if record.get("id") == identity:
                return record
        return None

    def _resolve_delete_target(self, kind, identity):
        if kind == "draft":
            return self._draft_store.get_draft_by_id(identity)
        if kind == "history_entry":
            return self._fetch_history_record(identity)
        if kind == "recording":
            for record in self._recordings.list_recordings():
                if record.get("id") == identity:
                    return record
            return None
        return None

    def _perform_delete(self, kind, identity):
        if kind == "draft":
            queue_removed = self._draft_store.delete_draft(identity, save_fn=self._save_fn)
            archive_removed = self._history_store.delete_draft(identity)
            return queue_removed or archive_removed
        if kind == "history_entry":
            return self._history_store.delete_draft(identity)
        if kind == "recording":
            return self._recordings.delete_recording(identity)
        return False

    def delete_item(self, kind, identity, confirmed):
        """Resolve the target FIRST, then let delete_decision decide.

        A recording identity is validated before anything else touches the
        filesystem: an invalid rec_id is a 400 ``invalid_id``, never a 404
        (which would imply a well-formed id that just wasn't found) and
        never a call into ``recordings_mod`` at all (the path-traversal
        guard recordings.py already enforces must never even be reached with
        a hostile id).
        """
        if kind == "recording" and not self._recordings.is_valid_rec_id(identity):
            self._audit(action="delete", kind=kind, identity=identity, outcome="invalid_id")
            return {"ok": False, "error": "invalid_id", "http_status": 400, "preview": None}

        target = self._resolve_delete_target(kind, identity)
        decision = domain.delete_decision(
            kind, target, confirmed=confirmed, in_flight_ids=self._in_flight_ids_fn(),
        )
        action = decision["action"]

        if action == "refuse":
            self._audit(action="delete", kind=kind, identity=identity, outcome=decision["error"])
            return {
                "ok": False, "error": decision["error"],
                "http_status": decision["http_status"], "preview": decision["preview"],
            }

        if action == "noop_absent":
            self._audit(action="delete", kind=kind, identity=identity, outcome="already_absent")
            return {"ok": True, "removed": False, "already_absent": True}

        removed = self._perform_delete(kind, identity)
        counts = {"char_count": decision["preview"]["char_count"]} if decision["preview"] else None
        if not removed:
            self._audit(action="delete", kind=kind, identity=identity, outcome="write_failed", counts=counts)
            return {"ok": False, "error": "write_failed", "http_status": 500, "preview": decision["preview"]}

        self._audit(action="delete", kind=kind, identity=identity, outcome="deleted", counts=counts)
        return {"ok": True, "removed": True, "already_absent": False, "preview": decision["preview"]}

    # -- duplicate / reopen / resend / restore ----------------------------------
    #
    # These four all follow the same shape: resolve the source, ask the
    # domain layer to build the new record (with a placeholder id -- the
    # store's create_from_record assigns and overwrites the real id while
    # holding its lock, so no id race is possible), then place it via
    # draft_store.create_from_record. The domain builder decides what the
    # new record IS; the store only places it (contract §3).

    _PLACEHOLDER_ID = 0

    def duplicate(self, draft_id):
        source = self._draft_store.get_draft_by_id(draft_id)
        if source is None:
            self._audit(action="duplicate", kind="draft", identity=draft_id, outcome="not_found")
            return {"ok": False, "error": "not_found"}

        record = domain.build_duplicate(source, self._PLACEHOLDER_ID, self._now())
        new_draft = self._draft_store.create_from_record(record, save_fn=self._save_fn)
        self._audit(action="duplicate", kind="draft", identity=draft_id, outcome="ok",
                    counts={"new_id": new_draft.get("id")})
        return {"ok": True, "draft": new_draft}

    def reopen(self, draft_id):
        """Read-only: builds a payload, never a record. Not audited -- nothing
        was mutated or created."""
        source = self._draft_store.get_draft_by_id(draft_id)
        if source is None:
            return {"ok": False, "error": "not_found"}
        return {"ok": True, "reopen": domain.build_reopen_payload(source)}

    def commit_reopen_edit(self, draft_id, raw_text=None, final_text=None):
        source = self._draft_store.get_draft_by_id(draft_id)
        if source is None:
            self._audit(action="reopen_commit", kind="draft", identity=draft_id, outcome="not_found")
            return {"ok": False, "error": "not_found"}

        record = domain.build_reopen_edit(
            source, self._PLACEHOLDER_ID, self._now(), raw_text=raw_text, final_text=final_text,
        )
        new_draft = self._draft_store.create_from_record(record, save_fn=self._save_fn)
        provenance = "reopened_from_id" if record.get("reopened_from_id") is not None else "revision_of_id"
        self._audit(action="reopen_commit", kind="draft", identity=draft_id, outcome="ok",
                    counts={"new_id": new_draft.get("id"), "provenance": provenance})
        return {"ok": True, "draft": new_draft}

    def resend(self, draft_id):
        # NOTE: resend never triggers delivery. This method only returns a
        # plan (domain.resend_plan, whose only next_action is
        # "reopen_for_review") plus a reopen payload -- there is no branch
        # anywhere in this file that sends, injects, or schedules a send.
        # Delivery only ever happens through the ordinary review -> send
        # path, initiated separately by the caller acting on next_action.
        source = self._draft_store.get_draft_by_id(draft_id)
        if source is None:
            return {"ok": False, "error": "not_found"}

        plan = domain.resend_plan(source)
        payload = domain.build_reopen_payload(source)
        self._audit(action="resend", kind="draft", identity=draft_id,
                    outcome="allowed" if plan["allowed"] else plan["reason"])
        return {"ok": True, "resend": plan, "reopen": payload}

    def restore_recording(self, rec_id, retranscribe_fn):
        """Restore a retained recording by re-running it through the injected
        ``retranscribe_fn`` -- never the transcriber module itself, so this
        service stays free of any audio/model dependency."""
        if not self._recordings.is_valid_rec_id(rec_id):
            return {"ok": False, "error": "invalid_id"}

        transcript = retranscribe_fn(rec_id)
        if transcript is None:
            self._audit(action="restore", kind="recording", identity=rec_id, outcome="not_found")
            return {"ok": False, "error": "not_found"}

        # A transcription result is content, not a draft: shape it into the
        # same fields build_restore_from_draft carries over, with no id (so
        # the result's restored_from_draft_id -- source.get("id") -- comes
        # back None, distinct from the restored_from_recording_id set below).
        pseudo_source = {
            "raw_text": transcript.get("raw_text", ""),
            "final_text": transcript.get("final_text", ""),
            "preset": transcript.get("preset"),
            "contact_id": transcript.get("contact_id"),
            "confidence": transcript.get("confidence"),
            "transcription_result": transcript.get("transcription_result"),
            "speech_signals": transcript.get("speech_signals"),
            "metadata": transcript.get("metadata"),
        }
        record = domain.build_restore_from_draft(pseudo_source, self._PLACEHOLDER_ID, self._now())
        record["restored_from_recording_id"] = rec_id
        new_draft = self._draft_store.create_from_record(record, save_fn=self._save_fn)
        self._audit(action="restore", kind="recording", identity=rec_id, outcome="ok",
                    counts={"new_id": new_draft.get("id")})
        return {"ok": True, "draft": new_draft}

    def restore_draft(self, draft_id):
        """Clone a recoverable draft. Looks in the live queue first, then the
        archive, since a "recoverable" draft may already have aged out of
        the bounded in-memory queue while still being present in history."""
        source = self._draft_store.get_draft_by_id(draft_id)
        if source is None:
            source = self._fetch_history_record(draft_id)
        if source is None:
            self._audit(action="restore", kind="draft", identity=draft_id, outcome="not_found")
            return {"ok": False, "error": "not_found"}

        record = domain.build_restore_from_draft(source, self._PLACEHOLDER_ID, self._now())
        new_draft = self._draft_store.create_from_record(record, save_fn=self._save_fn)
        self._audit(action="restore", kind="draft", identity=draft_id, outcome="ok",
                    counts={"new_id": new_draft.get("id")})
        return {"ok": True, "draft": new_draft}

    # -- search ------------------------------------------------------------------

    def search(self, filters, limit=50, offset=0):
        try:
            parsed = domain.parse_filters(filters)
        except ValueError as exc:
            code = str(exc) or "invalid_filter"
            return {"ok": False, "error": code}

        result = self._history_store.query(parsed, limit=limit, offset=offset)
        return {
            "ok": True,
            "results": result.get("results", []),
            "total": result.get("total", 0),
            "limit": result.get("limit", limit),
            "offset": result.get("offset", offset),
        }

    # -- clear ---------------------------------------------------------------

    def _gather_clear_counts(self, scope):
        """Counted BEFORE anything is cleared, so an unconfirmed preview
        reports what would be destroyed rather than what already was."""
        counts = {}
        if scope in ("drafts_and_history", "all_conversation_data"):
            counts["drafts"] = len(self._draft_store.draft_queue)
            history_total = self._history_store.query({}, limit=1, offset=0)
            counts["history_entries"] = history_total.get("total", 0) if isinstance(history_total, dict) else 0
        if scope in ("recordings", "all_conversation_data"):
            counts["recordings"] = len(self._recordings.list_recordings())
        return counts

    def _perform_clear(self, scope):
        # Independent per category -- "drafts_and_history" must never touch
        # retained recordings, and "recordings" must never touch drafts or
        # history. Only "all_conversation_data" does both. Neither branch
        # ever reaches voices, models, or profiles.
        if scope in ("drafts_and_history", "all_conversation_data"):
            with self._draft_store.lock:
                self._draft_store.draft_queue.clear()
                self._draft_store.draft_recordings.clear()
            self._save_fn()
            self._history_store.clear()
        if scope in ("recordings", "all_conversation_data"):
            self._recordings.clear_recordings()

    def clear(self, scope, confirmed):
        counts = self._gather_clear_counts(scope)
        decision = domain.clear_decision(scope, confirmed=confirmed, counts=counts)

        if decision["action"] == "refuse":
            self._audit(action="clear", kind=scope, identity=scope, outcome=decision["error"], counts=counts)
            return {
                "ok": False, "error": decision["error"],
                "http_status": decision["http_status"], "preview": decision["preview"],
            }

        self._perform_clear(scope)
        self._audit(action="clear", kind=scope, identity=scope, outcome="cleared", counts=counts)
        return {"ok": True, "preview": decision["preview"]}
