"""Selection capture adapter tests (F2.5).

Everything here is driven through injected ``capture_fn``/``supported_fn``
stand-ins, so no real clipboard, keyboard, or display server is touched.
"""

from backend.services.selection_capture import SelectionCaptureResult, capture_selection


def _supported_true():
    return True


def _supported_false():
    return False


def test_fresh_selection_classified_as_selection():
    result = capture_selection(
        capture_fn=lambda: {"ok": True, "text": "Meet at noon", "used_fallback": False},
        supported_fn=_supported_true,
    )
    assert result == SelectionCaptureResult(outcome="selection", text="Meet at noon")


def test_preexisting_clipboard_classified_as_fallback():
    result = capture_selection(
        capture_fn=lambda: {"ok": True, "text": "Old copy", "used_fallback": True},
        supported_fn=_supported_true,
    )
    assert result == SelectionCaptureResult(outcome="clipboard_fallback", text="Old copy")


def test_no_readable_text_classified_as_empty():
    result = capture_selection(
        capture_fn=lambda: {"ok": False, "text": "", "used_fallback": False},
        supported_fn=_supported_true,
    )
    assert result == SelectionCaptureResult(outcome="empty", text="")


def test_ok_but_blank_text_still_classified_as_empty():
    result = capture_selection(
        capture_fn=lambda: {"ok": True, "text": "", "used_fallback": False},
        supported_fn=_supported_true,
    )
    assert result.outcome == "empty"


def test_unsupported_platform_short_circuits_before_capture():
    calls = []

    def _capture():
        calls.append(1)
        return {"ok": True, "text": "should not be reached", "used_fallback": False}

    result = capture_selection(capture_fn=_capture, supported_fn=_supported_false)
    assert result == SelectionCaptureResult(outcome="unsupported", text="")
    assert calls == []  # never attempted capture once platform is unsupported


def test_default_supported_fn_reflects_platform_capabilities(monkeypatch):
    import platform_capabilities

    monkeypatch.setattr(platform_capabilities, "_detect_clipboard_backend", lambda: "")
    result = capture_selection(capture_fn=lambda: {"ok": True, "text": "x", "used_fallback": False})
    assert result.outcome == "unsupported"


def test_default_capture_fn_restores_clipboard_via_existing_adapter(monkeypatch):
    """No capture_fn override: exercises the real clipboard_capture path, but with
    the clipboard itself faked out (same technique as test_clipboard_capture.py),
    so restoration-on-success is verified without touching a real clipboard."""
    import clipboard_capture as cc

    box = {"value": "PRIOR_CLIPBOARD"}

    def fake_get():
        return box["value"]

    def fake_set(v):
        box["value"] = v or ""
        return True

    monkeypatch.setattr(cc, "_clipboard_get_text", fake_get)
    monkeypatch.setattr(cc, "_clipboard_set_text", fake_set)
    monkeypatch.setattr(cc, "_capture_clipboard_snapshot_windows", lambda: None)
    monkeypatch.setattr(cc, "_restore_clipboard_snapshot_windows", lambda snap: False)
    monkeypatch.setattr(cc.time, "sleep", lambda *_a, **_k: None)

    def fake_press_and_release(_combo):
        # Simulate the OS having copied the selection over our sentinel probe.
        box["value"] = "SELECTED TEXT"

    monkeypatch.setattr(cc.keyboard, "press_and_release", fake_press_and_release)

    result = capture_selection(supported_fn=_supported_true)

    assert result.outcome == "selection"
    assert result.text == "SELECTED TEXT"
    assert box["value"] == "PRIOR_CLIPBOARD"  # restored after capture


def test_default_capture_fn_restores_clipboard_on_empty_capture(monkeypatch):
    import clipboard_capture as cc

    box = {"value": "PRIOR_CLIPBOARD"}

    monkeypatch.setattr(cc, "_clipboard_get_text", lambda: box["value"])
    monkeypatch.setattr(cc, "_clipboard_set_text", lambda v: (box.__setitem__("value", v or ""), True)[1])
    monkeypatch.setattr(cc, "_capture_clipboard_snapshot_windows", lambda: None)
    monkeypatch.setattr(cc, "_restore_clipboard_snapshot_windows", lambda snap: False)
    monkeypatch.setattr(cc.time, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(cc.keyboard, "press_and_release", lambda _combo: None)
    # No prior clipboard text and no fresh selection copied -> nothing readable.
    box["value"] = ""

    result = capture_selection(supported_fn=_supported_true)

    assert result.outcome == "empty"
    assert box["value"] == ""  # restored (to its original empty state)
