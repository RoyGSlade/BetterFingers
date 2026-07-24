import hmac
import os
import queue
import re
import sys
import shutil
import tempfile
import logging
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import typing
import pyperclip
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from llm_engine import LLMEngine, get_engine, get_engine_if_initialized, resolve_dictation_preset
from log_redaction import redact_exc, redact_user_text
from store_migration import get_degraded_events
from transcriber import Transcriber
from streaming_transcriber import BatchCutter, StreamingTranscriptionSession
from hotkey_manager import HotkeyManager
from audio_gate import should_block_for_no_audio
from user_profile_manager import profile_manager
from intent_engine import intent_engine, IntentState
from project_generator import project_generator
from platform_capabilities import get_capabilities
from hardware_report import get_hardware_report, assess_model_fit, get_hardware_tier
from platform_paths import ensure_app_dirs, get_app_data_dir, get_config_dir
import recordings
import upload_safety
import dictionary
import dictation_commands
import macros
import voice_presets
import voice_clone_qa
import history_store
import mcp_client
from job_manager import JOBS, JobState
from backend.runtime.dependencies import JobManagerCancellationBridge, PipelineDependencies
from backend.services.dictation_pipeline import DictationPipeline, FunctionStage
from backend.services.speech_signals import compute_speech_signals
from backend.domain.contracts import to_dict as _contract_to_dict
from output_coordinator import OutputCoordinator
import voice_commands
import voice_edit_commands
from utterance_history import Utterance, utterance_history
from model_manager import (
    DEFAULT_MODEL,
    AVAILABLE_MODELS,
    check_and_download_resources,
    delete_model,
    get_download_state,
    get_model_file_status,
    get_model_path,
    get_models_dir,
    get_repo_local_server_path,
    get_server_path,
    is_ready as is_llm_model_ready,
    check_model_exists,
    required_llama_server_build,
    validate_llama_server_runtime,
)
# Configure Logging
from transcriber import (
    SUPPORTED_MODEL_SIZES,
    download_whisper_model,
    get_whisper_download_state,
    list_cached_models,
    remove_cached_model,
)
from utils import (
    get_app_path,
    get_last_active_profile,
    get_profiles_dir,
    get_user_data_path,
    list_profiles,
    load_profile,
    save_profile as save_runtime_profile,
    set_last_active_profile,
    setup_logging,
)
# Will be initialized in __main__ or implicitly if imported (logging lib handles singleton)
# But let's verify we don't double init.
if __name__ != "__main__":
    # If imported by uvicorn (e.g. uvicorn server:app), we need to setup logging.
    setup_logging(level="INFO")

app = FastAPI(title="BetterFingers Sidecar")
_llm_download_jobs = {}
_llm_download_jobs_lock = threading.Lock()

# CORS — only the app's own renderer surfaces, not the wildcard. The Electron
# renderer loads from file:// (Chromium sends `Origin: null` for cross-origin
# fetches from file pages) and from the electron-vite dev server in
# development. Additional origins can be granted explicitly via env.
# Pure startup-security policy lives in server_security.py (M6); re-imported here
# so server.validate_startup_security / server._allowed_cors_origins still exist.
from server_security import (  # noqa: E402
    _LOOPBACK_HOSTS,
    _allowed_cors_origins,
    validate_startup_security,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

from fastapi import Request
from starlette.responses import JSONResponse, FileResponse


def _is_test_env():
    # Under pytest we must not auto-generate a token or hard-fail startup —
    # the suite runs the app open on loopback by design.
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


def enforce_startup_security():
    """Application-startup auth gate (runs from the FastAPI startup event, so
    `uvicorn server:app` is covered — not only `python server.py`).

    In production without a token: raise, aborting startup. In dev without a
    token (real launch, not tests): generate one, publish it to the
    environment and app.state so every worker sees it. The active token lives
    in app.state.auth_token, not only os.environ.
    """
    host = os.getenv("BETTERFINGERS_HOST", "127.0.0.1")
    token = os.getenv("BETTERFINGERS_AUTH_TOKEN")
    result = validate_startup_security(
        host, token, allow_remote=os.getenv("BETTERFINGERS_ALLOW_REMOTE") == "1"
    )
    if not result["ok"]:
        if _is_test_env():
            # Never abort the test suite; just record and continue open.
            app.state.auth_token = token or None
            return result
        logging.error("Startup security check failed: %s", result["error"])
        raise RuntimeError(result["error"])
    if result["generated"]:
        if _is_test_env():
            app.state.auth_token = token or None
            return result
        os.environ["BETTERFINGERS_AUTH_TOKEN"] = result["token"]
        logging.warning("No auth token supplied; generated an ephemeral one for this run.")
        print(f"[betterfingers] Generated auth token for this run:\n"
              f"[betterfingers]   BETTERFINGERS_AUTH_TOKEN={result['token']}")
    app.state.auth_token = os.getenv("BETTERFINGERS_AUTH_TOKEN")
    return result


# Naive per-process throttle on repeated auth failures. Loopback single-user,
# so this is a tripwire against a local runaway/loop, not a hardened limiter.
_auth_failures = deque(maxlen=64)
_AUTH_FAIL_WINDOW_S = 10.0
_AUTH_FAIL_LIMIT = 20


def _record_auth_failure():
    now = time.monotonic()
    _auth_failures.append(now)
    recent = [t for t in _auth_failures if now - t <= _AUTH_FAIL_WINDOW_S]
    return len(recent)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    expected_token = os.getenv("BETTERFINGERS_AUTH_TOKEN")
    if expected_token and not request.url.path.startswith("/ws/"):
        if request.method != "OPTIONS":
            auth_header = request.headers.get("Authorization", "")
            parts = auth_header.split(" ", 1)
            # Constant-time comparison — a plain != leaks match length/prefix
            # timing to anything that can reach the port.
            presented = parts[1] if len(parts) == 2 and parts[0] == "Bearer" else ""
            if not hmac.compare_digest(presented, expected_token):
                if _record_auth_failure() > _AUTH_FAIL_LIMIT:
                    return JSONResponse(status_code=429, content={"detail": "Too many auth failures; slow down."})
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)

# Global Instances
transcriber = None
hotkey_manager = None
hotkey_recorder = None
hotkey_manager_started = False
_warmup_thread = None  # background model-warmup thread started by startup_event
# Rolling per-utterance pipeline latency samples for the /metrics HUD (C10).
pipeline_metrics = deque(maxlen=50)
pipeline_metrics_lock = threading.Lock()
output_injector = None
# Serializes creation, config reload, and use of the shared output injector.
# Two concurrent sends (different drafts) would otherwise race the singleton
# and could reload its config mid-injection. Reentrant so the drain path can
# take it too.
_output_injector_lock = threading.RLock()
tts_engine = None
active_websockets = []
pending_manual_send_ids = []
MAX_DRAFT_HISTORY = 100
is_processing_draft = False
# Unique to this process run. A send stamps the draft it is injecting with this
# token and persists "sending" to disk *before* the (non-idempotent) injection.
# A draft found in "sending" whose token differs from this one was interrupted
# by a crash of a previous process — its injection outcome is unknown, so
# recovery moves it to "send_interrupted" rather than silently reverting it.
SEND_PROCESS_TOKEN = uuid.uuid4().hex

# Draft persistence + lookup (queue, recordings, id counter, the coalesced
# JSON+SQLite writer, startup load, and crash-recovery reclassification) live
# in backend/stores/drafts.py (A1.5). draft_queue/draft_recordings/draft_lock
# below are the SAME objects the store owns (identity-shared, not copies) so
# every existing direct reference/mutation throughout this file and the test
# suite keeps working unchanged. get_user_data_path is passed as a thunk (not
# resolved once) so `patch("server.get_user_data_path", ...)` in tests still
# takes effect on every call, exactly as it did before extraction.
from backend.stores.drafts import DraftStore  # noqa: E402

_draft_store = DraftStore(
    data_dir_fn=lambda: get_user_data_path(),
    history_store=history_store,
    send_process_token=SEND_PROCESS_TOKEN,
    max_history=MAX_DRAFT_HISTORY,
)
draft_queue = _draft_store.draft_queue
draft_recordings = _draft_store.draft_recordings
draft_lock = _draft_store.lock
next_draft_id = _draft_store.next_draft_id

# Vestigial: no longer read by save_draft_history (the revision-guarded writer
# now lives entirely inside DraftStore's instance state), kept only so the
# persistence tests' setUp reset of this "shared writer state" doesn't need to
# change (test isolation predates the extraction and doesn't assert on these
# values afterward).
_draft_persist_lock = threading.Lock()
_draft_write_lock = threading.Lock()
_draft_request_rev = 0
_draft_written_rev = 0
_draft_pending_full_mirror = False
_draft_pending_changed_ids = set()
cancellation_event = threading.Event()
# Single-flight gate for the dictation pipeline. is_processing_draft remains as
# a read-only mirror for status displays/hotkey guards; the coordinator owns
# admission (atomic try_begin) so competing invocations are rejected instead of
# interleaving (a boolean is not a mutex).
from dictation_coordinator import DictationCoordinator

dictation_coordinator = DictationCoordinator(cancellation_event=cancellation_event)
# Read/write leases guarding the model runtimes (STT/LLM/TTS): inference takes
# a read lease, destructive ops (unload/reload/select/delete) take an exclusive
# write lease that fails fast (→ 409) while inference is active.
from model_runtime_coordinator import ModelRuntimeCoordinator, RuntimeBusyError

model_runtime = ModelRuntimeCoordinator()
# Resource ledger + admission control (DESIGN.md M6): each evictor is the
# SAME unload path /models/unload/{component} already uses, so a coordinator-
# driven eviction (admission or idle sweep) and a user-driven manual unload
# converge on one release path — no double-free risk. Registered once here
# with a lambda (not a direct reference) because _unload_model_component_locked
# is defined later in this file; the lambda body only resolves it at call
# time, well after the whole module has finished loading.
model_runtime.register_evictor("llm", lambda: _unload_model_component_locked("llm"))
model_runtime.register_evictor("stt", lambda: _unload_model_component_locked("stt"))
model_runtime.register_evictor("tts", lambda: _unload_model_component_locked("tts"))
# LLMEngine is a process-level singleton (class attributes, not instance
# state) — injecting its admission hooks once here covers every get_engine()
# call for the life of the process. Transcriber/ReviewTTSEngine are per-
# instance instead, so their hooks are injected at construction time in
# ensure_transcriber_initialized()/ensure_tts_initialized() below.
LLMEngine.set_admission_fn(lambda est, mid=None: model_runtime.request_admission("llm", est, mid))
LLMEngine.set_load_reporter(lambda mid, est: model_runtime.note_loaded("llm", mid, est))
# Set for the duration of a privacy wipe. While it is set, every path that
# could create or re-persist user data (new recordings, dictation processing,
# recovery saves, sends, TTS, retranscription) refuses, so the wipe operates on
# a quiescent system and nothing regrows behind it.
privacy_wipe_in_progress = threading.Event()
# Held-recording queue: a recording that finishes while the pipeline is busy
# waits here (FIFO) instead of being rejected, so back-to-back dictations never
# interrupt the user. One dispatcher thread drains it; each item optionally
# carries the recording's StreamingTranscriptionSession whose finalize() yields
# the already-streamed transcript. The drop generation lets a privacy wipe
# invalidate items already dequeued but not yet processed.
MAX_PENDING_RECORDINGS = 12
_pending_recordings = queue.Queue()
_recording_dispatcher_lock = threading.Lock()
_recording_dispatcher_thread = None
_pending_drop_generation = 0
_active_stream_session = None
_stream_session_lock = threading.Lock()
# Coordinates draft sends against the privacy wipe's output-drain step: a send
# registers begin_send/end_send around its injection+persist, and the wipe
# drains (cancel + wait for zero active sends + exclusive lease) before it is
# allowed to delete anything. See output_coordinator.py.
output_coordinator = OutputCoordinator()
OUTPUT_DRAIN_TIMEOUT_SECONDS = 5.0


def _reject_if_wiping(what):
    """Return a rejection dict if a privacy wipe is running, else None."""
    if privacy_wipe_in_progress.is_set():
        logging.info("Rejected %s: a privacy wipe is in progress.", what)
        return {"ok": False, "error": "privacy_wipe_in_progress",
                "message": "A privacy wipe is in progress; try again in a moment."}
    return None


# The dictation pipeline is the first consumer of the central job registry
# (§6.3). Only one dictation runs at a time (guarded by the coordinator), so
# a single active-id pointer lets the /jobs cancel route target it.
_active_dictation_job_id = None
runtime_error_history = []
runtime_error_lock = threading.Lock()
MAX_RUNTIME_ERROR_HISTORY = 50

# The wrappers below delegate to _draft_store (backend/stores/drafts.py,
# A1.5). Each passes server.py's *current* module-level bindings (bare name
# lookups, resolved at call time) rather than values captured once, so
# `patch("server.save_draft_history", ...)`, `patch("server.get_user_data_path",
# ...)`, etc. in the test suite keep intercepting exactly as before extraction.
def save_draft_history(changed_draft_id=None):
    _draft_store.save_history(changed_draft_id)


def load_draft_history():
    global next_draft_id
    _draft_store.load_history(max_history=MAX_DRAFT_HISTORY)
    next_draft_id = _draft_store.next_draft_id


def recover_interrupted_sends():
    return _draft_store.recover_interrupted_sends(save_fn=save_draft_history)


def get_voices_path() -> Path:
    # Unified under the single data root (was the split XDG location).
    # Pure lookup — never creates the directory, so the privacy report,
    # wipe, and postcondition checks don't resurrect it (P0).
    return Path(get_user_data_path()) / "voices"


def ensure_voices_dir() -> Path:
    """Only call when about to save a voice — this is the sole creation point."""
    path = get_voices_path()
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_graph_path():
    return Path(get_user_data_path()) / "graph.json"


def get_debug_log_path():
    return Path(get_user_data_path()) / "debug.log"


