from typing import Dict, List, Tuple


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

