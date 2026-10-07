"""Diagnostics and runtime-info routes lifted out of server.py (R5): version, audio
devices, doctor, health, runtime status/output-settings, capabilities, audio
status, metrics, jobs, logs/paths, runtime errors and the support report (17
routes).

Behaviour is moved, not changed. In particular:

* ``/health`` keeps its exact path, method and body. The auth middleware in
  server.py matches by PATH (only ``/ws/`` is exempt), so ``/health`` still
  requires the sidecar token whenever one is set, exactly as before.
* Status reads observe separately published engine snapshots, independently
  of model loading. Heavy doctor probes run on worker threads.
* ``/runtime/version`` needs no server state, so it reads ``version`` directly
  (a top-level import of the root ``version.py``, same module object server.py
  uses) instead of ``s.version``. tests/test_version_source.py regex-checks the
  handler text in THIS file.
* ``gather_support_report`` (and its ``version_block``) is a helper shared with
  tests and docs, so it stays in server.py and is reached as
  ``s.gather_support_report``.

Same strangler shape as dev.py, settings.py and history.py: ``server`` stays the
owner of all state and helpers and is imported lazily inside each handler
(``import server as s``), because server.py imports this module near the end of
its own load and a top-level ``import server`` here would be a partially
initialized circular import. Every server name is read as ``s.<name>`` at call
time, so ``patch.object(server, ...)`` in tests still lands. Registered via
``app.include_router`` at the end of server.py.
"""
import os
import typing
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

import version

router = APIRouter()


@router.get("/runtime/version")
async def runtime_version():
    return {
        "backend_version": version.BACKEND_VERSION,
        "expected_electron_api_version": version.APP_VERSION,
        "schema_version": 1,
        "config_version": 1,
    }


@router.get("/runtime/audio-devices")
async def list_audio_devices():
    import server as s

    return s.get_audio_devices()


@router.post("/runtime/audio-devices/refresh")
async def refresh_audio_devices():
    import server as s

    return s.get_audio_devices(refresh=True)


