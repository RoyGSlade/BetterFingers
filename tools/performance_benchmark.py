import argparse
import json
import os
import subprocess
import time

import numpy as np

from llm_engine import get_engine
from transcriber import Transcriber
from tts_engine import ReviewTTSEngine


def _token_count(text):
    return len(str(text or "").split())


def _safe_nvidia_smi():
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return []
        rows = []
        for raw_line in str(result.stdout or "").splitlines():
            parts = [p.strip() for p in raw_line.split(",")]
            if len(parts) != 3:
                continue
            rows.append(
                {
                    "gpu": parts[0],
                    "memory_total_mb": int(parts[1]),
                    "memory_used_mb": int(parts[2]),
                }
            )
        return rows
    except Exception:
        return []


def benchmark_llm(sample_text, token_limit):
    start = time.perf_counter()
    try:
        engine = get_engine()
        out = engine.process_fast_lane(
            sample_text,
            preset_name="True Janitor",
            true_gen=False,
            max_output_tokens=token_limit,
        )
        elapsed = time.perf_counter() - start
        output_tokens = _token_count(out)
        return {
            "ok": True,
            "elapsed_sec": elapsed,
            "output_tokens": output_tokens,
            "tokens_per_sec": (output_tokens / elapsed) if elapsed > 0 else 0.0,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "elapsed_sec": time.perf_counter() - start}


def benchmark_stt(sample_seconds=3):
    audio = np.zeros(int(16000 * sample_seconds), dtype=np.float32)
    transcriber = None
    start = time.perf_counter()
    try:
        transcriber = Transcriber(profile_name="Default", preload=False)
        text = transcriber.transcribe(audio)
        elapsed = time.perf_counter() - start
        return {"ok": True, "elapsed_sec": elapsed, "output_tokens": _token_count(text)}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "elapsed_sec": time.perf_counter() - start}
    finally:
        if transcriber is not None:
            try:
                transcriber.unload()
            except Exception:
                pass


def benchmark_tts():
    engine = ReviewTTSEngine()
    start = time.perf_counter()
    try:
        status = engine.ensure_loaded(voice_hint="english")
        if not status.get("ok", False):
            return {"ok": False, "error": status.get("message", "TTS unavailable"), "elapsed_sec": time.perf_counter() - start}
        result = engine.speak("Benchmark speech playback sample.", speed=1.2, voice_hint="english")
        elapsed = time.perf_counter() - start
        return {
            "ok": bool(result.get("ok", False)),
            "elapsed_sec": elapsed,
            "backend": result.get("backend", "unknown"),
            "fallback": bool(result.get("fallback", False)),
            "message": result.get("message", ""),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "elapsed_sec": time.perf_counter() - start}
    finally:
        try:
            engine.shutdown()
        except Exception:
            pass


def summarize_hardware_tier(results):
    llm = results.get("llm", {})
    llm_tps = float(llm.get("tokens_per_sec", 0.0) or 0.0)
    if llm_tps >= 35.0:
        return "high-performance"
    if llm_tps >= 12.0:
        return "recommended"
    return "minimum"


def write_markdown(path, results):
    lines = []
    lines.append("# BetterFingers Performance Benchmark")
    lines.append("")
    lines.append(f"- Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- Recommended hardware tier: **{results.get('recommended_tier', 'minimum')}**")
    lines.append("")
    for key in ("llm", "stt", "tts"):
        row = results.get(key, {})
        lines.append(f"## {key.upper()}")
        if row.get("ok", False):
            for field, value in row.items():
                lines.append(f"- {field}: {value}")
        else:
            lines.append(f"- error: {row.get('error', 'unknown')}")
        lines.append("")
    gpus = results.get("gpus", [])
    lines.append("## GPU Snapshot")
    if gpus:
        for gpu in gpus:
            lines.append(
                f"- {gpu.get('gpu')}: {gpu.get('memory_used_mb')} MB / {gpu.get('memory_total_mb')} MB"
            )
    else:
        lines.append("- nvidia-smi unavailable or no NVIDIA GPU detected.")
    lines.append("")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description="Run BetterFingers performance benchmarks.")
    parser.add_argument("--token-limit", type=int, default=1100)
    parser.add_argument("--out-dir", type=str, default="artifacts")
    args = parser.parse_args()

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    sample_text = (
        "Rotate back post and hold second man. Push after possession is secured and avoid over-committing."
    )
    results = {
        "llm": benchmark_llm(sample_text=sample_text, token_limit=max(900, min(1200, int(args.token_limit)))),
        "stt": benchmark_stt(sample_seconds=3),
        "tts": benchmark_tts(),
        "gpus": _safe_nvidia_smi(),
    }
    results["recommended_tier"] = summarize_hardware_tier(results)

    json_path = os.path.join(out_dir, "performance_benchmark.json")
    md_path = os.path.join(out_dir, "performance_benchmark.md")

    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)
    write_markdown(md_path, results)

    print(f"Wrote benchmark JSON: {json_path}")
    print(f"Wrote benchmark Markdown: {md_path}")
    print(f"Recommended tier: {results['recommended_tier']}")


if __name__ == "__main__":
    main()
