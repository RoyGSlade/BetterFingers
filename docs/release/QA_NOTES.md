# QA NOTES — the single intake for every issue found

> **Testing by hand? You want [`OPERATOR_QA.md`](OPERATOR_QA.md), not this file.**
> That one is the step-by-step script with tick boxes. **This** file is where
> findings get *filed* — the entry format and a copy-paste template are at the
> bottom of the operator doc.

Companion to [`PUBLISH_PLAN.md`](PUBLISH_PLAN.md). **Every** problem anyone
finds — operator, worker, supervisor, director — lands here, in the section for
its screen/feature, using the entry format below. Nothing gets fixed from
memory, chat scrollback, or a commit message alone; if it isn't in this file,
it doesn't exist.

## Status at a glance — 2026-07-30

| Entry | Screen | Sev | Status |
|---|---|---|---|
| [QA-FR-001](#qa-fr-001) Escape drops focus out of the onboarding dialog | First-run | YEL | **OPEN** — fix candidate |
| [QA-FR-002](#qa-fr-002) Silent first-run model download | First-run | RED | **FIXED** `630a4bc` — needs operator confirmation (§1.10) |
| [QA-FR-003](#qa-fr-003) Doctor guidance never reached Talk | First-run | YEL | **FIXED** `630a4bc` |
| [QA-TALK-001](#qa-talk-001) Delivery offered three methods | Talk | YEL | **FIXED** `2740396` — Paste only |
| [QA-TALK-002](#qa-talk-002) Recording toggle partially anchored | Talk | YEL | **RESOLVED** — cut per D-0037 |
| [QA-TALK-003](#qa-talk-003) Watchdog warning is inline, not a toast | Talk | GRN | **OPEN** — operator judgement (§2.8) |
| [QA-LIB-001](#qa-lib-001) Empty Library had no action | Library | YEL | **FIXED** `52c1905` |
| [QA-UTIL-001](#qa-util-001) Wake list never rendered; badge always "Not installed" | Utilities | RED | **FIXED** `098dfba` — confirm at §5.1/§5.2 |
| [QA-SEC-001](#qa-sec-001) Wake upload skipped `upload_safety` | Security | RED | **FIXED** `080cd90` |
| [QA-SEC-002](#qa-sec-002) Dev routes mounted unconditionally | Security | YEL | **FIXED** `20a307b` |
| [QA-SEC-003](#qa-sec-003) `project_generator` arbitrary `target_dir` | Security | YEL | **FIXED** `f0f2b33` |
| [QA-OVL-001](#qa-ovl-001) Read/Stop never posted `/tts/stop` | Overlays | RED | **VERIFIED** — was already fixed in `ed1bede` |
| [QA-DOC-001](#qa-doc-001) False GPU claim | Docs | YEL | **FIXED** `f321bbe` — the *claim* was the bug |
| [QA-DOC-002](#qa-doc-002) Parity numbers disagreed | Docs | YEL | **FIXED** `f321bbe` |
| [QA-DOC-003](#qa-doc-003) Stale remediation claims | Docs | GRN | **FIXED** `f321bbe` |
| [QA-DOC-004](#qa-doc-004) QA board fails 6 scenarios without two env vars | Docs | YEL | **OPEN** — documented in OPERATOR_QA §0 |
| [QA-BL-001](#qa-bl-001) Parity tool counts dead `glitch-ring.js` | Backlog | YEL | **DEFERRED** post-publish |

**Four RED findings this wave. All four are fixed.** Two of them
(QA-FR-002, QA-UTIL-001) were user-facing defects nobody had reported — they were
found by auditing rather than by a bug report.

## How to file an entry

Append under the right section, newest last:

```
### QA-<screen>-<number> · <one-line title> · <RED|YEL|GRN> · OPEN
- Found by / date: <who> / <YYYY-MM-DD>
- Where: <exact surface — element id, route, file:line if known>
- Repro: <numbered steps from a known state; say which data dir / target>
- Expected vs actual: <one line each>
- Evidence: <PASTED command output, QA report path, screenshot path, or "manual">
- Disposition: (director fills) → task <ID> in PUBLISH_PLAN | deferred §7 | not-a-bug
```

> **Evidence means pasted output, not a named command.** Amended by **D-0039**:
> QA-DOC-001 cited "`nvidia-smi` + `get_hardware_tier()` → `dgpu-12g+`/`cuda`"
> with nothing pasted, and the claim turned out to be false — it reached the
> plan as assigned work before anyone ran it. Naming a command you did not run,
> or whose output you did not paste, is how a fabricated fact becomes a task.
> If you cannot paste output, write `unverified —` and say what you'd run.

- **Severity:** `RED` blocks publish. `YEL` fix if cheap before publish. `GRN`
  observation, no action promised.
- **Status:** `OPEN` → `TRIAGED` (director set Disposition) → `FIXED (commit)`
  → `VERIFIED (by whom)`. Only an Opus reviewer or the operator moves an entry
  to `VERIFIED`.
- **Numbering:** per-section, sequential: `QA-TALK-001`, `QA-SET-001`, …
- Workers who find something outside their task's file claim: file it here and
  keep going — do **not** fix it in place (PUBLISH_PLAN §1 rule 3).

## Routing map (where fixes come from)

| Section prefix | Screen / surface | Fixes flow into |
|---|---|---|
| `QA-FR` | First-run / onboarding / consent | PUBLISH_PLAN D-series; parity B-1 |
| `QA-TALK` | Talk workspace | B-2/B-3; D-series |
| `QA-LIB` | Library workspace | D-series |
| `QA-STU` | Studio / personas | B-4; D-series |
| `QA-UTIL` | Utilities / models / doctor | D-series |
| `QA-SET` | Settings / privacy / voice | B-5/B-6/B-8; C-4; D-series |
| `QA-OVL` | Overlay windows (ring, review) | A-1; B-7 |
| `QA-SEC` | Security / privacy boundary | C-1..C-4 (escalate RED to director same day) |
| `QA-PKG` | Installer / packaged app | F-1/F-2 |
| `QA-DOC` | Docs that contradict the code | E-series |
| `QA-BL` | Backlog / out-of-scope ideas | nowhere this release — §7 candidates |

---

## First-run & onboarding (QA-FR)

### QA-FR-001 · Escape blurs focus inside the onboarding dialog, weakening the trap · YEL · TRIAGED
- Found by / date: w-parity while writing B-1's keyboard-trap test / 2026-07-29,
  at `545e582`
- Where: `app/src/renderer/bootstrap/signalDeskApp.js:176-182` (global
  Escape/Cancel shortcut, bubble-phase on `doc`, via
  `features/shortcuts.js`), interacting with
  `app/src/renderer/features/guidedFlow.js:217-224` (capture-phase Escape
  handler)
- Repro: open onboarding on a fresh data dir; focus the consent step's Next
  button; press Escape.
- Expected vs actual: a non-dismissible flow swallows Escape and **keeps focus
  inside the dialog** / the dialog correctly stays open, but focus is knocked to
  `document.body`
- Root cause: `guidedFlow.js` correctly `preventDefault()`s Escape for
  non-dismissible flows but never calls `stopPropagation()`, so the bubble-phase
  global handler still runs and does `doc.activeElement?.blur?.()`
  unconditionally.
- **Why it matters:** with focus on `document.body`, a subsequent Tab can leave
  the trap into the underlying document instead of wrapping back inside it. The
  focus trap is the accessibility guarantee of a modal first-run gate — this is
  a hole in it, not a cosmetic nit.
- Evidence: verified live by the worker; the row's own requirement ("Tab cycles,
  Escape doesn't dismiss") still holds and is covered by the new
  `keyboard-trap-cycles-focus-and-swallows-escape` scenario in
  `onboarding-prod.mjs`
- Disposition: (director) → **D-series fix candidate**, one-line
  `stopPropagation()` in `guidedFlow.js`'s Escape branch. Not folded into B-1 —
  that task's file claim does not cover `guidedFlow.js`, and PUBLISH_PLAN §1
  rule 3 forbids fixing it in place. Held for the operator QA pass to confirm
  severity before it becomes a task.

### QA-FR-002 · First dictation silently triggers an untracked model download with no progress · RED · TRIAGED
- Found by / date: w-firstrun (D-1 audit) / 2026-07-29; **director-verified** at `20a307b`
- Where: `transcriber.py:388` — `local_files_only = self._is_model_cached(model_size)`,
  so an uncached model means `local_files_only=False` and `_load_model()` fetches
  over the network. Triggered from `server.py:749`
  (`ensure_transcriber_initialized(preload=False)`) on the stop/transcribe path.
  This is **not** the tracked path: `transcriber.py:221-266`
  (`download_whisper_model`) wraps the same load with
  `_set_whisper_download_state()` / `_emit_download_progress()` and is used
  **only** by the Utilities Download button.
- Repro: fresh `BETTERFINGERS_DATA_DIR` with no cached Whisper model → finish
  onboarding (the models step explicitly invites you to skip,
  `signal-desk.html:146-149`) → land on Talk → Start Recording → speak → Stop.
- Expected vs actual: an explained "Downloading speech model (~150 MB)…" state
  with progress / a generic **"Processing…"** that is indistinguishable from a
  hang, for as long as the download takes
- Evidence (director-verified, pasted):
  ```
  transcriber.py:388   local_files_only = self._is_model_cached(model_size)
  talkCapture.js:45    CAPTURE_STATES = ['idle','starting','recording','stopping','busy','error']
                       (no download state exists to render)
  $ grep -c "missing_model\|recoveryTriggers\|llm_runtime_status" \
        app/src/renderer/features/talkWorkspace.js \
        app/src/renderer/bootstrap/signalDeskApp.js
  talkWorkspace.js:0
  signalDeskApp.js:0
  ```
- **Why RED.** This is the *first thing a new user does*, and the app appears to
  hang. It defeats §5.2 ("just keep going always works" — onboarding actively
  tells them to skip the download, then punishes it) and §5.5 (no error
  dead-ends — there is no retry, no explanation, and no route to the Doctor).
  Nothing is broken in the backend; the failure is entirely one of feedback.
- Not reproduced end-to-end live: the QA harness stubs the backend and drives no
  real audio or network fetch. Code path verified by reading; timing unmeasured.
- Disposition: → task **D-3** (see PUBLISH_PLAN WS-D)

### QA-FR-003 · Doctor's `missing_model` recovery guidance never reaches Talk · YEL · TRIAGED
- Found by / date: w-firstrun (D-1 audit) / 2026-07-29; director-verified at `20a307b`
- Where: guidance text `server.py:2655` ("Go to the Models screen…"), consumed by
  `utilitiesWorkspace.js:432,455,463,477` and legacy `main.js:4014-4172`
- Expected vs actual: Talk surfaces or links to the guidance the backend already
  writes / it only ever appears on Utilities, which nothing on Talk points to
- Evidence: the zero-hit grep above
- **The backend already knows the right thing to say.** It just has no path to
  the screen where the user is standing.
- Disposition: → folded into **D-3**; not a standalone fix

## Talk (QA-TALK)

### QA-TALK-001 · Delivery offers three methods where one is intended · YEL · TRIAGED
- Found by / date: publish planning / 2026-07-29
- Where: `#sdDeliverySegmented`, `app/src/renderer/signal-desk.html:3211`
- Expected vs actual: one delivery method (Paste) per D-0036 / segmented
  control offers Type / Paste / Copy
- Evidence: D-0036; `features/talkWorkspace.js:492`
- Disposition: → task **B-3a**

### QA-TALK-002 · Recording toggle only partially anchored in production · YEL · TRIAGED
- Where: `#toggleRecordingButton`, parity row UI-06-016
- Expected vs actual: whole control resolves on the shipping page / some
  handles resolve only in legacy `index.html`
- Disposition: **ruled by D-0037** → `intentional_cut`, replacement
  `#sdCaptureStartButton`/`#sdCaptureStopButton` (`features/talkCapture.js`).
  Executed by task **B-3b**.

### QA-TALK-003 · Watchdog-timeout warning no longer surfaces as a toast · GRN · OPEN
- Found by / date: w-parity while evidencing UI-06-063 (B-2) / 2026-07-29,
  director-confirmed at `ded3300`
- Where: `server.py:723` `_broadcast_watchdog_timeout` emits status
  `watchdog_timeout_warning`; it reaches the voice-status fan-out, but
  `statusToState()` in `app/src/renderer/features/talkCapture.js` maps it to the
  default case, so the backend's message renders in the capture status line
  (`#sdCaptureMessage`) instead of a discrete toast popup
- Expected vs actual: legacy behavior raised a toast / the message is surfaced,
  but inline and easier to miss
- Evidence: worker read `statusToState` / `reduceCaptureState` /
  `interpretVoiceStatus` end to end; **no `showToast()` call exists anywhere in
  that fan-out** for this status
- **Not a regression in information, only in prominence.** The user is still
  told. Filed GRN because a stranded-recording warning is exactly the kind of
  thing an inline line can be missed — the operator should judge during §6.2
  whether it reads as urgent enough.
- Note: the same row's "draft-history refresh" effect was also re-architected —
  it moved off the websocket push onto direct calls in `features/drafts.js`
  (`refreshDrafts()` runs off the accept/decline/send/edit response). That one
  is a clean improvement, no action.
- Disposition: (director) → operator judgment at §6.2; no task opened. Related
  to parked board item #3 (background refreshes should paint in-panel, not toast)
  — which points the *opposite* direction, so resolve them together post-publish.

## Library (QA-LIB)

### QA-LIB-001 · Genuine-empty Library state has no primary action · YEL · TRIAGED
- Found by / date: w-firstrun (D-2 audit) / 2026-07-29; director-verified at `20a307b`
- Where: `app/src/renderer/features/libraryWorkspace.js` — the true-empty branch
  of `buildEmptyState()` (the final `else`, ~:1178-1181)
- Repro: fresh data dir, nothing captured yet, open Library
- Expected vs actual: §5.4 wants exactly one primary action on every empty state
  / this branch appends only a `<p>` and stops
- Evidence (director-verified): both sibling branches in the *same function* do
  it correctly — the error branch appends a `Try again` button
  (`#sdLibraryRetryButton`) and the filtered branch appends `Clear filters`
  (`#sdLibraryEmptyResetButton`). Only the branch a **first-time user** actually
  hits is missing its action.
- Suggested fix shape: a "Go to Talk" action, matching the copy that already
  says "Messages you capture in Talk land here."
- Disposition: (director) → **D-4 candidate**, one-screen task. Cheap and
  self-contained; batch with D-3 if a renderer worker is already in that file.

## Studio / Personas (QA-STU)

_No entries yet._

## Utilities / Models (QA-UTIL)

### QA-UTIL-001 · Wake backbone list is permanently empty; engine badge always reads "Not installed" · RED · TRIAGED
- Found by / date: w-lastrows while starting B-8's build / 2026-07-30;
  **director-verified** at `28f1557`
- Where: `app/src/renderer/features/utilitiesWorkspace.js:1100-1105`
  (`refreshWakeBackbones`) and `:1058,1062` (`renderWakeBackbones`)
- Two key/field mismatches, both verified live:
  1. The renderer reads `res?.backbones`. The backend returns
     `{"models": [...]}` (`routes_wake.py:299-303`; pinned by
     `tests/test_server_wake_routes.py:157`). `res.backbones` is therefore
     **always `undefined`** → `renderWakeBackbones([])` → the list renders
     "No wake-word backbones listed." no matter what the backend has.
  2. The renderer reads `backbone.installed`. Entries have no such field — the
     boolean is `downloaded`.
- Evidence (director-verified, pasted):
  ```
  utilitiesWorkspace.js:1105   renderWakeBackbones(res?.backbones || [])
  routes_wake.py:301           return {"models": wake_models.list_wake_models()}
  $ .venv/bin/python -c "import wake_models; print(wake_models.list_wake_models()[0])"
  {"id":"melspectrogram","kind":"backbone","origin":"bundled",
   "size_bytes":1087958,"downloaded":true}      <- no `installed` key
  ```
- **Second effect, same root cause:** the wake engine badge
  (`:1104`) is `res.backbones.some(b => b.installed) ? 'Ready' : 'Not installed'`
  — with both bugs it can **never** read "Ready". The screen tells every user
  their wake engine is not installed even when the models are downloaded and
  the feature works.
- **Why it slipped in:** the LLM and Whisper payloads on the *same screen*
  genuinely do use `installed` (`:934, :943-949, :965-982`). The wake payload is
  the odd one out, so the wrong code reads perfectly plausibly.
- Disposition: → fixed as a prerequisite inside task **B-8**, ruled in-scope
  because the Delete action D-0043 authorises would otherwise be unreachable
  dead code. Bounded to the three mismatched reads; the LLM/Whisper `installed`
  reads are correct for their own payloads and must not be touched.

## Settings / Privacy / Voice (QA-SET)

_No entries yet._

## Overlays (QA-OVL)

### QA-OVL-001 · Review Deck Read/Stop second press never posts /tts/stop · RED · VERIFIED
- Found by / date: qa board `91d19b8` / 2026-07-29
- Where: `#readButton`, `app/src/renderer/review-overlay.html:620`;
  scenario `review-overlay-rewrite-instruct-and-read` (`overlay-prod.mjs`)
- Repro: full board run `node app/tests/qa/run.mjs`; second press of Read must
  POST `/tts/stop`; captured request array is empty (Expected 1, Received 0)
- Expected vs actual: toggle stops playback via `/tts/stop` / no request issued
- Evidence **at time of filing**: `app/tests/qa/out/signal-desk-prod/qa-report.md`
  (96/97 header) — captured at `91d19b8`
- **VERIFIED FIXED (director, 2026-07-29, at `545e582`) — see D-0041.** The fix
  landed in `ed1bede`, *before* the baseline this entry was triaged against; the
  QA report was simply never regenerated, so the stale 96/97 header outlived the
  bug. Real defect was two-part: the handler never reset state after the stop
  POST (so the control was a dead end after one use, `review-overlay.html:633`),
  and the scenario checked the capture array flat after a `click()` that
  resolves on dispatch (`overlay-prod.mjs:512-518`). Director re-ran the full
  board three times: **97/97, 97/97, 97/97**, scenario ✅ PASS in all three.
- Disposition: → task **A-1**, closed with **no code change required**

> **Evidence must name the commit it was captured at.** This entry was accurate
> when written and false by the time it was assigned, because a report path
> alone says nothing about *when*. Amended by D-0041, alongside D-0039's
> pasted-output rule.

## Security / privacy boundary (QA-SEC)

### QA-SEC-001 · Wake-model import skips upload_safety · RED · TRIAGED
- Found by / date: remediation reconciliation / 2026-07-29
- Where: `routes_wake.py:390` — raw unbounded `handle.write(await file.read())`
- Expected vs actual: same streamed/size-capped/magic-checked path as
  dictation/clone/OCR / raw unlimited write
- Evidence: code citation, verified at HEAD `be2ebaa`
- Disposition: → task **C-1**

### QA-SEC-002 · Dev routes mounted unconditionally on the backend · YEL · TRIAGED
- Where: `server.py` — `/graph/`, `/intent/`, `/project/`, `/mcp/`, `/llm/process`
- Evidence: absent from Electron `ROUTE_ALLOWLIST` but reachable by anything
  that can reach the port
- Disposition: → task **C-2**

### QA-SEC-003 · project_generator accepts arbitrary target_dir · YEL · TRIAGED
- Where: `project_generator.py`, `routes_foundry.py` — no
  resolve-inside-root check, no system-path refusal
- Disposition: → task **C-3**

## Installer / package (QA-PKG)

_No entries yet — opens with Wave 12 (F-1/F-2)._

## Docs vs code (QA-DOC)

### QA-DOC-001 · Docs' "no GPU" line is imprecise (machine is `igpu`, not dGPU) · YEL · TRIAGED
- Found by / date: publish planning / 2026-07-29; **corrected by director 2026-07-29**
- Where: `KNOWN_LIMITATIONS.md` GPU section; `docs/archive/REMEDIATION_WHATS_LEFT.md` Phase 4
- ~~Original claim: "this machine has a 4060 Ti 16 GB; `get_hardware_tier()` →
  `dgpu-12g+`/`cuda`".~~ **STRUCK — false.** It was written with no pasted
  output and could not be reproduced. `w-docs` refused the task rather than
  write it; the director then verified. See **D-0039**.
- Expected vs actual: docs should name the real tier / docs say "no GPU", which
  reads as "no graphics hardware at all" when the truth is "no *discrete* GPU
  and no CUDA; an integrated one is present and usable"
- Evidence (director-verified on host `Shitbox`, 2026-07-29, HEAD `545e582`):
  ```
  command -v nvidia-smi               → NOT FOUND
  lspci | grep -i nvidia              → (no output)
  glxinfo | grep "OpenGL renderer"    → Mesa Intel(R) Iris(R) Xe Graphics (TGL GT2)
  get_hardware_tier()                 → {"tier":"igpu","gpu_kind":"integrated",
                                         "ram_mb":15632,"cores":4}
  /proc/cpuinfo                       → 11th Gen Intel Core i7-1165G7
  ```
- Disposition: → task **E-1** (rewritten per D-0039 — precision fix, not inversion)

### QA-DOC-002 · Parity totals differ across three docs vs live validator · YEL · TRIAGED
- Where: `RELEASE_BOARD.md` (396/21/21 and 161/10/267), `KNOWN_LIMITATIONS.md`
  (0/4/434); validator says 398/23/17
- Disposition: → task **E-2**

### QA-DOC-004 · QA board silently fails 6 scenarios without two env vars · YEL · OPEN
- Found by / date: w-overlay during A-1 / 2026-07-29, director-confirmed at `545e582`
- Where: `node app/tests/qa/run.mjs`; guard at `app/tests/qa/harness.mjs:602,659`;
  documented requirement at `onboarding-prod.mjs:5-6`, `RELEASE_BOARD.md:103`
- Repro: run the full board with **neither** `BETTERFINGERS_DATA_DIR` nor
  `BF_QA_USER_DATA_DIR` exported → **91/97**, with all 6 `onboarding-prod`
  scenarios failing. Export both to throwaway dirs → **97/97**.
- Expected vs actual: a missing prerequisite should announce itself / the board
  reports 6 ordinary-looking scenario failures, indistinguishable from real
  regressions
- Evidence (director, 2026-07-29, at `545e582`): five runs by `w-overlay`
  (2× without the vars → 91/97; 3× with → 97/97) and three by the director
  with the vars → 97/97, 97/97, 97/97
- **Why this is not cosmetic:** the guard is correct — it fail-closes rather
  than touching the real user-data root. The problem is the *reporting*. An
  operator who runs the board the obvious way sees 6 red scenarios and has no
  way to tell a setup gap from a real break. This wave has already burned
  effort on one stale QA figure (D-0041); this is the same failure shape
  waiting to happen to the operator.
- Disposition: (director) → fold into the operator QA runbook as a required
  pre-step, and file a D-series task if the board should detect the missing
  vars and say so instead of failing 6 scenarios

### QA-DOC-003 · Lifespan migration + Finding #3-residual reported open; both landed · GRN · TRIAGED
- Where: `docs/archive/REMEDIATION_WHATS_LEFT.md`
- Evidence: `server.py:2353/:2366`; `wipeSummary.mjs` dict handling
- Disposition: → task **E-3**

### QA-DOC-005 · The QA board and the Python suite need OPPOSITE environments · YEL · TRIAGED
- Found by / date: director, during final verification / 2026-07-30
- Where: `BETTERFINGERS_DATA_DIR` + `BF_QA_USER_DATA_DIR`
- **The trap:** those two variables are *required* for the QA board (without
  them, 6 onboarding scenarios fail — QA-DOC-004) and *poisonous* for pytest
  (with them exported, **42 tests fail**).
- Evidence (director-verified, same commit `3d935c6`, back to back):
  ```
  with the two vars exported   -> 42 failed, 3056 passed
  env -u both                  -> 0 failed,  3098 passed
  pre-wave main, env -u both   -> 0 failed,  3074 passed
  ```
  The failures are pollution, not defects: `tests/test_voice_presets.py` passes
  28/28 in isolation and 45/45 under `-k voice_preset`.
- **Why it matters:** the failure mode is a *false alarm that looks exactly like
  a regression*. It cost the director a full diagnostic cycle, including a
  worktree comparison against pre-wave `main`, before it resolved to an
  environment leak. The next person deserves the sign.
- Disposition: documented in [`OPERATOR_QA.md`](OPERATOR_QA.md) §0. A better fix
  post-publish is for `conftest.py` to refuse to run when those variables are
  set, so the trap announces itself instead of producing 42 red herrings.

## Backlog / out of scope this release (QA-BL)

_Ideas land here instead of in code. Director reviews after publish._

### QA-BL-001 · Parity tooling counts dead `glitch-ring.js` as production · YEL · TRIAGED
- Found by / date: w-parity2 during B-7 / 2026-07-29; director-verified at `323ba30`
- Where: `tools/parity_evidence.py:49-51` —
  `PROD_EXTRA_PAGES = ((RENDERER/"overlay.html", RENDERER/"glitch-ring.js"), …)`
- Evidence (director-verified, pasted):
  ```
  app/src/renderer/overlay.html:56   import { createSignalCore } from './signalCore.js';
  app/src/renderer/overlay.html:64   "...reused here instead of glitch-ring.js so..."
  $ grep -rn "glitch-ring" app/src --include=*.js --include=*.html --include=*.mjs \
        | grep -v "^app/src/renderer/glitch-ring.js"
  (only comment references — NOTHING imports it)
  ```
- Expected vs actual: the production closure reflects what the shipping windows
  load / it includes a file the overlay stopped loading when it was rewritten
  onto `signalCore.js`
- **Why this is filed and not fixed:** repointing the mapping changes the
  production closure for **all 438 rows** and could silently flip unrelated ones
  at the finish line. That needs a churn proof (`tools/parity_churn.py`), which
  is post-publish work. Related to parked board item #1, which records a
  separate known attribution defect in the same tooling.
- **Mitigation already shipped:** B-7 added enumeration-driven state coverage for
  **both** `glitch-ring.js` and `signalCore.js`, so UI-12-003's underlying claim
  is true whichever file the tool inspects. The ledger's bookkeeping is stale;
  the tested behavior is not.
- Disposition: post-publish — repoint `PROD_EXTRA_PAGES` at `signalCore.js`,
  regenerate, prove zero unintended status churn, then re-decide UI-12-003.
