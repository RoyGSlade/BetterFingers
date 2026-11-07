"""Single-flight gate for the dictation pipeline (§6.3).

``is_processing_draft`` was a plain boolean: it was assigned, never
check-and-set, so two pipelines could interleave — overwriting the active job
id, clearing each other's cancellation event, and sharing the STT/LLM
instances concurrently. A boolean is not a mutex.

The coordinator owns the gate. ``try_begin`` atomically claims the pipeline
(non-blocking) and only then clears the shared cancellation event — a loser
never clears a cancel meant for the running job. ``finish`` releases the gate.

Prefer the ``session()`` context manager over raw try_begin/finish: it puts the
release in a finally that runs even if job creation or a state transition
raises immediately after admission, so the gate can never leak.

Pure threading, no server imports — unit-tested in
``tests/test_dictation_coordinator.py`` and ``tests/test_pipeline_single_flight.py``.
"""

import contextlib
import logging
import threading


class Lease:
    """Handle yielded by ``session()``. ``admitted`` says whether this caller
    won the gate; the token identifies the holder so a stale finish can't
    release someone else's lease."""

    __slots__ = ("admitted", "token")

    def __init__(self, admitted, token=None):
        self.admitted = admitted
        self.token = token


class DictationCoordinator:
    """Non-blocking single-flight gate with an owned cancellation event."""

    def __init__(self, cancellation_event=None):
        self._gate = threading.Lock()
        self._state_lock = threading.Lock()
        self._active_job_id = None
        self._holder_token = None  # identifies the current gate owner
        self._token_seq = 0
        self.cancellation_event = cancellation_event or threading.Event()

    @property
    def active_job_id(self):
        with self._state_lock:
            return self._active_job_id

    def is_busy(self):
        # Peek without acquiring: locked() is advisory, callers that need a
        # guarantee must use try_begin()/session().
        return self._gate.locked()

    def try_begin(self):
        """Claim the pipeline. Returns True if this caller now owns it.

        Only the winner clears the cancellation event, so a pending cancel for
        the running job can never be wiped by a rejected competitor.
        """
        if not self._gate.acquire(blocking=False):
            return False
        self._claim()
        return True

    def begin(self, timeout=None):
        """Blocking variant of try_begin for the held-recording dispatcher:
        wait (up to ``timeout`` seconds, forever when None) for the running
        pipeline to finish instead of rejecting. Returns True once this caller
        owns the gate; same clear-cancel semantics as try_begin."""
        if timeout is None:
            acquired = self._gate.acquire()
        else:
            acquired = self._gate.acquire(timeout=max(0.0, float(timeout)))
        if not acquired:
            return False
        self._claim()
        return True

    def _claim(self):
        with self._state_lock:
            self._token_seq += 1
            self._holder_token = self._token_seq
        self.cancellation_event.clear()

    def set_active_job(self, job_id):
        with self._state_lock:
            self._active_job_id = job_id

    def cancel_active(self):
        """Signal the running pipeline (if any) to stop. Returns the job id."""
        with self._state_lock:
            job_id = self._active_job_id
        self.cancellation_event.set()
        return job_id

    def finish(self, token=None):
        """Release the gate. Call exactly once after a successful try_begin.

        If ``token`` is given it must match the current holder — a mismatched or
        double release is logged and ignored rather than silently corrupting a
        newer holder's ownership.
        """
        with self._state_lock:
            if not self._gate.locked():
                logging.warning("DictationCoordinator.finish() called on an unheld gate; ignoring.")
                return
            if token is not None and token != self._holder_token:
                logging.warning("DictationCoordinator.finish() with a stale token; ignoring.")
                return
            self._active_job_id = None
            self._holder_token = None
        try:
            self._gate.release()
        except RuntimeError:
            # Defensive: the pipeline must never die on teardown.
            logging.warning("DictationCoordinator gate release raced; ignoring.")

    @contextlib.contextmanager
    def session(self):
        """Context manager wrapping admission + guaranteed release.

        Yields a :class:`Lease`. When ``lease.admitted`` is False the caller
        lost the gate and must not touch shared pipeline state. When True, the
        gate is released on exit even if the body raises before finishing — so
        a failure in job creation or a state transition can't leak the gate.
        """
        if not self.try_begin():
            yield Lease(admitted=False)
            return
        with self._state_lock:
            token = self._holder_token
        try:
            yield Lease(admitted=True, token=token)
        finally:
            self.finish(token=token)
