"""In-app wake-phrase / command-phrase model builder (DESIGN.md M3 Phase 2).

Trains a tiny classifier head on top of the SHIPPED Apache-2.0 embedding
backbone (``wake_models.WakeScorer`` turns raw audio into ``(16, 96)`` embedding
feature windows). Two deliberate design choices make this work in a packaged app
where the earlier plan assumed it couldn't:

* **Pure NumPy training, no torch.** The head is a one-hidden-layer MLP over the
  1536-dim flattened feature window — trainable by hand in NumPy in well under a
  second. No torch, no side-runtime, no onnx-export package; it behaves
  identically in dev and frozen builds. The trained head plugs straight into
  ``WakeScorer`` through the duck-typed :class:`NumpyClassifierSession`, which
  mirrors the onnxruntime session surface ``get_inputs()`` / ``run()`` that
  ``wake_word.OpenWakeWordDetector.predict`` already calls.

* **Synthetic positives from Kokoro, not Piper.** openWakeWord generates
  training positives with Piper TTS (GPL). BetterFingers already ships Kokoro
  (Apache-2.0 / MIT), so the phrase can be synthesized across many voices with
  pitch/speed augmentation for free and license-clean. That audio generation
  lives in the route layer (real TTS); THIS module stays pure/testable and only
  consumes already-extracted feature windows, so it needs no models to unit-test.

Scope is calibration-grade per the milestone: a handful of real recordings +
synthetic positives + negatives -> a personalised threshold and an honest
"reliable" / "noisy" verdict, not a from-scratch SOTA trainer.
"""

import json
import os

import numpy as np

EMBED_DIM = 96
EMBED_WINDOW = 16                 # frames per classifier input (matches WakeScorer)
FEATURE_LEN = EMBED_WINDOW * EMBED_DIM  # 1536
_MODEL_FORMAT_VERSION = 1


# --- Duck-typed classifier session (plugs into WakeScorer) --------------------

class _NamedInput:
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


class NumpyClassifierSession:
    """A NumPy MLP wrapped in the minimal onnxruntime-session surface
    (``get_inputs()`` + ``run(output_names, input_feed)``) that
    ``OpenWakeWordDetector.predict`` uses. Lets a locally-trained head drop into
    the exact same code path as a real ``.onnx`` classifier, no ONNX involved.

    ``weights`` is the dict returned by :func:`train_classifier` /
    :func:`load_model`. Input feed value is shape ``(1, 16, 96)`` float32; the
    single output is a ``(1, 1)`` probability in ``[0, 1]``.
    """

    def __init__(self, weights, input_name="features"):
        self._w = weights
        self._input_name = input_name

    def get_inputs(self):
        return [_NamedInput(self._input_name)]

    def run(self, output_names, input_feed):  # noqa: ARG002 - onnxruntime signature
        x = np.asarray(next(iter(input_feed.values())), dtype=np.float32)
        score = _forward(self._w, x.reshape(x.shape[0], -1))
        return [score.reshape(-1, 1)]


# --- Forward / training math (pure NumPy) -------------------------------------

def _sigmoid(z):
    # Numerically stable logistic.
    out = np.empty_like(z, dtype=np.float64)
    pos = z >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    ez = np.exp(z[~pos])
    out[~pos] = ez / (1.0 + ez)
    return out


def _standardize(x, mean, std):
    return (x - mean) / std


def _forward(weights, x_flat):
    """(B, 1536) -> (B,) probability. Standardizes with the stored stats, one
    tanh hidden layer, sigmoid output."""
    x = _standardize(np.asarray(x_flat, dtype=np.float64), weights["mean"], weights["std"])
    h = np.tanh(x @ weights["W1"] + weights["b1"])
    logits = h @ weights["W2"] + weights["b2"]
    return _sigmoid(logits).reshape(-1)


