"""Tests for backend.services.library.LibraryService (Wave 3, contract §4).

Plain pytest against hand-rolled fakes for draft_store/history_store_mod/
recordings_mod -- no FastAPI, no numpy, no sqlite, no real filesystem. This
is a hard requirement: the sandbox's system python3 lacks fastapi/numpy, and
recordings.py imports both (numpy/scipy) at module level, so this file must
never import it. The fakes below reimplement just enough of each store's
documented shape (contract §3) to exercise LibraryService in isolation, and
were written without depending on the sibling w3-persistence worker's real
implementations landing.
"""

import copy
import re
import threading

import pytest

from backend.domain import library as domain
from backend.services.library import LibraryService

_VALID_REC_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
NOW = "2026-01-01T00:00:00+00:00"


def make_draft(id, status="pending", **overrides):
    draft = {
        "id": id,
        "raw_text": f"raw {id}",
        "final_text": f"final {id}",
        "preset": "True Janitor",
        "status": status,
        "metadata": {},
        "error": "",
        "gate_reasons": [],
        "confidence": {"score": None, "avg_logprob": None, "no_speech_prob": None},
        "transcription_result": None,
        "speech_signals": None,
        "contact_id": None,
        "pending_send": False,
        "send_result": None,
        "created_at": "2025-06-01T00:00:00+00:00",
    }
    draft.update(overrides)
    return draft


class FakeDraftStore:
    def __init__(self, drafts=None):
        self.draft_queue = list(drafts or [])
        self.draft_recordings = {}
        self.lock = threading.RLock()
        self.next_id = max([d["id"] for d in self.draft_queue], default=0) + 1
        self.save_calls = []

    def get_draft_by_id(self, draft_id):
        for d in self.draft_queue:
            if d["id"] == draft_id:
                return d
        return None

    def set_pinned(self, draft_id, pinned, save_fn=None):
        draft = self.get_draft_by_id(draft_id)
        if draft is None:
            return None
        updated = domain.apply_pin(draft, pinned, NOW)
        draft.clear()
        draft.update(updated)
        if save_fn is not None:
            save_fn(changed_draft_id=draft_id)
        return dict(draft)

    def delete_draft(self, draft_id, save_fn=None):
        for i, d in enumerate(self.draft_queue):
            if d["id"] == draft_id:
                del self.draft_queue[i]
                self.draft_recordings.pop(draft_id, None)
                if save_fn is not None:
                    save_fn(changed_draft_id=draft_id)
                return True
        return False

    def create_from_record(self, record, save_fn=None):
        draft = dict(record)
        draft["id"] = self.next_id
        self.next_id += 1
        self.draft_queue.append(draft)
        if save_fn is not None:
            save_fn(changed_draft_id=draft["id"])
        return dict(draft)


class RaisingDraftStore(FakeDraftStore):
    """A draft store that fails any test relying on resend to never mutate."""

    def set_pinned(self, *a, **k):
        raise AssertionError("resend must never write through set_pinned")

    def delete_draft(self, *a, **k):
        raise AssertionError("resend must never delete")

    def create_from_record(self, *a, **k):
        raise AssertionError("resend must never create a record")


class FakeHistoryStore:
    def __init__(self, records=None):
        self.records = [dict(r) for r in (records or [])]
        self.pin_calls = []
        self.query_calls = []
        self.get_calls = []
        self.cleared = False

    def set_pinned(self, draft_id, pinned, pinned_at):
        self.pin_calls.append((draft_id, pinned, pinned_at))
        for r in self.records:
            if r["id"] == draft_id:
                r["pinned"] = bool(pinned)
                r["pinned_at"] = pinned_at
                return True
        return False

    def delete_draft(self, draft_id):
        for i, r in enumerate(self.records):
            if r["id"] == draft_id:
                del self.records[i]
                return True
        return False

    def get(self, draft_id):
        self.get_calls.append(draft_id)
        for r in self.records:
            if r["id"] == draft_id:
                return dict(r)
        return None

    def query(self, filters, limit=50, offset=0):
        self.query_calls.append(dict(filters))
        matched = [r for r in self.records if domain.matches_filters(r, filters)]
        matched.sort(key=domain.sort_key, reverse=True)
        total = len(matched)
        page = matched[offset:offset + limit]
        return {"results": page, "total": total, "limit": limit, "offset": offset}

    def clear(self):
        self.records = []
        self.cleared = True
        return True


