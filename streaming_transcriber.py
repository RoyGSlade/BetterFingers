"""Streaming batch transcription: Whisper keeps up while recording continues.

The recorder's chunk stream is segmented into silence-bounded batches
(:class:`BatchCutter`) and a dedicated worker thread transcribes each batch as
it is cut (:class:`StreamingTranscriptionSession`) — so by the time the user
stops talking, most of the transcript already exists and the stop→draft wait
collapses to draining whatever the worker hasn't finished yet.

Both classes are model-free by construction: the session takes a
``transcribe_fn(audio) -> (text, confidence_dict)`` callable (server.py wraps
the shared Transcriber + its STT read lease), and the cutter is pure
numpy-on-chunks logic. Unit-tested without loading Whisper in
``tests/test_streaming_transcriber.py``.
"""

import logging
import queue
import threading
import time

import numpy as np

from log_redaction import redact_exc

# A cut is only forced mid-speech once the pending buffer hits the max batch
# length; the cut point is then the quietest chunk in this trailing fraction of
# the buffer, so a forced boundary still lands on the least-speechy moment.
_FORCED_CUT_SEARCH_FRACTION = 0.25


class BatchCutter:
    """Segment a live chunk stream into Whisper-sized batches.

    Feed order defines batch order. A batch is cut when the pending audio is at
    least ``min_batch_seconds`` long and ends in ``silence_ms`` of trailing
    silence (natural pause), or unconditionally at ``max_batch_seconds`` — then
    at the quietest chunk near the tail so a forced cut avoids splitting a word.
    Silence uses the same RMS/peak definition as the no-audio gate.
    """

    def __init__(
        self,
        sample_rate=16000,
        min_batch_seconds=3.0,
        max_batch_seconds=12.0,
        silence_ms=600,
        rms_threshold=0.003,
        peak_threshold=0.015,
    ):
        self.sample_rate = max(1, int(sample_rate))
        self.min_batch_seconds = max(0.5, float(min_batch_seconds))
        self.max_batch_seconds = max(self.min_batch_seconds, float(max_batch_seconds))
        self.silence_ms = max(100, int(silence_ms))
        self.rms_threshold = float(rms_threshold)
        self.peak_threshold = float(peak_threshold)

        # Pending chunks: list of (array, duration_ms, is_silent).
        self._chunks = []
        self._pending_ms = 0.0

    def _pending_seconds(self):
        return self._pending_ms / 1000.0

    def _trailing_silence_ms(self):
        total = 0.0
        for _, ms, silent in reversed(self._chunks):
            if not silent:
                break
            total += ms
        return total

    def _has_speech(self):
        return any(not silent for _, _, silent in self._chunks)

    def _cut(self, count):
        """Remove the first ``count`` chunks and return them as one batch."""
        taken = self._chunks[:count]
        self._chunks = self._chunks[count:]
        self._pending_ms = sum(ms for _, ms, _ in self._chunks)
        return np.concatenate([arr for arr, _, _ in taken])

    def _forced_cut_index(self):
        """Chunk index to cut AFTER when the max-length cut fires: the quietest
        chunk in the trailing search window (ties go to the latest, keeping
        batches long). Falls back to the last chunk (cut everything)."""
        n = len(self._chunks)
        if n <= 1:
            return n - 1
        window = max(1, int(n * _FORCED_CUT_SEARCH_FRACTION))
        start = n - window
        best_idx = n - 1
        best_rms = None
        for i in range(start, n):
            arr = self._chunks[i][0]
            rms = float(np.sqrt(np.mean(np.square(arr)))) if arr.size else 0.0
            if best_rms is None or rms <= best_rms:
                best_rms = rms
                best_idx = i
        return best_idx

    def feed(self, chunk):
        """Add one recorder chunk. Returns a list of 0..n complete batches."""
        arr = np.asarray(chunk, dtype=np.float32).flatten()
        if arr.size == 0:
            return []
        rms = float(np.sqrt(np.mean(np.square(arr))))
        peak = float(np.max(np.abs(arr)))
        ms = (arr.size / float(self.sample_rate)) * 1000.0
        silent = rms < self.rms_threshold and peak < self.peak_threshold
        self._chunks.append((arr, ms, silent))
        self._pending_ms += ms

        batches = []
        while True:
            seconds = self._pending_seconds()
            if seconds >= self.max_batch_seconds:
                # A forced cut of pure silence (user thinking) is dropped, not
                # transcribed: nothing to hear, and silence is what makes
                # Whisper hallucinate ("thank you", "the end", ...).
                count = self._forced_cut_index() + 1
                had_speech = any(not s for _, _, s in self._chunks[:count])
                batch = self._cut(count)
                if had_speech:
                    batches.append(batch)
                continue
            if (
                seconds >= self.min_batch_seconds
                and self._has_speech()
                and self._trailing_silence_ms() >= self.silence_ms
            ):
                batches.append(self._cut(len(self._chunks)))
                continue
            break
        return batches

    def flush(self):
        """Return whatever is pending as a final batch (or None when empty)."""
        if not self._chunks:
            return None
        return self._cut(len(self._chunks))


