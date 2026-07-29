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


# --- the human anchor table (Wave 11B) --------------------------------------
#
# This module's docstring has always promised an ``ANCHORS`` escape hatch for
# rows the mechanical rules cannot follow, and until Wave 11B it did not exist.
# Two real defects need it, and neither is fixable by loosening the matcher:
#
#   * a workspace MOVE. The namespace rule below strips ONE `sd<workspace>`
#     token, so it follows a rename inside a workspace (`#settingRecordingMode`
#     -> `#sdSetRecordingMode`) but cannot follow a control that moved to a
#     different workspace on the way (`#settingHotkey` ->
#     `#sdUtilHotkeyRecordingInput`). Widening the tail match to cover that
#     would let unrelated ids collide, which is how an audit starts lying.
#   * a PROSE row. `App shell header — logo/title/tagline + Quit button` names
#     no handle at all, so there is nothing to resolve however clever the rule.
#
# The answer to both is a human naming the concrete production element, with
# the reason, in a data-only table -- `tools/parity_anchors.py`. A declared
# anchor is a claim about a specific production element, so it is CHECKED:
# `validate_anchor_table()` below fails loudly if a declared anchor is not in
# the production closure, if a declared legacy handle already resolves on its
# own (a redundant mapping is a mapping nobody re-derived), or if a row anchor
# is attached to a row that was never unanchored. A table that silently rots
# would be worse than no table.
#
# The module is imported optionally so this collector still runs in a checkout
# that does not have it yet. Once it is present, every rule above is hard.

ANCHOR_SCHEMA_VERSION = 1


class AnchorError(RuntimeError):
    """A declared anchor does not hold against the production closure."""


ANCHOR_MODULE = Path(__file__).with_name("parity_anchors.py")


def load_anchor_table():
    """`tools.parity_anchors` as (handle_anchors, row_anchors, cuts).

    A table that is ABSENT FROM DISK yields three empty dicts, so this collector
    still runs in a checkout that predates it. A table that is on disk but fails
    to import is an ERROR, not an empty.

    That distinction is not hypothetical. While this was still a bare
    `except ImportError: return {}, {}, {}`, a regeneration that happened to land
    during another session's atomic rewrite of the module read it as absent and
    produced a ledger 60 rows lighter — no warning, no failure, a clean-looking
    file with the wrong numbers in it. The ledger is only checkable if the
    difference between "there is no table" and "the table did not load" is
    visible.
    """
    try:
        from tools import parity_anchors as pa  # noqa: PLC0415 - optional dependency
    except ImportError:
        if ANCHOR_MODULE.exists():
            raise AnchorError(
                f"{ANCHOR_MODULE} exists but could not be imported. Refusing to regenerate from an "
                "empty anchor table — that silently drops every hand-declared anchor and cut."
            ) from None
        return {}, {}, {}

    declared = getattr(pa, "SCHEMA_VERSION", None)
    if declared != ANCHOR_SCHEMA_VERSION:
        raise AnchorError(
            f"tools/parity_anchors.py declares SCHEMA_VERSION={declared!r}, but this collector "
            f"speaks {ANCHOR_SCHEMA_VERSION}. Reconcile the two rather than guessing."
        )
    return (
        dict(getattr(pa, "HANDLE_ANCHORS", {})),
        dict(getattr(pa, "ROW_ANCHORS", {})),
        dict(getattr(pa, "CUTS", {})),
    )

# The only QA target that exercises the production composition root.
#
# `signal-desk` is the mockup preview and is pinned there by D-0007. Untagged
# scenarios are NOT included either, even though the Wave 11 flip made the
# production page the default RUN target: untagged scenarios belong to the
# `legacy` target (app/tests/qa/run.mjs's DEFAULT_SCENARIO_UI), because they
# were written against index.html's ids. Counting them would credit the
# production page with coverage that never touches it.
PROD_QA_TARGETS = {"signal-desk-prod"}

