"""Dependency-injected dictation pipeline shell (Phase 1 Wave 1B, A1.6).

This defines the reusable ordering/cancellation/error/recovery runner that
A1.9 will fill with real named stages (transcribe, post-process, rewrite,
finalize) and wire behind ``server.process_recording_result`` as a
compatibility wrapper. It intentionally has no FastAPI, model, or audio
imports: every collaborator is injected via
``backend.runtime.dependencies.PipelineDependencies``, and stages are plain
named callables, so the whole shell is exercisable with fakes alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Protocol, runtime_checkable

from backend.runtime.dependencies import PipelineDependencies


class PipelineStatus:
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


ALL_STATUSES = frozenset(
    {PipelineStatus.COMPLETED, PipelineStatus.CANCELLED, PipelineStatus.FAILED}
)


@dataclass
class PipelineContext:
    """Mutable state threaded through the pipeline stages in order.

    ``extra`` is an open bag a stage can use for data with no named field yet
    (e.g. structured transcription/signal results land here until a later
    wave promotes them to explicit attributes).
    """

    recording_result: Any
    metadata: dict = field(default_factory=dict)
    raw_text: str = ""
    final_text: str = ""
    draft: Any = None
    extra: dict = field(default_factory=dict)


@dataclass
class PipelineOutcome:
    """The terminal result of one pipeline run."""

    status: str
    stage_reached: Optional[str]
    context: PipelineContext
    job_id: Optional[str] = None
    recovery_ref: Optional[str] = None
    error: str = ""
    exception: Optional[BaseException] = None

    @property
    def completed(self) -> bool:
        return self.status == PipelineStatus.COMPLETED

    @property
    def cancelled(self) -> bool:
        return self.status == PipelineStatus.CANCELLED

    @property
    def failed(self) -> bool:
        return self.status == PipelineStatus.FAILED


@runtime_checkable
class PipelineStage(Protocol):
    """One named unit of work. ``run`` mutates ``ctx`` in place.

    ``job_state`` is the state passed to ``job_manager.transition`` when this
    stage starts; it defaults to ``name`` so stage names that already match
    ``job_manager.JobState`` values (e.g. "transcribing", "refining") need no
    extra wiring. Unknown state strings are a no-op in the real JobManager,
    so a stage can use a purely descriptive name without breaking anything.
    """

    name: str
    job_state: Optional[str]

    def run(self, ctx: PipelineContext, deps: PipelineDependencies) -> None: ...


@dataclass(frozen=True)
class FunctionStage:
    """Adapt a plain function into a :class:`PipelineStage` — used by tests
    and by real stage implementations alike."""

    name: str
    func: Callable[[PipelineContext, PipelineDependencies], None]
    job_state: Optional[str] = None

    def run(self, ctx: PipelineContext, deps: PipelineDependencies) -> None:
        self.func(ctx, deps)


class DictationPipeline:
    """Runs named stages over a :class:`PipelineContext`, honoring cooperative
    cancellation and guaranteeing raw-audio recovery before any stage runs.

    No stage implementation lives here: this is the ordering/cancellation/
    error/recovery shell A1.9 wires real STT/rewrite stages into.
    """

    def __init__(
        self,
        stages: List[PipelineStage],
        deps: PipelineDependencies,
        kind: str = "dictation",
        label: Optional[str] = None,
    ):
        self._stages = list(stages)
        self._deps = deps
        self._kind = kind
        self._label = label or kind

    @property
    def stage_names(self) -> List[str]:
        return [stage.name for stage in self._stages]

    def run(
        self,
        recording_result: Any,
        *,
        metadata: Optional[dict] = None,
        job: Any = None,
    ) -> PipelineOutcome:
        """Run every stage in order over a fresh context.

        ``job`` lets a caller pre-create the job (via its own
        ``job_manager.create``) and pass it in — needed when the job id must
        be visible to external cancel-dispatch (e.g. a REST cancel endpoint)
        *before* the first stage starts, which a job created internally here
        cannot provide in time. When omitted, a job is created exactly as
        before.

        A stage may set ``ctx.extra["_pipeline_stop"] = True`` to end the run
        early as COMPLETED (not cancelled/failed) — e.g. a domain-specific
        gate (no usable audio, an edit command that short-circuits the rest
        of the pipeline) that is a legitimate terminal outcome, not an error.
        Setting ``ctx.extra["result_ref"]`` (from that stage or the final
        one) overrides ``recovery_ref`` as the ``result_ref`` passed to
        ``job_manager.complete`` — the recovery reference and "what this job
        produced" are different things once real stages produce a result.
        """
        ctx = PipelineContext(recording_result=recording_result, metadata=dict(metadata or {}))
        if job is not None:
            job_id = getattr(job, "id", None)
        else:
            job = self._deps.job_manager.create(self._kind, label=self._label)
            job_id = getattr(job, "id", None)

        # Persist the raw recording up front so it survives a crash, an
        # error, or a cancellation partway through — mirrors the existing
        # recovery-first behavior in server.process_recording_result.
        recovery_ref = self._deps.recovery_sink.save(recording_result, reason="pre-pipeline")

        stage_reached: Optional[str] = None
        for stage in self._stages:
            stage_reached = stage.name
            if self._deps.job_manager.is_cancel_requested(job_id):
                self._deps.job_manager.mark_cancelled(job_id)
                return PipelineOutcome(
                    status=PipelineStatus.CANCELLED,
                    stage_reached=stage_reached,
                    context=ctx,
                    job_id=job_id,
                    recovery_ref=recovery_ref,
                )
            job_state = getattr(stage, "job_state", None) or stage.name
            self._deps.job_manager.transition(job_id, job_state)
            try:
                stage.run(ctx, self._deps)
            except InterruptedError as exc:
                self._deps.job_manager.mark_cancelled(job_id)
                return PipelineOutcome(
                    status=PipelineStatus.CANCELLED,
                    stage_reached=stage_reached,
                    context=ctx,
                    job_id=job_id,
                    recovery_ref=recovery_ref,
                    error=str(exc),
                    exception=exc,
                )
            except Exception as exc:
                self._deps.job_manager.fail(job_id, str(exc))
                return PipelineOutcome(
                    status=PipelineStatus.FAILED,
                    stage_reached=stage_reached,
                    context=ctx,
                    job_id=job_id,
                    recovery_ref=recovery_ref,
                    error=str(exc),
                    exception=exc,
                )
            if ctx.extra.get("_pipeline_stop"):
                result_ref = ctx.extra.get("result_ref", recovery_ref)
                self._deps.job_manager.complete(job_id, result_ref=result_ref)
                return PipelineOutcome(
                    status=PipelineStatus.COMPLETED,
                    stage_reached=stage_reached,
                    context=ctx,
                    job_id=job_id,
                    recovery_ref=recovery_ref,
                )

        result_ref = ctx.extra.get("result_ref", recovery_ref)
        self._deps.job_manager.complete(job_id, result_ref=result_ref)
        return PipelineOutcome(
            status=PipelineStatus.COMPLETED,
            stage_reached=stage_reached,
            context=ctx,
            job_id=job_id,
            recovery_ref=recovery_ref,
        )
