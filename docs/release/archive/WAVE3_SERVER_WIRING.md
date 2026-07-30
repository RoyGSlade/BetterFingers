# Wave 3 — `server.py` wiring for `/library/*` (director-applied)

Written by `w3-service` (Task W3-C) per contract §8. This is the complete,
additive `server.py` diff. **No other `server.py` change is required** —
`backend/api/routes/library.py` resolves every one of its dependencies at
request time via a per-request factory (`_service()`), the same pattern
`backend/api/routes/contacts.py` uses (`_store()`), so the router just needs
to be imported and registered.

## The diff

Apply at the existing router-registration block near the end of the file
(currently `server.py:5131-5146`, right after `routes_contacts` is imported
and registered):

```diff
--- a/server.py
+++ b/server.py
@@ -5134,10 +5134,12 @@
 from backend.api.routes import personas as routes_personas  # noqa: E402
 from backend.api.routes import message_rescue as routes_message_rescue  # noqa: E402
 from backend.api.routes import contacts as routes_contacts  # noqa: E402
+from backend.api.routes import library as routes_library  # noqa: E402

 app.include_router(routes_foundry.router)
 app.include_router(routes_user_config.router)
 app.include_router(routes_models_resources.router)
 app.include_router(routes_wake.router)
 app.include_router(routes_personas.router)
 app.include_router(routes_message_rescue.router)
 app.include_router(routes_contacts.router)
+app.include_router(routes_library.router)
 _foundry_sessions = routes_foundry._foundry_sessions
```

Concretely, at the current line numbers:

* Insert `from backend.api.routes import library as routes_library  # noqa: E402`
  as a new line **after line 5137**
  (`from backend.api.routes import contacts as routes_contacts  # noqa: E402`)
  and before the blank line at 5138.
* Insert `app.include_router(routes_library.router)` as a new line **after
  line 5145** (`app.include_router(routes_contacts.router)`) and before line
  5146 (`_foundry_sessions = routes_foundry._foundry_sessions`).

That's it — two lines, both additive, both in the same block every other
extracted route module (`routes_personas`, `routes_message_rescue`,
`routes_contacts`, …) is already wired up in.

## How `_service()` resolves its dependencies

`backend/api/routes/library.py`'s `_service()` factory is called fresh on
every request (never cached at import time), exactly like `contacts.py`'s
`_store()`. It builds a `backend.services.library.LibraryService` from five
things, all reached via `import server` inside the factory (so it always
sees the live, current module state rather than a stale reference captured
at import time):

| `LibraryService` constructor arg | Resolved from |
|---|---|
| `draft_store` | `server._draft_store` — the live `DraftStore` instance server.py already constructs at module load (`server.py:229`) |
| `history_store_mod` | the `history_store` module, imported directly by the route file (already a plain module of functions, same as `server.py` uses it) |
| `recordings_mod` | the `recordings` module, imported directly by the route file |
| `save_fn` | `server.save_draft_history` — the same revision-guarded writer every existing draft mutation in server.py already calls |
| `in_flight_ids_fn` | a small closure built inside `_service()`: the **union** of (a) every draft in `server._draft_store.draft_queue` whose `status == "sending"`, and (b) `set(server.pending_manual_send_ids)` — matching contract §4's requirement that `in_flight_ids_fn()` return "the live set of draft ids that are mid-send (server.py's `pending_manual_send_ids` plus anything with status `sending`)" |

`audit_sink` and `now_fn` are left at their defaults (`None` → no-op audit
sink; UTC ISO-8601 now) — Wave 3 doesn't specify a durable audit log
destination, so nothing in `server.py` needs to supply one yet. Wiring a
real audit sink (e.g. a log line, a table) is a follow-up, not part of this
two-line diff.

## Explicit statement

No `server.py` change beyond the two lines above is required to serve
`/library/*`. Everything else — the `LibraryService` construction, the
`in_flight_ids_fn` union logic, error-code → HTTP-status mapping — lives
entirely inside `backend/services/library.py` and
`backend/api/routes/library.py`, both additive new files that import from
`server.py` (via a lazy `import server` inside `_service()`) rather than
requiring `server.py` to import anything about Library.

## Known follow-up (not part of this diff, flagged separately)

`backend/api/routes/library.py`'s `POST /library/recordings/{rec_id}/restore`
route needs a way to turn a retained recording's audio back into transcript
text. It uses `server.transcriber` / `server.model_runtime` directly (both
already module-level singletons in `server.py`) rather than the existing
`/recordings/{rec_id}/retranscribe` endpoint, because that endpoint runs the
*full* dictation pipeline (`process_recording_result`) and creates its own
draft — reusing it would double-create a draft rather than letting
`LibraryService.restore_recording` build the single Wave-3-shaped record
(with `restored_from_recording_id` set) via `domain.build_restore_from_draft`.
This needs no `server.py` change (both singletons it reads already exist and
are already public module attributes), but is worth a second pair of eyes
from whoever owns the dictation pipeline — noted in the W3-C handoff as a
contract ambiguity, not blocking.
