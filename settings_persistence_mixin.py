import logging
import os

from input_binding import InputBinding, events_to_expression, parse_binding_expression
from utils import (
    get_draft_history_path,
    get_profiles_dir,
    get_user_data_path,
    load_profile,
    save_profile,
    set_last_active_profile,
)

try:
    import flet as ft
except Exception:
    ft = None


if ft is None:
    raise ImportError("Flet is required for BetterFingers settings. Please install with: pip install flet")


class SettingsPersistenceMixin:
    def _load_settings(self):
        cfg = load_profile(self.current_profile)
        c = self._controls

        self._refresh_persona_options()
        self._refresh_tts_voice_options()

        c["hotkey"].value = cfg.get("hotkey", "f8")
        c["force_stop_key"].value = cfg.get("force_stop_key", "")
        c["recording_mode"].value = cfg.get("recording_mode", "toggle")

        c["audio_ducking"].value = bool(cfg.get("audio_ducking", False))
        c["audio_ducking_level"].value = self._safe_float(cfg.get("audio_ducking_level_percent", 18.0), 18.0, 1.0, 100.0)
        c["audio_ducking_fallback_return"].value = self._safe_float(
            cfg.get("audio_ducking_fallback_return_percent", 100.0),
            100.0,
            1.0,
            100.0,
        )

        min_delay = float(cfg.get("min_inter_key_delay", 0.08))
        max_delay = float(cfg.get("max_inter_key_delay", 0.16))
        avg_delay = (min_delay + max_delay) / 2.0
        min_hold = float(cfg.get("min_key_hold", 0.015))
        max_hold = float(cfg.get("max_key_hold", 0.035))
        avg_hold = (min_hold + max_hold) / 2.0
        if avg_delay < 0.02:
            char_time = max(0.0005, avg_delay + avg_hold)
            wpm = int(60 / (5 * char_time))
        elif avg_delay + 0.025 > 0:
            wpm = int(60 / (5 * (avg_delay + 0.025)))
        else:
            wpm = 1200
        wpm = max(10, min(1200, wpm))
        c["wpm"].value = wpm
        self._set_value_label_text("wpm_label", f"{wpm} WPM")
        c["instant_typing"].value = bool(cfg.get("instant_typing", False))
        c["sign_off"].value = cfg.get("sign_off_text", "")

        binding = InputBinding.from_dict(
            cfg.get("controller_binding"),
            default_button=cfg.get("controller_button", 4),
        )
        c["controller_enabled"].value = bool(cfg.get("controller_enabled", cfg.get("controller_ptt", False)))
        c["controller_style"].value = binding.style
        c["controller_binding_expr"].value = binding.to_expression()
        c["controller_sequence_window"].value = str(int(cfg.get("controller_sequence_window_ms", binding.sequence_window_ms)))
        c["controller_axis_threshold"].value = self._safe_float(
            cfg.get("controller_axis_threshold", binding.axis_threshold),
            0.6,
            0.1,
            1.0,
        )

        c["chat_open_key"].value = cfg.get("chat_open_key", "")
        c["voice_mute_key"].value = cfg.get("voice_mute_key", "")

        c["send_mode"].value = cfg.get("send_mode", "review_first")
        c["chat_close_action"].value = cfg.get("chat_close_action", "none")
        c["auto_submit"].value = bool(cfg.get("auto_submit", False))
        c["manual_send_hotkey"].value = cfg.get("manual_send_hotkey", "f9")
        c["organic_formatting_enabled"].value = bool(cfg.get("organic_formatting_enabled", True))
        output_limit = self._safe_int(cfg.get("output_token_limit", 1100), 1100, minimum=900, maximum=1200)
        c["output_token_limit"].value = output_limit
        self._set_value_label_text("output_token_limit_value", f"{output_limit} tokens")
        draft_history_limit = self._safe_int(
            cfg.get("draft_history_limit", 80),
            80,
            minimum=10,
            maximum=500,
        )
        c["draft_history_limit"].value = draft_history_limit
        self._set_value_label_text("draft_history_limit_value", f"{draft_history_limit} drafts")
        c["long_input_message"].value = cfg.get(
            "long_input_message",
            "It looks like you have a lot to say. Give us a second.",
        )

        c["review_tts_enabled"].value = bool(cfg.get("review_tts_enabled", True))
        c["review_tts_hotkey"].value = cfg.get("review_tts_hotkey", "ctrl+shift+space")
        c["review_tts_speed"].value = self._safe_float(cfg.get("review_tts_speed", 1.5), 1.5, 0.5, 3.0)
        c["review_tts_voice_hint"].value = cfg.get("review_tts_voice_hint", "english")
        c["review_tts_sample_text"].value = self.SAMPLE_TTS_TEXTS[0]
        c["tts_status"].value = ""
        self._refresh_tts_voice_options()

        self._set_value_label_text(
            "audio_ducking_level_value",
            self._format_slider_value(
                c["audio_ducking_level"].value,
                suffix="%",
                decimals=0,
            ),
        )
        self._set_value_label_text(
            "audio_ducking_fallback_return_value",
            self._format_slider_value(
                c["audio_ducking_fallback_return"].value,
                suffix="%",
                decimals=0,
            ),
        )
        self._set_value_label_text(
            "controller_axis_threshold_value",
            self._format_slider_value(
                c["controller_axis_threshold"].value,
                decimals=2,
            ),
        )
        self._set_value_label_text(
            "review_tts_speed_value",
            self._format_slider_value(
                c["review_tts_speed"].value,
                suffix="x",
                decimals=2,
            ),
        )

        c["no_audio_min_duration"].value = str(self._safe_float(cfg.get("no_audio_min_duration_sec", 0.30), 0.30, 0.0, 30.0))
        c["no_audio_min_rms"].value = str(self._safe_float(cfg.get("no_audio_min_rms", 0.003), 0.003, 0.0, 1.0))
        c["no_audio_min_peak"].value = str(self._safe_float(cfg.get("no_audio_min_peak", 0.015), 0.015, 0.0, 1.0))

        c["llm_enabled"].value = bool(cfg.get("llm_enabled", True))
        c["persona"].value = cfg.get("current_preset", "True Janitor")
        self._refresh_persona_options()
        c["true_gen"].value = bool(cfg.get("true_gen", False))
        c["model_size"].value = cfg.get("model_size", "base.en")
        c["quantization"].value = cfg.get("quantization", "int8")
        if "kokoro_quantization" in c:
            c["kokoro_quantization"].value = cfg.get("kokoro_quantization", "fp32")
        c["model_keep_llm_loaded"].value = bool(cfg.get("model_keep_llm_loaded", True))
        c["model_keep_stt_loaded"].value = bool(cfg.get("model_keep_stt_loaded", True))
        c["model_keep_tts_loaded"].value = bool(cfg.get("model_keep_tts_loaded", False))
        c["use_gpu"].value = bool(cfg.get("use_gpu", True))
        
        # Load LLM Model Selection
        self._refresh_llm_model_options()
        current_llm = cfg.get("llm_model_id", "gemma-3-4b-q4")
        if c.get("llm_model_id"):
             c["llm_model_id"].value = current_llm

        if c.get("experience_preset"):
            inferred_preset = self._infer_experience_preset(cfg)
            c["experience_preset"].value = inferred_preset
            self._set_active_experience_preset(inferred_preset)
            self._selected_preset_current = inferred_preset
            self._selected_preset_pending = None

        if "whisper_download_model" in c:
            c["whisper_download_model"].value = c["model_size"].value
            self._refresh_whisper_download_status()

        self._refresh_experience_preset_ui()

        c["overlay_position"].value = cfg.get("overlay_position", "Bottom-Right")
        c["status_indicator_enabled"].value = bool(cfg.get("status_indicator_enabled", True))
        c["status_indicator_flash_enabled"].value = bool(cfg.get("status_indicator_flash_enabled", True))
        c["status_indicator_color_idle"].value = cfg.get("status_indicator_color_idle", "#808080")
        c["status_indicator_color_listening"].value = cfg.get("status_indicator_color_listening", "#14b8a6")
        c["status_indicator_color_recording"].value = cfg.get("status_indicator_color_recording", "#ff3b30")
        c["status_indicator_color_processing"].value = cfg.get("status_indicator_color_processing", "#fbbf24")
        c["notification_overlay_enabled"].value = bool(cfg.get("notification_overlay_enabled", True))
        c["notification_overlay_position"].value = cfg.get("notification_overlay_position", "Bottom-Right")
        c["notification_overlay_alpha"].value = str(
            self._safe_float(cfg.get("notification_overlay_alpha", 0.85), 0.85, 0.1, 1.0)
        )
        c["notification_overlay_bg"].value = cfg.get("notification_overlay_bg", "#161616")
        c["notification_overlay_fg"].value = cfg.get("notification_overlay_fg", "#f2f2f2")

        c["preview_overlay_enabled"].value = bool(cfg.get("preview_overlay_enabled", True))
        c["preview_overlay_position"].value = cfg.get("preview_overlay_position", "Bottom-Right")
        c["preview_overlay_alpha"].value = str(self._safe_float(cfg.get("preview_overlay_alpha", 0.95), 0.95, 0.1, 1.0))
        c["preview_overlay_bg"].value = cfg.get("preview_overlay_bg", "#111111")
        c["preview_overlay_fg"].value = cfg.get("preview_overlay_fg", "#f2f2f2")
        c["preview_overlay_text_bg"].value = cfg.get("preview_overlay_text_bg", "#1d1d1d")

        if callable(getattr(self, "_mark_settings_clean", None)):
            self._mark_settings_clean()

    def _on_save_clicked(self, _event):
        self._save_settings()

    def _save_settings(self):
        c = self._controls
        cfg = load_profile(self.current_profile)

        wpm = self._safe_int(c["wpm"].value, 70, minimum=10, maximum=1200)
        if wpm <= 500:
            char_time = 60 / (wpm * 5)
            avg_delay = max(0.001, char_time - 0.025)
            min_delay = float(avg_delay * 0.8)
            max_delay = float(avg_delay * 1.2)
            if wpm > 150:
                min_hold, max_hold = 0.005, 0.015
            else:
                min_hold, max_hold = 0.015, 0.035
        else:
            char_time = 60 / (wpm * 5)
            target_hold = min(0.004, max(0.001, char_time * 0.2))
            target_delay = max(0.0005, char_time - target_hold)
            min_delay = float(max(0.0005, target_delay * 0.8))
            max_delay = float(max(min_delay + 0.0005, target_delay * 1.2))
            min_hold = float(max(0.001, target_hold * 0.8))
            max_hold = float(max(min_hold + 0.0005, target_hold * 1.2))

        binding = InputBinding.from_dict(cfg.get("controller_binding"))
        style = (c["controller_style"].value or binding.style or "single").strip().lower() or "single"
        expr = (c["controller_binding_expr"].value or "").strip()
        events = parse_binding_expression(style, expr)
        if events:
            binding.style = style
            binding.events = events
        binding.sequence_window_ms = self._safe_int(c["controller_sequence_window"].value, 400, minimum=100, maximum=2000)
        binding.axis_threshold = self._safe_float(c["controller_axis_threshold"].value, 0.6, minimum=0.1, maximum=1.0)
        binding.validate()
        c["controller_binding_expr"].value = events_to_expression(binding.style, binding.events)

        legacy_button = cfg.get("controller_button", 4)
        for token in binding.events:
            if token.startswith("button:"):
                try:
                    legacy_button = int(token.split(":", 1)[1])
                except Exception:
                    pass
                break

        cfg["hotkey"] = (c["hotkey"].value or "").strip()
        cfg["force_stop_key"] = (c["force_stop_key"].value or "").strip()
        cfg["recording_mode"] = (c["recording_mode"].value or "toggle").strip()
        cfg["min_inter_key_delay"] = min_delay
        cfg["max_inter_key_delay"] = max_delay
        cfg["min_key_hold"] = min_hold
        cfg["max_key_hold"] = max_hold
        cfg["instant_typing"] = bool(c["instant_typing"].value)

        cfg["audio_ducking"] = bool(c["audio_ducking"].value)
        cfg["audio_ducking_level_percent"] = self._safe_float(c["audio_ducking_level"].value, 18.0, minimum=1.0, maximum=100.0)
        cfg["audio_ducking_fallback_return_percent"] = self._safe_float(
            c["audio_ducking_fallback_return"].value,
            100.0,
            minimum=1.0,
            maximum=100.0,
        )
        cfg["chat_open_key"] = (c["chat_open_key"].value or "").strip()
        cfg["voice_mute_key"] = (c["voice_mute_key"].value or "").strip()
        cfg["sign_off_text"] = c["sign_off"].value or ""

        cfg["controller_enabled"] = bool(c["controller_enabled"].value)
        cfg["controller_ptt"] = bool(c["controller_enabled"].value)
        cfg["controller_button"] = legacy_button
        cfg["controller_sequence_window_ms"] = int(binding.sequence_window_ms)
        cfg["controller_axis_threshold"] = float(binding.axis_threshold)
        cfg["controller_binding"] = binding.to_dict()

        send_mode = (c["send_mode"].value or "review_first").strip().lower()
        if send_mode not in {"review_first", "auto_send"}:
            send_mode = "review_first"
        cfg["send_mode"] = send_mode
        cfg.pop("send_method", None)
        cfg["auto_submit"] = bool(c["auto_submit"].value)
        cfg["manual_send_hotkey"] = (c["manual_send_hotkey"].value or "f9").strip()
        cfg["chat_close_action"] = (c["chat_close_action"].value or "none").strip()
        cfg["organic_formatting_enabled"] = bool(c["organic_formatting_enabled"].value)
        cfg["output_token_limit"] = self._safe_int(
            c["output_token_limit"].value,
            1100,
            minimum=900,
            maximum=1200,
        )
        cfg["draft_history_limit"] = self._safe_int(
            c["draft_history_limit"].value,
            80,
            minimum=10,
            maximum=500,
        )
        cfg["long_input_message"] = (
            (c["long_input_message"].value or "It looks like you have a lot to say. Give us a second.").strip()
            or "It looks like you have a lot to say. Give us a second."
        )
        cfg["review_tts_enabled"] = bool(c["review_tts_enabled"].value)
        cfg["review_tts_hotkey"] = (c["review_tts_hotkey"].value or "").strip()
        cfg["review_tts_speed"] = self._safe_float(c["review_tts_speed"].value, 1.5, minimum=0.5, maximum=3.0)
        cfg["review_tts_voice_hint"] = ((c["review_tts_voice_hint"].value or "english").strip() or "english")

        cfg["no_audio_min_duration_sec"] = self._safe_float(c["no_audio_min_duration"].value, 0.30, minimum=0.0, maximum=30.0)
        cfg["no_audio_min_rms"] = self._safe_float(c["no_audio_min_rms"].value, 0.003, minimum=0.0, maximum=1.0)
        cfg["no_audio_min_peak"] = self._safe_float(c["no_audio_min_peak"].value, 0.015, minimum=0.0, maximum=1.0)

        cfg["overlay_position"] = (c["overlay_position"].value or "Bottom-Right").strip()
        cfg["status_indicator_enabled"] = bool(c["status_indicator_enabled"].value)
        cfg["status_indicator_flash_enabled"] = bool(c["status_indicator_flash_enabled"].value)
        cfg["status_indicator_color_idle"] = (c["status_indicator_color_idle"].value or "#808080").strip()
        cfg["status_indicator_color_listening"] = (c["status_indicator_color_listening"].value or "#14b8a6").strip()
        cfg["status_indicator_color_recording"] = (c["status_indicator_color_recording"].value or "#ff3b30").strip()
        cfg["status_indicator_color_processing"] = (c["status_indicator_color_processing"].value or "#fbbf24").strip()
        cfg["notification_overlay_enabled"] = bool(c["notification_overlay_enabled"].value)
        cfg["notification_overlay_position"] = (c["notification_overlay_position"].value or "Bottom-Right").strip()
        cfg["notification_overlay_alpha"] = self._safe_float(c["notification_overlay_alpha"].value, 0.85, minimum=0.1, maximum=1.0)
        cfg["notification_overlay_bg"] = (c["notification_overlay_bg"].value or "#161616").strip()
        cfg["notification_overlay_fg"] = (c["notification_overlay_fg"].value or "#f2f2f2").strip()

        cfg["preview_overlay_enabled"] = bool(c["preview_overlay_enabled"].value)
        cfg["preview_overlay_position"] = (c["preview_overlay_position"].value or "Bottom-Right").strip()
        cfg["preview_overlay_alpha"] = self._safe_float(c["preview_overlay_alpha"].value, 0.95, minimum=0.1, maximum=1.0)
        cfg["preview_overlay_bg"] = (c["preview_overlay_bg"].value or "#111111").strip()
        cfg["preview_overlay_fg"] = (c["preview_overlay_fg"].value or "#f2f2f2").strip()
        cfg["preview_overlay_text_bg"] = (c["preview_overlay_text_bg"].value or "#1d1d1d").strip()

        cfg["llm_enabled"] = bool(c["llm_enabled"].value)
        cfg["current_preset"] = c["persona"].value or "True Janitor"
        cfg["true_gen"] = bool(c["true_gen"].value)
        pending = str(getattr(self, "_selected_preset_pending", "") or "").strip().lower()
        if pending:
            # Pending preset switches are preview-only until Apply is clicked.
            experience = str(getattr(self, "_active_experience_preset", "custom") or "custom").strip().lower() or "custom"
        else:
            experience = str(c["experience_preset"].value or "custom").strip().lower() or "custom"
        if experience not in self._allowed_experience_presets():
            experience = "custom"
        cfg["experience_preset"] = experience
        cfg["model_keep_llm_loaded"] = bool(c["model_keep_llm_loaded"].value)
        cfg["model_keep_stt_loaded"] = bool(c["model_keep_stt_loaded"].value)
        cfg["model_keep_tts_loaded"] = bool(c["model_keep_tts_loaded"].value)
        cfg["use_gpu"] = bool(c["use_gpu"].value)
        cfg["quantization"] = c["quantization"].value or "int8"
        cfg["model_size"] = c["model_size"].value or "base.en"
        cfg["llm_model_id"] = c["llm_model_id"].value or "gemma-3-4b-q4"
        if "kokoro_quantization" in c:
            cfg["kokoro_quantization"] = c["kokoro_quantization"].value or "fp32"

        save_profile(self.current_profile, cfg)
        try:
            set_last_active_profile(self.current_profile)
        except Exception as exc:
            logging.debug("Failed to persist active profile marker '%s': %s", self.current_profile, exc)
        self._toast(f"Profile '{self.current_profile}' saved.")
        if callable(getattr(self, "_mark_settings_clean", None)):
            self._mark_settings_clean()
        self._invoke_on_save()
        self._safe_update()

    def _on_open_word_rules_clicked(self, _event):
        path = os.path.join(get_user_data_path(), "context_rules.yaml")
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('context_rules:\n  "keyword/example": "Describe context-based replacement here."\n')
        try:
            if hasattr(os, "startfile"):
                os.startfile(path)
                return
        except Exception as exc:
            logging.error("Failed to open context rules file: %s", exc)
        self._toast(f"Word rules file saved at: {path}")

    def _on_open_draft_history_clicked(self, _event):
        path = get_draft_history_path()
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("[]\n")
        try:
            if hasattr(os, "startfile"):
                os.startfile(path)
                return
        except Exception as exc:
            logging.error("Failed to open draft history file: %s", exc)
        self._toast(f"Draft history file saved at: {path}")

    def _on_new_profile_clicked(self, _event):
        name_input = ft.TextField(label="Profile name", autofocus=True)

        def _close(_):
            self._close_dialog(key=self.MODAL_KEY_PROFILE_NEW)

        def _create(_):
            candidate = self._sanitize_profile_name(name_input.value)
            if not candidate:
                self._toast("Enter a valid profile name.")
                return
            save_profile(candidate, load_profile("Default"))
            self.current_profile = candidate
            try:
                set_last_active_profile(self.current_profile)
            except Exception:
                pass
            self._refresh_profile_options()
            self._load_settings()
            self._close_dialog(key=self.MODAL_KEY_PROFILE_NEW)
            self._toast(f"Profile '{candidate}' created.")

        def _on_dismiss(_):
            return

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("New Profile"),
            content=name_input,
            actions=[
                ft.TextButton("Cancel", on_click=_close),
                ft.Button("Create", on_click=_create),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=_on_dismiss,
        )
        self._show_dialog(dialog, key=self.MODAL_KEY_PROFILE_NEW)

    def _on_delete_profile_clicked(self, _event):
        if self.current_profile == "Default":
            self._toast("Default profile cannot be deleted.")
            return

        def _close(_):
            self._close_dialog(key=self.MODAL_KEY_PROFILE_DELETE)

        def _delete(_):
            path = os.path.join(get_profiles_dir(), f"{self.current_profile}.yaml")
            try:
                if os.path.exists(path):
                    os.remove(path)
                deleted = self.current_profile
                self.current_profile = "Default"
                try:
                    set_last_active_profile(self.current_profile)
                except Exception:
                    pass
                self._refresh_profile_options()
                self._load_settings()
                self._toast(f"Profile '{deleted}' deleted.")
            except Exception as exc:
                logging.error("Failed to delete profile '%s': %s", self.current_profile, exc)
                self._toast("Delete failed. See debug log.")
            finally:
                self._close_dialog(key=self.MODAL_KEY_PROFILE_DELETE)

        def _on_dismiss(_):
            return

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Delete Profile"),
            content=ft.Text(f"Delete profile '{self.current_profile}'?"),
            actions=[
                ft.TextButton("Cancel", on_click=_close),
                ft.Button("Delete", on_click=_delete),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=_on_dismiss,
        )
        self._show_dialog(dialog, key=self.MODAL_KEY_PROFILE_DELETE)

