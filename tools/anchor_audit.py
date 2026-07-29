#!/usr/bin/env python3
"""Do the parity ledger's production-anchor claims actually hold?

Motivated by a concrete falsehood found while executing the Wave 12 C-6 ruling
(see docs/release/DECISIONS.md D-0032). Rows UI-06-021 and UI-14-007 both read:

    Production anchor(s): `#draftConfidence` in `app/src/renderer/signal-desk.html`

`#draftConfidence` occurs zero times in that file. The id resolved only through
the ledger's "an id may live in JS" fallback -- matching
`features/drafts.js`'s `getElementById('draftConfidence')` -- and the ledger
then reported the LOCATION as the production page rather than as the JS file
the fallback actually matched. That turns "this element ships on the page a
user sees" into "this string exists somewhere in the renderer", which is a
materially weaker claim wearing the stronger one's clothes.

tools/parity_validator.py deliberately does not catch this: it checks the
ledger is internally consistent and bound to the source inventory, not that
each prose anchor claim is true against the page. This script checks the claim.

It is a REPORT, not a gate. A token flagged here is not automatically a lie --
see the caveats on `probe_for()` -- it is a row whose evidence a human should
re-read before it is counted as production evidence.

Usage:  python3 tools/anchor_audit.py
Exit:   0 always (report-only, so it never blocks a release run on its own).
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs/release/PARITY_INVENTORY.md"
PAGE = ROOT / "app/src/renderer/signal-desk.html"

# The audit half only ever asks about the dashboard's own claims.
CLAIM_RE = re.compile(
    r"Production anchor\(s\): (.+?) in `app/src/renderer/signal-desk\.html`"
)
# The --fix half must match a claim naming ANY production file, not just the
# dashboard, so that re-running is idempotent AND can correct a location this
# tool itself previously got wrong. Captured up to the end of the sentence
# (". " + capital, e.g. ". Unit coverage:") or the end of the table cell.
ANY_CLAIM_RE = re.compile(
    r"Production anchor\(s\): (.+?)(?=\. [A-Z]|\s*\|)"
)
TOKEN_RE = re.compile(r"`([^`]+)`")
HTTP_VERBS = ("GET ", "POST ", "PUT ", "DELETE ", "PATCH ")

# HTML files only. A `#id` or `.class` is anchored where the ELEMENT is
# declared -- never in the JavaScript that happens to mention the string.
#
# This distinction is the entire point of the audit and it was worth learning
# twice: the first --fix pass attributed `#personaLearningSection` to
# features/personaLearning.js and `#draftRawText` to talkDrafts.js purely
# because those files call getElementById with those names. That is exactly
# the JS-fallback mislabelling that D-0032 was written to expose, reproduced
# mechanically and at scale. A DOM token that appears in no shipping HTML is
# NOT relocatable; it is a finding.
MARKUP_SUFFIX = ".html"


def probe_for(token: str) -> str:
    """The substring that must appear in the page if `token`'s claim is true.

    Anchor tokens come in several shapes and each needs reducing before it can
    be looked for literally:

      `#sdSendButton`      -> sdSendButton      (id= in the markup)
      `.sd-persona-flow`   -> sd-persona-flow   (class= in the markup)
      `retryDraft()`       -> retryDraft        (a call, parens vary)
      `POST /drafts/:id/x` -> /drafts           (":id" never appears literally,
                                                 so only the stem is checkable)

    That last reduction is why this is a report and not a gate: a route stem is
    a weak probe and can match coincidentally. Findings on id/class tokens are
    the strong ones.
    """
    probe = token.strip()
    if probe.startswith(("#", ".")):
        probe = probe[1:]
    probe = probe.split("(")[0].strip()
    for verb in HTTP_VERBS:
        if probe.startswith(verb):
            probe = probe[len(verb):]
            break
    return probe.split(":")[0].rstrip("/")


# The production closure, in the order a location should be preferred: the page
# a user looks at first, then the two other shipping pages, then the modules.
# `parity_validator.py`'s PRODUCTION_MARKERS is the authority on what counts as
# production; this list is that set enumerated concretely so a token can be
# attributed to the file it actually lives in.
def production_files() -> list[tuple[str, str]]:
    names = [
        "app/src/renderer/signal-desk.html",
        "app/src/renderer/overlay.html",
        "app/src/renderer/review-overlay.html",
        "app/src/renderer/bootstrap/signalDeskApp.js",
        "app/src/renderer/api/backend.js",
        "app/src/renderer/signalCore.js",
        "app/src/renderer/talkDrafts.js",
        "app/src/renderer/glitch-ring.js",
    ]
    for sub in ("features", "lib"):
        d = ROOT / "app/src/renderer" / sub
        if d.is_dir():
            names.extend(
                sorted(f"app/src/renderer/{sub}/{p.name}" for p in d.iterdir() if p.is_file())
            )
    out = []
    for rel in names:
        p = ROOT / rel
        if p.is_file():
            out.append((rel, p.read_text(encoding="utf-8")))
    return out


def relocate(ledger: str) -> tuple[str, int, list[str]]:
    """Rewrite each anchor claim's location list to name the files that really hold it.

    Only the `… in \\`<file>\\`` tail of a "Production anchor(s):" clause is
    touched; every other character of every row is preserved. A row whose
    tokens cannot ALL be located is left exactly as-is and reported, because a
    half-corrected pointer is worse than an honestly wrong one.
    """
    files = production_files()
    fixed = 0
    unresolved: list[str] = []
    out_lines = []

    for line in ledger.splitlines():
        match = ANY_CLAIM_RE.search(line) if line.startswith("| UI-") else None
        if not match:
            out_lines.append(line)
            continue

        row_id = line.split("|")[1].strip()
        # Only the anchor tokens, not the file paths a previous pass wrote into
        # the same clause -- otherwise re-running would treat its own output as
        # anchors to relocate.
        tokens = [
            t for t in TOKEN_RE.findall(match.group(1))
            if not t.startswith("app/src/")
        ]
        by_file: dict[str, list[str]] = {}
        missing = []
        for tok in tokens:
            probe = probe_for(tok)
            if not probe:
                continue
            # A DOM anchor may only be attributed to markup. See MARKUP_SUFFIX.
            is_dom = tok.startswith(("#", "."))
            home = next(
                (rel for rel, text in files
                 if (rel.endswith(MARKUP_SUFFIX) or not is_dom) and probe in text),
                None,
            )
            if home is None:
                missing.append(tok)
            else:
                by_file.setdefault(home, []).append(tok)

        if missing or not by_file:
            unresolved.append(f"{row_id}: {', '.join(missing) or 'no locatable tokens'}")
            out_lines.append(line)
            continue

        clause = "; ".join(
            f"{', '.join('`%s`' % t for t in toks)} in `{rel}`"
            for rel, toks in by_file.items()
        )
        new_line = line.replace(match.group(0), f"Production anchor(s): {clause}")
        if new_line != line:
            fixed += 1
        out_lines.append(new_line)

    return "\n".join(out_lines) + "\n", fixed, unresolved


def main() -> int:
    ledger = LEDGER.read_text(encoding="utf-8")
    page = PAGE.read_text(encoding="utf-8")

    if "--fix" in sys.argv:
        updated, fixed, unresolved = relocate(ledger)
        LEDGER.write_text(updated, encoding="utf-8")
        print(f"rewrote the location field on {fixed} row(s).")
        if unresolved:
            print(f"\n{len(unresolved)} row(s) LEFT UNCHANGED -- a token could not be located")
            print("anywhere in the production closure. These need a human, not a rewrite:")
            for entry in unresolved:
                print(f"  {entry}")
        print("\nNow re-run `python3 tools/anchor_audit.py` and `python3 tools/parity_validator.py`.")
        return 0

    rows: list[tuple[str, list[str]]] = []
    for line in ledger.splitlines():
        if not line.startswith("| UI-"):
            continue
        match = CLAIM_RE.search(line)
        if not match:
            continue
        row_id = line.split("|")[1].strip()
        rows.append((row_id, TOKEN_RE.findall(match.group(1))))

    # Two very different findings hide behind one "absent" count, and reporting
    # them as one number would badly overstate the problem.
    #
    #  * A missing FUNCTION or ROUTE token is usually benign mislabelling. The
    #    capability is real and lives in features/*.js or api/backend.js -- an
    #    HTML file is not where `acceptDraft()` or `POST /macros` would ever
    #    appear. Only the stated LOCATION is wrong.
    #  * A missing #id or .class is the serious kind, and the kind C-6 was: the
    #    row claims a DOM anchor on the shipping page, and the page has no such
    #    element. Either it lives on another page (the overlays, or legacy
    #    index.html) or it does not ship at all -- and only reading the row
    #    tells you which.
    # A DOM anchor absent from signal-desk.html may still SHIP -- the app has
    # three production pages, and the two floating overlay windows own a large
    # id vocabulary of their own (#readButton, #finalText, #statusRing...).
    # Checking only the dashboard would report every overlay row as a hole when
    # the real defect is just the stated location. So the residue that matters
    # is: absent from signal-desk.html AND from both overlay pages.
    other_pages = "\n".join(
        (ROOT / f"app/src/renderer/{name}").read_text(encoding="utf-8")
        for name in ("overlay.html", "review-overlay.html")
    )

    dom_absent_everywhere: list[tuple[str, list[str], int]] = []
    dom_wrong_page: list[tuple[str, list[str], int]] = []
    code_only: list[tuple[str, list[str], int]] = []
    for row_id, tokens in rows:
        missing = [t for t in tokens if probe_for(t) and probe_for(t) not in page]
        if not missing:
            continue
        dom_missing = [t for t in missing if t.startswith(("#", "."))]
        if not dom_missing:
            code_only.append((row_id, missing, len(tokens)))
            continue
        nowhere = [t for t in dom_missing if probe_for(t) not in other_pages]
        if nowhere:
            dom_absent_everywhere.append((row_id, nowhere, len(tokens)))
        else:
            dom_wrong_page.append((row_id, dom_missing, len(tokens)))
    dom_only = dom_absent_everywhere

    total_flagged = len(dom_only) + len(dom_wrong_page) + len(code_only)
    pct = lambda n: f"{100.0 * n / len(rows):.1f}%" if rows else "n/a"
    print(f"ledger rows claiming a signal-desk.html anchor : {len(rows)}")
    print(f"rows with >=1 claimed anchor ABSENT from page  : {total_flagged}  ({pct(total_flagged)})")
    print()
    print(f"  SERIOUS  -- #id/.class on NO shipping page   : {len(dom_only)}  ({pct(len(dom_only))})")
    print(f"  location -- #id/.class ships on an overlay   : {len(dom_wrong_page)}  ({pct(len(dom_wrong_page))})")
    print(f"  location -- fn/route lives in features/api   : {len(code_only)}  ({pct(len(code_only))})")
    print()

    if not total_flagged:
        print("OK -- every claimed signal-desk.html anchor is present in the page.")
        return 0

    if dom_only:
        print("SERIOUS -- the row claims a DOM anchor that exists on NONE of the three")
        print("shipping pages. This is the C-6 class: read each before counting it as")
        print("evidence, because the element may only exist in legacy index.html.")
        for row_id, missing, total in dom_only:
            print(f"  {row_id}: missing {', '.join(missing)}  (of {total} claimed token(s))")
        print()

    print(f"LOCATION-ONLY ({len(dom_wrong_page) + len(code_only)} rows): the capability is real and ships; only the")
    print("stated file is wrong. Overlay ids are attributed to signal-desk.html when they")
    print("live in overlay.html / review-overlay.html, and functions/routes are attributed")
    print("to the page when they live in features/*.js or api/backend.js. Worth correcting")
    print("for accuracy, but these are not missing capabilities.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
