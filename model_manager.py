import hashlib
import json
import logging
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
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
        # Verified against Hugging Face LFS metadata (supply-chain gate, §11).
        "sha256": "9378bc471710229ef165709b62e34bfb62231420ddaf6d729e727305b5b8672d",
        "size_bytes": 3106736256,
        "size_mb": 2963,
        "family": "gemma-4",
        "group": "studio",
        "roles": ["dispatcher", "rewrite"],
        "lane": "cpu",
        "recommended_for": "Default rewrite/persona model and Studio dispatcher on low-RAM machines.",
        "server_args": ["--jinja", "--chat-template-kwargs", '{"enable_thinking":false}'],
    },
    "gemma-4-e2b-q8": {
        "name": "Gemma 4 E2B (Q8_0)",
        "filename": "gemma-4-E2B-it-Q8_0.gguf",
        "url": "https://huggingface.co/unsloth/gemma-4-E2B-it-GGUF/resolve/main/gemma-4-E2B-it-Q8_0.gguf",
        # Verified against Hugging Face LFS metadata (supply-chain gate, §11).
        "sha256": "0a8488b149e1f700712c35d5bf0a3795f9dcc2563b4944d5ef2fb89375f9483e",
        "size_bytes": 5048350848,
        "size_mb": 4814,
        "family": "gemma-4",
        "group": "studio",
        "roles": ["dispatcher", "rewrite"],
        "lane": "cpu",
        "recommended_for": "Sharper rewrite/dispatcher quality when RAM allows.",
        "server_args": ["--jinja", "--chat-template-kwargs", '{"enable_thinking":false}'],
    },
    "gemma-4-e4b-q4": {
        "name": "Gemma 4 E4B (Q4_K_M)",
        "filename": "gemma-4-E4B-it-Q4_K_M.gguf",
        "url": "https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q4_K_M.gguf",
        # Verified against Hugging Face LFS metadata (supply-chain gate, §11).
        "sha256": "519b9793ed6ce0ff530f1b7c96e848e08e49e7af4d57bb97f76215963a54146d",
        "size_bytes": 4977169568,
        "size_mb": 4747,
        "family": "gemma-4",
        "group": "studio",
        "roles": ["dispatcher", "rewrite"],
        "lane": "cpu",
        "recommended_for": "Default always-on Studio dispatcher.",
        "server_args": ["--jinja", "--chat-template-kwargs", '{"enable_thinking":false}'],
    },
    "gemma-4-e4b-q8": {
        "name": "Gemma 4 E4B (Q8_0)",
        "filename": "gemma-4-E4B-it-Q8_0.gguf",
        "url": "https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/resolve/main/gemma-4-E4B-it-Q8_0.gguf",
        # Verified against Hugging Face LFS metadata (supply-chain gate, §11).
        "sha256": "a2232a649523c36bf530f1dc3614eb8c800645c4227390381c8b05d4d6eee05a",
        "size_bytes": 8192951456,
        "size_mb": 7813,
        "family": "gemma-4",
        "group": "studio",
        "roles": ["dispatcher", "writer", "rewrite"],
        "lane": "cpu",
        "recommended_for": "High-quality dispatcher or smaller Studio writer.",
        "server_args": ["--jinja", "--chat-template-kwargs", '{"enable_thinking":false}'],
    },
    "gemma-4-12b-q4": {
        "name": "Gemma 4 12B (Q4_K_M)",
        "filename": "gemma-4-12b-it-Q4_K_M.gguf",
        "url": "https://huggingface.co/unsloth/gemma-4-12b-it-GGUF/resolve/main/gemma-4-12b-it-Q4_K_M.gguf",
        # Verified against Hugging Face LFS metadata (supply-chain gate, §11).
        "sha256": "43fec98c5102b1c446b4ddd0a9439f1db3a2e1f2e0b8cd143ce1ea619a9403d6",
        "size_bytes": 7121860000,
        "size_mb": 6792,
        "family": "gemma-4",
        "group": "studio",
        "roles": ["writer"],
        "lane": "gpu-transient",
        "recommended_for": "Default Studio smart writer/showrunner model.",
        "server_args": ["--jinja", "--chat-template-kwargs", '{"enable_thinking":false}'],
    },
    "gemma-4-12b-q8": {
        "name": "Gemma 4 12B (Q8_0)",
        "filename": "gemma-4-12b-it-Q8_0.gguf",
        "url": "https://huggingface.co/unsloth/gemma-4-12b-it-GGUF/resolve/main/gemma-4-12b-it-Q8_0.gguf",
        # Verified against Hugging Face LFS metadata (supply-chain gate, §11).
        "sha256": "74d2d4f0b5b08ca8589d1a5f50e689c0984469f3cedbdc7d67458c6e9e35496a",
        "size_bytes": 12669646240,
        "size_mb": 12083,
        "family": "gemma-4",
        "group": "studio",
        "roles": ["writer"],
        "lane": "gpu-transient",
        "recommended_for": "Highest-quality Studio writer for 24 GB+ machines.",
        "server_args": ["--jinja", "--chat-template-kwargs", '{"enable_thinking":false}'],
    },
}

