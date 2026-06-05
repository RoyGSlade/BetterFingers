import ctypes
import json
import logging
import os
import re
import shutil
import sys
import threading
import time

import pystray
import tkinter as tk
from tkinter import messagebox
from PIL import Image

from audio_gate import should_block_for_no_audio
from clipboard_capture import capture_selection_text_with_restore
from injector import InputInjector
from llm_engine import get_engine, get_engine_if_initialized
from notification_overlay import NotificationOverlay
from overlay import Overlay
from preview_overlay import PreviewOverlay
from recorder import AudioRecorder, RecordingResult
from settings import SettingsWindow
from splash import SplashWindow
from text_formatter import format_text
from tts_engine import ReviewTTSEngine
from transcriber import (
    Transcriber,
    SUPPORTED_MODEL_SIZES,
    download_whisper_model,
    list_cached_models,
    remove_cached_model,
)
from hotkey_manager import HotkeyManager
from utils import (
    check_first_run,
    get_app_path,
    get_draft_history_path,
    get_last_active_profile,
    get_user_data_path,
    list_profiles,
    load_profile,
    register_launch_and_should_show_donation,
    save_profile,
    set_last_active_profile,
    setup_logging,
)


def load_icon(filename):
    path = os.path.join(get_app_path(), "images", filename)
    try:
        if not os.path.exists(path):
            logging.error(f"Icon missing: {path}")
            return Image.new("RGB", (64, 64), (255, 0, 0))
        return Image.open(path)
    except Exception as exc:
        logging.error(f"Failed to load icon {filename}: {exc}")
        return Image.new("RGB", (64, 64), (255, 0, 0))


ICON_IDLE = None
ICON_RECORDING = None
ICON_PROCESSING = None

