import sys
import os
import shutil
import logging
import glob
import copy
import re
import math
import yaml

def get_app_path():
    """
    Returns the base path for READ-ONLY assets (images, default config).
    CRITICAL: This path is often inside a frozen EXE or temporary _MEIPASS folder.
    NEVER attempt to write files here.
    """
    # PyInstaller creates a temp folder and stores path in _MEIPASS
    if hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS

    # PyInstaller 6+ (onedir mode) or standard script execution
    if getattr(sys, 'frozen', False):
        # We are running as an EXE (but not onefile, or onefile handled above)
        base_path = os.path.dirname(sys.executable)
        
        # Check for PyInstaller 6+ structure (everything inside _internal)
        internal_path = os.path.join(base_path, '_internal')
        if os.path.exists(internal_path):
            return internal_path
            
        return base_path
        
    # Standard script execution
    return os.path.dirname(os.path.abspath(__file__))

def get_user_data_path():
    """
    Returns the base path for READ/WRITE files (user config, logs, profiles).
    Always returns: %APPDATA%/BetterFingers/
    Ensures the directory exists before returning.
    """
    app_data = os.environ.get('APPDATA')
    if not app_data:
        app_data = os.path.expanduser("~")
        
    path = os.path.join(app_data, "BetterFingers")
    
    # CRITICAL: This is the ONLY place we should ever write files.
    if not os.path.exists(path):
        try:
            os.makedirs(path)
            # Logging implies this function works, so use safe print if logging fails later
            print(f"Verified User Data path: {path}") 
        except OSError as e:
            print(f"FATAL: Failed to create User Data path {path}: {e}")
            
    return path

def get_profiles_dir():
    """Returns the path to the 'profiles' directory."""
    path = os.path.join(get_user_data_path(), "profiles")
    if not os.path.exists(path):
        os.makedirs(path)
    return path


def get_draft_history_path():
    """Returns the path to the persisted finalized draft history file."""
    return os.path.join(get_user_data_path(), "draft_history.json")

def check_first_run():
    """Returns True if this is the first run, False otherwise."""
    marker_path = os.path.join(get_user_data_path(), ".first_run_complete")
    if not os.path.exists(marker_path):
        try:
            with open(marker_path, "w") as f:
                f.write("Welcome to BetterFingers!")
            return True
        except Exception:
            return False # Fail safe
    return False

def _app_state_path():
    return os.path.join(get_user_data_path(), "app_state.yaml")


def _app_state_defaults():
    return {
        "launch_count": 0,
        "donation_prompt_shown": False,
        "last_active_profile": "Default",
    }


def _sanitize_app_state(state):
    defaults = _app_state_defaults()
    payload = state if isinstance(state, dict) else {}
    launch_count = _coerce_int(payload.get("launch_count", defaults["launch_count"]), defaults["launch_count"], minimum=0)
    donation_prompt_shown = _coerce_bool(
        payload.get("donation_prompt_shown", defaults["donation_prompt_shown"]),
        defaults["donation_prompt_shown"],
    )
    last_active_profile = _coerce_str(
        payload.get("last_active_profile", defaults["last_active_profile"]),
        defaults["last_active_profile"],
    )
    last_active_profile = "".join(
        ch for ch in last_active_profile if ch.isalnum() or ch in (" ", "_", "-")
    ).strip() or defaults["last_active_profile"]
    return {
        "launch_count": launch_count,
        "donation_prompt_shown": donation_prompt_shown,
        "last_active_profile": last_active_profile,
    }


def load_app_state():
    path = _app_state_path()
    defaults = _app_state_defaults()
    if not os.path.exists(path):
        return copy.deepcopy(defaults)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    except Exception as exc:
        logging.error("Failed to load app_state.yaml: %s", exc)
        return copy.deepcopy(defaults)
    return _sanitize_app_state(raw)


def save_app_state(state):
    path = _app_state_path()
    payload = _sanitize_app_state(state)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, sort_keys=True)
    except Exception as exc:
        logging.error("Failed to save app_state.yaml: %s", exc)


def register_launch_and_should_show_donation(threshold=5):
    safe_threshold = max(1, _coerce_int(threshold, 5, minimum=1))
    state = load_app_state()
    state["launch_count"] = int(state.get("launch_count", 0)) + 1
    should_show = bool(state["launch_count"] >= safe_threshold and not state.get("donation_prompt_shown", False))
    if should_show:
        state["donation_prompt_shown"] = True
    save_app_state(state)
    return should_show