def record_runtime_error(component, message, severity="recoverable", details=None):
    if isinstance(severity, dict):
        details = severity
        severity = "recoverable"
    with runtime_error_lock:
        row = {
            "component": str(component or "runtime"),
            "message": str(message or ""),
            "severity": str(severity or "recoverable").lower(),
            "details": details or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if row["severity"] not in {"info", "warning", "recoverable", "fatal"}:
            row["severity"] = "recoverable"
        runtime_error_history.append(row)
        if len(runtime_error_history) > MAX_RUNTIME_ERROR_HISTORY:
            del runtime_error_history[: len(runtime_error_history) - MAX_RUNTIME_ERROR_HISTORY]
        return dict(row)



def get_runtime_error_history():
    with runtime_error_lock:
        return [dict(row) for row in runtime_error_history]


def read_log_tail(max_lines=120):
    safe_max_lines = max(1, min(int(max_lines or 120), 500))
    log_path = get_debug_log_path()
    if not log_path.exists():
        return {"path": str(log_path), "exists": False, "lines": []}

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except Exception as exc:
        logging.exception("Failed reading debug log")
        record_runtime_error("diagnostics", f"Failed reading debug log: {exc}")
        return {"path": str(log_path), "exists": True, "error": str(exc), "lines": []}

    return {
        "path": str(log_path),
        "exists": True,
        "lines": [line.rstrip("\n") for line in lines[-safe_max_lines:]],
    }


def get_runtime_paths_snapshot():
    model_path = get_model_path(DEFAULT_MODEL)
    server_path = get_server_path()
    repo_server_path = get_repo_local_server_path()
    return {
        "app_path": str(get_app_path()),
        "user_data_path": str(get_user_data_path()),
        "app_data_dir": str(get_app_data_dir()),
        "config_dir": str(get_config_dir()),
        "debug_log_path": str(get_debug_log_path()),
        "models_dir": str(get_models_dir()),
        "default_model_path": str(model_path),
        "default_model_exists": os.path.exists(model_path),
        "llama_server_path": str(server_path),
        "llama_server_exists": os.path.exists(server_path),
        "repo_local_llama_server_path": str(repo_server_path),
        "repo_local_llama_server_exists": os.path.exists(repo_server_path),
        "BETTERFINGERS_LLAMA_SERVER": os.getenv("BETTERFINGERS_LLAMA_SERVER", ""),
        "BETTERFINGERS_MODEL_PATH": os.getenv("BETTERFINGERS_MODEL_PATH", ""),
        "BETTERFINGERS_LAZY_STARTUP": os.getenv("BETTERFINGERS_LAZY_STARTUP", ""),
    }


def sanitize_profile_name(raw_name):
    value = "".join(ch for ch in str(raw_name or "") if ch.isalnum() or ch in (" ", "_", "-")).strip()
    return value or "Default"


def get_active_profile_payload():
    name = get_last_active_profile()
    return {
        "active_profile": name,
        "profiles": list_profiles(),
        "settings": load_profile(name),
    }


def apply_active_profile_runtime(profile_name):
    global output_injector
    safe_name = sanitize_profile_name(profile_name)
    set_last_active_profile(safe_name)

    if transcriber is not None:
        try:
            transcriber.reload_profile(profile_name=safe_name, preload=False)
        except Exception as exc:
            logging.warning(f"Failed applying profile to transcriber: {exc}")

    if hotkey_manager is not None:
        try:
            hotkey_manager.update_config(safe_name)
        except Exception as exc:
            logging.warning(f"Failed applying profile to hotkeys: {exc}")

    with _output_injector_lock:
        if output_injector is not None:
            try:
                output_injector.reload_config(safe_name)
            except Exception as exc:
                logging.warning(f"Failed applying profile to output injector: {exc}")

    try:
        cfg = load_profile(safe_name)
        engine = get_engine_if_initialized()
        if engine is not None:
            model_id = str(cfg.get("llm_model_id", DEFAULT_MODEL) or DEFAULT_MODEL).strip()
            engine.set_model_id(model_id)
    except Exception as exc:
        logging.warning(f"Failed applying profile to LLM engine: {exc}")

    # apply_active_profile_runtime is the single choke point both profile
    # activation AND a settings-save-of-the-active-profile flow through, so
    # re-syncing pinned state here (same as startup_event's initial sync)
    # means a keep-loaded toggle takes effect immediately — no restart needed
    # for A3's idle sweep / admission eviction to keep skipping pinned components.
    residency = get_model_residency_settings()
    for component, pinned in residency.items():
        model_runtime.set_pinned(component, pinned)

    return get_active_profile_payload()


def is_lazy_startup_enabled():
    return os.getenv("BETTERFINGERS_LAZY_STARTUP") == "1"


def get_pipeline_flags(config=None):
    """Per-profile toggles used on the hot dictation path, read with a single
    load_profile() call rather than one per flag (each call is disk I/O).
    Pass a pre-loaded profile dict via ``config`` to skip even that read —
    process_recording_result() loads the profile once and shares it."""
    if config is None:
        try:
            config = load_profile(get_last_active_profile())
        except Exception:
            config = {}
    return {
        "voice_commands": bool(config.get("voice_commands_enabled", True)),
        "macros": bool(config.get("macros_enabled", True)),
        "editing_commands": bool(config.get("editing_commands_enabled", True)),
        "app_commands": bool(config.get("app_commands_enabled", True)),
        "current_preset": str(config.get("current_preset", "True Janitor") or "True Janitor"),
    }


def voice_commands_enabled():
    """Whether spoken dictation commands (C2) are applied. Per-profile, default on."""
    return get_pipeline_flags()["voice_commands"]


def macros_enabled():
    """Whether voice macros (C11) are expanded. Per-profile, default on."""
    return get_pipeline_flags()["macros"]


def editing_commands_enabled():
    """Whether phrase-history editing commands ("scratch that", "delete last
    word", ...) are applied. Per-profile, default on. Distinct from
    voice_commands_enabled(), which gates the pure formatting pass in
    dictation_commands.py."""
    return get_pipeline_flags()["editing_commands"]


def app_commands_enabled():
    """Whether app-control voice commands ("send it", "emergency stop", ...)
    are recognized. Per-profile, default on — safety comes from context
    gating in voice_commands.parse_command, not from this toggle."""
    return get_pipeline_flags()["app_commands"]


def get_model_residency_settings():
    try:
        config = load_profile(get_last_active_profile())
    except Exception as exc:
        logging.warning(f"Failed loading active profile for model residency settings: {exc}")
        config = {}

    return {
        "llm": bool(config.get("model_keep_llm_loaded", True)),
        "stt": bool(config.get("model_keep_stt_loaded", True)),
        "tts": bool(config.get("model_keep_tts_loaded", False)),
    }


def ensure_transcriber_initialized(preload=False):
    global transcriber
    if transcriber is None:
        # preload=False here even when the caller wants preloading: the DI
        # hooks below must be wired BEFORE the first ensure_loaded() call, and
        # Transcriber.__init__(preload=True) would call it internally before
        # we get a chance to inject admission control. Preload explicitly
        # afterward instead — same end state, correct ordering.
        transcriber = Transcriber(profile_name=get_last_active_profile(), preload=False)
        # hasattr-guarded: test doubles that stand in for Transcriber (several
        # DummyTranscriber fakes across the suite) predate this DI surface and
        # needn't implement it — same defensive style as the getattr(engine,
        # method, None) checks in _unload_model_component_locked.
        if hasattr(transcriber, "set_admission_fn"):
            transcriber.set_admission_fn(lambda est, size=None: model_runtime.request_admission("stt", est, size))
        if hasattr(transcriber, "set_load_reporter"):
            transcriber.set_load_reporter(lambda size, est: model_runtime.note_loaded("stt", size, est))
        if preload:
            transcriber.ensure_loaded()
    elif preload:
        transcriber.ensure_loaded()
    return transcriber


def warm_start_resident_models(settings=None):
    settings = settings or get_model_residency_settings()
    results = {}

    if settings.get("stt"):
        try:
            logging.info("Preloading STT because keep-loaded is enabled.")
            trans = ensure_transcriber_initialized(preload=True)
            results["stt"] = {"ok": True, "loaded": bool(getattr(trans, "model", None))}
        except Exception as exc:
            logging.error(f"STT keep-loaded startup failure: {exc}")
            record_runtime_error("stt", str(exc), {"action": "keep_loaded_startup"})
            results["stt"] = {"ok": False, "error": str(exc)}

    if settings.get("llm"):
        try:
            logging.info("Starting selected LLM because keep-loaded is enabled.")
            engine = get_selected_llm_engine()
            ready = bool(getattr(engine, "_ready", False))
            results["llm"] = {
                "ok": ready,
                "ready": ready,
                "model_id": getattr(engine, "model_id", None),
            }
        except Exception as exc:
            logging.error(f"LLM keep-loaded startup failure: {exc}")
            record_runtime_error("llm", str(exc), {"action": "keep_loaded_startup"})
            results["llm"] = {"ok": False, "ready": False, "error": str(exc)}

    if settings.get("tts"):
        try:
            logging.info("Loading review TTS because keep-loaded is enabled.")
            config = load_profile(get_last_active_profile())
            voice_hint = normalize_tts_voice_id(config.get("review_tts_voice_hint", "english"))
            engine = ensure_tts_initialized()
            if engine:
                engine.set_keep_loaded(True)
                load_result = engine.ensure_loaded(voice_hint=voice_hint)
                results["tts"] = {
                    "ok": bool(load_result.get("ok")),
                    "loaded": engine.is_loaded(),
                    "backend": engine.backend(),
                    "message": load_result.get("message", ""),
                }
        except Exception as exc:
            logging.error(f"TTS keep-loaded startup failure: {exc}")
            record_runtime_error("tts", str(exc), {"action": "keep_loaded_startup"})
            results["tts"] = {"ok": False, "loaded": False, "error": str(exc)}

    return results


def get_runtime_status_snapshot():
    engine = get_engine_if_initialized()
    engine_ready = False
    if engine is not None:
        try:
            engine_ready = bool(getattr(engine, "_ready", False))
        except Exception:
            engine_ready = False

    return {
        "transcriber_initialized": transcriber is not None,
        "llm_initialized": engine is not None,
        "hotkey_manager_started": hotkey_manager_started,
        "hotkey_keyboard_hooks_ok": bool(
            hotkey_manager is not None and not getattr(hotkey_manager, "keyboard_hook_errors", [])
        ) if hotkey_manager_started else False,
        "hotkey_keyboard_hook_errors": list(getattr(hotkey_manager, "keyboard_hook_errors", [])) if hotkey_manager else [],
        "recording_active": bool(getattr(hotkey_manager, "is_recording", False)) if hotkey_manager else False,
        "transcriber_loaded": bool(getattr(transcriber, "model", None)),
        "llm_ready": engine_ready,
    }


_last_amplitude_broadcast = 0.0
_AMPLITUDE_BROADCAST_INTERVAL_S = 0.08


def _broadcast_recording_amplitude(chunk, sample_rate):
    """Chunk callback (runs on AudioRecorder's chunk-worker thread, not the
    audio callback itself): throttled real-time mic RMS so the renderer's
    glitch-ring can pulse to the voice during 'recording'."""
    del sample_rate
    global _last_amplitude_broadcast
    now = time.time()
    if now - _last_amplitude_broadcast < _AMPLITUDE_BROADCAST_INTERVAL_S:
        return
    _last_amplitude_broadcast = now
    import numpy as np

    try:
        amplitude = float(np.sqrt(np.mean(np.square(chunk)))) if getattr(chunk, "size", 0) else 0.0
    except Exception:
        amplitude = 0.0
    broadcast_status_threadsafe("recording", {"amplitude": amplitude})


def _broadcast_watchdog_timeout():
    """Phase 11: the missed-release watchdog fired — recording was force-
    stopped after max_recording_seconds. Surface it so it doesn't look like
    a silent glitch."""
    broadcast_status_threadsafe(
        "watchdog_timeout_warning",
        {"message": "Recording stopped after max duration."},
    )


def _broadcast_partial_transcript(text, batch_count):
    """Streaming STT progress: lets the UI show live text while recording."""
    broadcast_status_threadsafe(
        "stt_partial", {"text": text, "batches": batch_count}
    )


def _begin_stream_session():
    """Create the streaming transcription session for a recording that is
    about to start. Failure here is never fatal — the pipeline's classic
    full-audio pass still runs when no streamed transcript arrives."""
    global _active_stream_session
    try:
        config = get_active_recording_config()
        if not bool(config.get("streaming_transcription_enabled", True)):
            return
        trans = ensure_transcriber_initialized(preload=False)
        dict_terms = dictionary.get_terms()
        hotwords = dictionary.hotwords_string(dict_terms)

        def _transcribe(audio):
            # Same lease discipline as the pipeline's STT stage: a Whisper
            # unload/reload can't free the model mid-batch.
            with model_runtime.read_lease("stt"):
                return trans.transcribe_with_confidence(audio, hotwords=hotwords)

        cutter = BatchCutter(
            sample_rate=16000,
            min_batch_seconds=float(config.get("streaming_batch_min_seconds", 3.0)),
            max_batch_seconds=float(config.get("streaming_batch_max_seconds", 12.0)),
            silence_ms=int(config.get("streaming_batch_silence_ms", 600)),
            rms_threshold=float(config.get("no_audio_min_rms", 0.003)),
            peak_threshold=float(config.get("no_audio_min_peak", 0.015)),
        )
        session = StreamingTranscriptionSession(
            _transcribe,
            sample_rate=16000,
            cutter=cutter,
            on_partial=_broadcast_partial_transcript,
        )
        with _stream_session_lock:
            _active_stream_session = session
    except Exception as exc:
        logging.warning(f"Streaming transcription unavailable for this recording: {redact_exc(exc)}")


def _detach_stream_session():
    """Take ownership of the active session (recording just stopped)."""
    global _active_stream_session
    with _stream_session_lock:
        session = _active_stream_session
        _active_stream_session = None
    return session


def _on_recorder_chunk(chunk, sample_rate):
    """Recorder chunk callback: UI amplitude + feed the streaming session.
    Runs on the recorder's chunk-worker thread; both halves are O(chunk)."""
    _broadcast_recording_amplitude(chunk, sample_rate)
    with _stream_session_lock:
        session = _active_stream_session
    if session is not None:
        try:
            session.feed(chunk, sample_rate)
        except Exception as exc:
            logging.debug(f"Streaming session feed failed: {exc}")


def start_hotkey_manager():
    global hotkey_manager, hotkey_manager_started, hotkey_recorder

    if hotkey_manager_started and hotkey_manager is not None:
        return hotkey_manager

    if hotkey_manager is not None:
        try:
            hotkey_manager.stop()
        except Exception as exc:
            logging.warning(f"Hotkey Manager stop before restart failed: {exc}")

    from recorder import AudioRecorder

    recorder = AudioRecorder()
    recorder.set_chunk_callback(_on_recorder_chunk)
    manager = HotkeyManager(
        recorder=recorder,
        on_recording_complete_callback=on_recording_complete,
        on_recording_start_callback=on_recording_start,
        on_force_stop_callback=emergency_stop_runtime,
        on_manual_send_callback=handle_primary_action,
        on_review_tts_callback=handle_review_tts_shortcut,
        # Recording is never blocked by draft processing anymore — a finished
        # recording is held in _pending_recordings and processed in order. The
        # only true blocker is a privacy wipe, which must stay quiescent.
        is_busy_callback=lambda: privacy_wipe_in_progress.is_set(),
        on_watchdog_timeout_callback=_broadcast_watchdog_timeout,
    )
    try:
        manager.update_config(get_last_active_profile())
    except Exception as exc:
        logging.warning(f"Failed to apply profile to hotkeys on startup: {exc}")
    manager.start()
    hotkey_manager = manager
    hotkey_recorder = recorder
    hotkey_manager_started = True
    return manager


def stop_hotkey_manager():
    global hotkey_manager, hotkey_manager_started, hotkey_recorder

    if hotkey_manager:
        try:
            hotkey_manager.stop()
        except Exception as exc:
            logging.warning(f"Hotkey Manager stop failed: {exc}")

    hotkey_manager = None
    hotkey_recorder = None
    hotkey_manager_started = False

# Status Broadcaster
async def broadcast_status(status: str, data: typing.Optional[dict] = None):
    """
    Status: 'listening', 'thinking', 'speaking', 'idle'
    """
    message = {"status": status}
    if data:
        message.update(data)
    
    to_remove = []
    for ws in list(active_websockets):
        try:
            await ws.send_json(message)
        except Exception:
            to_remove.append(ws)

    for ws in to_remove:
        if ws in active_websockets:
            active_websockets.remove(ws)


def broadcast_status_threadsafe(status: str, data: typing.Optional[dict] = None):
    if not loop or loop.is_closed():
        logging.warning("Loop not ready for broadcast")
        return

    coroutine = broadcast_status(status, data)
    try:
        asyncio.run_coroutine_threadsafe(coroutine, loop)
    except Exception as exc:
        logging.warning(f"Failed scheduling broadcast '{status}': {exc}")
        coroutine.close()


def get_recording_metadata(recording_result):
    if recording_result is None:
        return {}

    return {
        "sample_rate": int(getattr(recording_result, "sample_rate", 0) or 0),
        "duration_seconds": float(getattr(recording_result, "duration_seconds", 0.0) or 0.0),
        "frame_count": int(getattr(recording_result, "frame_count", 0) or 0),
        "sample_count": int(getattr(recording_result, "sample_count", 0) or 0),
        "max_amplitude": float(getattr(recording_result, "max_amplitude", 0.0) or 0.0),
        "rms_amplitude": float(getattr(recording_result, "rms_amplitude", 0.0) or 0.0),
        "stop_reason": str(getattr(recording_result, "stop_reason", "") or ""),
    }


def get_active_recording_config():
    try:
        return load_profile(get_last_active_profile())
    except Exception as exc:
        logging.warning(f"Failed loading active profile for recording gate: {exc}")
        return {}


def get_active_token_limit():
    try:
        config = load_profile(get_last_active_profile())
        return int(config.get("output_token_limit", 1100) or 1100)
    except Exception as exc:
        logging.warning(f"Failed loading active profile token limit: {exc}")
        return 1100


def get_active_completion_tokens():
    """Per-call LLM completion ceiling. Prefers max_completion_tokens, falls back
    to the legacy output_token_limit alias, then the engine default."""
    try:
        config = load_profile(get_last_active_profile())
        value = config.get("max_completion_tokens")
        if value in (None, ""):
            value = config.get("output_token_limit", 1600)
        return int(value or 1600)
    except Exception as exc:
        logging.warning(f"Failed loading active profile completion tokens: {exc}")
        return 1600


def get_active_long_draft_warning_words():
    """Word count above which a final draft is flagged as long in the UI. This is
    intentionally separate from the LLM completion cap."""
    try:
        config = load_profile(get_last_active_profile())
        value = config.get("long_draft_warning_words")
        if value in (None, ""):
            value = config.get("output_token_limit", 1200)
        return int(value or 1200)
    except Exception as exc:
        logging.warning(f"Failed loading active profile long-draft warning: {exc}")
        return 1200


# Pure send/review-gating policy lives in send_policy.py (M6); re-imported so
# server.evaluate_confidence_send_policy / server.count_draft_tokens still exist.
# The config readers below stay here (tests patch server.load_profile).
from send_policy import count_draft_tokens, evaluate_confidence_send_policy  # noqa: E402


def update_draft_review_fields(draft):
    warning_words = get_active_long_draft_warning_words()
    token_count = count_draft_tokens(draft.get("final_text") or draft.get("raw_text") or "")
    draft["token_count"] = token_count
    draft["token_limit"] = warning_words
    draft["long_text"] = token_count > warning_words
    draft["review_state"] = draft.get("review_state") or "ready"
    try:
        policy_config = load_profile(get_last_active_profile())
    except Exception:
        policy_config = {}
    policy = evaluate_confidence_send_policy(
        draft.get("confidence"), draft["long_text"], draft.get("gate_reasons"), policy_config
    )
    draft["auto_send_ok"] = policy["auto_send_ok"]
    draft["force_review"] = policy["force_review"]
    draft["force_review_reason"] = policy["reason"]
    return draft


def _serialize_optional_contract(value):
    """None-safe backend.domain.contracts.to_dict() for I3.1's optional
    structured-transcription/speech-signal pipeline extras."""
    return _contract_to_dict(value) if value is not None else None


def create_draft(raw_text, final_text, preset="True Janitor", status="pending", metadata=None, error="", gate_reasons=None, recording_result=None, confidence=None, transcription_result=None, speech_signals=None):
    global next_draft_id
    _draft_store.next_draft_id = next_draft_id
    result = _draft_store.create_draft(
        raw_text, final_text, preset=preset, status=status, metadata=metadata,
        error=error, gate_reasons=gate_reasons, recording_result=recording_result,
        confidence=confidence, review_fields_fn=update_draft_review_fields,
        save_fn=save_draft_history, max_history=MAX_DRAFT_HISTORY,
        transcription_result=transcription_result, speech_signals=speech_signals,
    )
    next_draft_id = _draft_store.next_draft_id
    return result


def get_draft_by_id(draft_id):
    return _draft_store.get_draft_by_id(draft_id)


def get_profile_output_settings():
    try:
        config = load_profile(get_last_active_profile())
    except Exception as exc:
        logging.warning(f"Failed loading active profile for output settings: {exc}")
        config = {}

    send_mode = str(config.get("send_mode", "review_first") or "review_first").strip().lower()
    if send_mode not in {"review_first", "auto_send"}:
        send_mode = "review_first"

    return {
        "send_mode": send_mode,
        "auto_submit": bool(config.get("auto_submit", False)),
        "chat_close_action": str(config.get("chat_close_action", "none") or "none").strip().lower(),
        "instant_typing": bool(config.get("instant_typing", False)),
        "review_tts_voice_hint": str(config.get("review_tts_voice_hint", "english") or "english").strip(),
        "kokoro_quantization": str(config.get("kokoro_quantization", "fp32") or "fp32").strip(),
        "review_tts_speed": float(config.get("review_tts_speed", 0.95)),
    }


def copy_text_to_clipboard(text):
    try:
        pyperclip.copy(text or "")
        return {
            "ok": True,
            "requested_action": "copy_only",
            "actual_action": "copy_only",
            "action": "copy_only",
            "message": "Copied text to clipboard.",
        }
    except Exception as exc:
        logging.exception("Clipboard copy failed")
        return {
            "ok": False,
            "requested_action": "copy_only",
            "actual_action": "copy_only",
            "action": "copy_only",
            "message": f"Clipboard copy failed: {exc}",
            "error": str(exc),
        }


def perform_output_action(text, action="copy_only", open_chat=False):
    global output_injector
    requested_action = str(action or "copy_only").strip().lower()
    if requested_action not in {"copy_only", "paste", "type", "open_chat_then_send"}:
        requested_action = "copy_only"

    capabilities = get_capabilities()
    payload = {
        "requested_action": requested_action,
        "actual_action": requested_action,
        "action": requested_action,
        "fallback": False,
        "fallback_reason": "",
        "input_injection_supported": bool(capabilities.get("supports_input_injection", False)),
        "platform": capabilities.get("platform", "unknown"),
        "session_type": capabilities.get("session_type", "unknown"),
        "open_chat_requested": bool(open_chat or requested_action == "open_chat_then_send"),
        "clipboard_result": None,
        "injection_attempted": False,
        "ok": False,
        "message": "",
    }

    # Strip only to test emptiness — the user's whitespace (indentation,
    # trailing newlines, deliberate blank lines) is content and must survive
    # copy/type/paste unchanged.
    final_text = str(text or "")
    if not final_text.strip():
        payload.update({"message": "No text available to send.", "error": "empty_text"})
        return payload

    if requested_action == "copy_only":
        result = copy_text_to_clipboard(final_text)
        payload.update(result)
        payload["actual_action"] = str(result.get("actual_action") or result.get("action") or "copy_only")
        payload["clipboard_result"] = dict(result)
        return payload

    if not capabilities.get("supports_input_injection", False):
        result = copy_text_to_clipboard(final_text)
        payload.update(result)
        payload.update(
            {
                "requested_action": requested_action,
                "actual_action": "copy_only",
                "action": "copy_only",
                "fallback": True,
                "fallback_reason": "input_injection_unsupported",
                "clipboard_result": dict(result),
                "message": (
                    "Input injection is not supported in this session; copied text to clipboard instead."
                    if result.get("ok")
                    else result.get("message", "Copy fallback failed.")
                ),
            }
        )
        return payload

    try:
        settings = get_profile_output_settings()
        # Hold the injector lock across create + reload + the actual injection
        # so a concurrent send can't swap the config out mid-type or race the
        # singleton's construction.
        with _output_injector_lock:
            if output_injector is None:
                from injector import InputInjector

                output_injector = InputInjector(profile_name=get_last_active_profile())
            else:
                try:
                    output_injector.reload_config(get_last_active_profile())
                except Exception as exc:
                    logging.debug(f"Failed reloading output injector config: {exc}")
            injector = output_injector
            should_open_chat = open_chat or requested_action == "open_chat_then_send"
            payload["injection_attempted"] = True
            if should_open_chat:
                injector.open_chat()

            if requested_action == "type":
                injector.type_text(final_text)
                actual_action = "type"
            else:
                injector.send_output(
                    text=final_text,
                    auto_submit=settings["auto_submit"],
                    close_action=settings["chat_close_action"],
                )
                actual_action = "open_chat_then_send" if should_open_chat else "paste"

        payload.update(
            {
                "ok": True,
                "message": "Output sent.",
                "action": actual_action,
                "actual_action": actual_action,
            }
        )
        return payload
    except Exception as exc:
        logging.exception("Output action failed")
        result = copy_text_to_clipboard(final_text)
        payload.update(result)
        payload.update(
            {
                "requested_action": requested_action,
                "actual_action": "copy_only",
                "action": "copy_only",
                "fallback": True,
                "fallback_reason": "injection_failed",
                "clipboard_result": dict(result),
                "message": (
                    f"Output action failed ({exc}); copied text to clipboard instead."
                    if result.get("ok")
                    else f"Output action failed ({exc}); copy fallback also failed."
                ),
                "error": str(exc),
            }
        )
        return payload


def mark_draft_pending_send(draft):
    draft["pending_send"] = True
    if draft["id"] not in pending_manual_send_ids:
        pending_manual_send_ids.append(draft["id"])


def send_draft_by_id(draft_id, action=None, open_chat=False, allow_resend=False):
    # A wipe is draining/deleting user data — do not inject (which could reopen
    # or re-clipboard content the user is trying to erase).
    wiping = _reject_if_wiping("draft send")
    if wiping:
        return {"id": draft_id, **wiping}
    # Register with the output coordinator BEFORE any state mutation so the
    # wipe's drain (which cancels + waits for the active-send count to hit
    # zero) cannot miss this send in a gap between the flag check above and
    # this point. Refused while draining or leased — same rejection as the
    # flag check, just closing the race window the flag alone can't close.
    send_op_id = output_coordinator.begin_send()
    if send_op_id is None:
        wiping = _reject_if_wiping("draft send") or {
            "ok": False, "error": "privacy_wipe_in_progress",
            "message": "A privacy wipe is in progress; try again in a moment.",
        }
        return {"id": draft_id, **wiping}
    try:
        return _send_draft_by_id_locked(draft_id, action, open_chat, allow_resend)
    finally:
        output_coordinator.end_send(send_op_id)


def _send_draft_by_id_locked(draft_id, action, open_chat, allow_resend):
    # Atomic state transition (compare-and-set to "sending" under the lock)
    # so two simultaneous requests cannot both inject the same text. A request
    # that loses the race gets the existing outcome instead of re-injecting.
    # "send_interrupted" (a crash-recovered draft, outcome unknown) is
    # deliberately resendable without allow_resend: it was never confirmed sent.
    with draft_lock:
        draft = get_draft_by_id(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        status = draft.get("status")
        if status == "sending":
            response = dict(draft)
            response.update({"ok": False, "error": "send_in_progress",
                             "message": "This draft is already being sent."})
            return response
        if status == "sent" and not allow_resend:
            response = dict(draft)
            response.update({"ok": False, "error": "already_sent",
                             "message": "This draft was already sent; pass allow_resend to send again."})
            return response
        prior_status = status
        # Stamp this send with an operation id + this process's token, and record
        # that a send is in flight. Persisted below *before* injection so a crash
        # mid-send is recoverable (see recover_interrupted_sends).
        operation_id = uuid.uuid4().hex
        draft["status"] = "sending"
        draft["send_operation_id"] = operation_id
        draft["send_process_token"] = SEND_PROCESS_TOKEN
        draft["send_started_at"] = datetime.now(timezone.utc).isoformat()
        draft["send_outcome"] = None
        final_text = draft.get("final_text", "")

    # Persist the "sending" marker to disk BEFORE the (non-idempotent) injection.
    # If the process dies during perform_output_action, the draft reloads as
    # "sending" and recovery reclassifies it to "send_interrupted" instead of a
    # resendable state that would risk a silent double paste. Outside the lock
    # (§9): disk + SQLite IO must not serialize other draft operations.
    save_draft_history(changed_draft_id=draft_id)

    settings = get_profile_output_settings()
    requested_action = action or ("open_chat_then_send" if settings["send_mode"] == "auto_send" else "copy_only")
    try:
        result = perform_output_action(final_text, requested_action, open_chat=open_chat)
    except BaseException:
        # Abnormal interruption mid-injection (KeyboardInterrupt/SystemExit):
        # the text may or may not have landed, so the honest state is
        # "interrupted" (outcome unknown, still resendable), not the prior
        # state as if nothing was attempted.
        with draft_lock:
            wedged = get_draft_by_id(draft_id)
            if wedged is not None and wedged.get("status") == "sending" \
                    and wedged.get("send_operation_id") == operation_id:
                wedged["status"] = "send_interrupted"
                wedged["send_outcome"] = "interrupted"
                wedged.pop("send_process_token", None)
        # A wipe that is draining right now will delete this draft the moment
        # it acquires the lease; writing it back here would just recreate
        # what the wipe is about to erase (or just erased).
        if not output_coordinator.cancel_requested():
            save_draft_history(changed_draft_id=draft_id)
        raise

    with draft_lock:
        draft = get_draft_by_id(draft_id)
        if draft is not None:
            draft["send_result"] = result
            # The send has completed (one way or another): it is no longer in
            # flight, so drop the in-flight process token.
            draft.pop("send_process_token", None)
            if result.get("ok"):
                draft["status"] = "sent"
                draft["send_outcome"] = "sent"
                draft["pending_send"] = False
                while draft_id in pending_manual_send_ids:
                    pending_manual_send_ids.remove(draft_id)
            else:
                draft["status"] = "send_error"
                draft["send_outcome"] = "failed"
                draft["error"] = result.get("message", "Send failed.")
            response = dict(draft)
        else:
            response = {"id": draft_id, "send_result": result}

    # Persist outside the lock: disk + SQLite IO must not serialize every
    # other draft operation behind this send (§9). Recheck cancellation
    # first: if a wipe started draining after the "sending" persist above,
    # this write must not resurrect the data the wipe is deleting/deleted.
    if not output_coordinator.cancel_requested():
        save_draft_history(changed_draft_id=draft_id)
    broadcast_status_threadsafe("draft_sent" if result.get("ok") else "draft_send_error", {"draft_id": draft_id, "send_result": result})
    return response


def speak_text_aloud(text: str):
    phrase = (text or "").strip()
    if not phrase:
        return

    if _reject_if_wiping("review TTS"):
        return

    profile_name = get_last_active_profile()
    try:
        config = load_profile(profile_name)
    except Exception:
        config = {}

    if not bool(config.get("review_tts_enabled", True)):
        logging.info("TTS playback skipped: review_tts_enabled is False in settings.")
        return

    voice_id = normalize_tts_voice_id(config.get("review_tts_voice_hint") or "standard_female")
    quantization = str(config.get("kokoro_quantization", "fp32") or "fp32").strip()
    speed = max(0.5, min(3.0, float(config.get("review_tts_speed") or 0.95)))
    # Voice Studio's blend/modulation, carried through the same profile
    # (utils.py _profile_defaults/_sanitize_profile_values). This is the
    # canonical/automatic playback path (Review TTS hotkey, voice-command
    # read-back) — it used to call engine.speak() with only voice_id/speed,
    # silently dropping any blend or modulation the user had set up, even
    # though /tts/speak and /drafts/{id}/tts already forward both.
    blend = voice_presets._coerce_blend(config.get("review_tts_blend"))
    modulation = {
        "pitch": float(config.get("review_tts_pitch", 0.0) or 0.0),
        "energy": float(config.get("review_tts_energy", 0.5) or 0.5),
        "warmth": float(config.get("review_tts_warmth", 0.0) or 0.0),
        "brightness": float(config.get("review_tts_brightness", 0.0) or 0.0),
        "pause_style": str(config.get("review_tts_pause_style", "natural") or "natural"),
    }

    engine = ensure_tts_initialized()
    if engine is not None:
        setattr(engine, "_kokoro_quantization", quantization)
        logging.info(f"Speaking text aloud: {redact_user_text(phrase)} (voice={voice_id}, speed={speed}x, quant={quantization})")
        # Same guard as /tts/speak and /drafts/{id}/tts: a concurrent
        # destructive TTS reconfiguration (write lease) fails this fast
        # rather than letting the keyboard path bypass runtime coordination.
        try:
            with model_runtime.read_lease("tts"):
                engine.speak(phrase, speed=speed, voice_hint=voice_id, blend=blend or None, modulation=modulation)
        except RuntimeBusyError:
            logging.info("Review TTS skipped: TTS runtime is being reconfigured.")


def handle_review_tts_shortcut():
    if hotkey_manager is not None and bool(getattr(hotkey_manager, "is_recording", False)):
        logging.info("Ignored review TTS hotkey while recording is active.")
        return
    if is_processing_draft:
        logging.info("Ignored review TTS hotkey while draft processing is active.")
        return

    active_draft = None
    with draft_lock:
        if pending_manual_send_ids:
            active_draft = get_draft_by_id(pending_manual_send_ids[0])
        elif draft_queue and draft_queue[-1].get("status") in {"pending", "awaiting_manual_send"}:
            active_draft = draft_queue[-1]

    if active_draft:
        text = active_draft.get("final_text", "").strip()
        if text:
            speak_text_aloud(text)
            return

    try:
        from clipboard_capture import capture_selection_text_with_restore
        result = capture_selection_text_with_restore(timeout_ms=350, poll_ms=25)
    except Exception as exc:
        logging.exception("Review TTS shortcut selection capture failed")
        result = {"ok": False, "text": "", "message": f"Selection capture failed: {exc}"}

    if result.get("ok"):
        text = str(result.get("text", "")).strip()
        if text:
            speak_text_aloud(text)


def handle_primary_action():
    if hotkey_manager is not None and bool(getattr(hotkey_manager, "is_recording", False)):
        logging.info("Ignored primary action while recording is active.")
        return {"ok": False, "message": "Recording is active; primary action ignored."}
    if is_processing_draft:
        logging.info("Ignored primary action while draft processing is active.")
        return {"ok": False, "message": "Draft processing is active; primary action ignored."}

    while pending_manual_send_ids:
        draft_id = pending_manual_send_ids.pop(0)
        draft = get_draft_by_id(draft_id)
        if not draft or not draft.get("pending_send"):
            continue
        return send_draft_by_id(draft_id, action="paste", open_chat=False)

    try:
        from clipboard_capture import capture_selection_text_with_restore

        result = capture_selection_text_with_restore(timeout_ms=350, poll_ms=25)
    except Exception as exc:
        logging.exception("Primary action selection capture failed")
        result = {"ok": False, "text": "", "message": f"Selection capture failed: {exc}", "error": str(exc)}

    if result.get("ok"):
        text = str(result.get("text", "")).strip()
        if text:
            speak_text_aloud(text)

    broadcast_status_threadsafe("selection_captured" if result.get("ok") else "selection_capture_failed", result)
    return result


def emergency_stop_runtime():
    # Signal cancellation of draft processing
    cancellation_event.set()
    if _active_dictation_job_id:
        JOBS.request_cancel(_active_dictation_job_id)

    # Silence any active TTS speech
    if tts_engine is not None:
        try:
            tts_engine.stop_current()
        except Exception as exc:
            logging.warning(f"Emergency TTS stop failed: {exc}")

    if hotkey_manager is not None:
        try:
            hotkey_manager.request_stop(reason="emergency_stop")
        except Exception as exc:
            logging.warning(f"Emergency recording stop failed: {exc}")

    if output_injector is not None:
        try:
            output_injector.stop_typing()
            output_injector.release_mute_key()
        except Exception as exc:
            logging.warning(f"Emergency injector stop failed: {exc}")

    pending_manual_send_ids.clear()
    broadcast_status_threadsafe("emergency_stop", {"message": "Emergency stop completed."})
    return {"ok": True, "message": "Emergency stop completed."}


def toggle_recording_runtime():
    manager = start_hotkey_manager()
    if manager is None:
        raise HTTPException(status_code=500, detail="Recording runtime is unavailable.")

    was_recording = bool(getattr(manager, "is_recording", False))
    manager.request_toggle(reason="dashboard_button")
    is_recording = bool(getattr(manager, "is_recording", False))
    if is_recording:
        return {"ok": True, "recording": True, "message": "Recording started."}
    if was_recording:
        return {"ok": True, "recording": False, "message": "Recording stopped. Processing audio..."}
    return {"ok": False, "recording": False, "message": "Recording did not start. Check microphone permissions/device."}


def start_recording_runtime():
    """Explicit recording start, used for push-to-talk key-down (idempotent)."""
    manager = start_hotkey_manager()
    if manager is None:
        raise HTTPException(status_code=500, detail="Recording runtime is unavailable.")

    if bool(getattr(manager, "is_recording", False)):
        return {"ok": True, "recording": True, "message": "Already recording."}
    manager.request_start(reason="ptt")
    is_recording = bool(getattr(manager, "is_recording", False))
    if is_recording:
        return {"ok": True, "recording": True, "message": "Recording started."}
    return {"ok": False, "recording": False, "message": "Recording did not start. Check microphone permissions/device."}


def stop_recording_runtime():
    """Explicit recording stop, used for push-to-talk key-up (idempotent)."""
    manager = start_hotkey_manager()
    if manager is None:
        raise HTTPException(status_code=500, detail="Recording runtime is unavailable.")

    if not bool(getattr(manager, "is_recording", False)):
        return {"ok": True, "recording": False, "message": "Not recording."}
    manager.request_stop(reason="ptt_release")
    return {"ok": True, "recording": False, "message": "Recording stopped. Processing audio..."}


def record_pipeline_metrics(stt_ms=None, post_ms=None, llm_ms=None, total_ms=None, audio_seconds=0.0, chars=0):
    """Append one utterance's pipeline latency sample (C10 HUD)."""
    entry = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stt_ms": round(stt_ms, 1) if stt_ms is not None else None,
        "post_ms": round(post_ms, 1) if post_ms is not None else None,
        "llm_ms": round(llm_ms, 1) if llm_ms is not None else None,
        "total_ms": round(total_ms, 1) if total_ms is not None else None,
        "audio_seconds": round(float(audio_seconds or 0.0), 2),
        "chars": int(chars or 0),
    }
    with pipeline_metrics_lock:
        pipeline_metrics.append(entry)
    return entry


def _percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return round(ordered[k], 1)


def get_pipeline_metrics_summary():
    """Summary stats over the recent latency samples for the HUD."""
    with pipeline_metrics_lock:
        samples = list(pipeline_metrics)

    def stage_stats(key):
        vals = [s[key] for s in samples if s.get(key) is not None]
        if not vals:
            return {"count": 0, "avg_ms": None, "p50_ms": None, "p95_ms": None, "last_ms": None}
        return {
            "count": len(vals),
            "avg_ms": round(sum(vals) / len(vals), 1),
            "p50_ms": _percentile(vals, 50),
            "p95_ms": _percentile(vals, 95),
            "last_ms": vals[-1],
        }

    return {
        "count": len(samples),
        "stt": stage_stats("stt_ms"),
        "post": stage_stats("post_ms"),
        "llm": stage_stats("llm_ms"),
        "total": stage_stats("total_ms"),
        "recent": samples[-10:],
    }


# The real Thread class, captured at import. The heartbeat is inherently async —
# its wait-loop only exits once stop() is called from another thread. A test that
# patches threading.Thread to run workers synchronously (ImmediateThread) would
# otherwise turn start() into an infinite synchronous loop, so it must not be
# affected by that patch.
_REAL_THREAD_CLS = threading.Thread


class _StatusHeartbeat:
    """Re-broadcast a status on an interval so a long, non-chunked stage (e.g. an
    LLM cleanup of a big-but-under-the-chunk-threshold utterance) doesn't look
    frozen in the UI. Chunked work already emits per-chunk progress, so this only
    wraps the non-chunked path. ``stop()`` is idempotent and joins the thread."""

    def __init__(self, status, interval_s=4.0):
        self._status = status
        self._interval = max(0.5, float(interval_s))
        self._stop = threading.Event()
        self._thread = None
        self._start_ts = 0.0

    def start(self):
        self._start_ts = time.time()
        self._thread = _REAL_THREAD_CLS(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self):
        # wait() returns True only when stop() is set, so the loop ticks once per
        # interval until stopped and never fires an immediate duplicate.
        while not self._stop.wait(self._interval):
            try:
                elapsed_ms = round((time.time() - self._start_ts) * 1000.0)
                broadcast_status_threadsafe(self._status, {"elapsed_ms": elapsed_ms, "heartbeat": True})
            except Exception as exc:
                logging.debug(f"Status heartbeat broadcast failed: {exc}")

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._thread = None


class _RecordingsRecoverySink:
    """Real ``RecoverySinkLike`` adapter (A1.6 risk #2): persists the raw
    recording via the ``recordings`` module, matching the pre-A1.9 inline
    persist-audio call exactly (same metadata shape, same swallow-and-log
    error handling so a disk failure never breaks dictation)."""

    def save(self, recording_result, *, reason):
        try:
            recordings.save_recording(
                recording_result,
                rec_id=recordings.new_rec_id(),
                metadata={"stop_reason": getattr(recording_result, "stop_reason", "manual")},
            )
        except Exception as exc:
            logging.debug(f"Could not persist recording: {exc}")
        return None


_dictation_recovery_sink = _RecordingsRecoverySink()


def process_recording_result(
    recording_result,
    streamed_text=None,
    streamed_confidence=None,
    streamed_stt_ms=None,
    wait_for_gate=False,
):
    """Run one recording through STT → post-passes → LLM cleanup → draft.

    ``streamed_text`` (from a StreamingTranscriptionSession) skips the
    full-audio Whisper pass — the transcript was already built while the user
    was still talking. ``wait_for_gate`` is the held-queue dispatcher's mode:
    block until the running pipeline finishes instead of rejecting, so
    back-to-back recordings are processed in order rather than bounced.
    """
    global is_processing_draft, _active_dictation_job_id
    # A privacy wipe must operate on a quiescent system: never start (or
    # recover-save) a recording while one is running, or it would regrow data
    # the wipe is trying to erase.
    if privacy_wipe_in_progress.is_set():
        logging.info("Dropping recording: a privacy wipe is in progress.")
        broadcast_status_threadsafe(
            "dictation_busy",
            {"message": "A privacy wipe is in progress; this recording was discarded."},
        )
        return None
    # Atomic admission: exactly one pipeline may run. A rejected competitor
    # must not clear the running job's cancellation event, overwrite its
    # active id, or share the STT/LLM instances — so it persists its audio to
    # the recovery bin and bows out (callers surface 409 / a busy status).
    # The dispatcher instead waits its turn (bounded, so a wedged pipeline
    # degrades to the recovery-save path rather than deadlocking the queue).
    admitted = (
        dictation_coordinator.begin(timeout=600.0)
        if wait_for_gate
        else dictation_coordinator.try_begin()
    )
    if not admitted:
        logging.warning("Dictation pipeline busy; rejecting competing invocation.")
        # Re-check the wipe flag: it may have been set after the top guard.
        # A rejected recording must not seed the recovery bin during a wipe.
        if not privacy_wipe_in_progress.is_set():
            try:
                recordings.save_recording(
                    recording_result,
                    rec_id=recordings.new_rec_id(),
                    metadata={
                        "stop_reason": getattr(recording_result, "stop_reason", "manual"),
                        "rejected_reason": "pipeline_busy",
                    },
                )
            except Exception as exc:
                logging.debug(f"Could not persist rejected recording: {exc}")
        broadcast_status_threadsafe(
            "dictation_busy",
            {"message": "A dictation is already processing; recording saved to recovery."},
        )
        return None
    # Re-check the wipe AFTER admission: a wipe may have begun while this
    # caller was blocked in begin() (or between try_begin and here). Running
    # the pipeline now would save/create data behind the wipe's back.
    if privacy_wipe_in_progress.is_set():
        dictation_coordinator.finish()
        logging.info("Dropping recording: a privacy wipe began while awaiting the pipeline gate.")
        broadcast_status_threadsafe(
            "dictation_busy",
            {"message": "A privacy wipe is in progress; this recording was discarded."},
        )
        return None
    # Admission is won. From here the gate MUST be released on every exit.
    # Registering the job (and its first transition) runs in its own guard so a
    # failure there cannot leak the gate or leave is_processing_draft stuck —
    # the main try/finally below only starts after the job exists. The job is
    # created here (not inside the pipeline) so its id is visible to external
    # cancel-dispatch (emergency stop, /jobs/{id}/cancel) before any stage runs.
    try:
        with draft_lock:
            is_processing_draft = True
        # Register this dictation as a job so the UI can observe/cancel it (§6.3).
        job = JOBS.create("dictation", label="Dictation")
        _active_dictation_job_id = job.id
        dictation_coordinator.set_active_job(job.id)
        JOBS.transition(job.id, JobState.TRANSCRIBING)
    except Exception as exc:
        logging.error(f"Failed to start dictation job: {exc}")
        with draft_lock:
            is_processing_draft = False
        _active_dictation_job_id = None
        dictation_coordinator.finish()
        broadcast_status_threadsafe("idle")
        return None

    preset = "True Janitor"
    raw_text = ""
    final_text = ""
    dict_terms = []
    confidence = {"score": None, "avg_logprob": None, "no_speech_prob": None}
    profile_config = {}
    pipeline_flags = {}
    stt_ms = post_ms = llm_ms = None
    try:
        metadata = get_recording_metadata(recording_result)
    except Exception as exc:
        logging.debug(f"metadata extraction failed: {exc}")
        metadata = {}
    pipeline_t0 = time.perf_counter()

    # Named stages, each a thin wrapper around the exact logic that used to be
    # inlined here — composed and run by DictationPipeline (backend/services/
    # dictation_pipeline.py), which owns cancellation checks (before every
    # stage, matching the four former check_cancelled() call sites),
    # recovery-first persistence, and per-stage JobState transitions. These
    # closures read/write the locals above via `nonlocal` so the outer
    # cancelled/failed handling below sees the same state the old inline
    # except-blocks did.

    def _stage_transcribe(ctx, deps):
        nonlocal raw_text, confidence, stt_ms, dict_terms
        broadcast_status_threadsafe("transcribing")
        audio_data = getattr(recording_result, "audio_data", recording_result)
        # Personal dictionary (C1): bias the ASR toward the user's terms.
        dict_terms = dictionary.get_terms()
        _stt_start = time.perf_counter()
        confidence = {"score": None, "avg_logprob": None, "no_speech_prob": None}
        if streamed_text is not None and str(streamed_text).strip():
            # The transcript was already built batch-by-batch while the user
            # was still talking; the only STT cost paid here was draining the
            # tail (streamed_stt_ms, measured by the dispatcher).
            raw_text = str(streamed_text)
            if isinstance(streamed_confidence, dict) and streamed_confidence:
                confidence = streamed_confidence
            stt_ms = streamed_stt_ms
        else:
            trans = ensure_transcriber_initialized(preload=False)
            hotwords = dictionary.hotwords_string(dict_terms)
            if hasattr(audio_data, "size") and audio_data.size <= 0:
                raw_text = ""
            elif audio_data is None:
                raw_text = ""
            else:
                # STT read lease: a Whisper reload/unload cannot free the model
                # mid-transcription (it will 409 or wait for this to finish).
                with model_runtime.read_lease("stt"):
                    if hasattr(trans, "transcribe_with_structured"):
                        # Single decode covers both the legacy confidence dict and
                        # the structured segments (I3.1) — transcribe_with_confidence
                        # + transcribe_structured would each decode independently.
                        raw_text, confidence, structured = trans.transcribe_with_structured(audio_data, hotwords=hotwords)
                        ctx.extra["transcription_result"] = structured
                        try:
                            ctx.extra["speech_signals"] = compute_speech_signals(
                                structured.segments, audio_duration_s=structured.audio_duration_s,
                            )
                        except Exception as exc:
                            logging.debug(f"speech signal computation failed: {exc}")
                    elif hasattr(trans, "transcribe_with_confidence"):
                        raw_text, confidence = trans.transcribe_with_confidence(audio_data, hotwords=hotwords)
                    else:
                        raw_text = trans.transcribe(audio_data)
            # Inside the else-branch on purpose: the streamed path already set
            # stt_ms to the dispatcher-measured tail-drain time.
            stt_ms = (time.perf_counter() - _stt_start) * 1000.0
        ctx.raw_text = raw_text

    def _stage_post_process(ctx, deps):
        nonlocal raw_text, preset, profile_config, pipeline_flags, post_ms
        _post_start = time.perf_counter()
        # Post-ASR correction snaps near-miss tokens back to dictionary terms.
        if raw_text and dict_terms:
            raw_text = dictionary.correct_text(raw_text, dict_terms)
        # ONE profile read backs the entire dictation pipeline — the toggles
        # below, the no-audio gate, and the LLM chunking settings further down.
        # Each load_profile() call is disk I/O + YAML parse, so the hot path
        # loads once and shares the dict.
        profile_config = get_active_recording_config()
        pipeline_flags = get_pipeline_flags(profile_config)
        # Honour the user's selected persona for cleanup. resolve_dictation_preset
        # falls back to True Janitor when the selection is empty or names a persona
        # that no longer exists, so a stale choice never breaks the core loop.
        preset = resolve_dictation_preset(pipeline_flags["current_preset"])
        # Phrase-history "scratch that": undo the previous utterance instead of
        # treating this one as new dictation. Checked before any other pass so
        # the command phrase itself never reaches the LLM.
        if raw_text and pipeline_flags["editing_commands"]:
            edit_cmd = voice_edit_commands.parse_edit_command(raw_text)
            if edit_cmd and edit_cmd.action == "scratch_that":
                popped = utterance_history.pop_last()
                draft = create_draft(
                    raw_text,
                    "",
                    preset=preset,
                    status="scratch",
                    metadata=metadata,
                    recording_result=recording_result,
                )
                broadcast_status_threadsafe(
                    "scratch_last",
                    {
                        "draft_id": draft["id"],
                        "scratched_draft_id": popped.target_draft_id if popped else None,
                        "scratched_text": popped.final_text if popped else "",
                    },
                )
                ctx.raw_text = raw_text
                ctx.draft = draft
                ctx.extra["result_ref"] = f"draft:{draft['id']}"
                ctx.extra["_pipeline_stop"] = True
                return
            raw_text = voice_edit_commands.apply_inline_edits(raw_text)
        # Spoken dictation commands (C2): "new paragraph", "period", "all caps", ...
        if raw_text and pipeline_flags["voice_commands"]:
            raw_text = dictation_commands.apply_commands(raw_text)
        # Voice macros (C11): expand user snippets like "my address".
        if raw_text and pipeline_flags["macros"]:
            raw_text = macros.apply_macros(raw_text)
        post_ms = (time.perf_counter() - _post_start) * 1000.0
        ctx.raw_text = raw_text

    def _stage_no_audio_gate(ctx, deps):
        blocked, reasons = should_block_for_no_audio(
            recording_result,
            raw_text,
            profile_config,
        )
        if blocked:
            draft = create_draft(
                raw_text,
                "",
                preset=preset,
                status="blocked",
                metadata=metadata,
                error="No usable audio was recorded.",
                gate_reasons=reasons,
                recording_result=recording_result,
                transcription_result=_serialize_optional_contract(ctx.extra.get("transcription_result")),
                speech_signals=_serialize_optional_contract(ctx.extra.get("speech_signals")),
            )
            broadcast_status_threadsafe(
                "draft_blocked",
                {
                    "draft_id": draft["id"],
                    "raw_text": draft["raw_text"],
                    "final_text": draft["final_text"],
                    "error": draft["error"],
                    "gate_reasons": draft["gate_reasons"],
                    "token_count": draft["token_count"],
                    "token_limit": draft["token_limit"],
                    "long_text": draft["long_text"],
                },
            )
            ctx.draft = draft
            ctx.extra["result_ref"] = f"draft:{draft['id']}"
            ctx.extra["_pipeline_stop"] = True

    def _stage_rewrite(ctx, deps):
        nonlocal final_text, llm_ms
        broadcast_status_threadsafe("rewriting")
        engine = get_selected_llm_engine()
        # llm_chunk_size + completion cap come from the profile dict already
        # loaded at the top of this request (no second disk read).
        try:
            llm_chunk_size = profile_config.get("llm_chunk_size", 750)
            completion_tokens = int(profile_config.get("max_completion_tokens") or profile_config.get("output_token_limit", 1600) or 1600)
            stitch_enabled = bool(profile_config.get("long_recording_stitch_pass_enabled", True))
        except Exception:
            llm_chunk_size = 750
            completion_tokens = 1600
            stitch_enabled = True

        _llm_start = time.perf_counter()
        # Long recordings (word count over the chunk threshold) get progress
        # notifications so the user sees chunk-by-chunk progress instead of a
        # silent wait. The review overlay stays closed until preview_ready.
        will_chunk = len(str(raw_text or "").split()) > llm_chunk_size

        def _chunk_progress(update):
            if not isinstance(update, dict):
                return
            status = update.get("status")
            if not status:
                return
            broadcast_status_threadsafe(
                status,
                {k: v for k, v in update.items() if k != "status"},
            )

        if will_chunk:
            broadcast_status_threadsafe(
                "long_recording_detected",
                {"word_count": len(raw_text.split()), "chunk_size": llm_chunk_size},
            )

        # A non-chunked LLM call emits no progress; a heartbeat keeps the
        # "rewriting" status fresh so a long single-utterance cleanup doesn't
        # look frozen. Chunked work already reports per-chunk progress.
        heartbeat = None if will_chunk else _StatusHeartbeat("rewriting").start()
        try:
            # LLM read lease: an unload/reload/select can't drop the runtime
            # while this cleanup awaits llama-server.
            with model_runtime.read_lease("llm"):
                final_text = engine.process_fast_lane(
                    raw_text,
                    preset,
                    max_output_tokens=completion_tokens,
                    chunk_size=llm_chunk_size,
                    progress_callback=_chunk_progress if will_chunk else None,
                    stitch_pass=stitch_enabled,
                )
        finally:
            if heartbeat is not None:
                heartbeat.stop()
        llm_ms = (time.perf_counter() - _llm_start) * 1000.0
        ctx.final_text = final_text

    def _stage_finalize(ctx, deps):
        draft = create_draft(
            raw_text,
            final_text,
            preset=preset,
            metadata=metadata,
            recording_result=recording_result,
            confidence=confidence,
            transcription_result=_serialize_optional_contract(ctx.extra.get("transcription_result")),
            speech_signals=_serialize_optional_contract(ctx.extra.get("speech_signals")),
        )
        if pipeline_flags["editing_commands"]:
            utterance_history.record(
                Utterance(
                    raw_transcript=raw_text,
                    final_text=final_text,
                    emitted_length=len(final_text or ""),
                    target_draft_id=draft["id"],
                    timestamp=time.time(),
                    injected=False,
                )
            )
        record_pipeline_metrics(
            stt_ms=stt_ms,
            post_ms=post_ms,
            llm_ms=llm_ms,
            total_ms=(time.perf_counter() - pipeline_t0) * 1000.0,
            audio_seconds=float(getattr(recording_result, "duration_seconds", 0.0) or 0.0),
            chars=len(final_text or ""),
        )
        broadcast_status_threadsafe(
            "preview_ready",
            {
                "draft_id": draft["id"],
                "raw_text": draft["raw_text"],
                "final_text": draft["final_text"],
                "token_count": draft["token_count"],
                "token_limit": draft["token_limit"],
                "long_text": draft["long_text"],
                "confidence": draft["confidence"],
                "auto_send_ok": draft["auto_send_ok"],
                "force_review": draft["force_review"],
                "force_review_reason": draft["force_review_reason"],
            },
        )
        ctx.draft = draft
        ctx.extra["result_ref"] = f"draft:{draft['id']}"

    stages = [
        FunctionStage(name="transcribe", func=_stage_transcribe),
        FunctionStage(name="post_process", func=_stage_post_process),
        FunctionStage(name="no_audio_gate", func=_stage_no_audio_gate),
        FunctionStage(name="rewrite", func=_stage_rewrite, job_state=JobState.REFINING),
        FunctionStage(name="finalize", func=_stage_finalize, job_state=JobState.REVIEW_READY),
    ]
    deps = PipelineDependencies(
        job_manager=JobManagerCancellationBridge(JOBS, cancellation_event),
        recovery_sink=_dictation_recovery_sink,
    )
    pipeline = DictationPipeline(stages, deps, kind="dictation", label="Dictation")

    try:
        outcome = pipeline.run(recording_result, metadata=metadata, job=job)
        if outcome.completed:
            return outcome.context.draft
        if outcome.cancelled:
            logging.info("Recording processing was cancelled by the user.")
            error_msg = outcome.error or "Operation cancelled by user."
            draft = create_draft(
                raw_text,
                "",
                preset=preset,
                status="error",
                metadata=metadata,
                error=error_msg,
                recording_result=recording_result,
            )
            broadcast_status_threadsafe(
                "draft_error",
                {
                    "draft_id": draft["id"],
                    "raw_text": draft["raw_text"],
                    "final_text": draft["final_text"],
                    "error": draft["error"],
                    "token_count": draft["token_count"],
                    "token_limit": draft["token_limit"],
                    "long_text": draft["long_text"],
                },
            )
            broadcast_status_threadsafe("error", {"message": error_msg, "draft_id": draft["id"]})
            return draft
        # Failed: any exception raised by a stage lands here (mirrors the old
        # inline `except Exception as exc:` branch exactly).
        exc = outcome.exception if outcome.exception is not None else Exception(outcome.error)
        logging.error(f"Recording processing failed: {redact_exc(exc)}")
        record_runtime_error("recording", outcome.error)
        draft = create_draft(
            raw_text,
            "",
            preset=preset,
            status="error",
            metadata=metadata,
            error=outcome.error,
            recording_result=recording_result,
        )
        broadcast_status_threadsafe(
            "draft_error",
            {
                "draft_id": draft["id"],
                "raw_text": draft["raw_text"],
                "final_text": draft["final_text"],
                "error": draft["error"],
                "token_count": draft["token_count"],
                "token_limit": draft["token_limit"],
                "long_text": draft["long_text"],
            },
        )
        broadcast_status_threadsafe("error", {"message": outcome.error, "draft_id": draft["id"]})
        return draft
    finally:
        with draft_lock:
            is_processing_draft = False
        # Guarantee the job reaches a terminal state even on an unexpected exit.
        active = JOBS.get(job.id)
        if active is not None and not active.is_terminal:
            JOBS.fail(job.id, "processing ended without a terminal state")
        _active_dictation_job_id = None
        dictation_coordinator.finish()
        broadcast_status_threadsafe("idle")


# Hotkey Callbacks
import asyncio
loop = None

def on_recording_start():
    broadcast_status_threadsafe("recording_started")
    _begin_stream_session()

def on_recording_complete(recording_result):
    try:
        size = len(recording_result.audio_data)
    except Exception:
        size = len(recording_result) if recording_result is not None else 0
    logging.info(f"CALLBACK: Recording Complete ({size} samples)")
    broadcast_status_threadsafe("recording_complete", {"sample_count": size})
    # Hand off to the dispatcher and return immediately: the hotkey thread is
    # free to start the next recording right away — the user is never blocked
    # on transcription or the LLM.
    _enqueue_recording(recording_result, _detach_stream_session())


def _ensure_recording_dispatcher():
    global _recording_dispatcher_thread
    with _recording_dispatcher_lock:
        if _recording_dispatcher_thread is not None and _recording_dispatcher_thread.is_alive():
            return
        # _REAL_THREAD_CLS, not threading.Thread: the dispatcher loop is
        # infinite by design, so a test's ImmediateThread patch must never run
        # it synchronously (same rationale as _StatusHeartbeat).
        _recording_dispatcher_thread = _REAL_THREAD_CLS(
            target=_recording_dispatcher_loop,
            daemon=True,
            name="betterfingers-recording-dispatcher",
        )
        _recording_dispatcher_thread.start()


def _enqueue_recording(recording_result, stream_session=None):
    """Hold a finished recording for in-order processing (never reject)."""
    _ensure_recording_dispatcher()
    depth = _pending_recordings.qsize()
    if depth >= MAX_PENDING_RECORDINGS:
        # Safety valve against unbounded RAM growth if the pipeline wedges:
        # persist to the recovery bin exactly like the old rejection path.
        if stream_session is not None:
            stream_session.abort()
        if not privacy_wipe_in_progress.is_set():
            try:
                recordings.save_recording(
                    recording_result,
                    rec_id=recordings.new_rec_id(),
                    metadata={
                        "stop_reason": getattr(recording_result, "stop_reason", "manual"),
                        "rejected_reason": "queue_full",
                    },
                )
            except Exception as exc:
                logging.debug(f"Could not persist overflow recording: {exc}")
        broadcast_status_threadsafe(
            "dictation_busy",
            {"message": "Too many recordings are waiting; this one was saved to recovery."},
        )
        return
    _pending_recordings.put((recording_result, stream_session, _pending_drop_generation))
    if depth > 0 or dictation_coordinator.is_busy():
        broadcast_status_threadsafe("dictation_queued", {"position": depth + 1})


def _drop_pending_recordings():
    """Privacy wipe: discard every held recording and poison items already
    dequeued but not yet processed (generation bump). Returns the drop count."""
    global _pending_drop_generation
    _pending_drop_generation += 1
    dropped = 0
    while True:
        try:
            item = _pending_recordings.get_nowait()
        except queue.Empty:
            break
        if item is None:
            continue
        _, session, _ = item
        if session is not None:
            session.abort()
        dropped += 1
    active = _detach_stream_session()
    if active is not None:
        active.abort()
    return dropped


def _recording_dispatcher_loop():
    while True:
        item = _pending_recordings.get()
        if item is None:
            continue
        recording_result, session, generation = item
        try:
            if generation != _pending_drop_generation or privacy_wipe_in_progress.is_set():
                # Invalidated by a privacy wipe after being queued/dequeued.
                if session is not None:
                    session.abort()
                logging.info("Dropping held recording: invalidated by privacy wipe.")
                continue
            streamed_text = None
            streamed_conf = None
            streamed_stt_ms = None
            if session is not None:
                _drain_start = time.perf_counter()
                fin = session.finalize()
                if fin.get("ok") and str(fin.get("text") or "").strip():
                    streamed_text = fin["text"]
                    streamed_conf = fin.get("confidence")
                    # The user-visible STT cost of this recording is just the
                    # tail drain — the batches ran during recording.
                    streamed_stt_ms = (time.perf_counter() - _drain_start) * 1000.0
                    logging.info(
                        f"Streaming STT covered {fin.get('batches', 0)} batches; "
                        f"drain took {streamed_stt_ms:.0f}ms."
                    )
            process_recording_result(
                recording_result,
                streamed_text=streamed_text,
                streamed_confidence=streamed_conf,
                streamed_stt_ms=streamed_stt_ms,
                wait_for_gate=True,
            )
        except Exception as exc:
            logging.error(f"Recording dispatcher failed: {redact_exc(exc)}")

@app.on_event("startup")
async def startup_event():
    global loop, _warmup_thread
    # Auth gate first: covers `uvicorn server:app` as well as `python
    # server.py`, and fails startup in production if no token is configured.
    enforce_startup_security()
    # Consolidate any legacy/split data root into the unified base (idempotent).
    # Guarded from the test suite so running tests never moves real user data.
    if not _is_test_env():
        try:
            import app_paths
            report = app_paths.migrate_legacy_data()
            if report.get("moved"):
                logging.info("Migrated legacy data into %s: %s", report["target"], report["moved"])
        except Exception as exc:
            logging.warning(f"Legacy data migration skipped: {exc}")
    loop = asyncio.get_event_loop()
    # SQLite-first (history_store is canonical); load_draft_history() falls
    # back to draft_history.json only if the DB is empty/unrecoverable, and
    # imports+retires the JSON as a migration backup when it does (C8/P1).
    load_draft_history()
    # Reconcile any draft a crashed process left mid-send (→ send_interrupted,
    # outcome unknown) so it is never silently double-sent or silently dropped.
    recover_interrupted_sends()
    lazy_startup = is_lazy_startup_enabled()
    residency_settings = get_model_residency_settings()
    for component, pinned in residency_settings.items():
        model_runtime.set_pinned(component, pinned)

    def background_warmup():
        try:
            logging.info("Initializing Transcriber...")
            ensure_transcriber_initialized(preload=bool(residency_settings.get("stt")))
            logging.info("Transcriber initialized successfully.")
        except Exception as e:
            logging.error(f"Transcriber startup failure: {e}")
            record_runtime_error("stt", str(e))

        if any(residency_settings.values()):
            warm_results = warm_start_resident_models(residency_settings)
            logging.info(f"Keep-loaded startup results: {warm_results}")
        else:
            logging.info("No keep-loaded model residency flags are enabled; model startup is deferred.")

    _warmup_thread = threading.Thread(target=background_warmup, daemon=True, name="betterfingers-warmup")
    _warmup_thread.start()

    if lazy_startup:
        logging.info("Lazy startup enabled; deferring Hotkey Manager startup.")
        return

    try:
        manager = start_hotkey_manager()
        hook_errors = list(getattr(manager, "keyboard_hook_errors", [])) if manager else []
        if hook_errors:
            message = "Hotkey Manager started, but keyboard hooks are unavailable: " + "; ".join(hook_errors)
            logging.warning(message)
            record_runtime_error("hotkeys", message, {"action": "startup", "degraded": True})
        else:
            logging.info("Hotkey Manager started.")
    except Exception as e:
        logging.error(f"Hotkey Manager startup failure: {e}")
        record_runtime_error("hotkeys", str(e))

@app.on_event("shutdown")
def shutdown_event():
    stop_hotkey_manager()
    # Safety net in case /wake/disable was never called before shutdown --
    # idempotent, safe even if wake word was never enabled this run.
    import routes_wake
    routes_wake.stop_wake_listener()
    # Join the background warmup thread so it can't outlive this app instance and
    # mutate global model state afterwards (also keeps tests deterministic).
    thread = _warmup_thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=5)

