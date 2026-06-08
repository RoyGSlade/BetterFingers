import logging
import os
import re
import subprocess
import sys
import threading
import zipfile

try:
    import pwd
    import grp
except Exception:  # pragma: no cover - Windows
    pwd = None
    grp = None

import requests

from utils import get_user_data_path

# --- Constants ---
AVAILABLE_MODELS = {
    "gemma-4-e2b-q4": {
        "name": "Gemma 4 E2B (Q4_K_M)",
        "filename": "gemma-4-E2B-it-Q4_K_M.gguf",
        "url": "https://huggingface.co/unsloth/gemma-4-E2B-it-GGUF/resolve/main/gemma-4-E2B-it-Q4_K_M.gguf",
        "size_mb": 2963,
        "family": "gemma-4",
        "group": "studio",
        "roles": ["dispatcher"],
        "lane": "cpu",
        "recommended_for": "Studio dispatcher on low-RAM machines.",
        "server_args": ["--jinja", "--chat-template-kwargs", '{"enable_thinking":false}'],
    },
    "gemma-4-e2b-q8": {
        "name": "Gemma 4 E2B (Q8_0)",
        "filename": "gemma-4-E2B-it-Q8_0.gguf",
        "url": "https://huggingface.co/unsloth/gemma-4-E2B-it-GGUF/resolve/main/gemma-4-E2B-it-Q8_0.gguf",
        "size_mb": 4814,
        "family": "gemma-4",
        "group": "studio",
        "roles": ["dispatcher"],
        "lane": "cpu",
        "recommended_for": "Sharper Studio dispatcher when RAM allows.",
        "server_args": ["--jinja", "--chat-template-kwargs", '{"enable_thinking":false}'],
    },
    "gemma-4-e4b-q4": {
        "name": "Gemma 4 E4B (Q4_K_M)",
        "filename": "gemma-4-E4B-it-Q4_K_M.gguf",
        "url": "https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_K_M.gguf",
        "size_mb": 4747,
        "family": "gemma-4",
        "group": "studio",
        "roles": ["dispatcher"],
        "lane": "cpu",
        "recommended_for": "Default always-on Studio dispatcher.",
        "server_args": ["--jinja", "--chat-template-kwargs", '{"enable_thinking":false}'],
    },
    "gemma-4-e4b-q8": {
        "name": "Gemma 4 E4B (Q8_0)",
        "filename": "gemma-4-E4B-it-Q8_0.gguf",
        "url": "https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q8_0.gguf",
        "size_mb": 7813,
        "family": "gemma-4",
        "group": "studio",
        "roles": ["dispatcher", "writer"],
        "lane": "cpu",
        "recommended_for": "High-quality dispatcher or smaller Studio writer.",
        "server_args": ["--jinja", "--chat-template-kwargs", '{"enable_thinking":false}'],
    },
    "gemma-4-12b-q4": {
        "name": "Gemma 4 12B (Q4_K_M)",
        "filename": "gemma-4-12b-it-Q4_K_M.gguf",
        "url": "https://huggingface.co/unsloth/gemma-4-12b-it-GGUF/resolve/main/gemma-4-12b-it-Q4_K_M.gguf",
        "size_mb": 6792,
        "family": "gemma-4",
        "group": "studio",
        "roles": ["writer"],
        "lane": "gpu-transient",
        "recommended_for": "Default Studio smart writer/showrunner model.",
        "server_args": ["--jinja", "--chat-template-kwargs", '{"enable_thinking":false}'],
    },
    "gemma-4-26b-a4b-q4": {
        "name": "Gemma 4 26B-A4B MoE (UD-Q4_K_M)",
        "filename": "gemma-4-26B-A4B-it-UD-Q4_K_M.gguf",
        "url": "https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/resolve/main/gemma-4-26B-A4B-it-UD-Q4_K_M.gguf",
        "size_mb": 16162,
        "family": "gemma-4",
        "group": "studio",
        "roles": ["writer"],
        "lane": "gpu-transient",
        "recommended_for": "Large Studio writer for users with more RAM/VRAM.",
        "server_args": ["--jinja", "--chat-template-kwargs", '{"enable_thinking":false}'],
    },
    "gemma-4-31b-q4": {
        "name": "Gemma 4 31B (Q4_K_M)",
        "filename": "gemma-4-31B-it-Q4_K_M.gguf",
        "url": "https://huggingface.co/unsloth/gemma-4-31B-it-GGUF/resolve/main/gemma-4-31B-it-Q4_K_M.gguf",
        "size_mb": 17475,
        "family": "gemma-4",
        "group": "studio",
        "roles": ["writer"],
        "lane": "gpu-transient",
        "recommended_for": "Experimental large Studio writer.",
        "server_args": ["--jinja", "--chat-template-kwargs", '{"enable_thinking":false}'],
    },
    "gemma-3-4b-q4": {
        "name": "Gemma 3 4B (Q4_K_M)",
        "filename": "gemma-3-4b-it-Q4_K_M.gguf",
        "url": "https://huggingface.co/unsloth/gemma-3-4b-it-GGUF/resolve/main/gemma-3-4b-it-Q4_K_M.gguf",
        "size_mb": 2600,
        "group": "betterfingers",
        "roles": ["rewrite"],
        "lane": "gpu",
        "recommended_for": "Default BetterFingers rewrite/persona model.",
    },
    "gemma-3-4b-q6": {
        "name": "Gemma 3 4B (Q6_K)",
        "filename": "gemma-3-4b-it-Q6_K.gguf",
        "url": "https://huggingface.co/unsloth/gemma-3-4b-it-GGUF/resolve/main/gemma-3-4b-it-Q6_K.gguf",
        "size_mb": 3500,
        "group": "betterfingers",
        "roles": ["rewrite"],
        "lane": "gpu",
        "recommended_for": "BetterFingers rewrite model with a quality bump.",
    },
    "gemma-3-4b-q8": {
        "name": "Gemma 3 4B (Q8_0)",
        "filename": "gemma-3-4b-it-Q8_0.gguf",
        "url": "https://huggingface.co/unsloth/gemma-3-4b-it-GGUF/resolve/main/gemma-3-4b-it-Q8_0.gguf",
        "size_mb": 4600,
        "group": "betterfingers",
        "roles": ["rewrite"],
        "lane": "gpu",
        "recommended_for": "Best 4B BetterFingers rewrite quality.",
    },
    "gemma-3-12b-q4": {
        "name": "Gemma 3 12B (Q4_K_M)",
        "filename": "gemma-3-12b-it-Q4_K_M.gguf",
        "url": "https://huggingface.co/unsloth/gemma-3-12b-it-GGUF/resolve/main/gemma-3-12b-it-Q4_K_M.gguf",
        "size_mb": 7500,
        "group": "betterfingers",
        "roles": ["rewrite", "writer"],
        "lane": "gpu",
        "recommended_for": "Bigger BetterFingers rewrite or fallback Studio writer.",
    },
    "gemma-3-12b-q6": {
        "name": "Gemma 3 12B (Q6_K)",
        "filename": "gemma-3-12b-it-Q6_K.gguf",
        "url": "https://huggingface.co/unsloth/gemma-3-12b-it-GGUF/resolve/main/gemma-3-12b-it-Q6_K.gguf",
        "size_mb": 10000,
        "group": "betterfingers",
        "roles": ["rewrite", "writer"],
        "lane": "gpu",
        "recommended_for": "Higher-quality 12B rewrite/writer model.",
    },
    "gemma-3-12b-q8": {
        "name": "Gemma 3 12B (Q8_0)",
        "filename": "gemma-3-12b-it-Q8_0.gguf",
        "url": "https://huggingface.co/unsloth/gemma-3-12b-it-GGUF/resolve/main/gemma-3-12b-it-Q8_0.gguf",
        "size_mb": 13000,
        "group": "betterfingers",
        "roles": ["rewrite", "writer"],
        "lane": "gpu",
        "recommended_for": "Largest Gemma 3 rewrite/writer option.",
    },
}

