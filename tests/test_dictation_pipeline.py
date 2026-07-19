"""Pure tests for the A1.6 dictation pipeline shell.

No FastAPI, no live models, no real audio: every collaborator is a fake that
satisfies backend.runtime.dependencies' structural protocols.
"""

from dataclasses import dataclass

import pytest

from backend.runtime.dependencies import JobManagerCancellationBridge, PipelineDependencies
from backend.services.dictation_pipeline import (
    DictationPipeline,
    FunctionStage,
    PipelineStatus,
)


@dataclass
class FakeJob:
    id: str


class FakeJobManager:
    """Records every call so tests can assert on transition/terminal order."""

    def __init__(self):
        self.calls = []
        self._next_id = 0
        self._cancel_requested = False
        self.terminal_state = None
        self.terminal_error = ""
        self.terminal_result_ref = None

    def request_cancel(self):
        self._cancel_requested = True

    def create(self, kind, label=None):
        self._next_id += 1
        job = FakeJob(id=f"job-{self._next_id}")
        self.calls.append(("create", kind, label))
        return job

    def transition(self, job_id, state):
        self.calls.append(("transition", job_id, state))

    def complete(self, job_id, result_ref=None):
        self.calls.append(("complete", job_id, result_ref))
        self.terminal_state = "completed"
        self.terminal_result_ref = result_ref

    def fail(self, job_id, error=""):
        self.calls.append(("fail", job_id, error))
        self.terminal_state = "failed"
        self.terminal_error = error

    def mark_cancelled(self, job_id):
        self.calls.append(("mark_cancelled", job_id))
        self.terminal_state = "cancelled"

    def is_cancel_requested(self, job_id):
        return self._cancel_requested


class FakeRecoverySink:
    def __init__(self):
        self.saved = []

    def save(self, recording_result, *, reason):
        ref = f"recovery-{len(self.saved)}"
        self.saved.append((recording_result, reason, ref))
        return ref


def make_deps(job_manager=None, recovery_sink=None):
    return PipelineDependencies(
        job_manager=job_manager or FakeJobManager(),
        recovery_sink=recovery_sink or FakeRecoverySink(),
    )


def _recording_stage(order_log, name, job_state=None):
    def _run(ctx, deps):
        order_log.append(name)
        ctx.extra.setdefault("visited", []).append(name)

    return FunctionStage(name=name, func=_run, job_state=job_state)


# --- stage order -------------------------------------------------------------


def test_stages_run_in_declared_order_and_complete():
    order_log = []
    stages = [
        _recording_stage(order_log, "transcribe"),
        _recording_stage(order_log, "post_process"),
        _recording_stage(order_log, "rewrite"),
        _recording_stage(order_log, "finalize"),
    ]
    job_manager = FakeJobManager()
    deps = make_deps(job_manager=job_manager)
    pipeline = DictationPipeline(stages, deps)

    outcome = pipeline.run(recording_result="fake-audio")

    assert order_log == ["transcribe", "post_process", "rewrite", "finalize"]
    assert outcome.completed
    assert outcome.status == PipelineStatus.COMPLETED
    assert outcome.stage_reached == "finalize"
    assert pipeline.stage_names == ["transcribe", "post_process", "rewrite", "finalize"]

    transitions = [call[2] for call in job_manager.calls if call[0] == "transition"]
    assert transitions == ["transcribe", "post_process", "rewrite", "finalize"]
    assert job_manager.terminal_state == "completed"


def test_job_state_overrides_stage_name_for_transitions():
    job_manager = FakeJobManager()
    deps = make_deps(job_manager=job_manager)
    stage = FunctionStage(name="rewrite", func=lambda ctx, deps: None, job_state="refining")
    pipeline = DictationPipeline([stage], deps)

    pipeline.run(recording_result="fake-audio")

    transitions = [call[2] for call in job_manager.calls if call[0] == "transition"]
    assert transitions == ["refining"]


# --- cancellation -------------------------------------------------------------


def test_cancellation_before_a_stage_stops_the_pipeline():
    order_log = []
    job_manager = FakeJobManager()

    def _cancel_after_first(ctx, deps):
        order_log.append("first")
        job_manager.request_cancel()

    stages = [
        FunctionStage(name="first", func=_cancel_after_first),
        _recording_stage(order_log, "second"),
        _recording_stage(order_log, "third"),
    ]
    deps = make_deps(job_manager=job_manager)
    pipeline = DictationPipeline(stages, deps)

    outcome = pipeline.run(recording_result="fake-audio")

    assert order_log == ["first"]  # second/third never ran
    assert outcome.cancelled
    assert outcome.status == PipelineStatus.CANCELLED
    assert outcome.stage_reached == "second"
    assert job_manager.terminal_state == "cancelled"


