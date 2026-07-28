# Wave 3 — Library backend domain contract

Authoritative interface spec for Wave 3 (Gate 3). Written by `sup-library`
before implementation so the three worker tasks can be built against fixed
signatures. **Implementers must not change a signature in this document
without reporting a `bug` upward first.**

Scope is backend domain semantics only. No UI wiring (that is Wave 4). No git
mutation. `server.py` is integration-owned: the only permitted `server.py`
change is documented in §8 and is applied by the director, not by a worker.

---

## 1. Draft record additions

A draft is a plain `dict` living in `DraftStore.draft_queue`, mirrored whole
into `history_store` (the `data` JSON column). Wave 3 adds these keys:

| Key | Type | Default | Meaning |
|---|---|---|---|
| `pinned` | `bool` | `False` | User pinned this item in the Library. |
| `pinned_at` | `str \| None` | `None` | ISO-8601 UTC instant of the most recent pin. `None` whenever `pinned` is `False`. |
| `duplicated_from_id` | `int \| None` | `None` | Set on a draft created by Duplicate. |
| `reopened_from_id` | `int \| None` | `None` | Set on a draft created by editing a reopened historical entry. |
| `revision_of_id` | `int \| None` | `None` | Set when the new draft is a revision of a still-pending draft rather than a fork of history. |
| `restored_from_recording_id` | `str \| None` | `None` | Set on a draft created by restoring a retained recording. |
| `restored_from_draft_id` | `int \| None` | `None` | Set on a draft created by restoring a recoverable draft. |

**Migration rule: read-time defaulting, no destructive rewrite.** Records
written before Wave 3 will not have these keys. Every reader goes through
`normalize_draft_record()` (§2). Nothing rewrites `draft_history.json` or the
SQLite `data` blobs solely to add defaults; the keys materialize the next time
a record is saved for an unrelated reason. Old data must load unchanged.

**SQLite columns.** `history_store` gains `pinned INTEGER NOT NULL DEFAULT 0`
and `pinned_at TEXT` via the existing `PRAGMA table_info` + `ALTER TABLE`
back-compat pattern already used for the `data` column. These columns exist so
pinned filtering and pinned-first ordering can be pushed into SQL; the `data`
JSON stays the source of truth for the record body.

## 2. `backend/domain/library.py` — pure semantics, no I/O

No filesystem, no sqlite, no FastAPI, no threads. Every function is a pure
transformation over dicts. This module is the reference for what each Library
action *means*.

> **Amendment A1 (sup-library, after review of w3-domain).** The status
> vocabulary below was originally under-specified and had to be widened; the
> `persona` filter mapping in §3 was outright WRONG in the first revision. Both
> corrections are binding. See §3 and the amendment notes inline.

