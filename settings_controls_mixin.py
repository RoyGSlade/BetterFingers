import logging

import math

from input_binding import InputBinding
from llm_engine import (
    build_guided_persona_prompt,
    delete_persona,
    get_fast_lane_preset_names,
    get_persona_prompt,
    upsert_persona,
)
from model_manager import AVAILABLE_MODELS
from utils import list_profiles, load_profile, set_last_active_profile

try:
    import flet as ft
except Exception:
    ft = None


if ft is None:
    raise ImportError("Flet is required for BetterFingers settings. Please install with: pip install flet")


class SettingsControlsMixin:
    EXPERIENCE_PRESET_OPTIONS = [
        ("simple", "Simple Mode"),
        ("plus", "Plus Mode"),
        ("pro", "Pro Mode"),
        ("dont_use", "Dont Use This Mode"),
        ("custom", "Custom"),
    ]

    EXPERIENCE_PRESET_DEFINITIONS = {
        "simple": {
            "label": "Simple Mode",
            "description": "Whisper tiny + fast typing, optimized for low hardware usage.",
            "values": {
                "llm_enabled": False,
                "model_size": "tiny.en",
                "llm_model_id": "gemma-3-4b-q4",
                "quantization": "int4",
                "persona": "True Janitor",
                "use_gpu": False,
                "model_keep_llm_loaded": False,
                "model_keep_stt_loaded": False,
                "model_keep_tts_loaded": False,
                "wpm": 350,
                "instant_typing": True,
            },
        },
        "plus": {
            "label": "Plus Mode",
            "description": "Whisper base + Gemma 3 4B Q4 balanced for quality and speed.",
            "values": {
                "llm_enabled": True,
                "model_size": "base.en",
                "llm_model_id": "gemma-3-4b-q4",
                "quantization": "int4",
                "persona": "True Janitor",
                "use_gpu": True,
                "model_keep_llm_loaded": True,
                "model_keep_stt_loaded": True,
            },
        },
        "pro": {
            "label": "Pro Mode",
            "description": "Whisper small + Gemma 3 4B Q8 for stronger quality on better hardware.",
            "values": {
                "llm_enabled": True,
                "model_size": "small.en",
                "llm_model_id": "gemma-3-4b-q8",
                "quantization": "int8",
                "persona": "True Janitor",
                "use_gpu": True,
                "model_keep_llm_loaded": True,
                "model_keep_stt_loaded": True,
            },
        },
        "dont_use": {
            "label": "Dont Use This Mode",
            "description": "Whisper large + Gemma 3 12B Q4, very heavy memory usage.",
            "values": {
                "llm_enabled": True,
                "model_size": "large-v3",
                "llm_model_id": "gemma-3-12b-q4",
                "quantization": "int4",
                "persona": "True Janitor",
                "use_gpu": True,
                "model_keep_llm_loaded": True,
                "model_keep_stt_loaded": True,
            },
        },
    }

    WHISPER_VRAM_ESTIMATE_GB = {
        "tiny.en": 0.5,
        "base.en": 0.9,
        "small.en": 2.0,
        "medium.en": 4.8,
        "large-v3": 8.5,
    }

    @staticmethod
    def _centered_value_text(value: str):
        return ft.Row(
            [ft.Text(value, size=12)],
            alignment=ft.MainAxisAlignment.CENTER,
        )

    def _format_slider_value(self, value, suffix="", decimals=0):
        safe = self._safe_float(value, 0.0)
        if decimals <= 0:
            return f"{int(round(safe))}{suffix}"
        return f"{safe:.{decimals}f}{suffix}"

    def _slider_with_value(self, slider_key: str, value_key: str):
        return ft.Column(
            [
                self._controls[value_key],
                ft.Row(
                    [self._controls[slider_key]],
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
            ],
            tight=True,
            spacing=4,
        )

    def _set_value_label_text(self, label_key: str, value: str):
        control = self._controls.get(label_key)
        if control is None:
            return
        # Value labels may be a Row(Text(...)) or Container(content=Text(...)).
        if hasattr(control, "controls"):
            children = getattr(control, "controls") or []
            if children:
                first = children[0]
                if hasattr(first, "value"):
                    first.value = str(value)
                    return
        inner = getattr(control, "content", None)
        if hasattr(inner, "value"):
            inner.value = str(value)
            return
        if hasattr(control, "value"):
            control.value = str(value)

    def _card(self, title: str, controls, target_key: str = "", tab_key: str = "", help_key: str = ""):
        scroll_key = ""
        if target_key:
            scroll_key = f"tour-target-{target_key}"
        heading = ft.Text(title, size=18, weight=ft.FontWeight.W_600, color=self._palette["text"])
        heading_row = ft.Row(
            [
                ft.Container(content=heading, expand=True),
                self._help_icon(help_key) if help_key else ft.Container(),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        panel = ft.Container(
            key=scroll_key or None,
            bgcolor=self._palette["card"],
            border_radius=14,
            border=ft.Border.all(1, self._palette["card_border"]),
            padding=16,
            content=ft.Column(
                [heading_row] + controls,
                spacing=10,
                tight=True,
            ),
        )
        if target_key:
            self._tour_targets[target_key] = panel
            if tab_key:
                self._tour_target_tabs[target_key] = tab_key
            if scroll_key:
                self._tour_target_scroll_keys[target_key] = scroll_key
        return ft.Card(
            elevation=1,
            margin=ft.Margin.only(bottom=12),
            content=panel,
        )

    @staticmethod
    def _options(values):
        return [ft.dropdown.Option(v) for v in values]

    def _hotkey_row(self, field_key: str, label: str, hint: str = ""):
        """Create a hotkey field with a Map button for key capture."""
        c = self._controls
        c[field_key] = ft.TextField(label=label, hint_text=hint, expand=True, read_only=True)
        c[f"{field_key}_map_btn"] = ft.Button(
            "Map",
            on_click=lambda e: self._start_key_capture(field_key),
            style=ft.ButtonStyle(padding=ft.Padding.symmetric(horizontal=16)),
        )
        return ft.Row(
            [c[field_key], c[f"{field_key}_map_btn"]],
            spacing=8,
            alignment=ft.MainAxisAlignment.START,
        )

    def _start_key_capture(self, field_key: str):
        """Start capturing a key press for the given field."""
        if not self._page:
            return
        c = self._controls
        btn = c.get(f"{field_key}_map_btn")
        field = c.get(field_key)
        if btn:
            btn.text = "Press key..."
            btn.disabled = True
        if field:
            field.value = "Waiting..."
        self._safe_update()

        # Store the target field for the key handler
        self._capturing_key_for = field_key
        self._page.on_keyboard_event = self._on_key_captured

    def _on_key_captured(self, e: ft.KeyboardEvent):
        """Handle captured key press."""
        if not hasattr(self, "_capturing_key_for") or not self._capturing_key_for:
            return

        field_key = self._capturing_key_for
        self._capturing_key_for = None

        # Build key string
        parts = []
        if e.ctrl:
            parts.append("ctrl")
        if e.alt:
            parts.append("alt")
        if e.shift:
            parts.append("shift")
        if e.key and e.key.lower() not in ("control", "alt", "shift", "meta"):
            parts.append(e.key.lower())

        key_str = "+".join(parts) if parts else e.key.lower()

        c = self._controls
        field = c.get(field_key)
        btn = c.get(f"{field_key}_map_btn")
        if field:
            field.value = key_str
        if btn:
            btn.text = "Map"
            btn.disabled = False

        # Clear the keyboard handler
        if self._page:
            self._page.on_keyboard_event = None
        self._safe_update()

    def _controller_map_row(self, field_key: str, label: str, hint: str = ""):
        """Create a controller mapping row with Map button."""
        c = self._controls
        c[field_key] = ft.TextField(label=label, hint_text=hint, expand=True, read_only=True)
        c[f"{field_key}_map_btn"] = ft.Button(
            "Map Input",
            on_click=lambda e: self._start_controller_mapping(field_key),
            style=ft.ButtonStyle(
                padding=ft.Padding.symmetric(horizontal=16),
                color=self._palette["accent"],
            ),
        )
        return ft.Row(
            [c[field_key], c[f"{field_key}_map_btn"]],
            spacing=8,
            alignment=ft.MainAxisAlignment.START,
        )

    def _start_controller_mapping(self, field_key: str):
        """Start controller mapping process."""
        if not self.hotkey_manager:
            self._toast("Controller manager not available")
            return

        style = self._controls["controller_style"].value or "single"

        c = self._controls
        btn = c.get(f"{field_key}_map_btn")
        field = c.get(field_key)

        if btn:
            btn.text = "Press Controller..."
            btn.disabled = True
        if field:
            field.value = "Listening..."
        self._safe_update()

        def _on_activity(token):
            # Show what's being pressed
            if btn:
                btn.text = f"Pressed: {token}"
                self._safe_update()

        # Start mapping with 5s timeout
        self.hotkey_manager.start_mapping(
            lambda result: self._on_controller_mapped(field_key, result),
            style=style,
            timeout_ms=5000,
            activity_callback=_on_activity,
        )

    def _on_controller_mapped(self, field_key: str, result: dict):
        """Handle completion of controller mapping."""

        def _update_ui():
            c = self._controls
            btn = c.get(f"{field_key}_map_btn")
            field = c.get(field_key)

            if btn:
                btn.text = "Map Input"
                btn.disabled = False

            if result:
                try:
                    binding = InputBinding.from_dict(result)
                    expr = binding.to_expression()
                    if field:
                        field.value = expr
                    self._toast(f"Mapped: {expr}")
                except Exception as exc:
                    logging.error(f"Failed to parse mapping result: {exc}")
                    if field:
                        field.value = "Error"
            else:
                self._toast("Mapping timed out or cancelled")
                # Restore previous value or leave as is?
                # Probably leave as is, but currently it says "Listening..."
                # Let's try to restore from current config if possible, or clear
                if field and field.value == "Listening...":
                    profile = load_profile(self.current_profile)
                    field.value = profile.get("controller_binding_expr", "")

            self._safe_update()

        # Execute UI update on main thread if possible, or just run it since _safe_update handles page.update()
        _update_ui()

    def _build_controls(self):
        c = self._controls
        c.clear()
        self._tour_targets = {}
        self._tour_target_tabs = {}
        self._tour_target_scroll_keys = {}
        self._tour_tab_scrollers = {}

        c["profile"] = ft.Dropdown(
            label="Active Profile",
            width=280,
        )
        if hasattr(c["profile"], "on_select"):
            c["profile"].on_select = self._on_profile_changed
        elif hasattr(c["profile"], "on_change"):
            c["profile"].on_change = self._on_profile_changed
        c["recording_mode"] = ft.Dropdown(
            label="Record Mode",
            options=self._options(["toggle", "ptt"]),
        )
        c["audio_ducking"] = ft.Switch(label="Smart Audio Ducking")
        c["audio_ducking_level"] = ft.Slider(min=1, max=100, divisions=99, label="{value:.0f}%")
        c["audio_ducking_fallback_return"] = ft.Slider(min=1, max=100, divisions=99, label="{value:.0f}%")
        c["audio_ducking_level_value"] = self._centered_value_text("18%")
        c["audio_ducking_fallback_return_value"] = self._centered_value_text("100%")
        c["wpm"] = ft.Slider(min=10, max=1200, divisions=238, on_change=self._on_wpm_slider_changed)
        c["wpm_label"] = self._centered_value_text("70 WPM")
        c["wpm_warning"] = ft.Text("", size=12, color="orange", visible=False)
        c["instant_typing"] = ft.Switch(label="Instant Typing")
        c["sign_off"] = ft.TextField(label="Sign-off Text")

        # ... (lines omitted) ...

        c["llm_enabled"] = ft.Switch(label="Enable LLM Post-Processing")
        c["persona"] = ft.Dropdown(label="Persona")
        c["true_gen"] = ft.Switch(label="TrueGen Universal Grammar")
        
        # New LLM Model Selector
        dd = ft.Dropdown(
            label="LLM Model (Gemma)",
            width=300,
            options=[ft.dropdown.Option(k, text=v["name"]) for k, v in AVAILABLE_MODELS.items()]
        )
        dd.on_change = lambda e: (self._on_llm_model_action("check"), self._on_preset_related_setting_changed(e))
        c["llm_model_id"] = dd
        c["llm_model_status"] = ft.Text("", size=12, color=self._palette["muted"])
        c["llm_model_buttons"] = ft.Row(
            [
                ft.Button("Download", on_click=lambda e: self._on_llm_model_action("download")),
                ft.OutlinedButton("Delete", on_click=lambda e: self._on_llm_model_action("delete")),
                ft.OutlinedButton("Check Status", on_click=lambda e: self._on_llm_model_action("check")),
            ],
            spacing=8
        )

        c["model_size"] = ft.Dropdown(
            label="Model Size (Whisper)",
            options=self._options(["tiny.en", "base.en", "small.en", "medium.en", "large-v3"]),
        )
        c["quantization"] = ft.Dropdown(label="Quantization", options=self._options(["int4", "int8"]))
        
        # Update Card content
        # ... (need to update the card content list) ...

        c["controller_enabled"] = ft.Switch(label="Enable Controller / Gamepad Input")
        c["controller_style"] = ft.Dropdown(
            label="Binding Style",
            options=self._options(["single", "chord", "sequence"]),
        )
        c["controller_binding_expr"] = ft.TextField(label="Binding Expression", hint_text="button:4")
        c["controller_sequence_window"] = ft.TextField(label="Sequence Window (ms)")
        c["controller_axis_threshold"] = ft.Slider(min=0.1, max=1.0, divisions=18, label="{value:.2f}")
        c["controller_axis_threshold_value"] = self._centered_value_text("0.60")
        # chat_open_key and voice_mute_key created via _hotkey_row

        c["send_mode"] = ft.Dropdown(
            label="Send Mode",
            options=self._options(["review_first", "auto_send"]),
        )
        c["chat_close_action"] = ft.Dropdown(
            label="Chat Close Action",
            options=self._options(["none", "esc", "chat_key"]),
        )
        c["auto_submit"] = ft.Switch(label="Auto-Submit (Press Enter)")
        c["organic_formatting_enabled"] = ft.Switch(label="Organic Formatting")
        c["output_token_limit"] = ft.Slider(min=900, max=1200, divisions=300, label="{value:.0f}")
        c["output_token_limit_value"] = self._centered_value_text("1100 tokens")
        c["draft_history_limit"] = ft.Slider(min=10, max=500, divisions=49, label="{value:.0f}")
        c["draft_history_limit_value"] = self._centered_value_text("80 drafts")
        c["long_input_message"] = ft.TextField(
            label="Long Input Notice",
            multiline=True,
            min_lines=3,
            max_lines=5,
        )
        # manual_send_hotkey and review_tts_hotkey created via _hotkey_row

        c["review_tts_enabled"] = ft.Switch(label="Enable Review TTS")
        # review_tts_hotkey created via _hotkey_row
        c["review_tts_voice_hint"] = ft.Dropdown(label="Voice Model")
        c["review_tts_speed"] = ft.Slider(min=0.5, max=3.0, divisions=50, label="{value:.2f}x")
        c["review_tts_speed_value"] = self._centered_value_text("1.50x")
        c["review_tts_sample_text"] = ft.Dropdown(
            label="TTS Sample Text",
            options=self._options(self.SAMPLE_TTS_TEXTS),
        )
        c["tts_status"] = ft.Text("", size=12, color=self._palette["muted"])

        c["audio_ducking_level"].on_change = (
            lambda e: self._on_slider_change(
                e, "audio_ducking_level_value", suffix="%", decimals=0
            )
        )
        c["audio_ducking_fallback_return"].on_change = (
            lambda e: self._on_slider_change(
                e, "audio_ducking_fallback_return_value", suffix="%", decimals=0
            )
        )
        c["controller_axis_threshold"].on_change = (
            lambda e: self._on_slider_change(
                e, "controller_axis_threshold_value", suffix="", decimals=2
            )
        )
        c["review_tts_speed"].on_change = (
            lambda e: self._on_slider_change(
                e, "review_tts_speed_value", suffix="x", decimals=2
            )
        )
        c["output_token_limit"].on_change = (
            lambda e: self._on_slider_change(
                e, "output_token_limit_value", suffix=" tokens", decimals=0
            )
        )
        c["draft_history_limit"].on_change = (
            lambda e: self._on_slider_change(
                e, "draft_history_limit_value", suffix=" drafts", decimals=0
            )
        )

        c["no_audio_min_duration"] = ft.TextField(label="No-Audio Min Duration (s)")
        c["no_audio_min_rms"] = ft.TextField(label="No-Audio Min RMS")
        c["no_audio_min_peak"] = ft.TextField(label="No-Audio Min Peak")

        c["llm_enabled"] = ft.Switch(label="Enable LLM Post-Processing")
        c["llm_enabled"].on_change = self._on_preset_related_setting_changed
        c["persona"] = ft.Dropdown(label="Persona")
        if hasattr(c["persona"], "on_select"):
            c["persona"].on_select = self._on_persona_selection_changed
        elif hasattr(c["persona"], "on_change"):
            c["persona"].on_change = self._on_persona_selection_changed
        c["true_gen"] = ft.Switch(label="TrueGen Universal Grammar")
        c["experience_preset"] = ft.Dropdown(
            label="Experience Preset",
            options=[ft.dropdown.Option(key, text=label) for key, label in self.EXPERIENCE_PRESET_OPTIONS],
        )
        if hasattr(c["experience_preset"], "on_select"):
            c["experience_preset"].on_select = self._on_experience_preset_changed
        elif hasattr(c["experience_preset"], "on_change"):
            c["experience_preset"].on_change = self._on_experience_preset_changed
        c["experience_preset_note"] = ft.Text(
            "",
            size=12,
            color=self._palette["muted"],
        )
        c["model_size"] = ft.Dropdown(
            label="Model Size",
            options=self._options(["tiny.en", "base.en", "small.en", "medium.en", "large-v3"]),
        )
        c["model_size"].on_change = self._on_preset_related_setting_changed
        c["quantization"] = ft.Dropdown(label="Quantization", options=self._options(["int4", "int8"]))
        c["quantization"].on_change = self._on_preset_related_setting_changed
        c["model_keep_llm_loaded"] = ft.Switch(label="Keep LLM Loaded")
        c["model_keep_stt_loaded"] = ft.Switch(label="Keep STT Loaded")
        c["model_keep_tts_loaded"] = ft.Switch(label="Keep TTS Loaded")
        c["use_gpu"] = ft.Switch(label="Use GPU (where available)")
        c["use_gpu"].on_change = self._on_preset_related_setting_changed
        c["hardware_estimate"] = ft.Text(
            "",
            size=12,
            color=self._palette["muted"],
        )
        c["hardware_change_preview"] = ft.Text(
            "",
            size=12,
            color=self._palette["muted"],
        )
        c["preset_cancel_button"] = ft.TextButton(
            "Cancel",
            on_click=self._on_cancel_pending_experience_preset,
        )
        c["preset_apply_button"] = ft.Button(
            "Apply Preset",
            on_click=self._on_apply_pending_experience_preset,
        )
        c["preset_pending_actions"] = ft.Row(
            [
                c["preset_cancel_button"],
                c["preset_apply_button"],
            ],
            spacing=8,
            visible=False,
        )
        c["whisper_download_model"] = ft.Dropdown(
            label="Whisper Model",
            options=self._options(["tiny.en", "base.en", "small.en", "medium.en", "large-v3"]),
        )
        c["whisper_downloaded_summary"] = ft.Text(
            "No Whisper models found in cache.",
            size=12,
            color=self._palette["muted"],
        )
        c["whisper_download_status"] = ft.Text(
            "",
            size=12,
            color=self._palette["muted"],
        )
        c["persona_create_button"] = ft.Button("Create Persona", on_click=self._on_create_persona_clicked)
        c["persona_edit_button"] = ft.OutlinedButton("Edit Persona", on_click=self._on_edit_persona_clicked)
        c["persona_delete_button"] = ft.OutlinedButton("Delete Persona", on_click=self._on_delete_persona_clicked)
        c["persona_action_row"] = ft.Row(
            [
                c["persona_create_button"],
                c["persona_edit_button"],
                c["persona_delete_button"],
            ],
            spacing=8,
            wrap=True,
        )
        c["model_catalog_status"] = ft.Text("", size=12, color=self._palette["muted"])
        c["model_catalog_rows"] = ft.Column(scroll=ft.ScrollMode.AUTO, expand=False, height=320, spacing=8)

        c["overlay_position"] = ft.Dropdown(
            label="Status Dot Position",
            options=self._options(
                ["Top-Left", "Top-Right", "Bottom-Left", "Bottom-Right", "Mid-Left", "Mid-Right"]
            ),
        )
        c["status_indicator_enabled"] = ft.Switch(label="Show Status Indicator")
        c["status_indicator_flash_enabled"] = ft.Switch(label="Flash While Recording")
        c["status_indicator_color_idle"] = ft.TextField(label="Idle Color (#RRGGBB)")
        c["status_indicator_color_listening"] = ft.TextField(label="Listening Color (#RRGGBB)")
        c["status_indicator_color_recording"] = ft.TextField(label="Recording Color (#RRGGBB)")
        c["status_indicator_color_processing"] = ft.TextField(label="Processing Color (#RRGGBB)")
        c["notification_overlay_enabled"] = ft.Switch(label="Show Notification Toasts")
        c["notification_overlay_position"] = ft.Dropdown(
            label="Notification Position",
            options=self._options(["Top-Left", "Top-Right", "Bottom-Left", "Bottom-Right", "Custom"]),
        )
        c["notification_overlay_alpha"] = ft.TextField(label="Notification Alpha")
        c["notification_overlay_bg"] = ft.TextField(label="Notification BG")
        c["notification_overlay_fg"] = ft.TextField(label="Notification FG")

        c["preview_overlay_enabled"] = ft.Switch(label="Show Live Preview Box")
        c["preview_overlay_position"] = ft.Dropdown(
            label="Preview Position",
            options=self._options(["Top-Left", "Top-Right", "Bottom-Left", "Bottom-Right", "Custom"]),
        )
        c["preview_overlay_alpha"] = ft.TextField(label="Preview Alpha")
        c["preview_overlay_bg"] = ft.TextField(label="Preview BG")
        c["preview_overlay_fg"] = ft.TextField(label="Preview FG")
        c["preview_overlay_text_bg"] = ft.TextField(label="Preview Text BG")

        general_column = ft.Column(
            [
                self._card(
                    "Core Controls",
                    [
                        self._with_help(self._hotkey_row("hotkey", "Master Hotkey", "f8"), "master_hotkey"),
                        self._with_help(
                            self._hotkey_row("force_stop_key", "Emergency Stop Key", "escape"),
                            "emergency_stop",
                        ),
                        self._with_help(c["recording_mode"], "record_mode"),
                    ],
                    target_key="hotkey_row",
                    tab_key="general",
                    help_key="core_controls",
                ),
                self._card(
                    "Audio Processing",
                    [
                        self._with_help(c["audio_ducking"], "smart_audio_ducking"),
                        ft.Text("Ducking Level (%)"),
                        self._with_help(
                            self._slider_with_value("audio_ducking_level", "audio_ducking_level_value"),
                            "ducking_level",
                        ),
                        ft.Text("Fallback Return Level (%)"),
                        self._with_help(
                            self._slider_with_value(
                                "audio_ducking_fallback_return",
                                "audio_ducking_fallback_return_value",
                            ),
                            "fallback_return",
                        ),
                    ],
                    target_key="ducking_check",
                    tab_key="general",
                    help_key="audio_processing",
                ),
                self._card(
                    "Typing Behavior",
                    [
                        ft.Text("Target Speed"),
                        self._with_help(self._slider_with_value("wpm", "wpm_label"), "target_speed"),
                        c["wpm_warning"],
                        self._with_help(c["instant_typing"], "instant_typing"),
                        self._with_help(c["sign_off"], "sign_off"),
                    ],
                    target_key="typing_behavior",
                    tab_key="general",
                    help_key="typing_behavior",
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        general_view = ft.Container(padding=4, content=general_column)

        input_column = ft.Column(
            [
                self._card(
                    "Hardware Integration",
                    [
                        self._with_help(c["controller_enabled"], "controller_enabled"),
                        self._with_help(c["controller_style"], "controller_style"),
                        self._with_help(
                            self._controller_map_row("controller_binding_expr", "Binding Expression", "button:4"),
                            "controller_binding",
                        ),
                        c["controller_sequence_window"],
                        ft.Text("Axis Threshold"),
                        self._with_help(
                            self._slider_with_value(
                                "controller_axis_threshold",
                                "controller_axis_threshold_value",
                            ),
                            "axis_threshold",
                        ),
                    ],
                    target_key="controller_check",
                    tab_key="input",
                    help_key="hardware_integration",
                ),
                self._card(
                    "Auxiliary Keys",
                    [
                        self._with_help(
                            self._hotkey_row("chat_open_key", "Chat Open Key", "enter"),
                            "chat_open_key",
                        ),
                        self._with_help(
                            self._hotkey_row("voice_mute_key", "Voice Mute Key", "v"),
                            "voice_mute_key",
                        ),
                    ],
                    target_key="aux_keys",
                    tab_key="input",
                    help_key="aux_keys",
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        input_view = ft.Container(padding=4, content=input_column)

        output_column = ft.Column(
            [
                self._card(
                    "Delivery Pipeline",
                    [
                        self._with_help(c["send_mode"], "send_mode"),
                        self._with_help(c["chat_close_action"], "chat_close_action"),
                        c["auto_submit"],
                        self._with_help(
                            self._hotkey_row("manual_send_hotkey", "Primary Action Hotkey", "f9"),
                            "primary_action_hotkey",
                        ),
                        ft.Text(
                            "F9 sends accepted drafts first. If no draft is pending, it reads highlighted text.",
                            size=12,
                            color=self._palette["muted"],
                        ),
                    ],
                    target_key="send_mode_combo",
                    tab_key="output",
                    help_key="delivery_pipeline",
                ),
                self._card(
                    "Review TTS",
                    [
                        self._with_help(c["review_tts_enabled"], "review_tts"),
                        self._with_help(
                            self._hotkey_row("review_tts_hotkey", "Review TTS Shortcut", "ctrl+shift+space"),
                            "review_tts_shortcut",
                        ),
                        c["review_tts_voice_hint"],
                        ft.Text("Playback Speed"),
                        self._with_help(
                            self._slider_with_value("review_tts_speed", "review_tts_speed_value"),
                            "review_tts_speed",
                        ),
                        c["review_tts_sample_text"],
                        ft.Row(
                            [
                                ft.Button("Test Voice", on_click=self._on_play_tts_sample),
                                ft.OutlinedButton("Stop", on_click=self._on_stop_tts_sample),
                            ],
                            spacing=8,
                        ),
                        c["tts_status"],
                    ],
                    target_key="review_tts",
                    tab_key="output",
                    help_key="review_tts",
                ),
                self._card(
                    "Token Guardrails",
                    [
                        self._with_help(c["organic_formatting_enabled"], "typing_behavior"),
                        self._with_help(
                            ft.Column(
                                [
                                    ft.Text("Output Token Limit"),
                                    self._slider_with_value("output_token_limit", "output_token_limit_value"),
                                ],
                                spacing=4,
                                tight=True,
                            ),
                            "output_token_limit",
                        ),
                        self._with_help(c["long_input_message"], "long_input_notice"),
                        self._with_help(
                            ft.Column(
                                [
                                    ft.Text("Draft History Retention"),
                                    self._slider_with_value("draft_history_limit", "draft_history_limit_value"),
                                ],
                                spacing=4,
                                tight=True,
                            ),
                            "draft_history_limit",
                        ),
                        ft.Row(
                            [
                                ft.OutlinedButton("Open Draft History", on_click=self._on_open_draft_history_clicked),
                            ],
                            spacing=8,
                        ),
                    ],
                    target_key="token_guardrails",
                    tab_key="output",
                    help_key="delivery_pipeline",
                ),
                self._card(
                    "Transcription Safeguards",
                    [
                        c["no_audio_min_duration"],
                        c["no_audio_min_rms"],
                        c["no_audio_min_peak"],
                    ],
                    help_key="transcription_safeguards",
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        output_view = ft.Container(padding=4, content=output_column)
        ai_column = ft.Column(
            [
                self._card(
                    "Inference Engine",
                    [
                        c["llm_enabled"],
                        c["persona"],
                        c["persona_action_row"],
                        c["true_gen"],
                        ft.Divider(),
                        ft.Text("LLM Model Management", size=12, weight=ft.FontWeight.BOLD),
                        c["llm_model_id"],
                        c["llm_model_buttons"],
                        c["llm_model_status"],
                        ft.Divider(),
                        c["model_size"],
                        c["quantization"],
                    ],
                    target_key="llm_check",
                    tab_key="ai",
                    help_key="inference_engine",
                ),
                self._card(
                    "Model Catalog",
                    [
                        ft.Text(
                            "Combined LLM + Whisper inventory with status, progress, selected model, and row actions.",
                            size=12,
                            color=self._palette["muted"],
                        ),
                        c["model_catalog_rows"],
                        c["model_catalog_status"],
                    ],
                    target_key="model_catalog",
                    tab_key="ai",
                    help_key="model_catalog",
                ),
                self._card(
                    "Memory Management",
                    [
                        c["model_keep_llm_loaded"],
                        c["model_keep_stt_loaded"],
                        c["model_keep_tts_loaded"],
                        c["use_gpu"],
                        ft.Text(
                            "Turning Keep Loaded off saves memory but adds a short delay while models load on demand.",
                            size=12,
                            color=self._palette["muted"],
                        ),
                    ],
                    target_key="model_size_combo",
                    tab_key="ai",
                    help_key="memory_management",
                ),
                self._card(
                    "Hardware Guidance",
                    [
                        ft.Text("Use the top Quick Preset panel for live VRAM estimates and deltas.", size=12),
                        ft.Text("Rule of thumb: keep 1-2 GB VRAM headroom for smoother runtime.", size=12),
                        ft.Text("Simple targets low hardware. Pro and Dont Use This Mode are much heavier.", size=12),
                    ],
                    tab_key="ai",
                    help_key="hardware_estimator",
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        ai_view = ft.Container(padding=4, content=ai_column)

        overlays_column = ft.Column(
            [
                self._card(
                    "Status Indicator",
                    [
                        c["overlay_position"],
                        c["status_indicator_enabled"],
                        c["status_indicator_flash_enabled"],
                        c["status_indicator_color_idle"],
                        c["status_indicator_color_listening"],
                        c["status_indicator_color_recording"],
                        c["status_indicator_color_processing"],
                    ],
                    target_key="overlay_status",
                    tab_key="overlays",
                    help_key="status_indicator",
                ),
                self._card(
                    "Notification Overlay",
                    [
                        c["notification_overlay_enabled"],
                        c["notification_overlay_position"],
                        c["notification_overlay_alpha"],
                        c["notification_overlay_bg"],
                        c["notification_overlay_fg"],
                    ],
                    target_key="overlay_notification",
                    tab_key="overlays",
                    help_key="notification_overlay",
                ),
                self._card(
                    "Preview Overlay",
                    [
                        c["preview_overlay_enabled"],
                        c["preview_overlay_position"],
                        c["preview_overlay_alpha"],
                        c["preview_overlay_bg"],
                        c["preview_overlay_fg"],
                        c["preview_overlay_text_bg"],
                    ],
                    target_key="overlay_preview",
                    tab_key="overlays",
                    help_key="preview_overlay",
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )
        overlays_view = ft.Container(padding=4, content=overlays_column)

        self._tour_tab_scrollers = {
            "general": general_column,
            "input": input_column,
            "output": output_column,
            "ai": ai_column,
            "overlays": overlays_column,
        }
        self._tab_views = {
            "general": general_view,
            "input": input_view,
            "output": output_view,
            "ai": ai_view,
            "overlays": overlays_view,
        }
        self._tab_buttons = {}
        tab_buttons = []
        for index, tab_key in enumerate(self._tab_order):
            button = ft.OutlinedButton(
                self._tab_labels.get(tab_key, tab_key.title()),
                on_click=lambda _event, idx=index: self._set_active_tab(idx, refresh=True),
            )
            self._tab_buttons[index] = button
            tab_buttons.append(button)

        self._tab_content_host = ft.Container(
            expand=True,
            content=self._tab_views.get("general"),
        )
        self._tabs = ft.Container(
            bgcolor=self._palette["surface"],
            border=ft.Border.all(1, self._palette["card_border"]),
            border_radius=14,
            padding=12,
            expand=True,
            content=ft.Column(
                [
                    ft.Row(tab_buttons, wrap=True, spacing=8),
                    self._tab_content_host,
                ],
                spacing=10,
                expand=True,
            ),
        )
        self._set_active_tab(0, refresh=False)
        self._refresh_whisper_download_status()
        self._refresh_model_catalog()
        self._sync_persona_action_buttons()
        self._refresh_experience_preset_ui()

    def _build_profile_bar(self):
        c = self._controls
        return ft.Container(
            bgcolor=self._palette["surface"],
            border=ft.Border.all(1, self._palette["card_border"]),
            border_radius=14,
            padding=12,
            content=ft.Row(
                [
                    ft.Button("Save", on_click=self._on_save_clicked),
                    c["profile"],
                    ft.Button("New", on_click=self._on_new_profile_clicked),
                    ft.OutlinedButton("Delete", on_click=self._on_delete_profile_clicked),
                ],
                spacing=8,
                wrap=True,
            ),
        )

    def _refresh_profile_options(self):
        c = self._controls
        profiles = list_profiles()
        if self.current_profile not in profiles:
            self.current_profile = "Default"
        c["profile"].options = self._options(profiles)
        c["profile"].value = self.current_profile

    def _is_true_janitor_selected(self):
        selected = str((self._controls.get("persona").value if self._controls.get("persona") else "") or "").strip()
        return selected.lower() == "true janitor"

    def _sync_persona_action_buttons(self):
        controls = self._controls or {}
        disable_actions = self._is_true_janitor_selected()
        for key in ("persona_edit_button", "persona_delete_button"):
            button = controls.get(key)
            if button is None:
                continue
            try:
                button.disabled = bool(disable_actions)
            except Exception:
                pass

    @classmethod
    def _allowed_experience_presets(cls):
        return {key for key, _label in cls.EXPERIENCE_PRESET_OPTIONS}

    @classmethod
    def _infer_experience_preset(cls, cfg):
        if not isinstance(cfg, dict):
            return "custom"

        explicit = str(cfg.get("experience_preset", "") or "").strip().lower()
        if explicit in cls._allowed_experience_presets():
            return explicit

        llm_enabled = bool(cfg.get("llm_enabled", True))
        model_size = str(cfg.get("model_size", "") or "").strip().lower()
        llm_model_id = str(cfg.get("llm_model_id", "") or "").strip().lower()
        quantization = str(cfg.get("quantization", "") or "").strip().lower()

        if (not llm_enabled) and model_size == "tiny.en":
            return "simple"
        if model_size == "base.en" and llm_model_id == "gemma-3-4b-q4" and quantization == "int4":
            return "plus"
        if model_size == "small.en" and llm_model_id == "gemma-3-4b-q8" and quantization == "int8":
            return "pro"
        if model_size == "large-v3" and llm_model_id == "gemma-3-12b-q4" and quantization == "int4":
            return "dont_use"
        return "custom"

    def _set_active_experience_preset(self, preset_key: str):
        key = str(preset_key or "custom").strip().lower() or "custom"
        if key not in self._allowed_experience_presets():
            key = "custom"
        self._active_experience_preset = key
        return key

    @classmethod
    def _preset_label(cls, preset_key: str) -> str:
        key = str(preset_key or "custom").strip().lower() or "custom"
        if key in cls.EXPERIENCE_PRESET_DEFINITIONS:
            return str(cls.EXPERIENCE_PRESET_DEFINITIONS[key].get("label", key) or key)
        for option_key, option_label in cls.EXPERIENCE_PRESET_OPTIONS:
            if option_key == key:
                return option_label
        return key.title()

    def _snapshot_for_preset(self, preset_key: str | None = None):
        controls = self._controls or {}
        snapshot = {
            "llm_enabled": bool(getattr(controls.get("llm_enabled"), "value", True)),
            "model_size": str(getattr(controls.get("model_size"), "value", "") or "").strip().lower() or "base.en",
            "llm_model_id": str(getattr(controls.get("llm_model_id"), "value", "") or "").strip(),
            "use_gpu": bool(getattr(controls.get("use_gpu"), "value", True)),
        }
        key = str(preset_key or "").strip().lower()
        preset = self.EXPERIENCE_PRESET_DEFINITIONS.get(key, {})
        values = dict(preset.get("values", {}) or {})
        if "llm_enabled" in values:
            snapshot["llm_enabled"] = bool(values.get("llm_enabled"))
        if "model_size" in values:
            snapshot["model_size"] = str(values.get("model_size", snapshot["model_size"]) or "").strip().lower() or snapshot["model_size"]
        if "llm_model_id" in values:
            snapshot["llm_model_id"] = str(values.get("llm_model_id", snapshot["llm_model_id"]) or "").strip() or snapshot["llm_model_id"]
        if "use_gpu" in values:
            snapshot["use_gpu"] = bool(values.get("use_gpu"))
        return snapshot

    def _estimate_snapshot_vram(self, snapshot):
        if not isinstance(snapshot, dict):
            snapshot = {}
        use_gpu = bool(snapshot.get("use_gpu", True))
        llm_enabled = bool(snapshot.get("llm_enabled", True))
        whisper_size = str(snapshot.get("model_size", "base.en") or "base.en").strip().lower()
        llm_model_id = str(snapshot.get("llm_model_id", "") or "").strip()

        whisper_vram = float(self.WHISPER_VRAM_ESTIMATE_GB.get(whisper_size, 1.0))
        llm_vram = 0.0
        if llm_enabled:
            row = AVAILABLE_MODELS.get(llm_model_id, {})
            size_mb = self._safe_float(row.get("size_mb", 0), 0.0, minimum=0.0)
            llm_vram = float(size_mb / 1024.0) * 1.18 if size_mb > 0 else 0.0

        total = llm_vram + whisper_vram
        recommended = int(math.ceil(total + (1.0 if llm_enabled else 0.5)))
        return {
            "use_gpu": use_gpu,
            "llm_enabled": llm_enabled,
            "whisper_size": whisper_size,
            "llm_model_id": llm_model_id,
            "whisper_vram": whisper_vram,
            "llm_vram": llm_vram,
            "total_vram": total,
            "recommended_vram": recommended,
        }

    def _set_pending_experience_preset(self, target_key: str, previous_key: str | None = None):
        target = str(target_key or "").strip().lower()
        if target not in self.EXPERIENCE_PRESET_DEFINITIONS:
            return False

        active = str(
            previous_key
            if previous_key is not None
            else getattr(self, "_active_experience_preset", "custom")
        ).strip().lower() or "custom"
        active = self._set_active_experience_preset(active)
        self._selected_preset_current = active
        self._selected_preset_pending = target

        preset_control = self._controls.get("experience_preset")
        if preset_control is not None:
            self._applying_experience_preset = True
            try:
                preset_control.value = target
            finally:
                self._applying_experience_preset = False
        return True

    def _clear_pending_experience_preset(self, reset_dropdown: bool = True):
        active = str(getattr(self, "_active_experience_preset", "custom") or "custom").strip().lower() or "custom"
        active = self._set_active_experience_preset(active)
        self._selected_preset_current = active
        self._selected_preset_pending = None

        preset_control = self._controls.get("experience_preset")
        if reset_dropdown and preset_control is not None:
            self._applying_experience_preset = True
            try:
                preset_control.value = active
            finally:
                self._applying_experience_preset = False

    def _on_cancel_pending_experience_preset(self, _event=None):
        self._clear_pending_experience_preset(reset_dropdown=True)
        self._refresh_experience_preset_ui()
        self._safe_update()

    def _on_apply_pending_experience_preset(self, _event=None):
        pending = str(getattr(self, "_selected_preset_pending", "") or "").strip().lower()
        if pending in self.EXPERIENCE_PRESET_DEFINITIONS:
            self._apply_experience_preset(pending)
            return
        self._clear_pending_experience_preset(reset_dropdown=True)
        self._refresh_experience_preset_ui()
        self._safe_update()

    def _on_preset_related_setting_changed(self, _event=None):
        if bool(getattr(self, "_applying_experience_preset", False)):
            return

        preset_control = self._controls.get("experience_preset")
        if preset_control is not None:
            current = str(preset_control.value or "custom").strip().lower() or "custom"
            if current != "custom":
                preset_control.value = "custom"
        self._set_active_experience_preset("custom")
        self._selected_preset_current = "custom"
        self._selected_preset_pending = None

        self._refresh_experience_preset_ui()
        self._safe_update()

    def _on_experience_preset_changed(self, event):
        if bool(getattr(self, "_applying_experience_preset", False)):
            return
        control = getattr(event, "control", None)
        allowed = self._allowed_experience_presets()
        control_selected = str((getattr(control, "value", "") if control is not None else "") or "").strip().lower()
        data_selected = str(getattr(event, "data", "") or "").strip().strip('"').strip("'").lower()

        if data_selected in allowed:
            selected = data_selected
        else:
            selected = control_selected or data_selected

        if control is not None and selected:
            try:
                control.value = selected
            except Exception:
                pass
        if selected not in allowed:
            selected = "custom"

        previous = str(getattr(self, "_active_experience_preset", "custom") or "custom").strip().lower() or "custom"
        if previous not in allowed:
            previous = "custom"

        if selected == previous:
            self._selected_preset_current = previous
            self._selected_preset_pending = None
            self._refresh_experience_preset_ui()
            self._safe_update()
            return

        if selected == "custom":
            self._set_active_experience_preset("custom")
            self._selected_preset_current = "custom"
            self._selected_preset_pending = None
            self._refresh_experience_preset_ui()
            self._safe_update()
            return

        self._set_pending_experience_preset(selected, previous)
        self._refresh_experience_preset_ui()
        self._safe_update()

    def _apply_experience_preset(self, preset_key: str):
        key = str(preset_key or "").strip().lower()
        preset = self.EXPERIENCE_PRESET_DEFINITIONS.get(key)
        if not preset:
            return

        controls = self._controls or {}
        values = dict(preset.get("values", {}) or {})

        self._applying_experience_preset = True
        try:
            for control_key, value in values.items():
                control = controls.get(control_key)
                if control is None:
                    continue
                try:
                    control.value = value
                except Exception:
                    pass

            persona_control = controls.get("persona")
            if persona_control is not None:
                try:
                    self._refresh_persona_options()
                    persona_names = [
                        str(getattr(option, "key", "") or getattr(option, "text", "") or "").strip()
                        for option in (getattr(persona_control, "options", None) or [])
                    ]
                    target_persona = str(values.get("persona", "True Janitor") or "True Janitor").strip()
                    if target_persona not in persona_names:
                        target_persona = "True Janitor"
                    persona_control.value = target_persona
                except Exception:
                    pass
        finally:
            self._applying_experience_preset = False

        preset_control = controls.get("experience_preset")
        if preset_control is not None:
            preset_control.value = key
        self._set_active_experience_preset(key)
        self._selected_preset_current = key
        self._selected_preset_pending = None

        if controls.get("wpm") is not None:
            wpm = self._safe_int(controls["wpm"].value, 70, minimum=10, maximum=1200)
            controls["wpm"].value = wpm
            self._set_value_label_text("wpm_label", f"{wpm} WPM")

        self._sync_persona_action_buttons()
        self._refresh_experience_preset_ui()
        self._toast(f"Applied {preset.get('label', key)}.")
        self._safe_update()

    def _refresh_experience_preset_ui(self):
        controls = self._controls or {}
        preset_control = controls.get("experience_preset")
        note_control = controls.get("experience_preset_note")
        estimate_control = controls.get("hardware_estimate")
        delta_control = controls.get("hardware_change_preview")
        if preset_control is None:
            return

        selected = str(preset_control.value or "custom").strip().lower() or "custom"
        if selected not in self._allowed_experience_presets():
            selected = "custom"
            preset_control.value = selected

        active = str(getattr(self, "_active_experience_preset", "custom") or "custom").strip().lower() or "custom"
        if active not in self._allowed_experience_presets():
            active = self._set_active_experience_preset("custom")
        self._selected_preset_current = active
        pending = str(getattr(self, "_selected_preset_pending", "") or "").strip().lower()
        if pending not in self.EXPERIENCE_PRESET_DEFINITIONS:
            pending = ""
            self._selected_preset_pending = None

        if note_control is not None:
            display_key = pending or selected
            if display_key == "custom":
                note_control.value = "Custom mode: manual settings are active."
            else:
                preset = self.EXPERIENCE_PRESET_DEFINITIONS.get(display_key, {})
                prefix = "Pending switch: " if pending else ""
                note_control.value = prefix + str(preset.get("description", "") or "").strip()
            if display_key == "dont_use":
                note_control.color = "#f59e0b"
            else:
                note_control.color = self._palette["muted"]

        current_est = self._estimate_snapshot_vram(self._snapshot_for_preset(None))
        if estimate_control is not None:
            estimate_control.value = self._estimate_hardware_requirements_text()
        if delta_control is not None:
            if pending:
                target_est = self._estimate_snapshot_vram(self._snapshot_for_preset(pending))
                delta = float(target_est["total_vram"] - current_est["total_vram"])
                sign = "+" if delta >= 0 else "-"
                delta_control.value = (
                    f"Pending switch to {self._preset_label(pending)}: {sign}{abs(delta):.1f} GB "
                    f"(~{current_est['total_vram']:.1f} -> ~{target_est['total_vram']:.1f} GB)"
                )
                delta_control.color = "#f59e0b" if delta > 0 else self._palette["muted"]
            else:
                delta_control.value = "No pending preset switch."
                delta_control.color = self._palette["muted"]

        action_row = controls.get("preset_pending_actions")
        apply_button = controls.get("preset_apply_button")
        if apply_button is not None:
            try:
                apply_button.text = (
                    f"Apply {self._preset_label(pending)}" if pending else "Apply Preset"
                )
            except Exception:
                pass
        if action_row is not None:
            try:
                action_row.visible = bool(pending)
            except Exception:
                pass

    def _estimate_hardware_requirements_text(self) -> str:
        estimate = self._estimate_snapshot_vram(self._snapshot_for_preset(None))
        if not estimate["use_gpu"]:
            return (
                f"Current model-memory estimate: ~{estimate['total_vram']:.1f} GB (CPU mode). "
                f"VRAM is optional, but 16-32 GB system RAM is recommended."
            )

        if estimate["llm_enabled"]:
            return (
                f"Current VRAM estimate: ~{estimate['total_vram']:.1f} GB "
                f"(LLM {estimate['llm_vram']:.1f} + Whisper {estimate['whisper_vram']:.1f}). "
                f"Recommended GPU VRAM: {estimate['recommended_vram']} GB or higher."
            )
        return (
            f"Current VRAM estimate: ~{estimate['whisper_vram']:.1f} GB for Whisper ({estimate['whisper_size']}). "
            f"Recommended GPU VRAM: {estimate['recommended_vram']} GB or higher."
        )

    def _on_persona_selection_changed(self, _event=None):
        self._sync_persona_action_buttons()
        self._on_preset_related_setting_changed(_event)

    def _refresh_persona_options(self):
        names = get_fast_lane_preset_names()
        if not names:
            names = ["True Janitor"]
        self._controls["persona"].options = self._options(names)
        if self._controls["persona"].value not in names:
            self._controls["persona"].value = names[0]
        self._sync_persona_action_buttons()

    def _refresh_tts_voice_options(self):
        values = []
        if callable(self.get_tts_voice_options):
            try:
                for option in self.get_tts_voice_options() or []:
                    text = str(option or "").strip()
                    if text and text not in values:
                        values.append(text)
            except Exception as exc:
                logging.error("Failed to resolve runtime TTS voices: %s", exc)

        if not values:
            values = list(self.DEFAULT_TTS_VOICES)

        current = (self._controls["review_tts_voice_hint"].value or "").strip()
        if current and current not in values:
            values.insert(0, current)

        self._controls["review_tts_voice_hint"].options = self._options(values)
        if not current and values:
            self._controls["review_tts_voice_hint"].value = values[0]

    def _on_profile_changed(self, event):
        chosen = (event.control.value or "").strip()
        if not chosen:
            return
        self.current_profile = chosen
        try:
            set_last_active_profile(self.current_profile)
        except Exception:
            pass
        self._load_settings()
        self._safe_update()

    def _sync_tab_button_styles(self):
        for index, button in self._tab_buttons.items():
            is_active = index == self._active_tab_index
            button.style = ft.ButtonStyle(
                color="#042f2e" if is_active else self._palette["muted"],
                bgcolor=self._palette["accent"] if is_active else self._palette["card"],
                side=ft.BorderSide(1, self._palette["accent"] if is_active else self._palette["card_border"]),
                shape=ft.RoundedRectangleBorder(radius=10),
                padding=ft.Padding.symmetric(horizontal=14, vertical=10),
            )

    def _set_active_tab(self, tab_index: int, refresh: bool = False):
        if tab_index < 0 or tab_index >= len(self._tab_order):
            return
        self._active_tab_index = tab_index
        tab_key = self._tab_order[tab_index]
        if self._tab_content_host:
            self._tab_content_host.content = self._tab_views.get(tab_key)
        self._sync_tab_button_styles()
        if refresh:
            self._safe_update()

    def _on_slider_change(self, event, label_key, suffix="", decimals=0):
        value_text = self._format_slider_value(event.control.value, suffix=suffix, decimals=decimals)
        self._set_value_label_text(label_key, value_text)
        if self._page:
            self._safe_update()

    def _on_wpm_slider_changed(self, event):
        wpm = self._safe_int(event.control.value, 70, minimum=10, maximum=1200)
        self._set_value_label_text("wpm_label", f"{wpm} WPM")
        
        warning = self._controls.get("wpm_warning")
        if warning:
            if wpm > 150:
                 warning.value = "?? High speed may trigger bot detection!"
                 warning.visible = True
            else:
                 warning.visible = False
                 
        self._safe_update()

    def _refresh_llm_model_options(self):
         from model_manager import AVAILABLE_MODELS
         c = self._controls
         model_dropdown = c.get("llm_model_id")
         if not model_dropdown:
             return
             
         options = [key for key in AVAILABLE_MODELS.keys()]
         model_dropdown.options = self._options(options)
         
         from utils import load_profile
         profile = load_profile(self.current_profile)
         current = profile.get("llm_model_id")
         if current in options:
             model_dropdown.value = current
         elif not model_dropdown.value:
             model_dropdown.value = "gemma-3-4b-q4" # Default

    def _on_llm_model_action(self, action):
        from model_manager import check_and_download_resources, check_model_exists, delete_model
        
        model_id = self._controls["llm_model_id"].value
        if not model_id:
            return

        status_lbl = self._controls["llm_model_status"]
        model_state = getattr(self, "_model_catalog_state", {})
        if not isinstance(model_state, dict):
            model_state = {}
            self._model_catalog_state = model_state
        
        if action == "check":
            exists = check_model_exists(model_id)
            status_lbl.value = f"Model '{model_id}' {'is installed.' if exists else 'not found.'}"
            model_state[f"llm:{model_id}"] = {"status": "installed" if exists else "missing", "percent": 100.0 if exists else 0.0}
        elif action == "delete":
             success, msg = delete_model(model_id)
             status_lbl.value = msg
             model_state[f"llm:{model_id}"] = {"status": "deleted" if success else "error", "percent": 0.0}
        elif action == "download":
             status_lbl.value = f"Downloading {model_id}..."
             model_state[f"llm:{model_id}"] = {"status": "starting", "percent": 0.0}
             self._safe_update()
             # Run in thread to not block UI
             import threading

             def _on_progress(payload):
                 row = payload if isinstance(payload, dict) else {}
                 status = str(row.get("status", "") or "").strip() or "downloading"
                 percent = self._safe_float(row.get("percent", 0.0), 0.0, minimum=0.0, maximum=100.0)
                 message = str(row.get("message", "") or "").strip()
                 model_state[f"llm:{model_id}"] = {"status": status, "percent": percent, "message": message}
                 self._invoke_ui_callback(self._refresh_model_catalog, "llm_catalog_progress")

             def _dl():
                 try:
                     result = check_and_download_resources(model_id, progress_callback=_on_progress)
                     ok = bool(result.get("ok", False)) if isinstance(result, dict) else False
                     message = (
                         str(result.get("message", "")).strip()
                         if isinstance(result, dict)
                         else ""
                     )
                     if not ok:
                         model_state[f"llm:{model_id}"] = {
                             "status": "error",
                             "percent": 0.0,
                             "message": message or f"Failed to download {model_id}.",
                         }
                         self._invoke_ui_callback(
                             lambda: setattr(
                                 status_lbl,
                                 "value",
                                 message or f"Failed to download {model_id}.",
                             ),
                             "dl_fail",
                         )
                         return
                     self._invoke_ui_callback(
                         lambda: setattr(status_lbl, "value", message or f"Downloaded {model_id}"),
                         "dl_complete",
                     )
                 except Exception as e:
                     model_state[f"llm:{model_id}"] = {"status": "error", "percent": 0.0, "message": str(e)}
                     self._invoke_ui_callback(lambda: setattr(status_lbl, "value", f"Download failed: {e}"), "dl_fail")
             threading.Thread(target=_dl, daemon=True).start()
             
        self._refresh_model_catalog()
        self._safe_update()

    def _on_play_tts_sample(self, _event):
        if not callable(self.on_tts_preview):
            self._controls["tts_status"].value = "TTS sample preview is unavailable in this runtime."
            self._safe_update()
            return

        text = (self._controls["review_tts_sample_text"].value or self.SAMPLE_TTS_TEXTS[0]).strip()
        voice_hint = (self._controls["review_tts_voice_hint"].value or "english").strip() or "english"
        speed = self._safe_float(self._controls["review_tts_speed"].value, 1.5, minimum=0.5, maximum=3.0)
        self._controls["review_tts_speed"].value = speed

        try:
            result = self.on_tts_preview(text, speed, voice_hint) or {}
        except Exception as exc:
            self._controls["tts_status"].value = f"TTS sample failed: {exc}"
            self._safe_update()
            return

        if not isinstance(result, dict):
            result = {"ok": bool(result), "backend": "unknown", "message": ""}

        if result.get("ok", False):
            backend = str(result.get("backend", "unknown"))
            self._controls["tts_status"].value = f"Playing sample via {backend}."
        else:
            self._controls["tts_status"].value = str(result.get("message", "TTS sample playback failed."))
        self._safe_update()

    def _on_stop_tts_sample(self, _event):
        if callable(self.on_tts_stop):
            try:
                self.on_tts_stop()
            except Exception as exc:
                self._controls["tts_status"].value = f"Failed to stop sample: {exc}"
                self._safe_update()
                return
        self._controls["tts_status"].value = "Sample playback stopped."
        self._safe_update()

    def _refresh_whisper_download_status(self):
        controls = self._controls
        model_control = controls.get("whisper_download_model")
        summary_control = controls.get("whisper_downloaded_summary")
        status_control = controls.get("whisper_download_status")
        if not model_control or not summary_control or not status_control:
            return

        fallback_models = ["tiny.en", "base.en", "small.en", "medium.en", "large-v3"]
        if not callable(getattr(self, "get_whisper_download_status", None)):
            model_control.options = self._options(fallback_models)
            if not model_control.value:
                model_control.value = fallback_models[1]
            summary_control.value = "Whisper download manager is unavailable in this runtime."
            return

        try:
            result = self.get_whisper_download_status() or {}
        except Exception as exc:
            summary_control.value = f"Failed to inspect Whisper cache: {exc}"
            return

        models = result.get("models", [])
        options = []
        installed = []
        for row in models if isinstance(models, list) else []:
            model_size = str((row or {}).get("model_size", "")).strip()
            if not model_size:
                continue
            if model_size not in options:
                options.append(model_size)
            if bool((row or {}).get("installed", False)):
                installed.append(model_size)

        if not options:
            options = list(fallback_models)

        prior = (model_control.value or "").strip()
        current_profile_model = str((controls.get("model_size").value if controls.get("model_size") else "") or "").strip()
        model_control.options = self._options(options)
        if prior in options:
            model_control.value = prior
        elif current_profile_model in options:
            model_control.value = current_profile_model
        else:
            model_control.value = options[0]

        summary = str(result.get("summary", "") or "").strip()
        if not summary:
            if installed:
                summary = f"Installed: {', '.join(installed)}"
            else:
                summary = "No Whisper models found in cache."
        summary_control.value = summary
        self._refresh_model_catalog()

    def _on_refresh_whisper_downloads(self, _event):
        self._refresh_whisper_download_status()
        self._controls["whisper_download_status"].value = "Whisper cache refreshed."
        self._refresh_model_catalog()
        self._safe_update()

    def _on_test_whisper_model(self, _event):
        callback = getattr(self, "on_test_whisper_model", None)
        if not callable(callback):
            self._controls["whisper_download_status"].value = "Whisper model test is unavailable in this runtime."
            self._safe_update()
            return

        selected = str(self._controls["whisper_download_model"].value or "").strip() or "base.en"
        try:
            result = callback(selected) or {}
        except Exception as exc:
            self._controls["whisper_download_status"].value = f"Whisper model test failed: {exc}"
            self._safe_update()
            return

        ok = bool(result.get("ok", False))
        message = str(result.get("message", "") or "").strip() or (
            f"Whisper '{selected}' test {'passed' if ok else 'failed'}."
        )
        self._controls["whisper_download_status"].value = message
        self._refresh_model_catalog()
        self._safe_update()

    def _on_uninstall_whisper_model_clicked(self, _event):
        callback = getattr(self, "on_uninstall_whisper_model", None)
        if not callable(callback):
            self._controls["whisper_download_status"].value = "Whisper uninstall is unavailable in this runtime."
            self._safe_update()
            return

        selected = str(self._controls["whisper_download_model"].value or "").strip() or "base.en"

        def _close(_):
            self._close_dialog(key=self.MODAL_KEY_WHISPER_UNINSTALL)

        def _confirm(_):
            try:
                result = callback(selected) or {}
                ok = bool(result.get("ok", False))
                message = str(result.get("message", "") or "").strip() or (
                    f"Whisper '{selected}' uninstall {'completed' if ok else 'failed'}."
                )
                self._controls["whisper_download_status"].value = message
            except Exception as exc:
                self._controls["whisper_download_status"].value = f"Uninstall failed: {exc}"
            self._close_dialog(key=self.MODAL_KEY_WHISPER_UNINSTALL)
            self._refresh_whisper_download_status()
            self._refresh_model_catalog()
            self._safe_update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Uninstall Whisper Model"),
            content=ft.Text(f"Uninstall cached Whisper model '{selected}' from this computer?"),
            actions=[
                ft.TextButton("Cancel", on_click=_close),
                ft.Button("Uninstall", on_click=_confirm),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=lambda _event: None,
        )
        self._show_dialog(dialog, key=self.MODAL_KEY_WHISPER_UNINSTALL)

    def _ensure_model_catalog_state(self):
        if not isinstance(getattr(self, "_model_catalog_state", None), dict):
            self._model_catalog_state = {}
        return self._model_catalog_state

    def _run_llm_action_for(self, model_id, action):
        self._controls["llm_model_id"].value = model_id
        self._on_llm_model_action(action)

    def _set_llm_model_selection(self, model_id):
        self._controls["llm_model_id"].value = model_id
        self._controls["llm_model_status"].value = f"Selected {model_id}."
        self._refresh_model_catalog()
        self._safe_update()

    def _set_whisper_model_selection(self, model_size):
        self._controls["model_size"].value = model_size
        self._controls["whisper_download_model"].value = model_size
        self._controls["whisper_download_status"].value = f"Selected Whisper model '{model_size}'."
        self._refresh_model_catalog()
        self._safe_update()

    def _on_download_whisper_model_action(self, model_size):
        callback = getattr(self, "on_download_whisper_model", None)
        if not callable(callback):
            self._controls["whisper_download_status"].value = "Whisper download is unavailable in this runtime."
            self._safe_update()
            return

        selected = str(model_size or "").strip() or "base.en"
        self._controls["whisper_download_model"].value = selected
        state = self._ensure_model_catalog_state()
        state[f"whisper:{selected}"] = {"status": "starting", "percent": 0.0, "message": f"Downloading {selected}..."}
        self._refresh_model_catalog()
        self._safe_update()

        import threading

        def _progress(payload):
            row = payload if isinstance(payload, dict) else {}
            status = str(row.get("status", "") or "").strip() or "downloading"
            percent = self._safe_float(row.get("percent", 0.0), 0.0, minimum=0.0, maximum=100.0)
            message = str(row.get("message", "") or "").strip()
            state[f"whisper:{selected}"] = {"status": status, "percent": percent, "message": message}
            self._invoke_ui_callback(self._refresh_model_catalog, "whisper_catalog_progress")

        def _worker():
            try:
                result = callback(selected, progress_callback=_progress) or {}
                ok = bool(result.get("ok", False))
                message = str(result.get("message", "") or "").strip() or (
                    f"Whisper '{selected}' download {'completed' if ok else 'failed'}."
                )
                state[f"whisper:{selected}"] = {
                    "status": "complete" if ok else "error",
                    "percent": 100.0 if ok else 0.0,
                    "message": message,
                }
                self._invoke_ui_callback(lambda: setattr(self._controls["whisper_download_status"], "value", message), "whisper_download_status")
            except Exception as exc:
                state[f"whisper:{selected}"] = {"status": "error", "percent": 0.0, "message": str(exc)}
                self._invoke_ui_callback(
                    lambda: setattr(self._controls["whisper_download_status"], "value", f"Whisper download failed: {exc}"),
                    "whisper_download_fail",
                )
            finally:
                self._invoke_ui_callback(self._refresh_whisper_download_status, "whisper_refresh_after_download")
                self._invoke_ui_callback(self._refresh_model_catalog, "whisper_refresh_catalog")

        threading.Thread(target=_worker, daemon=True).start()

    def _catalog_cell(self, value, width=120):
        return ft.Container(content=ft.Text(str(value), size=11, color=self._palette["text"]), width=width)

    def _refresh_model_catalog(self):
        controls = self._controls
        host = controls.get("model_catalog_rows")
        if host is None:
            return

        state = self._ensure_model_catalog_state()
        rows = [
            ft.Row(
                [
                    self._catalog_cell("Model", width=210),
                    self._catalog_cell("Type", width=52),
                    self._catalog_cell("Size", width=80),
                    self._catalog_cell("Installed", width=64),
                    self._catalog_cell("Selected", width=64),
                    ft.Container(content=ft.Text("Status / Actions", size=11, color=self._palette["muted"]), expand=True),
                ],
                spacing=8,
            )
        ]

        from model_manager import check_model_exists

        selected_llm = str((controls.get("llm_model_id").value if controls.get("llm_model_id") else "") or "").strip()
        for model_id, info in AVAILABLE_MODELS.items():
            installed = bool(check_model_exists(model_id))
            key = f"llm:{model_id}"
            row_state = state.get(key, {})
            percent = self._safe_float(row_state.get("percent", 100.0 if installed else 0.0), 0.0, minimum=0.0, maximum=100.0)
            status = str(row_state.get("message", "") or "").strip()
            if not status:
                status = "Installed" if installed else "Not installed"
            selected = selected_llm == model_id
            size_label = f"{int(info.get('size_mb', 0) or 0)} MB"

            rows.append(
                ft.Container(
                    border=ft.Border.all(1, self._palette["card_border"]),
                    border_radius=8,
                    padding=8,
                    bgcolor="#1f2937" if selected else self._palette["card"],
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    self._catalog_cell(info.get("name", model_id), width=210),
                                    self._catalog_cell("LLM", width=52),
                                    self._catalog_cell(size_label, width=80),
                                    self._catalog_cell("Yes" if installed else "No", width=64),
                                    self._catalog_cell("Yes" if selected else "No", width=64),
                                    ft.Container(content=ft.Text(status, size=11, color=self._palette["muted"]), expand=True),
                                ],
                                spacing=8,
                                wrap=False,
                            ),
                            ft.Row(
                                [
                                    ft.Container(
                                        width=220,
                                        content=ft.ProgressBar(value=float(percent / 100.0), color=self._palette["accent"], bgcolor="#334155"),
                                    ),
                                    ft.Text(f"{percent:.0f}%", size=11, color=self._palette["muted"]),
                                    ft.Row(
                                        [
                                            ft.TextButton("Select", on_click=lambda _e, mid=model_id: self._set_llm_model_selection(mid)),
                                            ft.TextButton("Check", on_click=lambda _e, mid=model_id: self._run_llm_action_for(mid, "check")),
                                            ft.TextButton("Download", on_click=lambda _e, mid=model_id: self._run_llm_action_for(mid, "download")),
                                            ft.TextButton("Delete", on_click=lambda _e, mid=model_id: self._run_llm_action_for(mid, "delete")),
                                        ],
                                        spacing=2,
                                        wrap=True,
                                    ),
                                ],
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ],
                        spacing=6,
                        tight=True,
                    ),
                )
            )

        selected_whisper = str((controls.get("model_size").value if controls.get("model_size") else "") or "").strip()
        whisper_result = {}
        if callable(getattr(self, "get_whisper_download_status", None)):
            try:
                whisper_result = self.get_whisper_download_status() or {}
            except Exception as exc:
                controls["model_catalog_status"].value = f"Failed loading whisper catalog: {exc}"

        whisper_models = whisper_result.get("models", []) if isinstance(whisper_result, dict) else []
        for row in whisper_models if isinstance(whisper_models, list) else []:
            model_size = str((row or {}).get("model_size", "")).strip()
            if not model_size:
                continue
            installed = bool((row or {}).get("installed", False))
            size_bytes = int((row or {}).get("size_bytes", 0) or 0)
            size_label = f"{round(size_bytes / (1024 * 1024), 1)} MB" if size_bytes > 0 else "-"
            key = f"whisper:{model_size}"
            row_state = state.get(key, {})
            percent = self._safe_float(row_state.get("percent", 100.0 if installed else 0.0), 0.0, minimum=0.0, maximum=100.0)
            status = str(row_state.get("message", "") or "").strip()
            if not status:
                status = "Installed" if installed else "Not installed"
            selected = selected_whisper == model_size

            rows.append(
                ft.Container(
                    border=ft.Border.all(1, self._palette["card_border"]),
                    border_radius=8,
                    padding=8,
                    bgcolor="#1f2937" if selected else self._palette["card"],
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    self._catalog_cell(model_size, width=210),
                                    self._catalog_cell("Whisper", width=52),
                                    self._catalog_cell(size_label, width=80),
                                    self._catalog_cell("Yes" if installed else "No", width=64),
                                    self._catalog_cell("Yes" if selected else "No", width=64),
                                    ft.Container(content=ft.Text(status, size=11, color=self._palette["muted"]), expand=True),
                                ],
                                spacing=8,
                                wrap=False,
                            ),
                            ft.Row(
                                [
                                    ft.Container(
                                        width=220,
                                        content=ft.ProgressBar(value=float(percent / 100.0), color=self._palette["accent"], bgcolor="#334155"),
                                    ),
                                    ft.Text(f"{percent:.0f}%", size=11, color=self._palette["muted"]),
                                    ft.Row(
                                        [
                                            ft.TextButton("Select", on_click=lambda _e, ms=model_size: self._set_whisper_model_selection(ms)),
                                            ft.TextButton("Download", on_click=lambda _e, ms=model_size: self._on_download_whisper_model_action(ms)),
                                            ft.TextButton(
                                                "Test",
                                                on_click=lambda _e, ms=model_size: (
                                                    setattr(self._controls["whisper_download_model"], "value", ms),
                                                    self._on_test_whisper_model(None),
                                                ),
                                            ),
                                            ft.TextButton(
                                                "Uninstall",
                                                on_click=lambda _e, ms=model_size: (
                                                    setattr(self._controls["whisper_download_model"], "value", ms),
                                                    self._on_uninstall_whisper_model_clicked(None),
                                                ),
                                            ),
                                        ],
                                        spacing=2,
                                        wrap=True,
                                    ),
                                ],
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ],
                        spacing=6,
                        tight=True,
                    ),
                )
            )

        host.controls = rows
        controls["model_catalog_status"].value = f"{len(rows)} entries loaded."
        self._safe_update()

    def _on_create_persona_clicked(self, _event):
        self._open_persona_editor(mode="create")

    def _on_edit_persona_clicked(self, _event):
        selected = str((self._controls.get("persona").value if self._controls.get("persona") else "") or "").strip()
        if not selected:
            self._toast("Select a persona first.")
            return
        if selected.lower() == "true janitor":
            self._toast("True Janitor cannot be edited.")
            return
        self._open_persona_editor(mode="edit", existing_name=selected)

    def _on_delete_persona_clicked(self, _event):
        selected = str((self._controls.get("persona").value if self._controls.get("persona") else "") or "").strip()
        if not selected:
            self._toast("Select a persona first.")
            return
        if selected.lower() == "true janitor":
            self._toast("True Janitor cannot be deleted.")
            return

        def _cancel(_):
            self._close_dialog(key="persona_delete")

        def _confirm(_):
            # Allow deleting built-in personas from settings, except True Janitor.
            ok, msg = delete_persona(selected, allow_builtin=True)
            self._close_dialog(key="persona_delete")
            self._toast(msg)
            if ok:
                self._refresh_persona_options()
                names = get_fast_lane_preset_names() or ["True Janitor"]
                self._controls["persona"].value = names[0]
                self._sync_persona_action_buttons()
                self._safe_update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Delete Persona"),
            content=ft.Text(f"Delete persona '{selected}'?"),
            actions=[
                ft.TextButton("Cancel", on_click=_cancel),
                ft.Button("Delete", on_click=_confirm),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=lambda _event: None,
        )
        self._show_dialog(dialog, key="persona_delete")

    def _open_persona_editor(self, mode="create", existing_name=""):
        mode_key = str(mode or "create").strip().lower()
        current_name = str(existing_name or "").strip()
        if mode_key == "edit" and current_name.lower() == "true janitor":
            self._toast("True Janitor cannot be edited.")
            return
        existing_prompt = get_persona_prompt(current_name, default="") if current_name else ""

        name_input = ft.TextField(label="Persona Name", value=current_name, disabled=mode_key == "edit")
        goal_input = ft.TextField(
            label="Goal",
            value="Rewrite text clearly while preserving intent.",
            multiline=True,
            min_lines=2,
            max_lines=4,
        )
        tone_input = ft.TextField(
            label="Tone",
            value="Confident and concise",
            multiline=True,
            min_lines=2,
            max_lines=4,
        )
        constraints_input = ft.TextField(
            label="Constraints",
            value="Do not add facts. Keep meaning intact.",
            multiline=True,
            min_lines=3,
            max_lines=6,
        )
        style_input = ft.TextField(
            label="Output Style",
            value="Clean plain text",
            multiline=True,
            min_lines=3,
            max_lines=6,
        )
        advanced_toggle = ft.Switch(label="Advanced Mode", value=(mode_key == "edit"))
        prompt_input = ft.TextField(
            label="Persona Prompt",
            multiline=True,
            min_lines=14,
            max_lines=20,
            value=existing_prompt,
        )
        status_text = ft.Text("", size=12, color=self._palette["muted"])

        def _refresh_prompt_enabled():
            prompt_input.disabled = not bool(advanced_toggle.value)

        def _generate_prompt(_):
            prompt_input.value = build_guided_persona_prompt(
                goal_input.value,
                tone_input.value,
                constraints_input.value,
                style_input.value,
            )
            status_text.value = "Generated prompt from guided fields."
            _refresh_prompt_enabled()
            self._safe_update()

        def _close(_):
            self._close_dialog(key="persona_editor")

        def _save(_):
            persona_name = (name_input.value or "").strip()
            if not persona_name:
                status_text.value = "Persona name is required."
                self._safe_update()
                return
            if bool(advanced_toggle.value):
                prompt = (prompt_input.value or "").strip()
            else:
                prompt = build_guided_persona_prompt(
                    goal_input.value,
                    tone_input.value,
                    constraints_input.value,
                    style_input.value,
                )
                prompt_input.value = prompt

            ok, msg = upsert_persona(persona_name, prompt)
            status_text.value = msg
            if ok:
                self._close_dialog(key="persona_editor")
                self._refresh_persona_options()
                persona_control = self._controls.get("persona")
                if persona_control is not None:
                    persona_control.value = persona_name
                self._sync_persona_action_buttons()
                self._safe_update()
                self._toast(msg)
            else:
                self._safe_update()

        advanced_toggle.on_change = lambda _e: (_refresh_prompt_enabled(), self._safe_update())
        _refresh_prompt_enabled()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Edit Persona" if mode_key == "edit" else "Create Persona"),
            content=ft.Container(
                width=980,
                height=620,
                content=ft.Column(
                    [
                        name_input,
                        goal_input,
                        tone_input,
                        constraints_input,
                        style_input,
                        ft.Row(
                            [
                                advanced_toggle,
                                ft.OutlinedButton("Generate Prompt", on_click=_generate_prompt),
                            ],
                            spacing=8,
                        ),
                        prompt_input,
                        status_text,
                    ],
                    spacing=8,
                    tight=True,
                    scroll=ft.ScrollMode.AUTO,
                ),
            ),
            actions=[
                ft.TextButton("Cancel", on_click=_close),
                ft.Button("Save Persona", on_click=_save),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=lambda _event: None,
        )
        self._show_dialog(dialog, key="persona_editor")

