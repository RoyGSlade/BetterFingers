import logging
import threading
import time

import keyboard

from input_binding import InputBinding
from utils import load_profile

try:
    import pygame

    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
    logging.warning("pygame not found. Controller support disabled.")


class HotkeyManager:
    @staticmethod
    def _coerce_bool(value):
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @staticmethod
    def _normalize_hotkey(value, default=""):
        hotkey = str(value or default or "").strip().lower()
        if not hotkey:
            return ""
        parts = [part.strip() for part in hotkey.split("+") if part.strip()]
        return "+".join(parts)

    def __init__(
        self,
        recorder,
        on_recording_complete_callback,
        on_recording_start_callback,
        on_force_stop_callback=None,
        on_manual_send_callback=None,
        on_review_tts_callback=None,
        is_busy_callback=None,
    ):
        self.recorder = recorder
        self.on_complete = on_recording_complete_callback
        self.on_start_ui = on_recording_start_callback
        self.on_force_stop = on_force_stop_callback
        self.on_manual_send = on_manual_send_callback
        self.on_review_tts = on_review_tts_callback
        self.is_busy_callback = is_busy_callback
        self.current_profile = "Default"

        self.state_lock = threading.RLock()
        self.config = load_profile(self.current_profile)

        self.hotkey = "f8"
        self.force_stop_key = ""
        self.manual_send_hotkey = "f9"
        self.review_tts_hotkey = "ctrl+shift+space"
        self.mode = "toggle"
        self.controller_enabled = False
        self.controller_binding = InputBinding()
        self._load_runtime_config(self.config)

        self.is_recording = False
        self.recording_start_time = 0.0
        self.last_toggle_time = 0.0
        self.ptt_held = False
        self.last_stop_reason = "manual"

        self.keyboard_hooks = []
        self.keyboard_hook_errors = []
        self.toggle_hotkey_handle = None
        self.force_stop_handle = None
        self.manual_send_handle = None
        self.review_tts_handle = None
        self.review_tts_deduped = False

        self.stop_threads = False
        self.controller_thread = None
        self.joysticks = {}
        self._running = False

        self.controller_pressed_tokens = set()
        self.axis_active = {}
        self.hat_active = {}
        self.chord_latched = False
        self.sequence_progress = 0
        self.sequence_last_time = 0.0
        self.sequence_hold_token = None
        self.controller_trigger_active = False

        self.is_mapping = False
        self.mapping_style = "single"
        self.mapping_callback = None
        self.mapping_deadline = 0.0
        self.mapping_tokens = []
        self.mapping_active_tokens = set()
        self.mapping_chord_peak = set()

    def _load_runtime_config(self, config):
        self.hotkey = self._normalize_hotkey(config.get("hotkey"), "f8")
        self.force_stop_key = self._normalize_hotkey(config.get("force_stop_key"), "")
        self.manual_send_hotkey = self._normalize_hotkey(config.get("manual_send_hotkey"), "f9")
        self.review_tts_hotkey = self._normalize_hotkey(config.get("review_tts_hotkey"), "ctrl+shift+space")
        self.mode = config.get("recording_mode", "toggle")
        self.controller_enabled = self._coerce_bool(
            config.get("controller_enabled", config.get("controller_ptt", False))
        )
        self.controller_binding = InputBinding.from_dict(
            config.get("controller_binding"),
            default_button=config.get("controller_button", 4),
        )
        self.controller_binding.sequence_window_ms = int(
            config.get("controller_sequence_window_ms", self.controller_binding.sequence_window_ms)
        )
        self.controller_binding.axis_threshold = float(
            config.get("controller_axis_threshold", self.controller_binding.axis_threshold)
        )
        self.controller_binding.validate()

    # --- Keyboard PTT ---
    def _on_ptt_press(self, event):
        del event
        if self.ptt_held:
            return
        self.ptt_held = True
        if not self.is_recording:
            self._start_recording(reason="keyboard_ptt")

    def _on_ptt_release(self, event):
        del event
        if not self.ptt_held:
            return
        self.ptt_held = False
        if self.is_recording:
            self._stop_recording(reason="keyboard_ptt_release")

    # --- Toggle ---
    def _toggle(self):
        logging.info("Recording hotkey triggered.")
        now = time.time()
        if now - self.last_toggle_time < 0.20:
            return
        self.last_toggle_time = now

        if not self.is_recording:
            self._start_recording(reason="toggle")
        else:
            self._stop_recording(reason="toggle")

    def _start_recording(self, reason="manual"):
        logging.info("Recording trigger received (%s)", reason)
        if self.is_busy_callback and self.is_busy_callback():
            logging.info("Ignored recording trigger: backend is busy processing a previous draft.")
            return
        with self.state_lock:
            if self.is_recording:
                return
            self.is_recording = True
            self.recording_start_time = time.time()
            self.last_stop_reason = reason

        logging.info(f"Recording START ({reason}) profile={self.current_profile}")
        if self.on_start_ui:
            self.on_start_ui()
        self.recorder.start_recording(self.current_profile)
        if not self.recorder.recording:
            with self.state_lock:
                self.is_recording = False
            if self.on_force_stop:
                try:
                    self.on_force_stop()
                except Exception as exc:
                    logging.error(f"Start-recording cleanup failed: {exc}")

    def _stop_recording(self, reason="manual"):
        with self.state_lock:
            if not self.is_recording:
                return
            self.is_recording = False
            self.last_stop_reason = reason

        duration = max(0.0, time.time() - self.recording_start_time)
        logging.info(f"Recording STOP ({reason}) duration={duration:.2f}s")

        result = self.recorder.stop_recording(stop_reason=reason)
        if self.on_complete:
            self.on_complete(result)

    def request_stop(self, reason="manual"):
        self._stop_recording(reason=reason)

    def request_toggle(self, reason="manual_button"):
        if self.is_recording:
            self._stop_recording(reason=reason)
        else:
            self._start_recording(reason=reason)

    # --- Mapping ---
    def start_mapping(self, callback, style="single", timeout_ms=2500, activity_callback=None):
        self._ensure_controller_thread()
        self.mapping_callback = callback
        self.mapping_activity_callback = activity_callback
        self.mapping_style = (style or "single").strip().lower()
        if self.mapping_style not in {"single", "chord", "sequence"}:
            self.mapping_style = "single"
        self.mapping_deadline = time.time() + (max(500, int(timeout_ms)) / 1000.0)
        self.mapping_tokens = []
        self.mapping_active_tokens = set()
        self.mapping_chord_peak = set()
        self.is_mapping = True
        logging.info(f"Controller mapping started (style={self.mapping_style})")

    def stop_mapping(self):
        self.is_mapping = False
        self.mapping_callback = None
        self.mapping_activity_callback = None
        if not self.controller_enabled:
            self.stop_threads = True

    def _finish_mapping(self, binding_dict):
        callback = self.mapping_callback
        self.is_mapping = False
        self.mapping_callback = None
        self.mapping_activity_callback = None
        self.mapping_tokens = []
        self.mapping_active_tokens = set()
        self.mapping_chord_peak = set()
        if callback:
            callback(binding_dict)
        if not self.controller_enabled:
            self.stop_threads = True

    def _mapping_token_down(self, token):
        if self.mapping_activity_callback:
            try:
                self.mapping_activity_callback(token)
            except Exception:
                pass

        if self.mapping_style == "single":
            self._finish_mapping(
                {
                    "style": "single",
                    "events": [token],
                    "sequence_window_ms": self.controller_binding.sequence_window_ms,
                    "axis_threshold": self.controller_binding.axis_threshold,
                    "device_scope": "any_device",
                }
            )
            return

        if self.mapping_style == "chord":
            self.mapping_active_tokens.add(token)
            self.mapping_chord_peak.update(self.mapping_active_tokens)
            return

        # sequence
        if not self.mapping_tokens or self.mapping_tokens[-1] != token:
            self.mapping_tokens.append(token)

    def _mapping_token_up(self, token):
        if self.mapping_style != "chord":
            return
        self.mapping_active_tokens.discard(token)
        if not self.mapping_active_tokens and self.mapping_chord_peak:
            self._finish_mapping(
                {
                    "style": "chord",
                    "events": sorted(self.mapping_chord_peak),
                    "sequence_window_ms": self.controller_binding.sequence_window_ms,
                    "axis_threshold": self.controller_binding.axis_threshold,
                    "device_scope": "any_device",
                }
            )

    def _mapping_timeout_check(self):
        if not self.is_mapping:
            return
        if time.time() < self.mapping_deadline:
            return

        if self.mapping_style == "sequence" and self.mapping_tokens:
            self._finish_mapping(
                {
                    "style": "sequence",
                    "events": list(self.mapping_tokens),
                    "sequence_window_ms": self.controller_binding.sequence_window_ms,
                    "axis_threshold": self.controller_binding.axis_threshold,
                    "device_scope": "any_device",
                }
            )
            return

        if self.mapping_style == "chord" and self.mapping_chord_peak:
            self._finish_mapping(
                {
                    "style": "chord",
                    "events": sorted(self.mapping_chord_peak),
                    "sequence_window_ms": self.controller_binding.sequence_window_ms,
                    "axis_threshold": self.controller_binding.axis_threshold,
                    "device_scope": "any_device",
                }
            )
            return

        self._finish_mapping(None)

    def _ensure_controller_thread(self):
        if not PYGAME_AVAILABLE:
            return
        if self.controller_thread is not None and self.controller_thread.is_alive():
            return
        self.stop_threads = False
        self.controller_thread = threading.Thread(target=self._controller_loop, daemon=True)
        self.controller_thread.start()

    # --- Controller processing ---
    def _controller_loop(self):
        if not PYGAME_AVAILABLE:
            return

        logging.info("Controller thread starting.")
        try:
            pygame.init()
            pygame.joystick.init()
            self._refresh_joysticks()
        except Exception as exc:
            logging.error(f"Failed to init pygame joystick: {exc}")
            return

        while not self.stop_threads:
            try:
                self._mapping_timeout_check()
                for event in pygame.event.get():
                    self._handle_controller_event(event)
                time.sleep(0.005)
            except Exception as exc:
                logging.error(f"Controller loop error: {exc}")
                time.sleep(0.15)

        logging.info("Controller thread stopped.")
        try:
            pygame.quit()
        except Exception:
            pass

    def _refresh_joysticks(self):
        if not PYGAME_AVAILABLE:
            return
        for index in range(pygame.joystick.get_count()):
            try:
                joystick = pygame.joystick.Joystick(index)
                joystick.init()
                instance_id = joystick.get_instance_id()
                if instance_id not in self.joysticks:
                    self.joysticks[instance_id] = joystick
                    logging.info(f"Controller connected: {joystick.get_name()} ({instance_id})")
            except Exception as exc:
                logging.debug(f"Failed to init joystick index {index}: {exc}")

    def _remove_joystick(self, instance_id):
        if instance_id in self.joysticks:
            try:
                self.joysticks[instance_id].quit()
            except Exception:
                pass
            del self.joysticks[instance_id]
            logging.info(f"Controller removed: {instance_id}")

    def _event_instance_id(self, event):
        if hasattr(event, "instance_id"):
            return event.instance_id
        if hasattr(event, "joy"):
            return event.joy
        return -1

    def _handle_controller_event(self, event):
        etype = event.type

        if etype == pygame.JOYDEVICEADDED:
            self._refresh_joysticks()
            return
        if etype == pygame.JOYDEVICEREMOVED:
            instance_id = getattr(event, "instance_id", None)
            if instance_id is not None:
                self._remove_joystick(instance_id)
            return

        if etype == pygame.JOYBUTTONDOWN:
            token = f"button:{event.button}"
            self._controller_token_down(token)
            return

        if etype == pygame.JOYBUTTONUP:
            token = f"button:{event.button}"
            self._controller_token_up(token)
            return

        if etype == pygame.JOYHATMOTION:
            instance_id = self._event_instance_id(event)
            hat_index = int(getattr(event, "hat", 0))
            x, y = event.value
            current_tokens = set()
            if x < 0:
                current_tokens.add(f"hat:{hat_index}:left")
            if x > 0:
                current_tokens.add(f"hat:{hat_index}:right")
            if y < 0:
                current_tokens.add(f"hat:{hat_index}:down")
            if y > 0:
                current_tokens.add(f"hat:{hat_index}:up")

            key = (instance_id, hat_index)
            previous = self.hat_active.get(key, set())
            for token in current_tokens - previous:
                self._controller_token_down(token)
            for token in previous - current_tokens:
                self._controller_token_up(token)
            self.hat_active[key] = current_tokens
            return

        if etype == pygame.JOYAXISMOTION:
            instance_id = self._event_instance_id(event)
            axis = int(event.axis)
            value = float(event.value)
            threshold = float(self.controller_binding.axis_threshold)
            release_threshold = threshold * 0.75

            pos_token = f"axis:{axis}:pos"
            neg_token = f"axis:{axis}:neg"
            pos_key = (instance_id, axis, "pos")
            neg_key = (instance_id, axis, "neg")

            pos_active = self.axis_active.get(pos_key, False)
            neg_active = self.axis_active.get(neg_key, False)

            if value >= threshold and not pos_active:
                self.axis_active[pos_key] = True
                self._controller_token_down(pos_token)
            elif value < release_threshold and pos_active:
                self.axis_active[pos_key] = False
                self._controller_token_up(pos_token)

            if value <= -threshold and not neg_active:
                self.axis_active[neg_key] = True
                self._controller_token_down(neg_token)
            elif value > -release_threshold and neg_active:
                self.axis_active[neg_key] = False
                self._controller_token_up(neg_token)

    def _controller_token_down(self, token):
        token = token.lower().strip()
        if not token:
            return

        self.controller_pressed_tokens.add(token)

        if self.is_mapping:
            self._mapping_token_down(token)
            return

        if not self.controller_enabled:
            return

        now = time.time()
        triggered = self._binding_pressed(token, now)
        if not triggered:
            return

        if self.mode == "ptt":
            if not self.controller_trigger_active:
                self.controller_trigger_active = True
                self._start_recording(reason="controller_ptt")
        else:
            self._toggle()

    def _controller_token_up(self, token):
        token = token.lower().strip()
        if not token:
            return

        self.controller_pressed_tokens.discard(token)

        if self.controller_binding.style == "sequence" and token == self.sequence_hold_token:
            self.sequence_hold_token = None

        if self.is_mapping:
            self._mapping_token_up(token)
            return

        if not self.controller_enabled:
            return

        if self.controller_binding.style == "chord":
            required = set(self.controller_binding.events)
            if not required.issubset(self.controller_pressed_tokens):
                self.chord_latched = False

        if self.mode == "ptt" and self.controller_trigger_active:
            if not self._is_binding_active():
                self.controller_trigger_active = False
                self._stop_recording(reason="controller_ptt_release")

    def _binding_pressed(self, token, now):
        binding = self.controller_binding
        events = binding.events
        if not events:
            return False

        if binding.style == "single":
            return token == events[0]

        if binding.style == "chord":
            required = set(events)
            active = required.issubset(self.controller_pressed_tokens)
            if active and not self.chord_latched:
                self.chord_latched = True
                return True
            if not active:
                self.chord_latched = False
            return False

        # sequence
        window_seconds = max(0.1, binding.sequence_window_ms / 1000.0)
        if self.sequence_progress > 0 and (now - self.sequence_last_time) > window_seconds:
            self.sequence_progress = 0
            self.sequence_last_time = 0.0

        expected = events[self.sequence_progress] if self.sequence_progress < len(events) else events[0]
        if token == expected:
            self.sequence_progress += 1
            self.sequence_last_time = now
            if self.sequence_progress >= len(events):
                self.sequence_progress = 0
                self.sequence_last_time = 0.0
                self.sequence_hold_token = token
                return True
            return False

        if token == events[0]:
            self.sequence_progress = 1
            self.sequence_last_time = now
        else:
            self.sequence_progress = 0
            self.sequence_last_time = 0.0
        return False

    def _is_binding_active(self):
        binding = self.controller_binding
        events = binding.events
        if not events:
            return False

        if binding.style == "single":
            return events[0] in self.controller_pressed_tokens
        if binding.style == "chord":
            return set(events).issubset(self.controller_pressed_tokens)
        if self.sequence_hold_token:
            return self.sequence_hold_token in self.controller_pressed_tokens
        return False

    def _force_stop_trigger(self):
        logging.warning("Force stop hotkey triggered.")
        if self.is_recording:
            self.request_stop(reason="force_stop")
        if self.on_force_stop:
            self.on_force_stop()

    def _manual_send_trigger(self):
        if self.is_recording:
            logging.info("Ignored manual send hotkey while recording.")
            return
        logging.info("Manual send hotkey triggered.")
        if self.on_manual_send:
            self.on_manual_send()

    def _review_tts_trigger(self):
        logging.info("Review TTS hotkey triggered.")
        if self.on_review_tts:
            self.on_review_tts()

    def start(self):
        if self._running:
            logging.info("Hotkey listener already running; restart skipped.")
            return
        self.keyboard_hook_errors = []
        logging.info(
            "Hotkey listener start: "
            f"hotkey='{self.hotkey}' force_stop='{self.force_stop_key}' "
            f"manual_send='{self.manual_send_hotkey}' review_tts='{self.review_tts_hotkey}' "
            f"mode='{self.mode}'"
        )
        try:
            if self.mode == "ptt":
                h1 = keyboard.on_press_key(self.hotkey, self._on_ptt_press, suppress=False)
                h2 = keyboard.on_release_key(self.hotkey, self._on_ptt_release, suppress=False)
                self.keyboard_hooks.extend([h1, h2])
            else:
                self.toggle_hotkey_handle = keyboard.add_hotkey(self.hotkey, self._toggle, suppress=False)
        except Exception as exc:
            message = f"Failed to hook hotkey '{self.hotkey}': {exc}"
            self.keyboard_hook_errors.append(message)
            logging.error(message)

        if self.force_stop_key:
            try:
                self.force_stop_handle = keyboard.add_hotkey(
                    self.force_stop_key, self._force_stop_trigger, suppress=False
                )
            except Exception as exc:
                message = f"Failed to hook force stop key '{self.force_stop_key}': {exc}"
                self.keyboard_hook_errors.append(message)
                logging.error(message)

        if self.manual_send_hotkey:
            try:
                self.manual_send_handle = keyboard.add_hotkey(
                    self.manual_send_hotkey, self._manual_send_trigger, suppress=False
                )
            except Exception as exc:
                message = f"Failed to hook manual send key '{self.manual_send_hotkey}': {exc}"
                self.keyboard_hook_errors.append(message)
                logging.error(message)

        self.review_tts_deduped = False
        if self.review_tts_hotkey:
            manual_key = (self.manual_send_hotkey or "").strip().lower()
            review_key = (self.review_tts_hotkey or "").strip().lower()
            if manual_key and manual_key == review_key:
                self.review_tts_deduped = True
                logging.info(
                    "Review TTS hotkey matches primary action hotkey; skipping duplicate hook."
                )
            else:
                try:
                    self.review_tts_handle = keyboard.add_hotkey(
                        self.review_tts_hotkey, self._review_tts_trigger, suppress=False
                    )
                except Exception as exc:
                    message = f"Failed to hook review TTS key '{self.review_tts_hotkey}': {exc}"
                    self.keyboard_hook_errors.append(message)
                    logging.error(message)

        if self.controller_enabled:
            self._ensure_controller_thread()
        self._running = True

    def stop(self):
        self._running = False
        self.stop_threads = True
        if self.controller_thread:
            self.controller_thread.join(timeout=1.0)
            self.controller_thread = None

        for hook in self.keyboard_hooks:
            try:
                keyboard.unhook(hook)
            except Exception:
                pass
        self.keyboard_hooks = []

        if self.toggle_hotkey_handle is not None:
            try:
                keyboard.remove_hotkey(self.toggle_hotkey_handle)
            except Exception:
                pass
            self.toggle_hotkey_handle = None
        else:
            try:
                keyboard.remove_hotkey(self.hotkey)
            except Exception:
                pass

        if self.force_stop_handle is not None:
            try:
                keyboard.remove_hotkey(self.force_stop_handle)
            except Exception:
                pass
            self.force_stop_handle = None
        elif self.force_stop_key:
            try:
                keyboard.remove_hotkey(self.force_stop_key)
            except Exception:
                pass

        if self.manual_send_handle is not None:
            try:
                keyboard.remove_hotkey(self.manual_send_handle)
            except Exception:
                pass
            self.manual_send_handle = None
        elif self.manual_send_hotkey:
            try:
                keyboard.remove_hotkey(self.manual_send_hotkey)
            except Exception:
                pass

        if self.review_tts_handle is not None:
            try:
                keyboard.remove_hotkey(self.review_tts_handle)
            except Exception:
                pass
            self.review_tts_handle = None
        elif self.review_tts_hotkey and not self.review_tts_deduped:
            try:
                keyboard.remove_hotkey(self.review_tts_hotkey)
            except Exception:
                pass
        self.review_tts_deduped = False

    def update_config(self, profile_name):
        self.current_profile = profile_name
        config = load_profile(profile_name)

        old_hotkey = self.hotkey
        old_force_stop = self.force_stop_key
        old_manual_send = self.manual_send_hotkey
        old_review_tts = self.review_tts_hotkey
        old_mode = self.mode
        old_controller_enabled = self.controller_enabled

        self._load_runtime_config(config)

        keyboard_needs_restart = (
            old_hotkey != self.hotkey
            or old_force_stop != self.force_stop_key
            or old_manual_send != self.manual_send_hotkey
            or old_review_tts != self.review_tts_hotkey
            or old_mode != self.mode
        )
        controller_state_changed = old_controller_enabled != self.controller_enabled

        if keyboard_needs_restart and self._running:
            self.stop()
            self.start()
            return

        if controller_state_changed:
            if self.controller_enabled:
                self._ensure_controller_thread()
            else:
                self.stop_threads = True
                if self.controller_thread:
                    self.controller_thread.join(timeout=1.0)
                    self.controller_thread = None