```python
# --- statuses -------------------------------------------------------------
# These must cover EVERY status server.py actually writes, because
# parse_filters rejects an unknown status and a status the store really
# contains must stay filterable. Verified against server.py: "sending"
# (l.1177), "send_interrupted" (l.1204), "sent" (l.1222), "send_error"
# (l.1228), "accepted" (l.3996), "declined" (l.4012), "pending" (l.936/4236),
# "scratch" (l.1752), "blocked" (l.1790), "error" (l.1985/2013).
PENDING_STATUSES: frozenset[str]        # {"pending", "accepted", "send_interrupted", "failed", "declined"}
SENT_STATUSES: frozenset[str]           # {"sent"}
IN_FLIGHT_STATUSES: frozenset[str]      # {"sending"}
TERMINAL_ERROR_STATUSES: frozenset[str] # {"send_error", "error", "blocked"}
DRAFT_ONLY_STATUSES: frozenset[str]     # {"scratch"}
KNOWN_STATUSES: frozenset[str]          # union of all five sets above


LIBRARY_FIELD_DEFAULTS: dict            # the §1 table as {key: default}

def normalize_draft_record(draft: dict) -> dict:
    """Return a copy with every §1 key present at its default. Never mutates
    the input. Repairs the pinned/pinned_at invariant: pinned False forces
    pinned_at None; pinned True with no pinned_at is left as (True, None)
    rather than being invented a timestamp."""

def apply_pin(draft: dict, pinned: bool, now_iso: str) -> dict:
    """Return a normalized copy with pinned set. Setting True stamps
    pinned_at=now_iso ONLY if not already pinned (re-pinning an already-pinned
    draft is a no-op that preserves the original pinned_at). Setting False
    clears pinned_at to None. Idempotent."""

def build_duplicate(source: dict, new_id: int, now_iso: str) -> dict:
    """A NEW pending draft that copies content and authoring context from
    `source`. Guarantees: status == "pending"; created_at == now_iso;
    duplicated_from_id == source["id"]; id == new_id; pinned False /
    pinned_at None; pending_send False; send_result None; error "";
    gate_reasons []; every send/delivery field reset. Carried over: raw_text,
    final_text, preset, contact_id, confidence, transcription_result,
    speech_signals, and metadata (shallow copy). A duplicate NEVER inherits a
    sent/sending status and therefore can never masquerade as sent history."""

def build_reopen_payload(source: dict) -> dict:
    """What Talk needs to load a selected draft for review. Read-only: does
    NOT create a record and does NOT mutate `source`. Returns
    {"source_id", "raw_text", "final_text", "preset", "contact_id",
     "status", "created_at", "editable": bool, "requires_new_record": bool}.
    `editable` is False while the source is in IN_FLIGHT_STATUSES.
    `requires_new_record` is True when source status is in SENT_STATUSES --
    i.e. editing it must fork a new record rather than mutate history."""

def build_reopen_edit(source: dict, new_id: int, now_iso: str,
                      raw_text: str | None, final_text: str | None) -> dict:
    """The record produced when the user edits a reopened item. Always a new
    pending draft; the original historical entry is never mutated. If source
    status is in SENT_STATUSES the result sets reopened_from_id=source["id"];
    otherwise it sets revision_of_id=source["id"]. Exactly one of the two is
    non-None. Text arguments default to the source's when None."""

def build_restore_from_draft(source: dict, new_id: int, now_iso: str) -> dict:
    """Clone a recoverable draft's content into a fresh pending draft.
    Sets restored_from_draft_id; leaves duplicated_from_id None (restore and
    duplicate are distinct provenance)."""

def resend_plan(source: dict) -> dict:
    """Resend is NOT a delivery primitive. Returns
    {"allowed": bool, "reason": str, "next_action": "reopen_for_review"}.
    `allowed` is False (reason "send_in_flight") while the source is in
    IN_FLIGHT_STATUSES. There is no branch of this function that performs or
    authorizes an immediate send: the only next_action it ever emits is
    reopen_for_review, so resend always routes through reopen -> review ->
    the ordinary delivery path."""

# --- filters --------------------------------------------------------------
FILTER_FIELDS: frozenset[str]           # {"persona", "date_from", "date_to", "status", "pinned", "query"}

def parse_filters(raw: dict) -> dict:
    """Validate and canonicalize a filter request. Unknown keys are dropped.
    Raises ValueError with a machine code ("invalid_status", "invalid_date",
    "invalid_pinned") on a malformed value. `status` is validated against
    KNOWN_STATUSES, not against PENDING|SENT|IN_FLIGHT alone.
    `date_from`/`date_to` are INCLUSIVE ISO-8601 dates or datetimes.
    AMENDMENT A1 -- inclusivity requires canonicalization, because
    `created_at` is a full ISO datetime and a naive string compare against a
    date-only bound silently excludes the whole day: "2026-07-28T04:20:00" >
    "2026-07-28" is True, so `date_to="2026-07-28"` would drop every item
    recorded that day. parse_filters MUST therefore expand a DATE-ONLY
    `date_to` to an end-of-day bound ("2026-07-28" -> "2026-07-28T23:59:59.999999")
    and leave a full datetime untouched. `date_from` needs no expansion (a
    date-only lower bound already sorts before that day's datetimes) but must
    still be canonicalized to a comparable string. Both the in-memory
    predicate and the SQL pushdown consume the SAME canonicalized bounds, so
    they cannot disagree. `query` is trimmed; empty means
    absent. NOTE: there is deliberately NO `destination` filter -- no draft
    record in this codebase has ever carried a destination field; it exists
    only in unwired renderer preview markup and must not be reintroduced
    here. NOTE: there is deliberately NO `contact` filter in Wave 3 --
    contacts are not qualified until Wave 5."""

def matches_filters(draft: dict, filters: dict) -> bool:
    """In-memory predicate matching the SQL pushdown in §3. `persona` matches
    draft["preset"] exactly. `status` may be a str or a collection.
    `pinned` True/False matches the normalized flag. `query` is a
    case-insensitive substring test over raw_text + final_text (SQLite FTS is
    the fast path; this is the authority for what a match means)."""

def sort_key(draft: dict) -> tuple:
    """Pinned-first, then newest-first by created_at, then id descending."""

# --- deletion + clear -----------------------------------------------------
DELETE_KINDS: frozenset[str]            # {"draft", "history_entry", "recording"}
CLEAR_SCOPES: frozenset[str]            # {"drafts_and_history", "recordings", "all_conversation_data"}

def delete_decision(kind: str, target: dict | None, *,
                    confirmed: bool, in_flight_ids: set) -> dict:
    """The single authority for whether a per-item delete may proceed.
    Returns {"action", "error", "http_status", "preview"} where action is one
    of "delete" | "noop_absent" | "refuse".
      - unknown kind                      -> refuse, "invalid_kind", 400
      - not confirmed                     -> refuse, "confirmation_required", 400,
                                             with a content-free `preview`
      - target is None (already gone)     -> noop_absent, 200  (IDEMPOTENT)
      - draft in IN_FLIGHT_STATUSES or in
        in_flight_ids                     -> refuse, "send_in_flight", 409
      - otherwise                         -> delete, 200
    The `preview` dict is content-free: {"kind", "id", "created_at",
    "status", "char_count", "has_recording"}. It never contains raw_text,
    final_text, transcript text, or any message body."""

def clear_decision(scope: str, *, confirmed: bool, counts: dict) -> dict:
    """Same shape as delete_decision for the three clear scopes. Unknown
    scope -> refuse "invalid_scope" 400. Unconfirmed -> refuse
    "confirmation_required" 400 with a content-free preview carrying the
    per-category counts the user is about to destroy. Each scope requires its
    OWN confirmation; confirming one scope never authorizes another."""

def audit_entry(*, action: str, kind: str, identity, outcome: str,
                now_iso: str, counts: dict | None = None) -> dict:
    """A content-free audit record: {"action", "kind", "identity", "outcome",
    "at", "counts"}. Callers MUST NOT pass message content; this function
    additionally strips any key whose name matches raw_text/final_text/
    text/transcript/content from `counts` as a defensive backstop."""
```

