"""Voice clone sample QA (Voice Studio, consent-gated clone tier).

Cheap, well-understood checks on an uploaded audio sample before it's
accepted as a clone source: duration, noise floor, clipping, and
leading/trailing-silence ratio. Pure numpy over raw audio arrays, so the
checks are fully unit-testable; `check_file` is a thin wrapper for the
`/tts/clone` route, reading WAV via the stdlib `wave` module (no extra
dependency — `/tts/clone` only ever saves `.wav` uploads).

This does not perform actual voice cloning — no cloning engine (NeuTTS Air /
Chatterbox) is installed. See docs/MASTER_PLAN.md U6: cloning synthesis is
deferred; this module only gates what gets *saved* as a clone source.
"""
import wave

import numpy as np

MIN_DURATION_SECONDS = 2.0
MAX_DURATION_SECONDS = 120.0
MIN_RMS = 0.001  # near-total silence / dead input
CLIPPING_THRESHOLD = 0.999
MAX_CLIPPING_RATIO = 0.001
SILENCE_AMPLITUDE = 0.01
MAX_SILENCE_RATIO = 0.5


def check_duration(audio, sample_rate):
    duration = len(audio) / float(sample_rate) if sample_rate else 0.0
    if duration < MIN_DURATION_SECONDS:
        return False, f"Sample is too short ({duration:.1f}s) — need at least {MIN_DURATION_SECONDS:.0f}s."
    if duration > MAX_DURATION_SECONDS:
        return False, f"Sample is too long ({duration:.1f}s) — keep it under {MAX_DURATION_SECONDS:.0f}s."
    return True, ""


def check_noise_floor(audio):
    arr = np.asarray(audio, dtype=np.float32)
    if arr.size == 0:
        return False, "Sample is empty."
    rms = float(np.sqrt(np.mean(arr.astype(np.float64) ** 2)))
    if rms < MIN_RMS:
        return False, "Sample is silent or near-silent — check your microphone."
    return True, ""


def check_clipping(audio):
    arr = np.asarray(audio, dtype=np.float32)
    if arr.size == 0:
        return True, ""
    clipped_ratio = float(np.mean(np.abs(arr) >= CLIPPING_THRESHOLD))
    if clipped_ratio > MAX_CLIPPING_RATIO:
        return False, f"Sample is clipped ({clipped_ratio * 100:.1f}% of samples at full scale) — record quieter."
    return True, ""


def check_silence_ratio(audio):
    arr = np.asarray(audio, dtype=np.float32)
    if arr.size == 0:
        return True, ""
    silent_ratio = float(np.mean(np.abs(arr) < SILENCE_AMPLITUDE))
    if silent_ratio > MAX_SILENCE_RATIO:
        return False, f"Sample is mostly silence ({silent_ratio * 100:.0f}%) — trim dead air before uploading."
    return True, ""


def evaluate_sample(audio, sample_rate):
    """Run all QA checks. Returns (ok, warnings: list[str]).

    Duration and noise-floor failures are hard blockers (ok=False) — the
    sample is unusable outright. Clipping and silence-ratio issues are
    reported as warnings without forcing ok=False on their own: a slightly
    clipped or padded sample is still usable, and blocking on it would just
    force a re-record for marginal gain.
    """
    arr = np.asarray(audio, dtype=np.float32)
    warnings = []
    ok = True

    duration_ok, duration_msg = check_duration(arr, sample_rate)
    if not duration_ok:
        ok = False
        warnings.append(duration_msg)

    noise_ok, noise_msg = check_noise_floor(arr)
    if not noise_ok:
        ok = False
        warnings.append(noise_msg)

    clip_ok, clip_msg = check_clipping(arr)
    if not clip_ok:
        warnings.append(clip_msg)

    silence_ok, silence_msg = check_silence_ratio(arr)
    if not silence_ok:
        warnings.append(silence_msg)

    return ok, warnings


def _read_wav_as_float32(path):
    with wave.open(path, "rb") as wav_file:
        n_channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        raw = wav_file.readframes(wav_file.getnframes())

    if sample_width == 1:
        audio = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sample_width} bytes")

    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1)
    return audio.astype(np.float32), sample_rate


def check_file(path):
    """Read a WAV file from disk and evaluate_sample() it. Returns
    (ok, warnings) same as evaluate_sample; (False, [message]) if the file
    can't be read at all (not a WAV, corrupt, unsupported format)."""
    try:
        audio, sample_rate = _read_wav_as_float32(path)
    except Exception as exc:
        return False, [f"Could not read audio file: {exc}"]
    return evaluate_sample(audio, sample_rate)
