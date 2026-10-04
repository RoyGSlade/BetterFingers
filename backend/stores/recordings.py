"""Persist raw utterance audio to disk so nothing spoken is ever silently lost (C6).

Each utterance is written as a WAV plus a small JSON sidecar of metadata. A bounded
retention policy prunes the oldest recordings. Audio can be re-read for
re-transcription from the recovery UI.
"""
import json
import logging
import os
import re
import time
import uuid

import numpy as np
from scipy.io import wavfile

from utils import get_user_data_path

# Keep at most this many recordings on disk (oldest pruned first).
MAX_RECORDINGS = 50

# Recording ids become filenames. Ids are now UUID-based (collision-free even
# when several recordings are saved in the same millisecond); the HTTP API
# still accepts the id as a path parameter, so it must never carry path
# components ("../", separators, drive letters). Legacy millisecond-timestamp
# ids on disk remain valid under this pattern.
_VALID_REC_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def new_rec_id():
    """A fresh, collision-free recording id. Time-ordered prefix (so listings
    and pruning stay chronological) + a uuid4 suffix for uniqueness."""
    return f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:12]}"


def is_valid_rec_id(rec_id):
    return bool(_VALID_REC_ID.match(str(rec_id or "")))


def _safe_rec_id(rec_id):
    rec_id = str(rec_id or "")
    if not _VALID_REC_ID.match(rec_id):
        raise ValueError(f"Invalid recording id: {rec_id!r}")
    return rec_id


def get_recordings_dir():
    path = os.path.join(get_user_data_path(), "recordings")
    os.makedirs(path, exist_ok=True)
    return path


def _resolve_inside_recordings_dir(filename):
    """Join + resolve, refusing anything that escapes the recordings dir."""
    directory = os.path.realpath(get_recordings_dir())
    path = os.path.realpath(os.path.join(directory, filename))
    if os.path.commonpath([directory, path]) != directory:
        raise ValueError(f"Recording path escapes recordings dir: {filename!r}")
    return path


def _wav_path(rec_id):
    return _resolve_inside_recordings_dir(f"{_safe_rec_id(rec_id)}.wav")


def _meta_path(rec_id):
    return _resolve_inside_recordings_dir(f"{_safe_rec_id(rec_id)}.json")


def save_recording(recording_result, rec_id, metadata=None):
    """Write one utterance's audio + metadata to disk. Returns the record dict,
    or None if there was no audio to save."""
    audio = getattr(recording_result, "audio_data", None)
    if audio is None or not hasattr(audio, "size") or audio.size <= 0:
        return None

    sample_rate = int(getattr(recording_result, "sample_rate", 16000) or 16000)
    rec_id = str(rec_id)

    wav_path = _wav_path(rec_id)
    meta_path = _meta_path(rec_id)
    # Unique temp names (pid + uuid) so two concurrent saves — even of the same
    # rec_id — never write over each other's staging files.
    stamp = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    wav_tmp = f"{wav_path}.{stamp}.tmp"
    meta_tmp = f"{meta_path}.{stamp}.tmp"

    # Collision guard: a completed recording already owns this id. With UUID
    # ids this never fires in practice; refuse rather than silently clobber.
    if os.path.exists(wav_path) or os.path.exists(meta_path):
        logging.warning("Refusing to overwrite existing recording %s", rec_id)
        return None

    record = {
        "id": rec_id,
        "created_at": time.time(),
        "sample_rate": sample_rate,
        "duration_seconds": round(float(getattr(recording_result, "duration_seconds", 0.0) or 0.0), 2),
        "stop_reason": getattr(recording_result, "stop_reason", "manual"),
        "metadata": metadata or {},
    }

    def _cleanup(paths):
        for p in paths:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass

    # Phase 1: write both staging files. On any failure nothing is promoted.
    try:
        # scipy writes float32 as IEEE-float WAV, which re-reads losslessly.
        data = np.asarray(audio, dtype=np.float32)
        wavfile.write(wav_tmp, sample_rate, data)
        with open(meta_tmp, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
    except Exception as exc:
        logging.warning(f"Failed to stage recording {rec_id}: {exc}")
        _cleanup([wav_tmp, meta_tmp])
        return None

    # Phase 2: promote the pair. If the second promotion fails, roll the first
    # one back so we never leave a half-recording (orphan WAV or orphan meta).
    try:
        os.replace(wav_tmp, wav_path)
    except Exception as exc:
        logging.warning(f"Failed to promote recording WAV {rec_id}: {exc}")
        _cleanup([wav_tmp, meta_tmp])
        return None
    try:
        os.replace(meta_tmp, meta_path)
    except Exception as exc:
        logging.warning(f"Failed to promote recording metadata {rec_id}; rolling back WAV: {exc}")
        _cleanup([wav_path, meta_tmp])  # undo the promoted WAV
        return None

    prune_recordings()
    return record


def list_recordings():
    """All persisted recordings, newest first."""
    directory = get_recordings_dir()
    records = []
    for name in os.listdir(directory):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, name), "r", encoding="utf-8") as handle:
                record = json.load(handle)
            record["has_audio"] = os.path.exists(_wav_path(record.get("id", "")))
            records.append(record)
        except (OSError, ValueError):
            continue
    records.sort(key=lambda r: r.get("created_at", 0), reverse=True)
    return records


def load_recording_audio(rec_id):
    """Read a persisted WAV back into a float32 numpy array + sample rate."""
    try:
        path = _wav_path(rec_id)
    except ValueError as exc:
        logging.warning(str(exc))
        return None, None
    if not os.path.exists(path):
        return None, None
    sample_rate, data = wavfile.read(path)
    if data.dtype != np.float32:
        # Normalize integer PCM back to float in [-1, 1].
        max_val = float(np.iinfo(data.dtype).max) if np.issubdtype(data.dtype, np.integer) else 1.0
        data = data.astype(np.float32) / (max_val or 1.0)
    return data, int(sample_rate)


def delete_recording(rec_id):
    try:
        paths = (_wav_path(rec_id), _meta_path(rec_id))
    except ValueError as exc:
        logging.warning(str(exc))
        return False
    removed = False
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
                removed = True
        except OSError as exc:
            logging.warning(f"Failed to delete recording file {path}: {exc}")
    return removed


def clear_recordings():
    """Delete every recognized recording file by enumerating the directory —
    not just entries with valid JSON metadata — so orphaned WAVs, corrupt
    sidecars, and interrupted temp files are all swept (privacy wipe must not
    leave audio behind). Returns the number of files removed."""
    directory = get_recordings_dir()
    count = 0
    for name in os.listdir(directory):
        if not name.endswith((".wav", ".json", ".tmp")):
            continue
        try:
            os.remove(os.path.join(directory, name))
            count += 1
        except OSError as exc:
            logging.warning(f"Failed to delete recording file {name}: {exc}")
    return count


def list_leftover_files():
    """Recording-shaped files still on disk — the wipe postcondition check."""
    directory = get_recordings_dir()
    return sorted(
        name for name in os.listdir(directory)
        if name.endswith((".wav", ".json", ".tmp"))
    )


def prune_recordings(max_keep=MAX_RECORDINGS):
    records = list_recordings()  # newest first
    removed = 0
    for record in records[max_keep:]:
        if delete_recording(record.get("id")):
            removed += 1
    return removed
