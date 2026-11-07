"""Instrumentation must be invisible: whatever the recorder does (works, is off,
raises from every method, or is lock-contended), the dictation-visible outputs of
the real stop -> enqueue -> dispatcher -> process_recording_result flow are identical.

Compared per scenario: ordered create_draft calls (args), the broadcast sequence
(event names + payloads), recovery saves, process_recording_result's call
arguments and return value, stop-path exceptions and post-run gate state.
"""
import copy
from collections import deque
from types import SimpleNamespace

import pytest

import server
from backend.runtime import latency
from test_latency_pipeline import SECRET, capture_and_enqueue, dispatch_one, make_env

# scenario -> (healthy recorder outcome, reason, broadcast statuses that must appear,
#              and that must not). Guards against comparing two identical no-ops.
SCENARIOS = {
    "normal": ("success", "none", {"preview_ready"}, {"draft_error", "draft_blocked", "dictation_busy"}),
    "streaming_text": ("success", "none", {"preview_ready"}, {"draft_error"}),
    "streaming_empty": ("success", "none", {"preview_ready", "transcribing"}, {"draft_error"}),
    "stream_raises": ("failed", "dispatch_error", set(), {"preview_ready", "transcribing"}),
    "stt_raises": ("failed", "stage_error", {"draft_error", "error"}, {"preview_ready"}),
    "cleanup_fails": ("failed", "stage_error", {"rewriting", "draft_error"}, {"preview_ready"}),
    "no_audio": ("incomplete", "no_audio", {"draft_blocked"}, {"preview_ready"}),
    "queue_full": ("incomplete", "queue_full", {"dictation_busy"}, {"transcribing", "preview_ready"}),
    "capture_raises": ("failed", "capture_error", set(), {"transcribing", "preview_ready"}),
}
VARIANTS = ["disabled", "every_method_raises", "lock_held_after_stop", "lock_held_throughout"]


class Stream:
    def __init__(self, clock, result):
        self.clock, self.result = clock, result

    def finalize(self):
        self.clock.advance(9)
        if self.result == "raise":
            raise RuntimeError(SECRET)
        ok, text = self.result
        return {"ok": ok, "text": text, "confidence": {}, "batches": 1}


def _plain(value, recording):
    return "<recording>" if value is recording else copy.deepcopy(value)


def _install_tracing(m, trace, recording):
    base_commit, base_publish = server.create_draft, server.broadcast_status_threadsafe
    base_save, base_ensure = server.recordings.save_recording, server.ensure_transcriber_initialized
    base_engine, original_process = server.get_selected_llm_engine, server.process_recording_result

    def create_draft(*args, **kwargs):
        seen = {k: v for k, v in vars(recording).items() if k != "_latency_context"}
        trace.append(("create_draft", [_plain(a, recording) for a in args],
                      {k: _plain(v, recording) for k, v in kwargs.items()}, seen))
        draft = dict(base_commit(*args, **kwargs))
        draft.update(id=sum(e[0] == "create_draft" for e in trace), raw_text=args[0], final_text=args[1],
                     status=kwargs.get("status", "pending"), error=kwargs.get("error", ""))
        return draft

    def publish(status, payload=None):
        trace.append(("broadcast", status, copy.deepcopy(payload)))
        return base_publish(status, payload)

    def save(rec, **kwargs):
        trace.append(("save_recording", _plain(rec, recording), copy.deepcopy(kwargs.get("metadata"))))
        return base_save(rec, **kwargs)

    def ensure(**kwargs):
        trace.append(("ensure_transcriber", dict(kwargs)))
        return base_ensure(**kwargs)

    def engine(*args, **kwargs):
        trace.append(("llm_engine",))
        return base_engine(*args, **kwargs)

    def process(rec, *args, **kwargs):
        # streamed_stt_ms is a real wall-clock measurement: record only that it exists.
        shown = {k: v for k, v in kwargs.items() if k != "streamed_stt_ms"}
        trace.append(("process_called", _plain(rec, recording), shown, kwargs.get("streamed_stt_ms") is None))
        try:
            result = original_process(rec, *args, **kwargs)
        except BaseException as exc:
            trace.append(("process_raised", type(exc).__name__, str(exc)))
            raise
        trace.append(("process_returned", copy.deepcopy(result)))
        return result

    m.setattr(server, "create_draft", create_draft)
    m.setattr(server, "broadcast_status_threadsafe", publish)
    m.setattr(server.recordings, "save_recording", save)
    m.setattr(server, "ensure_transcriber_initialized", ensure)
    m.setattr(server, "get_selected_llm_engine", engine)
    m.setattr(server, "process_recording_result", process)


