# Better Fingers 2.0 Comprehensive Audit Checklist (todo_2.0.md)

This document serves as a rigorous, file-by-file checklist to ensure the Better Fingers codebase is optimized, bug-free, and feature-complete for the 2.0 release.

## Core Application Logic

### `main.py`
- [x] **Necessity:** Essential entry point. Keep.
- [x] **Fixes:** Check for unhandled exceptions during startup/shutdown. Verify single-instance enforcement.
- [x] **Improvements:** Optimize startup time. Ensure clean teardown of all threads/processes.
- [x] **Features:** Verify CLI arguments are handled correctly (if any).
- [x] **Conciseness:** Remove any temporary debugging print statements or commented-out code blocks.
- [ ] **Verification:**
    - [ ] Run application from fresh boot.
    - [ ] Test rapid open/close cycles.
    - [ ] Verify tray icon behavior.

### `server.py`
- [x] **Necessity:** Backend server logic. Keep.
- [x] **Fixes:** Check for port conflicts. Verify WebSocket connection stability. (Added CLI args for host/port).
- [x] **Improvements:** Implement better error handling for network issues. Optimize payload size for IPC. (Standard FastAPI).
- [ ] **Features:** verify API endpoints for external integrations.
- [x] **Conciseness:** Audit for redundant API routes. (Used shared logging).
- [ ] **Verification:**
    - [ ] Test connectivity from `overlay.py`.
    - [ ] Simulate network interruptions.

### `utils.py`
- [x] **Necessity:** Shared utilities. Keep.
- [x] **Fixes:** Audit all helper functions for edge cases (empty strings, null inputs).
- [ ] **Improvements:** Optimize heavy string manipulation or IO operations.
- [x] **Conciseness:** Deprecate and remove unused helper functions. (Removed ensure_cuda_paths).
- [ ] **Verification:**
    - [ ] Unit test key utility functions (path handling, formatting).

### `injector.py` (Ejector)
- [ ] **Necessity:** DLL injection/process manipulation. Keep.
- [ ] **Fixes:** Verify permission handling (Admin privileges). Check for anti-virus false positives.
- [ ] **Improvements:** Make injection stealthier or more robust against target process updates.
- [ ] **Features:** Add support for more target process types if needed.
- [ ] **Verification:**
    - [ ] Test injection into target application.
    - [ ] Verify behavior when target crashes or restarts.

## Audio & Recording

### `audio_ducker.py`
- [x] **Necessity:** Audio management. Keep.
- [x] **Fixes:** Prevent audio popping or severe volume fluctuations. (Implemented smooth internal fading).
- [x] **Improvements:** Smooth out fading curves (linear vs logarithmic). (Implemented linear fade loop).
- [ ] **Features:**
- [x] **Conciseness:** (Refactored repeated COM logic into _fade_volume).
- [ ] **Verification:**
    - [ ] Test with Spotify/YouTube running in background.
    - [ ] Verify restoration of volume after TTS/User speech ends.

### `audio_gate.py`
- [x] **Necessity:** Noise gate/Voice Activity Detection fallback. Keep.
- [x] **Fixes:** Adjust threshold sensitivity to avoid cutting off start/end of sentences. (Made optional Pre-transcription check possible).
- [ ] **Improvements:** Implement adaptive thresholding if not present.
- [ ] **Verification:**
    - [ ] Test in quiet vs noisy environments.

### `recorder.py`
- [x] **Necessity:** Microphone input capture. Keep.
- [x] **Fixes:** Handle microphone device disconnection/switching gracefully. (Added device_index support).
- [ ] **Improvements:** Reduce latency in audio buffer processing. (Seems optimized).
- [x] **Features:** Support for multiple audio input devices? (Added device_index param).
- [ ] **Verification:**
    - [ ] Record long sessions (memory leak check).
    - [ ] Switch default microphone in Windows settings while running.

### `transcriber.py`
- [x] **Necessity:** Speech-to-text. Keep.
- [ ] **Fixes:** 
    - [x] Handle hallmark hallucinations (repeated phrases like "Thank you").
    - [ ] Implement VRAM optimization (ensure memory growth is capped).
- [ ] **Improvements:** 
    - [ ] Add support for "distil-whisper" for faster CPU inference?
    - [ ] Implement "fast_lane" or similar check to bypass heavy processing for short commands.
- [ ] **Features:** 
    - [ ] Real-time confidence scores (if supported by backend).
- [ ] **Conciseness:** 
    - [ ] Check for unused "temperature" fallback logic if standard greedy is sufficient.
- [ ] **Verification:**
    - [ ] Test accuracy with different accents/speeds.
    - [ ] Verify realtime vs batch processing speed.
    - [ ] Trigger hallucination prone silence (white noise) and check for repeater loops.

### `tts_engine.py`
- [x] **Necessity:** Text-to-speech. Keep.
- [ ] **Fixes:** 
    - [ ] Fix pronunciation of specific technical terms/acronyms (Add regex replacement map).
