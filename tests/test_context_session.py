"""In-memory ContextSession tests (F2.5).

No FastAPI, Electron, or real clipboard involved: capture is driven through
injected capture_fn/supported_fn stand-ins and an injected clock, matching the
selection-adapter tests.
"""

import json
import threading

import pytest

from backend.domain.contracts import to_dict
from backend.services.context_session import (
    ContextCaptureError,
    ContextExhaustedError,
    ContextSession,
)


def _clock(times):
    it = iter(times)
    return lambda: next(it)


def _ids(values):
    it = iter(values)
    return lambda: next(it)


def _selection_ok(text="Meet at noon tomorrow", used_fallback=False):
    return lambda: {"ok": True, "text": text, "used_fallback": used_fallback}


def _selection_empty():
    return lambda: {"ok": False, "text": "", "used_fallback": False}


def test_capture_from_selection_success_stores_and_previews():
    session = ContextSession(clock=_clock([100.0, 100.0]), id_factory=_ids(["ctx-1"]))

    envelope = session.capture_from_selection(
        capture_fn=_selection_ok("Please send the file by 5pm"),
        supported_fn=lambda: True,
    )

    assert envelope.id == "ctx-1"
    assert envelope.source == "selection"
    assert envelope.text == "Please send the file by 5pm"
    assert envelope.visible_preview == "Please send the file by 5pm"
    assert envelope.use_count == 0
    assert envelope.max_uses == 1


def test_capture_from_selection_uses_clipboard_fallback_source():
    session = ContextSession(clock=_clock([100.0]), id_factory=_ids(["ctx-1"]))
    envelope = session.capture_from_selection(
        capture_fn=_selection_ok("Old clipboard text", used_fallback=True),
        supported_fn=lambda: True,
    )
    assert envelope.source == "clipboard_fallback"


def test_capture_from_selection_empty_raises_and_stores_nothing():
    session = ContextSession(clock=_clock([100.0]), id_factory=_ids(["ctx-1"]))

    with pytest.raises(ContextCaptureError) as excinfo:
        session.capture_from_selection(capture_fn=_selection_empty(), supported_fn=lambda: True)

    assert excinfo.value.reason == "empty"
    assert session.status() is None


def test_capture_from_selection_unsupported_wayland_raises_and_stores_nothing():
    session = ContextSession(clock=_clock([100.0]), id_factory=_ids(["ctx-1"]))

    with pytest.raises(ContextCaptureError) as excinfo:
        session.capture_from_selection(capture_fn=_selection_ok("x"), supported_fn=lambda: False)

    assert excinfo.value.reason == "unsupported"
    assert session.status() is None


def test_capture_manual_stores_explicit_text():
    session = ContextSession(clock=_clock([100.0]), id_factory=_ids(["ctx-1"]))
    envelope = session.capture_manual("Typed in by hand")
    assert envelope.source == "manual"
    assert envelope.text == "Typed in by hand"


def test_capture_manual_blank_raises():
    session = ContextSession(clock=_clock([100.0]), id_factory=_ids(["ctx-1"]))
    with pytest.raises(ContextCaptureError) as excinfo:
        session.capture_manual("   ")
    assert excinfo.value.reason == "empty"


def test_visible_preview_is_truncated_for_long_text():
    long_text = "word " * 100
    session = ContextSession(clock=_clock([100.0]), id_factory=_ids(["ctx-1"]))
    envelope = session.capture_manual(long_text)
    assert len(envelope.visible_preview) <= 80
    assert envelope.visible_preview.endswith("…")


def test_status_never_exposes_raw_text():
    session = ContextSession(clock=_clock([100.0, 100.0]), id_factory=_ids(["ctx-1"]))
    session.capture_manual("Secret message contents")
    status = session.status()
    assert "text" not in status
    assert status["visible_preview"] == "Secret message contents"
    assert status["active"] is True


def test_status_reports_none_when_empty():
    session = ContextSession()
    assert session.status() is None


