import logging
import hashlib
import os
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
from log_redaction import redact_exc


_URL_ONLY_RE = re.compile(r"^(https?://|www\.)\S+$", re.IGNORECASE)
_MAX_TTS_CHARS = 6000

IS_WINDOWS = platform_capabilities.IS_WINDOWS
_COPY_TRIGGER_TIMEOUT_SECONDS = 2
_MAX_CLIPBOARD_SNAPSHOT_BYTES = 20 * 1024 * 1024

# GetClipboardData does not always return an HGLOBAL.  In particular,
# CF_BITMAP/CF_PALETTE/CF_ENHMETAFILE return GDI handles, and passing those
# handles to GlobalSize/GlobalLock can trigger a native access violation on
# Windows.  These formats are documented as self-contained HGLOBAL payloads.
# Registered formats (HTML Format, Rich Text Format, and application-specific
# formats) also use HGLOBAL with the Win32 clipboard API.
_HGLOBAL_CLIPBOARD_FORMATS = frozenset(
    {
        0x0001,  # CF_TEXT
        0x0004,  # CF_SYLK
        0x0005,  # CF_DIF
        0x0006,  # CF_TIFF
        0x0007,  # CF_OEMTEXT
        0x0008,  # CF_DIB
        0x000A,  # CF_PENDATA
        0x000B,  # CF_RIFF
        0x000C,  # CF_WAVE
        0x000D,  # CF_UNICODETEXT
        0x000F,  # CF_HDROP
        0x0010,  # CF_LOCALE
        0x0011,  # CF_DIBV5
        0x0081,  # CF_DSPTEXT
    }
)
_REGISTERED_CLIPBOARD_FORMAT_FIRST = 0xC000
_REGISTERED_CLIPBOARD_FORMAT_LAST = 0xFFFF


def _backend(name: str, available: bool, required: list[str]) -> dict:
    return {
        "name": name,
        "available": bool(available),
        "required": list(required),
    }


def _selection_capture_support() -> dict:
    """Return the selection-capture backend available *right now*.

    Linux clipboard support is provided by an external command, so this must
    stay a live check rather than reusing platform capability values computed
    during module import.  That lets an operator install the missing package
    while BetterFingers is running and retry the hotkey successfully.
    """
    if IS_WINDOWS:
        clipboard = _backend("native", True, [])
        trigger = _backend("native-keyboard", True, [])
    elif platform_capabilities.is_macos:
        # README explicitly says macOS is not supported.  Do not silently use
        # keyboard.press_and_release here: the keyboard package may require
        # elevated privileges and this is not a qualified product path.
        clipboard = _backend("native", True, [])
        trigger = _backend("unsupported", False, ["macOS selection capture support"])
    elif platform_capabilities.is_wayland:
        display_missing = not bool(os.environ.get("WAYLAND_DISPLAY"))
        wl_paste = shutil.which("wl-paste")
        wl_copy = shutil.which("wl-copy")
        clipboard_available = bool(wl_paste and wl_copy and not display_missing)
        clipboard_requirements = []
        if display_missing:
            clipboard_requirements.append("WAYLAND_DISPLAY")
        if not wl_copy:
            clipboard_requirements.append("wl-copy")
        if not wl_paste:
            clipboard_requirements.append("wl-paste")
        clipboard = _backend(
            "wl-clipboard",
            clipboard_available,
            clipboard_requirements,
        )
        trigger_paths = {name: shutil.which(name) for name in ("wtype", "ydotool")}
        trigger_tool = next((name for name in ("wtype", "ydotool") if trigger_paths[name]), None)
        trigger = _backend(
            trigger_tool or "unsupported",
            bool(trigger_tool),
            [] if trigger_tool else ["wtype or ydotool"],
        )
    elif platform_capabilities.is_x11 or platform_capabilities.is_linux:
        display_missing = not bool(os.environ.get("DISPLAY"))
        clipboard_paths = {name: shutil.which(name) for name in ("xclip", "xsel")}
        clipboard_tool = next((name for name in ("xclip", "xsel") if clipboard_paths[name]), None)
        clipboard_requirements = ["DISPLAY"] if display_missing else []
        if not clipboard_tool:
            clipboard_requirements.append("xclip or xsel")
        clipboard = _backend(
            clipboard_tool or "unsupported",
            bool(clipboard_tool and not display_missing),
            clipboard_requirements,
        )
        xdotool_path = shutil.which("xdotool")
        trigger = _backend("xdotool" if xdotool_path else "unsupported", bool(xdotool_path), [] if xdotool_path else ["xdotool"])
    else:
        clipboard = _backend("unsupported", False, ["a supported clipboard tool"])
        trigger = _backend("unsupported", False, ["a supported copy trigger"])

    missing = clipboard["required"] + trigger["required"]
    missing_tool = (
        clipboard["required"][0]
        if clipboard["required"]
        else trigger["required"][0]
        if trigger["required"]
        else ""
    )
    return {
        "supported": clipboard["available"] and trigger["available"],
        "tool": clipboard["name"],
        "missing_tool": missing_tool,
        "missing_tools": " or ".join(missing) if missing else "",
        "clipboard_backend": clipboard,
        "copy_trigger_backend": trigger,
    }


