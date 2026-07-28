import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

import audio_input_broker
import audio_schema
from audio_device_resolver import resolve_input_device
from audio_ducker import AudioDucker
from audio_gate import TrailingSilenceDetector
from utils import load_profile

# Recording reasons that mean "the user is not holding anything down". A wake
# word has no key release to end the command, so the trailing-silence detector
# is not optional for these the way it is for hold-to-talk.
HANDS_FREE_REASONS = frozenset({"wake_word"})


@dataclass
class RecordingResult:
    audio_data: np.ndarray
    sample_rate: int
    duration_seconds: float
    frame_count: int
    sample_count: int
    max_amplitude: float
    rms_amplitude: float
    stop_reason: str = "manual"


class AudioRecorder:
    def __init__(self, sample_rate=16000, channels=1, device_index=None, broker=None,
                 privacy_lease=None):
        self.sample_rate = sample_rate
        # `channels` is retained for API compatibility; the broker owns the
        # capture format and opens the shared stream as 16 kHz mono float32 —
        # the same format this recorder has always requested.
        self.channels = channels
        self.device_index = device_index
        self.recording = False
        self.frames = []
        self.lock = threading.Lock()
        # Since Wave 8A the recorder does not open the microphone itself: it
        # subscribes to audio_input_broker, the one process-wide device owner
        # (D-0013), so a running wake-word listener and a live dictation share
        # a single capture stream instead of competing for the hardware.
        # Injectable for tests; resolved lazily so importing the recorder never
        # constructs the broker.
        self._broker = broker
        self._subscription = None
        # Wave 8B: input voice privacy is a lease held for exactly as long as
        # the recording (D-0010). Acquired below at start, released on EVERY
        # stop path — normal, trailing-silence, watchdog, and the failed-start
        # branch right here. Emergency stop, privacy wipe and shutdown release
        # it too, from server.py; a crash is undone from the journal at the
        # next startup. Injectable for tests; resolved lazily so importing the
        # recorder never probes the audio server.
        self._privacy_lease = privacy_lease
        self.ducker = AudioDucker()
        self.started_at = 0.0
        # Why the current recording started. Set per start; read by the
        # trailing-silence choice and useful to anything downstream that needs
        # to know a clip was hands-free.
        self.start_reason = "manual"

        self.chunk_callback: Optional[Callable[[np.ndarray, int], None]] = None
        self.chunk_queue = queue.Queue()
        self.chunk_worker = None
        self.chunk_worker_running = False

        # Hands-free auto-stop (Phase 10): built per-recording from the profile.
        self.on_auto_stop: Optional[Callable[[str], None]] = None
        self._auto_stop_detector: Optional[TrailingSilenceDetector] = None

    def _get_broker(self):
        if self._broker is None:
            self._broker = audio_input_broker.get_broker()
        return self._broker

    def _get_privacy_lease(self):
        if self._privacy_lease is None:
            from backend.platform.audio_privacy import lease as privacy_lease

            self._privacy_lease = privacy_lease.get_lease()
        return self._privacy_lease

    def _acquire_privacy(self, config, reason):
        """Engage input voice privacy for this recording.

        Never raises and never blocks the recording: a dictation app that
        refused to record because another application's mixer was unreachable
        would trade the user's actual task for a secondary protection. The
        failure is reported through the lease's status instead.
        """
        try:
            self._get_privacy_lease().acquire(config, reason=reason)
        except Exception as exc:
            logging.warning(f"Voice privacy could not be engaged: {exc}")

    def _release_privacy(self, reason):
        """Release the lease. Idempotent, so every stop path can call it
        unconditionally without knowing whether one was ever held."""
        try:
            self._get_privacy_lease().release(reason=reason)
        except Exception as exc:
            logging.warning(f"Voice privacy could not be released: {exc}")

    def set_chunk_callback(self, callback: Optional[Callable[[np.ndarray, int], None]]):
        self.chunk_callback = callback

    def set_auto_stop_callback(self, callback: Optional[Callable[[str], None]]):
        """Called (on a fresh thread) with a stop reason when trailing silence
        is detected. The owner should route it to its normal stop path."""
        self.on_auto_stop = callback

    def _build_auto_stop_detector(self, config, reason="manual"):
        """Construct a TrailingSilenceDetector from profile config, or None when
        the feature is disabled. Silence thresholds default to the no-audio gate
        values so there is one silence definition to tune.

        A hands-free start (``reason="wake_word"``) always gets a detector,
        whatever ``auto_stop_after_silence_enabled`` says: there is no key
        release to end a spoken command, so without one the recording would run
        until the watchdog force-stops it. It uses
        :func:`wake_pretrigger.build_command_capture_detector`, which reuses
        this same class and the same profile silence thresholds — one notion of
        "silence", tighter timing.
        """
        try:
            if reason in HANDS_FREE_REASONS:
                import wake_pretrigger

                return wake_pretrigger.build_command_capture_detector(config)
            if not config.get("auto_stop_after_silence_enabled", False):
                return None
            return TrailingSilenceDetector(
                silence_ms=config.get("auto_stop_silence_ms", 900),
                min_recording_ms=config.get("auto_stop_min_recording_ms", 700),
                rms_threshold=config.get("auto_stop_rms_threshold", config.get("no_audio_min_rms", 0.003)),
                peak_threshold=config.get("auto_stop_peak_threshold", config.get("no_audio_min_peak", 0.015)),
            )
        except Exception as exc:
            logging.debug(f"Auto-stop detector setup failed: {exc}")
            return None

    def start_recording(self, profile_name="Default", reason="manual", prepend_audio=None):
        """Begin capturing.

        ``reason`` is the trigger that started this recording (``"wake_word"``,
        ``"keyboard_ptt"``, ...). It is not decoration: a wake-started
        recording gets trailing-silence command capture, because nothing else
        will end it.

        ``prepend_audio`` is the wake handoff's pre-roll — the audio the wake
        listener already heard while it was recognizing the phrase. Prepending
        it is what stops the first word of the command being lost, and it is
        placed before the first live chunk arrives so ordering cannot race.
        """
        with self.lock:
            if self.recording:
                logging.debug("Recorder already active; duplicate start ignored.")
                return

            self.recording = True
            self.frames = []
            self.started_at = time.time()
            self._auto_stop_detector = None
            self.start_reason = reason
            self._seed_frames(prepend_audio)
            logging.info("Recording started.")

            # Input device: the system default (None) unless the active profile
            # selects a specific microphone (input_device_index >= 0).
            device = self.device_index

            try:
                config = load_profile(profile_name)
                self._auto_stop_detector = self._build_auto_stop_detector(config, reason=reason)
                # Voice privacy is engaged before the stream opens, so no other
                # capture client hears the first block we do.
                self._acquire_privacy(config, reason)
                configured_device = config.get("input_device_index", -1)
                if isinstance(configured_device, int) and configured_device >= 0:
                    device = configured_device
                    # The stored index is only a hint — PortAudio indices shift
                    # after reboots/USB churn. Resolve the saved fingerprint to
                    # the device's current index; an unresolvable fingerprint
                    # keeps the hint, and the existing fallback below still
                    # rescues a failed open with the system default.
                    fingerprint = config.get("input_device_fingerprint")
                    resolved = resolve_input_device(fingerprint) if fingerprint else None
                    if resolved is not None:
                        if resolved != configured_device:
                            logging.info(
                                f"Input device '{fingerprint.get('name')}' moved from index "
                                f"{configured_device} to {resolved}; using the current index."
                            )
                        device = resolved
                # Output ducking only (D-0010): lowering the speakers is a
                # separate setting from input voice privacy, which the injector
                # drives from voice_privacy.mode. audio_schema reads the new
                # block and falls back to the legacy flat keys, so a profile
                # that has not been migrated yet behaves exactly as before.
                ducking = audio_schema.output_ducking_of(config)
                if ducking["enabled"]:
                    duck_level_percent = float(ducking["target_percent"])
                    restore_fallback_percent = float(ducking["restore_fallback_percent"])
                    # Fire-and-forget ducking to avoid blocking recording start.
                    # The generation captured here lets a stop that lands before
                    # the thread commits cancel the duck instead of losing the
                    # race and stranding the system quiet.
                    duck_generation = self.ducker.generation()

                    def _duck_async():
                        try:
                            self.ducker.duck(
                                target_level=duck_level_percent / 100.0,
                                fallback_restore_level=restore_fallback_percent / 100.0,
                                generation=duck_generation,
                            )
                        except Exception as e:
                            logging.warning(f"Async ducking failed: {e}")
                    threading.Thread(target=_duck_async, daemon=True).start()
            except Exception as exc:
                logging.warning(f"Audio ducking configuration load failed: {exc}")

            self._start_chunk_worker()

            # The broker owns device selection from here: it opens the shared
            # stream, and a selected microphone that is unplugged, busy, or
            # invalid still falls back to the system default rather than
            # dropping the recording (the behavior this path has always had).
            subscription = self._get_broker().subscribe(
                "recorder", self._on_chunk, device=device, allow_default_fallback=True
            )
            if subscription is None:
                logging.error("Error starting audio capture: no input device could be opened.")
                self.recording = False
                self.frames = []
                self._stop_chunk_worker()
                self.ducker.unduck()
                # The recording never happened, so nothing may be left muted.
                self._release_privacy("recorder_failed")
                return
            self._subscription = subscription

    def _seed_frames(self, prepend_audio):
        """Place the wake pre-roll at the head of the clip, before capture.

        Called with the lock held and ``self.frames`` freshly emptied, so the
        pre-roll can only ever land first. A malformed or empty pre-roll is
        dropped rather than allowed to break the recording — losing the first
        word is bad, losing the whole command is worse.
        """
        if prepend_audio is None:
            return 0
        try:
            audio = np.asarray(prepend_audio, dtype=np.float32).reshape(-1)
        except (TypeError, ValueError) as exc:
            logging.warning(f"Wake pre-roll could not be prepended: {exc}")
            return 0
        if audio.size == 0:
            return 0
        self.frames.append(audio)
        logging.debug("Prepended %d frames of wake pre-trigger audio.", int(audio.size))
        return int(audio.size)

    def prepend_audio(self, audio):
        """Public entry point for the wake handoff (D-0013).

        Prefer passing ``prepend_audio=`` to :meth:`start_recording`, which
        cannot race an incoming chunk. This exists for the case where the
        pre-roll only becomes available after the start call, and it inserts
        at the head so ordering is preserved either way. A no-op when not
        recording — audio handed to a stopped recorder is dropped, never
        buffered for the next clip.
        """
        with self.lock:
            if not self.recording:
                return 0
            try:
                array = np.asarray(audio, dtype=np.float32).reshape(-1)
            except (TypeError, ValueError) as exc:
                logging.warning(f"Wake pre-roll could not be prepended: {exc}")
                return 0
            if array.size == 0:
                return 0
            self.frames.insert(0, array)
            return int(array.size)

    def stop_recording(self, stop_reason="manual") -> RecordingResult:
        with self.lock:
            if not self.recording:
                # Not recording, but a stop path still ran: release
                # unconditionally so no caller has to know whether privacy was
                # engaged. Idempotent by construction.
                self._release_privacy(stop_reason)
                return RecordingResult(
                    audio_data=np.array([], dtype=np.float32),
                    sample_rate=self.sample_rate,
                    duration_seconds=0.0,
                    frame_count=0,
                    sample_count=0,
                    max_amplitude=0.0,
                    rms_amplitude=0.0,
                    stop_reason=stop_reason,
                )

            self.recording = False
            self._auto_stop_detector = None
            logging.info(f"Recording stopped. reason={stop_reason}")

            try:
                subscription = self._subscription
                self._subscription = None
                if subscription is not None:
                    # Releases the microphone unless another subscriber (a
                    # running wake-word listener) still holds it.
                    subscription.close()
            finally:
                self._stop_chunk_worker()
                self.ducker.unduck()
                # Every ordinary end of a recording arrives here: manual stop,
                # trailing-silence auto-stop, and the watchdog force-stop all
                # call stop_recording. In `finally` so a failure closing the
                # subscription cannot strand another application's microphone.
                self._release_privacy(stop_reason)

            frame_count = len(self.frames)
            duration = max(0.0, time.time() - self.started_at)

            if frame_count == 0:
                return RecordingResult(
                    audio_data=np.array([], dtype=np.float32),
                    sample_rate=self.sample_rate,
                    duration_seconds=duration,
                    frame_count=0,
                    sample_count=0,
                    max_amplitude=0.0,
                    rms_amplitude=0.0,
                    stop_reason=stop_reason,
                )

            raw_data = np.concatenate(self.frames, axis=0)
            flat_data = np.asarray(raw_data, dtype=np.float32).flatten()
            sample_count = int(flat_data.size)
            max_amp = float(np.max(np.abs(flat_data))) if sample_count > 0 else 0.0
            rms_amp = float(np.sqrt(np.mean(np.square(flat_data)))) if sample_count > 0 else 0.0

            if max_amp == 0.0:
                logging.warning("Captured audio appears silent (peak=0.0).")

            return RecordingResult(
                audio_data=flat_data,
                sample_rate=self.sample_rate,
                duration_seconds=duration,
                frame_count=frame_count,
                sample_count=sample_count,
                max_amplitude=max_amp,
                rms_amplitude=rms_amp,
                stop_reason=stop_reason,
            )

    def _start_chunk_worker(self):
        self.chunk_queue = queue.Queue()
        self.chunk_worker_running = True
        self.chunk_worker = threading.Thread(target=self._chunk_worker_loop, daemon=True)
        self.chunk_worker.start()

    def _stop_chunk_worker(self):
        self.chunk_worker_running = False
        try:
            self.chunk_queue.put_nowait(None)
        except Exception:
            pass

        if self.chunk_worker and self.chunk_worker.is_alive():
            self.chunk_worker.join(timeout=1.5)
        self.chunk_worker = None

    def _chunk_worker_loop(self):
        while self.chunk_worker_running or not self.chunk_queue.empty():
            try:
                item = self.chunk_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                continue
            if self.chunk_callback:
                try:
                    self.chunk_callback(item, self.sample_rate)
                except Exception as exc:
                    logging.debug(f"Chunk callback error: {exc}")
            self._feed_auto_stop_detector(item)

    def _feed_auto_stop_detector(self, item):
        detector = self._auto_stop_detector
        callback = self.on_auto_stop
        if detector is None or callback is None:
            return
        try:
            arr = np.asarray(item, dtype=np.float32).flatten()
            n = int(arr.size)
            if n == 0:
                return
            rms = float(np.sqrt(np.mean(np.square(arr))))
            peak = float(np.max(np.abs(arr)))
            chunk_ms = (n / float(self.sample_rate)) * 1000.0
            if detector.update(rms, peak, chunk_ms):
                # Clear first so no further chunk can re-fire, then run the stop
                # on a fresh thread — calling stop from this worker would join
                # this very thread.
                self._auto_stop_detector = None
                threading.Thread(
                    target=callback, args=("trailing_silence",), daemon=True
                ).start()
        except Exception as exc:
            logging.debug(f"Auto-stop detector error: {exc}")

    def _on_chunk(self, indata, sample_rate):
        """Broker subscriber callback. ``indata`` is the broker's single copy
        of the captured block, shared read-only with every other subscriber —
        appended as-is and never modified in place."""
        del sample_rate
        if not self.recording:
            # A late in-flight callback after stop: don't extend the clip.
            return

        self.frames.append(indata)

        if self.chunk_callback:
            try:
                self.chunk_queue.put_nowait(np.asarray(indata, dtype=np.float32).flatten())
            except Exception:
                pass
