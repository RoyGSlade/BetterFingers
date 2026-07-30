# PUBLISH PLAN — the one document for shipping BetterFingers

- **Objective (the only one):** Publish `v0.2.0-alpha.1` — Linux AppImage + Windows
  .exe — where every shipped feature is **clean, hardened, and simple to set up**,
  and a first-time user is never overloaded.
- **HEAD at writing:** `be2ebaa` (2026-07-29). Verified live: parity ledger
  **398 wired / 23 intentional_cut / 17 blocked**, QA board **96/97**, Python suite
  3074 passed, Node suite 1638 passed.
- **This document supersedes** `docs/archive/REMEDIATION_WHATS_LEFT.md` for planning purposes.
  `RELEASE_BOARD.md` remains the gate authority; this doc is the work queue that
  gets its remaining gates accepted.
- **QA issues found by anyone go to** [`QA_NOTES.md`](QA_NOTES.md) — never into
  this file, never into ad-hoc TODOs.

---

## 1. Scope freeze — the anti-creep contract

Scope creep is the named enemy. These rules bind every session, worker, and
supervisor working from this plan:

1. **No new features.** The feature set is what `signal-desk.html` ships today.
   Work is limited to: closing the 17 parity rows, fixing what QA finds,
   hardening listed items, and packaging.
2. **Cut beats build.** When a parity row or QA finding would require building
   something new, the default answer is `intentional_cut` with a named
   replacement — building it requires a director decision recorded in
   `DECISIONS.md`.
3. **Every task below has a fixed file list.** A worker touching files outside
   its task's list has failed the task, even if the change is good. Flag the
   idea in `QA_NOTES.md` §Backlog instead.
4. **Deferred means deferred.** Section 7 lists everything explicitly out of
   scope. Do not "quickly also fix" anything in it.
5. **One task, one commit** (or a small commit series). No omnibus commits.

## 2. Definition of "publishable"

All of the following, nothing more:

- [ ] Parity ledger reads `N wired / M intentional_cut / 0 blocked` (Gate 11)
- [ ] Production QA board 97/97, **three consecutive** full-board green runs
- [ ] The four hardening items in WS-C are closed (they are user-safety, not polish)
- [ ] Operator QA checklist (§6) completed; all RED findings in `QA_NOTES.md` fixed
- [ ] First-run flow passes the §5 simplicity bar on a wiped data dir
- [ ] Wave 12 package qualification: AppImage + .exe built, installed, and
      smoke-tested on real machines (installer pipeline already proven green
      once at `8d2f180` — this is re-qualification at release HEAD, not new work)
- [ ] Release docs corrected (WS-E) so published claims match the code

Signing stays **out** of the alpha bar (see §7) unless the director reverses
D-marked precedent — record either way in `DECISIONS.md`.

---

## 3. Work breakdown — sized for Sonnet workers, reviewed by Opus

**Task format contract.** Every task states: *Objective* (one sentence), *Files*
(exclusive claim list), *Done when* (mechanically checkable), *Review* (the exact
commands the Opus reviewer runs — the reviewer runs them independently; a task is
`COMPLETE` only after that review passes). Status vocabulary: `OPEN`,
`IN PROGRESS`, `NEEDS REVIEW`, `COMPLETE`, `REJECTED (reason)`.

### WS-A — Fix the one broken QA scenario (blocks the 97/97 bar)

#### A-1 · Review Deck Read/Stop toggle drops `POST /tts/stop` · `OPEN`
- **Objective:** Second press of `#readButton` in the review overlay must issue
  `POST /tts/stop`; today the captured request array is empty and
  `review-overlay-rewrite-instruct-and-read` fails (the director ruled it
  "genuinely broken… needs a real fix, not a rerun").
- **Files:** `app/src/renderer/review-overlay.html` (toggle handler ~line 620),
  `app/tests/qa/scenarios/overlay-prod.mjs`; if the fault is request capture,
  also the main-process capture path — but then STOP and report which file
  before claiming it.
