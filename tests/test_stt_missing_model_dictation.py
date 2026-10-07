"""Dictating with no usable speech model must say so, not blame the recording.

Local-only STT (BF-H2) means a fresh profile with no model returns an empty
transcript from a real, loud recording. The no-audio gate used to answer that
with "No usable audio was recorded.", sending the user to their microphone
instead of the Models page. Fakes only: no real model, no network.
"""
from unittest.mock import Mock, patch

import numpy as np
import pytest

import server
from backend.stt import transcriber as stt


class LoudRecording:
    sample_rate = 16000
    duration_seconds = 1.0
    frame_count = 16000
    sample_count = 16000
    max_amplitude = 0.4
    rms_amplitude = 0.1
    stop_reason = "manual"

    def __init__(self):
        self.audio_data = np.full(16000, 0.1, dtype=np.float32)


class _EmptyDecodeModel:
    def transcribe(self, *_args, **_kwargs):
        return iter(()), None


@pytest.fixture
def dictation(monkeypatch, tmp_path):
    """Run process_recording_result against a REAL Transcriber with a fake WhisperModel."""
    monkeypatch.setattr(stt, "HF_HUB_CACHE", str(tmp_path / "hub"))
    constructor = Mock(return_value=_EmptyDecodeModel())
    monkeypatch.setattr(stt, "WhisperModel", constructor)
    monkeypatch.setattr(stt, "ensure_cuda_libraries_on_path", lambda: [])
    monkeypatch.setattr(server, "load_draft_history", Mock())
    monkeypatch.setattr(server, "save_draft_history", Mock())
    monkeypatch.setattr(server, "transcriber", None)
    server.draft_queue.clear()
    server.draft_recordings.clear()
    statuses = []

    def run(*, cached, constructor_error=None):
        monkeypatch.setattr(stt.Transcriber, "_is_model_cached", lambda self, size: cached)
        if constructor_error is not None:
            constructor.side_effect = constructor_error
        with patch("backend.stt.transcriber.load_profile",
                   return_value={"model_size": "base.en", "use_gpu": False}), \
                patch.object(server, "broadcast_status_threadsafe",
                             side_effect=lambda status, data=None: statuses.append((status, data or {}))):
            draft = server.process_recording_result(LoudRecording())
        return draft, statuses, constructor

    yield run
    server.draft_queue.clear()
    server.draft_recordings.clear()


def _blocked_payload(statuses):
    return next(data for status, data in statuses if status == "draft_blocked")


def test_missing_model_blocked_draft_names_the_model_not_the_audio(dictation):
    draft, statuses, constructor = dictation(cached=False)
    assert draft["status"] == "blocked"
    assert "No usable audio" not in draft["error"]
    assert "speech model" in draft["error"].lower()
    assert "download" in draft["error"].lower()
    assert "model_missing" in draft["gate_reasons"]
    constructor.assert_not_called()
    # The renderer overlay and the draft pane both read the broadcast copy.
    payload = _blocked_payload(statuses)
    assert payload["error"] == draft["error"]
    assert "model_missing" in payload["gate_reasons"]


def test_unverifiable_model_blocked_draft_says_it_could_not_be_loaded(dictation):
    draft, statuses, _constructor = dictation(cached=True, constructor_error=RuntimeError("corrupt"))
    assert draft["status"] == "blocked"
    assert "No usable audio" not in draft["error"]
    assert "speech model" in draft["error"].lower()
    assert "verification_failed" in draft["gate_reasons"]
    assert "corrupt" not in draft["error"]
    assert _blocked_payload(statuses)["error"] == draft["error"]


def test_loaded_model_with_empty_transcript_keeps_the_audio_message(dictation):
    draft, _statuses, constructor = dictation(cached=True)
    assert draft["status"] == "blocked"
    assert draft["error"] == "No usable audio was recorded."
    assert draft["gate_reasons"] == ["empty_transcript"]
    constructor.assert_called_once()
