"""Selection capture adapter (Phase 2 Wave 2A, F2.5).

Thin, test-friendly wrapper around ``clipboard_capture.capture_selection_text_with_restore``
that turns its raw ``{ok, text, used_fallback, message}`` result into an explicit
outcome — ``selection``, ``clipboard_fallback``, ``empty``, or ``unsupported`` — instead
of leaking the raw flag pair to callers. Clipboard save/restore is entirely owned by
``clipboard_capture``'s existing ``finally`` block; this module never touches the
clipboard directly, and never logs captured text.

``capture_fn``/``supported_fn`` are injectable so the core adapter logic is testable
without a real clipboard, keyboard, or display server.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

SelectionOutcome = Literal["selection", "clipboard_fallback", "empty", "unsupported"]


@dataclass(frozen=True)
class SelectionCaptureResult:
    outcome: SelectionOutcome
    text: str = ""


def selection_capture_supported() -> bool:
    """Whether the complete selection-capture backend is available right now.

    ``clipboard_capture`` owns the live clipboard and copy-trigger capability
    checks; this adapter only exposes their structured ``supported`` result.
    """
    import clipboard_capture

    return bool(clipboard_capture._selection_capture_support().get("supported"))


def capture_selection(
    capture_fn: Callable[[], dict] | None = None,
    supported_fn: Callable[[], bool] | None = None,
) -> SelectionCaptureResult:
    """Capture the current selection, classifying the result explicitly.

    Returns ``unsupported`` before attempting any capture when the platform has
    no working clipboard mechanism (e.g. Wayland without wl-clipboard). Returns
    ``empty`` when capture ran but found no readable text. Otherwise returns
    ``selection`` for freshly copied text. The ``clipboard_fallback`` outcome
    remains available for explicitly injected legacy adapter results; the
    concrete clipboard capture path never produces that outcome.
    """
    is_supported = (supported_fn or selection_capture_supported)()
    if not is_supported:
        return SelectionCaptureResult(outcome="unsupported")

    if capture_fn is None:
        import clipboard_capture

        capture_fn = clipboard_capture.capture_selection_text_with_restore

    raw = capture_fn() or {}
    text = raw.get("text") or ""
    if not raw.get("ok") or not text:
        return SelectionCaptureResult(outcome="empty")

    outcome: SelectionOutcome = "clipboard_fallback" if raw.get("used_fallback") else "selection"
    return SelectionCaptureResult(outcome=outcome, text=text)