def get_last_active_profile(default="Default"):
    safe_default = _coerce_str(default, "Default").strip() or "Default"
    state = load_app_state()
    candidate = _coerce_str(state.get("last_active_profile", safe_default), safe_default).strip()
    if not candidate:
        return safe_default
    try:
        profiles = set(list_profiles())
    except Exception:
        return safe_default
    if candidate in profiles:
        return candidate
    return safe_default


def set_last_active_profile(profile_name):
    state = load_app_state()
    candidate = _coerce_str(profile_name, "Default")
    candidate = "".join(ch for ch in candidate if ch.isalnum() or ch in (" ", "_", "-")).strip() or "Default"
    state["last_active_profile"] = candidate
    save_app_state(state)


def _coerce_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on", "enabled"}:
            return True
        if lowered in {"0", "false", "no", "off", "disabled"}:
            return False
    return default


def _coerce_int(value, default, minimum=None, maximum=None):
    try:
        parsed = int(float(value))
    except Exception:
        parsed = int(default)
    if minimum is not None:
        parsed = max(int(minimum), parsed)
    if maximum is not None:
        parsed = min(int(maximum), parsed)
    return parsed


def _coerce_float(value, default, minimum=None, maximum=None):
    try:
        parsed = float(value)
    except Exception:
        parsed = float(default)
    if not math.isfinite(parsed):
        parsed = float(default)
    if minimum is not None:
        parsed = max(float(minimum), parsed)
    if maximum is not None:
        parsed = min(float(maximum), parsed)
    return parsed


def _coerce_str(value, default=""):
    if value is None:
        return default
    try:
        return str(value)
    except Exception:
        return default


def _coerce_choice(value, default, allowed):
    lowered_allowed = {str(item).strip().lower() for item in allowed}
    parsed = _coerce_str(value, default).strip().lower()
    if parsed in lowered_allowed:
        return parsed
    return str(default).strip().lower()


def _coerce_color(value, default):
    parsed = _coerce_str(value, default).strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", parsed):
        return parsed
    return default


