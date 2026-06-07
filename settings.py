import logging
import os
import signal
import subprocess
import threading
import time
import webbrowser
import inspect
import json
import ctypes
from typing import Callable, Optional

from guided_tour import load_guided_tour_steps
from settings_controls_mixin import SettingsControlsMixin
from settings_modal_manager import SettingsModalManager
from settings_persistence_mixin import SettingsPersistenceMixin
from settings_tour_mixin import SettingsTourMixin

try:
    import flet as ft
except Exception:
    ft = None


def _safe_float(value, default, minimum=None, maximum=None):
    try:
        parsed = float(value)
    except Exception:
        parsed = float(default)
    if minimum is not None:
        parsed = max(float(minimum), parsed)
    if maximum is not None:
        parsed = min(float(maximum), parsed)
    return parsed


def _safe_int(value, default, minimum=None, maximum=None):
    try:
        parsed = int(float(value))
    except Exception:
        parsed = int(default)
    if minimum is not None:
        parsed = max(int(minimum), parsed)
    if maximum is not None:
        parsed = min(int(maximum), parsed)
    return parsed


def _sanitize_profile_name(raw_name: str) -> str:
    return "".join(ch for ch in str(raw_name or "") if ch.isalnum() or ch in (" ", "_", "-")).strip()



if ft is None:
    raise ImportError("Flet is required for BetterFingers settings. Please install with: pip install flet")