RE_WORD_TOKENS = re.compile(r"[a-z0-9']+")
RE_TOKEN_UNITS = re.compile(r"\S+")
RE_PARAGRAPH_SPLIT = re.compile(r"\n{2,}")
RE_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _dedupe_preserve_order(values):
    seen = set()
    ordered = []
    for raw in values or []:
        value = str(raw or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(value)
    return ordered


def prefetch_runtime_assets(
    llm_model_ids=None,
    whisper_models=None,
    include_tts=False,
    prefer_gpu=True,
    tts_voice_hint="english",
):
    """
    Download/cache selected runtime assets without launching the desktop UI.

    Returns a dict with per-component results and an aggregate `ok` flag.
    """
    results = {"ok": True, "llm": [], "whisper": [], "tts": None}

    llm_targets = _dedupe_preserve_order(llm_model_ids)
    if llm_targets:
        try:
            from model_manager import AVAILABLE_MODELS, check_and_download_resources
        except Exception as exc:
            logging.error("Unable to import model manager for LLM prefetch: %s", exc)
            results["ok"] = False
            for model_id in llm_targets:
                results["llm"].append(
                    {"model_id": model_id, "ok": False, "message": f"LLM prefetch unavailable: {exc}"}
                )
        else:
            for model_id in llm_targets:
                target = str(model_id or "").strip()
                if target not in AVAILABLE_MODELS:
                    msg = f"Unsupported LLM model '{target}'."
                    logging.warning(msg)
                    results["ok"] = False
                    results["llm"].append({"model_id": target, "ok": False, "message": msg})
                    continue
                try:
                    row = check_and_download_resources(target)
                except Exception as exc:
                    msg = f"LLM prefetch failed for '{target}': {exc}"
                    logging.error(msg)
                    results["ok"] = False
                    results["llm"].append({"model_id": target, "ok": False, "message": msg})
                    continue
                ok = bool(isinstance(row, dict) and row.get("ok", False))
                msg = (
                    str(row.get("message", "")).strip()
                    if isinstance(row, dict)
                    else f"Unexpected LLM prefetch response for '{target}'."
                )
                if not ok:
                    results["ok"] = False
                logging.info("LLM prefetch [%s]: %s", target, msg)
                results["llm"].append({"model_id": target, "ok": ok, "message": msg})

    whisper_targets = _dedupe_preserve_order(whisper_models)
    for model_size in whisper_targets:
        target = str(model_size or "").strip()
        if target not in SUPPORTED_MODEL_SIZES:
            msg = f"Unsupported Whisper model '{target}'."
            logging.warning(msg)
            results["ok"] = False
            results["whisper"].append({"model_size": target, "ok": False, "message": msg})
            continue
        try:
            row = download_whisper_model(target, prefer_gpu=bool(prefer_gpu))
        except Exception as exc:
            msg = f"Whisper prefetch failed for '{target}': {exc}"
            logging.error(msg)
            results["ok"] = False
            results["whisper"].append({"model_size": target, "ok": False, "message": msg})
            continue
        ok = bool(isinstance(row, dict) and row.get("ok", False))
        msg = (
            str(row.get("message", "")).strip()
            if isinstance(row, dict)
            else f"Unexpected Whisper prefetch response for '{target}'."
        )
        if not ok:
            results["ok"] = False
        logging.info("Whisper prefetch [%s]: %s", target, msg)
        results["whisper"].append({"model_size": target, "ok": ok, "message": msg})

    if include_tts:
        engine = None
        try:
            engine = ReviewTTSEngine()
            status = engine.ensure_loaded(voice_hint=(tts_voice_hint or "english"))
            ok = bool(status.get("ok", False))
            msg = str(status.get("message", "")).strip() or "TTS prefetch completed."
            if not ok:
                results["ok"] = False
            logging.info("TTS prefetch: %s", msg)
            results["tts"] = {"ok": ok, "message": msg, "backend": status.get("backend", "none")}
        except Exception as exc:
            msg = f"TTS prefetch failed: {exc}"
            logging.error(msg)
            results["ok"] = False
            results["tts"] = {"ok": False, "message": msg, "backend": "none"}
        finally:
            try:
                if engine is not None:
                    engine.shutdown()
            except Exception:
                pass

    return results


class App:
    @staticmethod
    def _coerce_send_mode(value):
        mode = str(value or "review_first").strip().lower()
        if mode in {"review_first", "auto_send"}:
            return mode
        return "review_first"

    @staticmethod
    def _coerce_draft_history_limit(value):
        try:
            parsed = int(value)
        except Exception:
            parsed = 80
        return max(10, min(500, parsed))

    def __init__(self, startup_profile=None):
        self.icon = None
        self.root = None
        self.running = True
        self.active_profile = startup_profile or "Default"
        self._startup_profile_override = startup_profile

        self.recorder = None
        self.transcriber = None
        self.injector = None
        self.manager = None
        self.settings_window = None

        self.overlay = None
        self.notification_overlay = None
        self.preview_overlay = None
        self.tts_engine = None
        self._overlay_hidden_for_settings = False

        self.pipeline_state = "idle"
        self.draft_queue = []
        self.next_draft_id = 1
        self.pending_manual_send_ids = []

        self.current_preset = "True Janitor"
        self.llm_model_id = "gemma-3-4b-q4"
        self.llm_enabled = True
        self.true_gen = False
        self.use_gpu = True

        self.send_mode = "review_first"
        self.manual_send_hotkey = "f9"
        self.chat_close_action = "none"
        self.draft_history_limit = 80
        self.notification_overlay_enabled = True
        self.review_tts_enabled = True
        self.review_tts_hotkey = "ctrl+shift+space"
        self.review_tts_speed = 1.5
        self.review_tts_voice_hint = "english"

        self.model_keep_llm_loaded = True
        self.model_keep_stt_loaded = True
        self.model_keep_tts_loaded = False
        self.output_token_limit = 1100
        self.organic_formatting_enabled = True
        self.long_input_message = "It looks like you have a lot to say. Give us a second."
        self._exit_requested = False

    @staticmethod
    def _resolve_startup_profile():
        default_profile = "Default"
        try:
            available_profiles = set(list_profiles())
            if default_profile not in available_profiles:
                available_profiles.add(default_profile)
            candidate = get_last_active_profile(default=default_profile)
            if candidate in available_profiles:
                return candidate
        except Exception as exc:
            logging.debug("Failed to resolve startup profile from app state: %s", exc)
        return default_profile

    def bootstrap_config(self):
        user_config = os.path.join(get_user_data_path(), "config.yaml")
        if os.path.exists(user_config):
            return
        default_config = os.path.join(get_app_path(), "config.yaml")
        if not os.path.exists(default_config):
            logging.error("Default config.yaml not found in app path.")
            return
        try:
            shutil.copy(default_config, user_config)
        except Exception as exc:
            logging.error(f"Failed to bootstrap config.yaml: {exc}")

    def _safe_after(self, delay_ms, callback):
        if not self.root:
            return
        try:
            self.root.after(delay_ms, callback)
        except Exception as exc:
            logging.debug(f"Skipping UI callback during shutdown: {exc}")

    @staticmethod
    def _normalize_text(value):
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        try:
            return str(value).strip()
        except Exception:
            return ""

    @staticmethod
    def _word_tokens(value):
        return RE_WORD_TOKENS.findall(str(value or "").lower())

    @staticmethod
    def _token_units(value):
        return RE_TOKEN_UNITS.findall(str(value or ""))

    @classmethod
    def _token_count(cls, value):
        return len(cls._token_units(value))

    @classmethod
    def _split_text_by_token_limit(cls, text, token_limit):
        clean = cls._normalize_text(text)
        if not clean:
            return []

        limit = max(1, int(token_limit or 1))
        if cls._token_count(clean) <= limit:
            return [clean]

        paragraphs = [piece.strip() for piece in RE_PARAGRAPH_SPLIT.split(clean) if piece.strip()]
        if not paragraphs:
            paragraphs = [clean]

        units = []
        for paragraph in paragraphs:
            sentences = [s.strip() for s in RE_SENTENCE_SPLIT.split(paragraph) if s.strip()]
            if sentences:
                units.extend(sentences)
            else:
                units.append(paragraph)

        chunks = []
        current_units = []
        current_count = 0

        def _flush_current():
            nonlocal current_units, current_count
            if not current_units:
                return
            chunk = " ".join(current_units).strip()
            if chunk:
                chunks.append(chunk)
            current_units = []
            current_count = 0

        for unit in units:
            unit_count = cls._token_count(unit)
            if unit_count <= 0:
                continue

            if unit_count > limit:
                _flush_current()
                words = cls._token_units(unit)
                while words:
                    take = words[:limit]
                    words = words[limit:]
                    part = " ".join(take).strip()
                    if part:
                        chunks.append(part)
                continue

            if current_units and (current_count + unit_count) > limit:
                _flush_current()

            current_units.append(unit)
            current_count += unit_count

        _flush_current()
        return chunks or [clean]

    @classmethod
    def _should_reject_janitor_output(cls, source_text, candidate_text):
        """
        Guardrail for True Janitor mode:
        reject outputs that look like assistant-style responses instead of rewrites.
        """
        source = cls._normalize_text(source_text)
        candidate = cls._normalize_text(candidate_text)
        if not source or not candidate:
            return False

        source_tokens = cls._word_tokens(source)
        candidate_tokens = cls._word_tokens(candidate)
        if not source_tokens or not candidate_tokens:
            return False

        source_set = set(source_tokens)
        candidate_set = set(candidate_tokens)
        overlap = len(source_set & candidate_set)
        source_coverage = overlap / max(1, len(source_set))
        output_coverage = overlap / max(1, len(candidate_set))
        length_ratio = len(candidate_tokens) / max(1, len(source_tokens))

        source_lower = source.lower()
        candidate_lower = candidate.lower()
        suspicious_prefixes = (
            "i offer",
            "i can",
            "i will",
            "as an ai",
            "here's",
            "here is",
            "my offer",
        )
        if candidate_lower.startswith(suspicious_prefixes) and not source_lower.startswith(suspicious_prefixes):
            return True

        if source_coverage < 0.45 and output_coverage < 0.45 and length_ratio > 1.15:
            return True
        if source_coverage < 0.35 and length_ratio > 1.0:
            return True
        return False

    def _resolve_final_text(self, transcript):
        base_text = self._normalize_text(transcript)
        if not base_text:
            return ""

        # Direct transcript mode: deterministic fallback when LLM is disabled.
        if not self.llm_enabled:
            return base_text

        try:
            processed = get_engine().process_fast_lane(
                base_text,
                preset_name=self.current_preset,
                true_gen=self.true_gen,
                max_output_tokens=self.output_token_limit,
            )
            processed_text = self._normalize_text(processed)
            if not processed_text:
                return base_text

            if (
                str(self.current_preset or "").strip().lower() == "true janitor"
                and self._should_reject_janitor_output(base_text, processed_text)
            ):
                logging.warning(
                    "Discarding suspicious True Janitor output and falling back to transcript. "
                    "input='%s' output='%s'",
                    base_text[:120],
                    processed_text[:120],
                )
                return base_text

            return processed_text
        except Exception as exc:
            logging.error(f"Fast lane failed; falling back to transcript: {exc}")
            return base_text

    def setup(self):
        logging.info("Initializing BetterFingers...")

        global ICON_IDLE, ICON_RECORDING, ICON_PROCESSING
        ICON_IDLE = load_icon("InactiveTray.png")
        ICON_RECORDING = load_icon("activetray.png")
        ICON_PROCESSING = load_icon("activetray.png")

        self.root = tk.Tk()
        self.root.withdraw()

        first_run = check_first_run()

        self.bootstrap_config()

        if not self._startup_profile_override:
            self.active_profile = self._resolve_startup_profile()
        startup_cfg = load_profile(self.active_profile)
        self.model_keep_llm_loaded = bool(startup_cfg.get("model_keep_llm_loaded", True))
        self.model_keep_stt_loaded = bool(startup_cfg.get("model_keep_stt_loaded", True))
        self.model_keep_tts_loaded = bool(startup_cfg.get("model_keep_tts_loaded", False))
        self.use_gpu = bool(startup_cfg.get("use_gpu", True))

        self.recorder = AudioRecorder(sample_rate=16000)
        self.injector = InputInjector()
        self.tts_engine = ReviewTTSEngine()
        self.tts_engine.set_prefer_gpu(self.use_gpu)
        try:
            self.transcriber = Transcriber(
                profile_name=self.active_profile,
                preload=self.model_keep_stt_loaded,
            )
        except Exception as exc:
            logging.critical(f"FATAL: Could not load transcriber: {exc}")
            sys.exit(1)

        self.manager = HotkeyManager(
            recorder=self.recorder,
            on_recording_complete_callback=self.on_recording_complete,
            on_recording_start_callback=self.on_recording_start,
            on_force_stop_callback=self.on_force_stop,
            on_manual_send_callback=self.on_manual_send_hotkey,
            on_review_tts_callback=self.on_review_tts_hotkey,
        )

        self.settings_window = SettingsWindow(
            self.root,
            self.manager,
            self.on_settings_saved,
            on_tts_preview_callback=self.on_settings_tts_preview,
            on_tts_stop_callback=self.on_settings_tts_stop,
            get_tts_voice_options_callback=self.get_tts_voice_options,
            get_whisper_download_status_callback=self.get_whisper_download_status,
            on_download_whisper_model_callback=self.on_settings_download_whisper_model,
            on_test_whisper_model_callback=self.on_settings_test_whisper_model,
            on_uninstall_whisper_model_callback=self.on_settings_uninstall_whisper_model,
            on_show_callback=self._on_settings_show,
            on_hide_callback=self._on_settings_hide,
        )
        self.overlay = Overlay(self.root)
        self.notification_overlay = NotificationOverlay(self.root, on_position_changed=self.on_notification_dragged)
        self.preview_overlay = PreviewOverlay(
            self.root,
            on_accept=self.on_preview_accept,
            on_decline=self.on_preview_decline,
            on_tts=self.on_preview_tts,
            on_rewrite=self.on_preview_rewrite,
            on_position_changed=self.on_preview_dragged,
        )
        show_donation_prompt = register_launch_and_should_show_donation(threshold=5)

        self._safe_after(
            0,
            lambda: SplashWindow(
                self.root,
                on_open_settings=lambda: self._show_settings(force_tour=first_run),
                first_run=first_run,
                auto_close_ms=0,
                auto_open_settings_ms=350 if first_run else 0,
                show_donation_prompt=show_donation_prompt,
                donation_url="https://ko-fi.com/democratizegm",
            ),
        )

        self._apply_runtime_settings(self.active_profile)

        menu = pystray.Menu(
            pystray.MenuItem("Settings", self.open_settings, default=True),
            pystray.MenuItem("Exit", self.on_exit),
        )
        self.icon = pystray.Icon("BetterFingers", ICON_IDLE, "BetterFingers: Ready", menu)

    def _apply_runtime_settings(self, profile_name):
        resolved_profile = str(profile_name or "Default").strip() or "Default"
        try:
            available_profiles = set(list_profiles())
            if resolved_profile not in available_profiles:
                resolved_profile = "Default"
        except Exception:
            if not resolved_profile:
                resolved_profile = "Default"
        self.active_profile = resolved_profile
        try:
            set_last_active_profile(self.active_profile)
        except Exception as exc:
            logging.debug("Failed to persist last active profile '%s': %s", self.active_profile, exc)

        config = load_profile(self.active_profile)
        self.injector.reload_config(self.active_profile)

        self.current_preset = config.get("current_preset", "True Janitor")
        self.llm_model_id = str(config.get("llm_model_id", "gemma-3-4b-q4") or "gemma-3-4b-q4").strip()
        self.llm_enabled = bool(config.get("llm_enabled", True))
        self.true_gen = bool(config.get("true_gen", False))

        raw_send_mode = config.get("send_mode", "review_first")
        self.send_mode = self._coerce_send_mode(raw_send_mode)
        if str(raw_send_mode).strip().lower() != self.send_mode:
            logging.info(
                "Unsupported send_mode '%s' in profile '%s'; using '%s'.",
                raw_send_mode,
                self.active_profile,
                self.send_mode,
            )
        self.manual_send_hotkey = (config.get("manual_send_hotkey", "f9") or "").strip()
        self.chat_close_action = config.get("chat_close_action", "none")
        self.draft_history_limit = self._coerce_draft_history_limit(
            config.get("draft_history_limit", 80)
        )
        self.notification_overlay_enabled = bool(config.get("notification_overlay_enabled", True))
        self.review_tts_enabled = bool(config.get("review_tts_enabled", True))
        self.review_tts_hotkey = (config.get("review_tts_hotkey", "ctrl+shift+space") or "").strip()
        self.review_tts_speed = float(config.get("review_tts_speed", 1.5))
        self.review_tts_voice_hint = (
            config.get("review_tts_voice_hint", "english") or "english"
        ).strip() or "english"
        self.use_gpu = bool(config.get("use_gpu", True))

        self.model_keep_llm_loaded = bool(config.get("model_keep_llm_loaded", True))
        self.model_keep_stt_loaded = bool(config.get("model_keep_stt_loaded", True))
        self.model_keep_tts_loaded = bool(config.get("model_keep_tts_loaded", False))
        self.organic_formatting_enabled = bool(config.get("organic_formatting_enabled", True))
        try:
            requested_limit = int(config.get("output_token_limit", 1100))
            self.output_token_limit = max(900, min(1200, requested_limit))
        except Exception:
            self.output_token_limit = 1100
        self.long_input_message = (
            config.get("long_input_message", "It looks like you have a lot to say. Give us a second.")
            or "It looks like you have a lot to say. Give us a second."
        ).strip()

        if self.tts_engine:
            try:
                self.tts_engine.set_prefer_gpu(self.use_gpu)
                self.tts_engine.set_keep_loaded(self.model_keep_tts_loaded)
            except Exception as exc:
                logging.error(f"Failed to apply TTS runtime preference: {exc}")

        if self.transcriber:
            try:
                self.transcriber.reload_profile(profile_name=self.active_profile, preload=False)
            except Exception as exc:
                logging.error(f"Failed to reload transcriber profile: {exc}")
        if self.transcriber and not self.model_keep_stt_loaded:
            try:
                self.transcriber.unload()
            except Exception as exc:
                logging.error(f"Failed to unload STT model: {exc}")

        if not self.model_keep_llm_loaded:
            try:
                engine = get_engine_if_initialized()
                if engine:
                    engine.set_model_id(self.llm_model_id)
                    engine.shutdown()
            except Exception as exc:
                logging.error(f"Failed to unload LLM model: {exc}")
        else:
            try:
                engine = get_engine_if_initialized()
                if engine:
                    previous_model = str(getattr(engine, "model_id", "") or "").strip()
                    engine.set_model_id(self.llm_model_id)
                    if previous_model and previous_model != self.llm_model_id:
                        engine.reload_model()
            except Exception as exc:
                logging.error("Failed to apply selected LLM model '%s': %s", self.llm_model_id, exc)

        if self.tts_engine and not self.model_keep_tts_loaded:
            try:
                self.tts_engine.unload()
            except Exception as exc:
                logging.error(f"Failed to unload TTS model: {exc}")

        if self.model_keep_llm_loaded:
            threading.Thread(target=self._warm_load_llm, daemon=True).start()
        if self.model_keep_stt_loaded and self.transcriber:
            threading.Thread(target=self._warm_load_stt, daemon=True).start()
        if self.model_keep_tts_loaded and self.tts_engine:
            threading.Thread(target=self._warm_load_tts, daemon=True).start()

        if self.overlay:
            try:
                self.overlay.apply_config(config)
            except Exception:
                self.overlay.update_position(config.get("overlay_position", "Bottom-Right"))
        if self.notification_overlay:
            self.notification_overlay.apply_config(config)
        if self.preview_overlay:
            self.preview_overlay.apply_config(config)

    def _warm_load_llm(self):
        try:
            engine = get_engine()
            current_model = str(getattr(engine, "model_id", "") or "").strip()
            if current_model != self.llm_model_id:
                engine.set_model_id(self.llm_model_id)
                engine.reload_model()
        except Exception as exc:
            logging.error(f"Background LLM init failed: {exc}")

    def _warm_load_stt(self):
        if not self.transcriber:
            return
        try:
            self.transcriber.ensure_loaded()
        except Exception as exc:
            logging.error(f"Background STT init failed: {exc}")

    def _warm_load_tts(self):
        if not self.tts_engine:
            return
        try:
            self.tts_engine.ensure_loaded(voice_hint=self.review_tts_voice_hint)
        except Exception as exc:
            logging.error(f"Background TTS init failed: {exc}")

    def _on_settings_show(self):
        """Called when settings panel opens."""
        if self.overlay:
            try:
                self._overlay_hidden_for_settings = bool(self.overlay.root.winfo_viewable())
            except Exception:
                self._overlay_hidden_for_settings = True
            try:
                self.overlay.stop_transparency_refresh()
            except Exception:
                pass
            try:
                self.overlay.root.withdraw()
            except Exception as e:
                logging.debug("Failed to hide status overlay during settings: %s", e)

    def _on_settings_hide(self):
        """Called when settings panel closes."""
        if self._exit_requested:
            return
        if self.overlay:
            try:
                overlay_root = getattr(self.overlay, "root", None)
                if overlay_root is None or not overlay_root.winfo_exists():
                    return
                self.overlay.stop_transparency_refresh()
                # Reapply transparency one more time after Flet closes
                self.overlay._setup_windows_transparency()
                if self._overlay_hidden_for_settings:
                    desired_state = self.pipeline_state if self.pipeline_state in {
                        "recording",
                        "processing",
                        "listening",
                    } else "idle"
                    self.overlay.set_state(desired_state)
            except Exception as e:
                logging.debug("Failed to restore status overlay after settings: %s", e)
            finally:
                self._overlay_hidden_for_settings = False

    def _show_settings(self, force_tour=False):
        if not self.root:
            return

        def _show():
            if self.pipeline_state == "recording":
                message = "Finish or stop recording before opening Settings."
                if self.notification_overlay and self.notification_overlay_enabled:
                    try:
                        self.notification_overlay.show_message(message, 2500)
                    except Exception:
                        pass
                logging.info("Blocked settings open while pipeline state is '%s'.", self.pipeline_state)
                return

            if not self.settings_window:
                return
            try:
                self.settings_window.show(start_tour=bool(force_tour))
                return
            except TypeError:
                pass

            if force_tour and hasattr(self.settings_window, "request_tour_on_next_show"):
                try:
                    self.settings_window.request_tour_on_next_show()
                except Exception:
                    pass
            self.settings_window.show()

        self._safe_after(0, _show)

    def open_settings(self, icon=None, item=None):
        del icon, item
        self._show_settings(force_tour=False)

    def on_settings_saved(self):
        active_profile = self.settings_window.current_profile
        logging.info(f"Settings saved. Active profile = {active_profile}")
        self._apply_runtime_settings(active_profile)
        try:
            self.manager.update_config(self.active_profile)
        except Exception as exc:
            logging.error(f"Failed to update hotkey manager config: {exc}")

    def get_tts_voice_options(self):
        options = []
        if self.tts_engine:
            try:
                options = list(self.tts_engine.get_voice_hints() or [])
            except Exception as exc:
                logging.error(f"Failed to resolve TTS voice options: {exc}")
                options = []
        if not options:
            options = ReviewTTSEngine.default_voice_hints()
        return options

    def get_whisper_download_status(self):
        model_order = list(SUPPORTED_MODEL_SIZES)
        known = {
            model_size: {
                "model_size": model_size,
                "installed": False,
                "size_bytes": 0,
            }
            for model_size in model_order
        }
        summary = "No Whisper models found in cache."

        try:
            cache_rows = list_cached_models()
            for row in cache_rows:
                model_size = str(row.get("model_size", "")).strip()
                if not model_size:
                    continue
                if model_size not in known:
                    known[model_size] = {
                        "model_size": model_size,
                        "installed": False,
                        "size_bytes": 0,
                    }
                    model_order.append(model_size)
                known[model_size]["installed"] = bool(row.get("installed", False))
                known[model_size]["size_bytes"] = int(row.get("size_bytes", 0) or 0)
            installed = [entry for entry in model_order if known[entry]["installed"]]
            if installed:
                summary = f"Installed: {', '.join(installed)}"
        except Exception as exc:
            logging.error("Failed to inspect Whisper cache: %s", exc)
            summary = f"Failed to inspect cache: {exc}"

        return {
            "ok": True,
            "models": [known[name] for name in model_order],
            "summary": summary,
        }

    def on_settings_test_whisper_model(self, model_size):
        selected = str(model_size or "").strip() or "base.en"
        if selected not in SUPPORTED_MODEL_SIZES:
            return {"ok": False, "message": f"Unsupported Whisper model: {selected}"}

        probe = None
        try:
            probe = Transcriber(profile_name=self.active_profile, preload=False)
            probe.model_size = selected
            probe.prefer_gpu = bool(self.use_gpu)
            if not probe.ensure_loaded():
                return {"ok": False, "message": f"Failed to load Whisper '{selected}'."}
            return {
                "ok": True,
                "message": f"Whisper '{selected}' loaded successfully.",
            }
        except Exception as exc:
            logging.error("Whisper smoke test failed for '%s': %s", selected, exc)
            return {"ok": False, "message": f"Whisper test failed: {exc}"}
        finally:
            if probe is not None:
                try:
                    probe.unload()
                except Exception:
                    pass

    def on_settings_download_whisper_model(self, model_size, progress_callback=None):
        selected = str(model_size or "").strip() or "base.en"
        if selected not in SUPPORTED_MODEL_SIZES:
            return {"ok": False, "message": f"Unsupported Whisper model: {selected}"}
        try:
            return download_whisper_model(
                selected,
                prefer_gpu=bool(self.use_gpu),
                progress_callback=progress_callback,
            )
        except Exception as exc:
            logging.error("Whisper download failed for '%s': %s", selected, exc)
            return {"ok": False, "message": f"Whisper download failed: {exc}"}

    def on_settings_uninstall_whisper_model(self, model_size):
        selected = str(model_size or "").strip() or "base.en"
        if selected not in SUPPORTED_MODEL_SIZES:
            return {"ok": False, "message": f"Unsupported Whisper model: {selected}"}

        try:
            if self.transcriber and self.transcriber.model_size == selected:
                self.transcriber.unload()
        except Exception as exc:
            logging.debug("Failed unloading active transcriber before uninstall: %s", exc)

        try:
            result = remove_cached_model(selected)
            message = str(result.get("message", "")).strip() or f"Whisper '{selected}' uninstall completed."
            return {"ok": bool(result.get("ok", False)), "message": message}
        except Exception as exc:
            logging.error("Failed uninstalling Whisper model '%s': %s", selected, exc)
            return {"ok": False, "message": f"Uninstall failed: {exc}"}

    def on_settings_tts_preview(self, text, speed, voice_hint):
        phrase = (text or "").strip()
        if not phrase:
            return {
                "ok": False,
                "backend": "none",
                "fallback": False,
                "message": "No sample text provided.",
            }

        if not self.tts_engine:
            return {
                "ok": False,
                "backend": "none",
                "fallback": False,
                "message": "TTS engine is not available.",
            }

        safe_speed = max(0.5, min(3.0, float(speed)))
        hint = (voice_hint or "english").strip() or "english"
        result = self.tts_engine.speak(phrase, speed=safe_speed, voice_hint=hint)
        if result.get("fallback", False):
            if self.notification_overlay and self.notification_overlay_enabled:
                self.notification_overlay.show_message(
                    "Kokoro unavailable. Using Windows voice fallback.",
                    2200,
                )
        return result

    def on_settings_tts_stop(self):
        if self.tts_engine:
            self.tts_engine.stop_current()

    def on_notification_dragged(self, x, y):
        cfg = load_profile(self.active_profile)
        cfg["notification_overlay_position"] = "Custom"
        cfg["notification_overlay_custom_x"] = int(x)
        cfg["notification_overlay_custom_y"] = int(y)
        save_profile(self.active_profile, cfg)

    def on_preview_dragged(self, x, y):
        cfg = load_profile(self.active_profile)
        cfg["preview_overlay_position"] = "Custom"
        cfg["preview_overlay_custom_x"] = int(x)
        cfg["preview_overlay_custom_y"] = int(y)
        save_profile(self.active_profile, cfg)

    def on_force_stop(self):
        logging.warning("Force stop requested.")
        try:
            self.manager.request_stop(reason="force_stop")
        except Exception:
            pass
        if self.injector:
            self.injector.stop_typing()
            try:
                self.injector.release_mute_key()
            except Exception:
                pass
        if self.tts_engine:
            try:
                self.tts_engine.stop_current()
            except Exception:
                pass
        if self.overlay:
            self._safe_after(0, lambda: self.overlay.set_state("error"))
            self._safe_after(1500, lambda: self.overlay.set_state("idle"))
        self.pipeline_state = "idle"
        self._release_transient_models(include_tts=True)

    def on_recording_start(self):
        self.pipeline_state = "recording"

        if self.injector:
            try:
                self.injector.hold_mute_key()
            except Exception as exc:
                logging.error(f"Mute hold failed: {exc}")

        if self.overlay:
            self._safe_after(0, lambda: self.overlay.set_state("recording"))
        if self.icon and ICON_RECORDING:
            self.icon.icon = ICON_RECORDING
            self.icon.title = "BetterFingers: Recording..."

        if self.preview_overlay:
            self._safe_after(0, self.preview_overlay.hide)

    def on_recording_complete(self, recording_result: RecordingResult):
        self.pipeline_state = "processing"

        if self.injector:
            try:
                self.injector.release_mute_key()
            except Exception as exc:
                logging.error(f"Mute release failed: {exc}")

        if self.overlay:
            self._safe_after(0, lambda: self.overlay.set_state("processing"))
        if self.icon and ICON_PROCESSING:
            self.icon.icon = ICON_PROCESSING
            self.icon.title = "BetterFingers: Processing..."

        worker = threading.Thread(target=self.process_and_route, args=(recording_result,), daemon=True)
        worker.start()

    def process_and_route(self, recording_result: RecordingResult):
        try:
            transcript = ""
            if recording_result.audio_data.size > 0:
                transcript = self._normalize_text(
                    self.transcriber.transcribe(recording_result.audio_data)
                )

            blocked, reasons = should_block_for_no_audio(
                recording_result,
                transcript,
                load_profile(self.active_profile),
            )
            if blocked:
                logging.info(f"No-audio gate blocked downstream processing: {reasons}")
                self.pipeline_state = "idle"
                if self.notification_overlay and self.notification_overlay_enabled:
                    self._safe_after(
                        0,
                        lambda: self.notification_overlay.show_message("No sound was recorded.", 2400),
                    )
                return

            final_text = self._resolve_final_text(transcript)
            if not final_text:
                self.pipeline_state = "idle"
                if self.notification_overlay and self.notification_overlay_enabled:
                    self._safe_after(
                        0, lambda: self.notification_overlay.show_message("No text detected.", 2000)
                    )
                return
            if self.organic_formatting_enabled:
                try:
                    final_text = format_text(final_text)
                except Exception as exc:
                    logging.error("Organic formatting failed; continuing without formatting: %s", exc)

            self.last_final_text = final_text
            output_chunks = self._split_text_by_token_limit(final_text, self.output_token_limit)
            if not output_chunks:
                self.pipeline_state = "idle"
                return

            if len(output_chunks) > 1:
                logging.info(
                    "Long input detected (%d tokens). Split into %d chunk(s) at limit=%d.",
                    self._token_count(final_text),
                    len(output_chunks),
                    self.output_token_limit,
                )
                if self.notification_overlay and self.notification_overlay_enabled:
                    notice = str(self.long_input_message or "").strip() or "It looks like you have a lot to say. Give us a second."
                    self._safe_after(
                        0,
                        lambda msg=notice: self.notification_overlay.show_message(msg, 3000),
                    )

            for index, chunk in enumerate(output_chunks, start=1):
                self._route_output(
                    chunk,
                    transcript,
                    recording_result.stop_reason,
                    part_index=index,
                    part_total=len(output_chunks),
                )
        except Exception as exc:
            logging.error(f"Processing pipeline failed: {exc}")
        finally:
            self._release_transient_models(include_tts=False)
            if self.icon and ICON_IDLE:
                self.icon.icon = ICON_IDLE
                self.icon.title = "BetterFingers: Ready"
            if self.overlay:
                self._safe_after(0, lambda: self.overlay.set_state("idle"))

    def _release_transient_models(self, include_tts=False):
        if self.transcriber and not self.model_keep_stt_loaded:
            try:
                self.transcriber.unload()
            except Exception as exc:
                logging.error(f"Failed to unload STT model after request: {exc}")

        if not self.model_keep_llm_loaded:
            try:
                engine = get_engine_if_initialized()
                if engine:
                    engine.shutdown()
            except Exception as exc:
                logging.error(f"Failed to unload LLM model after request: {exc}")

        if include_tts and self.tts_engine and not self.model_keep_tts_loaded:
            try:
                self.tts_engine.unload()
            except Exception as exc:
                logging.error(f"Failed to unload TTS model after request: {exc}")

    def _route_output(self, final_text, raw_text, stop_reason, part_index=1, part_total=1):
        draft = self._create_draft(
            final_text,
            raw_text,
            stop_reason,
            part_index=part_index,
            part_total=part_total,
        )

        if self.send_mode == "auto_send":
            self.pipeline_state = "accepted"
            self._dispatch_send(draft, final_text, open_chat=(part_index == 1))
            return

        # review_first default
        if self.preview_overlay and self.preview_overlay.enabled:
            shown = self._show_next_review_draft()
            if shown:
                self.pipeline_state = "review_pending"
            else:
                self.pipeline_state = "queued"
                if self.notification_overlay and self.notification_overlay_enabled:
                    self._safe_after(
                        0,
                        lambda did=draft["id"]: self.notification_overlay.show_message(
                            f"Draft #{did} queued while another review is open.",
                            2200,
                        ),
                    )
        else:
            draft["status"] = "awaiting_manual_send"
            if draft["id"] not in self.pending_manual_send_ids:
                self.pending_manual_send_ids.append(draft["id"])
            self.pipeline_state = "awaiting_manual_send"
            if self.notification_overlay and self.notification_overlay_enabled:
                self._safe_after(
                    0,
                    lambda: self.notification_overlay.show_message(
                        (
                            f"Draft #{draft['id']} ready for manual send "
                            f"(preview overlay disabled). Press {self.manual_send_hotkey or 'F9'}."
                        ),
                        2600,
                    ),
                )

    def _create_draft(self, final_text, raw_text, stop_reason, part_index=1, part_total=1):
        draft = {
            "id": self.next_draft_id,
            "created_at": time.time(),
            "status": "review_pending",
            "final_text": final_text,
            "raw_text": raw_text,
            "stop_reason": stop_reason,
            "part_index": int(max(1, part_index)),
            "part_total": int(max(1, part_total)),
            "token_count": self._token_count(final_text),
            "token_limit": int(self.output_token_limit),
        }
        self.next_draft_id += 1
        self.draft_queue.append(draft)
        return draft

    def _find_draft(self, draft_id):
        for draft in self.draft_queue:
            if draft["id"] == draft_id:
                return draft
        return None

    def _remove_draft(self, draft_id):
        target_id = int(draft_id or 0)
        self.draft_queue = [row for row in self.draft_queue if int(row.get("id", 0) or 0) != target_id]
        self.pending_manual_send_ids = [row_id for row_id in self.pending_manual_send_ids if int(row_id or 0) != target_id]

    def _history_entry_from_draft(self, draft):
        return {
            "id": int(draft.get("id", 0) or 0),
            "status": str(draft.get("status", "") or "").strip(),
            "profile": str(self.active_profile or "Default").strip() or "Default",
            "created_at": float(draft.get("created_at", 0.0) or 0.0),
            "finalized_at": time.time(),
            "final_text": str(draft.get("final_text", "") or ""),
            "raw_text": str(draft.get("raw_text", "") or ""),
            "stop_reason": str(draft.get("stop_reason", "") or ""),
            "part_index": int(draft.get("part_index", 1) or 1),
            "part_total": int(draft.get("part_total", 1) or 1),
            "token_count": int(draft.get("token_count", 0) or 0),
            "token_limit": int(draft.get("token_limit", self.output_token_limit) or self.output_token_limit),
        }

    def _archive_draft_to_history(self, draft):
        if not isinstance(draft, dict):
            return
        path = get_draft_history_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        limit = self._coerce_draft_history_limit(self.draft_history_limit)
        entry = self._history_entry_from_draft(draft)

        rows = []
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if isinstance(payload, list):
                    rows = [row for row in payload if isinstance(row, dict)]
        except Exception as exc:
            logging.warning("Failed reading draft history; recreating file: %s", exc)
            rows = []

        rows.append(entry)
        if len(rows) > limit:
            rows = rows[-limit:]

        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(rows, handle, ensure_ascii=True, indent=2)
        except Exception as exc:
            logging.error("Failed writing draft history: %s", exc)

    def _finalize_draft(self, draft):
        if not isinstance(draft, dict):
            return
        draft_id = int(draft.get("id", 0) or 0)
        if draft_id <= 0:
            return
        self._archive_draft_to_history(draft)
        self._remove_draft(draft_id)

    def _show_next_review_draft(self):
        if not self.preview_overlay or not self.preview_overlay.enabled:
            return False
        try:
            if self.preview_overlay.is_review_active():
                return False
        except Exception:
            return False

        pending = [draft for draft in self.draft_queue if draft.get("status") == "review_pending"]
        if not pending:
            return False
        pending.sort(key=lambda draft: int(draft.get("id", 0)))
        next_draft = pending[0]
        draft_id = int(next_draft.get("id", 0))
        draft_text = next_draft.get("final_text", "")
        token_count = int(next_draft.get("token_count", 0) or 0)
        token_limit = int(next_draft.get("token_limit", self.output_token_limit) or self.output_token_limit)
        self._safe_after(
            0,
            lambda did=draft_id, text=draft_text, tc=token_count, tl=token_limit: self.preview_overlay.show_review(
                did,
                text,
                token_count=tc,
                token_limit=tl,
            ),
        )
        return True

    def on_preview_accept(self, draft_id, edited_text):
        draft = self._find_draft(draft_id)
        if not draft:
            return
        if edited_text:
            draft["final_text"] = edited_text.strip()
        draft["status"] = "awaiting_manual_send"
        self.pipeline_state = "awaiting_manual_send"
        if draft_id not in self.pending_manual_send_ids:
            self.pending_manual_send_ids.append(draft_id)
        if self.preview_overlay:
            self.preview_overlay.hide()
        self._show_next_review_draft()

        part_total = int(draft.get("part_total", 1) or 1)
        part_index = int(draft.get("part_index", 1) or 1)
        part_suffix = f" (part {part_index}/{part_total})" if part_total > 1 else ""
        key_label = self.manual_send_hotkey or "(unset)"
        message = (
            f"Draft #{draft_id}{part_suffix} ready. Click your target text field, then press {key_label} to paste. "
            "Change this in Settings -> Output -> Primary Action Hotkey."
        )
        if self.notification_overlay and self.notification_overlay_enabled:
            self.notification_overlay.show_message(message, 4200)
        else:
            try:
                messagebox.showinfo("Draft Ready", message)
            except Exception:
                pass
        logging.info(message)

    def on_preview_decline(self, draft_id):
        draft = self._find_draft(draft_id)
        if not draft:
            return
        draft["status"] = "declined"
        self.pipeline_state = "declined"
        if self.preview_overlay:
            self.preview_overlay.hide()
        self._finalize_draft(draft)
        shown = self._show_next_review_draft()
        if shown:
            self.pipeline_state = "review_pending"
        if self.notification_overlay and self.notification_overlay_enabled:
            self.notification_overlay.show_message(f"Draft #{draft_id} declined.", 1800)

    def on_preview_tts(self, draft_id, selected_or_full_text):
        del draft_id
        self._speak_review_text(selected_or_full_text, source="button")

    def on_preview_rewrite(self, draft_id, source_text, action, custom_instruction=""):
        draft = self._find_draft(draft_id)
        if not draft:
            return {"ok": False, "message": "Draft is no longer available.", "text": source_text}

        action_key = str(action or "").strip().lower()
        text = (source_text or "").strip()
        if not text:
            return {"ok": False, "message": "No text available to rewrite.", "text": source_text}

        if action_key == "format":
            rewritten = format_text(text)
            return {
                "ok": True,
                "message": "Applied organic formatting.",
                "text": rewritten,
                "token_count": self._token_count(rewritten),
            }

        if not self.llm_enabled:
            return {"ok": False, "message": "LLM rewrites are disabled in settings.", "text": source_text}

        try:
            rewritten = get_engine().rewrite_text(
                text,
                action=action_key,
                custom_instruction=custom_instruction,
                max_output_tokens=self.output_token_limit,
            )
            rewritten_text = (rewritten or "").strip() or text
            if self.organic_formatting_enabled:
                rewritten_text = format_text(rewritten_text)
            return {
                "ok": True,
                "message": f"{action_key.title()} rewrite complete.",
                "text": rewritten_text,
                "token_count": self._token_count(rewritten_text),
            }
        except Exception as exc:
            logging.error("Preview rewrite failed for draft #%s: %s", draft_id, exc)
            return {"ok": False, "message": f"Rewrite failed: {exc}", "text": source_text}

    def on_manual_send_hotkey(self):
        if self.root:
            self._safe_after(0, self._handle_manual_send_hotkey)

    def on_review_tts_hotkey(self):
        if self.root:
            self._safe_after(0, self._handle_review_tts_hotkey)

    def _handle_review_tts_hotkey(self):
        if self.preview_overlay and self.preview_overlay.is_review_active():
            text = self.preview_overlay.get_selected_or_full_text()
            self._speak_review_text(text, source="shortcut")
            return

        capture_result = capture_selection_text_with_restore(timeout_ms=350, poll_ms=25)
        if not capture_result.get("ok", False):
            message = capture_result.get("message", "No readable selected/copied text found.")
            if self.notification_overlay and self.notification_overlay_enabled:
                self.notification_overlay.show_message(message, 1800)
            else:
                logging.info(message)
            return

        if capture_result.get("used_fallback", False):
            logging.info("Review TTS hotkey using clipboard fallback text.")
        else:
            logging.info("Review TTS hotkey captured selected text.")

        self._speak_review_text(capture_result.get("text", ""), source="review_hotkey")

    def _speak_review_text(self, text, source="button"):
        phrase = (text or "").strip()
        if not phrase:
            if self.notification_overlay and self.notification_overlay_enabled:
                self.notification_overlay.show_message("No text available for TTS.", 1800)
            else:
                logging.info("No text available for TTS.")
            return

        if not self.review_tts_enabled:
            if self.notification_overlay and self.notification_overlay_enabled:
                self.notification_overlay.show_message("Review TTS is disabled in settings.", 2000)
            else:
                logging.info("Review TTS is disabled in settings.")
            return

        if not self.tts_engine:
            if self.notification_overlay and self.notification_overlay_enabled:
                self.notification_overlay.show_message("TTS engine is not available.", 2000)
            else:
                logging.error("TTS engine is not available.")
            return

        speed = max(0.5, min(3.0, float(self.review_tts_speed)))
        result = self.tts_engine.speak(
            phrase,
            speed=speed,
            voice_hint=self.review_tts_voice_hint,
        )
        if not result.get("ok", False):
            message = result.get("message", "TTS playback failed.")
            if self.notification_overlay and self.notification_overlay_enabled:
                self.notification_overlay.show_message(message, 2600)
            else:
                logging.error(message)
            return

        if result.get("fallback", False):
            message = "Kokoro unavailable. Using Windows voice fallback."
            if self.notification_overlay and self.notification_overlay_enabled:
                self.notification_overlay.show_message(message, 2200)
            else:
                logging.info(message)

        logging.info(f"Review TTS triggered via {source} using backend={result.get('backend')}.")

    def _handle_manual_send_hotkey(self):
        while self.pending_manual_send_ids:
            draft_id = self.pending_manual_send_ids.pop(0)
            draft = self._find_draft(draft_id)
            if not draft:
                continue
            if draft.get("status") != "awaiting_manual_send":
                continue
            self._dispatch_send(draft, draft.get("final_text", ""), open_chat=False)
            return

        capture_result = capture_selection_text_with_restore(timeout_ms=350, poll_ms=25)
        if not capture_result.get("ok", False):
            message = capture_result.get("message", "No readable selected/copied text found.")
            if self.notification_overlay and self.notification_overlay_enabled:
                self.notification_overlay.show_message(message, 1800)
            else:
                logging.info(message)
            return

        if capture_result.get("used_fallback", False):
            logging.info("Primary action hotkey using clipboard fallback text for TTS.")
        else:
            logging.info("Primary action hotkey captured selected text for TTS.")

        self._speak_review_text(capture_result.get("text", ""), source="primary_hotkey")

    def _dispatch_send(self, draft, text, open_chat=True):
        try:
            if open_chat:
                self.injector.open_chat()
            auto_submit = bool(load_profile(self.active_profile).get("auto_submit", False))
            self.injector.send_output(
                text=text,
                auto_submit=auto_submit,
                close_action=self.chat_close_action,
            )
            draft["status"] = "sent"
            self.pipeline_state = "sent"
            self._finalize_draft(draft)
        except Exception as exc:
            draft["status"] = "error"
            self.pipeline_state = "idle"
            logging.error(f"Send dispatch failed: {exc}")
            self._finalize_draft(draft)

    def on_exit(self, icon=None, item=None):
        del item
        if self._exit_requested:
            return
        self._exit_requested = True
        logging.info("Exiting app.")
        self.running = False

        # Start hard-exit watchdog first so any blocking cleanup can't stall shutdown.
        settings_active = bool(
            self.settings_window and (
                getattr(self.settings_window, "_is_open", False)
                or getattr(self.settings_window, "_window_thread", None)
            )
        )
        timeout = 3.0 if settings_active else 1.5
        threading.Thread(
            target=self._force_exit_after_timeout,
            kwargs={"timeout_sec": timeout},
            daemon=True,
        ).start()

        if self.injector:
            try:
                self.injector.release_mute_key()
            except Exception:
                pass
        try:
            self.manager.stop()
        except Exception:
            pass
        if self.tts_engine:
            try:
                self.tts_engine.shutdown()
            except Exception:
                pass
        try:
            engine = get_engine_if_initialized()
            if engine:
                engine.shutdown()
        except Exception:
            pass

        # Ensure settings window closes to allow process termination.
        # Use forced shutdown close so unsaved-change prompts do not keep Flet open.
        if self.settings_window:
            try:
                if hasattr(self.settings_window, "force_close_for_shutdown"):
                    self.settings_window.force_close_for_shutdown()
                else:
                    self.settings_window.hide()
            except Exception:
                pass
            try:
                wait_for_shutdown = getattr(self.settings_window, "wait_for_shutdown", None)
                if callable(wait_for_shutdown):
                    wait_for_shutdown(timeout_sec=1.4)
            except Exception:
                pass

        if self.overlay:
            self._safe_after(0, self.overlay.destroy)
        if self.preview_overlay:
            self._safe_after(0, self.preview_overlay.hide)

        if icon:
            icon.stop()
        if self.root:
            self._safe_after(0, self.root.quit)

    def _force_exit_after_timeout(self, timeout_sec=2.5):
        try:
            time.sleep(max(0.5, float(timeout_sec)))
        except Exception:
            time.sleep(2.5)
        if self.running:
            return
        try:
            if self.icon:
                self.icon.stop()
        except Exception:
            pass
        os._exit(0)

    def run(self):
        self.setup()
        self.manager.start()
        tray_thread = threading.Thread(target=self.icon.run, daemon=True)
        tray_thread.start()
        self.root.mainloop()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="BetterFingers Application")
    parser.add_argument("--profile", type=str, help="Startup profile name")
    parser.add_argument("--log-level", type=str, default="DEBUG", help="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
    parser.add_argument(
        "--prefetch-mvp",
        action="store_true",
        help="Download recommended first-time runtime assets and exit.",
    )
    parser.add_argument(
        "--prefetch-llm-model",
        action="append",
        default=[],
        help="Download/cache a specific LLM model id (repeatable).",
    )
    parser.add_argument(
        "--prefetch-whisper-model",
        action="append",
        default=[],
        help="Download/cache a specific Whisper model size (repeatable).",
    )
    parser.add_argument(
        "--prefetch-tts-assets",
        action="store_true",
        help="Download/cache TTS model assets and exit.",
    )
    parser.add_argument(
        "--prefetch-voice",
        type=str,
        default="english",
        help="Voice hint used during TTS prefetch.",
    )
    parser.add_argument(
        "--prefetch-cpu",
        action="store_true",
        help="Force CPU mode for Whisper prefetch probes.",
    )
    args = parser.parse_args()

    setup_logging(level=args.log_level)

    prefetch_requested = bool(
        args.prefetch_mvp
        or args.prefetch_tts_assets
        or list(args.prefetch_llm_model or [])
        or list(args.prefetch_whisper_model or [])
    )
    if prefetch_requested:
        llm_targets = list(args.prefetch_llm_model or [])
        whisper_targets = list(args.prefetch_whisper_model or [])
        include_tts = bool(args.prefetch_tts_assets)
        if args.prefetch_mvp:
            llm_targets.append("gemma-3-4b-q4")
            whisper_targets.append("base.en")
            include_tts = True

        summary = prefetch_runtime_assets(
            llm_model_ids=llm_targets,
            whisper_models=whisper_targets,
            include_tts=include_tts,
            prefer_gpu=not bool(args.prefetch_cpu),
            tts_voice_hint=args.prefetch_voice,
        )
        logging.info("Prefetch summary: %s", json.dumps(summary, ensure_ascii=True))
        if summary.get("ok", False):
            logging.info("Prefetch completed successfully.")
        else:
            logging.warning("Prefetch completed with one or more issues.")
        sys.exit(0)

    mutex_name = "Global\\BetterFingers_Mutex"
    mutex = ctypes.windll.kernel32.CreateMutexW(None, True, mutex_name)
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.user32.MessageBoxW(0, "BetterFingers is already running.", "BetterFingers", 0x40)
        sys.exit(0)

    app = App(startup_profile=args.profile)
    app.run()