def _apply_scenario(m, name, clock):
    session = None
    if name in {"streaming_text", "streaming_empty", "stream_raises"}:
        session = Stream(clock, {"streaming_text": (True, "stream text"), "streaming_empty": (True, ""),
                                 "stream_raises": "raise"}[name])
    if name == "stt_raises":
        def boom(**kwargs):
            raise RuntimeError(SECRET)
        m.setattr(server, "ensure_transcriber_initialized", boom)
    elif name == "cleanup_fails":
        def boom():
            raise RuntimeError(SECRET)
        m.setattr(server, "get_active_recording_config", lambda: {"llm_enabled": True})
        m.setattr(server, "get_selected_llm_engine", boom)
    elif name == "no_audio":
        m.setattr(server, "should_block_for_no_audio", lambda *_: (True, [SECRET]))
    elif name == "queue_full":
        m.setattr(server, "MAX_PENDING_RECORDINGS", 0)
    return session


def _apply_variant(m, variant, recorder):
    """Returns a release callable for variants that hold the collector lock."""
    if variant == "disabled":
        m.setattr(latency, "recorder", object())
    elif variant == "every_method_raises":
        def raiser(*args, **kwargs):
            raise RuntimeError("collector exploded")  # distinct from every scenario error
        public = [name for name, attr in vars(latency.LatencyRecorder).items()
                  if callable(attr) and not name.startswith("_")]
        assert {"begin", "start", "end", "skip", "configure", "committed", "finish",
                "reset", "snapshot"} <= set(public)
        for name in public + ["_now"]:
            m.setattr(latency.LatencyRecorder, name, raiser)
    elif variant == "lock_held_after_stop":
        original = server._enqueue_recording

        def contended_enqueue(rec, session=None):
            recorder._lock.acquire()  # a stalled thread owns the collector from here on
            return original(rec, session)
        m.setattr(server, "_enqueue_recording", contended_enqueue)
    elif variant == "lock_held_throughout":
        recorder._lock.acquire()
    return lambda: recorder._lock.locked() and recorder._lock.release()


def run_flow(monkeypatch, scenario, variant):
    with monkeypatch.context() as m:
        recorder, clock, coordinator = make_env(m)
        metrics = deque(maxlen=50)
        m.setattr(server, "pipeline_metrics", metrics)
        recording = SimpleNamespace(audio_data=[.1], stop_reason=SECRET, sample_rate=16000,
                                    duration_seconds=123456, path=SECRET)
        session = _apply_scenario(m, scenario, clock)
        trace = []
        _install_tracing(m, trace, recording)
        release = _apply_variant(m, variant, recorder) if variant else (lambda: None)
        try:
            try:
                capture_and_enqueue(m, clock, session, fail=scenario == "capture_raises", recording=recording)
            except Exception as exc:
                trace.append(("stop_raised", type(exc).__name__, str(exc)))
            dispatch_one(m)
        finally:
            release()
        outputs = {
            "trace": trace,
            "recording_fields": {k: v for k, v in vars(recording).items() if k != "_latency_context"},
            "gate_busy": coordinator.is_busy(),
            "processing_draft": server.is_processing_draft,
            "still_queued": server._pending_recordings.qsize(),
            "legacy_metrics": [(e["chars"], e["audio_seconds"]) for e in metrics],
        }
        return outputs, recorder


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_healthy_baseline_is_instrumented_and_exercises_the_scenario(monkeypatch, scenario):
    outputs, recorder = run_flow(monkeypatch, scenario, None)
    outcome, reason, present, absent = SCENARIOS[scenario]
    snap = recorder.snapshot()
    assert snap["n"] == 1 and snap["active"] == 0
    assert (snap["recent"][0]["outcome"], snap["recent"][0]["reason"]) == (outcome, reason)
    statuses = {e[1] for e in outputs["trace"] if e[0] == "broadcast"}
    assert present <= statuses and not (absent & statuses)
    assert not outputs["gate_busy"] and not outputs["processing_draft"]
    if scenario not in {"queue_full", "capture_raises", "stream_raises"}:
        assert any(e[0] == "create_draft" for e in outputs["trace"])
        assert any(e[:1] == ("process_returned",) and e[1] for e in outputs["trace"])


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_dictation_visible_outputs_are_identical_whatever_the_recorder_does(monkeypatch, scenario, variant):
    baseline, _ = run_flow(monkeypatch, scenario, None)
    observed, _ = run_flow(monkeypatch, scenario, variant)
    assert observed["trace"] == baseline["trace"]
    assert observed == baseline
