"""Runtime-control routes and the voice-status WebSocket, lifted out of server.py
(R10, the last router batch): ``/ws/voice_status``, ``/runtime/rewrite-selection``,
``/voice-commands/execute``, the five recording/primary-action/emergency-stop
controls, ``/runtime/warmup`` and ``/transcribe`` (9 HTTP routes + 1 WebSocket).

This is the hot path (it starts and stops the recorder, fires the injector and
reads the clipboard through server helpers), so it is a pure relocation:

* Every handler keeps its exact sync/async signature and its exact body, apart
  from reading server state as ``s.<name>``. The thin control routes call
  ``s.handle_primary_action`` / ``s.emergency_stop_runtime`` /
  ``s.toggle|start|stop_recording_runtime`` -- the helpers (and the hotkey
  manager, recorder, injector and selection-capture they drive) stay in
  server.py untouched, and so does ``start_hotkey_manager``, the one place that
  rebinds ``hotkey_manager`` / ``hotkey_manager_started`` / ``hotkey_recorder``.
* ``transcribe_audio`` carried ``global transcriber`` but only ever READ the
  name, so the declaration was a no-op; it reads ``s.transcriber`` now. Its form
  signature (``file: UploadFile = File(...)``) is unchanged. No other handler
  here declares ``global`` or assigns a server name.
* ``/ws/voice_status`` authenticates with a first-message ``auth:<token>``
  frame only (the legacy ``?token=`` query form was removed in Phase 0:
  tokens in URLs reach access logs), ``auth_ok`` on success, close code 1008 otherwise. The
  ``active_websockets`` registry is a server list that this handler mutates only
  through ``append`` / ``remove``; the event-loop capture (``loop``, set in
  ``startup_event`` under ``global``) and ``broadcast_status`` /
  ``broadcast_status_threadsafe`` stay in server.py, so the message format and
  the cross-thread scheduling are unchanged. The ``auth_middleware`` exemption
  for ``/ws/`` paths is path-based and untouched.
* ``execute_voice_command`` awaits the draft handlers through ``routes_drafts``
  (R8). ``backend.api.routes.drafts`` has no top-level import of ``server``, so
  importing it at the top of this module cannot create a cycle in any import
  order.
* ``RuntimeWarmupRequest`` and ``VoiceCommandExecuteRequest`` (with the two
  constants ``execute_voice_command`` alone uses) are used only by these routes,
  so they live here.

Same strangler shape as the earlier routers: ``server`` is imported lazily inside
each handler (``import server as s``) because server.py imports this module near
the end of its own load, and every server name is read as ``s.<name>`` at call
time so ``patch.object(server, ...)`` in tests still lands. Registered via
``app.include_router`` at the end of server.py.
"""
import asyncio
import hmac
import logging
import os
import tempfile
import typing
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, StrictBool, StrictInt, StrictStr

from backend.api.routes import drafts as routes_drafts

router = APIRouter()


# NOT decorated with @router.websocket: the handler is attached to the app by
# server.py (`app.add_api_websocket_route("/ws/voice_status", ...)`, exactly what
# the old `@app.websocket` decorator did). FastAPI 0.140.x reports the path of a
# WebSocket route that arrives through `include_router` as '' in
# `iter_route_contexts`, which is what tests/test_route_table_snapshot.py reads, so
# an included-router WebSocket would change the pinned route table ('' instead of
# '/ws/voice_status') even though it dispatches correctly. Registering it on the
# app keeps the public route table byte-identical.
async def websocket_endpoint(websocket: WebSocket):
    import server as s

    # First-message auth ONLY: the bearer token must arrive as the first frame
    # ("auth:<token>"). The legacy ``?token=`` query form is gone (Phase 0
    # item 10): a query string lands in access logs, proxy logs, diagnostics and
    # crash reports, so a token in a URL is a token in every one of them. A
    # client that still sends one is simply unauthenticated.
    expected_token = os.getenv("BETTERFINGERS_AUTH_TOKEN")
    await websocket.accept()
    if expected_token:
        try:
            first = await asyncio.wait_for(websocket.receive_text(), timeout=3.0)
            presented = first[5:] if first.startswith("auth:") else ""
            authed = hmac.compare_digest(presented, expected_token)
        except Exception:
            authed = False
        if not authed:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await websocket.send_text("auth_ok")
    s.active_websockets.append(websocket)
    try:
        while True:
            # Keep alive / listen for client commands (like 'cancel')
            data = await websocket.receive_text()
            # Handle client commands if needed
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        s.active_websockets.remove(websocket)
    except Exception as e:
        logging.error(f"WebSocket Error: {e}")
        if websocket in s.active_websockets:
            s.active_websockets.remove(websocket)


