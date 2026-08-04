import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

import server


@pytest.fixture(autouse=True)
def clean_selection_state(monkeypatch):
    server.privacy_wipe_in_progress.clear()
    server.hotkey_manager = None
    server.is_processing_draft = False
    with server.draft_lock:
        server.draft_queue.clear()
        server.draft_recordings.clear()
        server.pending_manual_send_ids.clear()
        server.next_draft_id = 1
        server._draft_store.next_draft_id = 1
    monkeypatch.setattr(server, "save_draft_history", lambda **_kwargs: None)
    yield
    server.privacy_wipe_in_progress.clear()
    server.hotkey_manager = None
    server.is_processing_draft = False
    with server.draft_lock:
        server.draft_queue.clear()
        server.draft_recordings.clear()
        server.pending_manual_send_ids.clear()


def _profile(**overrides):
    result = {
        "current_preset": "Warm",
        "llm_chunk_size": 42,
        "max_completion_tokens": 321,
        "long_recording_stitch_pass_enabled": False,
        "use_persona_traits": True,
        "llm_model_id": "test-model",
    }
    result.update(overrides)
    return result


def _capture(text="selected source"):
    return {
        "ok": True,
        "text": text,
        "capture_status": "captured",
        "used_fallback": False,
    }


def test_success_uses_selected_persona_and_preserves_source_output(monkeypatch):
    engine = Mock()
    engine.process_fast_lane.return_value = "cleaned output"
    statuses = []
    monkeypatch.setattr(server, "load_profile", lambda _name: _profile())
    monkeypatch.setattr(server, "resolve_dictation_preset", lambda value: f"resolved:{value}")
    monkeypatch.setattr(server, "get_selected_llm_engine", lambda: engine)
    monkeypatch.setattr(server, "broadcast_status_threadsafe", lambda status, data=None: statuses.append((status, data or {})))
    monkeypatch.setattr(
        "clipboard_capture.capture_selection_text_with_restore",
        lambda **_kwargs: _capture("source text"),
    )

    result = server.handle_selection_rewrite_shortcut()

    assert result["ok"] is True
    draft = result["draft"]
    assert draft["raw_text"] == "source text"
    assert draft["final_text"] == "cleaned output"
    assert draft["preset"] == "resolved:Warm"
    assert draft["status"] == "pending"
    assert draft["metadata"] == {"source": "selection_rewrite"}
    engine.process_fast_lane.assert_called_once_with(
        "source text",
        "resolved:Warm",
        max_output_tokens=321,
        chunk_size=42,
        progress_callback=None,
        stitch_pass=False,
        delivery_summary=None,
        audience_summary=None,
        include_traits=True,
    )
    preview = next(data for status, data in statuses if status == "preview_ready")
    assert preview["source"] == "selection_rewrite"
    assert preview["preset"] == "resolved:Warm"
    assert preview["raw_text"] == "source text"
    assert preview["final_text"] == "cleaned output"
    assert [status for status, _data in statuses].index("rewriting") < [
        status for status, _data in statuses
    ].index("preview_ready")


@pytest.mark.parametrize(
    ("capture_result", "reason"),
    [
        (
            {
                "ok": False,
                "text": "",
                "capture_status": "unsupported",
                "missing_tool": "xclip or xsel",
                "message": "helper-specific xclip message",
            },
            "unsupported",
        ),
        (
            {"ok": False, "text": "", "capture_status": "empty"},
            "empty",
        ),
    ],
)
def test_empty_or_unsupported_capture_fails_without_model_or_draft(
    monkeypatch, capture_result, reason
):
    engine = Mock()
    broadcaster = Mock()
    monkeypatch.setattr(server, "get_selected_llm_engine", lambda: engine)
    monkeypatch.setattr(server, "broadcast_status_threadsafe", broadcaster)
    monkeypatch.setattr(
        "clipboard_capture.capture_selection_text_with_restore",
        lambda **_kwargs: capture_result,
    )

    result = server.handle_selection_rewrite_shortcut()

    assert result == {
        "ok": False,
        "reason": reason,
        "message": (
            "helper-specific xclip message"
            if reason == "unsupported"
            else "Can't read selected text — no selected text was captured. Select text and try again."
        ),
        "capture_status": reason,
    }
    engine.process_fast_lane.assert_not_called()
    assert server.draft_queue == []
    broadcaster.assert_called_once()
    status, payload = broadcaster.call_args.args
    assert status == "selection_capture_failed"
    assert payload["source"] == "selection_rewrite"
    assert payload["capture_status"] == capture_result["capture_status"]
    assert "text" not in payload


