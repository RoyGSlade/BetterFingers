"""Kokoro TTS audio modulation — pure numpy/scipy post-synthesis DSP.

Cheap, dependency-light (numpy + scipy, already core deps — no librosa)
transforms applied to a fully-generated audio buffer: pitch shift, loudness
("energy") gain, and warmth/brightness tone shelving. These are intentionally
simple "quick nudge" sliders, not professional-grade audio restoration —
mirrors this repo's existing "DEFERRED (audio-DSP, heavier)" stance on
streaming/crossfade/loudness-normalization (see docs/MASTER_PLAN.md, U5).

`stability` has no function here: Kokoro's ONNX style-vector lookup has no
exposed sampling temperature to modulate. It's a stored-only persona field
(see llm_engine.py), same treatment as `model_hint`.

Knows nothing about Kokoro, sounddevice, or playback — takes/returns plain
numpy arrays so it is fully unit-testable in isolation, mirroring
voice_blend.py's style.
"""
import numpy as np
from scipy import signal

MAX_PITCH_SEMITONES = 12.0


def pitch_shift_semitones(audio, sample_rate, semitones):
    """Shift pitch by `semitones` (clamped to +/-12), preserving duration.

    Two-pass resample: shift the sample rate to change pitch (and duration),
    then resample back to the original sample count to restore duration/
    tempo. This is the standard cheap-DSP approach without a phase vocoder;
    it introduces timbre artifacts at larger shifts (chipmunk/deep-voice
    coloring), an accepted tradeoff for a "quick nudge" slider. Output length
    always exactly matches input length.
    """
    arr = np.asarray(audio, dtype=np.float32)
    try:
        semitones = float(semitones)
    except (TypeError, ValueError):
        semitones = 0.0
    if not np.isfinite(semitones):
        semitones = 0.0
    semitones = max(-MAX_PITCH_SEMITONES, min(MAX_PITCH_SEMITONES, semitones))

    n = arr.size
    if n == 0 or abs(semitones) < 1e-6:
        return arr

    rate_factor = 2.0 ** (semitones / 12.0)
    n_shifted = max(1, int(round(n / rate_factor)))
    shifted = signal.resample(arr, n_shifted)
    restored = signal.resample(shifted, n)
    return restored.astype(np.float32)


def apply_energy_gain(audio, energy):
    """Scale loudness by `energy` (0..1, 0.5 = unity gain: 0 -> 0.5x quieter,
    1 -> 1.5x louder). Soft-limits via tanh only when the scaled peak would
    otherwise clip full scale — unity gain on normal-level audio is an exact
    no-op, tanh is only invoked to avoid hard-clip distortion at high gain.
    """
    try:
        energy = float(energy)
    except (TypeError, ValueError):
        energy = 0.5
    if not np.isfinite(energy):
        energy = 0.5
    energy = max(0.0, min(1.0, energy))

    arr = np.asarray(audio, dtype=np.float32)
    if arr.size == 0:
        return arr

    gain = 0.5 + energy
    scaled = arr * gain
    peak = float(np.max(np.abs(scaled))) if scaled.size else 0.0
    if peak > 0.98:
        scaled = np.tanh(scaled)
    return scaled.astype(np.float32)