# --- comments are not evidence (Wave 11B) ------------------------------------
#
# The collector resolves an id by looking for it anywhere in reachable source.
# Until this was fixed, "anywhere" included COMMENTS -- so a module that merely
# mentioned `#backendStatus` while explaining what replaced it was enough to make
# that row resolve in production, and the row could then reach `wired` on a
# sentence. That does not merely under-report; it silently INFLATES the wired
# count, which is the one number this gate exists to make trustworthy.
#
# So every file is stripped of its comments before anything is matched against
# it -- markup, module source, QA scenarios and unit tests alike. Only real
# markup and real code can anchor a row or cover one. Stripping replaces each
# comment with a space rather than deleting it, so nothing on either side of a
# comment is accidentally joined into a new token.

HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
SCRIPT_BLOCK_RE = re.compile(r"(<script\b[^>]*>)(.*?)(</script>)", re.DOTALL | re.IGNORECASE)


_REGEX_PRECEDING_KEYWORDS = frozenset({
    "return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
    "case", "do", "else", "yield", "await", "throw",
})


def _regex_allowed(emitted: list[str]) -> bool:
    """Whether a `/` at this point opens a regex literal rather than divides.

    Decided from what was emitted before it: nothing (start of file), an
    operator or opening bracket, or a keyword that can precede a value. After
    an identifier, number, `)` or `]` a slash is division.
    """
    k = len(emitted) - 1
    while k >= 0 and emitted[k].strip() == "":
        k -= 1
    if k < 0:
        return True
    prev = emitted[k][-1:]
    if prev in "(,=:[!&|?{};+-*%~^<>":
        return True
    if not (prev.isalnum() or prev in "_$)]"):
        return True
    word = ""
    while k >= 0 and (emitted[k][-1:].isalnum() or emitted[k][-1:] in "_$"):
        word = emitted[k][-1:] + word
        k -= 1
    return word in _REGEX_PRECEDING_KEYWORDS


def strip_js_comments(text: str) -> str:
    """`text` with // and /* */ comments blanked, string literals preserved.

    A hand-written scanner rather than a regex because the two things that must
    not be confused -- `//` starting a comment and `//` inside `"https://..."` --
    are indistinguishable without tracking string state. Quotes, apostrophes in
    template literals and escapes are all handled.

    REGEX LITERALS ARE TRACKED TOO, and that is not a nicety. A literal like
    `.replace(/[&<>"']/g, ...)` carries a `"` and a `'` inside its character
    class. Without regex tracking those open a phantom string that closes at
    the next matching quote somewhere further down the file, and every comment
    in between survives stripping -- which put the comment hole straight back
    (a row claimed `#sendActionSelect` shipped when the id existed only in a
    comment). Five files in the production closure carry that exact
    escape-HTML regex, the composition root among them, so this was not an
    edge case.

    A `/` opens a regex only in expression position: at the start of input,
    after an operator or opening bracket, or after a keyword that can precede
    a value. After an identifier, a number, or a closing bracket it is
    division. Inside the literal, a `/` within `[...]` does not close it.
    """
    out: list[str] = []
    i = 0
    length = len(text)
    quote: str | None = None
    while i < length:
        char = text[i]
        if quote:
            out.append(char)
            if char == "\\" and i + 1 < length:
                out.append(text[i + 1])
                i += 2
                continue
            if char == quote:
                quote = None
            i += 1
            continue
        if char in "\"'`":
            quote = char
            out.append(char)
            i += 1
            continue
        if char == "/" and i + 1 < length and text[i + 1] not in "/*" and _regex_allowed(out):
            # A regex literal: copy it verbatim so its contents cannot be
            # mistaken for string or comment syntax.
            j = i + 1
            in_class = False
            while j < length:
                cur = text[j]
                if cur == "\\":
                    j += 2
                    continue
                if cur == "[":
                    in_class = True
                elif cur == "]":
                    in_class = False
                elif cur == "/" and not in_class:
                    j += 1
                    break
                elif cur == "\n":
                    # An unterminated literal is not a regex after all; bail out
                    # and let the ordinary scanner have the character.
                    j = i
                    break
                j += 1
            if j > i:
                out.append(text[i:j])
                i = j
                continue
        if char == "/" and i + 1 < length:
            nxt = text[i + 1]
            if nxt == "/":
                end = text.find("\n", i)
                end = length if end == -1 else end
                out.append(" " * (end - i))
                i = end
                continue
            if nxt == "*":
                end = text.find("*/", i + 2)
                end = length if end == -1 else end + 2
                # Keep newlines so line-based tooling and error messages that
                # index into this text stay aligned with the original file.
                out.append("".join("\n" if c == "\n" else " " for c in text[i:end]))
                i = end
                continue
        out.append(char)
        i += 1
    return "".join(out)


