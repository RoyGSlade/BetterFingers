"""Pure Library domain semantics for Wave 3 (Gate 3).

This module is the reference for what each Library action *means*: pin,
duplicate, reopen, resend, restore, filter, delete, clear, audit. Every
function is a total, side-effect-free transformation over plain dicts --
no filesystem, no sqlite, no FastAPI, no threads, and no wall-clock reads.
Anything that needs "now" takes a ``now_iso`` argument from its caller so
tests stay deterministic and so the persistence layer (backend/stores/
drafts.py, history_store.py) remains the only place that actually decides
what time it is.

Nothing here mutates an argument. Every function that hands back a draft
returns a fresh dict, because the in-memory ``draft_queue`` and the
SQLite-backed archive both hold direct references to whatever a caller
passes around; a domain function that mutated in place could silently
corrupt state a caller thought was still the "before" copy (e.g. an audit
entry recorded before the change, or a response already sent to a client).

The five §1 provenance keys (``duplicated_from_id``, ``reopened_from_id``,
``revision_of_id``, ``restored_from_recording_id``, ``restored_from_draft_id``)
exist so History can answer "where did this come from" without guessing from
content. Exactly one is ever non-None on a record built by this module,
because a draft has exactly one origin story.
"""

from datetime import datetime

# --- statuses ---------------------------------------------------------------
# These mirror the status vocabulary server.py already writes into a draft's
# "status" field. They live here (rather than being re-derived ad hoc at each
# call site) so "is this in flight" / "is this sent" is answered identically
# everywhere -- library routes, the service layer, and these domain
# functions all import the same three sets instead of drifting.
PENDING_STATUSES = frozenset({"pending", "accepted", "send_interrupted", "failed", "declined"})
SENT_STATUSES = frozenset({"sent"})
IN_FLIGHT_STATUSES = frozenset({"sending"})

# Statuses server.py writes that are neither pending/sent/in-flight in the
# workflow sense above, but that real rows carry and a Library filter must
# still be able to select. Kept as their own sets (rather than folded into
# PENDING_STATUSES) because delete_decision/resend_plan/reopen semantics key
# off the three sets above and must not shift meaning just because the
# filter vocabulary grew. Verified against actual writers as of Wave 3:
#   "send_error" -- server.py:1228 (send attempt failed)
#   "error"      -- server.py:1985, 2013 (create_draft status="error")
#   "blocked"    -- server.py:1790 (no usable audio)
#   "scratch"    -- server.py:1752 (scratch capture)
TERMINAL_ERROR_STATUSES = frozenset({"send_error", "error", "blocked"})
DRAFT_ONLY_STATUSES = frozenset({"scratch"})
KNOWN_STATUSES = PENDING_STATUSES | SENT_STATUSES | IN_FLIGHT_STATUSES | TERMINAL_ERROR_STATUSES | DRAFT_ONLY_STATUSES

# The §1 additions, as {key: default}. normalize_draft_record() walks this
# dict rather than hardcoding key names twice (once here, once in the
# function body) so adding a future key is a one-line change.
LIBRARY_FIELD_DEFAULTS = {
    "pinned": False,
    "pinned_at": None,
    "duplicated_from_id": None,
    "reopened_from_id": None,
    "revision_of_id": None,
    "restored_from_recording_id": None,
    "restored_from_draft_id": None,
}


def normalize_draft_record(draft):
    """Return a copy of ``draft`` with every §1 key present at its default.

    Pre-Wave-3 records on disk have none of these keys (§1's read-time-
    defaulting migration rule: nothing rewrites old data just to add them).
    Every reader is expected to pass records through here before treating
    them as Wave-3-shaped, so a missing key never becomes a KeyError three
    layers up in a filter or a sort.

    Also repairs the pinned/pinned_at invariant: a record that is somehow
    ``pinned=False`` with a stale ``pinned_at`` gets that timestamp cleared,
    since "not pinned" must mean "no pin time" everywhere else in this
    module (sort_key, matches_filters). The inverse -- ``pinned=True`` with
    no ``pinned_at`` -- is left alone rather than inventing a timestamp: this
    function has no ``now_iso`` to stamp with, and a missing pin time is
    honestly "unknown", not "now".
    """
    result = dict(draft)
    for key, default in LIBRARY_FIELD_DEFAULTS.items():
        result.setdefault(key, default)
    if not result["pinned"]:
        result["pinned_at"] = None
    return result