DEFAULT_MODEL = "gemma-3-4b-q4"

if sys.platform.startswith("win"):
    SERVER_FILENAME = "llama-server.exe"
    SERVER_ARCHIVE_NAME = "server-cuda-bin.zip"
    CUDA_ARCHIVE_NAME = "cuda-libs.zip"
    SERVER_BIN_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b9548/llama-b9548-bin-win-cuda-12.4-x64.zip"
    CUDA_LIB_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b9548/cudart-llama-bin-win-cuda-12.4-x64.zip"
else:
    SERVER_FILENAME = "llama-server"
    SERVER_ARCHIVE_NAME = "server-ubuntu-vulkan-bin.tar.gz"
    CUDA_ARCHIVE_NAME = None
    SERVER_BIN_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b9548/llama-b9548-bin-ubuntu-vulkan-x64.tar.gz"
    CUDA_LIB_URL = None

PACKAGED_LLAMA_CPP_BUILD = 9548
GEMMA4_MIN_LLAMA_CPP_BUILD = 8660

LINUX_RUNTIME_LINKS = {
    "libmtmd.so.0": "libmtmd.so.0.0.7870",
    "libllama.so.0": "libllama.so.0.0.7870",
    "libggml.so.0": "libggml.so.0.9.5",
    "libggml-base.so.0": "libggml-base.so.0.9.5",
}

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
    result = dict(row)
    if key in AVAILABLE_MODELS:
        partial_path = get_partial_model_path(key)
        partial_bytes = _file_size(partial_path)
        file_status = get_model_file_status(key)
        result.setdefault("model_id", key)
        result.setdefault("installed", bool(file_status.get("complete")))
        result.setdefault("partial_bytes", partial_bytes)
        result.setdefault("partial_path", partial_path if partial_bytes else "")
        result.setdefault("resumable", bool(partial_bytes))
        result.setdefault("file_status", file_status)
    return result


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


