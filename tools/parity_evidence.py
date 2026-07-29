#!/usr/bin/env python3
"""Collect production evidence for the Wave 11 strict parity re-audit.

The Gate 0 ledger classified every row ``blocked`` because the production
Signal Desk page did not exist as a shipping target. Waves 1-10 built it.
This module answers, mechanically and per row, the question the strict rule
(D-0015) actually asks:

    does this inventory item resolve inside the PRODUCTION composition --
    ``signal-desk.html`` plus the module closure its bootstrap actually
    imports -- and is it covered by a test or a production-target QA
    scenario?

What it does NOT do is decide the status. It reports resolvable facts;
``docs/release/PARITY_INVENTORY.md`` records the ruling, and rows whose
evidence chain is incomplete stay ``blocked``. Nothing here promotes a row
because a legacy handler exists: the legacy closure is collected only so a
row can be reported as "legacy-only", which is a *reason to stay blocked*
or to be cut, never a reason to pass.

Identifier extraction is deliberately conservative. Only tokens the source
inventory itself wrote in backticks are treated as identifiers, because
those are the ones the inventory author asserted are real code handles.
Prose-only rows resolve to nothing and are reported as ``unanchored`` --
they need a human anchor (see ``ANCHORS``) or they stay blocked.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "app/src/renderer"

PROD_ENTRY_HTML = RENDERER / "signal-desk.html"
PROD_ENTRY_JS = RENDERER / "bootstrap/signalDeskApp.js"
LEGACY_ENTRY_HTML = RENDERER / "index.html"
LEGACY_ENTRY_JS = RENDERER / "main.js"

# The two floating windows are production surfaces in their own right: they
# are separate always-on-top BrowserWindows created by app/src/main/windows.js
# and they ship whichever dashboard page is loaded, so they belong in the
# production closure. Leaving them out made §12 read as 13 product gaps that
# are in fact shipping code.
PROD_EXTRA_PAGES = (
    (RENDERER / "overlay.html", RENDERER / "glitch-ring.js"),
    (RENDERER / "review-overlay.html", None),
)

QA_DIR = ROOT / "app/tests/qa/scenarios"
UNIT_DIR = ROOT / "app/tests"

# The only QA target that exercises the production composition root.
#
# `signal-desk` is the mockup preview and is pinned there by D-0007. Untagged
# scenarios are NOT included either, even though the Wave 11 flip made the
# production page the default RUN target: untagged scenarios belong to the
# `legacy` target (app/tests/qa/run.mjs's DEFAULT_SCENARIO_UI), because they
# were written against index.html's ids. Counting them would credit the
# production page with coverage that never touches it.
PROD_QA_TARGETS = {"signal-desk-prod"}

IMPORT_RE = re.compile(r"""["']((?:\.{1,2}/)[^"']+)["']""")
SCRIPT_SRC_RE = re.compile(r"""<script[^>]+src=["']([^"']+)["']""")
ID_ATTR_RE = re.compile(r"""\bid=["']([A-Za-z0-9_\-]+)["']""")
CLASS_ATTR_RE = re.compile(r"""\bclass=["']([^"']+)["']""")


# --- module closure ---------------------------------------------------------


def _resolve_import(spec: str, importer: Path) -> Path | None:
    target = (importer.parent / spec).resolve()
    if target.exists() and target.is_file():
        return target
    for suffix in (".js", ".mjs"):
        candidate = target.with_name(target.name + suffix)
        if candidate.exists():
            return candidate
    return None


def module_closure(entry_html: Path, entry_js: Path) -> set[Path]:
    """Every renderer file reachable from a page's own script graph.

    Reachability is the whole point: a feature module that exists on disk but
    is never imported by the production bootstrap is not in the product, and
    a ledger that counted it would be lying.
    """
    seen: set[Path] = set()
    queue: list[Path] = []

    if entry_html.exists():
        seen.add(entry_html)
        html = entry_html.read_text(encoding="utf-8", errors="replace")
        for src in SCRIPT_SRC_RE.findall(html):
            if src.startswith(("http:", "https:", "//")):
                continue
            resolved = _resolve_import(src if src.startswith(".") else f"./{src}", entry_html)
            if resolved:
                queue.append(resolved)
    if entry_js.exists():
        queue.append(entry_js)

    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            text = current.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for spec in IMPORT_RE.findall(text):
            resolved = _resolve_import(spec, current)
            if resolved and resolved not in seen:
                queue.append(resolved)
    return seen


@dataclass
class Closure:
    """A page's reachable source, indexed for identifier lookup."""

    name: str
    files: set[Path]
    text: str = ""
    element_ids: set[str] = field(default_factory=set)
    class_names: set[str] = field(default_factory=set)

    @classmethod
    def build(cls, name: str, entry_html: Path, entry_js: Path, extra=()) -> "Closure":
        files = module_closure(entry_html, entry_js)
        for extra_html, extra_js in extra:
            files |= module_closure(extra_html, extra_js or Path("/nonexistent"))
        chunks = []
        ids: set[str] = set()
        classes: set[str] = set()
        for path in sorted(files):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            chunks.append(text)
            if path.suffix == ".html":
                ids.update(ID_ATTR_RE.findall(text))
                for value in CLASS_ATTR_RE.findall(text):
                    classes.update(value.split())
        return cls(name=name, files=files, text="\n".join(chunks), element_ids=ids, class_names=classes)

    def rel_files(self) -> list[str]:
        return sorted(str(path.relative_to(ROOT)) for path in self.files)


# --- identifier extraction --------------------------------------------------

BACKTICK_RE = re.compile(r"`([^`]+)`")
ENDPOINT_RE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|WS)\s+(/\S+)$")

