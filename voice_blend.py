"""
Kokoro voice blending — pure tensor math.

Kokoro voice packs are style tensors (numpy arrays). A "blend" is a weighted
average of two or more same-shape voice tensors, producing a new voice tensor
that can be saved as a custom voicepack. This module is the dependency-light
(numpy-only) math core; it knows nothing about where the tensors come from.

Extracting real voice tensors from `voices-v1.0.bin`, persisting blended
voicepacks, and the slider-based blend editor UI are handled elsewhere.
"""

import numpy as np


def _as_array(vec, name="vector"):
    arr = np.asarray(vec, dtype=np.float32)
    if arr.size == 0:
        raise ValueError(f"{name} is empty.")
    return arr


def clamp_weight(weight, lo=0.0, hi=1.0):
    """Clamp a blend weight into [lo, hi]; non-numeric falls back to 0.5."""
    try:
        value = float(weight)
    except (TypeError, ValueError):
        return 0.5
    if np.isnan(value):
        return 0.5
    return max(lo, min(hi, value))


def blend_voices(vec_a, vec_b, weight=0.5):
    """
    Weighted average of two same-shape voice tensors.

    Result = (1 - weight) * A + weight * B, so:
      weight=0.0 -> A unchanged, weight=1.0 -> B unchanged, weight=0.5 -> mean.
    `weight` is clamped to [0, 1]. Raises ValueError on shape mismatch or empty.
    """
    a = _as_array(vec_a, "vec_a")
    b = _as_array(vec_b, "vec_b")
    if a.shape != b.shape:
        raise ValueError(f"Voice tensors must share a shape: {a.shape} != {b.shape}.")
    w = clamp_weight(weight)
    return (1.0 - w) * a + w * b


def blend_many(vectors, weights=None):
    """
    N-way normalized weighted average of same-shape voice tensors.

    `weights` defaults to equal weighting. Weights are treated as non-negative
    magnitudes and normalized to sum to 1 (all-zero / missing -> uniform).
    Raises ValueError on empty input or shape mismatch.
    """
    if vectors is None:
        raise ValueError("vectors is required.")
    arrays = [_as_array(v, f"vectors[{i}]") for i, v in enumerate(vectors)]
    if not arrays:
        raise ValueError("At least one voice tensor is required.")

    base_shape = arrays[0].shape
    for i, arr in enumerate(arrays):
        if arr.shape != base_shape:
            raise ValueError(f"vectors[{i}] shape {arr.shape} != {base_shape}.")

    n = len(arrays)
    if weights is None:
        w = np.full(n, 1.0 / n, dtype=np.float64)
    else:
        w = np.asarray(weights, dtype=np.float64)
        if w.shape != (n,):
            raise ValueError(f"weights must have length {n}, got {w.shape}.")
        w = np.clip(w, 0.0, None)
        total = float(w.sum())
        w = np.full(n, 1.0 / n) if total <= 0.0 else w / total

    stacked = np.stack(arrays, axis=0).astype(np.float64)
    # Broadcast weights across the tensor's non-leading axes.
    weight_shape = (n,) + (1,) * (stacked.ndim - 1)
    result = (stacked * w.reshape(weight_shape)).sum(axis=0)
    return result.astype(np.float32)


def validate_blend_request(names, weights=None):
    """
    Validate a user blend request before touching tensors. Returns (ok, msg).

    `names` is the list of source voice names; `weights` (optional) must match
    in length and contain at least one positive value.
    """
    if not names or not isinstance(names, (list, tuple)):
        return False, "Select at least one source voice to blend."
    if len(names) < 2:
        return False, "Blending needs at least two source voices."
    if any(not str(n or "").strip() for n in names):
        return False, "Every source voice must be named."
    if weights is not None:
        if len(weights) != len(names):
            return False, "Provide one weight per source voice."
        try:
            numeric = [float(w) for w in weights]
        except (TypeError, ValueError):
            return False, "Weights must be numbers."
        if any(w < 0 for w in numeric):
            return False, "Weights cannot be negative."
        if sum(numeric) <= 0:
            return False, "At least one weight must be positive."
    return True, "OK"
