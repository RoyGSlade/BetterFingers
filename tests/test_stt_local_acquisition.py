"""Acquisition permission tests: all artifacts and constructors are fakes."""
from unittest.mock import Mock

import huggingface_hub
import pytest
import requests

from backend.stt import transcriber as stt
from backend.models import model_manager as mm


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    denied = Mock(side_effect=AssertionError("Network is forbidden in acquisition tests"))
    monkeypatch.setattr(huggingface_hub, "snapshot_download", denied)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", denied)
    monkeypatch.setattr(requests.sessions.Session, "request", denied)
    yield denied
    denied.assert_not_called()


@pytest.fixture
def fake_stt(monkeypatch, tmp_path):
    monkeypatch.setattr(stt, "HF_HUB_CACHE", str(tmp_path / "hub"))
    monkeypatch.setattr(stt, "load_profile", lambda name: {"model_size": "base.en", "use_gpu": False})
    constructor = Mock(return_value=object())
    monkeypatch.setattr(stt, "WhisperModel", constructor)
    return constructor


def test_missing_implicit_load_never_constructs_or_claims_download(monkeypatch, fake_stt):
    monkeypatch.setattr(stt.Transcriber, "_is_model_cached", lambda self, size: False)
    progress = Mock()
    monkeypatch.setattr(stt, "_set_whisper_download_state", progress)
    trans = stt.Transcriber(preload=False)
    assert trans.ensure_loaded() is False
    assert trans.get_runtime_status()["error_state"] == "model_missing"
    assert trans.get_runtime_status()["error_code"] == "model_missing"
    fake_stt.assert_not_called()
    progress.assert_not_called()


def test_corrupt_cache_local_failure_has_no_retry(monkeypatch, fake_stt):
    monkeypatch.setattr(stt.Transcriber, "_is_model_cached", lambda self, size: True)
    fake_stt.side_effect = RuntimeError("corrupt cached files")
    trans = stt.Transcriber(preload=False)
    assert trans.ensure_loaded() is False
    assert trans.get_runtime_status()["error_code"] == "verification_failed"
    fake_stt.assert_called_once()
    assert fake_stt.call_args.kwargs["local_files_only"] is True
    assert trans.model is None
    assert trans.active_device is None


def test_direct_local_load_does_not_swallow_cpu_failure(monkeypatch, fake_stt):
    monkeypatch.setattr(stt.Transcriber, "_is_model_cached", lambda self, size: True)
    fake_stt.side_effect = RuntimeError("CPU construction failed")
    trans = stt.Transcriber(preload=False)
    with pytest.raises(RuntimeError, match="CPU construction failed"):
        trans._load_model()
    fake_stt.assert_called_once()


def test_cuda_and_cpu_constructor_failures_surface_once(monkeypatch, fake_stt):
    monkeypatch.setattr(stt.Transcriber, "_is_model_cached", lambda self, size: True)
    monkeypatch.setattr(stt, "ensure_cuda_libraries_on_path", lambda: [])
    def fail(model_size, **kwargs):
        raise RuntimeError("weird" if kwargs["device"] == "cuda" else "CPU construction failed")
    fake_stt.side_effect = fail
    trans = stt.Transcriber(preload=False)
    trans.prefer_gpu = True
    with pytest.raises(RuntimeError, match="CPU construction failed"):
        trans._load_model()
    assert [call.kwargs["device"] for call in fake_stt.call_args_list] == ["cuda", "cpu"]
    assert all(call.kwargs["local_files_only"] is True for call in fake_stt.call_args_list)


class _SilentModel:
    """Constructed fake that survives the load-time CUDA inference probe."""

    def transcribe(self, *_args, **_kwargs):
        return iter(()), None