# Tokens that are prose, units or types rather than code handles. Treating
# these as identifiers would manufacture false "unresolved" reports.
NOISE = {
    "true",
    "false",
    "null",
    "undefined",
    "number",
    "string",
    "boolean",
    "object",
    "array",
    "0",
    "1",
}


@dataclass
class Identifier:
    raw: str
    kind: str  # 'id' | 'class' | 'endpoint' | 'symbol'
    needle: str


def extract_identifiers(text: str) -> list[Identifier]:
    out: list[Identifier] = []
    seen: set[str] = set()
    for token in BACKTICK_RE.findall(text):
        token = token.strip()
        if not token or token.lower() in NOISE or token in seen:
            continue
        seen.add(token)

        endpoint = ENDPOINT_RE.match(token)
        if endpoint:
            out.append(Identifier(token, "endpoint", endpoint.group(2).split("?")[0]))
            continue
        if token.startswith("#") and re.fullmatch(r"#[A-Za-z0-9_\-]+", token):
            out.append(Identifier(token, "id", token[1:]))
            continue
        if token.startswith(".") and re.fullmatch(r"\.[A-Za-z0-9_\-]+", token):
            out.append(Identifier(token, "class", token[1:]))
            continue
        if token.startswith("/") and re.fullmatch(r"/[A-Za-z0-9_\-/{}:.]+", token):
            out.append(Identifier(token, "endpoint", token.split("?")[0]))
            continue
        symbol = re.fullmatch(r"([A-Za-z_$][A-Za-z0-9_$]*)(?:\(\))?", token)
        if symbol:
            out.append(Identifier(token, "symbol", symbol.group(1)))
            continue
        # Anything else (prose in backticks, selectors with combinators,
        # localStorage['x'] expressions) is reported but not resolved -- it
        # is not a handle this collector can honestly look up.
        out.append(Identifier(token, "other", token))
    return out


# --- the Signal Desk renaming rule -------------------------------------------
#
# Signal Desk did not keep index.html's element ids. It namespaces every id by
# workspace: `#exportProfileButton` became `#sdSetExportProfileButton`,
# `#privacyWipeVoices` became `#sdSetPrivacyWipeVoices`, and the profile-field
# ids dropped their `setting` prefix on the way (`#settingRecordingMode` ->
# `#sdSetRecordingMode`). The mapping is not a guess: it is written out
# explicitly in features/settingsWorkspace.js's SETTINGS_ELEMENT_IDS and the
# sibling collect*Elements() maps.
#
# Matching on the namespaced tail is therefore a real resolution, not a
# coincidence -- but it is only ever used to *find a candidate anchor*, and
# the ledger records the concrete production id it matched so the ruling
# stays checkable. A tail match alone never promotes a row; the row still
# needs the rest of the D-0015 chain.
SD_WORKSPACE_TOKENS = (
    "set",
    "util",
    "talk",
    "library",
    "studio",
    "ctx",
    "context",
    "status",
    "teach",
    "persona",
    "contact",
    "first",
    "onboarding",
    "onboard",
    "send",
    "signal",
    "test",
    "stress",
    "capture",
    "delivery",
    "draft",
    "voice",
    "read",
    "raw",
    "refined",
    "revise",
    "rewrite",
    "publish",
    "filter",
    "example",
    "confidence",
    "header",
    "shortcut",
    "selected",
)

