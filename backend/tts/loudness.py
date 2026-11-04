"""Loudness envelope of a TTS audio buffer, for the overlay face's lip-sync.

Pure and dependency-light (numpy only) so it is cheap to call right before a
chunk plays and easy to test. The overlay plays the envelope back from the
moment it arrives, so one message per chunk is enough -- no per-frame stream.
"""

from __future__ import annotations

import numpy as np

ENVELOPE_FPS = 30
MAX_FRAMES = 30 * 60  # one chunk is ~220 chars; cap well above that (60 s)


def loudness_envelope(audio, sample_rate: int, fps: int = ENVELOPE_FPS) -> dict:
    """RMS loudness per 1/fps slice, normalised to 0..1.

    Normalising by the chunk's own 95th percentile makes quiet and loud voices
    move the mouth the same amount; a floor keeps silence closed rather than
    amplifying noise. Returns ``{"envelope": [...], "fps": fps, "duration": s}``.
    """
    a = np.asarray(audio, dtype=np.float64)
    if a.ndim > 1:  # (frames, channels) -> mono
        a = a.mean(axis=1)
    if a.size == 0 or not sample_rate or sample_rate <= 0:
        return {"envelope": [], "fps": fps, "duration": 0.0}
    hop = max(1, int(round(sample_rate / fps)))
    frames = min(MAX_FRAMES, int(np.ceil(a.size / hop)))
    padded = np.zeros(frames * hop)
    n = min(a.size, padded.size)
    padded[:n] = a[:n]
    rms = np.sqrt(np.mean(padded.reshape(frames, hop) ** 2, axis=1))
    voiced = rms[rms > 1e-4]
    ref = float(np.percentile(voiced, 95)) if voiced.size else 0.0
    if ref < 1e-3:
        env = np.zeros(frames)
    else:
        env = np.clip(rms / ref, 0.0, 1.0)
        env[rms < ref * 0.06] = 0.0  # silence stays shut
    return {
        "envelope": [round(float(x), 2) for x in env],
        "fps": fps,
        "duration": round(a.size / float(sample_rate), 3),
    }