from fastapi import Query, status

@app.websocket("/ws/voice_status")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(None)):
    # First-message auth: the bearer token must arrive as the first frame
    # ("auth:<token>"), not in the query string — query strings leak into
    # proxy logs, diagnostics, and crash reports. The legacy ?token= form is
    # still accepted for one release (logged as deprecated).
    expected_token = os.getenv("BETTERFINGERS_AUTH_TOKEN")
    await websocket.accept()
    if expected_token:
        authed = False
        if token is not None and hmac.compare_digest(str(token), expected_token):
            logging.warning("WS auth via query string is deprecated; send an 'auth:<token>' first message.")
            authed = True
        else:
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
    active_websockets.append(websocket)
    try:
        while True:
            # Keep alive / listen for client commands (like 'cancel')
            data = await websocket.receive_text()
            # Handle client commands if needed
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        active_websockets.remove(websocket)
    except Exception as e:
        logging.error(f"WebSocket Error: {e}")
        if websocket in active_websockets:
            active_websockets.remove(websocket)


def ensure_tts_initialized():
    global tts_engine
    if tts_engine is None:
        try:
            from tts_engine import ReviewTTSEngine
            tts_engine = ReviewTTSEngine()
            if hasattr(tts_engine, "set_admission_fn"):
                tts_engine.set_admission_fn(lambda est, mid=None: model_runtime.request_admission("tts", est, mid))
            if hasattr(tts_engine, "set_load_reporter"):
                tts_engine.set_load_reporter(lambda mid, est: model_runtime.note_loaded("tts", mid, est))

            def tts_start_callback(text):
                broadcast_status_threadsafe("draft_tts_started", {"text": text})
                
            def tts_stop_callback():
                broadcast_status_threadsafe("draft_tts_stopped", {})
                
            tts_engine.on_start = tts_start_callback
            tts_engine.on_stop = tts_stop_callback
        except Exception as e:
            logging.error(f"Failed to load ReviewTTSEngine: {e}")
            record_runtime_error("tts", str(e))
    return tts_engine


