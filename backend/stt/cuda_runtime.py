"""Make the NVIDIA cuBLAS/cuDNN runtime reachable for faster-whisper on Windows.

CTranslate2 loads ``cublas64_12.dll`` with a plain ``LoadLibrary`` by name and
cuDNN loads its sub-libraries the same way, so ``os.add_dll_directory`` alone
does not help: the folders must be on THIS process's PATH (never the system
PATH). Child processes inherit it, which is harmless for llama-server because
Windows searches an executable's own folder first and it ships its own CUDA DLLs.

Where the runtime may live, first match wins:

1. ``BETTERFINGERS_CUDA_RUNTIME_DIR`` -- explicit override (diagnostics, or a
   future optional GPU pack location).
2. ``<user data>/runtimes/cuda12`` -- reserved for the optional GPU pack.
3. The ``nvidia-cublas-cu12`` / ``nvidia-cudnn-cu12`` wheels in this Python
   environment (development installs).

A root qualifies only if BOTH ``cublas/bin`` and ``cudnn/bin`` exist. Nothing here
downloads anything; with no runtime present, transcriber's CUDA load probe fails
and it falls back to CPU exactly as before.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

CUDA_RUNTIME_ENV = "BETTERFINGERS_CUDA_RUNTIME_DIR"
_LIBS = ("cublas", "cudnn")

_lock = threading.Lock()
_registered: list[str] | None = None
_dll_handles: list = []  # os.add_dll_directory handles must stay alive


def _wheel_roots() -> list[Path]:
    """``site-packages/nvidia`` folders holding the pip-installed runtime wheels."""
    try:
        import importlib.util

        spec = importlib.util.find_spec("nvidia")
    except (ImportError, ValueError):
        return []
    if spec is None or not spec.submodule_search_locations:
        return []
    return [Path(location) for location in spec.submodule_search_locations]


def _pack_root() -> Path | None:
    try:
        from backend.config.utils import get_user_data_path

        return Path(get_user_data_path()) / "runtimes" / "cuda12"
    except Exception:
        return None


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    override = os.environ.get(CUDA_RUNTIME_ENV, "").strip()
    if override:
        roots.append(Path(override))
    pack = _pack_root()
    if pack is not None:
        roots.append(pack)
    roots.extend(_wheel_roots())
    return roots


def _bins_for(root: Path) -> list[str]:
    bins = [root / lib / "bin" for lib in _LIBS]
    return [str(b) for b in bins] if all(b.is_dir() for b in bins) else []


def ensure_cuda_libraries_on_path() -> list[str]:
    """Prepend the first complete runtime's ``bin`` folders to this process's
    PATH (and register them as DLL directories). Idempotent and thread-safe.
    Returns the folders in effect, or ``[]`` when no runtime was found."""
    global _registered
    with _lock:
        if _registered is not None:
            return list(_registered)
        bins: list[str] = []
        for root in _candidate_roots():
            bins = _bins_for(root)
            if bins:
                break
        if bins:
            current = os.environ.get("PATH", "")
            present = {os.path.normcase(p) for p in current.split(os.pathsep) if p}
            missing = [b for b in bins if os.path.normcase(b) not in present]
            if missing:
                os.environ["PATH"] = os.pathsep.join(missing + ([current] if current else []))
            add_dll_directory = getattr(os, "add_dll_directory", None)
            if add_dll_directory is not None:
                for b in bins:
                    try:
                        _dll_handles.append(add_dll_directory(b))
                    except OSError:
                        pass
        _registered = bins
        return list(bins)