def _sanitize_profile_values(config, defaults):
    if not isinstance(config, dict):
        return copy.deepcopy(defaults)

    cfg = config
    d = defaults

    cfg["hotkey"] = _coerce_str(cfg.get("hotkey", d["hotkey"]), d["hotkey"]).strip() or d["hotkey"]
    cfg["force_stop_key"] = _coerce_str(cfg.get("force_stop_key", d["force_stop_key"]), d["force_stop_key"]).strip()
    cfg["manual_send_hotkey"] = _coerce_str(
        cfg.get("manual_send_hotkey", d["manual_send_hotkey"]), d["manual_send_hotkey"]
    ).strip()
    cfg["recording_mode"] = _coerce_choice(cfg.get("recording_mode", d["recording_mode"]), d["recording_mode"], {"toggle", "ptt"})
    cfg["send_mode"] = _coerce_choice(cfg.get("send_mode", d["send_mode"]), d["send_mode"], {"review_first", "auto_send"})
    cfg["chat_close_action"] = _coerce_choice(
        cfg.get("chat_close_action", d["chat_close_action"]),
        d["chat_close_action"],
        {"none", "esc", "chat_key"},
    )
    cfg["quantization"] = _coerce_choice(cfg.get("quantization", d["quantization"]), d["quantization"], {"int4", "int8"})
    cfg["model_size"] = _coerce_choice(
        cfg.get("model_size", d["model_size"]),
        d["model_size"],
        {"tiny.en", "base.en", "small.en", "medium.en", "large-v3"},
    )

    cfg["chat_open_key"] = _coerce_str(cfg.get("chat_open_key", d["chat_open_key"]), d["chat_open_key"]).strip()
    cfg["voice_mute_key"] = _coerce_str(cfg.get("voice_mute_key", d["voice_mute_key"]), d["voice_mute_key"]).strip()
    cfg["sign_off_text"] = _coerce_str(cfg.get("sign_off_text", d["sign_off_text"]), d["sign_off_text"])
    cfg["review_tts_hotkey"] = _coerce_str(
        cfg.get("review_tts_hotkey", d["review_tts_hotkey"]), d["review_tts_hotkey"]
    ).strip()
    cfg["review_tts_voice_hint"] = (
        _coerce_str(cfg.get("review_tts_voice_hint", d["review_tts_voice_hint"]), d["review_tts_voice_hint"]).strip()
        or d["review_tts_voice_hint"]
    )
    cfg["current_preset"] = _coerce_str(cfg.get("current_preset", d["current_preset"]), d["current_preset"])
    cfg["experience_preset"] = _coerce_choice(
        cfg.get("experience_preset", d["experience_preset"]),
        d["experience_preset"],
        {"custom", "simple", "plus", "pro", "dont_use"},
    )
    cfg["llm_model_id"] = (
        _coerce_str(cfg.get("llm_model_id", d["llm_model_id"]), d["llm_model_id"]).strip() or d["llm_model_id"]
    )

    cfg["audio_ducking"] = _coerce_bool(cfg.get("audio_ducking", d["audio_ducking"]), d["audio_ducking"])
    cfg["auto_submit"] = _coerce_bool(cfg.get("auto_submit", d["auto_submit"]), d["auto_submit"])
    cfg["instant_typing"] = _coerce_bool(cfg.get("instant_typing", d["instant_typing"]), d["instant_typing"])
    cfg["review_tts_enabled"] = _coerce_bool(cfg.get("review_tts_enabled", d["review_tts_enabled"]), d["review_tts_enabled"])
    cfg["llm_enabled"] = _coerce_bool(cfg.get("llm_enabled", d["llm_enabled"]), d["llm_enabled"])
    cfg["true_gen"] = _coerce_bool(cfg.get("true_gen", d["true_gen"]), d["true_gen"])
    cfg["organic_formatting_enabled"] = _coerce_bool(
        cfg.get("organic_formatting_enabled", d["organic_formatting_enabled"]),
        d["organic_formatting_enabled"],
    )
    cfg["use_gpu"] = _coerce_bool(cfg.get("use_gpu", d["use_gpu"]), d["use_gpu"])
    cfg["model_keep_llm_loaded"] = _coerce_bool(
        cfg.get("model_keep_llm_loaded", d["model_keep_llm_loaded"]),
        d["model_keep_llm_loaded"],
    )
    cfg["model_keep_stt_loaded"] = _coerce_bool(
        cfg.get("model_keep_stt_loaded", d["model_keep_stt_loaded"]),
        d["model_keep_stt_loaded"],
    )
    cfg["model_keep_tts_loaded"] = _coerce_bool(
        cfg.get("model_keep_tts_loaded", d["model_keep_tts_loaded"]),
        d["model_keep_tts_loaded"],
    )
    cfg["notification_overlay_enabled"] = _coerce_bool(
        cfg.get("notification_overlay_enabled", d["notification_overlay_enabled"]),
        d["notification_overlay_enabled"],
    )
    cfg["preview_overlay_enabled"] = _coerce_bool(
        cfg.get("preview_overlay_enabled", d["preview_overlay_enabled"]),
        d["preview_overlay_enabled"],
    )
    cfg["status_indicator_enabled"] = _coerce_bool(
        cfg.get("status_indicator_enabled", d["status_indicator_enabled"]),
        d["status_indicator_enabled"],
    )
    cfg["status_indicator_flash_enabled"] = _coerce_bool(
        cfg.get("status_indicator_flash_enabled", d["status_indicator_flash_enabled"]),
        d["status_indicator_flash_enabled"],
    )
    cfg["controller_enabled"] = _coerce_bool(cfg.get("controller_enabled", d["controller_enabled"]), d["controller_enabled"])
    cfg["controller_ptt"] = _coerce_bool(cfg.get("controller_ptt", d["controller_ptt"]), d["controller_ptt"])

    cfg["audio_ducking_level_percent"] = _coerce_float(
        cfg.get("audio_ducking_level_percent", d["audio_ducking_level_percent"]),
        d["audio_ducking_level_percent"],
        minimum=1.0,
        maximum=100.0,
    )
    cfg["audio_ducking_fallback_return_percent"] = _coerce_float(
        cfg.get("audio_ducking_fallback_return_percent", d["audio_ducking_fallback_return_percent"]),
        d["audio_ducking_fallback_return_percent"],
        minimum=1.0,
        maximum=100.0,
    )
    cfg["min_inter_key_delay"] = _coerce_float(
        cfg.get("min_inter_key_delay", d["min_inter_key_delay"]),
        d["min_inter_key_delay"],
        minimum=0.0001,
        maximum=1.0,
    )
    cfg["max_inter_key_delay"] = _coerce_float(
        cfg.get("max_inter_key_delay", d["max_inter_key_delay"]),
        d["max_inter_key_delay"],
        minimum=0.0002,
        maximum=1.5,
    )
    cfg["min_key_hold"] = _coerce_float(
        cfg.get("min_key_hold", d["min_key_hold"]),
        d["min_key_hold"],
        minimum=0.0005,
        maximum=1.0,
    )
    cfg["max_key_hold"] = _coerce_float(
        cfg.get("max_key_hold", d["max_key_hold"]),
        d["max_key_hold"],
        minimum=0.0006,
        maximum=1.5,
    )
    if cfg["max_inter_key_delay"] < cfg["min_inter_key_delay"]:
        cfg["max_inter_key_delay"] = cfg["min_inter_key_delay"]
    if cfg["max_key_hold"] < cfg["min_key_hold"]:
        cfg["max_key_hold"] = cfg["min_key_hold"]

    cfg["review_tts_speed"] = _coerce_float(
        cfg.get("review_tts_speed", d["review_tts_speed"]),
        d["review_tts_speed"],
        minimum=0.5,
        maximum=3.0,
    )
    cfg["notification_overlay_alpha"] = _coerce_float(
        cfg.get("notification_overlay_alpha", d["notification_overlay_alpha"]),
        d["notification_overlay_alpha"],
        minimum=0.1,
        maximum=1.0,
    )
    cfg["preview_overlay_alpha"] = _coerce_float(
        cfg.get("preview_overlay_alpha", d["preview_overlay_alpha"]),
        d["preview_overlay_alpha"],
        minimum=0.1,
        maximum=1.0,
    )
    cfg["no_audio_min_duration_sec"] = _coerce_float(
        cfg.get("no_audio_min_duration_sec", d["no_audio_min_duration_sec"]),
        d["no_audio_min_duration_sec"],
        minimum=0.0,
        maximum=30.0,
    )
    cfg["no_audio_min_rms"] = _coerce_float(
        cfg.get("no_audio_min_rms", d["no_audio_min_rms"]),
        d["no_audio_min_rms"],
        minimum=0.0,
        maximum=1.0,
    )
    cfg["no_audio_min_peak"] = _coerce_float(
        cfg.get("no_audio_min_peak", d["no_audio_min_peak"]),
        d["no_audio_min_peak"],
        minimum=0.0,
        maximum=1.0,
    )
    cfg["controller_axis_threshold"] = _coerce_float(
        cfg.get("controller_axis_threshold", d["controller_axis_threshold"]),
        d["controller_axis_threshold"],
        minimum=0.1,
        maximum=1.0,
    )

    cfg["notification_overlay_custom_x"] = _coerce_int(
        cfg.get("notification_overlay_custom_x", d["notification_overlay_custom_x"]),
        d["notification_overlay_custom_x"],
    )
    cfg["notification_overlay_custom_y"] = _coerce_int(
        cfg.get("notification_overlay_custom_y", d["notification_overlay_custom_y"]),
        d["notification_overlay_custom_y"],
    )
    cfg["preview_overlay_custom_x"] = _coerce_int(
        cfg.get("preview_overlay_custom_x", d["preview_overlay_custom_x"]),
        d["preview_overlay_custom_x"],
    )
    cfg["preview_overlay_custom_y"] = _coerce_int(
        cfg.get("preview_overlay_custom_y", d["preview_overlay_custom_y"]),
        d["preview_overlay_custom_y"],
    )
    cfg["controller_button"] = _coerce_int(cfg.get("controller_button", d["controller_button"]), d["controller_button"], minimum=0)
    cfg["controller_sequence_window_ms"] = _coerce_int(
        cfg.get("controller_sequence_window_ms", d["controller_sequence_window_ms"]),
        d["controller_sequence_window_ms"],
        minimum=100,
        maximum=2000,
    )
    cfg["output_token_limit"] = _coerce_int(
        cfg.get("output_token_limit", d["output_token_limit"]),
        d["output_token_limit"],
        minimum=900,
        maximum=1200,
    )
    # max_completion_tokens is the real per-call LLM completion ceiling;
    # long_draft_warning_words only drives the "this draft is long" UI warning.
    cfg["max_completion_tokens"] = _coerce_int(
        cfg.get("max_completion_tokens", d["max_completion_tokens"]),
        d["max_completion_tokens"],
        minimum=512,
        maximum=4096,
    )
    cfg["long_draft_warning_words"] = _coerce_int(
        cfg.get("long_draft_warning_words", d["long_draft_warning_words"]),
        d["long_draft_warning_words"],
        minimum=300,
        maximum=10000,
    )
    cfg["llm_chunk_size"] = _coerce_int(
        cfg.get("llm_chunk_size", d.get("llm_chunk_size", 750)),
        d.get("llm_chunk_size", 750),
        minimum=50,
        maximum=5000,
    )
    cfg["whisper_chunk_size"] = _coerce_int(
        cfg.get("whisper_chunk_size", d.get("whisper_chunk_size", 1000)),
        d.get("whisper_chunk_size", 1000),
        minimum=50,
        maximum=5000,
    )
    cfg["draft_history_limit"] = _coerce_int(
        cfg.get("draft_history_limit", d["draft_history_limit"]),
        d["draft_history_limit"],
        minimum=10,
        maximum=500,
    )
    cfg["long_input_message"] = (
        _coerce_str(cfg.get("long_input_message", d["long_input_message"]), d["long_input_message"]).strip()
        or d["long_input_message"]
    )

    cfg["overlay_position"] = _coerce_choice(
        cfg.get("overlay_position", d["overlay_position"]),
        d["overlay_position"],
        {"top-left", "top-right", "bottom-left", "bottom-right", "mid-left", "mid-right"},
    ).title().replace("-", "-")
    cfg["notification_overlay_position"] = _coerce_choice(
        cfg.get("notification_overlay_position", d["notification_overlay_position"]),
        d["notification_overlay_position"],
        {"top-left", "top-right", "bottom-left", "bottom-right", "custom"},
    ).title().replace("-", "-")
    cfg["preview_overlay_position"] = _coerce_choice(
        cfg.get("preview_overlay_position", d["preview_overlay_position"]),
        d["preview_overlay_position"],
        {"top-left", "top-right", "bottom-left", "bottom-right", "custom"},
    ).title().replace("-", "-")

    cfg["notification_overlay_bg"] = _coerce_color(
        cfg.get("notification_overlay_bg", d["notification_overlay_bg"]),
        d["notification_overlay_bg"],
    )
    cfg["notification_overlay_fg"] = _coerce_color(
        cfg.get("notification_overlay_fg", d["notification_overlay_fg"]),
        d["notification_overlay_fg"],
    )
    cfg["preview_overlay_bg"] = _coerce_color(
        cfg.get("preview_overlay_bg", d["preview_overlay_bg"]),
        d["preview_overlay_bg"],
    )
    cfg["preview_overlay_fg"] = _coerce_color(
        cfg.get("preview_overlay_fg", d["preview_overlay_fg"]),
        d["preview_overlay_fg"],
    )
    cfg["preview_overlay_text_bg"] = _coerce_color(
        cfg.get("preview_overlay_text_bg", d["preview_overlay_text_bg"]),
        d["preview_overlay_text_bg"],
    )
    cfg["status_indicator_color_idle"] = _coerce_color(
        cfg.get("status_indicator_color_idle", d["status_indicator_color_idle"]),
        d["status_indicator_color_idle"],
    )
    cfg["status_indicator_color_listening"] = _coerce_color(
        cfg.get("status_indicator_color_listening", d["status_indicator_color_listening"]),
        d["status_indicator_color_listening"],
    )
    cfg["status_indicator_color_recording"] = _coerce_color(
        cfg.get("status_indicator_color_recording", d["status_indicator_color_recording"]),
        d["status_indicator_color_recording"],
    )
    cfg["status_indicator_color_processing"] = _coerce_color(
        cfg.get("status_indicator_color_processing", d["status_indicator_color_processing"]),
        d["status_indicator_color_processing"],
    )
    return cfg

