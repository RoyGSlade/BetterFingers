"""Local bundled speech artifacts: locating and integrity only; never loads STT."""
from dataclasses import dataclass
import hashlib
from importlib import resources
import json
import os
from pathlib import Path
import re
import sys
import threading

_REQUIRED_FILES = frozenset({"config.json", "model.bin", "tokenizer.json", "vocabulary.txt"})
_hash_cache = {}
_cache_lock = threading.RLock()


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    code: str | None = None
    path: str | None = None


def load_manifest(manifest=None):
    """Read packaged metadata, or validate an explicit build/test manifest."""
    if manifest is None:
        manifest = json.loads(resources.files("backend.stt").joinpath(
            "bundled_manifest.json").read_text(encoding="utf-8"))
    elif isinstance(manifest, (str, Path)):
        manifest = json.loads(Path(manifest).read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise ValueError("Unsupported manifest schema")
    for key in ("model_id", "model_size", "license", "source_url"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise ValueError("Missing manifest identity")
    if manifest["model_id"] != "Systran/faster-whisper-base.en" or manifest["model_size"] != "base.en":
        raise ValueError("Unsupported bundled model")
    if not isinstance(manifest.get("revision"), str) or not re.fullmatch(r"[0-9a-f]{40}", manifest["revision"]):
        raise ValueError("Unpinned revision")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != len(_REQUIRED_FILES):
        raise ValueError("Incomplete file manifest")
    seen = set()
    for row in files:
        if not isinstance(row, dict):
            raise ValueError("Invalid file entry")
        name = row.get("path")
        if not isinstance(name, str) or name not in _REQUIRED_FILES or name in seen:
            raise ValueError("Invalid or duplicate file path")
        seen.add(name)
        if type(row.get("size")) is not int or row["size"] < 1:
            raise ValueError("Invalid file size")
        if not isinstance(row.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            raise ValueError("Invalid SHA-256")
    return manifest


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _signature(path):
    stat = path.stat()
    return (str(path.absolute()), stat.st_mtime_ns, stat.st_size)


def verify_bundled_model(directory, *, manifest=None):
    """Check bytes with a process cache keyed by path, mtime_ns and size.

    Every call stats each file. Hashes are reused only while those attributes
    match. Like any metadata cache, this does not detect malicious replacement
    that preserves size and mtime; installer files must retain OS protection.
    """
    try:
        metadata = load_manifest(manifest)
    except (OSError, ValueError, TypeError, AttributeError):
        return VerifyResult(False, "manifest_invalid")
    directory = Path(directory)
    for row in metadata["files"]:
        path = directory / row["path"]
        try:
            signature = _signature(path)
            if not path.is_file():
                return VerifyResult(False, "missing_file", row["path"])
            if signature[2] != row["size"]:
                return VerifyResult(False, "size_mismatch", row["path"])
            with _cache_lock:
                cached = _hash_cache.get(signature[0])
                if cached and cached[0] == signature:
                    digest = cached[1]
                else:
                    digest = _sha256(path)
                    if _signature(path) != signature:
                        return VerifyResult(False, "hash_mismatch", row["path"])
                    _hash_cache[signature[0]] = (signature, digest)
            if digest != row["sha256"]:
                return VerifyResult(False, "hash_mismatch", row["path"])
        except OSError:
            return VerifyResult(False, "missing_file", row["path"])
    return VerifyResult(True)


def bundled_model_dir(model_size):
    """Locate a candidate, without granting readiness or verifying its bytes.

    Override names the *root* containing base.en. Frozen builds use
    _MEIPASS/bundled_models/base.en, staged with PyInstaller --add-data.
    Separate app resources may also live beside the sidecar or in Electron's
    resources/bundled_models. Development has no implicit HF-cache fallback.
    """
    if model_size != "base.en":
        return None
    override = os.environ.get("BETTERFINGERS_BUNDLED_MODELS_DIR")
    if override:
        candidate = Path(override) / "base.en"
        return candidate if candidate.is_dir() else None
    if not getattr(sys, "frozen", False):
        return None
    roots = []
    if getattr(sys, "_MEIPASS", None):
        roots.append(Path(sys._MEIPASS) / "bundled_models")
    sidecar_dir = Path(sys.executable).parent
    roots.extend((sidecar_dir / "bundled_models", sidecar_dir.parent.parent / "bundled_models"))
    return next((root / "base.en" for root in roots if (root / "base.en").is_dir()), None)
