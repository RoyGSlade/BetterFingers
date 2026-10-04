"""Draft routes lifted out of server.py (R8): list / latest / clear, the dev-only
mock draft, accept / decline / retry / edit / contact / rewrite, draft read-aloud
(``/drafts/{id}/tts``) and send (12 routes).

Drafts are the user's dictated text and ``send`` places it into another
application, so this is a pure relocation: every handler body is unchanged apart
from reaching server state as ``s.<name>``, and every handler keeps its exact
sync/async signature (``clear_draft_history`` / ``create_mock_draft`` stay plain
``def``; ``send_draft`` stays ``async def`` and still calls the synchronous
``send_draft_by_id`` directly, as before).

State ownership is unchanged. ``draft_queue``, ``draft_recordings``,
``draft_lock``, ``pending_manual_send_ids``, ``is_processing_draft``,
``next_draft_id`` and ``output_coordinator`` stay in server.py, and so do the
helpers that rebind them under ``global`` (``load_draft_history``,
``process_recording_result``, ...). No handler here declares ``global`` or assigns
a server name; the queue and id list are only ever MUTATED through method calls
(``.clear()``, ``.remove()``) while ``s.draft_lock`` is held, exactly as before.
``send_draft_by_id`` -> ``perform_output_action`` (injector, clipboard, the
gaming-policy ``get_service().poll()`` check) is a server helper and is untouched.

Shared helpers stay in server.py and are reached as ``s.<helper>``:
``_resolve_voice_and_modulation`` (also used by /tts/speak), ``rewrite_draft_text``,
``get_rewrite_instruction``, ``create_draft``, ``get_draft_by_id``,
``mark_draft_pending_send``, ``update_draft_review_fields`` and
``save_draft_history``.

The five request models are used only by these routes (and ``DraftRewriteRequest``
by ``execute_voice_command`` in runtime.py, which reaches it, and the
``decline_draft`` / ``rewrite_draft`` / ``retry_draft`` handlers it awaits,
through ``routes_drafts``).

Same strangler shape as the earlier routers: ``server`` is imported lazily inside
each handler (``import server as s``) because server.py imports this module near
the end of its own load. Every server name is read as ``s.<name>`` at call time,
so ``patch.object(server, ...)`` in tests still lands. Registered via
``app.include_router`` at the end of server.py.
"""
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

router = APIRouter()


@router.get("/drafts")
async def list_drafts():
    import server as s

    with s.draft_lock:
        return {"drafts": [dict(draft) for draft in s.draft_queue]}


@router.get("/drafts/latest")
async def latest_draft():
    import server as s

    with s.draft_lock:
        if not s.draft_queue:
            return {"draft": None}
        return {"draft": dict(s.draft_queue[-1])}


@router.delete("/drafts")
def clear_draft_history():
    import server as s

    with s.draft_lock:
        s.draft_queue.clear()
        s.draft_recordings.clear()
        s.pending_manual_send_ids.clear()
    s.save_draft_history()
    s.broadcast_status_threadsafe("draft_history_cleared")
    return {"ok": True, "message": "Draft history cleared."}


@router.post("/drafts/test-mock")
def create_mock_draft(status: str = "pending", raw: str = "Mock raw transcript text.", final: str = "Mock cleaned and polished output."):
    import server as s

    if os.getenv("BETTERFINGERS_ENV", "development") == "production":
        raise HTTPException(status_code=403, detail="Mock endpoints are disabled in production.")

    metadata = {
        "duration_seconds": 3.45,
        "sample_rate": 16000,
        "sample_count": 55200,
        "max_amplitude": 0.35,
        "rms_amplitude": 0.08,
        "stop_reason": "manual"
    }
    draft = s.create_draft(raw, final, preset="True Janitor", status=status, metadata=metadata)
    s.broadcast_status_threadsafe("preview_ready", {
        "draft_id": draft["id"],
        "raw_text": draft["raw_text"],
        "final_text": draft["final_text"],
        "token_count": draft["token_count"],
        "token_limit": draft["token_limit"],
        "long_text": draft["long_text"],
    })
    return draft



@router.post("/drafts/{draft_id}/accept")
async def accept_draft(draft_id: int):
    import server as s

    with s.draft_lock:
        for draft in s.draft_queue:
            if draft["id"] == draft_id:
                draft["status"] = "accepted"
                s.mark_draft_pending_send(draft)
                response = dict(draft)
                break
        else:
            raise HTTPException(status_code=404, detail="Draft not found")
    s.save_draft_history(changed_draft_id=draft_id)
    s.broadcast_status_threadsafe("draft_accepted", {"draft_id": draft_id, "pending_send": True})
    return response


