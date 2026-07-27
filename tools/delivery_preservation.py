"""Run the delivery-signal preservation probe against the REAL local model.

This is the gate described in plan Stage 9: `use_delivery_signals` feeds a
delivery summary into the main dictation prompt, and it ships OFF until this
passes on a real model rather than a fake one.

Mirrors tools/live_model_harness.py's split -- all decision logic lives in
delivery_preservation.py (unit-tested with fakes); this file is only readiness
discovery, engine wiring and argparse. It never starts, stops or reloads the
sidecar: it discovers whether one is already available and otherwise reports
UNAVAILABLE, which is deliberately not the same as PASS.

Never prints transcript or model text -- only the structural report.

Usage:
    python3 tools/delivery_preservation.py           # human-readable
    python3 tools/delivery_preservation.py --json    # machine-readable

Exit codes: 0 = PASS, 1 = FAIL or CALL_FAILED, 2 = UNAVAILABLE (no live model).
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from delivery_preservation import run_delivery_preservation_suite  # noqa: E402


def _build_process_fn():
    """Return (process_fn, error) using the already-running llama-server.

    process_fn(text, delivery_summary=...) -> cleaned text, i.e. exactly the
    signature the probe expects and exactly the call the dictation pipeline
    makes in server.py.
    """
    try:
        import llm_engine
    except Exception as exc:  # noqa: BLE001
        return None, f"llm_engine import failed: {type(exc).__name__}"

    # DISCOVER, never start. engine.ensure_ready() would call _setup_server()
    # and spin up llama-server -- loading a 12B model as a side effect of asking
    # "is one available?" is both slow and surprising, and it would make this
    # probe's result depend on a server it created rather than the one the app
    # actually runs. Same discipline as tools/live_model_harness.py.
    try:
        if not llm_engine.is_server_running():
            return None, "llama-server is not running (start the app first; this probe never spawns one)"
    except Exception as exc:  # noqa: BLE001
        return None, f"readiness check failed: {type(exc).__name__}"

    try:
        engine = llm_engine.LLMEngine()
    except Exception as exc:  # noqa: BLE001
        return None, f"engine construction failed: {type(exc).__name__}"

    def process_fn(text, delivery_summary=None):
        return engine.process_fast_lane(
            text,
            "True Janitor",
            delivery_summary=delivery_summary,
        )

    return process_fn, None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args(argv)

    process_fn, error = _build_process_fn()
    if process_fn is None:
        report = {
            "overall": "UNAVAILABLE",
            "reason": error,
            "gate_note": (
                "No live model, so this run is not evidence either way. "
                "use_delivery_signals stays OFF."
            ),
        }
        print(json.dumps(report, indent=2) if args.json else f"UNAVAILABLE: {error}")
        return 2

    report = run_delivery_preservation_suite(process_fn)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Delivery-signal preservation: {report['overall']} "
              f"({report['passed']}/{report['probe_count']} probes passed)")
        for result in report["results"]:
            print(f"  - {result['probe']}: {result['status']}")
            if result["status"] == "CALL_FAILED":
                print(f"      model call raised {result['exception_type']}")
                continue
            if result.get("lost_intensity_markers"):
                print(f"      intensity lost in: {', '.join(result['lost_intensity_markers'])}")
            if result.get("fact_preservation_failures"):
                print(f"      facts dropped: {result['fact_preservation_failures']}")
            if result.get("signal_leak_detected"):
                print(f"      measurements leaked into output: {', '.join(result['signal_leak_detected'])}")
            if result.get("length_ratio_exceeded"):
                print(f"      calm vs agitated length ratio {result['calm_vs_agitated_length_ratio']} "
                      "-- the model editorialised")
            if result["status"] == "FAIL":
                if result.get("failure_attributable_to_delivery"):
                    print("      ATTRIBUTABLE: the delivery summary caused this")
                elif result.get("baseline_also_failed"):
                    print("      pre-existing: the baseline (no delivery summary) fails identically")
            print(f"      facts checked: {', '.join(result.get('fact_categories_checked') or ['NONE'])}")
        print(f"\n{report['gate_note']}")

    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