def apply_pin(draft, pinned, now_iso):
    """Return a normalized copy of ``draft`` with ``pinned`` set.

    Pinning is idempotent: re-pinning an already-pinned draft must not bump
    ``pinned_at`` to a new timestamp, or every redundant "pin" click from a
    slow UI would keep reordering the pinned-first list. Only the
    False -> True transition stamps a fresh ``pinned_at``; True -> True
    preserves whatever was already there. Unpinning always clears it,
    matching the invariant normalize_draft_record repairs.
    """
    normalized = normalize_draft_record(draft)
    if pinned:
        if not normalized["pinned"]:
            normalized["pinned_at"] = now_iso
        normalized["pinned"] = True
    else:
        normalized["pinned"] = False
        normalized["pinned_at"] = None
    return normalized


# Send-state fields (server.py, not §1) that must never leak from one draft
# into a freshly built one. A duplicate/reopen/restore is a brand-new record
# that has never been sent, so it must start exactly like create_draft's
# output: no token, no outcome, nothing pending.
_SEND_STATE_RESET = {
    "pending_send": False,
    "send_result": None,
    "send_process_token": None,
    "send_outcome": None,
}

# Fields copied verbatim (or shallow-copied, for metadata) from the source
# draft into a build_duplicate/build_restore_from_draft result. This is the
# authoring content and context -- what was said and how -- as distinct from
# status/provenance/send-state, which the new record always sets fresh.
_CARRIED_CONTENT_FIELDS = (
    "raw_text", "final_text", "preset", "contact_id",
    "confidence", "transcription_result", "speech_signals",
)


def _fresh_pending_record(source, new_id, now_iso):
    """Shared skeleton for build_duplicate / build_restore_from_draft: a
    brand-new pending draft carrying over authoring content but none of the
    source's status, provenance, or send state."""
    result = {key: source.get(key) for key in _CARRIED_CONTENT_FIELDS}
    result["metadata"] = dict(source.get("metadata") or {})
    result.update(LIBRARY_FIELD_DEFAULTS)
    result.update(_SEND_STATE_RESET)
    result.update({
        "id": new_id,
        "created_at": now_iso,
        "status": "pending",
        "error": "",
        "gate_reasons": [],
    })
    return result


def build_duplicate(source, new_id, now_iso):
    """A NEW pending draft that copies content and authoring context from
    ``source``.

    A duplicate must never be able to present as sent history -- that would
    let a user "duplicate" a sent message and have it show up already
    marked delivered, without ever going through send. So status is forced
    to "pending" unconditionally, regardless of what ``source["status"]``
    was, and every send/delivery field is reset rather than copied.
    """
    result = _fresh_pending_record(source, new_id, now_iso)
    result["duplicated_from_id"] = source.get("id")
    return result


def build_restore_from_draft(source, new_id, now_iso):
    """Clone a recoverable draft's content into a fresh pending draft.

    Sets ``restored_from_draft_id`` rather than ``duplicated_from_id``:
    restore and duplicate are distinct provenance (one recovers something
    that was on its way out, the other forks something still live), and a
    reader tracing history needs to tell them apart.
    """
    result = _fresh_pending_record(source, new_id, now_iso)
    result["restored_from_draft_id"] = source.get("id")
    return result