DEFAULT_MODEL = "gemma-4-e2b-q4"

# SHA-256 for every downloaded executable runtime (supply-chain gate, §11).
# The app downloads, extracts, chmods, and *launches* these — the most
# sensitive path in the application. Hashes computed from the pinned b9548
# release assets; a release bump must update these alongside the URLs.
RUNTIME_ARTIFACT_SHA256 = {
    "llama-b9548-bin-win-cuda-12.4-x64.zip":
        "c954d7a206b40ad57023fe09bc50c26f2c1af6ddd767e524c91a9a5674e0f1fe",
    "cudart-llama-bin-win-cuda-12.4-x64.zip":
        "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
    "llama-b9548-bin-win-vulkan-x64.zip":
        "ecc031e41eb46025e2303fc5412339042b7a9c5881d6c53f91bebeef33f6cabd",
    "llama-b9548-bin-ubuntu-vulkan-x64.tar.gz":
        "5ea8c3b051312e12c649d2214b1a7fdfd773b82f9724141771d22cdfe544f0aa",
}


def runtime_artifact_sha256(url):
    return RUNTIME_ARTIFACT_SHA256.get(str(url or "").rsplit("/", 1)[-1])


# Named llama.cpp b9548 runtime archives (single source of truth per URL).
# Windows ships two vendor archives — CUDA (NVIDIA) and Vulkan (AMD/Intel, plus
# a CPU fallback baked in) — and the one to install is chosen at provision time
# by :func:`resolve_runtime_spec`. Linux uses the vendor-neutral Vulkan build.
_LLAMA_RELEASE = "https://github.com/ggml-org/llama.cpp/releases/download/b9548"
WIN_CUDA_BIN_URL = f"{_LLAMA_RELEASE}/llama-b9548-bin-win-cuda-12.4-x64.zip"
WIN_CUDA_LIB_URL = f"{_LLAMA_RELEASE}/cudart-llama-bin-win-cuda-12.4-x64.zip"
WIN_VULKAN_BIN_URL = f"{_LLAMA_RELEASE}/llama-b9548-bin-win-vulkan-x64.zip"
LINUX_VULKAN_BIN_URL = f"{_LLAMA_RELEASE}/llama-b9548-bin-ubuntu-vulkan-x64.tar.gz"

WIN_CUDA_ARCHIVE_NAME = "server-cuda-bin.zip"
WIN_CUDA_LIB_ARCHIVE_NAME = "cuda-libs.zip"
WIN_VULKAN_ARCHIVE_NAME = "server-win-vulkan-bin.zip"
LINUX_VULKAN_ARCHIVE_NAME = "server-ubuntu-vulkan-bin.tar.gz"

if sys.platform == "win32":
    # Module-level defaults describe the CUDA spec for back-compat; the actual
    # per-machine choice is made by resolve_runtime_spec() at install time.
    SERVER_FILENAME = "llama-server.exe"
    SERVER_ARCHIVE_NAME = WIN_CUDA_ARCHIVE_NAME
    CUDA_ARCHIVE_NAME = WIN_CUDA_LIB_ARCHIVE_NAME
    SERVER_BIN_URL = WIN_CUDA_BIN_URL
    CUDA_LIB_URL = WIN_CUDA_LIB_URL
