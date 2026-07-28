"""Wake handoff hardening (D-0013 / Wave 8A package F).

Two problems this fixes, both of which show up as "the wake word worked but
the first word of my command was lost":

1. **Pre-trigger audio.** A wake phrase is only recognized ~200-400 ms after
   it finished, and the user is usually already speaking the command by then.
   The recorder starts at trigger time, so that leading audio never existed.
   :class:`PreTriggerRing` keeps a short rolling window of the audio the wake
   listener has already seen, so the recording can be prepended with it.

2. **Command termination.** A hands-free command has no key release to end
   it. :func:`build_command_capture_detector` builds the SAME
   :class:`audio_gate.TrailingSilenceDetector` the hold-to-talk auto-stop
   already uses, rather than inventing a second definition of silence — one
   place to tune, one behavior to explain.

Privacy constraints are the reason this module is small and explicit:

- The ring is **in memory only**. Nothing here writes to disk, and no other
  module is given a handle that outlives an activation — :meth:`drain`
  returns the audio and clears the buffer in the same call.
- It is bounded on **both** axes: a wall-clock window (``max_ms``) and a hard
  byte ceiling (``max_bytes``), so a wrong sample rate or a runaway feed can
  never grow it without limit.
- :meth:`clear` is the single wipe hook, and the three moments that must call
  it are named in one place: activation (the audio has been handed off),
  disable (wake word turned off), and privacy wipe.

numpy is imported lazily and only to concatenate on drain, so the bounding
and lifecycle logic is testable in a bare interpreter.
"""

import logging
import threading

# ~1.5 s comfortably covers the recognition tail plus the first word or two of
# a command, and is short enough that the buffer is a rounding error (96 KB of
# float32 at 16 kHz).
DEFAULT_PRETRIGGER_MS = 1500.0
# Hard ceiling, independent of the time window: bytes, not intentions.
DEFAULT_MAX_BYTES = 512 * 1024
DEFAULT_SAMPLE_RATE = 16000
_BYTES_PER_SAMPLE = 4  # float32

# Wake commands are spoken in one breath and there is no key release to end
# them, so the default trailing-silence window is a little tighter than the
# hold-to-talk auto-stop's.
DEFAULT_COMMAND_SILENCE_MS = 800
DEFAULT_COMMAND_MIN_MS = 500


def _frame_count(chunk):
    try:
        return int(len(chunk))
    except TypeError:
        return 0


def _byte_size(chunk):
    nbytes = getattr(chunk, "nbytes", None)
    if isinstance(nbytes, int):
        return nbytes
    return _frame_count(chunk) * _BYTES_PER_SAMPLE


class PreTriggerRing:
    """Bounded, in-memory-only rolling buffer of the most recent audio.

    Thread-safe: the wake listener pushes from the PortAudio callback thread
    while the activation path drains from a request/hotkey thread.
    """

    def __init__(self, max_ms=DEFAULT_PRETRIGGER_MS, sample_rate=DEFAULT_SAMPLE_RATE,
                 max_bytes=DEFAULT_MAX_BYTES):
        self.max_ms = max(0.0, float(max_ms))
        self.sample_rate = max(1, int(sample_rate))
        self.max_bytes = max(0, int(max_bytes))
        self._lock = threading.Lock()
        self._chunks = []
        self._frames = 0
        self._bytes = 0

    # -- writing -------------------------------------------------------

    def push(self, chunk):
        """Append one capture block, evicting from the front until BOTH the
        time window and the byte ceiling are satisfied. A chunk larger than
        the whole window replaces the buffer rather than being dropped — the
        most recent audio is always the audio worth keeping."""
        frames = _frame_count(chunk)
        if frames <= 0 or self.max_ms <= 0.0 or self.max_bytes <= 0:
            return False
        size = _byte_size(chunk)
        with self._lock:
            self._chunks.append(chunk)
            self._frames += frames
            self._bytes += size
            self._evict_locked()
        return True

    def _evict_locked(self):
        max_frames = int(self.max_ms * self.sample_rate / 1000.0)
        while self._chunks and (self._frames > max_frames or self._bytes > self.max_bytes):
            if len(self._chunks) == 1:
                # One oversized chunk: keeping it would breach the ceiling, and
                # dropping it would silently lose the newest audio. Keep it and
                # say so — the caller's window is misconfigured.
                if self._bytes > self.max_bytes:
                    logging.debug(
                        "Pre-trigger chunk (%d bytes) exceeds the ring ceiling (%d bytes).",
                        self._bytes, self.max_bytes,
                    )
                break
            oldest = self._chunks.pop(0)
            self._frames -= _frame_count(oldest)
            self._bytes -= _byte_size(oldest)

    # -- reading / clearing --------------------------------------------

    def drain(self):
        """Return the buffered audio as one flat float32 array AND clear the
        buffer, so audio is never left behind after a handoff. Returns None
        when there is nothing buffered."""
        with self._lock:
            chunks = self._chunks
            self._chunks = []
            self._frames = 0
            self._bytes = 0
        if not chunks:
            return None
        try:
            import numpy as np

            flat = [np.asarray(c, dtype=np.float32).reshape(-1) for c in chunks]
            return np.concatenate(flat) if flat else None
        except Exception as exc:
            logging.warning("Pre-trigger drain failed; dropping the pre-roll: %s", exc)
            return None

    def clear(self):
        """The single wipe hook. Call on activation, on wake disable, and from
        the privacy-wipe path. Idempotent."""
        with self._lock:
            had = bool(self._chunks)
            self._chunks = []
            self._frames = 0
            self._bytes = 0
        return had

    # -- diagnostics ---------------------------------------------------

    def frame_count(self):
        with self._lock:
            return self._frames

    def byte_size(self):
        with self._lock:
            return self._bytes

    def duration_ms(self):
        with self._lock:
            return (self._frames / float(self.sample_rate)) * 1000.0

    def stats(self):
        """Sizes only — never audio. Safe to log or expose in a status route."""
        with self._lock:
            return {
                "chunks": len(self._chunks),
                "frames": self._frames,
                "bytes": self._bytes,
                "duration_ms": (self._frames / float(self.sample_rate)) * 1000.0,
                "max_ms": self.max_ms,
                "max_bytes": self.max_bytes,
            }