- **Done when:** the scenario passes inside the **full** board, not standalone,
  and the root cause is written up in the commit message (was it the toggle, a
  race, or the capture path?).
- **Review (Opus):** run `node app/tests/qa/run.mjs` (no filter) **three times**;
  all three must be 97/97. Read the diff: the fix must change behavior, not
  loosen the assertion. Any weakened assertion = `REJECTED`.

### WS-B — Close the 17 blocked parity rows (Gate 11)

Ground rules for all B-tasks: the ledger is regenerated with
`python3 tools/parity_ledger_build.py` and checked with
`python3 tools/parity_validator.py`; hand-declared anchors go in
`tools/parity_anchors.py`; a row may move only to `wired` (with real evidence)
or `intentional_cut` (with a named replacement or a director decision). No row
is ever edited by hand in `PARITY_INVENTORY.md`.

#### B-1 · Onboarding evidence rows: UI-02-005, UI-02-007, UI-02-012 · `OPEN`
- **Objective:** Three onboarding rows (Welcome step, "How it works" step,
  keyboard trap) have no code handle in the source row; declare their production
  anchors and make a production-target QA assertion name them.
- **Files:** `tools/parity_anchors.py`,
  `app/tests/qa/scenarios/onboarding-prod.mjs`, regenerated ledger.
- **Done when:** all three rows are `wired` in a regenerated ledger; the QA
  scenario genuinely asserts the behavior (focus trap actually traps Tab,
  Escape is actually swallowed), not just element existence.
- **Review (Opus):** `python3 tools/parity_validator.py` shows blocked count
  reduced by exactly 3; run the onboarding-prod scenario; read the assertions —
  existence-only checks for the keyboard-trap row = `REJECTED`.

#### B-2 · Talk evidence rows: UI-06-063, UI-06-074, UI-06-076 · `OPEN`
- **Objective:** Same shape as B-1 for Talk (event-driven refresh surfaces,
  assessment/delivery/clarification regions, preservation warnings): declare
  anchors, name them in production-target QA or unit tests.
- **Files:** `tools/parity_anchors.py`, the relevant
  `app/tests/qa/scenarios/*-prod.mjs` or `app/tests/*.test.mjs`, regenerated ledger.
