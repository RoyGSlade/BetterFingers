import json
import queue
from types import SimpleNamespace

import pytest

import server
from backend.input.hotkey_manager import HotkeyManager
from backend.runtime import latency
from backend.runtime.dictation_coordinator import DictationCoordinator
from backend.services.dictation_pipeline import DictationPipeline, FunctionStage
from test_dictation_pipeline import FakeJobManager, FakeRecoverySink, make_deps
from test_latency_recorder import Clock

SECRET = "SECRET_transcript_path_token_clipboard_profile_draft_contact_id"


@pytest.fixture
def env(monkeypatch):
    return make_env(monkeypatch)


def make_env(monkeypatch):
    clock = Clock()
    recorder = latency.LatencyRecorder(clock)
    monkeypatch.setattr(latency, "recorder", recorder)
    coordinator = DictationCoordinator()
    monkeypatch.setattr(server, "dictation_coordinator", coordinator)
    monkeypatch.setattr(server, "cancellation_event", coordinator.cancellation_event)
    monkeypatch.setattr(server, "get_active_recording_config", lambda: {"llm_enabled": False})
    monkeypatch.setattr(server, "resolve_dictation_preset", lambda _: SECRET)
    monkeypatch.setattr(server, "get_recording_metadata", lambda _: {"secret": SECRET})
    monkeypatch.setattr(server.dictionary, "get_terms", lambda: [])
    monkeypatch.setattr(server.dictionary, "hotwords_string", lambda _: SECRET)
    monkeypatch.setattr(server, "should_block_for_no_audio", lambda *_: (False, []))
    monkeypatch.setattr(server, "_ensure_recording_dispatcher", lambda: None)
    monkeypatch.setattr(server, "_pending_recordings", queue.Queue())
    monkeypatch.setattr(server, "_pending_drop_generation", 0)
    server.privacy_wipe_in_progress.clear()

    class Decoder:
        model_size = SECRET  # reject paths/adversarial unknown model IDs
        active_device = "cpu"
        active_compute_type = "int8"
        model = object()

        def transcribe(self, audio):
            # Inference is lazy: the call site timer must include consumption.
            def lazy():
                for _ in range(4):
                    clock.advance(3)
                    yield SECRET
            return " ".join(lazy())

    monkeypatch.setattr(server, "ensure_transcriber_initialized", lambda **_: Decoder())
    monkeypatch.setattr(server.recordings, "save_recording", lambda *args, **kwargs: clock.advance(3))
    def commit(*args, **kwargs):
        clock.advance(4)
        return {"id": SECRET, "raw_text": SECRET, "final_text": SECRET,
                "token_count": 123456, "token_limit": 2000, "long_text": False,
                "confidence": {}, "auto_send_ok": False, "force_review": False,
                "force_review_reason": "", "error": SECRET, "gate_reasons": []}
    monkeypatch.setattr(server, "create_draft", commit)
    def publish(status, payload=None):
        if status in {"preview_ready", "draft_blocked", "scratch_last"}:
            clock.advance(17)
    monkeypatch.setattr(server, "broadcast_status_threadsafe", publish)
    return recorder, clock, coordinator


class EndLoop(BaseException):
    pass


def dispatch_one(monkeypatch):
    pending = server._pending_recordings
    original_get = pending.get
    def get():
        try:
            return original_get(block=False)
        except queue.Empty:
            raise EndLoop()
    monkeypatch.setattr(pending, "get", get)
    with pytest.raises(EndLoop):
        server._recording_dispatcher_loop()


def capture_and_enqueue(monkeypatch, clock, session=None, fail=False, recording=None):
    if recording is None:
        recording = SimpleNamespace(audio_data=[.1], stop_reason=SECRET,
                                    sample_rate=16000, duration_seconds=123456, path=SECRET)
    class Capture:
        def stop_recording(self, **kwargs):
            clock.advance(8)
            if fail:
                raise RuntimeError(SECRET)
            return recording
    monkeypatch.setattr("backend.input.hotkey_manager.load_profile", lambda _: {})
    manager = HotkeyManager(Capture(), lambda rec: server._enqueue_recording(rec, session), lambda: None)
    manager.is_recording = True
    manager.recording_start_time = 0
    manager.request_stop()
    return recording


