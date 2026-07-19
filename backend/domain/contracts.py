"""Additive, JSON-friendly contracts for the Message Rescue pipeline.

These types intentionally have no FastAPI, model, audio, or persistence imports so
they can be used by pure tests and compatibility adapters independently.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class TimedSegment:
    start_s: float
    end_s: float
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    segments: list[TimedSegment] = field(default_factory=list)
    confidence: float | None = None
    audio_duration_s: float | None = None


@dataclass(frozen=True)
class SpeechSignals:
    words_per_minute: float = 0.0
    speaking_ratio: float = 0.0
    pause_count: int = 0
    pause_ratio: float = 0.0
    mean_pause_s: float = 0.0
    longest_pause_s: float = 0.0
    filler_count: int = 0
    self_correction_count: int = 0
    energy_mean: float = 0.0
    energy_variation: float = 0.0
    delivery_axes: dict[str, float] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass(frozen=True)
class ContextEnvelope:
    id: str
    text: str
    source: Literal["selection", "clipboard_fallback", "manual"]
    captured_at: float
    expires_at: float
    use_count: int = 0
    max_uses: int = 1
    visible_preview: str = ""


@dataclass(frozen=True)
class MessageRescueResult:
    assessment: dict[str, Any] = field(default_factory=dict)
    delivery: dict[str, Any] = field(default_factory=dict)
    variants: dict[str, str] = field(default_factory=dict)
    preservation_checks: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def to_dict(value: Any) -> dict[str, Any]:
    """Serialize one contract using only JSON-compatible containers."""

    return asdict(value)