def _unsupported_capture_result(support: dict) -> dict:
    missing_tool = str(support.get("missing_tool") or "a supported clipboard tool")
    clipboard = support.get("clipboard_backend") or {}
    trigger = support.get("copy_trigger_backend") or {}
    if not clipboard.get("available"):
        if missing_tool == "DISPLAY":
            message = "Can't read selected text — DISPLAY is not set for the active X11 session. Start BetterFingers inside an X11 desktop session and retry."
        elif missing_tool == "WAYLAND_DISPLAY":
            message = "Can't read selected text — WAYLAND_DISPLAY is not set for the active Wayland session. Start BetterFingers inside a Wayland desktop session and retry."
        elif missing_tool == "xclip or xsel":
            message = "Can't read selected text — xclip or xsel is not installed. Install xclip to enable this."
        elif missing_tool in {"wl-copy", "wl-paste"}:
            message = "Can't read selected text — wl-clipboard is not installed. Install wl-clipboard to enable this."
        else:
            message = f"Can't read selected text — {missing_tool} is not available on this system."
    elif not trigger.get("available"):
        if missing_tool == "xdotool":
            message = "Can't read selected text — xdotool is required to trigger Ctrl+C on X11. Install xdotool and retry."
        elif missing_tool == "wtype or ydotool":
            message = "Can't read selected text — Wayland needs wtype or ydotool to trigger Ctrl+C. Install one and retry."
        elif platform_capabilities.is_macos:
            message = "Can't read selected text — macOS selection capture is not supported yet."
        else:
            message = f"Can't read selected text — {missing_tool} is not available on this system."
    else:
        message = f"Can't read selected text — {missing_tool} is not available on this system."
    return {
        "ok": False,
        "text": "",
        "capture_status": "unsupported",
        "missing_tool": missing_tool,
        "missing_tools": support.get("missing_tools", missing_tool),
        "clipboard_backend": clipboard,
        "copy_trigger_backend": trigger,
        "message": message,
    }


def _trigger_selection_copy(trigger_backend: dict) -> dict:
    """Trigger Ctrl+C without invoking the privileged keyboard path on Linux."""
    tool = trigger_backend.get("name")
    if tool == "native-keyboard":
        try:
            keyboard.press_and_release("ctrl+c")
            return {"ok": True, "tool": tool}
        except Exception as exc:
            return {"ok": False, "tool": tool, "error": str(exc)}

    commands = {
        "xdotool": ["xdotool", "key", "--clearmodifiers", "ctrl+c"],
        "wtype": ["wtype", "-M", "ctrl", "-k", "c", "-m", "ctrl"],
        "ydotool": ["ydotool", "key", "29:1", "46:1", "46:0", "29:0"],
    }
    command = commands.get(tool)
    if not command:
        return {"ok": False, "tool": tool or "unsupported", "error": "no supported copy trigger"}
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            timeout=_COPY_TRIGGER_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logging.debug("%s copy trigger failed: %s", tool, exc)
        return {"ok": False, "tool": tool, "error": str(exc)}
    if result.returncode != 0:
        return {"ok": False, "tool": tool, "error": f"exit status {result.returncode}"}
    return {"ok": True, "tool": tool}


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


def _linux_clipboard_get_text(tool: str) -> str:
    commands = {
        "xclip": ["xclip", "-selection", "clipboard", "-o"],
        "xsel": ["xsel", "--clipboard", "--output"],
        "wl-clipboard": ["wl-paste", "--no-newline"],
    }
    command = commands.get(tool)
    if not command:
        return ""
    try:
        result = subprocess.run(command, check=False, capture_output=True, timeout=5)
        if result.returncode != 0:
            return ""
        return result.stdout.decode("utf-8", "replace")
    except Exception as exc:
        logging.debug(f"{tool} read failed: {exc}")
        return ""