## 3. `history_store.py` + `backend/stores/drafts.py` — persistence

### `history_store` additions

```python
def set_pinned(draft_id: int, pinned: bool, pinned_at: str | None) -> bool:
    """Update the pinned columns AND the pinned/pinned_at keys inside the
    stored `data` JSON so the archive stays self-consistent. Returns False if
    no such row. Defensive like the rest of this module: never raises."""

def get(draft_id: int) -> dict | None:
    """AMENDMENT A2. One complete archive record by exact id, or None.

    Added because ``delete_item(kind="history_entry")`` must resolve its
    target to a dict before ``delete_decision`` can build a preview or check
    in-flight state, and the id may exist ONLY in the archive -- the
    in-memory ``draft_queue`` is bounded at 100 while the archive holds up to
    MAX_HISTORY_RECORDS (5000). Without this, the service layer has to call
    ``query({}, limit=<total>)`` and scan, which deserializes the entire
    archive's JSON blobs to delete a single row. Returns the record via
    _full_from_row, normalized. Defensive: never raises, returns None on any
    failure."""

def delete_draft(draft_id: int) -> bool:
    """Delete one archive row by exact id. The existing drafts_ad trigger
    keeps FTS in sync. Idempotent: returns False (not an error) when absent."""

def query(filters: dict, limit: int = 50, offset: int = 0) -> dict:
    """Backend-driven filtering. `filters` is the output of
    domain.library.parse_filters. Returns
    {"results": [full records], "total": int, "limit", "offset"}.
    persona -> preset column (SEE AMENDMENT A1 BELOW -- NOT the profile
    column); status -> status column; pinned -> pinned
    column; date_from/date_to -> created_at range; query -> FTS5 MATCH joined
    against the same row set. Ordering is pinned DESC, created_at DESC,
    id DESC. Results are complete records via the existing _full_from_row,
    each passed through normalize_draft_record."""
```

