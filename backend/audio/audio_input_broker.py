"""One owner of the microphone (D-0013 / Wave 8A package B).

Before this module, two independent components opened ``sd.InputStream``
themselves: :class:`recorder.AudioRecorder` (per dictation) and
:class:`wake_word.WakeListener` (continuously, while wake word is enabled).
On a device that only allows one capture client — or any time the two
disagreed about which microphone to use — the second open simply failed, and
neither side could see why. There was also no single place that could answer
"is anything holding the mic right now?", which is exactly the question the
privacy surfaces and the Wave 8B capture-isolation adapter need to ask.

``AudioInputBroker`` is that single owner:

- Subscribers register a callback; the broker opens the device on the FIRST
  subscription and closes it when the LAST one goes away. Disabling wake word
  therefore releases the microphone — unless a recording is still running, in
  which case the device stays open for the recorder and is released when that
  finishes. Neither side has to know the other exists.
- One stream, one format (16 kHz mono float32), fanned out to every
  subscriber. Each callback is isolated: a subscriber that raises is logged
  and counted, and never takes down the stream or its peers.
- Device changes are the broker's job. A subscriber may state a device
  preference; ``device=None`` means "no preference". A new explicit
  preference that differs from the open device reopens the stream underneath
  every subscriber, so a mic switch mid-session doesn't require tearing the
  app down. A device that fails to open falls back to the system default,
  preserving the recorder's long-standing rescue behavior.
- :meth:`status` reports what is open, on which device, for whom, and what
  went wrong last — the honest input for the capability/status vocabulary in
  :mod:`audio_status`.

Testability is a hard requirement: the stream is built through an injectable
``stream_factory``, and the default factory resolves ``sounddevice.InputStream``
at call time so tests can patch it. No test in this repo opens a real audio
device.

Threading: subscriber bookkeeping is guarded by one re-entrant lock, but the
audio callback deliberately never takes it — it reads an immutable tuple
snapshot instead, so closing a stream can never deadlock against the
PortAudio callback thread.
"""

import logging
import threading

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHANNELS = 1
# 1280 frames = 80 ms at 16 kHz — the chunk size wake_word.WakeListener has
# always used, and the granularity wake_models' feature pipeline expects.
# The recorder is indifferent to chunk size (it concatenates), so one
# blocksize serves both owners.
DEFAULT_BLOCKSIZE = 1280


class _DefaultStreamFactory:
    """Builds a real ``sounddevice.InputStream``.

    ``sounddevice`` is imported lazily and ``InputStream`` is looked up at
    call time, so (a) importing this module never pulls in PortAudio, and
    (b) ``patch("sounddevice.InputStream", ...)`` in a test is honored.
    """

    def __call__(self, samplerate, device, channels, dtype, blocksize, callback):
        import sounddevice as sd

        return sd.InputStream(
            samplerate=samplerate,
            device=device,
            channels=channels,
            dtype=dtype,
            blocksize=blocksize,
            callback=callback,
        )


class Subscription:
    """Handle returned by :meth:`AudioInputBroker.subscribe`.

    Closing it is idempotent, so a caller may close on both its normal stop
    path and its error path without double-releasing the device.
    """

    def __init__(self, broker, name, callback, on_stream_error=None):
        self.broker = broker
        self.name = name
        self.callback = callback
        self.on_stream_error = on_stream_error
        self._closed = False

    @property
    def active(self):
        return not self._closed

    def close(self):
        if self._closed:
            return False
        self._closed = True
        self.broker._release(self)
        return True


