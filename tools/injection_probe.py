"""Injection compatibility probe (§7, M2) — fills the matrix against live apps.

Injects the test battery into whatever window you focus, times it, and records
your pass/fail/partial verdict per dimension into a versioned matrix JSON. The
schema, aggregation, and Markdown rendering live in the top-level
``injection_matrix`` module (unit-tested); this is the interactive glue.

Usage (focus the target app when prompted):

    python3 tools/injection_probe.py --app "VS Code" --out matrix-linux.json
    python3 tools/injection_probe.py --render matrix-linux.json   # print capability table
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import injection_matrix as im


def _platform_string():
    import platform_capabilities as pc

    if pc.is_windows:
        return "windows"
    if pc.is_macos:
        return "macos"
    if pc.is_linux:
        return "linux-wayland" if pc.is_wayland else "linux-x11"
    return "unknown"


def _ask(prompt, choices=("pass", "fail", "partial", "skip")):
    hint = "/".join(choices)
    while True:
        answer = input(f"{prompt} [{hint}]: ").strip().lower()
        if answer in choices:
            return answer
        print(f"  please answer one of: {hint}")


def probe(app, out_path, countdown=4):
    from injector import InputInjector

    injector = InputInjector()
    platform = _platform_string()
    result = im.TargetResult(app=app, platform=platform, injection_method=injector.injection_method)
    try:
        result.app_version = input("Target app version (optional): ").strip()
    except EOFError:
        result.app_version = ""

    latencies = []
    for dimension, text in im.TEST_STRINGS.items():
        print(f"\n=== {dimension} ===\nWill inject: {text!r}")
        print(f"Focus the target app now — injecting in {countdown}s...")
        for remaining in range(countdown, 0, -1):
            print(f"  {remaining}...", end="", flush=True)
            time.sleep(1)
        print()
        start = time.perf_counter()
        try:
            injector.type_text(text)
        except Exception as exc:  # noqa: BLE001
            print(f"  injection raised: {exc}")
        latencies.append((time.perf_counter() - start) * 1000.0)
        verdict = _ask(f"Did {dimension!r} land correctly?")
        if verdict != "skip":
            result.set(dimension, verdict)

    # Behavioral dimensions the operator judges without a fresh injection.
    for dimension in ("selection_replace", "clipboard_restore", "focus_loss", "elevated"):
        verdict = _ask(f"{dimension}?")
        if verdict != "skip":
            result.set(dimension, verdict)

    if latencies:
        result.latency_ms = round(sum(latencies) / len(latencies), 1)
    result.notes = input("Notes (optional): ").strip()

    # Merge into any existing matrix file (replace this app+platform row).
    existing = im.load(out_path) if os.path.exists(out_path) else []
    existing = [r for r in existing if not (r.app == app and r.platform == platform)]
    existing.append(result)
    im.dump(existing, out_path)
    print(f"\nRecorded {app} [{platform}] → {out_path} (overall: {result.overall})")


def main(argv=None):
    parser = argparse.ArgumentParser(description="BetterFingers injection compatibility probe (§7).")
    parser.add_argument("--app", help="Target app name (must match a matrix target).")
    parser.add_argument("--out", default="injection-matrix.json", help="Matrix JSON to write/merge.")
    parser.add_argument("--countdown", type=int, default=4, help="Seconds to focus the target before injecting.")
    parser.add_argument("--render", metavar="MATRIX_JSON", help="Print the capability table for a matrix file and exit.")
    args = parser.parse_args(argv)

    if args.render:
        print(im.to_capability_markdown(im.load(args.render)))
        return 0
    if not args.app:
        parser.error("--app is required unless --render is given")
    probe(args.app, args.out, countdown=args.countdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