def build_reopen_payload(source):
    """What Talk needs to load a selected draft for review.

    Read-only: this never creates a record and never mutates ``source``. It
    only tells the caller what state the source is in so the UI can decide
    whether editing it is even possible (``editable``) and whether an edit
    would have to fork a new record (``requires_new_record``) -- sent
    history is immutable, so editing a sent item always forks.
    """
    return {
        "source_id": source.get("id"),
        "raw_text": source.get("raw_text", ""),
        "final_text": source.get("final_text", ""),
        "preset": source.get("preset"),
        "contact_id": source.get("contact_id"),
        "status": source.get("status"),
        "created_at": source.get("created_at"),
        "editable": source.get("status") not in IN_FLIGHT_STATUSES,
        "requires_new_record": source.get("status") in SENT_STATUSES,
    }


def build_reopen_edit(source, new_id, now_iso, raw_text=None, final_text=None):
    """The record produced when the user edits a reopened item.

    Always a new pending draft -- the original historical entry is never
    mutated, so history stays an honest record of what was actually sent
    (or not). Which provenance key gets set depends on whether the source
    was already sent: sent history can only be forked (``reopened_from_id``),
    while a still-pending draft can be revised in place conceptually even
    though this always creates a new record (``revision_of_id``). Exactly
    one of the two is ever non-None, since a draft has one origin story.
    """
    result = _fresh_pending_record(source, new_id, now_iso)
    result["raw_text"] = raw_text if raw_text is not None else source.get("raw_text", "")
    result["final_text"] = final_text if final_text is not None else source.get("final_text", "")
    if source.get("status") in SENT_STATUSES:
        result["reopened_from_id"] = source.get("id")
    else:
        result["revision_of_id"] = source.get("id")
    return result


def resend_plan(source):
    """Resend is NOT a delivery primitive.

    There is deliberately no code path here that performs or authorizes an
    immediate send -- the only ``next_action`` this function ever emits is
    "reopen_for_review", so a resend always routes back through review and
    the ordinary delivery path rather than silently re-injecting text a
    user never re-confirmed. The single refusal case is a source that is
    still mid-send: resending something already in flight would race the
    active send.
    """
    if source.get("status") in IN_FLIGHT_STATUSES:
        return {"allowed": False, "reason": "send_in_flight", "next_action": "reopen_for_review"}
    return {"allowed": True, "reason": "", "next_action": "reopen_for_review"}


# --- filters -----------------------------------------------------------------
# NOTE: there is deliberately no "destination" filter. No draft record in
# this codebase has ever carried a destination field -- it exists only in
# unwired renderer preview markup (app/src/renderer) and must not be given a
# backend meaning by being accepted here. NOTE: there is deliberately no
# "contact" filter in Wave 3 either -- contacts are not qualified for Library
# filtering until Wave 5.
FILTER_FIELDS = frozenset({"persona", "date_from", "date_to", "status", "pinned", "query"})

_TRUE_STRINGS = {"true", "1", "yes"}
_FALSE_STRINGS = {"false", "0", "no"}


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE_STRINGS:
            return True
        if lowered in _FALSE_STRINGS:
            return False
    raise ValueError("invalid_pinned")


_END_OF_DAY_SUFFIX = "T23:59:59.999999"