class SettingsWindow(
    SettingsControlsMixin,
    SettingsPersistenceMixin,
    SettingsTourMixin,
):
    DEFAULT_TTS_VOICES = [
        "english",
        "af_heart",
        "af_bella",
        "af_nicole",
        "af_sarah",
        "am_adam",
        "am_michael",
        "am_puck",
        "bf_emma",
        "bm_george",
    ]
    SAMPLE_TTS_TEXTS = [
        "Quick preview: BetterFingers is ready for review mode.",
        "Voice sample: clean, clear, and easy to understand.",
        "Team check: this is a short playback test for your selected voice.",
        "Rocket League comms test: rotate back post and cover the clear.",
    ]
    HELP_COPY = {
        "core_controls": (
            "Core Controls",
            "Set your main recording keys. Master Hotkey starts and stops capture, Emergency Stop cancels immediately, and Record Mode chooses toggle or push-to-talk.",
        ),
        "master_hotkey": (
            "Master Hotkey",
            "This is your primary recording trigger. Default is F8. Pick a key that is easy to hit without looking.",
        ),
        "emergency_stop": (
            "Emergency Stop",
            "Emergency Stop instantly cancels recording and processing. Use this if capture starts at the wrong time.",
        ),
        "record_mode": (
            "Record Mode",
            "Toggle means one press starts and the next press stops. Push-to-talk means hold to record and release to stop.",
        ),
        "audio_processing": (
            "Audio Processing",
            "Use these controls to keep system audio balanced while recording and to avoid getting buried under game or call audio.",
        ),
        "smart_audio_ducking": (
            "Smart Audio Ducking",
            "When enabled, Better Fingers lowers other app audio while listening so your voice is captured more clearly.",
        ),
        "ducking_level": (
            "Ducking Level",
            "How much other audio gets lowered while listening. Higher values reduce background audio more aggressively.",
        ),
        "fallback_return": (
            "Fallback Return Level",
            "How loud your system audio returns after recording. One hundred percent returns to normal volume.",
        ),
        "typing_behavior": (
            "Typing Behavior",
            "Control typing speed, instant output behavior, and optional sign-off text added to final output.",
        ),
        "target_speed": (
            "Target Speed",
            "This sets output typing speed in words per minute. Increase for faster delivery, decrease for safer compatibility in fragile text boxes.",
        ),
        "instant_typing": (
            "Instant Typing",
            "When enabled, text is typed as soon as it is ready instead of waiting for manual review flow.",
        ),
        "sign_off": (
            "Sign-off Text",
            "Optional text appended to the end of messages. Leave blank to disable.",
        ),
        "hardware_integration": (
            "Hardware Integration",
            "Map controller or gamepad input as a recording trigger with single, chord, or sequence bindings.",
        ),
        "controller_enabled": (
            "Controller Input",
            "Enable this to let a controller button or sequence control recording.",
        ),
        "controller_style": (
            "Binding Style",
            "Single listens for one input, chord requires multiple at once, and sequence requires inputs in order.",
        ),
        "controller_binding": (
            "Binding Expression",
            "Defines the exact controller input token such as button:4 or a sequence.",
        ),
        "axis_threshold": (
            "Axis Threshold",
            "Minimum joystick trigger movement needed before it counts as input.",
        ),
        "aux_keys": (
            "Auxiliary Keys",
            "Optional helper keys for opening chat quickly or temporarily muting voice key behavior.",
        ),
        "chat_open_key": (
            "Chat Open Key",
            "Key used to open a chat box before sending text, if your workflow needs it.",
        ),
        "voice_mute_key": (
            "Voice Mute Key",
            "Optional key to hold while recording so your in-game voice channel stays muted.",
        ),
        "delivery_pipeline": (
            "Delivery Pipeline",
            "Controls how finalized text is sent. F9 is the primary action hotkey for send-or-read behavior.",
        ),
        "send_mode": (
            "Send Mode",
            "Review First queues drafts for approval. Auto Send sends output immediately.",
        ),
        "chat_close_action": (
            "Chat Close Action",
            "Choose what happens after send: nothing, press Escape, or reuse your chat key.",
        ),
        "primary_action_hotkey": (
            "Primary Action Hotkey",
            "Default F9. If a review draft is waiting, F9 sends it. If not, F9 reads highlighted text with TTS.",
        ),
        "review_tts": (
            "Review TTS",
            "Configure read-back voice, speed, and shortcut. Default shortcut is Ctrl+Shift+Space, and F9 can read selected text too.",
        ),
        "review_tts_shortcut": (
            "Review TTS Shortcut",
            "Press this shortcut to read selected or active review text out loud.",
        ),
        "review_tts_speed": (
            "Playback Speed",
            "Adjust speech speed from slower and clearer to faster and more compact playback.",
        ),
        "transcription_safeguards": (
            "Transcription Safeguards",
            "These thresholds help ignore accidental captures when no meaningful audio is present.",
        ),
        "inference_engine": (
            "Inference Engine",
            "Choose whether LLM post-processing runs, which persona applies, and what model/quantization to use.",
        ),
        "experience_preset": (
            "Experience Preset",
            "Applies a full AI stack profile in one click: Simple, Plus, Pro, or Dont Use This Mode.",
        ),
        "output_token_limit": (
            "Output Token Limit",
            "Hard cap for generated output tokens per response. Keep this between 900 and 1200 to balance quality and latency.",
        ),
        "draft_history_limit": (
            "Draft History Retention",
            "Maximum number of finalized draft edits to keep in local history for quick lookup.",
        ),
        "long_input_notice": (
            "Long Input Notice",
            "Message shown when captured input is longer than the configured token limit and must be split into chunks.",
        ),
        "model_catalog": (
            "Model Catalog",
            "Unified list of LLM and Whisper models with install state, selection state, download progress, and per-model actions.",
        ),
        "memory_management": (
            "Memory Management",
            "Keep models loaded for faster responses, or unload to save VRAM and system memory.",
        ),
        "hardware_estimator": (
            "Hardware Estimator",
            "Shows an approximate VRAM target for the currently selected Whisper + LLM stack.",
        ),
        "status_indicator": (
            "Status Indicator",
            "Controls where the small recording state indicator appears on your screen.",
        ),
        "notification_overlay": (
            "Notification Overlay",
            "Controls position and style of short toasts for app events and state messages.",
        ),
        "preview_overlay": (
            "Preview Overlay",
            "Controls position and style of the live preview/review box.",
        ),
    }
    MODAL_KEY_HELP = "help"
    MODAL_KEY_SUPPORT = "support"
    MODAL_KEY_PROFILE_NEW = "profile_new"
    MODAL_KEY_PROFILE_DELETE = "profile_delete"
    MODAL_KEY_TOUR_INTRO = "tour_intro"
    MODAL_KEY_WHISPER_UNINSTALL = "whisper_uninstall"
    MODAL_KEY_UNSAVED_CHANGES = "unsaved_changes"

    @staticmethod
    def _safe_float(value, default, minimum=None, maximum=None):
        return _safe_float(value, default, minimum=minimum, maximum=maximum)

    @staticmethod
    def _safe_int(value, default, minimum=None, maximum=None):
        return _safe_int(value, default, minimum=minimum, maximum=maximum)

    @staticmethod
    def _sanitize_profile_name(raw_name: str) -> str:
        return _sanitize_profile_name(raw_name)

    def __init__(
        self,
        root,
        hotkey_manager,
        on_save_callback,
        on_tts_preview_callback: Optional[Callable[[str, float, str, str], dict]] = None,
        on_tts_stop_callback: Optional[Callable[[], None]] = None,
        get_tts_voice_options_callback: Optional[Callable[[], list]] = None,
        get_whisper_download_status_callback: Optional[Callable[[], dict]] = None,
        on_download_whisper_model_callback: Optional[Callable[[str, Optional[Callable[[dict], None]]], dict]] = None,
        on_test_whisper_model_callback: Optional[Callable[[str], dict]] = None,
        on_uninstall_whisper_model_callback: Optional[Callable[[str], dict]] = None,
        on_show_callback: Optional[Callable[[], None]] = None,
        on_hide_callback: Optional[Callable[[], None]] = None,
    ):
        self.app_root = root
        self.hotkey_manager = hotkey_manager
        self.on_save = on_save_callback
        self.on_tts_preview = on_tts_preview_callback
        self.on_tts_stop = on_tts_stop_callback
        self.get_tts_voice_options = get_tts_voice_options_callback
        self.get_whisper_download_status = get_whisper_download_status_callback
        self.on_download_whisper_model = on_download_whisper_model_callback
        self.on_test_whisper_model = on_test_whisper_model_callback
        self.on_uninstall_whisper_model = on_uninstall_whisper_model_callback
        self.on_show = on_show_callback
        self.on_hide = on_hide_callback

        self.current_profile = "Default"
        self._controls = {}
        self._page = None
        self._modal_manager = SettingsModalManager(page_getter=lambda: self._page, on_update=self._safe_update)
        self._tabs = None
        self._tab_order = ["general", "input", "output", "ai", "overlays"]
        self._tab_labels = {
            "general": "General",
            "input": "Input",
            "output": "Output",
            "ai": "AI Engine",
            "overlays": "Overlays",
        }
        self._tab_buttons = {}
        self._tab_views = {}
        self._tab_content_host = None
        self._active_tab_index = 0
        self._is_open = False
        self._open_requested_at = 0.0
        self._show_lock = threading.Lock()
        self._window_thread = None
        self._start_tour_on_show = False
        self._palette = {
            "bg": "#0b1220",
            "surface": "#111827",
            "card": "#1f2937",
            "card_border": "#374151",
            "text": "#f9fafb",
            "muted": "#9ca3af",
            "accent": "#14b8a6",
            "accent_soft": "#0ea5e9",
        }

        self._tour_steps = load_guided_tour_steps()
        self._tour_index = 0
        self._tour_started = False
        self._tour_dialog = None
        self._tour_bar = None  # Bottom bar container
        self._tour_bar_visible = False
        self._tour_title = None
        self._tour_body = None
        self._tour_progress = None
        self._tour_next_btn = None
        self._tour_back_btn = None
        self._tour_start_btn = None
        self._tour_skip_btn = None
        self._tour_play_btn = None
        self._tour_in_intro = False
        self._tour_targets = {}
        self._tour_target_tabs = {}
        self._tour_target_scroll_keys = {}
        self._tour_tab_scrollers = {}
        self._tour_page_ref = None
        self._tour_intro_dialog = None
        self._support_dialog = None
        self._help_dialog = None
        self._saved_controls_snapshot = {}
        self._close_dialog_open = False
        self._shutdown_requested = False
        self._selected_preset_current = "custom"
        self._selected_preset_pending = None

    def _safe_update(self):
        """Safely update the Flet page, guarding against closed window exceptions."""
        if not self._page:
            return
        try:
            self._page.update()
        except Exception as exc:
            logging.debug("Settings page update skipped: %s", exc)

    def _schedule_awaitable(self, awaitable_obj):
        if not inspect.isawaitable(awaitable_obj):
            return False
        try:
            import asyncio

            session = getattr(self._page, "session", None)
            loop = getattr(getattr(session, "connection", None), "loop", None)
            if loop is not None:
                asyncio.run_coroutine_threadsafe(awaitable_obj, loop)
                return True
            asyncio.run(awaitable_obj)
            return True
        except Exception:
            try:
                awaitable_obj.close()
            except Exception:
                pass
        return False

    def _schedule_page_method(self, method, *args, prefer_run_task=True):
        if not callable(method):
            return False
        if prefer_run_task and self._page:
            run_task = getattr(self._page, "run_task", None)
            if callable(run_task):
                try:
                    run_task(method, *args)
                    return True
                except Exception:
                    pass
        try:
            result = method(*args)
        except Exception as exc:
            logging.debug("Settings window method call failed: %s", exc)
            return False
        if inspect.isawaitable(result):
            return self._schedule_awaitable(result)
        return True

    def _bring_settings_window_to_front(self):
        if not self._page:
            return
        window = getattr(self._page, "window", None)
        if not window:
            return

        try:
            if hasattr(window, "visible"):
                window.visible = True
            if hasattr(window, "minimized"):
                window.minimized = False
            if hasattr(window, "focused"):
                window.focused = True
        except Exception:
            pass

        # Flush restored window state before requesting front focus.
        self._safe_update()
        self._schedule_page_method(getattr(window, "wait_until_ready_to_show", None))
        moved = self._schedule_page_method(getattr(window, "to_front", None))
        if not moved:
            self._safe_update()

    def _invoke_ui_callback(self, callback, label: str):
        if not callable(callback):
            return
        try:
            if self.app_root and hasattr(self.app_root, "after"):
                self.app_root.after(0, callback)
            else:
                callback()
        except Exception as exc:
            logging.debug("%s callback failed: %s", label, exc)

    def _show_dialog(self, dialog, key: Optional[str] = None, replace_active: bool = True):
        if dialog is None:
            return
        dialog_key = str(key or "").strip()
        if not dialog_key:
            dialog_key = f"dialog:{id(dialog)}"
        self._modal_manager.show(dialog_key, dialog, replace_active=replace_active)

    def _close_dialog(self, dialog=None, key: Optional[str] = None):
        dialog_key = str(key or "").strip()
        if not dialog_key and dialog is not None:
            dialog_key = self._modal_manager.get_key_for_dialog(dialog) or f"dialog:{id(dialog)}"
        if dialog_key:
            self._modal_manager.close(key=dialog_key)

    def _open_external_url(self, url: str) -> bool:
        target = str(url or "").strip()
        if not target:
            return False

        if self._page:
            try:
                run_task = getattr(self._page, "run_task", None)
                service = getattr(self._page, "url_launcher", None)
                service_launcher = getattr(service, "launch_url", None)
                if callable(run_task) and callable(service_launcher):
                    run_task(service_launcher, target)
                    return True
            except Exception:
                pass
            try:
                launcher = getattr(self._page, "launch_url", None)
                if callable(launcher):
                    result = launcher(target)
                    if inspect.isawaitable(result):
                        try:
                            import asyncio

                            session = getattr(self._page, "session", None)
                            loop = getattr(getattr(session, "connection", None), "loop", None)
                            if loop is not None:
                                asyncio.run_coroutine_threadsafe(result, loop)
                                return True
                            asyncio.run(result)
                            return True
                        except Exception:
                            try:
                                result.close()
                            except Exception:
                                pass
                    else:
                        return True
            except Exception:
                pass

        if hasattr(os, "startfile"):
            try:
                os.startfile(target)  # type: ignore[attr-defined]
                return True
            except Exception:
                pass

        try:
            if webbrowser.open(target, new=2):
                return True
        except Exception:
            pass

        if os.name == "nt":
            try:
                subprocess.Popen(
                    ["cmd", "/c", "start", "", target],
                    shell=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return True
            except Exception:
                pass

        return False

    def _resolve_help_copy(self, help_key: str):
        key = str(help_key or "").strip()
        if not key:
            return ("Quick Help", "No help text is available for this setting yet.")
        return self.HELP_COPY.get(
            key,
            ("Quick Help", "No help text is available for this setting yet."),
        )

    def _help_icon(self, help_key: str):
        key = str(help_key or "").strip()
        return ft.IconButton(
            icon=ft.Icons.HELP_OUTLINE,
            icon_size=14,
            icon_color="#cbd5e1",
            tooltip="What does this do?",
            on_click=lambda _event, k=key: self._show_help_dialog(k),
            style=ft.ButtonStyle(
                bgcolor="#64748b55",
                side=ft.BorderSide(1, "#94a3b877"),
                padding=ft.Padding.all(6),
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )

    def _with_help(self, control, help_key: str, expand_control: bool = True):
        key = str(help_key or "").strip()
        if not key:
            return control
        return ft.Row(
            [
                ft.Container(content=control, expand=bool(expand_control)),
                self._help_icon(key),
            ],
            spacing=8,
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _play_help_tts(self, title: str, body: str):
        if not callable(self.on_tts_preview):
            return
        controls = self._controls or {}
        speed_control = controls.get("review_tts_speed")
        voice_control = controls.get("review_tts_voice_hint")
        quant_control = controls.get("kokoro_quantization")
        speed = _safe_float(getattr(speed_control, "value", 0.95), 0.95, minimum=0.5, maximum=3.0)
        voice = (getattr(voice_control, "value", "english") or "english").strip() or "english"
        quant = (getattr(quant_control, "value", "fp32") or "fp32").strip()
        narration = f"{str(title or '').strip()}. {str(body or '').strip()}"
        try:
            self.on_tts_preview(narration, speed, voice, quant)
        except Exception as exc:
            logging.debug("Help TTS playback failed: %s", exc)

    def _show_help_dialog(self, help_key: str):
        if not self._page:
            return
        title, text = self._resolve_help_copy(help_key)

        if self._help_dialog is not None:
            self._close_dialog(key=self.MODAL_KEY_HELP)
            self._help_dialog = None

        def _close(_event=None):
            self._close_dialog(key=self.MODAL_KEY_HELP)
            self._help_dialog = None

        def _on_dismiss(_event=None):
            self._help_dialog = None

        dialog = ft.AlertDialog(
            modal=False,
            title=ft.Text(title),
            content=ft.Container(width=520, content=ft.Text(text)),
            actions=[
                ft.TextButton("Read Aloud", on_click=lambda _event: self._play_help_tts(title, text)),
                ft.TextButton("Close", on_click=_close),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=_on_dismiss,
        )
        self._help_dialog = dialog
        self._show_dialog(dialog, key=self.MODAL_KEY_HELP)

    def _toast(self, message: str):
        if not self._page:
            return
        try:
            self._page.snack_bar = ft.SnackBar(ft.Text(str(message)))
            self._page.snack_bar.open = True
            self._safe_update()
        except Exception:
            pass

    def _snapshot_controls(self):
        snapshot = {}
        controls = self._controls or {}
        for key, control in controls.items():
            try:
                if hasattr(control, "value"):
                    snapshot[str(key)] = getattr(control, "value")
            except Exception:
                continue
        return snapshot

    def _mark_settings_clean(self):
        self._saved_controls_snapshot = self._snapshot_controls()

    def _has_unsaved_changes(self):
        if not self._controls:
            return False
        return self._snapshot_controls() != dict(self._saved_controls_snapshot or {})

    def _on_window_event(self, event):
        try:
            tokens = []
            for attr in ("data", "name", "event_type", "type"):
                raw_value = getattr(event, attr, None)
                if raw_value is None:
                    continue
                text = str(raw_value).strip().lower()
                if not text:
                    continue
                tokens.append(text)
                if text.startswith("{") and text.endswith("}"):
                    try:
                        payload = json.loads(text)
                    except Exception:
                        payload = {}
                    for payload_key in ("data", "name", "event", "event_type", "type", "action"):
                        payload_value = payload.get(payload_key)
                        if payload_value is None:
                            continue
                        payload_text = str(payload_value).strip().lower()
                        if payload_text:
                            tokens.append(payload_text)

            if any("close" in token for token in tokens):
                self._on_close_clicked()
        except Exception:
            pass

    def _show_unsaved_close_dialog(self):
        if self._close_dialog_open:
            return
        self._close_dialog_open = True

        def _cancel(_event=None):
            self._close_dialog_open = False
            self._close_dialog(key=self.MODAL_KEY_UNSAVED_CHANGES)

        def _discard(_event=None):
            self._close_dialog_open = False
            self._close_dialog(key=self.MODAL_KEY_UNSAVED_CHANGES)
            self._force_close_settings_window()

        def _save_and_close(_event=None):
            self._close_dialog_open = False
            self._close_dialog(key=self.MODAL_KEY_UNSAVED_CHANGES)
            self._save_settings()
            self._force_close_settings_window()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Unsaved Changes"),
            content=ft.Text("You have unsaved changes. Save before closing settings?"),
            actions=[
                ft.TextButton("Cancel", on_click=_cancel),
                ft.OutlinedButton("Discard", on_click=_discard),
                ft.Button("Save", on_click=_save_and_close),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=lambda _event: _cancel(None),
        )
        self._show_dialog(dialog, key=self.MODAL_KEY_UNSAVED_CHANGES)

    def _on_close_clicked(self, _event=None):
        if (not self._shutdown_requested) and self._has_unsaved_changes():
            self._show_unsaved_close_dialog()
            return
        self._force_close_settings_window()

    def _force_close_settings_window(self):
        if not self._page:
            return False
        page = self._page
        window = getattr(page, "window", None)

        try:
            if window is not None and hasattr(window, "prevent_close"):
                window.prevent_close = False
        except Exception:
            pass

        close_paths = []
        if window is not None:
            close_paths.append(("page.window.close", getattr(window, "close", None)))
            close_paths.append(("page.window.destroy", getattr(window, "destroy", None)))
        close_paths.append(("page.window_close", getattr(page, "window_close", None)))
        close_paths.append(("page.window_destroy", getattr(page, "window_destroy", None)))

        for label, close_fn in close_paths:
            if not callable(close_fn):
                continue
            try:
                # Prefer immediate invocation during shutdown; if that fails,
                # fall back to queuing onto the page task runner.
                if self._schedule_page_method(close_fn, prefer_run_task=False):
                    return True
                if self._schedule_page_method(close_fn, prefer_run_task=True):
                    return True
            except Exception as exc:
                logging.debug("Settings close path failed (%s): %s", label, exc)

        logging.debug("Unable to close Flet settings window cleanly: no close path succeeded")
        return False

    def wait_for_shutdown(self, timeout_sec=1.5):
        try:
            timeout = max(0.0, float(timeout_sec))
        except Exception:
            timeout = 1.5
        deadline = time.time() + timeout

        while True:
            with self._show_lock:
                worker = self._window_thread
                is_open = bool(self._is_open)
            worker_alive = bool(worker and worker.is_alive())
            if (not is_open) and (not worker_alive):
                return True

            remaining = deadline - time.time()
            if remaining <= 0:
                return False

            pause = min(0.12, remaining)
            if worker_alive and worker is not threading.current_thread():
                try:
                    worker.join(timeout=pause)
                except Exception:
                    time.sleep(pause)
            else:
                time.sleep(pause)

    @staticmethod
    def _close_native_window_by_title(window_title: str) -> bool:
        if os.name != "nt":
            return False
        title = str(window_title or "").strip()
        if not title:
            return False
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, title)
            if not hwnd:
                return False
            # WM_CLOSE
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
            return True
        except Exception as exc:
            logging.debug("Native WM_CLOSE fallback failed for '%s': %s", title, exc)
            return False

    def force_close_for_shutdown(self):
        """
        Close settings immediately during app shutdown, bypassing unsaved-change prompts.
        """
        self._shutdown_requested = True
        self._close_dialog_open = False
        try:
            self._modal_manager.close_all()
        except Exception:
            pass
        try:
            self._close_dialog(key=self.MODAL_KEY_UNSAVED_CHANGES)
        except Exception:
            pass
        try:
            self._force_close_settings_window()
        except Exception:
            pass

        if not self.wait_for_shutdown(timeout_sec=1.2):
            if self._close_native_window_by_title("BetterFingers Settings"):
                self.wait_for_shutdown(timeout_sec=0.45)

    def _invoke_on_save(self):
        if not callable(self.on_save):
            return
        try:
            if self.app_root:
                self.app_root.after(0, self.on_save)
            else:
                self.on_save()
        except Exception as exc:
            logging.error("Settings save callback failed: %s", exc)

    def _open_support_panel(self, _event=None):
        if not self._page:
            return
        logging.debug("Support button clicked.")

        if self._support_dialog is not None:
            self._close_dialog(key=self.MODAL_KEY_SUPPORT)
            self._support_dialog = None

        def _close(_event=None):
            self._close_dialog(key=self.MODAL_KEY_SUPPORT)
            self._support_dialog = None

        def _on_dismiss(_event=None):
            self._support_dialog = None

        def _donate(_event=None):
            url = "https://ko-fi.com/democratizegm"
            opened = self._open_external_url(url)
            logging.info("Support donate link requested. opened=%s url=%s", opened, url)
            if not opened:
                self._toast(f"Open this link manually: {url}")
            _close(None)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Support Better Fingers"),
            content=ft.Container(
                width=500,
                content=ft.Column(
                    [
                        ft.Text(
                            "This app is built to stay free, local, and subscription-free.",
                            color=self._palette["text"],
                        ),
                        ft.Text(
                            'No "Pro plan." No paywalls. No renting software forever.',
                            color=self._palette["muted"],
                        ),
                        ft.Container(height=6),
                        ft.Text(
                            "If Better Fingers has helped you, support the work here.",
                            color=self._palette["text"],
                        ),
                        ft.Text(
                            "Donation link:",
                            size=12,
                            color=self._palette["muted"],
                        ),
                        ft.TextButton(
                            "https://ko-fi.com/democratizegm",
                            on_click=_donate,
                            style=ft.ButtonStyle(color=self._palette["accent_soft"]),
                        ),
                    ],
                    tight=True,
                    spacing=10,
                ),
            ),
            actions=[
                ft.TextButton("Close", on_click=_close),
                ft.Button("Open Ko-fi", on_click=_donate),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=_on_dismiss,
        )
        self._support_dialog = dialog
        self._show_dialog(self._support_dialog, key=self.MODAL_KEY_SUPPORT)

    def _run_flet_settings_app(self):
        original_signal = signal.signal
        signal_patched = False

        # Flet 0.80 registers SIGINT/SIGTERM in run_async(), which fails in worker threads.
        # Keep main-thread behavior unchanged while allowing settings to run asynchronously.
        if threading.current_thread() is not threading.main_thread():
            def _safe_signal(signum, handler):
                try:
                    return original_signal(signum, handler)
                except ValueError as exc:
                    if "main thread" in str(exc).lower():
                        logging.debug(
                            "Ignoring non-main-thread signal registration for settings window: %s",
                            exc,
                        )
                        return None
                    raise

            signal.signal = _safe_signal
            signal_patched = True

        try:
            ft.app(target=self._build_page, view=ft.AppView.FLET_APP)
        except Exception as exc:
            logging.error("Failed to launch Flet settings window: %s", exc)
        finally:
            if signal_patched:
                try:
                    signal.signal = original_signal
                except Exception:
                    pass
            try:
                self._modal_manager.close_all()
            except Exception as exc:
                logging.debug("Failed to close settings modals during shutdown: %s", exc)
            with self._show_lock:
                self._is_open = False
                self._open_requested_at = 0.0
                self._page = None
                self._tabs = None
                self._tab_buttons = {}
                self._tab_views = {}
                self._tab_content_host = None
                self._tour_bar = None
                self._tour_title = None
                self._tour_body = None
                self._tour_progress = None
                self._tour_next_btn = None
                self._tour_back_btn = None
                self._tour_start_btn = None
                self._tour_skip_btn = None
                self._tour_play_btn = None
                self._tour_page_ref = None
                self._support_dialog = None
                self._help_dialog = None
                self._window_thread = None

            # Notify after closing (for overlay transparency refresh)
            self._invoke_ui_callback(self.on_hide, "on_hide")

    def show(self, start_tour=False):
        del start_tour
        if self._shutdown_requested:
            return
        self._start_tour_on_show = False
        launch_thread = None
        with self._show_lock:
            if self._is_open:
                stale = False
                if self._page is not None:
                    try:
                        self._page.update()
                        self._bring_settings_window_to_front()
                        return
                    except Exception:
                        stale = True
                if self._page is None:
                    thread_alive = bool(self._window_thread and self._window_thread.is_alive())
                    stale = stale or (
                        (time.time() - self._open_requested_at > 2.0) and not thread_alive
                    )
                if stale:
                    logging.warning("Detected stale settings open state. Resetting and retrying launch.")
                    self._is_open = False
                    self._page = None
                    self._window_thread = None
                else:
                    return

            self._is_open = True
            self._open_requested_at = time.time()
            launch_thread = threading.Thread(
                target=self._run_flet_settings_app,
                name="SettingsWindowThread",
                daemon=True,
            )
            self._window_thread = launch_thread

        # Notify before opening (for overlay transparency refresh)
        self._invoke_ui_callback(self.on_show, "on_show")
        launch_thread.start()

    def hide(self):
        self._on_close_clicked()

    def request_tour_on_next_show(self):
        self._start_tour_on_show = False

    def _build_page(self, page):
        self._page = page
        if self._shutdown_requested:
            self._force_close_settings_window()
            return
        page.title = "BetterFingers Settings"
        page.theme_mode = ft.ThemeMode.DARK
        page.theme = ft.Theme(color_scheme_seed=self._palette["accent"], use_material3=True)
        page.padding = 20
        page.bgcolor = self._palette["bg"]
        page.scroll = ft.ScrollMode.HIDDEN

        try:
            page.window.width = 1140
            page.window.height = 860
            page.window.min_width = 980
            page.window.min_height = 720
            window_event_hooked = False
            if hasattr(page.window, "on_event"):
                page.window.on_event = self._on_window_event
                window_event_hooked = True
            if hasattr(page, "on_window_event"):
                page.on_window_event = self._on_window_event
                window_event_hooked = True
            if hasattr(page.window, "prevent_close"):
                # Only intercept native close when we can reliably receive close events.
                page.window.prevent_close = bool(window_event_hooked)
        except Exception:
            pass
        page.floating_action_button = ft.FloatingActionButton(
            icon=ft.Icons.SAVE,
            content="Save",
            on_click=self._on_save_clicked,
            bgcolor=self._palette["accent"],
            foreground_color="#042f2e",
        )
        page.floating_action_button_location = ft.FloatingActionButtonLocation.END_FLOAT

        try:
            header = ft.Container(
                gradient=ft.LinearGradient(
                    begin=ft.Alignment(-1, -1),
                    end=ft.Alignment(1, 1),
                    colors=["#0f172a", "#0f766e"],
                ),
                border_radius=18,
                padding=18,
                content=ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text(
                                    "BetterFingers Settings",
                                    size=28,
                                    weight=ft.FontWeight.W_600,
                                    color="#ffffff",
                                ),
                                ft.Text(
                                    "private, local, democratizing intelligence.",
                                    size=14,
                                    color="#c7d2fe",
                                ),
                            ],
                            spacing=6,
                            tight=True,
                        ),
                        ft.TextButton(
                            "Support",
                            icon=ft.Icons.VOLUNTEER_ACTIVISM_OUTLINED,
                            on_click=self._open_support_panel,
                            style=ft.ButtonStyle(color="#e2e8f0"),
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
            )

            self._build_controls()
            self._refresh_profile_options()
            self._load_settings()

            actions = ft.Container(
                bgcolor=self._palette["surface"],
                border=ft.Border.all(1, self._palette["card_border"]),
                border_radius=14,
                padding=12,
                content=ft.Row(
                    [
                        ft.Button("Save Configuration", on_click=self._on_save_clicked),
                        ft.OutlinedButton("Open Word Rules", on_click=self._on_open_word_rules_clicked),
                        ft.OutlinedButton("Open Draft History", on_click=self._on_open_draft_history_clicked),
                    ],
                    wrap=True,
                    spacing=10,
                ),
            )

            quick_preset = ft.Container(
                bgcolor=self._palette["surface"],
                border=ft.Border.all(1, self._palette["card_border"]),
                border_radius=14,
                padding=12,
                content=ft.Column(
                    [
                        ft.Text("Quick Preset", size=16, weight=ft.FontWeight.W_600, color=self._palette["text"]),
                        ft.Row(
                            [
                                ft.Container(
                                    content=self._with_help(self._controls["experience_preset"], "experience_preset"),
                                    width=320,
                                ),
                                ft.Container(content=self._controls["experience_preset_note"], width=700),
                            ],
                            wrap=False,
                            spacing=12,
                            alignment=ft.MainAxisAlignment.START,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        self._controls["preset_pending_actions"],
                        self._with_help(self._controls["hardware_estimate"], "hardware_estimator"),
                        self._controls["hardware_change_preview"],
                    ],
                    spacing=8,
                    tight=True,
                ),
            )

            page.add(
                ft.Column(
                    [
                        header,
                        actions,
                        quick_preset,
                        self._build_profile_bar(),
                        self._tabs,
                    ],
                    spacing=16,
                    expand=True,
                )
            )
        except Exception as exc:
            logging.exception("Failed while building Flet settings page: %s", exc)
            try:
                page.clean()
                page.add(
                    ft.Container(
                        bgcolor=self._palette["surface"],
                        border=ft.Border.all(1, self._palette["card_border"]),
                        border_radius=14,
                        padding=18,
                        content=ft.Column(
                            [
                                ft.Text("Settings failed to render", size=20, weight=ft.FontWeight.W_600),
                                ft.Text(str(exc)),
                                ft.Text("Close and reopen settings. If this repeats, check debug.log."),
                                ft.Button("Close", on_click=lambda _: self.hide()),
                            ],
                            spacing=10,
                            tight=True,
                        ),
                    )
                )
                self._safe_update()
            except Exception:
                pass





