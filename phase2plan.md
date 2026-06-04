# Phase 2 Verification and Completion Plan

This document outlines the detailed plan to verify and complete **Phase 2: Recording To Draft Pipeline** in the BetterFingers Electron application, preparing the codebase for Phase 3.

---

## 1. Goal

Reliably produce reviewable drafts with raw transcripts, cleaned output, metadata, and clear failure states from hotkey recording on Linux (X11 & Wayland) and Windows.

---

## 2. Open Questions

1. **Draft Persistence**: Do you want draft history to persist across application restarts (e.g., saving to a local JSON file or SQLite database), or is keeping drafts strictly in-memory (session-only) acceptable?
2. **Production Guarding**: Should the new dev/test mock draft API endpoint be disabled in production packages?
3. **Emergency Stop Sound/TTS**: When Phase 7 (TTS) is complete, should emergency stop immediately terminate any active voice/read-aloud speech?

---

## 3. Proposed Robustness Enhancements

### A. Busy Check Callback for Hotkey Manager
* **Backend (`server.py`)**: Introduce a thread-safe `is_processing_draft = False` flag. Set to `True` during draft STT/LLM post-processing and `False` in the `finally` block.
* **Hotkey Manager (`hotkey_manager.py`)**: Accept an `is_busy_callback` constructor parameter. In `_start_recording`, check this callback and ignore recording triggers if the backend is busy.

### B. Operation Cancellation Semantics
* **Backend (`server.py`)**: Define a thread-safe `cancellation_event = threading.Event()`.
* **Worker Execution**: Clear `cancellation_event` at start, and check `cancellation_event.is_set()` before major steps (transcription, no-audio gate, LLM post-processing, draft creation). If set, raise an `InterruptedError` to transition the draft to an error state ("Operation cancelled by user.") and broadcast `draft_error`.
* **Emergency Stop**: Trigger `cancellation_event.set()` inside `emergency_stop_runtime()`.

### C. Clear Draft History Action
* **Backend (`server.py`)**: Expose a `DELETE /drafts` API endpoint to clear the draft queue, cached recordings, and pending manual send IDs.
* **Electron UI (`main.js` & `index.html`)**: Add a "Clear History" button that calls the endpoint and clears the UI lists.

### D. Mock Drafts Endpoint for UI/QA Testing
* **Backend (`server.py`)**: Add a `POST /drafts/test-mock` endpoint that creates a draft with custom mock status (pending, blocked, error, etc.) and payload without requiring actual audio recording.

### E. Text Length and Timeout Guards
* Enforce a text length limit on the raw transcript (e.g., 10,000 characters) before sending to LLM post-processing to avoid crashing the engine.

---

## 4. Automated Test Enhancements

Add the following unit tests in `tests/test_server_drafts.py` to cover all Phase 2 goals:
- `test_retry_missing_recording_returns_409`: Verify retrying a draft when its recording is missing in `draft_recordings` returns a 409 status code.
- `test_edit_draft_resets_accepted_sent_state_safely`: Verify editing a draft resets status to `pending`, clears `pending_send` flag, and removes it from `pending_manual_send_ids`.
- `test_clear_draft_history`: Verify `DELETE /drafts` clears `draft_queue`, `draft_recordings`, and `pending_manual_send_ids`.
- `test_fake_draft_endpoint`: Verify `POST /drafts/test-mock` successfully inserts mock drafts with correct status and metadata.
- `test_cancellation_semantics`: Verify setting `cancellation_event` causes transcription/rewriting to abort cleanly, resulting in a cancelled/error draft state.

---

## 5. Verification Plan

### Automated Verification
1. Run pytest suite:
   ```bash
   python3 -m pytest tests/test_server_drafts.py
   ```
2. Build and run Playwright integration tests:
   ```bash
   npm run build && npx playwright test
   ```

### Manual Verification
1. **Busy State Block**: Trigger a recording and press the hotkey again while the backend is processing. Verify that the new trigger is ignored.
2. **Emergency Stop Cancellation**: Trigger a rewrite, hit "Emergency Stop", and confirm that the draft status transitions immediately to `error` ("Operation cancelled by user.").
3. **Clear History**: Populate the draft list, click "Clear History", and verify that the UI and backend queues are empty.
