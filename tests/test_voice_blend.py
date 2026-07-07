import unittest

import numpy as np

from voice_blend import blend_many, blend_voices, clamp_weight, validate_blend_request


class ClampWeightTests(unittest.TestCase):
    def test_within_range(self):
        self.assertEqual(clamp_weight(0.3), 0.3)

    def test_clamps_out_of_range(self):
        self.assertEqual(clamp_weight(-1.0), 0.0)
        self.assertEqual(clamp_weight(5.0), 1.0)

    def test_non_numeric_falls_back(self):
        self.assertEqual(clamp_weight("nope"), 0.5)
        self.assertEqual(clamp_weight(None), 0.5)
        self.assertEqual(clamp_weight(float("nan")), 0.5)


class BlendVoicesTests(unittest.TestCase):
    def setUp(self):
        self.a = np.zeros((2, 4), dtype=np.float32)
        self.b = np.ones((2, 4), dtype=np.float32)

    def test_weight_zero_returns_a(self):
        np.testing.assert_allclose(blend_voices(self.a, self.b, 0.0), self.a)

    def test_weight_one_returns_b(self):
        np.testing.assert_allclose(blend_voices(self.a, self.b, 1.0), self.b)

    def test_half_is_mean(self):
        np.testing.assert_allclose(blend_voices(self.a, self.b, 0.5), np.full((2, 4), 0.5))

    def test_weight_clamped(self):
        # weight 2.0 clamps to 1.0 -> returns b
        np.testing.assert_allclose(blend_voices(self.a, self.b, 2.0), self.b)

    def test_shape_mismatch_raises(self):
        with self.assertRaises(ValueError):
            blend_voices(self.a, np.ones((3, 4), dtype=np.float32))

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            blend_voices(np.array([]), self.b)

    def test_result_is_float32(self):
        self.assertEqual(blend_voices(self.a, self.b, 0.5).dtype, np.float32)


class BlendManyTests(unittest.TestCase):
    def test_equal_weighting_default(self):
        vecs = [np.zeros((3,), dtype=np.float32), np.full((3,), 2.0, dtype=np.float32)]
        np.testing.assert_allclose(blend_many(vecs), np.full((3,), 1.0))

    def test_explicit_weights_normalized(self):
        vecs = [np.zeros((2,), dtype=np.float32), np.full((2,), 4.0, dtype=np.float32)]
        # weights [1, 3] -> normalized [0.25, 0.75] -> 0.75 * 4 = 3.0
        np.testing.assert_allclose(blend_many(vecs, weights=[1, 3]), np.full((2,), 3.0))

    def test_all_zero_weights_fall_back_to_uniform(self):
        vecs = [np.zeros((2,), dtype=np.float32), np.full((2,), 2.0, dtype=np.float32)]
        np.testing.assert_allclose(blend_many(vecs, weights=[0, 0]), np.full((2,), 1.0))

    def test_negative_weights_clipped(self):
        vecs = [np.zeros((2,), dtype=np.float32), np.full((2,), 2.0, dtype=np.float32)]
        # [-5, 1] -> clipped [0, 1] -> all weight on second vector
        np.testing.assert_allclose(blend_many(vecs, weights=[-5, 1]), np.full((2,), 2.0))

    def test_nway_three_vectors(self):
        vecs = [np.full((2,), v, dtype=np.float32) for v in (0.0, 3.0, 6.0)]
        np.testing.assert_allclose(blend_many(vecs), np.full((2,), 3.0))

    def test_higher_dim_tensors(self):
        vecs = [np.zeros((2, 1, 4), dtype=np.float32), np.ones((2, 1, 4), dtype=np.float32)]
        np.testing.assert_allclose(blend_many(vecs), np.full((2, 1, 4), 0.5))

    def test_shape_mismatch_raises(self):
        with self.assertRaises(ValueError):
            blend_many([np.zeros((2,)), np.zeros((3,))])

    def test_empty_input_raises(self):
        with self.assertRaises(ValueError):
            blend_many([])

    def test_wrong_weight_length_raises(self):
        with self.assertRaises(ValueError):
            blend_many([np.zeros((2,)), np.ones((2,))], weights=[1.0])


class ValidateBlendRequestTests(unittest.TestCase):
    def test_ok(self):
        ok, _ = validate_blend_request(["af_heart", "af_bella"], weights=[0.5, 0.5])
        self.assertTrue(ok)

    def test_needs_two(self):
        ok, msg = validate_blend_request(["af_heart"])
        self.assertFalse(ok)
        self.assertIn("two", msg.lower())

    def test_empty_names(self):
        ok, _ = validate_blend_request([])
        self.assertFalse(ok)

    def test_blank_name_rejected(self):
        ok, _ = validate_blend_request(["af_heart", "  "])
        self.assertFalse(ok)

    def test_weight_length_mismatch(self):
        ok, _ = validate_blend_request(["a", "b"], weights=[1.0])
        self.assertFalse(ok)

    def test_negative_weight_rejected(self):
        ok, _ = validate_blend_request(["a", "b"], weights=[-1.0, 2.0])
        self.assertFalse(ok)

    def test_all_zero_weights_rejected(self):
        ok, _ = validate_blend_request(["a", "b"], weights=[0.0, 0.0])
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