@router.get("/doctor")
async def run_doctor(refresh_audio: bool = False):
    import server as s

    engine = s.get_engine_if_initialized()
    engine_ready = False
    model_id = None
    if engine is not None:
        try:
            engine_ready = bool(getattr(engine, "_ready", False))
            model_id = getattr(engine, "model_id", None)
        except Exception:
            pass

    # STT details
    # device/compute_type/device_fallback_reason reflect what the model ACTUALLY
    # loaded with (set in transcriber._load_model()), not just the user's
    # prefer_gpu setting -- e.g. on Windows without cuDNN, CUDA init fails and
    # this honestly reports device="cpu" instead of implying GPU acceleration.
    stt_status = s._transcriber_status_snapshot(s.transcriber)
    stt_info = {
        "initialized": s.transcriber is not None,
        "loaded": stt_status.get("constructed", False),
        "model_size": stt_status.get("model_size", getattr(s.transcriber, "model_size", None)),
        "constructed": stt_status.get("constructed", False),
        "probe_passed": stt_status.get("probe_passed", False),
        "inference_ready": stt_status.get("inference_ready", False),
        "error_code": stt_status.get("error_code"),
        "error_state": stt_status.get("error_state"),
        "device": stt_status.get("active_device"),
        "compute_type": stt_status.get("active_compute_type"),
        "device_fallback_reason": stt_status.get("device_fallback_reason"),
        "device_fallback_code": stt_status.get("device_fallback_code"),
        # Derived from the same published snapshot as the fields above (G3), so
        # Doctor and status can never disagree about a CUDA -> CPU fallback.
        "using_cpu_fallback": bool(stt_status.get("using_cpu_fallback", False)),
    }

    # LLM details. Diagnostics remain observation-only when AI cleanup is off;
    # in particular, this route never constructs the engine or downloads it.
    try:
        llm_enabled = bool(s.load_profile(s.get_last_active_profile()).get("llm_enabled", False))
    except Exception:
        llm_enabled = False
    selected_model_id = model_id or s.get_selected_llm_model_id()
    llama_server_path = str(s.get_server_path())
    llama_server_exists = os.path.exists(llama_server_path)
    model_exists = s.check_model_exists(selected_model_id)
    if not llm_enabled:
        runtime_validation = {"ok": False, "message": "AI cleanup is disabled."}
    elif llama_server_exists:
        runtime_validation = await run_in_threadpool(s.validate_llama_server_runtime, llama_server_path)
    else:
        runtime_validation = {"ok": False, "message": "llama-server binary is missing."}
    required_runtime_build = s.required_llama_server_build(selected_model_id)
    runtime_build = runtime_validation.get("build")
    runtime_build_ok = (
        not required_runtime_build
        or (runtime_build is not None and int(runtime_build) >= required_runtime_build)
    )
    llm_last_error = str(getattr(engine, "_last_error", "") or "") if engine else ""
    if not llm_enabled:
        llm_runtime_status = "disabled"
    elif not llama_server_exists:
        llm_runtime_status = "missing_llama_server"
    elif not model_exists:
        llm_runtime_status = "missing_model"
    elif runtime_validation.get("error_code") == "runtime_validation_timeout":
        llm_runtime_status = "runtime_validation_timeout"
    elif not runtime_validation.get("ok", False):
        llm_runtime_status = "runtime_link_failure"
    elif not runtime_build_ok:
        llm_runtime_status = "runtime_outdated"
    elif engine_ready:
        llm_runtime_status = "ready"
    elif llm_last_error:
        llm_runtime_status = "startup_failure"
    else:
        llm_runtime_status = "not_loaded"

    llm_info = {
        "enabled": llm_enabled,
        "initialized": engine is not None,
        "ready": engine_ready,
        "model_id": selected_model_id,
        "llama_server_path": llama_server_path,
        "llama_server_exists": llama_server_exists,
        "model_exists": model_exists,
        "runtime_status": llm_runtime_status,
        "runtime_valid": bool(runtime_validation.get("ok", False)),
        "runtime_compatible": bool(runtime_validation.get("ok", False) and runtime_build_ok),
        "runtime_build": runtime_build,
        "required_runtime_build": required_runtime_build,
        "runtime_validation_error_code": runtime_validation.get("error_code"),
        "runtime_validation_elapsed_sec": runtime_validation.get("elapsed_sec"),
        "runtime_validation_timeout_sec": runtime_validation.get("timeout_sec"),
        "runtime_message": runtime_validation.get("message", ""),
        "last_error": llm_last_error,
        "last_error_details": dict(getattr(engine, "_last_error_details", {}) or {}) if engine else {},
    }

    # TTS details are observation-only here. Diagnostics must never trigger a
    # model import, download, or initialization merely because a caller opened
    # the health panel; only report the singleton that is already present.
    tts_info = await run_in_threadpool(s._snapshot_tts_status, s.tts_engine)

    # Hotkeys details
    hotkeys_info = {
        "started": s.hotkey_manager_started,
        "active": s.hotkey_manager is not None and getattr(s.hotkey_manager, "_running", False),
        "keyboard_hooks_ok": bool(s.hotkey_manager is not None and not getattr(s.hotkey_manager, "keyboard_hook_errors", [])),
        "keyboard_hook_errors": list(getattr(s.hotkey_manager, "keyboard_hook_errors", [])) if s.hotkey_manager else [],
    }

    # Models dir
    model_dir = Path(s.get_model_path(s.DEFAULT_MODEL)).parent
    model_path_info = {
        "models_dir": str(model_dir),
        "models_dir_exists": os.path.exists(model_dir),
        "default_model_path": str(s.get_model_path(s.DEFAULT_MODEL)),
        "default_model_exists": os.path.exists(s.get_model_path(s.DEFAULT_MODEL)),
    }

    # Audio
    audio_info = await run_in_threadpool(s.get_audio_devices, refresh=refresh_audio)

    # Capabilities
    platform_info = await run_in_threadpool(s.get_capabilities)

    # Honest, freshly-checked (not cached-at-import) injection status: the
    # detected method, whether the CLI tool it depends on is actually present
    # right now, the session type, and injection_hint()'s guidance -- so e.g.
    # a Wayland user missing wl-clipboard sees why typing/paste won't work
    # instead of a silent no-op (DESIGN §7 injection matrix). This never
    # performs real injection -- it only re-runs shutil.which() PATH lookups
    # (see platform_capabilities.get_injection_status). The interactive,
    # actually-injecting probe in tools/injection_probe.py is a standalone
    # CLI script and is intentionally NOT wired into this route.
    injection_info = await run_in_threadpool(s.get_injection_status)

    # Hardware specs + model-fit assessment for the selected LLM
    hardware_info = await run_in_threadpool(s.get_hardware_report)
    model_fit_info = await run_in_threadpool(
        s.assess_model_fit, selected_model_id, report=hardware_info
    )
    hardware_tier_info = await run_in_threadpool(
        s.get_hardware_tier, report=hardware_info
    )

    # Recovery instructions
    recovery_guidelines = {
        "missing_model": "Go to the Models screen to download the recommended LLM or Whisper models, or verify that the GGUF/Whisper files exist in the models directory.",
        "missing_llama_server": "llama-server binary could not be found. If you are on Linux, please compile or install llama-server and set the BETTERFINGERS_LLAMA_SERVER environment variable.",
        "runtime_link_failure": "llama-server exists, but its shared runtime libraries are incomplete. Reinstall the runtime or repair the Linux .so symlinks in the models directory.",
        "runtime_outdated": "The selected model requires a newer llama.cpp runtime. Download or reinstall the LLM runtime from the Models screen.",
        "port_conflict": "Port 8000 is occupied by another process. Please close the conflicting application or configure a different port.",
        "microphone_unavailable": "No input audio devices were detected, or microphone permission was denied. Please connect a microphone and ensure BetterFingers has permission to access it.",
        # This fires on `is_wayland && !supports_input_injection`, and
        # supports_input_injection is False only when injection_method ==
        # "none" -- which platform_capabilities reaches solely when the
        # clipboard fallback ALSO failed (no wl-clipboard/xclip/xsel). The
        # previous text told that user "BetterFingers has safely fallen back
        # to copying text to the clipboard", i.e. it reassured them that the
        # one path that had also just failed was working. Nothing reaches the
        # target application in this state, so say so and give the install
        # that actually fixes it.
        "unsupported_wayland_injection": "Text cannot be delivered to other applications: this Wayland session has no typing tool (wtype or ydotool) and no clipboard tool (wl-clipboard), so both the typing path and the clipboard fallback are unavailable. Install wl-clipboard to restore copy-to-clipboard, and wtype (or ydotool) for direct typing; then restart BetterFingers. Dictation, transcription and drafts keep working — only delivery into another window is affected.",
        "failed_clipboard": "The clipboard manager is not responding. On Linux, ensure xclip or xsel is installed.",
        "failed_tts_dependency": "Sound playback dependencies are missing. Ensure libsndfile1 is installed on Linux."
    }

    return {
        "health": "active",
        "stt": stt_info,
        "llm": llm_info,
        "tts": tts_info,
        "hotkeys": hotkeys_info,
        "models": model_path_info,
        "audio": audio_info,
        "platform": platform_info,
        "injection": injection_info,
        "hardware": hardware_info,
        "hardware_tier": hardware_tier_info,
        "model_fit": model_fit_info,
        "recovery": recovery_guidelines,
        # Config-store quarantine/downgrade-refusal events (DESIGN §9.5, M4
        # B1/B2): a corrupt or too-new personas/voice_presets/profile/
        # app_state file is never silently dropped or destructively
        # overwritten -- this is the "visible warning" the downgrade policy
        # requires, queryable here in addition to the startup log line each
        # event already gets.
        "store_warnings": s.get_degraded_events(),
    }


