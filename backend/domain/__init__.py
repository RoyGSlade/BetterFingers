"""Stable data contracts shared by the backend pipeline and adapters."""

from .contracts import (
    ContextEnvelope,
    MessageRescueResult,
    SpeechSignals,
    TimedSegment,
    TranscriptionResult,
    to_dict,
)

__all__ = [
    "ContextEnvelope",
    "MessageRescueResult",
    "SpeechSignals",
    "TimedSegment",
    "TranscriptionResult",
    "to_dict",
]