class FakeHistoryStoreNoGet:
    """A history store shaped like history_store_mod before Amendment A2
    landed -- no get(id) method at all, so LibraryService must fall back to
    its scanning lookup (via query()) rather than break. Deliberately does
    NOT inherit from FakeHistoryStore, so there is no risk of accidentally
    picking up a get() method through the class hierarchy."""

    def __init__(self, records=None):
        self.records = [dict(r) for r in (records or [])]
        self.query_calls = []

    def delete_draft(self, draft_id):
        for i, r in enumerate(self.records):
            if r["id"] == draft_id:
                del self.records[i]
                return True
        return False

    def query(self, filters, limit=50, offset=0):
        self.query_calls.append(dict(filters))
        matched = [r for r in self.records if domain.matches_filters(r, filters)]
        matched.sort(key=domain.sort_key, reverse=True)
        total = len(matched)
        page = matched[offset:offset + limit]
        return {"results": page, "total": total, "limit": limit, "offset": offset}


class FakeRecordings:
    def __init__(self, recordings=None):
        self.recordings = [dict(r) for r in (recordings or [])]
        self.deleted = []
        self.cleared = False
        self.filesystem_touched = False

    def is_valid_rec_id(self, rec_id):
        return bool(_VALID_REC_ID.match(str(rec_id or "")))

    def list_recordings(self):
        return list(self.recordings)

    def delete_recording(self, rec_id):
        self.filesystem_touched = True
        for i, r in enumerate(self.recordings):
            if r["id"] == rec_id:
                del self.recordings[i]
                self.deleted.append(rec_id)
                return True
        return False

    def clear_recordings(self):
        self.cleared = True
        count = len(self.recordings)
        self.recordings = []
        return count


def make_service(draft_store=None, history_store=None, recordings=None, audit=None,
                  in_flight_ids=None, now=NOW):
    ds = draft_store if draft_store is not None else FakeDraftStore()
    hs = history_store if history_store is not None else FakeHistoryStore()
    rec = recordings if recordings is not None else FakeRecordings()
    audit_log = audit if audit is not None else []
    service = LibraryService(
        draft_store=ds,
        history_store_mod=hs,
        recordings_mod=rec,
        save_fn=lambda changed_draft_id=None: ds.save_calls.append(changed_draft_id),
        in_flight_ids_fn=in_flight_ids or (lambda: set()),
        audit_sink=audit_log.append,
        now_fn=lambda: now,
    )
    return service, ds, hs, rec, audit_log


# --- pinning -----------------------------------------------------------------


def test_set_pinned_writes_through_both_stores_and_unpin_clears_pinned_at():
    draft = make_draft(1)
    ds = FakeDraftStore([draft])
    hs = FakeHistoryStore([dict(draft)])
    service, ds, hs, rec, audit = make_service(ds, hs)

    result = service.set_pinned(1, True)
    assert result["ok"] is True
    assert ds.get_draft_by_id(1)["pinned"] is True
    assert ds.get_draft_by_id(1)["pinned_at"] == NOW
    assert hs.records[0]["pinned"] is True
    assert hs.records[0]["pinned_at"] == NOW

    result = service.set_pinned(1, False)
    assert result["ok"] is True
    assert ds.get_draft_by_id(1)["pinned"] is False
    assert ds.get_draft_by_id(1)["pinned_at"] is None
    assert hs.records[0]["pinned"] is False
    assert hs.records[0]["pinned_at"] is None


def test_set_pinned_not_found_in_either_store():
    service, ds, hs, rec, audit = make_service()
    result = service.set_pinned(999, True)
    assert result == {"ok": False, "error": "not_found", "draft": None}


# --- deletion ------------------------------------------------------------------


def test_delete_draft_removes_queue_and_archive_row():
    ds = FakeDraftStore([make_draft(1)])
    hs = FakeHistoryStore([make_draft(1)])
    service, ds, hs, rec, audit = make_service(ds, hs)

    result = service.delete_item("draft", 1, confirmed=True)
    assert result == {"ok": True, "removed": True, "already_absent": False,
                       "preview": result["preview"]}
    assert ds.get_draft_by_id(1) is None
    assert hs.records == []


