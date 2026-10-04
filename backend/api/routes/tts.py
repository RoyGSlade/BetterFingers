"""TTS routes lifted out of server.py (R7): read-aloud toggle, speak/stop, runtime
TTS status, the voice list, voice cloning (upload, status, provisioning) and
cloned-voice deletion (9 routes). ``/drafts/{id}/tts`` is a drafts route and is
NOT here (R8).

These routes can synthesize and play audio and provision a download, so the move
changes nothing about what they call or in what order:

* The routes rebind NO server global. ``stop_tts_route`` and ``get_tts_status``
  carried a ``global tts_engine`` declaration but only ever READ the name (the
  declaration was a no-op); here they read ``s.tts_engine`` at call time instead
  and the declaration is gone. The one real rebinding, in ``ensure_tts_initialized``
  (``tts_engine = ReviewTTSEngine()``), stays in server.py and is reached as
  ``s.ensure_tts_initialized`` -- as do ``_reject_if_wiping``,
  ``_resolve_voice_and_modulation`` (shared with /drafts/{id}/tts),
  ``handle_review_tts_shortcut``, ``get_voices_path`` and ``ensure_voices_dir``.
* ``get_voice_clone_status`` and ``provision_voice_cloning`` touch no server
  state (their only collaborator is the lazily imported ``voice_clone_engine``),
  so they have no ``import server as s``.
* ``/tts/voices`` (``list_voices``) is the handler ``app/src/renderer/lib/
  modelCompat.mjs`` cites as ``backend/api/routes/tts.py::list_voices``;
  ``app/tests/modelCompat.test.mjs`` resolves that citation against this file.
* The gaming-policy spoken-text clamp (``backend.domain.gaming_policy.
  trim_spoken_text`` / ``MAX_TTS_*``) is applied by backend/services/
  app_context.py, not by any of these routes, so there is nothing to carry over.

Same strangler shape as dev.py, settings.py, history.py, diagnostics.py and
models.py: ``server`` stays the owner of all state and helpers and is imported
lazily inside each handler (``import server as s``), because server.py imports
this module near the end of its own load and a top-level ``import server`` here
would be a partially initialized circular import. Every server name is read as
``s.<name>`` at call time, so ``patch.object(server, ...)`` in tests still lands.
``TTSRequest`` is used only by ``/tts/speak``, so it lives here. Registered via
``app.include_router`` at the end of server.py.
"""
import logging
import os
import shutil
import tempfile
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

router = APIRouter()


@router.post("/runtime/tts/toggle")
async def runtime_tts_toggle():
    import server as s

    return s.handle_review_tts_shortcut()


class TTSRequest(BaseModel):
    text: str
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

@router.post("/tts/speak")
async def tts_speak(request: TTSRequest):
    import server as s

    wiping = s._reject_if_wiping("TTS")
    if wiping:
        return {"status": "error", **wiping}
    text = (request.text or "").strip()
    if not text:
        return {"ok": False, "status": "error", "message": "No text to speak.", "error": "empty_text"}

    profile_name = s.get_last_active_profile()
    try:
        config = s.load_profile(profile_name)
    except Exception:
        config = {}

    voice_id, speed, blend, modulation = s._resolve_voice_and_modulation(request, config)
    logging.info(f"TTS Request: {s.redact_user_text(text)} | Voice: {voice_id} | Speed: {speed}x")

    engine = await run_in_threadpool(s.ensure_tts_initialized)
    if engine is None:
        message = "TTS engine is not available."
        s.record_runtime_error("tts", message, {"action": "tts_speak"})
        return {"ok": False, "status": "error", "message": message, "error": "tts_unavailable"}

    try:
        with s.model_runtime.read_lease("tts"):
            result = await run_in_threadpool(
                engine.speak, text, speed=speed, voice_hint=voice_id, blend=blend, modulation=modulation
            )
    except s.RuntimeBusyError:
        return {"ok": False, "status": "error", "error": "tts_reconfiguring",
                "message": "TTS runtime is being reconfigured; retry shortly."}
    result["status"] = "success" if result.get("ok") else "error"
    return result

@router.post("/tts/stop")
async def stop_tts_route():
    import server as s

    if s.tts_engine is not None:
        try:
            s.tts_engine.stop_current()
            s.broadcast_status_threadsafe("draft_tts_stopped", {"message": "TTS stopped manually."})
            return {"ok": True, "message": "TTS playback stopped."}
        except Exception as e:
            return {"ok": False, "message": f"Failed to stop TTS: {e}"}
    return {"ok": True, "message": "TTS engine not active."}