@router.get("/health")
async def health_check():
    import server as s

    engine_ready = False
    try:
        engine = s.get_engine_if_initialized()
        engine_ready = bool(getattr(engine, "_ready", False)) if engine else False
    except Exception:
        pass

    # Active-job visibility for the supervisor: a busy backend is not a dead
    # backend. Everything here is in-memory — /health must stay free of model
    # loads, device scans, and filesystem walks.
    active_jobs = []
    last_progress_at = None
    try:
        active_jobs = s.JOBS.list(active_only=True)
        if active_jobs:
            last_progress_at = max(j.get("updated_at") or 0 for j in active_jobs)
    except Exception:
        pass

    return {
        "status": "active",
        "transcriber": s.transcriber is not None,
        "llm_engine": engine_ready,
        "active_job_count": len(active_jobs),
        "active_jobs": [
            {"id": j.get("id"), "kind": j.get("kind"), "state": j.get("state"), "updated_at": j.get("updated_at")}
            for j in active_jobs[:5]
        ],
        "last_progress_at": last_progress_at,
        # Which model runtimes currently hold a read (inference) or write
        # (reconfigure) lease — lets the supervisor and diagnostics see live work.
        "runtime_leases": s.model_runtime.active_leases(),
    }


@router.get("/runtime/status")
async def runtime_status():
    import server as s

    return s.get_runtime_status_snapshot()