def strip_comments(path: Path, text: str) -> str:
    """`text` with comments blanked, dispatched on file type.

    HTML is handled precisely rather than by running the JS scanner over the
    whole document: prose apostrophes ("the user's draft") would open a string
    that never closes and swallow the rest of the page. So HTML comments are
    removed by pattern, and the JS scanner is applied only inside <script>
    blocks, where quoting really is JavaScript quoting.
    """
    if path.suffix in (".html", ".htm"):
        text = HTML_COMMENT_RE.sub(
            lambda m: "".join("\n" if c == "\n" else " " for c in m.group(0)), text
        )
        return SCRIPT_BLOCK_RE.sub(
            lambda m: m.group(1) + strip_js_comments(m.group(2)) + m.group(3), text
        )
    return strip_js_comments(text)


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
        # Stripped, so a commented-out <script src> cannot drag a file that is
        # not in the product into the production closure.
        html = strip_comments(entry_html, entry_html.read_text(encoding="utf-8", errors="replace"))
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
            text = strip_comments(current, current.read_text(encoding="utf-8", errors="replace"))
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
                text = strip_comments(path, path.read_text(encoding="utf-8", errors="replace"))
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


def _legacy_aliases(legacy_id: str) -> list[str]:
    """Aliases to try, MOST SPECIFIC FIRST and in a stable order.

    This returns a list, not a set, and the order is load-bearing. When more
    than one alias resolves, whichever is tried first becomes the anchor the
    ledger prints -- so a set here made the generated file depend on the
    interpreter's hash seed: `#onboardingTitle` cited `#sdOnboardingTitle` in
    one process and `#sdHeaderTitle` in the next, from identical sources. A
    gate artifact that does not reproduce byte-for-byte cannot be audited, and
    the staleness test that guards it becomes a coin flip.

    The full id is tried before any prefix-stripped tail, because the longer
    name is the more specific claim; ties among tails are broken by the
    LEGACY_DROPPED_PREFIXES order, and `resolve_id` already sorts the matches
    within one alias.
    """
    lower = legacy_id.lower()
    out = [lower]
    for prefix in LEGACY_DROPPED_PREFIXES:
        if lower.startswith(prefix) and len(lower) > len(prefix):
            tail = lower[len(prefix):]
            if tail not in out:
                out.append(tail)
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


