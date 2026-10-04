"""Bounded, process-local dictation timings. Never accepts business metadata.

Ticks stay private; exported durations are integer milliseconds. Spans diagnose
nested work, while the stop-to-commit endpoint is measured independently.
Production uses the fail-open helpers below; the recorder itself rejects schema
violations. A busy collector lock drops instrumentation rather than delaying work.
"""
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
import copy
import json
import math
import statistics
import threading
import time

STAGES = frozenset({"stop_to_finalize", "dispatch_wait", "stream_tail",
                    "pipeline_wait", "recovery_save", "stt_decode",
                    "post_process", "cleanup", "draft_commit", "preview_publish"})
STATUSES = frozenset({"completed", "failed", "cancelled", "skipped", "unavailable"})
OUTCOMES = frozenset({"success", "failed", "cancelled", "timeout", "incomplete"})
REASONS = frozenset({"none", "no_audio", "pipeline_busy", "queue_full",
                     "privacy_wipe", "cancel_requested", "stage_error",
                     "capture_error", "dispatch_error", "event_overflow",
                     "active_evicted", "deadline", "invalid_event", "collector_failure",
                     "missing_boundary"})
ENUMS = {
    "origin": frozenset({"interactive", "synthetic_benchmark"}),
    "mode": frozenset({"unknown", "dictation", "work", "gamer", "ideas", "messages", "hands_free"}),
    "engine": frozenset({"whisper", "unknown"}),
    "model": frozenset({"unknown", "tiny.en", "base.en", "small.en",
                        "medium.en", "large-v3", "distil-medium.en", "distil-large-v3"}),
    "device": frozenset({"unknown", "cpu", "cuda"}),
    "compute_type": frozenset({"unknown", "int8", "float16", "float32", "int8_float16"}),
    "temperature": frozenset({"cold", "warm", "unknown"}),
    "cleanup": frozenset({"unknown", "enabled", "skipped"}),
}
MAX_RECORDS, MAX_ACTIVE, MAX_EVENTS = 50, 16, 64
MAX_RECORD_BYTES, MAX_ACTIVE_BYTES, MAX_PAYLOAD_BYTES = 8192, 4096, 512 * 1024
DEADLINE_NS = 900 * 1_000_000_000
MAX_DURATION_MS = 24 * 60 * 60 * 1000


@dataclass(frozen=True, slots=True)
class Handle:
    generation: int
    sequence: int


@dataclass(slots=True)
class _Context:
    start: int
    boundary: bool
    metadata: dict
    last: int
    count: int = 0
    starts: dict = field(default_factory=dict)
    spans: dict = field(default_factory=dict)
    committed: int | None = None
    lost_event: bool = False


def _enum(value, allowed):
    if type(value) is not str or value not in allowed:
        raise ValueError("Unknown latency enum")


def _metadata(values):
    for key, value in values.items():
        if key == "streaming":
            if type(value) is not bool:
                raise ValueError("Latency streaming must be boolean")
        elif key in ENUMS:
            _enum(value, ENUMS[key])
        else:
            raise ValueError("Unknown latency field")


def _duration(start, end):
    if type(end) is not int or type(start) is not int or end < start:
        return None
    duration = (end - start) // 1_000_000
    return duration if duration <= MAX_DURATION_MS else None


