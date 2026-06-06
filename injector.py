import logging
import random
import threading
import time

import sys

import keyboard
import pyperclip

if sys.platform == "win32":
    import pydirectinput
else:
    # pydirectinput uses ctypes.windll which is Windows-only.
    # Stub it on Linux so this module and its tests collect cleanly.
    import types as _types
    pydirectinput = _types.SimpleNamespace(
        PAUSE=0.0,
        keyDown=lambda key: None,
        keyUp=lambda key: None,
        press=lambda key: None,
    )

from utils import load_profile


class InputInjector:
    def __init__(self, profile_name="Default"):
        pydirectinput.PAUSE = 0.0
        self.current_profile = profile_name
        self.config = load_profile(self.current_profile)
        self._update_params()
        self.stop_signal = False
        self._voice_mute_lock = threading.Lock()
        self._held_voice_mute_key = ""

    def _update_params(self):
        self.min_hold = float(self.config.get("min_key_hold", 0.015))
        self.max_hold = float(self.config.get("max_key_hold", 0.035))
        self.min_delay = float(self.config.get("min_inter_key_delay", 0.08))
        self.max_delay = float(self.config.get("max_inter_key_delay", 0.16))

    def reload_config(self, profile_name="Default"):
        logging.info(f"Reloading injector config for profile: {profile_name}")
        old_held_key = ""
        with self._voice_mute_lock:
            old_held_key = self._held_voice_mute_key

        self.current_profile = profile_name
        self.config = load_profile(self.current_profile)
        self._update_params()

        if old_held_key:
            ducking_enabled = bool(self.config.get("audio_ducking", False))
            if not ducking_enabled:
                self.release_mute_key()

    def stop_typing(self):
        self.stop_signal = True

    def _compose_output_text(self, text: str) -> str:
        base = (text or "").strip()
        if not base:
            return ""
        sign_off = (self.config.get("sign_off_text", "") or "").strip()
        if sign_off:
            base = f"{base} {sign_off}".strip()
        return base

    def type_text(self, text: str):
        text = self._compose_output_text(text)
        if not text:
            return

        self.stop_signal = False
        is_instant = bool(self.config.get("instant_typing", False))

        if is_instant:
            try:
                keyboard.write(text, delay=0)
            except Exception as exc:
                logging.error(f"Instant typing failed: {exc}")
            return

        for char in text:
            if self.stop_signal:
                return

            key = char
            is_upper = False
            if char == " ":
                key = "space"
            elif char.isupper():
                is_upper = True
                key = char.lower()

            if is_upper:
                pydirectinput.keyDown("shift")
                time.sleep(random.uniform(0.006, 0.02))

            try:
                pydirectinput.keyDown(key)
            except Exception as exc:
                logging.debug(f"Could not type key '{key}': {exc}")
                if is_upper:
                    pydirectinput.keyUp("shift")
                continue

            time.sleep(random.uniform(self.min_hold, self.max_hold))
            pydirectinput.keyUp(key)

            if is_upper:
                time.sleep(random.uniform(0.004, 0.012))
                pydirectinput.keyUp("shift")

            time.sleep(random.uniform(self.min_delay, self.max_delay))

    def type_live_delta(self, delta_text: str):
        if not delta_text:
            return
        try:
            keyboard.write(delta_text, delay=0)
        except Exception as exc:
            logging.debug(f"Live delta injection failed: {exc}")

    def paste_text(self, text: str):
        text = self._compose_output_text(text)
        if not text:
            return

        try:
            pyperclip.copy(text)
            pydirectinput.keyDown("ctrl")
            pydirectinput.press("v")
            pydirectinput.keyUp("ctrl")
        except Exception as exc:
            logging.error(f"Paste injection failed ({exc}); falling back to instant type.")
            try:
                keyboard.write(text, delay=0)
            except Exception as fallback_exc:
                logging.error(f"Fallback typing failed: {fallback_exc}")

    def open_chat(self):
        key = (self.config.get("chat_open_key", "") or "").strip()
        if not key:
            return
        try:
            pydirectinput.press(key)
            time.sleep(0.08)
        except Exception as exc:
            logging.error(f"Failed to open chat with '{key}': {exc}")

    def close_chat(self, action: str = "none"):
        action = (action or "none").strip().lower()
        if action == "none":
            return
        try:
            if action == "esc":
                pydirectinput.press("esc")
            elif action == "chat_key":
                key = (self.config.get("chat_open_key", "") or "").strip()
                if key:
                    pydirectinput.press(key)
        except Exception as exc:
            logging.error(f"Failed close-chat action '{action}': {exc}")

    def send_output(
        self,
        text: str,
        auto_submit: bool = False,
        close_action: str = "none",
    ):
        if bool(self.config.get("instant_typing", False)):
            self.type_text(text)
        else:
            self.paste_text(text)

        if auto_submit:
            try:
                time.sleep(max(0.01, self.min_delay))
                pydirectinput.press("enter")
            except Exception as exc:
                logging.error(f"Auto submit failed: {exc}")

        self.close_chat(close_action)

    def hold_mute_key(self):
        if not self.config.get("audio_ducking", False):
            return
        key = (self.config.get("voice_mute_key", "") or "").strip()
        if not key:
            return
        with self._voice_mute_lock:
            if self._held_voice_mute_key:
                return
        try:
            keyboard.press(key)
            with self._voice_mute_lock:
                self._held_voice_mute_key = key
        except Exception as exc:
            logging.error(f"Failed to hold mute key '{key}': {exc}")

    def release_mute_key(self):
        with self._voice_mute_lock:
            key = self._held_voice_mute_key
        if not key:
            return
        try:
            keyboard.release(key)
            with self._voice_mute_lock:
                if self._held_voice_mute_key == key:
                    self._held_voice_mute_key = ""
        except Exception as exc:
            logging.error(f"Failed to release mute key '{key}': {exc}")