def normalize_tts_voice_id(voice_id):
    value = str(voice_id or "").strip()
    aliases = {
        "standard_female": "af_heart",
        "standard_male": "am_puck",
        "female": "af_heart",
        "male": "am_puck",
    }
    return aliases.get(value.lower(), value or "english")


cached_audio_devices = None
cached_audio_devices_lock = threading.Lock()


def get_audio_devices(refresh=False):
    global cached_audio_devices
    with cached_audio_devices_lock:
        if cached_audio_devices is None or refresh:
            try:
                import sounddevice as sd
                devices = []
                for idx, dev in enumerate(sd.query_devices()):
                    devices.append({
                        "index": idx,
                        "name": str(dev.get("name", "")),
                        "max_input_channels": int(dev.get("max_input_channels", 0)),
                        "max_output_channels": int(dev.get("max_output_channels", 0)),
                        "default_samplerate": float(dev.get("default_samplerate", 0.0)),
                    })
                
                default_input = -1
                default_output = -1
                try:
                    default_input = int(sd.default.device[0])
                    default_output = int(sd.default.device[1])
                except Exception:
                    pass

                cached_audio_devices = {
                    "devices": devices,
                    "default_input_device": default_input,
                    "default_output_device": default_output,
                    "error": None,
                }
            except Exception as e:
                logging.warning(f"Failed to query sound devices: {e}")
                cached_audio_devices = {
                    "devices": [],
                    "default_input_device": -1,
                    "default_output_device": -1,
                    "error": str(e),
                }
        return dict(cached_audio_devices)


@app.get("/runtime/version")
async def runtime_version():
    return {
        "backend_version": "0.1.0",
        "expected_electron_api_version": "0.1.0",
        "schema_version": 1,
        "config_version": 1,
    }


@app.get("/runtime/audio-devices")
async def list_audio_devices():
    return get_audio_devices()


@app.post("/runtime/audio-devices/refresh")
async def refresh_audio_devices():
    return get_audio_devices(refresh=True)


