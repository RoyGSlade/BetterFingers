"""Doctor/diagnostics must tell the truth about the speech model (QA D6-D7).

No real model is ever loaded: the transcriber is either a status stub or a real
``Transcriber`` whose ``WhisperModel`` is a recording fake.
"""
import threading
import time
import types
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

import server
from backend.stt import transcriber as stt
from backend.stt.transcriber import Transcriber

CUBLAS_MSG = "Library cublas64_12.dll is not found or cannot be loaded"


def _status_stub(**fields):
    """A transcriber double that only publishes a status dict (the G3 snapshot)."""
    base = {
        "constructed": True, "probe_passed": False, "inference_ready": False,
        "error_code": None, "error_state": None,
        "active_device": "cpu", "active_compute_type": "int8",
        "device_fallback_reason": None, "device_fallback_code": None,
        "state": "ready", "model_size": "base.en", "loading": False,
        "downloading": False, "progress": None, "generation": 1,
    }
    base.update(fields)
    return Mock(get_runtime_status=Mock(return_value=base), model=object())


# ---------------------------------------------------------------------------
# D6: using_cpu_fallback derives from the published status snapshot
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fields,expected_reason", [
    # What the loader publishes after a CUDA inference probe fails (transcriber.py:812).
    (dict(device_fallback_reason="CUDA inference probe failed",
          device_fallback_code="cuda_runtime_missing",
          error_code="cuda_runtime_missing", error_state="fallback_active"),
     "CUDA inference probe failed"),
    # An unclassified probe failure: no code, exception class appended. The class
    # name is dropped at the privacy boundary; the fallback itself is still real.
    (dict(device_fallback_reason="CUDA inference probe failed (ValueError)"),
     "CUDA inference probe failed"),
    # CUDA constructor failure.
    (dict(device_fallback_reason="CUDA initialization failed",
          device_fallback_code="cuda_init_failed"),
     "CUDA initialization failed"),
    # Lazy decode-time recovery (transcriber._load_cpu_fallback_model).
    (dict(device_fallback_reason="CUDA inference initialization failed",
          device_fallback_code="cuda_runtime_missing", error_state="fallback_active"),
     "CUDA inference initialization failed"),
    # Code alone is enough: the status row says fallback_active even if the reason
    # text was not publishable.
    (dict(device_fallback_code="cuda_runtime_missing", error_state="fallback_active"),
     None),
])
def test_snapshot_reports_cpu_fallback_when_cuda_fell_back(fields, expected_reason):
    snap = server._transcriber_status_snapshot(_status_stub(**fields))
    assert snap["using_cpu_fallback"] is True
    assert snap["device_fallback_reason"] == expected_reason
    assert snap["active_device"] == "cpu"


@pytest.mark.parametrize("fields", [
    {},                                                    # CPU by choice (prefer_gpu off): not a fallback
    dict(active_device="cuda", active_compute_type="float16"),   # CUDA healthy
    dict(active_device=None, active_compute_type=None, constructed=False,
         device_fallback_code="cuda_runtime_missing",
         error_code="cuda_runtime_missing", error_state="fallback_load_failed"),  # fallback attempted, nothing running
    dict(device_fallback_reason="private payload", device_fallback_code="private payload"),
])
def test_snapshot_does_not_invent_a_cpu_fallback(fields):
    snap = server._transcriber_status_snapshot(_status_stub(**fields))
    assert snap["using_cpu_fallback"] is False
    assert snap["device_fallback_reason"] is None


def test_snapshot_without_a_transcriber_is_not_a_fallback():
    assert server._transcriber_status_snapshot(None)["using_cpu_fallback"] is False


def test_privacy_boundary_still_drops_unknown_reason_text():
    snap = server._transcriber_status_snapshot(_status_stub(
        device_fallback_reason="CUDA inference probe failed (C:\\Users\\someone\\secret.wav)"))
    # Only the fixed vocabulary survives; the parenthetical never does.
    assert snap["device_fallback_reason"] == "CUDA inference probe failed"
    assert "secret" not in str(snap)


def _fake_whisper_cuda_probe_fails():
    class FakeWhisperModel:
        attempts = []

        def __init__(self, model, **kwargs):
            type(self).attempts.append(kwargs.get("device"))
            self.device = kwargs.get("device")

        def transcribe(self, audio, **kwargs):
            device = self.device

            def segments():
                if device == "cuda":
                    raise RuntimeError(CUBLAS_MSG)
                return
                yield  # pragma: no cover - generator marker

            return segments(), None

    return FakeWhisperModel