@router.post("/drafts/{draft_id}/decline")
async def decline_draft(draft_id: int):
    import server as s

    with s.draft_lock:
        for draft in s.draft_queue:
            if draft["id"] == draft_id:
                draft["status"] = "declined"
                draft["pending_send"] = False
                while draft_id in s.pending_manual_send_ids:
                    s.pending_manual_send_ids.remove(draft_id)
                response = dict(draft)
                break
        else:
            raise HTTPException(status_code=404, detail="Draft not found")
    s.save_draft_history(changed_draft_id=draft_id)
    s.broadcast_status_threadsafe("draft_declined", {"draft_id": draft_id})
    return response


@router.post("/drafts/{draft_id}/retry")
async def retry_draft(draft_id: int):
    import server as s

    with s.draft_lock:
        recording_result = s.draft_recordings.get(draft_id)

    if recording_result is None:
        raise HTTPException(status_code=409, detail="No recording data is available for this draft")

    # Blocking model pipeline must not run on the event loop (it would starve
    # /health and trip Electron's restart watchdog).
    draft = await run_in_threadpool(s.process_recording_result, recording_result)
    if draft is None:
        raise HTTPException(status_code=409, detail="A dictation is already processing; try again shortly.")
    return draft


class DraftEditRequest(BaseModel):
    final_text: str


class DraftRewriteRequest(BaseModel):
    action: str = "clearer"
    custom_instruction: str = ""


class DraftTtsRequest(BaseModel):
    text: str = ""
    voice_id: Optional[str] = None
    speed: Optional[float] = None
    pitch: Optional[float] = None
    blend: Optional[dict] = None
    energy: Optional[float] = None
    warmth: Optional[float] = None
    brightness: Optional[float] = None
    pause_style: Optional[str] = None
    preset_name: Optional[str] = None
    persona: Optional[str] = None


