"""Model-management routes lifted out of server.py (R6): hardware tier and model
recommendation, the LLM model catalogue (list/select/download/delete/
download-state), the Whisper models (list/download/delete/test/select) and
``/models/unload/{component}`` (14 routes).

These routes trigger real downloads and model loads, so they are moved with no
change in what they call or in what order:

* The routes themselves rebind NO server global. The one ``global transcriber,
  tts_engine`` in this area lives in ``_unload_model_component_locked``, a
  helper (not a route) that stays in server.py, so ``/models/unload/{component}``
  stays a thin route that calls ``s._unload_model_component_locked`` under the
  same ``model_runtime`` write lease.
* ``select_llm_model`` and ``select_whisper_model`` call ``list_llm_models`` /
  ``list_whisper_models`` directly, as they always did; both now live in this
  module, so the calls are module-local.
* ``test_whisper`` builds its probe through ``s.Transcriber`` so the many tests
  that patch ``server.Transcriber`` still apply.
* ``download_llm_model`` stays a plain ``def`` (FastAPI runs it in a worker
  thread) and its background-thread closure reads ``s.check_and_download_resources``
  at the time the thread runs, exactly like the old global lookup.
* ``backend/api/routes/models_resources.py`` (``GET /models/resources``) is a
  separate router and is intentionally not merged here.

Same strangler shape as dev.py, settings.py, history.py and diagnostics.py:
``server`` stays the owner of all state and helpers and is imported lazily
inside each handler (``import server as s``), because server.py imports this
module near the end of its own load and a top-level ``import server`` here would
be a partially initialized circular import. Every server name is read as
``s.<name>`` at call time, so ``patch.object(server, ...)`` in tests still lands.
The two request models are used only by these routes, so they live here.
Registered via ``app.include_router`` at the end of server.py.
"""
import logging
import os
import threading

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

router = APIRouter()


@router.get("/hardware/tier")
async def hardware_tier():
    import server as s

    return {"ok": True, "tier": s.get_hardware_tier()}


@router.get("/models/recommend")
async def models_recommend():
    import server as s

    from backend.models import model_recommender

    report = s.get_hardware_report()
    tier_info = s.get_hardware_tier(report=report)
    ram_mb = (report.get("memory") or {}).get("total_mb") or 0
    recommendation = model_recommender.recommend(tier_info["tier"], ram_mb)
    recommendation["tier_label"] = tier_info.get("label")
    recommendation["tier_guidance"] = tier_info.get("guidance")
    return {"ok": True, "recommendation": recommendation}


class LlmModelSelectRequest(BaseModel):
    model_id: str


class WhisperModelRequest(BaseModel):
    model_size: str
    prefer_gpu: bool = True


@router.get("/models/llm")
async def list_llm_models():
    import server as s

    selected = s.get_selected_llm_model_id()
    models = []
    for model_id, info in s.AVAILABLE_MODELS.items():
        model_path = s.get_model_path(model_id)
        download_state = s.get_download_state(model_id)
        file_status = s.get_model_file_status(model_id)
        with s._llm_download_jobs_lock:
            job = s._llm_download_jobs.get(model_id)
            download_active = bool(job and job.is_alive())
        download_state["active"] = download_active
        download_state["file_status"] = file_status
        models.append(
            {
                "id": model_id,
                "selected": model_id == selected,
                "installed": s.check_model_exists(model_id),
                "ready": s.is_llm_model_ready(model_id),
                "path": model_path,
                "file_status": file_status,
                "download_state": download_state,
                "download_active": download_active,
                "partial_bytes": download_state.get("partial_bytes", 0),
                "resumable": bool(download_state.get("resumable")),
                **info,
            }
        )
    return {
        "selected_model_id": selected,
        "models": models,
        "download_state": s.get_download_state(selected),
        "llama_server_path": s.get_server_path(),
        "llama_server_exists": os.path.exists(s.get_server_path()),
    }


@router.post("/models/llm/select")
async def select_llm_model(request: LlmModelSelectRequest, force: int = 0):
    import server as s

    if request.model_id not in s.AVAILABLE_MODELS:
        raise HTTPException(status_code=400, detail="Unsupported LLM model")
    # Switching the model reconfigures the LLM runtime — take the exclusive
    # lease so it can't race an in-flight completion (409 if busy).
    try:
        with s.model_runtime.write_lease("llm", wait=bool(force), timeout=15.0):
            profile_name = s.get_last_active_profile()
            cfg = s.load_profile(profile_name)
            cfg["llm_model_id"] = request.model_id
            s.save_runtime_profile(profile_name, cfg)
            engine = s.get_engine_if_initialized()
            if engine is not None:
                engine.set_model_id(request.model_id)
    except s.RuntimeBusyError:
        raise HTTPException(status_code=409, detail="LLM is busy with active inference. Retry, or pass force=1.")
    return await list_llm_models()


