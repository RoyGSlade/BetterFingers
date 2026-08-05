#!/usr/bin/env python3
"""Regenerate docs/release/PARITY_INVENTORY.md from production evidence.

Wave 11 re-audits all 438 rows against the PRODUCTION page. Doing that by
hand would produce 438 unverifiable prose cells; doing it from a script
produces 438 cells whose every claim names a concrete artifact a reviewer can
open. The ruling is still a ruling -- the classification rule below is a
decision, and the OVERRIDES are hand judgments with stated reasons -- but the
*evidence* is collected, not asserted.

The classification rule (Wave 11, under D-0015)
-----------------------------------------------
``wired``
    Every code handle the source inventory names for this item resolves to a
    concrete anchor in the production closure (``signal-desk.html`` plus the
    modules ``bootstrap/signalDeskApp.js`` actually imports), AND at least one
    of those anchors is named by a production-target QA scenario or a renderer
    unit test. The ledger records the anchor and the covering artifact.

``intentional_cut``
    A hand ruling, always with a rationale and, where the capability survives
    in another form, a pointer to what replaced it.

``blocked``
    Everything else. The cell names WHICH handles failed to resolve and why,
    and distinguishes two very different situations, because conflating them
    would mislead the release director:

      * ``blocked (product)``  -- the item genuinely has no production
        anchor: it exists only in the legacy page, or nowhere at all.
      * ``blocked (evidence)`` -- the item IS anchored in production but the
        strict chain is not fully evidenced: no covering QA/test names it, or
        the source row is prose with no code handle to resolve at all.

    Both stay ``blocked``. The release vocabulary is not softened; the split
    exists so the BLOCKERS list can say which are gaps in the product and
    which are gaps in the audit.

Run: ``python3 tools/parity_ledger_build.py`` (writes the ledger), then
``python3 tools/parity_validator.py`` to check what it wrote.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import parity_evidence as pe  # noqa: E402
from tools import parity_validator as pv  # noqa: E402

LEDGER = ROOT / "docs/release/PARITY_INVENTORY.md"

WORKSPACE_BY_SECTION = {
    0: "Release control",
    1: "Shell / surfaces",
    2: "Onboarding",
    3: "Studio / Foundry",
    4: "Shell / header",
    5: "Shell / navigation",
    6: "Dashboard / Talk",
    7: "Settings",
    8: "Utilities / Models",
    9: "Utilities / Diagnostics",
    12: "Overlay windows",
    14: "Status / notification",
    15: "Cross-cutting / orphans",
}

# --- hand rulings ------------------------------------------------------------
#
# Every entry is a decision a script cannot make, with the reason it was made.
# `cut` entries become `intentional_cut`; `block` entries force `blocked` even
# where the mechanical evidence would have allowed `wired`.

OVERRIDES: dict[str, tuple[str, str]] = {}


def _cut(stable_id: str, rationale: str) -> None:
    OVERRIDES[stable_id] = ("intentional_cut", rationale)


def _block(stable_id: str, reason: str) -> None:
    OVERRIDES[stable_id] = ("blocked", reason)


# --- rows evidenced by a static contract test (Wave 12, director Ruling A) ----
#
# A handful of inventory rows assert a NEGATIVE property -- "no backend calls",
# "no donation prompt exists anywhere". Those have no production anchor BY
# CONSTRUCTION: you cannot point at the call that is not there. classify()
# requires an anchor, so however well evidenced such a row is it could only ever
# be reported `blocked`, which said the product was missing something when the
# truth was that the ledger had no way to express the evidence.
#
# This is that way. It is deliberately NOT a hand-claimed status: the binding is
# checked, and `verify_test_evidence()` raises if the named file stops existing
# or stops naming the row. Delete the test, rename its assertion away from the
# stable id, or move the file, and the ledger build FAILS rather than silently
# keeping a `wired` nobody is checking any more.
#
# What it does NOT do is run the test. The suite proves it passes; this proves
# the evidence still exists and still names the thing it claims to evidence.
# stable_id -> (test_path, subject_files, why). `subject_files` are the real
# production files the property is asserted OVER. They matter for two reasons:
# a negative property is only meaningful once you say what it is negative about
# ("no backend calls" -- in WHAT?), and parity_validator requires every `wired`
# row to carry a production-file evidence pointer. That rule is a good one and
# is not weakened here; the subject files satisfy it honestly.
EVIDENCED_BY_TEST: dict[str, tuple[str, tuple[str, ...], str]] = {}


class EvidenceBindingError(RuntimeError):
    """A declared test-evidence binding no longer holds."""


def _evidenced_by_test(stable_id: str, test_path: str, subject_files: tuple[str, ...], why: str) -> None:
    EVIDENCED_BY_TEST[stable_id] = (test_path, subject_files, why)


def verify_test_evidence() -> None:
    """Fail loudly on any binding whose test file is gone or no longer names the row."""
    for stable_id, (test_path, subjects, _why) in sorted(EVIDENCED_BY_TEST.items()):
        path = ROOT / test_path
        if not path.is_file():
            raise EvidenceBindingError(
                f"{stable_id} is declared evidenced by `{test_path}`, but that file does not "
                f"exist. Either restore the test or drop the declaration -- a row may not stay "
                f"`wired` on evidence that has been deleted."
            )
        if stable_id not in path.read_text(encoding="utf-8"):
            raise EvidenceBindingError(
                f"{stable_id} is declared evidenced by `{test_path}`, but that file no longer "
                f"mentions {stable_id}. The binding is what makes this auditable: the test must "
                f"name the row it evidences, so a renamed or removed assertion cannot leave a "
                f"stale `wired` behind."
            )
        if not subjects:
            raise EvidenceBindingError(
                f"{stable_id} declares no subject files. A negative property is meaningless "
                f"without saying what it is negative ABOUT."
            )
        for subject in subjects:
            if not (ROOT / subject).is_file():
                raise EvidenceBindingError(
                    f"{stable_id} asserts its property over `{subject}`, which does not exist. "
                    f"A property proved about a deleted file evidences nothing."
                )


_NEGATIVE_PROPERTY_TEST = "app/tests/negativeProperties.test.mjs"

_evidenced_by_test(
    "UI-12-008",
    _NEGATIVE_PROPERTY_TEST,
    ("app/src/renderer/overlay.html", "app/src/renderer/review-overlay.html"),
    "The overlay windows make no backend call of their own: the test asserts `overlay.html` and "
    "`review-overlay.html` contain no `fetch(`, `XMLHttpRequest`, `new WebSocket`, `EventSource` "
    "or `sendBeacon`, and pairs that absence with a POSITIVE assertion that `review-overlay.html` "
    "DOES route through `window.betterFingers.backendRequest` -- otherwise a file making no calls "
    "at all would satisfy the absence trivially. A third test feeds known violations to the same "
    "detectors so a broken detector fails loudly instead of going quietly green",
)

_evidenced_by_test(
    "UI-15-007",
    _NEGATIVE_PROPERTY_TEST,
    (
        "app/src/renderer/signal-desk.html",
        "app/src/renderer/overlay.html",
        "app/src/renderer/review-overlay.html",
    ),
    "No donation or monetisation prompt exists anywhere in the renderer: the test walks every "
    "`.js`/`.mjs`/`.html`/`.css` under `app/src/renderer` case-insensitively for donate/patreon/"
    "ko-fi/paypal/buymeacoffee/'tip jar'/gofundme/opencollective. This is STRONGER than the source "
    "row, which was hand-scoped to index.html + main.js + features/* + overlays and left the "
    "caveat 'if one exists it must live outside this scope' -- the walk settles that caveat. It "
    "asserts it visited >20 files, so an empty traversal cannot masquerade as a clean result",
)


# The four Gate 0 cuts, carried forward unchanged: the static, fixture-only
# Message Rescue example surface. Directive §§3.5/11 forbid production mock
# data, and Wave 11 removes preview pages as production targets.
for _sid in ("UI-01-012", "UI-06-064", "UI-06-065", "UI-06-066"):
    _cut(
        _sid,
        "Intentional cut: the static Message Rescue example panel is fixture-only "
        "(`#messageRescuePanel`), and directive §§3.5/11 forbid production mock data. "
        "Retained as a QA fixture only; the DRAFT-BOUND rescue panel "
        "(`features/messageRescueDraft.js`) is the shipping surface and is audited "
        "separately in §6.4.",
    )

# The four-tab strip. Signal Desk replaced it with a five-workspace rail, so
# the four tab-button ids resolve nowhere -- but navigation itself is not
# missing, and calling these rows `blocked` would report a navigation gap that
# does not exist. Cut the SURFACE, name the replacement.
_TAB_REPLACEMENT = (
    "Intentional cut: the four-tab strip (`#tabButtonDashboard`/`Settings`/`Models`/"
    "`Diagnostics`) is replaced by Signal Desk's five-workspace rail — "
    "`.sd-nav__button[data-nav]` in `app/src/renderer/signal-desk.html`, wired by "
    "`app/src/renderer/features/signalDeskShell.js`, with reachability and "
    "`aria-current` asserted for all five workspaces by "
    "`app/tests/qa/scenarios/signal-desk-prod-sweep.mjs`. The capability ships; "
    "the legacy ids deliberately do not."
)
for _sid in ("UI-01-005", "UI-05-001", "UI-05-002", "UI-05-003", "UI-05-004", "UI-05-005"):
    _cut(_sid, _TAB_REPLACEMENT)

# Wave 11B: the hand rulings that live in the shared anchor table
# (`tools/parity_anchors.py`) rather than here, because they belong next to the
# verified legacy-handle -> production-anchor mappings that justify them. A cut
# there is exactly a cut here -- same vocabulary, same requirement to name a
# replacement -- it is just recorded where the evidence for it is. The table is
# validated against the production closure before any of this runs (see
# parity_evidence.validate_anchor_table), so a cut whose named replacement has
# gone missing fails the build instead of quietly persisting.
for _sid, _rationale in pe.load_anchor_table()[2].items():
    _cut(_sid, _rationale)

# --- The overlay windows: Wave 11B blocked them, Wave 11C built the caller ----
#
# HISTORY, because the override that used to live here is the reason 21 rows read
# `blocked (product)` and deleting it silently would make the movement look like
# an accounting change rather than a fix.
#
# Wave 11 recorded the 18 unevidenced overlay rows as an AUDIT gap: the windows
# ship, so the only thing missing was QA. `app/tests/qa/scenarios/overlay-prod.mjs`
# supplied that QA -- and writing it established that the premise was wrong. On
# the production page the surfaces could not be reached at all:
#
#   * `overlay:update-status` is what makes the capture overlay show a pipeline
#     state. Its only renderer-side caller anywhere in the repo was
#     `app/src/renderer/main.js` -- the LEGACY page.
#   * `review:show` is the only thing that ever creates the review window. Same
#     single legacy caller. On the shipping page that window was never created.
#
# Wave 11B therefore forced those rows to `blocked (product)` with an override
# here, and said the fix was a production caller rather than more QA.
#
# WAVE 11C BUILT THAT CALLER, so the override is gone rather than relaxed. The
# caller is `app/src/renderer/features/overlayBridge.js`, constructed by
# `bootstrap/signalDeskApp.js` as a third consumer of the voice-status stream
# `talkWorkspace` and `talkCapture` already read: every message is forwarded to
# `overlay:update-status`, `preview_ready` opens the Review Deck through
# `review:show` with the draft the message carried, and `draft_sent` /
# `emergency_stop` put it away again. All show/hide policy stays in the main
# process, so the two pages cannot drift.
#
# These rows are now left to the MECHANICAL rules below, which is the point: an
# override that says "reachable now, trust me" would be exactly the asserted
# evidence this ledger exists to avoid. A row still has to resolve its handles in
# the production closure AND be named by a production-target QA scenario or unit
# test before it can reach `wired`, and several of them still do not.
#
# What makes the reachability claim checkable rather than asserted:
#
#   * `app/tests/qa/scenarios/overlay-prod.mjs`'s
#     `production-page-drives-both-overlay-windows` starts from a message on
#     `backend:voice-status:message` -- the exact channel `main/backendProxy.js`
#     sends on when the real WebSocket produces one -- and asserts that both
#     windows show, render the draft, and are PUT AWAY again on `draft_sent`.
#     Nothing in that path is a test-only call.
#   * `app/tests/overlayBridge.test.mjs` covers the mapping and, deliberately at
#     the same weight, every hide path: a surface that fails to release is worse
#     than one that never appeared.
#
# If the director's Electron QA run of `overlay-windows` does not go green, this
# reachability claim is not established and these rows must go back to `blocked`.

# NOT ledger rows, deliberately: two Wave 11 rulings the brief asked for have
# no counterpart in the 438-item source inventory, because that inventory
# predates the work they concern.
#
#   * the legacy index.html Privacy section vs the five Wave 6 groups (D-0028);
#   * the D-0029 `unavailable` dispatcher actions (command.begin/end,
#     activate_persona, activate_writing_preset).
#
# Inventing ledger rows for them would break the 1:1 source binding that makes
# this ledger checkable. Both are ruled on in
# docs/release/WAVE11_BLOCKERS.md instead, where they can be read as the
# decisions they are rather than smuggled in as parity rows.


def cell_safe(text: str) -> str:
    """`text` made safe to put in a Markdown table cell.

    A pipe becomes `&#124;` rather than `\\|`. Markdown renders both as a bar,
    but the ledger is parsed by splitting rows on `|` (parity_validator), and a
    backslash-escaped pipe still splits — which is how a hand-written anchor
    rationale containing `POST /wake/enable | POST /wake/disable` produced an
    8-cell row and broke the validator outright. The entity carries no literal
    pipe, so the row survives the round trip with its meaning intact.
    """
    return text.replace("|", "&#124;").replace("\n", " ")


def build_evidence_cell(row: pe.RowEvidence, status: str, reason: str) -> str:
    parts: list[str] = []
    if row.stable_id in EVIDENCED_BY_TEST:
        test_path, subjects, why = EVIDENCED_BY_TEST[row.stable_id]
        parts.append(
            "Property asserted over: " + ", ".join(f"`{path}`" for path in subjects)
        )
        # Stated as its own kind of evidence rather than dressed up as an
        # anchor, because it is not one: this row asserts an ABSENCE, which has
        # no production location by construction. The binding to the test file
        # is verified by verify_test_evidence() on every build.
        parts.append(
            f"Evidenced by static contract test (`{test_path}`, binding checked on every "
            f"ledger build): {why}"
        )
    if row.anchors:
        shown = ", ".join(f"`{anchor}`" for anchor in row.anchors[:6])
        more = "" if len(row.anchors) <= 6 else f" (+{len(row.anchors) - 6} more)"
        parts.append(f"Production anchor(s): {shown}{more} in `app/src/renderer/signal-desk.html`")
    if row.declared:
        # Say out loud that a human put this anchor here and why. A declared
        # anchor carries the same weight as a derived one ONLY because it was
        # checked against the production closure; printing it unlabelled would
        # hide which half of the ledger rests on a person's verified claim.
        shown = ", ".join(f"`{item}`" for item in row.declared[:4])
        parts.append(
            f"Hand-declared anchor(s) (`tools/parity_anchors.py`): {shown} — {row.declared_why}"
        )
    if row.qa_hits:
        parts.append(
            "Production-target QA: " + ", ".join(f"`{path}`" for path in row.qa_hits[:3])
        )
    if row.unit_hits:
        parts.append("Unit coverage: " + ", ".join(f"`{path}`" for path in row.unit_hits[:3]))
    if row.legacy_only:
        parts.append(
            "Legacy-only handle(s): " + ", ".join(f"`{tok}`" for tok in row.legacy_only[:6])
        )
    if row.not_in_prod:
        parts.append("Unresolved handle(s): " + ", ".join(f"`{tok}`" for tok in row.not_in_prod[:6]))
    if status == "blocked":
        parts.append(f"Blocked: {reason}")
    return cell_safe(". ".join(parts))


def classify(row: pe.RowEvidence) -> tuple[str, str]:
    if row.stable_id in OVERRIDES:
        status, text = OVERRIDES[row.stable_id]
        return status, text
    # Checked by verify_test_evidence() before any row is classified, so this
    # can never be a bare assertion: the named test exists and names this row.
    if row.stable_id in EVIDENCED_BY_TEST:
        return ("wired", "")
    if not row.anchored:
        return (
            "blocked",
            "(evidence) the source row states no code handle, so no production anchor "
            "can be resolved mechanically; it needs a named production location before "
            "it can be ruled on",
        )
    if row.legacy_only and not row.in_prod:
        return (
            "blocked",
            "(product) every handle resolves only in the legacy `index.html` closure, "
            "never in the production composition root",
        )
    if row.not_in_prod and not row.in_prod:
        return (
            "blocked",
            "(product) no handle resolves in either closure; the item may no longer exist",
        )
    if row.legacy_only or row.not_in_prod:
        return (
            "blocked",
            "(product) partially anchored — some handles resolve in production and some "
            "do not, so the item is not wholly present on the shipping page",
        )
    if not row.covered:
        return (
            "blocked",
            "(evidence) fully anchored in production but no production-target QA scenario "
            "or renderer unit test names any of its anchors, so the D-0015 QA leg is unmet",
        )
    return ("wired", "")


def main() -> int:
    # Before anything is classified: a test-evidence binding that no longer
    # holds must stop the build, not quietly produce a `wired` row resting on a
    # deleted assertion.
    verify_test_evidence()

    source_rows = pv.parse_source()
    evidence = {row.stable_id: row for row in pe.collect(source_rows)}

    rulings: list[tuple[pv.SourceRow, pe.RowEvidence, str, str]] = []
    for src in source_rows:
        ev = evidence[src.stable_id]
        status, reason = classify(ev)
        rulings.append((src, ev, status, reason))

    totals = defaultdict(int)
    by_section: dict[str, list[int]] = {}
    by_workspace: dict[str, list[int]] = {}
    lines: list[str] = []

    for src, ev, status, reason in rulings:
        totals[status] += 1
        workspace = WORKSPACE_BY_SECTION.get(src.section_number, "Cross-cutting / orphans")
        cell = cell_safe(reason) if status == "intentional_cut" else build_evidence_cell(ev, status, reason)
        item = src.text
        if len(item) > 150:
            item = item[:149].rstrip() + "…"
        item = cell_safe(item)
        lines.append(
            f"| {src.stable_id} | {workspace} | {src.source_ref} | {item} | {cell} | "
            f"`sha256:{src.binding}` | `{status}` |"
        )
        for table, key in ((by_section, src.section), (by_workspace, workspace)):
            bucket = table.setdefault(key, [0, 0, 0, 0])
            index = {"wired": 0, "intentional_cut": 1, "blocked": 2}[status]
            bucket[index] += 1
            bucket[3] += 1

    # Hash the logical UTF-8 source, not platform-specific checkout bytes.
    # ``Path.read_text`` applies universal-newline normalization, so the audit
    # binding remains identical when Git checks the inventory out as CRLF on
    # Windows and LF on Linux.
    source_sha = pv.hashlib.sha256(
        (ROOT / "docs/ui/CURRENT_UI_INVENTORY.md")
        .read_text(encoding="utf-8")
        .encode("utf-8")
    ).hexdigest()

    header = f"""# BetterFingers 438-item release parity inventory