def test_existing_clipboard_fallback_is_never_rewritten_as_a_selection(monkeypatch):
    engine = Mock()
    statuses = []
    monkeypatch.setattr(server, "get_selected_llm_engine", lambda: engine)
    monkeypatch.setattr(
        server,
        "broadcast_status_threadsafe",
        lambda status, data=None: statuses.append((status, data or {})),
    )
    monkeypatch.setattr(
        "clipboard_capture.capture_selection_text_with_restore",
        lambda **_kwargs: {
            "ok": True,
            "text": "stale private clipboard text",
            "capture_status": "captured",
            "used_fallback": True,
        },
    )

    result = server.handle_selection_rewrite_shortcut()

    assert result == {
        "ok": False,
        "reason": "empty",
        "message": "Can't read selected text — no selected text was captured. Select text and try again.",
        "capture_status": "empty",
    }
    engine.process_fast_lane.assert_not_called()
    assert server.draft_queue == []
    assert statuses == [
        (
            "selection_capture_failed",
            {
                "reason": "empty",
                "message": "Can't read selected text — no selected text was captured. Select text and try again.",
                "source": "selection_rewrite",
                "capture_status": "empty",
            },
        )
    ]


def test_wayland_missing_wl_copy_preserves_actionable_install_message(monkeypatch):
    capture_result = {
        "ok": False,
        "text": "",
        "capture_status": "unsupported",
        "missing_tool": "wl-copy",
        "message": "helper-specific wl-copy message",
    }
    monkeypatch.setattr(
        "clipboard_capture.capture_selection_text_with_restore",
        lambda **_kwargs: capture_result,
    )
    monkeypatch.setattr(server, "broadcast_status_threadsafe", lambda *_args, **_kwargs: None)

    result = server.handle_selection_rewrite_shortcut()

    assert result["reason"] == "unsupported"
    assert result["message"] == "helper-specific wl-copy message"


def test_missing_display_preserves_capture_helper_message(monkeypatch):
    capture_result = {
        "ok": False,
        "text": "",
        "capture_status": "unsupported",
        "missing_tool": "DISPLAY",
        "message": "helper-specific missing-display message",
    }
    monkeypatch.setattr(
        "clipboard_capture.capture_selection_text_with_restore",
        lambda **_kwargs: capture_result,
    )
    monkeypatch.setattr(server, "broadcast_status_threadsafe", lambda *_args, **_kwargs: None)

    result = server.handle_selection_rewrite_shortcut()

    assert result["reason"] == "unsupported"
    assert result["message"] == "helper-specific missing-display message"


def test_unsupported_capture_constructs_message_when_helper_message_absent(monkeypatch):
    capture_result = {
        "ok": False,
        "text": "",
        "capture_status": "unsupported",
        "missing_tool": "wl-copy",
    }
    monkeypatch.setattr(
        "clipboard_capture.capture_selection_text_with_restore",
        lambda **_kwargs: capture_result,
    )
    monkeypatch.setattr(server, "broadcast_status_threadsafe", lambda *_args, **_kwargs: None)

    result = server.handle_selection_rewrite_shortcut()

    assert result["reason"] == "unsupported"
    assert result["message"] == (
        "Can't read selected text — wl-clipboard is not installed. "
        "Install wl-clipboard to enable this."
    )


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        ("recording", "recording"),
        ("processing", "processing"),
        ("wipe", "privacy_wipe"),
    ],
)
def test_busy_recording_processing_and_wipe_fail_closed(monkeypatch, setup, reason):
    capture = Mock(return_value=_capture())
    monkeypatch.setattr("clipboard_capture.capture_selection_text_with_restore", capture)
    monkeypatch.setattr(server, "broadcast_status_threadsafe", Mock())
    if setup == "recording":
        server.hotkey_manager = SimpleNamespace(is_recording=True)
    elif setup == "processing":
        server.is_processing_draft = True
    else:
        server.privacy_wipe_in_progress.set()

    result = server.handle_selection_rewrite_shortcut()

    assert result["ok"] is False
    assert result["reason"] == reason
    capture.assert_not_called()
    assert server.draft_queue == []