def _shelf_biquad(freq, gain_db, sample_rate, kind):
    """RBJ audio-EQ-cookbook shelf biquad coefficients (shelf slope S=1)."""
    freq = max(20.0, min(float(sample_rate) / 2.0 - 100.0, float(freq)))
    a_gain = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * freq / float(sample_rate)
    cos_w0 = np.cos(w0)
    sin_w0 = np.sin(w0)
    shelf_slope = 1.0
    alpha = sin_w0 / 2.0 * np.sqrt((a_gain + 1.0 / a_gain) * (1.0 / shelf_slope - 1.0) + 2.0)
    sqrt_a = np.sqrt(a_gain)

    if kind == "low":
        b0 = a_gain * ((a_gain + 1) - (a_gain - 1) * cos_w0 + 2 * sqrt_a * alpha)
        b1 = 2 * a_gain * ((a_gain - 1) - (a_gain + 1) * cos_w0)
        b2 = a_gain * ((a_gain + 1) - (a_gain - 1) * cos_w0 - 2 * sqrt_a * alpha)
        a0 = (a_gain + 1) + (a_gain - 1) * cos_w0 + 2 * sqrt_a * alpha
        a1 = -2 * ((a_gain - 1) + (a_gain + 1) * cos_w0)
        a2 = (a_gain + 1) + (a_gain - 1) * cos_w0 - 2 * sqrt_a * alpha
    else:
        b0 = a_gain * ((a_gain + 1) + (a_gain - 1) * cos_w0 + 2 * sqrt_a * alpha)
        b1 = -2 * a_gain * ((a_gain - 1) + (a_gain + 1) * cos_w0)
        b2 = a_gain * ((a_gain + 1) + (a_gain - 1) * cos_w0 - 2 * sqrt_a * alpha)
        a0 = (a_gain + 1) - (a_gain - 1) * cos_w0 + 2 * sqrt_a * alpha
        a1 = 2 * ((a_gain - 1) - (a_gain + 1) * cos_w0)
        a2 = (a_gain + 1) - (a_gain - 1) * cos_w0 - 2 * sqrt_a * alpha

    b = np.array([b0, b1, b2], dtype=np.float64) / a0
    a = np.array([1.0, a1 / a0, a2 / a0], dtype=np.float64)
    return b, a


def apply_warmth_brightness(audio, sample_rate, warmth, brightness):
    """Low-shelf (warmth, 300Hz corner) and/or high-shelf (brightness,
    3000Hz corner) boost. Each 0..1, mapped linearly to 0-6dB. Neutral
    (both 0) is a no-op. Boost-only (no cut) — this is a "warmer/brighter"
    knob, not a full parametric EQ.
    """
    try:
        warmth = max(0.0, min(1.0, float(warmth)))
    except (TypeError, ValueError):
        warmth = 0.0
    try:
        brightness = max(0.0, min(1.0, float(brightness)))
    except (TypeError, ValueError):
        brightness = 0.0

    arr = np.asarray(audio, dtype=np.float32)
    if arr.size == 0 or (warmth <= 0.0 and brightness <= 0.0):
        return arr

    result = arr.astype(np.float64)
    if warmth > 0.0:
        b, a = _shelf_biquad(300.0, warmth * 6.0, sample_rate, "low")
        result = signal.sosfilt(signal.tf2sos(b, a), result)
    if brightness > 0.0:
        b, a = _shelf_biquad(3000.0, brightness * 6.0, sample_rate, "high")
        result = signal.sosfilt(signal.tf2sos(b, a), result)
    return result.astype(np.float32)


def apply_modulation(audio, sample_rate, settings):
    """Apply pitch -> warmth/brightness -> energy, in that order, from a
    settings dict. Missing/neutral keys are no-ops. `settings` may be None
    or omit any key; `pause_style` and `stability` are ignored here (pause
    style is a text-domain transform, see tts_text.apply_pause_style;
    stability is stored-only, see module docstring)."""
    arr = np.asarray(audio, dtype=np.float32)
    if not settings:
        return arr

    result = arr
    pitch = settings.get("pitch", 0.0) or 0.0
    if pitch:
        result = pitch_shift_semitones(result, sample_rate, pitch)

    warmth = settings.get("warmth", 0.0) or 0.0
    brightness = settings.get("brightness", 0.0) or 0.0
    if warmth or brightness:
        result = apply_warmth_brightness(result, sample_rate, warmth, brightness)

    energy = settings.get("energy", None)
    if energy is not None and abs(float(energy) - 0.5) > 1e-9:
        result = apply_energy_gain(result, energy)

    return result