# Legacy prefixes Signal Desk drops when it re-namespaces a control:
# `#settingRecordingMode` -> `#sdSetRecordingMode`, `#onboardingConsent` ->
# `#sdOnboardConsent`. The legacy id repeated its section name; the Signal
# Desk id carries it in the `sd<Workspace>` prefix instead, so the same word
# would otherwise appear twice and never match.
LEGACY_DROPPED_PREFIXES = ("setting", "settings", "onboarding", "dashboard")


def _namespace_tails(prod_id: str) -> set[str]:
    """The names a production id can answer to, lowercased."""
    lower = prod_id.lower()
    tails = {lower}
    if lower.startswith("sd"):
        rest = lower[2:]
        tails.add(rest)
        for token in SD_WORKSPACE_TOKENS:
            if rest.startswith(token) and len(rest) > len(token):
                tails.add(rest[len(token):])
    return tails


def _legacy_aliases(legacy_id: str) -> set[str]:
    lower = legacy_id.lower()
    out = {lower}
    for prefix in LEGACY_DROPPED_PREFIXES:
        if lower.startswith(prefix) and len(lower) > len(prefix):
            out.add(lower[len(prefix):])
    return out


def build_id_index(closure: Closure) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for prod_id in closure.element_ids:
        for tail in _namespace_tails(prod_id):
            index.setdefault(tail, []).append(prod_id)
    return index


def resolve_id(needle: str, closure: Closure, index: dict[str, list[str]]) -> str | None:
    """The production id anchoring `needle`, or None."""
    if needle in closure.element_ids:
        return needle
    for alias in _legacy_aliases(needle):
        matches = index.get(alias)
        if matches:
            return sorted(matches)[0]
    return None


def resolve(identifier: Identifier, closure: Closure, index: dict[str, list[str]] | None = None) -> str | None:
    """The concrete production anchor for `identifier`, or None.

    Returns the anchor rather than a boolean so the ledger can name it.
    """
    if identifier.kind == "id":
        index = index if index is not None else build_id_index(closure)
        anchor = resolve_id(identifier.needle, closure, index)
        if anchor:
            return f"#{anchor}"
        # An id can also live only in JS (created dynamically); accept a
        # quoted/selector reference in the reachable module text.
        if re.search(rf"""['"#]{re.escape(identifier.needle)}\b""", closure.text):
            return identifier.raw
        return None
    if identifier.kind == "class":
        if identifier.needle in closure.class_names or f".{identifier.needle}" in closure.text:
            return identifier.raw
        return None
    if identifier.kind == "endpoint":
        # `/drafts/:id/rewrite` is written with a placeholder the code never
        # contains; require every LITERAL segment instead, in order.
        segments = [s for s in identifier.needle.split("/") if s and not s.startswith((":", "{"))]
        if not segments:
            return None
        if all(re.search(rf"\b{re.escape(seg)}\b", closure.text) for seg in segments):
            return identifier.raw
        return None
    if identifier.kind == "symbol":
        if re.search(rf"\b{re.escape(identifier.needle)}\b", closure.text):
            return identifier.raw
        return None
    return None


# --- QA / unit coverage -----------------------------------------------------


@dataclass
class Coverage:
    """Which production-target QA scenarios and unit tests name which handles.

    Kept per FILE, not as one concatenated blob: the ledger has to name the
    concrete artifact that covers a row, or "QA coverage" is an assertion
    rather than a pointer someone can open.
    """

    qa_files: list[tuple[str, str]]  # (repo-relative path, text)
    unit_files: list[tuple[str, str]]

    @property
    def prod_qa_text(self) -> str:
        return "\n".join(text for _, text in self.qa_files)

    @property
    def unit_text(self) -> str:
        return "\n".join(text for _, text in self.unit_files)

    @property
    def prod_qa_files(self) -> list[str]:
        return [path for path, _ in self.qa_files]

    @classmethod
    def build(cls) -> "Coverage":
        qa: list[tuple[str, str]] = []
        for path in sorted(QA_DIR.glob("*.mjs")):
            if path.name == "index.mjs":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            targets = set(re.findall(r"ui:\s*'([a-z\-]+)'", text))
            # No `ui:` tag at all means the file rides the DEFAULT SCENARIO
            # target, which is `legacy` -- see app/tests/qa/run.mjs. Those
            # scenarios were written against index.html's ids and prove
            # nothing about the production page, so they are excluded.
            if targets & {t for t in PROD_QA_TARGETS if t}:
                qa.append((str(path.relative_to(ROOT)), text))
        unit = [
            (str(path.relative_to(ROOT)), path.read_text(encoding="utf-8", errors="replace"))
            for path in sorted(UNIT_DIR.glob("*.test.mjs"))
        ]
        return cls(qa, unit)

    def files_naming(self, needle: str) -> tuple[list[str], list[str]]:
        """(qa files, unit files) that mention `needle` as a whole word."""
        if not needle:
            return [], []
        pattern = re.compile(rf"\b{re.escape(needle)}\b")
        return (
            [path for path, text in self.qa_files if pattern.search(text)],
            [path for path, text in self.unit_files if pattern.search(text)],
        )