def _migrate_controller_binding(config):
    """Backfill modern controller binding fields from legacy config keys."""
    if not isinstance(config, dict):
        return config

    legacy_enabled = bool(config.get("controller_ptt", False))
    current_enabled = bool(config.get("controller_enabled", False))
    if "controller_enabled" not in config:
        config["controller_enabled"] = legacy_enabled
    elif legacy_enabled and not current_enabled:
        config["controller_enabled"] = True

    sequence_window_ms = config.get("controller_sequence_window_ms", 400)
    axis_threshold = config.get("controller_axis_threshold", 0.6)

    binding = config.get("controller_binding")
    if isinstance(binding, dict):
        style = str(binding.get("style", "single")).strip().lower() or "single"
        events = binding.get("events", [])
        if isinstance(events, str):
            events = [events]
        if not isinstance(events, list):
            events = []
        binding["style"] = style
        binding["events"] = [str(e).strip().lower() for e in events if str(e).strip()]
        try:
            legacy_button = int(config.get("controller_button", 4))
        except (TypeError, ValueError):
            legacy_button = 4
        if binding["events"] == ["button:4"] and legacy_button != 4:
            binding["events"] = [f"button:{legacy_button}"]
        if not binding["events"]:
            binding["events"] = [f"button:{legacy_button}"]
        binding["sequence_window_ms"] = int(binding.get("sequence_window_ms", sequence_window_ms))
        binding["axis_threshold"] = float(binding.get("axis_threshold", axis_threshold))
        binding["device_scope"] = binding.get("device_scope", "any_device")
        config["controller_binding"] = binding
        return config

    try:
        btn = int(config.get("controller_button", 4))
    except (TypeError, ValueError):
        btn = 4

    config["controller_binding"] = {
        "style": "single",
        "events": [f"button:{btn}"],
        "sequence_window_ms": int(sequence_window_ms),
        "axis_threshold": float(axis_threshold),
        "device_scope": "any_device",
    }
    return config