def test_capture_queue_lazy_decode_commit_publish_and_privacy(env, monkeypatch):
    monkeypatch.setenv("BETTERFINGERS_LOG_RAW_TEXT", "1")
    r, clock, coord = env
    original = coord.begin
    def admission(**kwargs):
        clock.advance(6)
        return original(**kwargs)
    monkeypatch.setattr(coord, "begin", admission)
    capture_and_enqueue(monkeypatch, clock)
    clock.advance(5)
    dispatch_one(monkeypatch)
    snap = server.get_pipeline_metrics_summary()["latency"]
    record = snap["recent"][0]
    assert record["outcome"] == "success"
    for stage, ms in {"stop_to_finalize": 8, "dispatch_wait": 5, "pipeline_wait": 6,
                      "recovery_save": 3, "stt_decode": 12, "draft_commit": 4,
                      "preview_publish": 17}.items():
        assert record["spans"][stage]["duration_ms"] == ms
    assert record["stop_to_draft_committed_ms"] == 38
    assert record["spans"]["cleanup"]["status"] == "skipped"
    assert record["model"] == "unknown" and record["device"] == "cpu"
    assert SECRET not in json.dumps(snap)
    for field in ("audio_seconds", "chars", "token_count", "duration_seconds", "timestamp"):
        assert field not in json.dumps(snap)


@pytest.mark.parametrize("ok,text", [(True, "stream text"), (True, ""), (False, "")])
def test_stream_tail_success_empty_and_failed_fallback(env, monkeypatch, ok, text):
    r, clock, _ = env
    class Stream:
        def finalize(self):
            clock.advance(9)
            return {"ok": ok, "text": text, "confidence": {}, "batches": 1}
    capture_and_enqueue(monkeypatch, clock, Stream())
    dispatch_one(monkeypatch)
    record = r.snapshot()["recent"][0]
    tail = record["spans"]["stream_tail"]
    assert record["outcome"] == "success"
    assert tail["status"] == ("completed" if ok else "failed")
    assert tail["duration_ms"] == (9 if ok else None)
    assert record["spans"]["stt_decode"]["status"] == ("skipped" if text else "completed")


def test_stream_exception_is_terminal_and_not_success(env, monkeypatch):
    r, clock, _ = env
    class Stream:
        def finalize(self):
            raise RuntimeError(SECRET)
    capture_and_enqueue(monkeypatch, clock, Stream())
    dispatch_one(monkeypatch)
    record = r.snapshot()["recent"][0]
    assert record["reason"] == "dispatch_error"
    assert record["spans"]["stream_tail"]["status"] == "failed"
    assert record["stop_to_draft_committed_ms"] is None
    assert SECRET not in json.dumps(r.snapshot())


def test_capture_exception_is_terminal(env, monkeypatch):
    r, clock, _ = env
    with pytest.raises(RuntimeError):
        capture_and_enqueue(monkeypatch, clock, fail=True)
    record = r.snapshot()["recent"][0]
    assert record["reason"] == "capture_error"
    assert record["spans"]["stop_to_finalize"]["duration_ms"] is None


def test_queue_overflow_and_privacy_drop_do_not_resurrect(env, monkeypatch):
    r, clock, _ = env
    monkeypatch.setattr(server, "MAX_PENDING_RECORDINGS", 0)
    capture_and_enqueue(monkeypatch, clock)
    assert r.snapshot()["recent"][0]["reason"] == "queue_full"
    monkeypatch.setattr(server, "MAX_PENDING_RECORDINGS", 10)
    rec = capture_and_enqueue(monkeypatch, clock)
    old = latency.context(rec)
    assert server._drop_pending_recordings() == 1
    assert not r.committed(old) and not r.finish(old)
    assert r.snapshot()["n"] == 0 and r.snapshot()["active"] == 0


