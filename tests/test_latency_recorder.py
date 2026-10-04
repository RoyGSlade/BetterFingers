"""No models, microphone, persistent data or content in exported timings."""
import json
import threading
import time
from dataclasses import asdict

import pytest

from backend.runtime import latency


class Clock:
    def __init__(self):
        self.now = 1_000_000_000

    def __call__(self):
        return self.now

    def advance(self, ms):
        self.now += ms * 1_000_000


@pytest.fixture
def collector(monkeypatch):
    clock = Clock()
    recorder = latency.LatencyRecorder(clock)
    monkeypatch.setattr(latency, "recorder", recorder)
    return recorder, clock


def completed(recorder, clock, ms=10):
    handle = recorder.begin()
    clock.advance(ms)
    recorder.committed(handle)
    recorder.finish(handle)
    return handle


def test_exact_endpoint_nested_spans_and_publish_excluded(collector):
    r, clock = collector
    handle = r.begin()
    r.start(handle, "post_process")
    clock.advance(2)
    r.start(handle, "draft_commit")
    clock.advance(5)
    r.end(handle, "draft_commit")
    r.committed(handle)
    clock.advance(3)
    r.end(handle, "post_process")
    r.start(handle, "preview_publish")
    clock.advance(20)
    r.end(handle, "preview_publish")
    r.skip(handle, "cleanup")
    r.finish(handle)
    record = r.snapshot()["recent"][0]
    assert record["stop_to_draft_committed_ms"] == 7
    assert record["spans"]["post_process"]["duration_ms"] == 10
    assert record["spans"]["draft_commit"]["duration_ms"] == 5
    assert record["spans"]["preview_publish"]["duration_ms"] == 20
    assert record["spans"]["cleanup"] == {"stage": "cleanup", "status": "skipped", "duration_ms": None}
    assert "start" not in record and "committed" not in record


def test_real_zero_is_distinct_from_skipped_and_failure(collector):
    r, clock = collector
    h = r.begin()
    r.start(h, "stt_decode")
    r.end(h, "stt_decode")
    r.start(h, "draft_commit")
    r.end(h, "draft_commit", "failed")
    r.skip(h, "cleanup")
    r.finish(h, "failed", "stage_error")
    record = r.snapshot()["recent"][0]
    assert record["spans"]["stt_decode"]["duration_ms"] == 0
    assert record["spans"]["draft_commit"]["duration_ms"] is None
    assert record["spans"]["cleanup"]["duration_ms"] is None
    assert record["stop_to_draft_committed_ms"] is None


@pytest.mark.parametrize("event", [
    lambda r, h: r.end(h, "stt_decode"),
    lambda r, h: (r.start(h, "stt_decode"), r.start(h, "stt_decode")),
    lambda r, h: (r.skip(h, "cleanup"), r.skip(h, "cleanup")),
    lambda r, h: (r.committed(h), r.committed(h)),
])
def test_invalid_or_duplicate_event_terminates_once(collector, event):
    r, clock = collector
    h = r.begin()
    event(r, h)
    assert not r.finish(h)
    assert not r.start(h, "draft_commit")
    snap = r.snapshot()
    assert snap["n"] == 1
    assert snap["recent"][0]["reason"] == "invalid_event"


def test_clock_discontinuity_is_incomplete_not_negative(collector):
    r, clock = collector
    h = r.begin()
    r.start(h, "stt_decode")
    clock.advance(-1)
    r.end(h, "stt_decode")
    assert r.snapshot()["recent"][0]["reason"] == "invalid_event"


@pytest.mark.parametrize("call", [
    lambda r, h: r.begin(transcript="CANARY"),
    lambda r, h: r.configure(h, path="CANARY"),
    lambda r, h: r.configure(h, model="C:/CANARY"),
    lambda r, h: r.configure(h, streaming="CANARY"),
    lambda r, h: r.start(h, "CANARY"),
    lambda r, h: r.end(h, "stt_decode", "CANARY"),
    lambda r, h: r.finish(h, "success", "CANARY"),
    lambda r, h: r.finish(h, "CANARY"),
])
def test_schema_rejects_unknown_fields_and_enums(collector, call):
    r, clock = collector
    h = r.begin()
    with pytest.raises(ValueError):
        call(r, h)
    r.finish(h, "failed", "stage_error")
    assert "CANARY" not in json.dumps(r.snapshot())


