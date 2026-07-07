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


def detect_injection_method():
    """Pick the best available text-injection backend for this platform.

    Returns one of: "pydirectinput" | "xdotool" | "wtype" | "ydotool" | "paste".
    Clipboard-paste ("paste") is the guaranteed universal fallback and is always
    available wherever the clipboard works. "none" is only returned when even the
    clipboard is unavailable.
    """
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
    if supports_basic_clipboard:
        return "paste"
    return "none"


supports_basic_clipboard = is_windows or is_macos or is_linux
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
    }