# --- the id-in-JS rule (Wave 12, D-0034 / director Ruling B) ------------------
#
# This used to accept ANY quoted or selector-shaped mention of an id anywhere in
# the reachable module text:
#
#     re.search(rf'''['"#]{needle}\b''', closure.text)
#
# which meant `document.getElementById('draftConfidence')` in a features/*.js
# module counted as production evidence that `#draftConfidence` SHIPS. It does
# not. A lookup is evidence that something LOOKS FOR an element; only the markup
# (or JS that builds it) is evidence the element exists. The ledger then printed
# the location as `signal-desk.html`, turning "a user can see this" into "this
# string appears somewhere in the renderer".
#
# UI-15-001 proved the rule wrong by design rather than by accident:
# features/studioWorkspace.js documents that Studio's teach panel deliberately
# uses distinct `sdTeach*` ids SO THAT personaLearning.js's self-init IIFE --
# which queries `#personaLearningSection` -- never matches. That guarantees
# `#personaLearningSection` exists in no page at all, and the old rule still
# reported it as a production anchor.
#
# The fix is not to drop JS-created ids wholesale: some elements really are
# built at runtime and never appear in markup, and un-anchoring those would
# swap one false report for another. The distinction that matters is CREATION
# vs LOOKUP.
_ID_CREATION_PATTERNS = (
    # el.id = 'name'
    r"""\.id\s*=\s*['"]{needle}['"]""",
    # setAttribute('id', 'name')
    r"""setAttribute\(\s*['"]id['"]\s*,\s*['"]{needle}['"]""",
    # id="name" / id='name' written inside a JS string or template literal
    # (innerHTML / insertAdjacentHTML markup built in JS)
    r"""id=\\?['"]{needle}\\?['"]""",
)

# Lookups, listed only to document what deliberately does NOT count:
#   getElementById('name'), querySelector('#name'), closest('#name'),
#   matches('#name'), getElementById(`name`)


def js_creates_id(needle: str, text: str) -> bool:
    """True when the reachable JS BUILDS an element carrying `needle` as its id.

    Deliberately narrow. A false positive here fabricates production evidence,
    which is the failure this function exists to stop; a false negative merely
    sends a genuinely-dynamic row back for a hand-declared anchor, which is
    auditable.
    """
    escaped = re.escape(needle)
    return any(
        re.search(pattern.replace("{needle}", escaped), text)
        for pattern in _ID_CREATION_PATTERNS
    )


def resolve(identifier: Identifier, closure: Closure, index: dict[str, list[str]] | None = None) -> str | None:
    """The concrete production anchor for `identifier`, or None.

    Returns the anchor rather than a boolean so the ledger can name it.
    """
    if identifier.kind == "id":
        index = index if index is not None else build_id_index(closure)
        anchor = resolve_id(identifier.needle, closure, index)
        if anchor:
            return f"#{anchor}"
        # An id can also live only in JS -- but only when the JS CREATES it.
        # See js_creates_id() for why a lookup no longer counts.
        if js_creates_id(identifier.needle, closure.text):
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


def anchor_identifier(anchor: str) -> Identifier | None:
    """A hand-DECLARED anchor string parsed as if the inventory had written it.

    Declared anchors are written the way the inventory writes handles
    (`#sdUtilHotkeyRecordingInput`, `.sd-nav__button`, `GET /wake/status`,
    `applyAppearance`), so they go through the same extractor and the same
    resolver. Nothing about being hand-written earns a looser check -- if
    anything the opposite, since there is no source row backing it up.
    """
    identifiers = extract_identifiers(f"`{anchor}`")
    if len(identifiers) != 1 or identifiers[0].kind == "other":
        return None
    return identifiers[0]


def resolve_anchor_text(anchor: str, closure: Closure, index: dict[str, list[str]]) -> str | None:
    identifier = anchor_identifier(anchor)
    return None if identifier is None else resolve(identifier, closure, index)