- **Authority:** `docs/ui/CURRENT_UI_INVENTORY.md` (all Markdown checklist entries).
- **Source SHA-256 at audit:** `{source_sha}`.
- **Audit posture:** Wave 11 strict re-audit against the PRODUCTION page
  (`app/src/renderer/signal-desk.html`), 2026-07-28. This is an evidence ledger, not a
  claim that Gate 11 has passed — that is the release director's ruling.
- **Status vocabulary:** `wired`, `intentional_cut`, `blocked` only.
- **Regenerate:** `python3 tools/parity_ledger_build.py`; **check:** `python3 tools/parity_validator.py`
  (also enforced by `tests/test_parity_inventory.py`).

## Release-status rule

`wired` requires the full Wave 11 chain: a reachable production Signal Desk location, a real
data source, a real action handler where the item is actionable, a user-visible failure state,
keyboard/accessibility evidence, QA coverage, and privacy review. Wave 11 evidences that chain
mechanically wherever it can: every code handle the source inventory names for a row is resolved
against the **production closure** — `signal-desk.html` plus the module graph
`bootstrap/signalDeskApp.js` actually imports — and against production-target QA scenarios and
renderer unit tests. A row is `wired` only when every handle resolves in production **and** at
least one covering QA scenario or unit test names one of those anchors. The ledger records the
concrete anchor, so every promotion is checkable rather than asserted.