class LatencyRecorder:
    def __init__(self, clock=time.perf_counter_ns):
        self._clock = clock
        self._lock = threading.Lock()
        self._generation = 1
        self._sequence = 0
        self._blocked = False
        self._active = {}
        self._records = deque(maxlen=MAX_RECORDS)

    def _now(self):
        now = self._clock()
        if type(now) is not int or not 0 <= now <= 2**63 - 1:
            raise ValueError("Invalid latency clock")
        return now

    def begin(self, *, boundary=True, stop_tick=None, **metadata):
        if type(boundary) is not bool:
            raise ValueError("Invalid latency boundary")
        _metadata(metadata)
        now = self._now()
        if stop_tick is not None and (type(stop_tick) is not int or not 0 <= stop_tick <= now):
            raise ValueError("Invalid stop origin clock")
        if not self._lock.acquire(blocking=False):
            return None
        try:
            if self._blocked:
                return None
            self._expire(now)
            if len(self._active) >= MAX_ACTIVE:
                oldest = next(iter(self._active))
                self._terminate(oldest, "incomplete", "active_evicted", now)
            self._sequence += 1
            handle = Handle(self._generation, self._sequence)
            defaults = {key: "unknown" for key in ENUMS}
            defaults.update(origin="interactive", streaming=False)
            defaults.update(metadata)
            ctx = _Context(now if stop_tick is None else stop_tick, boundary, defaults, now)
            if stop_tick is not None:
                ctx.starts["stop_to_finalize"] = stop_tick
                ctx.count = 1
            self._active[handle] = ctx
            return handle
        finally:
            self._lock.release()

    def _expire(self, now):
        for handle, ctx in list(self._active.items()):
            if now - ctx.start >= DEADLINE_NS:
                self._terminate(handle, "timeout", "deadline", now)

    def _event(self, handle, operation):
        now = self._now()
        if not self._lock.acquire(blocking=False):
            # A primitive dirty bit on an existing context is safe even if reset
            # removes that context concurrently; it cannot reinsert anything.
            if type(handle) is Handle:
                ctx = self._active.get(handle)
                if ctx is not None:
                    ctx.lost_event = True
            return False
        try:
            self._expire(now)
            if type(handle) is not Handle or handle not in self._active:
                return False
            ctx = self._active[handle]
            ctx.count += 1
            if ctx.count > MAX_EVENTS:
                self._terminate(handle, "incomplete", "event_overflow", now)
                return False
            if now < ctx.last:
                self._terminate(handle, "incomplete", "invalid_event", now)
                return False
            ctx.last = now
            return operation(ctx, now)
        finally:
            self._lock.release()

    def configure(self, handle, **metadata):
        _metadata(metadata)
        return self._event(handle, lambda ctx, now: ctx.metadata.update(metadata))

    def start(self, handle, stage):
        _enum(stage, STAGES)
        def op(ctx, now):
            if stage in ctx.starts or stage in ctx.spans:
                self._terminate(handle, "incomplete", "invalid_event", now)
                return False
            ctx.starts[stage] = now
            return True
        return self._event(handle, op)

    def end(self, handle, stage, status="completed"):
        _enum(stage, STAGES)
        _enum(status, STATUSES)
        def op(ctx, now):
            if stage not in ctx.starts or stage in ctx.spans:
                self._terminate(handle, "incomplete", "invalid_event", now)
                return False
            start = ctx.starts.pop(stage)
            duration = _duration(start, now) if status == "completed" else None
            ctx.spans[stage] = {"stage": stage, "status": status, "duration_ms": duration}
            return True
        return self._event(handle, op)

    def skip(self, handle, stage):
        _enum(stage, STAGES)
        def op(ctx, now):
            if stage in ctx.starts or stage in ctx.spans:
                self._terminate(handle, "incomplete", "invalid_event", now)
                return False
            ctx.spans[stage] = {"stage": stage, "status": "skipped", "duration_ms": None}
            return True
        return self._event(handle, op)

    def committed(self, handle):
        def op(ctx, now):
            if ctx.committed is not None:
                self._terminate(handle, "incomplete", "invalid_event", now)
                return False
            ctx.committed = now
            return True
        return self._event(handle, op)

    def finish(self, handle, outcome="success", reason="none"):
        _enum(outcome, OUTCOMES)
        _enum(reason, REASONS)
        return self._event(handle, lambda ctx, now: self._terminate(handle, outcome, reason, now))

    def _terminate(self, handle, outcome, reason, now):
        ctx = self._active.pop(handle)
        if outcome == "success" and ctx.lost_event:
            outcome, reason = "incomplete", "collector_failure"
        if outcome == "success" and (ctx.committed is None or not ctx.boundary):
            outcome, reason = "incomplete", "missing_boundary"
        spans = dict(ctx.spans)
        for stage in ctx.starts:
            status = "cancelled" if outcome == "cancelled" else "unavailable"
            spans[stage] = {"stage": stage, "status": status, "duration_ms": None}
        for stage in STAGES - spans.keys():
            spans[stage] = {"stage": stage, "status": "unavailable", "duration_ms": None}
        record = {"schema_version": 1, "sequence": handle.sequence,
                  "clock_generation": handle.generation, **ctx.metadata,
                  "spans": spans, "stop_to_draft_committed_ms":
                  _duration(ctx.start, ctx.committed) if outcome == "success" and ctx.boundary and ctx.committed is not None else None,
                  "cross_clock": "unavailable", "outcome": outcome, "reason": reason}
        # Finite vocabulary bounds this well below 8 KiB; enforce it at export.
        if len(json.dumps(record, separators=(",", ":")).encode()) > MAX_RECORD_BYTES:
            return False
        self._records.append(record)
        return True

    def is_active(self, handle):
        # Lock-free membership read: handles are immutable and never reused.
        return type(handle) is Handle and handle in self._active

    def reset(self, *, block_new=False):
        # Reset is a lifecycle barrier. It may wait for a tiny in-memory update,
        # never for business work; generation change invalidates all old handles.
        with self._lock:
            self._blocked = bool(block_new)
            self._generation += 1
            self._active.clear()
            self._records.clear()

    def snapshot(self):
        now = self._now()
        with self._lock:
            self._expire(now)
            records = list(self._records)
            active = len(self._active)
        # Completed records are immutable; copy and aggregate after unlocking.
        records = copy.deepcopy(records)
        def stats(values):
            values = sorted(values)
            return {"n": len(values), "p50_ms": statistics.median(values) if values else None,
                    "p95_ms": values[math.ceil(.95 * len(values)) - 1] if values else None,
                    "max_ms": values[-1] if values else None}
        successful = [r for r in records if r["outcome"] == "success"]
        spans = {stage: stats([r["spans"][stage]["duration_ms"] for r in successful
                              if stage in r["spans"] and r["spans"][stage]["duration_ms"] is not None])
                 for stage in sorted(STAGES)}
        result = {"schema_version": 1, "boundary": "stop_to_draft_committed",
                  "n": len(records), "active": active,
                  "counts": {outcome: sum(r["outcome"] == outcome for r in records) for outcome in sorted(OUTCOMES)},
                  "spans": spans, "stop_to_draft_committed": stats([r["stop_to_draft_committed_ms"] for r in successful
                                                                    if r["stop_to_draft_committed_ms"] is not None]),
                  "recent": records}
        if len(json.dumps(result, separators=(",", ":")).encode()) > MAX_PAYLOAD_BYTES:
            raise ValueError("Latency snapshot capacity exceeded")
        return result


