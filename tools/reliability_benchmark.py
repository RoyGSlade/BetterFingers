"""Reliability benchmark runner (§6.1) — drives a live BetterFingers sidecar.

Runs the automatable reliability checks against a running backend and prints a
pass/fail gate plus the hardware-bound manual checklist. The runner/report logic
lives in the top-level ``reliability_benchmark`` module (unit-tested); this file
is only the HTTP + argparse glue.

Usage (with the sidecar running, NOT in production mode so /drafts/test-mock is
available):

    python3 tools/reliability_benchmark.py --dictations 100 --health-checks 50
    python3 tools/reliability_benchmark.py --json report.json --skip-manual

Restart-recovery, audio-device unplug/replug, sleep/resume, long recordings, and
the injection matrix are hardware-bound and reported as manual checks to confirm.
"""

import argparse
import json
import os
import sys

# Allow running as `python3 tools/reliability_benchmark.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import reliability_benchmark as rb


def _http_call(base_url, token):
    import requests

    session = requests.Session()
    if token:
        session.headers["Authorization"] = f"Bearer {token}"

    def call(method, path, timeout=15):
        resp = session.request(method, f"{base_url}{path}", timeout=timeout)
        if not (200 <= resp.status_code < 300):
            raise RuntimeError(f"{method} {path} -> {resp.status_code}")
        return resp.json() if resp.content else {}

    return call


def main(argv=None):
    parser = argparse.ArgumentParser(description="BetterFingers reliability benchmark (§6.1).")
    parser.add_argument("--base-url", default=os.getenv("BETTERFINGERS_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--token", default=os.getenv("BETTERFINGERS_AUTH_TOKEN", ""))
    parser.add_argument("--dictations", type=int, default=100)
    parser.add_argument("--health-checks", type=int, default=50)
    parser.add_argument("--json", dest="json_path", default="")
    parser.add_argument("--skip-manual", action="store_true")
    args = parser.parse_args(argv)

    call = _http_call(args.base_url, args.token)
    report = rb.build_report(
        call,
        dictations=args.dictations,
        health_checks=args.health_checks,
        include_manual=not args.skip_manual,
    )
    print(report.summary())
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as fh:
            json.dump(report.to_dict(), fh, indent=2)
        print(f"\nWrote {args.json_path}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