class AudioInputBroker:
    def __init__(
        self,
        sample_rate=DEFAULT_SAMPLE_RATE,
        channels=DEFAULT_CHANNELS,
        blocksize=DEFAULT_BLOCKSIZE,
        stream_factory=None,
    ):
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.blocksize = int(blocksize)
        self.stream_factory = stream_factory or _DefaultStreamFactory()

        self._lock = threading.RLock()
        self._stream = None
        self._device = None
        # Immutable snapshot read by the audio callback WITHOUT the lock.
        self._subscribers = ()
        self._last_error = ""
        self._fell_back_to_default = False
        self._callback_errors = 0

    # -- lifecycle -----------------------------------------------------

    def is_open(self):
        return self._stream is not None

    def device(self):
        return self._device

    def subscriber_names(self):
        return [sub.name for sub in self._subscribers]

    def subscribe(self, name, callback, device=None, allow_default_fallback=True, on_stream_error=None):
        """Register ``callback`` and make sure the microphone is open.

        Args:
          name: short label for diagnostics ("recorder", "wake", "meter").
          callback: ``fn(chunk, sample_rate)``. ``chunk`` is the broker's own
            copy of the captured block, shared read-only across subscribers —
            do not mutate it.
          device: device index preference, or ``None`` for "no preference".
            An explicit preference that differs from the currently open
            device reopens the stream for everyone.
          allow_default_fallback: on open failure, retry on the system
            default device (the recorder's long-standing rescue behavior).
          on_stream_error: optional ``fn(reason)`` invoked when the stream
            this subscriber depends on could not be (re)opened.

        Returns the :class:`Subscription` on success, or ``None`` if the
        device could not be opened at all — the caller reports its own
        unavailable status rather than pretending to listen.
        """
        subscription = Subscription(self, name, callback, on_stream_error=on_stream_error)
        with self._lock:
            self._subscribers = self._subscribers + (subscription,)
            needs_reopen = device is not None and self.is_open() and device != self._device
            if not self.is_open() or needs_reopen:
                target = device if device is not None else self._device
                if not self._switch_locked(target, allow_default_fallback):
                    # Roll the registration back: a subscriber that never got a
                    # stream must not keep the broker looking occupied. Existing
                    # subscribers keep whatever stream _switch_locked restored.
                    self._subscribers = tuple(s for s in self._subscribers if s is not subscription)
                    subscription._closed = True
                    self._notify_stream_error(subscription, self._last_error)
                    return None
            return subscription

    def _release(self, subscription):
        """Drop one subscriber; close the device when the last one leaves."""
        with self._lock:
            remaining = tuple(s for s in self._subscribers if s is not subscription)
            self._subscribers = remaining
            if not remaining:
                self._close_locked()

    def stop_all(self):
        """Drop every subscriber and close the device.

        The unconditional quiesce hook — for emergency stop and the
        privacy-wipe path, which must be able to guarantee no live capture
        without knowing who was holding it. Idempotent.
        """
        with self._lock:
            subscribers = self._subscribers
            self._subscribers = ()
            for sub in subscribers:
                sub._closed = True
            self._close_locked()
        return len(subscribers)

    def set_device(self, device, allow_default_fallback=True):
        """Switch the shared input device, reopening under live subscribers.

        Returns True when the stream is open on ``device`` afterwards. On
        failure every subscriber is told (``on_stream_error``) rather than
        being left silently attached to a dead stream.
        """
        with self._lock:
            if device == self._device and self.is_open():
                return True
            if not self._subscribers:
                # Nobody is listening; remember the preference for the next open.
                self._device = device
                return True
            if self._switch_locked(device, allow_default_fallback):
                return True
            if not self.is_open():
                # Nothing was salvaged — subscribers are attached to nothing and
                # must be told, not left believing they are still listening.
                for sub in self._subscribers:
                    self._notify_stream_error(sub, self._last_error)
            return False

    # -- stream plumbing (callers hold self._lock) ---------------------

    def _switch_locked(self, target, allow_default_fallback):
        """Reopen on ``target``, restoring the previous device if that fails.

        PortAudio will not reliably hand out a second capture client for the
        same device, so the old stream has to close before the new one opens.
        That makes a failed switch destructive unless it is undone — so when
        the new device cannot be opened, the previously working one is
        reopened and the failure is still reported through ``last_error``.
        """
        previous_device = self._device
        had_stream = self.is_open()
        if self._open_locked(target, allow_default_fallback):
            return True

        failure = self._last_error
        if had_stream and previous_device != target and self._open_locked(previous_device, False):
            logging.warning(
                "Audio input device %r could not be opened; staying on %r.", target, previous_device
            )
        self._last_error = failure
        return False

    def _open_locked(self, device, allow_default_fallback):
        self._close_locked()
        attempts = [device]
        if allow_default_fallback and device is not None:
            attempts.append(None)

        for index, candidate in enumerate(attempts):
            try:
                stream = self.stream_factory(
                    samplerate=self.sample_rate,
                    device=candidate,
                    channels=self.channels,
                    dtype="float32",
                    blocksize=self.blocksize,
                    callback=self._audio_callback,
                )
                stream.start()
            except Exception as exc:
                logging.warning("Audio input device %r failed to open: %s", candidate, exc)
                self._last_error = f"device_open_failed: {exc}"
                continue
            self._stream = stream
            self._device = candidate
            self._fell_back_to_default = index > 0
            self._last_error = ""
            if self._fell_back_to_default:
                logging.warning(
                    "Audio input device %r unavailable; using the system default microphone.", device
                )
            return True
        return False

    def _close_locked(self):
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception as exc:
            logging.warning("Audio input stream close failed: %s", exc)

    def _notify_stream_error(self, subscription, reason):
        handler = getattr(subscription, "on_stream_error", None)
        if handler is None:
            return
        try:
            handler(reason)
        except Exception as exc:
            logging.debug("Subscriber %s stream-error handler failed: %s", subscription.name, exc)

    # -- capture -------------------------------------------------------

    def _audio_callback(self, indata, frames, time_info, status):
        """PortAudio callback. Deliberately lock-free: it reads the immutable
        subscriber tuple, so tearing a stream down can never deadlock here."""
        del frames, time_info
        if status:
            logging.debug("Audio input stream status: %s", status)

        subscribers = self._subscribers
        if not subscribers:
            return

        try:
            # sounddevice reuses its buffer between callbacks, so one copy is
            # mandatory. Every subscriber shares that single copy read-only.
            chunk = indata.copy()
        except Exception as exc:  # pragma: no cover - defensive
            logging.debug("Audio input chunk copy failed: %s", exc)
            return

        for sub in subscribers:
            if not sub.active:
                continue
            try:
                sub.callback(chunk, self.sample_rate)
            except Exception as exc:
                self._callback_errors += 1
                logging.error("Audio subscriber %s failed on a chunk: %s", sub.name, exc)

    # -- diagnostics ---------------------------------------------------

    def status(self):
        with self._lock:
            return {
                "open": self.is_open(),
                "device": self._device,
                "sample_rate": self.sample_rate,
                "channels": self.channels,
                "blocksize": self.blocksize,
                "subscribers": self.subscriber_names(),
                "subscriber_count": len(self._subscribers),
                "fell_back_to_default": self._fell_back_to_default,
                "callback_errors": self._callback_errors,
                "last_error": self._last_error,
            }


_broker = None
_broker_lock = threading.Lock()


def get_broker():
    """The process-wide microphone owner. One per process by construction —
    that is the whole point of the module."""
    global _broker
    with _broker_lock:
        if _broker is None:
            _broker = AudioInputBroker()
        return _broker


def reset_broker_for_tests():
    """Drop the singleton after closing anything it holds.

    Test-only: unit tests share a process, and a subscription leaked by one
    test would otherwise keep the device "open" for the next one.
    """
    global _broker
    with _broker_lock:
        if _broker is not None:
            _broker.stop_all()
        _broker = None