- **Done when:** all three rows `wired` in a regenerated ledger.
- **Review (Opus):** validator delta = exactly 3; spot-run the named tests;
  confirm each anchor exists in `signal-desk.html` (grep, don't trust).

#### B-3a · Delivery = Paste only; cut UI-06-038 · `OPEN` *(ruled — D-0036)*
- **Objective:** Per **D-0036**, the release delivers by Paste only. Declare
  UI-06-038 (`#sendActionSelect`) `intentional_cut` with named replacement
  `#sdDeliverySegmented`, and reduce that segmented control
  (`signal-desk.html:3211`, Type / Paste / Copy) to **Paste** on the shipping
  page. Do **not** rebuild the legacy five-option dropdown; do **not** touch
  `perform_output_action()` — the backend keeps accepting all three actions.
- **Files:** `app/src/renderer/signal-desk.html` (**integration-owned — the
  claim must come from the director**), `app/src/renderer/features/talkWorkspace.js`,
  the cut declaration + regenerated ledger, and whichever prod QA scenario
  covers Talk delivery.
- **Done when:** the shipping page offers no delivery choice but Paste; a
  dictation still delivers end-to-end; UI-06-038 reads `intentional_cut`;
  ledger blocked count drops 17 → 16.
- **Careful — do not "fix" this:** `gaming_policy.resolve_send_action()`
  converts `paste` → `copy_only` while a gaming profile is active. That
  downgrade is deliberate (synthetic input reaches the game's movement keys)
  and must survive. A diff that removes it = `REJECTED`.
- **Review (Opus):** `python3 tools/parity_validator.py` shows blocked 16;
  grep `signal-desk.html` for any remaining Type/Copy delivery option; run
  `.venv/bin/python -m pytest -q -k "gaming or send"` and confirm the gaming
  downgrade still passes; run the Talk prod scenario.

#### B-3b · Recording toggle: UI-06-016 — DIRECTOR DECISION FIRST · `BLOCKED (needs ruling)`
- **Objective:** `#toggleRecordingButton` is only partially anchored in
  production — some handles resolve on the shipping page, some don't. Decide
  wire-vs-cut. **D-0036 explicitly did not rule on this row.**
- **Step 0 (director, not a worker):** record the ruling in `DECISIONS.md`.
  Only then spawn the worker.
- **Files (if wired):** `app/src/renderer/signal-desk.html`, the owning
  feature module, a prod QA scenario. **(if cut):** cut declaration +
  regenerated ledger.
- **Done when:** the row is `wired` or `intentional_cut` per the ruling.
- **Review (Opus):** ruling exists in `DECISIONS.md` *before* the work commit;
  validator delta = 1; if wired, run the scenario.

#### B-4 · Persona Wizard QA: UI-07-051 · `OPEN`
- **Objective:** The four-step Persona Wizard (`.sd-persona-flow`,
  `features/personaFlow.js`) is fully anchored in production but no prod-target
  QA or unit test names its anchors — write that coverage.
- **Files:** a new or extended prod-target scenario (e.g.
  `app/tests/qa/scenarios/personas-prod.mjs`) and/or
  `app/tests/personaFlow.test.mjs`, regenerated ledger.
- **Done when:** the row is `wired`; the scenario walks all four steps
  (advance, back, finish) on the production page.
- **Review (Opus):** validator delta = 1; run the scenario; a scenario that
  only opens step 1 = `REJECTED`.

#### B-5 · Voice defaults + blend: UI-07-126, UI-07-127, UI-15-012 · `OPEN`
- **Objective:** Voice-preset make-default/clear-default
  (`setDefaultVoicePreset`/`clearDefaultVoicePreset`) and the voice-blend cards
  (`#sdVoiceBlendCards`) are anchored but unevidenced; name them in prod-target
  QA/unit tests. **First check** whether a UI trigger for make/clear-default
  actually exists in production — if not, this is a B-3-style decision, escalate
  to the director instead of building one.
- **Files:** relevant prod scenario + unit tests, `tools/parity_anchors.py`,
  regenerated ledger.
- **Done when:** all three rows resolved (`wired`, or escalated with a written
  finding of "no UI trigger exists").
- **Review (Opus):** validator delta accounts for all 3; run named tests;
  verify the make-default trigger claim by grepping `signal-desk.html` and
  `features/` yourself.

#### B-6 · Blend/modulation chips: UI-07-133, UI-07-134, UI-07-138 · `OPEN`
- **Objective:** Quick-blend chips (`[data-blend-preset]`), the Modulation
  umbrella row, and quick-modulation chips (`[data-mod-preset]`) have no code
  handle; declare anchors and evidence them. The new
  `voiceStudioModulationContract.test.mjs` (landed 2026-07-29) may already carry
  part of this — bind to it rather than duplicating.
- **Files:** `tools/parity_anchors.py`, `app/tests/voiceStudioModulationContract.test.mjs`
  or a prod scenario, regenerated ledger.
- **Done when:** all three rows resolved; chips proven present *and* functional
  (clicking a chip changes the bound slider values) on the production page.
- **Review (Opus):** validator delta = 3; run the tests; a presence-only chip
  check = `REJECTED`.

#### B-7 · Ring states: UI-12-003 · `OPEN`
- **Objective:** The overlay ring's `STATE_STYLES` (idle, listening, recording,
  transcribing, stitching, ready, error, warning + aliases) are anchored but no
  test names them — write a unit test asserting every state in the contract
  exists with a distinct style, and that unknown states fall back safely.
- **Files:** new `app/tests/glitchRingStates.test.mjs` (or extend an existing
  overlay test), `tools/parity_anchors.py` if needed, regenerated ledger.
- **Done when:** the row is `wired`.
- **Review (Opus):** validator delta = 1; run the test; the test must enumerate
  the states from the shipped `STATE_STYLES`, not a copied list that can drift.

#### B-8 · Wake model deletion: UI-15-014 · `OPEN`
- **Objective:** `deleteWakeModel()`/`DELETE /wake/models/:id` is exported with
  reportedly no UI trigger — verify whether production has one; if yes, evidence
  it; if no, escalate for a wire-or-cut decision (do not silently build UI).
- **Files:** investigation first; then either a prod scenario/unit test, or a
  written escalation in `QA_NOTES.md` §Settings.
- **Done when:** row resolved or escalated with evidence.
- **Review (Opus):** validator delta = 1 (or a written escalation the director
  has ruled on); grep for the trigger yourself before accepting either claim.

### WS-C — Hardening (user-safety items that gate publishing)

#### C-1 · Wake-model upload bypasses `upload_safety` · `OPEN`
- **Objective:** `routes_wake.py:390` does a raw, unbounded
  `handle.write(await file.read())` with no size cap or magic-byte check while
  every other upload path (dictation, TTS clone, OCR) goes through
  `upload_safety.stream_to_file`/`validate_signature` — unify it.
- **Files:** `routes_wake.py`, `upload_safety.py` (only if a new signature type
  is needed), plus a test in `tests/` covering oversize + wrong-magic rejection.
- **Done when:** wake import streams through `upload_safety` with the same
  limits; new tests pass; full wake test selection passes
  (`.venv/bin/python -m pytest -q -k wake`).
- **Review (Opus):** read the diff — no raw `await file.read()` remains in
  `routes_wake.py`; run the wake selection and the new tests.

#### C-2 · Unguarded dev routes exposed on the backend · `OPEN`
- **Objective:** `/graph/`, `/intent/`, `/project/`, `/mcp/`, `/llm/process`
  are mounted unconditionally in `server.py`; the Electron allowlist can't reach
  them but anything that can reach the port directly can — gate them behind a
  dev flag (e.g. `BETTERFINGERS_DEV_ROUTES=1`), default off.
- **Files:** `server.py` (mount sites only), one new test
  `tests/test_dev_route_gating.py` asserting 404/403 by default and available
  with the flag.
- **Done when:** default-off proven by test; existing suites green (the QA stub
  backend and dev boot must still work — set the flag where dev tooling needs it).
- **Review (Opus):** run the new test both ways; grep `server.py` for any of the
  five prefixes mounted outside the guard; run
  `.venv/bin/python -m pytest -q -k "server or routes"` for regressions.

#### C-3 · `project_generator` accepts arbitrary `target_dir` · `OPEN`
- **Objective:** `project_generator.py` (and its caller `routes_foundry.py`)
  takes an arbitrary target path with no resolve-inside-allowed-root check and
  no system-path refusal — add a fail-closed guard (resolve, must be inside the
  user-selected/allowed root, refuse system paths and traversal).
- **Files:** `project_generator.py`, `routes_foundry.py`, new tests (traversal,
  absolute system path, symlink escape).
- **Done when:** guard is fail-closed; tests prove the three escape shapes are
  refused with honest HTTP errors; foundry tests green.
- **Review (Opus):** attempt one escape the tests *don't* cover (reviewer picks);
  if it passes through, `REJECTED`.

#### C-4 · Finish the wipe-gate unification (plan item 2.3) · `OPEN`
- **Objective:** `_reject_if_wiping` exists (`server.py:316`, 6 call sites) but
  8 raw `privacy_wipe_in_progress.is_set()` checks remain — route every
  write-path check through the one gate so wipe-blocking behavior is uniform.
- **Files:** `server.py` only; extend existing wipe tests if a converted site
  lacks coverage.
- **Done when:** `grep -c "privacy_wipe_in_progress.is_set()" server.py` returns
  only the gate's own internal use; wipe/privacy test selection green.
- **Review (Opus):** run the grep and
  `.venv/bin/python -m pytest -q -k "wipe or privacy"`; read each converted
  site — response shape for blocked writes must be unchanged.

#### C-5 · CI gates: Ruff + Bandit + `npm audit` · `OPEN` *(three sub-tasks, one worker each)*
- **Objective:** `.github/workflows/` has zero lint/security gates — add
  `ruff check` (C-5a), `bandit` on the backend (C-5b), and
  `npm audit --omit=dev` (C-5c) as CI jobs. First run of each is
  report-only; promoting to fail-the-build happens only after its baseline is
  clean or triaged in `QA_NOTES.md` §Backlog.
- **Files:** `ci.yml` (or a new workflow file per gate), any config file the
  tool needs (`ruff.toml` etc.). **No product code changes in these tasks** —
  fixing findings is separate follow-up work.
- **Done when:** the job runs green (report-only) on a PR/branch push.
- **Review (Opus):** confirm the workflow triggered and uploaded/printed its
  report; confirm zero product-code changes snuck in.

### WS-D — First-time-user flow (simplicity is the feature)

The bar (§5) is enforced by operator QA, not by speculative building. Only two
build tasks exist up front; everything else must come out of `QA_NOTES.md`
findings.

#### D-1 · First-run walkthrough audit on a wiped data root · `OPEN`
- **Objective:** Script and record the complete first-run path (fresh
  `BETTERFINGERS_DATA_DIR`): onboarding steps → consent → landing on Talk →
  first dictation. Count every decision the user is forced to make before their
  first successful dictation; list each against the §5 bar. **This task changes
  no code** — it produces a findings report in `QA_NOTES.md` §First-run.
- **Files:** none (report-only).
- **Done when:** the report exists with a numbered decision list, screenshots
  or QA-runner evidence, and a pass/fail against each §5 rule.
- **Review (Opus):** re-run the walkthrough independently on a fresh dir; the
  report must match what the reviewer sees.

#### D-2 · Per-feature "set up & personalize" paths · `OPEN`
- **Objective:** For each of the five workspaces, verify there is exactly one
  obvious place to set the feature up and personalize it (Talk: send action +
  hotkeys; Library: nothing to set up — verify empty states; Studio: persona
  wizard; Utilities: model download/doctor; Settings: profile save/wipe/voice).
  Report-only, same shape as D-1, filed per-screen in `QA_NOTES.md`.
- **Files:** none (report-only).
- **Done when:** five per-screen reports filed with pass/fail per §5.
- **Review (Opus):** spot-verify two screens independently.

Fix tasks born from D-1/D-2 findings get IDs `D-3+`, sized one-screen-one-task,
and follow the standard format. The director triages which findings become
tasks — not the workers.

### WS-E — Make the docs stop lying (small, mechanical)

#### E-1 · Correct the GPU claims · `OPEN`
- **Objective:** `KNOWN_LIMITATIONS.md` ("this machine… no GPU") and
  `docs/archive/REMEDIATION_WHATS_LEFT.md` (Phase 4 "concretely confirmed" no-GPU) are
  wrong — this machine has an RTX 4060 Ti 16 GB and
  `hardware_report.get_hardware_tier()` returns `dgpu-12g+`/`cuda`. Correct
  both; keep the CPU-only tier documented as a supported configuration.
- **Files:** `docs/release/KNOWN_LIMITATIONS.md`, `docs/archive/REMEDIATION_WHATS_LEFT.md`.
- **Review (Opus):** run the tier probe; grep both files for "no GPU".

#### E-2 · Reconcile parity numbers everywhere they appear · `OPEN`
- **Objective:** The live validator says 398/23/17 but `RELEASE_BOARD.md`'s
  header says 396/21/21, its evidence ledger row says 161/10/267, and
  `KNOWN_LIMITATIONS.md` says 0/4/434. Update every stale citation to either
  the live number or an explicitly dated historical baseline.
- **Files:** `docs/release/RELEASE_BOARD.md`,
  `docs/release/KNOWN_LIMITATIONS.md`, `docs/release/archive/WAVE11_BLOCKERS.md`
  (banner note only).
- **Review (Opus):** run the validator; grep all three files for `434`, `267`,
  `396` — every hit must be dated-historical or gone.

#### E-3 · Retire stale REMEDIATION_WHATS_LEFT claims · `OPEN`
- **Objective:** Mark the lifespan migration (landed at `server.py:2353`,
  `:2366`, zero `@app.on_event` remaining) and Finding #3-residual (fixed —
  `wipeSummary.mjs` handles the `{ok, recreated}` dict) as closed; point the
  doc's "How to resume" at this plan.