class RuntimeWarmupRequest(BaseModel):
    stt: bool = False
    llm: bool = False
    hotkeys: bool = False


@router.post("/runtime/rewrite-selection")
async def runtime_rewrite_selection():
    """Rewrite the current selection and open it as a review-only draft."""
    import server as s

    return await run_in_threadpool(s.handle_selection_rewrite_shortcut)


class VoiceCommandExecuteRequest(BaseModel):
    text: str
    draft_id: Optional[int] = None
    context: dict = {}
    confirm: bool = False


_REWRITE_ACTION_FOR = {"rewrite_shorter": "shorter", "rewrite_clearer": "clearer"}
_DRAFT_DEPENDENT_ACTIONS = {"cancel", "send", "copy", "read_back", "retry", *_REWRITE_ACTION_FOR}


@router.post("/voice-commands/execute")
async def execute_voice_command(request: VoiceCommandExecuteRequest):
    """Real trigger point for app-control voice commands (task 9): classify
    `text` via voice_commands.parse_command, then execute the resolved
    action against the existing draft/runtime functions. `emergency_stop`
    always executes; anything else with requires_confirmation=True only
    executes when `confirm=True` is sent as a follow-up call."""
    import server as s

    if not s.app_commands_enabled():
        return {"ok": False, "reason": "disabled"}

    intent = s.voice_commands.parse_command(request.text, request.context)
    if intent is None:
        return {"ok": False, "reason": "no_command_recognized"}

    s.broadcast_status_threadsafe(
        "command_detected",
        {"action": intent.action, "kind": intent.kind, "confidence": intent.confidence},
    )

    if intent.requires_confirmation and not request.confirm:
        s.broadcast_status_threadsafe(
            "command_needs_confirmation",
            {"action": intent.action, "kind": intent.kind},
        )
        return {"ok": False, "reason": "needs_confirmation", "action": intent.action}

    draft_id = request.draft_id
    try:
        if intent.action == "emergency_stop":
            s.emergency_stop_runtime()
            return {"ok": True, "action": intent.action}
        if intent.action == "start_recording":
            s.start_recording_runtime()
            return {"ok": True, "action": intent.action}
        if intent.action == "stop_recording":
            s.stop_recording_runtime()
            return {"ok": True, "action": intent.action}
        if intent.action not in _DRAFT_DEPENDENT_ACTIONS:
            return {"ok": False, "reason": "not_implemented", "action": intent.action}

        if draft_id is None:
            return {"ok": False, "reason": "no_draft", "action": intent.action}

        if intent.action == "cancel":
            result = await routes_drafts.decline_draft(draft_id)
        elif intent.action == "send":
            result = s.send_draft_by_id(draft_id)
        elif intent.action == "copy":
            draft = s.get_draft_by_id(draft_id)
            if draft is None:
                return {"ok": False, "reason": "no_draft", "action": intent.action}
            s.copy_text_to_clipboard(draft.get("final_text", ""))
            result = {"draft_id": draft_id}
        elif intent.action == "read_back":
            draft = s.get_draft_by_id(draft_id)
            if draft is None:
                return {"ok": False, "reason": "no_draft", "action": intent.action}
            s.speak_text_aloud(draft.get("final_text", ""))
            result = {"draft_id": draft_id}
        elif intent.action in _REWRITE_ACTION_FOR:
            result = await routes_drafts.rewrite_draft(draft_id, routes_drafts.DraftRewriteRequest(action=_REWRITE_ACTION_FOR[intent.action]))
        else:  # intent.action == "retry"
            result = await routes_drafts.retry_draft(draft_id)
        return {"ok": True, "action": intent.action, "result": result}
    except HTTPException:
        raise
    except Exception as exc:
        logging.error(f"Voice command execution failed: {s.redact_exc(exc)}")
        return {"ok": False, "reason": "error", "action": intent.action, "error": str(exc)}