def _migrate_output_delivery(config):
    """Normalize output delivery settings and drop deprecated keys."""
    if not isinstance(config, dict):
        return config

    legacy_token_cap = config.get("token_cap_tokens")
    if legacy_token_cap is not None:
        config["output_token_limit"] = legacy_token_cap

    legacy_cap_message = config.get("token_cap_message")
    if legacy_cap_message:
        config["long_input_message"] = legacy_cap_message

    mode = str(config.get("send_mode", "review_first") or "review_first").strip().lower()
    if mode not in {"review_first", "auto_send"}:
        mode = "review_first"
    config["send_mode"] = mode
    config.pop("send_method", None)
    config.pop("live_output_mode", None)
    config.pop("token_cap_enabled", None)
    config.pop("token_cap_tokens", None)
    config.pop("token_cap_message", None)
    config.pop("final_transcription_pass", None)
    return config


def _apply_completion_token_alias(data):
    """Map the legacy ``output_token_limit`` onto ``max_completion_tokens`` for
    profiles saved before the two token concepts were split. Operates on the raw
    loaded dict *before* it is merged with defaults, so we can tell whether the
    new field was actually stored or is about to be filled in from defaults."""
    if not isinstance(data, dict):
        return data
    if "max_completion_tokens" not in data and "output_token_limit" in data:
        try:
            legacy = int(data["output_token_limit"])
            data["max_completion_tokens"] = max(512, min(4096, legacy))
        except (TypeError, ValueError):
            pass
    return data