- **Files:** `docs/archive/REMEDIATION_WHATS_LEFT.md`.
- **Review (Opus):** grep `server.py` for `on_event`; read
  `isDeletionOutcome()`; confirm doc now matches.

### WS-F — Package qualification (Wave 12; starts only when Gate 11 is accepted)

#### F-1 · Build + qualify Linux AppImage at release HEAD · `BLOCKED (Gate 11)`
- **Objective:** Re-run the proven installer pipeline at the release commit;
  install on a clean machine/VM; run the operator smoke (§6.8).
- **Review (Opus + operator):** artifact hashes recorded in
  `PACKAGE_BASELINE.md`; operator smoke checklist signed off.

#### F-2 · Build + qualify Windows .exe at release HEAD · `BLOCKED (Gate 11)`
- Same shape as F-1. Unsigned per §7 unless the director rules otherwise.

---

## 4. Orchestration protocol (director + supervisors + Sonnet workers)

- **Hierarchy:** director (this plan's owner) → Opus supervisors (own room) →
  Sonnet workers. Hard caps: **2 Opus / 4 Sonnet repo-wide** — the `/hierarchy`
  skill is the authority on spawning; `/wake` covers keepalive.
- **Sessions MUST start from the repo root** (`~/Desktop/BetterFingers`), never
  `~/Desktop` — off-root sessions silently disable file-claim enforcement.
- **Claims:** a worker claims exactly its task's file list before editing.
  `server.py`, `signal-desk.html`, `app/package.json` and the other
  integration-owned paths in `RELEASE_BOARD.md` need a director-granted claim.
- **Full test suite:** claim the `__full-test-suite__` pseudo-path first
  (memory-heavy); targeted selections don't need it.
- **Sizing rule:** if a worker can't state the task's Done-when as a command it
  can run, the task is too big — the supervisor splits it before spawning.
- **Review rule (the only path to COMPLETE):** the worker hands off with its
  evidence; the Opus reviewer *independently re-runs* the task's Review
  commands and reads the diff. Reviewer accepts (`COMPLETE`), or rejects with a
  one-line reason (`REJECTED (…)`) and the task reopens. Workers never mark
  their own tasks complete. Self-reported green is not evidence.
- **Suggested batching for 4 Sonnet slots:** lane 1: WS-B evidence rows
  (B-1→B-2→B-4→B-6→B-7); lane 2: WS-C (C-1→C-4→C-2→C-3); lane 3: WS-A (A-1 —
  hardest, give it a dedicated worker); lane 4: WS-E then C-5 then WS-D
  reports. B-3a is ruled and ready; B-3b/B-5/B-8 wait for director decisions.

## 5. The simplicity bar (what "don't overload the first-time user" means)

A screen/flow **passes** iff:

1. First successful dictation requires **≤ 3 decisions** after consent
   (mic OK, hotkey OK, go).
2. Every setup step has a working default — "just keep going" always works.
3. Personalization (persona, voice, blend, send action) is **discoverable but
   never demanded**: no modal, no badge-nag, no blocking step for any of it.
4. Every screen's empty state says what the screen is for and gives exactly
   **one** primary action.
5. No error state dead-ends: every failure surface offers retry or points at
   the Doctor.
6. Advanced controls (modulation curves, wake tuning, injection pacing) are
   behind a disclosure, not on the first paint of the screen.

Violations are QA findings (→ `QA_NOTES.md`), triaged by the director into
D-series tasks. The bar is a *test*, not a license to redesign.

## 6. Operator QA checklist (for Donaven — things only a human can judge)

Work through per screen; file every issue in `QA_NOTES.md` under that screen's
section with a severity (RED = blocks publish / YEL = fix if cheap / GRN = note).

**6.1 First run** (wiped `BETTERFINGERS_DATA_DIR`)
- [ ] Onboarding: step count feels short; copy is plain; Escape/Tab trapped
- [ ] Consent: clear what's being consented to; declining behaves honestly
- [ ] Land on Talk; first dictation succeeds within 3 decisions (§5.1)

**6.2 Talk**
- [ ] Record → review → send loop feels immediate; ring states match reality
- [ ] Retry on a failed draft works; nothing claims success that didn't happen
- [ ] Hotkeys: push-to-talk on X11; degraded toggle mode on Wayland is honest

**6.3 Library**
- [ ] Empty states (no selection, no data) explain themselves
- [ ] History/dictionary refresh doesn't blank on a failed fetch

**6.4 Studio**
- [ ] Persona wizard: 4 steps flow forward/back cleanly; finish lands somewhere sensible
- [ ] Persona is optional — skipping it costs nothing (§5.3)

**6.5 Utilities**
- [ ] Doctor: run, fail, re-run — cards persist, button re-enables
- [ ] Model download/status honest; sidecar logs readable

**6.6 Settings**
- [ ] Profile save/load; validation blocks save with a visible reason
- [ ] Privacy wipe: all three modes preview correctly; wiped things are listed
      honestly (including history DB); nothing writes during a wipe
- [ ] Voice presets/blend/modulation: defaults sound right; chips do something

**6.7 Overlays**
- [ ] Ring overlay states track a real dictation end-to-end
- [ ] Review overlay: rewrite-instruct works; **Read then Stop actually stops** (A-1)

**6.8 Package smoke** (after F-1/F-2)
- [ ] Fresh install → first dictation on a machine with no dev tooling
- [ ] Uninstall/reinstall keeps or wipes data per what the UI promised
- [ ] **Gate 10 hardware pass:** controller + Stream Deck per `WAVE10_QA.md`
      (only if devices are on hand; otherwise director records it as deferred)

## 7. Explicitly deferred — the scope-creep graveyard (do not touch)

| Deferred item | Why it can wait | Revisit |
|---|---|---|
| Remediation Phase 3 (support-report privacy split) | Redaction exists (`log_redaction.py`); the split is a refactor, not a leak fix | post-publish |
| Phase 4 (AcceleratorKind / runtime manifest) | App runs correctly CPU-only and on CUDA today; this is architecture | post-publish |
| Phase 6/7 line-count DoDs (`server.py` <300 etc.) | Modularization is structural health, invisible to users | Wave 14 |
| Phase 9 (KISS adapter boundary) | Zero user-facing effect | Wave 14 |
| 2.1b review comments (graph_data sensitivity, `opt_in_wipe`, docstrings) | Real but tiny and non-blocking; batch post-publish | post-publish |
| Contacts completion / audience enable / persona traits enable | Gated features stay off; already honest in the UI | next release |
| Signed installers (8.5) | Alpha ships unsigned; signing needs credentials that don't exist yet | before public beta |
| macOS build | Never in scope for this release | someday |
| Light theme | Dark-only is a recorded Wave 12 limitation | next release |
| Controller/Stream Deck hardware matrix | Software-qualified; hardware needs the operator + devices | §6.8 or deferred by decision |
| Legacy `index.html` extraction | It's the rollback path, not the product | Wave 14 |

Anything not in this plan and not in this table is **new scope** and needs a
director decision before any work happens.
