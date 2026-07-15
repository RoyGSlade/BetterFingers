import unittest

import numpy as np

import wake_training_data as wtd
import wake_trainer as wt


class _StubScorer:
    """WakeScorer-shaped: turns pushed audio into a feature buffer whose values
    encode whether the clip was a 'positive' (high) or 'negative' (low) clip, so
    the assembled windows are separable without any real backbone."""

    def __init__(self):
        self._buffer = np.zeros((0, 96), dtype=np.float32)

    def reset(self):
        self._buffer = np.zeros((0, 96), dtype=np.float32)

    def push_audio(self, chunk):
        chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)
        # The stub synth encodes its label in the DC level of the clip; map ~20
        # frames off it so every clip yields several windows.
        level = float(np.mean(chunk)) if chunk.size else 0.0
        self._buffer = np.full((20, 96), level, dtype=np.float32)

    def all_feature_windows(self, n_frames, stride=1):
        total = self._buffer.shape[0]
        if total < n_frames:
            return np.zeros((0, n_frames, 96), dtype=np.float32)
        starts = range(0, total - n_frames + 1, max(1, stride))
        return np.stack([self._buffer[s:s + n_frames] for s in starts], axis=0)


def _make_scorer():
    return _StubScorer()


def _synth(text, voice, speed):
    # Positive phrase renders as high-DC audio; decoys render low-DC. Voice/speed
    # nudge the level slightly so augmentation produces distinct-but-close windows.
    base = 1.0 if text == "hey fingers" else -1.0
    jitter = (hash((voice, round(speed, 2))) % 7) * 1e-3
    return np.full(4000, base + jitter, dtype=np.float32)


class SyntheticWindowsTests(unittest.TestCase):
    def test_renders_every_combo(self):
        w = wtd.synthetic_windows(
            ["hey fingers"], ["v1", "v2"], _synth, _make_scorer, speeds=(1.0, 1.1)
        )
        # 1 phrase x 2 voices x 2 speeds x 5 windows each = 20.
        self.assertEqual(w.shape, (20, 16, 96))

    def test_skips_failed_synthesis(self):
        def flaky(text, voice, speed):
            if voice == "bad":
                raise RuntimeError("tts failed")
            return _synth(text, voice, speed)

        w = wtd.synthetic_windows(["hey fingers"], ["good", "bad"], flaky, _make_scorer, speeds=(1.0,))
        self.assertEqual(w.shape[0], 5)  # only the good voice contributed

    def test_none_audio_skipped(self):
        w = wtd.synthetic_windows(["x"], ["v"], lambda *a: None, _make_scorer)
        self.assertEqual(w.shape[0], 0)


class BuildTrainingSetTests(unittest.TestCase):
    def test_produces_separable_train_and_heldout_eval(self):
        train_pos, train_neg, eval_pos, eval_neg = wtd.build_training_set(
            "hey fingers", ["v1", "v2"], _synth, _make_scorer,
            negative_phrases=("hello there", "what time is it"), speeds=(1.0, 1.1),
        )
        for part in (train_pos, train_neg):
            self.assertGreater(part.shape[0], 0)
        # Held-out eval exists (calibration must not self-grade on train data).
        self.assertGreater(eval_pos.shape[0], 0)
        self.assertGreater(eval_neg.shape[0], 0)

        # End-to-end: the assembled set trains a working head.
        weights = wt.train_classifier(train_pos, train_neg, epochs=250)
        pos_scores = wt.score_windows(weights, eval_pos)
        neg_scores = wt.score_windows(weights, eval_neg)
        result = wt.calibrate(pos_scores, neg_scores)
        self.assertIn(result["verdict"], ("reliable", "noisy"))

    def test_user_clips_count_as_positives(self):
        pos_clip = np.full(4000, 1.0, dtype=np.float32)
        train_pos, _, _, _ = wtd.build_training_set(
            "hey fingers", ["v1"], _synth, _make_scorer,
            user_positive_clips=[pos_clip], negative_phrases=("hello there",), speeds=(1.0,),
        )
        self.assertGreater(train_pos.shape[0], 0)

    def test_empty_positive_raises_actionable(self):
        with self.assertRaises(ValueError):
            wtd.build_training_set(
                "hey fingers", [], lambda *a: None, _make_scorer,
                negative_phrases=("hello there",),
            )


if __name__ == "__main__":
    unittest.main()