@router.get("/runtime/tts-status")
async def get_tts_status():
    import server as s

    engine = s.tts_engine

    import platform
    is_linux = (platform.system().lower() == "linux")
    libsndfile_missing = False
    libsndfile_error = ""

    try:
        import sounddevice as sd
    except Exception as e:
        if is_linux and ("sndfile" in str(e).lower() or "libsndfile" in str(e).lower() or "not found" in str(e).lower() or "cannot open shared object file" in str(e).lower()):
            libsndfile_missing = True
        libsndfile_error = str(e)

    if engine is None:
        msg = f"Failed to instantiate TTS engine: {libsndfile_error}" if libsndfile_error else "TTS engine is not available."
        if libsndfile_missing:
            msg = f"Linux system package dependency failure: libsndfile1 is missing ({libsndfile_error}). Run 'sudo apt-get install libsndfile1' to resolve."
        return {
            "ok": False,
            "backend": "unavailable",
            "fallback": False,
            "message": msg,
            "libsndfile_missing": libsndfile_missing,
            "libsndfile_error": libsndfile_error
        }

    getter = getattr(engine, "get_status_snapshot", None)
    if callable(getter):
        status = getter()
        capabilities = status["capabilities"]
    else:
        # Legacy adapters only; real engines never touch a model lock here.
        status = await run_in_threadpool(s._snapshot_tts_status, engine)
        get_capabilities = getattr(engine, "get_capabilities", None)
        capabilities = await run_in_threadpool(get_capabilities) if callable(get_capabilities) else None
    backend_val = status["backend"]

    backend_name = "unavailable"
    if backend_val == "kokoro":
        backend_name = "Kokoro"
    elif backend_val == "kokoro_onnx":
        backend_name = "ONNX"
    elif backend_val == "sapi":
        backend_name = "SAPI fallback"

    msg = status["status_message"]
    if libsndfile_missing:
        msg = f"Linux system package dependency failure: libsndfile1 is missing ({libsndfile_error}). Run 'sudo apt-get install libsndfile1' to resolve."
        backend_name = "unavailable"

    return {
        "ok": status["loaded"] and not libsndfile_missing,
        "backend": backend_name,
        "raw_backend": backend_val,
        "fallback": status["fallback"],
        "message": msg,
        "libsndfile_missing": libsndfile_missing,
        "libsndfile_error": libsndfile_error if libsndfile_missing else None,
        "capabilities": capabilities,
    }

@router.post("/tts/clone")
async def tts_clone(file: UploadFile = File(...), name: str = Form("My Voice"), consent: bool = Form(...)):
    """Save an uploaded sample as a clone source, gated on explicit consent
    and basic quality checks (voice_clone_qa). This does NOT perform actual
    voice-cloning synthesis — no cloning engine is installed (see
    DESIGN.md §10 M5 cloning / its kokoclone note); it only gates
    and tags what gets saved, so a real engine can be wired in later without
    revisiting this validation/consent layer.
    """
    import server as s

    import json

    if not consent:
        raise HTTPException(
            status_code=400,
            detail="Voice cloning requires explicit consent that you own this voice or have permission to clone it.",
        )

    safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '_', '-')]).strip().replace(" ", "_")
    if not safe_name:
        raise HTTPException(status_code=400, detail="A voice name is required.")

    voices_dir = s.ensure_voices_dir()
    target_path = voices_dir / f"cloned_{safe_name}.wav"
    tmp_path = None
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tmp_path = tmp.name
        tmp.close()
        # Bounded, signature-checked, duration-limited upload.
        try:
            s.upload_safety.stream_to_file(file.file, tmp_path, s.upload_safety.MAX_AUDIO_BYTES)
            s.upload_safety.validate_signature(tmp_path, "audio")
            s.upload_safety.validate_wav_duration(tmp_path)
        except s.upload_safety.UploadTooLarge as exc:
            raise HTTPException(status_code=413, detail=f"Voice sample too large (max {exc.limit} bytes).")
        except s.upload_safety.UploadRejected as exc:
            raise HTTPException(status_code=400, detail=f"Invalid voice sample: {exc}")

        ok, warnings = s.voice_clone_qa.check_file(tmp_path)
        if not ok:
            raise HTTPException(
                status_code=400,
                detail={"message": "Sample failed quality checks.", "warnings": warnings},
            )

        shutil.move(tmp_path, target_path)
        tmp_path = None

        meta = {
            "cloned_voice": True,
            "consent": True,
            "qa": {"warnings": warnings},
            "created_at": s.datetime.now(s.timezone.utc).isoformat(),
        }
        meta_path = voices_dir / f"cloned_{safe_name}.meta.json"
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(meta, handle, indent=2)

        logging.info(f"Voice cloned: {safe_name} saved to {target_path}")
        return {"status": "success", "voice_id": f"cloned_{safe_name}", "path": str(target_path), "warnings": warnings}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Cloning failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

