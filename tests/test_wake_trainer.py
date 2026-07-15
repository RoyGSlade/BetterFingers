import os
import tempfile
import unittest

import numpy as np

import wake_trainer as wt


def _make_separable(n, center, spread=0.15, seed=0):
    """Synthetic (n, 16, 96) feature windows clustered around `center` — stands
    in for real embedding windows so the trainer/calibrator are testable with
    no audio, models, or TTS."""
    rng = np.random.default_rng(seed)
    return (center + spread * rng.standard_normal((n, wt.EMBED_WINDOW, wt.EMBED_DIM))).astype(np.float32)


class TrainClassifierTests(unittest.TestCase):
    def test_learns_a_separable_boundary(self):
        pos = _make_separable(40, center=1.0, seed=1)
        neg = _make_separable(40, center=-1.0, seed=2)
        weights = wt.train_classifier(pos, neg, epochs=300)

        pos_scores = wt.score_windows(weights, pos)
        neg_scores = wt.score_windows(weights, neg)
        # Cleanly separable data -> positives score high, negatives low.
        self.assertGreater(pos_scores.mean(), 0.8)
        self.assertLess(neg_scores.mean(), 0.2)

    def test_requires_both_classes(self):
        pos = _make_separable(5, center=1.0)
        with self.assertRaises(ValueError):
            wt.train_classifier(pos, np.zeros((0, 16, 96)))
        with self.assertRaises(ValueError):
            wt.train_classifier(np.zeros((0, 16, 96)), pos)

    def test_class_balancing_handles_lopsided_counts(self):
        # Many negatives, few positives: balanced weighting must still learn the
        # positive class instead of collapsing to "always negative".
        pos = _make_separable(6, center=1.0, seed=3)
        neg = _make_separable(200, center=-1.0, seed=4)
        weights = wt.train_classifier(pos, neg, epochs=300)
        self.assertGreater(wt.score_windows(weights, pos).mean(), 0.7)

    def test_accepts_flattened_windows(self):
        pos = _make_separable(20, center=1.0).reshape(20, wt.FEATURE_LEN)
        neg = _make_separable(20, center=-1.0).reshape(20, wt.FEATURE_LEN)
        weights = wt.train_classifier(pos, neg, epochs=200)
        self.assertEqual(wt.score_windows(weights, pos).shape, (20,))

    def test_rejects_wrong_shape(self):
        with self.assertRaises(ValueError):
            wt.train_classifier(np.zeros((3, 10)), np.zeros((3, 10)))


class NumpyClassifierSessionTests(unittest.TestCase):
    """The session must be a drop-in for the onnxruntime surface
    OpenWakeWordDetector.predict() calls."""

    def setUp(self):
        pos = _make_separable(30, center=1.0, seed=5)
        neg = _make_separable(30, center=-1.0, seed=6)
        self.weights = wt.train_classifier(pos, neg, epochs=250)

    def test_session_matches_detector_call_contract(self):
        session = wt.NumpyClassifierSession(self.weights)
        # Exactly what wake_word.OpenWakeWordDetector.predict does:
        name = session.get_inputs()[0].name
        features = _make_separable(1, center=1.0, seed=7)  # (1, 16, 96)
        output = session.run(None, {name: features})
        score = float(np.asarray(output[0]).reshape(-1)[0])
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)
        self.assertGreater(score, 0.5)  # a positive-cluster window

    def test_session_agrees_with_score_windows(self):
        session = wt.NumpyClassifierSession(self.weights)
        w = _make_separable(1, center=-1.0, seed=8)
        via_session = float(np.asarray(session.run(None, {"features": w})[0]).reshape(-1)[0])
        via_helper = float(wt.score_windows(self.weights, w)[0])
        self.assertAlmostEqual(via_session, via_helper, places=5)


class CalibrateTests(unittest.TestCase):
    def test_reliable_when_cleanly_separated(self):
        result = wt.calibrate(pos_scores=[0.9, 0.95, 0.88, 0.92], neg_scores=[0.05, 0.1, 0.02, 0.08])
        self.assertEqual(result["verdict"], "reliable")
        self.assertTrue(0.1 < result["threshold"] < 0.9)
        self.assertLessEqual(result["fa_rate"], 0.05)
        self.assertLessEqual(result["fr_rate"], 0.10)

    def test_noisy_when_overlapping(self):
        result = wt.calibrate(pos_scores=[0.6, 0.55, 0.7, 0.45], neg_scores=[0.4, 0.5, 0.35, 0.3])
        self.assertIn(result["verdict"], ("noisy", "unusable"))

    def test_unusable_when_inseparable(self):
        result = wt.calibrate(pos_scores=[0.5, 0.5, 0.5], neg_scores=[0.5, 0.5, 0.5])
        self.assertEqual(result["verdict"], "unusable")

    def test_empty_scores_is_unusable_not_crash(self):
        self.assertEqual(wt.calibrate([], [0.1])["verdict"], "unusable")


class PersistenceTests(unittest.TestCase):
    def test_save_load_round_trip_preserves_scores(self):
        pos = _make_separable(20, center=1.0, seed=9)
        neg = _make_separable(20, center=-1.0, seed=10)
        weights = wt.train_classifier(pos, neg, epochs=200)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "phrase.npz")
            wt.save_model(path, weights, metadata={"phrase": "hey fingers", "verdict": "reliable"})
            loaded = wt.load_model(path)
        before = wt.score_windows(weights, pos)
        after = wt.score_windows(loaded, pos)
        np.testing.assert_allclose(before, after, rtol=1e-5, atol=1e-6)
        self.assertEqual(loaded["meta"]["phrase"], "hey fingers")
        self.assertEqual(loaded["meta"]["embed_window"], wt.EMBED_WINDOW)

    def test_save_is_atomic_no_tmp_left(self):
        pos = _make_separable(10, center=1.0)
        neg = _make_separable(10, center=-1.0)
        weights = wt.train_classifier(pos, neg, epochs=100)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "m.npz")
            wt.save_model(path, weights)
            self.assertTrue(os.path.exists(path))
            self.assertFalse(os.path.exists(path + ".tmp"))


class ExtractFeatureWindowsTests(unittest.TestCase):
    """extract_feature_windows drives any WakeScorer-shaped object; here a stub
    that yields a fixed feature buffer, so no real backbone/audio is needed."""

    class _StubScorer:
        def __init__(self, buffer):
            self._buffer = np.asarray(buffer, dtype=np.float32)
            self._pushed = None

        def reset(self):
            self._pushed = None

        def push_audio(self, chunk):
            self._pushed = chunk

        def all_feature_windows(self, n_frames, stride=1):
            total = self._buffer.shape[0]
            if total < n_frames:
                return np.zeros((0, n_frames, 96), dtype=np.float32)
            starts = range(0, total - n_frames + 1, max(1, stride))
            return np.stack([self._buffer[s:s + n_frames] for s in starts], axis=0)

    def test_slides_over_buffer(self):
        buffer = np.random.default_rng(0).standard_normal((20, 96)).astype(np.float32)
        scorer = self._StubScorer(buffer)
        windows = wt.extract_feature_windows(scorer, np.zeros(16000, dtype=np.float32))
        # 20 frames, window 16 -> 5 windows.
        self.assertEqual(windows.shape, (5, 16, 96))

    def test_short_clip_yields_no_windows(self):
        scorer = self._StubScorer(np.zeros((8, 96), dtype=np.float32))
        windows = wt.extract_feature_windows(scorer, np.zeros(4000, dtype=np.float32))
        self.assertEqual(windows.shape[0], 0)


if __name__ == "__main__":
    unittest.main()
