"""Per-application injection pacing.

Synthetic typing (``xdotool``/``ydotool`` "type") streams keystrokes as fast as
the tool emits them. Some targets can't keep up and drop or reorder characters —
the M2 injection probe saw this with LibreOffice, where a fast ``xdotool type``
mangles the inserted text. This module picks a pacing strategy for the focused
application: either slow the per-key delay, or fall back to an atomic clipboard
paste (which no target can mangle).

The active app is detected best-effort per platform (``xdotool`` on X11, the
foreground window on Windows) and normalized to a small set of app keys. When it
can't be determined — Wayland has no portable focused-window query, or the tools
are missing — detection returns ``""`` and callers use the safe default (type at
the tool's own rate), so pacing never blocks or breaks an injection.

Pure logic (``normalize_app`` / ``resolve_pacing``) is unit-tested; detection is
tested with the subprocess mocked.
"""

import logging
import os
import shutil
import subprocess

# Strategies.
TYPE = "type"
PASTE = "paste"

# xdotool's own default inter-keystroke delay when ``--delay`` is not given.
XDOTOOL_DEFAULT_DELAY_MS = 12

_DEFAULT = {"strategy": TYPE, "key_delay_ms": XDOTOOL_DEFAULT_DELAY_MS}

# Built-in policy: only the apps the probe flagged deviate from the default;
# everything else types at the tool's own rate. Keyed by normalized app key.
DEFAULT_PACING = {
    # LibreOffice drops/reorders characters under fast synthetic typing (M2).
    # An atomic paste can't be mangled, so it is the safe default there. The
    # key_delay_ms is the fallback rate if a user overrides strategy back to
    # "type".
    "libreoffice": {"strategy": PASTE, "key_delay_ms": 45},
}

# Window-class / process-name substrings → normalized app key. First match wins.
_APP_ALIASES = (
    ("soffice", "libreoffice"),
    ("libreoffice", "libreoffice"),
    ("gnome-terminal", "terminal"),
    ("konsole", "terminal"),
    ("xterm", "terminal"),
    ("alacritty", "terminal"),
    ("kitty", "terminal"),
    ("code", "vscode"),
    ("chromium", "chrome"),
    ("google-chrome", "chrome"),
    ("firefox", "firefox"),
)


def normalize_app(raw):
    """Map a raw window class / process name to a normalized app key ("" if
    empty). Unrecognized names collapse to their last dotted segment so a
    WM_CLASS like ``Navigator.Firefox`` and a process ``firefox`` agree."""
    if not raw:
        return ""
    token = str(raw).strip().lower()
    if not token:
        return ""
    for needle, key in _APP_ALIASES:
        if needle in token:
            return key
    return token.split(".")[-1]


def resolve_pacing(app_key, config=None):
    """Effective pacing for an app key: the built-in policy overlaid with user
    config.

    config keys:
      * ``per_app_pacing_enabled`` (bool, default True) — off → always the tool
        default (no per-app behavior).
      * ``injection_pacing_overrides`` (map app_key → {strategy, key_delay_ms}) —
        user tuning that wins over the built-in policy.
    """
    config = config or {}
    if not config.get("per_app_pacing_enabled", True):
        return dict(_DEFAULT)

    pacing = dict(_DEFAULT)
    if app_key in DEFAULT_PACING:
        pacing.update(DEFAULT_PACING[app_key])

    overrides = config.get("injection_pacing_overrides") or {}
    if isinstance(overrides, dict):
        override = overrides.get(app_key)
        if isinstance(override, dict):
            if override.get("strategy") in (TYPE, PASTE):
                pacing["strategy"] = override["strategy"]
            if "key_delay_ms" in override:
                try:
                    pacing["key_delay_ms"] = max(0, int(override["key_delay_ms"]))
                except (TypeError, ValueError):
                    pass
    return pacing


def _detect_x11_app():
    """Focused window's class (or title) on X11, or "" if unavailable."""
    if not os.environ.get("DISPLAY") or not shutil.which("xdotool"):
        return ""
    for query in ("getwindowclassname", "getwindowname"):
        try:
            out = subprocess.run(
                ["xdotool", "getactivewindow", query],
                check=False, capture_output=True, timeout=2,
            )
        except Exception as exc:  # subprocess/timeout — degrade to default
            logging.debug("active-window detect (x11 %s) failed: %s", query, exc)
            return ""
        lines = [ln for ln in (out.stdout or b"").decode("utf-8", "replace").splitlines() if ln.strip()]
        if lines:
            return lines[-1].strip()
    return ""


def _detect_windows_app():
    """Foreground window's process name on Windows, or "" if unavailable."""
    try:
        import ctypes

        import psutil

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return psutil.Process(pid.value).name()
    except Exception as exc:
        logging.debug("active-window detect (windows) failed: %s", exc)
        return ""


def detect_active_app_key():
    """Best-effort normalized key for the focused application. "" when it can't
    be determined (Wayland, missing tools) — callers fall back to the default."""
    import platform_capabilities

    raw = _detect_windows_app() if platform_capabilities.IS_WINDOWS else _detect_x11_app()
    return normalize_app(raw)