def test_delete_is_idempotent_second_call_is_noop_absent_not_an_error():
    ds = FakeDraftStore([make_draft(1)])
    service, ds, hs, rec, audit = make_service(ds)

    first = service.delete_item("draft", 1, confirmed=True)
    assert first["ok"] is True
    second = service.delete_item("draft", 1, confirmed=True)
    assert second == {"ok": True, "removed": False, "already_absent": True}


def test_delete_refuses_while_draft_is_in_flight():
    ds = FakeDraftStore([make_draft(1)])
    service, ds, hs, rec, audit = make_service(ds, in_flight_ids=lambda: {1})

    result = service.delete_item("draft", 1, confirmed=True)
    assert result["ok"] is False
    assert result["error"] == "send_in_flight"
    assert result["http_status"] == 409
    assert ds.get_draft_by_id(1) is not None  # nothing was actually removed


def test_delete_unconfirmed_returns_content_free_preview():
    ds = FakeDraftStore([make_draft(1, raw_text="secret raw", final_text="secret final")])
    service, ds, hs, rec, audit = make_service(ds)

    result = service.delete_item("draft", 1, confirmed=False)
    assert result["ok"] is False
    assert result["error"] == "confirmation_required"
    assert result["http_status"] == 400
    preview = result["preview"]
    assert "raw_text" not in preview
    assert "final_text" not in preview
    assert "secret" not in str(preview)
    assert ds.get_draft_by_id(1) is not None


def test_delete_recording_rejects_invalid_id_without_touching_filesystem():
    rec = FakeRecordings([{"id": "abc-123", "created_at": 1.0}])
    service, ds, hs, rec, audit = make_service(recordings=rec)

    result = service.delete_item("recording", "../../etc/passwd", confirmed=True)
    assert result == {"ok": False, "error": "invalid_id", "http_status": 400, "preview": None}
    assert rec.filesystem_touched is False


def test_delete_history_entry_uses_history_store_get_when_available():
    hs = FakeHistoryStore([make_draft(1)])
    service, ds, hs, rec, audit = make_service(history_store=hs)

    result = service.delete_item("history_entry", 1, confirmed=True)
    assert result["ok"] is True
    assert result["removed"] is True
    assert hs.get_calls == [1]
    assert hs.query_calls == []  # the scanning fallback must not have run
    assert hs.records == []


def test_delete_history_entry_falls_back_when_history_store_lacks_get():
    hs = FakeHistoryStoreNoGet([make_draft(1)])
    service, ds, hs, rec, audit = make_service(history_store=hs)

    result = service.delete_item("history_entry", 1, confirmed=True)
    assert result["ok"] is True
    assert result["removed"] is True
    assert len(hs.query_calls) >= 1  # the fallback scan did run
    assert hs.records == []


def test_delete_recording_valid_id():
    rec = FakeRecordings([{"id": "abc-123", "created_at": 1.0}])
    service, ds, hs, rec, audit = make_service(recordings=rec)

    result = service.delete_item("recording", "abc-123", confirmed=True)
    assert result["ok"] is True
    assert result["removed"] is True
    assert rec.recordings == []


# --- duplicate -----------------------------------------------------------------


def test_duplicate_creates_new_pending_draft_with_provenance():
    ds = FakeDraftStore([make_draft(1)])
    service, ds, hs, rec, audit = make_service(ds)

    result = service.duplicate(1)
    assert result["ok"] is True
    new_draft = result["draft"]
    assert new_draft["id"] != 1
    assert new_draft["status"] == "pending"
    assert new_draft["duplicated_from_id"] == 1


def test_duplicate_of_sent_draft_is_never_sent_shaped():
    ds = FakeDraftStore([make_draft(1, status="sent")])
    service, ds, hs, rec, audit = make_service(ds)

    result = service.duplicate(1)
    assert result["ok"] is True
    assert result["draft"]["status"] == "pending"


# --- reopen --------------------------------------------------------------------


