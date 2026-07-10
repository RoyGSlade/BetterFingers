import logging
import re
import shutil
import subprocess
import threading
import time
import uuid
import ctypes

import keyboard
import pyperclip

import platform_capabilities


_URL_ONLY_RE = re.compile(r"^(https?://|www\.)\S+$", re.IGNORECASE)
_MAX_TTS_CHARS = 6000

IS_WINDOWS = platform_capabilities.IS_WINDOWS


def _wayland_clipboard_get_text() -> str:
    """Best-effort Wayland clipboard read via wl-clipboard's `wl-paste`.

    pyperclip cannot read the Wayland selection on many setups; if wl-paste is
    available, use it as a fallback. Returns "" on any failure.
    """
    if not (platform_capabilities.is_wayland and shutil.which("wl-paste")):
        return ""
    try:
        result = subprocess.run(
            ["wl-paste", "--no-newline"],
            check=False,
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.decode("utf-8", "replace")
    except Exception as exc:
        logging.debug(f"wl-paste read failed: {exc}")
        return ""


def _clipboard_get_text() -> str:
    try:
        value = pyperclip.paste()
        text = str(value or "")
    except Exception as exc:
        logging.debug(f"Clipboard read failed: {exc}")
        text = ""
    if not text:
        # Best-effort Wayland fallback where pyperclip returns nothing.
        wayland_text = _wayland_clipboard_get_text()
        if wayland_text:
            return wayland_text
    return text


def _clipboard_set_text(value: str) -> bool:
    try:
        pyperclip.copy(value or "")
        return True
    except Exception as exc:
        logging.debug(f"Clipboard write failed: {exc}")
        return False


def get_clipboard_text() -> str:
    """Public cross-platform snapshot of the current clipboard text."""
    return _clipboard_get_text()


def schedule_text_clipboard_restore(prior_text: str, injected_text: str, delay_ms: int = 300):
    """Restore the user's prior clipboard after a paste-injection, on a background
    thread. Only restores if ``injected_text`` is *still* on the clipboard — i.e.
    the paste consumed it and the user hasn't copied anything new — so it never
    clobbers a fresh copy. Fire-and-forget; a no-op when nothing changed.

    The delay lets the target app's paste read our text before we swap it back."""
    if prior_text == injected_text:
        return

    def _worker():
        try:
            time.sleep(max(0, int(delay_ms)) / 1000.0)
            current = _clipboard_get_text()
            if current == injected_text:
                _clipboard_set_text(prior_text)
        except Exception as exc:
            logging.debug(f"Clipboard text restore skipped: {exc}")

    threading.Thread(target=_worker, daemon=True).start()


def _sanitize_tts_text(text: str) -> str:
    value = (text or "").strip()
    if len(value) <= _MAX_TTS_CHARS:
        return value
    return value[:_MAX_TTS_CHARS].rstrip()


def is_readable_tts_text(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return False

    if not any(ch.isalpha() for ch in value):
        return False

    tokens = value.split()
    if len(tokens) == 1 and _URL_ONLY_RE.match(tokens[0]):
        return False

    non_alnum = sum(1 for ch in value if not ch.isalnum() and not ch.isspace())
    ratio = non_alnum / max(1, len(value))
    if ratio > 0.55:
        return False

    return True


def _capture_clipboard_snapshot_windows():
    if not IS_WINDOWS:
        return None

    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
    except Exception:
        return None

    snapshot = []
    try:
        if not user32.OpenClipboard(None):
            return None
        fmt = 0
        while True:
            fmt = user32.EnumClipboardFormats(fmt)
            if fmt == 0:
                break
            handle = user32.GetClipboardData(fmt)
            if not handle:
                continue
            size = int(kernel32.GlobalSize(handle) or 0)
            if size <= 0:
                continue
            if size > 20 * 1024 * 1024:  # Skip if > 20MB to prevent freeze
                logging.warning(f"Skipping clipboard format {fmt} (size={size}) - too large.")
                continue
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                continue
            try:
                payload = ctypes.string_at(ptr, size)
            finally:
                kernel32.GlobalUnlock(handle)
            snapshot.append((int(fmt), bytes(payload)))
    except Exception as exc:
        logging.debug("Failed to snapshot Windows clipboard: %s", exc)
        snapshot = None
    finally:
        try:
            user32.CloseClipboard()
        except Exception:
            pass

    return snapshot


def _restore_clipboard_snapshot_windows(snapshot):
    if not IS_WINDOWS:
        return False
    if not snapshot:
        return False

    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
    except Exception:
        return False

    GMEM_MOVEABLE = 0x0002
    restored_any = False
    try:
        if not user32.OpenClipboard(None):
            return False
        user32.EmptyClipboard()
        for fmt, payload in snapshot:
            data = bytes(payload or b"")
            size = max(1, len(data))
            hglobal = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
            if not hglobal:
                continue
            ptr = kernel32.GlobalLock(hglobal)
            if not ptr:
                kernel32.GlobalFree(hglobal)
                continue
            try:
                if data:
                    ctypes.memmove(ptr, data, len(data))
                else:
                    ctypes.memset(ptr, 0, size)
            finally:
                kernel32.GlobalUnlock(hglobal)
            if not user32.SetClipboardData(int(fmt), hglobal):
                kernel32.GlobalFree(hglobal)
                continue
            restored_any = True
    except Exception as exc:
        logging.debug("Failed to restore Windows clipboard snapshot: %s", exc)
        return False
    finally:
        try:
            user32.CloseClipboard()
        except Exception:
            pass

    return restored_any


def _snapshot_signature(snapshot):
    if not snapshot:
        return ()
    signature = []
    for fmt, payload in snapshot:
        data = bytes(payload or b"")
        signature.append((int(fmt), len(data), data[:32]))
    return tuple(signature)


def _schedule_delayed_clipboard_restore(snapshot, delay_ms=150):
    if not IS_WINDOWS:
        return
    if not snapshot:
        return

    target_signature = _snapshot_signature(snapshot)

    def _worker():
        try:
            time.sleep(max(0.05, float(delay_ms) / 1000.0))
            current = _capture_clipboard_snapshot_windows()
            if _snapshot_signature(current) != target_signature:
                _restore_clipboard_snapshot_windows(snapshot)
        except Exception as exc:
            logging.debug("Delayed clipboard restore skipped: %s", exc)

    threading.Thread(target=_worker, name="ClipboardRestoreGuard", daemon=True).start()


def capture_selection_text_with_restore(timeout_ms=350, poll_ms=25) -> dict:
    timeout_ms = max(50, int(timeout_ms))
    poll_ms = max(5, int(poll_ms))
    attempts = max(1, timeout_ms // poll_ms)

    original_text = _clipboard_get_text()
    original_snapshot = _capture_clipboard_snapshot_windows()
    sentinel = f"__betterfingers_clipboard_probe_{uuid.uuid4().hex}__"
    captured_text = ""

    try:
        _clipboard_set_text(sentinel)
        try:
            keyboard.press_and_release("ctrl+c")
        except Exception as exc:
            logging.debug(f"Ctrl+C trigger failed during selection capture: {exc}")

        for _ in range(attempts):
            current = _clipboard_get_text()
            if current and current != sentinel:
                captured_text = current
                break
            time.sleep(poll_ms / 1000.0)

        if captured_text and is_readable_tts_text(captured_text):
            return {
                "ok": True,
                "text": _sanitize_tts_text(captured_text),
                "used_fallback": False,
                "message": "Captured selected text.",
            }

        if is_readable_tts_text(original_text):
            return {
                "ok": True,
                "text": _sanitize_tts_text(original_text),
                "used_fallback": True,
                "message": "Using existing clipboard text fallback.",
            }

        return {
            "ok": False,
            "text": "",
            "used_fallback": False,
            "message": "No readable selected/copied text found.",
        }
    finally:
        restored = False
        if original_snapshot is not None:
            restored = _restore_clipboard_snapshot_windows(original_snapshot)
            if restored:
                _schedule_delayed_clipboard_restore(original_snapshot, delay_ms=max(120, poll_ms * 4))
        if not restored and not _clipboard_set_text(original_text):
            logging.debug("Failed to restore original clipboard text after selection capture.")
