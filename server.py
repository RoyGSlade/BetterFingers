import os
import shutil
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import pyperclip
from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from llm_engine import get_engine, get_engine_if_initialized
from transcriber import Transcriber
from hotkey_manager import HotkeyManager
from audio_gate import should_block_for_no_audio
from user_profile_manager import profile_manager
from intent_engine import intent_engine, IntentState
from project_generator import project_generator
from platform_capabilities import get_capabilities
from platform_paths import ensure_app_dirs, get_app_data_dir, get_config_dir
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

# Global Instances
transcriber = None
hotkey_manager = None
hotkey_recorder = None
hotkey_manager_started = False
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


def ensure_transcriber_initialized(preload=False):
    global transcriber
    if transcriber is None:
        transcriber = Transcriber(profile_name=get_last_active_profile(), preload=preload)
    elif preload:
        transcriber.ensure_loaded()
    return transcriber


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
    for ws in active_websockets:
        try:
            await ws.send_json(message)
        except Exception:
            to_remove.append(ws)
    
    for ws in to_remove:
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


def create_draft(raw_text, final_text, preset="True Janitor", status="pending", metadata=None, error="", gate_reasons=None, recording_result=None):
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
        "review_tts_speed": float(config.get("review_tts_speed", 1.5)),
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
    try:
        check_cancelled()
        broadcast_status_threadsafe("transcribing")
        trans = ensure_transcriber_initialized(preload=False)
        audio_data = getattr(recording_result, "audio_data", recording_result)
        if hasattr(audio_data, "size") and audio_data.size <= 0:
            raw_text = ""
        elif audio_data is None:
            raw_text = ""
        else:
            raw_text = trans.transcribe(audio_data)

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
        
        final_text = engine.process_fast_lane(raw_text, preset, chunk_size=llm_chunk_size)

        check_cancelled()
        draft = create_draft(
            raw_text,
            final_text,
            preset=preset,
            metadata=metadata,
            recording_result=recording_result,
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
    global loop
    loop = asyncio.get_event_loop()
    load_draft_history()
    lazy_startup = is_lazy_startup_enabled()


    try:
        logging.info("Initializing Transcriber...")
        ensure_transcriber_initialized(preload=not lazy_startup)
        logging.info("Transcriber initialized successfully.")
    except Exception as e:
        logging.error(f"Transcriber startup failure: {e}")
        record_runtime_error("stt", str(e))

    if lazy_startup:
        logging.info("Lazy startup enabled; deferring LLM warmup and Hotkey Manager startup.")
        return

    try:
        logging.info("Warming up LLM Engine...")
        get_selected_llm_engine()
        logging.info("LLM Engine ready.")
    except Exception as e:
        logging.error(f"LLM Engine startup failure: {e}")
        record_runtime_error("llm", str(e))

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

@app.websocket("/ws/voice_status")
async def websocket_endpoint(websocket: WebSocket):
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
        "recovery": recovery_guidelines,
    }


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


@app.get("/personas")
async def list_personas_route():
    from llm_engine import load_personas
    return load_personas(force_reload=True)


@app.post("/personas")
async def save_persona_route(request: PersonaRequest):
    from llm_engine import upsert_persona
    ok, msg = upsert_persona(request.name, request.prompt)
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
    normalized = component.strip().lower()
    if normalized == "stt":
        if transcriber is not None:
            transcriber.unload()
        return {"ok": True, "component": "stt", "message": "STT unloaded."}
    if normalized == "llm":
        engine = get_engine_if_initialized()
        if engine is not None:
            engine.shutdown()
        return {"ok": True, "component": "llm", "message": "LLM unloaded."}
    if normalized == "tts":
        if tts_engine is not None:
            tts_engine.unload()
        return {"ok": True, "component": "tts", "message": "TTS unloaded."}
    raise HTTPException(status_code=400, detail="Unsupported component")


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
    
    # Save Upload to Temp
    temp_filename = f"temp_{file.filename}"
    try:
        with open(temp_filename, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Transcribe (pass filename string, supported by faster-whisper wrapper)
        text = transcriber.transcribe(temp_filename)
        return {"text": text}
        
    except Exception as e:
        logging.error(f"Transcription Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Cleanup
        if os.path.exists(temp_filename):
            try:
                os.remove(temp_filename)
            except Exception:
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
        
        # Save temp file
        temp_filename = f"temp_ocr_{file.filename}"
        with open(temp_filename, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        try:
            # Attempt OCR
            # Requires Tesseract installed on system and in PATH
            # If on Windows, you might need: pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
            text = pytesseract.image_to_string(Image.open(temp_filename))
            return {"text": text.strip()}
        except Exception as e:
            logging.error(f"Tesseract Error: {e}")
            return {"text": "[Error: Tesseract not found or failed. Please ensure Tesseract-OCR is installed.]"}
        finally:
            if os.path.exists(temp_filename):
                os.remove(temp_filename)
                
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
        
        # In a real app we might return a file download response directly
        # But since we are calling this from fetch in Electron, we might want to save it to a temp path 
        # or return base64. For simplicity, let's return the path to a saved temp file that Electron can "download" or move.
        # Actually, let's stick to the "server saves to desktop" or "downloads folder" approach for this local app.
        
        # For this specific task constraints, let's save to the Desktop for easy verification.
        export_path = os.path.join(os.path.expanduser("~"), "Desktop", f"{request.title.replace(' ', '_')}_Export.zip")
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
