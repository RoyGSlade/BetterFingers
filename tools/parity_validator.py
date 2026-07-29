#!/usr/bin/env python3
"""Strict release-parity validator for the 438-item BetterFingers inventory.

This is the machine half of D-0015. It does NOT decide whether a row is
``wired`` -- a human does that, against the production Signal Desk page --
but it enforces every property that can be checked mechanically, so a
ledger cannot drift, soften, or quietly lose rows between waves:

* the ledger binds 1:1 to ``docs/ui/CURRENT_UI_INVENTORY.md`` (438 checkbox
  rows), by stable id AND by per-row SHA-256 binding, so an edit to the
  source inventory invalidates the binding instead of silently re-scoping
  the release;
* the status vocabulary is exactly ``wired`` / ``intentional_cut`` /
  ``blocked`` -- ``false``/``todo``/``stub``/``mock``/``cross_document``
  are release-forbidden (D-0015) and are rejected as statuses;
* every stated total (the exact-totals table, the by-section table and the
  by-workspace table) is recomputed from the rows rather than trusted;
* every ``wired`` row carries at least one resolvable production-evidence
  pointer and at least one resolvable QA/test-evidence pointer, and every
  pointed-at file actually exists;
* every ``intentional_cut`` row states a rationale;
* every ``blocked`` row names what is missing.

Per-row binding
---------------
``sha256("<stable id>\\n<source ref>\\n<full source item text>")``, where the
item text is the checkbox row with its ``- [ ]`` marker removed and any
continuation lines folded into one space-separated line. This is the Wave 0
scheme, reproduced exactly so Wave 11 does not invalidate Gate 0 evidence.

Run it directly (``python3 tools/parity_validator.py``) for a report, or
through ``tests/test_parity_inventory.py`` for the enforced version.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DOC = ROOT / "docs/ui/CURRENT_UI_INVENTORY.md"
LEDGER_DOC = ROOT / "docs/release/PARITY_INVENTORY.md"

VALID_STATUSES = ("wired", "intentional_cut", "blocked")

# D-0015: these are the words a release ledger is not allowed to use as a
# status. `blocked` is a legitimate status; it is the *release* that may not
# ship with one, which is a director ruling, not a validator rule.
FORBIDDEN_STATUS_WORDS = ("false", "todo", "stub", "mock", "cross_document", "partial", "wip")

CHECKBOX_RE = re.compile(r"^(?P<indent>\s*)- \[[ xX]\]\s?(?P<text>.*)$")
SECTION_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
LEDGER_ROW_RE = re.compile(r"^\|\s*(?P<sid>UI-\d\d-\d\d\d)\s*\|")


@dataclass
class SourceRow:
    """One checkbox row of the authoritative UI inventory."""

    index: int  # 1-based across the whole document
    line: int  # 1-based line number of the checkbox line
    section: str  # e.g. "§0 KNOWN BUGS FOUND DURING THIS INVENTORY (...)"
    section_number: int
    item_in_section: int
    text: str  # full text, continuation lines folded

    @property
    def stable_id(self) -> str:
        return f"UI-{self.section_number:02d}-{self.item_in_section:03d}"

    @property
    def source_ref(self) -> str:
        return f"§{self.section_number} item {self.item_in_section:03d} · L{self.line}"

    @property
    def binding(self) -> str:
        payload = f"{self.stable_id}\n{self.source_ref}\n{self.text}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class LedgerRow:
    """One row of docs/release/PARITY_INVENTORY.md's ledger table."""

    stable_id: str
    workspace: str
    source: str
    item: str
    evidence: str
    binding: str
    status: str
    line: int


