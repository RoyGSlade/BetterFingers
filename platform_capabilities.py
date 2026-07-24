import os
import platform as platform_module
import shutil
import sys


# Standardized platform detection. Prefer sys.platform == "win32" for exactness
# across the codebase; expose it here as a shared helper so injector.py /
# model_manager.py / audio_ducker.py / clipboard_capture.py agree.
IS_WINDOWS = sys.platform == "win32"


platform = platform_module.system().lower() or "unknown"
session_type = (os.getenv("XDG_SESSION_TYPE") or "").strip().lower()
is_windows = platform == "windows"
is_linux = platform == "linux"
is_macos = platform == "darwin"
is_wayland = session_type == "wayland" or bool(os.getenv("WAYLAND_DISPLAY"))
is_x11 = session_type == "x11" or bool(os.getenv("DISPLAY"))


def _detect_clipboard_backend():
    """Name of a working clipboard mechanism, or "" if none is available.

    On Linux, pyperclip drives the clipboard through an external tool; without
    one, *both* copy and paste fail at runtime — so clipboard-paste injection is
    not actually available even though the platform "has a clipboard". Windows and
    macOS ship a native mechanism. Assuming Linux always has a clipboard (the old
    behavior) made the app report a "paste" injection method that then failed on
    a stock box without xclip/xsel/wl-clipboard.
    """
    if is_windows or is_macos:
        return "native"
    if is_linux:
        if is_wayland and shutil.which("wl-copy"):
            return "wl-copy"
        for tool in ("xclip", "xsel"):
            if shutil.which(tool):
                return tool
        if shutil.which("wl-copy"):  # also works under some XWayland setups
            return "wl-copy"
    return ""


def detect_injection_method(clipboard_available=None):
    """Pick the best available text-injection backend for this platform.

    Returns one of: "pydirectinput" | "xdotool" | "wtype" | "ydotool" | "paste".
    Clipboard-paste ("paste") is the guaranteed universal fallback and is always
    available wherever the clipboard works. "none" is only returned when even the
    clipboard is unavailable.

    `clipboard_available` overrides the cached `supports_basic_clipboard` check
    for the paste-vs-none decision below; defaults to that module-level global
    (computed once at import) so existing callers are unaffected. A fresh,
    non-cached re-check (see `get_injection_status`) passes in a just-detected
    value instead, so e.g. a clipboard tool installed after startup is
    reflected immediately rather than only after a restart.
    """
    if clipboard_available is None:
        clipboard_available = supports_basic_clipboard

    if is_windows:
        # pydirectinput drives the Windows path; if for some reason it's missing,
        # paste still works.
        return "pydirectinput"

    if is_linux:
        if is_wayland:
            if shutil.which("wtype"):
                return "wtype"
            if shutil.which("ydotool"):
                return "ydotool"
            # Some Wayland compositors still expose an XWayland DISPLAY; xdotool
            # only works for XWayland clients, so prefer wtype/ydotool above.
            if is_x11 and shutil.which("xdotool"):
                return "xdotool"
        else:
            if shutil.which("xdotool"):
                return "xdotool"
    # macOS and any Linux without a typing tool fall back to clipboard paste.
    if clipboard_available:
        return "paste"
    return "none"


clipboard_backend = _detect_clipboard_backend()
# Real capability: on Linux this is False without xclip/xsel/wl-clipboard.
supports_basic_clipboard = bool(clipboard_backend)
supports_rich_clipboard_restore = is_windows
supports_global_hotkeys = is_windows or is_macos or (is_linux and is_x11)
# Linux audio ducking is best-effort via PipeWire/PulseAudio's `pactl`.
supports_audio_ducking = is_windows or (is_linux and bool(shutil.which("pactl")))
supports_stt = True
supports_llm = True
supports_tts = True

# Actual runtime injection capability (chosen backend + whether real typing works).
injection_method = detect_injection_method()
supports_typing = injection_method not in ("paste", "none")
# We can inject input as long as we have at least a working paste path.
supports_input_injection = injection_method != "none"


def injection_hint(method=None):
    """User-facing guidance when injection is unavailable, else "".

    Defaults to the cached startup-time `injection_method`. Callers doing a
    fresh check (see `get_injection_status` below) can pass a just-detected
    method instead, so the hint reflects the tool situation right now rather
    than whatever was true when this module was first imported.
    """
    if method is None:
        method = injection_method
    if method != "none":
        return ""
    if is_linux:
        tool = "wl-clipboard" if is_wayland else "xclip (or xsel)"
        return f"Text injection is unavailable: install {tool} to enable clipboard paste."
    return "Text injection is unavailable on this system."


# CLI binary each Linux typing method shells out to (see injector.py's
# _type_via_external_tool / _send_paste_via_tool). Windows' pydirectinput and
# the universal "paste"/"none" fallbacks need no separate external tool here
# -- "paste"'s dependency is the clipboard backend, already surfaced via
# `clipboard_backend` / `_detect_clipboard_backend()`.
_INJECTION_METHOD_TOOL = {
    "xdotool": "xdotool",
    "wtype": "wtype",
    "ydotool": "ydotool",
}


def required_injection_tool(method):
    """CLI binary `method` depends on, or None if it needs no external tool."""
    return _INJECTION_METHOD_TOOL.get(method)


def get_injection_status():
    """Live (non-cached) snapshot of the injection situation, for diagnostics.

    `injection_method` / `clipboard_backend` above are computed once at import
    time so the running InputInjector's choice is stable for the process's
    lifetime. This instead re-runs the same shutil.which() PATH lookups on
    every call -- no keys are typed, no clipboard is touched, no cursor moves,
    nothing is injected -- so a status route (e.g. /doctor) can honestly
    report a tool that was installed or removed after startup, rather than
    silently repeating a stale verdict.
    """
    live_clipboard_backend = _detect_clipboard_backend()
    live_method = detect_injection_method(clipboard_available=bool(live_clipboard_backend))
    tool = required_injection_tool(live_method)
    if tool is not None:
        tool_available = bool(shutil.which(tool))
    else:
        # paste/pydirectinput need no separate typing tool; "none" means even
        # clipboard-paste isn't available, so report that honestly instead of
        # defaulting to True.
        tool_available = live_method != "none"
    return {
        "method": live_method,
        "required_tool": tool,
        "tool_available": tool_available,
        "clipboard_backend": live_clipboard_backend,
        "supports_typing": live_method not in ("paste", "none"),
        "supports_input_injection": live_method != "none",
        "session_type": session_type or "unknown",
        "is_wayland": is_wayland,
        "is_x11": is_x11,
        "hint": injection_hint(live_method),
    }


def get_capabilities():
    return {
        "platform": platform,
        "session_type": session_type or "unknown",
        "is_windows": is_windows,
        "is_linux": is_linux,
        "is_wayland": is_wayland,
        "is_x11": is_x11,
        "supports_basic_clipboard": supports_basic_clipboard,
        "supports_rich_clipboard_restore": supports_rich_clipboard_restore,
        "supports_input_injection": supports_input_injection,
        "supports_global_hotkeys": supports_global_hotkeys,
        "supports_audio_ducking": supports_audio_ducking,
        "supports_stt": supports_stt,
        "supports_llm": supports_llm,
        "supports_tts": supports_tts,
        "injection_method": injection_method,
        "supports_typing": supports_typing,
        "clipboard_backend": clipboard_backend,
        "injection_hint": injection_hint(),
    }