else:
    SERVER_FILENAME = "llama-server"
    SERVER_ARCHIVE_NAME = LINUX_VULKAN_ARCHIVE_NAME
    CUDA_ARCHIVE_NAME = None
    SERVER_BIN_URL = LINUX_VULKAN_BIN_URL
    CUDA_LIB_URL = None


def _runtime_backend_override():
    """Operator override for runtime selection: ``cuda`` | ``vulkan`` | ``cpu``.
    Lets a tester force either Windows backend without swapping hardware (e.g.
    validate the Vulkan path on an NVIDIA box, or vice-versa)."""
    return (os.getenv("BETTERFINGERS_LLAMA_RUNTIME", "") or "").strip().lower()


def _windows_has_nvidia_gpu():
    """True when an NVIDIA GPU + driver is present (``nvidia-smi`` enumerates a
    GPU). Deterministic and cheap, and — unlike hardware_report's Vulkan probe —
    it never touches the (possibly not-yet-installed) llama-server binary, so it
    is safe to call during provisioning."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return False
    try:
        result = subprocess.run([exe, "-L"], capture_output=True, text=True, timeout=8)
    except Exception:
        return False
    return result.returncode == 0 and "GPU 0" in (result.stdout or "")


def _select_runtime_spec(platform_name, prefer_cuda):
    """Pure mapping from (platform, prefer_cuda) → the archive spec to install.

    Split out from :func:`resolve_runtime_spec` so the selection table is
    unit-testable without patching ``sys.platform`` or shelling out to
    nvidia-smi. Returns a dict: ``filename``, ``archive_name``, ``bin_url``,
    ``cuda_archive_name``, ``cuda_lib_url``, ``backend``.
    """
    if platform_name == "win32":
        if prefer_cuda:
            return {
                "filename": "llama-server.exe",
                "archive_name": WIN_CUDA_ARCHIVE_NAME,
                "bin_url": WIN_CUDA_BIN_URL,
                "cuda_archive_name": WIN_CUDA_LIB_ARCHIVE_NAME,
                "cuda_lib_url": WIN_CUDA_LIB_URL,
                "backend": "cuda",
            }
        # Vulkan build is vendor-neutral (AMD/Intel) and runs CPU-only when no
        # Vulkan device is present, so it also IS the CPU fallback. No cudart.
        return {
            "filename": "llama-server.exe",
            "archive_name": WIN_VULKAN_ARCHIVE_NAME,
            "bin_url": WIN_VULKAN_BIN_URL,
            "cuda_archive_name": None,
            "cuda_lib_url": None,
            "backend": "vulkan",
        }
    # Linux (and any non-Windows that reaches the download path): ubuntu-vulkan.
    return {
        "filename": "llama-server",
        "archive_name": LINUX_VULKAN_ARCHIVE_NAME,
        "bin_url": LINUX_VULKAN_BIN_URL,
        "cuda_archive_name": None,
        "cuda_lib_url": None,
        "backend": "vulkan",
    }


def resolve_runtime_spec():
    """Choose the llama.cpp runtime archive to install for THIS machine.

    On Windows we pick CUDA only when an NVIDIA GPU is actually present;
    otherwise Vulkan — so a non-NVIDIA Windows PC gets a runtime that works and
    accelerates (AMD/Intel via Vulkan, or CPU) instead of a CUDA build with no
    usable device and a pointless ~300 MB cudart download. Honors the
    ``BETTERFINGERS_LLAMA_RUNTIME`` override. Linux/macOS are unchanged.
    """
    if sys.platform != "win32":
        return _select_runtime_spec(sys.platform, prefer_cuda=False)

    override = _runtime_backend_override()
    if override == "cuda":
        prefer_cuda = True
    elif override in ("vulkan", "cpu"):
        prefer_cuda = False
    else:
        prefer_cuda = _windows_has_nvidia_gpu()
    return _select_runtime_spec("win32", prefer_cuda)

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
    """Guard against partial/corrupt/wrong files being treated as installed.

    Completeness is never inferred from size alone (§11): a size-matching file is
    only "complete" once its SHA-256 matches the catalog digest. The digest check
    is cache-aware (see :func:`_cached_digest_ok`) so multi-GB models are not
    rehashed on every call.
    """
    path = get_model_path(model_id)
    if not os.path.exists(path):
        return False
    if not os.access(path, os.R_OK):
        return False
    actual = _file_size(path)
    info = AVAILABLE_MODELS.get(model_id, {})
    # Tiny fixture allowance for unit tests / dev overrides, gated behind an
    # explicit flag. Production leaves it off, so a sub-16MiB file falls through
    # to the exact-size and digest checks below and is rejected like any other
    # truncated or wrong file — size is never enough on its own.
    if actual < 16 * 1024 * 1024 and _tiny_models_allowed():
        return True
    # Exact byte size from the artifact manifest (§11) when available —
    # a size mismatch means truncation or the wrong file.
    exact = info.get("size_bytes")
    if exact:
        if actual != int(exact):
            return False
    else:
        expected = _expected_model_bytes(model_id)
        # Catalog sizes are rounded, so allow a little slack while still catching truncation.
        if expected and actual < int(expected * 0.90):
            return False
    # Size looked right; only the digest proves it is the artifact we pinned.
    expected_sha = info.get("sha256")
    if expected_sha:
        ok, _from_cache = _cached_digest_ok(path, expected_sha)
        return ok
    return True


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
    # Drop the verification sidecar + cached verdict so a later file that happens
    # to land at the same path can't be trusted on a stale digest (§11).
    sidecar = f"{path}.sha256"
    if os.path.exists(sidecar):
        try:
            os.remove(sidecar)
        except OSError:
            pass
    _drop_verify_cache_entry(path)
    return (True, f"Deleted {model_id}") if removed else (False, "Model not found")


def get_server_filename():
    """Returns the platform-specific llama-server binary name."""
    if sys.platform == "win32":
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
                    try:
                        os.remove(target_path)
                    except PermissionError:
                        # Windows refuses to unlink read-only files; clear the
                        # bit and retry (0o555-installed runtimes are normal).
                        os.chmod(target_path, 0o644)
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
    # Only the gemma-4 family has a known minimum build today; a new model
    # family with its own llama.cpp runtime requirement must be added here
    # explicitly, or it silently gets 0 (no minimum enforced).
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

    # Verify the binary's digest BEFORE we execute it with --version (§11).
    # A managed binary swapped underneath us (same filename) is caught here and
    # quarantined, so a tampered executable is never launched.
    integrity = verify_installed_runtime(server_path, quarantine=True)
    if not integrity.get("ok", False):
        return {
            "ok": False,
            "message": f"llama-server binary failed integrity check ({integrity.get('reason')}): {server_path}",
            "integrity": integrity,
        }

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


def sha256_file(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hmac_compare(a, b):
    import hmac as _hmac
    return _hmac.compare_digest(str(a or "").lower(), str(b or "").lower())


# --- Existing-artifact verification (supply-chain gate, §11) -------------------
# download_file() proves NEW transfers; the helpers below prove artifacts that
# are already on disk. A byte size can be forged or coincidentally matched, so
# nothing here trusts size alone — the digest is the only proof an installed
# GGUF or the managed llama-server binary is still the file we pinned/installed.

_VERIFY_CACHE_NAME = ".verify_cache.json"


def _tiny_models_allowed():
    """Tiny fixture files (unit tests, dev overrides) are only trusted when this
    flag is set. Production leaves it unset so a sub-16MiB "model" is never
    accepted by size — it falls through to the exact-size and digest checks and
    is rejected like any other truncated/wrong file."""
    return str(os.getenv("BETTERFINGERS_ALLOW_TINY_MODELS", "")).strip().lower() in (
        "1", "true", "yes", "on",
    )


def _verify_cache_path():
    return os.path.join(get_models_dir(), _VERIFY_CACHE_NAME)


def _load_verify_cache():
    try:
        with open(_verify_cache_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_verify_cache(cache):
    path = _verify_cache_path()
    try:
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(cache, handle)
        os.replace(tmp, path)
    except OSError:
        pass


def _file_signature(path):
    """(size, mtime_ns) identity used to decide whether a rehash is needed."""
    st = os.stat(path)
    return int(st.st_size), int(st.st_mtime_ns)


def _drop_verify_cache_entry(path):
    cache = _load_verify_cache()
    if cache.pop(os.path.abspath(path), None) is not None:
        _save_verify_cache(cache)


def _cached_digest_ok(path, expected_sha256):
    """Verify ``path`` against ``expected_sha256`` without rehashing multi-GB
    files on every call.

    The verified verdict is cached keyed by (path, size, mtime, expected digest);
    the expensive SHA-256 pass only runs when any of those change. Returns
    ``(matched, from_cache)``.
    """
    if not expected_sha256:
        return True, False
    try:
        size, mtime = _file_signature(path)
    except OSError:
        return False, False
    key = os.path.abspath(path)
    cache = _load_verify_cache()
    entry = cache.get(key)
    if (
        isinstance(entry, dict)
        and entry.get("size") == size
        and entry.get("mtime") == mtime
        and hmac_compare(entry.get("expected_digest"), expected_sha256)
    ):
        return bool(entry.get("verified_ok")), True

    actual = sha256_file(path)
    ok = hmac_compare(actual, expected_sha256)
    cache[key] = {
        "size": size,
        "mtime": mtime,
        "digest": actual,
        "expected_digest": str(expected_sha256).lower(),
        "verified_ok": ok,
        "ts": time.time(),
    }
    _save_verify_cache(cache)
    return ok, False


def _quarantine_artifact(path):
    """Move a digest-mismatched artifact aside to ``<file>.corrupt`` so it can
    never be loaded/executed again, and drop its cache entry + sidecar."""
    corrupt = f"{path}.corrupt"
    try:
        if os.path.exists(corrupt):
            os.remove(corrupt)
        os.replace(path, corrupt)
    except OSError as exc:
        logging.error("Failed to quarantine %s: %s", path, exc)
        return ""
    _drop_verify_cache_entry(path)
    sidecar = f"{path}.sha256"
    if os.path.exists(sidecar):
        try:
            os.remove(sidecar)
        except OSError:
            pass
    return corrupt


def verify_installed_model(model_id, quarantine=True):
    """Rehash an already-installed GGUF and compare it to the catalog digest.

    Cache-aware (see :func:`_cached_digest_ok`) so it is cheap to call on every
    launch. On a mismatch the file is quarantined to ``<file>.corrupt`` (unless
    ``quarantine`` is False) rather than silently trusted (§11).
    """
    path = get_model_path(model_id)
    info = AVAILABLE_MODELS.get(model_id, {})
    result = {"model_id": model_id, "path": path, "ok": False, "reason": "", "from_cache": False}
    if not os.path.exists(path):
        result["reason"] = "missing"
        return result
    if not os.access(path, os.R_OK):
        result["reason"] = "not_readable"
        return result
    expected = info.get("sha256")
    if not expected:
        # Nothing pinned to compare against (e.g. a dev-injected model id).
        result["ok"] = True
        result["reason"] = "no_pinned_digest"
        return result
    ok, from_cache = _cached_digest_ok(path, expected)
    result["from_cache"] = from_cache
    if ok:
        result["ok"] = True
        result["reason"] = "verified"
        return result
    result["reason"] = "digest_mismatch"
    if quarantine:
        result["quarantined"] = _quarantine_artifact(path)
        logging.error(
            "Model %s failed SHA-256 verification and was quarantined to %s",
            model_id,
            result.get("quarantined") or "<failed>",
        )
    return result


def get_server_digest_sidecar(server_path=None):
    return f"{server_path or get_server_path()}.sha256"


def record_runtime_digest(server_path=None):
    """Pin a freshly-installed llama-server binary's digest (trust-on-first-use).

    The release manifest only pins the *archive*; the extracted executable has
    no upstream digest. Recording it here lets :func:`verify_installed_runtime`
    later detect a binary that was swapped underneath us with the same filename.
    """
    server_path = server_path or get_server_path()
    try:
        digest = sha256_file(server_path)
    except OSError:
        return ""
    try:
        with open(get_server_digest_sidecar(server_path), "w", encoding="utf-8") as handle:
            handle.write(f"{digest}  {os.path.basename(server_path)}\n")
    except OSError:
        pass
    # Seed the verified-state cache so the first verify is already a cheap hit.
    _cached_digest_ok(server_path, digest)
    return digest


def _read_recorded_digest(sidecar_path):
    try:
        with open(sidecar_path, "r", encoding="utf-8") as handle:
            fields = handle.read().strip().split()
    except OSError:
        return ""
    return fields[0].lower() if fields else ""


def verify_installed_runtime(server_path=None, quarantine=True):
    """Rehash the managed llama-server binary and compare it to the digest we
    recorded at install time. On mismatch the binary is quarantined so it is
    never executed (§11). Binaries with no recorded digest (dev/repo-local or an
    ``BETTERFINGERS_LLAMA_SERVER`` override) are left alone — nothing to compare.
    """
    server_path = server_path or get_server_path()
    result = {"path": server_path, "ok": False, "reason": "", "from_cache": False}
    if not os.path.exists(server_path):
        result["reason"] = "missing"
        return result
    expected = _read_recorded_digest(get_server_digest_sidecar(server_path))
    if not expected:
        result["ok"] = True
        result["reason"] = "no_recorded_digest"
        return result
    ok, from_cache = _cached_digest_ok(server_path, expected)
    result["from_cache"] = from_cache
    if ok:
        result["ok"] = True
        result["reason"] = "verified"
        return result
    result["reason"] = "digest_mismatch"
    if quarantine:
        result["quarantined"] = _quarantine_artifact(server_path)
        logging.error(
            "llama-server binary at %s failed integrity check and was quarantined to %s",
            server_path,
            result.get("quarantined") or "<failed>",
        )
    return result


# --- Safe archive extraction (supply-chain gate, §11) -------------------------
# The runtime archives are fetched over the network and their contents are then
# *executed*. Extraction is therefore a trust boundary: a malicious/corrupt
# archive must not be able to write outside the target dir (absolute paths,
# ``..`` traversal, escaping symlinks) or leave a half-written runtime in place.

class ArchiveValidationError(RuntimeError):
    """Raised when an archive member fails a safety check during extraction."""


def _safe_member_basename(name):
    """Validate an archive member path and return the flat basename to use.

    Rejects absolute paths and ``..`` traversal; the runtime archives are always
    extracted flat, so any directory component that tries to escape is refused
    rather than silently stripped.
    """
    raw = str(name or "")
    if not raw:
        return ""
    if raw.startswith(("/", "\\")) or os.path.isabs(raw) or (len(raw) > 1 and raw[1] == ":"):
        raise ArchiveValidationError(f"absolute member path rejected: {raw}")
    # posixpath, NOT os.path: archive member names always use "/" once the
    # backslash replace above runs, but on Windows os.path.normpath converts
    # them back to "\", so splitting on "/" produced one chunk and the ".."
    # check silently never matched (traversal members were flattened instead
    # of rejected). posixpath keeps "/" semantics on every platform.
    norm = posixpath.normpath(raw.replace("\\", "/"))
    parts = norm.split("/")
    if posixpath.isabs(norm) or ".." in parts:
        raise ArchiveValidationError(f"path traversal rejected: {raw}")
    return posixpath.basename(norm)


def _safe_symlink_basename(link_name, link_target, staging_root):
    """Validate a symlink member and return the flat target basename.

    A soname symlink (e.g. ``libllama.so.0 -> libllama.so.0.0.7870``) is fine as
    long as its resolved target stays inside the staging dir. Absolute targets or
    ``..`` targets that escape the extraction root are rejected.
    """
    target = str(link_target or "")
    if not target:
        raise ArchiveValidationError(f"empty symlink target for {link_name}")
    if target.startswith(("/", "\\")) or os.path.isabs(target):
        raise ArchiveValidationError(f"absolute symlink target rejected: {link_name} -> {target}")
    resolved = os.path.normpath(os.path.join(staging_root, target.replace("\\", "/")))
    root = os.path.normpath(staging_root)
    if resolved != root and not resolved.startswith(root + os.sep):
        raise ArchiveValidationError(f"escaping symlink target rejected: {link_name} -> {target}")
    return os.path.basename(target)


def _stage_zip(archive_path, staging_dir):
    with zipfile.ZipFile(archive_path, "r") as archive:
        for member in archive.infolist():
            mode = (member.external_attr >> 16) & 0o170000
            base = _safe_member_basename(member.filename)
            if not base:
                continue
            if mode == 0o120000:  # symlink stored in a zip (unix)
                link_target = archive.read(member).decode("utf-8", "replace")
                target_base = _safe_symlink_basename(base, link_target, staging_dir)
                _safe_symlink(staging_dir, base, target_base, replace=True, require_target=False)
                continue
            if member.filename.endswith("/"):
                continue
            with archive.open(member) as src, open(os.path.join(staging_dir, base), "wb") as dst:
                shutil.copyfileobj(src, dst)


def _stage_tar(archive_path, staging_dir):
    import tarfile

    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            base = _safe_member_basename(member.name)
            if not base:
                continue
            if member.issym() or member.islnk():
                target_base = _safe_symlink_basename(base, member.linkname, staging_dir)
                _safe_symlink(staging_dir, base, target_base, replace=True, require_target=False)
                continue
            if not member.isfile():
                continue
            src = archive.extractfile(member)
            if src is None:
                continue
            with src, open(os.path.join(staging_dir, base), "wb") as dst:
                shutil.copyfileobj(src, dst)


def safe_extract_runtime_archive(archive_path, dest_dir, archive_name, required_members=()):
    """Extract a runtime archive safely and promote it only once validated.

    The archive is expanded into a private staging dir first; every member is
    checked for absolute paths, ``..`` traversal and escaping symlinks. After
    extraction the expected-member allowlist must be satisfied (e.g. the
    ``llama-server`` executable is present) before anything is promoted. Only
    then are the files moved into ``dest_dir`` (backing up any file they
    replace) and the executable chmod'd. Any failure raises and rolls back,
    leaving the previously-installed runtime untouched.
    """
    name = str(archive_name or "")
    os.makedirs(dest_dir, exist_ok=True)
    staging_dir = tempfile.mkdtemp(prefix=".staging-runtime-", dir=dest_dir)
    promoted = []
    backups = {}
    try:
        if name.endswith(".zip"):
            _stage_zip(archive_path, staging_dir)
        elif name.endswith(".tar.gz") or name.endswith(".tgz"):
            _stage_tar(archive_path, staging_dir)
        else:
            raise ArchiveValidationError(f"unsupported runtime archive: {name}")

        staged = set(os.listdir(staging_dir))
        missing = [m for m in required_members if m not in staged]
        if missing:
            raise ArchiveValidationError(
                f"runtime archive {name} missing expected member(s): {', '.join(sorted(missing))}"
            )

        # Promote only after validation. Back up replaced files so a mid-promote
        # failure can be rolled back to the previously-installed runtime.
        backup_dir = tempfile.mkdtemp(prefix=".backup-runtime-", dir=dest_dir)
        for entry in sorted(staged):
            final_path = os.path.join(dest_dir, entry)
            staged_path = os.path.join(staging_dir, entry)
            if os.path.lexists(final_path):
                backup_path = os.path.join(backup_dir, entry)
                os.replace(final_path, backup_path)
                backups[final_path] = backup_path
            os.replace(staged_path, final_path)
            promoted.append(final_path)

        # chmod +x only after the executable has landed and validated.
        for member in required_members:
            candidate = os.path.join(dest_dir, member)
            if os.path.isfile(candidate) and not member.lower().endswith((".dll", ".so", ".txt")):
                try:
                    os.chmod(candidate, 0o755)
                except OSError:
                    pass

        shutil.rmtree(backup_dir, ignore_errors=True)
        return {"ok": True, "dest_dir": dest_dir, "members": sorted(staged)}
    except Exception:
        # Roll back any files we already promoted before the failure.
        for final_path in promoted:
            try:
                if final_path in backups:
                    os.replace(backups[final_path], final_path)
                elif os.path.lexists(final_path):
                    os.remove(final_path)
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def download_file(url, dest_path, desc="File", progress_callback=None, progress_key="", resume=True,
                  expected_sha256=None):
    """Download a file safely.

    The transfer writes to ``dest_path + ".part"`` and atomically replaces the final
    path only after the response completes. If a previous partial exists and the
    server supports byte ranges, the download resumes instead of restarting.
    When ``expected_sha256`` is given, the completed file must match it exactly
    or it is deleted and the download fails (§11).
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
        # Cryptographic verification before promotion (§11): size says the
        # transfer finished; only the digest says it's the artifact we pinned.
        if expected_sha256:
            _emit_progress(
                progress_callback,
                {
                    "key": key,
                    "status": "verifying",
                    "desc": desc,
                    "percent": 100.0,
                    "downloaded_bytes": int(_file_size(part_path)),
                    "total_bytes": int(total_size),
                    "message": f"Verifying {desc} checksum...",
                },
            )
            actual_sha256 = sha256_file(part_path)
            if not hmac_compare(actual_sha256, expected_sha256):
                try:
                    os.remove(part_path)
                except OSError:
                    pass
                raise IOError(
                    f"checksum mismatch for {desc}: expected {expected_sha256}, got {actual_sha256}. "
                    "The download was discarded."
                )
            # Sidecar digest for diagnostics: what was verified, when.
            try:
                with open(dest_path + ".sha256", "w", encoding="utf-8") as digest_file:
                    digest_file.write(f"{actual_sha256}  {os.path.basename(dest_path)}\n")
            except OSError:
                pass
        else:
            logging.warning("No pinned checksum for %s — installing UNVERIFIED artifact from %s", desc, url)
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
                expected_sha256=model_info.get("sha256"),
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

    # Windows and Linux both have a known-good prebuilt llama.cpp archive to fetch
    # (win-cuda / ubuntu-vulkan). macOS has no prebuilt binary here, so rather than
    # download a Linux archive that can't run, tell the user to provide their own.
    if server_needs_install and sys.platform == "darwin":
        message = (
            "llama-server binary not found. On macOS, build it yourself or set "
            "BETTERFINGERS_LLAMA_SERVER to the path of an existing llama-server."
        )
        report({"key": target_model_id, "status": "error", "percent": 0.0, "message": message})
        return {"ok": False, "model_id": target_model_id, "message": message}

    if server_needs_install:
        # Pick CUDA vs Vulkan (vendor-neutral / CPU fallback) for THIS machine —
        # an AMD/Intel Windows PC must not get the CUDA-only build (§ item 2).
        spec = resolve_runtime_spec()
        logging.info("llama-server not found or outdated. Downloading %s runtime...", spec["backend"])

        bin_archive = os.path.join(models_dir, spec["archive_name"])
        try:
            download_file(
                spec["bin_url"],
                bin_archive,
                "llama-server",
                progress_callback=report,
                progress_key=f"{target_model_id}:server",
                expected_sha256=runtime_artifact_sha256(spec["bin_url"]),
            )
            # Validated staging + atomic promote: a malicious/corrupt archive
            # can't escape models_dir or leave a half-written runtime, and the
            # executable is only chmod'd after the expected member is present.
            safe_extract_runtime_archive(
                bin_archive,
                models_dir,
                spec["archive_name"],
                required_members=[spec["filename"]],
            )
            if not spec["archive_name"].endswith(".zip"):
                repair_linux_runtime_links(os.path.dirname(os.path.abspath(server_path)))
            # Pin the extracted binary's digest so a later swap is detected (§11).
            record_runtime_digest(server_path)
        finally:
            if os.path.exists(bin_archive):
                os.remove(bin_archive)

        if spec["cuda_lib_url"] and spec["cuda_archive_name"]:
            cuda_archive = os.path.join(models_dir, spec["cuda_archive_name"])
            try:
                download_file(
                    spec["cuda_lib_url"],
                    cuda_archive,
                    "CUDA Runtime",
                    progress_callback=report,
                    progress_key=f"{target_model_id}:cuda",
                    expected_sha256=runtime_artifact_sha256(spec["cuda_lib_url"]),
                )
                safe_extract_runtime_archive(cuda_archive, models_dir, spec["cuda_archive_name"])
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
