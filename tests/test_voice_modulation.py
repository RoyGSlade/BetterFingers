import unittest

import numpy as np

from voice_modulation import (
    apply_energy_gain,
    apply_modulation,
    apply_warmth_brightness,
    pitch_shift_semitones,
)


class PitchShiftTests(unittest.TestCase):
    def setUp(self):
        # A short synthetic tone, not silence/zeros, so resample artifacts
        # are exercised (all-zero input is a degenerate case).
        t = np.linspace(0, 1, 2400, endpoint=False)
        self.audio = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)

    def test_zero_semitones_is_exact_noop(self):
        result = pitch_shift_semitones(self.audio, 24000, 0.0)
        np.testing.assert_array_equal(result, self.audio.astype(np.float32))

    def test_output_length_matches_input(self):
        for semitones in (-12, -3.5, 0.1, 7, 12, 50):
            result = pitch_shift_semitones(self.audio, 24000, semitones)
            self.assertEqual(len(result), len(self.audio))

    def test_odd_length_input_preserved(self):
        odd = self.audio[:-1]  # odd length
        self.assertEqual(len(odd) % 2, 1)
        result = pitch_shift_semitones(odd, 24000, 5.0)
        self.assertEqual(len(result), len(odd))

    def test_clamps_beyond_max(self):
        over = pitch_shift_semitones(self.audio, 24000, 100.0)
        at_max = pitch_shift_semitones(self.audio, 24000, 12.0)
        np.testing.assert_allclose(over, at_max)

        under = pitch_shift_semitones(self.audio, 24000, -100.0)
        at_min = pitch_shift_semitones(self.audio, 24000, -12.0)
        np.testing.assert_allclose(under, at_min)

    def test_non_numeric_falls_back_to_noop(self):
        result = pitch_shift_semitones(self.audio, 24000, "nope")
        np.testing.assert_array_equal(result, self.audio.astype(np.float32))

    def test_empty_audio(self):
        result = pitch_shift_semitones(np.array([]), 24000, 5.0)
        self.assertEqual(result.size, 0)

    def test_result_is_float32(self):
        result = pitch_shift_semitones(self.audio, 24000, 4.0)
        self.assertEqual(result.dtype, np.float32)


class EnergyGainTests(unittest.TestCase):
    def setUp(self):
        self.audio = np.full(100, 0.2, dtype=np.float32)

    def test_unity_gain_is_exact_noop(self):
        result = apply_energy_gain(self.audio, 0.5)
        np.testing.assert_array_equal(result, self.audio)

    def test_low_energy_quieter(self):
        result = apply_energy_gain(self.audio, 0.0)
        np.testing.assert_allclose(result, self.audio * 0.5)

    def test_high_energy_louder(self):
        result = apply_energy_gain(self.audio, 1.0)
        np.testing.assert_allclose(result, self.audio * 1.5)

    def test_clamped_to_0_1(self):
        over = apply_energy_gain(self.audio, 5.0)
        at_max = apply_energy_gain(self.audio, 1.0)
        np.testing.assert_allclose(over, at_max)

    def test_soft_limits_near_clipping_instead_of_hard_clip(self):
        loud = np.full(50, 0.9, dtype=np.float32)
        result = apply_energy_gain(loud, 1.0)  # 0.9 * 1.5 = 1.35 -> would clip
        self.assertTrue(np.all(np.abs(result) < 1.0))
        # Soft limiter, not zero/silence.
        self.assertTrue(np.all(np.abs(result) > 0.5))

    def test_non_numeric_falls_back_to_unity(self):
        result = apply_energy_gain(self.audio, "nope")
        np.testing.assert_array_equal(result, self.audio)

    def test_empty_audio(self):
        result = apply_energy_gain(np.array([]), 0.8)
        self.assertEqual(result.size, 0)


class WarmthBrightnessTests(unittest.TestCase):
    def setUp(self):
        t = np.linspace(0, 1, 2400, endpoint=False)
        self.low_tone = (0.3 * np.sin(2 * np.pi * 150 * t)).astype(np.float32)
        self.high_tone = (0.3 * np.sin(2 * np.pi * 6000 * t)).astype(np.float32)

    def test_neutral_is_noop(self):
        result = apply_warmth_brightness(self.low_tone, 24000, 0.0, 0.0)
        np.testing.assert_array_equal(result, self.low_tone.astype(np.float32))

    def test_warmth_boosts_low_frequency_energy(self):
        boosted = apply_warmth_brightness(self.low_tone, 24000, 1.0, 0.0)
        rms_before = np.sqrt(np.mean(self.low_tone.astype(np.float64) ** 2))
        rms_after = np.sqrt(np.mean(boosted.astype(np.float64) ** 2))
        self.assertGreater(rms_after, rms_before)

    def test_brightness_boosts_high_frequency_energy(self):
        boosted = apply_warmth_brightness(self.high_tone, 24000, 0.0, 1.0)
        rms_before = np.sqrt(np.mean(self.high_tone.astype(np.float64) ** 2))
        rms_after = np.sqrt(np.mean(boosted.astype(np.float64) ** 2))
        self.assertGreater(rms_after, rms_before)

    def test_clamped_to_0_1(self):
        over = apply_warmth_brightness(self.low_tone, 24000, 5.0, 0.0)
        at_max = apply_warmth_brightness(self.low_tone, 24000, 1.0, 0.0)
        np.testing.assert_allclose(over, at_max)

    def test_result_length_and_dtype(self):
        result = apply_warmth_brightness(self.low_tone, 24000, 0.5, 0.5)
        self.assertEqual(len(result), len(self.low_tone))
        self.assertEqual(result.dtype, np.float32)

    def test_empty_audio(self):
        result = apply_warmth_brightness(np.array([]), 24000, 0.5, 0.5)
        self.assertEqual(result.size, 0)


class ApplyModulationTests(unittest.TestCase):
    def setUp(self):
        self.audio = np.full(200, 0.2, dtype=np.float32)

    def test_none_settings_is_noop(self):
        result = apply_modulation(self.audio, 24000, None)
        np.testing.assert_array_equal(result, self.audio)

    def test_empty_settings_is_noop(self):
        result = apply_modulation(self.audio, 24000, {})
        np.testing.assert_array_equal(result, self.audio)

    def test_neutral_settings_is_noop(self):
        result = apply_modulation(
            self.audio, 24000,
            {"pitch": 0.0, "energy": 0.5, "warmth": 0.0, "brightness": 0.0},
        )
        np.testing.assert_array_equal(result, self.audio)

    def test_energy_only_matches_direct_call(self):
        via_orchestrator = apply_modulation(self.audio, 24000, {"energy": 1.0})
        direct = apply_energy_gain(self.audio, 1.0)
        np.testing.assert_allclose(via_orchestrator, direct)

    def test_ignores_pause_style_and_stability(self):
        # These keys are handled elsewhere (text-domain / inert); make sure
        # their presence doesn't raise or change audio-only behavior.
        result = apply_modulation(
            self.audio, 24000,
            {"pause_style": "dramatic", "stability": 0.9},
        )
        np.testing.assert_array_equal(result, self.audio)


if __name__ == "__main__":
    unittest.main()
