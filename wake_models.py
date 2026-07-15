"""Wake-word model catalog, download/verify, and the streaming ONNX feature
pipeline (melspectrogram -> embedding -> classifier) used by
``wake_word.OpenWakeWordDetector`` (Tier-3 M3).

License gate (§11 + tier3-wake-word.md hard constraint #3): only
Apache-2.0/CC0/MIT models may be listed in ``AVAILABLE_WAKE_MODELS``. The
openWakeWord project's shared melspectrogram/embedding backbone is
Apache-2.0 (it re-hosts Google's TFHub speech_embedding model, itself
Apache-2.0); its own six pre-trained wake-phrase classifiers are
CC-BY-NC-SA-4.0 and are deliberately NOT listed here (see LICENSES-MODELS.md
for the full finding). The catalog therefore ships zero phrase classifiers
by default — a user may supply their own via :func:`import_wake_model`,
recorded with ``license="user-provided"`` so the UI can be honest about
whose responsibility that license is.

Supply-chain discipline mirrors model_manager.py: every catalog entry has a
pinned https URL + sha256 + size, verified after download AND on every load
of an already-installed file (a swapped-in file must never be trusted by
size/mtime alone).
"""
import hashlib
import json
import logging
import os
import shutil
import time

from utils import get_user_data_path

WAKE_BACKBONE_RELEASE = "v0.5.1"
_BACKBONE_BASE_URL = f"https://github.com/dscripka/openWakeWord/releases/download/{WAKE_BACKBONE_RELEASE}"

# Shared feature-extraction backbone (Apache-2.0). No wake-phrase classifier
# is bundled -- see module docstring. sha256/size verified by downloading and
# hashing the actual release assets (not guessed).
AVAILABLE_WAKE_MODELS = {
    "melspectrogram": {
        "name": "Melspectrogram feature extractor",
        "filename": "melspectrogram.onnx",
        "url": f"{_BACKBONE_BASE_URL}/melspectrogram.onnx",
        "sha256": "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f",
        "size_bytes": 1087958,
        "kind": "backbone",
        "license": "Apache-2.0",
        "source": "openWakeWord (Apache-2.0), re-hosting Google TFHub speech_embedding (Apache-2.0)",
    },
    "embedding_model": {
        "name": "Speech embedding model",
        "filename": "embedding_model.onnx",
        "url": f"{_BACKBONE_BASE_URL}/embedding_model.onnx",
        "sha256": "70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f",
        "size_bytes": 1326578,
        "kind": "backbone",
        "license": "Apache-2.0",
        "source": "openWakeWord (Apache-2.0), re-hosting Google TFHub speech_embedding (Apache-2.0)",
    },
}

ALLOWED_LICENSES = {"Apache-2.0", "CC0-1.0", "MIT", "user-provided"}

# Defensive cap for user-imported classifiers -- real wake classifiers are a
# few hundred KB; this only exists to reject "imported the wrong file".
MAX_IMPORT_BYTES = 20 * 1024 * 1024

_IMPORTED_MANIFEST_NAME = "imported_models.json"


class WakeEngineUnavailable(RuntimeError):
    """Raised when the ONNX runtime or a required model file can't be used.

    Callers (server.py's wake-enable path) catch this and surface a truthful
    ``unavailable: <reason>`` status instead of a broken/silent listener.
    """


def get_wake_models_dir():
    path = os.path.join(get_user_data_path(), "wake_models")
    os.makedirs(path, exist_ok=True)
    return path


def get_wake_model_path(model_id):
    info = AVAILABLE_WAKE_MODELS.get(model_id)
    if not info:
        raise KeyError(f"Unknown wake model id: {model_id}")
    return os.path.join(get_wake_models_dir(), info["filename"])


