"""Wake-word routes: enable/disable, model catalog + download/import, and a
short live-test window (Tier-3 M3). Mirrors routes_foundry.py's structure --
a self-contained router registered via ``app.include_router`` in server.py.

Module-level singleton state (one WakeListener per process, like
routes_foundry.py's ``_foundry_sessions``): nothing here needs to survive a
process restart -- ``wake_word_enabled`` and the chosen model live in the
profile, so re-enabling on next launch is just the UI calling /wake/enable
again on startup.

Runtime-capable by design (orchestrator amendment to the Phase 0 design):
service/listener construction happens in /wake/enable, not at app startup,
so enabling wake word never needs a restart. :func:`stop_wake_listener` is
the single quiesce hook -- /wake/disable calls it, and so does the
privacy-wipe path (server.py), so wiping data always leaves no live mic
stream rather than merely a paused one.
"""
import logging
import os
import tempfile
import threading
import time
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

router = APIRouter()

_lock = threading.Lock()
_listener = None  # wake_word.WakeListener, once enabled
_status_reason = "disabled"

# Each entry is a state dict, NOT a bare Thread, so a failed download leaves a
# durable, queryable record instead of vanishing into the server log the moment
# the thread exits. Shape:
#   {"thread": Thread|None, "status": "running"|"complete"|"failed",
#    "error": str|None, "verified": bool}
# The thread is retained only to answer is_alive(); it is never removed on
# failure (only replaced when a fresh download for the same id is started).
_download_jobs = {}
_download_jobs_lock = threading.Lock()


def _download_job_active(job):
    thread = job.get("thread") if job else None
    return bool(thread and thread.is_alive())


def _profile_config():
    from utils import get_last_active_profile, load_profile

    return load_profile(get_last_active_profile())


def _persist_profile_fields(fields: dict):
    """Best-effort profile write. A persistence failure must never undo an
    already-started/stopped listener -- caller state changes first, this
    just tries to make the UI's next load reflect it."""
    try:
        from utils import get_last_active_profile, load_profile, save_profile

        profile_name = get_last_active_profile()
        cfg = load_profile(profile_name)
        cfg.update(fields)
        save_profile(profile_name, cfg)
    except Exception as exc:
        logging.warning(f"Wake-word: profile persistence failed (state change still applied): {exc}")


def is_wake_listening():
    return bool(_listener and _listener.is_listening())


def stop_wake_listener():
    """Full quiesce: close the mic stream if running. Idempotent. Called by
    /wake/disable AND server.py's privacy-wipe path (mirrors how that path
    drains the recorder) -- always safe to call even if never enabled."""
    global _listener, _status_reason
    with _lock:
        listener = _listener
        _listener = None
        _status_reason = "disabled"
    if listener is not None:
        listener.stop()
    return True


class WakeEnableRequest(BaseModel):
    classifier_id: Optional[str] = None
    classifier_origin: str = "bundled"
    threshold: Optional[float] = None
    cooldown_ms: Optional[int] = None
    device_index: Optional[int] = None


class WakeTestRequest(BaseModel):
    duration_s: float = 10.0


class WakeTrainRequest(BaseModel):
    phrase: str
    voices: Optional[list] = None
    # The user's own recordings of the phrase (positive) and of other speech
    # (negative), as base64-encoded 16-bit PCM WAV. These are the anchor of a
    # good model; Kokoro synthetics only augment them. Optional so a
    # Kokoro-only run still works, but the UI is expected to supply several.
    positive_clips: Optional[list] = None
    negative_clips: Optional[list] = None


# Wake-phrase training runs in a background thread (synthetic-sample generation
# via Kokoro is seconds-to-a-minute of TTS, too long to block the request).
# One training run at a time; the UI polls GET /wake/train/status.
_training_lock = threading.Lock()
_training_state = {"status": "idle", "percent": 0, "message": "", "result": None}