def _profile_defaults():
    return {
        "hotkey": "f8",
        "force_stop_key": "",
        "manual_send_hotkey": "f9",
        "recording_mode": "toggle",
        "min_inter_key_delay": 0.08,
        "max_inter_key_delay": 0.16,
        "min_key_hold": 0.015,
        "max_key_hold": 0.035,
        "instant_typing": False,
        "chat_open_key": "",
        "voice_mute_key": "",
        "audio_ducking": False,
        "audio_ducking_level_percent": 18.0,
        "audio_ducking_fallback_return_percent": 100.0,
        "auto_submit": False,
        "sign_off_text": "",
        "send_mode": "review_first",
        "output_token_limit": 1100,  # legacy alias for max_completion_tokens
        "max_completion_tokens": 1600,
        "long_draft_warning_words": 1200,
        "llm_chunk_size": 750,
        "whisper_chunk_size": 1000,
        "draft_history_limit": 80,
        "long_input_message": "It looks like you have a lot to say. Give us a second.",
        "chat_close_action": "none",
        "review_tts_enabled": True,
        "review_tts_hotkey": "ctrl+shift+space",
        "review_tts_speed": 1.5,
        "review_tts_voice_hint": "english",
        "organic_formatting_enabled": True,
        "model_keep_llm_loaded": True,
        "model_keep_stt_loaded": True,
        "model_keep_tts_loaded": False,
        "llm_model_id": "gemma-3-4b-q4",
        "overlay_position": "Bottom-Right",
        "status_indicator_enabled": True,
        "status_indicator_flash_enabled": True,
        "status_indicator_color_idle": "#808080",
        "status_indicator_color_listening": "#14b8a6",
        "status_indicator_color_recording": "#ff3b30",
        "status_indicator_color_processing": "#fbbf24",
        "notification_overlay_enabled": True,
        "notification_overlay_position": "Bottom-Right",
        "notification_overlay_custom_x": 40,
        "notification_overlay_custom_y": 40,
        "notification_overlay_alpha": 0.85,
        "notification_overlay_bg": "#161616",
        "notification_overlay_fg": "#f2f2f2",
        "preview_overlay_enabled": True,
        "preview_overlay_position": "Bottom-Right",
        "preview_overlay_custom_x": 120,
        "preview_overlay_custom_y": 120,
        "preview_overlay_alpha": 0.95,
        "preview_overlay_bg": "#111111",
        "preview_overlay_fg": "#f2f2f2",
        "preview_overlay_text_bg": "#1d1d1d",
        "no_audio_min_duration_sec": 0.30,
        "no_audio_min_rms": 0.003,
        "no_audio_min_peak": 0.015,
        "llm_enabled": True,
        "current_preset": "True Janitor",
        "experience_preset": "custom",
        "true_gen": False,
        "use_gpu": True,
        "quantization": "int8",
        "model_size": "base.en",
        "controller_enabled": False,
        "controller_ptt": False,  # legacy compatibility key
        "controller_button": 4,   # legacy compatibility key
        "controller_sequence_window_ms": 400,
        "controller_axis_threshold": 0.6,
        "controller_binding": {
            "style": "single",
            "events": ["button:4"],
            "sequence_window_ms": 400,
            "axis_threshold": 0.6,
            "device_scope": "any_device",
        },
    }