def test_consume_returns_text_once_then_exhausts_by_default():
    session = ContextSession(clock=_clock([100.0, 100.0, 100.0]), id_factory=_ids(["ctx-1"]))
    session.capture_manual("One-time context")

    text = session.consume()
    assert text == "One-time context"
    assert session.status() is None  # single-use envelope cleared itself

    with pytest.raises(ContextExhaustedError) as excinfo:
        session.consume()
    assert excinfo.value.reason == "missing"


def test_consume_respects_custom_max_uses():
    session = ContextSession(clock=_clock([100.0] * 6), id_factory=_ids(["ctx-1"]))
    session.capture_manual("Reusable context", max_uses=2)

    assert session.consume() == "Reusable context"
    status_after_one = session.status()
    assert status_after_one["use_count"] == 1
    assert status_after_one["active"] is True

    assert session.consume() == "Reusable context"
    assert session.status() is None  # cleared after the second (final) use

    with pytest.raises(ContextExhaustedError) as excinfo:
        session.consume()
    assert excinfo.value.reason == "missing"


def test_consume_raises_missing_when_nothing_captured():
    session = ContextSession()
    with pytest.raises(ContextExhaustedError) as excinfo:
        session.consume()
    assert excinfo.value.reason == "missing"


def test_consume_raises_expired_and_clears_state():
    # captured_at=100, ttl default 120 -> expires_at=220; consume called at t=300.
    session = ContextSession(clock=_clock([100.0, 300.0]), id_factory=_ids(["ctx-1"]))
    session.capture_manual("Will go stale")

    with pytest.raises(ContextExhaustedError) as excinfo:
        session.consume()
    assert excinfo.value.reason == "expired"
    assert session.status() is None


def test_expiry_ttl_is_configurable():
    session = ContextSession(clock=_clock([100.0, 100.5]), id_factory=_ids(["ctx-1"]))
    session.capture_manual("Short lived", ttl_s=0.2)

    with pytest.raises(ContextExhaustedError) as excinfo:
        session.consume()
    assert excinfo.value.reason == "expired"


def test_clear_drops_context_and_is_privacy_wipe_compatible():
    session = ContextSession(clock=_clock([100.0, 100.0]), id_factory=_ids(["ctx-1"]))
    session.capture_manual("Sensitive text")
    assert session.status() is not None

    session.clear()

    assert session.status() is None
    with pytest.raises(ContextExhaustedError) as excinfo:
        session.consume()
    assert excinfo.value.reason == "missing"


def test_new_capture_replaces_any_prior_uncomsumed_context():
    session = ContextSession(clock=_clock([100.0, 100.0, 100.0, 100.0]), id_factory=_ids(["ctx-1", "ctx-2"]))
    session.capture_manual("First")
    session.capture_manual("Second")

    assert session.status()["id"] == "ctx-2"
    assert session.consume() == "Second"


def test_double_consume_race_only_one_winner():
    session = ContextSession(clock=lambda: 100.0, id_factory=lambda: "ctx-1")
    session.capture_manual("Race me")

    results = []
    errors = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        try:
            results.append(session.consume())
        except ContextExhaustedError as exc:
            errors.append(exc.reason)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results == ["Race me"]
    assert errors == ["missing"]


def test_envelope_is_json_round_trip_safe():
    session = ContextSession(clock=_clock([100.0]), id_factory=_ids(["ctx-1"]))
    envelope = session.capture_manual("Round trip me")
    payload = to_dict(envelope)
    assert json.loads(json.dumps(payload)) == payload


def test_status_payload_is_json_round_trip_safe():
    session = ContextSession(clock=_clock([100.0, 100.0]), id_factory=_ids(["ctx-1"]))
    session.capture_manual("Round trip status")
    status = session.status()
    assert json.loads(json.dumps(status)) == status


def test_no_content_bearing_diagnostics_in_module_source():
    """Guard against a future edit accidentally logging captured text: the
    service module must never import logging, since it has no legitimate
    reason to emit anything that could carry context text into log output."""
    import backend.services.context_session as module

    assert not hasattr(module, "logging")