@router.get("/wake/status")
async def wake_status():
    with _lock:
        listener = _listener
        reason = _status_reason
    if listener is None:
        return {"enabled": False, "available": False, "listening": False, "reason": reason}
    status = listener.status()
    status["enabled"] = True
    status["available"] = True
    status["reason"] = reason
    return status


@router.post("/wake/enable")
async def wake_enable(request: WakeEnableRequest):
    import wake_word

    global _listener, _status_reason

    with _lock:
        if _listener is not None and _listener.is_listening():
            status = _listener.status()
            status.update({"ok": True, "already_enabled": True, "enabled": True, "available": True})
            return status

    config = _profile_config()
    classifier_id = request.classifier_id or (config.get("wake_word_model") or None) or None
    threshold = (
        request.threshold
        if request.threshold is not None
        else float(config.get("wake_word_sensitivity", wake_word.DEFAULT_THRESHOLD))
    )
    cooldown_ms = (
        request.cooldown_ms
        if request.cooldown_ms is not None
        else int(float(config.get("wake_word_cooldown_s", wake_word.DEFAULT_COOLDOWN_MS / 1000.0)) * 1000)
    )

    detector, available, reason = wake_word.build_openwakeword_detector(
        classifier_id=classifier_id, classifier_origin=request.classifier_origin
    )
    if not available:
        return {"ok": False, "enabled": False, "available": False, "listening": False, "reason": reason}

    def on_detect():
        # The SAME entry point keyboard/controller triggers use -- no
        # duplicated recording-start logic (D2 requirement).
        import server

        manager = server.hotkey_manager
        if manager is not None:
            manager.request_start(reason="wake_word")
        else:
            logging.warning("Wake word triggered but no hotkey manager is running; ignoring.")

    service = wake_word.WakeWordService(detector, on_detect=on_detect, threshold=threshold, cooldown_ms=cooldown_ms)
    listener = wake_word.WakeListener(service, device_index=request.device_index)
    if not listener.start():
        return {
            "ok": False,
            "enabled": False,
            "available": False,
            "listening": False,
            "reason": "unavailable: microphone stream failed to start",
        }

    with _lock:
        _listener = listener
        _status_reason = "ready"

    fields = {"wake_word_enabled": True, "wake_word_sensitivity": threshold, "wake_word_cooldown_s": cooldown_ms / 1000.0}
    if classifier_id:
        fields["wake_word_model"] = classifier_id
    _persist_profile_fields(fields)

    status = listener.status()
    status.update({"ok": True, "enabled": True, "available": True})
    return status


@router.post("/wake/disable")
async def wake_disable():
    stop_wake_listener()
    _persist_profile_fields({"wake_word_enabled": False})
    return {"ok": True, "enabled": False, "listening": False}


@router.get("/wake/models")
async def wake_models_list():
    import wake_models

    return {"models": wake_models.list_wake_models()}


@router.post("/wake/models/{model_id}/download")
def wake_model_download(model_id: str):
    import wake_models

    if model_id not in wake_models.AVAILABLE_WAKE_MODELS:
        raise HTTPException(status_code=400, detail="Unknown wake model id")

    with _download_jobs_lock:
        job = _download_jobs.get(model_id)
        if _download_job_active(job):
            return {"ok": True, "model_id": model_id, "background": True, "already_running": True}

        def run_download():
            error = None
            try:
                wake_models.download_wake_model(model_id)
            except Exception as exc:
                # The phrase is user-agnostic (a model id + failure), so it is
                # safe to log; keep the detail for the state record too.
                logging.error(f"Background wake model download failed for {model_id}: {exc}")
                error = str(exc)
            with _download_jobs_lock:
                current = _download_jobs.get(model_id)
                # Only the job we own writes its own terminal state (a newer
                # download started for the same id supersedes us).
                if current is not None and current.get("thread") is threading.current_thread():
                    if error is None:
                        current["status"] = "complete"
                        current["error"] = None
                        # Confirm the just-downloaded file is truthfully usable,
                        # not merely present (download_wake_model already checks
                        # the sha, but loadability is what "verified" promises).
                        current["verified"] = wake_models.backbone_status(model_id).get("loadable", False)
                    else:
                        current["status"] = "failed"
                        current["error"] = error
                        current["verified"] = False

        thread = threading.Thread(target=run_download, name=f"wake-download-{model_id}", daemon=True)
        _download_jobs[model_id] = {"thread": thread, "status": "running", "error": None, "verified": False}
        thread.start()

    return {"ok": True, "model_id": model_id, "background": True}