def test_cuda_not_memoized_unavailable_when_cpu_construction_also_fails(monkeypatch, fake_stt):
    """A cache/network-style failure fails CUDA and CPU alike; it says nothing about CUDA."""
    monkeypatch.setattr(stt.Transcriber, "_is_model_cached", lambda self, size: True)
    monkeypatch.setattr(stt, "ensure_cuda_libraries_on_path", lambda: [])
    fail = {"on": True}

    def construct(model_size, **kwargs):
        if fail["on"]:
            raise RuntimeError("cache unreadable")
        return _SilentModel()

    fake_stt.side_effect = construct
    trans = stt.Transcriber(preload=False)
    trans.prefer_gpu = True
    with pytest.raises(RuntimeError, match="cache unreadable"):
        trans._load_model()
    assert stt._known_cuda_failure() is None, "CPU also failed: CUDA must not be marked unavailable"

    # The cache is repaired; the next load must try CUDA again and get it.
    fail["on"] = False
    fake_stt.reset_mock()
    model = trans._load_model()
    assert isinstance(model, _SilentModel)
    assert [call.kwargs["device"] for call in fake_stt.call_args_list] == ["cuda"]
    assert trans.active_device == "cuda"


def test_cuda_memoized_unavailable_once_cpu_construction_succeeds(monkeypatch, fake_stt):
    monkeypatch.setattr(stt.Transcriber, "_is_model_cached", lambda self, size: True)
    monkeypatch.setattr(stt, "ensure_cuda_libraries_on_path", lambda: [])

    def construct(model_size, **kwargs):
        if kwargs["device"] == "cuda":
            raise RuntimeError("weird")
        return _SilentModel()

    fake_stt.side_effect = construct
    trans = stt.Transcriber(preload=False)
    trans.prefer_gpu = True
    trans._load_model()
    assert [call.kwargs["device"] for call in fake_stt.call_args_list] == ["cuda", "cpu"]
    assert stt._known_cuda_failure() == ("CUDA initialization failed", "cuda_init_failed")
    assert trans.device_fallback_code == "cuda_init_failed"

    # Remembered for the process: the next load goes straight to CPU.
    fake_stt.reset_mock()
    trans._load_model()
    assert [call.kwargs["device"] for call in fake_stt.call_args_list] == ["cpu"]


def test_stale_snapshot_markers_do_not_enable_hub_ref_repair(fake_stt):
    from pathlib import Path
    snapshot = Path(stt.HF_HUB_CACHE) / "models--Systran--faster-whisper-base.en" / "snapshots" / "stale"
    snapshot.mkdir(parents=True)
    for name in ("model.bin", "tokenizer.json"):
        (snapshot / name).write_bytes(b"fixture")
    fake_stt.side_effect = FileNotFoundError("Actual requested Hub ref is unavailable locally")
    trans = stt.Transcriber(preload=False)
    assert trans._is_model_cached("base.en") is True
    assert trans.ensure_loaded() is False
    assert trans.get_runtime_status()["error_code"] == "verification_failed"
    fake_stt.assert_called_once()
    assert fake_stt.call_args.kwargs["local_files_only"] is True


def test_direct_local_load_rejects_missing_cache(monkeypatch, fake_stt):
    monkeypatch.setattr(stt.Transcriber, "_is_model_cached", lambda self, size: False)
    with pytest.raises(FileNotFoundError):
        stt.Transcriber(preload=False)._load_model()
    fake_stt.assert_not_called()


def test_lazy_cpu_recovery_remains_local_on_missing_cache(monkeypatch, fake_stt):
    monkeypatch.setattr(stt.Transcriber, "_is_model_cached", lambda self, size: False)
    with pytest.raises(FileNotFoundError):
        stt.Transcriber(preload=False)._load_cpu_fallback_model()
    fake_stt.assert_not_called()


def test_explicit_whisper_route_grants_constructor_permission(monkeypatch, fake_stt):
    import server
    from backend.api.routes.models import WhisperModelRequest, download_whisper
    monkeypatch.setattr(stt.Transcriber, "_is_model_cached", lambda self, size: False)
    monkeypatch.setattr(server, "download_whisper_model", stt.download_whisper_model)
    result = download_whisper(WhisperModelRequest(model_size="base.en", prefer_gpu=False))
    assert result["ok"] is True
    fake_stt.assert_called_once()
    assert fake_stt.call_args.kwargs["local_files_only"] is False


