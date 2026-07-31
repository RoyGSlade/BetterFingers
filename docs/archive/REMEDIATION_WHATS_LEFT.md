# BetterFingers Remediation — What's Left

_Snapshot: 2026-07-17 · branch `remediation/phased-loop` (off clean `main`)._
_Reconciled: 2026-07-29 against HEAD `3f86e30` by `worker-releasedocs`, per
`git log --oneline` since 2026-07-17 and `docs/release/WAVE8A_WIRING.md`
through `WAVE12A_UI_CONTROLS.md`. Every status below is either a direct code
citation (file:line, checked against HEAD) or is marked `UNVERIFIED`. Nothing
is upgraded to done on inference._

This is the forward-looking companion to `REMEDIATION_CHANGELOG.md` (which is
the per-chunk history). It tracks what remains across the original 9-phase
remediation plan. **Since the 2026-07-17 snapshot, a separate and much larger
release effort (Waves 8 through 12A, tracked in `docs/release/`) landed on top
of this plan** — restricted actions, controller/Stream Deck input, the
Signal Desk default flip, strict UI parity closure, and Wave 12A's
native-control/data-root/startup hardening. That work is **not** part of the
9-phase plan below and is not summarized twice here; see
`docs/release/RELEASE_BOARD.md` for the wave/gate status. This document only
reconciles the phases below against what those waves happened to touch.

## Test baseline (the "must stay green" bar)

