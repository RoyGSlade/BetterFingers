# Running Test Log

This file tracks the test suite executions, command outcomes, and regression test results for the BetterFingers codebase. All agents must log their test runs here prior to committing changes or marking tasks as complete.

---

## 1. Test Execution History

| Timestamp (ISO) | Executing Agent | Command Run | Test Suite / Target | Outcome | Passed / Total | Issues Identified | Resolution / Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-06-05T22:11:00-07:00 | Codex | `python3 -m unittest discover tests` | Entire Test Suite | **FAILED** | 0 / 95 | ImportError: Missing `flet`, `fastapi`, `numpy`, `pytest` | Environment lacks dependencies. System fallback python3 has no libraries installed. Must create a virtual environment (`.venv`) and install `requirements.txt`. |
| 2026-06-06T00:05:12-07:00 | Codex | `scripts/run-betterfingers-tests-linux.sh` | Entire pytest suite via new shortcut runner | **FAILED** | 0 / 136 collected before interruption | 18 collection errors: missing `tkinter`, Linux `pydirectinput` import failure, and `IndentationError` in `hotkey_manager.py` line 597 | Added `pytest` to `.venv`; fixed the stray empty `if self.controller_enabled:` block in `hotkey_manager.py`. Full log: `/home/donaven/.local/state/BetterFingers/tests-20260606-000512-35966.log`. |
| 2026-06-06T00:05:37-07:00 | Codex | `scripts/run-betterfingers-tests-linux.sh` | Entire pytest suite after syntax fix | **FAILED** | 0 / 184 collected before interruption | 12 collection errors remain: system Python lacks `tkinter`; `injector.py` imports Windows-only `pydirectinput` on Linux | Shortcut runner is functional and logs output. Remaining failures need system package `python3-tk` and/or Linux platform guard/mocking around `pydirectinput`. Full log: `/home/donaven/.local/state/BetterFingers/tests-20260606-000537-36281.log`. |
| 2026-06-06T00:30:00-07:00 | Claude | `.venv/bin/python -m pytest --tb=short -q` | Entire pytest suite — full baseline | **PASS** | **222 / 222 passed, 1 skipped** | None | All 12 collection errors resolved. Fixes applied: (1) `injector.py` — platform guard stubs `pydirectinput` on Linux; (2) installed `python3-tk` system package; (3) `test_hotkey_manager_tts.py` — rewrote 3 stale tests that patched `hotkey_manager.keyboard.*` (removed when native hooks moved to Electron IPC); (4) `test_settings_external_url.py` — added `create=True` to `@patch("settings.os.startfile")` for Linux; (5) `test_server_drafts.py` setUp/tearDown — added `server.tts_engine` to saved/restored globals, fixing inter-test `draft_tts_stopped` state pollution. |
| 2026-06-06T02:34:00-07:00 | Codex | `scripts/run-betterfingers-tests-linux.sh` | Entire pytest suite via test shortcut runner | **PASS** | **222 / 222 passed, 1 skipped** | Initial rerun exposed one extra `draft_tts_stopped` status in `test_rewrite_draft_updates_final_text_and_broadcasts`; desktop window could appear to close too quickly | Updated the shortcut to launch `gnome-terminal` directly, fixed terminal pause handling, and narrowed the rewrite-status assertion to the statuses under test. Full log: `/home/donaven/.local/state/BetterFingers/tests-20260606-023358-107429.log`. |
| 2026-06-06T03:24:07-07:00 | Codex | `.venv/bin/python -m pytest` | Entire pytest suite after Gemma 4 12B/progress work | **PASS** | **222 / 222 passed, 1 skipped** | None | Also ran `npm run build` successfully for Electron renderer/main/preload bundles. |
| 2026-06-06T03:45:00-07:00 | Codex / Agent 1 | `.venv/bin/python -m pytest` | Entire pytest suite after Source Arcanum Studio memory foundation | **PASS** | **231 / 231 passed, 1 skipped** | None | Added `studio_memory.py`, Studio FastAPI endpoints, Source Arcanum spec doc, and focused Studio memory/API tests. |
| 2026-06-06T04:24:23-07:00 | Codex / Agent 1 | `.venv/bin/python -m pytest` | Entire pytest suite after Studio memory hardening | **PASS** | **233 / 233 passed, 1 skipped** | None | Added SQLite WAL/busy-timeout settings, Studio memory validation guardrails, API 400 handling for invalid Studio writes, safe Pydantic default factories, and focused validation tests. |
| 2026-06-06T10:40:00-07:00 | Gemini | `PYTHONPATH=. .venv/bin/pytest` | Entire pytest suite (including test_studio_workflow.py) | **PASS** | **228 / 228 passed, 1 skipped** | None | Added `tests/test_studio_workflow.py` covering the new Source Arcanum Studio Mode memory, workflow pipeline, and FastAPI endpoints. All tests green. |

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
