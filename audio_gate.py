from typing import Dict, List, Tuple


class TrailingSilenceDetector:
    """Pure streaming state machine for hands-free auto-stop (Phase 10).

    Fed one audio chunk's ``(rms, peak, chunk_ms)`` at a time via :meth:`update`.
    It only begins counting *trailing* silence once speech has been observed, so
    a slow start never trips it; a brief pause mid-sentence resets the counter
    because a louder chunk clears it. It returns ``True`` exactly once — when
    speech has been seen, the recording has run at least ``min_recording_ms``,
    and silence has persisted for ``silence_ms`` — so a single detector drives a
    single stop.

    A chunk counts as silent only when *both* its RMS and peak fall below their
    thresholds, matching :func:`should_block_for_no_audio`'s near-silent rule.
    Non-positive ``silence_ms`` disables firing entirely (feature off).
    """

    def __init__(self, silence_ms=900.0, min_recording_ms=700.0, rms_threshold=0.003, peak_threshold=0.015):
        self.silence_ms = max(0.0, float(silence_ms))
        self.min_recording_ms = max(0.0, float(min_recording_ms))
        self.rms_threshold = max(0.0, float(rms_threshold))
        self.peak_threshold = max(0.0, float(peak_threshold))
        self.total_ms = 0.0
        self.trailing_silence_ms = 0.0
        self.has_speech = False
        self.fired = False

    def update(self, rms, peak, chunk_ms) -> bool:
        if self.fired or self.silence_ms <= 0.0:
            return False
        try:
            rms = float(rms)
            peak = float(peak)
            chunk_ms = max(0.0, float(chunk_ms))
        except (TypeError, ValueError):
            return False

        self.total_ms += chunk_ms
        is_silent = rms < self.rms_threshold and peak < self.peak_threshold
        if is_silent:
            if self.has_speech:
                self.trailing_silence_ms += chunk_ms
        else:
            self.has_speech = True
            self.trailing_silence_ms = 0.0

        if (
            self.has_speech
            and self.total_ms >= self.min_recording_ms
            and self.trailing_silence_ms >= self.silence_ms
        ):
            self.fired = True
            return True
        return False


def should_block_for_no_audio(recording_result, transcript_text: str = None, config: Dict[str, object] = None) -> Tuple[bool, List[str]]:
    if config is None:
        config = {}
    reasons = []

    min_duration = float(config.get("no_audio_min_duration_sec", 0.30))
    min_rms = float(config.get("no_audio_min_rms", 0.003))
    min_peak = float(config.get("no_audio_min_peak", 0.015))

    duration = float(getattr(recording_result, "duration_seconds", 0.0))
    rms = float(getattr(recording_result, "rms_amplitude", 0.0))
    peak = float(getattr(recording_result, "max_amplitude", 0.0))

    if duration < min_duration:
        reasons.append(f"clip_too_short({duration:.3f}s<{min_duration:.3f}s)")

    if peak < min_peak and rms < min_rms:
        reasons.append(f"near_silent(peak={peak:.5f},rms={rms:.5f})")

    if transcript_text is not None and not transcript_text.strip():
        reasons.append("empty_transcript")

    return (len(reasons) > 0, reasons)