def validate_anchor_table(handle_anchors, row_anchors, cuts, prod, prod_index, source_ids):
    """Fail loudly on any declared anchor that does not hold.

    Six ways a table can lie, all of them fatal:

      1. a declared production anchor that is not in the production closure --
         the whole point of the table is to name something real;
      2. a legacy handle that ALREADY resolves in production -- the mapping is
         then either redundant or, worse, redirecting a row away from the
         anchor the collector found on its own;
      3. a row anchor keyed to a stable id the source inventory does not have;
      4. a cut keyed to a stable id the source inventory does not have;
      5. an entry with no stated reason -- an unexplained anchor is an
         assertion, which is the thing this ledger exists to avoid;
      6. the same stable id claimed by both ROW_ANCHORS and CUTS, which would
         make the ruling depend on evaluation order.
    """
    problems: list[str] = []

    for handle, entry in sorted(handle_anchors.items()):
        anchor = (entry or {}).get("anchor", "")
        why = (entry or {}).get("why", "")
        if not why.strip():
            problems.append(f"HANDLE_ANCHORS[{handle!r}] states no reason")
        if not anchor:
            problems.append(f"HANDLE_ANCHORS[{handle!r}] declares no anchor")
            continue
        if resolve_anchor_text(anchor, prod, prod_index) is None:
            problems.append(
                f"HANDLE_ANCHORS[{handle!r}] -> {anchor!r} does not resolve in the production closure"
            )
        if resolve_anchor_text(handle, prod, prod_index) is not None:
            problems.append(
                f"HANDLE_ANCHORS[{handle!r}] is redundant: that handle already resolves in production"
            )

    for stable_id, entry in sorted(row_anchors.items()):
        if stable_id not in source_ids:
            problems.append(f"ROW_ANCHORS[{stable_id!r}] is not a source inventory row")
        if stable_id in cuts:
            problems.append(f"{stable_id!r} is claimed by both ROW_ANCHORS and CUTS")
        why = (entry or {}).get("why", "")
        anchors = list((entry or {}).get("anchors", []))
        if not why.strip():
            problems.append(f"ROW_ANCHORS[{stable_id!r}] states no reason")
        if not anchors:
            problems.append(f"ROW_ANCHORS[{stable_id!r}] declares no anchors")
        for anchor in anchors:
            if resolve_anchor_text(anchor, prod, prod_index) is None:
                problems.append(
                    f"ROW_ANCHORS[{stable_id!r}] -> {anchor!r} does not resolve in the production closure"
                )

    for stable_id, rationale in sorted(cuts.items()):
        if stable_id not in source_ids:
            problems.append(f"CUTS[{stable_id!r}] is not a source inventory row")
        if not str(rationale or "").strip():
            problems.append(f"CUTS[{stable_id!r}] states no rationale")

    if problems:
        raise AnchorError(
            "tools/parity_anchors.py declares anchors that do not hold:\n  - "
            + "\n  - ".join(problems)
        )


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
            # Same rule as the closure: a scenario that only MENTIONS a control
            # in its header comment does not exercise it, and must not be
            # reported as covering it.
            text = strip_comments(path, path.read_text(encoding="utf-8", errors="replace"))
            targets = set(re.findall(r"ui:\s*'([a-z\-]+)'", text))
            # No `ui:` tag at all means the file rides the DEFAULT SCENARIO
            # target, which is `legacy` -- see app/tests/qa/run.mjs. Those
            # scenarios were written against index.html's ids and prove
            # nothing about the production page, so they are excluded.
            if targets & {t for t in PROD_QA_TARGETS if t}:
                qa.append((str(path.relative_to(ROOT)), text))
        unit = [
            (
                str(path.relative_to(ROOT)),
                strip_comments(path, path.read_text(encoding="utf-8", errors="replace")),
            )
            for path in sorted(UNIT_DIR.glob("*.test.mjs"))
        ]
        return cls(qa, unit)

    def files_naming(self, needle: str) -> tuple[list[str], list[str]]:
        """(qa files, unit files) that mention `needle` as a whole token.

        Boundaries are lookarounds rather than `\\b`, because `\\b` silently
        could not match an ENDPOINT needle at all. `\\b` asserts a word/non-word
        transition, so `\\b/personas/interview/answer` requires a word character
        immediately before the leading slash -- and a QA stub writes it as
        `'POST /personas/interview/answer'`, where the slash is preceded by a
        space. Every endpoint row was therefore reported as uncovered no matter
        how thoroughly a scenario exercised it, which is the same defect as the
        comment hole pointing the other way: it under-reported instead of
        inflating, and it was just as invisible.

        The lookarounds are no looser than `\\b` for identifier needles -- they
        additionally refuse a `/` neighbour, so `answer` still does not match
        inside `/answers` or `foundryAnswer`.
        """
        if not needle:
            return [], []
        pattern = re.compile(rf"(?<![A-Za-z0-9_/]){re.escape(needle)}(?![A-Za-z0-9_/])")
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
    # Anchors this row got from tools/parity_anchors.py rather than from its own
    # text, kept separate so the ledger can say so out loud: a hand-declared
    # anchor is a human's verified claim, not something the collector derived.
    declared: list[str] = field(default_factory=list)
    declared_why: str = ""

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

    handle_anchors, row_anchors, cuts = load_anchor_table()
    validate_anchor_table(
        handle_anchors,
        row_anchors,
        cuts,
        prod,
        prod_index,
        {row.stable_id for row in source_rows},
    )

    def credit(anchor: str, needle: str, anchors, qa_hits, unit_hits) -> None:
        """Record `anchor` and everything that names it, once."""
        if anchor not in anchors:
            anchors.append(anchor)
        qa_files, unit_files = coverage.files_naming(needle)
        # The production anchor is the name QA scenarios and unit tests
        # actually use (they were written against `#sdSet...`, not the
        # legacy id), so look it up under that name too.
        if anchor.startswith(("#", ".")):
            extra_qa, extra_unit = coverage.files_naming(anchor[1:])
            qa_files = sorted(set(qa_files) | set(extra_qa))
            unit_files = sorted(set(unit_files) | set(extra_unit))
        for path in qa_files:
            if path not in qa_hits:
                qa_hits.append(path)
        for path in unit_files:
            if path not in unit_hits:
                unit_hits.append(path)

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
        declared: list[str] = []
        declared_why = ""

        for identifier in identifiers:
            if identifier.kind == "other":
                unresolvable.append(identifier.raw)
                continue
            anchor = resolve(identifier, prod, prod_index)
            if anchor is None and identifier.raw in handle_anchors:
                # A control that MOVED workspace: the tail rule cannot follow it,
                # a human verified where it went. Credited as production, and the
                # ledger prints which handle was redirected where.
                entry = handle_anchors[identifier.raw]
                anchor = resolve_anchor_text(entry["anchor"], prod, prod_index)
                if anchor and entry["anchor"] not in declared:
                    declared.append(f"{identifier.raw} → {entry['anchor']}")
                    declared_why = declared_why or entry["why"]
            if anchor:
                in_prod.append(identifier.raw)
                credit(anchor, identifier.needle, anchors, qa_hits, unit_hits)
            elif resolve(identifier, legacy, legacy_index):
                legacy_only.append(identifier.raw)
            else:
                not_in_prod.append(identifier.raw)

        # Prose rows: the source names no handle, so a human named the
        # production element instead. Only ever applied to a row the collector
        # could not anchor by itself -- a declared anchor on a row that already
        # resolved would be overriding real evidence with an assertion, which
        # is a table bug, not a ruling.
        if row.stable_id in row_anchors:
            entry = row_anchors[row.stable_id]
            if in_prod:
                raise AnchorError(
                    f"ROW_ANCHORS[{row.stable_id!r}] is declared, but that row already resolves "
                    f"in production on its own ({', '.join(anchors)}). Remove the declaration."
                )
            declared_why = entry["why"]
            for declared_anchor in entry["anchors"]:
                identifier = anchor_identifier(declared_anchor)
                resolved = resolve(identifier, prod, prod_index)
                declared.append(declared_anchor)
                in_prod.append(declared_anchor)
                credit(resolved, identifier.needle, anchors, qa_hits, unit_hits)

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
                declared=declared,
                declared_why=declared_why,
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
