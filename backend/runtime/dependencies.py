"""Structural collaborator contracts for injected backend service runtimes.

Pure stdlib only: no FastAPI, model, or audio imports. Real collaborators
(``job_manager.JobManager``, a recovery-bin writer, a status broadcaster) and
test fakes both satisfy these protocols structurally — nothing here imports
the concrete implementations.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol, runtime_checkable


@runtime_checkable
class JobHandleLike(Protocol):
    id: str


@runtime_checkable
class JobManagerLike(Protocol):
    """The subset of ``job_manager.JobManager`` a pipeline needs."""

    def create(self, kind: str, label: Optional[str] = None) -> JobHandleLike: ...

    def transition(self, job_id: str, state: str) -> Any: ...

    def complete(self, job_id: str, result_ref: Optional[str] = None) -> Any: ...

    def fail(self, job_id: str, error: str = "") -> Any: ...

    def mark_cancelled(self, job_id: str) -> Any: ...

    def is_cancel_requested(self, job_id: str) -> bool: ...


@runtime_checkable
class RecoverySinkLike(Protocol):
    """Persists the raw recording so it survives a crash/cancel/failure."""

    def save(self, recording_result: Any, *, reason: str) -> Optional[str]: ...


@runtime_checkable
class StatusReporterLike(Protocol):
    """Broadcasts pipeline progress. Optional — defaults to a no-op."""

    def emit(self, status: str, payload: dict) -> None: ...


class NullStatusReporter:
    """Default :class:`StatusReporterLike` that discards every event."""

    def emit(self, status: str, payload: dict) -> None:
        return None


@runtime_checkable
class CancelEventLike(Protocol):
    """The subset of ``threading.Event`` a cancellation source needs."""

    def is_set(self) -> bool: ...


class JobManagerCancellationBridge:
    """Adapts a real job manager to :class:`JobManagerLike`, folding in an
    extra cancellation source that the job manager itself doesn't know about.

    Some cancel triggers (e.g. a privacy wipe quiescing the pipeline) only
    set a shared ``cancellation_event`` and never call the job manager's own
    ``request_cancel`` — so checking the job manager alone would miss them.
    This bridge ORs the two together, matching a single combined check.
    Every other method delegates straight through to the wrapped manager.
    """

    def __init__(self, job_manager: JobManagerLike, cancellation_event: CancelEventLike):
        self._job_manager = job_manager
        self._cancellation_event = cancellation_event

    def create(self, kind: str, label: Optional[str] = None) -> JobHandleLike:
        return self._job_manager.create(kind, label=label)

    def transition(self, job_id: str, state: str) -> Any:
        return self._job_manager.transition(job_id, state)

    def complete(self, job_id: str, result_ref: Optional[str] = None) -> Any:
        return self._job_manager.complete(job_id, result_ref=result_ref)

    def fail(self, job_id: str, error: str = "") -> Any:
        return self._job_manager.fail(job_id, error=error)

    def mark_cancelled(self, job_id: str) -> Any:
        return self._job_manager.mark_cancelled(job_id)

    def is_cancel_requested(self, job_id: str) -> bool:
        return self._cancellation_event.is_set() or self._job_manager.is_cancel_requested(job_id)


@dataclass
class PipelineDependencies:
    """Explicit collaborators for :class:`backend.services.dictation_pipeline.DictationPipeline`.

    Construct with fakes in tests, or with the real ``job_manager.JOBS`` /
    a recordings-backed recovery sink / the status broadcaster once A1.9
    wires this shell into ``server.process_recording_result``.
    """

    job_manager: JobManagerLike
    recovery_sink: RecoverySinkLike
    status_reporter: StatusReporterLike = field(default_factory=NullStatusReporter)
    clock: Callable[[], float] = time.perf_counter