def aggregate_confidence(parts):
    """Combine per-batch confidence dicts into one draft-level dict with the
    same shape ({score, avg_logprob, no_speech_prob}).

    score/avg_logprob are duration-weighted means over batches that reported
    them; no_speech_prob keeps the worst batch (same pessimism as the
    single-pass path). ``parts`` is a list of (confidence_dict, duration_sec).
    """
    total = 0.0
    score_sum = 0.0
    logprob_sum = 0.0
    logprob_dur = 0.0
    worst_no_speech = None
    for conf, dur in parts:
        if not isinstance(conf, dict):
            continue
        dur = max(0.001, float(dur or 0.0))
        score = conf.get("score")
        if score is not None:
            score_sum += float(score) * dur
            total += dur
        logprob = conf.get("avg_logprob")
        if logprob is not None:
            logprob_sum += float(logprob) * dur
            logprob_dur += dur
        no_speech = conf.get("no_speech_prob")
        if no_speech is not None:
            worst_no_speech = max(worst_no_speech or 0.0, float(no_speech))
    return {
        "score": round(score_sum / total, 3) if total else None,
        "avg_logprob": round(logprob_sum / logprob_dur, 3) if logprob_dur else None,
        "no_speech_prob": round(worst_no_speech, 3) if worst_no_speech is not None else None,
    }


class StreamingTranscriptionSession:
    """Transcribe cut batches on a worker thread while recording continues.

    ``feed()`` is called from the recorder's chunk-worker thread and only does
    O(chunk) math + a queue put, so it can never stall the audio path. The
    worker owns all transcribe_fn calls, keeping batch order (and therefore
    text order) trivially correct without cross-thread stitching.

    A transcribe_fn failure poisons the session (``ok=False``) rather than
    silently dropping a batch: the pipeline then falls back to the classic
    full-audio pass, so streaming can only ever make things faster, not lossier.
    """

    def __init__(self, transcribe_fn, sample_rate=16000, cutter=None, on_partial=None):
        self._transcribe_fn = transcribe_fn
        self.sample_rate = max(1, int(sample_rate))
        self._cutter = cutter or BatchCutter(sample_rate=self.sample_rate)
        self._on_partial = on_partial

        self._batch_queue = queue.Queue()
        self._results_lock = threading.Lock()
        self._texts = []
        self._conf_parts = []
        self._failed = False
        self._aborted = False
        self._finalized = False
        self.transcribe_ms_total = 0.0
        self.batch_count = 0

        self._worker = threading.Thread(
            target=self._run, daemon=True, name="betterfingers-streaming-stt"
        )
        self._worker.start()

    # -- producer side (recorder chunk-worker thread) --------------------

    def feed(self, chunk, sample_rate=None):
        del sample_rate  # the cutter was built for the recorder's rate
        if self._aborted or self._finalized:
            return
        for batch in self._cutter.feed(chunk):
            self._batch_queue.put(batch)

    # -- worker -----------------------------------------------------------

    def _run(self):
        while True:
            batch = self._batch_queue.get()
            if batch is None:
                return
            if self._aborted:
                continue  # drain without transcribing
            started = time.perf_counter()
            try:
                text, confidence = self._transcribe_fn(batch)
            except Exception as exc:
                self._failed = True
                logging.warning(f"Streaming batch transcription failed: {redact_exc(exc)}")
                continue
            self.transcribe_ms_total += (time.perf_counter() - started) * 1000.0
            duration = batch.size / float(self.sample_rate)
            with self._results_lock:
                self.batch_count += 1
                if str(text or "").strip():
                    self._texts.append(text.strip())
                self._conf_parts.append((confidence, duration))
                partial = " ".join(self._texts)
            if self._on_partial is not None:
                try:
                    self._on_partial(partial, self.batch_count)
                except Exception as exc:
                    logging.debug(f"Partial transcript callback failed: {redact_exc(exc)}")

    # -- consumer side (dispatcher thread, after recording stopped) -------

    def finalize(self, timeout=120.0):
        """Flush the tail, wait for the worker to drain, and return the joined
        transcript. Safe to call once; returns ok=False on failure/timeout so
        the caller falls back to full-audio transcription."""
        self._finalized = True
        tail = self._cutter.flush()
        if tail is not None:
            self._batch_queue.put(tail)
        self._batch_queue.put(None)
        self._worker.join(timeout=max(1.0, float(timeout)))
        timed_out = self._worker.is_alive()
        if timed_out:
            logging.warning("Streaming STT drain timed out; falling back to the full pass.")
        with self._results_lock:
            text = " ".join(self._texts).strip()
            confidence = aggregate_confidence(self._conf_parts)
            batches = self.batch_count
        ok = not (self._failed or self._aborted or timed_out)
        return {
            "ok": ok,
            "text": text if ok else "",
            "confidence": confidence,
            "batches": batches,
            "transcribe_ms_total": round(self.transcribe_ms_total, 1),
        }

    def abort(self):
        """Drop everything (privacy wipe / cancelled recording): the worker
        drains its queue without transcribing and buffered text is discarded."""
        self._aborted = True
        self._finalized = True
        with self._results_lock:
            self._texts = []
            self._conf_parts = []
        self._batch_queue.put(None)
