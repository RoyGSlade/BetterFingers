import gc
import logging
import os
import re
import threading
import time

import numpy as np
from faster_whisper import WhisperModel
from huggingface_hub import scan_cache_dir
from huggingface_hub.constants import HF_HUB_CACHE

from text_formatter import TextFormatter
from utils import load_profile

# --- Hallucination Guard ---
# Whisper sometimes "hallucinates" repeated short phrases during silence or
# noise.  The patterns below catch the most common ones.
_HALLUCINATION_PHRASES = {
    "thank you", "thanks for watching", "subscribe",
    "please subscribe", "thanks for listening", "bye",
    "you", "the end",
}

_SENTENCE_SPLIT_RE = re.compile(r'[.!?]+')


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
        return f"Systran/faster-{size}"
    return f"Systran/faster-whisper-{size}"


def list_cached_models(download_root=None):
    cache_dir = str(download_root or HF_HUB_CACHE or "").strip() or HF_HUB_CACHE
    rows = {
        name: {
            "model_size": name,
            "repo_id": _repo_id_for_model(name),
            "installed": False,
            "size_bytes": 0,
        }
        for name in SUPPORTED_MODEL_SIZES
    }

    try:
        cache_info = scan_cache_dir(cache_dir=cache_dir)
    except TypeError:
        try:
            cache_info = scan_cache_dir()
        except Exception:
            return [rows[name] for name in SUPPORTED_MODEL_SIZES]
    except Exception:
        return [rows[name] for name in SUPPORTED_MODEL_SIZES]

    for repo in getattr(cache_info, "repos", []) or []:
        repo_id = str(getattr(repo, "repo_id", "") or "").strip()
        if not repo_id:
            continue
        size_name = ""
        if repo_id.startswith("Systran/faster-whisper-"):
            size_name = repo_id.split("Systran/faster-whisper-", 1)[1].strip()
        if not size_name:
            continue
        if size_name not in rows:
            rows[size_name] = {
                "model_size": size_name,
                "repo_id": repo_id,
                "installed": False,
                "size_bytes": 0,
            }
        size_on_disk = int(getattr(repo, "size_on_disk", 0) or 0)
        rows[size_name]["installed"] = size_on_disk > 0
        rows[size_name]["size_bytes"] = size_on_disk

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

        ok = probe.ensure_loaded()
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
        self.download_root = HF_HUB_CACHE
        os.makedirs(self.download_root, exist_ok=True)

        self._model_lock = threading.RLock()

        self.reload_profile(profile_name=profile_name, preload=preload)

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

            self.profile_name = profile_name
            self.config = cfg
            self.model_size = new_size
            self.prefer_gpu = new_prefer_gpu

            if size_changed or gpu_pref_changed:
                self.model = None

        if preload is None:
            preload = self.model is not None
        if preload:
            self.ensure_loaded()

    def _load_model(self):
        model_size = self.model_size
        local_files_only = self._is_model_cached(model_size)

        # Use a stable app-owned cache path so model artifacts are shared across restarts.
        base_kwargs = {
            "download_root": self.download_root,
            "local_files_only": local_files_only,
        }

        if self.prefer_gpu:
            try:
                device = "cuda"
                compute_type = "float16"
                logging.info(
                    f"Attempting to load Whisper model '{model_size}' on {device} ({compute_type}) "
                    f"(cache='{self.download_root}', local_only={local_files_only})..."
                )
                model = WhisperModel(
                    model_size,
                    device=device,
                    compute_type=compute_type,
                    **base_kwargs,
                )
                logging.info("Whisper model loaded successfully on CUDA.")
                return model
            except Exception as exc:
                if local_files_only:
                    # Cache may be partial/corrupt; retry once with network allowed.
                    try:
                        logging.warning(
                            f"CUDA load from local cache failed ({exc}). Retrying with remote fetch enabled."
                        )
                        # Explicit GC before retry
                        gc.collect()
                        model = WhisperModel(
                            model_size,
                            device=device,
                            compute_type=compute_type,
                            download_root=self.download_root,
                            local_files_only=False,
                        )
                        logging.info("Whisper model loaded successfully on CUDA after cache refresh.")
                        return model
                    except Exception as retry_exc:
                        exc = retry_exc
                logging.warning(f"CUDA initialization failed ({exc}). Falling back to CPU.")

        device = "cpu"
        compute_type = "int8"
        logging.info(
            f"Loading Whisper model '{model_size}' on {device} ({compute_type}) "
            f"(cache='{self.download_root}', local_only={local_files_only})..."
        )
        try:
            model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
                **base_kwargs,
            )
        except Exception as exc:
            if local_files_only:
                logging.warning(
                    f"CPU load from local cache failed ({exc}). Retrying with remote fetch enabled."
                )
                model = WhisperModel(
                    model_size,
                    device=device,
                    compute_type=compute_type,
                    download_root=self.download_root,
                    local_files_only=False,
                )
            else:
                raise
        logging.info("Whisper model loaded successfully on CPU.")
        return model

    def _is_model_cached(self, model_size):
        local_path = (model_size or "").strip()
        if local_path and os.path.isdir(local_path):
            return os.path.exists(os.path.join(local_path, "model.bin"))

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

    def ensure_loaded(self):
        with self._model_lock:
            if self.model is not None:
                return True
            try:
                self.model = self._load_model()
                return self.model is not None
            except Exception as exc:
                logging.error(f"Failed to load Whisper model: {exc}")
                self.model = None
                return False

    def unload(self):
        with self._model_lock:
            self.model = None
        logging.info("Whisper model unloaded.")

    def transcribe(self, audio_array):
        # Kept for callers that only need text; delegates to the confidence path.
        return self.transcribe_with_confidence(audio_array)[0]

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
            logprob = float(getattr(seg, "avg_logprob", -1.0) or -1.0)
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

    def transcribe_with_confidence(self, audio_array):
        """Return (text, confidence_dict). confidence_dict has score/avg_logprob/
        no_speech_prob (score is None-safe 0..1)."""
        empty_conf = {"score": None, "avg_logprob": None, "no_speech_prob": None}
        if not self.ensure_loaded():
            return "", empty_conf

        try:
            if hasattr(audio_array, "dtype") and audio_array.dtype != np.float32:
                audio_array = audio_array.astype(np.float32)

            with self._model_lock:
                model = self.model
                if model is None:
                    return "", empty_conf

                # --- Fast Lane & VRAM Protection ---
                # For short audio (< 2.0s), use greedy search (beam_size=1) for speed.
                duration = len(audio_array) / 16000.0
                beam_size = 1 if duration < 2.0 else 5

                segments, _info = model.transcribe(audio_array, beam_size=beam_size)

                # Periodic GC to prevent VRAM fragmentation/leaks
                if duration > 5.0:
                    gc.collect()

            seg_list = list(segments)
            if not seg_list:
                return "", empty_conf
            raw = TextFormatter.format_segments(seg_list, paragraph_threshold=1.2)
            if _is_hallucination(raw):
                logging.debug("Hallucination detected, discarding: %r", raw)
                return "", empty_conf
            return raw, self._compute_confidence(seg_list)
        except Exception as exc:
            logging.error(f"Error during transcription: {exc}")
            return "", empty_conf
