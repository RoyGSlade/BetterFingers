"""Exact displayed-draft F9 authorization; all delivery/clipboard IO is fake."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture
def state(monkeypatch):
    original = list(server.draft_queue)
    pending = list(server.pending_manual_send_ids)
    server.draft_queue.clear()
    server.pending_manual_send_ids.clear()
    monkeypatch.setattr(server, "hotkey_manager", None)
    monkeypatch.setattr(server, "is_processing_draft", False)
    monkeypatch.setattr(server, "_primary_action_selection_guard_until", 0.0)
    monkeypatch.setattr(server, "_primary_action_selection_guard_draft_id", None)
    monkeypatch.setattr(server, "save_draft_history", Mock())
    monkeypatch.setattr(server, "load_draft_history", Mock())
    monkeypatch.setattr(server, "broadcast_status_threadsafe", Mock())
    monkeypatch.setattr(server, "get_profile_output_settings", lambda: {"send_mode": "review_first"})
    capture = Mock(return_value={"ok": True, "text": "selected fixture"})
    monkeypatch.setattr("backend.output.clipboard_capture.capture_selection_text_with_restore", capture)
    monkeypatch.setattr(server, "speak_text_aloud", Mock())
    real_deliver = server.perform_output_action
    deliver = Mock(return_value={"ok": True, "action": "paste"})
    monkeypatch.setattr(server, "perform_output_action", deliver)
    yield SimpleNamespace(deliver=deliver, capture=capture, real_deliver=real_deliver)
    server.draft_queue[:] = original
    server.pending_manual_send_ids[:] = pending


def shown(draft):
    return {"displayed_draft_id": draft["id"], "displayed_final_text": draft["final_text"]}


def make_draft(raw, final):
    created = server.create_draft(raw, final)
    return server.get_draft_by_id(created["id"])


def test_route_accepts_and_places_exact_shown_draft_without_confidence_gate(state):
    draft = make_draft("fixture", "shown fixture")
    draft["auto_send_ok"] = False
    with TestClient(server.app) as client:
        result = client.post("/runtime/primary-action", json=shown(draft))
    assert result.status_code == 200
    assert result.json()["status"] == "sent"
    state.deliver.assert_called_once_with("shown fixture", "paste", open_chat=False)
    assert not server.pending_manual_send_ids
    state.capture.assert_not_called()


def test_newer_draft_does_not_replace_displayed_draft(state):
    draft = make_draft("fixture", "shown")
    newer = make_draft("fixture", "unseen newer")
    server.handle_primary_action(**shown(draft))
    state.deliver.assert_called_once_with("shown", "paste", open_chat=False)
    assert newer["status"] == "pending"


def test_double_press_does_not_place_twice(state):
    draft = make_draft("fixture", "shown")
    assert server.handle_primary_action(**shown(draft))["status"] == "sent"
    assert server.handle_primary_action(**shown(draft))["error"] == "already_sent"
    assert state.deliver.call_count == 1
    state.capture.assert_not_called()


def test_double_press_after_overlay_hides_does_not_read_aloud(state, monkeypatch):
    draft = make_draft("fixture", "shown")
    server.handle_primary_action(**shown(draft))
    assert server.handle_primary_action()["error"] == "primary_action_repeat"
    state.capture.assert_not_called()
    server.speak_text_aloud.assert_not_called()
    # A later deliberate action keeps the established selection-read path.
    monkeypatch.setattr(server, "_primary_action_selection_guard_until", 0.0)
    assert server.handle_primary_action()["ok"]
    server.speak_text_aloud.assert_called_once_with("selected fixture")


def test_visible_but_unacknowledged_overlay_never_guesses_or_captures_selection(state):
    server.create_draft("fixture", "pending")
    with TestClient(server.app) as client:
        result = client.post("/runtime/primary-action", json={"review_visible": True})
    assert result.json()["error"] == "displayed_draft_unknown"
    state.deliver.assert_not_called()
    state.capture.assert_not_called()


def test_hidden_overlay_with_ignored_pending_draft_keeps_read_aloud(state):
    # Escape hides the overlay without declining, so the draft stays pending.
    # One ignored draft must not disable F9 read-aloud, and nothing is placed.
    draft = server.create_draft("fixture", "ignored")
    with TestClient(server.app) as client:
        for payload in (None, {}):
            result = client.post("/runtime/primary-action", json=payload)
            assert result.json()["ok"]
    state.deliver.assert_not_called()
    assert server.speak_text_aloud.call_count == 2
    assert server.get_draft_by_id(draft["id"])["status"] == "pending"


def test_in_flight_send_blocks_selection_capture(state):
    draft = make_draft("fixture", "placing")
    draft["status"] = "sending"
    result = server.handle_primary_action()
    assert result["error"] == "send_in_progress"
    state.capture.assert_not_called()
    state.deliver.assert_not_called()


def test_backend_edit_after_display_is_rejected_without_accepting_new_content(state):
    draft = make_draft("fixture", "shown")
    evidence = shown(draft)
    with TestClient(server.app) as client:
        client.post(f"/drafts/{draft['id']}/edit", json={"final_text": "changed"})
        response = client.post("/runtime/primary-action", json=evidence)
    assert response.json()["error"] == "displayed_draft_changed"
    assert draft["status"] == "pending"
    assert draft["final_text"] == "changed"
    state.deliver.assert_not_called()


def test_unsaved_renderer_edit_is_evidence_not_replacement_text(state):
    draft = make_draft("fixture", "backend text")
    result = server.handle_primary_action(draft["id"], "unsaved displayed edit")
    assert result["error"] == "displayed_draft_changed"
    assert draft["final_text"] == "backend text"
    state.deliver.assert_not_called()


def test_accepted_queue_and_empty_selection_paths_are_preserved(state, monkeypatch):
    draft = make_draft("fixture", "accepted")
    with TestClient(server.app) as client:
        client.post(f"/drafts/{draft['id']}/accept")
    assert server.handle_primary_action()["status"] == "sent"
    monkeypatch.setattr(server, "_primary_action_selection_guard_until", 0.0)
    assert server.handle_primary_action()["ok"]
    server.speak_text_aloud.assert_called_once_with("selected fixture")


@pytest.mark.parametrize("recording,processing", [(True, False), (False, True)])
def test_recording_or_processing_ignores_shown_draft(state, monkeypatch, recording, processing):
    draft = make_draft("fixture", "shown")
    monkeypatch.setattr(server, "hotkey_manager", SimpleNamespace(is_recording=recording))
    monkeypatch.setattr(server, "is_processing_draft", processing)
    assert not server.handle_primary_action(**shown(draft))["ok"]
    assert draft["status"] == "pending"
    state.deliver.assert_not_called()


def test_concurrent_press_and_accept_do_not_reopen_inflight_send(state):
    entered, release = Event(), Event()
    draft = make_draft("fixture", "shown")

    def deliver(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return {"ok": True, "action": "paste"}

    state.deliver.side_effect = deliver
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(server.handle_primary_action, **shown(draft))
        assert entered.wait(5)
        try:
            assert server.handle_primary_action(**shown(draft))["error"] == "primary_action_in_progress"
            with TestClient(server.app) as client:
                assert client.post(f"/drafts/{draft['id']}/accept").json()["status"] == "sending"
        finally:
            release.set()
        assert first.result()["status"] == "sent"
    assert state.deliver.call_count == 1
    state.capture.assert_not_called()


@pytest.mark.parametrize("context_fails", [False, True, "missing_policy"])
def test_gamer_or_unknown_foreground_policy_copies_without_injection(state, monkeypatch, context_fails):
    # Restore the actual delivery policy while faking every OS side effect.
    monkeypatch.setattr(server, "perform_output_action", state.real_deliver)
    with patch.object(server, "save_draft_history"), patch.object(server, "broadcast_status_threadsafe"), \
         patch.object(server, "get_profile_output_settings", return_value={"send_mode": "review_first"}), \
         patch.object(server, "get_capabilities", return_value={"supports_input_injection": True}), \
         patch.object(server, "copy_text_to_clipboard", return_value={"ok": True}) as copy, \
         patch("backend.output.injector.InputInjector") as injector, \
         patch("backend.services.app_context.get_service") as context:
        if context_fails is True:
            context.side_effect = RuntimeError("fake foreground observation unavailable")
        elif context_fails == "missing_policy":
            context.return_value.poll.return_value = {}
        else:
            context.return_value.poll.return_value = {"gaming_policy": {"active": True}}
        draft = make_draft("fixture", "shown")
        result = server.handle_primary_action(**shown(draft))
        assert result["send_result"]["actual_action"] == "copy_only"
        copy.assert_called_once_with("shown")
        injector.assert_not_called()


@pytest.mark.parametrize("payload", [{"displayed_draft_id": True}, {"displayed_draft_id": -1},
                                     {"displayed_draft_id": "1"}, {"displayed_final_text": 12}])
def test_route_rejects_malformed_display_evidence(state, payload):
    with TestClient(server.app) as client:
        assert client.post("/runtime/primary-action", json=payload).status_code == 422
    state.deliver.assert_not_called()
