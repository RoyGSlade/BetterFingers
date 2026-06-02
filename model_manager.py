import logging
import os
import sys
import threading
import zipfile

import requests

from utils import get_user_data_path

# --- Constants ---
AVAILABLE_MODELS = {
    "gemma-3-4b-q4": {
        "name": "Gemma 3 4B (Q4_K_M)",
        "filename": "gemma-3-4b-it-Q4_K_M.gguf",
        "url": "https://huggingface.co/unsloth/gemma-3-4b-it-GGUF/resolve/main/gemma-3-4b-it-Q4_K_M.gguf",
        "size_mb": 2600,
    },
    "gemma-3-4b-q6": {
        "name": "Gemma 3 4B (Q6_K)",
        "filename": "gemma-3-4b-it-Q6_K.gguf",
        "url": "https://huggingface.co/unsloth/gemma-3-4b-it-GGUF/resolve/main/gemma-3-4b-it-Q6_K.gguf",
        "size_mb": 3500,
    },
    "gemma-3-4b-q8": {
        "name": "Gemma 3 4B (Q8_0)",
        "filename": "gemma-3-4b-it-Q8_0.gguf",
        "url": "https://huggingface.co/unsloth/gemma-3-4b-it-GGUF/resolve/main/gemma-3-4b-it-Q8_0.gguf",
        "size_mb": 4600,
    },
    "gemma-3-12b-q4": {
        "name": "Gemma 3 12B (Q4_K_M)",
        "filename": "gemma-3-12b-it-Q4_K_M.gguf",
        "url": "https://huggingface.co/unsloth/gemma-3-12b-it-GGUF/resolve/main/gemma-3-12b-it-Q4_K_M.gguf",
        "size_mb": 7500,
    },
    "gemma-3-12b-q6": {
        "name": "Gemma 3 12B (Q6_K)",
        "filename": "gemma-3-12b-it-Q6_K.gguf",
        "url": "https://huggingface.co/unsloth/gemma-3-12b-it-GGUF/resolve/main/gemma-3-12b-it-Q6_K.gguf",
        "size_mb": 10000,
    },
    "gemma-3-12b-q8": {
        "name": "Gemma 3 12B (Q8_0)",
        "filename": "gemma-3-12b-it-Q8_0.gguf",
        "url": "https://huggingface.co/unsloth/gemma-3-12b-it-GGUF/resolve/main/gemma-3-12b-it-Q8_0.gguf",
        "size_mb": 13000,
    },
}

DEFAULT_MODEL = "gemma-3-4b-q4"

SERVER_FILENAME = "llama-server.exe"
SERVER_ZIP_NAME = "server-cuda-bin.zip"
CUDA_ZIP_NAME = "cuda-libs.zip"

SERVER_BIN_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b7870/llama-b7870-bin-win-cuda-12.4-x64.zip"
CUDA_LIB_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b7870/cudart-llama-bin-win-cuda-12.4-x64.zip"

_download_state_lock = threading.Lock()
_download_state = {}


def _emit_progress(progress_callback, payload):
    if not callable(progress_callback):
        return
    try:
        progress_callback(dict(payload or {}))
    except Exception:
        pass


def _set_download_state(model_id, payload):
    key = str(model_id or "").strip() or DEFAULT_MODEL
    with _download_state_lock:
        _download_state[key] = dict(payload or {})


def get_download_state(model_id=None):
    key = str(model_id or "").strip() or DEFAULT_MODEL
    with _download_state_lock:
        row = _download_state.get(key, {})
    return dict(row)


def get_models_dir():
    """Returns the directory where models and binaries are stored."""
    path = os.path.join(get_user_data_path(), "models")
    os.makedirs(path, exist_ok=True)
    return path


def get_repo_root():
    return os.path.dirname(os.path.abspath(__file__))


