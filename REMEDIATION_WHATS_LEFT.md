# BetterFingers Remediation — What's Left

_Snapshot: 2026-07-17 · branch `remediation/phased-loop` (off clean `main`)._

This is the forward-looking companion to `REMEDIATION_CHANGELOG.md` (which is the
per-chunk history). It tracks what remains across the 9-phase plan. Work has been
landing as small, reviewable, per-chunk commits — never mixing unrelated behavior
changes — with an overseer session (`bf-plan-reviewer`) reviewing each handoff.

## Test baseline (the "must stay green" bar)

1,229 Python tests · 40 Electron unit tests · production build · CodeQL · E2E CI.
Loop iterations use targeted checks (`py_compile`, focused `pytest`, `node --test`),
**not** the full suite. Before any *unfiltered* `pytest`, claim the collab
pseudo-path `__full-test-suite__` (loads ~6.5 GB of models — OOM risk).

## Release levels

| Level | Requirement | Status |
| --- | --- | --- |
| Development | Existing tests remain green | ✅ holding |
| Friends alpha | Phases 1–4 complete | Phase 1 done; 2–4 remain |
| Public alpha | Phases 1–7 complete + signed installers | remains |
| 1.0 | Reliability benchmark, injection matrix, DataRegistry, modular architecture | remains |

---

## ✅ Done (committed on `remediation/phased-loop`)

| Commit | Chunk |
| --- | --- |
| `5c6f1e6` | **1.1** `/privacy/wipe` returns honest HTTP status (409/503/500; never 200 on failure) |
| `2e6355c` | **1.2** renderer never reports success unless `ok===true`; `lib/wipeSummary.mjs` |
| `b290cb5` | **1.3** failure-injection route tests → **Phase 1 complete** |
| `9193da2` | **1.2 polish** show what WAS deleted + surface `stuck_sends` (review) |
| `eea6314` | **2.1a** `DataRegistry` mechanism + completeness validation |
| `e868033` | chore: record collab protocol for the loop |
| `a185845` | **2.1b** register all 21 persistent categories + hard-coded CI guard |

**Phase 1 (release-blocking) ✅** · **Phase 2 🚧** (2.1a + 2.1b done).

---

## 🔜 Immediate next

