"""Central job registry for long-running work (§6.3).

Long recordings, TTS, cloning, Whisper, LLM cleanup, and model downloads all
compete for the same machine and can each take a while. This module gives every
unit of work a stable id, an observable state, progress, a resource estimate, and
cooperative cancellation — so the UI can show what is running and the user can
cancel it, and so abandoned work can be cleaned up.

Pure and thread-safe: no FastAPI/server imports, so it unit-tests in isolation.
The server owns one process-wide ``JOBS`` instance and threads job updates
alongside the status broadcasts it already emits.

State machine (a job moves forward through the relevant subset, then to exactly
one terminal state):

    queued → loading → capturing → transcribing → refining → stitching →
    review_ready → injecting → (completed | failed | cancelled)
"""

import threading
import time
import uuid
from typing import Callable, Dict, List, Optional


class JobState:
    QUEUED = "queued"
    LOADING = "loading"
    CAPTURING = "capturing"
    TRANSCRIBING = "transcribing"
    REFINING = "refining"
    STITCHING = "stitching"
    REVIEW_READY = "review_ready"
    INJECTING = "injecting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES = frozenset({JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED})
ALL_STATES = frozenset(
    {
        JobState.QUEUED,
        JobState.LOADING,
        JobState.CAPTURING,
        JobState.TRANSCRIBING,
        JobState.REFINING,
        JobState.STITCHING,
        JobState.REVIEW_READY,
        JobState.INJECTING,
        JobState.COMPLETED,
        JobState.FAILED,
        JobState.CANCELLED,
    }
)


def _clamp01(value):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num:  # NaN
        return None
    return max(0.0, min(1.0, num))


class Job:
    """A single unit of tracked work. Mutated only under the manager's lock."""

    __slots__ = (
        "id",
        "kind",
        "label",
        "state",
        "progress",
        "error",
        "result_ref",
        "resource_estimate",
        "created_at",
        "updated_at",
        "_cancel",
    )

    def __init__(self, job_id, kind, label, resource_estimate, now):
        self.id = job_id
        self.kind = kind
        self.label = label or kind
        self.state = JobState.QUEUED
        self.progress: Optional[float] = None
        self.error = ""
        self.result_ref = None
        self.resource_estimate = dict(resource_estimate or {})
        self.created_at = now
        self.updated_at = now
        self._cancel = threading.Event()

    @property
    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "state": self.state,
            "progress": self.progress,
            "error": self.error,
            "result_ref": self.result_ref,
            "resource_estimate": dict(self.resource_estimate),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "cancel_requested": self._cancel.is_set(),
        }


class JobManager:
    def __init__(self, max_finished: int = 50, clock: Callable[[], float] = time.time):
        self._jobs: Dict[str, Job] = {}
        self._order: List[str] = []
        self._lock = threading.RLock()
        self._max_finished = max(1, int(max_finished))
        self._clock = clock
        self._listeners: List[Callable[[dict], None]] = []

    # --- observation ---------------------------------------------------------
    def subscribe(self, listener: Callable[[dict], None]):
        """Register a callback invoked with a public snapshot on every change.
        Used to bridge job updates onto the existing status WebSocket."""
        with self._lock:
            self._listeners.append(listener)

    def _emit(self, job: Job):
        snapshot = job.to_public()
        for listener in list(self._listeners):
            try:
                listener(snapshot)
            except Exception:
                pass

    # --- lifecycle -----------------------------------------------------------
    def create(self, kind: str, label: Optional[str] = None, resource_estimate: Optional[dict] = None) -> Job:
        with self._lock:
            job_id = uuid.uuid4().hex[:12]
            job = Job(job_id, kind, label, resource_estimate, self._clock())
            self._jobs[job_id] = job
            self._order.append(job_id)
            self._prune_locked()
        self._emit(job)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, active_only: bool = False) -> List[dict]:
        with self._lock:
            jobs = [self._jobs[jid] for jid in self._order if jid in self._jobs]
        if active_only:
            jobs = [j for j in jobs if not j.is_terminal]
        return [j.to_public() for j in jobs]

    def _set_locked(self, job: Job, state=None, progress=None):
        if state is not None:
            job.state = state
        if progress is not None:
            clamped = _clamp01(progress)
            if clamped is not None:  # ignore un-parseable progress, don't null it
                job.progress = clamped
        job.updated_at = self._clock()

    def transition(self, job_id: str, state: str, progress=None) -> Optional[Job]:
        """Move a non-terminal job to ``state``. No-op (returns None) if the job
        is unknown, already terminal, or ``state`` is not a known state."""
        if state not in ALL_STATES:
            return None
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.is_terminal:
                return None
            self._set_locked(job, state, progress)
        self._emit(job)
        return job

    def update_progress(self, job_id: str, progress) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.is_terminal:
                return None
            self._set_locked(job, None, progress)
        self._emit(job)
        return job

    def complete(self, job_id: str, result_ref=None) -> Optional[Job]:
        return self._finish(job_id, JobState.COMPLETED, result_ref=result_ref)

    def fail(self, job_id: str, error: str = "") -> Optional[Job]:
        return self._finish(job_id, JobState.FAILED, error=str(error or ""))

    def mark_cancelled(self, job_id: str) -> Optional[Job]:
        """Move a job to the terminal CANCELLED state (call once the worker has
        actually unwound in response to a cancel request)."""
        return self._finish(job_id, JobState.CANCELLED)

    def _finish(self, job_id: str, state: str, result_ref=None, error="") -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.is_terminal:
                return None
            if result_ref is not None:
                job.result_ref = result_ref
            if error:
                job.error = error
            self._set_locked(job, state)
            self._prune_locked()
        self._emit(job)
        return job

    # --- cancellation --------------------------------------------------------
    def request_cancel(self, job_id: str) -> bool:
        """Cooperatively signal a running job to stop. The worker observes
        :meth:`is_cancel_requested` and then calls :meth:`mark_cancelled`.
        Returns False for unknown or already-terminal jobs."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.is_terminal:
                return False
            job._cancel.set()
            job.updated_at = self._clock()
        self._emit(job)
        return True

    def cancel(self, job_id: str) -> Optional[Job]:
        """Signal cancellation AND move straight to CANCELLED — for work that has
        not started or can be abandoned immediately."""
        if not self.request_cancel(job_id):
            return None
        return self.mark_cancelled(job_id)

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job and job._cancel.is_set())

    # --- housekeeping --------------------------------------------------------
    def _prune_locked(self):
        """Drop the oldest terminal jobs beyond the cap; never drop active work."""
        terminal_ids = [jid for jid in self._order if jid in self._jobs and self._jobs[jid].is_terminal]
        excess = len(terminal_ids) - self._max_finished
        for jid in terminal_ids[:max(0, excess)]:
            self._jobs.pop(jid, None)
        self._order = [jid for jid in self._order if jid in self._jobs]

    def clear(self):
        with self._lock:
            self._jobs.clear()
            self._order.clear()


# Process-wide instance the server threads job updates through.
JOBS = JobManager()
