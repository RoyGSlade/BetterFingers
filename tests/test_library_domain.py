"""Tests for backend.domain.library, the pure Wave 3 Library semantics module.

Plain pytest, no fixtures needed beyond simple dict literals -- every
function under test is a pure transformation, so each test just builds an
input dict, calls the function, and asserts on the result. now_iso is always
passed explicitly (never datetime.now()) so these tests are deterministic.
"""

import pytest

from backend.domain import library


def _draft(**overrides):
    """A minimal pre-Wave-3-shaped draft: none of the §1 keys present, since
    that is the realistic on-disk shape normalize_draft_record must handle."""
    base = {
        "id": 1,
        "raw_text": "hello",
        "final_text": "Hello.",
        "preset": "True Janitor",
        "status": "pending",
        "metadata": {"a": 1},
        "error": "",
        "gate_reasons": [],
        "confidence": {"score": 0.9, "avg_logprob": -0.1, "no_speech_prob": 0.0},
        "transcription_result": None,
        "speech_signals": None,
        "contact_id": None,
        "pending_send": False,
        "send_result": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


# --- normalize_draft_record --------------------------------------------------

def test_normalize_adds_all_defaults_to_a_pre_wave3_record():
    draft = _draft()
    original = dict(draft)

    result = library.normalize_draft_record(draft)

    for key, default in library.LIBRARY_FIELD_DEFAULTS.items():
        assert key in result
        assert result[key] == default
    assert draft == original  # never mutated


def test_normalize_repairs_pinned_false_with_stale_pinned_at():
    draft = _draft(pinned=False, pinned_at="2026-01-01T00:00:00+00:00")
    result = library.normalize_draft_record(draft)
    assert result["pinned"] is False
    assert result["pinned_at"] is None


def test_normalize_leaves_pinned_true_with_no_pinned_at_alone():
    draft = _draft(pinned=True, pinned_at=None)
    result = library.normalize_draft_record(draft)
    assert result["pinned"] is True
    assert result["pinned_at"] is None


# --- apply_pin ---------------------------------------------------------------

def test_apply_pin_stamps_pinned_at_on_first_pin():
    draft = _draft()
    result = library.apply_pin(draft, True, "2026-02-01T00:00:00+00:00")
    assert result["pinned"] is True
    assert result["pinned_at"] == "2026-02-01T00:00:00+00:00"


def test_apply_pin_is_idempotent_and_preserves_original_pinned_at():
    draft = _draft(pinned=True, pinned_at="2026-01-01T00:00:00+00:00")
    result = library.apply_pin(draft, True, "2026-02-01T00:00:00+00:00")
    assert result["pinned"] is True
    assert result["pinned_at"] == "2026-01-01T00:00:00+00:00"


def test_apply_pin_unpin_clears_pinned_at():
    draft = _draft(pinned=True, pinned_at="2026-01-01T00:00:00+00:00")
    result = library.apply_pin(draft, False, "2026-02-01T00:00:00+00:00")
    assert result["pinned"] is False
    assert result["pinned_at"] is None


# --- build_duplicate ----------------------------------------------------------

def test_build_duplicate_from_sent_source_is_pending():
    source = _draft(id=7, status="sent", pending_send=False, send_result={"ok": True})
    source["send_process_token"] = "tok"
    source["send_outcome"] = "sent"

    result = library.build_duplicate(source, new_id=8, now_iso="2026-03-01T00:00:00+00:00")

    assert result["status"] == "pending"
    assert result["duplicated_from_id"] == 7
    assert result["id"] == 8
    assert result["created_at"] == "2026-03-01T00:00:00+00:00"
    assert result["pending_send"] is False
    assert result["send_result"] is None
    assert result["send_process_token"] is None
    assert result["send_outcome"] is None
    assert result["pinned"] is False
    assert result["pinned_at"] is None
    assert result["error"] == ""
    assert result["gate_reasons"] == []
    assert result["raw_text"] == source["raw_text"]
    assert result["final_text"] == source["final_text"]


def test_build_duplicate_does_not_mutate_source():
    source = _draft(id=7, status="sent")
    original = dict(source)
    library.build_duplicate(source, new_id=8, now_iso="2026-03-01T00:00:00+00:00")
    assert source == original


def test_build_duplicate_shallow_copies_metadata():
    source = _draft(id=7, metadata={"nested": {"x": 1}})
    result = library.build_duplicate(source, new_id=8, now_iso="2026-03-01T00:00:00+00:00")
    assert result["metadata"] == source["metadata"]
    assert result["metadata"] is not source["metadata"]


# --- build_reopen_payload -----------------------------------------------------

def test_build_reopen_payload_does_not_mutate_source():
    source = _draft(id=3, status="sent")
    original = dict(source)
    library.build_reopen_payload(source)
    assert source == original


def test_build_reopen_payload_sent_requires_new_record():
    source = _draft(id=3, status="sent")
    payload = library.build_reopen_payload(source)
    assert payload["requires_new_record"] is True
    assert payload["editable"] is True


def test_build_reopen_payload_sending_is_not_editable():
    source = _draft(id=3, status="sending")
    payload = library.build_reopen_payload(source)
    assert payload["editable"] is False
    assert payload["requires_new_record"] is False


def test_build_reopen_payload_pending_does_not_require_new_record():
    source = _draft(id=3, status="pending")
    payload = library.build_reopen_payload(source)
    assert payload["requires_new_record"] is False
    assert payload["editable"] is True


# --- build_reopen_edit ---------------------------------------------------------

def test_build_reopen_edit_from_sent_sets_reopened_from_id():
    source = _draft(id=5, status="sent")
    original = dict(source)

    result = library.build_reopen_edit(source, new_id=9, now_iso="2026-04-01T00:00:00+00:00",
                                        raw_text="new raw", final_text="New final.")

    assert source == original  # untouched
    assert result["status"] == "pending"
    assert result["reopened_from_id"] == 5
    assert result["revision_of_id"] is None
    assert result["raw_text"] == "new raw"
    assert result["final_text"] == "New final."


def test_build_reopen_edit_from_pending_sets_revision_of_id():
    source = _draft(id=5, status="pending")
    result = library.build_reopen_edit(source, new_id=9, now_iso="2026-04-01T00:00:00+00:00",
                                        raw_text=None, final_text=None)
    assert result["revision_of_id"] == 5
    assert result["reopened_from_id"] is None
    # exactly one non-None
    assert (result["revision_of_id"] is None) != (result["reopened_from_id"] is None)


def test_build_reopen_edit_defaults_text_to_source_when_none():
    source = _draft(id=5, status="pending", raw_text="orig raw", final_text="orig final")
    result = library.build_reopen_edit(source, new_id=9, now_iso="2026-04-01T00:00:00+00:00",
                                        raw_text=None, final_text=None)
    assert result["raw_text"] == "orig raw"
    assert result["final_text"] == "orig final"


# --- build_restore_from_draft --------------------------------------------------

def test_build_restore_from_draft_sets_restored_id_and_not_duplicated():
    source = _draft(id=11, status="failed")
    result = library.build_restore_from_draft(source, new_id=12, now_iso="2026-05-01T00:00:00+00:00")
    assert result["restored_from_draft_id"] == 11
    assert result["duplicated_from_id"] is None
    assert result["status"] == "pending"


# --- resend_plan ---------------------------------------------------------------

def test_resend_plan_refuses_while_in_flight():
    source = _draft(status="sending")
    plan = library.resend_plan(source)
    assert plan["allowed"] is False
    assert plan["reason"] == "send_in_flight"
    assert plan["next_action"] == "reopen_for_review"


@pytest.mark.parametrize("status", ["sent", "pending", "failed", "declined", "send_interrupted"])
def test_resend_plan_allowed_for_non_in_flight_statuses(status):
    source = _draft(status=status)
    plan = library.resend_plan(source)
    assert plan["allowed"] is True
    assert plan["next_action"] == "reopen_for_review"


@pytest.mark.parametrize("status", library.PENDING_STATUSES | library.SENT_STATUSES | library.IN_FLIGHT_STATUSES)
def test_resend_plan_next_action_is_never_anything_but_reopen_for_review(status):
    plan = library.resend_plan(_draft(status=status))
    assert plan["next_action"] == "reopen_for_review"


# --- parse_filters --------------------------------------------------------------

def test_parse_filters_canonicalizes_each_valid_field():
    result = library.parse_filters({
        "persona": "  True Janitor  ",
        "date_from": "2026-01-01",
        "date_to": "2026-02-01",
        "status": "sent",
        "pinned": "true",
        "query": "  hello  ",
    })
    assert result["persona"] == "True Janitor"
    assert result["date_from"] == "2026-01-01"
    assert result["date_to"] == "2026-02-01T23:59:59.999999"  # date-only date_to expands to end-of-day (inclusive)
    assert result["status"] == "sent"
    assert result["pinned"] is True
    assert result["query"] == "hello"


def test_parse_filters_drops_destination():
    result = library.parse_filters({"destination": "someone@example.com", "persona": "x"})
    assert "destination" not in result
    assert result["persona"] == "x"


def test_parse_filters_drops_contact():
    result = library.parse_filters({"contact": "abc123", "persona": "x"})
    assert "contact" not in result
    assert result["persona"] == "x"


def test_parse_filters_empty_query_is_absent():
    result = library.parse_filters({"query": "   "})
    assert "query" not in result


def test_parse_filters_invalid_status_raises_machine_code():
    with pytest.raises(ValueError, match="invalid_status"):
        library.parse_filters({"status": "not_a_real_status"})


def test_parse_filters_invalid_date_raises_machine_code():
    with pytest.raises(ValueError, match="invalid_date"):
        library.parse_filters({"date_from": "not-a-date"})


def test_parse_filters_invalid_pinned_raises_machine_code():
    with pytest.raises(ValueError, match="invalid_pinned"):
        library.parse_filters({"pinned": "maybe"})


def test_parse_filters_status_accepts_a_collection():
    result = library.parse_filters({"status": ["sent", "pending"]})
    assert set(result["status"]) == {"sent", "pending"}


@pytest.mark.parametrize("status", ["send_error", "error", "blocked", "scratch"])
def test_parse_filters_accepts_real_but_non_workflow_statuses(status):
    """These are statuses server.py actually writes (send_error, error,
    blocked, scratch) that don't belong to PENDING/SENT/IN_FLIGHT -- they
    must still be filterable, not rejected as invalid_status."""
    result = library.parse_filters({"status": status})
    assert result["status"] == status


def test_parse_filters_date_only_date_to_is_inclusive_of_that_day():
    result = library.parse_filters({"date_to": "2026-07-28"})
    assert result["date_to"] > "2026-07-28T23:59:59"
    # A same-day full-datetime created_at must compare <= the canonicalized bound.
    assert "2026-07-28T23:00:00+00:00" <= result["date_to"]


def test_parse_filters_full_datetime_date_to_is_untouched():
    result = library.parse_filters({"date_to": "2026-07-28T10:00:00+00:00"})
    assert result["date_to"] == "2026-07-28T10:00:00+00:00"


def test_matches_filters_date_only_date_to_includes_same_day_item():
    """This must FAIL against the pre-fix implementation: a naive string
    compare of a full datetime against a bare date excludes the whole day."""
    draft = _draft(created_at="2026-07-28T23:00:00+00:00")
    filters = library.parse_filters({"date_to": "2026-07-28"})
    assert library.matches_filters(draft, filters)


def test_matches_filters_date_range_spans_full_day_at_both_edges():
    early = _draft(id=1, created_at="2026-07-28T00:00:01+00:00")
    late = _draft(id=2, created_at="2026-07-28T23:59:58+00:00")
    filters = library.parse_filters({"date_from": "2026-07-28", "date_to": "2026-07-28"})
    assert library.matches_filters(early, filters)
    assert library.matches_filters(late, filters)


# --- matches_filters --------------------------------------------------------------

def test_matches_filters_persona():
    draft = _draft(preset="Coach")
    assert library.matches_filters(draft, {"persona": "Coach"})
    assert not library.matches_filters(draft, {"persona": "True Janitor"})


def test_matches_filters_status():
    draft = _draft(status="sent")
    assert library.matches_filters(draft, {"status": "sent"})
    assert library.matches_filters(draft, {"status": ["sent", "pending"]})
    assert not library.matches_filters(draft, {"status": "pending"})


def test_matches_filters_pinned():
    draft = _draft(pinned=True, pinned_at="2026-01-01T00:00:00+00:00")
    assert library.matches_filters(draft, {"pinned": True})
    assert not library.matches_filters(draft, {"pinned": False})


def test_matches_filters_date_range():
    draft = _draft(created_at="2026-02-15T00:00:00+00:00")
    assert library.matches_filters(draft, {"date_from": "2026-02-01", "date_to": "2026-03-01"})
    assert not library.matches_filters(draft, {"date_from": "2026-03-01"})
    assert not library.matches_filters(draft, {"date_to": "2026-01-01"})


def test_matches_filters_query_case_insensitive_raw_and_final():
    raw_hit = _draft(raw_text="Something ABOUT dogs", final_text="unrelated")
    final_hit = _draft(raw_text="unrelated", final_text="Something about CATS")
    miss = _draft(raw_text="nothing", final_text="here")

    assert library.matches_filters(raw_hit, {"query": "about dogs"})
    assert library.matches_filters(final_hit, {"query": "about cats"})
    assert not library.matches_filters(miss, {"query": "about dogs"})


def test_matches_filters_combined():
    draft = _draft(preset="Coach", status="sent", pinned=True, pinned_at="2026-01-01T00:00:00+00:00",
                    created_at="2026-02-15T00:00:00+00:00", raw_text="hello world", final_text="")
    filters = {
        "persona": "Coach",
        "status": "sent",
        "pinned": True,
        "date_from": "2026-02-01",
        "date_to": "2026-03-01",
        "query": "hello",
    }
    assert library.matches_filters(draft, filters)
    assert not library.matches_filters(draft, {**filters, "persona": "Other"})


# --- sort_key --------------------------------------------------------------------

def test_sort_key_pinned_sorts_before_unpinned_regardless_of_created_at():
    old_pinned = _draft(id=1, pinned=True, pinned_at="2020-01-01T00:00:00+00:00",
                         created_at="2020-01-01T00:00:00+00:00")
    new_unpinned = _draft(id=2, pinned=False, created_at="2026-01-01T00:00:00+00:00")

    ordered = sorted([new_unpinned, old_pinned], key=library.sort_key, reverse=True)
    assert ordered[0]["id"] == 1


def test_sort_key_newest_first_within_same_pin_state():
    a = _draft(id=1, created_at="2020-01-01T00:00:00+00:00")
    b = _draft(id=2, created_at="2026-01-01T00:00:00+00:00")
    ordered = sorted([a, b], key=library.sort_key, reverse=True)
    assert ordered[0]["id"] == 2


def test_sort_key_required_call_form_yields_pinned_and_newest_first_together():
    """The documented call form is sorted(items, key=sort_key, reverse=True).
    Sorting ascending would silently invert the whole Library."""
    old_pinned = _draft(id=1, pinned=True, pinned_at="2020-01-01T00:00:00+00:00",
                         created_at="2020-01-01T00:00:00+00:00")
    new_pinned = _draft(id=2, pinned=True, pinned_at="2021-01-01T00:00:00+00:00",
                         created_at="2021-01-01T00:00:00+00:00")
    new_unpinned = _draft(id=3, pinned=False, created_at="2026-01-01T00:00:00+00:00")

    ordered = sorted([old_pinned, new_unpinned, new_pinned], key=library.sort_key, reverse=True)
    assert [d["id"] for d in ordered] == [2, 1, 3]


# --- delete_decision --------------------------------------------------------------

def test_delete_decision_invalid_kind():
    result = library.delete_decision("not_a_kind", _draft(), confirmed=True, in_flight_ids=set())
    assert result["action"] == "refuse"
    assert result["error"] == "invalid_kind"
    assert result["http_status"] == 400


def test_delete_decision_confirmation_required_has_content_free_preview():
    target = _draft(raw_text="secret raw", final_text="secret final")
    result = library.delete_decision("draft", target, confirmed=False, in_flight_ids=set())
    assert result["action"] == "refuse"
    assert result["error"] == "confirmation_required"
    assert result["http_status"] == 400
    preview = result["preview"]
    assert "raw_text" not in preview
    assert "final_text" not in preview
    assert "secret" not in str(preview)


def test_delete_decision_noop_absent_for_missing_target():
    result = library.delete_decision("draft", None, confirmed=True, in_flight_ids=set())
    assert result["action"] == "noop_absent"
    assert result["http_status"] == 200


def test_delete_decision_refuses_in_flight_via_status():
    target = _draft(id=4, status="sending")
    result = library.delete_decision("draft", target, confirmed=True, in_flight_ids=set())
    assert result["action"] == "refuse"
    assert result["error"] == "send_in_flight"
    assert result["http_status"] == 409


def test_delete_decision_refuses_in_flight_via_in_flight_ids():
    target = _draft(id=4, status="pending")
    result = library.delete_decision("draft", target, confirmed=True, in_flight_ids={4})
    assert result["action"] == "refuse"
    assert result["error"] == "send_in_flight"


def test_delete_decision_ordinary_delete():
    target = _draft(id=4, status="pending", raw_text="secret", final_text="also secret")
    result = library.delete_decision("draft", target, confirmed=True, in_flight_ids=set())
    assert result["action"] == "delete"
    assert result["http_status"] == 200
    preview = result["preview"]
    assert "secret" not in str(preview)
    assert preview["id"] == 4


# --- clear_decision --------------------------------------------------------------

def test_clear_decision_unknown_scope():
    result = library.clear_decision("not_a_scope", confirmed=True, counts={})
    assert result["action"] == "refuse"
    assert result["error"] == "invalid_scope"
    assert result["http_status"] == 400


def test_clear_decision_unconfirmed_carries_counts():
    counts = {"drafts": 3, "history": 10}
    result = library.clear_decision("drafts_and_history", confirmed=False, counts=counts)
    assert result["action"] == "refuse"
    assert result["error"] == "confirmation_required"
    assert result["preview"]["counts"] == counts


def test_clear_decision_confirming_one_scope_does_not_authorize_another():
    library.clear_decision("drafts_and_history", confirmed=True, counts={"drafts": 1})
    # A fresh call for a different scope must still require its own confirmation.
    result = library.clear_decision("recordings", confirmed=False, counts={"recordings": 2})
    assert result["action"] == "refuse"
    assert result["error"] == "confirmation_required"


def test_clear_decision_confirmed_clears():
    result = library.clear_decision("all_conversation_data", confirmed=True, counts={"drafts": 1})
    assert result["action"] == "clear"
    assert result["http_status"] == 200


# --- audit_entry --------------------------------------------------------------

def test_audit_entry_shape():
    entry = library.audit_entry(action="delete", kind="draft", identity=5, outcome="ok",
                                 now_iso="2026-06-01T00:00:00+00:00", counts={"n": 1})
    assert entry == {
        "action": "delete",
        "kind": "draft",
        "identity": 5,
        "outcome": "ok",
        "at": "2026-06-01T00:00:00+00:00",
        "counts": {"n": 1},
    }


def test_audit_entry_strips_content_shaped_keys():
    entry = library.audit_entry(
        action="delete", kind="draft", identity=5, outcome="ok",
        now_iso="2026-06-01T00:00:00+00:00",
        counts={"n": 1, "raw_text": "secret", "final_text": "secret", "text": "secret",
                "transcript": "secret", "content": "secret"},
    )
    assert entry["counts"] == {"n": 1}