@router.post("/drafts/{draft_id}/edit")
async def edit_draft(draft_id: int, request: DraftEditRequest):
    import server as s

    with s.draft_lock:
        draft = s.get_draft_by_id(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")

        draft["final_text"] = request.final_text or ""
        if draft.get("status") in {"accepted", "declined", "sent", "send_error"}:
            draft["status"] = "pending"
            draft["pending_send"] = False
            while draft_id in s.pending_manual_send_ids:
                s.pending_manual_send_ids.remove(draft_id)
        else:
            draft["status"] = draft.get("status", "pending")
        draft["error"] = ""
        draft["updated_at"] = s.datetime.now(s.timezone.utc).isoformat()
        s.update_draft_review_fields(draft)
        response = dict(draft)

    s.save_draft_history(changed_draft_id=draft_id)
    s.broadcast_status_threadsafe(
        "draft_updated",
        {
            "draft_id": response["id"],
            "final_text": response["final_text"],
            "token_count": response["token_count"],
            "token_limit": response["token_limit"],
            "long_text": response["long_text"],
        },
    )
    return response


class DraftContactRequest(BaseModel):
    contact_id: str = ""


@router.post("/drafts/{draft_id}/contact")
async def set_draft_contact(draft_id: int, request: DraftContactRequest):
    """Apply (or clear) a contact on an existing draft.

    Recording the audience after the fact is the same act as recording it at
    dictation time -- it is metadata about who the message is for, and it is
    what lets Library resolve a name on the card. It does NOT re-run cleanup:
    the draft text was produced without that context and rewriting it here
    would change the user's words behind their back.

    An empty contact_id clears the field. A non-empty one must name a contact
    that exists, so a deleted contact cannot be re-attached by id.
    """
    import server as s

    contact_id = (request.contact_id or "").strip()
    if contact_id:
        from backend.services.contacts import ContactStore
        if ContactStore().get(contact_id) is None:
            raise HTTPException(status_code=404, detail=f"Contact '{contact_id}' not found.")

    with s.draft_lock:
        draft = s.get_draft_by_id(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        draft["contact_id"] = contact_id or None
        draft["updated_at"] = s.datetime.now(s.timezone.utc).isoformat()
        response = dict(draft)

    s.save_draft_history(changed_draft_id=draft_id)
    return response


@router.post("/drafts/{draft_id}/rewrite")
async def rewrite_draft(draft_id: int, request: DraftRewriteRequest):
    import server as s

    with s.draft_lock:
        draft = s.get_draft_by_id(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        source_text = draft.get("final_text") or draft.get("raw_text") or ""

    action_key, _instruction = s.get_rewrite_instruction(request.action, request.custom_instruction)
    try:
        s.broadcast_status_threadsafe("draft_rewriting", {"draft_id": draft_id, "action": action_key})
        rewritten = str(s.rewrite_draft_text(source_text, action_key, request.custom_instruction) or source_text).strip()
        with s.draft_lock:
            draft = s.get_draft_by_id(draft_id)
            if draft is None:
                raise HTTPException(status_code=404, detail="Draft not found")
            draft["final_text"] = rewritten
            draft["status"] = "pending"
            draft["error"] = ""
            draft["rewrite_action"] = action_key
            draft["updated_at"] = s.datetime.now(s.timezone.utc).isoformat()
            s.update_draft_review_fields(draft)
            response = dict(draft)
        s.save_draft_history(changed_draft_id=draft_id)
        s.broadcast_status_threadsafe(
            "draft_rewritten",
            {
                "draft_id": response["id"],
                "action": action_key,
                "final_text": response["final_text"],
                "token_count": response["token_count"],
                "token_limit": response["token_limit"],
                "long_text": response["long_text"],
            },
        )
        return response
    except HTTPException:
        raise
    except Exception as exc:
        logging.error(f"Draft rewrite failed: {s.redact_exc(exc)}")
        s.record_runtime_error("review", str(exc), {"action": "rewrite", "draft_id": draft_id})
        s.broadcast_status_threadsafe("draft_rewrite_error", {"draft_id": draft_id, "action": action_key, "error": str(exc)})
        return {
            "ok": False,
            "draft_id": draft_id,
            "action": action_key,
            "error": str(exc),
            "draft": dict(s.get_draft_by_id(draft_id) or {}),
        }


@router.post("/drafts/{draft_id}/tts")
async def speak_draft(draft_id: int, request: DraftTtsRequest):
    import server as s

    wiping = s._reject_if_wiping("draft TTS")
    if wiping:
        return {"draft_id": draft_id, **wiping}
    with s.draft_lock:
        draft = s.get_draft_by_id(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        text = (request.text or draft.get("final_text") or draft.get("raw_text") or "").strip()

    if not text:
        return {"ok": False, "draft_id": draft_id, "message": "No draft text is available to read aloud.", "error": "empty_text"}

    profile_name = s.get_last_active_profile()
    try:
        config = s.load_profile(profile_name)
    except Exception:
        config = {}

    voice_id, speed, blend, modulation = s._resolve_voice_and_modulation(request, config)
    logging.info(f"Draft TTS Request: draft={draft_id} {s.redact_user_text(text)} | Voice: {voice_id} | Speed: {speed}x")

    engine = await run_in_threadpool(s.ensure_tts_initialized)
    if engine is None:
        result = {
            "ok": False,
            "status": "error",
            "draft_id": draft_id,
            "message": "TTS engine is not available.",
            "error": "tts_unavailable",
            "text_length": len(text),
        }
        s.record_runtime_error("tts", result["message"], {"action": "draft_tts", "draft_id": draft_id})
        return result

    try:
        with s.model_runtime.read_lease("tts"):
            result = await run_in_threadpool(
                engine.speak, text, speed=speed, voice_hint=voice_id, blend=blend, modulation=modulation
            )
    except s.RuntimeBusyError:
        return {"ok": False, "status": "error", "draft_id": draft_id,
                "error": "tts_reconfiguring", "message": "TTS runtime is being reconfigured; retry shortly."}
    result.update(
        {
            "status": "success" if result.get("ok") else "error",
            "draft_id": draft_id,
            "text_length": len(text),
        }
    )
    s.broadcast_status_threadsafe("draft_tts_requested", {"draft_id": draft_id, "text_length": len(text)})
    return result


class DraftSendRequest(BaseModel):
    action: str = "copy_only"
    open_chat: bool = False
    allow_resend: bool = False


@router.post("/drafts/{draft_id}/send")
async def send_draft(draft_id: int, request: DraftSendRequest = DraftSendRequest()):
    import server as s

    return s.send_draft_by_id(
        draft_id,
        action=request.action,
        open_chat=request.open_chat,
        allow_resend=request.allow_resend,
    )
