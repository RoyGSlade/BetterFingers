import logging
import random
import subprocess
import threading
import time

import sys

import keyboard
import pyperclip

import clipboard_capture
import injection_pacing
import platform_capabilities

IS_WINDOWS = platform_capabilities.IS_WINDOWS

if IS_WINDOWS:
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


def _run_type_tool(argv, text=None) -> bool:
    """Shell out to an external typing tool (xdotool/wtype/ydotool).

    Returns True on success, False if the tool is missing or exits non-zero so
    the caller can fall back to clipboard paste. `text` is appended as the
    final argv element when given (typing tools take the payload last); omit
    it for a fixed-argument command like a hotkey press.
    """
    full_argv = argv + [text] if text is not None else argv
    try:
        result = subprocess.run(
            full_argv,
            check=False,
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            logging.debug(
                "Type tool %s exited %s: %s",
                full_argv[0],
                result.returncode,
                (result.stderr or b"").decode("utf-8", "replace").strip(),
            )
            return False
        return True
    except FileNotFoundError:
        logging.debug("Type tool not found: %s", full_argv[0])
        return False
    except Exception as exc:
        logging.debug("Type tool %s failed: %s", full_argv[0], exc)
        return False


class InputInjector:
    def __init__(self, profile_name="Default"):
        pydirectinput.PAUSE = 0.0
        self.current_profile = profile_name
        self.config = load_profile(self.current_profile)
        self._update_params()
        self.stop_signal = False
        self._voice_mute_lock = threading.Lock()
        self._held_voice_mute_key = ""
        # Runtime-selected text-injection backend:
        # "pydirectinput" | "xdotool" | "wtype" | "ydotool" | "paste" | "none".
        self.injection_method = platform_capabilities.injection_method
        logging.info(f"InputInjector active injection method: {self.injection_method}")

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
        # Whitespace is user content (indentation, trailing newlines, blank
        # lines) — strip only to decide emptiness, never the sent text.
        base = text or ""
        if not base.strip():
            return ""
        sign_off = (self.config.get("sign_off_text", "") or "").strip()
        if sign_off:
            base = f"{base} {sign_off}"
        return base

    def _type_via_external_tool(self, text: str, key_delay_ms=None) -> bool:
        """Type via the selected Linux backend. Returns True on success.

        key_delay_ms, when set, slows xdotool's inter-keystroke rate (its
        ``--delay``) so a slow target doesn't drop characters. wtype/ydotool
        have no portable per-key delay, so they ignore it — a mangling target
        under those backends is handled by the paste strategy in type_text.
        """
        method = self.injection_method
        if method == "xdotool":
            argv = ["xdotool", "type", "--clearmodifiers"]
            if key_delay_ms is not None:
                argv += ["--delay", str(max(0, int(key_delay_ms)))]
            argv += ["--"]
            return _run_type_tool(argv, text)
        if method == "wtype":
            return _run_type_tool(["wtype", "--"], text)
        if method == "ydotool":
            return _run_type_tool(["ydotool", "type"], text)
        return False

    def _active_injection_pacing(self):
        """Resolve the pacing strategy for the currently-focused app. Never
        raises — falls back to the tool default if detection/config fail."""
        default = {"strategy": injection_pacing.TYPE,
                   "key_delay_ms": injection_pacing.XDOTOOL_DEFAULT_DELAY_MS}
        try:
            if not self.config.get("per_app_pacing_enabled", True):
                return default
            app_key = injection_pacing.detect_active_app_key()
            pacing = injection_pacing.resolve_pacing(app_key, self.config)
            if app_key:
                logging.debug("injection pacing: app=%s strategy=%s delay=%sms",
                              app_key, pacing["strategy"], pacing["key_delay_ms"])
            return pacing
        except Exception as exc:
            logging.debug("injection pacing resolution failed; using default: %s", exc)
            return default

    def type_text(self, text: str):
        text = self._compose_output_text(text)
        if not text:
            return

        self.stop_signal = False

        # Non-Windows: route through the runtime injection matrix. External typing
        # tools (xdotool/wtype/ydotool) inject the whole string at once; if the
        # selected tool is missing or fails, fall back to clipboard paste, which
        # is the guaranteed universal fallback. Per-app pacing (below) slows the
        # keystroke rate for slow targets or, for known-mangling apps like
        # LibreOffice, uses an atomic paste that can't drop characters.
        if not IS_WINDOWS:
            if self.injection_method in ("xdotool", "wtype", "ydotool"):
                pacing = self._active_injection_pacing()
                if pacing["strategy"] == injection_pacing.PASTE:
                    self._paste_raw(text)
                    return
                if self._type_via_external_tool(text, key_delay_ms=pacing.get("key_delay_ms")):
                    return
                logging.warning(
                    f"Injection tool '{self.injection_method}' failed; falling back to paste."
                )
            self._paste_raw(text)
            return

        # Windows-only below this point: the `if not IS_WINDOWS` block above
        # always returns, so this `keyboard.write` is never reached on
        # Linux/macOS (where `keyboard` requires root and would raise).
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
        if IS_WINDOWS:
            try:
                keyboard.write(delta_text, delay=0)
            except Exception as exc:
                logging.debug(f"Live delta injection failed: {exc}")
            return
        # `keyboard` requires root on Linux/macOS, so it can't be used here.
        # Route the delta through the detected external tool instead; there's
        # no clipboard-paste equivalent for a streaming delta, so if no tool
        # is available we just drop it (debug-logged) rather than crash.
        if not self._type_via_external_tool(delta_text):
            logging.debug(
                f"Live delta injection unavailable (no external tool for "
                f"method '{self.injection_method}'); dropping delta."
            )

    def _send_paste_hotkey(self):
        """Send Ctrl+V using the platform-appropriate mechanism."""
        if IS_WINDOWS:
            pydirectinput.keyDown("ctrl")
            pydirectinput.press("v")
            pydirectinput.keyUp("ctrl")
            return
        # `keyboard` requires root on Linux ("You must be root to use this
        # library on linux") so, unlike Windows, it can never be used here.
        # Route Ctrl+V through the detected external tool instead.
        if not self._send_paste_via_tool():
            # No tool available (or it failed): _paste_raw already copied the
            # text to the clipboard via pyperclip before calling us, so the
            # honest fallback is telling the user to paste it themselves
            # rather than silently doing nothing.
            logging.warning(
                "No input-injection tool available to send Ctrl+V; the "
                "dictated text is on the clipboard — press Ctrl+V to paste it."
            )

    def _send_paste_via_tool(self) -> bool:
        """Send Ctrl+V via the detected external tool. Returns True on success.

        Mirrors `_type_via_external_tool`'s dispatch, but for a single hotkey
        rather than a text payload — this is what replaces
        `keyboard.press_and_release("ctrl+v")`, which requires root on Linux.
        """
        method = self.injection_method
        if method == "xdotool":
            return _run_type_tool(["xdotool", "key", "--clearmodifiers", "ctrl+v"])
        if method == "wtype":
            return _run_type_tool(["wtype", "-M", "ctrl", "v", "-m", "ctrl"])
        if method == "ydotool":
            # ctrl (keycode 29) down, v (keycode 47) down+up, ctrl up.
            return _run_type_tool(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"])
        return False

    def _press_key(self, key: str):
        """Press a single key (e.g. enter/esc/chat-open) cross-platform."""
        if IS_WINDOWS:
            pydirectinput.press(key)
        else:
            keyboard.press_and_release(key)

    def _paste_raw(self, text: str):
        """Copy already-composed text to the clipboard and paste it.

        This is the guaranteed universal fallback across all platforms. Unless
        disabled, the user's prior clipboard is restored shortly after the paste
        so injecting a draft doesn't destroy whatever they had copied.
        """
        if not text:
            return
        restore = bool(self.config.get("restore_clipboard_after_paste", True))
        prior_clipboard = None
        if restore:
            try:
                prior_clipboard = clipboard_capture.get_clipboard_text()
            except Exception as exc:
                logging.debug(f"Could not snapshot clipboard before paste: {exc}")
                prior_clipboard = None
        try:
            pyperclip.copy(text)
            self._send_paste_hotkey()
        except Exception as exc:
            logging.error(f"Paste injection failed ({exc}); falling back to instant type.")
            self._fallback_type_after_paste_failure(text)
            return
        if restore and prior_clipboard is not None:
            clipboard_capture.schedule_text_clipboard_restore(prior_clipboard, text)

    def _fallback_type_after_paste_failure(self, text: str):
        """Last-resort typing when the paste path itself raised an exception.

        Windows keeps using `keyboard.write` here — unchanged behavior. On
        Linux/macOS `keyboard` requires root (this is what used to produce
        "Fallback typing failed: You must be root to use this library on
        linux" right after the paste-hotkey failure above), so route through
        the detected external tool instead. If none is available, the text is
        still sitting on the clipboard from the `pyperclip.copy` above, so log
        a clear hint instead of raising the same root-permission error again.
        """
        if IS_WINDOWS:
            try:
                keyboard.write(text, delay=0)
            except Exception as fallback_exc:
                logging.error(f"Fallback typing failed: {fallback_exc}")
            return
        if self._type_via_external_tool(text):
            return
        logging.warning(
            "Fallback typing unavailable; the text is on the clipboard — "
            "press Ctrl+V to paste it manually."
        )

    def paste_text(self, text: str):
        text = self._compose_output_text(text)
        self._paste_raw(text)

    def open_chat(self):
        key = (self.config.get("chat_open_key", "") or "").strip()
        if not key:
            return
        try:
            self._press_key(key)
            time.sleep(0.08)
        except Exception as exc:
            logging.error(f"Failed to open chat with '{key}': {exc}")

    def close_chat(self, action: str = "none"):
        action = (action or "none").strip().lower()
        if action == "none":
            return
        try:
            if action == "esc":
                self._press_key("esc")
            elif action == "chat_key":
                key = (self.config.get("chat_open_key", "") or "").strip()
                if key:
                    self._press_key(key)
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
                self._press_key("enter")
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
