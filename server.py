import os
import re
import shutil
import tempfile
import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import pyperclip
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from llm_engine import get_engine, get_engine_if_initialized
from transcriber import Transcriber
from hotkey_manager import HotkeyManager
from audio_gate import should_block_for_no_audio
from user_profile_manager import profile_manager
from intent_engine import intent_engine, IntentState
from project_generator import project_generator
from platform_capabilities import get_capabilities
from hardware_report import get_hardware_report, assess_model_fit, get_hardware_tier
from platform_paths import ensure_app_dirs, get_app_data_dir, get_config_dir
import recordings
import dictionary
import dictation_commands
import macros
import history_store
from model_manager import (
    DEFAULT_MODEL,
    AVAILABLE_MODELS,
    check_and_download_resources,
    delete_model,
    get_download_state,
    get_model_path,
    get_models_dir,
    get_repo_local_server_path,
    get_server_path,
    is_ready as is_llm_model_ready,
    check_model_exists,
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

# CORS - Allow Electron to communicate
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi import Request
from starlette.responses import JSONResponse, FileResponse

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    expected_token = os.getenv("BETTERFINGERS_AUTH_TOKEN")
    if expected_token and not request.url.path.startswith("/ws/"):
        if request.method != "OPTIONS":
            auth_header = request.headers.get("Authorization", "")
            parts = auth_header.split(" ", 1)
            if len(parts) != 2 or parts[0] != "Bearer" or parts[1] != expected_token:
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
tts_engine = None
active_websockets = []
draft_queue = []
draft_recordings = {}
pending_manual_send_ids = []
next_draft_id = 1
draft_lock = threading.RLock()
MAX_DRAFT_HISTORY = 100
is_processing_draft = False
cancellation_event = threading.Event()
runtime_error_history = []
runtime_error_lock = threading.Lock()
MAX_RUNTIME_ERROR_HISTORY = 50

def save_draft_history():
    import json
    history_file = os.path.join(get_user_data_path(), "draft_history.json")
    try:
        with draft_lock:
            serializable_drafts = [dict(draft) for draft in draft_queue]
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(serializable_drafts, f, indent=2)
        # Mirror into the searchable, uncapped archive (C8). Defensive: never fatal.
        history_store.upsert_many(serializable_drafts)
    except Exception as exc:
        logging.exception(f"Failed to save draft history to {history_file}: {exc}")

def load_draft_history():
    global next_draft_id
    import json
    history_file = os.path.join(get_user_data_path(), "draft_history.json")
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                with draft_lock:
                    draft_queue.clear()
                    max_id = 0
                    for d in data:
                        if isinstance(d, dict) and "id" in d:
                            draft_queue.append(d)
                            if d["id"] > max_id:
                                max_id = d["id"]
                    next_draft_id = max_id + 1
            logging.info(f"Loaded {len(draft_queue)} drafts from history, next draft ID is {next_draft_id}")
        except Exception as exc:
            logging.exception(f"Failed to load draft history from {history_file}: {exc}")



def get_voices_dir():
    ensure_app_dirs()
    voices_dir = get_app_data_dir() / "voices"
    voices_dir.mkdir(parents=True, exist_ok=True)
    return voices_dir


def get_graph_path():
    ensure_app_dirs()
    return get_config_dir() / "graph.json"


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

    return get_active_profile_payload()


def is_lazy_startup_enabled():
    return os.getenv("BETTERFINGERS_LAZY_STARTUP") == "1"


def voice_commands_enabled():
    """Whether spoken dictation commands (C2) are applied. Per-profile, default on."""
    try:
        config = load_profile(get_last_active_profile())
    except Exception:
        return True
    return bool(config.get("voice_commands_enabled", True))


def macros_enabled():
    """Whether voice macros (C11) are expanded. Per-profile, default on."""
    try:
        config = load_profile(get_last_active_profile())
    except Exception:
        return True
    return bool(config.get("macros_enabled", True))


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
        transcriber = Transcriber(profile_name=get_last_active_profile(), preload=preload)
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
    manager = HotkeyManager(
        recorder=recorder,
        on_recording_complete_callback=on_recording_complete,
        on_recording_start_callback=on_recording_start,
        on_force_stop_callback=emergency_stop_runtime,
        on_manual_send_callback=handle_primary_action,
        on_review_tts_callback=handle_review_tts_shortcut,
        is_busy_callback=lambda: is_processing_draft,
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
async def broadcast_status(status: str, data: dict = None):
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


def broadcast_status_threadsafe(status: str, data: dict = None):
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


def count_draft_tokens(text):
    return len(str(text or "").split())


def update_draft_review_fields(draft):
    token_limit = get_active_token_limit()
    token_count = count_draft_tokens(draft.get("final_text") or draft.get("raw_text") or "")
    draft["token_count"] = token_count
    draft["token_limit"] = token_limit
    draft["long_text"] = token_count > token_limit
    draft["review_state"] = draft.get("review_state") or "ready"
    return draft


def create_draft(raw_text, final_text, preset="True Janitor", status="pending", metadata=None, error="", gate_reasons=None, recording_result=None, confidence=None):
    global next_draft_id

    with draft_lock:
        draft = {
            "id": next_draft_id,
            "raw_text": raw_text or "",
            "final_text": final_text or "",
            "preset": preset,
            "status": status or "pending",
            "metadata": metadata or {},
            "error": error or "",
            "gate_reasons": list(gate_reasons or []),
            "confidence": confidence or {"score": None, "avg_logprob": None, "no_speech_prob": None},
            "pending_send": False,
            "send_result": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        update_draft_review_fields(draft)
        next_draft_id += 1
        draft_queue.append(draft)
        if recording_result is not None:
            draft_recordings[draft["id"]] = recording_result

        if len(draft_queue) > MAX_DRAFT_HISTORY:
            removed = draft_queue[: len(draft_queue) - MAX_DRAFT_HISTORY]
            del draft_queue[: len(draft_queue) - MAX_DRAFT_HISTORY]
            for removed_draft in removed:
                draft_recordings.pop(removed_draft["id"], None)

        save_draft_history()
        return dict(draft)


def get_draft_by_id(draft_id):
    with draft_lock:
        for draft in draft_queue:
            if draft["id"] == draft_id:
                return draft
    return None


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

    final_text = str(text or "").strip()
    if not final_text:
        payload.update({"message": "No text available to send.", "error": "empty_text"})
        return payload

    if requested_action == "copy_only":
        result = copy_text_to_clipboard(final_text)
        payload.update(result)
        payload["actual_action"] = result.get("actual_action") or result.get("action") or "copy_only"
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


def send_draft_by_id(draft_id, action=None, open_chat=False):
    with draft_lock:
        draft = get_draft_by_id(draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        final_text = draft.get("final_text", "")

    settings = get_profile_output_settings()
    requested_action = action or ("open_chat_then_send" if settings["send_mode"] == "auto_send" else "copy_only")
    result = perform_output_action(final_text, requested_action, open_chat=open_chat)

    with draft_lock:
        draft = get_draft_by_id(draft_id)
        if draft is not None:
            draft["send_result"] = result
            if result.get("ok"):
                draft["status"] = "sent"
                draft["pending_send"] = False
                while draft_id in pending_manual_send_ids:
                    pending_manual_send_ids.remove(draft_id)
            else:
                draft["status"] = "send_error"
                draft["error"] = result.get("message", "Send failed.")
            response = dict(draft)
            save_draft_history()
        else:
            response = {"id": draft_id, "send_result": result}

    broadcast_status_threadsafe("draft_sent" if result.get("ok") else "draft_send_error", {"draft_id": draft_id, "send_result": result})
    return response


def speak_text_aloud(text: str):
    phrase = (text or "").strip()
    if not phrase:
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

    engine = ensure_tts_initialized()
    if engine is not None:
        engine._kokoro_quantization = quantization
        logging.info(f"Speaking text aloud: '{phrase[:30]}...' (voice={voice_id}, speed={speed}x, quant={quantization})")
        engine.speak(phrase, speed=speed, voice_hint=voice_id)


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
        text = result.get("text", "").strip()
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
        text = result.get("text", "").strip()
        if text:
            speak_text_aloud(text)

    broadcast_status_threadsafe("selection_captured" if result.get("ok") else "selection_capture_failed", result)
    return result


def emergency_stop_runtime():
    # Signal cancellation of draft processing
    cancellation_event.set()

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


def record_pipeline_metrics(stt_ms=None, llm_ms=None, total_ms=None, audio_seconds=0.0, chars=0):
    """Append one utterance's pipeline latency sample (C10 HUD)."""
    entry = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stt_ms": round(stt_ms, 1) if stt_ms is not None else None,
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
        "llm": stage_stats("llm_ms"),
        "total": stage_stats("total_ms"),
        "recent": samples[-10:],
    }


def process_recording_result(recording_result):
    global is_processing_draft
    with draft_lock:
        is_processing_draft = True
    cancellation_event.clear()

    def check_cancelled():
        if cancellation_event.is_set():
            raise InterruptedError("Operation cancelled by user.")

    preset = "True Janitor"
    raw_text = ""
    metadata = get_recording_metadata(recording_result)
    # Persist the raw audio up front so it survives even a processing crash (C6).
    try:
        recordings.save_recording(
            recording_result,
            rec_id=str(int(time.time() * 1000)),
            metadata={"stop_reason": getattr(recording_result, "stop_reason", "manual")},
        )
    except Exception as exc:
        logging.debug(f"Could not persist recording: {exc}")
    pipeline_t0 = time.perf_counter()
    stt_ms = None
    llm_ms = None
    try:
        check_cancelled()
        broadcast_status_threadsafe("transcribing")
        trans = ensure_transcriber_initialized(preload=False)
        audio_data = getattr(recording_result, "audio_data", recording_result)
        # Personal dictionary (C1): bias the ASR toward the user's terms.
        dict_terms = dictionary.get_terms()
        hotwords = dictionary.hotwords_string(dict_terms)
        _stt_start = time.perf_counter()
        confidence = {"score": None, "avg_logprob": None, "no_speech_prob": None}
        if hasattr(audio_data, "size") and audio_data.size <= 0:
            raw_text = ""
        elif audio_data is None:
            raw_text = ""
        elif hasattr(trans, "transcribe_with_confidence"):
            raw_text, confidence = trans.transcribe_with_confidence(audio_data, hotwords=hotwords)
        else:
            raw_text = trans.transcribe(audio_data)
        # Post-ASR correction snaps near-miss tokens back to dictionary terms.
        if raw_text and dict_terms:
            raw_text = dictionary.correct_text(raw_text, dict_terms)
        # Spoken dictation commands (C2): "new paragraph", "period", "all caps", ...
        if raw_text and voice_commands_enabled():
            raw_text = dictation_commands.apply_commands(raw_text)
        # Voice macros (C11): expand user snippets like "my address".
        if raw_text and macros_enabled():
            raw_text = macros.apply_macros(raw_text)
        stt_ms = (time.perf_counter() - _stt_start) * 1000.0

        check_cancelled()
        blocked, reasons = should_block_for_no_audio(
            recording_result,
            raw_text,
            get_active_recording_config(),
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
            return draft

        check_cancelled()
        broadcast_status_threadsafe("rewriting")
        engine = get_selected_llm_engine()
        # Retrieve llm_chunk_size from active profile
        try:
            config = load_profile(get_last_active_profile())
            llm_chunk_size = config.get("llm_chunk_size", 750)
        except Exception:
            llm_chunk_size = 750
        
        _llm_start = time.perf_counter()
        final_text = engine.process_fast_lane(raw_text, preset, chunk_size=llm_chunk_size)
        llm_ms = (time.perf_counter() - _llm_start) * 1000.0

        check_cancelled()
        draft = create_draft(
            raw_text,
            final_text,
            preset=preset,
            metadata=metadata,
            recording_result=recording_result,
            confidence=confidence,
        )
        record_pipeline_metrics(
            stt_ms=stt_ms,
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
            },
        )
        return draft
    except InterruptedError as exc:
        logging.info("Recording processing was cancelled by the user.")
        draft = create_draft(
            raw_text,
            "",
            preset=preset,
            status="error",
            metadata=metadata,
            error=str(exc),
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
        broadcast_status_threadsafe("error", {"message": str(exc), "draft_id": draft["id"]})
        return draft
    except Exception as exc:
        logging.error(f"Recording processing failed: {exc}")
        record_runtime_error("recording", str(exc))
        draft = create_draft(
            raw_text,
            "",
            preset=preset,
            status="error",
            metadata=metadata,
            error=str(exc),
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
        broadcast_status_threadsafe("error", {"message": str(exc), "draft_id": draft["id"]})
        return draft
    finally:
        with draft_lock:
            is_processing_draft = False
        broadcast_status_threadsafe("idle")


# Hotkey Callbacks
import asyncio
loop = None

def on_recording_start():
    broadcast_status_threadsafe("recording_started")

def on_recording_complete(recording_result):
    try:
        size = len(recording_result.audio_data)
    except Exception:
        size = len(recording_result) if recording_result is not None else 0
    logging.info(f"CALLBACK: Recording Complete ({size} samples)")
    broadcast_status_threadsafe("recording_complete", {"sample_count": size})

    def _worker():
        try:
            process_recording_result(recording_result)
        except Exception:
            logging.exception("Recording worker failed")

    threading.Thread(target=_worker, daemon=True, name="betterfingers-recording-worker").start()

@app.on_event("startup")
async def startup_event():
    global loop, _warmup_thread
    loop = asyncio.get_event_loop()
    load_draft_history()
    # One-time backfill of the searchable archive from the legacy JSON (C8).
    try:
        history_store.migrate_from_json(os.path.join(get_user_data_path(), "draft_history.json"))
    except Exception as exc:
        logging.debug(f"history archive migration skipped: {exc}")
    lazy_startup = is_lazy_startup_enabled()
    residency_settings = get_model_residency_settings()

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
    # Join the background warmup thread so it can't outlive this app instance and
    # mutate global model state afterwards (also keeps tests deterministic).
    thread = _warmup_thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=5)

from fastapi import Query, status

@app.websocket("/ws/voice_status")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(None)):
    expected_token = os.getenv("BETTERFINGERS_AUTH_TOKEN")
    if expected_token and token != expected_token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
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
    stt_info = {
        "initialized": transcriber is not None,
        "loaded": bool(getattr(transcriber, "model", None)) if transcriber else False,
        "model_size": getattr(transcriber, "model_size", None) if transcriber else None,
        "device": getattr(transcriber, "device", None) if transcriber else None,
    }

    # LLM details
    selected_model_id = model_id or get_selected_llm_model_id()
    llm_info = {
        "initialized": engine is not None,
        "ready": engine_ready,
        "model_id": selected_model_id,
        "llama_server_path": str(get_server_path()),
        "llama_server_exists": os.path.exists(get_server_path()),
        "model_exists": check_model_exists(selected_model_id),
    }

    # TTS details
    tts_engine_inst = ensure_tts_initialized()
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
        
    return {
        "status": "active", 
        "transcriber": transcriber is not None,
        "llm_engine": engine_ready
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
    settings = get_profile_output_settings()
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


class PersonaRequest(BaseModel):
    name: str
    prompt: str
    # Optional persona schema v2 fields (U7). Omitted fields are left untouched on
    # update, so legacy {name, prompt} clients keep working unchanged.
    temperature: Optional[float] = None
    model_hint: Optional[str] = None
    dictionary_scope: Optional[str] = None
    voice: Optional[dict] = None
    format: Optional[dict] = None
    few_shot: Optional[list] = None


@app.get("/personas")
async def list_personas_route():
    from llm_engine import load_personas
    return load_personas(force_reload=True)


@app.get("/personas/{name}")
async def get_persona_route(name: str):
    """Return the full schema v2 persona dict for the editor."""
    from llm_engine import get_persona
    entry = get_persona(name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Persona '{name}' not found.")
    return entry


@app.post("/personas")
async def save_persona_route(request: PersonaRequest):
    from llm_engine import upsert_persona
    # Build a v2 payload from the provided fields; drop unspecified ones so an
    # update preserves prior rich values (upsert_persona merges partial dicts).
    payload = {"prompt": request.prompt}
    for key in ("temperature", "model_hint", "dictionary_scope", "voice", "format", "few_shot"):
        value = getattr(request, key)
        if value is not None:
            payload[key] = value
    ok, msg = upsert_persona(request.name, payload)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


@app.delete("/personas/{name}")
async def delete_persona_route(name: str):
    from llm_engine import delete_persona
    ok, msg = delete_persona(name)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


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
        models.append(
            {
                "id": model_id,
                "selected": model_id == selected,
                "installed": os.path.exists(model_path),
                "ready": is_llm_model_ready(model_id),
                "path": model_path,
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
async def select_llm_model(request: LlmModelSelectRequest):
    if request.model_id not in AVAILABLE_MODELS:
        raise HTTPException(status_code=400, detail="Unsupported LLM model")
    profile_name = get_last_active_profile()
    cfg = load_profile(profile_name)
    cfg["llm_model_id"] = request.model_id
    save_runtime_profile(profile_name, cfg)
    engine = get_engine_if_initialized()
    if engine is not None:
        engine.set_model_id(request.model_id)
    return await list_llm_models()


@app.post("/models/llm/{model_id}/download")
def download_llm_model(model_id: str):
    if model_id not in AVAILABLE_MODELS:
        raise HTTPException(status_code=400, detail="Unsupported LLM model")
    result = check_and_download_resources(model_id)
    return {"model_id": model_id, **(result if isinstance(result, dict) else {"ok": bool(result)})}


@app.delete("/models/llm/{model_id}")
async def delete_llm_model(model_id: str):
    if model_id not in AVAILABLE_MODELS:
        raise HTTPException(status_code=400, detail="Unsupported LLM model")
    ok, message = delete_model(model_id)
    return {"ok": ok, "model_id": model_id, "message": message}


@app.get("/models/llm/{model_id}/download-state")
async def llm_download_state(model_id: str):
    return get_download_state(model_id)


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


@app.post("/models/unload/{component}")
async def unload_model_component(component: str):
    """Genuinely release a model component's memory.

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
        return {
            "ok": True,
            "component": "tts",
            "unloaded": unloaded,
            "message": "TTS unloaded." if unloaded else "TTS was not loaded.",
        }

    raise HTTPException(status_code=400, detail="Unsupported component")


@app.get("/metrics")
async def pipeline_metrics_endpoint():
    return get_pipeline_metrics_summary()


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


def get_privacy_report():
    """Everything that touches the network + where local data lives (C7)."""
    history_file = os.path.join(get_user_data_path(), "draft_history.json")
    voices_dir = str(get_app_data_dir() / "voices")
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

    data_locations = [
        {"name": "Draft history", "path": history_file, "bytes": _path_size_bytes(history_file)},
        {"name": "Cloned voices", "path": voices_dir, "bytes": _path_size_bytes(voices_dir)},
        {"name": "Models", "path": str(get_models_dir()), "bytes": _path_size_bytes(str(get_models_dir()))},
    ]

    return {
        "offline_by_default": True,
        "network_touchpoints": network_touchpoints,
        "data_locations": data_locations,
        "retention": {
            "recordings_persisted_to_disk": False,
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


@app.post("/privacy/wipe")
async def privacy_wipe(request: PrivacyWipeRequest = PrivacyWipeRequest()):
    """Delete app-generated conversational data (drafts, history, in-memory
    recordings). Models and profiles are intentionally NOT touched; cloned
    voices are removed only when explicitly requested."""
    cleared = {}
    with draft_lock:
        cleared["drafts"] = len(draft_queue)
        cleared["recordings"] = len(draft_recordings)
        draft_queue.clear()
        draft_recordings.clear()
        pending_manual_send_ids.clear()
    save_draft_history()

    history_file = os.path.join(get_user_data_path(), "draft_history.json")
    try:
        if os.path.exists(history_file):
            os.remove(history_file)
            cleared["history_file_removed"] = True
    except OSError as exc:
        logging.warning(f"Could not remove draft history file: {exc}")
        cleared["history_file_removed"] = False

    if request.wipe_voices:
        voices_dir = get_app_data_dir() / "voices"
        try:
            if voices_dir.exists():
                shutil.rmtree(voices_dir, ignore_errors=True)
                cleared["voices_removed"] = True
        except OSError as exc:
            logging.warning(f"Could not remove voices dir: {exc}")
            cleared["voices_removed"] = False

    broadcast_status_threadsafe("draft_history_cleared")
    return {"ok": True, "cleared": cleared, "message": "Your data was wiped."}


@app.get("/recordings")
async def list_recordings_endpoint():
    return {"ok": True, "recordings": recordings.list_recordings()}


@app.post("/recordings/{rec_id}/retranscribe")
async def retranscribe_recording(rec_id: str):
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
    return {"ok": True, "draft": draft}


@app.delete("/recordings/{rec_id}")
async def delete_recording_endpoint(rec_id: str):
    removed = recordings.delete_recording(rec_id)
    return {"ok": True, "removed": removed}


@app.delete("/recordings")
async def clear_recordings_endpoint():
    count = recordings.clear_recordings()
    return {"ok": True, "cleared": count}


class DictionaryTermRequest(BaseModel):
    term: str


@app.get("/dictionary")
async def get_dictionary():
    return {"ok": True, "terms": dictionary.get_terms()}


@app.post("/dictionary")
async def add_dictionary_term(request: DictionaryTermRequest):
    if not str(request.term or "").strip():
        raise HTTPException(status_code=400, detail="Term must not be empty.")
    return {"ok": True, "terms": dictionary.add_term(request.term)}


@app.delete("/dictionary/{term}")
async def delete_dictionary_term(term: str):
    return {"ok": True, "terms": dictionary.remove_term(term)}


class DictionarySuggestRequest(BaseModel):
    raw_text: str = ""
    edited_text: str = ""


@app.post("/dictionary/suggest")
async def suggest_dictionary_terms(request: DictionarySuggestRequest):
    suggestions = dictionary.suggest_from_edit(request.raw_text, request.edited_text)
    return {"ok": True, "suggestions": suggestions}


class MacroRequest(BaseModel):
    trigger: str
    expansion: str


@app.get("/macros")
async def get_macros_endpoint():
    return {"ok": True, "macros": macros.get_macros()}


@app.post("/macros")
async def add_macro_endpoint(request: MacroRequest):
    if not str(request.trigger or "").strip() or not str(request.expansion or "").strip():
        raise HTTPException(status_code=400, detail="Both a trigger and an expansion are required.")
    return {"ok": True, "macros": macros.add_macro(request.trigger, request.expansion)}


@app.delete("/macros/{trigger}")
async def delete_macro_endpoint(trigger: str):
    return {"ok": True, "macros": macros.remove_macro(trigger)}


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
                save_draft_history()
                broadcast_status_threadsafe("draft_accepted", {"draft_id": draft_id, "pending_send": True})
                return response
    raise HTTPException(status_code=404, detail="Draft not found")


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
                save_draft_history()
                broadcast_status_threadsafe("draft_declined", {"draft_id": draft_id})
                return response
    raise HTTPException(status_code=404, detail="Draft not found")


@app.post("/drafts/{draft_id}/retry")
async def retry_draft(draft_id: int):
    with draft_lock:
        recording_result = draft_recordings.get(draft_id)

    if recording_result is None:
        raise HTTPException(status_code=409, detail="No recording data is available for this draft")

    return process_recording_result(recording_result)


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
    token_limit = get_active_token_limit()
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
        save_draft_history()

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
            save_draft_history()
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
        logging.exception("Draft rewrite failed")
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

    req_voice = request.voice_id
    if req_voice is None:
        req_voice = config.get("review_tts_voice_hint") or "standard_female"

    req_speed = request.speed
    if req_speed is None:
        req_speed = config.get("review_tts_speed") or 1.0

    voice_id = normalize_tts_voice_id(req_voice)
    speed = max(0.5, min(3.0, float(req_speed)))
    logging.info(f"Draft TTS Request: draft={draft_id} '{text[:20]}...' | Voice: {voice_id} | Speed: {speed}x")

    engine = ensure_tts_initialized()
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

    result = engine.speak(text, speed=speed, voice_hint=voice_id)
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


@app.post("/drafts/{draft_id}/send")
async def send_draft(draft_id: int, request: DraftSendRequest = DraftSendRequest()):
    return send_draft_by_id(draft_id, action=request.action, open_chat=request.open_chat)


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
    result = {"requested": request.dict()}

    if request.stt:
        try:
            trans = ensure_transcriber_initialized(preload=False)
            result["stt"] = {
                "ok": True,
                "initialized": trans is not None,
                "loaded": bool(trans and trans.ensure_loaded()),
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
            result["llm"] = {
                "ok": True,
                "initialized": engine is not None,
                "ready": bool(getattr(engine, "_ready", False)),
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
        engine = get_selected_llm_engine()
        result = engine.process_fast_lane(
            request.text,
            request.preset,
            true_gen=request.true_gen,
        )
        return {"text": result}
    except Exception as e:
        logging.error(f"LLM Process Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    global transcriber
    if not transcriber:
        raise HTTPException(status_code=503, detail="Transcriber not initialized")
    
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    temp_filename = tmp.name
    try:
        with tmp:
            shutil.copyfileobj(file.file, tmp)
        text = transcriber.transcribe(temp_filename)
        return {"text": text}
    except Exception as e:
        logging.error(f"Transcription Error: {e}")
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

@app.post("/tts/speak")
async def tts_speak(request: TTSRequest):
    text = (request.text or "").strip()
    if not text:
        return {"ok": False, "status": "error", "message": "No text to speak.", "error": "empty_text"}

    profile_name = get_last_active_profile()
    try:
        config = load_profile(profile_name)
    except Exception:
        config = {}

    req_voice = request.voice_id
    if req_voice is None:
        req_voice = config.get("review_tts_voice_hint") or "standard_female"

    req_speed = request.speed
    if req_speed is None:
        req_speed = config.get("review_tts_speed") or 1.0

    voice_id = normalize_tts_voice_id(req_voice)
    speed = max(0.5, min(3.0, float(req_speed)))
    logging.info(f"TTS Request: '{text[:20]}...' | Voice: {voice_id} | Speed: {speed}x")

    engine = ensure_tts_initialized()
    if engine is None:
        message = "TTS engine is not available."
        record_runtime_error("tts", message, {"action": "tts_speak"})
        return {"ok": False, "status": "error", "message": message, "error": "tts_unavailable"}

    result = engine.speak(text, speed=speed, voice_hint=voice_id)
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
    engine = ensure_tts_initialized()
    
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

    status = engine.ensure_loaded()
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
        
    return {
        "ok": engine.is_loaded() and not libsndfile_missing,
        "backend": backend_name,
        "raw_backend": backend_val,
        "fallback": engine._fallback,
        "message": msg,
        "libsndfile_missing": libsndfile_missing,
        "libsndfile_error": libsndfile_error if libsndfile_missing else None
    }

@app.post("/tts/clone")
async def tts_clone(file: UploadFile = File(...), name: str = "My Voice"):
    # Ensure directory exists
    voices_dir = get_voices_dir()
    
    safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '_', '-')]).strip().replace(" ", "_")
    target_path = voices_dir / f"cloned_{safe_name}.wav" # Saving wav for now, real impl extracts embedding
    
    try:
        with open(target_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        logging.info(f"Voice cloned: {safe_name} saved to {target_path}")
        return {"status": "success", "voice_id": f"cloned_{safe_name}", "path": str(target_path)}
    except Exception as e:
        logging.error(f"Cloning failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tts/voices")
async def list_voices():
    voices_dir = get_voices_dir()
    
    cloned = []
    if os.path.exists(voices_dir):
        for f in os.listdir(voices_dir):
            if f.endswith(".wav") or f.endswith(".npy"):
                cloned.append({"id": f.split('.')[0], "name": f.split('.')[0].replace("cloned_", "").replace("_", " ")})
                
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
    
    return {"defaults": defaults, "cloned": cloned}

@app.post("/ocr/extract")
async def ocr_extract(file: UploadFile = File(...)):
    try:
        import pytesseract
        from PIL import Image
        
        tmp_ocr = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        temp_filename = tmp_ocr.name
        try:
            with tmp_ocr:
                shutil.copyfileobj(file.file, tmp_ocr)
            text = pytesseract.image_to_string(Image.open(temp_filename))
            return {"text": text.strip()}
        except Exception as e:
            logging.error(f"Tesseract Error: {e}")
            return {"text": "[Error: Tesseract not found or failed. Please ensure Tesseract-OCR is installed.]"}
        finally:
            try:
                os.remove(temp_filename)
            except OSError:
                pass
                
    except ImportError:
         return {"text": "[Error: pytesseract library not installed on backend.]"}
    except Exception as e:
        logging.error(f"OCR Endpoint Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
            json.dump(data.dict(), f)
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
    json_text = engine.process_fast_lane(prompt, preset_name="Plan Generator", true_gen=False, context_rules=False)
    
    # Attempt to clean potential markdown code blocks if the LLM ignores instructions
    clean_text = json_text.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    if clean_text.startswith("```"):
        clean_text = clean_text[3:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]
    
    try:
        import json
        plan = json.loads(clean_text.strip())
        return plan
    except json.JSONDecodeError:
        logging.error(f"LLM produced invalid JSON: {clean_text}")
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
    
    success, msg = project_generator.generate_project(plan, path)
    return {"status": "success" if success else "error", "message": msg}


if __name__ == "__main__":
    import argparse
    import uvicorn
    
    parser = argparse.ArgumentParser(description="BetterFingers Sidecar Server")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host IP")
    parser.add_argument("--port", type=int, default=8000, help="Port number")
    parser.add_argument("--log-level", type=str, default="INFO", help="Logging level")
    args = parser.parse_args()

    setup_logging(level=args.log_level)
    uvicorn.run(app, host=args.host, port=args.port)