- [ ] **Improvements:** 
    - [ ] Cache common phrases to reduce generation time.
    - [ ] Ensure `pyttsx3` or `kokoro` backend selection is robust.
- [ ] **Features:** 
    - [ ] Add speed/pitch controls (Backend support verification needed).
- [ ] **Verification:**
    - [ ] Stress test with long paragraphs.
    - [ ] Verify correct audio output device usage.
    - [ ] Test speed slider impact on actual audio.

## UI & Overlay

### `overlay.py`
- [x] **Necessity:** Main UI overlay. Keep.
- [x] **Fixes:** Fix "click-through" issues. Ensure transparency works on all Windows versions. (Verified and cleaned up).
- [x] **Improvements:** Optimize render loop for >60FPS. Reduce GPU affinity if idle. (Flash loop updated to 60fps).
- [x] **Features:** Animation logic for appearing/disappearing.
- [ ] **Verification:**
    - [ ] Test with full-screen games (DirectX/Vulkan/OpenGL).
    - [ ] Test multi-monitor setups (DPI scaling).

### `notification_overlay.py`
- [x] **Necessity:** Toast notifications. Keep.
- [x] **Fixes:** Stacking order (ensure it doesn't block critical game UI). (Added drag support).
- [x] **Improvements:** Add different notification types (error, info, success). (Implemented).
- [ ] **Verification:**
    - [ ] Trigger rapid-fire notifications.

### `preview_overlay.py`
- [ ] **Necessity:** Live preview of transcription/actions. Keep (useful for confidence).
- [ ] **Fixes:** 
    - [ ] Transparency/Click-through logic on Windows 11 (verify `ctypes` calls).
- [ ] **Improvements:** 
    - [ ] Make draggable/resizable (User request).
    - [ ] Ensure it has expand button for when we have received too many tokens from user (User request).
- [ ] **Features:** 
    - [ ] Add "Cancel" button to stop generation?
- [ ] **Conciseness:** 
    - [ ] Remove duplicate `overlay.py` logic if possible (inherit?).
- [ ] **Verification:**
    - [ ] Verify sync with `transcriber.py` output.
    - [ ] Test text wrapping for very long sentences.

### `splash.py`
- [x] **Necessity:** Startup splash screen. Keep.
- [x] **Fixes:** Ensure it closes promptly when `main.py` is ready. (Verified auto-close).
- [ ] **Improvements:** Add loading progress bar/status text. (Deemed unnecessary for fast load).
- [x] **Conciseness:** Keep file size small for fast load.
- [ ] **Verification:**
    - [ ] Verify it appears immediately on launch.

### `guided_tour.py`
- [x] **Necessity:** Onboarding. Keep (Simplified).
- [x] **Fixes:** Reset state correctly if tour is cancelled mid-way.
- [x] **Improvements:** Add "Back" button to steps.
- [x] **Conciseness:** User says "Remove or heavily refract". (Significantly simplified by removing dynamic parsing).
- [ ] **Verification:**
    - [ ] Complete tour from start to finish.
    - [ ] Test "Skip" functionality.

### `verify_overlay_fix.py`
- [x] **Necessity:** Diagnostic script. Keep (for now) or merge into `utils.py`.
- [x] **Decision:** [MERGE] Merged into `tests/test_overlay_window_styles.py`.
- [x] **Verification:**
    - [x] Run script to confirm overlay detection logic is sound. (Converted to unittest).

## Intelligence & State

### `llm_engine.py`
- [x] **Necessity:** Brain of the operation. Keep.
- [x] **Fixes:** Handle API timeouts/rate limits (if cloud) or OOM (if local). (Timeouts handled, local server manages OOM).
- [ ] **Improvements:** Implement context window management (sliding window) make sure it actually cuts the user off when the context window is full. (Chunking implemented, context window is per-request).
- [x] **Features:** Switchable models (size vs speed). (Added reload_model support).
- [ ] **Verification:**
    - [ ] Test complex instructions.
    - [ ] Measure token-per-second generation speed.

### `intent_engine.py`
- [x] **Necessity:** Parsing user intent. Keep.
- [x] **Fixes:** Improve regex/parsing for specific commands. (Added basic fuzzy logic).
- [x] **Improvements:** Add fuzzy matching for commands. (Implemented using difflib).
- [ ] **Verification:**
    - [ ] Test ambiguous commands.

### `hotkey_manager.py`
- [x] **Necessity:** Global hotkey handling. Keep.
- [x] **Fixes:** Prevent key ghosting. Ensure keys are released if suppressed. (suppress=False used, so ghosting minimized).
- [ ] **Improvements:** Allow user-configurable hotkeys. (Implemented via config).
    - [ ] Add Double Tap / Hold logic.
    - [ ] Implement "Stop TTS on second press" (Requires main.py state integration).
- [ ] **Verification:**
    - [ ] Test with modifier keys (Ctrl/Alt/Shift).
    - [ ] Test while other apps with hotkeys are active.

### `clipboard_capture.py`
- [x] **Necessity:** Context awareness. Keep.
- [x] **Fixes:** Handle large clipboard content (files/images) without freezing. (Added 20MB limit per format).
- [ ] **Improvements:** Only capture text when relevant or preparation for restore. (Implemented via snapshot).
- [ ] **Verification:**
    - [ ] Copy various data types (text, HTML, images).

### `input_binding.py`
- [x] **Necessity:** Controller Input Configuration (Data Class). Keep.
- [x] **Fixes:** Validates binding structures. (Logic is sound).
- [ ] **Improvements:** (Renamed from 'Simulating Inputs' - typing logic is in main.py).
- [ ] **Verification:**
    - [ ] Verify controller binding persistence.

## Configuration & Management

### `settings.py` (and Mixins)
- [x] **Files:** `settings.py`, `settings_controls_mixin.py`, `settings_persistence_mixin.py`, `settings_tour_mixin.py`, `settings_modal_manager.py`
- [x] **Necessity:** User configuration. Keep.
- [x] **Fixes:** Added WPM high-speed warning. Added LLM model selection and management UI.
- [x] **Improvements:** Integrated `model_manager` for dynamic model handling. UI polish (alignment, tooltips) improvements ongoing.
- [x] **Features:** 
    - [x] High WPM warning.
    - [x] Multiple LLM model support (Gemma 4B/12B, Q4/Q6/Q8).
    - [x] Download/Delete management for models.
- [ ] **Verification:**
    - [ ] Open Settings > Typing Behavior. Set WPM > 150. Verify warning appears.
    - [ ] Open Settings > Inference Engine. Verify "LLM Model (Gemma)" dropdown exists.
    - [ ] Select a model, click "Check Status". Verify status updates.
    - [ ] Click "Download" (if not present). Verify background download starts (check console).
    - [ ] Save profile. Restart app. Verify LLM model selection persists.
    - [ ] Test invalid values (e.g., negative numbers for timeouts).

### `user_profile_manager.py`
- [x] **Necessity:** Multi-user/profile support. Keep.
- [x] **Fixes:** 
    - [x] Ensure valid filename generation (sanitize inputs).
- [ ] **Features:** 
    - [ ] Import/Export profiles (shareable YAMLs).
- [ ] **Verification:**
    - [ ] Create new profile with special characters.
    - [ ] Switch profiles while recording (stress test).

### `model_manager.py`
- [x] **Necessity:** Managing local LLM/Whisper models. Keep.
- [x] **Fixes:** Added `check_model_exists`, `delete_model` for UI integration.
- [x] **Improvements:** 
    - [x] Progress bar for model downloads (Implemented in console).
    - [x] Unsloth Gemma 3 GGUF support (4B & 12B, Q4/Q6/Q8).
- [x] **Features:** 
    - [x] Add 12B model support.
    - [x] Q6/Q8 quantization options.
- [ ] **Verification:**
    - [ ] Delete a model file, verify re-download triggers.
    - [ ] Download a new model variant (e.g., 12B Q4) and verify it loads.
    - [ ] Corrupt a model file (partial delete) and verify recovery or error.

## Generators & Build

### `project_generator.py`
- [ ] **Necessity:** Dev tool or user feature? Unclear usage in current `main.py`.
- [ ] **Decision:** [REMOVE] or [KEEP] if planning "Generate Project" feature via LLM.
- [ ] **Verification:**
    - [ ] If kept, does it generate valid projects?

### `text_formatter.py`
- [x] **Necessity:** Cleaning output text. Keep.
- [ ] **Fixes:** 
    - [ ] Markdown parsing issues (ensure nested lists work).
- [ ] **Improvements:** 
    - [ ] Add options for more customization (bullet vs numbered lists).
    - [ ] Drop-down menu for format style (Email, Code, List).
    - [ ] Custom prompt box for specific formatting rules.
- [ ] **Verification:**
    - [ ] Test mixed content (code blocks + text).
    - [ ] Verify list formatting behavior.

### `requirements.txt`
- [x] **Necessity:** Dependency list. Keep.
- [x] **Action:** 
    - [x] Audit for unused packages (e.g., `sentence-transformers` if not used).
    - [x] Pin versions for stability (e.g., `faster-whisper==0.10.0`).
- [x] **Verification:**
    - [x] Fresh install in new venv using this file.
    - [x] Check for known vulnerabilities in pinned versions.

### `enable_cuda.bat`
- [x] Removed as stale utility script (no longer part of supported build/runtime flow).

---
**General Audit Tasks:**
1. [ ] Run `pylint` or `flake8` on all files.
2. [ ] Check for hardcoded paths (use `os.path.join` or `pathlib`).
3. [ ] Check for exposed API keys or credentials.