def test_reopen_returns_payload_and_leaves_source_untouched():
    source = make_draft(1, status="sent")
    ds = FakeDraftStore([source])
    service, ds, hs, rec, audit = make_service(ds)
    before = copy.deepcopy(source)

    result = service.reopen(1)
    assert result["ok"] is True
    assert result["reopen"]["requires_new_record"] is True
    assert ds.get_draft_by_id(1) == before


def test_commit_reopen_edit_creates_new_record_and_leaves_original_intact():
    source = make_draft(1, status="sent")
    ds = FakeDraftStore([source])
    service, ds, hs, rec, audit = make_service(ds)
    before = copy.deepcopy(source)

    result = service.commit_reopen_edit(1, raw_text="edited raw", final_text="edited final")
    assert result["ok"] is True
    new_draft = result["draft"]
    assert new_draft["id"] != 1
    assert new_draft["status"] == "pending"
    assert new_draft["reopened_from_id"] == 1
    assert new_draft["raw_text"] == "edited raw"
    assert ds.get_draft_by_id(1) == before


# --- resend --------------------------------------------------------------------


def test_resend_routes_through_reopen_for_review_and_never_delivers():
    ds = RaisingDraftStore([make_draft(1, status="send_error")])
    service, ds, hs, rec, audit = make_service(ds)

    result = service.resend(1)
    assert result["ok"] is True
    assert result["resend"]["allowed"] is True
    assert result["resend"]["next_action"] == "reopen_for_review"
    assert result["reopen"]["source_id"] == 1


def test_resend_refuses_while_in_flight():
    ds = RaisingDraftStore([make_draft(1, status="sending")])
    service, ds, hs, rec, audit = make_service(ds)

    result = service.resend(1)
    assert result["ok"] is True
    assert result["resend"]["allowed"] is False
    assert result["resend"]["reason"] == "send_in_flight"


# --- restore -------------------------------------------------------------------


def test_restore_recording_calls_injected_retranscribe_fn_and_result_is_pending():
    service, ds, hs, rec, audit = make_service()
    calls = []

    def retranscribe(rec_id):
        calls.append(rec_id)
        return {"raw_text": "restored text", "final_text": "restored text"}

    result = service.restore_recording("abc-123", retranscribe)
    assert calls == ["abc-123"]
    assert result["ok"] is True
    assert result["draft"]["status"] == "pending"
    assert result["draft"]["restored_from_recording_id"] == "abc-123"


def test_restore_recording_invalid_id_never_calls_retranscribe():
    service, ds, hs, rec, audit = make_service()

    def retranscribe(rec_id):
        raise AssertionError("must not be called for an invalid id")

    result = service.restore_recording("../evil", retranscribe)
    assert result == {"ok": False, "error": "invalid_id"}


def test_restore_draft_from_recoverable_draft():
    ds = FakeDraftStore([make_draft(1, status="send_interrupted")])
    service, ds, hs, rec, audit = make_service(ds)

    result = service.restore_draft(1)
    assert result["ok"] is True
    assert result["draft"]["status"] == "pending"
    assert result["draft"]["restored_from_draft_id"] == 1
    assert result["draft"]["id"] != 1


# --- filters ---------------------------------------------------------------------


def test_search_canonicalizes_each_filter_and_reaches_history_store_query():
    hs = FakeHistoryStore()
    service, ds, hs, rec, audit = make_service(history_store=hs)

    service.search({"persona": "True Janitor", "status": "pending", "pinned": True,
                     "date_from": "2026-01-01", "date_to": "2026-01-01", "query": " hello "},
                    limit=10, offset=0)

    assert hs.query_calls[-1] == {
        "persona": "True Janitor",
        "status": "pending",
        "pinned": True,
        "date_from": "2026-01-01",
        "date_to": "2026-01-01T23:59:59.999999",
        "query": "hello",
    }


def test_search_invalid_filter_returns_structured_error_not_an_exception():
    service, ds, hs, rec, audit = make_service()
    result = service.search({"status": "not-a-real-status"}, limit=10, offset=0)
    assert result == {"ok": False, "error": "invalid_status"}


def test_search_returns_matching_results():
    matching = make_draft(1, pinned=True)
    other = make_draft(2, pinned=False)
    hs = FakeHistoryStore([matching, other])
    service, ds, hs, rec, audit = make_service(history_store=hs)

    result = service.search({"pinned": True}, limit=10, offset=0)
    assert result["ok"] is True
    assert [r["id"] for r in result["results"]] == [1]
    assert result["total"] == 1


