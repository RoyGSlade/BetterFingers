"""Assemble a wake/command-phrase training set from three sources, then hand
clean ``(M, 16, 96)`` feature windows to ``wake_trainer``.

Positives:
  * the user's own recordings of the phrase (real voice, real mic — the anchor),
  * synthetic renderings of the phrase by the app's Kokoro voices (Apache/MIT),
    across a few speeds for augmentation — this is the GPL-free replacement for
    openWakeWord's Piper-generated positives.
Negatives:
  * synthetic renderings of decoy phrases (so the head learns "this phrase, not
    speech in general"),
  * any "not the phrase" clips the user recorded.

Everything model/TTS/audio-touching is injected as callables
(``synthesize_fn``, ``make_scorer``) so this module is unit-testable with stubs
and never imports torch, kokoro, or onnxruntime itself. The route layer supplies
the real Kokoro adapter (24 kHz -> 16 kHz mono) and the real backbone scorer.
"""

import numpy as np

import wake_trainer

# Decoy phrases for synthetic negatives — ordinary words/short phrases that are
# NOT a wake phrase, so the classifier learns the phrase rather than "any
# speech". Kept generic and license-free (plain English).
DEFAULT_NEGATIVE_PHRASES = (
    "hello there", "what time is it", "open the door", "thank you very much",
    "the weather today", "let me think about it", "one two three four",
    "good morning everyone", "see you later", "how are you doing",
    "turn it up", "never mind that", "play some music", "add it to the list",
)

# Speed multipliers for augmentation. Kokoro renders each natively; the stub
# ignores the arg. 1.0 always included so an un-augmented rendering exists.
DEFAULT_SPEEDS = (0.9, 1.0, 1.15)


def _windows_from_audio(audio, make_scorer, stride):
    scorer = make_scorer()
    return wake_trainer.extract_feature_windows(scorer, audio, stride=stride)


def synthetic_windows(phrases, voices, synthesize_fn, make_scorer, *,
                      speeds=DEFAULT_SPEEDS, stride=1):
    """Render every (phrase x voice x speed) with ``synthesize_fn`` and return
    the stacked ``(M, 16, 96)`` feature windows. ``synthesize_fn(text, voice,
    speed) -> float32 mono 16 kHz`` (or None/empty to skip a combo)."""
    collected = []
    for phrase in phrases:
        for voice in voices:
            for speed in speeds:
                try:
                    audio = synthesize_fn(phrase, voice, speed)
                except Exception:
                    audio = None
                if audio is None:
                    continue
                audio = np.asarray(audio, dtype=np.float32).reshape(-1)
                if audio.size == 0:
                    continue
                w = _windows_from_audio(audio, make_scorer, stride)
                if w.shape[0] > 0:
                    collected.append(w)
    if not collected:
        return np.zeros((0, wake_trainer.EMBED_WINDOW, wake_trainer.EMBED_DIM), dtype=np.float32)
    return np.concatenate(collected, axis=0)


def windows_from_clips(clips, make_scorer, *, stride=1):
    """Feature windows for a list of already-16 kHz-mono float32 clips (the
    user's own recordings)."""
    collected = []
    for clip in clips or ():
        clip = np.asarray(clip, dtype=np.float32).reshape(-1)
        if clip.size == 0:
            continue
        w = _windows_from_audio(clip, make_scorer, stride)
        if w.shape[0] > 0:
            collected.append(w)
    if not collected:
        return np.zeros((0, wake_trainer.EMBED_WINDOW, wake_trainer.EMBED_DIM), dtype=np.float32)
    return np.concatenate(collected, axis=0)


def build_training_set(
    phrase,
    voices,
    synthesize_fn,
    make_scorer,
    *,
    user_positive_clips=None,
    user_negative_clips=None,
    negative_phrases=DEFAULT_NEGATIVE_PHRASES,
    speeds=DEFAULT_SPEEDS,
    eval_fraction=0.25,
    seed=0,
):
    """Gather all windows and split into train/eval sets.

    Returns ``(train_pos, train_neg, eval_pos, eval_neg)`` — the first two feed
    :func:`wake_trainer.train_classifier`, the last two feed
    :func:`wake_trainer.calibrate` (held-out, so the reliability verdict isn't
    self-graded on training data). Raises ``ValueError`` when a class ends up
    empty, so the caller can tell the user exactly what's missing.
    """
    pos = [
        windows_from_clips(user_positive_clips, make_scorer),
        synthetic_windows([phrase], voices, synthesize_fn, make_scorer, speeds=speeds),
    ]
    neg = [
        windows_from_clips(user_negative_clips, make_scorer),
        synthetic_windows(list(negative_phrases), voices, synthesize_fn, make_scorer, speeds=speeds),
    ]
    pos_windows = _concat(pos)
    neg_windows = _concat(neg)
    if pos_windows.shape[0] == 0:
        raise ValueError("no positive windows — record the phrase or check TTS voices")
    if neg_windows.shape[0] == 0:
        raise ValueError("no negative windows — check TTS voices / decoy phrases")

    train_pos, eval_pos = _split(pos_windows, eval_fraction, seed)
    train_neg, eval_neg = _split(neg_windows, eval_fraction, seed + 1)
    return train_pos, train_neg, eval_pos, eval_neg


def _concat(parts):
    parts = [p for p in parts if p.shape[0] > 0]
    if not parts:
        return np.zeros((0, wake_trainer.EMBED_WINDOW, wake_trainer.EMBED_DIM), dtype=np.float32)
    return np.concatenate(parts, axis=0)


def _split(windows, eval_fraction, seed):
    """Shuffle then split into (train, eval). Guarantees at least one eval
    sample when there are >=2 windows, so calibration always has held-out data."""
    n = windows.shape[0]
    rng = np.random.default_rng(seed)
    idx = rng.permutation(n)
    n_eval = int(round(n * eval_fraction))
    if n >= 2:
        n_eval = min(max(1, n_eval), n - 1)
    else:
        n_eval = 0
    eval_idx, train_idx = idx[:n_eval], idx[n_eval:]
    return windows[train_idx], windows[eval_idx]
