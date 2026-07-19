"""Deterministic speech-signal calculation (Phase 2 Wave 2A, F2.1).

Turns :class:`~backend.domain.contracts.TimedSegment` timing data, plus an
optional sequence of numeric audio-window energy summaries, into a
:class:`~backend.domain.contracts.SpeechSignals`. Pure function, no I/O: no
FastAPI, model, audio, or logging imports, so it is exercisable with plain
synthetic fixtures.

Every derived number is traceable to an observable timing, energy, filler, or
correction fact — never to an inferred emotion. ``evidence`` entries report
only counts and metrics, never the underlying transcript text, so nothing
here can leak raw dictated content into logs or diagnostics.
"""

from __future__ import annotations

import re
import statistics
from typing import Sequence

from backend.domain.contracts import SpeechSignals, TimedSegment

# A gap between segments shorter than this is normal articulation spacing,
# not a hesitation pause. 0.5s matches common speech-analysis conventions
# for a perceptible mid-utterance pause.
PAUSE_THRESHOLD_S = 0.5

# Words-per-minute band used to normalize pace into the delivery axes.
# 60 wpm is a halting/deliberate pace; 200 wpm is a rapid, animated one.
_WPM_FLOOR = 60.0
_WPM_CEIL = 200.0

# Density ceilings: at or above these rates, filler/self-correction density
# is treated as maximally hesitant (normalized to 1.0).
_FILLER_RATE_CEIL = 0.15
_SELF_CORRECTION_RATE_CEIL = 0.10

_FILLER_WORDS = frozenset({"um", "uh", "uhh", "umm", "erm", "hmm"})
_FILLER_PHRASE_RE = re.compile(r"\byou know\b", re.IGNORECASE)
_SELF_CORRECTION_PHRASE_RE = re.compile(
    r"\b(i mean|no wait|sorry i meant|scratch that|let me rephrase|correction)\b",
    re.IGNORECASE,
)
_STUTTER_RE = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z']+")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _total_duration_s(segments: Sequence[TimedSegment], audio_duration_s: float | None) -> float:
    if audio_duration_s is not None and audio_duration_s > 0:
        return float(audio_duration_s)
    if segments:
        return max(seg.end_s for seg in segments)
    return 0.0


def _count_pauses(segments: Sequence[TimedSegment]) -> list[float]:
    ordered = sorted(segments, key=lambda seg: seg.start_s)
    gaps = []
    for prev, nxt in zip(ordered, ordered[1:]):
        gap = nxt.start_s - prev.end_s
        if gap > PAUSE_THRESHOLD_S:
            gaps.append(gap)
    return gaps


def _energy_stats(energy_windows: Sequence[float] | None) -> tuple[float, float]:
    if not energy_windows:
        return 0.0, 0.0
    values = [max(0.0, float(v)) for v in energy_windows]
    mean = statistics.fmean(values)
    if len(values) < 2 or mean <= 0:
        return mean, 0.0
    variation = statistics.pstdev(values) / mean
    return mean, variation


