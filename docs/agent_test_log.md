# Running Test Log

This file tracks the test suite executions, command outcomes, and regression test results for the BetterFingers codebase. All agents must log their test runs here prior to committing changes or marking tasks as complete.

---

## 1. Test Execution History

| Timestamp (ISO) | Executing Agent | Command Run | Test Suite / Target | Outcome | Passed / Total | Issues Identified | Resolution / Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-06-07T17:43:36-07:00 | Codex / Agent 1 | `.venv/bin/python -m pytest tests/test_server_studio.py tests/test_studio_workflow.py tests/test_studio_agents.py -q`; `npm --prefix app run build` | Focused Studio backend/orchestrator tests and Electron build after storyboard edit/memory refresh/Whisper edit work | **PASS** | **28 / 28 passed** | Existing FastAPI/pygame deprecation warnings only | Added persisted storyboard edit endpoint, Studio Whisper edit transcription endpoint, visual consistency guide refresh, editable Storyboard Beats UI, regression test for storyboard updates, and fixed `studio_agents.py` registry drift back to panels. |
| 2026-06-05T22:11:00-07:00 | Codex | `python3 -m unittest discover tests` | Entire Test Suite | **FAILED** | 0 / 95 | ImportError: Missing `flet`, `fastapi`, `numpy`, `pytest` | Environment lacks dependencies. System fallback python3 has no libraries installed. Must create a virtual environment (`.venv`) and install `requirements.txt`. |
| 2026-06-06T00:05:12-07:00 | Codex | `scripts/run-betterfingers-tests-linux.sh` | Entire pytest suite via new shortcut runner | **FAILED** | 0 / 136 collected before interruption | 18 collection errors: missing `tkinter`, Linux `pydirectinput` import failure, and `IndentationError` in `hotkey_manager.py` line 597 | Added `pytest` to `.venv`; fixed the stray empty `if self.controller_enabled:` block in `hotkey_manager.py`. Full log: `/home/donaven/.local/state/BetterFingers/tests-20260606-000512-35966.log`. |
| 2026-06-06T00:05:37-07:00 | Codex | `scripts/run-betterfingers-tests-linux.sh` | Entire pytest suite after syntax fix | **FAILED** | 0 / 184 collected before interruption | 12 collection errors remain: system Python lacks `tkinter`; `injector.py` imports Windows-only `pydirectinput` on Linux | Shortcut runner is functional and logs output. Remaining failures need system package `python3-tk` and/or Linux platform guard/mocking around `pydirectinput`. Full log: `/home/donaven/.local/state/BetterFingers/tests-20260606-000537-36281.log`. |
| 2026-06-06T00:30:00-07:00 | Claude | `.venv/bin/python -m pytest --tb=short -q` | Entire pytest suite — full baseline | **PASS** | **222 / 222 passed, 1 skipped** | None | All 12 collection errors resolved. Fixes applied: (1) `injector.py` — platform guard stubs `pydirectinput` on Linux; (2) installed `python3-tk` system package; (3) `test_hotkey_manager_tts.py` — rewrote 3 stale tests that patched `hotkey_manager.keyboard.*` (removed when native hooks moved to Electron IPC); (4) `test_settings_external_url.py` — added `create=True` to `@patch("settings.os.startfile")` for Linux; (5) `test_server_drafts.py` setUp/tearDown — added `server.tts_engine` to saved/restored globals, fixing inter-test `draft_tts_stopped` state pollution. |
| 2026-06-06T02:34:00-07:00 | Codex | `scripts/run-betterfingers-tests-linux.sh` | Entire pytest suite via test shortcut runner | **PASS** | **222 / 222 passed, 1 skipped** | Initial rerun exposed one extra `draft_tts_stopped` status in `test_rewrite_draft_updates_final_text_and_broadcasts`; desktop window could appear to close too quickly | Updated the shortcut to launch `gnome-terminal` directly, fixed terminal pause handling, and narrowed the rewrite-status assertion to the statuses under test. Full log: `/home/donaven/.local/state/BetterFingers/tests-20260606-023358-107429.log`. |
| 2026-06-06T03:24:07-07:00 | Codex | `.venv/bin/python -m pytest` | Entire pytest suite after Gemma 4 12B/progress work | **PASS** | **222 / 222 passed, 1 skipped** | None | Also ran `npm run build` successfully for Electron renderer/main/preload bundles. |
| 2026-06-06T03:45:00-07:00 | Codex / Agent 1 | `.venv/bin/python -m pytest` | Entire pytest suite after Source Arcanum Studio memory foundation | **PASS** | **231 / 231 passed, 1 skipped** | None | Added `studio_memory.py`, Studio FastAPI endpoints, Source Arcanum spec doc, and focused Studio memory/API tests. |
| 2026-06-06T04:24:23-07:00 | Codex / Agent 1 | `.venv/bin/python -m pytest` | Entire pytest suite after Studio memory hardening | **PASS** | **233 / 233 passed, 1 skipped** | None | Added SQLite WAL/busy-timeout settings, Studio memory validation guardrails, API 400 handling for invalid Studio writes, safe Pydantic default factories, and focused validation tests. |
| 2026-06-06T05:00:38-07:00 | Codex / Agent 3 support | `npm run build` from `app/`; `.venv/bin/python -m pytest` | Electron renderer build and full pytest after Studio UI wiring | **PASS** | **233 / 233 passed, 1 skipped** | Initial `npm run build` from repo root failed because `package.json` lives in `app/`; one unrelated draft test expected an exact status list and saw `draft_tts_stopped` lifecycle noise | Wired Studio create/load/run/approval buttons in `main.js`, improved backend API error detail display, reran Electron build from `app/`, narrowed the draft-status assertion to draft statuses, and verified full pytest green. |
| 2026-06-06T05:49:35-07:00 | Codex | `npm run build` from `app/`; `.venv/bin/python -m pytest` | Electron build and full pytest after keep-loaded startup + Studio model telemetry | **PASS** | **239 / 239 passed, 1 skipped** | Pyrefly IDE diagnostics were using system Python instead of `.venv`; Studio did not disclose local-model vs fallback path | Added `pyrefly.toml` and VS Code interpreter settings, made backend startup respect `model_keep_*_loaded` flags, added Studio workflow `model_status`, surfaced model/fallback status in the UI, and added startup/workflow tests. |
| 2026-06-06T05:54:08-07:00 | Codex / Agent 3 support | `npm run build` from `app/`; `.venv/bin/python -m pytest` | Electron build and full pytest after Studio project dropdown | **PASS** | **239 / 239 passed, 1 skipped** | None | Added Studio project listing in `studio_memory.py`, `/studio/projects` and `/studio/project/list` endpoints, replaced the load-project text input with a dropdown, refreshed it on startup/tab open/project create, and added API/memory tests. |
| 2026-06-06T05:59:03-07:00 | Codex / Agent 3 support | `npm run build` from `app/`; `.venv/bin/python -m pytest` | Electron build and full pytest after Studio rerun collision fix | **PASS** | **240 / 240 passed, 1 skipped** | Studio production rerun failed with duplicate panel numbers; project list could show Not Found against older route | Scoped panel generation to the current episode's minutes, reused existing panels when rerunning the same episode, added a rerun regression test, and made project listing fall back from `/studio/project/list` to `/studio/projects`. |
| 2026-06-06T06:07:18-07:00 | Codex / Agent 3 support | `npm run build` from `app/`; `.venv/bin/python -m pytest` | Electron build and full pytest after Studio brief-check gate | **PASS** | **241 / 241 passed, 1 skipped** | Studio jumped straight into full production without confirming interpretation | Added `/studio/workflow/brief`, `StudioWorkflowRunner.run_brief_review`, a Brief Check UI with accept/retry/freeform changes, and tests for the pre-production review path. |
| 2026-06-06T06:28:13-07:00 | Codex / Agent 1 | `.venv/bin/python -m py_compile studio_capabilities.py studio_workflow.py server.py`; `.venv/bin/python -m pytest tests/test_server_studio.py tests/test_studio_workflow.py -q`; `.venv/bin/python -m pytest` | Director Phase 1 exploration registry and full pytest baseline | **PASS** | **244 / 244 passed, 1 skipped** | None | Added deterministic read-only Studio capability registry, paginated `/studio/capabilities` endpoints, `POST /studio/workflow/explore`, workflow exploration snapshot persistence, and focused API/workflow tests. |
| 2026-06-06T06:44:04-07:00 | Codex / Agent 1 | `.venv/bin/python -m py_compile studio_workflow.py studio_capabilities.py server.py`; `.venv/bin/python -m pytest tests/test_studio_workflow.py tests/test_server_studio.py -q`; `.venv/bin/python -m pytest` | Director Phase 2 casting integration and full pytest baseline | **PASS** | **247 / 247 passed, 1 skipped** | None | Integrated `run_director_casting()` into the full production pipeline, returned casting in workflow output, fed casting anchors into character building, stored cast-derived `skin_id` metadata on fallback characters, and added regression assertions. |
| 2026-06-06T06:54:35-07:00 | Codex / Agent 1 | `.venv/bin/python -m py_compile studio_workflow.py studio_scene.py server.py`; `.venv/bin/python -m pytest tests/test_studio_workflow.py tests/test_studio_scene.py tests/test_server_studio.py -q`; `.venv/bin/python -m pytest` | Director Phase 3 scene-spec planning and full pytest baseline | **PASS** | **256 / 256 passed, 1 skipped** | None | Added Director scene-spec generation, deterministic fallback scene specs, full-pipeline Scene Builder delegation, `scene_planning` stage alias, persisted `bible.scene_spec`, and regression tests proving production commits GEST nodes. |
| 2026-06-06T10:40:00-07:00 | Gemini | `PYTHONPATH=. .venv/bin/pytest` | Entire pytest suite (including test_studio_workflow.py) | **PASS** | **228 / 228 passed, 1 skipped** | None | Added `tests/test_studio_workflow.py` covering the new Source Arcanum Studio Mode memory, workflow pipeline, and FastAPI endpoints. All tests green. |
| 2026-06-06T11:15:00-07:00 | Claude | `.venv/bin/python -m pytest tests/test_studio_memory.py tests/test_studio_workflow.py tests/test_server_studio.py -q`; `.venv/bin/python -m pytest` | Phase 1 GEST graph schema (Claude task) + Director Casting + full pytest baseline | **PASS** | **247 / 247 passed, 1 skipped** | None | (1) Claude Phase 1 task per G-002 handoff: added the GEST graph backend in `studio_memory.py` — `gest_nodes`/`gest_edges` tables, node/edge add+get helpers, Allen-interval/logical/semantic relation vocabulary, programmatic temporal **cycle detection** rejecting edges that break the DAG, and `gest` in the project export. (2) Also advanced the Director with Casting (`studio_capabilities.validate_casting`/`default_casting`, `run_director_casting`, `POST /studio/workflow/cast`). Focused GEST + casting tests added. |
| 2026-06-06T12:05:00-07:00 | Claude | `.venv/bin/python -m pytest tests/test_studio_scene.py -q`; `.venv/bin/python -m pytest` | Scene Builder round-based state machine (Scene Planning → GEST) + full pytest baseline | **PASS** | **255 / 255 passed, 1 skipped** | None | Added `studio_scene.py` (round-based state machine enforcing posture/POI/capacity/object/receiver/chain-order constraints against the capability registry and committing to GEST with rollback), `StudioWorkflowRunner.run_scene_round`, `POST /studio/workflow/scene` (invalid chains → 400), and `tests/test_studio_scene.py` (8 tests). |
| 2026-06-06T12:45:00-07:00 | Claude | `.venv/bin/python -m pytest tests/test_studio_scene.py tests/test_studio_memory.py -q`; `.venv/bin/python -m pytest` | Director Phase 4 Finalization (cross-scene temporal linking + timeline) + full pytest baseline | **PASS** | **259 / 259 passed, 1 skipped** | None | Added `studio_memory.compute_gest_timeline` (deterministic Kahn topo sort over before/after edges), `SceneBuilder` `scene_id` tagging, `StudioWorkflowRunner.run_finalization` (orders scenes, adds cross-scene `before` edges, idempotent, persists `gest_timeline`), `POST /studio/workflow/finalize` + `finalization` stage alias, and finalization/timeline tests. |

---

## 2. Environment Setup & Troubleshooting Guide

To ensure that the test suite runs successfully, agents should follow these steps to construct a localized virtual environment:

### Step 1: Create Virtual Environment
Create a localized `.venv` directory in the project root:
```bash
python3 -m venv .venv
```

### Step 2: Activate and Install Dependencies
Activate the virtual environment and install all packages required by the application:
```bash
source .venv/bin/activate
python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
python -m pip install pytest
```

On Linux, full collection of UI/overlay tests also requires the system Tk package, commonly `python3-tk`.

### Step 3: Run the Test Suite
Execute the test suite using `pytest` inside the virtual environment:
```bash
.venv/bin/pytest
```

---

## 3. Test Categories & Critical Path Coverage

- **Smoke Tests**: Focus on the primary hotkey handlers (`hotkey_manager.py`), transcription flows (`transcriber.py`), and settings persistence (`settings_persistence_mixin.py`).
- **Mock Tests**: Ensure hardware mocks (`sounddevice` audio streams and Windows COM interfaces) are utilized to avoid blocking headlessly.
- **Sidecar Lifecycle Tests**: Validate server startup, model reload, and process termination safety (`llm_engine.py`).
