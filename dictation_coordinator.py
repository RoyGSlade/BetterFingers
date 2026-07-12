"""Single-flight gate for the dictation pipeline (§6.3).

``is_processing_draft`` was a plain boolean: it was assigned, never
check-and-set, so two pipelines could interleave — overwriting the active job
id, clearing each other's cancellation event, and sharing the STT/LLM
instances concurrently. A boolean is not a mutex.

The coordinator owns the gate. ``try_begin`` atomically claims the pipeline
(non-blocking) and only then clears the shared cancellation event — a loser
never clears a cancel meant for the running job. ``finish`` releases the gate
and is safe to call exactly once per successful ``try_begin``.

Pure threading, no server imports — unit-tested in
``tests/test_dictation_coordinator.py``.
"""

import threading


class DictationCoordinator:
    """Non-blocking single-flight gate with an owned cancellation event."""

    def __init__(self, cancellation_event=None):
        self._gate = threading.Lock()
        self._state_lock = threading.Lock()
        self._active_job_id = None
        self.cancellation_event = cancellation_event or threading.Event()

    @property
    def active_job_id(self):
        with self._state_lock:
            return self._active_job_id

    def is_busy(self):
        # Peek without acquiring: locked() is advisory, callers that need a
        # guarantee must use try_begin().
        return self._gate.locked()

    def try_begin(self):
        """Claim the pipeline. Returns True if this caller now owns it.

        Only the winner clears the cancellation event, so a pending cancel for
        the running job can never be wiped by a rejected competitor.
        """
        if not self._gate.acquire(blocking=False):
            return False
        self.cancellation_event.clear()
        return True

    def set_active_job(self, job_id):
        with self._state_lock:
            self._active_job_id = job_id

    def cancel_active(self):
        """Signal the running pipeline (if any) to stop. Returns the job id."""
        with self._state_lock:
            job_id = self._active_job_id
        self.cancellation_event.set()
        return job_id

    def finish(self):
        """Release the gate. Call exactly once after a successful try_begin."""
        with self._state_lock:
            self._active_job_id = None
        try:
            self._gate.release()
        except RuntimeError:
            # Defensive: releasing an unheld gate is a caller bug, but the
            # pipeline must never die on teardown.
            pass