The 2026-07-17 figure (1,229 Python tests / 40 Electron unit tests) is stale
and not re-asserted here — this reconciliation pass did **not** run the full
suite (out of scope; the collab workspace's `__full-test-suite__` OOM-risk
rule still applies). The most recent **self-reported, commit-message**
figures, not independently re-run by this pass: backend "`3052 passed / 0
failed`" (`2507930`, `9399e54`), renderer "`1533/1533`" (`9399e54`, and
independently re-run by `sup-backend` on 2026-07-29 at this same HEAD per the
collab room). A full-suite re-run at HEAD is `sup-backend`'s pending item, not
this document's.

Loop iterations use targeted checks (`py_compile`, focused `pytest`,
`node --test`), **not** the full suite. Before any *unfiltered* `pytest`,
claim the collab pseudo-path `__full-test-suite__` (loads ~6.5 GB of models —
OOM risk).

## Release levels

| Level | Requirement | Status |
| --- | --- | --- |
| Development | Existing tests remain green | ✅ holding (per self-reported commit figures above; not independently re-verified this pass) |
| Friends alpha | Phases 1–4 complete | Phase 1 done; 2–4 remain (see below — 2 is well advanced, 3–4 barely started) |
| Public alpha | Phases 1–7 complete + signed installers | remains; installers are UNBUILT (`docs/release/PACKAGE_BASELINE.md`) |
| 1.0 | Reliability benchmark, injection matrix, DataRegistry, modular architecture | remains |

---

## ✅ Done (committed on `remediation/phased-loop`, unaffected by later waves)

| Commit | Chunk |
| --- | --- |
| `5c6f1e6` | **1.1** `/privacy/wipe` returns honest HTTP status (409/503/500; never 200 on failure) |
| `2e6355c` | **1.2** renderer never reports success unless `ok===true`; `lib/wipeSummary.mjs` |
| `b290cb5` | **1.3** failure-injection route tests → **Phase 1 complete** |
| `9193da2` | **1.2 polish** show what WAS deleted + surface `stuck_sends` (review) |
| `eea6314` | **2.1a** `DataRegistry` mechanism + completeness validation |
| `e868033` | chore: record collab protocol for the loop |
| `a185845` | **2.1b** register all 21 persistent categories + hard-coded CI guard |

**Phase 1 (release-blocking) ✅** — still holding, no later wave touched it.

---

## Newly closed since 2026-07-17 (verified against HEAD `3f86e30`)

- **2.1c** — real `paths`/`size` callables. `data_categories.py`'s `_cat()`
  entries now call real `data_paths.*` functions (e.g.
  `data_paths.raw_recordings`, `data_paths.history_db`, `data_paths.drafts`)
  instead of stubs; `data_paths.py` exists at repo root with real
  implementations (`def raw_recordings() -> list[Path]` at
  `data_paths.py:149`, similarly for `history_db`, `drafts`, and the rest).
- **2.1d** — `_perform_privacy_wipe` (`server.py:3809`) is now
  registry-driven: it calls `data_lifecycle.execute_mode(registry, mode)`
  rather than hand-rolled per-store deletion, and `data_lifecycle.py` defines
  `execute_mode` (`:193`), `preview_mode` (`:233`), and `report_rows`
  (`:416`).
- **2.2** — three wipe modes with a UI preview. `data_registry.py` defines
  `WIPE_MODES`; `GET /privacy` (`server.py:3621-3638`) returns a per-mode
  category preview built from `preview_mode()`; the renderer's
  `settingsWorkspace.js` wires a wipe-mode selector with a live preview.
- **2.4** — narrow Electron-owned wipe IPC. `app/src/main/ipc.js:108-110`
  registers `handleTrusted('backend:wipe-privacy', ...)`.
- **2.5** — `GET /privacy` generated from the registry, not hand-written
  (`server.py:3621-3638`, same citation as 2.2).
- **5.1** — exact/segment-aware route allowlisting.
  `app/src/main/backendProxy.js`'s `ROUTE_ALLOWLIST` (`:21`) is matched by
  `_matchesRoute()` (`:169`) doing per-segment exact/`:param` comparison, not
  prefix matching — replaces the old prefix allowlist this item asked for.
- **8.3** — single-source versioning. `version.py` + root `VERSION` file feed
  `/runtime/version`, the support-report version block, and
  `app/package.json` (integration diffs documented and landed per
  `docs/release/WAVE11_INTEGRATION_DIFFS.md`).
- **8.4** — dependency maintenance. `.github/dependabot.yml` exists
  (weekly, pip, grouped); `git log` since 2026-07-17 shows a steady stream of
  bump commits (`50c0c93`, `a8a5c80`, `3d71a61`, `f27c720`, `d0773b4`,
  `a4056e7`, `30b23cb`, `2831aa6`, `b004bff`, `7df2884`, and more).

## Still open, unchanged in substance since 2026-07-17

- **2.1b, review comment (a)** — `graph_data` sensitivity is still `personal`,
  not promoted to `sensitive` (`data_categories.py:406`).
- **2.1b, review comment (b)** — `may_contain_user_text`'s semantics are still
  not documented precisely on `DataCategory` itself
  (`data_registry.py:78-94` has only a one-line class docstring).
- **2.1b, review comment (c)** — no explicit `opt_in_wipe: bool` field exists;
  `downloaded_models`-shaped entries are still special-cased via an empty
  `wipe_modes` set rather than a named flag.
- **2.3** — no shared `data_lifecycle.write_access(...)` gate or
  `_reject_if_wiping()` exists anywhere in the repo. Gating is still ad hoc:
  `privacy_wipe_in_progress.is_set()` is checked individually at roughly
  eight separate call sites in `server.py`.
- **3.1 / 3.2 / 3.3** — the Phase 3 support-report privacy split has not
  started. `support_report.py:31` still defines `redact_error_message`, not
  the planned `sanitize_error_message()`; there is no
  `record_runtime_error(component, code, public_message, private_exception)`
  anywhere in the repo; there are no privacy-safe-vs-detailed-local report
  modes; there are no adversarial-input fixture tests for this path.
- **Phase 4 (4.1–4.4)** — no `AcceleratorKind` selector, no
  `verifyBackendCompatibility`, and no data-driven runtime artifact manifest
  exist anywhere in the repo (checked by name across `.py` and `.js`).
  `model_runtime_coordinator.py` and `platform_capabilities.py` exist but
  cover clipboard/injection detection, not GPU/accelerator selection. Unlike
  2026-07-17, this is no longer purely hypothetical: this dev machine has no
  discrete GPU and no CUDA — it runs an integrated Intel Iris Xe, tier
  `igpu` per `hardware_report.get_hardware_tier()`, verified 2026-07-29
  (D-0039; see `docs/release/KNOWN_LIMITATIONS.md`'s GPU/CPU section) — so any
  future 4.1–4.4 work here can only be fixture-tested locally, or tested
  against the `cpu-only`/`igpu` tiers this host actually has; the
  `dgpu-8g`/`dgpu-12g+` (CUDA) code paths exist but remain unverified against
  real discrete-GPU hardware, exactly as the original doc anticipated.
- **5.2** — `/graph/`, `/intent/`, `/project/`, `/mcp/`, and `/llm/process`
  are still mounted unconditionally in `server.py`, with no dev-flag guard.
  (They are absent from the Electron `ROUTE_ALLOWLIST`, so the renderer can't
  reach them — but the backend itself still exposes them to anyone who can
  reach it directly.)
- **5.3** — `project_generator.py` still takes an arbitrary `target_dir`
  string with no capability token, no resolve-inside-selected-dir check, and
  no system-path refusal; `routes_foundry.py` has no such guard either.
- **8.1** — CI gates are partial, not the full list this item asks for.
  `.github/workflows/` has `ci.yml` (pytest, Electron/Node unit tests,
  Playwright smoke, production build) plus `codeql.yml` and
  `lock-freshness.yml`. Grepping every workflow file for `ruff`, `bandit`, and
  `npm audit` returns zero matches — none of those three gates exist yet.
- **8.5** — release signing is still best-effort, not fail-closed.
  `build-installer.yml` treats an unsigned build as acceptable rather than
  failing a `v*` tag without signing credentials.
- **Phase 9** — no KISS adapter contract work has landed. `git log --since
  2026-07-17 -- intent_engine.py mcp_client.py` returns **zero commits** on
  either file.

## Newly-found residual bug (2.1d landed, but its own findings surfaced a fresh gap) — **CLOSED, verified 2026-07-29**

`server.py:3994` sets `cleared["history_db_wiped"] = db_result`, where
`db_result` is a **dict** (`{"ok": ..., "recreated": ...}`,
`server.py:3988-3993`) rather than the plain boolean the original finding was
written against. This originally meant `app/src/renderer/lib/wipeSummary.mjs`'s
`isDeletionOutcome(key, value)` only recognized `number` and `boolean` values,
so the history DB fell through to `false` and didn't appear in the renderer's
"already cleared" list. **That gap is now closed:** `isDeletionOutcome()`
(`app/src/renderer/lib/wipeSummary.mjs:41-58`) has an explicit object branch —
`if (value && typeof value === 'object' && !Array.isArray(value)) return
value.ok === true && /_(removed|wiped|cleared)$/.test(key);` — that recognizes
the dict shape, and `describeDeletion()` (`:67-73`) surfaces a
`(store not recreated — reopen the app to rebuild it)` note when
`recreated === false`. Verified by reading the current file; re-run
`node --test app/tests/wipe-summary.test.mjs` to confirm coverage.

## Partially landed

- **5.4** — unified upload policy. `upload_safety.py` (streamed, magic-byte
  checked, size-capped) is real and used by dictation transcription, TTS
  clone, and OCR uploads (`server.py:5132-5137, 5315-5320, 5469-5474` all
  route through `upload_safety.stream_to_file`/`validate_signature`). Wake-
  model import does **not** go through it: `routes_wake.py:390` still does a
  raw, unbounded `handle.write(await file.read())` with no magic-byte check —
  the "identical Electron+Python limits" goal is not met for this one upload
  path.
- **Phase 6 (backend modularization)** — substantially further along than
  2026-07-17, but not done. `server.py` is still one file, **5,832 lines**
  (originally the DoD wanted it under ~300). Real extraction has happened,
  though — driven by Waves 8-10, not by this plan directly:
  `backend/api/routes/` (`actions.py`, `app_context.py`, `contacts.py`,
  `input_devices.py`, `library.py`, `message_rescue.py`, `personas.py`),
  `backend/services/`, `backend/stores/`, and
  `backend/platform/audio_privacy/` all exist and are real, tested modules.
  `data_registry.py` and `data_categories.py` are still at the repo root,
  not relocated to `domain/privacy/` as the DoD specifies.
  **`@app.on_event` → FastAPI lifespan is CLOSED, verified 2026-07-29.**
  `server.py:2353` defines `async def lifespan(app: FastAPI):` and
  `server.py:2366` wires it in via `app.router.lifespan_context = lifespan`.
  `grep -n "on_event\|lifespan" server.py` returns zero `@app.on_event` sites
  — only the `lifespan` function and its wiring, plus unrelated
  `cancellation_event`/`privacy_wipe_in_progress` names that happen to share
  the substring. The migration that this document previously tracked as an
  in-progress, uncommitted `worker-startup` diff has since landed as history.

  The adjacent Wave 10 item named alongside it in the prior reconciliation
  (controller poll-thread pygame crash fix) was a separate, unrelated change
  from the same concurrent session and is not re-verified by this pass — see
  `docs/release/RELEASE_BOARD.md` Wave 10 status for its current disposition.
- **Phase 7 (renderer modularization)** — ambiguous by design, not simply
  open or done. The legacy `app/src/renderer/main.js` itself was never
  extracted (still ~4,277 lines) and does not meet the original `<300 line
  bootstrap` DoD. But `app/src/renderer/features/` now has 31 feature
  modules, and Wave 11 flipped the shipping default away from `main.js`
  entirely: unset `BF_UI` now serves `signal-desk.html` +
  `bootstrap/signalDeskApp.js`, built on those feature modules from the
  start (see `docs/release/RELEASE_BOARD.md`'s "Default UI route" row).
  Whether Phase 7's original goal (extract the *legacy* monolith) still
  matters now that the legacy page is a rollback-only path rather than the
  shipping product is a scope question for the release director, not
  something this reconciliation resolves. `UNVERIFIED`: this pass did not
  measure `signalDeskApp.js`'s own line count against the `<300`-line
  bootstrap DoD.

---

## What Waves 8–12A actually closed (tracked separately, referenced not duplicated)

Waves 8 through 12A are a distinct, later, and larger effort layered on top
of this 9-phase plan — restricted actions and the application registry
(Wave 9), controller/Stream Deck input (Wave 10), audio privacy/capture
isolation (Wave 8), strict 438-item UI parity closure and the Signal Desk
default flip (Wave 11), and native-control styling plus a P0 data-root fix
plus startup hardening (Wave 12A). None of that work was scoped against this
document's phase numbering, so it is not re-listed here item by item. See:

- `docs/release/WAVE8A_WIRING.md`, `WAVE8B_WIRING.md` — audio privacy, capture
  isolation, wake handoff.
- `docs/release/WAVE9_INTEGRATION_DIFFS.md` — restricted action engine.
- `docs/release/WAVE10_INTEGRATION_DIFFS.md`, `WAVE10_QA.md` — controller and
  Stream Deck input (software-qualified; hardware unqualified, no device on
  any machine this project has touched).
- `docs/release/WAVE11_BLOCKERS.md`, `WAVE11_INTEGRATION_DIFFS.md` — parity
  ledger closure (434 → 21 blocked) and the default-UI flip.
- `docs/release/WAVE12A_UI_CONTROLS.md`, `WAVE12A_PROBE_EVIDENCE.md` — native
  form-control styling, the P0 data-root resolver fix, and what its scratch
  probes established (and didn't).
- `docs/release/RELEASE_BOARD.md` — the authoritative current gate/wave
  status; Gate 11 is **NOT ACCEPTED** as of this reconciliation (21 blocked
  rows; separately, the full production QA board is 96/97, one scenario
  genuinely broken — see the board's "Why the board is 96/97" section).

---

## 🗺️ Remaining by phase (updated statuses; see citations above for detail)

### Phase 2 — Unified data-lifecycle (DataRegistry) · release-blocking · 🚧 (well advanced)
- Closed: 2.1c, 2.1d, 2.2, 2.4, 2.5 (see above).
- Open: 2.1b's three review comments (a/b/c), 2.3 (shared write-access gate),
  and the freshly-found `history_db_wiped` dict/renderer mismatch.

### Phase 3 — Support-report privacy · release-blocking · ⬜ (not started)
- 3.1, 3.2, 3.3 all still open, unchanged from 2026-07-17.
- Relevant files today: `support_report.py`, `log_redaction.py`.

### Phase 4 — Runtime & process boundaries · release-blocking · ⬜ (not started)
- 4.1–4.4 all still open.
- ⚠️ Hardware-dependent as originally noted, and now concretely confirmed: no
  local discrete GPU / CUDA device exists to test against — this host has an
  integrated Intel Iris Xe (`igpu` tier), verified 2026-07-29, D-0039 (see
  `docs/release/KNOWN_LIMITATIONS.md`).
- Relevant files: `model_runtime_coordinator.py`, `model_manager.py`,
  `platform_capabilities.py`, `hardware_report.py`, `app/src/main/*`.

### Phase 5 — API/renderer security boundary · 🚧 (partial)
- Closed: 5.1. Partial: 5.4 (dictation/clone/OCR done; wake-model import not
  unified). Open: 5.2, 5.3.
- Files: `project_generator.py`, `routes_foundry.py`, `upload_safety.py`,
  `server_security.py`, `routes_wake.py`, `app/src/main/backendProxy.js`.

### Phase 6 — Backend modularization · 🚧 (substantially advanced by Waves 8-10, not by this plan)
- `backend/api/routes/*`, `backend/services/*`, `backend/stores/*`,
  `backend/platform/audio_privacy/*` exist and are real. `server.py` is
  still 5,832 lines. `data_registry.py`/`data_categories.py` not relocated to
  `domain/privacy/`. `@app.on_event` → lifespan (8.2) is **closed** — see
  Phase 8 below.

### Phase 7 — Renderer modularization · 🚧 (ambiguous — see note above)
- `main.js` itself unextracted; the shipping page (`signal-desk.html` +
  `signalDeskApp.js`) is a different, already-modular composition root that
  Wave 11 made the default. Scope question for the release director.

### Phase 8 — Quality/dependency/release gates · 🚧 (partial)
- Closed: 8.2 (`@app.on_event` → FastAPI lifespan, verified 2026-07-29 —
  `server.py:2353`/`:2366`, zero `@app.on_event` remaining), 8.3, 8.4.
  Partial: 8.1 (pytest/unit/CodeQL/build/lockfile-freshness gates exist;
  Ruff, Bandit, `npm audit --omit=dev` do not — tracked as WS-C5 in
  `docs/release/PUBLISH_PLAN.md`). Open: 8.5 (signing still best-effort, ⛔
  still needs credentials).

### Phase 9 — KISS boundary · ⬜ (not started, zero commits since 2026-07-17)
- File today: `intent_engine.py`, `mcp_client.py` — both untouched since the
  snapshot date.

---

## ⚠️ Known blockers / deferrals

- **Finding #3-residual** — **CLOSED (verified 2026-07-29).**
  `app/src/renderer/lib/wipeSummary.mjs`'s `isDeletionOutcome()` (`:41-58`) now
  explicitly handles the object-shaped `{ok, recreated}` outcome 2.1d
  introduced: `if (value && typeof value === 'object' && !Array.isArray(value))
  return value.ok === true && /_(removed|wiped|cleared)$/.test(key);` — the
  history DB dict is recognized as a real deletion, not silently dropped. See
  "Newly-found residual bug" above for the original citation; the fix has
  since landed.
- **Phase 4** hardware matrix — still blocked on real hardware; this machine
  specifically has no discrete GPU / CUDA device (integrated Intel Iris Xe,
  `igpu` tier, confirmed 2026-07-29, D-0039 — not the RTX 4060 Ti a prior
  release-docs pass briefly assigned it; see
  `docs/release/KNOWN_LIMITATIONS.md`).
- **Phase 8.5** signing — still requires credentials; still fail-open rather
  than fail-closed by design-in-progress.
- **Phase 9** — entirely unstarted; not merely deferred, untouched.

## How to resume
This document is superseded for planning purposes by
[`docs/release/PUBLISH_PLAN.md`](../release/PUBLISH_PLAN.md), which is the
current work queue and supersession note (see its header). `RELEASE_BOARD.md`
remains the gate authority. Do not resume work directly from this document's
old `/loop` chunk list — the `history_db_wiped` renderer fix and the 8.2
lifespan migration it names are both closed (see above); remaining open items
here (2.1b review comments, 2.3's shared write-access gate, Phase 3, Phase 9,
8.5 signing) are explicitly deferred in `PUBLISH_PLAN.md` §7 or tracked as its
own WS-C tasks — check there before picking up anything from this file.
