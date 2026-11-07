"""Fake-only paired collector overhead and Python allocation measurement.

Run from the worktree root: python -m tools.benchmark_latency_recorder
No server import, data-root access, models, microphone, disk writes or network.
"""
import argparse
import gc
import json
import statistics
import time
import tracemalloc
from types import SimpleNamespace

from backend.runtime import latency
from backend.runtime.dependencies import PipelineDependencies
from backend.services.dictation_pipeline import DictationPipeline, FunctionStage


class Jobs:
    def create(self, *args, **kwargs):
        return SimpleNamespace(id="fake-only")

    def is_cancel_requested(self, *args):
        return False

    def transition(self, *args):
        pass

    def complete(self, *args, **kwargs):
        pass


class Recovery:
    def save(self, *args, **kwargs):
        return None


def stage(name):
    def run(ctx, deps):
        with latency.span(ctx.latency_context, name):
            pass
        if name == "draft_commit":
            latency.safe(ctx.latency_context, "committed")
    return FunctionStage(name, run)


def measure(iterations, pipeline):
    started = time.perf_counter_ns()
    for _ in range(iterations):
        stop_tick = latency.stop_request_tick()
        handle = latency.begin(origin="synthetic_benchmark", stop_tick=stop_tick, boundary=stop_tick is not None)
        latency.safe(handle, "end", "stop_to_finalize")
        for name in ("dispatch_wait", "stream_tail", "pipeline_wait"):
            with latency.span(handle, name):
                pass
        latency.safe(handle, "configure", engine="whisper", model="base.en", device="cpu",
                     compute_type="int8", temperature="warm", cleanup="skipped")
        latency.safe(handle, "skip", "cleanup")
        pipeline.run(None, latency_context=handle)
        latency.safe(handle, "finish")
    return (time.perf_counter_ns() - started) / iterations / 1000


def memory():
    gc.collect()
    tracemalloc.start()
    baseline = tracemalloc.get_traced_memory()[0]
    r = latency.LatencyRecorder()
    for _ in range(latency.MAX_RECORDS):
        h = r.begin()
        for name in latency.STAGES:
            r.start(h, name)
            r.end(h, name)
        r.committed(h)
        r.finish(h)
    for _ in range(latency.MAX_ACTIVE):
        h = r.begin()
        for name in latency.STAGES:
            r.start(h, name)
            r.end(h, name)
    snapshot = r.snapshot()
    current, peak = tracemalloc.get_traced_memory()
    payload = len(json.dumps(snapshot, separators=(",", ":")).encode())
    tracemalloc.stop()
    return {"current_traced_allocated_bytes_including_snapshot": current - baseline,
            "peak_traced_allocated_bytes_including_snapshot": peak - baseline,
            "snapshot_payload_bytes": payload}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", type=int, default=21)
    parser.add_argument("--iterations", type=int, default=1000)
    args = parser.parse_args()
    if not 3 <= args.pairs <= 100 or not 100 <= args.iterations <= 100000:
        parser.error("Use 3..100 pairs and 100..100000 iterations")
    pipeline = DictationPipeline([stage(name) for name in
                                 ("stt_decode", "post_process", "draft_commit", "preview_publish")],
                                PipelineDependencies(job_manager=Jobs(), recovery_sink=Recovery()))
    on, off, deltas = [], [], []
    original = latency.recorder
    try:
        for pair in range(args.pairs + 3):  # three paired warmups excluded
            results = {}
            for enabled in ((True, False) if pair % 2 == 0 else (False, True)):
                latency.recorder = latency.LatencyRecorder() if enabled else None
                results[enabled] = measure(args.iterations, pipeline)
            if pair >= 3:
                on.append(results[True])
                off.append(results[False])
                deltas.append(results[True] - results[False])
    finally:
        latency.recorder = original
    report = {"boundary": "fake_pipeline_full_recorder_lifecycle",
              "pairs": args.pairs, "dictations_per_batch": args.iterations,
              "excluded_warmup_pairs": 3, "on_median_us": statistics.median(on),
              "off_median_us": statistics.median(off),
              "paired_overhead_median_us": statistics.median(deltas),
              "paired_overhead_min_us": min(deltas), "paired_overhead_max_us": max(deltas),
              **memory(), "real_pipeline_regression": "unavailable"}
    print(json.dumps(report, indent=2))
    if report["on_median_us"] > 1000 or report["peak_traced_allocated_bytes_including_snapshot"] > 2 * 1024 * 1024:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