def test_no_audio_is_terminal_and_excluded_from_speed_quantiles(env, monkeypatch):
    r, clock, _ = env
    monkeypatch.setattr(server, "should_block_for_no_audio", lambda *_: (True, [SECRET]))
    capture_and_enqueue(monkeypatch, clock)
    dispatch_one(monkeypatch)
    snap = r.snapshot()
    assert snap["recent"][0]["reason"] == "no_audio"
    assert snap["recent"][0]["stop_to_draft_committed_ms"] is None
    assert snap["stop_to_draft_committed"]["n"] == 0


@pytest.mark.parametrize("stage", ["stt_decode", "post_process", "cleanup", "draft_commit", "preview_publish"])
@pytest.mark.parametrize("cancel", [False, True])
def test_errors_and_cancellation_during_stages_are_terminal(env, monkeypatch, stage, cancel):
    r, clock, _ = env
    def fail(*args, **kwargs):
        raise InterruptedError(SECRET) if cancel else RuntimeError(SECRET)
    if stage == "stt_decode":
        monkeypatch.setattr(server, "ensure_transcriber_initialized", fail)
    elif stage == "post_process":
        monkeypatch.setattr(server, "get_active_recording_config", fail)
    elif stage == "cleanup":
        monkeypatch.setattr(server, "get_active_recording_config", lambda: {"llm_enabled": True})
        monkeypatch.setattr(server, "get_selected_llm_engine", fail)
    elif stage == "draft_commit":
        original = server.create_draft
        def fail_ready(*args, **kwargs):
            if kwargs.get("status") != "error":
                fail()
            return original(*args, **kwargs)
        monkeypatch.setattr(server, "create_draft", fail_ready)
    else:
        original = server.broadcast_status_threadsafe
        def fail_preview(status, payload=None):
            if status == "preview_ready":
                fail()
            return original(status, payload)
        monkeypatch.setattr(server, "broadcast_status_threadsafe", fail_preview)
    capture_and_enqueue(monkeypatch, clock)
    dispatch_one(monkeypatch)
    snap = r.snapshot()
    assert snap["n"] == 1
    assert snap["recent"][0]["outcome"] == ("cancelled" if cancel else "failed")
    assert snap["recent"][0]["spans"][stage]["duration_ms"] is None
    assert SECRET not in json.dumps(snap)


@pytest.mark.parametrize("cancel_before", range(4))
def test_generic_pipeline_cancellation_before_every_stage(env, cancel_before):
    r, clock, _ = env
    job_manager = FakeJobManager()
    h = r.begin()
    def run(ctx, deps):
        assert ctx.latency_context is h
        ctx.extra["visits"] = ctx.extra.get("visits", 0) + 1
        if ctx.extra["visits"] == cancel_before:
            job_manager.request_cancel()
    if cancel_before == 0:
        job_manager.request_cancel()
    stages = [FunctionStage(str(i), run) for i in range(4)]
    outcome = DictationPipeline(stages, make_deps(job_manager, FakeRecoverySink())).run(SECRET, latency_context=h)
    assert outcome.cancelled
    assert r.snapshot()["n"] == 1
    assert r.snapshot()["recent"][0]["outcome"] == "cancelled"


def test_handled_recovery_failure_is_visible_and_dictation_continues(env, monkeypatch):
    r, clock, _ = env
    monkeypatch.setattr(server.recordings, "save_recording", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(SECRET)))
    capture_and_enqueue(monkeypatch, clock)
    dispatch_one(monkeypatch)
    record = r.snapshot()["recent"][0]
    assert record["outcome"] == "success"
    assert record["spans"]["recovery_save"]["status"] == "failed"