@pytest.fixture
def live_transcriber(monkeypatch, fake_stt):
    """A live server.transcriber that already failed local-only (model absent), plus the cache switch."""
    import server
    cached = {"present": False}
    monkeypatch.setattr(stt.Transcriber, "_is_model_cached", lambda self, size: cached["present"])
    monkeypatch.setattr(server, "download_whisper_model", stt.download_whisper_model)
    live = stt.Transcriber(preload=False)
    monkeypatch.setattr(server, "transcriber", live)

    def construct(model_size, **kwargs):
        if not kwargs["local_files_only"]:
            cached["present"] = True  # the explicit download "fetched" it
        return object()

    fake_stt.side_effect = construct
    return live, cached


def test_successful_explicit_download_clears_the_live_transcribers_stale_failure(live_transcriber, fake_stt):
    from backend.api.routes.models import WhisperModelRequest, download_whisper
    live, _cached = live_transcriber
    assert live.ensure_loaded() is False
    stale = live.get_runtime_status()
    assert stale["error_code"] == "model_missing" and stale["state"] == "failed"
    fake_stt.assert_not_called()

    assert download_whisper(WhisperModelRequest(model_size="base.en", prefer_gpu=False))["ok"] is True

    status = live.get_runtime_status()
    assert status["error_code"] is None and status["error_state"] is None
    assert status["state"] == "ready" and status["constructed"] is True
    assert live.model is not None
    # Exactly one network-capable construction (the probe); the live refresh stays local-only.
    flags = [call.kwargs["local_files_only"] for call in fake_stt.call_args_list]
    assert flags == [False, True]


def test_failed_explicit_download_leaves_the_live_status_truthful(live_transcriber, fake_stt):
    from backend.api.routes.models import WhisperModelRequest, download_whisper
    live, _cached = live_transcriber
    assert live.ensure_loaded() is False
    fake_stt.side_effect = RuntimeError("offline")

    assert download_whisper(WhisperModelRequest(model_size="base.en", prefer_gpu=False))["ok"] is False

    status = live.get_runtime_status()
    assert status["error_code"] == "model_missing" and status["state"] == "failed"
    assert live.model is None


def test_download_of_another_model_does_not_touch_the_live_status(live_transcriber, fake_stt):
    from backend.api.routes.models import WhisperModelRequest, download_whisper
    live, _cached = live_transcriber
    assert live.ensure_loaded() is False

    assert download_whisper(WhisperModelRequest(model_size="small.en", prefer_gpu=False))["ok"] is True

    status = live.get_runtime_status()
    assert status["error_code"] == "model_missing" and live.model is None
    assert [call.kwargs["local_files_only"] for call in fake_stt.call_args_list] == [False]


def test_download_does_not_load_a_live_transcriber_that_never_failed(live_transcriber, fake_stt):
    """Residency stays the user's call: only a stale acquisition failure is refreshed."""
    from backend.api.routes.models import WhisperModelRequest, download_whisper
    live, _cached = live_transcriber
    assert live.get_runtime_status()["error_code"] is None

    assert download_whisper(WhisperModelRequest(model_size="base.en", prefer_gpu=False))["ok"] is True

    assert live.model is None and live.get_runtime_status()["state"] == "unloaded"
    assert [call.kwargs["local_files_only"] for call in fake_stt.call_args_list] == [False]


def test_cached_implicit_load_uses_local_only(monkeypatch, fake_stt):
    monkeypatch.setattr(stt.Transcriber, "_is_model_cached", lambda self, size: True)
    assert stt.Transcriber(preload=False).ensure_loaded() is True
    assert fake_stt.call_args.kwargs["local_files_only"] is True


