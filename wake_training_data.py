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
    collected = _synthetic_window_groups(
        phrases,
        voices,
        synthesize_fn,
        make_scorer,
        speeds=speeds,
        stride=stride,
    )
    return _concat(collected)


def _synthetic_window_groups(phrases, voices, synthesize_fn, make_scorer, *,
                             speeds=DEFAULT_SPEEDS, stride=1):
    """Return one feature-window array per independently rendered utterance.

    Keeping the utterance boundary lets :func:`build_training_set` hold out
    entire renders.  Randomly splitting their heavily-overlapping windows made
    calibration see near-copies of training examples and report fantasy-grade
    reliability.
    """
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
    return collected


def windows_from_clips(clips, make_scorer, *, stride=1):
    """Feature windows for a list of already-16 kHz-mono float32 clips (the
    user's own recordings)."""
    return _concat(_clip_window_groups(clips, make_scorer, stride=stride))


def _clip_window_groups(clips, make_scorer, *, stride=1):
    """Return one feature-window array per recorded clip."""
    collected = []
    for clip in clips or ():
        clip = np.asarray(clip, dtype=np.float32).reshape(-1)
        if clip.size == 0:
            continue
        w = _windows_from_audio(clip, make_scorer, stride)
        if w.shape[0] > 0:
            collected.append(w)
    return collected


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
    pos_groups = [
        *_clip_window_groups(user_positive_clips, make_scorer),
        *_synthetic_window_groups(
            [phrase], voices, synthesize_fn, make_scorer, speeds=speeds
        ),
    ]
    neg_groups = [
        *_clip_window_groups(user_negative_clips, make_scorer),
        *_synthetic_window_groups(
            list(negative_phrases), voices, synthesize_fn, make_scorer, speeds=speeds
        ),
    ]
    if not pos_groups:
        raise ValueError("no positive windows — record the phrase or check TTS voices")
    if not neg_groups:
        raise ValueError("no negative windows — check TTS voices / decoy phrases")

    train_pos, eval_pos = _split_groups(pos_groups, eval_fraction, seed, "positive")
    train_neg, eval_neg = _split_groups(neg_groups, eval_fraction, seed + 1, "negative")
    return train_pos, train_neg, eval_pos, eval_neg


def _concat(parts):
    parts = [p for p in parts if p.shape[0] > 0]
    if not parts:
        return np.zeros((0, wake_trainer.EMBED_WINDOW, wake_trainer.EMBED_DIM), dtype=np.float32)
    return np.concatenate(parts, axis=0)


def _split_groups(groups, eval_fraction, seed, label):
    """Split whole utterance groups, then concatenate each side.

    At least two independently captured/rendered utterances are required for a
    leakage-free held-out set.  We fail honestly instead of quietly grading a
    model on overlapping windows from the same clip.
    """
    normalized = []
    for group in groups:
        group = np.asarray(group, dtype=np.float32)
        if group.shape[0] > 0:
            normalized.append(group)
    groups = normalized
    if len(groups) < 2:
        raise ValueError(
            f"need at least two independent {label} utterances for leakage-free evaluation"
        )
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(groups))
    n_eval = int(round(len(groups) * eval_fraction))
    n_eval = min(max(1, n_eval), len(groups) - 1)
    eval_ids = order[:n_eval]
    train_ids = order[n_eval:]
    return _concat([groups[i] for i in train_ids]), _concat([groups[i] for i in eval_ids])