def get_partial_model_path(model_id=None):
    return f"{get_model_path(model_id)}.part"


def _expected_model_bytes(model_id):
    info = AVAILABLE_MODELS.get(model_id or DEFAULT_MODEL, {})
    size_mb = int(info.get("size_mb") or 0)
    return size_mb * 1024 * 1024 if size_mb > 0 else 0


def _file_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _owner_name(uid):
    try:
        if pwd is None:
            return str(uid)
        return pwd.getpwuid(uid).pw_name
    except Exception:
        return str(uid)


def _group_name(gid):
    try:
        if grp is None:
            return str(gid)
        return grp.getgrgid(gid).gr_name
    except Exception:
        return str(gid)


def get_model_file_status(model_id):
    """Return first-run health details for a managed GGUF file.

    ``installed`` answers "is the file complete enough to use"; this status explains whether
    the app can also read, repair, resume, replace, or delete it without surprising the user.
    """
    path = get_model_path(model_id)
    exists = os.path.exists(path)
    size = _file_size(path)
    status = {
        "model_id": model_id,
        "path": path,
        "exists": exists,
        "size_bytes": size,
        "complete": is_model_file_complete(model_id) if exists else False,
        "readable": False,
        "writable": False,
        "owner": "",
        "group": "",
        "mode": "",
        "attention": [],
        "fix_command": "",
        "ok": False,
    }
    if not exists:
        status["attention"].append("missing")
        return status
    try:
        st = os.stat(path)
        status["owner"] = _owner_name(st.st_uid)
        status["group"] = _group_name(st.st_gid)
        status["mode"] = oct(st.st_mode & 0o777)
    except OSError as exc:
        status["attention"].append(f"stat_failed:{exc}")
    status["readable"] = os.access(path, os.R_OK)
    status["writable"] = os.access(path, os.W_OK)
    if not status["complete"]:
        status["attention"].append("incomplete")
    if not status["readable"]:
        status["attention"].append("not_readable")
    # A non-writable managed model may still load, but it cannot be repaired/replaced/deleted by
    # the app. Surface that explicitly so a root-owned file is not mistaken for a perfect install.
    if not status["writable"]:
        status["attention"].append("not_writable")
    current_uid = getattr(os, "getuid", lambda: None)()
    try:
        if current_uid is not None and os.stat(path).st_uid != current_uid:
            status["attention"].append("owned_by_other_user")
            user = _owner_name(current_uid)
            if user and not user.isdigit():
                status["fix_command"] = f"sudo chown {user}:{user} {path}"
    except OSError:
        pass
    status["ok"] = bool(status["complete"] and status["readable"])
    return status