**Open review comments on 2.1b** (from `bf-plan-reviewer`, non-blocking — fold into the next chunk):
- (a) promote `graph_data` sensitivity `personal → sensitive` (derived from the same dictated content as `history_db`).
- (b) document the exact semantics of `may_contain_user_text` in the `DataCategory` docstring (keep the plan's field name).
- (c) add an explicit `opt_in_wipe: bool` field instead of special-casing `downloaded_models` with empty `wipe_modes` (2.2's UI needs the separate opt-in checkbox).

**Phase 2.1c** — replace stub `paths`/`size` callables with real ones (history DB + WAL/SHM, recordings dir, voices, drafts file, profiles/personas/dictionary/macros/presets, app-state + first-run marker, wake models, MCP config, debug log) via `app_paths.py` / `server.py` helpers. Electron-owned paths (sidecar log, overlay state) stay stubbed until 2.4's IPC. Temp-dir tests for path resolution + byte sizing.

---

## 🗺️ Remaining by phase

### Phase 2 — Unified data-lifecycle (DataRegistry) · release-blocking · 🚧
- 2.1c real `paths` + `size` · 2.1d real `wipe`/`verify` + back `_perform_privacy_wipe` with the registry (**also** finding #3-residual: normalize the `cleared.history_db_wiped` dict so the history DB shows in the renderer's "already cleared" list).
- 2.2 three explicit wipe modes (clear conversations / clear personal data / factory reset) + UI preview of exactly which categories each includes.
- 2.3 shared lifecycle gate (`data_lifecycle.write_access(...)`) coordinating every writer; `_reject_if_wiping()` / registry guard on every data-creating route; full quiesce→delete→verify ordering.
- 2.4 narrow IPC so the Python wipe workflow can delete + verify Electron-owned data (sidecar_backend_raw.log, overlay position/appearance, other userData) and return Electron postconditions.
- 2.5 generate `GET /privacy` from the registry (no hand-written list); DoD: adding a store requires registering it, tests fail if metadata incomplete (guard already in place from 2.1b).

### Phase 3 — Support-report privacy · release-blocking · ⬜
- 3.1 split sanitize vs redact: rename to `sanitize_error_message()`; add semantic redaction (home-dir usernames, absolute paths, bearer tokens/API keys, credential URLs, emails, env values, text after prompt markers); prefer structured error codes (`record_runtime_error(component, code, public_message, private_exception)`) over `str(exc)`.
- 3.2 report modes: privacy-safe (anonymized default) vs detailed-local (full paths, preview before copy).
- 3.3 adversarial-input fixtures (`/home/roy/...`, `C:\Users\Roy\...`, tokens, multiline prompt text, credential URLs, exception-echoing-input, unicode controls). DoD: privacy-safe report can't reveal usernames/secrets/injected sample text.
- Relevant files today: `support_report.py`, `log_redaction.py`.

### Phase 4 — Runtime & process boundaries · release-blocking · ⬜
- 4.1 explicit `AcceleratorKind` capability selector (detect OS/arch/GPU → validate backend → select artifact → verify checksum → startup probe → clean fallback → report why).
- 4.2 Windows runtime matrix (NVIDIA/AMD/Intel Arc/integrated/no-GPU → LLM + STT defaults); **do not** treat `use_gpu=true` as `use_cuda=true`.
- 4.3 data-driven runtime artifact manifest (URLs/hashes/platforms/accelerators) replacing `if sys.platform` constants; fixture tests per hardware class (no real hardware).
- 4.4 one `verifyBackendCompatibility(origin, headers)` for spawned + external backends (health / runtime-version / schema / capability); external backend must pass auth+health+schema, get passive monitoring, never be killed by Electron.
- ⚠️ Partly hardware/CI-dependent — some sub-items may land as fixture tests only until real hardware/CI runs (mark ⛔ if truly blocked). A `feat/windows-vulkan-fallback` branch already exists and may seed this.
- Relevant files: `model_runtime_coordinator.py`, `model_manager.py`, `platform_capabilities.py`, `hardware_report.py`, `app/src/main/*`.

### Phase 5 — API/renderer security boundary · ⬜
- 5.1 replace prefix allowlisting with exact/segment-aware route patterns + per-method restriction; negative tests (`/healthcheck`, `/draftsmanship`, `/privacy-override`, encoded traversal, duplicate slashes, wrong methods, stray query params).
- 5.2 remove unfinished surfaces from the production proxy (`/graph/`, `/intent/`, `/project/`, `/mcp/`, unused `/llm/process`) behind a dev flag.
- 5.3 constrain project generation (Electron file-picker dir + short-lived capability token + resolve-inside-selected-dir + refuse system paths; never accept arbitrary renderer path). File: `project_generator.py`, `routes_foundry.py`.
- 5.4 unify upload policy (dictation 50 MB / clone / wake 20 MB / OCR) — magic-byte + streamed bounded temp file, never unrestricted `await file.read()`; identical Electron+Python limits. Files: `upload_safety.py`, `server_security.py`.

### Phase 6 — Backend modularization · ⬜
- Incrementally extract `server.py` (~192 KB) into `api/routes/*`, `domain/*`, `infrastructure/*`, `experimental/*`; `AppServices` container via FastAPI **lifespan** (replace `@app.on_event`); formal draft state machine (reject illegal transitions). DoD: `server.py` → small bootstrap (<~300 lines); domain code doesn't import FastAPI; persistence doesn't import routes; one owner per mutable resource. (Relocate `data_registry.py`/`data_categories.py` → `domain/privacy/`.)

### Phase 7 — Renderer modularization · ⬜
- Extract `app/src/renderer/main.js` by vertical slice (privacy → diagnostics → runtime → drafts → settings → dashboard → overlay); lightweight observable store; `pages/` shells. DoD: `main.js` → bootstrap (<~300 lines); feature tests don't launch Electron.

### Phase 8 — Quality/dependency/release gates · ⬜
- 8.1 CI gates (Ruff, py-compile, pytest, Bandit high-sev, CodeQL, Electron unit, prod build, Playwright smoke, `npm audit --omit=dev`, lockfile freshness); fix existing 25 first-party Ruff findings; incremental typing on new services/schemas.
- 8.2 resolve deprecations (FastAPI `on_event`→lifespan — overlaps Phase 6; explicit tar extraction filter; dead imports/vars; fix TTS-clone docstrings/requirements comments). _Note: the `on_event` DeprecationWarning is already visible in the wipe test runs._
- 8.3 single-source versioning (`version.json` → Electron pkg, backend response, support report, installer naming, compat tests; CI fails on drift).
- 8.4 dependency maintenance (Electron/undici + Vite/esbuild advisories, Dependabot grouping, per-platform Python audits, hash-locked public installs, CI tests the packaged locks).
- 8.5 enforce release signing (public `v*` fails without signing creds; split `alpha-unsigned-*` prerelease vs signed `v*`; verify signatures + keep checksums/SBOM/provenance). ⚠️ Needs signing credentials — likely ⛔ until provided.

### Phase 9 — KISS boundary · ⬜
- Define the single BetterFingers⇄KISS adapter contract (produces accepted text / persona / context / explicit action; KISS returns response + proposed state changes + confirmation requirements). Invariants: no ambient speech invokes MCP tools; tool writes default-deny; destructive actions need visible confirmation; BetterFingers doesn't touch KISS storage; KISS can't bypass review/send policy. Graph/intent/project/MCP stay experimental until this exists (ties to 5.2). File today: `intent_engine.py`, `mcp_client.py`.

---

## ⚠️ Known blockers / deferrals
- **Finding #3-residual** (history-DB dict not shown as "already cleared") → deferred to **2.1d** (avoids throwaway JS if `cleared{}` is normalized server-side).
- **Phase 4** hardware matrix — real GPU classes not present locally; land as fixture tests, mark ⛔ where a live probe is required.
- **Phase 8.5** signing — requires credentials; will fail-closed by design until provided.

## How to resume
Re-run `/loop [interval] <the standard remediation prompt>`; each iteration reads
`REMEDIATION_CHANGELOG.md` "Next up", does one chunk, commits, and posts a handoff
to `bf-plan-reviewer`. Immediate next chunk: the 2.1b review comments (a/b/c), then 2.1c.