# --- clear -----------------------------------------------------------------------


def test_clear_drafts_and_history_leaves_recordings_untouched():
    ds = FakeDraftStore([make_draft(1)])
    hs = FakeHistoryStore([make_draft(1)])
    rec = FakeRecordings([{"id": "r1", "created_at": 1.0}])
    service, ds, hs, rec, audit = make_service(ds, hs, rec)

    result = service.clear("drafts_and_history", confirmed=True)
    assert result["ok"] is True
    assert ds.draft_queue == []
    assert hs.records == []
    assert hs.cleared is True
    assert rec.recordings == [{"id": "r1", "created_at": 1.0}]
    assert rec.cleared is False


def test_clear_recordings_leaves_drafts_and_history_untouched():
    ds = FakeDraftStore([make_draft(1)])
    hs = FakeHistoryStore([make_draft(1)])
    rec = FakeRecordings([{"id": "r1", "created_at": 1.0}])
    service, ds, hs, rec, audit = make_service(ds, hs, rec)

    result = service.clear("recordings", confirmed=True)
    assert result["ok"] is True
    assert rec.recordings == []
    assert rec.cleared is True
    assert len(ds.draft_queue) == 1
    assert hs.cleared is False
    assert len(hs.records) == 1


def test_clear_all_conversation_data_clears_both():
    ds = FakeDraftStore([make_draft(1)])
    hs = FakeHistoryStore([make_draft(1)])
    rec = FakeRecordings([{"id": "r1", "created_at": 1.0}])
    service, ds, hs, rec, audit = make_service(ds, hs, rec)

    result = service.clear("all_conversation_data", confirmed=True)
    assert result["ok"] is True
    assert ds.draft_queue == []
    assert hs.cleared is True
    assert rec.cleared is True


def test_clear_unconfirmed_returns_counts_and_destroys_nothing():
    ds = FakeDraftStore([make_draft(1), make_draft(2)])
    hs = FakeHistoryStore([make_draft(1), make_draft(2)])
    rec = FakeRecordings([{"id": "r1", "created_at": 1.0}])
    service, ds, hs, rec, audit = make_service(ds, hs, rec)

    result = service.clear("all_conversation_data", confirmed=False)
    assert result["ok"] is False
    assert result["error"] == "confirmation_required"
    assert result["preview"]["counts"] == {"drafts": 2, "history_entries": 2, "recordings": 1}
    assert len(ds.draft_queue) == 2
    assert len(hs.records) == 2
    assert len(rec.recordings) == 1


def test_clear_scopes_require_independent_confirmation():
    ds = FakeDraftStore([make_draft(1)])
    hs = FakeHistoryStore([make_draft(1)])
    rec = FakeRecordings([{"id": "r1", "created_at": 1.0}])
    service, ds, hs, rec, audit = make_service(ds, hs, rec)

    # Confirming "recordings" must not also authorize "drafts_and_history".
    result = service.clear("recordings", confirmed=True)
    assert result["ok"] is True
    result = service.clear("drafts_and_history", confirmed=False)
    assert result["ok"] is False
    assert len(ds.draft_queue) == 1
    assert len(hs.records) == 1


# --- audit -------------------------------------------------------------------------


def test_every_mutating_action_produces_a_content_free_audit_entry():
    ds = FakeDraftStore([make_draft(1, raw_text="secret raw", final_text="secret final")])
    hs = FakeHistoryStore([make_draft(1)])
    service, ds, hs, rec, audit = make_service(ds, hs)

    service.set_pinned(1, True)
    service.delete_item("draft", 1, confirmed=True)

    assert len(audit) >= 2
    for entry in audit:
        assert set(entry.keys()) == {"action", "kind", "identity", "outcome", "at", "counts"}
        blob = str(entry)
        assert "secret" not in blob
        assert "raw_text" not in entry.get("counts", {})
        assert "final_text" not in entry.get("counts", {})


def test_reopen_read_only_produces_no_audit_entry():
    ds = FakeDraftStore([make_draft(1)])
    service, ds, hs, rec, audit = make_service(ds)

    service.reopen(1)
    assert audit == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