@pytest.fixture
def cuda_fallback_transcriber():
    """A real Transcriber that loaded, hit a failing CUDA probe and fell back to CPU."""
    fake = _fake_whisper_cuda_probe_fails()
    with patch("backend.stt.transcriber.load_profile",
               return_value={"model_size": "base.en", "use_gpu": True}), \
            patch.object(Transcriber, "_is_model_cached", return_value=True), \
            patch("backend.stt.transcriber.WhisperModel", new=fake):
        t = Transcriber(profile_name="Default", preload=False)
        assert t.ensure_loaded()
        assert fake.attempts == ["cuda", "cpu"]
        yield t


def _get_doctor(transcriber):
    # No `with`: skip the lifespan so startup never touches the transcriber under test.
    with patch.object(server, "transcriber", transcriber):
        response = TestClient(server.app).get("/doctor")
    assert response.status_code == 200
    return response.json()


def test_doctor_reports_cpu_fallback_after_cuda_probe_failure(cuda_fallback_transcriber):
    """The QA D6 scenario end to end: status says fallback_active, doctor must agree."""
    status = cuda_fallback_transcriber.get_runtime_status()
    assert status["device_fallback_code"] == "cuda_runtime_missing"
    assert status["error_state"] == "fallback_active"

    body = _get_doctor(cuda_fallback_transcriber)["stt"]
    assert body["device"] == "cpu"
    assert body["error_state"] == "fallback_active"
    assert body["device_fallback_code"] == "cuda_runtime_missing"
    assert body["using_cpu_fallback"] is True
    assert body["device_fallback_reason"] == "CUDA inference probe failed"


def test_doctor_fallback_flag_never_takes_the_model_lock(cuda_fallback_transcriber):
    """Status reads stay lock-free: hold the model lock and /doctor must still answer."""
    t = cuda_fallback_transcriber
    held, release = threading.Event(), threading.Event()

    def hold():
        with t._model_lock:
            held.set()
            assert release.wait(10)

    holder = threading.Thread(target=hold)
    holder.start()
    assert held.wait(5)
    result = {}

    def call():
        result["body"] = _get_doctor(t)

    caller = threading.Thread(target=call)
    started = time.monotonic()
    caller.start()
    try:
        caller.join(8)
        assert not caller.is_alive(), "/doctor blocked on the model lock"
    finally:
        release.set()
        holder.join(5)
        caller.join(5)
    assert time.monotonic() - started < 8
    assert result["body"]["stt"]["using_cpu_fallback"] is True


def test_doctor_does_not_claim_fallback_for_cpu_by_choice():
    fake = _fake_whisper_cuda_probe_fails()
    with patch("backend.stt.transcriber.load_profile",
               return_value={"model_size": "base.en", "use_gpu": False}), \
            patch.object(Transcriber, "_is_model_cached", return_value=True), \
            patch("backend.stt.transcriber.WhisperModel", new=fake):
        t = Transcriber(profile_name="Default", preload=False)
        assert t.ensure_loaded()
        assert fake.attempts == ["cpu"]
        body = _get_doctor(t)["stt"]
    assert body["device"] == "cpu"
    assert body["using_cpu_fallback"] is False
    assert body["device_fallback_reason"] is None


# ---------------------------------------------------------------------------
# D7: POST /transcribe must not answer 200 with empty text when the speech
# model is missing or failed verification
# ---------------------------------------------------------------------------

def _wav_upload(seconds=0.1, rate=16000):
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return {"file": ("clip.wav", buf.getvalue(), "audio/wav")}


def _post_transcribe(transcriber):
    with patch.object(server, "transcriber", transcriber):
        return TestClient(server.app).post("/transcribe", files=_wav_upload())


def _empty_transcriber(**status_fields):
    """transcribe() returns "" (what the real Transcriber does on any failure)."""
    t = _status_stub(**status_fields)
    t.transcribe = Mock(return_value="")
    return t


@pytest.mark.parametrize("code", ["model_missing", "verification_failed"])
def test_transcribe_reports_an_unavailable_model_instead_of_empty_200(code):
    t = _empty_transcriber(constructed=False, active_device=None, active_compute_type=None,
                           error_code=code, error_state=code, state="failed")
    response = _post_transcribe(t)
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == code
    assert detail["ok"] is False
    assert detail["message"] == server._STT_UNAVAILABLE_MESSAGES[code]
    assert "text" not in response.json()