class PrimaryActionRequest(BaseModel):
    displayed_draft_id: StrictInt | None = Field(default=None, gt=0)
    displayed_final_text: StrictStr | None = None
    # True when the review overlay is visible but has not acknowledged which
    # draft it painted (Electron main knows; the backend cannot).
    review_visible: StrictBool = False


@router.post("/runtime/primary-action")
async def runtime_primary_action(request: PrimaryActionRequest | None = None):
    import server as s

    if request is None:
        return await run_in_threadpool(s.handle_primary_action)
    return await run_in_threadpool(s.handle_primary_action,
                                  displayed_draft_id=request.displayed_draft_id,
                                  displayed_final_text=request.displayed_final_text,
                                  review_visible=request.review_visible)


@router.post("/runtime/emergency-stop")
async def runtime_emergency_stop():
    import server as s

    return s.emergency_stop_runtime()


@router.post("/runtime/recording/toggle")
async def runtime_recording_toggle():
    import server as s

    return s.toggle_recording_runtime()


@router.post("/runtime/recording/start")
async def runtime_recording_start():
    import server as s

    return s.start_recording_runtime()


@router.post("/runtime/recording/stop")
async def runtime_recording_stop():
    import server as s

    return s.stop_recording_runtime()


@router.post("/runtime/warmup")
async def runtime_warmup(request: RuntimeWarmupRequest):
    import server as s

    result: typing.Dict[str, typing.Any] = {"requested": request.model_dump()}

    if request.stt:
        trans = None
        try:
            trans = await run_in_threadpool(s.ensure_transcriber_initialized, preload=False)
            probe_fn = getattr(trans, "runtime_probe", None) if trans is not None else None
            if callable(probe_fn):
                probe = await run_in_threadpool(probe_fn)
                stt_status = s._transcriber_status_snapshot(trans, probe)
            else:
                # Compatibility for test doubles/older injected transcribers:
                # constructor success is the only fact available when there is
                # no probe API, and is not called inference-ready by new code.
                loaded = bool(trans and await run_in_threadpool(trans.ensure_loaded))
                stt_status = s._transcriber_status_snapshot(trans)
                stt_status["constructed"] = loaded or stt_status.get("constructed", False)
            result["stt"] = {
                "ok": bool(stt_status.get("probe_passed", False)),
                "initialized": trans is not None,
                "loaded": bool(stt_status.get("constructed", False)),
                **stt_status,
            }
        except Exception as e:
            logging.error("Transcriber warmup failure (stt_inference_failed).")
            s._record_transcriber_runtime_event({
                "code": "stt_inference_failed",
                "state": "probe_failed",
                "severity": "recoverable",
            })
            stt_status = s._transcriber_status_snapshot(trans)
            result["stt"] = {
                "ok": False,
                "initialized": s.transcriber is not None,
                "loaded": bool(stt_status.get("constructed", False)),
                **stt_status,
                "error": stt_status.get("error_code") or "stt_inference_failed",
            }

    if request.llm:
        try:
            engine = s.get_selected_llm_engine()
            ready = bool(getattr(engine, "_ready", False))
            result["llm"] = {
                "ok": ready,
                "initialized": engine is not None,
                "ready": ready,
                "error": "" if ready else str(getattr(engine, "_last_error", "") or ""),
            }
        except Exception as e:
            logging.exception("LLM warmup failure")
            s.record_runtime_error("llm", str(e), {"action": "warmup"})
            engine = s.get_engine_if_initialized()
            result["llm"] = {
                "ok": False,
                "initialized": engine is not None,
                "ready": bool(getattr(engine, "_ready", False)) if engine else False,
                "error": str(e),
            }

    if request.hotkeys:
        try:
            manager = s.start_hotkey_manager()
            hook_errors = list(getattr(manager, "keyboard_hook_errors", [])) if manager else []
            if hook_errors:
                message = "Keyboard hooks are unavailable: " + "; ".join(hook_errors)
                s.record_runtime_error("hotkeys", message, {"action": "warmup", "degraded": True})
            result["hotkeys"] = {
                "ok": not hook_errors,
                "started": manager is not None and s.hotkey_manager_started,
                "keyboard_hooks_ok": not hook_errors,
                "keyboard_hook_errors": hook_errors,
                "error": "; ".join(hook_errors) if hook_errors else "",
            }
        except Exception as e:
            logging.exception("Hotkey warmup failure")
            s.record_runtime_error("hotkeys", str(e), {"action": "warmup"})
            result["hotkeys"] = {
                "ok": False,
                "started": s.hotkey_manager_started,
                "error": str(e),
            }

    # The warmup result contains stronger, action-specific evidence than the
    # observation-only snapshot (notably the STT probe result). Merge it last
    # so /runtime/warmup never overwrites that proof with a stale status row.
    status_snapshot = s.get_runtime_status_snapshot()
    status_snapshot.update(result)
    return status_snapshot