Signal Desk renamed the legacy element ids: `#exportProfileButton` became
`#sdSetExportProfileButton`, `#settingRecordingMode` became `#sdSetRecordingMode`. That mapping is
not inferred — it is written out in `app/src/renderer/features/settingsWorkspace.js`'s
`SETTINGS_ELEMENT_IDS` and its sibling `collect*Elements()` maps — so resolving a legacy id to its
namespaced production id is a real resolution. It is still only ever a *candidate anchor*: the row
must also clear the coverage leg, and the anchor it matched is printed in the cell.

### What this ledger does and does not verify per row

Stated plainly, so `wired` is not read as more than it is. Verified **per row**,
mechanically, with the anchor printed: the production location, that the item's named
handlers/endpoints resolve inside the production closure, and that a production-target QA
scenario or renderer unit test names one of its anchors.

Verified **per workspace, not per row**: the failure-state, keyboard/accessibility and
privacy legs. Those rest on the accepted gate evidence for the workspace the row lives in —
Gates 1-10 (D-0019 through D-0029) each reviewed those properties for the surfaces they
landed, and the production sweep asserts `aria-current` on the workspace rail and zero
console errors across every section. No per-row accessibility audit was performed.

A row marked `wired` therefore means: *this item is anchored in the shipping page, its
handlers resolve there, and something exercises it* — inside a workspace whose failure and
accessibility behaviour was accepted at its gate. It does not mean an individual
accessibility pass was run on that control. Anyone reading this ledger to decide Gate 11
should read that sentence as the actual claim.