def load_profile(profile_name="Default"):
    """
    Loads a specific profile. 
    If it doesn't exist, returns default settings (and creates the file for 'Default').
    """
    profiles_dir = get_profiles_dir()
    file_path = os.path.join(profiles_dir, f"{profile_name}.yaml")
    
    defaults = _profile_defaults()

    if not os.path.exists(file_path):
        if profile_name == "Default":
            # Check for legacy config.yaml migration
            legacy_config = os.path.join(get_user_data_path(), "config.yaml")
            if os.path.exists(legacy_config):
                try:
                    with open(legacy_config, "r") as f:
                        data = yaml.safe_load(f) or {}
                        _apply_completion_token_alias(data)
                        # Merge with defaults to ensure all keys exist
                        migrated = copy.deepcopy(defaults)
                        migrated.update(data)
                        _migrate_controller_binding(migrated)
                        _migrate_output_delivery(migrated)
                        _sanitize_profile_values(migrated, defaults)
                        save_profile("Default", migrated)
                        return migrated
                except Exception as e:
                    logging.error(f"Failed to migrate legacy config: {e}")

            migrated = copy.deepcopy(defaults)
            _migrate_controller_binding(migrated)
            _migrate_output_delivery(migrated)
            _sanitize_profile_values(migrated, defaults)
            save_profile("Default", migrated)
            return migrated
        return copy.deepcopy(defaults)

    try:
        with open(file_path, "r") as f:
            data = yaml.safe_load(f) or {}
            _apply_completion_token_alias(data)
            # Merge with defaults to ensure missing keys don't break things
            final_data = copy.deepcopy(defaults)
            final_data.update(data)
            _migrate_controller_binding(final_data)
            _migrate_output_delivery(final_data)
            _sanitize_profile_values(final_data, defaults)
            return final_data
    except Exception as e:
        logging.error(f"Failed to load profile {profile_name}: {e}")
        return defaults