def test_model_exception_creates_no_draft_and_does_not_leak_source(monkeypatch):
    secret = "patient source should stay private"
    engine = Mock()
    engine.process_fast_lane.side_effect = RuntimeError(secret)
    statuses = []
    monkeypatch.setattr(server, "load_profile", lambda _name: _profile())
    monkeypatch.setattr(server, "resolve_dictation_preset", lambda value: value)
    monkeypatch.setattr(server, "get_selected_llm_engine", lambda: engine)
    monkeypatch.setattr(server, "broadcast_status_threadsafe", lambda status, data=None: statuses.append((status, data or {})))
    monkeypatch.setattr(
        "clipboard_capture.capture_selection_text_with_restore",
        lambda **_kwargs: _capture(secret),
    )

    result = server.handle_selection_rewrite_shortcut()

    assert result == {
        "ok": False,
        "reason": "model_error",
        "message": "Selected-text rewrite failed. Try again.",
    }
    assert server.draft_queue == []
    assert any(status == "draft_error" for status, _data in statuses)
    assert secret not in repr(result)
    assert secret not in repr(statuses)
    assert secret not in repr(server.get_runtime_error_history()[-1])


def test_recording_started_during_model_work_fails_closed_without_draft(monkeypatch):
    engine = Mock()
    engine.process_fast_lane.side_effect = lambda *_args, **_kwargs: (
        setattr(server.hotkey_manager, "is_recording", True) or "cleaned output"
    )
    manager = SimpleNamespace(is_recording=False)
    statuses = []
    monkeypatch.setattr(server, "hotkey_manager", manager)
    monkeypatch.setattr(server, "load_profile", lambda _name: _profile())
    monkeypatch.setattr(server, "get_selected_llm_engine", lambda: engine)
    monkeypatch.setattr(server, "broadcast_status_threadsafe", lambda status, data=None: statuses.append((status, data or {})))
    monkeypatch.setattr(
        "clipboard_capture.capture_selection_text_with_restore",
        lambda **_kwargs: _capture("source text"),
    )

    result = server.handle_selection_rewrite_shortcut()

    assert result == {
        "ok": False,
        "reason": "recording",
        "message": "Selected-text rewrite is unavailable while recording.",
    }
    assert server.draft_queue == []
    assert statuses[-1][0] == "draft_error"


def test_malformed_profile_chunk_size_is_normalized_before_model_call(monkeypatch):
    engine = Mock()
    engine.process_fast_lane.return_value = "cleaned output"
    monkeypatch.setattr(
        server,
        "get_active_recording_config",
        lambda: _profile(llm_chunk_size="42", max_completion_tokens="321"),
    )
    monkeypatch.setattr(server, "get_selected_llm_engine", lambda: engine)
    monkeypatch.setattr(
        "clipboard_capture.capture_selection_text_with_restore",
        lambda **_kwargs: _capture("source text"),
    )

    result = server.handle_selection_rewrite_shortcut()

    assert result["ok"] is True
    assert engine.process_fast_lane.call_args.kwargs["chunk_size"] == 42
    assert engine.process_fast_lane.call_args.kwargs["max_output_tokens"] == 321


def test_route_delegates_helper_to_threadpool():
    expected = {"ok": True, "draft": {"id": 7}}
    delegated = AsyncMock(return_value=expected)
    with patch.object(server, "run_in_threadpool", delegated):
        result = asyncio.run(server.runtime_rewrite_selection())

    assert result == expected
    delegated.assert_awaited_once_with(server.handle_selection_rewrite_shortcut)
