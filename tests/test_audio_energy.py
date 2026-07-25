"""Tests for backend.services.audio_energy.rms_windows.

The contract this protects: the function returns loudness numbers only, never
raises on the dictation path, and stays bounded for long recordings. A failure
here means either a transcription can be killed by a bad audio frame, or
`arousal` silently goes back to being a pace metric.
"""

import math

import numpy as np
import pytest

from backend.services.audio_energy import DEFAULT_WINDOW_MS, MAX_WINDOWS, rms_windows


def _tone(seconds: float, amplitude: float, sample_rate: int = 16000) -> np.ndarray:
    return np.full(int(sample_rate * seconds), amplitude, dtype=np.float32)


class TestEmptyAndInvalidInput:
    """Never raise on the dictation path -- degrade to []."""

    @pytest.mark.parametrize(
        "audio",
        [None, np.array([], dtype=np.float32), []],
    )
    def test_empty_inputs_return_empty_list(self, audio):
        assert rms_windows(audio) == []

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"sample_rate": 0},
            {"sample_rate": -16000},
            {"window_ms": 0},
            {"window_ms": -5.0},
            {"max_windows": 0},
        ],
    )
    def test_nonsense_parameters_return_empty_rather_than_raising(self, kwargs):
        assert rms_windows(_tone(1.0, 0.1), **kwargs) == []


class TestRmsCorrectness:
    def test_constant_amplitude_yields_that_amplitude(self):
        values = rms_windows(_tone(1.0, 0.25))
        assert values
        assert all(v == pytest.approx(0.25, abs=1e-6) for v in values)

    def test_silence_is_zero_not_absent(self):
        values = rms_windows(_tone(0.5, 0.0))
        assert values
        assert all(v == 0.0 for v in values)

    def test_window_count_follows_duration_and_window_size(self):
        # 1s of 16kHz audio at 100ms windows -> 10 windows.
        assert len(rms_windows(_tone(1.0, 0.1), window_ms=DEFAULT_WINDOW_MS)) == 10
        assert len(rms_windows(_tone(1.0, 0.1), window_ms=250.0)) == 4

    def test_loud_and_quiet_halves_are_distinguishable(self):
        audio = np.concatenate([_tone(0.5, 0.02), _tone(0.5, 0.6)])
        values = rms_windows(audio)
        assert min(values) == pytest.approx(0.02, abs=1e-6)
        assert max(values) == pytest.approx(0.6, abs=1e-6)

    def test_clip_shorter_than_one_window_is_a_single_window(self):
        # 10ms at 16kHz = 160 samples, far shorter than a 100ms window.
        values = rms_windows(_tone(0.01, 0.4))
        assert len(values) == 1
        assert values[0] == pytest.approx(0.4, abs=1e-6)


class TestRobustness:
    def test_non_finite_samples_are_zeroed_not_propagated(self):
        audio = _tone(1.0, 0.3).copy()
        audio[0] = np.nan
        audio[1] = np.inf
        audio[2] = -np.inf
        values = rms_windows(audio)
        assert values
        assert all(math.isfinite(v) for v in values), "a bad frame poisoned the statistic"
        assert all(v >= 0.0 for v in values)

    def test_negative_samples_do_not_produce_negative_rms(self):
        # A normal waveform swings negative; RMS must stay non-negative.
        audio = np.linspace(-1.0, 1.0, 16000, dtype=np.float32)
        values = rms_windows(audio)
        assert values
        assert all(v >= 0.0 for v in values)

    def test_accepts_a_plain_list(self):
        assert rms_windows([0.5] * 16000) == pytest.approx([0.5] * 10, abs=1e-6)


class TestLongRecordingBound:
    def test_window_count_stays_bounded_for_a_long_recording(self):
        # 60 minutes is an explicitly supported case; at fixed 100ms windows
        # that would be 36,000 entries.
        long_audio = _tone(60 * 60, 0.1)
        values = rms_windows(long_audio)
        assert len(values) <= MAX_WINDOWS

    def test_long_recording_is_widened_not_truncated(self):
        # The tail must still be represented: a recording that is quiet for its
        # first half and loud for its second must report both.
        audio = np.concatenate([_tone(30 * 60, 0.01), _tone(30 * 60, 0.5)])
        values = rms_windows(audio)
        assert len(values) <= MAX_WINDOWS
        assert max(values) == pytest.approx(0.5, abs=1e-3), "the loud tail was truncated away"
        assert min(values) == pytest.approx(0.01, abs=1e-3)


class TestNoLeakage:
    def test_output_is_plain_floats_only(self):
        values = rms_windows(_tone(1.0, 0.2))
        assert values
        assert all(type(v) is float for v in values), "must be JSON-safe plain floats, not np.float32"
