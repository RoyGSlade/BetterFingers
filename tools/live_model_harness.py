"""Live-model Message Rescue integration harness CLI (I3.10).

Exercises the REAL local llama-server sidecar (if one is already running and
healthy) through ``backend.services.rescue_llm_adapter`` +
``backend.services.message_rescue`` with one preservation-critical synthetic
transcript, using the same decision/report logic
(``live_model_harness.run_harness``, unit-tested with fakes in
``tests/test_live_model_harness.py``) that ``tests/test_live_model_integration.py``
uses. This file is only the readiness-check + adapter-wiring + argparse glue,
mirroring ``tools/reliability_benchmark.py``'s split from ``reliability_benchmark.py``.

Deliberately does NOT start, stop, or reload the sidecar (that is
llm_engine.LLMEngine / server.py's job, out of this task's claimed scope) — it
only discovers whether one is already available. Never prints transcript or
model *content*: only the structural report (booleans, counts, category
names).

Usage:
    python3 tools/live_model_harness.py            # human-readable
    python3 tools/live_model_harness.py --json      # machine-readable

Exit codes: 0 = PASS, 2 = UNAVAILABLE (no live model — not a failure), 1 =
FAIL or CALL_FAILED. UNAVAILABLE is never reported as 0/PASS.
"""

import argparse
import json
import os
import sys

# Allow running as `python3 tools/live_model_harness.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import live_model_harness as harness
from backend.services.rescue_llm_adapter import build_llm_call_fn
from llm_engine import SIDECAR_PORT, is_server_running
from model_manager import DEFAULT_MODEL, get_model_file_status


class _RealEngine:
    """Minimal ``rescue_llm_adapter._EngineLike`` — just carries ``api_url``."""

    def __init__(self, api_url: str):
        self.api_url = api_url


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Live-model Message Rescue integration harness (I3.10). Runs one "
            "preservation-critical request through the real local llama-server "
            "sidecar if one is already available; never starts/stops the sidecar "
            "itself. Never prints transcript or model content."
        )
    )
    parser.add_argument("--api-url", default=f"http://127.0.0.1:{SIDECAR_PORT}")
    parser.add_argument("--model-id", default=DEFAULT_MODEL)
    parser.add_argument("--json", action="store_true", help="Emit the structural report as JSON.")
    args = parser.parse_args(argv)

    call_fn = build_llm_call_fn(_RealEngine(args.api_url))
    report = harness.run_harness(
        is_server_running=is_server_running,
        call_fn=call_fn,
        get_model_status=get_model_file_status,
        model_id=args.model_id,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"status: {report['status']}")
        print(f"reason: {report['reason']}")
        if report["probe"] is not None:
            print("probe:")
            for key, value in report["probe"].items():
                print(f"  {key}: {value}")

    if report["status"] == "UNAVAILABLE":
        return 2
    if report["status"] == "PASS":
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