@router.get("/runtime/output-settings")
async def runtime_output_settings():
    import server as s

    settings: typing.Dict[str, typing.Any] = dict(s.get_profile_output_settings())
    settings["pending_manual_send_ids"] = list(s.pending_manual_send_ids)
    settings["supported_actions"] = ["copy_only", "paste", "type", "open_chat_then_send"]
    settings["capabilities"] = s.get_capabilities()
    return settings


@router.get("/capabilities")
async def capabilities():
    import server as s

    from backend.audio import audio_status
    from backend.api.routes import wake as routes_wake

    payload = s.get_capabilities()
    push_to_mute_available = bool(payload.get("supports_input_injection", False))
    from backend.platform.audio_privacy import lease as privacy_lease
    payload["voice_privacy_status"] = audio_status.voice_privacy_capability(
        isolation_available=privacy_lease.get_lease().isolation_available(),
        push_to_mute_available=push_to_mute_available,
    )
    payload["wake_status"] = audio_status.wake_capability(
        engine_available=True,
        classifier_available=bool(routes_wake.selected_classifier_id()),
        # Deliberately false until a measured wake qualification exists
        # (false accepts/rejects, latency, CPU, handoff, device recovery).
        qualified=False,
    )
    return payload


@router.get("/audio/status")
async def audio_runtime_status():
    import server as s

    from backend.audio import audio_input_broker
    from backend.audio import audio_status
    from backend.api.routes import wake as routes_wake

    from backend.platform.audio_privacy import lease as privacy_lease
    lease = privacy_lease.get_lease()

    config = s.load_profile(s.get_last_active_profile())
    return audio_status.audio_status_snapshot(
        config,
        broker_status=audio_input_broker.get_broker().status(),
        isolation_available=lease.isolation_available(),
        push_to_mute_available=bool(s.get_capabilities().get("supports_input_injection", False)),
        # The lease knows about both mechanisms; the injector only knows about
        # the key. `held` is true for an isolation lease too.
        engaged=lease.is_held(),
        restore_complete=lease.restore_complete(),
        enabled=bool(config.get("wake_word_enabled", False)),
        listening=routes_wake.is_wake_listening(),
    )


@router.get("/metrics")
async def pipeline_metrics_endpoint():
    import server as s

    return s.get_pipeline_metrics_summary()


@router.get("/jobs")
async def list_jobs_endpoint(active: int = 0):
    """Central job registry (§6.3): what work is running or recently finished."""
    import server as s

    return {
        "ok": True,
        "jobs": s.JOBS.list(active_only=bool(active)),
        "runtime_leases": s.model_runtime.active_leases(),
    }


@router.get("/jobs/{job_id}")
async def get_job_endpoint(job_id: str):
    import server as s

    job = s.JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True, "job": job.to_public()}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job_endpoint(job_id: str):
    import server as s

    job = s.JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    s.JOBS.request_cancel(job_id)
    # For the active dictation job, also trip the pipeline's cancellation event so
    # the DictationPipeline's per-stage cancellation check (via
    # JobManagerCancellationBridge) unwinds process_recording_result promptly.
    if job_id == s._active_dictation_job_id:
        s.cancellation_event.set()
    updated = s.JOBS.get(job_id)
    return {"ok": True, "job": updated.to_public() if updated else None}


@router.get("/diagnostics/logs")
async def diagnostics_logs(lines: int = 120):
    import server as s

    return s.read_log_tail(lines)


@router.get("/diagnostics/paths")
async def diagnostics_paths():
    import server as s

    return s.get_runtime_paths_snapshot()


@router.get("/runtime/errors")
async def runtime_errors():
    import server as s

    return {"errors": s.get_runtime_error_history()}


@router.get("/diagnostics/support-report")
async def diagnostics_support_report():
    """One-click support report (Markdown) for alpha testers — no telemetry
    means this is how a tester hands us diagnostics. Runs off the event loop
    since it touches the filesystem and may shell out to llama-server --version."""
    import server as s

    return await run_in_threadpool(s.gather_support_report)
