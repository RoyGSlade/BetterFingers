"""Pipeline-level proof that a negated editing command is DICTATED, not executed.

``server.process_recording_result`` runs the real post-process stage: the
"scratch that" check (``parse_edit_command``) and then the in-utterance edits
(``apply_inline_edits``). Both must treat a vetoed command as ordinary words:
the draft carries the spoken text, nothing is scratched, no history is popped.

The positive controls ("scratch that" really scratches) sit beside the negative
cases on purpose -- a harness that cannot observe a scratch would pass the
negative tests vacuously.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import server
from backend.config import utils
from backend.runtime.utterance_history import Utterance, utterance_history


def _transcriber_saying(text):
    class SayingTranscriber:
        def __init__(self, preload=False, profile_name=None, *args, **kwargs):
            self.preload = preload

        def transcribe(self, audio_data):
            return text

    return SayingTranscriber


class _Recording:
    audio_data = [0.1, 0.2, 0.3]
    sample_rate = 16000
    duration_seconds = 1.0
    frame_count = 3
    sample_count = 3
    max_amplitude = 0.2
    rms_amplitude = 0.05
    stop_reason = "manual"


def _reset(monkeypatch):
    for name in ("load_draft_history", "save_draft_history"):
        monkeypatch.setattr(server, name, lambda *a, **k: None)
    for name in ("transcriber", "output_injector", "hotkey_manager", "tts_engine"):
        monkeypatch.setattr(server, name, None)
    server.draft_queue.clear()
    server.draft_recordings.clear()
    server.pending_manual_send_ids.clear()
    monkeypatch.setattr(server, "next_draft_id", 1)
    utterance_history.clear()


@pytest.fixture
def dictation(monkeypatch):
    """dictate(spoken) -> SimpleNamespace(draft, statuses): one real pipeline run."""
    _reset(monkeypatch)

    def dictate(spoken, *, editing_commands=True, previous=None):
        utterance_history.clear()
        if previous:
            utterance_history.record(
                Utterance(raw_transcript=previous, final_text=previous, emitted_length=len(previous),
                          target_draft_id=99, timestamp=1.0)
            )
        statuses = []
        profile = utils._profile_defaults()
        assert not profile["llm_enabled"], "cleanup is opt-in; the test must not need an LLM"
        profile["editing_commands_enabled"] = editing_commands
        # The pipeline caches its transcriber after first use; drop it so every
        # dictation hears ITS phrase.
        server.transcriber = None
        with patch.object(server, "Transcriber", _transcriber_saying(spoken)), patch.object(
            server, "get_active_recording_config", return_value=profile
        ), patch.object(
            server, "get_selected_llm_engine", side_effect=AssertionError("cleanup is disabled")
        ), patch.object(
            server,
            "broadcast_status_threadsafe",
            side_effect=lambda status, data=None: statuses.append((status, data or {})),
        ):
            draft = server.process_recording_result(_Recording())
        return SimpleNamespace(draft=draft, statuses=[s for s, _ in statuses])

    yield dictate
    utterance_history.clear()
    server.draft_queue.clear()
    server.draft_recordings.clear()
    server.pending_manual_send_ids.clear()


# --- positive controls: the harness can see a real scratch ---------------------------------

def test_scratch_that_really_scratches(dictation):
    run = dictation("scratch that", previous="earlier words")
    assert run.draft["status"] == "scratch"
    assert run.draft["final_text"] == ""
    assert "scratch_last" in run.statuses
    assert len(utterance_history) == 0, "the previous utterance must have been popped"


@pytest.mark.parametrize("spoken", ["no, scratch that", "never mind, scratch that", "scratch that, no problem"])
def test_benign_phrasing_still_scratches(dictation, spoken):
    run = dictation(spoken, previous="earlier words")
    assert run.draft["status"] == "scratch"
    assert "scratch_last" in run.statuses


def test_inline_edit_still_applies(dictation):
    run = dictation("the quick brown fox delete last word")
    assert run.draft["raw_text"] == "the quick brown"
    assert run.draft["final_text"] == "the quick brown"


# --- the bug: a negated command must come out as text ----------------------------------------

@pytest.mark.parametrize("spoken", [
    "don't scratch that",
    "don’t scratch that",
    "do not scratch that",
    "no don't scratch that",
    "never mind don't scratch that",
    "don't undo that",
    "scratch that? No, don't.",
])
def test_negated_scratch_that_is_dictated_not_executed(dictation, spoken):
    run = dictation(spoken, previous="earlier words")

    assert run.draft["status"] == "pending"
    assert run.draft["raw_text"] == spoken
    assert run.draft["final_text"] == spoken
    assert "scratch_last" not in run.statuses
    assert "preview_ready" in run.statuses
    # The earlier utterance survives; this dictation is recorded after it.
    assert [u.raw_transcript for u in utterance_history.all()] == ["earlier words", spoken]


@pytest.mark.parametrize("spoken", [
    "do not delete last word",
    "don't delete last word",
    "never undo last sentence",
    "don't quote that",
    "please don't replace foo with bar",
    "I would not capitalize london here",
    "don't start a new heading",
])
def test_negated_inline_edit_is_dictated_not_executed(dictation, spoken):
    run = dictation(spoken)
    assert run.draft["status"] == "pending"
    assert run.draft["raw_text"] == spoken
    assert run.draft["final_text"] == spoken


def test_editing_commands_off_still_dictates_everything(dictation):
    """Gating is unchanged: with the toggle off nothing is parsed at all."""
    run = dictation("scratch that", editing_commands=False)
    assert run.draft["status"] == "pending"
    assert run.draft["final_text"] == "scratch that"
    assert "scratch_last" not in run.statuses