def train_classifier(
    pos_windows,
    neg_windows,
    *,
    hidden=32,
    epochs=400,
    lr=0.05,
    l2=1e-4,
    seed=0,
):
    """Train the phrase classifier head.

    Args:
      pos_windows: ``(P, 16, 96)`` feature windows that contain the phrase.
      neg_windows: ``(N, 16, 96)`` windows that do not (other speech, ambient,
        the user's "not the phrase" recordings).
    Returns a weights dict (also the on-disk model payload) with keys
    ``W1 b1 W2 b2 mean std`` plus ``meta`` (hidden size, counts, format version).

    Raises ``ValueError`` if either class is empty — the caller (route layer)
    surfaces that as an actionable "record more samples" message.
    """
    pos = _as_flat(pos_windows)
    neg = _as_flat(neg_windows)
    if pos.shape[0] == 0 or neg.shape[0] == 0:
        raise ValueError("training needs at least one positive and one negative window")

    x = np.concatenate([pos, neg], axis=0).astype(np.float64)
    y = np.concatenate([np.ones(pos.shape[0]), np.zeros(neg.shape[0])]).astype(np.float64)

    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std[std < 1e-6] = 1e-6

    rng = np.random.default_rng(seed)
    xs = _standardize(x, mean, std)
    # He-ish init for tanh hidden, small output init.
    w1 = rng.standard_normal((FEATURE_LEN, hidden)) * np.sqrt(1.0 / FEATURE_LEN)
    b1 = np.zeros(hidden)
    w2 = rng.standard_normal((hidden, 1)) * np.sqrt(1.0 / hidden)
    b2 = np.zeros(1)

    # Class-balanced weighting so a lopsided pos/neg count doesn't bias the head.
    n = y.shape[0]
    w_pos = n / (2.0 * max(1, pos.shape[0]))
    w_neg = n / (2.0 * max(1, neg.shape[0]))
    sample_w = np.where(y > 0.5, w_pos, w_neg)

    for _ in range(int(epochs)):
        h = np.tanh(xs @ w1 + b1)
        logits = (h @ w2 + b2).reshape(-1)
        p = _sigmoid(logits)
        # dL/dlogit for weighted BCE.
        g = (p - y) * sample_w / n
        gw2 = h.T @ g.reshape(-1, 1) + l2 * w2
        gb2 = np.array([g.sum()])
        dh = (g.reshape(-1, 1) @ w2.T) * (1.0 - h ** 2)
        gw1 = xs.T @ dh + l2 * w1
        gb1 = dh.sum(axis=0)
        w1 -= lr * gw1
        b1 -= lr * gb1
        w2 -= lr * gw2
        b2 -= lr * gb2

    return {
        "W1": w1, "b1": b1, "W2": w2, "b2": b2, "mean": mean, "std": std,
        "meta": {
            "format_version": _MODEL_FORMAT_VERSION,
            "hidden": int(hidden),
            "embed_window": EMBED_WINDOW,
            "embed_dim": EMBED_DIM,
            "n_pos": int(pos.shape[0]),
            "n_neg": int(neg.shape[0]),
        },
    }


def _as_flat(windows):
    arr = np.asarray(windows, dtype=np.float64)
    if arr.size == 0:
        return np.zeros((0, FEATURE_LEN))
    if arr.ndim == 3:  # (M, 16, 96)
        return arr.reshape(arr.shape[0], -1)
    if arr.ndim == 2 and arr.shape[1] == FEATURE_LEN:
        return arr
    raise ValueError(f"expected (M,16,96) or (M,1536) windows, got {arr.shape}")


# --- Threshold calibration + reliability verdict ------------------------------

