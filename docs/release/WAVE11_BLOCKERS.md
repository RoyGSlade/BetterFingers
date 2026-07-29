# Wave 11 BLOCKERS — what is not `wired`, and why

Companion to [PARITY_INVENTORY.md](PARITY_INVENTORY.md). The ledger carries
the per-row ruling; this is the director-facing summary of everything that did
**not** clear the strict D-0015 chain, stated without softening.

**Wave 11 totals: 161 `wired` / 10 `intentional_cut` / 267 `blocked` / 438 total.**
(Gate 0 baseline was 0 / 4 / 434.) Reproduce with
`python3 tools/parity_validator.py`; regenerate with
`python3 tools/parity_ledger_build.py`.

Gate 11 asks whether Signal Desk is the product. On this evidence the honest
answer is: **it is the product, and it is not yet fully evidenced as the
product.** 161 rows clear the whole chain against the page that ships. 267 do
not, and they do not for two very different reasons that must not be added
together.

## The split

| | Count | Meaning |
|---|---:|---|
| `blocked (product)` | **91** | No production anchor. The item lives only in `index.html`, or nowhere. A real gap. |
| `blocked (evidence)` | **176** | Anchored in production, but the chain is not fully evidenced — no production-target QA/unit test names it, or the source row is prose with no code handle to resolve. A gap in the audit. |

Both are `blocked` in the ledger. The vocabulary is not softened and no row was
promoted to make a number look better. The split exists because reporting 267
undifferentiated blockers would tell the director the product is missing 267
things, which is false — and would be exactly as useless as a victory lap.

### By workspace

| Workspace | product | evidence |
|---|---:|---:|
| Settings | 31 | 69 |
| Dashboard / Talk | 18 | 18 |
| Utilities / Models | 17 | 4 |
| Status / notification | 7 | 7 |
| Shell / surfaces | 6 | 7 |
| Onboarding | 4 | 5 |
| Cross-cutting / orphans | 2 | 15 |
| Shell / header | 2 | 1 |
| Utilities / Diagnostics | 2 | 9 |
| Release control | 2 | 0 |
| Studio / Foundry | 0 | 23 |
| Overlay windows | 0 | 18 |

## BLOCKERS the director should act on

### B-1 — The Foundry has no production-target QA at all (23 rows, evidence)

Every Persona Foundry control resolves in the production closure — the ids are
in `signal-desk.html` and `features/personas.js` is imported by the production
bootstrap — but its QA scenarios (`app/tests/qa/scenarios/personas.mjs`) carry
no `ui:` tag, so they run against **`index.html`**. Twenty-three rows are
therefore anchored-but-unevidenced on the page that ships.

This is the single cheapest win in the list: the Foundry markup is already in
the production page, so the fix is a QA retarget, not a build.

### B-2 — Overlay windows have no production-target QA (18 rows, evidence)

`overlay.html` and `review-overlay.html` are production surfaces (separate
always-on-top windows from `app/src/main/windows.js`, shipped whichever
dashboard is loaded). Wave 11 corrected the audit to include them in the
production closure — they are **not** product gaps. But no QA scenario drives
either window, so no row can clear the QA leg. The floating overlay is the
surface a user watches while dictating; it being unexercised by QA is a real
hole even though the code ships.

### B-3 — Settings: 31 rows with no production anchor

The largest genuine product gap. Concentrated in the Settings chrome and the
hotkey/wake-word groups: `#settingsSearchInput`, `.settings-nav-button` ×14,
`#settingsSaveBar`, `#discardProfileChangesButton`, `#saveProfileButton`,
`#waylandHotkeyWarning`, `#settingHotkey`, `#settingForceStopKey`,
`#settingManualSendHotkey`, `#settingReviewTtsHotkey`, `#settingChatOpenKey`,
`#settingWakeWordEnabled/Model/Sensitivity/Cooldown/MaxRecording`,
`#importWakeModel*`, `#testMicButton`, `#testWakeButton`.

Signal Desk has its own save bar and search (`#sdSetSaveBar`,
`#sdSetSearchInput` — those rows ARE wired), so part of this is legacy-id
noise. The hotkey and wake-word capture controls are the substantive part:
those are user-facing capabilities with no resolvable production anchor.

### B-4 — Utilities / Models: 17 rows with no production anchor

`#refreshModelsButton`, `#modelRecommendation`, `#modelStatusSummary`,
`#llmModelBadge/Select/Details`, and the rest of the legacy Models tab. The
production page has a Models section (`#sdUtilSectionModels`) and it is partly
wired, but a substantial part of the legacy model-manager surface does not
resolve there.