def test_collector_failure_never_breaks_pipeline(env, monkeypatch):
    r, clock, _ = env
    capture_and_enqueue(monkeypatch, clock)
    monkeypatch.setattr(latency.LatencyRecorder, "configure", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(SECRET)))
    dispatch_one(monkeypatch)
    assert r.snapshot()["n"] == 1
    assert r.snapshot()["recent"][0]["reason"] == "collector_failure"
    assert not server.dictation_coordinator.is_busy()


def test_direct_invocation_without_stop_origin_records_nothing(env):
    r, clock, _ = env
    recording = SimpleNamespace(audio_data=[.1])
    assert server.process_recording_result(recording) is not None  # dictation still ran
    assert latency.context(recording) is None  # and no context was attached
    snap = r.snapshot()
    assert snap["n"] == 0 and snap["active"] == 0


def test_attached_terminal_handle_is_ignored(env):
    r, clock, _ = env
    handle = r.begin()
    r.committed(handle)
    r.finish(handle)
    recording = SimpleNamespace(audio_data=[.1])
    latency.attach(recording, handle)
    before = r.snapshot()
    assert before["n"] == 1
    assert server.process_recording_result(recording) is not None
    assert r.snapshot() == before


def test_retry_and_retranscribe_routes_leave_the_ring_unchanged(env, monkeypatch):
    import numpy as np
    from fastapi.testclient import TestClient
    r, clock, _ = env
    recording = SimpleNamespace(audio_data=[.1], stop_reason="manual", sample_rate=16000, duration_seconds=1)
    capture_and_enqueue(monkeypatch, clock, recording=recording)
    dispatch_one(monkeypatch)
    assert type(latency.context(recording)) is latency.Handle  # terminal handle stays attached
    before = r.snapshot()
    assert before["n"] == 1 and before["recent"][0]["outcome"] == "success"
    monkeypatch.setitem(server.draft_recordings, 4242, recording)
    monkeypatch.setattr(server.recordings, "is_valid_rec_id", lambda _: True)
    monkeypatch.setattr(server.recordings, "load_recording_audio",
                        lambda _: (np.ones(160, dtype=np.float32), 16000))
    client = TestClient(server.app)
    assert client.post("/drafts/4242/retry").status_code == 200
    assert client.post("/recordings/rec_1/retranscribe").status_code == 200
    assert r.snapshot() == before


def drop_first_finish(monkeypatch):
    """The first finish loses the collector lock, exactly like production contention."""
    original = latency.LatencyRecorder.finish
    seen = []

    def finish(self, handle, outcome="success", reason="none"):
        seen.append((outcome, reason))
        if len(seen) == 1:
            with self._lock:
                return original(self, handle, outcome, reason)
        return original(self, handle, outcome, reason)
    monkeypatch.setattr(latency.LatencyRecorder, "finish", finish)
    return seen


def test_dropped_success_finish_is_not_relabelled_as_stage_error(env, monkeypatch):
    r, clock, _ = env
    seen = drop_first_finish(monkeypatch)
    capture_and_enqueue(monkeypatch, clock)
    dispatch_one(monkeypatch)
    assert seen[0] == ("success", "none") and seen[-1] == ("incomplete", "collector_failure")
    record = r.snapshot()["recent"][0]
    assert (record["outcome"], record["reason"]) == ("incomplete", "collector_failure")
    assert record["stop_to_draft_committed_ms"] is None
    assert not server.dictation_coordinator.is_busy()


def test_dropped_cancel_finish_is_not_relabelled_as_stage_error(env, monkeypatch):
    r, clock, _ = env
    def cancel(*args, **kwargs):
        raise InterruptedError(SECRET)
    monkeypatch.setattr(server, "get_active_recording_config", cancel)
    seen = drop_first_finish(monkeypatch)
    capture_and_enqueue(monkeypatch, clock)
    dispatch_one(monkeypatch)
    assert seen[0] == ("cancelled", "cancel_requested")
    record = r.snapshot()["recent"][0]
    assert (record["outcome"], record["reason"]) == ("incomplete", "collector_failure")


