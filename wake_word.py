"""Wake-word service (C5 / Phase 9) — hands-free activation.

Owns a pluggable WakeDetector adapter, applies threshold + cooldown + optional
VAD gating, and calls back into the app's existing recording start path
(HotkeyManager.request_start(reason="wake_word")) on a real detection.
Disabled by default (see wake_word_enabled in the profile schema).

Owning the actual mic stream (sounddevice.InputStream) is left to the caller
(server.py) — WakeWordService only decides whether a given audio chunk should
trigger `on_detect`, so the cooldown/threshold/VAD state machine is fully
testable with a FakeWakeDetector and no real microphone or ML dependency.
"""
import time

DEFAULT_THRESHOLD = 0.55
DEFAULT_COOLDOWN_MS = 2500
_MAX_SCORE_LOG = 200


class WakeDetector:
    """Adapter interface. Real implementations (openWakeWord, ...) wrap a
    model and score one audio chunk at a time."""

    def predict(self, audio_chunk, sample_rate):
        """Return {"detected": bool, "score": float, "label": str}."""
        raise NotImplementedError


class FakeWakeDetector(WakeDetector):
    """Deterministic detector for tests: yields queued scores in order, 0.0
    once the queue is empty."""

    def __init__(self, scores=None, label="hey_betterfingers"):
        self._scores = list(scores or [])
        self._label = label

    def queue_score(self, score):
        self._scores.append(score)

    def predict(self, audio_chunk, sample_rate):
        score = self._scores.pop(0) if self._scores else 0.0
        return {"detected": score >= 1.0, "score": score, "label": self._label}


class WakeWordService:
    """Cooldown/threshold/VAD gating around a WakeDetector. `on_detect` is
    called with no arguments on an accepted trigger — the caller wires that
    to hotkey_manager.request_start(reason="wake_word")."""

    def __init__(
        self,
        detector,
        on_detect,
        threshold=DEFAULT_THRESHOLD,
        cooldown_ms=DEFAULT_COOLDOWN_MS,
        requires_vad=True,
    ):
        self.detector = detector
        self.on_detect = on_detect
        self.threshold = threshold
        self.cooldown_ms = cooldown_ms
        self.requires_vad = requires_vad
        self._last_trigger_time = None
        # False-trigger log for the settings-panel test view (Phase 13).
        self.score_log = []

    def _in_cooldown(self, now):
        if self._last_trigger_time is None:
            return False
        return (now - self._last_trigger_time) * 1000.0 < self.cooldown_ms

    def process_chunk(self, audio_chunk, sample_rate, has_speech=True, now=None):
        """Feed one audio chunk through the detector. Returns True iff this
        chunk triggered `on_detect`. `has_speech` should come from an
        upstream VAD gate; ignored when requires_vad is False."""
        now = time.time() if now is None else now
        result = self.detector.predict(audio_chunk, sample_rate)
        score = result.get("score", 0.0)

        triggered = False
        if score >= self.threshold and not self._in_cooldown(now):
            if not self.requires_vad or has_speech:
                triggered = True
                self._last_trigger_time = now
                self.on_detect()

        self.score_log.append({"score": score, "triggered": triggered, "ts": now})
        if len(self.score_log) > _MAX_SCORE_LOG:
            self.score_log.pop(0)
        return triggered

    def status(self, now=None):
        now = time.time() if now is None else now
        return {
            "threshold": self.threshold,
            "cooldown_ms": self.cooldown_ms,
            "requires_vad": self.requires_vad,
            "in_cooldown": self._in_cooldown(now),
            "recent_scores": list(self.score_log[-20:]),
        }
