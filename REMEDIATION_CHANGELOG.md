# BetterFingers Remediation — Change Log

This log is the coordination point for the phased remediation. Each work
iteration reads it, does one bounded/committable chunk, and appends here.
**Never mix unrelated behavior changes in one commit.** Work happens on branch
`remediation/phased-loop`.

> ## 🛑 STOP CONDITION (standing instruction from the user, 2026-07-17)
> Keep looping until **every** phase (1–9) and its Definition of Done is
> complete — i.e. every item in the phase/task tracker below is ✅. When that
> is true, the loop must **self-terminate**:
> 1. Call `CronList`, find the recurring remediation job (prompt contains
>    "BetterFingers remediation plan"), and `CronDelete` it.
> 2. Send a one-line completion notice via `PushNotification`.
> 3. Do **not** schedule any further work.
>
> Until then, each iteration just does the next chunk and updates this file.
> If a phase is genuinely blocked (needs hardware, external creds, or a
> product decision), record the blocker here, mark it ⛔, and move to the next
> unblocked task rather than stalling the loop.

---

## Baseline (Phase 0 — recorded 2026-07-16)

Reference baseline claimed by the plan; treated as the "must stay green" bar.
Full suites are **not** re-run inside a 3-minute loop iteration — targeted
checks (`py_compile`, focused `pytest`) are used per chunk instead.

| Signal | Baseline |
| --- | --- |
| Python tests | 1,229 passing |
| Electron unit tests | 40 passing |
| Production build | passing |
| CodeQL | passing |
| E2E CI | passing |

Repo state at Phase 0: branch `main`, clean tree, up to date with `origin/main`.
A `feat/windows-vulkan-fallback` branch already exists (Phase 4-related, not
touched by this loop yet).

### Release levels

| Level | Requirements |
| --- | --- |
| Development | Existing tests remain green |
| Friends alpha | Phases 1–4 complete |
| Public alpha | Phases 1–7 complete, signed installers |
| 1.0 | Reliability benchmark, injection matrix, DataRegistry, modular architecture complete |

---

## Phase / task tracker

Legend: ✅ done · 🚧 in progress · ⬜ not started

- **Phase 0 — Baseline** 🚧
  - ✅ 0.a Create tracking changelog (this file)
  - ⬜ 0.b Regression-test placeholders for every confirmed issue
- **Phase 1 — Truthful privacy wipe** ✅ (release blocking)
  - ✅ 1.1 Correct the HTTP contract (`/privacy/wipe` no longer 200 on failure)
  - ✅ 1.2 Make the renderer defensive (`if (!result?.ok) throw`; show what/why/retry)
  - ✅ 1.3 End-to-end contract tests: route status mapping, renderer summary unit tests,
    and failure-injection through the route — history-DB recreation → 500, voice deletion
    → 500, empty wipe → 200, populated wipe → 200. Pipeline-quiesce / output-drain /
    recording-remains covered by `test_privacy_wipe_verified.py`.
- **Phase 2 — Unified data-lifecycle (DataRegistry)** ⬜ (release blocking)
- **Phase 3 — Support-report privacy** ⬜ (release blocking)
- **Phase 4 — Runtime & process boundaries** ⬜ (release blocking)
- **Phase 5 — API/renderer security boundary** ⬜
- **Phase 6 — Backend modularization** ⬜
- **Phase 7 — Renderer modularization** ⬜
- **Phase 8 — Quality/dependency/release gates** ⬜
- **Phase 9 — KISS boundary** ⬜

---

## Iteration log

### Iteration 1 — 2026-07-16 — Phase 0 + Phase 1.1

**Context found.** The backend already computes a *truthful* wipe result:
`server._perform_privacy_wipe()` quiesces the pipeline, drains output, deletes,
verifies postconditions, and returns `{ok, error, message, cleared,
postconditions}`. Function-level truthfulness is well covered by
`tests/test_privacy_wipe_verified.py`. **The only defect at the HTTP layer was
that the route returned every result as HTTP 200**, so a failed wipe looked
successful to any HTTP client.

**Changed.**
- `server.py`: `/privacy/wipe` route now maps the result to an honest status
  via new `_wipe_status_code()` helper, returning a `JSONResponse`:
  - `200` — every postcondition passed (`ok is True`)
  - `409` — `wipe_already_running` or `pipeline_did_not_quiesce`
  - `503` — `output_did_not_quiesce` (a subsystem could not drain)
  - `500` — `ok is False` with no pre-deletion abort code (deletion ran but a
    postcondition/verification failed)
  The structured payload is preserved byte-for-byte; `_perform_privacy_wipe`
  return type is unchanged so all existing function-level tests still pass.
- `tests/test_privacy_wipe_contract.py`: new route-level contract test
  asserting the status/payload mapping for success, already-running (409),
  pipeline-stall (409), output-stall (503), and postcondition-failure (500).

**Why.** Phase 1.1 definition of done: "an unsuccessful operation does not
return HTTP 200 as though it succeeded." Backend already knew the truth; the
route was laundering it into a 200.

**Verification.** `python -m py_compile server.py` + focused
`pytest tests/test_privacy_wipe_contract.py tests/test_privacy_wipe_verified.py`.

