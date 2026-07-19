"""In-memory, one-use context session (Phase 2 Wave 2A, F2.5).

Holds at most one captured :class:`~backend.domain.contracts.ContextEnvelope`
for Message Rescue: an explicit selection/clipboard-fallback/manual capture
with a visible preview, a TTL, and a use-count ceiling (default one). Consume
is atomic so a stale or already-used context can never silently re-enter a
rescue prompt twice.

Nothing here is persisted to disk — ``clear()`` (and simply dropping the
process) removes it completely, which is what makes this privacy-wipe
compatible. ``status()`` deliberately returns metadata plus the bounded
``visible_preview`` only, never the raw captured text, so nothing here can
leak full dictated/selected content into logs or diagnostics; only
``consume()`` returns the raw text, and only once per allowed use.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Callable

from backend.domain.contracts import ContextEnvelope
from backend.services.selection_capture import capture_selection

DEFAULT_TTL_S = 120.0
DEFAULT_MAX_USES = 1
PREVIEW_CHARS = 80


def _make_preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 1].rstrip() + "…"


class ContextCaptureError(Exception):
    """Raised when a capture attempt yields no usable context."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ContextExhaustedError(Exception):
    """Raised by consume() when there is no live, unused context."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ContextSession:
    """Single-slot in-memory holder for one ContextEnvelope at a time."""

    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ):
        self._clock = clock
        self._id_factory = id_factory
        self._lock = threading.Lock()
        self._envelope: ContextEnvelope | None = None

    def capture_from_selection(
        self,
        capture_fn=None,
        supported_fn=None,
        ttl_s: float = DEFAULT_TTL_S,
        max_uses: int = DEFAULT_MAX_USES,
    ) -> ContextEnvelope:
        """Capture via the selection adapter and store the result.

        Raises :class:`ContextCaptureError` with reason ``"empty"`` or
        ``"unsupported"`` instead of storing an unusable envelope — callers
        (e.g. the manual-fallback UI path) branch on ``.reason``.
        """
        result = capture_selection(capture_fn=capture_fn, supported_fn=supported_fn)
        if result.outcome in ("empty", "unsupported"):
            raise ContextCaptureError(result.outcome)
        return self._store(result.text, result.outcome, ttl_s, max_uses)

    def capture_manual(
        self,
        text: str,
        ttl_s: float = DEFAULT_TTL_S,
        max_uses: int = DEFAULT_MAX_USES,
    ) -> ContextEnvelope:
        """Store user-typed context text directly, bypassing selection capture."""
        cleaned = (text or "").strip()
        if not cleaned:
            raise ContextCaptureError("empty")
        return self._store(cleaned, "manual", ttl_s, max_uses)

    def _store(self, text: str, source: str, ttl_s: float, max_uses: int) -> ContextEnvelope:
        now = self._clock()
        envelope = ContextEnvelope(
            id=self._id_factory(),
            text=text,
            source=source,
            captured_at=now,
            expires_at=now + max(0.0, float(ttl_s)),
            use_count=0,
            max_uses=max(1, int(max_uses)),
            visible_preview=_make_preview(text),
        )
        with self._lock:
            self._envelope = envelope
        return envelope

    def status(self) -> dict | None:
        """Metadata and preview for the held context, or None if there is none.

        Never includes the raw captured text.
        """
        with self._lock:
            envelope = self._envelope
        if envelope is None:
            return None
        alive = self._clock() < envelope.expires_at and envelope.use_count < envelope.max_uses
        return {
            "id": envelope.id,
            "source": envelope.source,
            "captured_at": envelope.captured_at,
            "expires_at": envelope.expires_at,
            "use_count": envelope.use_count,
            "max_uses": envelope.max_uses,
            "visible_preview": envelope.visible_preview,
            "active": alive,
        }

    def consume(self) -> str:
        """Atomically return the raw text once, enforcing expiry and max_uses.

        Raises :class:`ContextExhaustedError` (reason ``"missing"``,
        ``"expired"``, or ``"used_up"``) rather than returning stale or
        over-used content.
        """
        with self._lock:
            envelope = self._envelope
            if envelope is None:
                raise ContextExhaustedError("missing")
            if self._clock() >= envelope.expires_at:
                self._envelope = None
                raise ContextExhaustedError("expired")
            if envelope.use_count >= envelope.max_uses:
                self._envelope = None
                raise ContextExhaustedError("used_up")

            next_use_count = envelope.use_count + 1
            if next_use_count >= envelope.max_uses:
                self._envelope = None
            else:
                self._envelope = ContextEnvelope(
                    id=envelope.id,
                    text=envelope.text,
                    source=envelope.source,
                    captured_at=envelope.captured_at,
                    expires_at=envelope.expires_at,
                    use_count=next_use_count,
                    max_uses=envelope.max_uses,
                    visible_preview=envelope.visible_preview,
                )
            return envelope.text

    def clear(self) -> None:
        """Drop the held context. Privacy-wipe compatible: nothing is persisted."""
        with self._lock:
            self._envelope = None