def calibrate(pos_scores, neg_scores):
    """Pick a personalised threshold and judge reliability from held-out scores.

    Chooses the threshold that maximises balanced accuracy (ties broken toward a
    larger margin from both classes), then reports the false-accept / false-
    reject rates at that threshold and a coarse verdict:
      * ``"reliable"`` — clean separation (both error rates low, decent margin),
      * ``"noisy"``    — usable but with meaningful overlap (recommend more
        samples / a distinct phrase),
      * ``"unusable"`` — the classes are not separable at any threshold.
    Returns a dict the route/UI surfaces verbatim.
    """
    pos = np.asarray(pos_scores, dtype=np.float64).reshape(-1)
    neg = np.asarray(neg_scores, dtype=np.float64).reshape(-1)
    if pos.size == 0 or neg.size == 0:
        return {"threshold": 0.5, "verdict": "unusable", "fa_rate": 1.0,
                "fr_rate": 1.0, "margin": 0.0, "reason": "no evaluation samples"}

    candidates = np.unique(np.concatenate([pos, neg, [0.0, 1.0]]))
    best = None
    for t in candidates:
        fr = float(np.mean(pos < t))          # positives rejected
        fa = float(np.mean(neg >= t))         # negatives accepted
        bal_acc = 1.0 - 0.5 * (fr + fa)
        margin = float(pos.mean() - neg.mean())
        key = (round(bal_acc, 6), round(margin, 6))
        if best is None or key > best[0]:
            best = (key, t, fa, fr)
    _, threshold, fa_rate, fr_rate = best
    margin = float(pos.mean() - neg.mean())

    if fa_rate <= 0.05 and fr_rate <= 0.10 and margin >= 0.30:
        verdict = "reliable"
    elif fa_rate <= 0.25 and fr_rate <= 0.30:
        verdict = "noisy"
    else:
        verdict = "unusable"

    return {
        "threshold": float(np.clip(threshold, 0.05, 0.95)),
        "verdict": verdict,
        "fa_rate": round(fa_rate, 4),
        "fr_rate": round(fr_rate, 4),
        "margin": round(margin, 4),
    }


def score_windows(weights, windows):
    """Probability for each ``(16,96)`` window -> ``(M,)`` array."""
    flat = _as_flat(windows)
    if flat.shape[0] == 0:
        return np.zeros((0,), dtype=np.float64)
    return _forward(weights, flat)


# --- Persistence (.npz, no torch/onnx) ----------------------------------------

def save_model(path, weights, metadata=None):
    """Serialize a trained head to ``path`` (.npz). Metadata (phrase, voices,
    calibration verdict/threshold, created_at) rides along as a JSON blob so a
    model file is self-describing for the export/import-profile feature."""
    meta = dict(weights.get("meta") or {})
    if metadata:
        meta.update(metadata)
    tmp = f"{path}.tmp"
    with open(tmp, "wb") as fh:
        np.savez(
            fh,
            W1=weights["W1"], b1=weights["b1"], W2=weights["W2"], b2=weights["b2"],
            mean=weights["mean"], std=weights["std"],
            meta=np.frombuffer(json.dumps(meta).encode("utf-8"), dtype=np.uint8),
        )
    os.replace(tmp, path)
    return path


def load_model(path):
    """Inverse of :func:`save_model`. Returns a weights dict usable by
    :class:`NumpyClassifierSession` / :func:`score_windows`."""
    with np.load(path, allow_pickle=False) as data:
        meta = json.loads(bytes(data["meta"].tobytes()).decode("utf-8")) if "meta" in data else {}
        return {
            "W1": data["W1"], "b1": data["b1"], "W2": data["W2"], "b2": data["b2"],
            "mean": data["mean"], "std": data["std"], "meta": meta,
        }


# --- Feature extraction from a clip (via the shipped backbone) ----------------

def extract_feature_windows(scorer, audio, *, embed_window=EMBED_WINDOW, stride=1):
    """Run one audio clip through a (fresh) ``WakeScorer`` and return all of its
    ``(M, embed_window, 96)`` classifier-input windows. ``scorer`` is any object
    exposing ``reset()``, ``push_audio()`` and ``all_feature_windows()`` — the
    real backbone at runtime, a stub in tests."""
    scorer.reset()
    scorer.push_audio(np.asarray(audio, dtype=np.float32).reshape(-1))
    return scorer.all_feature_windows(embed_window, stride)
