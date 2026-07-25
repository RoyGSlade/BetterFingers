"""Per-window RMS energy summaries for delivery signals.

Companion to :mod:`backend.services.speech_signals`, which is deliberately
audio-free (it takes only timing data plus an optional sequence of numeric
energy summaries). This module is the one place allowed to touch a waveform,
and its entire output is a list of non-negative floats -- never audio, never
text -- so the purity guarantee downstream is preserved.

Why this exists: ``compute_speech_signals`` derives ``arousal`` as
``0.5*normalized_wpm + 0.5*normalized_energy_variation``. Production never
supplied ``energy_windows``, so the energy half was always 0.0 and ``arousal``
silently degraded into a rescaled pace metric wearing an emotion-adjacent
label. This closes that gap.

Nothing here infers or names an emotion; it reports loudness statistics only.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

# 100 ms is short enough to register a raised voice or a trailing-off phrase,
# long enough that a single plosive doesn't dominate a window.
DEFAULT_WINDOW_MS = 100.0

# Upper bound on window count so a 60-minute recording (a supported case) does
# not produce a 36k-element list. Past this, windows are widened rather than
# truncated -- the whole recording stays represented, just more coarsely.
# Truncating would silently describe only the opening of a long recording.
MAX_WINDOWS = 2048


def rms_windows(
    audio: Sequence[float] | np.ndarray | None,
    sample_rate: int = 16000,
    window_ms: float = DEFAULT_WINDOW_MS,
    max_windows: int = MAX_WINDOWS,
) -> list[float]:
    """Return per-window RMS amplitudes for ``audio``.

    Accepts mono float samples (the recorder's ``float32`` format) or anything
    ``numpy`` can coerce to a 1-D float array. Returns ``[]`` for empty, None,
    or unusable input rather than raising -- delivery signals are a
    nice-to-have on the dictation path and must never fail a transcription.

    All returned values are finite and non-negative. Non-finite samples
    (NaN/inf from a misbehaving device) are zeroed before the calculation so a
    single bad frame cannot poison the whole statistic.
    """

    if audio is None or sample_rate <= 0 or window_ms <= 0 or max_windows <= 0:
        return []

    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if samples.size == 0:
        return []

    window_len = max(1, int(round(sample_rate * (window_ms / 1000.0))))
    # Widen (never truncate) so long recordings stay fully represented.
    if samples.size / window_len > max_windows:
        window_len = int(np.ceil(samples.size / max_windows))

    usable = samples.size - (samples.size % window_len)
    if usable < window_len:
        # Shorter than one window: the whole clip is a single window.
        framed = samples.reshape(1, -1)
        divisor = float(samples.size)
    else:
        framed = samples[:usable].reshape(-1, window_len)
        divisor = float(window_len)

    values = np.sqrt(_sum_squares(framed) / divisor)
    return [float(v) for v in values]


def _sum_squares(framed: np.ndarray) -> np.ndarray:
    """Row-wise sum of squares, accumulated in float64.

    ``einsum`` reads the frames in place: it never materializes a squared or
    upcast copy of the waveform, which matters because this runs on the
    dictation hot path for every transcription and a supported 60-minute
    recording is ~57.6M float32 samples.

    Non-finite samples (NaN/inf from a misbehaving device) are repaired
    *lazily* -- only the affected rows are sanitized and recomputed. Scrubbing
    the whole buffer up front was measured at ~518MB of temporaries on a
    60-minute clip, paid on every recording to guard against a rare bad frame;
    a corrupt frame localizes to its own window, so only that window needs
    fixing. One bad frame must not discard the rest of the recording.
    """

    sums = np.einsum("ij,ij->i", framed, framed, dtype=np.float64)

    bad = ~np.isfinite(sums)
    if bad.any():
        repaired = np.nan_to_num(framed[bad], nan=0.0, posinf=0.0, neginf=0.0)
        sums[bad] = np.einsum("ij,ij->i", repaired, repaired, dtype=np.float64)

    # Squares are non-negative; clamp guards against a -0.0 reaching sqrt.
    return np.maximum(sums, 0.0)