The legacy catalog and the five preview placement maps remain discovery evidence only. Nothing is
promoted because a legacy handler exists; the legacy closure is consulted solely so a row can be
reported as legacy-only, which is a reason to stay `blocked` or to be cut — never a reason to pass.

### Why `blocked` still has two meanings

The release vocabulary is exactly three words and Wave 11 does not soften it. But `blocked` is
carrying two very different situations, and the BLOCKERS list separates them:

- **`blocked (product)`** — the item has no production anchor. It lives only in `index.html`, or
  nowhere. This is a gap in the product.
- **`blocked (evidence)`** — the item IS anchored in production, but the strict chain is not fully
  evidenced: either no QA scenario or unit test names its anchors, or the source row is prose with
  no code handle for the collector to resolve at all. This is a gap in the audit.

Both ship as `blocked`. Reporting them as one number would tell the director that the product is
missing things it is not missing, which is the mirror image of a victory lap and equally useless.

## Exact totals

| Status | Count |
|---|---:|
| `wired` | {totals['wired']} |
| `intentional_cut` | {totals['intentional_cut']} |
| `blocked` | {totals['blocked']} |
| **Total** | **{sum(totals.values())}** |

### Totals by source section (section index)

| Source section | Wired | Intentional cut | Blocked | Total |
|---|---:|---:|---:|---:|
"""
    for key in sorted(by_section, key=lambda k: int(k.split()[0].lstrip("§"))):
        w, c, b, t = by_section[key]
        header += f"| {key} | {w} | {c} | {b} | {t} |\n"

    header += """
Source §§10, 11, and 13 have zero ledger rows because they contain reference tables rather
than Markdown checkboxes. Section 16 is the source inventory's totals summary and likewise has
no checkbox row.

### Totals by release workspace

| Workspace | Wired | Intentional cut | Blocked | Total |
|---|---:|---:|---:|---:|
"""
    for key in sorted(by_workspace):
        w, c, b, t = by_workspace[key]
        header += f"| {key} | {w} | {c} | {b} | {t} |\n"

    header += """
## Ledger

| Stable ID | Workspace | Source | Concise item | Production/data/action evidence and decision | Source binding | Status |
|---|---|---|---|---|---|---|
"""

    LEDGER.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    try:
        where = LEDGER.relative_to(ROOT)
    except ValueError:  # a test regenerating into a temp dir
        where = LEDGER
    print(
        f"wrote {where}: {totals['wired']} wired / "
        f"{totals['intentional_cut']} intentional_cut / {totals['blocked']} blocked"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    sys.exit(main())