def compute_speech_signals(
    segments: Sequence[TimedSegment],
    audio_duration_s: float | None = None,
    energy_windows: Sequence[float] | None = None,
) -> SpeechSignals:
    """Compute bounded, evidence-backed delivery signals from timing data alone.

    ``energy_windows`` is an optional sequence of non-negative numeric energy
    summaries (e.g. per-window RMS) spanning the audio; it is never raw audio
    or text. All returned floats are finite; ``delivery_axes`` and
    ``confidence`` are always clamped to [0, 1].
    """

    total_duration_s = _total_duration_s(segments, audio_duration_s)
    total_words = sum(len(_WORD_RE.findall(seg.text)) for seg in segments)
    speaking_duration_s = sum(max(0.0, seg.end_s - seg.start_s) for seg in segments)

    words_per_minute = (
        total_words / (total_duration_s / 60.0) if total_duration_s > 0 and total_words > 0 else 0.0
    )
    speaking_ratio = _clamp01(speaking_duration_s / total_duration_s) if total_duration_s > 0 else 0.0

    pauses = _count_pauses(segments)
    pause_count = len(pauses)
    total_pause_s = sum(pauses)
    mean_pause_s = total_pause_s / pause_count if pause_count else 0.0
    longest_pause_s = max(pauses) if pauses else 0.0
    pause_ratio = _clamp01(total_pause_s / total_duration_s) if total_duration_s > 0 else 0.0

    joined_text = " ".join(seg.text for seg in segments)
    lowered = joined_text.lower()
    filler_count = sum(1 for word in _WORD_RE.findall(lowered) if word in _FILLER_WORDS)
    filler_count += len(_FILLER_PHRASE_RE.findall(joined_text))
    self_correction_count = len(_SELF_CORRECTION_PHRASE_RE.findall(joined_text))
    self_correction_count += len(_STUTTER_RE.findall(joined_text))

    energy_mean, energy_variation = _energy_stats(energy_windows)

    if total_words > 0:
        filler_rate = filler_count / total_words
        self_correction_rate = self_correction_count / total_words
    else:
        filler_rate = 0.0
        self_correction_rate = 0.0

    normalized_wpm = _clamp01((words_per_minute - _WPM_FLOOR) / (_WPM_CEIL - _WPM_FLOOR))
    normalized_energy_variation = _clamp01(energy_variation)
    normalized_filler = _clamp01(filler_rate / _FILLER_RATE_CEIL)
    normalized_self_correction = _clamp01(self_correction_rate / _SELF_CORRECTION_RATE_CEIL)

    if segments and total_words > 0:
        arousal = _clamp01(0.5 * normalized_wpm + 0.5 * normalized_energy_variation)
        urgency = _clamp01(0.5 * normalized_wpm + 0.3 * (1.0 - pause_ratio) + 0.2 * speaking_ratio)
        hesitation = _clamp01(
            0.5 * pause_ratio + 0.25 * normalized_filler + 0.25 * normalized_self_correction
        )
    else:
        arousal = urgency = hesitation = 0.0

    duration_score = _clamp01(total_duration_s / 5.0)
    word_score = _clamp01(total_words / 15.0)
    confidence = _clamp01(0.5 * duration_score + 0.5 * word_score) if segments and total_words > 0 else 0.0

    evidence: list[str] = []
    if not segments or total_words == 0:
        evidence.append("no speech segments provided")
    else:
        evidence.append(
            f"{words_per_minute:.0f} wpm across {total_words} words over {total_duration_s:.1f}s"
        )
        evidence.append(
            f"speaking ratio {speaking_ratio:.2f} ({speaking_duration_s:.1f}s speech of "
            f"{total_duration_s:.1f}s total)"
        )
        if pause_count:
            evidence.append(
                f"{pause_count} pause(s) totaling {total_pause_s:.1f}s, longest {longest_pause_s:.1f}s"
            )
        if filler_count:
            evidence.append(f"{filler_count} filler marker(s) detected")
        if self_correction_count:
            evidence.append(f"{self_correction_count} self-correction marker(s) detected")
        if energy_windows:
            evidence.append(
                f"energy mean {energy_mean:.3f}, variation {energy_variation:.2f} across "
                f"{len(energy_windows)} window(s)"
            )

    return SpeechSignals(
        words_per_minute=words_per_minute,
        speaking_ratio=speaking_ratio,
        pause_count=pause_count,
        pause_ratio=pause_ratio,
        mean_pause_s=mean_pause_s,
        longest_pause_s=longest_pause_s,
        filler_count=filler_count,
        self_correction_count=self_correction_count,
        energy_mean=energy_mean,
        energy_variation=energy_variation,
        delivery_axes={"arousal": arousal, "urgency": urgency, "hesitation": hesitation},
        evidence=evidence,
        confidence=confidence,
    )
