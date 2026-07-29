#!/usr/bin/env python3
"""Row-level status churn between the committed ledger and the working copy.

A totals line ("391 wired") says how many rows moved but not WHICH, and a
regenerated release artifact must never be adopted on a count alone. Prints
every row whose status changed, so a blast-radius review is a diff of rulings
rather than a diff of 438 reflowed prose cells.

Usage:  python3 tools/parity_churn.py [git-ref]      (default: HEAD)
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEDGER_REL = "docs/release/PARITY_INVENTORY.md"
ROW_RE = re.compile(r"^\| (UI-[0-9-]+) \|.*\| `([a-z_]+)` \|$")


def statuses(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        match = ROW_RE.match(line)
        if match:
            out[match.group(1)] = match.group(2)
    return out


def main() -> int:
    ref = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    committed = subprocess.run(
        ["git", "show", f"{ref}:{LEDGER_REL}"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    working = (ROOT / LEDGER_REL).read_text(encoding="utf-8")

    before, after = statuses(committed), statuses(working)
    print(f"rows parsed: {len(before)} at {ref}, {len(after)} in working copy\n")

    moved = [(rid, before[rid], after[rid])
             for rid in sorted(after)
             if rid in before and before[rid] != after[rid]]

    if not moved:
        print("no status changed.")
        return 0

    print(f"{len(moved)} row(s) changed status:")
    for rid, was, now in moved:
        print(f"  {rid}: {was} -> {now}")

    print("\nby transition:")
    counts: dict[str, int] = {}
    for _, was, now in moved:
        counts[f"{was} -> {now}"] = counts.get(f"{was} -> {now}", 0) + 1
    for transition, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {transition}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