@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    import server as s

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    temp_filename = tmp.name
    tmp.close()
    try:
        # Validate the upload before anything else — a malformed or oversized
        # file is rejected regardless of whether STT is loaded.
        try:
            s.upload_safety.stream_to_file(file.file, temp_filename, s.upload_safety.MAX_AUDIO_BYTES)
            s.upload_safety.validate_signature(temp_filename, "audio")
            s.upload_safety.validate_wav_duration(temp_filename)
        except s.upload_safety.UploadTooLarge as exc:
            raise HTTPException(status_code=413, detail=f"Audio too large (max {exc.limit} bytes).")
        except s.upload_safety.UploadRejected as exc:
            raise HTTPException(status_code=400, detail=f"Invalid audio: {exc}")
        if not s.transcriber:
            raise HTTPException(status_code=503, detail="Transcriber not initialized")
        # Read lease: a concurrent STT unload/reload waits or 409s instead of
        # freeing the Whisper model out from under this transcription.
        with s.model_runtime.read_lease("stt"):
            text = await run_in_threadpool(s.transcriber.transcribe, temp_filename)
        if not str(text or "").strip():
            # The transcriber answers "" both for silence and for a model that
            # could not load. Only silence from a loaded model is a 200: never
            # tell a caller nothing was said when the speech model is missing
            # or failed verification (503, same status as "not initialized").
            unavailable = s._stt_unavailable_code(s.transcriber)
            if unavailable:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "ok": False,
                        "error": unavailable,
                        "message": s._STT_UNAVAILABLE_MESSAGES[unavailable],
                    },
                )
        return {"text": text}
    except HTTPException:
        raise
    except s.RuntimeBusyError:
        raise HTTPException(status_code=409, detail="STT runtime is being reconfigured; retry shortly.")
    except Exception as e:
        logging.error(f"Transcription Error: {s.redact_exc(e)}")
        raise HTTPException(status_code=500, detail="Transcription failed")
    finally:
        try:
            os.remove(temp_filename)
        except OSError:
            pass