def is_model_file_complete(model_id):
    """Best-effort guard against power-loss partial files being treated as installed."""
    path = get_model_path(model_id)
    if not os.path.exists(path):
        return False
    if not os.access(path, os.R_OK):
        return False
    actual = _file_size(path)
    # Unit tests and developer overrides often use tiny fixture files. Real GGUF
    # downloads are gigabytes, so only enforce catalog-size sanity for model-sized files.
    if actual < 16 * 1024 * 1024:
        return True
    expected = _expected_model_bytes(model_id)
    if not expected:
        return True
    # Catalog sizes are rounded, so allow a little slack while still catching truncation.
    return actual >= int(expected * 0.90)


def get_model_server_args(model_id=None):
    """Returns additional llama-server args for model families that need them."""
    if not model_id or model_id not in AVAILABLE_MODELS:
        model_id = DEFAULT_MODEL
    return list(AVAILABLE_MODELS.get(model_id, {}).get("server_args", []))


def check_model_exists(model_id):
    """Returns True if the model file exists."""
    return is_model_file_complete(model_id)


def delete_model(model_id):
    """Deletes the model file if it exists."""
    path = get_model_path(model_id)
    partial_path = get_partial_model_path(model_id)
    removed = False
    if os.path.exists(path):
        try:
            os.remove(path)
            removed = True
        except Exception as exc:
            return False, f"Failed to delete {model_id}: {exc}"
    if os.path.exists(partial_path):
        try:
            os.remove(partial_path)
            removed = True
        except Exception as exc:
            return False, f"Failed to delete partial download for {model_id}: {exc}"
    return (True, f"Deleted {model_id}") if removed else (False, "Model not found")


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


def get_llama_runtime_env(server_path=None):
    env = os.environ.copy()
    runtime_dir = os.path.dirname(os.path.abspath(server_path or get_server_path()))
    if not sys.platform.startswith("win"):
        existing = env.get("LD_LIBRARY_PATH", "")
        paths = [runtime_dir]
        if existing:
            paths.append(existing)
        env["LD_LIBRARY_PATH"] = os.pathsep.join(paths)
    return env


def _find_runtime_target(runtime_dir, link_name, preferred_target):
    preferred_path = os.path.join(runtime_dir, preferred_target)
    if os.path.exists(preferred_path):
        return preferred_target

    prefix = f"{link_name}."
    candidates = [
        name
        for name in os.listdir(runtime_dir)
        if name.startswith(prefix) and os.path.isfile(os.path.join(runtime_dir, name))
    ]
    if candidates:
        return sorted(candidates)[-1]
    return preferred_target


def _safe_symlink(runtime_dir, link_name, target_name, replace=False, require_target=True):
    link_path = os.path.join(runtime_dir, link_name)
    target_path = os.path.join(runtime_dir, target_name)

    if os.path.islink(link_path):
        current_target = os.readlink(link_path)
        resolved = current_target if os.path.isabs(current_target) else os.path.join(runtime_dir, current_target)
        if os.path.exists(resolved) and not replace:
            return None
        os.remove(link_path)
    elif os.path.exists(link_path):
        return None

    if require_target and not os.path.exists(target_path):
        return f"{link_name} target missing: {target_name}"

    os.symlink(target_name, link_path)
    return None