### AMENDMENT A1 — `persona` maps to a NEW `preset` column, not `profile`

The first revision of this contract said `persona -> profile column`. **That was
wrong and must not be implemented.** Verified in the source:

* `history_store._row_from_draft` (l.118) computes `profile` as
  `metadata["profile"] or draft["profile"]`. That is the **application/settings
  profile** — `safe_name` from the profile routes at `server.py:2687/2705/2724`.
* The **persona** is `draft["preset"]` (e.g. `"True Janitor"`), the value
  `DraftStore.create_draft` takes as its `preset=` argument. It is stored only
  inside the `data` JSON blob; it has no column.

Filtering persona on `profile` would therefore match on an unrelated field and
silently return wrong rows — and it would disagree with
`domain.library.matches_filters`, which correctly tests `draft["preset"]`. A
cross-layer disagreement like that returns plausible results and is very hard to
notice, so it must be fixed before Wave 4 builds UI on top of it.

Required: add a third additive column `preset TEXT`, populated from
`draft.get("preset")`, and filter `persona` on it. For rows written before
Wave 3 the column is NULL while the JSON still holds the value, so the
predicate must be:

```sql
COALESCE(preset, json_extract(data, '$.preset')) = ?
```

The `profile` column keeps its current meaning and is untouched by Wave 3.

`_row_from_draft` gains the three new columns (`pinned`, `pinned_at`, `preset`).
`_ensure_schema` adds them with the existing additive `PRAGMA table_info` guard
so a pre-Wave-3 database keeps working and starts recording pin state and preset
on the next write.

### `DraftStore` additions

```python
def set_pinned(self, draft_id, pinned, save_fn=None) -> dict | None
def delete_draft(self, draft_id, save_fn=None) -> bool
    """Removes from draft_queue and draft_recordings. Does NOT touch
    pending_manual_send_ids -- that list is server.py's and is handled by the
    service layer in §4."""
def duplicate_draft(self, draft_id, save_fn=None) -> dict | None
def create_from_record(self, record, save_fn=None) -> dict
    """Append a fully-built record (from a domain build_* function), assigning
    next_draft_id and honouring max_history trimming. The domain layer builds
    the record; the store only places it."""
def list_drafts(self, filters=None) -> list
```

All new mutators persist via `save_fn(changed_draft_id=...)` exactly like
`create_draft` does, outside `self.lock`.

## 4. `backend/services/library.py` — orchestration

Owns the cross-store coordination the pure domain layer cannot do. Constructed
with injected dependencies so tests never need a live server:

```python
class LibraryService:
    def __init__(self, draft_store, history_store_mod, recordings_mod,
                 save_fn, in_flight_ids_fn, audit_sink=None, now_fn=None): ...

    def set_pinned(self, draft_id, pinned) -> dict          # queue + archive together
    def delete_item(self, kind, identity, confirmed) -> dict
    def duplicate(self, draft_id) -> dict
    def reopen(self, draft_id) -> dict                      # read-only payload
    def commit_reopen_edit(self, draft_id, raw_text, final_text) -> dict
    def resend(self, draft_id) -> dict                      # returns resend_plan + reopen payload
    def restore_recording(self, rec_id, retranscribe_fn) -> dict
    def restore_draft(self, draft_id) -> dict
    def search(self, filters, limit, offset) -> dict
    def clear(self, scope, confirmed) -> dict
```