def _parse_date_bound(value, *, end_of_day=False):
    """Validate and canonicalize one date_from/date_to bound.

    created_at is always a full ISO datetime, but a caller-supplied bound may
    be date-only ("2026-07-28"). A naive string compare of a date-only
    date_to against a full datetime silently excludes the whole day --
    "2026-07-28T04:20:00" > "2026-07-28" is True -- which breaks the
    contract's INCLUSIVE promise for the day a user most likely means.
    ``end_of_day`` (used for date_to only) expands a date-only bound to
    23:59:59.999999 so same-day items compare <=. Date-only-ness is detected
    as "parses via fromisoformat and has no 'T'", so a space-separated
    datetime like "2026-07-28 00:00" is ALSO treated as date-only and
    expanded to end-of-day. That widening is deliberate: an inclusive bound
    a user wrote with a space separator most plausibly means the whole day,
    and the ISO "T" form is available when midnight precision is intended.
    date_from needs no expansion -- a date-only lower bound already sorts
    before that day's datetimes -- but is still canonicalized (stripped) so
    both bounds are directly comparable strings.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid_date")
    cleaned = value.strip()
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        raise ValueError("invalid_date")
    is_date_only = "T" not in cleaned and parsed.time() == datetime.min.time()
    if end_of_day and is_date_only:
        return cleaned + _END_OF_DAY_SUFFIX
    return cleaned


def parse_filters(raw):
    """Validate and canonicalize a filter request.

    Unknown keys (including a fabricated ``destination`` or an
    unqualified ``contact``) are silently dropped rather than raising --
    dropping keeps the API additive-friendly for callers on an older
    client build, while raising is reserved for a KNOWN key holding a
    malformed value, which is a caller bug worth surfacing.
    """
    raw = raw or {}
    result = {}

    if "persona" in raw and raw["persona"] not in (None, ""):
        result["persona"] = str(raw["persona"]).strip()

    if "date_from" in raw and raw["date_from"] not in (None, ""):
        result["date_from"] = _parse_date_bound(raw["date_from"])

    if "date_to" in raw and raw["date_to"] not in (None, ""):
        result["date_to"] = _parse_date_bound(raw["date_to"], end_of_day=True)

    if "status" in raw and raw["status"] not in (None, ""):
        value = raw["status"]
        if isinstance(value, (list, tuple, set, frozenset)):
            statuses = [str(v).strip() for v in value]
        else:
            statuses = [str(value).strip()]
        for status in statuses:
            if status not in KNOWN_STATUSES:
                raise ValueError("invalid_status")
        result["status"] = statuses if len(statuses) > 1 else statuses[0]

    if "pinned" in raw and raw["pinned"] not in (None, ""):
        result["pinned"] = _parse_bool(raw["pinned"])

    if "query" in raw and raw["query"] is not None:
        query = str(raw["query"]).strip()
        if query:
            result["query"] = query

    return result


def matches_filters(draft, filters):
    """In-memory predicate matching the SQL pushdown history_store.query()
    performs. This is the authority for what a match means; the SQL is only
    a fast path to the same answer."""
    draft = normalize_draft_record(draft)
    filters = filters or {}

    # persona == draft["preset"] (the writing persona a draft was generated
    # with), not the SQL `profile` column (server.py:2687) -- that column is
    # the application/settings profile, a different concept entirely. An
    # earlier contract draft wrongly pointed the SQL pushdown at `profile`;
    # that has been corrected (Amendment A1). Do not "fix" this line to match
    # the old wrong spec.
    if "persona" in filters and draft.get("preset") != filters["persona"]:
        return False

    if "status" in filters:
        wanted = filters["status"]
        wanted_set = {wanted} if isinstance(wanted, str) else set(wanted)
        if draft.get("status") not in wanted_set:
            return False

    if "pinned" in filters and bool(draft.get("pinned")) != filters["pinned"]:
        return False

    created_at = draft.get("created_at") or ""
    if "date_from" in filters and created_at < filters["date_from"]:
        return False
    if "date_to" in filters and created_at > filters["date_to"]:
        return False

    if "query" in filters:
        needle = filters["query"].casefold()
        haystack = (draft.get("raw_text") or "") + "\n" + (draft.get("final_text") or "")
        if needle not in haystack.casefold():
            return False

    return True


def sort_key(draft):
    """Pinned-first, then newest-first by created_at, then id descending.

    REQUIRED call form: ``sorted(items, key=sort_key, reverse=True)``.
    Every field in this tuple compares in ascending order naturally
    (False < True, older ISO strings < newer, smaller ids < larger), so
    ``reverse=True`` is what turns that into pinned-first/newest-first/
    id-descending together. Sorting ascending (the default, easy to reach
    for by accident) silently inverts the whole Library -- unpinned-first,
    oldest-first -- so this is not a stylistic note, it's the difference
    between correct and backwards.
    """
    draft = normalize_draft_record(draft)
    return (
        bool(draft.get("pinned")),
        draft.get("created_at") or "",
        draft.get("id") or 0,
    )


# --- deletion + clear ---------------------------------------------------------
DELETE_KINDS = frozenset({"draft", "history_entry", "recording"})
CLEAR_SCOPES = frozenset({"drafts_and_history", "recordings", "all_conversation_data"})


def _content_free_preview(kind, target):
    """A delete/clear preview that carries shape, never substance: length
    counts and flags, never the raw_text/final_text/transcript itself."""
    text = (target.get("final_text") or target.get("raw_text") or "") if target else ""
    return {
        "kind": kind,
        "id": target.get("id") if target else None,
        "created_at": target.get("created_at") if target else None,
        "status": target.get("status") if target else None,
        "char_count": len(text),
        "has_recording": bool(target.get("recording_result") or target.get("has_recording")) if target else False,
    }


def delete_decision(kind, target, *, confirmed, in_flight_ids):
    """The single authority for whether a per-item delete may proceed.

    Ordering matters: an unknown kind is a caller bug and refused before
    anything else is even looked at; a missing target is checked before
    in-flight status because "already gone" must stay idempotent (safe to
    call twice) regardless of whether confirmation was supplied, rather
    than demanding a confirm flag just to discover there was nothing to
    confirm deleting.
    """
    if kind not in DELETE_KINDS:
        return {"action": "refuse", "error": "invalid_kind", "http_status": 400, "preview": None}

    if not confirmed:
        return {
            "action": "refuse",
            "error": "confirmation_required",
            "http_status": 400,
            "preview": _content_free_preview(kind, target),
        }

    if target is None:
        return {"action": "noop_absent", "error": None, "http_status": 200, "preview": None}

    in_flight_ids = in_flight_ids or set()
    if target.get("status") in IN_FLIGHT_STATUSES or target.get("id") in in_flight_ids:
        return {
            "action": "refuse",
            "error": "send_in_flight",
            "http_status": 409,
            "preview": _content_free_preview(kind, target),
        }

    return {"action": "delete", "error": None, "http_status": 200, "preview": _content_free_preview(kind, target)}


def clear_decision(scope, *, confirmed, counts):
    """Same shape as delete_decision for the three clear scopes.

    Each scope requires its own confirmation -- confirming
    "drafts_and_history" must never be treated as also confirming
    "recordings", since a user who cleared one category has said nothing
    about the other.
    """
    if scope not in CLEAR_SCOPES:
        return {"action": "refuse", "error": "invalid_scope", "http_status": 400, "preview": None}

    preview = {"scope": scope, "counts": dict(counts or {})}
    if not confirmed:
        return {"action": "refuse", "error": "confirmation_required", "http_status": 400, "preview": preview}

    return {"action": "clear", "error": None, "http_status": 200, "preview": preview}


_CONTENT_KEY_NAMES = {"raw_text", "final_text", "text", "transcript", "content"}


def audit_entry(*, action, kind, identity, outcome, now_iso, counts=None):
    """A content-free audit record.

    Callers must not pass message content in ``counts`` -- this is a log of
    what happened, not a copy of what was said. As a defensive backstop
    (belt-and-suspenders against a caller mistake, not the primary
    guarantee), any key in ``counts`` whose name matches a known
    content-shaped key is stripped before the entry is built.
    """
    safe_counts = {k: v for k, v in (counts or {}).items() if k not in _CONTENT_KEY_NAMES}
    return {
        "action": action,
        "kind": kind,
        "identity": identity,
        "outcome": outcome,
        "at": now_iso,
        "counts": safe_counts,
    }