**Next up →** Phase 1.2: make the renderer defensive. Find the privacy-wipe
handler in `app/src/renderer/main.js`, ensure it throws unless
`result?.ok === true`, and surface what was deleted / what was not / which
postcondition failed / whether retry is safe. Never display "Your data was
wiped" unless `ok === true`.

### Iteration 2 — 2026-07-17 — Phase 1.2 (renderer defensive)

(Note: a first attempt at this chunk on 2026-07-16 was interrupted before any
edit; it made read-only investigation only. Nothing to revert. Resumed here.)

**Context found.** `wipeData()` → `postJson` → `proxyRequest` in
`app/src/renderer/api/backend.js` already *throws* on any non-2xx, and
`errorMessageFromBody` reads `body.message` — so Phase 1.1's new 409/500/503
statuses already route a failed wipe into `handleWipeData`'s catch. Two gaps
remained: (1) the success path set "Your data was wiped." **without checking
`result.ok`** (no defense against a 200-with-ok:false), and (2) failures did
not surface *what* remained / which postcondition failed / retry safety.

**Changed.**
- `app/src/renderer/lib/wipeSummary.mjs` (new): pure, DOM-free helper —
  `summarizeWipeFailure()`, `failedPostconditions()`, `isPreDeleteAbort()`,
  `WIPE_PRE_DELETE_ABORTS`. Same testable pattern as `lib/draftSummary.mjs`.
  Distinguishes pre-deletion aborts ("Nothing was deleted. Safe to retry.")
  from partial failures (lists the postconditions that did not verify, counts
  leftover recordings, notes retry is safe).
- `app/src/renderer/api/backend.js`: `proxyRequest` now attaches `error.body`
  (the full parsed payload) to thrown non-2xx errors so callers can inspect
  structured detail. Minimal additive change; no behavior change for existing
  callers.
- `app/src/renderer/main.js`: `handleWipeData` now (a) throws unless
  `result?.ok === true` even on HTTP 200 (defense in depth), and (b) renders a
  truthful failure message via `summarizeWipeFailure` from either the returned
  body or `error.body`. "Your data was wiped." is shown only when `ok === true`.
- `app/tests/wipe-summary.test.mjs` (new): 5 unit tests for the helper.

**Why.** Phase 1.2 DoD: never display success unless `result.ok === true`; show
what was/wasn't deleted, which postcondition failed, and retry safety.

**Verification.** `node --check` on all three changed JS files; `node --test`
on the new + existing renderer suites → **27 passed, 0 failed**. (Full Electron
E2E not run inside the loop; the pure helper is covered by unit tests.)

**Next up →** Phase 1.3: close the remaining end-to-end contract-test cases so
Phase 1 can be marked done. Add backend failure-injection tests proving
`ok:false` + the right HTTP status when (a) history-DB recreation fails and
(b) voice deletion fails (patch `history_store.wipe_database` /
`shutil.rmtree` to fail, assert 500 through the route). Then flip Phase 1 to ✅
and begin Phase 2 (DataRegistry).

### Iteration 3 — 2026-07-17 — Phase 1.3 (Phase 1 COMPLETE) + stop condition

**Standing instruction recorded.** The user asked the loop to run until the
whole plan is done, then close itself — captured as the STOP CONDITION block at
the top of this file. Every iteration checks it.

**Changed.**
- `tests/test_privacy_wipe_contract.py`: added four end-to-end route tests —
  `test_populated_wipe_is_200_and_ok`, `test_history_db_recreation_failure_returns_500`
  (patches `history_store.wipe_database` to fail), `test_voice_deletion_failure_returns_500`
  (patches `shutil.rmtree` to no-op so `voices_absent` cannot hold). These prove a
  real backend failure yields `ok:false` **and** an honest 500 through the route.
- `REMEDIATION_CHANGELOG.md`: Phase 1 flipped to ✅; stop condition added.

**Why.** Phase 1.3 DoD: "no backend-declared wipe failure can produce a renderer
success message." The status contract (1.1), the defensive renderer (1.2), and
now failure-injection coverage across both success and failure paths satisfy it.
The pipeline-quiesce, output-drain, and recording-remains cases were already
covered by `tests/test_privacy_wipe_verified.py`.

**Verification.** `pytest tests/test_privacy_wipe_contract.py` → 15 passed,
4 subtests passed.

**Phase 1 (release-blocking) is DONE.** ✅ 1.1 ✅ 1.2 ✅ 1.3

**Next up →** Phase 2 (DataRegistry) — the most important architectural
correction. Begin 2.1: create `domain/privacy/registry.py` (or a top-level
`data_registry.py` consistent with the current flat layout) defining the frozen
`DataCategory` dataclass and a registry. Inventory the existing persistent
stores first (recordings, drafts JSON, history DB, voices, profiles, personas,
dictionary, macros, voice presets, app state, wake models, MCP config, graph,
debug log, sidecar raw log, overlay state, model/runtime metadata, temp audio)
by grepping for their path helpers in `app_paths.py` / `server.py`, then
register each with real `paths`/`size`/`wipe`/`verify` callables. Land it as
several small PRs: (a) the dataclass + empty registry + tests that fail if a
category is missing metadata, (b) register the read-only fields for all
categories, (c) wire `size`/`paths`, (d) wire `wipe`/`verify` and back
`_perform_privacy_wipe` with it. Keep the existing wipe behavior green
throughout.
