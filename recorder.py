import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

from audio_ducker import AudioDucker
from audio_gate import TrailingSilenceDetector
from utils import load_profile


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
    def __init__(self, sample_rate=16000, channels=1, device_index=None):
        self.sample_rate = sample_rate
        self.channels = channels
        self.device_index = device_index
        self.recording = False
        self.frames = []
        self.lock = threading.Lock()
        self.stream = None
        self.ducker = AudioDucker()
        self.started_at = 0.0

        self.chunk_callback: Optional[Callable[[np.ndarray, int], None]] = None
        self.chunk_queue = queue.Queue()
        self.chunk_worker = None
        self.chunk_worker_running = False

        # Hands-free auto-stop (Phase 10): built per-recording from the profile.
        self.on_auto_stop: Optional[Callable[[str], None]] = None
        self._auto_stop_detector: Optional[TrailingSilenceDetector] = None

    def set_chunk_callback(self, callback: Optional[Callable[[np.ndarray, int], None]]):
        self.chunk_callback = callback

    def set_auto_stop_callback(self, callback: Optional[Callable[[str], None]]):
        """Called (on a fresh thread) with a stop reason when trailing silence
        is detected. The owner should route it to its normal stop path."""
        self.on_auto_stop = callback

    def _build_auto_stop_detector(self, config):
        """Construct a TrailingSilenceDetector from profile config, or None when
        the feature is disabled. Silence thresholds default to the no-audio gate
        values so there is one silence definition to tune."""
        try:
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

    def start_recording(self, profile_name="Default"):
        with self.lock:
            if self.recording:
                logging.debug("Recorder already active; duplicate start ignored.")
                return

            self.recording = True
            self.frames = []
            self.started_at = time.time()
            self._auto_stop_detector = None
            logging.info("Recording started.")

            try:
                config = load_profile(profile_name)
                self._auto_stop_detector = self._build_auto_stop_detector(config)
                if config.get("audio_ducking", False):
                    duck_level_percent = float(config.get("audio_ducking_level_percent", 18.0))
                    restore_fallback_percent = float(
                        config.get("audio_ducking_fallback_return_percent", 100.0)
                    )
                    # Fire-and-forget ducking to avoid blocking recording start
                    def _duck_async():
                        try:
                            self.ducker.duck(
                                target_level=duck_level_percent / 100.0,
                                fallback_restore_level=restore_fallback_percent / 100.0,
                            )
                        except Exception as e:
                            logging.warning(f"Async ducking failed: {e}")
                    threading.Thread(target=_duck_async, daemon=True).start()
            except Exception as exc:
                logging.warning(f"Audio ducking configuration load failed: {exc}")

            self._start_chunk_worker()

            try:
                self.stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    device=self.device_index,
                    channels=self.channels,
                    dtype="float32",
                    callback=self._audio_callback,
                )
                self.stream.start()
            except Exception as exc:
                logging.error(f"Error starting audio stream: {exc}")
                self.recording = False
                self._stop_chunk_worker()
                self.ducker.unduck()

    def stop_recording(self, stop_reason="manual") -> RecordingResult:
        with self.lock:
            if not self.recording:
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
                if self.stream:
                    self.stream.stop()
                    self.stream.close()
                    self.stream = None
            finally:
                self._stop_chunk_worker()
                self.ducker.unduck()

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

    def _audio_callback(self, indata, frames, time_info, status):
        del frames, time_info
        if status:
            logging.warning(f"Audio status: {status}")

        chunk = indata.copy()
        self.frames.append(chunk)

        if self.chunk_callback:
            try:
                self.chunk_queue.put_nowait(np.asarray(chunk, dtype=np.float32).flatten())
            except Exception:
                pass