def test_stage_raising_interrupted_error_is_treated_as_cancellation():
    job_manager = FakeJobManager()

    def _raise_interrupted(ctx, deps):
        raise InterruptedError("Operation cancelled by user.")

    stages = [FunctionStage(name="transcribe", func=_raise_interrupted)]
    deps = make_deps(job_manager=job_manager)
    pipeline = DictationPipeline(stages, deps)

    outcome = pipeline.run(recording_result="fake-audio")

    assert outcome.cancelled
    assert outcome.stage_reached == "transcribe"
    assert outcome.error == "Operation cancelled by user."
    assert job_manager.terminal_state == "cancelled"


# --- errors -------------------------------------------------------------------


def test_stage_error_fails_the_job_and_stops_the_pipeline():
    order_log = []
    job_manager = FakeJobManager()

    def _explode(ctx, deps):
        raise ValueError("llama-server unreachable")

    stages = [
        _recording_stage(order_log, "transcribe"),
        FunctionStage(name="rewrite", func=_explode),
        _recording_stage(order_log, "finalize"),
    ]
    deps = make_deps(job_manager=job_manager)
    pipeline = DictationPipeline(stages, deps)

    outcome = pipeline.run(recording_result="fake-audio")

    assert order_log == ["transcribe"]  # finalize never ran
    assert outcome.failed
    assert outcome.status == PipelineStatus.FAILED
    assert outcome.stage_reached == "rewrite"
    assert outcome.error == "llama-server unreachable"
    assert job_manager.terminal_state == "failed"
    assert job_manager.terminal_error == "llama-server unreachable"


# --- recovery result -----------------------------------------------------------


def test_recovery_sink_saves_raw_audio_before_any_stage_runs():
    recovery_sink = FakeRecoverySink()
    order_log = []

    def _check_recovery_already_saved(ctx, deps):
        # By the time the first stage runs, recovery has already happened.
        assert len(recovery_sink.saved) == 1
        order_log.append("transcribe")

    stages = [FunctionStage(name="transcribe", func=_check_recovery_already_saved)]
    deps = make_deps(recovery_sink=recovery_sink)
    pipeline = DictationPipeline(stages, deps)

    outcome = pipeline.run(recording_result="fake-audio", metadata={"stop_reason": "manual"})

    assert order_log == ["transcribe"]
    assert len(recovery_sink.saved) == 1
    saved_recording, reason, ref = recovery_sink.saved[0]
    assert saved_recording == "fake-audio"
    assert reason == "pre-pipeline"
    assert outcome.recovery_ref == ref


@pytest.mark.parametrize(
    "make_stage",
    [
        lambda: FunctionStage(name="transcribe", func=lambda ctx, deps: None),
        lambda: FunctionStage(name="transcribe", func=lambda ctx, deps: (_ for _ in ()).throw(ValueError("boom"))),
        lambda: FunctionStage(name="transcribe", func=lambda ctx, deps: (_ for _ in ()).throw(InterruptedError("cancelled"))),
    ],
)
def test_recovery_ref_surfaces_regardless_of_outcome(make_stage):
    recovery_sink = FakeRecoverySink()
    deps = make_deps(recovery_sink=recovery_sink)
    pipeline = DictationPipeline([make_stage()], deps)

    outcome = pipeline.run(recording_result="fake-audio")

    assert outcome.recovery_ref is not None
    assert outcome.recovery_ref == recovery_sink.saved[0][2]


def test_context_carries_metadata_and_extra_between_stages():
    def _first(ctx, deps):
        assert ctx.metadata == {"stop_reason": "manual"}
        ctx.raw_text = "hello world"
        ctx.extra["stt_ms"] = 12.5

    def _second(ctx, deps):
        assert ctx.raw_text == "hello world"
        assert ctx.extra["stt_ms"] == 12.5
        ctx.final_text = "Hello world."

    stages = [
        FunctionStage(name="transcribe", func=_first),
        FunctionStage(name="rewrite", func=_second),
    ]
    deps = make_deps()
    pipeline = DictationPipeline(stages, deps)

    outcome = pipeline.run(recording_result="fake-audio", metadata={"stop_reason": "manual"})

    assert outcome.completed
    assert outcome.context.final_text == "Hello world."


# --- A1.9 extensions: pre-created job, early-stop-completed, exception -------


def test_run_accepts_a_precreated_job_and_does_not_create_a_second_one():
    job_manager = FakeJobManager()
    deps = make_deps(job_manager=job_manager)
    pipeline = DictationPipeline([FunctionStage(name="only", func=lambda ctx, deps: None)], deps)
    precreated = job_manager.create("dictation", label="Dictation")
    job_manager.calls.clear()  # the pre-create above isn't part of what run() does

    outcome = pipeline.run(recording_result="fake-audio", job=precreated)

    assert outcome.job_id == precreated.id
    assert [call for call in job_manager.calls if call[0] == "create"] == []