`in_flight_ids_fn()` returns the live set of draft ids that are mid-send
(server.py's `pending_manual_send_ids` plus anything with status `sending`).
`delete_item` consults it via `domain.library.delete_decision` and refuses with
409 rather than racing an active send. `restore_recording` takes the
retranscribe callable as an argument so the service never imports the
transcriber.

Every mutating method appends a `domain.library.audit_entry` to `audit_sink`.
`clear(scope="all_conversation_data")` must produce the same end state as the
existing `/privacy/wipe` conversational path for the categories it covers, and
must not silently widen into voices, models, or profiles.

## 5. `backend/api/routes/library.py` — thin adapters

`router = APIRouter()`, same shape as `backend/api/routes/contacts.py`: an
error-code -> HTTP-status map, a `_fail` helper, Pydantic request bodies, and
`run_in_threadpool` for anything touching disk. No business logic.

| Method | Path | Body / query |
|---|---|---|
| `POST` | `/library/drafts/{draft_id}/pin` | `{"pinned": bool}` |
| `GET` | `/library/search` | `persona, date_from, date_to, status, pinned, q, limit, offset` |
| `DELETE` | `/library/drafts/{draft_id}` | `?confirm=true` |
| `DELETE` | `/library/history/{entry_id}` | `?confirm=true` |
| `DELETE` | `/library/recordings/{rec_id}` | `?confirm=true` |
| `POST` | `/library/drafts/{draft_id}/duplicate` | — |
| `GET` | `/library/drafts/{draft_id}/reopen` | — |
| `POST` | `/library/drafts/{draft_id}/reopen` | `{"raw_text"?, "final_text"?}` |
| `POST` | `/library/drafts/{draft_id}/resend` | — |
| `POST` | `/library/recordings/{rec_id}/restore` | — |
| `POST` | `/library/drafts/{draft_id}/restore` | — |
| `POST` | `/library/clear` | `{"scope": str, "confirm": bool}` |

Status mapping: `invalid_kind`/`invalid_scope`/`confirmation_required`/
`invalid_status`/`invalid_date`/`invalid_pinned` -> 400; `not_found` -> 404;
`send_in_flight` -> 409; `write_failed` -> 500. Idempotent deletes return 200
with `{"ok": true, "removed": false, "already_absent": true}`.

The existing `/drafts`, `/history`, `/recordings`, and `/privacy/wipe` routes
are left in place and unmodified; `/library/*` is additive.

## 6. Waveform

Cut, per director ruling. No amplitude-envelope field is added by Wave 3. Do
not add `waveform`, `envelope`, or `peaks` to any record.

## 7. Privacy / audit contract

* Audit entries record **action, kind, identity, outcome, timestamp, counts**.
  They never record message content, transcripts, or any excerpt of them.
* Delete/clear previews are content-free (`char_count`, not the text).
* Deleting a draft also drops its in-memory `draft_recordings` entry; deleting
  a recording removes the WAV and its JSON sidecar via `recordings.delete_recording`.
* `clear(scope="drafts_and_history")` must NOT delete retained recordings, and
  `clear(scope="recordings")` must NOT delete drafts or history. Only
  `all_conversation_data` does both.

## 8. `server.py` route wiring (director applies; workers only document)

The complete required change is additive and confined to the existing
router-registration block at the end of the file:

```diff
 from backend.api.routes import contacts as routes_contacts  # noqa: E402
+from backend.api.routes import library as routes_library  # noqa: E402

 app.include_router(routes_contacts.router)
+app.include_router(routes_library.router)
```

plus one composition line placing the `LibraryService` instance where the
route module can reach it (module-level factory in the route file, resolved
per request, mirroring `contacts.py`'s `_store()` — so the wiring above is the
*entire* server.py diff). Any worker that finds it needs more than these two
lines must stop and report a `bug` upward rather than editing `server.py`.

## 9. Test policy

Cheap suite: `python3 -m pytest -q -k "not transcriber and not tts_engine"`
plus the targeted new files. Do not claim `__full-test-suite__`.

Every Gate 3 bullet needs at least one domain test that fails without the
change: pinning persistence across a store reload, per-item deletion identity
+ idempotency + in-flight refusal, duplicate never sent-shaped, reopen leaving
history intact, resend routing through review, restore from both sources,
each of the five filters plus a combination, and the three clear scopes with
independent confirmation.