def test_incomplete_local_directory_is_missing(tmp_path):
    (tmp_path / "model.bin").write_bytes(b"fixture")
    trans = stt.Transcriber.__new__(stt.Transcriber)
    assert trans._is_model_cached(str(tmp_path)) is False
    (tmp_path / "tokenizer.json").write_bytes(b"fixture")
    assert trans._is_model_cached(str(tmp_path)) is True


@pytest.mark.parametrize("present, expected", [(False, "model_missing"), (True, "verification_failed")])
def test_llm_missing_or_partial_model_does_not_download(monkeypatch, tmp_path, present, expected):
    model_id = mm.DEFAULT_MODEL
    model_path = tmp_path / "model.gguf"
    if present:
        model_path.write_bytes(b"partial fixture")
    monkeypatch.setattr(mm, "get_models_dir", lambda: str(tmp_path))
    monkeypatch.setattr(mm, "get_model_path", lambda model_id: str(model_path))
    monkeypatch.setattr(mm, "is_model_file_complete", lambda model_id: False)
    download = Mock(side_effect=AssertionError("Implicit LLM download"))
    monkeypatch.setattr(mm, "download_file", download)
    result = mm.check_and_download_resources(model_id)
    assert result["ok"] is False
    assert result["code"] == expected
    download.assert_not_called()
    if present:
        assert model_path.read_bytes() == b"partial fixture"


@pytest.mark.parametrize("present, expected", [(False, "model_missing"), (True, "verification_failed")])
def test_llm_missing_or_corrupt_runtime_does_not_repair(monkeypatch, tmp_path, present, expected):
    runtime = tmp_path / "llama-server.exe"
    if present:
        runtime.write_bytes(b"invalid fixture")
    monkeypatch.setattr(mm, "get_models_dir", lambda: str(tmp_path))
    monkeypatch.setattr(mm, "is_model_file_complete", lambda model_id: True)
    monkeypatch.setattr(mm, "get_server_path", lambda: str(runtime))
    monkeypatch.setattr(mm, "validate_llama_server_runtime", lambda path: {"ok": False})
    monkeypatch.setattr(mm, "is_managed_server_path", lambda path: True)
    monkeypatch.setattr(mm, "required_llama_server_build", lambda model_id: None)
    download = Mock(side_effect=AssertionError("Implicit runtime download"))
    monkeypatch.setattr(mm, "download_file", download)
    progress = Mock()
    result = mm.check_and_download_resources(mm.DEFAULT_MODEL, progress_callback=progress)
    assert result["ok"] is False
    assert result["code"] == expected
    download.assert_not_called()
    assert all(call.args[0]["status"] not in {"starting", "downloading"}
               for call in progress.call_args_list)
    if present:
        assert runtime.read_bytes() == b"invalid fixture"


def test_explicit_llm_route_passes_acquisition_permission(monkeypatch):
    import threading
    import server
    from backend.api.routes.models import download_llm_model
    called = threading.Event()
    def acquire(*args, **kwargs):
        called.set()
        return {"ok": True}
    acquisition = Mock(side_effect=acquire)
    monkeypatch.setattr(server, "check_and_download_resources", acquisition)
    monkeypatch.setattr(server, "get_download_state", lambda model_id: {})
    monkeypatch.setattr(server, "_llm_download_jobs", {})
    assert download_llm_model(mm.DEFAULT_MODEL)["ok"] is True
    assert called.wait(timeout=5)
    acquisition.assert_called_once_with(mm.DEFAULT_MODEL, allow_download=True)


