# Wave 11 BLOCKERS — what is not `wired`, and why

> **Archived wave doc — numbers below are historical, not current.** Every
> count in this document (161/10/267, and the later Wave 11B corrections) is
> a snapshot from when it was written. The live validator, re-run and
> director-verified at commit `545e582` (2026-07-29), reports **398 wired /
> 23 intentional_cut / 17 blocked / 438 total**. Reproduce with
> `python3 tools/parity_validator.py`. `RELEASE_BOARD.md` carries the current
> figure; this document's body is left unedited below as a historical record.

Companion to [PARITY_INVENTORY.md](../PARITY_INVENTORY.md). The ledger carries
the per-row ruling; this is the director-facing summary of everything that did
**not** clear the strict D-0015 chain, stated without softening.

**Wave 11 totals: 161 `wired` / 10 `intentional_cut` / 267 `blocked` / 438 total.**
(Gate 0 baseline was 0 / 4 / 434.) Reproduce with
`python3 tools/parity_validator.py`; regenerate with
`python3 tools/parity_ledger_build.py`.

> **SUPERSEDED BY WAVE 11B — read [§ Wave 11B](#wave-11b--corrections-to-this-document)
> before using any number above.** Wave 11B found two defects in the collector
> that produced these figures, closed three of the clusters below, and reversed
> the ruling on a fourth. The 161 / 10 / 267 line, the two tables under
> *The split*, and blockers **B-1**, **B-2** and **B-6** are all out of date. They
> are left in place rather than overwritten so the correction is legible as a
> correction; the ledger itself is regenerated and is the authority.

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

---

# Wave 11B — corrections to this document

Wave 11B (evidence lane) worked items 1-3 of the list above. Two of them closed.
The third turned out to rest on a mistaken premise, and the work of testing it is
what found the mistake. Everything below supersedes the corresponding section
above.

## C-0 — Two defects in the collector that produced the Wave 11 numbers

Both were invisible: the ledger regenerated cleanly and the validator passed
while the figures were wrong. Each is now covered by
`tests/test_parity_evidence_rules.py`, so neither can quietly return.

**Comments counted as evidence.** `parity_evidence.py` resolved an id by looking
for it anywhere in reachable source, and "anywhere" included comments. A module
that merely mentioned `#backendStatus` while explaining what replaced it made
that row resolve *in production*, and the row could then reach `wired` on the
strength of a sentence. Every file is now stripped of comments before anything is
matched against it — HTML comments by pattern, JS comments by a scanner that
tracks string state so `"https://…"` survives — and the same rule is applied to QA
scenarios and unit tests, because a scenario that only *mentions* a control in
its header does not exercise it. **Effect: −8 `wired`.** Five of the eight
resolved only off a comment naming the legacy handle (`.stream-panel`,
`settingEls`, `maybeLearnFromEdit`, `InsufficientDiskSpaceError`,
`#settingInputDevice`). This defect *inflated* the number Gate 11 exists to
trust, which makes it the more serious of the two.

**Endpoint rows could never be reported as covered.** Coverage matched
`\b<needle>\b`. `\b` asserts a word/non-word transition, so
`\b/personas/interview/answer` requires a word character immediately before the
leading slash — and a QA stub writes `'POST /personas/interview/answer'`, where
that character is a space. No endpoint row could clear the QA leg however
thoroughly a scenario drove it. Replaced with lookarounds that are no looser than
`\b` for identifiers. **Effect: +5 `wired`.** The same class of bug as the comment
hole, pointing the other way, and equally invisible.

Net collector correction on the checkout where both were measured in isolation:
**261 → 258 `wired`.** Wave 11B's own results are stated against the corrected
collector, never against 261.

## C-1 — B-1 is CLOSED, and its diagnosis was wrong

B-1 said the Foundry's 23 unevidenced rows would be closed by retargeting
`app/tests/qa/scenarios/personas.mjs` to `signal-desk-prod`. **That would have
moved zero rows.** `personas.mjs` does not touch the Foundry: it exercises the
manual persona *wizard* (`#wizard*`) and the Cleanup Preset select, and contains
no `#foundry*` id at all. Retargeting it would have moved nothing while breaking
the legacy rollback coverage it does provide. The Foundry had no QA on either
page — the gap was larger than reported, not smaller.

There is also almost no selector drift to fix. Signal Desk re-housed the Foundry
dialog without renaming its controls: every `#foundry*` id is identical in
`signal-desk.html` and `index.html`. The only two differences are the entry
points, and they matter:

- `#openFoundryButton` is a real Settings button on the legacy page and a
  **hidden compatibility trigger** in production, existing so `personas.js`'s own
  `initFoundry()` binding has something to bind.
- `#sdOpenFoundryButton` — Studio's "✨ Build with AI" — is the production entry
  point, routed `studioWorkspace.js` → `onOpenFoundryRequested` →
  `personaFlow.openFoundry()` (`signalDeskApp.js:557`), which opens the guided-flow
  chrome and only then clicks the hidden trigger.

`app/tests/qa/scenarios/foundry-prod.mjs` (new, `ui: 'signal-desk-prod'`) enters
through Studio and drives the whole path: interview → choice question →
example/anti-example collection → automatic compile → stress test with per-case
verdicts → character card → save. `personas.mjs` is left on the legacy target,
deliberately, as rollback coverage.

**§3: 3 `wired` / 23 `blocked` → 26 `wired` / 0 `blocked`.**

Contingent on the QA run: the collector credits a row when a production-target
scenario *names* its anchor, which the new file does. Whether the scenario
*passes* is the director's Electron QA run
(`BF_QA_UI=signal-desk-prod node tests/qa/run.mjs foundry`), which this lane
cannot execute. **If it fails, these 26 rows must go back to `blocked` until it
is green.** The same caveat applies to C-2.

## C-2 — B-2 is REVERSED: the overlay windows are a product gap, not an audit gap

B-2 stated that `overlay.html` and `review-overlay.html` "are **not** product
gaps" and that the only thing missing was QA. Writing that QA established the
opposite, and this is the most consequential finding of the objective.

**On the production page these windows cannot be reached.**

- `overlay:update-status` is what makes the capture overlay show a pipeline
  state. Its only renderer-side caller anywhere in the repository is
  `app/src/renderer/main.js` — the **legacy** page. The production closure
  (`signal-desk.html` plus everything `bootstrap/signalDeskApp.js` imports)
  contains no call to `updateOverlayStatus`. Signal Desk consumes the same
  voice-status stream itself (`features/talkCapture.js`) to drive its in-page
  ring, and never forwards it to the window.
- `review:show` is the only thing that ever creates the review window. Same
  single legacy caller. On the shipping page that window is never created at all.

So the floating overlay a user is supposed to watch while dictating does not
respond to dictation on the page that ships, and the Review Deck cannot be opened
from it. The code is fine. Nothing calls it.

D-0015 requires a *reachable* production location, so these rows stay `blocked`
and their reason is corrected from evidence to **product**
(`tools/parity_ledger_build.py`, `_OVERLAY_UNREACHABLE`): §12.1's status rows
(`UI-12-003/004/005`), all of §12.2 (`UI-12-009`…`UI-12-026`), and the two rows
elsewhere that describe the same window (`UI-01-018`, `UI-14-009`). Marking them
`wired` because a test can drive the IPC handler directly would report a surface
as shipped that a user can never see — the same failure as the comment hole,
reached by a different route.

**Not** blocked, deliberately: the capture overlay's ring, label, appearance and
drag rows. Settings → Appearance *is* a real production caller —
`#sdSetOverlaySize` reaches the window through `overlay:set-appearance`, which
also shows it — so `UI-12-001/002/006/007/008`, `UI-01-017` and `UI-14-008` do
resolve on the shipping page and are left to the mechanical rules.

The QA still landed and is worth having: `app/tests/qa/scenarios/overlay-prod.mjs`
(new, `ui: 'signal-desk-prod'`) drives both windows through the real main-process
handlers and the real preload bridge, covering the ring's state vocabulary, the
appearance chain end to end, the Review Deck's draft render, its rewrite/instruct/
read actions with request capture, and the non-destructive dismissal contract
(close and Escape must not decline). It is what makes the finding checkable and
it is the regression net the fix will need.

Reaching a second window needed no product change and no debug handle:
`app/tests/qa/run.mjs` now passes scenarios a `ctx` carrying the
`ElectronApplication`, which already tracks every window the app owns, and
`harness.mjs` gained `auxiliaryWindow()`. Screenshot entries accept `of(ctx)` so a
walkbook entry can photograph a window other than the dashboard.

**§12 plus the four related rows: 10 `wired` / 20 `blocked` → 5 `wired` /
25 `blocked`, and the rows B-2 called an audit gap are now correctly counted as
product gaps.** This is the one cluster in Wave 11B whose number gets *worse*,
and it does so on purpose: five rows that read as `wired` now read as `blocked
(product)` because the surface is unreachable on the page that ships. The fix is
a production caller, not more QA.

Measured against the corrected-collector baseline on one checkout with this
objective's two QA files withdrawn and this override removed, so the movement is
attributable rather than entangled with the surfaces lane's concurrent work.

## C-3 — B-6: the mechanism exists; 46 rows anchored, 12 stay prose-only

B-6's 57 prose rows needed a human to name a production anchor. That mechanism
now exists as `tools/parity_anchors.py` (owned by the surfaces lane; the import
hook, validation and ledger plumbing are in `parity_evidence.py` /
`parity_ledger_build.py`). A declared anchor is checked, not trusted: it must
resolve in the production closure, it may not duplicate a handle that already
resolves, it may not be attached to a row that anchored itself, and it must carry
a stated reason — any of which failing fails the build.

46 of the 58 rows that were unanchored at the start of Wave 11B now have verified
anchors, landed in `ROW_ANCHORS` by the surfaces lane (the §1/§4 shell, the
§6 Talk group headers, the §7 wizard steps and wake/voice groups, the §8/§9 panel
headers, the §12 IPC rows, the §14 progress surfaces, and the §15 orphan-list
rows). Anchoring supplies only the location leg — a row still has to clear
coverage on its own, and several of these correctly remain
`blocked (evidence)`.

**12 rows are deliberately left unanchored, and stay `blocked`:**

| Rows | Why no anchor |
|---|---|
| `UI-02-005`, `UI-02-007`, `UI-02-012` | The onboarding steps are unnamed `[data-flow-step]` sections addressed by index. Anchoring three rows to the shared `#sdOnboarding` container would be exactly the convenience mapping the table forbids. |
| `UI-06-063` | Describes the WS driving overlay and review-overlay pushes. Production does not do that (see C-2). Anchoring it would assert behaviour that is absent. |
| `UI-06-074`, `UI-06-076` | Message Rescue assessment/preservation regions. The rows name no element, and their siblings in §§6.4/6.6 are already `intentional_cut` as fixture-only. |
| `UI-07-133`, `UI-07-138` | The `[data-blend-preset]` / `[data-mod-preset]` quick chips. `features/voiceStudio.js` queries them; `signal-desk.html` does not contain them. **A real product gap, not an anchoring gap.** |
| `UI-07-134`, `UI-07-127` (chips), `UI-15-007` | `UI-15-007` is the donation prompt: the source row itself records that none exists anywhere in scope. There is nothing to anchor. |
| remainder | Group headers whose only honest anchor is a container another row already owns. |

## C-4 — Two smaller repairs made while regenerating

**A silent-empty anchor table.** `load_anchor_table()` swallowed a failed import
and returned three empty dicts. A regeneration that landed during another
session's atomic rewrite of `parity_anchors.py` read the module as absent and
wrote a clean-looking ledger sixty rows light — no warning, no failure. It now
raises if the file exists but will not import; absent-from-disk still degrades
quietly, which is correct for an older checkout.

**Pipes in generated cells.** Rationales legitimately contain `|` (for example
`POST /wake/enable | POST /wake/disable`). The generator escaped it as `\|`, but
`parity_validator` splits rows on `|` and a backslash-escaped pipe still splits —
one row came out with eight cells and broke parsing outright. Generated cells now
emit `&#124;`.

## What would move the numbers now

Replacing items 1-3 of the Wave 11 list, which are done:

1. **Give the production page a caller for the overlay windows** (C-2). This is
   the one item here that is real product work, and it is the one the Wave 11
   list said did not exist. Roughly: forward `talkCapture.js`'s status stream to
   `updateOverlayStatus`, and open the Review Deck from the draft flow.
2. **Land the 46 `ROW_ANCHORS`** and re-run. Pure audit work, already validated.
3. **Add the `[data-blend-preset]` / `[data-mod-preset]` chips** to
   `signal-desk.html`, or cut them with a named replacement (C-3). `voiceStudio.js`
   already binds them.
4. **Then** the remaining substantive gaps carried from Wave 11: B-3 and B-4, as
   re-scoped by the surfaces lane.

The Wave 11 conclusion was that the largest part of what stands between here and
a clean Gate 11 is evidence rather than code. After 11B that is still mostly
true — but it is less true than it looked, and the difference is the overlay
windows.

---

# Wave 11C — the evidence-gap rows (Objective A)

Wave 11C opened with **280 `wired` / 19 `intentional_cut` / 139 `blocked`**, the
139 split 31 product + 108 evidence. This section covers the 108 evidence rows:
items that *are* anchored in the shipping page but that no production-target QA
scenario and no renderer unit test named, so the D-0015 coverage leg was unmet.

No product change was made for any of them. The work was writing tests that
genuinely drive the shipping controls.

## D-0: the unit suite could not reach the DOM, which is where these rows live

Every one of these rows is an element. The renderer feature modules
(`features/settingsWorkspace.js`, `features/utilitiesWorkspace.js`,
`features/talkWorkspace.js`, …) are written against a browser document, this
repo has no jsdom, and the unit suite is plain `node --test`. So the existing
suites tested the *pure* halves — view models, reducers, validators — and the
DOM wiring was left to manual preview-page checks. Which id becomes which
control, which listener a button actually gets, and which backend route a click
actually reaches had never been executed by a test.

That is the gap the ledger was reporting, stated in its own terms.

`app/tests/helpers/rendererDom.mjs` closes it without adding a dependency: a
~300-line document that implements only what the feature modules touch —
`getElementById`, `classList`, `dataset`, `hidden`, `append`/`replaceChildren`,
attribute selectors, listeners, `style.setProperty`. It is deliberately not a
DOM emulator. Two places where an over-simplification would have *hidden* a
defect were found and fixed while writing it, and both are documented in the
file: `textContent` concatenates own text with descendants (modelling them as
alternatives hid the `×` a chip appends after its label), and `title` is
reflected between property and attribute (keeping them apart would have reported
a tooltip as cleared while it was still on screen).

The backend is stubbed at exactly one place: `window.betterFingers.backendRequest`,
the single preload bridge `api/backend.js` funnels every proxied route through.
So the tests exercise the real URL building, the real error unwrapping and the
real `(method, path, body)` triple, and can assert the exact route a control
reaches for. Destructive and sensitive calls (`wipePrivacyData`, `cancelJob`,
`uploadWakeModel`) go down dedicated typed IPC methods and are stubbed there,
which is itself a check that the sensitive paths are not on the generic proxy.

## What landed

Ten new files, **147 tests, all green**, and the whole renderer suite is
**1510/1510**.

| File | Rows it evidences |
|---|---|
| `app/tests/settingsProfileOps.test.mjs` | UI-07-003, -004, -005, -009, -010, -015, -016, -018, UI-15-023 |
| `app/tests/settingsAppearanceOverlay.test.mjs` | UI-07-151 … -156, -159, -160, -161, -163 |
| `app/tests/settingsPrivacyPanel.test.mjs` | UI-07-171, -172, -173, -174, -176 |
| `app/tests/utilitiesInputWake.test.mjs` | UI-07-026, -100, -103, -107, -108, UI-08-018, UI-14-012, UI-15-003, UI-15-010 |
| `app/tests/utilitiesTextAdvanced.test.mjs` | UI-07-091, -092, -093, -095, -165, -166, -167, -168, -170, -177, -178, -179, -182, -186, -187, UI-09-011 |
| `app/tests/utilitiesDiagnosticsPanels.test.mjs` | UI-01-016, UI-08-019, UI-08-021, UI-09-002, -010, -012, -013, -015, -016, UI-14-013, -014, UI-15-008, -016, -017, -018 |
| `app/tests/talkDraftSurfaces.test.mjs` | UI-06-014, -018, -022, -029, -032, -037, -041, UI-14-005 |
| `app/tests/shellHeaderCopy.test.mjs` | UI-01-019, UI-04-001, UI-06-073, -080, UI-14-001, UI-15-025 |
| `app/tests/personaWizardSteps.test.mjs` | UI-07-052, -058, -072, -074 |
| `app/tests/voiceCloningConsent.test.mjs` | UI-07-140, -143, -144, -147 |

**87 of the 108 evidence rows.** Per cluster, evidence-blocked before → after:

| Cluster | Before | After | What is left |
|---|---:|---:|---|
| Settings (§7) | 57 | 6 | UI-07-051, -126, -127, and the three missing preset chips |
| Dashboard / Talk (§6) | 14 | 5 | 2 inert handles + 3 prose rows |
| Utilities / Models + Diagnostics (§8/§9) | 11 | 1 | UI-09-006 only |
| Cross-cutting / orphans (§15) | 11 | 3 | UI-15-007, -012, -014 |
| Status / Shell / Onboarding (§14/§1/§4/§2) | 13 | 4 | 3 prose onboarding rows + UI-14-007 |
| Overlay windows (§12) | 2 | 2 | owned by the overlays lane |

Nothing in the table is asserted from a run of the generator by this lane — this
lane's toolchain permissions do not include running `tools/parity_ledger_build.py`
(see *Regeneration*, below). Every row above is claimed because a test that
**passes** names its printed anchor, which is the collector's own rule; the
authority is the regenerated ledger, not this table.

One partial regeneration landed mid-objective from the overlays lane and is
consistent with that claim: it moved the ledger to **381 `wired` / 21
`intentional_cut` / 36 `blocked`** with the first six of these files present and
the last four absent, and every row it left blocked is either on the list below
or covered by the four files it had not yet seen. That figure also contains the
overlays lane's own product work, so it is not attributable to this objective and
is quoted only as corroboration.

## C-5 — a comment can still count as evidence: the regex-literal hole

**This is the most important finding of the objective, and it is C-0's comment
hole reopened by a different route.**

`strip_js_comments()` in `tools/parity_evidence.py` tracks string state so that
`"https://…"` is not mistaken for a comment. It does not track **regex
literals**. A `/` is treated as a comment opener only when followed by `/` or
`*`, which keeps `/foo/` intact — but the characters *inside* a regex literal
are still scanned as ordinary source, so a quote character inside a character
class opens a string state that never closes:

```js
return String(value ?? '').replace(/[&<>"']/g, (c) => ESCAPES[c]);
```

The `"` opens a double-quoted string. It closes at the next `"` anywhere later
in the file. Everything between — **including every comment** — is emitted
verbatim instead of being blanked.

Five files in the production closure contain that exact escape-HTML regex,
including the production bootstrap itself:

- `app/src/renderer/bootstrap/signalDeskApp.js:76`
- `app/src/renderer/features/applicationProfiles.js:192`
- `app/src/renderer/features/messageRescuePanel.js:39`
- `app/src/renderer/features/workflowBuilder.js:264`
- `app/src/renderer/talkDrafts.js:30`

**A confirmed victim: `UI-06-038`.** The row names `#sendActionSelect`. That id
occurs in exactly three places in the repository: `index.html` (legacy),
`main.js` (legacy), and one **comment** at `app/src/renderer/talkDrafts.js:80` —
which sits after the regex on line 30. The ledger reports the row as
`Production anchor(s): #sendActionSelect in app/src/renderer/signal-desk.html`.
It is not in `signal-desk.html`, and it is not in any executable line of the
production closure. The row is a **product** gap (Signal Desk replaced the
control with `#sdDeliveryType`), not an evidence gap, and it is currently
mis-classified.

This lane did **not** cover UI-06-038, deliberately: crediting it would have
promoted a row whose production anchor does not exist.

The fix belongs to whoever owns `tools/parity_evidence.py` — the scanner needs
to recognise a regex literal (a `/` in expression position) and skip to its
closing `/`. Until then the `wired` count carries an unknown amount of
comment-derived evidence, and `tests/test_parity_evidence_rules.py` needs a case
for it so it cannot return a third time.

## C-6 — two rows whose named handle is inert on the shipping page

Not evidence gaps, and not covered here. Both are cases where the collector's
"an id may live only in JS" fallback resolved a handle that production never
attaches to an element.

**`UI-06-021` and `UI-14-007` — `#draftConfidence`.** `features/drafts.js` is in
the production closure and calls `document.getElementById('draftConfidence')`,
so the id resolves. But `signal-desk.html` contains no such element:
`renderConfidenceBadge()` is a permanent no-op on the shipping page. The
capability is not missing — Talk's meta strip shows the score in
`#sdConfidenceValue` and `#sdConfidenceBarFill`, and
`app/tests/talkDraftSurfaces.test.mjs` now evidences that replacement explicitly
so it is a named substitution rather than an assumption. But the rows as written
name a handle that does nothing, so they stay `blocked`. Either they get a
`ROW_ANCHORS`-style human ruling pointing at the meta strip, or they are cut with
that replacement named.

**`UI-06-038` — `#sendActionSelect`.** See C-5. Replaced by `#sdDeliveryType`,
which `talkDrafts.js` reads for exactly the contract the old select had.

## What is still `blocked (evidence)` after this objective, and why

Twenty-one rows. Grouped by what each actually needs — and only three of them
would be closed by more tests of the kind this objective wrote.

| Rows | Why still blocked |
|---|---|
| `UI-07-051` | The Persona Wizard container row, anchored on the CLASS `.sd-persona-flow` rather than on any of the wizard ids. `personaWizardSteps.test.mjs` now drives the wizard itself, but nothing names that class, and naming a CSS class in a unit test to satisfy the collector would be exactly the kind of token-matching this ledger exists to refuse. A production-target QA scenario that opens the flow is the honest close. |
| `UI-07-126`, `UI-15-012` | `setDefaultVoicePreset` / `clearDefaultVoicePreset`. Both source rows already say it: the backend routes and the `backend.js` wrappers exist and **no UI triggers them**. Confirmed still true — the only occurrences in the renderer are the wrapper definitions and the export list. Covering them would evidence a route rather than a surface, which is the failure C-2 named. Blocked, and it is a product decision (build the control or cut it), not audit work. |
| `UI-07-127` | The Blend group header, anchored on `#sdVoiceBlendCards` in `features/studioWorkspace.js`. Reachable by the same method as the rest; simply not reached before this objective closed. The smallest remaining item. |
| `UI-07-133`, `-134`, `-138` | The `[data-blend-preset]` / `[data-mod-preset]` quick chips. **A real product gap, carried unchanged from 11B's C-3**: `voiceStudio.js` queries them and `signal-desk.html` does not contain them. No test can honestly evidence a control that is not on the page. |
| `UI-09-006` | Anchored only on the symbol `retranscribeRecording` and on `POST /recordings/:id/retranscribe` (with the literal placeholder). `utilitiesDiagnosticsPanels.test.mjs` genuinely exercises the control — it clicks the real Re-transcribe button on a rendered recording row and asserts `POST /recordings/rec-77/retranscribe` — so if the regenerated ledger still shows this row blocked, the reason is the needle spelling, not missing coverage. |
| `UI-06-063`, `-074`, `-076`, `UI-02-005`, `-007`, `-012`, `UI-12-008`, `UI-15-007` | **Prose-only, and deliberately left that way** — 11B's C-3 already ruled each of them and nothing in 11C changes the ruling. `UI-15-007` (donation prompt) records that none exists anywhere in scope; `UI-06-063` describes overlay pushes production does not perform; the three §2 rows are unnamed `[data-flow-step]` sections addressed by index, and anchoring them to the shared `#sdOnboarding` container is exactly the convenience mapping `ROW_ANCHORS` forbids. |
| `UI-06-021`, `UI-14-007`, `UI-06-038` | Inert handles — see C-6. These are product/anchoring rulings, not evidence work. |
| `UI-15-014` | `deleteWakeModel()` / `DELETE /wake/models/:id` are exported and have **no UI trigger** — the source row says so and asks for verification. Confirmed: no production caller. A test could drive the wrapper, but that would evidence a route rather than a surface, which is the failure mode C-2 named. Left blocked. |
| `UI-12-003` | Overlay windows; the overlays lane owns it. |

## Regeneration

`python3 tools/parity_ledger_build.py` and `python3 tools/parity_validator.py`
were **not** run by this lane: its `taskSafe` allowlist covers `node --test` and
`pytest` but not arbitrary interpreter invocations, and the widening commit
(`f091714`) landed after this session's tool permissions were fixed at spawn.
The ledger must therefore be regenerated by the director (or by any lane that can
run the generator) before the numbers above are treated as measured. Every claim
in this section is stated so it can be checked against that regeneration rather
than in place of it.
