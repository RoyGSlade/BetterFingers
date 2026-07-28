"""Run the preservation probes against the REAL local model.

Two gates, one runner. Stage 9's `use_delivery_signals` feeds a delivery
summary into the main dictation prompt; Stage 11's `use_audience_context` feeds
a contact's prose into the same prompt. Both ship OFF until they pass here on a
real model rather than a fake one, and both are held to the same standard.

Mirrors tools/live_model_harness.py's split -- all decision logic lives in
delivery_preservation.py (unit-tested with fakes); this file is only readiness
discovery, engine wiring and argparse. It never starts, stops or reloads the
sidecar: it discovers whether one is already available and otherwise reports
UNAVAILABLE, which is deliberately not the same as PASS.

Never prints transcript or model text -- only the structural report.

Usage:
    python3 tools/delivery_preservation.py                    # both axes
    python3 tools/delivery_preservation.py --axis delivery    # one of them
    python3 tools/delivery_preservation.py --json             # machine-readable

Exit codes: 0 = every requested axis PASSed, 1 = FAIL or CALL_FAILED,
2 = UNAVAILABLE (no live model).
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from delivery_preservation import (  # noqa: E402
    run_audience_preservation_suite,
    run_delivery_preservation_suite,
)


def _build_process_fn():
    """Return (process_fn, error) using the already-running llama-server.

    process_fn(text, delivery_summary=..., audience_summary=...) -> cleaned
    text, i.e. exactly the signature the probes expect and exactly the call the
    dictation pipeline makes in server.py. Both kwargs are forwarded so one
    engine serves both axes.
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

    def process_fn(text, delivery_summary=None, audience_summary=None):
        return engine.process_fast_lane(
            text,
            "True Janitor",
            delivery_summary=delivery_summary,
            audience_summary=audience_summary,
        )

    return process_fn, None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    parser.add_argument(
        "--axis", choices=("delivery", "audience", "both"), default="both",
        help="which gate to run (default: both)",
    )
    args = parser.parse_args(argv)

    process_fn, error = _build_process_fn()
    if process_fn is None:
        report = {
            "overall": "UNAVAILABLE",
            "reason": error,
            "gate_note": (
                "No live model, so this run is not evidence either way. Both "
                "use_delivery_signals and use_audience_context stay OFF."
            ),
        }
        print(json.dumps(report, indent=2) if args.json else f"UNAVAILABLE: {error}")
        return 2

    axes = []
    if args.axis in ("delivery", "both"):
        axes.append(("Delivery-signal", "delivery", run_delivery_preservation_suite(process_fn)))
    if args.axis in ("audience", "both"):
        axes.append(("Audience", "audience", run_audience_preservation_suite(process_fn)))

    if args.json:
        print(json.dumps({name: report for _label, name, report in axes}, indent=2))
    else:
        for label, name, report in axes:
            _print_report(label, name, report)

    # Every requested axis has to pass. A green delivery run says nothing about
    # audience, and reporting the pair as one number would let one hide behind
    # the other.
    return 0 if all(report["overall"] == "PASS" for _l, _n, report in axes) else 1


def _print_report(label, axis, report):
    print(f"{label} preservation: {report['overall']} "
          f"({report['passed']}/{report['probe_count']} probes passed)")
    ratio_key = "calm_vs_agitated_length_ratio" if axis == "delivery" else "close_vs_formal_length_ratio"
    attributable_key = f"failure_attributable_to_{axis}"
    variants = "calm vs agitated" if axis == "delivery" else "close vs formal"

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
            print(f"      injected context leaked into output: {', '.join(result['signal_leak_detected'])}")
        if result.get("invented_addressing"):
            print(f"      greetings/sign-offs invented: {result['invented_addressing']}")
        if result.get("length_ratio_exceeded"):
            print(f"      {variants} length ratio {result[ratio_key]} -- the model editorialised")
        if result["status"] == "FAIL":
            if result.get(attributable_key):
                print(f"      ATTRIBUTABLE: the {axis} context caused this")
            elif result.get("baseline_also_failed"):
                print("      pre-existing: the baseline fails identically")
        print(f"      facts checked: {', '.join(result.get('fact_categories_checked') or ['NONE'])}")
    print(f"\n{report['gate_note']}\n")


if __name__ == "__main__":
    raise SystemExit(main())
