"""Library HTTP surface (Wave 3, contract §5).

Thin FastAPI adapters over ``backend.services.library.LibraryService``. No
business logic lives here -- every decision (is this in flight, may I
delete, what does a duplicate look like, ...) already happened in
``backend.domain.library`` by the time a service method returns; this module
only translates its structured ``{"ok": False, "error": ...}`` results into
HTTP status codes, same shape as ``backend/api/routes/contacts.py``.

``_service()`` is resolved fresh per request (like ``contacts.py``'s
``_store()``), reaching into ``server`` for the live singletons
(``_draft_store``, ``pending_manual_send_ids``, ``save_draft_history``) so
the whole of this file's server.py integration is the two-line diff
documented in docs/release/WAVE3_SERVER_WIRING.md -- nothing here is
resolved or cached at import time.
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from typing import Optional

import history_store
import recordings
from backend.services.library import LibraryService

router = APIRouter()
logger = logging.getLogger(__name__)

# Maps a service result's structured error code to HTTP status (contract
# §5). Exhaustive over every code domain.library's decision functions and
# parse_filters emit; a service method never raises for a caller-shaped
# error, so anything unlisted would be a genuine 500.
_ERROR_STATUS = {
    "invalid_kind": 400,
    "invalid_scope": 400,
    "confirmation_required": 400,
    "invalid_status": 400,
    "invalid_date": 400,
    "invalid_pinned": 400,
    "invalid_id": 400,
    "not_found": 404,
    "send_in_flight": 409,
    "write_failed": 500,
    "partial_write": 500,
}


def _service() -> LibraryService:
    # Fresh per call: server's module-level singletons (_draft_store,
    # pending_manual_send_ids) may be reassigned between requests in tests,
    # and resolving them here rather than at import time is what keeps the
    # server.py diff to exactly the two lines the wiring doc documents.
    import server

    def in_flight_ids_fn():
        sending = {
            draft["id"] for draft in server._draft_store.draft_queue
            if draft.get("status") == "sending"
        }
        return sending | set(server.pending_manual_send_ids)

    return LibraryService(
        draft_store=server._draft_store,
        history_store_mod=history_store,
        recordings_mod=recordings,
        save_fn=server.save_draft_history,
        in_flight_ids_fn=in_flight_ids_fn,
    )


def _fail(result: dict):
    error = result.get("error")
    status = result.get("http_status") or _ERROR_STATUS.get(error, 400)
    raise HTTPException(status_code=status, detail=error)


# --- Request models ----------------------------------------------------------


class PinRequest(BaseModel):
    pinned: bool


class ReopenEditRequest(BaseModel):
    raw_text: Optional[str] = None
    final_text: Optional[str] = None


class ClearRequest(BaseModel):
    scope: str
    confirm: bool = False


# --- Pin ----------------------------------------------------------------------


@router.post("/library/drafts/{draft_id}/pin")
async def pin_draft_route(draft_id: int, request: PinRequest):
    result = await run_in_threadpool(_service().set_pinned, draft_id, request.pinned)
    if not result.get("ok"):
        _fail(result)
    return result


# --- Search ---------------------------------------------------------------------


@router.get("/library/search")
async def search_library_route(
    persona: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    pinned: Optional[bool] = None,
    q: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    raw_filters = {
        "persona": persona,
        "date_from": date_from,
        "date_to": date_to,
        "status": status,
        "pinned": pinned,
        "query": q,
    }
    result = await run_in_threadpool(_service().search, raw_filters, limit, offset)
    if not result.get("ok"):
        _fail(result)
    return result


# --- Delete ---------------------------------------------------------------------


@router.delete("/library/drafts/{draft_id}")
async def delete_draft_route(draft_id: int, confirm: bool = False):
    result = await run_in_threadpool(_service().delete_item, "draft", draft_id, confirm)
    if not result.get("ok") and not result.get("removed"):
        _fail(result)
    return result


@router.delete("/library/history/{entry_id}")
async def delete_history_entry_route(entry_id: int, confirm: bool = False):
    result = await run_in_threadpool(_service().delete_item, "history_entry", entry_id, confirm)
    if not result.get("ok") and not result.get("removed"):
        _fail(result)
    return result


@router.delete("/library/recordings/{rec_id}")
async def delete_recording_route(rec_id: str, confirm: bool = False):
    result = await run_in_threadpool(_service().delete_item, "recording", rec_id, confirm)
    if not result.get("ok") and not result.get("removed"):
        _fail(result)
    return result


# --- Duplicate / reopen / resend / restore ---------------------------------------


@router.post("/library/drafts/{draft_id}/duplicate")
async def duplicate_draft_route(draft_id: int):
    result = await run_in_threadpool(_service().duplicate, draft_id)
    if not result.get("ok"):
        _fail(result)
    return result


@router.get("/library/drafts/{draft_id}/reopen")
async def reopen_draft_route(draft_id: int):
    result = await run_in_threadpool(_service().reopen, draft_id)
    if not result.get("ok"):
        _fail(result)
    return result


@router.post("/library/drafts/{draft_id}/reopen")
async def commit_reopen_edit_route(draft_id: int, request: ReopenEditRequest):
    result = await run_in_threadpool(
        _service().commit_reopen_edit, draft_id, request.raw_text, request.final_text,
    )
    if not result.get("ok"):
        _fail(result)
    return result


@router.post("/library/drafts/{draft_id}/resend")
async def resend_draft_route(draft_id: int):
    result = await run_in_threadpool(_service().resend, draft_id)
    if not result.get("ok"):
        _fail(result)
    return result


def _retranscribe(rec_id: str):
    """Turn a retained recording's audio back into transcript content.

    Deliberately lighter than the full dictation pipeline
    (``server.process_recording_result``): a restore is a provenance-tracked
    clone (contract §1's ``restored_from_recording_id``), built the same
    shallow-content way ``duplicate``/``restore_draft`` are, not a re-run of
    contact detection or review-gate scoring. Returns a transcript-shaped
    dict for ``LibraryService.restore_recording`` to build a fresh pending
    draft from, or None if there is no audio to restore.
    """
    import server

    audio, _sample_rate = recordings.load_recording_audio(rec_id)
    if audio is None:
        return None
    if not server.transcriber:
        raise HTTPException(status_code=503, detail="Transcriber not initialized")
    with server.model_runtime.read_lease("stt"):
        text = server.transcriber.transcribe(audio)
    return {"raw_text": text, "final_text": text}


@router.post("/library/recordings/{rec_id}/restore")
async def restore_recording_route(rec_id: str):
    result = await run_in_threadpool(_service().restore_recording, rec_id, _retranscribe)
    if not result.get("ok"):
        _fail(result)
    return result


@router.post("/library/drafts/{draft_id}/restore")
async def restore_draft_route(draft_id: int):
    result = await run_in_threadpool(_service().restore_draft, draft_id)
    if not result.get("ok"):
        _fail(result)
    return result


# --- Clear ------------------------------------------------------------------


@router.post("/library/clear")
async def clear_library_route(request: ClearRequest):
    result = await run_in_threadpool(_service().clear, request.scope, request.confirm)
    if not result.get("ok"):
        _fail(result)
    return result
