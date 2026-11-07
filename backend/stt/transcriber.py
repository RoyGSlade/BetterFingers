import gc
import logging
import os
import re
import threading
import time
import weakref
from dataclasses import dataclass, field

import numpy as np
from faster_whisper import WhisperModel
from huggingface_hub import scan_cache_dir
from huggingface_hub.constants import HF_HUB_CACHE

from backend.domain.contracts import TimedSegment, TranscriptionResult
from backend.privacy.log_redaction import redact_user_text
from backend.stt import bundled_models
from backend.stt.text_formatter import TextFormatter
from backend.stt.cuda_runtime import ensure_cuda_libraries_on_path
from backend.config.utils import load_profile

try:
    import psutil
except Exception:  # pragma: no cover - psutil is a hard dependency in practice
    psutil = None

# --- Hallucination Guard ---
# Whisper sometimes "hallucinates" repeated short phrases during silence or
# noise.  The patterns below catch the most common ones.
_HALLUCINATION_PHRASES = {
    "thank you", "thanks for watching", "subscribe",
    "please subscribe", "thanks for listening", "bye",
    "you", "the end",
}

_SENTENCE_SPLIT_RE = re.compile(r'[.!?]+')

# Static, conservative resident-MB estimates for admission control (faster-
# whisper/CTranslate2 footprint, int8 CPU or float16 GPU, overhead included).
# A custom/local model_size (a filesystem path, not a catalog name) falls
# back to _DEFAULT_WHISPER_RUNTIME_MB rather than under-estimating to 0.
_WHISPER_RUNTIME_MB_ESTIMATES = {
    "tiny.en": 150,
    "base.en": 300,
    "small.en": 700,
    "medium.en": 1800,
    "large-v3": 3500,
    "distil-medium.en": 900,
    "distil-large-v3": 1700,
}
_DEFAULT_WHISPER_RUNTIME_MB = 500

# Stable, privacy-safe runtime diagnostics.  Keep this classifier deliberately
# narrow: an arbitrary CUDA/inference exception must not cause a CPU reload or
# leak its payload into logs/runtime errors.
CUDA_RUNTIME_MISSING_CODE = "cuda_runtime_missing"
_CUDA_RUNTIME_LIBRARY_RE = re.compile(r"(?:cublas|cudnn|cudart)", re.IGNORECASE)
_CUDA_RUNTIME_LOAD_RE = re.compile(
    r"(?:missing|not found|(?:unable\s+)?to\s+load|cannot\s+load|could not\s+load|failed\s+to\s+load|load(?:ing)?\s+failed|dll)",
    re.IGNORECASE,
)


# Typed local-only load failures: the model is absent / cannot be loaded from disk.
# They clear only by a successful load, never by waiting.
_ACQUISITION_FAILURE_CODES = frozenset({"model_missing", "verification_failed"})


class ModelUnavailableError(FileNotFoundError):
    """A local-only load cannot proceed.

    ``code`` is fixed vocabulary (``model_missing`` / ``verification_failed``).
    Messages never carry a filesystem path: the bundle lives under the user's
    profile and its absolute path must not reach logs or status.
    """

    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _ModelSource:
    """Where the next Whisper load comes from, decided once by ``_resolve_model_source``."""

    # What WhisperModel receives: the model NAME, or a verified bundle DIRECTORY.
    # repr=False keeps the absolute bundle path out of any accidental log of this record.
    model: str = field(repr=False)
    local_files_only: bool
    cached: bool               # usable from disk right now (verified bundle, Hub cache or local dir)
    will_download: bool        # an explicit download would really fetch bytes
    bundled: bool = False
    failure_code: str | None = None  # a bundle exists but may not be used; never falls back to the network


def classify_cuda_runtime_error(exc):
    """Return a stable code only for the known CUDA DLL-load family."""
    text = str(exc or "")
    if _CUDA_RUNTIME_LIBRARY_RE.search(text) and _CUDA_RUNTIME_LOAD_RE.search(text):
        return CUDA_RUNTIME_MISSING_CODE
    return None


# Measured on a 12-core Zen 5 (Ryzen AI 9 HX 370), CPU int8: 8 threads is the knee; 16+ regress.
STT_CPU_THREAD_CAP = 8
_STT_CPU_THREADS_ENV = "BETTERFINGERS_STT_CPU_THREADS"

# Process-wide memo: once a CUDA decode has failed in this process, never try CUDA
# again until restart. A second CUDA decode after a failed cuBLAS load can hang
# inside CTranslate2 (observed on an RTX 5070 laptop without cublas64_12.dll, while
# holding the model lock), and every retry costs a wasted model construction.
# Keyed by the WhisperModel class (weakly): one entry per process in production,
# while each test's fake class starts clean. Value: (fallback_reason, fallback_code).
_cuda_unavailable = weakref.WeakKeyDictionary()


def _known_cuda_failure():
    return _cuda_unavailable.get(WhisperModel)


def _remember_cuda_unavailable(reason, code):
    _cuda_unavailable.setdefault(WhisperModel, (reason, code))