def test_corrupt_gguf_uses_existing_digest_gate_without_download(monkeypatch, tmp_path):
    import hashlib
    model_id = "h2-fixture"
    model = tmp_path / "model.gguf"
    model.write_bytes(b"wrong fixture bytes")
    monkeypatch.delenv("BETTERFINGERS_ALLOW_TINY_MODELS", raising=False)
    monkeypatch.setitem(mm.AVAILABLE_MODELS, model_id, {
        "name": "Fixture", "size_bytes": model.stat().st_size,
        "sha256": hashlib.sha256(b"right fixture bytes").hexdigest(),
    })
    monkeypatch.setattr(mm, "get_models_dir", lambda: str(tmp_path))
    monkeypatch.setattr(mm, "get_model_path", lambda selected: str(model))
    download = Mock(side_effect=AssertionError("Implicit corrupt model repair"))
    monkeypatch.setattr(mm, "download_file", download)
    result = mm.check_and_download_resources(model_id)
    assert result["code"] == "verification_failed"
    assert result["ok"] is False
    assert model.read_bytes() == b"wrong fixture bytes"
    download.assert_not_called()


@pytest.mark.parametrize("code,state,fallback", [
    ("model_missing", "model_missing", None),
    ("verification_failed", "verification_failed", None),
    ("cuda_init_failed", "fallback_active", "cuda_init_failed"),
])
def test_server_surfaces_safe_acquisition_and_fallback_codes(code, state, fallback):
    import server
    status = {"constructed": False, "error_code": code, "error_state": state,
              "device_fallback_code": fallback}
    fake = Mock(get_runtime_status=Mock(return_value=status))
    surfaced = server._transcriber_status_snapshot(fake)
    assert surfaced["error_code"] == code
    assert surfaced["error_state"] == state
    assert surfaced["device_fallback_code"] == fallback
    event = server._record_transcriber_runtime_event({"code": code, "state": state,
                                                     "device_fallback_code": fallback})
    assert event["details"]["code"] == code
    assert event["details"]["state"] == state
    assert event["details"]["device_fallback_code"] == fallback


def test_server_still_rejects_arbitrary_diagnostic_payloads():
    import server
    fake = Mock(get_runtime_status=Mock(return_value={
        "error_code": "private payload", "error_state": "private payload",
        "device_fallback_code": "private payload", "device_fallback_reason": "private payload"}))
    surfaced = server._transcriber_status_snapshot(fake)
    assert surfaced["error_code"] is None
    assert surfaced["error_state"] is None
    assert surfaced["device_fallback_code"] is None
    assert surfaced["device_fallback_reason"] is None


def test_youtube_benchmark_constructor_stays_local_only():
    # Inspect the standalone CLI without executing its YouTube fetch path.
    import ast
    from pathlib import Path
    source = Path("tools/youtube_stt_check.py").read_text(encoding="utf-8")
    constructors = [node for node in ast.walk(ast.parse(source))
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "WhisperModel"]
    assert constructors
    for call in constructors:
        local = next(keyword.value for keyword in call.keywords
                     if keyword.arg == "local_files_only")
        assert isinstance(local, ast.Constant) and local.value is True


def test_old_managed_runtime_does_not_report_an_implicit_update(monkeypatch, tmp_path):
    runtime = tmp_path / "llama-server.exe"
    runtime.write_bytes(b"old fixture")
    monkeypatch.setattr(mm, "get_models_dir", lambda: str(tmp_path))
    monkeypatch.setattr(mm, "is_model_file_complete", lambda model_id: True)
    monkeypatch.setattr(mm, "get_server_path", lambda: str(runtime))
    monkeypatch.setattr(mm, "validate_llama_server_runtime", lambda path: {"ok": True, "build": 1})
    monkeypatch.setattr(mm, "is_managed_server_path", lambda path: True)
    monkeypatch.setattr(mm, "required_llama_server_build", lambda model_id: 2)
    download = Mock(side_effect=AssertionError("Implicit runtime update"))
    monkeypatch.setattr(mm, "download_file", download)
    progress = Mock()
    result = mm.check_and_download_resources(mm.DEFAULT_MODEL, progress_callback=progress)
    assert result["ok"] is False
    assert result["code"] == "verification_failed"
    assert all(call.args[0]["status"] not in {"starting", "downloading"}
               for call in progress.call_args_list)
    assert runtime.read_bytes() == b"old fixture"
    download.assert_not_called()