def test_stage_can_stop_the_pipeline_early_as_completed_not_failed_or_cancelled():
    order_log = []
    job_manager = FakeJobManager()

    def _blocked_gate(ctx, deps):
        order_log.append("gate")
        ctx.extra["result_ref"] = "draft:blocked-1"
        ctx.extra["_pipeline_stop"] = True

    stages = [
        FunctionStage(name="gate", func=_blocked_gate),
        _recording_stage(order_log, "never_runs"),
    ]
    deps = make_deps(job_manager=job_manager)
    pipeline = DictationPipeline(stages, deps)

    outcome = pipeline.run(recording_result="fake-audio")

    assert order_log == ["gate"]  # never_runs skipped
    assert outcome.completed
    assert outcome.stage_reached == "gate"
    assert job_manager.terminal_state == "completed"
    assert job_manager.terminal_result_ref == "draft:blocked-1"


def test_result_ref_override_also_applies_to_natural_completion():
    job_manager = FakeJobManager()

    def _finalize(ctx, deps):
        ctx.extra["result_ref"] = "draft:42"

    deps = make_deps(job_manager=job_manager)
    pipeline = DictationPipeline([FunctionStage(name="finalize", func=_finalize)], deps)

    pipeline.run(recording_result="fake-audio")

    assert job_manager.terminal_result_ref == "draft:42"


def test_natural_completion_falls_back_to_recovery_ref_when_no_override():
    recovery_sink = FakeRecoverySink()
    job_manager = FakeJobManager()
    deps = make_deps(job_manager=job_manager, recovery_sink=recovery_sink)
    pipeline = DictationPipeline([FunctionStage(name="noop", func=lambda ctx, deps: None)], deps)

    pipeline.run(recording_result="fake-audio")

    assert job_manager.terminal_result_ref == recovery_sink.saved[0][2]


def test_failed_outcome_carries_the_original_exception_object():
    def _explode(ctx, deps):
        raise ValueError("llama-server unreachable")

    deps = make_deps()
    pipeline = DictationPipeline([FunctionStage(name="rewrite", func=_explode)], deps)

    outcome = pipeline.run(recording_result="fake-audio")

    assert isinstance(outcome.exception, ValueError)
    assert str(outcome.exception) == "llama-server unreachable"


def test_cancelled_via_interrupted_error_carries_the_original_exception_object():
    def _raise_interrupted(ctx, deps):
        raise InterruptedError("Operation cancelled by user.")

    deps = make_deps()
    pipeline = DictationPipeline([FunctionStage(name="transcribe", func=_raise_interrupted)], deps)

    outcome = pipeline.run(recording_result="fake-audio")

    assert isinstance(outcome.exception, InterruptedError)


def test_cancellation_detected_before_a_stage_has_no_exception_object():
    job_manager = FakeJobManager()
    job_manager.request_cancel()
    deps = make_deps(job_manager=job_manager)
    pipeline = DictationPipeline([FunctionStage(name="transcribe", func=lambda ctx, deps: None)], deps)

    outcome = pipeline.run(recording_result="fake-audio")

    assert outcome.cancelled
    assert outcome.exception is None
    assert outcome.error == ""


# --- JobManagerCancellationBridge ---------------------------------------------


class _FakeEvent:
    def __init__(self, set_=False):
        self._set = set_

    def is_set(self):
        return self._set


def test_bridge_delegates_lifecycle_calls_straight_through():
    job_manager = FakeJobManager()
    bridge = JobManagerCancellationBridge(job_manager, _FakeEvent(set_=False))

    job = bridge.create("dictation", label="Dictation")
    bridge.transition(job.id, "transcribing")
    bridge.complete(job.id, result_ref="draft:1")

    assert job_manager.terminal_state == "completed"
    assert job_manager.terminal_result_ref == "draft:1"


def test_bridge_is_cancel_requested_true_when_only_the_event_is_set():
    job_manager = FakeJobManager()  # job manager's own cancel flag stays False
    bridge = JobManagerCancellationBridge(job_manager, _FakeEvent(set_=True))

    assert bridge.is_cancel_requested("any-job-id") is True


def test_bridge_is_cancel_requested_true_when_only_the_job_manager_flag_is_set():
    job_manager = FakeJobManager()
    job_manager.request_cancel()
    bridge = JobManagerCancellationBridge(job_manager, _FakeEvent(set_=False))

    assert bridge.is_cancel_requested("any-job-id") is True


def test_bridge_is_cancel_requested_false_when_neither_is_set():
    job_manager = FakeJobManager()
    bridge = JobManagerCancellationBridge(job_manager, _FakeEvent(set_=False))

    assert bridge.is_cancel_requested("any-job-id") is False


def test_no_fastapi_or_model_imports_are_pulled_in():
    import subprocess
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    script = (
        "import sys; "
        "import backend.services.dictation_pipeline; "
        "leaked = [m for m in sys.modules if m.split('.')[0] in "
        "{'fastapi', 'starlette', 'torch', 'faster_whisper', 'server'}]; "
        "assert not leaked, leaked; "
        "print('OK')"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