@app.get("/doctor")
async def run_doctor(refresh_audio: bool = False):
    engine = get_engine_if_initialized()
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
    stt_fallback_reason = getattr(transcriber, "device_fallback_reason", None) if transcriber else None
    stt_info = {
        "initialized": transcriber is not None,
        "loaded": bool(getattr(transcriber, "model", None)) if transcriber else False,
        "model_size": getattr(transcriber, "model_size", None) if transcriber else None,
        "device": getattr(transcriber, "active_device", None) if transcriber else None,
        "compute_type": getattr(transcriber, "active_compute_type", None) if transcriber else None,
        "device_fallback_reason": stt_fallback_reason,
        "using_cpu_fallback": bool(stt_fallback_reason),
    }

    # LLM details
    selected_model_id = model_id or get_selected_llm_model_id()
    llama_server_path = str(get_server_path())
    llama_server_exists = os.path.exists(llama_server_path)
    model_exists = check_model_exists(selected_model_id)
    runtime_validation = (
        validate_llama_server_runtime(llama_server_path)
        if llama_server_exists
        else {"ok": False, "message": "llama-server binary is missing."}
    )
    required_runtime_build = required_llama_server_build(selected_model_id)
    runtime_build = runtime_validation.get("build")
    runtime_build_ok = (
        not required_runtime_build
        or (runtime_build is not None and int(runtime_build) >= required_runtime_build)
    )
    llm_last_error = str(getattr(engine, "_last_error", "") or "") if engine else ""
    if not llama_server_exists:
        llm_runtime_status = "missing_llama_server"
    elif not model_exists:
        llm_runtime_status = "missing_model"
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
        "runtime_message": runtime_validation.get("message", ""),
        "last_error": llm_last_error,
        "last_error_details": dict(getattr(engine, "_last_error_details", {}) or {}) if engine else {},
    }

    # TTS details
    tts_engine_inst = await run_in_threadpool(ensure_tts_initialized)
    tts_info = {
        "initialized": tts_engine_inst is not None,
        "loaded": tts_engine_inst.is_loaded() if tts_engine_inst else False,
        "backend": tts_engine_inst.backend() if tts_engine_inst else "none",
        "status_message": tts_engine_inst._status_message if tts_engine_inst else "TTS is not initialized.",
        "fallback": tts_engine_inst._fallback if tts_engine_inst else False,
    }

    # Hotkeys details
    hotkeys_info = {
        "started": hotkey_manager_started,
        "active": hotkey_manager is not None and getattr(hotkey_manager, "_running", False),
        "keyboard_hooks_ok": bool(hotkey_manager is not None and not getattr(hotkey_manager, "keyboard_hook_errors", [])),
        "keyboard_hook_errors": list(getattr(hotkey_manager, "keyboard_hook_errors", [])) if hotkey_manager else [],
    }

    # Models dir
    model_dir = Path(get_model_path(DEFAULT_MODEL)).parent
    model_path_info = {
        "models_dir": str(model_dir),
        "models_dir_exists": os.path.exists(model_dir),
        "default_model_path": str(get_model_path(DEFAULT_MODEL)),
        "default_model_exists": os.path.exists(get_model_path(DEFAULT_MODEL)),
    }

    # Audio
    audio_info = get_audio_devices(refresh=refresh_audio)

    # Capabilities
    platform_info = get_capabilities()

    # Hardware specs + model-fit assessment for the selected LLM
    hardware_info = get_hardware_report()
    model_fit_info = assess_model_fit(selected_model_id, report=hardware_info)
    hardware_tier_info = get_hardware_tier(report=hardware_info)

    # Recovery instructions
    recovery_guidelines = {
        "missing_model": "Go to the Models screen to download the recommended LLM or Whisper models, or verify that the GGUF/Whisper files exist in the models directory.",
        "missing_llama_server": "llama-server binary could not be found. If you are on Linux, please compile or install llama-server and set the BETTERFINGERS_LLAMA_SERVER environment variable.",
        "runtime_link_failure": "llama-server exists, but its shared runtime libraries are incomplete. Reinstall the runtime or repair the Linux .so symlinks in the models directory.",
        "runtime_outdated": "The selected model requires a newer llama.cpp runtime. Download or reinstall the LLM runtime from the Models screen.",
        "port_conflict": "Port 8000 is occupied by another process. Please close the conflicting application or configure a different port.",
        "microphone_unavailable": "No input audio devices were detected, or microphone permission was denied. Please connect a microphone and ensure BetterFingers has permission to access it.",
        "unsupported_wayland_injection": "Typing and pasting injection are not supported under Wayland. BetterFingers has safely fallen back to copying text to the clipboard.",
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
        "store_warnings": get_degraded_events(),
    }


@app.get("/hardware/tier")
async def hardware_tier():
    return {"ok": True, "tier": get_hardware_tier()}


@app.get("/models/recommend")
async def models_recommend():
    import model_recommender

    report = get_hardware_report()
    tier_info = get_hardware_tier(report=report)
    ram_mb = (report.get("memory") or {}).get("total_mb") or 0
    recommendation = model_recommender.recommend(tier_info["tier"], ram_mb)
    recommendation["tier_label"] = tier_info.get("label")
    recommendation["tier_guidance"] = tier_info.get("guidance")
    return {"ok": True, "recommendation": recommendation}


@app.get("/health")
async def health_check():

    engine_ready = False
    try:
        engine = get_engine_if_initialized()
        engine_ready = bool(getattr(engine, "_ready", False)) if engine else False
    except Exception:
        pass

    # Active-job visibility for the supervisor: a busy backend is not a dead
    # backend. Everything here is in-memory — /health must stay free of model
    # loads, device scans, and filesystem walks.
    active_jobs = []
    last_progress_at = None
    try:
        active_jobs = JOBS.list(active_only=True)
        if active_jobs:
            last_progress_at = max(j.get("updated_at") or 0 for j in active_jobs)
    except Exception:
        pass

    return {
        "status": "active",
        "transcriber": transcriber is not None,
        "llm_engine": engine_ready,
        "active_job_count": len(active_jobs),
        "active_jobs": [
            {"id": j.get("id"), "kind": j.get("kind"), "state": j.get("state"), "updated_at": j.get("updated_at")}
            for j in active_jobs[:5]
        ],
        "last_progress_at": last_progress_at,
        # Which model runtimes currently hold a read (inference) or write
        # (reconfigure) lease — lets the supervisor and diagnostics see live work.
        "runtime_leases": model_runtime.active_leases(),
    }


class RuntimeWarmupRequest(BaseModel):
    stt: bool = False
    llm: bool = False
    hotkeys: bool = False


@app.get("/runtime/status")
async def runtime_status():
    return get_runtime_status_snapshot()


@app.get("/runtime/output-settings")
async def runtime_output_settings():
    settings: typing.Dict[str, typing.Any] = dict(get_profile_output_settings())
    settings["pending_manual_send_ids"] = list(pending_manual_send_ids)
    settings["supported_actions"] = ["copy_only", "paste", "type", "open_chat_then_send"]
    settings["capabilities"] = get_capabilities()
    return settings


class ProfileSaveRequest(BaseModel):
    settings: dict


class ProfileCreateRequest(BaseModel):
    name: str
    settings: dict = {}


class ProfileRenameRequest(BaseModel):
    new_name: str


class ProfileDuplicateRequest(BaseModel):
    new_name: str


class ProfileImportRequest(BaseModel):
    kind: str = "betterfingers_profile"
    schema_version: int = 1
    name: str
    settings: dict


@app.post("/settings/profiles/import")
async def settings_import_profile(request: ProfileImportRequest):
    if request.kind != "betterfingers_profile":
        raise HTTPException(status_code=400, detail="Invalid profile format: missing 'betterfingers_profile' kind.")
    if request.schema_version != 1:
        raise HTTPException(status_code=400, detail=f"Unsupported profile schema version: {request.schema_version}")

    safe_name = sanitize_profile_name(request.name)
    if safe_name in list_profiles():
        raise HTTPException(status_code=409, detail="Profile name already exists")
    
    try:
        save_runtime_profile(safe_name, request.settings)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {e}")
        
    return get_active_profile_payload()


@app.get("/settings/profiles")
async def settings_profiles():
    return get_active_profile_payload()


@app.get("/settings/profiles/{profile_name}")
async def settings_profile(profile_name: str):
    safe_name = sanitize_profile_name(profile_name)
    return {
        "profile": safe_name,
        "active": safe_name == get_last_active_profile(),
        "settings": load_profile(safe_name),
    }


@app.post("/settings/profiles/{profile_name}")
async def settings_save_profile(profile_name: str, request: ProfileSaveRequest):
    safe_name = sanitize_profile_name(profile_name)
    try:
        save_runtime_profile(safe_name, request.settings)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Save failed: {e}")
    if safe_name == get_last_active_profile():
        apply_active_profile_runtime(safe_name)
    return {
        "profile": safe_name,
        "active": safe_name == get_last_active_profile(),
        "settings": load_profile(safe_name),
    }


@app.post("/settings/profiles")
async def settings_create_profile(request: ProfileCreateRequest):
    safe_name = sanitize_profile_name(request.name)
    if safe_name in list_profiles():
        raise HTTPException(status_code=409, detail="Profile already exists")
    base = load_profile(get_last_active_profile())
    base.update(request.settings or {})
    try:
        save_runtime_profile(safe_name, base)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Create failed: {e}")
    return {"profile": safe_name, "settings": load_profile(safe_name), "profiles": list_profiles()}


@app.post("/settings/profiles/{profile_name}/activate")
async def settings_activate_profile(profile_name: str):
    safe_name = sanitize_profile_name(profile_name)
    if safe_name not in list_profiles():
        raise HTTPException(status_code=404, detail="Profile not found")
    # Re-selecting the already-active profile is a no-op: skip the runtime
    # cascade (transcriber reload, hotkey rebind, injector + LLM reconfigure),
    # which costs 100-500 ms. Content edits to the active profile arrive via
    # settings_save_profile, which always re-applies — so this guard can only
    # suppress genuinely redundant switches, never a real settings change.
    if safe_name == get_last_active_profile():
        return get_active_profile_payload()
    return apply_active_profile_runtime(safe_name)


@app.delete("/settings/profiles/{profile_name}")
async def settings_delete_profile(profile_name: str):
    safe_name = sanitize_profile_name(profile_name)
    if safe_name == "Default":
        raise HTTPException(status_code=400, detail="Default profile cannot be deleted")
    profile_path = Path(get_profiles_dir()) / f"{safe_name}.yaml"
    if not profile_path.exists():
        raise HTTPException(status_code=404, detail="Profile not found")
    
    # Check active status before unlinking the file
    was_active = (get_last_active_profile() == safe_name)
    profile_path.unlink()
    
    if was_active:
        apply_active_profile_runtime("Default")
    return get_active_profile_payload()


