"""Studio media model catalog + background downloads.

This is the common downloader for non-GGUF Studio media departments: voice, music,
and ambience. It intentionally only downloads and tracks model assets; runtime
workers load them later through their own adapters.
"""

import logging
import os
import threading
from pathlib import Path

from betterfingers_env import load_local_env

logger = logging.getLogger("studio_media_models")

MEDIA_MODELS = {
    "chatterbox": {
        "kind": "voice",
        "name": "Chatterbox TTS",
        "repo": "ResembleAI/chatterbox",
        "subdir": "chatterbox",
        "size_mb": 4500,
        "roles": ["voice"],
        "lane": "gpu-transient",
        "recommended_for": "Premium expressive Studio voices and hero dialogue.",
    },
    "ace-step-1-5": {
        "kind": "music",
        "name": "ACE-Step 1.5",
        "repo": "ACE-Step/Ace-Step1.5",
        "subdir": "ace-step-1.5",
        "size_mb": 4000,
        "roles": ["music"],
        "lane": "gpu-transient",
        "recommended_for": "Local score generation for reels, acts, and full songs.",
    },
    "stable-audio-open-small": {
        "kind": "ambience",
        "name": "Stable Audio Open Small",
        "repo": "stabilityai/stable-audio-open-small",
        "subdir": "stable-audio-open-small",
        "size_mb": 3800,
        "roles": ["ambience", "sfx"],
        "lane": "gpu-transient",
        "recommended_for": "Scene ambience, room tone, short loops, and sound effects.",
    },
}

DEFAULTS = {
    "voice": "chatterbox",
    "music": "ace-step-1-5",
    "ambience": "stable-audio-open-small",
}

_DL_STATE = {}
_DL_THREADS = {}
_DL_LOCK = threading.Lock()


def _models_dir():
    try:
        import model_manager
        return Path(model_manager.get_models_dir())
    except Exception:
        from utils import get_user_data_path
        d = Path(get_user_data_path()) / "models"
        d.mkdir(parents=True, exist_ok=True)
        return d


def model_path(model_key):
    entry = MEDIA_MODELS.get(model_key)
    if not entry:
        return ""
    return str(_models_dir() / entry.get("subdir", model_key))


def model_installed(model_key):
    path = model_path(model_key)
    if not path:
        return False
    marker = os.path.join(path, ".betterfingers_download_complete")
    return os.path.isfile(marker)


def _dir_size(path):
    total = 0
    root = Path(path)
    if not root.exists():
        return 0
    try:
        for item in root.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
    except OSError:
        return total
    return total


def _partial_bytes(model_key):
    path = model_path(model_key)
    if not path or model_installed(model_key):
        return 0
    return _dir_size(path)


def list_models(kind=None):
    rows = []
    for key, entry in MEDIA_MODELS.items():
        if kind and entry.get("kind") != kind:
            continue
        rows.append({
            "key": key,
            "kind": entry.get("kind"),
            "name": entry.get("name"),
            "repo": entry.get("repo"),
            "size_mb": entry.get("size_mb"),
            "roles": list(entry.get("roles") or []),
            "lane": entry.get("lane", ""),
            "path": model_path(key),
            "installed": model_installed(key),
            "partial_bytes": _partial_bytes(key),
            "resumable": bool(_partial_bytes(key)),
            "recommended_for": entry.get("recommended_for", ""),
            "download_state": download_state(key),
        })
    return rows


def ensure_model(model_key, progress=None):
    entry = MEDIA_MODELS.get(model_key)
    if not entry:
        raise ValueError(f"Unknown media model '{model_key}'.")
    load_local_env()
    dest = model_path(model_key)
    if model_installed(model_key):
        return dest
    if progress:
        progress(f"Downloading {entry['name']} from {entry['repo']}...")
    from huggingface_hub import snapshot_download
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    snapshot_download(repo_id=entry["repo"], local_dir=dest, max_workers=8)
    Path(dest).mkdir(parents=True, exist_ok=True)
    Path(dest, ".betterfingers_download_complete").write_text(entry["repo"], encoding="utf-8")
    return dest


def start_download(model_key):
    with _DL_LOCK:
        thread = _DL_THREADS.get(model_key)
        state = _DL_STATE.get(model_key)
        if thread and thread.is_alive():
            body = dict(state or {})
            body["active"] = True
            return body
        if model_installed(model_key):
            _DL_STATE[model_key] = _done_state(model_key)
            return dict(_DL_STATE[model_key])
        _DL_STATE[model_key] = {
            "status": "downloading",
            "active": True,
            "installed": False,
            "message": f"Downloading {MEDIA_MODELS.get(model_key, {}).get('name', model_key)}...",
            "error": "",
        }

    def _run():
        try:
            ensure_model(model_key)
            with _DL_LOCK:
                _DL_STATE[model_key] = _done_state(model_key)
        except Exception as exc:
            logger.warning("Media model download failed for %s: %s", model_key, exc)
            with _DL_LOCK:
                _DL_STATE[model_key] = {
                    "status": "failed",
                    "active": False,
                    "installed": False,
                    "message": f"Download failed: {exc}",
                    "error": str(exc),
                }
        finally:
            with _DL_LOCK:
                current = _DL_THREADS.get(model_key)
                if current is threading.current_thread():
                    _DL_THREADS.pop(model_key, None)

    thread = threading.Thread(target=_run, name=f"studio-media-download-{model_key}", daemon=True)
    with _DL_LOCK:
        _DL_THREADS[model_key] = thread
    thread.start()
    return dict(_DL_STATE[model_key])


def download_state(model_key):
    with _DL_LOCK:
        thread = _DL_THREADS.get(model_key)
        state = dict(_DL_STATE.get(model_key) or {"status": "idle", "message": ""})
        state["active"] = bool(thread and thread.is_alive())
    state["installed"] = model_installed(model_key)
    state["partial_bytes"] = _partial_bytes(model_key)
    state["resumable"] = bool(state["partial_bytes"] and not state["installed"])
    if state["resumable"] and not state["active"] and state.get("status") == "idle":
        state["status"] = "partial"
        state["message"] = "Partial snapshot found. Download will resume when restarted."
    if state["installed"] and state.get("status") not in ("done", "downloading"):
        state.update(_done_state(model_key))
    return state


def all_downloads():
    return {
        "models": list_models(),
        "defaults": dict(DEFAULTS),
    }


def _done_state(model_key):
    entry = MEDIA_MODELS.get(model_key, {})
    return {
        "status": "done",
        "active": False,
        "installed": True,
        "message": f"{entry.get('name', model_key)} is installed.",
        "error": "",
    }