def _linux_clipboard_set_text(tool: str, value: str) -> bool:
    commands = {
        "xclip": ["xclip", "-selection", "clipboard"],
        "xsel": ["xsel", "--clipboard", "--input"],
        "wl-clipboard": ["wl-copy"],
    }
    command = commands.get(tool)
    if not command:
        return False
    try:
        result = subprocess.run(
            command,
            input=(value or "").encode("utf-8"),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return result.returncode == 0
    except Exception as exc:
        logging.debug(f"{tool} write failed: {exc}")
        return False


def _clipboard_get_text() -> str:
    support = _selection_capture_support()
    if support.get("supported") and support.get("tool") in {"xclip", "xsel", "wl-clipboard"}:
        return _linux_clipboard_get_text(support["tool"])
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
    support = _selection_capture_support()
    if support.get("supported") and support.get("tool") in {"xclip", "xsel", "wl-clipboard"}:
        return _linux_clipboard_set_text(support["tool"], value)
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


def _is_hglobal_clipboard_format(fmt: int) -> bool:
    value = int(fmt)
    return value in _HGLOBAL_CLIPBOARD_FORMATS or (
        _REGISTERED_CLIPBOARD_FORMAT_FIRST
        <= value
        <= _REGISTERED_CLIPBOARD_FORMAT_LAST
    )


def _windows_clipboard_apis():
    """Return pointer-width-correct Win32 clipboard functions.

    ctypes otherwise assumes C ``int`` arguments and return values.  That
    truncates clipboard/global-memory handles in 64-bit Python even for formats
    which really are HGLOBAL-backed.
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_int
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_int
    user32.EnumClipboardFormats.argtypes = [ctypes.c_uint]
    user32.EnumClipboardFormats.restype = ctypes.c_uint
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = ctypes.c_int
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p

    kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_int
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p
    return user32, kernel32


def _capture_clipboard_snapshot_windows():
    if not IS_WINDOWS:
        return None

    try:
        user32, kernel32 = _windows_clipboard_apis()
    except Exception:
        return None

    snapshot = []
    opened = False
    try:
        if not user32.OpenClipboard(None):
            return None
        opened = True
        fmt = 0
        while True:
            fmt = int(user32.EnumClipboardFormats(fmt) or 0)
            if fmt == 0:
                break

            # A partial snapshot is not safe: restoring it would clear and
            # silently discard every unsupported format.  Abort before the
            # caller mutates the clipboard instead.
            if not _is_hglobal_clipboard_format(fmt):
                logging.debug(
                    "Clipboard format %s cannot be safely duplicated as HGLOBAL; "
                    "selection capture will fail closed.",
                    fmt,
                )
                return None

            handle = user32.GetClipboardData(fmt)
            if not handle:
                return None
            size = int(kernel32.GlobalSize(handle) or 0)
            if size <= 0 or size > _MAX_CLIPBOARD_SNAPSHOT_BYTES:
                logging.debug(
                    "Clipboard format %s has an unsafe snapshot size (%s bytes).",
                    fmt,
                    size,
                )
                return None
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return None
            try:
                payload = ctypes.string_at(ptr, size)
            finally:
                kernel32.GlobalUnlock(handle)
            snapshot.append((fmt, bytes(payload)))
    except Exception as exc:
        logging.debug("Failed to snapshot Windows clipboard: %s", exc)
        return None
    finally:
        if opened:
            try:
                user32.CloseClipboard()
            except Exception:
                pass

    return snapshot


def _restore_clipboard_snapshot_windows(snapshot):
    if not IS_WINDOWS or not snapshot:
        return False

    normalized = []
    for fmt, payload in snapshot:
        value = int(fmt)
        data = bytes(payload or b"")
        if not _is_hglobal_clipboard_format(value):
            return False
        if len(data) > _MAX_CLIPBOARD_SNAPSHOT_BYTES:
            return False
        normalized.append((value, data))

    try:
        user32, kernel32 = _windows_clipboard_apis()
    except Exception:
        return False

    gmem_moveable = 0x0002
    allocations = []
    opened = False
    try:
        # Allocate every replacement before EmptyClipboard.  A local memory
        # failure must not leave the clipboard partially erased.
        for fmt, data in normalized:
            size = max(1, len(data))
            hglobal = kernel32.GlobalAlloc(gmem_moveable, size)
            if not hglobal:
                return False
            allocations.append({"fmt": fmt, "handle": hglobal, "owned": True})
            ptr = kernel32.GlobalLock(hglobal)
            if not ptr:
                return False
            try:
                if data:
                    ctypes.memmove(ptr, data, len(data))
                else:
                    ctypes.memset(ptr, 0, size)
            finally:
                kernel32.GlobalUnlock(hglobal)

        if not user32.OpenClipboard(None):
            return False
        opened = True
        if not user32.EmptyClipboard():
            return False

        for allocation in allocations:
            if not user32.SetClipboardData(
                allocation["fmt"], allocation["handle"]
            ):
                return False
            # SetClipboardData transfers ownership to the system.
            allocation["owned"] = False
        return True
    except Exception as exc:
        logging.debug("Failed to restore Windows clipboard snapshot: %s", exc)
        return False
    finally:
        if opened:
            try:
                user32.CloseClipboard()
            except Exception:
                pass
        for allocation in allocations:
            if allocation["owned"]:
                try:
                    kernel32.GlobalFree(allocation["handle"])
                except Exception:
                    pass


def _snapshot_signature(snapshot):
    if not snapshot:
        return ()
    signature = []
    for fmt, payload in snapshot:
        data = bytes(payload or b"")
        digest = hashlib.sha256(data).hexdigest()
        signature.append((int(fmt), len(data), digest))
    return tuple(signature)


def _schedule_delayed_clipboard_restore(snapshot, expected_owned_snapshot=None, delay_ms=150):
    if not IS_WINDOWS:
        return
    if not snapshot or not expected_owned_snapshot:
        return

    expected_signature = _snapshot_signature(expected_owned_snapshot)
    if not expected_signature:
        return

    def _worker():
        try:
            time.sleep(max(0.05, float(delay_ms) / 1000.0))
            current = _capture_clipboard_snapshot_windows()
            if _snapshot_signature(current) == expected_signature:
                _restore_clipboard_snapshot_windows(snapshot)
        except Exception as exc:
            logging.debug("Delayed clipboard restore skipped: %s", exc)

    threading.Thread(target=_worker, name="ClipboardRestoreGuard", daemon=True).start()


def capture_selection_text_with_restore(timeout_ms=350, poll_ms=25) -> dict:
    timeout_ms = max(50, int(timeout_ms))
    poll_ms = max(5, int(poll_ms))
    attempts = max(1, timeout_ms // poll_ms)

    support = _selection_capture_support()
    if not support.get("supported"):
        return _unsupported_capture_result(support)

    original_text = _clipboard_get_text()
    original_snapshot = _capture_clipboard_snapshot_windows()
    if IS_WINDOWS and original_snapshot is None:
        return {
            "ok": False,
            "text": "",
            "used_fallback": False,
            "capture_status": "clipboard_preservation_unsupported",
            "message": (
                "Can't read selected text without risking clipboard data. "
                "Copy plain text once, then try again."
            ),
        }
    sentinel = f"__betterfingers_clipboard_probe_{uuid.uuid4().hex}__"
    captured_text = ""
    owned_snapshot = None

    try:
        if not _clipboard_set_text(sentinel):
            return {
                "ok": False,
                "text": "",
                "used_fallback": False,
                "capture_status": "clipboard_write_failed",
                "message": "Can't read selected text — clipboard probe could not be written. Try again.",
            }

        trigger = _trigger_selection_copy(support.get("copy_trigger_backend") or {})
        if not trigger.get("ok"):
            # A failed trigger leaves the original clipboard as the only
            # readable value. Never label that stale value as this selection.
            return {
                "ok": False,
                "text": "",
                "used_fallback": False,
                "capture_status": "trigger_failed",
                "message": (
                    "Can't read selected text — the copy trigger failed. "
                    "Select text and try again."
                ),
                "trigger": trigger,
            }

        for _ in range(attempts):
            current = _clipboard_get_text()
            if current and current != sentinel:
                captured_text = current
                try:
                    # Capture ownership at the first observation of the
                    # selected text. A later snapshot could belong to a new
                    # user copy and must not authorize delayed restoration.
                    owned_snapshot = _capture_clipboard_snapshot_windows()
                except Exception as exc:
                    logging.debug(
                        "Could not prove clipboard ownership at detection: %s",
                        redact_exc(exc),
                    )
                break
            time.sleep(poll_ms / 1000.0)

        if captured_text and is_readable_tts_text(captured_text):
            return {
                "ok": True,
                "text": _sanitize_tts_text(captured_text),
                "used_fallback": False,
                "capture_status": "captured",
                "message": "Captured selected text.",
            }

        return {
            "ok": False,
            "text": "",
            "used_fallback": False,
            "capture_status": "empty",
            "message": "Can't read selected text — no selected text was captured. Select text and try again.",
        }
    finally:
        restored = False
        if original_snapshot is not None:
            restored = _restore_clipboard_snapshot_windows(original_snapshot)
            if restored and owned_snapshot:
                _schedule_delayed_clipboard_restore(
                    original_snapshot,
                    expected_owned_snapshot=owned_snapshot,
                    delay_ms=max(120, poll_ms * 4),
                )
        if not restored and not _clipboard_set_text(original_text):
            logging.debug("Failed to restore original clipboard text after selection capture.")