def get_model_path(model_id=None):
    """Returns absolute path to the GGUF model."""
    override = os.getenv("BETTERFINGERS_MODEL_PATH")
    if override and os.path.exists(override):
        return override

    if not model_id or model_id not in AVAILABLE_MODELS:
        model_id = DEFAULT_MODEL
    filename = AVAILABLE_MODELS[model_id]["filename"]
    return os.path.join(get_models_dir(), filename)


def check_model_exists(model_id):
    """Returns True if the model file exists."""
    path = get_model_path(model_id)
    return os.path.exists(path)


def delete_model(model_id):
    """Deletes the model file if it exists."""
    path = get_model_path(model_id)
    if os.path.exists(path):
        try:
            os.remove(path)
            return True, f"Deleted {model_id}"
        except Exception as exc:
            return False, f"Failed to delete {model_id}: {exc}"
    return False, "Model not found"


def get_server_filename():
    """Returns the platform-specific llama-server binary name."""
    if sys.platform.startswith("win"):
        return "llama-server.exe"
    return "llama-server"


def get_repo_local_server_path():
    """Returns the repo-local llama-server path used for Linux development."""
    return os.path.join(get_repo_root(), ".betterfingers", "llama-server", "bin", get_server_filename())


def get_server_path():
    """Returns absolute path to the llama-server binary."""
    override = os.getenv("BETTERFINGERS_LLAMA_SERVER")
    if override and os.path.exists(override):
        return override

    repo_local = get_repo_local_server_path()
    if os.path.exists(repo_local):
        return repo_local

    return os.path.join(get_models_dir(), get_server_filename())


def download_file(url, dest_path, desc="File", progress_callback=None, progress_key=""):
    """Downloads a file with optional progress callbacks."""
    key = str(progress_key or desc or "file").strip()
    if os.path.exists(dest_path):
        logging.info("%s already exists: %s", desc, dest_path)
        _emit_progress(
            progress_callback,
            {
                "key": key,
                "status": "already_installed",
                "desc": desc,
                "percent": 100.0,
                "downloaded_bytes": 0,
                "total_bytes": 0,
                "message": f"{desc} already installed.",
            },
        )
        return

    logging.info("Downloading %s...", desc)
    logging.info("URL: %s", url)
    _emit_progress(
        progress_callback,
        {
            "key": key,
            "status": "starting",
            "desc": desc,
            "percent": 0.0,
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "message": f"Starting {desc} download.",
        },
    )

    try:
        with requests.get(url, stream=True, timeout=120) as response:
            response.raise_for_status()
            total_size = int(response.headers.get("content-length", 0) or 0)
            downloaded = 0
            last_reported = -1

            with open(dest_path, "wb") as handle:
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    downloaded += len(chunk)

                    percent = (downloaded / total_size) * 100.0 if total_size else 0.0
                    rounded = int(percent) if total_size else int(downloaded / (1024 * 1024))
                    if rounded != last_reported:
                        _emit_progress(
                            progress_callback,
                            {
                                "key": key,
                                "status": "downloading",
                                "desc": desc,
                                "percent": float(percent),
                                "downloaded_bytes": int(downloaded),
                                "total_bytes": int(total_size),
                                "message": (
                                    f"Downloading {desc} ({percent:.1f}%)."
                                    if total_size
                                    else f"Downloading {desc}..."
                                ),
                            },
                        )
                        last_reported = rounded

        logging.info("Download complete: %s", dest_path)
        _emit_progress(
            progress_callback,
            {
                "key": key,
                "status": "complete",
                "desc": desc,
                "percent": 100.0,
                "downloaded_bytes": int(downloaded),
                "total_bytes": int(total_size),
                "message": f"{desc} download complete.",
            },
        )
    except Exception as exc:
        logging.error("Failed to download %s: %s", desc, exc)
        _emit_progress(
            progress_callback,
            {
                "key": key,
                "status": "error",
                "desc": desc,
                "percent": 0.0,
                "downloaded_bytes": 0,
                "total_bytes": 0,
                "message": f"Failed downloading {desc}: {exc}",
            },
        )
        if os.path.exists(dest_path):
            os.remove(dest_path)
        raise