### B-5 — Dashboard / Talk: 18 rows with no production anchor

Chiefly the three backend status cards (`#backendStatus`, `#transcriberStatus`,
`#llmStatus`), `#draftStatus`, `#dashboardEmergencyStopButton`,
`#recordingControlStatus`. Signal Desk's status bar reports backend state
through different cells (`#sdStatus*`), so the *capability* is largely present;
the specific inventory items are not resolvable. These deserve a per-row human
ruling — several are probably `intentional_cut` (replaced by the status bar)
rather than genuinely missing, but Wave 11 will not assert that without
naming the replacement, and did not have the evidence to name it row by row.

### B-6 — 57 rows state no code handle at all (evidence)

Prose-only inventory rows ("App shell header — logo/title/tagline + Quit
button") give the collector nothing to resolve. They need a human to name a
production anchor before they can be ruled on. They are honestly `blocked`
today; they are not evidence of a missing feature.

### B-7 — The two §0 known bugs are still unresolved (2 rows, product)

`UI-00-001` (the `renameProfileButton`/`duplicateProfileButton`/
`exportProfileButton` undeclared-identifier bug) and `UI-00-002` (the two
status notes with no defined contract) were carried from Gate 0 and remain
open. Signal Desk has its own `#sdSetRenameProfileButton` etc., so the legacy
bug does not affect the shipping page — but neither row has been formally
closed.

## Rulings recorded here rather than in the ledger

Two Wave 11 decisions have no counterpart in the 438-item source inventory,
which predates the work they concern. Inventing ledger rows for them would
break the 1:1 source binding that makes the ledger checkable, so they are
ruled on here.

### R-1 — The legacy `index.html` Privacy section: **intentional cut**

D-0028 deferred to Wave 11 the question of whether the legacy Privacy section
must grow the five Wave 6 groups (store list, persona-learning disclosure,
export, wipe mode, factory reset). **Ruling: intentional cut, rollback-only
rationale.**

After the Wave 11 default flip, `index.html` is reachable only via
`BF_UI=legacy`. It is a revert path, not a shipping product surface. The
capability it matters for is not missing on that path: wipe and export are
registry-driven in the backend (`data_categories.py`), the same registry both
pages call, and `tests/test_rollback_store_parity.py` asserts the backend
cannot even observe which page is loaded. Building a second full privacy UI on
a page users are not meant to reach adds a maintenance surface without adding
a capability.

Stated honestly, the cost of this cut: a user who has rolled back to legacy
sees a smaller privacy surface than a user on Signal Desk. They can still wipe
and export; they cannot browse the store list or the persona-learning
disclosure from that page. If the director judges the rollback path must be
capability-identical, this cut must be reversed and the work is real.

### R-2 — The D-0029 `unavailable` dispatcher actions: **blocked (product)**

`command.begin`, `command.end`, `activate_persona` and `activate_writing_preset`
report `unavailable` because the backend entry points do not exist. D-0029
asked Wave 11 to resolve each as wired-later or `intentional_cut`.

**Ruling: none of them is cut. All four stay blocked, wired-later.** They are
not surfaces that were replaced by something better — they are actions the
dispatcher already names and honestly refuses. `cancel_capture` and
`inject_latest` were deliberately left unset rather than second-implemented
(D-0029), which is the right call and the same reasoning applies here: the fix
is a backend entry point, not a UI decision. Cutting them would mean deciding
the product does not want controller/Stream Deck-driven persona switching, and
that is a product decision this lane has no basis to make.

## What would move the numbers

Ordered by evidence gained per unit of work:

1. **Retarget the Foundry QA** (`personas.mjs` → `ui: 'signal-desk-prod'`, or a
   production sibling). Unblocks up to 23 rows and costs no product work.
2. **Add overlay-window QA.** Unblocks up to 18 rows and closes a genuine hole
   in what is exercised.
3. **Per-row human anchoring for the 57 prose rows.** Pure audit work.
4. **Rule on the Dashboard status-card rows (B-5).** Likely converts a chunk of
   the 91 product blockers into `intentional_cut` with a named replacement —
   but only with the replacement actually named.
5. **Then** the substantive product gaps: hotkey/wake-word capture controls
   (B-3) and the model-manager surface (B-4).

None of 1-4 is a product change. That is the shape of this result: the largest
part of what stands between here and a clean Gate 11 is evidence, not code.