@app.post("/settings/profiles/{profile_name}/rename")
async def settings_rename_profile(profile_name: str, request: ProfileRenameRequest):
    safe_old = sanitize_profile_name(profile_name)
    safe_new = sanitize_profile_name(request.new_name)
    if safe_old == "Default":
        raise HTTPException(status_code=400, detail="Default profile cannot be renamed")
    if safe_new in list_profiles():
        raise HTTPException(status_code=409, detail="Profile already exists")
    
    old_path = Path(get_profiles_dir()) / f"{safe_old}.yaml"
    if not old_path.exists():
        raise HTTPException(status_code=404, detail="Profile not found")
        
    # Load and save under new name
    data = load_profile(safe_old)
    try:
        save_runtime_profile(safe_new, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rename failed during save: {e}")
        
    # Check active status before unlinking the file
    was_active = (get_last_active_profile() == safe_old)
    old_path.unlink()
    
    # If old was active, activate new
    if was_active:
        apply_active_profile_runtime(safe_new)
        
    return get_active_profile_payload()


@app.post("/settings/profiles/{profile_name}/duplicate")
async def settings_duplicate_profile(profile_name: str, request: ProfileDuplicateRequest):
    safe_old = sanitize_profile_name(profile_name)
    safe_new = sanitize_profile_name(request.new_name)
    if safe_new in list_profiles():
        raise HTTPException(status_code=409, detail="Profile already exists")
        
    if safe_old not in list_profiles():
        raise HTTPException(status_code=404, detail="Source profile not found")
        
    data = load_profile(safe_old)
    try:
        save_runtime_profile(safe_new, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Duplication failed: {e}")
        
    return get_active_profile_payload()


@app.get("/settings/profiles/{profile_name}/export")
async def settings_export_profile(profile_name: str):
    safe_name = sanitize_profile_name(profile_name)
    if safe_name not in list_profiles():
        raise HTTPException(status_code=404, detail="Profile not found")
    return {
        "kind": "betterfingers_profile",
        "schema_version": 1,
        "name": safe_name,
        "settings": load_profile(safe_name),
    }


# Persona Foundry (guided interview -> compile -> stress-test) is its own vertical
# slice in routes_foundry.py (M6); its router is registered at the end of this
# file and server._foundry_sessions is re-bound there for existing callers/tests.
#
# Persona CRUD/lint/preview routes (list/get/save/delete/lint/test) are their
# own slice in backend/api/routes/personas.py (A1.2); its router is registered
# at the end of this file, after get_selected_llm_engine and
# get_active_completion_tokens below are defined (the test route reaches them
# via a lazy ``import server`` at request time).


@app.get("/capabilities")
async def capabilities():
    return get_capabilities()


class LlmModelSelectRequest(BaseModel):
    model_id: str


class WhisperModelRequest(BaseModel):
    model_size: str
    prefer_gpu: bool = True


def get_selected_llm_model_id():
    cfg = load_profile(get_last_active_profile())
    return str(cfg.get("llm_model_id", DEFAULT_MODEL) or DEFAULT_MODEL).strip()


def get_selected_llm_engine():
    selected_model_id = get_selected_llm_model_id()
    engine = get_engine(selected_model_id)
    loaded_model_id = str(getattr(engine, "_loaded_model_id", "") or "").strip()
    if loaded_model_id and loaded_model_id != selected_model_id and hasattr(engine, "reload_model"):
        engine.set_model_id(selected_model_id)
        engine.reload_model()
    return engine


@app.get("/models/llm")
async def list_llm_models():
    selected = get_selected_llm_model_id()
    models = []
    for model_id, info in AVAILABLE_MODELS.items():
        model_path = get_model_path(model_id)
        download_state = get_download_state(model_id)
        file_status = get_model_file_status(model_id)
        with _llm_download_jobs_lock:
            job = _llm_download_jobs.get(model_id)
            download_active = bool(job and job.is_alive())
        download_state["active"] = download_active
        download_state["file_status"] = file_status
        models.append(
            {
                "id": model_id,
                "selected": model_id == selected,
                "installed": check_model_exists(model_id),
                "ready": is_llm_model_ready(model_id),
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
        "download_state": get_download_state(selected),
        "llama_server_path": get_server_path(),
        "llama_server_exists": os.path.exists(get_server_path()),
    }


@app.post("/models/llm/select")
async def select_llm_model(request: LlmModelSelectRequest, force: int = 0):
    if request.model_id not in AVAILABLE_MODELS:
        raise HTTPException(status_code=400, detail="Unsupported LLM model")
    # Switching the model reconfigures the LLM runtime — take the exclusive
    # lease so it can't race an in-flight completion (409 if busy).
    try:
        with model_runtime.write_lease("llm", wait=bool(force), timeout=15.0):
            profile_name = get_last_active_profile()
            cfg = load_profile(profile_name)
            cfg["llm_model_id"] = request.model_id
            save_runtime_profile(profile_name, cfg)
            engine = get_engine_if_initialized()
            if engine is not None:
                engine.set_model_id(request.model_id)
    except RuntimeBusyError:
        raise HTTPException(status_code=409, detail="LLM is busy with active inference. Retry, or pass force=1.")
    return await list_llm_models()


@app.post("/models/llm/{model_id}/download")
def download_llm_model(model_id: str):
    if model_id not in AVAILABLE_MODELS:
        raise HTTPException(status_code=400, detail="Unsupported LLM model")
    with _llm_download_jobs_lock:
        job = _llm_download_jobs.get(model_id)
        if job and job.is_alive():
            state = get_download_state(model_id)
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
                check_and_download_resources(model_id)
            except Exception as exc:
                logging.error("Background LLM download failed for %s: %s", model_id, exc)
            finally:
                with _llm_download_jobs_lock:
                    current = _llm_download_jobs.get(model_id)
                    if current is threading.current_thread():
                        _llm_download_jobs.pop(model_id, None)

        thread = threading.Thread(target=run_download, name=f"llm-download-{model_id}", daemon=True)
        _llm_download_jobs[model_id] = thread
        thread.start()

    return {
        "ok": True,
        "model_id": model_id,
        "background": True,
        "message": f"Started background download for {AVAILABLE_MODELS[model_id]['name']}.",
        "state": get_download_state(model_id),
    }


@app.delete("/models/llm/{model_id}")
async def delete_llm_model(model_id: str, force: int = 0):
    if model_id not in AVAILABLE_MODELS:
        raise HTTPException(status_code=400, detail="Unsupported LLM model")
    with _llm_download_jobs_lock:
        job = _llm_download_jobs.get(model_id)
        if job and job.is_alive():
            raise HTTPException(status_code=409, detail="That model is downloading. Wait for it to finish or restart the app before deleting it.")
    # Deleting model files must not race an active LLM inference reading them.
    try:
        with model_runtime.write_lease("llm", wait=bool(force), timeout=15.0):
            ok, message = delete_model(model_id)
    except RuntimeBusyError:
        raise HTTPException(status_code=409, detail="LLM is busy with active inference. Retry, or pass force=1.")
    return {"ok": ok, "model_id": model_id, "message": message}


@app.get("/models/llm/{model_id}/download-state")
async def llm_download_state(model_id: str):
    if model_id not in AVAILABLE_MODELS:
        raise HTTPException(status_code=400, detail="Unsupported LLM model")
    state = get_download_state(model_id)
    state["file_status"] = get_model_file_status(model_id)
    with _llm_download_jobs_lock:
        job = _llm_download_jobs.get(model_id)
        active = bool(job and job.is_alive())
    state["active"] = active
    if active and state.get("status") in (None, "", "error"):
        state["status"] = "downloading"
    return state


@app.get("/models/whisper")
async def list_whisper_models():
    selected = str(load_profile(get_last_active_profile()).get("model_size", "base.en") or "base.en").strip()
    return {
        "selected_model_size": selected,
        "supported": list(SUPPORTED_MODEL_SIZES),
        "models": list_cached_models(),
        "download_state": get_whisper_download_state(selected),
    }


@app.post("/models/whisper/download")
def download_whisper(request: WhisperModelRequest):
    result = download_whisper_model(request.model_size, prefer_gpu=request.prefer_gpu)
    return result


@app.delete("/models/whisper/{model_size}")
async def delete_whisper(model_size: str):
    result = remove_cached_model(model_size)
    if transcriber is not None and getattr(transcriber, "model_size", "") == model_size:
        transcriber.unload()
    return result


@app.post("/models/whisper/test")
def test_whisper(request: WhisperModelRequest):
    if request.model_size not in SUPPORTED_MODEL_SIZES:
        return {"ok": False, "message": f"Unsupported Whisper model: {request.model_size}"}
    try:
        probe = Transcriber(profile_name=get_last_active_profile(), preload=False)
        probe.model_size = request.model_size
        ok = probe.ensure_loaded()
        probe.unload()
        return {"ok": bool(ok), "message": f"Whisper {request.model_size} {'loaded' if ok else 'failed to load'}."}
    except Exception as exc:
        logging.exception("Whisper test failed")
        return {"ok": False, "message": str(exc)}


@app.post("/models/whisper/select")
async def select_whisper_model(request: WhisperModelRequest):
    if request.model_size not in SUPPORTED_MODEL_SIZES:
        raise HTTPException(status_code=400, detail="Unsupported Whisper model")
    # The active Whisper model is the active profile's `model_size`; persist the
    # choice there and reload the live transcriber so it takes effect immediately.
    profile_name = get_last_active_profile()
    cfg = load_profile(profile_name)
    cfg["model_size"] = request.model_size
    save_runtime_profile(profile_name, cfg)
    if transcriber is not None:
        transcriber.reload_profile(profile_name)
    return await list_whisper_models()


def _unload_model_component_locked(component: str):
    """The actual unload, run while holding the runtime's exclusive write lease.

    Beyond calling any .unload()/.shutdown()/.close() the engine exposes, this
    drops the module-level global reference so the object can be garbage
    collected, then runs gc.collect(). This matters on low-RAM machines where
    merely freeing the model tensor is not enough if the wrapper object (and its
    caches) stays reachable via a global.
    """
    import gc

    global transcriber, tts_engine

    normalized = component.strip().lower()
    unloaded = False

    if normalized == "stt":
        if transcriber is not None:
            try:
                transcriber.unload()
            except Exception as exc:
                logging.debug(f"transcriber.unload() failed: {exc}")
            transcriber = None
            unloaded = True
        gc.collect()
        model_runtime.note_unloaded("stt")
        return {
            "ok": True,
            "component": "stt",
            "unloaded": unloaded,
            "message": "STT unloaded." if unloaded else "STT was not loaded.",
        }

    if normalized == "llm":
        engine = get_engine_if_initialized()
        if engine is not None:
            # shutdown() stops the llama-server subprocess (frees its RAM/VRAM);
            # unload() also works but shutdown is the harder stop here.
            for method in ("shutdown", "unload", "close"):
                fn = getattr(engine, method, None)
                if callable(fn):
                    try:
                        fn()
                        unloaded = True
                        break
                    except Exception as exc:
                        logging.debug(f"LLM {method}() failed: {exc}")
            # Drop the module-level singleton so the wrapper can be collected.
            try:
                import llm_engine

                llm_engine._engine_instance = None
            except Exception as exc:
                logging.debug(f"Could not clear llm_engine singleton: {exc}")
        gc.collect()
        model_runtime.note_unloaded("llm")
        return {
            "ok": True,
            "component": "llm",
            "unloaded": unloaded,
            "message": "LLM unloaded." if unloaded else "LLM was not loaded.",
        }

    if normalized == "tts":
        if tts_engine is not None:
            for method in ("unload", "shutdown", "close"):
                fn = getattr(tts_engine, method, None)
                if callable(fn):
                    try:
                        fn()
                        unloaded = True
                        break
                    except Exception as exc:
                        logging.debug(f"TTS {method}() failed: {exc}")
            tts_engine = None
        gc.collect()
        model_runtime.note_unloaded("tts")
        return {
            "ok": True,
            "component": "tts",
            "unloaded": unloaded,
            "message": "TTS unloaded." if unloaded else "TTS was not loaded.",
        }

    raise HTTPException(status_code=400, detail="Unsupported component")


@app.post("/models/unload/{component}")
async def unload_model_component(component: str, force: int = 0):
    """Release a model component's memory under an exclusive runtime lease.

    Returns 409 if inference is active on that runtime (a destructive drop must
    not race an in-flight request); pass ?force=1 to cancel-and-wait for active
    inference to drain first.
    """
    normalized = component.strip().lower()
    if normalized not in ("stt", "llm", "tts"):
        raise HTTPException(status_code=400, detail="Unsupported component")
    try:
        with model_runtime.write_lease(normalized, wait=bool(force), timeout=15.0):
            return await run_in_threadpool(_unload_model_component_locked, normalized)
    except RuntimeBusyError:
        raise HTTPException(
            status_code=409,
            detail=f"{normalized.upper()} is in use by active inference. Retry, or pass force=1 to wait.",
        )


@app.get("/metrics")
async def pipeline_metrics_endpoint():
    return get_pipeline_metrics_summary()


@app.get("/jobs")
async def list_jobs_endpoint(active: int = 0):
    """Central job registry (§6.3): what work is running or recently finished."""
    return {
        "ok": True,
        "jobs": JOBS.list(active_only=bool(active)),
        "runtime_leases": model_runtime.active_leases(),
    }


@app.get("/jobs/{job_id}")
async def get_job_endpoint(job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True, "job": job.to_public()}


@app.post("/jobs/{job_id}/cancel")
async def cancel_job_endpoint(job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    JOBS.request_cancel(job_id)
    # For the active dictation job, also trip the pipeline's cancellation event so
    # the DictationPipeline's per-stage cancellation check (via
    # JobManagerCancellationBridge) unwinds process_recording_result promptly.
    if job_id == _active_dictation_job_id:
        cancellation_event.set()
    updated = JOBS.get(job_id)
    return {"ok": True, "job": updated.to_public() if updated else None}


def _path_size_bytes(path):
    """Total size of a file, or recursive size of a directory (0 if missing)."""
    try:
        if os.path.isfile(path):
            return os.path.getsize(path)
        total = 0
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
        return total
    except OSError:
        return 0


def _message_rescue_privacy_snapshot():
    """Counts-only Message Rescue + persona-learning state for /privacy and
    the support report (I3.4). Context/stored-results are in-memory (F2.5/
    F2.7); persona examples are the sole on-disk learned store (F2.6). Never
    includes captured/rewritten text, raw/out example pairs, or previews --
    only booleans, counts, and the store's file path."""
    from backend.services.persona_learning import PersonaLearningStore

    counts = routes_message_rescue.router.state_counts()
    persona_store = PersonaLearningStore()
    persona_names = persona_store.list_personas()
    total_examples = sum(len(persona_store.list_examples(name)) for name in persona_names)
    return {
        "context": {"active": counts["context_active"], "in_memory_only": True},
        "stored_results": {"count": counts["stored_results"], "in_memory_only": True},
        "persona_examples": {
            "total": total_examples,
            "personas": len(persona_names),
            "persisted": True,
            "path": persona_store.path,
        },
    }


def get_privacy_report():
    """Everything that touches the network + where local data lives (C7)."""
    history_file = os.path.join(get_user_data_path(), "draft_history.json")
    voices_dir = str(get_voices_path())
    with draft_lock:
        recordings_in_memory = len(draft_recordings)
        drafts_in_memory = len(draft_queue)

    network_touchpoints = [
        {
            "name": "Model & binary downloads",
            "hosts": ["huggingface.co", "github.com"],
            "direction": "outbound",
            "optional": True,
            "purpose": "Downloads STT/LLM/TTS models and the llama-server binary — only when you explicitly choose to install one.",
        },
        {
            "name": "Local LLM server",
            "hosts": ["127.0.0.1"],
            "direction": "local",
            "optional": False,
            "purpose": "The llama-server runs on localhost. Your prompts never leave this machine.",
        },
        {
            "name": "Speech-to-text & text-to-speech",
            "hosts": [],
            "direction": "local",
            "optional": False,
            "purpose": "Transcription and speech synthesis run fully on-device.",
        },
    ]

    history_db = history_store.get_db_path()
    recordings_dir = str(recordings.get_recordings_dir())

    data_locations = [
        {"name": "Draft history", "path": history_file, "bytes": _path_size_bytes(history_file)},
        {"name": "Searchable history (database)", "path": history_db, "bytes": _path_size_bytes(history_db)},
        {"name": "Raw audio recordings", "path": recordings_dir, "bytes": _path_size_bytes(recordings_dir)},
        {"name": "Cloned voices", "path": voices_dir, "bytes": _path_size_bytes(voices_dir)},
        {"name": "Models", "path": str(get_models_dir()), "bytes": _path_size_bytes(str(get_models_dir()))},
    ]

    import app_paths
    import routes_wake

    return {
        "offline_by_default": True,
        "network_touchpoints": network_touchpoints,
        "data_locations": data_locations,
        # Live-truthful, not static copy: reflects the actual running service
        # state so this never claims a listener exists while wake word is
        # disabled (or vice versa).
        "wake_listener": {
            "active": routes_wake.is_wake_listening(),
            "persists_audio": False,
            "note": (
                "When enabled, processes microphone audio locally for wake-phrase "
                "detection. Audio is never written to disk or sent anywhere -- only "
                "a redacted detection score (a number, never audio or transcripts) "
                "is kept in memory."
            ),
        },
        # Every root the app writes (or historically wrote) to, so the user can
        # see exactly where their data lives — current and any legacy location.
        "data_directories": app_paths.describe_locations(),
        # Message Rescue's held context/results (in-memory) + learned persona
        # examples (on-disk) -- counts/paths only, never content (I3.4).
        "message_rescue": _message_rescue_privacy_snapshot(),
        "retention": {
            "recordings_persisted_to_disk": True,
            "recordings_in_memory": recordings_in_memory,
            "drafts_in_memory": drafts_in_memory,
            "draft_history_limit": MAX_DRAFT_HISTORY,
        },
    }


@app.get("/privacy")
async def privacy_report():
    return get_privacy_report()


class PrivacyWipeRequest(BaseModel):
    wipe_voices: bool = False


def _drain_recorder(timeout=10.0):
    """Stop an active recording and wait for the recorder to actually stop.

    request_stop only *requests* a stop; this confirms is_recording has
    cleared so no in-flight callback can still produce audio after the wipe.
    """
    if hotkey_manager is None or not bool(getattr(hotkey_manager, "is_recording", False)):
        return True
    try:
        hotkey_manager.request_stop(reason="privacy_wipe")
    except Exception as exc:
        logging.warning(f"Privacy wipe: could not request recorder stop: {exc}")
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not bool(getattr(hotkey_manager, "is_recording", False)):
            return True
        time.sleep(0.05)
    return not bool(getattr(hotkey_manager, "is_recording", False))


def _cancel_active_injection():
    """Signal any in-progress injection to stop. Best-effort: the actual
    quiescence guarantee comes from output_coordinator.drain() waiting for
    the active-send count to reach zero, not from this callback succeeding."""
    injector = output_injector
    if injector is None:
        return
    try:
        injector.stop_typing()
    except Exception as exc:
        logging.debug(f"Privacy wipe: injector stop_typing failed: {exc}")


def _drain_output_injector(timeout=OUTPUT_DRAIN_TIMEOUT_SECONDS):
    """Cancel in-flight sends and wait until none are active, then take the
    exclusive output lease so no new send can start until release() is
    called. Returns (ok, stuck_sends): on timeout the lease is NOT held (the
    coordinator rolls back on failure) and stuck_sends maps each unfinished
    send's operation id to how long it has been running.
    """
    return output_coordinator.drain(cancel_active=_cancel_active_injection,
                                     timeout=timeout)


TTS_DRAIN_TIMEOUT_SECONDS = 10.0


def _drain_tts_and_clone(timeout=TTS_DRAIN_TIMEOUT_SECONDS):
    """Quiesce speech synthesis for a privacy wipe: stop playback, drop any
    queued speech, join the TTS worker, then wait out any in-flight
    voice-clone conversion (the chunked-playback generation thread can
    outlive the worker join and keep converting audio). Only once both are
    verified idle does it clear the synthesized-audio cache and unload the
    clone model — mirroring the on-failure-don't-touch-state discipline of
    the recorder/pipeline/output drains above.

    Returns (ok, results): ok=False means the wipe must ABORT without
    deleting — a live synthesis or conversion could still hold user
    text/audio.
    """
    import voice_clone_engine

    results = {
        "tts_playback_stopped": True,
        "tts_worker_idle": True,
        "tts_queue_empty": True,
        "voice_clone_conversion_idle": True,
        "voice_cache_cleared": True,
    }
    engine = tts_engine  # module global; draining must not itself initialize one
    if engine is not None:
        try:
            engine.stop_current()
        except Exception as exc:
            logging.warning(f"Privacy wipe: TTS stop_current failed: {exc}")
            results["tts_playback_stopped"] = False
        try:
            drained = engine.drain(timeout=timeout)
            results["tts_worker_idle"] = bool(drained.get("worker_idle"))
            results["tts_queue_empty"] = bool(drained.get("queue_empty"))
        except Exception as exc:
            logging.error(f"Privacy wipe: TTS drain failed: {exc}")
            results["tts_worker_idle"] = False
            results["tts_queue_empty"] = False

    # Backstop beyond the worker join: a chunked-playback generation thread
    # can still be mid-conversion even after the worker thread itself exits.
    results["voice_clone_conversion_idle"] = voice_clone_engine.wait_for_conversion_idle(timeout=timeout)

    ok = (results["tts_playback_stopped"] and results["tts_worker_idle"]
          and results["tts_queue_empty"] and results["voice_clone_conversion_idle"])
    if not ok:
        return False, results

    if engine is not None:
        try:
            results["voice_cache_cleared"] = bool(engine.clear_audio_cache())
        except Exception as exc:
            logging.error(f"Privacy wipe: TTS cache clear failed: {exc}")
            results["voice_cache_cleared"] = False
    try:
        voice_clone_engine.unload()
    except Exception as exc:
        logging.debug(f"Privacy wipe: clone unload skipped: {exc}")

    return results["voice_cache_cleared"], results


def _perform_privacy_wipe(wipe_voices: bool):
    """Quiesce fully, then delete, then verify — and only claim success when
    every postcondition holds. Reaching the final line is not proof of an
    empty landfill.

    Sets privacy_wipe_in_progress for the whole operation so recordings,
    dictation processing, recovery saves, sends, TTS, and retranscription all
    refuse while it runs. Aborts (without deleting) if the pipeline, output,
    or TTS/voice-clone path cannot be quiesced, so we never delete out from
    under a running job, send, or speech synthesis.
    """
    if privacy_wipe_in_progress.is_set():
        return {"ok": False, "error": "wipe_already_running",
                "message": "A privacy wipe is already in progress."}
    privacy_wipe_in_progress.set()
    cleared = {}
    postconditions = {}
    gate_held = False
    output_lease_held = False
    try:
        # 0. Stop the wake-word mic stream first (a second, independent mic
        #    consumer) -- before draining the recorder, so no audio consumer
        #    is left running while we quiesce the rest of the pipeline.
        #    Idempotent/no-op-safe: True even if wake word was never enabled.
        import routes_wake
        cleared["wake_listener_stopped"] = bool(routes_wake.stop_wake_listener())

        # 1. Drain the recorder: stop it and confirm it actually stopped.
        cleared["recorder_stopped"] = _drain_recorder()

        # 1b. Discard held recordings (and their streaming transcripts): a
        #     queued item processed after the wipe would regrow erased data.
        cleared["pending_recordings_dropped"] = _drop_pending_recordings()

        # 2. Cancel the active dictation and acquire the pipeline gate. If the
        #    pipeline will not quiesce, ABORT rather than delete under a live
        #    job — releasing the flag so the system keeps working.
        dictation_coordinator.cancel_active()
        gate_deadline = time.monotonic() + 10.0
        while time.monotonic() < gate_deadline:
            if dictation_coordinator.try_begin():
                gate_held = True
                break
            time.sleep(0.1)
        cleared["pipeline_quiesced"] = gate_held
        # With the gate held, the recording/processing worker has drained (it
        # takes the same gate) — so the completion callback has finished too.
        cleared["recording_callback_drained"] = gate_held
        if not gate_held:
            logging.error("Privacy wipe aborted: pipeline did not quiesce within 10s.")
            return {
                "ok": False,
                "error": "pipeline_did_not_quiesce",
                "cleared": cleared,
                "postconditions": {},
                "message": "Wipe aborted: a dictation would not stop. Nothing was deleted; try again.",
            }

        # 3. Cancel active injections and wait for every in-flight send to
        #    finish, then hold the exclusive output lease so no new send can
        #    start until the wipe releases it in the finally block below. If
        #    a send will not finish in time, ABORT without deleting — same
        #    principle as the pipeline-quiesce check above: never delete out
        #    from under a live send.
        output_lease_held, stuck_sends = _drain_output_injector()
        cleared["output_injector_idle"] = output_lease_held
        if not output_lease_held:
            logging.error(f"Privacy wipe aborted: output did not quiesce within "
                           f"{OUTPUT_DRAIN_TIMEOUT_SECONDS}s. Stuck sends: {stuck_sends}")
            return {
                "ok": False,
                "error": "output_did_not_quiesce",
                "cleared": cleared,
                "postconditions": {},
                "stuck_sends": stuck_sends,
                "message": "Wipe aborted: a draft send would not finish. Nothing was deleted; try again.",
            }

        # 3b. Drain speech synthesis: new TTS is already rejected via
        #     privacy_wipe_in_progress (both /tts routes and the keyboard
        #     review-TTS path check it); now stop playback, drop the queue,
        #     join the worker, and wait out any in-flight clone conversion.
        #     Same abort-without-deleting shape as steps 2 and 3.
        tts_ok, tts_results = _drain_tts_and_clone()
        cleared.update(tts_results)
        if not tts_ok:
            logging.error(f"Privacy wipe aborted: TTS/clone did not quiesce: {tts_results}")
            return {
                "ok": False,
                "error": "tts_did_not_quiesce",
                "cleared": cleared,
                "postconditions": {},
                "message": "Wipe aborted: speech synthesis would not stop. Nothing was deleted; try again.",
            }

        # 4. Delete in-memory queues.
        with draft_lock:
            cleared["drafts"] = len(draft_queue)
            cleared["recordings"] = len(draft_recordings)
            draft_queue.clear()
            draft_recordings.clear()
            pending_manual_send_ids.clear()
        save_draft_history()

        # 5. Delete on-disk stores (final sweep — callbacks/workers are drained).
        history_file = os.path.join(get_user_data_path(), "draft_history.json")
        try:
            if os.path.exists(history_file):
                os.remove(history_file)
            cleared["history_file_removed"] = not os.path.exists(history_file)
        except OSError as exc:
            logging.warning(f"Could not remove draft history file: {exc}")
            cleared["history_file_removed"] = False

        db_result = history_store.wipe_database()
        cleared["history_db_wiped"] = db_result

        cleared["recordings_files_removed"] = recordings.clear_recordings()

        if wipe_voices:
            voices_dir = get_voices_path()
            try:
                if voices_dir.exists():
                    # No ignore_errors: a suppressed failure must not report
                    # success. Verified below regardless.
                    shutil.rmtree(voices_dir)
            except OSError as exc:
                logging.warning(f"Could not remove voices dir: {exc}")
            cleared["voices_removed"] = not voices_dir.exists()

        # 5b. Clear Message Rescue's held context, stored generation results,
        #     and cancellation handles (F2.5/F2.7 in-memory state). Best-effort
        #     against new callers only -- an in-flight generation keeps
        #     running (that's /generate/{id}/cancel's job), but nothing
        #     rescued survives in memory after this point.
        mr_clear_result = routes_message_rescue.router.clear_state()
        mr_counts_after = routes_message_rescue.router.state_counts()
        cleared["message_rescue_context_cleared"] = not mr_counts_after["context_active"]
        cleared["message_rescue_results_cleared"] = mr_clear_result["stored_results_cleared"]
        cleared["message_rescue_generations_cleared"] = mr_clear_result["active_generations_cleared"]

        # 5c. Clear every learned persona example (F2.6 on-disk store),
        #     persona-by-persona so a single write failure is reported rather
        #     than silently skipped. Keys are dropped, not blacklisted -- a
        #     later add_example (with fresh consent) recreates them.
        from backend.services.persona_learning import PersonaLearningStore
        persona_store = PersonaLearningStore()
        persona_examples_ok = True
        for persona_name in persona_store.list_personas():
            persona_result = persona_store.clear_persona(persona_name)
            if not persona_result.get("ok"):
                persona_examples_ok = False
                logging.warning(
                    f"Privacy wipe: failed to clear persona examples for "
                    f"{persona_name!r}: {persona_result.get('message')}"
                )
        cleared["persona_examples_cleared"] = persona_examples_ok and not persona_store.list_personas()

        # 6. Verify every target and report per-path postconditions.
        leftover_recordings = recordings.list_leftover_files()
        postconditions = {
            "recorder_stopped": cleared["recorder_stopped"],
            "recording_callback_drained": cleared["recording_callback_drained"],
            "pending_queue_empty": _pending_recordings.empty(),
            "pipeline_quiesced": gate_held,
            "output_injector_idle": cleared["output_injector_idle"],
            "draft_queue_empty": len(draft_queue) == 0,
            "history_file_absent": not os.path.exists(history_file),
            "history_db_recreated": bool(db_result.get("recreated")),
            "history_db_wiped": bool(db_result.get("ok")),
            "recordings_dir_empty": not leftover_recordings,
            "leftover_recordings": leftover_recordings[:20],
            "tts_worker_idle": cleared["tts_worker_idle"],
            "tts_queue_empty": cleared["tts_queue_empty"],
            "tts_playback_stopped": cleared["tts_playback_stopped"],
            "voice_clone_conversion_idle": cleared["voice_clone_conversion_idle"],
            "voice_cache_cleared": cleared["voice_cache_cleared"],
            "message_rescue_context_cleared": cleared["message_rescue_context_cleared"],
            "persona_examples_cleared": cleared["persona_examples_cleared"],
        }
        if wipe_voices:
            postconditions["voices_absent"] = not get_voices_path().exists()
    finally:
        if output_lease_held:
            output_coordinator.release()
        if gate_held:
            dictation_coordinator.finish()
        privacy_wipe_in_progress.clear()

    ok = all(v for k, v in postconditions.items() if k != "leftover_recordings")
    broadcast_status_threadsafe("draft_history_cleared")
    return {
        "ok": ok,
        "cleared": cleared,
        "postconditions": postconditions,
        "message": "Your data was wiped." if ok else
                   "Wipe finished with leftovers — see postconditions. Data may remain.",
    }


# Phase 1.1 (remediation): map a truthful wipe result to an honest HTTP status.
# An unsuccessful wipe must never return 200. The structured payload
# (ok/error/message/cleared/postconditions) is preserved unchanged.
_WIPE_ERROR_STATUS = {
    "wipe_already_running": 409,      # a wipe is already running -> conflict
    "pipeline_did_not_quiesce": 409,  # pipeline could not be quiesced -> conflict
    "output_did_not_quiesce": 503,    # a subsystem could not drain -> unavailable
}


def _wipe_status_code(result: dict) -> int:
    """200 only when every postcondition passed; otherwise an honest error.

    ok is False with no recognized pre-deletion abort code means deletion ran
    but a postcondition (or verification) did not hold -> 500.
    """
    if result.get("ok"):
        return 200
    return _WIPE_ERROR_STATUS.get(result.get("error"), 500)


@app.post("/privacy/wipe")
async def privacy_wipe(request: PrivacyWipeRequest = PrivacyWipeRequest()):
    """Delete app-generated conversational data: drafts, the draft-history
    file, the searchable history database (C8), and persisted raw-audio
    recordings (C6), plus in-memory queues. Also drains any active TTS
    playback and voice-clone conversion and clears the synthesized-audio
    cache unconditionally (it holds spoken user text regardless of the
    wipe_voices toggle). Models and profiles are intentionally NOT touched;
    cloned voice samples are removed only when explicitly requested. Note:
    without at-rest encryption this is logical deletion — nothing readable
    remains through the app or its files, but SSD-level forensic erasure is
    not promised.

    Returns an honest HTTP status (see _wipe_status_code): a wipe that did not
    fully succeed never reports 200."""
    result = await run_in_threadpool(_perform_privacy_wipe, request.wipe_voices)
    return JSONResponse(status_code=_wipe_status_code(result), content=result)


@app.get("/mcp/status")
async def mcp_status():
    return mcp_client.status()


@app.get("/mcp/servers")
async def mcp_servers():
    return {"ok": True, "servers": mcp_client.list_servers()}


@app.get("/mcp/servers/{server_name}/tools")
async def mcp_server_tools(server_name: str):
    try:
        return await run_in_threadpool(mcp_client.list_tools, server_name)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' is not configured.")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/recordings")
async def list_recordings_endpoint():
    return {"ok": True, "recordings": recordings.list_recordings()}


@app.post("/recordings/{rec_id}/retranscribe")
async def retranscribe_recording(rec_id: str):
    # A recording id becomes a filename; reject anything path-shaped (§10).
    if not recordings.is_valid_rec_id(rec_id):
        raise HTTPException(status_code=400, detail="Invalid recording id.")
    import numpy as np
    from recorder import RecordingResult

    audio, sample_rate = recordings.load_recording_audio(rec_id)
    if audio is None:
        raise HTTPException(status_code=404, detail="Recording not found.")

    audio = np.asarray(audio, dtype=np.float32)
    rr = RecordingResult(
        audio_data=audio,
        sample_rate=int(sample_rate or 16000),
        duration_seconds=len(audio) / float(sample_rate or 16000),
        frame_count=0,
        sample_count=int(audio.size),
        max_amplitude=float(np.max(np.abs(audio))) if audio.size else 0.0,
        rms_amplitude=float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0,
        stop_reason="recovery",
    )
    draft = await run_in_threadpool(process_recording_result, rr)
    if draft is None:
        raise HTTPException(status_code=409, detail="A dictation is already processing; try again shortly.")
    return {"ok": True, "draft": draft}


@app.delete("/recordings/{rec_id}")
async def delete_recording_endpoint(rec_id: str):
    if not recordings.is_valid_rec_id(rec_id):
        raise HTTPException(status_code=400, detail="Invalid recording id.")
    removed = recordings.delete_recording(rec_id)
    return {"ok": True, "removed": removed}


@app.delete("/recordings")
async def clear_recordings_endpoint():
    count = recordings.clear_recordings()
    return {"ok": True, "cleared": count}


# Dictionary / macros / voice-preset routes are their own slice in
# routes_user_config.py (M6); registered via app.include_router at the end.


@app.get("/history/search")
async def history_search(q: str = "", limit: int = 50):
    limit = max(1, min(200, int(limit or 50)))
    results = history_store.search(q, limit=limit)
    return {"ok": True, "query": q, "count": len(results), "results": results}


@app.get("/history")
async def history_recent(limit: int = 50):
    limit = max(1, min(200, int(limit or 50)))
    results = history_store.recent(limit=limit)
    return {"ok": True, "count": len(results), "total": history_store.count(), "results": results}


@app.delete("/history")
async def history_clear():
    ok = history_store.clear()
    return {"ok": ok, "message": "Searchable history cleared." if ok else "Could not clear history."}


@app.get("/diagnostics/logs")
async def diagnostics_logs(lines: int = 120):
    return read_log_tail(lines)


@app.get("/diagnostics/paths")
async def diagnostics_paths():
    return get_runtime_paths_snapshot()


@app.get("/runtime/errors")
async def runtime_errors():
    return {"errors": get_runtime_error_history()}


def gather_support_report():
    """Collect a privacy-safe diagnostic snapshot and render it to Markdown
    (backlog item 6). NON-INVASIVE: reads current runtime state only — never
    initializes or loads a model — so copying a support report can't change
    what's resident. Contains NO transcription content (see support_report).

    Returns ``{"markdown", "report", "generated_at"}``.
    """
    import platform as _platform

    import support_report

    generated_at = datetime.now(timezone.utc).isoformat()

    # --- version (source of truth: /runtime/version) ---
    version = {"backend_version": "0.1.0", "profile_schema_version": 1, "config_version": 1}

    # --- platform ---
    platform_info = {
        "system": _platform.system(),
        "release": _platform.release(),
        "python": _platform.python_version(),
    }

    # --- hardware + tier (compute the report once, reuse for tier) ---
    hardware = get_hardware_report()
    try:
        tier = get_hardware_tier(report=hardware)
        if isinstance(tier, dict):
            label = tier.get("label") or tier.get("tier") or "unknown"
            code = tier.get("tier")
            hardware_tier = f"{label} ({code})" if code and code != label else str(label)
        else:
            hardware_tier = str(tier)
    except Exception:
        hardware_tier = "unknown"

    # --- runtime validation (read current state; do not initialize) ---
    engine = get_engine_if_initialized()
    selected_model_id = get_selected_llm_model_id()
    llama_server_path = str(get_server_path())
    llama_server_exists = os.path.exists(llama_server_path)
    model_exists = check_model_exists(selected_model_id)

    runtime_validation = {"ok": False}
    if llama_server_exists:
        try:
            runtime_validation = validate_llama_server_runtime(llama_server_path)
        except Exception as exc:  # never let diagnostics crash the report
            runtime_validation = {"ok": False, "message": f"{type(exc).__name__}"}
    runtime_build = runtime_validation.get("build")
    required_runtime_build = required_llama_server_build(selected_model_id)
    engine_ready = bool(getattr(engine, "_ready", False)) if engine is not None else False
    llm_last_error = str(getattr(engine, "_last_error", "") or "") if engine is not None else ""

    if not llama_server_exists:
        llm_status = "missing_llama_server"
    elif not model_exists:
        llm_status = "missing_model"
    elif not runtime_validation.get("ok", False):
        llm_status = "runtime_invalid"
    elif engine_ready:
        llm_status = "ready"
    elif llm_last_error:
        llm_status = "startup_failure"
    else:
        llm_status = "not_loaded"

    stt = transcriber
    stt_info = {
        "initialized": stt is not None,
        "loaded": bool(getattr(stt, "model", None)) if stt is not None else False,
        "model_size": getattr(stt, "model_size", None) if stt is not None else None,
        "device": getattr(stt, "device", None) if stt is not None else None,
    }

    tts = tts_engine
    tts_info = {
        "initialized": tts is not None,
        "loaded": bool(tts.is_loaded()) if (tts is not None and hasattr(tts, "is_loaded")) else False,
        "backend": tts.backend() if (tts is not None and hasattr(tts, "backend")) else "none",
    }

    runtime = {
        "llm": {
            "runtime_status": llm_status,
            "runtime_build": runtime_build,
            "required_runtime_build": required_runtime_build,
            "last_error": llm_last_error,
        },
        "stt": stt_info,
        "tts": tts_info,
    }

    # --- resident model ledger ---
    try:
        resources = model_runtime.resources_snapshot()
    except Exception:
        resources = {}

    data = {
        "generated_at": generated_at,
        "version": version,
        "platform": platform_info,
        "hardware": hardware,
        "hardware_tier": hardware_tier,
        "runtime": runtime,
        "resources": resources,
        "message_rescue": _message_rescue_privacy_snapshot(),
        "recent_errors": get_runtime_error_history(),
        "paths": get_runtime_paths_snapshot(),
    }
    return {
        "markdown": support_report.render_support_report(data),
        "report": data,
        "generated_at": generated_at,
    }


@app.get("/diagnostics/support-report")
async def diagnostics_support_report():
    """One-click support report (Markdown) for alpha testers — no telemetry
    means this is how a tester hands us diagnostics. Runs off the event loop
    since it touches the filesystem and may shell out to llama-server --version."""
    return await run_in_threadpool(gather_support_report)


@app.get("/drafts")
async def list_drafts():
    with draft_lock:
        return {"drafts": [dict(draft) for draft in draft_queue]}


@app.get("/drafts/latest")
async def latest_draft():
    with draft_lock:
        if not draft_queue:
            return {"draft": None}
        return {"draft": dict(draft_queue[-1])}


@app.delete("/drafts")
def clear_draft_history():
    with draft_lock:
        draft_queue.clear()
        draft_recordings.clear()
        pending_manual_send_ids.clear()
    save_draft_history()
    broadcast_status_threadsafe("draft_history_cleared")
    return {"ok": True, "message": "Draft history cleared."}


@app.post("/drafts/test-mock")
def create_mock_draft(status: str = "pending", raw: str = "Mock raw transcript text.", final: str = "Mock cleaned and polished output."):
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
    draft = create_draft(raw, final, preset="True Janitor", status=status, metadata=metadata)
    broadcast_status_threadsafe("preview_ready", {
        "draft_id": draft["id"],
        "raw_text": draft["raw_text"],
        "final_text": draft["final_text"],
        "token_count": draft["token_count"],
        "token_limit": draft["token_limit"],
        "long_text": draft["long_text"],
    })
    return draft



@app.post("/drafts/{draft_id}/accept")
async def accept_draft(draft_id: int):
    with draft_lock:
        for draft in draft_queue:
            if draft["id"] == draft_id:
                draft["status"] = "accepted"
                mark_draft_pending_send(draft)
                response = dict(draft)
                break
        else:
            raise HTTPException(status_code=404, detail="Draft not found")
    save_draft_history(changed_draft_id=draft_id)
    broadcast_status_threadsafe("draft_accepted", {"draft_id": draft_id, "pending_send": True})
    return response


@app.post("/drafts/{draft_id}/decline")
async def decline_draft(draft_id: int):
    with draft_lock:
        for draft in draft_queue:
            if draft["id"] == draft_id:
                draft["status"] = "declined"
                draft["pending_send"] = False
                while draft_id in pending_manual_send_ids:
                    pending_manual_send_ids.remove(draft_id)
                response = dict(draft)
                break
        else:
            raise HTTPException(status_code=404, detail="Draft not found")
    save_draft_history(changed_draft_id=draft_id)
    broadcast_status_threadsafe("draft_declined", {"draft_id": draft_id})
    return response


@app.post("/drafts/{draft_id}/retry")
async def retry_draft(draft_id: int):
    with draft_lock:
        recording_result = draft_recordings.get(draft_id)

    if recording_result is None:
        raise HTTPException(status_code=409, detail="No recording data is available for this draft")

    # Blocking model pipeline must not run on the event loop (it would starve
    # /health and trip Electron's restart watchdog).
    draft = await run_in_threadpool(process_recording_result, recording_result)
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


def _find_voice_preset(name, presets=None):
    key = str(name or "").strip().lower()
    if not key:
        return None
    presets = presets if presets is not None else voice_presets.get_presets()
    return next((p for p in presets if p["name"].lower() == key), None)


def _resolve_voice_and_modulation(request, config):
    """Merge, highest priority first: explicit request fields -> a named
    voice preset (if request.preset_name is given) -> the active persona's
    voice (if request.persona is given and the persona has a deliberate
    voice identity — see below), which is either its referenced preset
    (persona.voice.preset) or its own inline fields, never a blend of both
    -> the user's designated DEFAULT preset (Voice Studio "make default";
    see voice_presets.get_default_preset()) -> profile defaults, into
    (voice_id, speed, blend, modulation) ready for engine.speak(). Shared by
    both /tts/speak and /drafts/{id}/tts so the fallback chain lives in one
    place.

    The default preset sits BELOW the persona/request-preset layers and
    ABOVE profile config: it's the "otherwise use what I picked in Voice
    Studio" layer for ordinary read-aloud, which previously had no saved
    preset ever applied to it at all (a preset only took effect when a
    caller passed preset_name explicitly, which the app never does for
    plain read-aloud) — but an explicit ask (preset_name/persona) still
    wins outright, same as it always has.

    A persona only contributes voice defaults when it has an actual voice
    identity — persona.voice.base or persona.voice.preset non-empty.
    normalize_persona() always fully defaults every numeric field (energy,
    pitch, ...), so an untouched persona's voice dict is indistinguishable
    from a deliberately-configured one except via base/preset; without this
    gate, every persona would silently override profile-level speed/voice
    defaults even when its voice was never configured.
    """
    presets_cache = None

    def get_presets_cached():
        nonlocal presets_cache
        if presets_cache is None:
            presets_cache = voice_presets.get_presets()
        return presets_cache

    layers = []

    request_name = str(getattr(request, "preset_name", "") or "").strip()
    if request_name:
        preset = _find_voice_preset(request_name, get_presets_cached())
        if preset is not None:
            layers.append(preset)

    persona_name = str(getattr(request, "persona", "") or "").strip()
    if persona_name:
        from llm_engine import get_persona
        persona = get_persona(persona_name)
        persona_voice = (persona or {}).get("voice", {}) or {}
        has_voice_identity = bool(str(persona_voice.get("base", "") or "").strip()) or bool(
            str(persona_voice.get("preset", "") or "").strip()
        )
        if has_voice_identity:
            # A persona's voice is either "use this preset" or "use these inline
            # fields" — not a merge of both. normalize_persona() fully defaults
            # every numeric field (speed, pitch, ...), so if both were layered
            # the persona's own defaulted values (e.g. speed=1.0) would always
            # mask the preset's real values before the preset layer is ever
            # reached. A dangling preset reference falls back to the persona's
            # own inline fields rather than erroring.
            persona_preset_name = str(persona_voice.get("preset", "") or "").strip()
            persona_preset = _find_voice_preset(persona_preset_name, get_presets_cached()) if persona_preset_name else None
            if persona_preset is not None:
                layers.append(persona_preset)
            else:
                layers.append({k: v for k, v in persona_voice.items() if k not in ("preset", "stability")})

    # Lowest-priority preset layer: the user's Voice Studio default, so a
    # saved preset actually reaches ordinary read-aloud instead of only ever
    # applying when a caller explicitly passes preset_name (which neither
    # /tts/speak nor /drafts/{id}/tts do on their own). get_default_preset()
    # already validates the name still exists (returns None if dangling), so
    # no re-check is needed here.
    default_preset_name = voice_presets.get_default_preset()
    if default_preset_name:
        default_preset = _find_voice_preset(default_preset_name, get_presets_cached())
        if default_preset is not None:
            layers.append(default_preset)

    def pick(request_val, field, config_key=None, fallback=None):
        if request_val is not None:
            return request_val
        for layer in layers:
            layer_val = layer.get(field)
            if layer_val not in (None, ""):
                return layer_val
        if config_key is not None:
            config_val = config.get(config_key)
            if config_val not in (None, ""):
                return config_val
        return fallback

    req_voice = pick(request.voice_id, "base", "review_tts_voice_hint", "standard_female")
    req_speed = pick(request.speed, "speed", "review_tts_speed", 1.0)
    voice_id = normalize_tts_voice_id(req_voice)
    speed = max(0.5, min(3.0, float(req_speed)))

    blend = pick(request.blend, "blend", fallback=None) or None

    modulation = {
        "pitch": pick(request.pitch, "pitch", fallback=0.0),
        "energy": pick(getattr(request, "energy", None), "energy", fallback=0.5),
        "warmth": pick(getattr(request, "warmth", None), "warmth", fallback=0.0),
        "brightness": pick(getattr(request, "brightness", None), "brightness", fallback=0.0),
        "pause_style": pick(getattr(request, "pause_style", None), "pause_style", fallback="natural"),
    }
    return voice_id, speed, blend, modulation


def get_rewrite_instruction(action, custom_instruction=""):
    action_key = str(action or "clearer").strip().lower()
    custom = str(custom_instruction or "").strip()
    instructions = {
        "shorter": "Make the draft shorter while preserving the user's intent and important details.",
        "clearer": "Make the draft clearer, more direct, and easier to read.",
        "tone": "Adjust the tone to be polished, warm, and professional without changing the meaning.",
        "custom": custom or "Rewrite the draft according to the user's custom instruction.",
    }
    return action_key if action_key in instructions else "clearer", instructions.get(action_key, instructions["clearer"])


def rewrite_draft_text(text, action, custom_instruction=""):
    action_key, instruction = get_rewrite_instruction(action, custom_instruction)
    clean_text = str(text or "").strip()
    if not clean_text:
        raise ValueError("No cleaned output is available to rewrite.")

    try:
        config = load_profile(get_last_active_profile())
        llm_chunk_size = config.get("llm_chunk_size", 750)
    except Exception:
        llm_chunk_size = 750

    engine = get_selected_llm_engine()
    token_limit = get_active_completion_tokens()
    if hasattr(engine, "rewrite_text"):
        return (
            engine.rewrite_text(
                clean_text,
                action=action_key,
                custom_instruction=custom_instruction,
                max_output_tokens=token_limit,
                chunk_size=llm_chunk_size,
            )
            or clean_text
        )

    prompt = (
        f"{instruction}\n\n"
        "Return only the rewritten text.\n\n"
        f"Draft:\n{clean_text}"
    )
    return engine.process_fast_lane(prompt, "True Janitor", chunk_size=llm_chunk_size) or clean_text


@app.post("/drafts/{draft_id}/edit")
async def edit_draft(draft_id: int, request: DraftEditRequest):
    with draft_lock:
        draft = get_draft_by_id(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")

        draft["final_text"] = request.final_text or ""
        if draft.get("status") in {"accepted", "declined", "sent", "send_error"}:
            draft["status"] = "pending"
            draft["pending_send"] = False
            while draft_id in pending_manual_send_ids:
                pending_manual_send_ids.remove(draft_id)
        else:
            draft["status"] = draft.get("status", "pending")
        draft["error"] = ""
        draft["updated_at"] = datetime.now(timezone.utc).isoformat()
        update_draft_review_fields(draft)
        response = dict(draft)

    save_draft_history(changed_draft_id=draft_id)
    broadcast_status_threadsafe(
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


@app.post("/drafts/{draft_id}/rewrite")
async def rewrite_draft(draft_id: int, request: DraftRewriteRequest):
    with draft_lock:
        draft = get_draft_by_id(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        source_text = draft.get("final_text") or draft.get("raw_text") or ""

    action_key, _instruction = get_rewrite_instruction(request.action, request.custom_instruction)
    try:
        broadcast_status_threadsafe("draft_rewriting", {"draft_id": draft_id, "action": action_key})
        rewritten = str(rewrite_draft_text(source_text, action_key, request.custom_instruction) or source_text).strip()
        with draft_lock:
            draft = get_draft_by_id(draft_id)
            if draft is None:
                raise HTTPException(status_code=404, detail="Draft not found")
            draft["final_text"] = rewritten
            draft["status"] = "pending"
            draft["error"] = ""
            draft["rewrite_action"] = action_key
            draft["updated_at"] = datetime.now(timezone.utc).isoformat()
            update_draft_review_fields(draft)
            response = dict(draft)
        save_draft_history(changed_draft_id=draft_id)
        broadcast_status_threadsafe(
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
        logging.error(f"Draft rewrite failed: {redact_exc(exc)}")
        record_runtime_error("review", str(exc), {"action": "rewrite", "draft_id": draft_id})
        broadcast_status_threadsafe("draft_rewrite_error", {"draft_id": draft_id, "action": action_key, "error": str(exc)})
        return {
            "ok": False,
            "draft_id": draft_id,
            "action": action_key,
            "error": str(exc),
            "draft": dict(get_draft_by_id(draft_id) or {}),
        }


@app.post("/drafts/{draft_id}/tts")
async def speak_draft(draft_id: int, request: DraftTtsRequest):
    wiping = _reject_if_wiping("draft TTS")
    if wiping:
        return {"draft_id": draft_id, **wiping}
    with draft_lock:
        draft = get_draft_by_id(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        text = (request.text or draft.get("final_text") or draft.get("raw_text") or "").strip()

    if not text:
        return {"ok": False, "draft_id": draft_id, "message": "No draft text is available to read aloud.", "error": "empty_text"}

    profile_name = get_last_active_profile()
    try:
        config = load_profile(profile_name)
    except Exception:
        config = {}

    voice_id, speed, blend, modulation = _resolve_voice_and_modulation(request, config)
    logging.info(f"Draft TTS Request: draft={draft_id} {redact_user_text(text)} | Voice: {voice_id} | Speed: {speed}x")

    engine = await run_in_threadpool(ensure_tts_initialized)
    if engine is None:
        result = {
            "ok": False,
            "status": "error",
            "draft_id": draft_id,
            "message": "TTS engine is not available.",
            "error": "tts_unavailable",
            "text_length": len(text),
        }
        record_runtime_error("tts", result["message"], {"action": "draft_tts", "draft_id": draft_id})
        return result

    try:
        with model_runtime.read_lease("tts"):
            result = await run_in_threadpool(
                engine.speak, text, speed=speed, voice_hint=voice_id, blend=blend, modulation=modulation
            )
    except RuntimeBusyError:
        return {"ok": False, "status": "error", "draft_id": draft_id,
                "error": "tts_reconfiguring", "message": "TTS runtime is being reconfigured; retry shortly."}
    result.update(
        {
            "status": "success" if result.get("ok") else "error",
            "draft_id": draft_id,
            "text_length": len(text),
        }
    )
    broadcast_status_threadsafe("draft_tts_requested", {"draft_id": draft_id, "text_length": len(text)})
    return result


class DraftSendRequest(BaseModel):
    action: str = "copy_only"
    open_chat: bool = False
    allow_resend: bool = False


@app.post("/drafts/{draft_id}/send")
async def send_draft(draft_id: int, request: DraftSendRequest = DraftSendRequest()):
    return send_draft_by_id(
        draft_id,
        action=request.action,
        open_chat=request.open_chat,
        allow_resend=request.allow_resend,
    )


class VoiceCommandExecuteRequest(BaseModel):
    text: str
    draft_id: Optional[int] = None
    context: dict = {}
    confirm: bool = False


_REWRITE_ACTION_FOR = {"rewrite_shorter": "shorter", "rewrite_clearer": "clearer"}
_DRAFT_DEPENDENT_ACTIONS = {"cancel", "send", "copy", "read_back", "retry", *_REWRITE_ACTION_FOR}


@app.post("/voice-commands/execute")
async def execute_voice_command(request: VoiceCommandExecuteRequest):
    """Real trigger point for app-control voice commands (task 9): classify
    `text` via voice_commands.parse_command, then execute the resolved
    action against the existing draft/runtime functions. `emergency_stop`
    always executes; anything else with requires_confirmation=True only
    executes when `confirm=True` is sent as a follow-up call."""
    if not app_commands_enabled():
        return {"ok": False, "reason": "disabled"}

    intent = voice_commands.parse_command(request.text, request.context)
    if intent is None:
        return {"ok": False, "reason": "no_command_recognized"}

    broadcast_status_threadsafe(
        "command_detected",
        {"action": intent.action, "kind": intent.kind, "confidence": intent.confidence},
    )

    if intent.requires_confirmation and not request.confirm:
        broadcast_status_threadsafe(
            "command_needs_confirmation",
            {"action": intent.action, "kind": intent.kind},
        )
        return {"ok": False, "reason": "needs_confirmation", "action": intent.action}

    draft_id = request.draft_id
    try:
        if intent.action == "emergency_stop":
            emergency_stop_runtime()
            return {"ok": True, "action": intent.action}
        if intent.action == "start_recording":
            start_recording_runtime()
            return {"ok": True, "action": intent.action}
        if intent.action == "stop_recording":
            stop_recording_runtime()
            return {"ok": True, "action": intent.action}
        if intent.action not in _DRAFT_DEPENDENT_ACTIONS:
            return {"ok": False, "reason": "not_implemented", "action": intent.action}

        if draft_id is None:
            return {"ok": False, "reason": "no_draft", "action": intent.action}

        if intent.action == "cancel":
            result = await decline_draft(draft_id)
        elif intent.action == "send":
            result = send_draft_by_id(draft_id)
        elif intent.action == "copy":
            draft = get_draft_by_id(draft_id)
            if draft is None:
                return {"ok": False, "reason": "no_draft", "action": intent.action}
            copy_text_to_clipboard(draft.get("final_text", ""))
            result = {"draft_id": draft_id}
        elif intent.action == "read_back":
            draft = get_draft_by_id(draft_id)
            if draft is None:
                return {"ok": False, "reason": "no_draft", "action": intent.action}
            speak_text_aloud(draft.get("final_text", ""))
            result = {"draft_id": draft_id}
        elif intent.action in _REWRITE_ACTION_FOR:
            result = await rewrite_draft(draft_id, DraftRewriteRequest(action=_REWRITE_ACTION_FOR[intent.action]))
        else:  # intent.action == "retry"
            result = await retry_draft(draft_id)
        return {"ok": True, "action": intent.action, "result": result}
    except HTTPException:
        raise
    except Exception as exc:
        logging.error(f"Voice command execution failed: {redact_exc(exc)}")
        return {"ok": False, "reason": "error", "action": intent.action, "error": str(exc)}


@app.post("/runtime/primary-action")
async def runtime_primary_action():
    return handle_primary_action()


@app.post("/runtime/emergency-stop")
async def runtime_emergency_stop():
    return emergency_stop_runtime()


@app.post("/runtime/recording/toggle")
async def runtime_recording_toggle():
    return toggle_recording_runtime()


@app.post("/runtime/recording/start")
async def runtime_recording_start():
    return start_recording_runtime()


@app.post("/runtime/recording/stop")
async def runtime_recording_stop():
    return stop_recording_runtime()


@app.post("/runtime/tts/toggle")
async def runtime_tts_toggle():
    handle_review_tts_shortcut()
    return {"ok": True, "message": "Review TTS shortcut triggered."}


@app.post("/runtime/warmup")
async def runtime_warmup(request: RuntimeWarmupRequest):
    result: typing.Dict[str, typing.Any] = {"requested": request.model_dump()}

    if request.stt:
        try:
            trans = await run_in_threadpool(ensure_transcriber_initialized, preload=False)
            result["stt"] = {
                "ok": True,
                "initialized": trans is not None,
                "loaded": bool(trans and await run_in_threadpool(trans.ensure_loaded)),
            }
        except Exception as e:
            logging.exception("Transcriber warmup failure")
            record_runtime_error("stt", str(e), {"action": "warmup"})
            result["stt"] = {
                "ok": False,
                "initialized": transcriber is not None,
                "loaded": bool(getattr(transcriber, "model", None)),
                "error": str(e),
            }

    if request.llm:
        try:
            engine = get_selected_llm_engine()
            ready = bool(getattr(engine, "_ready", False))
            result["llm"] = {
                "ok": ready,
                "initialized": engine is not None,
                "ready": ready,
                "error": "" if ready else str(getattr(engine, "_last_error", "") or ""),
            }
        except Exception as e:
            logging.exception("LLM warmup failure")
            record_runtime_error("llm", str(e), {"action": "warmup"})
            engine = get_engine_if_initialized()
            result["llm"] = {
                "ok": False,
                "initialized": engine is not None,
                "ready": bool(getattr(engine, "_ready", False)) if engine else False,
                "error": str(e),
            }

    if request.hotkeys:
        try:
            manager = start_hotkey_manager()
            hook_errors = list(getattr(manager, "keyboard_hook_errors", [])) if manager else []
            if hook_errors:
                message = "Keyboard hooks are unavailable: " + "; ".join(hook_errors)
                record_runtime_error("hotkeys", message, {"action": "warmup", "degraded": True})
            result["hotkeys"] = {
                "ok": not hook_errors,
                "started": manager is not None and hotkey_manager_started,
                "keyboard_hooks_ok": not hook_errors,
                "keyboard_hook_errors": hook_errors,
                "error": "; ".join(hook_errors) if hook_errors else "",
            }
        except Exception as e:
            logging.exception("Hotkey warmup failure")
            record_runtime_error("hotkeys", str(e), {"action": "warmup"})
            result["hotkeys"] = {
                "ok": False,
                "started": hotkey_manager_started,
                "error": str(e),
            }

    result.update(get_runtime_status_snapshot())
    return result

class LLMRequest(BaseModel):
    text: str
    preset: str = "True Janitor"
    true_gen: bool = False

@app.post("/llm/process")
async def process_llm(request: LLMRequest):
    try:
        # Read lease: a concurrent LLM unload/reload/select waits or 409s
        # rather than dropping the runtime mid-completion.
        with model_runtime.read_lease("llm"):
            engine = get_selected_llm_engine()
            result = await run_in_threadpool(
                engine.process_fast_lane,
                request.text,
                request.preset,
                true_gen=request.true_gen,
            )
        return {"text": result}
    except RuntimeBusyError:
        raise HTTPException(status_code=409, detail="LLM runtime is being reconfigured; retry shortly.")
    except Exception as e:
        logging.error(f"LLM Process Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    global transcriber
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    temp_filename = tmp.name
    tmp.close()
    try:
        # Validate the upload before anything else — a malformed or oversized
        # file is rejected regardless of whether STT is loaded.
        try:
            upload_safety.stream_to_file(file.file, temp_filename, upload_safety.MAX_AUDIO_BYTES)
            upload_safety.validate_signature(temp_filename, "audio")
            upload_safety.validate_wav_duration(temp_filename)
        except upload_safety.UploadTooLarge as exc:
            raise HTTPException(status_code=413, detail=f"Audio too large (max {exc.limit} bytes).")
        except upload_safety.UploadRejected as exc:
            raise HTTPException(status_code=400, detail=f"Invalid audio: {exc}")
        if not transcriber:
            raise HTTPException(status_code=503, detail="Transcriber not initialized")
        # Read lease: a concurrent STT unload/reload waits or 409s instead of
        # freeing the Whisper model out from under this transcription.
        with model_runtime.read_lease("stt"):
            text = await run_in_threadpool(transcriber.transcribe, temp_filename)
        return {"text": text}
    except HTTPException:
        raise
    except RuntimeBusyError:
        raise HTTPException(status_code=409, detail="STT runtime is being reconfigured; retry shortly.")
    except Exception as e:
        logging.error(f"Transcription Error: {redact_exc(e)}")
        raise HTTPException(status_code=500, detail="Transcription failed")
    finally:
        try:
            os.remove(temp_filename)
        except OSError:
            pass

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

@app.post("/tts/speak")
async def tts_speak(request: TTSRequest):
    wiping = _reject_if_wiping("TTS")
    if wiping:
        return {"status": "error", **wiping}
    text = (request.text or "").strip()
    if not text:
        return {"ok": False, "status": "error", "message": "No text to speak.", "error": "empty_text"}

    profile_name = get_last_active_profile()
    try:
        config = load_profile(profile_name)
    except Exception:
        config = {}

    voice_id, speed, blend, modulation = _resolve_voice_and_modulation(request, config)
    logging.info(f"TTS Request: {redact_user_text(text)} | Voice: {voice_id} | Speed: {speed}x")

    engine = await run_in_threadpool(ensure_tts_initialized)
    if engine is None:
        message = "TTS engine is not available."
        record_runtime_error("tts", message, {"action": "tts_speak"})
        return {"ok": False, "status": "error", "message": message, "error": "tts_unavailable"}

    try:
        with model_runtime.read_lease("tts"):
            result = await run_in_threadpool(
                engine.speak, text, speed=speed, voice_hint=voice_id, blend=blend, modulation=modulation
            )
    except RuntimeBusyError:
        return {"ok": False, "status": "error", "error": "tts_reconfiguring",
                "message": "TTS runtime is being reconfigured; retry shortly."}
    result["status"] = "success" if result.get("ok") else "error"
    return result

@app.post("/tts/stop")
async def stop_tts_route():
    global tts_engine
    if tts_engine is not None:
        try:
            tts_engine.stop_current()
            broadcast_status_threadsafe("draft_tts_stopped", {"message": "TTS stopped manually."})
            return {"ok": True, "message": "TTS playback stopped."}
        except Exception as e:
            return {"ok": False, "message": f"Failed to stop TTS: {e}"}
    return {"ok": True, "message": "TTS engine not active."}

@app.get("/runtime/tts-status")
async def get_tts_status():
    global tts_engine
    engine = await run_in_threadpool(ensure_tts_initialized)
    
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

    status = await run_in_threadpool(engine.ensure_loaded)
    backend_val = engine.backend()

    backend_name = "unavailable"
    if backend_val == "kokoro":
        backend_name = "Kokoro"
    elif backend_val == "kokoro_onnx":
        backend_name = "ONNX"
    elif backend_val == "sapi":
        backend_name = "SAPI fallback"

    msg = engine._status_message
    if libsndfile_missing:
        msg = f"Linux system package dependency failure: libsndfile1 is missing ({libsndfile_error}). Run 'sudo apt-get install libsndfile1' to resolve."
        backend_name = "unavailable"

    # get_capabilities() is a newer, optional addition to ReviewTTSEngine
    # (backend/runtime/blend_capable snapshot for the UI to gate blend
    # controls on). Guard with getattr rather than assuming it exists so
    # this route works the same whether or not that method has landed yet.
    capabilities = None
    get_capabilities = getattr(engine, "get_capabilities", None)
    if callable(get_capabilities):
        capabilities = get_capabilities()

    return {
        "ok": engine.is_loaded() and not libsndfile_missing,
        "backend": backend_name,
        "raw_backend": backend_val,
        "fallback": engine._fallback,
        "message": msg,
        "libsndfile_missing": libsndfile_missing,
        "libsndfile_error": libsndfile_error if libsndfile_missing else None,
        "capabilities": capabilities,
    }

@app.post("/tts/clone")
async def tts_clone(file: UploadFile = File(...), name: str = Form("My Voice"), consent: bool = Form(...)):
    """Save an uploaded sample as a clone source, gated on explicit consent
    and basic quality checks (voice_clone_qa). This does NOT perform actual
    voice-cloning synthesis — no cloning engine is installed (see
    DESIGN.md §10 M5 cloning / its kokoclone note); it only gates
    and tags what gets saved, so a real engine can be wired in later without
    revisiting this validation/consent layer.
    """
    import json

    if not consent:
        raise HTTPException(
            status_code=400,
            detail="Voice cloning requires explicit consent that you own this voice or have permission to clone it.",
        )

    safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '_', '-')]).strip().replace(" ", "_")
    if not safe_name:
        raise HTTPException(status_code=400, detail="A voice name is required.")

    voices_dir = ensure_voices_dir()
    target_path = voices_dir / f"cloned_{safe_name}.wav"
    tmp_path = None
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tmp_path = tmp.name
        tmp.close()
        # Bounded, signature-checked, duration-limited upload.
        try:
            upload_safety.stream_to_file(file.file, tmp_path, upload_safety.MAX_AUDIO_BYTES)
            upload_safety.validate_signature(tmp_path, "audio")
            upload_safety.validate_wav_duration(tmp_path)
        except upload_safety.UploadTooLarge as exc:
            raise HTTPException(status_code=413, detail=f"Voice sample too large (max {exc.limit} bytes).")
        except upload_safety.UploadRejected as exc:
            raise HTTPException(status_code=400, detail=f"Invalid voice sample: {exc}")

        ok, warnings = voice_clone_qa.check_file(tmp_path)
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
            "created_at": datetime.now(timezone.utc).isoformat(),
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

@app.get("/tts/voices")
async def list_voices():
    import json

    voices_dir = get_voices_path()

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
    
    import voice_clone_engine
    return {"defaults": defaults, "cloned": cloned,
            "cloning": voice_clone_engine.availability()}


@app.get("/tts/clone/status")
async def get_voice_clone_status():
    """Cloning-runtime status for the models/settings UI: whether cloned-voice
    synthesis can run right now, why not if it can't, and whether the optional
    side-runtime has already been provisioned. availability() does real
    imports (torch/kanade_tokenizer) as its check, so — like every other
    availability-probing route here — it runs in a threadpool rather than
    blocking the event loop.
    """
    import voice_clone_engine
    status = await run_in_threadpool(voice_clone_engine.availability)
    return {
        "ok": True,
        "available": status["available"],
        "reason": status["reason"],
        "setup_hint": status["setup_hint"],
        "mechanism": status["mechanism"],
        "provisioned": voice_clone_engine.is_clone_runtime_provisioned(),
    }


@app.post("/tts/clone/provision")
async def provision_voice_cloning():
    """Provision the optional voice-cloning runtime on demand (models-page
    "Install voice cloning" card). Replaces the old "run tools/setup_voice_
    cloning.py" CLI hint — that path can't work inside a packaged app. Runs the
    download-verify-extract in a threadpool (it's I/O + subprocess-bound) and
    always returns the fresh availability() so the card re-renders truthfully.
    provision_clone_runtime() refuses cleanly (ok=False + message) when the
    platform has no catalog entry or the artifact isn't published yet, so this
    route never raises for the not-ready case."""
    import voice_clone_engine
    result = await run_in_threadpool(voice_clone_engine.provision_clone_runtime)
    return {**result, "cloning": voice_clone_engine.availability()}


@app.delete("/tts/voices/{voice_id}")
async def delete_cloned_voice(voice_id: str):
    """Immediately delete a cloned voice (sample + provenance metadata).

    Required by the cloning consent/abuse controls (DESIGN §10 M5 U6): a user
    must be able to remove a cloned voice without a full privacy wipe. Only the
    cloned_* namespace is deletable — built-in voices are not files on disk.
    """
    safe = os.path.basename(str(voice_id or "").strip())
    if not safe.startswith("cloned_") or safe != voice_id.strip():
        raise HTTPException(status_code=400, detail="Only cloned voices (cloned_*) can be deleted.")
    voices_dir = get_voices_path()
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


@app.post("/ocr/extract")
async def ocr_extract(file: UploadFile = File(...)):
    # Validate the upload before touching optional OCR dependencies — a
    # malformed/oversized image is rejected even if Tesseract isn't installed.
    # The temp file is always cleaned up in the outer finally.
    tmp_ocr = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    temp_filename = tmp_ocr.name
    tmp_ocr.close()
    try:
        try:
            upload_safety.stream_to_file(file.file, temp_filename, upload_safety.MAX_IMAGE_BYTES)
            upload_safety.validate_signature(temp_filename, "image")
            upload_safety.validate_image(temp_filename)
        except upload_safety.UploadTooLarge as exc:
            raise HTTPException(status_code=413, detail=f"Image too large (max {exc.limit} bytes).")
        except upload_safety.UploadRejected as exc:
            raise HTTPException(status_code=400, detail=f"Invalid image: {exc}")

        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            return {"text": "[Error: pytesseract library not installed on backend.]"}
        try:
            text = pytesseract.image_to_string(Image.open(temp_filename))
            return {"text": text.strip()}
        except Exception as e:
            logging.error(f"Tesseract Error: {e}")
            return {"text": "[Error: Tesseract not found or failed. Please ensure Tesseract-OCR is installed.]"}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"OCR Endpoint Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            os.remove(temp_filename)
        except OSError:
            pass

class GraphRequest(BaseModel):
    nodes: list
    edges: list

@app.post("/graph/save")
async def save_graph(data: GraphRequest):
    graph_path = get_graph_path()
    try:
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        with open(graph_path, "w") as f:
            import json
            json.dump(data.model_dump(), f)
        return {"status": "success"}
    except Exception as e:
        logging.error(f"Graph Save Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/graph/load")
async def load_graph():
    graph_path = get_graph_path()
    if os.path.exists(graph_path):
        try:
            with open(graph_path, "r") as f:
                import json
                return json.load(f)
        except Exception as e:
             logging.error(f"Graph Load Error: {e}")
             return {"nodes": [], "edges": []}
    return {"nodes": [], "edges": []}

class PlanRequest(BaseModel):
    goal: str

@app.post("/llm/generate_plan")
async def generate_plan(request: PlanRequest):
    engine = get_selected_llm_engine()
    prompt = f"Goal: {request.goal}"

    # Generate text
    json_text = await run_in_threadpool(
        engine.process_fast_lane, prompt, preset_name="Plan Generator", true_gen=False, context_rules=False
    )
    
    # Attempt to clean potential markdown code blocks if the LLM ignores instructions
    clean_text = json_text.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    if clean_text.startswith("```"):
        clean_text = clean_text[3:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]
    
    import json
    try:
        plan = json.loads(clean_text.strip())
        return plan
    except json.JSONDecodeError:
        # Do not log model output verbatim — it can contain the user's prompt
        # content. Length + error class is enough to diagnose.
        logging.error(f"LLM produced invalid JSON ({len(clean_text)} chars).")
        return {"title": "Generation Failed", "phases": [{"name": "Error", "tasks": ["The LLM did not return valid JSON.", "Please try again."]}]}
    except Exception as e:
        logging.error(f"Plan Gen Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def _get_downloads_dir():
    """Return the user's Downloads directory, cross-platform.

    Falls back to the home directory if a Downloads folder does not exist.
    Honors the XDG_DOWNLOAD_DIR env var on Linux when set.
    """
    home = os.path.expanduser("~")
    xdg = os.environ.get("XDG_DOWNLOAD_DIR")
    candidates = []
    if xdg:
        candidates.append(os.path.expanduser(os.path.expandvars(xdg)))
    candidates.append(os.path.join(home, "Downloads"))
    for path in candidates:
        if path and os.path.isdir(path):
            return path
    return home


class ExportRequest(BaseModel):
    title: str
    content: str
    plan: dict

@app.post("/project/export")
async def export_project(request: ExportRequest):
    import zipfile
    import io
    from fastapi.responses import StreamingResponse
    
    try:
        # Create ZIP in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            # Add README
            zip_file.writestr("README.md", f"# {request.title}\n\nExported from BetterFingers.")
            
            # Add Content
            zip_file.writestr("document.md", request.content)
            
            # Add Plan
            import json
            zip_file.writestr("plan.json", json.dumps(request.plan, indent=2))
            
        zip_buffer.seek(0)

        # Save under the user's Downloads dir (cross-platform), falling back to
        # the home directory if Downloads doesn't exist.
        export_dir = _get_downloads_dir()
        safe_title = re.sub(r"[^\w\-]", "_", request.title)[:60] or "export"
        export_path = os.path.join(export_dir, f"{safe_title}_Export.zip")
        with open(export_path, "wb") as f:
            f.write(zip_buffer.getvalue())

        return {"status": "success", "path": export_path}

    except Exception as e:
        logging.error(f"Export Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/profile")
async def get_profile():
    return profile_manager.get_profile()

@app.post("/profile")
async def save_profile(data: dict):
    success = profile_manager.save_profile(data)
    return {"status": "success" if success else "error"}

@app.get("/intent/state")
async def get_intent_state():
    return {"state": intent_engine.get_state()}

@app.post("/intent/state")
async def set_intent_state(data: dict):
    # expect {"state": "planning"}
    new_state = data.get("state")
    if new_state == "planning":
        intent_engine.set_state(IntentState.PLANNING)
    elif new_state == "executing":
        intent_engine.set_state(IntentState.EXECUTING)
    elif new_state == "idle":
        intent_engine.set_state(IntentState.IDLE)
    return {"state": intent_engine.get_state()}

@app.post("/project/generate")
async def generate_project(data: dict):
    # expect {"plan": {...}, "path": "..."}
    plan = data.get("plan")
    path = data.get("path")
    if not plan or not path:
        raise HTTPException(status_code=400, detail="Missing plan or path")
    
    success, msg = await run_in_threadpool(project_generator.generate_project, plan, path)
    return {"status": "success" if success else "error", "message": msg}


# --- Extracted route modules (M6). Registered after every server-level name is
# defined, so the routers' `import server` resolves fully. _foundry_sessions is
# re-bound so server._foundry_sessions stays the shared store existing tests use.
import routes_foundry  # noqa: E402
import routes_user_config  # noqa: E402
import routes_models_resources  # noqa: E402
import routes_wake  # noqa: E402
from backend.api.routes import personas as routes_personas  # noqa: E402
from backend.api.routes import message_rescue as routes_message_rescue  # noqa: E402

app.include_router(routes_foundry.router)
app.include_router(routes_user_config.router)
app.include_router(routes_models_resources.router)
app.include_router(routes_wake.router)
app.include_router(routes_personas.router)
app.include_router(routes_message_rescue.router)
_foundry_sessions = routes_foundry._foundry_sessions


if __name__ == "__main__":
    import argparse
    import uvicorn
    
    parser = argparse.ArgumentParser(description="BetterFingers Sidecar Server")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host IP")
    parser.add_argument("--port", type=int, default=8000, help="Port number")
    parser.add_argument("--log-level", type=str, default="INFO", help="Logging level")
    args = parser.parse_args()

    setup_logging(level=args.log_level)

    # Fail-closed auth (§5): never serve an open API by accident.
    _security = validate_startup_security(
        args.host,
        os.getenv("BETTERFINGERS_AUTH_TOKEN"),
        allow_remote=os.getenv("BETTERFINGERS_ALLOW_REMOTE") == "1",
    )
    if not _security["ok"]:
        logging.error(_security["error"])
        raise SystemExit(_security["error"])
    if _security["generated"]:
        os.environ["BETTERFINGERS_AUTH_TOKEN"] = _security["token"]
        # Printed once so a standalone developer can authenticate; the token
        # is ephemeral to this process.
        print(f"[betterfingers] No auth token supplied; generated one for this run:\n"
              f"[betterfingers]   BETTERFINGERS_AUTH_TOKEN={_security['token']}")
    uvicorn.run(app, host=args.host, port=args.port)