def sha256_file(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hmac_compare(a, b):
    import hmac as _hmac
    return _hmac.compare_digest(str(a or "").lower(), str(b or "").lower())


def is_backbone_model_downloaded(model_id):
    try:
        return os.path.exists(get_wake_model_path(model_id))
    except KeyError:
        return False


def download_wake_model(model_id, progress_callback=None):
    """Download and verify one catalog entry. Reuses model_manager's proven
    download+checksum implementation rather than re-deriving it."""
    import model_manager

    info = AVAILABLE_WAKE_MODELS.get(model_id)
    if not info:
        raise KeyError(f"Unknown wake model id: {model_id}")
    dest = get_wake_model_path(model_id)
    model_manager.download_file(
        info["url"],
        dest,
        desc=info["name"],
        progress_callback=progress_callback,
        progress_key=f"wake_model:{model_id}",
        expected_sha256=info["sha256"],
    )
    return dest


def _quarantine(path):
    corrupt = f"{path}.corrupt"
    try:
        if os.path.exists(corrupt):
            os.remove(corrupt)
        os.replace(path, corrupt)
    except OSError as exc:
        logging.error("Failed to quarantine wake model %s: %s", path, exc)
        return ""
    return corrupt


def verify_wake_model_file(model_id, quarantine=True):
    """Re-hash an already-installed catalog model on load (§11 discipline:
    a downloaded file is verified once at download time AND again every time
    it's loaded, so a file swapped in later is never silently trusted)."""
    info = AVAILABLE_WAKE_MODELS.get(model_id)
    if not info:
        return {"ok": False, "reason": "unknown_model"}
    path = get_wake_model_path(model_id)
    if not os.path.exists(path):
        return {"ok": False, "reason": "missing", "path": path}
    actual = sha256_file(path)
    if _hmac_compare(actual, info["sha256"]):
        return {"ok": True, "reason": "verified", "path": path}
    result = {"ok": False, "reason": "digest_mismatch", "path": path}
    if quarantine:
        result["quarantined"] = _quarantine(path)
        logging.error("Wake model %s failed SHA-256 verification and was quarantined", model_id)
    return result


# --- User-imported classifiers ------------------------------------------------
# The catalog ships zero wake-phrase classifiers (license gate). A user may
# import their own .onnx classifier; we record it as origin="user-imported",
# license="user-provided" so the UI can state plainly that its licensing is
# the user's responsibility, never ours to redistribute.

def _manifest_path():
    return os.path.join(get_wake_models_dir(), _IMPORTED_MANIFEST_NAME)


def load_imported_models():
    try:
        with open(_manifest_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_imported_models(manifest):
    path = _manifest_path()
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    os.replace(tmp, path)


def _safe_import_filename(model_id, source_path):
    ext = os.path.splitext(source_path)[1].lower() or ".onnx"
    if ext != ".onnx":
        ext = ".onnx"
    return f"imported_{model_id}{ext}"


def import_wake_model(display_name, source_path):
    """Copy a user-provided classifier .onnx into the wake models dir and
    record it in the manifest. Raises ValueError on an unusable source
    (missing, empty, oversized) rather than silently accepting garbage."""
    if not os.path.isfile(source_path):
        raise ValueError(f"Source file not found: {source_path}")
    size = os.path.getsize(source_path)
    if size <= 0:
        raise ValueError("Source file is empty.")
    if size > MAX_IMPORT_BYTES:
        raise ValueError(
            f"Source file is {size} bytes; wake classifiers are expected to be small "
            f"(cap {MAX_IMPORT_BYTES} bytes). Refusing to import."
        )

    manifest = load_imported_models()
    model_id = f"user_{int(time.time() * 1000)}"
    filename = _safe_import_filename(model_id, source_path)
    dest = os.path.join(get_wake_models_dir(), filename)
    shutil.copyfile(source_path, dest)
    digest = sha256_file(dest)

    entry = {
        "id": model_id,
        "name": str(display_name or os.path.basename(source_path)),
        "filename": filename,
        "sha256": digest,
        "size_bytes": os.path.getsize(dest),
        "kind": "classifier",
        "license": "user-provided",
        "origin": "user-imported",
        "imported_at": time.time(),
    }
    manifest[model_id] = entry
    _save_imported_models(manifest)
    return entry


def verify_imported_model(model_id, quarantine=True):
    manifest = load_imported_models()
    entry = manifest.get(model_id)
    if not entry:
        return {"ok": False, "reason": "unknown_model"}
    path = os.path.join(get_wake_models_dir(), entry["filename"])
    if not os.path.exists(path):
        return {"ok": False, "reason": "missing", "path": path}
    actual = sha256_file(path)
    if _hmac_compare(actual, entry["sha256"]):
        return {"ok": True, "reason": "verified", "path": path}
    result = {"ok": False, "reason": "digest_mismatch", "path": path}
    if quarantine:
        result["quarantined"] = _quarantine(path)
        manifest.pop(model_id, None)
        _save_imported_models(manifest)
        logging.error("Imported wake model %s failed SHA-256 verification and was removed", model_id)
    return result


def remove_imported_model(model_id):
    manifest = load_imported_models()
    entry = manifest.pop(model_id, None)
    if not entry:
        return False
    path = os.path.join(get_wake_models_dir(), entry["filename"])
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        logging.warning("Failed to remove imported wake model file %s: %s", path, exc)
    _save_imported_models(manifest)
    return True


def get_imported_model_path(model_id):
    entry = load_imported_models().get(model_id)
    if not entry:
        raise KeyError(f"Unknown imported wake model id: {model_id}")
    return os.path.join(get_wake_models_dir(), entry["filename"])


def register_trained_model(display_name, weights, metadata=None):
    """Save a locally-trained NumPy classifier head (.npz, produced by
    wake_trainer) into the wake models dir and record it in the SAME manifest as
    user-imported classifiers — so verify/remove/list/path helpers all apply.
    Distinguished by origin="trained", license="self-trained" (no third-party
    weights, so nothing to redistribute), and a .npz filename that wake_word
    loads via wake_trainer.NumpyClassifierSession instead of onnxruntime."""
    import wake_trainer

    os.makedirs(get_wake_models_dir(), exist_ok=True)
    manifest = load_imported_models()
    model_id = f"trained_{int(time.time() * 1000)}"
    filename = f"{model_id}.npz"
    dest = os.path.join(get_wake_models_dir(), filename)
    wake_trainer.save_model(dest, weights, metadata)
    meta = dict(metadata or {})
    entry = {
        "id": model_id,
        "name": str(display_name or meta.get("phrase") or "Trained phrase"),
        "filename": filename,
        "sha256": sha256_file(dest),
        "size_bytes": os.path.getsize(dest),
        "kind": "classifier",
        "license": "self-trained",
        "origin": "trained",
        "phrase": meta.get("phrase", ""),
        "verdict": meta.get("verdict", ""),
        "threshold": meta.get("threshold"),
        "trained_at": time.time(),
    }
    manifest[model_id] = entry
    _save_imported_models(manifest)
    return entry


def list_wake_models():
    """Merge the backbone catalog with any user-imported classifiers into one
    listing for the /wake/models route, each annotated with install status."""
    entries = []
    for model_id, info in AVAILABLE_WAKE_MODELS.items():
        entries.append({
            "id": model_id,
            "name": info["name"],
            "kind": info["kind"],
            "license": info["license"],
            "origin": "bundled",
            "size_bytes": info["size_bytes"],
            "downloaded": is_backbone_model_downloaded(model_id),
        })
    for model_id, entry in load_imported_models().items():
        entries.append({
            "id": model_id,
            "name": entry["name"],
            "kind": entry["kind"],
            "license": entry["license"],
            "origin": entry["origin"],
            "size_bytes": entry["size_bytes"],
            "downloaded": True,
        })
    return entries


# --- Streaming ONNX feature pipeline ------------------------------------------
# Faithful to openWakeWord's AudioFeatures algorithm (verified against its
# source, and the frame/hop constants empirically confirmed against the
# actual v0.5.1 melspectrogram.onnx: 512-sample window, 160-sample hop, i.e.
# 32ms/10ms at 16kHz): raw float32 audio (int16-scale, NOT normalized to
# [-1, 1]) -> melspectrogram model -> `x/10 + 2` scaling -> one 32-bin mel
# frame per hop -> the most recent 76-frame window, re-embedded every 8 new
# frames -> embedding model -> a rolling buffer of embeddings -> the last
# EMBED_WINDOW (default 16) embeddings, shape (1, 16, 96), is the
# classifier's input.

MEL_FRAME_SAMPLES = 512
MEL_HOP_SAMPLES = 160
MEL_WINDOW_FRAMES = 76
MEL_WINDOW_STRIDE = 8
EMBED_WINDOW_DEFAULT = 16
FEATURE_BUFFER_MAX_LEN = 120
# sounddevice captures float32 in [-1, 1]; the melspec model was trained on
# int16-scale PCM cast to float32 (not normalized) -- rescale before feeding it.
_INT16_SCALE = 32768.0


def build_onnx_session(path):
    """Lazily import onnxruntime and load one model file. Isolated so a
    missing/broken onnxruntime install degrades to WakeEngineUnavailable
    instead of crashing the whole wake-word feature."""
    import importlib

    try:
        onnxruntime = importlib.import_module("onnxruntime")
    except ImportError as exc:
        raise WakeEngineUnavailable(f"onnxruntime not available: {exc}") from exc
    try:
        return onnxruntime.InferenceSession(path, providers=["CPUExecutionProvider"])
    except Exception as exc:
        raise WakeEngineUnavailable(f"failed to load ONNX model {path}: {exc}") from exc


class WakeScorer:
    """Stateful streaming feature pipeline: raw audio chunks in, a rolling
    embedding-feature buffer out. Sessions are duck-typed (need
    ``get_inputs()`` and ``run(output_names, input_feed)``) so tests can
    inject lightweight stubs instead of real ONNX files.

    Memory stays bounded regardless of how long the listener runs: the raw
    buffer only ever holds the unconsumed tail (< 1 mel frame's worth), and
    the mel-frame buffer holds only the most recent ``MEL_WINDOW_FRAMES``.
    """

    def __init__(self, melspec_session, embedding_session, sample_rate=16000):
        import collections

        import numpy as np

        self._np = np
        self.melspec_session = melspec_session
        self.embedding_session = embedding_session
        self.sample_rate = sample_rate
        self._melspec_input_name = melspec_session.get_inputs()[0].name
        self._embedding_input_name = embedding_session.get_inputs()[0].name
        self._raw_buffer = np.zeros((0,), dtype=np.float32)
        self._mel_buffer = collections.deque(maxlen=MEL_WINDOW_FRAMES)
        self._mel_frame_count = 0
        self._feature_buffer = np.zeros((0, 96), dtype=np.float32)

    def reset(self):
        np = self._np
        self._raw_buffer = np.zeros((0,), dtype=np.float32)
        self._mel_buffer.clear()
        self._mel_frame_count = 0
        self._feature_buffer = np.zeros((0, 96), dtype=np.float32)

    def push_audio(self, chunk):
        """Feed one raw audio chunk (float32, normalized [-1, 1]) through the
        pipeline, updating the internal embedding-feature buffer."""
        np = self._np
        chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)
        if chunk.size == 0:
            return
        self._raw_buffer = np.concatenate([self._raw_buffer, chunk * _INT16_SCALE])

        while self._raw_buffer.shape[0] >= MEL_FRAME_SAMPLES:
            window = self._raw_buffer[:MEL_FRAME_SAMPLES]
            self._raw_buffer = self._raw_buffer[MEL_HOP_SAMPLES:]

            mel_out = self.melspec_session.run(None, {self._melspec_input_name: window[None, :]})
            frame = np.asarray(mel_out[0]).reshape(-1, 32)[-1] / 10.0 + 2.0
            self._mel_buffer.append(frame)
            self._mel_frame_count += 1

            if (
                self._mel_frame_count % MEL_WINDOW_STRIDE == 0
                and len(self._mel_buffer) == MEL_WINDOW_FRAMES
            ):
                window_arr = np.stack(list(self._mel_buffer), axis=0)
                batch = window_arr[None, :, :, None].astype(np.float32)
                embed_out = self.embedding_session.run(None, {self._embedding_input_name: batch})
                embedding = np.asarray(embed_out[0]).reshape(-1, 96)[-1:]
                self._feature_buffer = np.concatenate([self._feature_buffer, embedding], axis=0)
                if self._feature_buffer.shape[0] > FEATURE_BUFFER_MAX_LEN:
                    self._feature_buffer = self._feature_buffer[-FEATURE_BUFFER_MAX_LEN:]

    def feature_count(self):
        return int(self._feature_buffer.shape[0])

    def get_features(self, n_frames=EMBED_WINDOW_DEFAULT):
        if self._feature_buffer.shape[0] < n_frames:
            return None
        return self._feature_buffer[-n_frames:][None, :, :].astype(self._np.float32)

    def all_feature_windows(self, n_frames=EMBED_WINDOW_DEFAULT, stride=1):
        """Every ``n_frames``-frame sliding window over the accumulated feature
        buffer, shape ``(M, n_frames, 96)``. Used by the phrase-model trainer
        (wake_trainer.py) to turn one recorded/synthesized clip into all its
        candidate classifier inputs. Returns an empty ``(0, n_frames, 96)``
        array when the buffer is shorter than one window."""
        np = self._np
        total = self._feature_buffer.shape[0]
        if total < n_frames:
            return np.zeros((0, n_frames, 96), dtype=np.float32)
        starts = range(0, total - n_frames + 1, max(1, int(stride)))
        windows = [self._feature_buffer[s:s + n_frames] for s in starts]
        return np.stack(windows, axis=0).astype(np.float32)