recorder = LatencyRecorder()


def safe(handle, method, *args, **kwargs):
    """Best-effort instrumentation: never retain/log arbitrary failure text."""
    # Do not call arbitrary injected collectors. Supported test injection uses
    # an exact LatencyRecorder with a fake clock. This also bypasses instance
    # method overrides that could sleep in the production hot path.
    if type(recorder) is not LatencyRecorder:
        return None
    try:
        _enum(method, {"start", "end", "skip", "configure", "committed", "finish"})
        return getattr(LatencyRecorder, method)(recorder, handle, *args, **kwargs)
    except Exception:
        try:
            LatencyRecorder.finish(recorder, handle, "incomplete", "collector_failure")
        except Exception:
            pass
        return None


def begin(**metadata):
    if type(recorder) is not LatencyRecorder:
        return None
    try:
        return LatencyRecorder.begin(recorder, **metadata)
    except Exception:
        return None


def stop_request_tick():
    """Stamp request entry; admission may happen after the manager state lock."""
    if type(recorder) is not LatencyRecorder:
        return None
    try:
        return LatencyRecorder._now(recorder)
    except Exception:
        return None


def context(recording_result):
    try:
        handle = getattr(recording_result, "_latency_context", None)
        return handle if type(handle) is Handle else None
    except Exception:
        return None


def live_context(recording_result):
    """The attached stop-origin handle, only while it is still open.

    Direct callers (draft retry, recording re-transcription) carry no handle or
    a terminal one; they must record nothing rather than pollute the ring.
    """
    handle = context(recording_result)
    if handle is None or type(recorder) is not LatencyRecorder:
        return None
    try:
        return handle if LatencyRecorder.is_active(recorder, handle) else None
    except Exception:
        return None


def attach(recording_result, handle):
    try:
        setattr(recording_result, "_latency_context", handle)
    except Exception:
        safe(handle, "finish", "incomplete", "missing_boundary")


@contextmanager
def span(handle, stage):
    safe(handle, "start", stage)
    try:
        yield
    except InterruptedError:
        safe(handle, "end", stage, "cancelled")
        raise
    except Exception:
        safe(handle, "end", stage, "failed")
        raise
    else:
        safe(handle, "end", stage)


def reset(*, block_new=False):
    if type(recorder) is not LatencyRecorder:
        return
    try:
        LatencyRecorder.reset(recorder, block_new=block_new)
    except Exception:
        pass


def snapshot():
    try:
        if type(recorder) is not LatencyRecorder:
            raise ValueError("Unsupported collector")
        return LatencyRecorder.snapshot(recorder)
    except Exception:
        return {"schema_version": 1, "boundary": "stop_to_draft_committed", "unavailable": True}