@router.post("/models/llm/{model_id}/download")
def download_llm_model(model_id: str):
    import server as s

    if model_id not in s.AVAILABLE_MODELS:
        raise HTTPException(status_code=400, detail="Unsupported LLM model")
    with s._llm_download_jobs_lock:
        job = s._llm_download_jobs.get(model_id)
        if job and job.is_alive():
            state = s.get_download_state(model_id)
            return {
                "ok": True,
                "model_id": model_id,
                "background": True,
                "already_running": True,
                "message": state.get("message") or "Download is already running in the background.",
                "state": state,
            }

        def run_download():
            try:
                s.check_and_download_resources(model_id)
            except Exception as exc:
                logging.error("Background LLM download failed for %s: %s", model_id, exc)
            finally:
                with s._llm_download_jobs_lock:
                    current = s._llm_download_jobs.get(model_id)
                    if current is threading.current_thread():
                        s._llm_download_jobs.pop(model_id, None)

        thread = threading.Thread(target=run_download, name=f"llm-download-{model_id}", daemon=True)
        s._llm_download_jobs[model_id] = thread
        thread.start()

    return {
        "ok": True,
        "model_id": model_id,
        "background": True,
        "message": f"Started background download for {s.AVAILABLE_MODELS[model_id]['name']}.",
        "state": s.get_download_state(model_id),
    }


@router.delete("/models/llm/{model_id}")
async def delete_llm_model(model_id: str, force: int = 0):
    import server as s

    if model_id not in s.AVAILABLE_MODELS:
        raise HTTPException(status_code=400, detail="Unsupported LLM model")
    with s._llm_download_jobs_lock:
        job = s._llm_download_jobs.get(model_id)
        if job and job.is_alive():
            raise HTTPException(status_code=409, detail="That model is downloading. Wait for it to finish or restart the app before deleting it.")
    # Deleting model files must not race an active LLM inference reading them.
    try:
        with s.model_runtime.write_lease("llm", wait=bool(force), timeout=15.0):
            ok, message = s.delete_model(model_id)
    except s.RuntimeBusyError:
        raise HTTPException(status_code=409, detail="LLM is busy with active inference. Retry, or pass force=1.")
    return {"ok": ok, "model_id": model_id, "message": message}


@router.get("/models/llm/{model_id}/download-state")
async def llm_download_state(model_id: str):
    import server as s

    if model_id not in s.AVAILABLE_MODELS:
        raise HTTPException(status_code=400, detail="Unsupported LLM model")
    state = s.get_download_state(model_id)
    state["file_status"] = s.get_model_file_status(model_id)
    with s._llm_download_jobs_lock:
        job = s._llm_download_jobs.get(model_id)
        active = bool(job and job.is_alive())
    state["active"] = active
    if active and state.get("status") in (None, "", "error"):
        state["status"] = "downloading"
    return state


@router.get("/models/whisper")
async def list_whisper_models():
    import server as s

    selected = str(s.load_profile(s.get_last_active_profile()).get("model_size", "base.en") or "base.en").strip()
    return {
        "selected_model_size": selected,
        "supported": list(s.SUPPORTED_MODEL_SIZES),
        "models": s.list_cached_models(),
        "download_state": s.get_whisper_download_state(selected),
    }


@router.post("/models/whisper/download")
def download_whisper(request: WhisperModelRequest):
    import server as s

    result = s.download_whisper_model(request.model_size, prefer_gpu=request.prefer_gpu)
    return result


@router.delete("/models/whisper/{model_size}")
async def delete_whisper(model_size: str):
    import server as s

    result = s.remove_cached_model(model_size)
    if s.transcriber is not None and getattr(s.transcriber, "model_size", "") == model_size:
        s.transcriber.unload()
    return result


@router.post("/models/whisper/test")
def test_whisper(request: WhisperModelRequest):
    import server as s

    if request.model_size not in s.SUPPORTED_MODEL_SIZES:
        return {"ok": False, "message": f"Unsupported Whisper model: {request.model_size}"}
    try:
        probe = s.Transcriber(profile_name=s.get_last_active_profile(), preload=False)
        probe.model_size = request.model_size
        ok = probe.ensure_loaded()
        probe.unload()
        return {"ok": bool(ok), "message": f"Whisper {request.model_size} {'loaded' if ok else 'failed to load'}."}
    except Exception as exc:
        logging.exception("Whisper test failed")
        return {"ok": False, "message": str(exc)}


@router.post("/models/whisper/select")
async def select_whisper_model(request: WhisperModelRequest):
    import server as s

    if request.model_size not in s.SUPPORTED_MODEL_SIZES:
        raise HTTPException(status_code=400, detail="Unsupported Whisper model")
    # The active Whisper model is the active profile's `model_size`; persist the
    # choice there and reload the live transcriber so it takes effect immediately.
    profile_name = s.get_last_active_profile()
    cfg = s.load_profile(profile_name)
    cfg["model_size"] = request.model_size
    s.save_runtime_profile(profile_name, cfg)
    if s.transcriber is not None:
        s.transcriber.reload_profile(profile_name)
    return await list_whisper_models()


@router.post("/models/unload/{component}")
async def unload_model_component(component: str, force: int = 0):
    """Release a model component's memory under an exclusive runtime lease.

    Returns 409 if inference is active on that runtime (a destructive drop must
    not race an in-flight request); pass ?force=1 to cancel-and-wait for active
    inference to drain first.
    """
    import server as s

    normalized = component.strip().lower()
    if normalized not in ("stt", "llm", "tts"):
        raise HTTPException(status_code=400, detail="Unsupported component")
    try:
        with s.model_runtime.write_lease(normalized, wait=bool(force), timeout=15.0):
            return await run_in_threadpool(s._unload_model_component_locked, normalized)
    except s.RuntimeBusyError:
        raise HTTPException(
            status_code=409,
            detail=f"{normalized.upper()} is in use by active inference. Retry, or pass force=1 to wait.",
        )