def repair_linux_runtime_links(runtime_dir=None):
    """
    Recreate shared-library soname links lost by flattened tar extraction.
    """
    if sys.platform.startswith("win"):
        return {"ok": True, "repaired": [], "missing": [], "errors": []}

    runtime_dir = runtime_dir or os.path.dirname(os.path.abspath(get_server_path()))
    if not os.path.isdir(runtime_dir):
        return {"ok": False, "repaired": [], "missing": [runtime_dir], "errors": []}

    repaired = []
    missing = []
    errors = []
    for link_name, preferred_target in LINUX_RUNTIME_LINKS.items():
        link_path = os.path.join(runtime_dir, link_name)
        if os.path.exists(link_path):
            continue

        target_name = _find_runtime_target(runtime_dir, link_name, preferred_target)
        try:
            error = _safe_symlink(runtime_dir, link_name, target_name)
        except OSError as exc:
            errors.append(f"{link_name}: {exc}")
            continue

        if error:
            missing.append(error)
        else:
            repaired.append(f"{link_name} -> {target_name}")

    return {
        "ok": not missing and not errors,
        "repaired": repaired,
        "missing": missing,
        "errors": errors,
    }


def _extract_tar_flat(archive_path, dest_dir):
    import tarfile

    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            name = os.path.basename(member.name)
            if not name:
                continue
            if member.isfile():
                target_path = os.path.join(dest_dir, name)
                if os.path.lexists(target_path) and not os.path.isdir(target_path):
                    os.remove(target_path)
                member.name = name
                archive.extract(member, path=dest_dir)
            elif member.issym():
                target = os.path.basename(member.linkname or "")
                if not target:
                    continue
                error = _safe_symlink(dest_dir, name, target, replace=True, require_target=False)
                if error:
                    logging.warning("Skipped runtime symlink %s -> %s: %s", name, target, error)


def parse_llama_server_build(version_text):
    match = re.search(r"(?:version|build):\s*(\d+)", str(version_text or ""), flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def required_llama_server_build(model_id=None):
    info = AVAILABLE_MODELS.get(model_id or DEFAULT_MODEL, {})
    if str(info.get("family", "")).lower() == "gemma-4":
        return GEMMA4_MIN_LLAMA_CPP_BUILD
    return 0


def is_managed_server_path(server_path):
    try:
        managed_path = os.path.abspath(os.path.join(get_models_dir(), get_server_filename()))
        return os.path.abspath(server_path) == managed_path
    except Exception:
        return False


def validate_llama_server_runtime(server_path=None):
    """Returns whether llama-server can execute in its runtime directory."""
    server_path = server_path or get_server_path()
    if not os.path.exists(server_path):
        return {"ok": False, "message": f"llama-server runtime is missing: {server_path}"}

    repair_result = None
    if not sys.platform.startswith("win"):
        repair_result = repair_linux_runtime_links(os.path.dirname(os.path.abspath(server_path)))

    try:
        result = subprocess.run(
            [server_path, "--version"],
            cwd=os.path.dirname(os.path.abspath(server_path)),
            env=get_llama_runtime_env(server_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        return {"ok": False, "message": f"llama-server runtime failed validation: {exc}"}

    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part and part.strip())
    if result.returncode != 0:
        detail = output or f"exit code {result.returncode}"
        if repair_result and not repair_result.get("ok", False):
            repair_detail = "; ".join(repair_result.get("missing", []) + repair_result.get("errors", []))
            detail = f"{detail}; runtime libraries incomplete: {repair_detail}"
        return {"ok": False, "message": f"llama-server runtime failed validation: {detail}"}

    message = output or "llama-server runtime validated."
    return {"ok": True, "message": message, "build": parse_llama_server_build(message)}


def _parse_content_range_total(value):
    match = re.search(r"/(\d+)\s*$", str(value or ""))
    if not match:
        return 0
    try:
        return int(match.group(1))
    except ValueError:
        return 0


def download_file(url, dest_path, desc="File", progress_callback=None, progress_key="", resume=True):
    """Download a file safely.

    The transfer writes to ``dest_path + ".part"`` and atomically replaces the final
    path only after the response completes. If a previous partial exists and the
    server supports byte ranges, the download resumes instead of restarting.
    """
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
    part_path = f"{dest_path}.part"
    resumed_bytes = _file_size(part_path) if resume and os.path.exists(part_path) else 0
    _emit_progress(
        progress_callback,
        {
            "key": key,
            "status": "starting",
            "desc": desc,
            "percent": 0.0,
            "downloaded_bytes": int(resumed_bytes),
            "total_bytes": 0,
            "partial_path": part_path if resumed_bytes else "",
            "message": (
                f"Resuming {desc} download from {resumed_bytes // (1024 * 1024)} MB."
                if resumed_bytes
                else f"Starting {desc} download."
            ),
        },
    )

    try:
        headers = {"Range": f"bytes={resumed_bytes}-"} if resumed_bytes else {}
        with requests.get(url, stream=True, timeout=120, headers=headers) as response:
            response.raise_for_status()
            if resumed_bytes and response.status_code != 206:
                logging.info("%s server did not resume; restarting partial download.", desc)
                resumed_bytes = 0
                if os.path.exists(part_path):
                    os.remove(part_path)

            content_length = int(response.headers.get("content-length", 0) or 0)
            total_size = _parse_content_range_total(response.headers.get("content-range"))
            if not total_size:
                total_size = resumed_bytes + content_length if resumed_bytes else content_length
            downloaded = resumed_bytes
            last_reported = -1

            mode = "ab" if resumed_bytes else "wb"
            with open(part_path, mode) as handle:
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
                                "partial_path": part_path,
                                "message": (
                                    f"Downloading {desc} ({percent:.1f}%)."
                                    if total_size
                                    else f"Downloading {desc}..."
                                ),
                            },
                        )
                        last_reported = rounded

        if total_size and _file_size(part_path) < total_size:
            raise IOError(
                f"incomplete download: got {_file_size(part_path)} bytes, expected {total_size}"
            )
        os.replace(part_path, dest_path)
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
                "partial_path": "",
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
                "downloaded_bytes": int(_file_size(part_path)),
                "total_bytes": 0,
                "partial_path": part_path if os.path.exists(part_path) else "",
                "message": f"Failed downloading {desc}: {exc}",
            },
        )
        raise


