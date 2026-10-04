"""Locating the NVIDIA cuBLAS/cuDNN runtime for faster-whisper on Windows.

CTranslate2 loads ``cublas64_12.dll`` with a plain LoadLibrary by name, and
cuDNN loads its sub-libraries the same way, so ``os.add_dll_directory`` alone
is not enough: the folders must be on this process's PATH. Measured on the
owner's RTX 5070 laptop (2026-10-04, small.en float16, 10.7 s of speech):
warm 0.47 s vs 1.81 s on 8 CPU threads, once the runtime is reachable.
"""
import os

import pytest

from backend.stt import cuda_runtime


def _make_runtime(root, libs=("cublas", "cudnn")):
    for lib in libs:
        (root / lib / "bin").mkdir(parents=True)
        (root / lib / "bin" / f"{lib}64_dummy.dll").write_bytes(b"")
    return root


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(cuda_runtime, "_registered", None)
    monkeypatch.setattr(cuda_runtime, "_dll_handles", [])
    monkeypatch.setattr(cuda_runtime.os, "add_dll_directory", lambda path: path, raising=False)


def test_finds_wheel_bins_and_prepends_them_to_path_once(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path / "nvidia")
    monkeypatch.setattr(cuda_runtime, "_candidate_roots", lambda: [runtime])
    monkeypatch.setenv("PATH", "C:\\existing")

    first = cuda_runtime.ensure_cuda_libraries_on_path()
    second = cuda_runtime.ensure_cuda_libraries_on_path()

    expected = [str(runtime / "cublas" / "bin"), str(runtime / "cudnn" / "bin")]
    assert first == expected
    assert second == expected
    parts = os.environ["PATH"].split(os.pathsep)
    assert parts[:2] == expected
    assert parts.count(expected[0]) == 1  # idempotent: never prepended twice
    assert parts[-1] == "C:\\existing"


def test_requires_both_cublas_and_cudnn(tmp_path, monkeypatch):
    runtime = _make_runtime(tmp_path / "nvidia", libs=("cublas",))
    monkeypatch.setattr(cuda_runtime, "_candidate_roots", lambda: [runtime])
    monkeypatch.setenv("PATH", "C:\\existing")

    assert cuda_runtime.ensure_cuda_libraries_on_path() == []
    assert os.environ["PATH"] == "C:\\existing"


def test_no_runtime_leaves_path_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(cuda_runtime, "_candidate_roots", lambda: [tmp_path / "missing"])
    monkeypatch.setenv("PATH", "C:\\existing")

    assert cuda_runtime.ensure_cuda_libraries_on_path() == []
    assert os.environ["PATH"] == "C:\\existing"


def test_env_override_is_searched_first(tmp_path, monkeypatch):
    override = _make_runtime(tmp_path / "pack")
    wheels = _make_runtime(tmp_path / "wheels")
    monkeypatch.setenv(cuda_runtime.CUDA_RUNTIME_ENV, str(override))
    monkeypatch.setattr(cuda_runtime, "_wheel_roots", lambda: [wheels])

    roots = cuda_runtime._candidate_roots()

    assert roots[0] == override
    assert wheels in roots