def check_and_download_resources(model_id=None, progress_callback=None):
    """
    Ensures model and server (bin + cuda libs) are present.
    """
    models_dir = get_models_dir()

    target_model_id = model_id if model_id in AVAILABLE_MODELS else DEFAULT_MODEL
    model_info = AVAILABLE_MODELS[target_model_id]
    model_path = get_model_path(target_model_id)

    def report(payload):
        body = dict(payload or {})
        body.setdefault("model_id", target_model_id)
        _set_download_state(target_model_id, body)
        _emit_progress(progress_callback, body)

    if not os.path.exists(model_path):
        logging.info("Model %s not found.", target_model_id)
        try:
            report({"key": target_model_id, "status": "starting", "percent": 0.0, "message": f"Downloading {model_info['name']}..."})
            download_file(
                model_info["url"],
                model_path,
                model_info["name"],
                progress_callback=report,
                progress_key=target_model_id,
            )
        except Exception:
            logging.warning("Failed to download model %s. Check internet connection.", target_model_id)
            report({"key": target_model_id, "status": "error", "percent": 0.0, "message": f"Failed downloading {model_info['name']}."})
    else:
        report({"key": target_model_id, "status": "already_installed", "percent": 100.0, "message": f"{model_info['name']} already installed."})

    model_ready = os.path.exists(model_path)
    if not model_ready:
        message = f"{model_info['name']} is unavailable. Download failed."
        report({"key": target_model_id, "status": "error", "percent": 0.0, "message": message})
        return {"ok": False, "model_id": target_model_id, "message": message}

    server_path = get_server_path()
    if not os.path.exists(server_path):
        if not sys.platform.startswith("win"):
            repo_local_path = get_repo_local_server_path()
            message = (
                "llama-server is not configured for this platform. "
                "Install a local llama-server binary at "
                f"{repo_local_path} or set BETTERFINGERS_LLAMA_SERVER to its path."
            )
            logging.warning(message)
            report({"key": target_model_id, "status": "error", "percent": 0.0, "message": message})
            return {"ok": False, "model_id": target_model_id, "message": message}

        logging.info("llama-server not found. Downloading binaries...")

        bin_zip = os.path.join(models_dir, SERVER_ZIP_NAME)
        try:
            download_file(
                SERVER_BIN_URL,
                bin_zip,
                "llama-server (AVX2)",
                progress_callback=report,
                progress_key=f"{target_model_id}:server",
            )
            with zipfile.ZipFile(bin_zip, "r") as archive:
                archive.extractall(models_dir)
        finally:
            if os.path.exists(bin_zip):
                os.remove(bin_zip)

        cuda_zip = os.path.join(models_dir, CUDA_ZIP_NAME)
        try:
            download_file(
                CUDA_LIB_URL,
                cuda_zip,
                "CUDA 12.4 Runtime",
                progress_callback=report,
                progress_key=f"{target_model_id}:cuda",
            )
            with zipfile.ZipFile(cuda_zip, "r") as archive:
                archive.extractall(models_dir)
            os.remove(cuda_zip)
        except Exception as exc:
            logging.warning("Failed to download CUDA libs: %s. Server will run on CPU.", exc)
    else:
        logging.info("llama-server exists.")

    server_ready = os.path.exists(server_path)
    if not server_ready:
        message = "llama-server runtime is unavailable after download."
        report({"key": target_model_id, "status": "error", "percent": 0.0, "message": message})
        return {"ok": False, "model_id": target_model_id, "message": message}

    ready_message = f"{model_info['name']} and runtime are ready."
    report(
        {
            "key": target_model_id,
            "status": "ready",
            "percent": 100.0,
            "message": ready_message,
        }
    )
    return {"ok": True, "model_id": target_model_id, "message": ready_message}


def is_ready(model_id=None):
    return os.path.exists(get_model_path(model_id)) and os.path.exists(get_server_path())