@router.get("/tts/voices")
async def list_voices():
    import server as s

    import json

    voices_dir = s.get_voices_path()

    cloned = []
    if os.path.exists(voices_dir):
        for f in os.listdir(voices_dir):
            if f.endswith(".wav") or f.endswith(".npy"):
                voice_id = f.split('.')[0]
                entry = {"id": voice_id, "name": voice_id.replace("cloned_", "").replace("_", " ")}
                meta_path = os.path.join(voices_dir, f"{voice_id}.meta.json")
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as handle:
                            entry["meta"] = json.load(handle)
                    except (OSError, ValueError):
                        pass
                cloned.append(entry)

    defaults = [
        {"id": "af_heart", "name": "Kokoro Heart"},
        {"id": "af_bella", "name": "Kokoro Bella"},
        {"id": "af_nicole", "name": "Kokoro Nicole"},
        {"id": "af_sarah", "name": "Kokoro Sarah"},
        {"id": "am_puck", "name": "Kokoro Puck"},
        {"id": "am_michael", "name": "Kokoro Michael"},
        {"id": "bf_emma", "name": "Kokoro Emma"},
        {"id": "bm_george", "name": "Kokoro George"},
        {"id": "standard_female", "name": "Standard Female (Kokoro Heart)"},
        {"id": "standard_male", "name": "Standard Male (Kokoro Puck)"},
    ]

    from backend.tts import voice_clone_engine
    return {"defaults": defaults, "cloned": cloned,
            "cloning": voice_clone_engine.availability()}


@router.get("/tts/clone/status")
async def get_voice_clone_status():
    """Cloning-runtime status for the models/settings UI: whether cloned-voice
    synthesis can run right now, why not if it can't, and whether the optional
    side-runtime has already been provisioned. availability() does real
    imports (torch/kanade_tokenizer) as its check, so — like every other
    availability-probing route here — it runs in a threadpool rather than
    blocking the event loop.
    """
    from backend.tts import voice_clone_engine
    status = await run_in_threadpool(voice_clone_engine.availability)
    return {
        "ok": True,
        "available": status["available"],
        "reason": status["reason"],
        "setup_hint": status["setup_hint"],
        "mechanism": status["mechanism"],
        "provisioned": voice_clone_engine.is_clone_runtime_provisioned(),
    }


@router.post("/tts/clone/provision")
async def provision_voice_cloning():
    """Provision the optional voice-cloning runtime on demand (models-page
    "Install voice cloning" card). Replaces the old "run tools/setup_voice_
    cloning.py" CLI hint — that path can't work inside a packaged app. Runs the
    download-verify-extract in a threadpool (it's I/O + subprocess-bound) and
    always returns the fresh availability() so the card re-renders truthfully.
    provision_clone_runtime() refuses cleanly (ok=False + message) when the
    platform has no catalog entry or the artifact isn't published yet, so this
    route never raises for the not-ready case."""
    from backend.tts import voice_clone_engine
    result = await run_in_threadpool(voice_clone_engine.provision_clone_runtime)
    return {**result, "cloning": voice_clone_engine.availability()}


@router.delete("/tts/voices/{voice_id}")
async def delete_cloned_voice(voice_id: str):
    """Immediately delete a cloned voice (sample + provenance metadata).

    Required by the cloning consent/abuse controls (DESIGN §10 M5 U6): a user
    must be able to remove a cloned voice without a full privacy wipe. Only the
    cloned_* namespace is deletable — built-in voices are not files on disk.
    """
    import server as s

    safe = os.path.basename(str(voice_id or "").strip())
    if not safe.startswith("cloned_") or safe != voice_id.strip():
        raise HTTPException(status_code=400, detail="Only cloned voices (cloned_*) can be deleted.")
    voices_dir = s.get_voices_path()
    removed = []
    for suffix in (".wav", ".npy", ".meta.json"):
        path = os.path.join(str(voices_dir), f"{safe}{suffix}")
        try:
            if os.path.exists(path):
                os.remove(path)
                removed.append(os.path.basename(path))
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Could not delete {os.path.basename(path)}: {exc}")
    if not removed:
        raise HTTPException(status_code=404, detail=f"Cloned voice '{safe}' not found.")
    logging.info(f"Deleted cloned voice {safe}: {removed}")
    return {"ok": True, "voice_id": safe, "removed": removed}