@router.get("/wake/models/{model_id}/download-state")
async def wake_model_download_state(model_id: str):
    import wake_models

    with _download_jobs_lock:
        job = _download_jobs.get(model_id)
        active = _download_job_active(job)
        # A failed download's record survives its thread, so the UI can show
        # WHY the file isn't there instead of silently reverting to "Download".
        last_error = job.get("error") if (job and not active) else None
        last_status = job.get("status") if job else None

    if model_id in wake_models.AVAILABLE_WAKE_MODELS:
        status = wake_models.backbone_status(model_id)
    else:
        status = {"downloaded": False, "verified": False, "loadable": False, "error": "unknown_model"}

    return {
        "model_id": model_id,
        "active": active,
        # "downloaded" now means truthfully present-and-loadable, not just an
        # existing file (a corrupt/unloadable file reports downloaded=False).
        "downloaded": bool(status["loadable"]),
        "present": bool(status["downloaded"]),
        "verified": bool(status["verified"]),
        "loadable": bool(status["loadable"]),
        # Prefer the download job's recorded failure (the root cause, e.g.
        # "network down") over the status probe's symptom ("missing").
        "error": last_error or status["error"],
        "last_status": last_status,
    }


@router.post("/wake/models/import")
async def wake_model_import(name: str = Form(...), file: UploadFile = File(...)):
    import wake_models

    suffix = os.path.splitext(file.filename or "")[1] or ".onnx"
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(await file.read())
        entry = wake_models.import_wake_model(name, tmp_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
    return entry


@router.delete("/wake/models/{model_id}")
async def wake_model_delete(model_id: str):
    import wake_models

    if not wake_models.remove_imported_model(model_id):
        raise HTTPException(status_code=404, detail="Unknown imported wake model")
    return {"ok": True}


@router.post("/wake/test")
async def wake_test(request: WakeTestRequest = None):
    """Arm a test window and report score peaks -- powers the UI's live
    tester. Reuses the currently-enabled listener when there is one;
    otherwise spins up a temporary listener for just the test window and
    tears it down afterward (never left running, never persists anything)."""
    import wake_word

    duration_s = max(0.0, float((request or WakeTestRequest()).duration_s))

    with _lock:
        existing = _listener

    temporary = None
    listener = existing
    if listener is None or not listener.is_listening():
        config = _profile_config()
        classifier_id = config.get("wake_word_model") or None
        detector, available, reason = wake_word.build_openwakeword_detector(classifier_id=classifier_id)
        if not available:
            return {"ok": False, "reason": reason}
        service = wake_word.WakeWordService(detector, on_detect=lambda: None)
        temporary = wake_word.WakeListener(service)
        if not temporary.start():
            return {"ok": False, "reason": "unavailable: microphone stream failed to start"}
        listener = temporary

    start_index = len(listener.service.score_log)
    try:
        await run_in_threadpool(time.sleep, duration_s)
        scores = [entry["score"] for entry in listener.service.score_log[start_index:]]
    finally:
        if temporary is not None:
            temporary.stop()

    return {
        "ok": True,
        "duration_s": duration_s,
        "sample_count": len(scores),
        "peak_score": max(scores) if scores else 0.0,
        "scores": scores[-50:],
    }


def _decode_wav_clips(clips):
    """Decode a list of base64-encoded 16-bit PCM WAV strings into float32 mono
    16 kHz clips (the shape wake_training_data expects). Returns None for an
    empty input; raises ValueError with an actionable reason on a bad clip so
    the route can answer 400 rather than corrupting the training set."""
    if not clips:
        return None

    import base64
    import io
    import wave

    import numpy as np

    import wake_training_service

    decoded = []
    for index, item in enumerate(clips):
        try:
            raw = base64.b64decode(item, validate=True) if isinstance(item, str) else bytes(item)
            with wave.open(io.BytesIO(raw), "rb") as handle:
                sample_rate = handle.getframerate()
                channels = handle.getnchannels()
                sample_width = handle.getsampwidth()
                frames = handle.readframes(handle.getnframes())
        except Exception as exc:
            raise ValueError(f"clip {index} is not a readable WAV: {exc}")
        if sample_width != 2:
            raise ValueError(f"clip {index}: expected 16-bit PCM, got sample_width={sample_width}")
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if channels > 1:
            audio = audio.reshape(-1, channels).mean(axis=1)
        audio = wake_training_service._resample_to_16k(audio, int(sample_rate or 16000))
        if audio.size:
            decoded.append(audio)
    return decoded or None


@router.post("/wake/train")
async def wake_train(request: WakeTrainRequest):
    """Kick off a background wake-phrase training run: mix the user's own
    recordings (the anchor) with Kokoro-synthesized renderings of the phrase (+
    decoy negatives), train a NumPy classifier head on the shared Apache-2.0
    backbone, calibrate a threshold + reliability verdict, and register the
    result as a selectable trained classifier. The phrase itself is user
    content, so it is never written to the server log.

    Readiness is verified up front (backbones loadable + Kokoro actually
    loaded): the exact blocker is returned immediately, before the background
    thread spends up to a minute synthesizing audio that would otherwise fail
    with a generic empty-class error."""
    import server
    import wake_training_service

    phrase = (request.phrase or "").strip()
    if not phrase:
        raise HTTPException(status_code=400, detail="Enter a wake phrase to train.")

    # Cheap guard first: don't load Kokoro just to reject a concurrent run.
    with _training_lock:
        if _training_state["status"] == "running":
            return {"ok": False, "already_running": True,
                    "message": "A training run is already in progress."}

    # Decode recordings (cheap, and a bad payload should 400 regardless of
    # engine state).
    try:
        user_positive_clips = _decode_wav_clips(request.positive_clips)
        user_negative_clips = _decode_wav_clips(request.negative_clips)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Bad recording: {exc}")

    # Preflight in a threadpool (Kokoro's load can be slow -- don't block the
    # event loop). Returns the exact failure NOW instead of a minute from now.
    engine = await run_in_threadpool(server.ensure_tts_initialized)
    preflight = await run_in_threadpool(wake_training_service.preflight_training, engine)
    if not preflight["ok"]:
        return {"ok": False, "message": preflight["message"]}

    with _training_lock:
        # Re-check under the lock: a run could have started during preflight.
        if _training_state["status"] == "running":
            return {"ok": False, "already_running": True,
                    "message": "A training run is already in progress."}
        _training_state.update({"status": "running", "percent": 0,
                                "message": "Starting…", "result": None})

    voices = request.voices

    def _run():
        def progress(payload):
            with _training_lock:
                _training_state["percent"] = int(payload.get("percent", 0))
                _training_state["message"] = str(payload.get("message", ""))

        try:
            result = wake_training_service.train_phrase_model(
                phrase, engine=engine, voices=voices,
                user_positive_clips=user_positive_clips,
                user_negative_clips=user_negative_clips,
                progress=progress,
            )
        except Exception:
            logging.exception("Wake-phrase training crashed")
            result = {"ok": False, "message": "Training failed unexpectedly (see server log)."}
        with _training_lock:
            _training_state.update({"status": "done", "percent": 100, "result": result})

    threading.Thread(target=_run, name="wake-train", daemon=True).start()
    return {"ok": True, "started": True}


@router.get("/wake/train/status")
async def wake_train_status():
    """Current/last training run state: {status: idle|running|done, percent,
    message, result?} — result is train_phrase_model's payload once done."""
    with _training_lock:
        return dict(_training_state)