@dataclass
class Report:
    source_rows: list[SourceRow] = field(default_factory=list)
    ledger_rows: list[LedgerRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def totals(self) -> dict[str, int]:
        counts = {status: 0 for status in VALID_STATUSES}
        for row in self.ledger_rows:
            if row.status in counts:
                counts[row.status] += 1
        counts["total"] = len(self.ledger_rows)
        return counts

    @property
    def ok(self) -> bool:
        return not self.errors


# --- source parsing ---------------------------------------------------------


def parse_source(path: Path = SOURCE_DOC) -> list[SourceRow]:
    """Extract the inventory's checkbox rows, folding continuation lines.

    A continuation line is any non-blank line that is more indented than its
    checkbox and is not itself a checkbox or a heading. Folding matters: the
    §0 bug rows run to a dozen lines each, and hashing only the first line
    would let the rest of the statement change without invalidating the
    binding.
    """
    lines = path.read_text(encoding="utf-8").split("\n")
    rows: list[SourceRow] = []
    section_title = ""
    section_number = -1
    item_in_section = 0
    index = 0

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        heading = SECTION_RE.match(line)
        if heading:
            section_title = heading.group("title")
            marker = re.match(r"^(\d+)\.\s+(.*)$", section_title)
            if marker:
                section_number = int(marker.group(1))
                section_title = f"§{section_number} {marker.group(2)}"
            else:
                section_number += 1
                section_title = f"§{section_number} {section_title}"
            item_in_section = 0
            idx += 1
            continue

        match = CHECKBOX_RE.match(line)
        if not match:
            idx += 1
            continue

        indent = len(match.group("indent"))
        text_parts = [match.group("text").rstrip()]
        cursor = idx + 1
        while cursor < len(lines):
            nxt = lines[cursor]
            if not nxt.strip():
                break
            if SECTION_RE.match(nxt) or nxt.startswith("#"):
                break
            if CHECKBOX_RE.match(nxt):
                break
            if len(nxt) - len(nxt.lstrip()) <= indent:
                break
            text_parts.append(nxt.strip())
            cursor += 1

        index += 1
        item_in_section += 1
        rows.append(
            SourceRow(
                index=index,
                line=idx + 1,
                section=section_title,
                section_number=section_number,
                item_in_section=item_in_section,
                text=" ".join(part for part in text_parts if part).strip(),
            )
        )
        idx = cursor

    return rows


# --- ledger parsing ---------------------------------------------------------


def parse_ledger(path: Path = LEDGER_DOC) -> list[LedgerRow]:
    rows: list[LedgerRow] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").split("\n"), start=1):
        if not LEDGER_ROW_RE.match(line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 7:
            raise ValueError(f"{path}:{lineno}: expected 7 ledger cells, got {len(cells)}")
        rows.append(
            LedgerRow(
                stable_id=cells[0],
                workspace=cells[1],
                source=cells[2],
                item=cells[3],
                evidence=cells[4],
                binding=cells[5].strip("`").removeprefix("sha256:"),
                status=cells[6].strip("`"),
                line=lineno,
            )
        )
    return rows


# --- stated-total parsing ---------------------------------------------------


def parse_stated_totals(path: Path = LEDGER_DOC) -> dict[str, int]:
    """The `## Exact totals` table, as the document states it."""
    stated: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").split("\n"):
        match = re.match(r"^\|\s*\**`?(wired|intentional_cut|blocked|Total)`?\**\s*\|\s*\**(\d+)\**\s*\|$", line)
        if match:
            stated[match.group(1).lower()] = int(match.group(2))
    return stated


def normalize_key(name: str) -> str:
    """Compare table keys ignoring Markdown code formatting and bold."""
    return name.replace("`", "").replace("**", "").strip()


def parse_breakdown(path: Path, heading: str) -> dict[str, tuple[int, int, int, int]]:
    """A `| name | wired | cut | blocked | total |` breakdown table under `heading`."""
    text = path.read_text(encoding="utf-8")
    start = text.find(heading)
    if start < 0:
        return {}
    chunk = text[start + len(heading):]
    ends = [pos for pos in (chunk.find("\n## "), chunk.find("\n### ")) if pos > 0]
    if ends:
        chunk = chunk[: min(ends)]
    out: dict[str, tuple[int, int, int, int]] = {}
    for line in chunk.split("\n"):
        match = re.match(
            r"^\|\s*(?P<name>[^|]+?)\s*\|\s*(?P<w>\d+)\s*\|\s*(?P<c>\d+)\s*\|\s*(?P<b>\d+)\s*\|\s*(?P<t>\d+)\s*\|$",
            line,
        )
        if match:
            out[normalize_key(match.group("name"))] = (
                int(match.group("w")),
                int(match.group("c")),
                int(match.group("b")),
                int(match.group("t")),
            )
    return out


# --- evidence pointers ------------------------------------------------------

POINTER_RE = re.compile(r"`([^`]+)`")


# Evidence cells write some pointers repo-relative and some relative to the
# renderer root (the Wave 0 ledger did both). Resolution tries each base in
# order, so `lib/wipeSummary.mjs` and `app/src/renderer/lib/wipeSummary.mjs`
# both resolve to the same real file instead of one of them reading as a
# dangling pointer.
POINTER_BASES = ("", "app/src/renderer/", "app/", "app/src/")


def evidence_paths(cell: str) -> list[str]:
    """Repo-relative file paths named inside an evidence cell's backticks."""
    out: list[str] = []
    for token in POINTER_RE.findall(cell):
        candidate = token.split("#", 1)[0].split(":", 1)[0].strip()
        if "/" not in candidate:
            continue
        if not re.search(r"\.(js|mjs|py|html|css|md|json)$", candidate):
            continue
        out.append(candidate)
    return out


def resolve_pointer(pointer: str, root: Path) -> str | None:
    """The repo-relative path a pointer names, or None when nothing exists."""
    for base in POINTER_BASES:
        candidate = f"{base}{pointer}"
        if (root / candidate).exists():
            return candidate
    return None


PRODUCTION_MARKERS = (
    "app/src/renderer/signal-desk.html",
    "app/src/renderer/bootstrap/signalDeskApp.js",
    "app/src/renderer/features/",
    "app/src/renderer/lib/",
    "app/src/renderer/api/backend.js",
    "app/src/renderer/talkDrafts.js",
    "app/src/renderer/signalCore.js",
    "app/src/renderer/overlay.html",
    "app/src/renderer/review-overlay.html",
    "app/src/renderer/glitch-ring.js",
)

QA_MARKERS = (
    "app/tests/",
    "tests/",
)


def validate(root: Path = ROOT) -> Report:
    report = Report()
    source_doc = root / "docs/ui/CURRENT_UI_INVENTORY.md"
    ledger_doc = root / "docs/release/PARITY_INVENTORY.md"

    report.source_rows = parse_source(source_doc)
    report.ledger_rows = parse_ledger(ledger_doc)

    if len(report.source_rows) != 438:
        report.errors.append(
            f"source inventory has {len(report.source_rows)} checkbox rows, expected 438"
        )

    by_source = {row.stable_id: row for row in report.source_rows}
    seen: set[str] = set()

    for row in report.ledger_rows:
        if row.stable_id in seen:
            report.errors.append(f"L{row.line}: duplicate stable id {row.stable_id}")
        seen.add(row.stable_id)

        if row.status not in VALID_STATUSES:
            report.errors.append(
                f"L{row.line}: {row.stable_id} status {row.status!r} is not one of {VALID_STATUSES}"
            )
        if row.status.lower() in FORBIDDEN_STATUS_WORDS:
            report.errors.append(
                f"L{row.line}: {row.stable_id} uses release-forbidden status {row.status!r} (D-0015)"
            )

        src = by_source.get(row.stable_id)
        if src is None:
            report.errors.append(f"L{row.line}: {row.stable_id} has no source inventory row")
            continue
        if row.binding != src.binding:
            report.errors.append(
                f"L{row.line}: {row.stable_id} binding {row.binding[:12]}… does not match "
                f"source {src.binding[:12]}… (source inventory changed under the ledger)"
            )
        if row.source != src.source_ref:
            report.errors.append(
                f"L{row.line}: {row.stable_id} source ref {row.source!r} != {src.source_ref!r}"
            )

        resolved: list[str] = []
        for pointer in evidence_paths(row.evidence):
            target = resolve_pointer(pointer, root)
            if target is None:
                report.errors.append(
                    f"L{row.line}: {row.stable_id} points at missing file {pointer}"
                )
            else:
                resolved.append(target)

        if row.status == "wired":
            has_prod = any(p.startswith(PRODUCTION_MARKERS) for p in resolved)
            has_qa = any(p.startswith(QA_MARKERS) for p in resolved)
            if not has_prod:
                report.errors.append(
                    f"L{row.line}: {row.stable_id} is `wired` with no production-file evidence pointer"
                )
            if not has_qa:
                report.errors.append(
                    f"L{row.line}: {row.stable_id} is `wired` with no QA/test evidence pointer"
                )
        elif row.status == "intentional_cut":
            # Wave 11 standardises the prose so this is an exact check rather
            # than a keyword guess: a cut states its rationale or it is not a
            # decision, it is an omission.
            if "Intentional cut:" not in row.evidence:
                report.errors.append(
                    f"L{row.line}: {row.stable_id} is `intentional_cut` without an "
                    "`Intentional cut: <rationale>` statement"
                )
        elif row.status == "blocked":
            if "Blocked:" not in row.evidence:
                report.errors.append(
                    f"L{row.line}: {row.stable_id} is `blocked` without a "
                    "`Blocked: <what is missing>` statement"
                )

    missing = sorted(set(by_source) - seen)
    for stable_id in missing:
        report.errors.append(f"source row {stable_id} has no ledger row")

    # --- stated totals -------------------------------------------------------
    computed = report.totals
    stated = parse_stated_totals(ledger_doc)
    for key in ("wired", "intentional_cut", "blocked", "total"):
        if key not in stated:
            report.errors.append(f"exact-totals table is missing the {key!r} row")
        elif stated[key] != computed[key]:
            report.errors.append(
                f"exact-totals table says {key}={stated[key]}, rows say {computed[key]}"
            )

    for heading, attr in (
        ("### Totals by source section", "section"),
        ("### Totals by release workspace", "workspace"),
    ):
        table = parse_breakdown(ledger_doc, heading)
        if not table:
            report.errors.append(f"{heading} table is missing or unparsable")
            continue
        actual: dict[str, list[int]] = {}
        for row in report.ledger_rows:
            src = by_source.get(row.stable_id)
            if src is None:
                continue
            key = normalize_key(src.section if attr == "section" else row.workspace)
            bucket = actual.setdefault(key, [0, 0, 0, 0])
            if row.status == "wired":
                bucket[0] += 1
            elif row.status == "intentional_cut":
                bucket[1] += 1
            elif row.status == "blocked":
                bucket[2] += 1
            bucket[3] += 1
        for key, counts in sorted(actual.items()):
            if key not in table:
                report.errors.append(f"{heading}: no row for {key!r}")
            elif list(table[key]) != counts:
                report.errors.append(
                    f"{heading}: {key!r} states {list(table[key])}, rows say {counts}"
                )
        for key in table:
            if key not in actual and any(table[key]):
                report.errors.append(f"{heading}: states nonzero counts for unknown key {key!r}")

    return report


def main(argv: list[str]) -> int:
    report = validate()
    totals = report.totals
    payload = {
        "source_rows": len(report.source_rows),
        "ledger_rows": len(report.ledger_rows),
        "totals": totals,
        "errors": report.errors,
    }
    if "--json" in argv:
        print(json.dumps(payload, indent=2))
    else:
        print(f"source rows : {len(report.source_rows)}")
        print(f"ledger rows : {len(report.ledger_rows)}")
        print(
            "totals      : "
            f"{totals['wired']} wired / {totals['intentional_cut']} intentional_cut / "
            f"{totals['blocked']} blocked / {totals['total']} total"
        )
        if report.errors:
            print(f"\n{len(report.errors)} ERROR(S):")
            for error in report.errors:
                print(f"  - {error}")
        else:
            print("\nOK — ledger is internally consistent and bound to the source inventory.")
    return 0 if report.ok else 1


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.exit(main(sys.argv[1:]))