def build_command_capture_detector(config=None, **overrides):
    """A :class:`audio_gate.TrailingSilenceDetector` for hands-free command
    capture.

    Reuses the profile's existing silence definition (the same
    ``no_audio_min_rms`` / ``no_audio_min_peak`` thresholds the no-audio gate
    and the hold-to-talk auto-stop use) so there is exactly one notion of
    "silence" to tune. Only the timing defaults differ, and any of them can be
    overridden per call.
    """
    from audio_gate import TrailingSilenceDetector

    config = config if isinstance(config, dict) else {}
    settings = {
        "silence_ms": config.get("wake_command_silence_ms", DEFAULT_COMMAND_SILENCE_MS),
        "min_recording_ms": config.get("wake_command_min_recording_ms", DEFAULT_COMMAND_MIN_MS),
        "rms_threshold": config.get("auto_stop_rms_threshold", config.get("no_audio_min_rms", 0.003)),
        "peak_threshold": config.get("auto_stop_peak_threshold", config.get("no_audio_min_peak", 0.015)),
    }
    settings.update({k: v for k, v in overrides.items() if v is not None})
    return TrailingSilenceDetector(**settings)


class WakeHandoff:
    """Glue between the wake listener and the recorder.

    Armed while wake detection is listening: every chunk the listener scores
    is also pushed into the ring. On a detection the caller calls
    :meth:`activate`, which hands over the pre-roll and clears the ring in one
    step, so the audio exists in exactly one place at a time.

    The class deliberately holds no reference to the recorder or the broker —
    it is fed and drained by its owner, which keeps it unit-testable and keeps
    the privacy surface (one buffer, one clear) obvious.
    """

    def __init__(self, ring=None, max_ms=DEFAULT_PRETRIGGER_MS, sample_rate=DEFAULT_SAMPLE_RATE):
        self.ring = ring if ring is not None else PreTriggerRing(max_ms=max_ms, sample_rate=sample_rate)
        self._armed = False

    def is_armed(self):
        return self._armed

    def arm(self):
        """Start retaining pre-trigger audio (wake listening began)."""
        self.ring.clear()
        self._armed = True

    def disarm(self):
        """Stop retaining and wipe (wake listening ended, or privacy wipe)."""
        self._armed = False
        return self.ring.clear()

    def on_chunk(self, chunk, sample_rate=None):
        """Feed one capture block. A no-op when disarmed, so a stray callback
        after disable can never repopulate a wiped buffer."""
        del sample_rate
        if not self._armed:
            return False
        return self.ring.push(chunk)

    def activate(self):
        """Wake fired: hand the pre-roll to the recorder and wipe the ring.

        Stays armed afterwards only if the caller re-arms — the default is to
        disarm, because the recorder owns the microphone stream for the
        duration of the command and buffering the same audio twice would both
        waste memory and duplicate the pre-roll on a second trigger.
        """
        audio = self.ring.drain()
        self._armed = False
        return audio

    def stats(self):
        stats = self.ring.stats()
        stats["armed"] = self._armed
        return stats