def test_transcribe_loaded_model_with_empty_speech_is_still_200_empty():
    t = _empty_transcriber(constructed=True)  # no error_code: genuinely nothing said
    response = _post_transcribe(t)
    assert response.status_code == 200
    assert response.json() == {"text": ""}


def test_transcribe_loaded_model_ignores_a_stale_unavailable_code():
    t = _empty_transcriber(constructed=True, error_code="model_missing", error_state="model_missing")
    response = _post_transcribe(t)
    assert response.status_code == 200
    assert response.json() == {"text": ""}


def test_transcribe_nonempty_text_never_consults_the_error_code():
    t = _status_stub(constructed=True, error_code="model_missing")
    t.transcribe = Mock(return_value="hello there")
    response = _post_transcribe(t)
    assert response.status_code == 200
    assert response.json() == {"text": "hello there"}


@pytest.fixture
def real_transcriber(monkeypatch):
    monkeypatch.delenv("BETTERFINGERS_BUNDLED_MODELS_DIR", raising=False)
    with patch("backend.stt.transcriber.load_profile",
               return_value={"model_size": "base.en", "use_gpu": False}), \
            patch("backend.stt.transcriber.WhisperModel",
                  side_effect=AssertionError("a real model must never be constructed")):
        yield Transcriber(profile_name="Default", preload=False)


def test_transcribe_end_to_end_model_not_installed(real_transcriber):
    with patch.object(Transcriber, "_is_model_cached", return_value=False):
        response = _post_transcribe(real_transcriber)
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "model_missing"


def test_transcribe_end_to_end_bundled_model_fails_verification(real_transcriber, tmp_path, monkeypatch):
    bundle = tmp_path / "base.en"
    bundle.mkdir()
    for name in ("model.bin", "tokenizer.json", "config.json", "vocabulary.txt"):
        (bundle / name).write_bytes(b"not the pinned bytes")
    monkeypatch.setenv("BETTERFINGERS_BUNDLED_MODELS_DIR", str(tmp_path))
    response = _post_transcribe(real_transcriber)
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "verification_failed"


# Drift guard: every way the real loader can end up on CPU after preferring CUDA
# must be recognised by the status snapshot, whatever reason text it publishes.

def _scripted_whisper(*, construct_error=None, probe_error=None, decode_error=None):
    class Scripted:
        cuda_calls = 0

        def __init__(self, model, **kwargs):
            self.device = kwargs.get("device")
            if self.device == "cuda" and construct_error is not None:
                raise construct_error

        def transcribe(self, audio, **kwargs):
            device = self.device
            if device == "cuda":
                type(self).cuda_calls += 1
                error = probe_error if type(self).cuda_calls == 1 else decode_error
            else:
                error = None

            def segments():
                if error is not None:
                    raise error
                return
                yield  # pragma: no cover - generator marker

            return segments(), None

    return Scripted


@pytest.mark.parametrize("scripted,decode_first", [
    # CUDA constructor fails ("CUDA initialization failed")
    (dict(construct_error=RuntimeError(CUBLAS_MSG)), False),
    # load-time probe fails with a recognised cuBLAS error
    (dict(probe_error=RuntimeError(CUBLAS_MSG)), False),
    # load-time probe fails with an unclassified error (exception class in the reason)
    (dict(probe_error=ValueError("private words")), False),
    # CUDA probe passes, the first real decode fails and recovers lazily on CPU
    (dict(decode_error=RuntimeError(CUBLAS_MSG)), True),
])
def test_doctor_reports_every_real_cpu_fallback_path(scripted, decode_first):
    import numpy as np

    fake = _scripted_whisper(**scripted)
    with patch("backend.stt.transcriber.load_profile",
               return_value={"model_size": "base.en", "use_gpu": True}), \
            patch.object(Transcriber, "_is_model_cached", return_value=True), \
            patch("backend.stt.transcriber.WhisperModel", new=fake):
        t = Transcriber(profile_name="Default", preload=False)
        assert t.ensure_loaded()
        if decode_first:
            t.transcribe(np.zeros(16000, dtype=np.float32))
        assert t.active_device == "cpu"
        body = _get_doctor(t)["stt"]
    assert body["device"] == "cpu"
    assert body["using_cpu_fallback"] is True
    assert "private" not in str(body)