def _prepare_incomplete_model_for_resume(model_id):
    """If a previous crash left a truncated file at the final path, turn it into .part."""
    path = get_model_path(model_id)
    part_path = get_partial_model_path(model_id)
    if not os.path.exists(path) or is_model_file_complete(model_id):
        return 0
    existing = _file_size(path)
    if existing <= 0:
        try:
            os.remove(path)
        except OSError:
            pass
        return 0
    if os.path.exists(part_path):
        if _file_size(part_path) >= existing:
            os.remove(path)
            return _file_size(part_path)
        os.remove(part_path)
    os.replace(path, part_path)
    return existing


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

    if not is_model_file_complete(target_model_id):
        logging.info("Model %s not found.", target_model_id)
        try:
            _prepare_incomplete_model_for_resume(target_model_id)
            partial_path = get_partial_model_path(target_model_id)
            partial_bytes = _file_size(partial_path)
            report({
                "key": target_model_id,
                "status": "starting",
                "percent": 0.0,
                "downloaded_bytes": partial_bytes,
                "partial_path": partial_path if partial_bytes else "",
                "resumable": bool(partial_bytes),
                "message": (
                    f"Resuming {model_info['name']}..."
                    if partial_bytes
                    else f"Downloading {model_info['name']}..."
                ),
            })
            download_file(
                model_info["url"],
                model_path,
                model_info["name"],
                progress_callback=report,
                progress_key=target_model_id,
            )
        except Exception:
            logging.warning("Failed to download model %s. Check internet connection.", target_model_id)
            partial_path = get_partial_model_path(target_model_id)
            partial_bytes = _file_size(partial_path)
            report({
                "key": target_model_id,
                "status": "error",
                "percent": 0.0,
                "downloaded_bytes": partial_bytes,
                "partial_path": partial_path if partial_bytes else "",
                "resumable": bool(partial_bytes),
                "message": (
                    f"Failed downloading {model_info['name']}. "
                    "The partial file was kept and will resume next time."
                ),
            })
    else:
        report({"key": target_model_id, "status": "already_installed", "percent": 100.0, "message": f"{model_info['name']} already installed."})

    model_ready = is_model_file_complete(target_model_id)
    if not model_ready:
        message = f"{model_info['name']} is unavailable. Download failed."
        report({"key": target_model_id, "status": "error", "percent": 0.0, "message": message})
        return {"ok": False, "model_id": target_model_id, "message": message}

    server_path = get_server_path()
    server_needs_install = not os.path.exists(server_path)
    existing_validation = None
    required_build = required_llama_server_build(target_model_id)
    if not server_needs_install:
        existing_validation = validate_llama_server_runtime(server_path)
        existing_build = existing_validation.get("build")
        managed_server = is_managed_server_path(server_path)
        if not existing_validation.get("ok", False) and managed_server:
            server_needs_install = True
            report(
                {
                    "key": f"{target_model_id}:server",
                    "status": "starting",
                    "percent": 0.0,
                    "message": "Repairing llama-server runtime.",
                }
            )
        elif required_build and (existing_build is None or existing_build < required_build):
            if managed_server:
                server_needs_install = True
                report(
                    {
                        "key": f"{target_model_id}:server",
                        "status": "starting",
                        "percent": 0.0,
                        "message": (
                            f"Updating llama-server runtime for {model_info['name']} "
                            f"(found build {existing_build or 'unknown'}, need {required_build}+)."
                        ),
                    }
                )
            else:
                message = (
                    f"{model_info['name']} requires llama.cpp build {required_build}+; "
                    f"found {existing_build or 'unknown'} at {server_path}."
                )
                report({"key": target_model_id, "status": "error", "percent": 0.0, "message": message})
                return {"ok": False, "model_id": target_model_id, "message": message, "runtime": existing_validation}

    if server_needs_install:
        logging.info("llama-server not found or outdated. Downloading binaries...")

        bin_archive = os.path.join(models_dir, SERVER_ARCHIVE_NAME)
        try:
            download_file(
                SERVER_BIN_URL,
                bin_archive,
                "llama-server",
                progress_callback=report,
                progress_key=f"{target_model_id}:server",
            )
            if SERVER_ARCHIVE_NAME.endswith(".zip"):
                with zipfile.ZipFile(bin_archive, "r") as archive:
                    archive.extractall(models_dir)
            elif SERVER_ARCHIVE_NAME.endswith(".tar.gz"):
                _extract_tar_flat(bin_archive, models_dir)
                if os.path.exists(server_path):
                    os.chmod(server_path, 0o755)
                repair_linux_runtime_links(os.path.dirname(os.path.abspath(server_path)))
        finally:
            if os.path.exists(bin_archive):
                os.remove(bin_archive)

        if CUDA_LIB_URL and CUDA_ARCHIVE_NAME:
            cuda_archive = os.path.join(models_dir, CUDA_ARCHIVE_NAME)
            try:
                download_file(
                    CUDA_LIB_URL,
                    cuda_archive,
                    "CUDA Runtime",
                    progress_callback=report,
                    progress_key=f"{target_model_id}:cuda",
                )
                with zipfile.ZipFile(cuda_archive, "r") as archive:
                    archive.extractall(models_dir)
                os.remove(cuda_archive)
            except Exception as exc:
                logging.warning("Failed to download CUDA libs: %s. Server will run on CPU.", exc)
    else:
        logging.info("llama-server exists.")

    server_ready = os.path.exists(server_path)
    if not server_ready:
        message = "llama-server runtime is unavailable after download."
        report({"key": target_model_id, "status": "error", "percent": 0.0, "message": message})
        return {"ok": False, "model_id": target_model_id, "message": message}

    validation = validate_llama_server_runtime(server_path)
    if not validation.get("ok", False):
        message = validation.get("message", "llama-server runtime failed validation.")
        report({"key": target_model_id, "status": "error", "percent": 0.0, "message": message})
        return {"ok": False, "model_id": target_model_id, **validation}

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
    if not is_model_file_complete(model_id) or not os.path.exists(get_server_path()):
        return False
    validation = validate_llama_server_runtime(get_server_path())
    if not validation.get("ok", False):
        return False
    required_build = required_llama_server_build(model_id)
    runtime_build = validation.get("build")
    if required_build and (runtime_build is None or runtime_build < required_build):
        return False
    return True
