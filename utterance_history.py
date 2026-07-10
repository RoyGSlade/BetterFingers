"""Utterance history buffer — an in-memory record of recently emitted speech
chunks, kept so voice commands like "scratch that" can safely undo the last
emitted text instead of guessing what it was.

Pure and side-effect-free (no disk I/O): callers decide when to record and
what to do with a popped entry. Bounded ring buffer, oldest entries drop off
once the cap is reached.
"""
from dataclasses import dataclass, field
import threading

DEFAULT_CAPACITY = 40


@dataclass
class Utterance:
    raw_transcript: str
    final_text: str
    emitted_length: int
    target_draft_id: object = None
    timestamp: float = 0.0
    injected: bool = False


class UtteranceHistory:
    def __init__(self, capacity=DEFAULT_CAPACITY):
        self._capacity = capacity
        self._entries = []
        self._lock = threading.RLock()

    def record(self, utterance):
        with self._lock:
            self._entries.append(utterance)
            if len(self._entries) > self._capacity:
                self._entries.pop(0)

    def last(self):
        with self._lock:
            return self._entries[-1] if self._entries else None

    def pop_last(self):
        with self._lock:
            return self._entries.pop() if self._entries else None

    def all(self):
        with self._lock:
            return list(self._entries)

    def clear(self):
        with self._lock:
            self._entries.clear()

    def __len__(self):
        with self._lock:
            return len(self._entries)


# Process-wide default instance, mirroring intent_engine's module-level singleton.
utterance_history = UtteranceHistory()