def _detect_physical_cores():
    """Physical core count; falls back to half the logical count if psutil can't say."""
    try:
        count = psutil.cpu_count(logical=False) if psutil is not None else None
    except Exception:
        count = None
    return int(count or max(1, (os.cpu_count() or 4) // 2))


def _sample_cpu_load_percent():
    """Short system-wide CPU load sample; any psutil failure counts as idle (0)."""
    if psutil is None:
        return 0.0
    try:
        return float(psutil.cpu_percent(interval=0.1))
    except Exception:
        return 0.0


def choose_stt_cpu_threads(physical_cores=None, cpu_load_percent=None, env=None):
    """Pick the CTranslate2 CPU thread count for a Whisper model about to be built.

    faster-whisper's ``cpu_threads=0`` means "4"; the app never set it. CTranslate2 fixes
    the count at construction, so this is evaluated on every CPU model construction. Never
    above the physical core count or STT_CPU_THREAD_CAP, shrinks by the cores that are
    already busy, and keeps at least 2 threads when there are 2 or more cores.
    ``BETTERFINGERS_STT_CPU_THREADS`` (int > 0) is a diagnostics override with no UI.
    """
    env = os.environ if env is None else env
    try:
        override = int(str(env.get(_STT_CPU_THREADS_ENV, "")).strip())
    except (TypeError, ValueError):
        override = 0
    if override > 0:
        return override

    physical = max(1, int(physical_cores or _detect_physical_cores()))
    load = _sample_cpu_load_percent() if cpu_load_percent is None else cpu_load_percent
    try:
        load = float(load)
    except (TypeError, ValueError):
        load = 0.0
    load = min(100.0, max(0.0, load))
    busy = round(physical * load / 100)
    return max(min(2, physical), min(STT_CPU_THREAD_CAP, physical - busy))


def _select_cpu_threads():
    """Run the thread policy for one CPU model load and log it once."""
    physical = _detect_physical_cores()
    load = _sample_cpu_load_percent()
    threads = choose_stt_cpu_threads(physical_cores=physical, cpu_load_percent=load)
    logging.info("Whisper CPU threads: %d (physical=%d, load=%.0f%%)", threads, physical, load)
    return threads


def _estimate_whisper_runtime_mb(model_size):
    return _WHISPER_RUNTIME_MB_ESTIMATES.get((model_size or "").strip(), _DEFAULT_WHISPER_RUNTIME_MB)


def _is_hallucination(text: str) -> bool:
    """Return *True* when *text* looks like a Whisper hallucination loop."""
    clean = text.strip()
    if not clean:
        return False
    sentences = [s.strip().rstrip(".").lower()
                 for s in _SENTENCE_SPLIT_RE.split(clean) if s.strip()]
    if not sentences:
        return False
    # Single known hallucination phrase
    if len(sentences) == 1 and sentences[0] in _HALLUCINATION_PHRASES:
        return True
    # Same phrase repeated ≥ 3 times
    if len(sentences) >= 3 and len(set(sentences)) == 1:
        return True
    # Majority of sentences are a known hallucination phrase
    if len(sentences) >= 2:
        counts = {}
        for s in sentences:
            counts[s] = counts.get(s, 0) + 1
        most_common = max(counts, key=counts.get)
        if most_common in _HALLUCINATION_PHRASES and counts[most_common] >= len(sentences) * 0.6:
            return True
    return False


def _optional_float(value):
    return None if value is None else float(value)

SUPPORTED_MODEL_SIZES = (
    "tiny.en",
    "base.en",
    "small.en",
    "medium.en",
    "large-v3",
    "distil-medium.en",
    "distil-large-v3",
)
_whisper_download_state_lock = threading.Lock()
_whisper_download_state = {}


def _set_whisper_download_state(model_size, payload):
    key = str(model_size or "").strip()
    if not key:
        return
    with _whisper_download_state_lock:
        _whisper_download_state[key] = dict(payload or {})


def get_whisper_download_state(model_size):
    key = str(model_size or "").strip()
    with _whisper_download_state_lock:
        row = _whisper_download_state.get(key, {})
    return dict(row)


def _emit_download_progress(progress_callback, payload):
    if not callable(progress_callback):
        return
    try:
        progress_callback(dict(payload or {}))
    except Exception:
        pass


def _repo_id_for_model(model_size):
    size = str(model_size or "").strip()
    if not size:
        return None
    if "/" in size:
        return size
    if size.startswith("distil"):
        # Distil-Whisper repositories retain the ``whisper`` segment in their
        # Hub id (for example, ``faster-distil-whisper-large-v3``). Without
        # it, cache discovery reports an installed model as missing and the
        # loader asks Hugging Face for a repository that does not exist.
        return f"Systran/faster-distil-whisper-{size.removeprefix('distil-')}"
    return f"Systran/faster-whisper-{size}"


def _bundled_model_ready(model_size):
    """True when an installer-bundled model for this size is present AND verifies.

    Cheap after the first call (bundled_models caches hashes per process). A
    bundle that fails verification is not "installed": it is never used.
    """
    try:
        directory = bundled_models.bundled_model_dir(str(model_size or "").strip())
        return directory is not None and bundled_models.verify_bundled_model(directory).ok
    except Exception:
        return False


def _apply_bundled_inventory(rows):
    """Count a verified bundled base.en as installed (it needs no Hub cache entry)."""
    row = rows.get("base.en")
    if row is None or not _bundled_model_ready("base.en"):
        return
    row["bundled"] = True
    if not row["installed"]:
        row["installed"] = True
        try:
            row["size_bytes"] = sum(int(entry["size"]) for entry in bundled_models.load_manifest()["files"])
        except Exception:
            row["size_bytes"] = 0


def list_cached_models(download_root=None):
    cache_dir = str(download_root or HF_HUB_CACHE or "").strip() or HF_HUB_CACHE
    rows = {
        name: {
            "model_size": name,
            "repo_id": _repo_id_for_model(name),
            "installed": False,
            "size_bytes": 0,
            "bundled": False,
        }
        for name in SUPPORTED_MODEL_SIZES
    }

    try:
        cache_info = scan_cache_dir(cache_dir=cache_dir)
    except TypeError:
        try:
            cache_info = scan_cache_dir()
        except Exception:
            _apply_bundled_inventory(rows)
            return [rows[name] for name in SUPPORTED_MODEL_SIZES]
    except Exception:
        _apply_bundled_inventory(rows)
        return [rows[name] for name in SUPPORTED_MODEL_SIZES]

    for repo in getattr(cache_info, "repos", []) or []:
        repo_id = str(getattr(repo, "repo_id", "") or "").strip()
        if not repo_id:
            continue
        size_name = ""
        if repo_id.startswith("Systran/faster-whisper-"):
            size_name = repo_id.split("Systran/faster-whisper-", 1)[1].strip()
        elif repo_id.startswith("Systran/faster-distil-whisper-"):
            suffix = repo_id.split("Systran/faster-distil-whisper-", 1)[1].strip()
            size_name = f"distil-{suffix}" if suffix else ""
        if not size_name:
            continue
        if size_name not in rows:
            rows[size_name] = {
                "model_size": size_name,
                "repo_id": repo_id,
                "installed": False,
                "size_bytes": 0,
                "bundled": False,
            }
        size_on_disk = int(getattr(repo, "size_on_disk", 0) or 0)
        rows[size_name]["installed"] = size_on_disk > 0
        rows[size_name]["size_bytes"] = size_on_disk

    _apply_bundled_inventory(rows)
    ordered = [rows[name] for name in SUPPORTED_MODEL_SIZES]
    extras = sorted((name for name in rows.keys() if name not in SUPPORTED_MODEL_SIZES))
    ordered.extend(rows[name] for name in extras)
    return ordered


def remove_cached_model(model_size, download_root=None):
    selected = str(model_size or "").strip()
    if not selected:
        return {"ok": False, "message": "No Whisper model selected.", "freed_bytes": 0}

    repo_id = _repo_id_for_model(selected)
    if not repo_id:
        return {"ok": False, "message": f"Unsupported Whisper model '{selected}'.", "freed_bytes": 0}

    cache_dir = str(download_root or HF_HUB_CACHE or "").strip() or HF_HUB_CACHE
    try:
        cache_info = scan_cache_dir(cache_dir=cache_dir)
    except TypeError:
        try:
            cache_info = scan_cache_dir()
        except Exception as exc:
            return {"ok": False, "message": f"Failed to scan cache: {exc}", "freed_bytes": 0}
    except Exception as exc:
        return {"ok": False, "message": f"Failed to scan cache: {exc}", "freed_bytes": 0}

    target_repo = None
    for repo in getattr(cache_info, "repos", []) or []:
        if str(getattr(repo, "repo_id", "") or "").strip() == repo_id:
            target_repo = repo
            break
    if target_repo is None:
        if _bundled_model_ready(selected):
            return {
                "ok": False,
                "message": f"Whisper '{selected}' ships with BetterFingers and cannot be removed.",
                "freed_bytes": 0,
            }
        return {"ok": False, "message": f"Whisper '{selected}' is not installed.", "freed_bytes": 0}

    revisions = [str(getattr(rev, "commit_hash", "") or "").strip() for rev in (getattr(target_repo, "revisions", []) or [])]
    revisions = [rev for rev in revisions if rev]
    if not revisions:
        return {"ok": False, "message": f"No cached revisions found for '{selected}'.", "freed_bytes": 0}

    try:
        strategy = cache_info.delete_revisions(*revisions)
        freed_bytes = int(getattr(strategy, "expected_freed_size", 0) or 0)
        strategy.execute()
    except Exception as exc:
        return {"ok": False, "message": f"Failed uninstalling '{selected}': {exc}", "freed_bytes": 0}

    return {
        "ok": True,
        "message": f"Removed Whisper cache for '{selected}'.",
        "freed_bytes": freed_bytes,
    }


def download_whisper_model(model_size, prefer_gpu=True, download_root=None, progress_callback=None):
    selected = str(model_size or "").strip()
    if selected not in SUPPORTED_MODEL_SIZES:
        return {"ok": False, "message": f"Unsupported Whisper model: {selected}", "model_size": selected}

    if _bundled_model_ready(selected):
        # The installer ships this model and it verifies: nothing to fetch, and a
        # "download" must never touch the network for it.
        payload = {
            "model_size": selected,
            "status": "already_installed",
            "percent": 100.0,
            "message": f"Whisper '{selected}' is already installed.",
        }
        _set_whisper_download_state(selected, payload)
        _emit_download_progress(progress_callback, payload)
        return {"ok": True, "message": payload["message"], "model_size": selected}

    if download_root:
        cache_rows = list_cached_models(download_root=download_root)
        for row in cache_rows:
            if str(row.get("model_size", "")).strip() == selected and bool(row.get("installed", False)):
                payload = {
                    "model_size": selected,
                    "status": "already_installed",
                    "percent": 100.0,
                    "message": f"Whisper '{selected}' is already installed.",
                }
                _set_whisper_download_state(selected, payload)
                _emit_download_progress(progress_callback, payload)
                return {"ok": True, "message": payload["message"], "model_size": selected}

    probe = None
    started_at = time.time()
    try:
        payload = {
            "model_size": selected,
            "status": "starting",
            "percent": 0.0,
            "message": f"Starting Whisper '{selected}' download...",
        }
        _set_whisper_download_state(selected, payload)
        _emit_download_progress(progress_callback, payload)

        probe = Transcriber(profile_name="Default", preload=False)
        probe.model_size = selected
        probe.prefer_gpu = bool(prefer_gpu)
        if download_root:
            probe.download_root = str(download_root)
            os.makedirs(probe.download_root, exist_ok=True)

        payload = {
            "model_size": selected,
            "status": "downloading",
            "percent": 20.0,
            "message": f"Downloading Whisper '{selected}'. This can take a few minutes.",
        }
        _set_whisper_download_state(selected, payload)
        _emit_download_progress(progress_callback, payload)

        ok = probe.ensure_loaded(allow_download=True)
        elapsed = max(0.0, time.time() - started_at)
        if not ok:
            payload = {
                "model_size": selected,
                "status": "error",
                "percent": 0.0,
                "message": f"Failed to load Whisper '{selected}'.",
                "elapsed_sec": elapsed,
            }
            _set_whisper_download_state(selected, payload)
            _emit_download_progress(progress_callback, payload)
            return {"ok": False, "message": payload["message"], "model_size": selected, "elapsed_sec": elapsed}

        payload = {
            "model_size": selected,
            "status": "complete",
            "percent": 100.0,
            "message": f"Whisper '{selected}' download complete.",
            "elapsed_sec": elapsed,
        }
        _set_whisper_download_state(selected, payload)
        _emit_download_progress(progress_callback, payload)
        return {"ok": True, "message": payload["message"], "model_size": selected, "elapsed_sec": elapsed}
    except Exception as exc:
        payload = {
            "model_size": selected,
            "status": "error",
            "percent": 0.0,
            "message": f"Whisper download failed: {exc}",
        }
        _set_whisper_download_state(selected, payload)
        _emit_download_progress(progress_callback, payload)
        return {"ok": False, "message": payload["message"], "model_size": selected}
    finally:
        if probe is not None:
            try:
                probe.unload()
            except Exception:
                pass


class Transcriber:
    def __init__(self, profile_name="Default", preload=True):
        self.profile_name = profile_name
        self.config = {}

        self.model = None
        self.model_size = "base.en"
        self.prefer_gpu = True
        # Honest device-selection state (set in _load_model() right after the
        # WhisperModel that actually loaded is constructed): what the model is
        # ACTUALLY running on, as opposed to self.prefer_gpu which is only the
        # user's preference. None while unloaded.
        self.active_device = None          # "cuda" | "cpu" | None
        self.active_compute_type = None    # "float16" | "int8" | None
        self.active_cpu_threads = None     # int on a CPU load, None on CUDA / unloaded
        self.device_fallback_reason = None  # short string, or None if no fallback happened
        self.device_fallback_code = None   # stable privacy-safe code, if fallback happened
        self.download_root = HF_HUB_CACHE
        os.makedirs(self.download_root, exist_ok=True)

        self._model_lock = threading.RLock()
        # Never hold this short publication lock during model/cache/engine work.
        self._status_lock = threading.Lock()
        self._status_snapshot = None
        self._status_generation = 0
        self._runtime_state = "unloaded"
        # Admission-control DI (model_runtime_coordinator), same pattern as
        # llm_engine.set_admission_fn / tts_engine.set_runtime_lease_factory.
        # None-safe: unset means "no admission control".
        self._admission_fn = None      # (estimated_mb, model_size) -> AdmissionResult dict
        self._load_reporter = None     # (model_size, estimated_mb) -> None
        self._error_reporter = None    # (privacy-safe event dict) -> None
        self._last_error = ""
        self._last_error_code = None
        self._last_error_state = None
        self._probe_passed = False
        self._inference_ready = False
        # Set by _load_model() when a load-time CUDA inference probe passed; consumed
        # (and cleared) by ensure_loaded() to seed _inference_ready for that model.
        self._load_inference_verified = False
        self._decode_fallback_attempted = False
        self._publish_runtime_status()

        self.reload_profile(profile_name=profile_name, preload=preload)

    def set_admission_fn(self, fn):
        self._admission_fn = fn

    def set_load_reporter(self, fn):
        self._load_reporter = fn

    def set_error_reporter(self, fn):
        """Inject an owner-level reporter without importing the server."""
        self._error_reporter = fn
        with self._model_lock:
            if callable(fn) and self.device_fallback_code:
                self._emit_runtime_error(
                    self.device_fallback_code,
                    "fallback_active",
                    fallback=True,
                )

    def _emit_runtime_error(self, code, state, *, severity="recoverable", fallback=False):
        """Send only fixed vocabulary/device state to the server reporter."""
        self._last_error_code = code
        self._last_error_state = state
        if state == "fallback_active":
            # A working CPU fallback is not a failure: keep the lifecycle state
            # (loading during a load, ready once constructed) and let the
            # caller that finishes the transition publish it.
            self._publish_runtime_status()
        else:
            self._publish_runtime_status(
                "ready" if self._inference_ready else "failed"
            )
        reporter = self._error_reporter
        if not callable(reporter):
            return
        event = {
            "code": code,
            "state": state,
            "severity": severity,
            "fallback": bool(fallback),
            "active_device": self.active_device,
            "active_compute_type": self.active_compute_type,
            "active_cpu_threads": self.active_cpu_threads,
            "device_fallback_reason": self.device_fallback_reason,
            "device_fallback_code": getattr(self, "device_fallback_code", None),
        }
        try:
            reporter(event)
        except Exception:
            # Diagnostics must never break transcription or model lifecycle.
            logging.debug("STT runtime error reporter failed.")

    def _publish_runtime_status(self, state=None):
        """Publish scalars while the lifecycle owner holds the model lock.

        The independent lock only swaps an immutable record. Readers never
        acquire a model lock or inspect partially constructed engine state.
        No byte-progress callback exists in WhisperModel: progress is unknown
        during construction, rather than inventing a download percentage.
        """
        from types import MappingProxyType

        if state is not None:
            self._runtime_state = state
        snapshot = {
            "constructed": self.model is not None,
            "probe_passed": bool(self._probe_passed),
            "inference_ready": bool(self._inference_ready),
            "error_code": self._last_error_code,
            "error_state": self._last_error_state,
            "active_device": self.active_device,
            "active_compute_type": self.active_compute_type,
            "active_cpu_threads": self.active_cpu_threads,
            "device_fallback_reason": self.device_fallback_reason,
            "device_fallback_code": getattr(self, "device_fallback_code", None),
            "state": self._runtime_state,
            "model_size": self.model_size,
            "loading": self._runtime_state in {"loading", "downloading"},
            "downloading": self._runtime_state == "downloading",
            "progress": None,
        }
        with self._status_lock:
            self._status_generation += 1
            snapshot["generation"] = self._status_generation
            self._status_snapshot = MappingProxyType(snapshot)

    def get_runtime_status(self):
        """Return the latest observation without waiting for model work."""
        with self._status_lock:
            snapshot = self._status_snapshot
        return dict(snapshot)

    def _load_runtime_config(self, profile_name):
        try:
            return load_profile(profile_name)
        except Exception:
            logging.warning("Profile load failed, using transcriber defaults.")
            return {"model_size": "base.en", "use_gpu": True}

    @staticmethod
    def _normalize_model_size(model_size):
        size = (model_size or "base.en").strip()
        if size == "nemotron":
            # Legacy fallback for old profile artifacts.
            size = "base.en"
        return size or "base.en"

    def reload_profile(self, profile_name="Default", preload=None):
        cfg = self._load_runtime_config(profile_name)
        new_size = self._normalize_model_size(cfg.get("model_size", "base.en"))
        new_prefer_gpu = bool(cfg.get("use_gpu", True))

        with self._model_lock:
            size_changed = new_size != self.model_size
            gpu_pref_changed = new_prefer_gpu != self.prefer_gpu

            if size_changed or gpu_pref_changed:
                self._inference_ready = False
                self._probe_passed = False
                self._publish_runtime_status("unloading")

            self.profile_name = profile_name
            self.config = cfg
            self.model_size = new_size
            self.prefer_gpu = new_prefer_gpu

            if size_changed or gpu_pref_changed:
                self.model = None
                # Stale device info would misreport status until the next
                # ensure_loaded() actually reloads the model.
                self.active_device = None
                self.active_compute_type = None
                self.active_cpu_threads = None
                self.device_fallback_reason = None
                self.device_fallback_code = None
                self._probe_passed = False
                self._inference_ready = False
                self._last_error_code = None
                self._last_error_state = None
            self._publish_runtime_status("unloaded" if self.model is None else None)

        if preload is None:
            preload = self.model is not None
        if preload:
            self.ensure_loaded()

    def _resolve_model_source(self, allow_download: bool = False) -> _ModelSource:
        """Decide, in ONE place, where this model's bytes come from.

        Used by every load site (``_load_model``, ``_load_cpu_fallback_model`` and
        ``ensure_loaded``'s cached/will-download computation) so they cannot
        disagree.

        * ``base.en`` with an installer-bundled directory that verifies: load that
          DIRECTORY, local-only, even when ``allow_download`` is True -- the
          bundled model never touches the network.
        * A bundled directory that fails verification: ``failure_code`` is set and
          nothing else is tried; there is no Hub-cache or network fallback.
        * No bundle (development, or any other model size): the H2 local-only
          policy, unchanged. Only ``allow_download`` may fetch.

        ``self.model_size`` is never touched: the status snapshot validates it
        against SUPPORTED_MODEL_SIZES, and a path is not a model size.
        """
        size = self.model_size
        bundle_dir = bundled_models.bundled_model_dir(size)
        if bundle_dir is not None:
            try:
                verified = bundled_models.verify_bundled_model(bundle_dir).ok
            except Exception:
                verified = False
            if verified:
                return _ModelSource(
                    model=str(bundle_dir), local_files_only=True, cached=True,
                    will_download=False, bundled=True,
                )
            return _ModelSource(
                model=size, local_files_only=True, cached=False, will_download=False,
                bundled=True, failure_code="verification_failed",
            )
        cached = self._is_model_cached(size)
        return _ModelSource(
            model=size, local_files_only=not allow_download, cached=cached,
            will_download=bool(allow_download) and not cached,
        )

    def _load_model(self, allow_download: bool = False):
        source = self._resolve_model_source(allow_download)
        if source.failure_code:
            raise ModelUnavailableError("Bundled speech model failed verification.", source.failure_code)
        if source.local_files_only and not source.cached:
            raise ModelUnavailableError(
                "Speech model is not available locally. Use the explicit model download action.",
                "model_missing",
            )
        model_size = self.model_size
        model_arg = source.model
        local_files_only = source.local_files_only
        # Never log the bundle directory: it sits under the user's profile.
        where = "bundled model" if source.bundled else f"cache='{self.download_root}'"

        # Use a stable app-owned cache path so model artifacts are shared across restarts.
        base_kwargs = {
            "download_root": self.download_root,
            "local_files_only": local_files_only,
        }

        # Why we ended up on CPU despite prefer_gpu being True, if that happens.
        # Stays None when prefer_gpu is False (CPU was never a "fallback") or
        # when CUDA loads successfully.
        fallback_reason = None
        fallback_code = None
        self._load_inference_verified = False
        # A CUDA *constructor* exception is only evidence against CUDA if the CPU
        # construction below then succeeds. A cache/network/OOM failure breaks
        # both, and must not disable CUDA for the rest of the process.
        pending_cuda_memo = None

        known_cuda_failure = _known_cuda_failure() if self.prefer_gpu else None
        if known_cuda_failure is not None:
            fallback_reason, fallback_code = known_cuda_failure
            logging.info("Skipping CUDA for Whisper: it already failed in this process (%s).", fallback_reason)
        elif self.prefer_gpu:
            model = None
            # Make an installed cuBLAS/cuDNN runtime reachable before CTranslate2
            # loads it by name; without one, the load-time probe below fails
            # and we fall back to CPU exactly as before.
            ensure_cuda_libraries_on_path()
            try:
                device = "cuda"
                compute_type = "float16"
                logging.info(
                    f"Attempting to load Whisper model '{model_size}' on {device} ({compute_type}) "
                    f"({where}, local_only={local_files_only})..."
                )
                model = WhisperModel(
                    model_arg,
                    device=device,
                    compute_type=compute_type,
                    **base_kwargs,
                )
                logging.info("Whisper model loaded successfully on CUDA.")
            except Exception as exc:
                fallback_code = classify_cuda_runtime_error(exc) or "cuda_init_failed"
                fallback_reason = "CUDA initialization failed"
                pending_cuda_memo = (fallback_reason, fallback_code)
                logging.warning("CUDA initialization failed; falling back to CPU.")

            if model is not None:
                # A CUDA constructor can succeed while the first transcribe() fails
                # (e.g. cublas64_12.dll missing). Prove inference now, at load time,
                # instead of during the user's first dictation. Runs once for whichever
                # construction above succeeded; recovery always stays local-only
                # unless this is the explicit acquisition operation.
                probe_exc = self._probe_cuda_inference(model)
                if probe_exc is None:
                    self.active_device = device
                    self.active_compute_type = compute_type
                    self.active_cpu_threads = None
                    self.device_fallback_reason = None
                    self.device_fallback_code = None
                    self._load_inference_verified = True
                    return model
                fallback_code = classify_cuda_runtime_error(probe_exc)
                if fallback_code is not None:
                    fallback_reason = "CUDA inference probe failed"
                else:
                    # Unrecognized failure: still leave the broken GPU model behind, but
                    # keep the code None (the UI only knows cuda_runtime_missing) and
                    # record just the exception class, never its payload.
                    fallback_reason = f"CUDA inference probe failed ({type(probe_exc).__name__})"
                logging.warning("%s; falling back to CPU.", fallback_reason)
                _remember_cuda_unavailable(fallback_reason, fallback_code)
                # Drop the unusable CUDA model, then continue into the CPU path below.
                probe_exc = None
                model = None
                gc.collect()

        device = "cpu"
        compute_type = "int8"
        cpu_threads = _select_cpu_threads()
        logging.info(
            f"Loading Whisper model '{model_size}' on {device} ({compute_type}) "
            f"({where}, local_only={local_files_only})..."
        )
        model = WhisperModel(
            model_arg,
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            **base_kwargs,
        )
        logging.info("Whisper model loaded successfully on CPU.")
        if pending_cuda_memo is not None:
            _remember_cuda_unavailable(*pending_cuda_memo)
        self.active_device = device
        self.active_compute_type = compute_type
        self.active_cpu_threads = cpu_threads
        self.device_fallback_reason = fallback_reason
        self.device_fallback_code = fallback_code if fallback_reason else None
        return model

    @staticmethod
    def _probe_cuda_inference(model):
        """Run one minimal real inference; return None on success, else the exception."""
        try:
            segments, _info = model.transcribe(
                np.zeros(16000, dtype=np.float32),
                beam_size=1,
                without_timestamps=True,
            )
            list(segments)
            return None
        except Exception as exc:
            # Strip the traceback: its frames reference the model, which the
            # caller is about to drop and must be able to free.
            return exc.with_traceback(None)

    def _is_model_cached(self, model_size):
        local_path = (model_size or "").strip()
        if local_path and os.path.isdir(local_path):
            return all(os.path.isfile(os.path.join(local_path, name))
                       for name in ("model.bin", "tokenizer.json"))

        repo_id = self._model_repo_id(model_size)
        if not repo_id:
            return False

        repo_dir = os.path.join(self.download_root, f"models--{repo_id.replace('/', '--')}")
        snapshots_dir = os.path.join(repo_dir, "snapshots")
        if not os.path.isdir(snapshots_dir):
            return False

        try:
            with os.scandir(snapshots_dir) as entries:
                for entry in entries:
                    if not entry.is_dir():
                        continue
                    model_bin = os.path.join(entry.path, "model.bin")
                    tokenizer_json = os.path.join(entry.path, "tokenizer.json")
                    if os.path.exists(model_bin) and os.path.exists(tokenizer_json):
                        return True
        except Exception:
            return False

        return False

    @staticmethod
    def _model_repo_id(model_size):
        return _repo_id_for_model(model_size)

    def ensure_loaded(self, allow_download: bool = False):
        with self._model_lock:
            if self.model is not None:
                return True

            self._inference_ready = False
            self._probe_passed = False
            self._publish_runtime_status("loading")

            if self._admission_fn is not None:
                estimated_mb = _estimate_whisper_runtime_mb(self.model_size)
                admission = self._admission_fn(estimated_mb, self.model_size)
                if not admission.get("allowed", True):
                    refusal = admission.get("refusal") or {}
                    self._last_error = refusal.get(
                        "message", "Not enough RAM to load the speech model."
                    )
                    logging.error(self._last_error)
                    self._publish_runtime_status("failed")
                    return False

            # Residency and dictation never grant acquisition permission.
            # Only download_whisper_model's explicit action opts in.
            source = self._resolve_model_source(allow_download)
            cached = source.cached
            will_download = source.will_download
            if will_download:
                self._publish_runtime_status("downloading")
                _set_whisper_download_state(self.model_size, {
                    "model_size": self.model_size,
                    "status": "starting",
                    "percent": 0.0,
                    "message": f"Downloading Whisper '{self.model_size}' (first use)...",
                })

            try:
                if will_download:
                    _set_whisper_download_state(self.model_size, {
                        "model_size": self.model_size,
                        "status": "downloading",
                        "percent": 20.0,
                        "message": f"Downloading Whisper '{self.model_size}'. This can take a few minutes.",
                    })
                self.model = self._load_model(allow_download=allow_download)
            except Exception as exc:
                logging.error("Failed to load Whisper model (stt_model_load_failed).")
                self.model = None
                # Nothing loaded -- don't let a stale device from a previous
                # successful load misreport status as still-accelerated.
                self.active_device = None
                self.active_compute_type = None
                self.active_cpu_threads = None
                self.device_fallback_reason = None
                self.device_fallback_code = None
                self._last_error = str(exc)
                self._probe_passed = False
                self._inference_ready = False
                self._load_inference_verified = False
                # A typed refusal (absent model, bundle that failed verification)
                # keeps its own code even during an explicit download: a bad
                # bundle is never "repaired" over the network. An ordinary
                # constructor failure keeps the H2 mapping.
                code = exc.code if isinstance(exc, ModelUnavailableError) else None
                if code is None and not allow_download:
                    code = "verification_failed" if cached else "model_missing"
                if code is not None:
                    self._emit_runtime_error(code, code)
                else:
                    self._emit_runtime_error("stt_model_load_failed", "construction_failed")
                if will_download:
                    _set_whisper_download_state(self.model_size, {
                        "model_size": self.model_size,
                        "status": "error",
                        "percent": 0.0,
                        "message": f"Whisper download failed: {exc}",
                    })
                return False

            if self.model is not None:
                self._last_error = ""
                if self.device_fallback_code:
                    self._emit_runtime_error(
                        self.device_fallback_code,
                        "fallback_active",
                        fallback=True,
                    )
                else:
                    self._last_error_code = None
                    self._last_error_state = None
                # runtime_probe() owns _probe_passed. _inference_ready starts True only
                # when _load_model() already ran a real CUDA decode (load-time probe);
                # a CPU model has not decoded anything yet.
                self._probe_passed = False
                self._inference_ready = bool(self._load_inference_verified)
                self._load_inference_verified = False
                self._publish_runtime_status("ready")
                if will_download:
                    _set_whisper_download_state(self.model_size, {
                        "model_size": self.model_size,
                        "status": "complete",
                        "percent": 100.0,
                        "message": f"Whisper '{self.model_size}' download complete.",
                    })
                if self._load_reporter is not None:
                    try:
                        self._load_reporter(self.model_size, _estimate_whisper_runtime_mb(self.model_size))
                    except Exception:
                        logging.debug("Whisper load reporter failed.")
            else:
                self._publish_runtime_status("failed")
            return self.model is not None

    def refresh_after_download(self, model_size):
        """Re-check this live instance after the explicit download of ITS model.

        The download probes with a throwaway Transcriber, so a live instance that
        already failed local-only keeps reporting ``model_missing`` /
        ``verification_failed`` until something retries. Retry exactly once, still
        local-only, and only for that stale acquisition failure: an instance that
        never failed (e.g. residency off) is left unloaded, and a download of a
        different model says nothing about this one. Returns True when the model
        is now loaded.
        """
        with self._model_lock:
            if self.model is not None:
                return True
            if (model_size or "").strip() != self.model_size:
                return False
            if self._last_error_code not in _ACQUISITION_FAILURE_CODES:
                return False
            return self.ensure_loaded()

    def unload(self):
        with self._model_lock:
            self._inference_ready = False
            self._probe_passed = False
            self._publish_runtime_status("unloading")
            self.model = None
            self.active_device = None
            self.active_compute_type = None
            self.active_cpu_threads = None
            self.device_fallback_reason = None
            self.device_fallback_code = None
            self._probe_passed = False
            self._inference_ready = False
            self._load_inference_verified = False
            self._last_error_code = None
            self._last_error_state = None
            self._publish_runtime_status("unloaded")
        logging.info("Whisper model unloaded.")

    def transcribe(self, audio_array, hotwords=None):
        # Kept for callers that only need text; delegates to the confidence path.
        return self.transcribe_with_confidence(audio_array, hotwords=hotwords)[0]

    def _load_cpu_fallback_model(self):
        """Construct exactly one CPU/int8 model for a lazy CUDA recovery."""
        source = self._resolve_model_source(False)
        if source.failure_code:
            raise ModelUnavailableError("Bundled speech model failed verification.", source.failure_code)
        if not source.cached:
            raise ModelUnavailableError(
                "Speech model is not available locally for CPU recovery.", "model_missing")
        cpu_threads = _select_cpu_threads()
        model = WhisperModel(
            source.model,
            device="cpu",
            compute_type="int8",
            cpu_threads=cpu_threads,
            download_root=self.download_root,
            local_files_only=True,
        )
        self.active_device = "cpu"
        self.active_compute_type = "int8"
        self.active_cpu_threads = cpu_threads
        self.device_fallback_reason = "CUDA inference initialization failed"
        self.device_fallback_code = CUDA_RUNTIME_MISSING_CODE
        return model

    def _decode_segments_with_recovery(self, audio_array, hotwords=None):
        """Consume the lazy faster-whisper generator under the model lock.

        Returns ``(segments, error_code)`` where ``segments`` is ``None`` for
        an infrastructure failure.  The recovery branch is intentionally
        bounded: one CPU model construction and one retry of this same audio.
        """
        audio_duration_s = len(audio_array) / 16000.0
        beam_size = 1 if audio_duration_s < 2.0 else 5
        transcribe_kwargs = {"beam_size": beam_size}
        if hotwords:
            transcribe_kwargs["hotwords"] = hotwords

        with self._model_lock:
            model = self.model
            if model is None:
                self._inference_ready = False
                self._publish_runtime_status("unloaded")
                return None, "stt_model_not_loaded"

            def consume(active_model):
                # faster-whisper's encoder/decoder work can be lazy until the
                # iterator is advanced. Keep both call and iteration locked.
                segments, _info = active_model.transcribe(audio_array, **transcribe_kwargs)
                return list(segments)

            try:
                segments = consume(model)
                self._inference_ready = True
                self._publish_runtime_status("ready")
                return segments, None
            except Exception as exc:
                code = classify_cuda_runtime_error(exc)
                if self.active_device != "cuda" or code != CUDA_RUNTIME_MISSING_CODE:
                    self._inference_ready = False
                    self._emit_runtime_error("stt_inference_failed", "inference_failed")
                    return None, "stt_inference_failed"

                # No recursion and no second CUDA/CPU fallback attempt within
                # this decode. The marker is diagnostic and reset only after a
                # successful probe/normal call boundary.
                self._decode_fallback_attempted = True
                _remember_cuda_unavailable("CUDA inference initialization failed", code)
                self._inference_ready = False
                self._probe_passed = False
                self._publish_runtime_status("loading")
                try:
                    cpu_model = self._load_cpu_fallback_model()
                except Exception:
                    self.model = None
                    self.active_device = None
                    self.active_compute_type = None
                    self.active_cpu_threads = None
                    self._probe_passed = False
                    self._inference_ready = False
                    self._emit_runtime_error(code, "fallback_load_failed", fallback=True)
                    return None, code

                self.model = cpu_model
                try:
                    segments = consume(cpu_model)
                except Exception:
                    # The CPU retry was attempted exactly once. Preserve the
                    # truthful CPU active state but report that inference did
                    # not become ready.
                    self._probe_passed = False
                    self._inference_ready = False
                    self._emit_runtime_error("stt_inference_failed", "fallback_inference_failed", fallback=True)
                    return None, "stt_inference_failed"

                self._inference_ready = True
                self._emit_runtime_error(code, "fallback_active", fallback=True)
                self._publish_runtime_status("ready")
                return segments, None

    def runtime_probe(self):
        """Construct and exercise the real lazy encoder with in-memory silence."""
        silence = np.zeros(1600, dtype=np.float32)
        with self._model_lock:
            constructed = self.ensure_loaded()
            if not constructed:
                self._probe_passed = False
                self._inference_ready = False
                if not self._last_error_code:
                    self._emit_runtime_error("stt_model_load_failed", "construction_failed")
                return self.get_runtime_status()

            # Keep lifecycle ownership through decode and final publication:
            # unload/reload must not invalidate the model between these steps.
            _segments, error_code = self._decode_segments_with_recovery(silence)
            self._probe_passed = error_code is None
            if self._probe_passed and error_code is None and self._last_error_state not in {
                "fallback_active",
            }:
                self._last_error_code = None
                self._last_error_state = None
            elif error_code is not None and self._last_error_code is None:
                self._emit_runtime_error(error_code, "probe_failed")
            self._publish_runtime_status("ready" if error_code is None else "failed")
            return self.get_runtime_status()

    @staticmethod
    def _compute_confidence(seg_list):
        """Turn faster-whisper per-segment stats into a 0..1 confidence score.

        avg_logprob is a mean token log-probability (<= 0); exp() maps it to a
        rough probability. no_speech_prob is how likely the segment is silence.
        We length-weight the segments and penalize by the worst no_speech_prob.
        """
        import math

        if not seg_list:
            return {"score": 0.0, "avg_logprob": None, "no_speech_prob": None}

        total_dur = 0.0
        weighted_logprob = 0.0
        worst_no_speech = 0.0
        for seg in seg_list:
            dur = max(0.001, float(getattr(seg, "end", 0.0)) - float(getattr(seg, "start", 0.0)))
            # Zero is a valid log-probability (probability 1.0), so only a
            # missing value should use the conservative fallback.
            raw_logprob = getattr(seg, "avg_logprob", None)
            logprob = -1.0 if raw_logprob is None else float(raw_logprob)
            weighted_logprob += logprob * dur
            total_dur += dur
            worst_no_speech = max(worst_no_speech, float(getattr(seg, "no_speech_prob", 0.0) or 0.0))

        mean_logprob = weighted_logprob / total_dur if total_dur else -1.0
        prob = math.exp(max(-10.0, mean_logprob))  # exp of a mean log-prob -> ~0..1
        score = max(0.0, min(1.0, prob * (1.0 - worst_no_speech)))
        return {
            "score": round(score, 3),
            "avg_logprob": round(mean_logprob, 3),
            "no_speech_prob": round(worst_no_speech, 3),
        }

    def _transcribe_core(self, audio_array, hotwords=None):
        """Shared decode+guard path behind transcribe_with_confidence and
        transcribe_structured — runs the model exactly once per call.

        Returns (raw_text, confidence_dict, seg_list, audio_duration_s).
        seg_list holds the raw faster-whisper segments used to build raw_text;
        it is emptied alongside raw_text whenever the hallucination/no-speech
        guard discards the result, so the structured caller never surfaces
        hallucinated segment text either.
        """
        empty_conf = {"score": None, "avg_logprob": None, "no_speech_prob": None}
        audio_duration_s = len(audio_array) / 16000.0
        if not self.ensure_loaded():
            return "", empty_conf, [], audio_duration_s

        try:
            if hasattr(audio_array, "dtype") and audio_array.dtype != np.float32:
                audio_array = audio_array.astype(np.float32)

            seg_list, error_code = self._decode_segments_with_recovery(audio_array, hotwords=hotwords)
            if seg_list is None:
                return "", empty_conf, [], audio_duration_s

            # Periodic GC to prevent VRAM fragmentation/leaks
            if audio_duration_s > 5.0:
                gc.collect()

            if not seg_list:
                return "", empty_conf, [], audio_duration_s
            raw = TextFormatter.format_segments(seg_list, paragraph_threshold=1.2)
            if _is_hallucination(raw):
                logging.debug("Hallucination detected, discarding: %s", redact_user_text(raw))
                return "", empty_conf, [], audio_duration_s
            return raw, self._compute_confidence(seg_list), seg_list, audio_duration_s
        except Exception as exc:
            # Broad catch over segment formatting/hallucination-check, which
            # operates directly on the decoded transcript — an exception here
            # could echo it (found by the logging-leak regression gate, not
            # in the original Phase 0 audit).
            logging.error("STT inference failed (stt_inference_failed).")
            return "", empty_conf, [], audio_duration_s

    def transcribe_with_confidence(self, audio_array, hotwords=None):
        """Return (text, confidence_dict). confidence_dict has score/avg_logprob/
        no_speech_prob (score is None-safe 0..1). Optional `hotwords` biases the
        model toward user-dictionary terms (C1)."""
        raw, confidence, _seg_list, _audio_duration_s = self._transcribe_core(audio_array, hotwords=hotwords)
        return raw, confidence

    def transcribe_structured(self, audio_array, hotwords=None):
        """Return a frozen TranscriptionResult (backend.domain.contracts) for the
        same decode used by transcribe_with_confidence: per-segment start/end/
        text/avg_logprob/no_speech_prob, an aggregate confidence score, and
        audio_duration_s. Additive — existing tuple/text-return callers are
        untouched. Segments are empty whenever the hallucination/no-speech
        guard discards the result, same as the legacy text output."""
        _raw, _confidence, result = self.transcribe_with_structured(audio_array, hotwords=hotwords)
        return result

    def transcribe_with_structured(self, audio_array, hotwords=None):
        """Single-decode combined call: (raw_text, confidence_dict, TranscriptionResult)
        from one _transcribe_core() run. A caller that needs both the legacy
        confidence dict (send-policy score) and the structured segments (e.g. for
        speech-signal computation, I3.1) should use this instead of calling
        transcribe_with_confidence() and transcribe_structured() separately —
        each of those decodes independently and would double STT cost."""
        raw, confidence, seg_list, audio_duration_s = self._transcribe_core(audio_array, hotwords=hotwords)
        segments = [
            TimedSegment(
                start_s=float(getattr(seg, "start", 0.0) or 0.0),
                end_s=float(getattr(seg, "end", 0.0) or 0.0),
                text=str(getattr(seg, "text", "") or "").strip(),
                avg_logprob=_optional_float(getattr(seg, "avg_logprob", None)),
                no_speech_prob=_optional_float(getattr(seg, "no_speech_prob", None)),
            )
            for seg in seg_list
        ]
        result = TranscriptionResult(
            text=raw,
            segments=segments,
            confidence=confidence.get("score"),
            audio_duration_s=audio_duration_s,
        )
        return raw, confidence, result
