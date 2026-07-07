"""Persist raw utterance audio to disk so nothing spoken is ever silently lost (C6).

Each utterance is written as a WAV plus a small JSON sidecar of metadata. A bounded
retention policy prunes the oldest recordings. Audio can be re-read for
re-transcription from the recovery UI.
"""
import json
import logging
import os
import time

import numpy as np
from scipy.io import wavfile

from utils import get_user_data_path

# Keep at most this many recordings on disk (oldest pruned first).
MAX_RECORDINGS = 50


def get_recordings_dir():
    path = os.path.join(get_user_data_path(), "recordings")
    os.makedirs(path, exist_ok=True)
    return path


def _wav_path(rec_id):
    return os.path.join(get_recordings_dir(), f"{rec_id}.wav")


def _meta_path(rec_id):
    return os.path.join(get_recordings_dir(), f"{rec_id}.json")


def save_recording(recording_result, rec_id, metadata=None):
    """Write one utterance's audio + metadata to disk. Returns the record dict,
    or None if there was no audio to save."""
    audio = getattr(recording_result, "audio_data", None)
    if audio is None or not hasattr(audio, "size") or audio.size <= 0:
        return None

    sample_rate = int(getattr(recording_result, "sample_rate", 16000) or 16000)
    rec_id = str(rec_id)

    try:
        # scipy writes float32 as IEEE-float WAV, which re-reads losslessly.
        data = np.asarray(audio, dtype=np.float32)
        wavfile.write(_wav_path(rec_id), sample_rate, data)
    except Exception as exc:
        logging.warning(f"Failed to persist recording {rec_id}: {exc}")
        return None

    record = {
        "id": rec_id,
        "created_at": time.time(),
        "sample_rate": sample_rate,
        "duration_seconds": round(float(getattr(recording_result, "duration_seconds", 0.0) or 0.0), 2),
        "stop_reason": getattr(recording_result, "stop_reason", "manual"),
        "metadata": metadata or {},
    }
    try:
        with open(_meta_path(rec_id), "w", encoding="utf-8") as handle:
            json.dump(record, handle)
    except OSError as exc:
        logging.warning(f"Failed to write recording metadata {rec_id}: {exc}")

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
    path = _wav_path(str(rec_id))
    if not os.path.exists(path):
        return None, None
    sample_rate, data = wavfile.read(path)
    if data.dtype != np.float32:
        # Normalize integer PCM back to float in [-1, 1].
        max_val = float(np.iinfo(data.dtype).max) if np.issubdtype(data.dtype, np.integer) else 1.0
        data = data.astype(np.float32) / (max_val or 1.0)
    return data, int(sample_rate)


def delete_recording(rec_id):
    rec_id = str(rec_id)
    removed = False
    for path in (_wav_path(rec_id), _meta_path(rec_id)):
        try:
            if os.path.exists(path):
                os.remove(path)
                removed = True
        except OSError as exc:
            logging.warning(f"Failed to delete recording file {path}: {exc}")
    return removed


def clear_recordings():
    count = 0
    for record in list_recordings():
        if delete_recording(record.get("id")):
            count += 1
    return count


def prune_recordings(max_keep=MAX_RECORDINGS):
    records = list_recordings()  # newest first
    removed = 0
    for record in records[max_keep:]:
        if delete_recording(record.get("id")):
            removed += 1
    return removed