def test_pools_event_cap_expiry_and_payload_caps(collector):
    r, clock = collector
    handles = [r.begin() for _ in range(17)]
    assert len(r._active) == latency.MAX_ACTIVE
    assert r.snapshot()["recent"][0]["reason"] == "active_evicted"
    assert not r.finish(handles[0])
    h = handles[-1]
    for _ in range(latency.MAX_EVENTS + 1):
        r.configure(h, cleanup="unknown")
    assert r.snapshot()["recent"][-1]["reason"] == "event_overflow"
    clock.advance(latency.DEADLINE_NS // 1_000_000)
    assert r.snapshot()["active"] == 0
    assert r.snapshot()["counts"]["timeout"] == 15
    for _ in range(100):
        completed(r, clock)
    for _ in range(16):
        h = r.begin()
        for stage in latency.STAGES:
            r.start(h, stage)
            r.end(h, stage)
    snap = r.snapshot()
    assert snap["n"] == 50 and snap["active"] == 16
    assert all(len(json.dumps(record).encode()) <= latency.MAX_RECORD_BYTES for record in snap["recent"])
    assert all(len(json.dumps(asdict(ctx)).encode()) <= latency.MAX_ACTIVE_BYTES for ctx in r._active.values())
    assert len(json.dumps(snap).encode()) + sum(len(json.dumps(asdict(ctx)).encode()) for ctx in r._active.values()) < latency.MAX_PAYLOAD_BYTES


def test_reset_shutdown_barrier_and_late_events(collector):
    r, clock = collector
    old = completed(r, clock)
    active = r.begin()
    r.reset(block_new=True)
    assert r.begin() is None
    assert not r.finish(active)
    assert not r.committed(old)
    assert r.snapshot()["n"] == 0 and r.snapshot()["active"] == 0
    r.reset()
    fresh = completed(r, clock)
    assert fresh.generation != active.generation
    assert r.snapshot()["n"] == 1


def test_nearest_rank_p95_failure_counts_and_snapshot_copy(collector):
    r, clock = collector
    for ms in range(1, 21):
        completed(r, clock, ms)
    for outcome in ("failed", "cancelled", "timeout", "incomplete"):
        h = r.begin()
        r.finish(h, outcome, "stage_error")
    snap = r.snapshot()
    assert snap["n"] == 24
    assert snap["counts"] == {"success": 20, "failed": 1, "cancelled": 1, "timeout": 1, "incomplete": 1}
    assert snap["stop_to_draft_committed"] == {"n": 20, "p50_ms": 10.5, "p95_ms": 19, "max_ms": 20}
    snap["recent"][0]["model"] = "CANARY"
    assert "CANARY" not in json.dumps(r.snapshot())


def test_busy_collector_drops_events_without_waiting(collector):
    r, clock = collector
    h = r.begin()
    with r._lock:
        started = time.perf_counter()
        assert latency.begin() is None
        assert latency.safe(h, "start", "stt_decode") is False
        assert time.perf_counter() - started < .02
    # A missed event yields an incomplete sample, never fabricated speed.
    latency.safe(h, "end", "stt_decode")
    assert r.snapshot()["recent"][0]["outcome"] == "incomplete"


def test_unsupported_slow_collector_is_never_called(collector, monkeypatch):
    class SlowCollector:
        def begin(self, **kwargs):
            time.sleep(1)
            raise AssertionError("must not invoke arbitrary injected collector")

        start = begin

    monkeypatch.setattr(latency, "recorder", SlowCollector())
    started = time.perf_counter()
    assert latency.begin() is None
    assert latency.safe(None, "start", "stt_decode") is None
    assert time.perf_counter() - started < .02


def test_failing_clock_is_fail_open(collector):
    r, clock = collector
    h = r.begin()
    r._clock = lambda: (_ for _ in ()).throw(RuntimeError("SECRET_EXCEPTION"))
    assert latency.safe(h, "start", "stt_decode") is None
    assert latency.begin() is None
    assert "SECRET_EXCEPTION" not in json.dumps(latency.snapshot())


def test_concurrent_snapshot_reset_and_append_are_bounded(collector):
    r, clock = collector
    errors = []
    def writer():
        try:
            for _ in range(300):
                h = r.begin()
                r.committed(h)
                r.finish(h)
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=writer)
    thread.start()
    for _ in range(50):
        snap = r.snapshot()
        assert snap["n"] <= 50 and snap["active"] <= 16
        r.reset()
    thread.join()
    assert errors == []


def test_collector_performs_no_disk_or_network_io(collector, monkeypatch):
    import socket
    r, clock = collector
    def forbidden(*args, **kwargs):
        raise AssertionError("Collector must remain ephemeral")
    with monkeypatch.context() as patch:
        patch.setattr("builtins.open", forbidden)
        patch.setattr(socket, "socket", forbidden)
        completed(r, clock)
        assert r.snapshot()["n"] == 1
        r.reset()


def test_lost_event_cannot_be_reported_as_success(collector):
    r, clock = collector
    h = r.begin()
    with r._lock:
        latency.safe(h, "skip", "cleanup")
    r.committed(h)
    r.finish(h)
    assert r.snapshot()["recent"][0]["reason"] == "collector_failure"


def test_facade_rejects_internal_method_names(collector):
    r, clock = collector
    h = r.begin()
    latency.safe(h, "_terminate", "CANARY", "CANARY", clock())
    snap = r.snapshot()
    assert snap["recent"][0]["reason"] == "collector_failure"
    assert "CANARY" not in json.dumps(snap)
