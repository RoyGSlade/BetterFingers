"""Injection compatibility matrix (§7, M2).

"Works anywhere" is the product's promise and its most OS-fragile claim. This
module is the versioned record of *where* injection actually works — a matrix,
not tribal memory. For each target app on each platform it tracks, per dimension
(plain text, multiline, Unicode, punctuation, selection replacement, clipboard
restoration, focus-loss behavior, elevated windows), whether injection succeeds,
plus the method used and average latency.

The schema, aggregation, and capability-matrix rendering here are pure and
unit-tested. The probe that actually injects into live apps and records results
lives in ``tools/injection_probe.py``.
"""

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Per-target dimensions. A target "passes" overall only when the load-bearing
# dimensions (at least plain_text + clipboard_restore) pass.
DIMENSIONS = [
    "plain_text",
    "multiline",
    "unicode",
    "punctuation",
    "selection_replace",
    "clipboard_restore",
    "focus_loss",
    "elevated",
]

# Dimension result values.
PASS = "pass"
FAIL = "fail"
PARTIAL = "partial"
UNTESTED = "untested"
_VALID_STATUS = frozenset({PASS, FAIL, PARTIAL, UNTESTED})

# Platforms the matrix distinguishes (injection behavior differs sharply across them).
PLATFORMS = ["windows", "linux-x11", "linux-wayland", "macos"]

# The starting target list from the M2 plan. Known failure surfaces to probe are
# noted where relevant.
DEFAULT_TARGETS = [
    "Chrome text input",
    "Google Docs",
    "Outlook",
    "Word",
    "VS Code",
    "Discord",
    "Slack",
    "Notepad",
    "Terminal",
    "EHR-like web form",
    "Remote desktop",
]

# The battery a probe injects into each target.
TEST_STRINGS = {
    "plain_text": "the quick brown fox jumps over the lazy dog",
    "multiline": "first line\nsecond line\nthird line",
    "unicode": "café résumé naïve — emoji 😀 and Ω≈ç√",
    "punctuation": "Hello, world! \"Quotes\" (parens) [brackets] {braces} 50% @ #tag; a/b\\c.",
}


@dataclass
class TargetResult:
    app: str
    platform: str
    injection_method: str = ""
    app_version: str = ""
    latency_ms: Optional[float] = None
    notes: str = ""
    dimensions: Dict[str, str] = field(default_factory=lambda: {d: UNTESTED for d in DIMENSIONS})

    def set(self, dimension: str, status: str):
        if dimension not in DIMENSIONS:
            raise ValueError(f"unknown dimension: {dimension}")
        if status not in _VALID_STATUS:
            raise ValueError(f"invalid status: {status}")
        self.dimensions[dimension] = status

    @property
    def overall(self) -> str:
        """A target passes only when the load-bearing dimensions pass; fails if
        any dimension failed; otherwise it's still untested/partial."""
        core = [self.dimensions.get("plain_text", UNTESTED), self.dimensions.get("clipboard_restore", UNTESTED)]
        if any(v == FAIL for v in self.dimensions.values()):
            return FAIL
        if all(v == PASS for v in core):
            return PASS
        if any(v in (PASS, PARTIAL) for v in self.dimensions.values()):
            return PARTIAL
        return UNTESTED

    def to_dict(self) -> dict:
        return {
            "app": self.app,
            "platform": self.platform,
            "injection_method": self.injection_method,
            "app_version": self.app_version,
            "latency_ms": self.latency_ms,
            "notes": self.notes,
            "dimensions": dict(self.dimensions),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TargetResult":
        dims = {d: UNTESTED for d in DIMENSIONS}
        for key, value in (data.get("dimensions") or {}).items():
            if key in DIMENSIONS and value in _VALID_STATUS:
                dims[key] = value
        return cls(
            app=data.get("app", ""),
            platform=data.get("platform", ""),
            injection_method=data.get("injection_method", ""),
            app_version=data.get("app_version", ""),
            latency_ms=data.get("latency_ms"),
            notes=data.get("notes", ""),
            dimensions=dims,
        )


def default_matrix(platform: str, targets: Optional[List[str]] = None) -> List[TargetResult]:
    """A fresh, all-untested matrix for one platform."""
    return [TargetResult(app=app, platform=platform) for app in (targets or DEFAULT_TARGETS)]


def coverage(results: List[TargetResult]) -> dict:
    """How much of the matrix has actually been exercised."""
    cells = len(results) * len(DIMENSIONS)
    tested = sum(1 for r in results for v in r.dimensions.values() if v != UNTESTED)
    passed = sum(1 for r in results for v in r.dimensions.values() if v == PASS)
    return {
        "targets": len(results),
        "cells": cells,
        "tested": tested,
        "passed": passed,
        "tested_pct": round(100.0 * tested / cells, 1) if cells else 0.0,
    }


def load(path: str) -> List[TargetResult]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return [TargetResult.from_dict(item) for item in data.get("results", [])]


def dump(results: List[TargetResult], path: str):
    payload = {"version": 1, "results": [r.to_dict() for r in results]}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


_STATUS_MARK = {PASS: "✅", FAIL: "❌", PARTIAL: "⚠️", UNTESTED: "·"}


def to_capability_markdown(results: List[TargetResult]) -> str:
    """Render the per-target capability matrix as a Markdown table."""
    header = "| App | Platform | Method | " + " | ".join(DIMENSIONS) + " | Latency |"
    sep = "|" + "---|" * (4 + len(DIMENSIONS))
    lines = [header, sep]
    for r in results:
        cells = " | ".join(_STATUS_MARK.get(r.dimensions.get(d, UNTESTED), "·") for d in DIMENSIONS)
        latency = f"{r.latency_ms:.0f}ms" if isinstance(r.latency_ms, (int, float)) else "—"
        lines.append(f"| {r.app} | {r.platform} | {r.injection_method or '—'} | {cells} | {latency} |")
    return "\n".join(lines)