def validate_profile_settings(data: dict):
    # 1. Check numeric ranges
    token_limit = data.get("output_token_limit")
    if token_limit is not None:
        try:
            val = int(token_limit)
        except (TypeError, ValueError):
            raise ValueError("Output Token Limit must be an integer.")
        if not (900 <= val <= 1200):
            raise ValueError("Output Token Limit must be between 900 and 1200.")

    max_completion = data.get("max_completion_tokens")
    if max_completion is not None:
        try:
            val = int(max_completion)
        except (TypeError, ValueError):
            raise ValueError("Max Completion Tokens must be an integer.")
        if not (512 <= val <= 4096):
            raise ValueError("Max Completion Tokens must be between 512 and 4096.")

    long_warning = data.get("long_draft_warning_words")
    if long_warning is not None:
        try:
            val = int(long_warning)
        except (TypeError, ValueError):
            raise ValueError("Long Draft Warning must be an integer.")
        if not (300 <= val <= 10000):
            raise ValueError("Long Draft Warning must be between 300 and 10000.")

    llm_chunk = data.get("llm_chunk_size")
    if llm_chunk is not None:
        try:
            val = int(llm_chunk)
        except (TypeError, ValueError):
            raise ValueError("LLM Chunk Size must be an integer.")
        if not (50 <= val <= 5000):
            raise ValueError("LLM Chunk Size must be between 50 and 5000.")

    whisper_chunk = data.get("whisper_chunk_size")
    if whisper_chunk is not None:
        try:
            val = int(whisper_chunk)
        except (TypeError, ValueError):
            raise ValueError("Whisper Chunk Size must be an integer.")
        if not (50 <= val <= 5000):
            raise ValueError("Whisper Chunk Size must be between 50 and 5000.")

    tts_speed = data.get("review_tts_speed")
    if tts_speed is not None:
        try:
            val = float(tts_speed)
        except (TypeError, ValueError):
            raise ValueError("TTS Speed must be a float.")
        if not (0.5 <= val <= 3.0):
            raise ValueError("TTS Speed must be between 0.5 and 3.0.")

    no_audio_duration = data.get("no_audio_min_duration_sec")
    if no_audio_duration is not None:
        try:
            val = float(no_audio_duration)
        except (TypeError, ValueError):
            raise ValueError("No-Audio Min Duration must be a float.")
        if not (0.0 <= val <= 30.0):
            raise ValueError("No-Audio Min Duration must be between 0.0 and 30.0.")

    no_audio_rms = data.get("no_audio_min_rms")
    if no_audio_rms is not None:
        try:
            val = float(no_audio_rms)
        except (TypeError, ValueError):
            raise ValueError("No-Audio Min RMS must be a float.")
        if not (0.0 <= val <= 1.0):
            raise ValueError("No-Audio Min RMS must be between 0.0 and 1.0.")

    no_audio_peak = data.get("no_audio_min_peak")
    if no_audio_peak is not None:
        try:
            val = float(no_audio_peak)
        except (TypeError, ValueError):
            raise ValueError("No-Audio Min Peak must be a float.")
        if not (0.0 <= val <= 1.0):
            raise ValueError("No-Audio Min Peak must be between 0.0 and 1.0.")

    # 2. Check for duplicate/conflicting hotkeys
    hotkey_fields = {
        "Recording Hotkey": data.get("hotkey"),
        "Emergency Stop": data.get("force_stop_key"),
        "Primary Action": data.get("manual_send_hotkey"),
        "Review TTS Hotkey": data.get("review_tts_hotkey"),
        "Open Chat Key": data.get("chat_open_key"),
        "Voice Mute Key": data.get("voice_mute_key"),
    }
    cleaned_keys = {}
    for name, key in hotkey_fields.items():
        if key:
            key_clean = str(key).strip().lower()
            if key_clean:
                cleaned_keys[name] = key_clean

    seen_keys = {}
    for name, key in cleaned_keys.items():
        if key in seen_keys:
            other_name = seen_keys[key]
            raise ValueError(f"Duplicate hotkey detected: '{key}' is assigned to both '{other_name}' and '{name}'.")
        seen_keys[key] = name

def save_profile(profile_name, data):
    """Saves data to a profile yaml file atomically with a backup."""
    profiles_dir = get_profiles_dir()
    file_path = os.path.join(profiles_dir, f"{profile_name}.yaml")
    
    try:
        payload = copy.deepcopy(data) if isinstance(data, dict) else {}
        defaults = _profile_defaults()
        _migrate_controller_binding(payload)
        _migrate_output_delivery(payload)
        _sanitize_profile_values(payload, defaults)
        
        # Validate values strictly
        validate_profile_settings(payload)
        
        # Create backup before writing
        if os.path.exists(file_path):
            backup_path = file_path + ".bak"
            try:
                shutil.copy2(file_path, backup_path)
            except Exception as e:
                logging.warning(f"Failed to create backup for {profile_name}: {e}")
                
        # Atomic save: write to temp first, load to verify, then replace
        temp_path = file_path + ".tmp"
        with open(temp_path, "w") as f:
            yaml.dump(payload, f)
        
        # Validation load check
        with open(temp_path, "r") as f:
            yaml.safe_load(f)
            
        os.replace(temp_path, file_path)
        logging.info(f"Saved profile atomically: {profile_name}")
    except Exception as e:
        logging.error(f"Failed to save profile {profile_name}: {e}")
        raise

def list_profiles():
    """Returns a list of all available profile names."""
    profiles_dir = get_profiles_dir()
    files = [f for f in os.listdir(profiles_dir) if f.endswith(".yaml")]
    names = [os.path.splitext(f)[0] for f in files]
    
    if "Default" not in names:
        load_profile("Default") # Forces creation
        names.append("Default")
        
    return sorted(names) # Return sorted list

def setup_logging(level=logging.DEBUG):
    """Redirects logs to debug.log in the User Data directory."""
    log_dir = get_user_data_path()
    log_file = os.path.join(log_dir, "debug.log")
    
    # Map string level to logging constant if needed
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.DEBUG)

    logging.basicConfig(
        level=level,
        filename=log_file,
        format='%(asctime)s - %(levelname)s - %(message)s',
        filemode='a'
    )
    
    # Catch uncaught exceptions
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logging.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception
    logging.info(f"App started.")
    logging.info(f"App Path (Read-Only): {get_app_path()}")
    logging.info(f"User Data Path (Writable): {get_user_data_path()}")
