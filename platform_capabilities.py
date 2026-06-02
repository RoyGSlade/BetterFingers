import os
import platform as platform_module


platform = platform_module.system().lower() or "unknown"
session_type = (os.getenv("XDG_SESSION_TYPE") or "").strip().lower()
is_windows = platform == "windows"
is_linux = platform == "linux"
is_macos = platform == "darwin"
is_wayland = session_type == "wayland" or bool(os.getenv("WAYLAND_DISPLAY"))
is_x11 = session_type == "x11" or bool(os.getenv("DISPLAY"))

supports_basic_clipboard = is_windows or is_macos or is_linux
supports_rich_clipboard_restore = is_windows
supports_input_injection = is_windows or (is_linux and is_x11)
supports_global_hotkeys = is_windows or is_macos or (is_linux and is_x11)
supports_audio_ducking = is_windows
supports_stt = True
supports_llm = True
supports_tts = True


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
    }