def test_pipeline_that_never_returns_is_still_a_stage_error(env, monkeypatch):
    r, clock, _ = env
    def explode(self, *args, **kwargs):
        raise RuntimeError(SECRET)
    monkeypatch.setattr(server.DictationPipeline, "run", explode)
    capture_and_enqueue(monkeypatch, clock)
    dispatch_one(monkeypatch)
    record = r.snapshot()["recent"][0]
    assert (record["outcome"], record["reason"]) == ("failed", "stage_error")
    assert not server.dictation_coordinator.is_busy()


def test_stt_decode_excludes_speech_signal_math(env, monkeypatch):
    r, clock, _ = env
    from backend.domain.contracts import TranscriptionResult
    structured = TranscriptionResult(text="text", segments=[], confidence=None, audio_duration_s=1.0)

    class Decoder:
        model_size, active_device, active_compute_type, model = "base.en", "cpu", "int8", object()

        def transcribe_with_structured(self, audio, hotwords=None):
            clock.advance(5)
            return "text", {}, structured

    real_signals = server.compute_speech_signals

    def signals(*args, **kwargs):
        clock.advance(40)  # would inflate stt_decode if it stayed inside the span
        return real_signals(*args, **kwargs)
    monkeypatch.setattr(server, "ensure_transcriber_initialized", lambda **_: Decoder())
    monkeypatch.setattr(server, "compute_speech_signals", signals)
    monkeypatch.setattr(server, "rms_windows", lambda *a, **k: [])
    capture_and_enqueue(monkeypatch, clock)
    dispatch_one(monkeypatch)
    record = r.snapshot()["recent"][0]
    assert record["outcome"] == "success"
    assert record["spans"]["stt_decode"]["duration_ms"] == 5
    assert record["model"] == "base.en"


def test_mode_defaults_to_unknown_until_a_mode_is_wired(env, monkeypatch):
    r, clock, _ = env
    capture_and_enqueue(monkeypatch, clock)
    dispatch_one(monkeypatch)
    assert r.snapshot()["recent"][0]["mode"] == "unknown"


def test_end_to_end_stats_ignore_missing_durations():
    r = latency.LatencyRecorder(lambda: 1)
    handle = r.begin()
    r.committed(handle)
    r.finish(handle)
    r._records[0]["stop_to_draft_committed_ms"] = None  # an unmeasurable success must not poison stats
    assert r.snapshot()["stop_to_draft_committed"] == {"n": 0, "p50_ms": None, "p95_ms": None, "max_ms": None}


def test_slow_external_collector_is_disabled_while_pipeline_completes(env, monkeypatch):
    import time
    r, clock, _ = env
    class SlowCollector:
        def begin(self, **kwargs):
            time.sleep(1)
            raise AssertionError("Unsupported collector must never execute")
    monkeypatch.setattr(latency, "recorder", SlowCollector())
    capture_and_enqueue(monkeypatch, clock)
    dispatch_one(monkeypatch)
    assert not server.dictation_coordinator.is_busy()
    assert latency.snapshot()["unavailable"]


def test_capture_stop_includes_state_lock_wait_and_ignores_noop(env, monkeypatch):
    r, clock, _ = env
    monkeypatch.setattr("backend.input.hotkey_manager.load_profile", lambda _: {})
    class Capture:
        def stop_recording(self, **kwargs):
            clock.advance(8)
            return SimpleNamespace(audio_data=[.1])
    class DelayedLock:
        def __enter__(self):
            clock.advance(11)
        def __exit__(self, *args):
            pass
    manager = HotkeyManager(Capture(), lambda rec: server._enqueue_recording(rec), lambda: None)
    manager.state_lock = DelayedLock()
    manager.is_recording = True
    manager.recording_start_time = 0
    manager.request_stop()
    manager.request_stop()  # no-op: must not create/evict a latency sample
    dispatch_one(monkeypatch)
    snap = r.snapshot()
    assert snap["n"] == 1
    assert snap["recent"][0]["spans"]["stop_to_finalize"]["duration_ms"] == 19