# --- per-row report ---------------------------------------------------------


@dataclass
class RowEvidence:
    stable_id: str
    section: str
    identifiers: list[Identifier]
    in_prod: list[str]
    anchors: list[str]
    not_in_prod: list[str]
    legacy_only: list[str]
    unresolvable: list[str]
    qa_hits: list[str]  # repo-relative production-target QA scenario files
    unit_hits: list[str]  # repo-relative renderer unit test files

    @property
    def anchored(self) -> bool:
        return bool(self.in_prod or self.not_in_prod or self.legacy_only)

    @property
    def fully_in_prod(self) -> bool:
        return self.anchored and not self.not_in_prod and not self.legacy_only

    @property
    def covered(self) -> bool:
        return bool(self.qa_hits or self.unit_hits)


def collect(source_rows) -> list[RowEvidence]:
    prod = Closure.build("production", PROD_ENTRY_HTML, PROD_ENTRY_JS, PROD_EXTRA_PAGES)
    legacy = Closure.build("legacy", LEGACY_ENTRY_HTML, LEGACY_ENTRY_JS)
    prod_index = build_id_index(prod)
    legacy_index = build_id_index(legacy)
    coverage = Coverage.build()

    out: list[RowEvidence] = []
    for row in source_rows:
        identifiers = extract_identifiers(row.text)
        in_prod: list[str] = []
        anchors: list[str] = []
        not_in_prod: list[str] = []
        legacy_only: list[str] = []
        unresolvable: list[str] = []
        qa_hits: list[str] = []
        unit_hits: list[str] = []

        for identifier in identifiers:
            if identifier.kind == "other":
                unresolvable.append(identifier.raw)
                continue
            anchor = resolve(identifier, prod, prod_index)
            if anchor:
                in_prod.append(identifier.raw)
                if anchor not in anchors:
                    anchors.append(anchor)
                qa_files, unit_files = coverage.files_naming(identifier.needle)
                # The production anchor is the name QA scenarios and unit tests
                # actually use (they were written against `#sdSet...`, not the
                # legacy id), so look it up under that name too.
                if anchor.startswith("#"):
                    extra_qa, extra_unit = coverage.files_naming(anchor[1:])
                    qa_files = sorted(set(qa_files) | set(extra_qa))
                    unit_files = sorted(set(unit_files) | set(extra_unit))
                for path in qa_files:
                    if path not in qa_hits:
                        qa_hits.append(path)
                for path in unit_files:
                    if path not in unit_hits:
                        unit_hits.append(path)
            elif resolve(identifier, legacy, legacy_index):
                legacy_only.append(identifier.raw)
            else:
                not_in_prod.append(identifier.raw)

        out.append(
            RowEvidence(
                stable_id=row.stable_id,
                section=row.section,
                identifiers=identifiers,
                in_prod=in_prod,
                anchors=anchors,
                not_in_prod=not_in_prod,
                legacy_only=legacy_only,
                unresolvable=unresolvable,
                qa_hits=qa_hits,
                unit_hits=unit_hits,
            )
        )
    return out


def summarize(evidence: list[RowEvidence]) -> dict:
    buckets = {
        "prod_and_covered": 0,
        "prod_uncovered": 0,
        "partial_prod": 0,
        "legacy_only": 0,
        "unanchored": 0,
    }
    per_section: dict[str, dict[str, int]] = {}
    for row in evidence:
        if not row.anchored:
            key = "unanchored"
        elif row.fully_in_prod and row.covered:
            key = "prod_and_covered"
        elif row.fully_in_prod:
            key = "prod_uncovered"
        elif row.in_prod:
            key = "partial_prod"
        else:
            key = "legacy_only"
        buckets[key] += 1
        per_section.setdefault(row.section, dict.fromkeys(buckets, 0))[key] += 1
    return {"buckets": buckets, "per_section": per_section}


def main(argv: list[str]) -> int:  # pragma: no cover - CLI
    sys.path.insert(0, str(ROOT))
    from tools import parity_validator as pv

    rows = pv.parse_source()
    evidence = collect(rows)
    summary = summarize(evidence)
    if "--json" in argv:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        for key, value in summary["buckets"].items():
            print(f"{key:20s} {value}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.exit(main(sys.argv[1:]))
