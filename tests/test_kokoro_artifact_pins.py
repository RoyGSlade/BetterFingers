"""Kokoro voice files fetched on first read-aloud are checked against pinned
sizes/SHA-256s before onnxruntime ever sees them. No network: the requests
module is replaced by a fake that serves fixed bytes."""
import hashlib
import os

import pytest

from backend.tts import tts_engine
from backend.tts.tts_engine import ReviewTTSEngine

GOOD = b"kokoro-model-bytes" * 64


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        for start in range(0, len(self._payload), 100):
            yield self._payload[start:start + 100]


class _FakeRequests:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def get(self, url, stream=True, timeout=60):
        self.calls += 1
        return _Response(self.payload)


@pytest.fixture
def serve(monkeypatch):
    real_import = tts_engine.importlib.import_module

    def install(payload):
        fake = _FakeRequests(payload)
        monkeypatch.setattr(
            tts_engine.importlib, "import_module",
            lambda name: fake if name == "requests" else real_import(name),
        )
        return fake

    return install


@pytest.fixture
def pinned(monkeypatch):
    pins = dict(tts_engine._KOKORO_ARTIFACT_PINS)
    pins["kokoro-v1.0.onnx"] = (len(GOOD), hashlib.sha256(GOOD).hexdigest())
    monkeypatch.setattr(tts_engine, "_KOKORO_ARTIFACT_PINS", pins)


def _ensure(tmp_path, name="kokoro-v1.0.onnx"):
    path = tmp_path / name
    return path, ReviewTTSEngine._ensure_artifact(str(path), "https://example.invalid/x", "kokoro-onnx model")


def test_matching_download_is_installed(tmp_path, serve, pinned):
    serve(GOOD)
    path, (ok, msg) = _ensure(tmp_path)
    assert ok and "downloaded" in msg
    assert path.read_bytes() == GOOD
    assert not os.path.exists(f"{path}.part")


@pytest.mark.parametrize("payload", [GOOD[:-1] + b"X", GOOD[:-10]], ids=["tampered", "truncated"])
def test_mismatching_download_is_discarded(tmp_path, serve, pinned, payload):
    serve(payload)
    path, (ok, msg) = _ensure(tmp_path)
    assert not ok and "download failed" in msg
    assert not path.exists()
    assert not os.path.exists(f"{path}.part")


def test_existing_file_with_pinned_size_is_used_without_network(tmp_path, serve, pinned):
    fake = serve(b"never served")
    (tmp_path / "kokoro-v1.0.onnx").write_bytes(GOOD)
    _, (ok, msg) = _ensure(tmp_path)
    assert ok and "ready" in msg
    assert fake.calls == 0


def test_existing_file_with_wrong_size_is_fetched_again(tmp_path, serve, pinned):
    fake = serve(GOOD)
    path = tmp_path / "kokoro-v1.0.onnx"
    path.write_bytes(b"truncated earlier download")
    _, (ok, _msg) = _ensure(tmp_path)
    assert ok and fake.calls == 1
    assert path.read_bytes() == GOOD


def test_unpinned_artifact_keeps_previous_behaviour(tmp_path, serve):
    serve(b"anything")
    path, (ok, _msg) = _ensure(tmp_path, name="custom-voice.bin")
    assert ok and path.read_bytes() == b"anything"


def test_real_pins_cover_every_url_the_engine_builds():
    # Every filename _load_kokoro_onnx_backend can request has a pin; the full
    # model and voices carry a SHA-256.
    pins = tts_engine._KOKORO_ARTIFACT_PINS
    for name in ("kokoro-v1.0.onnx", "kokoro-v1.0.fp16.onnx", "kokoro-v1.0.int8.onnx", "voices-v1.0.bin"):
        assert name in pins and isinstance(pins[name][0], int)
    assert pins["kokoro-v1.0.onnx"][1] and pins["voices-v1.0.bin"][1]
