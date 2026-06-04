# BetterFingers Electron Full Functionality TODO - Expanded Release Plan

## Purpose

This document replaces the earlier short-form Electron TODO with a more detailed implementation, verification, and release-readiness plan.

The main goal is still simple:

> Bring BetterFingers to full Electron functionality on Linux and Windows while keeping the Python FastAPI backend as the source of truth until Electron reaches verified parity with the legacy Python desktop shell.

The bigger product goal remains:

> Build BetterFingers from a voice-to-text / AI voice-to-text / TTS utility into a reliable user-side assistant that can help with planning, goals, reminders, writing, review, and later controlled local-agent behavior.

The important constraint:

> Do not build planner/agent features on top of an unstable base. The Electron shell, backend contracts, settings system, audio pipeline, model pipeline, packaging, and QA must be dependable first.

---

## Status Legend

Use these labels when updating phase items.

- `[x] Implemented` - Code or UI exists and is wired.
- `[ ] Not started` - No meaningful implementation yet.
- `[ ] Needs QA` - Implementation exists but has not passed Linux/Windows manual QA.
- `[ ] Needs tests` - Implementation exists but lacks automated coverage.
- `[ ] Needs UX pass` - Function exists but is clunky, unclear, too basic, or not user-friendly.
- `[ ] Needs robustness pass` - Function works in the happy path but needs error handling, recovery, cancellation, or edge-case handling.
- `[ ] Deferred` - Intentionally postponed until after Electron parity.

A checkbox should only move to fully complete when it has:

1. Backend behavior or Electron UI implemented.
2. Clear user-facing error handling.
3. Linux and/or Windows behavior explicitly handled.
4. Manual QA completed where relevant.
5. Automated test coverage where practical.

Implementation alone is not enough for release-complete status.

---

## Guiding Rules

- Keep backend behavior shared wherever possible instead of duplicating old desktop logic in Electron.
- Prefer FastAPI endpoints and WebSocket events for UI state.
- Preserve secure Electron defaults:
  - `contextIsolation: true`
  - `nodeIntegration: false`
  - preload bridge only
- Keep Linux support explicit:
  - X11 behavior should be tested separately from Wayland.
  - Wayland limitations should be shown clearly.
  - Windows-only behavior should never silently pretend to work on Linux.
- Do not remove the legacy Python desktop app until a separate cutover plan is approved.
- Do not begin planner/agent expansion until:
  - record/review/send is reliable
  - settings are stable
  - TTS is real
  - audio devices are diagnosable
  - packaging works
  - manual QA passes on Linux and Windows
- Every future agent-style capability must be permissioned, inspectable, and user-controlled.

---

# Current Reality Snapshot

## What is currently strong

- Electron app shell exists.
- Python FastAPI backend sidecar startup exists.
- Backend health/runtime diagnostics exist.
- Draft pipeline exists.
- No-audio gate is wired into the recording pipeline.
- Draft history exists as session-only latest-20 history.
- Draft accept/decline/retry/edit/rewrite/send flows exist.
- Linux capability checks exist for clipboard/input injection/global hotkeys.
- Profile/settings endpoints exist.
- Model management endpoints and UI exist.
- Review panel exists and is already more flexible than a simple preview overlay.

## What is not release-ready yet

- TTS is still mostly mock/stub behavior.
- Settings UI is too basic and currently behaves like one long settings scroll.
- Themes, responsive layout, and visual polish are missing.
- Audio device selection/testing/live meters are missing.
- Notifications/mini status UI are not restored.
- Packaging exists structurally but needs Linux and Windows smoke tests.
- Automated test coverage is not yet sufficient.
- Manual QA checklist still needs to be run and updated.
- Backend robustness needs a deliberate pass before planner/agent systems are added.

---

# Phase 0: Baseline Inventory, Parity Map, And Documentation Sync

## Goal

Make sure every original BetterFingers feature has a clear Electron destination, explicit platform status, and up-to-date documentation.

## Current status

Implemented, but docs need synchronization.

## Checklist

- [x] Create a feature inventory from the original Python desktop app.
  - Current detail: `docs/ELECTRON_FEATURE_PARITY_MAP.md` exists and maps major legacy features.
  - Remaining detail: update it to reflect newer Phase 2-6 work that has since been implemented.
- [x] Mark each original feature as one of:
  - `portable`
  - `Windows-only`
  - `Linux-ready`
  - `linux-limited`
  - `needs abstraction`
  - `defer`
- [x] Define Electron destination for major workflows.
  - Dashboard
  - Review panel
  - Settings/profiles
  - Models
  - Diagnostics
  - Capabilities
  - WebSocket status
- [x] Decide overlay migration strategy at a high level.
  - Old preview overlay becomes Electron Review panel first.
  - Old status overlay becomes dashboard state first, then optional mini status window.
  - Old notification overlay becomes Electron toast/native notification system later.
  - Old splash screen remains deferred unless startup becomes slow.
- [x] Add a Linux and Windows manual QA checklist.
- [ ] Needs QA: run the existing manual QA checklist and mark real results.
- [ ] Needs docs pass: update the parity map after every completed implementation phase.
- [ ] Needs docs pass: remove stale "Immediate Next Tasks" entries once those tasks are completed.
- [ ] Needs docs pass: add a release-status table showing:
  - implemented
  - manual-QA passed
  - automated-tested
  - release-blocked
  - deferred
- [ ] Needs docs pass: add screenshots or short UX notes after the settings/UI redesign.

## Done when

- [ ] Every original BetterFingers feature has one clear migration destination.
- [ ] Every feature has platform status.
- [ ] TODO, parity map, QA checklist, and rebuild plan do not contradict each other.
- [ ] Linux limitations are documented in user-facing language.
- [ ] The document separates "implemented" from "verified."

---

# Phase 1: Core Runtime, Sidecar, And Diagnostics

## Goal

Electron should reliably start, monitor, diagnose, and shut down the Python backend on Linux and Windows.

## Current status

Mostly implemented, needs deeper QA and robustness pass.

## Checklist

- [x] Electron shell starts the Python FastAPI backend.
  - Current detail: Electron sidecar starts the backend in dev and packaged modes.
  - Current detail: sidecar can detect an already-running BetterFingers backend and use it without owning the process.
- [x] Lazy backend startup allows `/health` to respond quickly.
  - Current detail: lazy startup prevents heavyweight STT/LLM initialization from blocking health.
- [x] Runtime warmup supports:
  - STT
  - LLM
  - hotkeys
- [x] Dashboard shows:
  - backend health
  - runtime status
  - transcriber status
  - LLM status
  - WebSocket status
  - platform capabilities
- [x] Linux `llama-server` can be configured through:
  - repo-local path
  - environment override
- [x] Backend log tail endpoint exists.
- [x] Runtime error history panel exists.
- [x] Model/runtime path diagnostics exist.
- [x] Port conflict detection exists.
  - Current detail: port conflict with non-BetterFingers process should show a useful message instead of silently failing.
- [ ] Needs QA: verify backend starts on Linux dev mode.
- [ ] Needs QA: verify backend starts on Windows dev mode.
- [ ] Needs QA: verify backend starts from packaged Linux build.
- [ ] Needs QA: verify backend starts from packaged Windows build.
- [ ] Needs QA: verify Electron-owned backend is killed on app quit.
- [ ] Needs QA: verify externally-owned backend is not killed on app quit.
- [ ] Needs robustness pass: capture backend stdout/stderr into a persistent diagnostic view.
- [ ] Needs robustness pass: add a single `/doctor` endpoint summarizing:
  - backend health
  - STT status
  - LLM status
  - TTS status
  - hotkey status
  - model path status
  - audio device status
  - platform limitations
  - common recovery instructions
- [ ] Needs robustness pass: add a backend API contract version.
  - Example: `/runtime/version`
  - Include backend version, Electron expected API version, schema version, config version.
- [ ] Needs robustness pass: show "backend API mismatch" if Electron and backend versions drift.
- [ ] Needs robustness pass: classify runtime errors by severity:
  - `info`
  - `warning`
  - `recoverable`
  - `fatal`
- [ ] Needs robustness pass: add user-facing recovery steps for common failures:
  - missing model
  - missing llama-server
  - port conflict
  - microphone unavailable
  - unsupported Wayland injection
  - failed clipboard
  - failed TTS dependency
- [ ] Needs tests: backend health endpoint.
- [ ] Needs tests: runtime status endpoint.
- [ ] Needs tests: port conflict behavior where practical.
- [ ] Needs tests: diagnostics path snapshot structure.

## Done when

- [ ] A user can see exactly why STT, LLM, hotkeys, TTS, microphone, or llama-server is not ready.
- [ ] Warmup failures never appear as generic unexplained 500s in Electron.
- [ ] Electron can survive backend startup failure and show recovery guidance.
- [ ] Electron quit behavior never leaves zombie BetterFingers backend processes.
- [ ] Packaged Linux and Windows startup behavior is manually verified.

---

# Phase 2: Recording To Draft Pipeline

## Goal

Hotkey recording should reliably produce a reviewable draft with raw transcript, cleaned output, metadata, and clear failure states.

## Current status

Implemented, needs real-use QA and automated state-transition tests.

## Checklist

- [x] Hotkey recording result can create an in-memory draft.
  - Current detail: backend stores drafts in a session queue.
- [x] Draft endpoints exist:
  - `GET /drafts`
  - `GET /drafts/latest`
  - accept endpoint
  - decline endpoint
  - retry endpoint
  - edit endpoint
  - rewrite endpoint
  - send endpoint
- [x] Electron dashboard previews:
  - latest raw transcript
  - latest cleaned output
  - current draft status
- [x] Electron can copy cleaned output to clipboard.
- [x] No-audio gate parity exists using `audio_gate.py`.
  - Current detail: silent/empty recordings create blocked drafts instead of wasting LLM cleanup.
- [x] Draft metadata includes:
  - duration
  - sample count
  - RMS amplitude
  - max amplitude
  - stop reason
- [x] Draft error state exists for:
  - transcription failures
  - LLM failures
  - blocked no-audio results
- [x] Draft retry action exists.
  - Current detail: retry depends on retained recording data.
- [x] Draft history panel exists.
  - Current detail: latest 20 drafts are retained for the session.
- [x] Session-only draft storage is messaged in the UI.
- [x] WebSocket events exist for major draft states.
- [ ] Needs QA: verify real hotkey recording creates draft on Linux X11.
- [ ] Needs QA: verify hotkey behavior on Linux Wayland.
- [ ] Needs QA: verify real hotkey recording creates draft on Windows.
- [ ] Needs QA: verify silent recording is blocked.
- [ ] Needs QA: verify very short accidental recording is blocked.
- [ ] Needs QA: verify long recording produces understandable metadata and warning.
- [ ] Needs QA: verify failed STT produces a draft error state.
- [ ] Needs QA: verify failed LLM produces a draft error state.
- [ ] Needs robustness pass: add a "clear draft history" action.
- [ ] Needs robustness pass: add a dev/test-only endpoint to create fake drafts for UI testing.
- [ ] Needs robustness pass: decide whether any draft persistence is wanted.
  - Default recommendation: keep session-only for now.
  - Future option: local encrypted/personal draft history with explicit user opt-in.
- [ ] Needs robustness pass: add max text length and timeout handling for cleanup.
- [ ] Needs robustness pass: protect against rapid repeated recordings while a previous draft is still processing.
- [ ] Needs robustness pass: add cancellation semantics for:
  - recording
  - transcribing
  - rewriting
  - cleanup
- [ ] Needs tests: draft creation state.
- [ ] Needs tests: blocked no-audio draft.
- [ ] Needs tests: retry with missing recording returns clear error.
- [ ] Needs tests: max history limit keeps latest 20.
- [ ] Needs tests: draft edit resets accepted/sent state safely.

## Done when

- [ ] Recording with hotkeys reliably produces drafts on Linux and Windows.
- [ ] Empty/silent recordings do not trigger unwanted LLM cleanup.
- [ ] User can inspect, copy, accept, decline, edit, rewrite, send, and retry drafts.
- [ ] Draft pipeline failures are understandable and recoverable.
- [ ] Core draft state transitions have automated tests.

---

# Phase 3: Send Modes, Injection, Clipboard Safety, And Primary Action

## Goal

BetterFingers should safely move accepted text into the user's active workflow without destroying clipboard contents or failing silently on unsupported platforms.

## Current status

Implemented at backend level, needs platform QA and safety hardening.

## Checklist

- [x] Backend abstraction exists for output actions:
  - `copy_only`
  - `paste`
  - `type`
  - `open_chat_then_send`
- [x] `/drafts/{id}/send` endpoint exists.
- [x] Accepted draft can be queued for pending manual send.
- [x] Primary action behavior exists:
  - if accepted draft is pending, send it
  - if no draft is pending, capture selected text for review/TTS flow
- [x] Send mode settings exist:
  - review-first
  - auto-send
  - manual send / copy-only behavior
- [x] Clipboard snapshot/restore behavior is retained through backend selected-text capture.
- [x] Linux-aware input capability checks exist:
  - X11 paste/type support
  - Wayland fallback to clipboard copy
  - Windows behavior
- [x] Emergency stop exists for recording and typing.
- [ ] Needs QA: verify copy-only on Linux X11.
- [ ] Needs QA: verify paste injection on Linux X11.
- [ ] Needs QA: verify fallback behavior on Linux Wayland.
- [ ] Needs QA: verify paste/type/open-chat behavior on Windows.
- [ ] Needs QA: verify selected-text capture restores clipboard on Windows.
- [ ] Needs QA: verify clipboard fallback works if injection fails mid-action.
- [ ] Needs robustness pass: add a visible Send Mode control in the Review panel.
  - Copy only
  - Paste
  - Type
  - Open chat then send
  - Use profile default
- [ ] Needs robustness pass: add "test send behavior" button in settings.
  - It should send a harmless test phrase to a controlled test target or copy to clipboard.
- [ ] Needs robustness pass: show exactly which output action was used after send.
  - Requested action
  - Actual action
  - Whether fallback happened
  - Failure reason
- [ ] Needs robustness pass: preserve old clipboard content even when selected-text capture fails.
- [ ] Needs robustness pass: define and test emergency stop behavior for real TTS once Phase 7 is complete.
- [ ] Needs tests: unsupported injection falls back to copy.
- [ ] Needs tests: empty send result fails cleanly.
- [ ] Needs tests: accepted draft enters pending-send queue.
- [ ] Needs tests: sending draft removes it from pending queue.
- [ ] Needs tests: failed send leaves useful error state.

## Done when

- [ ] Electron can complete record -> draft -> accept -> send/copy end to end.
- [ ] Linux users get safe fallback behavior when injection is unsupported.
- [ ] Clipboard content is restored after selected-text capture where supported.
- [ ] Send failures are visible, recoverable, and do not corrupt clipboard state.
- [ ] Primary action behavior feels predictable.

---

# Phase 4: Settings, Profiles, And Configuration UX

## Goal

Replace the legacy settings window with a robust, attractive, searchable, responsive Electron settings experience.

The current Electron settings area works as a first pass, but it is too basic: a long scroll through many settings with limited hierarchy, limited explanation, no themes, no responsive design polish, and not enough validation.

## Current status

Implemented as a basic settings page, needs major UX redesign and schema hardening.

## Checklist

### Profile endpoints and behavior

- [x] Add Electron settings page.
  - Current detail: settings are visible in the dashboard as a large section.
  - Remaining detail: should become a proper settings route/page or tabbed panel.
- [x] Expose profile endpoints:
  - [x] list profiles
  - [x] get active profile
  - [x] save profile
  - [x] switch profile
  - [x] create profile
  - [x] delete profile
- [x] Apply active profile to runtime where possible.
- [x] Needs QA: verify profile switching updates runtime without app restart.
- [x] Needs QA: verify profile save/discard/create/delete behavior.
- [x] Needs robustness pass: prevent deletion of active/default profile unless safe fallback is guaranteed.
- [x] Needs robustness pass: add import/export profile JSON.
- [x] Needs robustness pass: add duplicate profile handling.
- [x] Needs robustness pass: add profile rename.
- [x] Needs robustness pass: add profile backup before migration.

### Core settings port

- [x] Recording hotkey.
- [x] Record mode:
  - toggle
  - push-to-talk
- [x] Emergency stop.
- [x] Primary action hotkey.
- [x] Review TTS hotkey.
- [x] Open chat hotkey.
- [x] Voice mute key.
- [x] Send mode.
- [x] Auto-submit.
- [x] Current cleanup preset.
- [x] WPM / typing behavior.
- [x] Audio gate thresholds.
- [x] Audio ducking option.
- [x] Overlay/notification preferences.
- [x] Model keep-loaded flags.
- [x] Needs QA: verify every setting actually maps to backend behavior.
- [x] Needs QA: verify changing each setting either applies immediately or clearly says restart/reload is needed.
- [x] Needs robustness pass: validate hotkey syntax before save.
- [x] Needs robustness pass: prevent duplicate/conflicting hotkeys.
- [x] Needs robustness pass: validate numeric ranges.
  - WPM
  - token limits
  - audio gate thresholds
  - TTS speed/pitch later
- [x] Needs robustness pass: setting save failures should not partially corrupt profile files.
- [x] Needs tests: profile defaults.
- [x] Needs tests: profile migration.
- [x] Needs tests: invalid values are corrected or rejected safely.

### Settings UI redesign

- [x] Needs UX pass: replace one-long-scroll layout with organized sections:
  - General
  - Recording
  - Review & Drafts
  - AI Cleanup
  - Send & Injection
  - Hotkeys
  - Audio Devices
  - TTS / Read-Aloud
  - Models
  - Notifications & Status UI
  - Appearance
  - Accessibility
  - Advanced / Developer
- [x] Needs UX pass: add left sidebar or tab navigation for settings categories.
- [x] Needs UX pass: add settings search/filter.
- [x] Needs UX pass: add setting descriptions under each setting.
- [x] Needs UX pass: add inline warnings for platform-limited settings.
  - Example: "Audio ducking is Windows-only."
  - Example: "Paste/type injection may not work on Wayland."
- [x] Needs UX pass: add save/discard bar that stays visible.
- [x] Needs UX pass: show dirty-state clearly.
- [x] Needs UX pass: show "requires restart" or "requires hotkey reload" labels where needed.
- [x] Needs UX pass: add "Reset section to defaults."
- [x] Needs UX pass: add "Reset profile to defaults."
- [x] Needs UX pass: add "Test this setting" where useful.
  - Test mic
  - Test hotkey conflict
  - Test TTS voice
  - Test paste/copy behavior
  - Test model load

### Themes and appearance

- [x] Needs UX pass: add theme support:
  - System
  - Dark
  - Light
- [x] Needs UX pass: add accent color support.
- [x] Needs UX pass: add compact/comfortable density.
- [x] Needs UX pass: add font size scaling.
- [x] Needs UX pass: add high contrast mode.
- [x] Needs UX pass: make settings responsive for:
  - small laptop screens
  - large desktop monitors
  - split-screen use
- [x] Needs UX pass: create reusable UI components:
  - setting row
  - setting group
  - toggle
  - select
  - text input
  - hotkey recorder input
  - warning callout
  - status pill
  - capability badge
  - action button group
- [x] Every setting has a clear label, explanation, validation, and platform status if needed.
- [x] Profile changes affect runtime without restarting Electron unless restart is explicitly required.
- [x] Settings are visually polished enough that they feel like a real app, not a debug panel wearing a trench coat.

---

# Phase 5: Model Management

## Goal

Users should understand, configure, download, test, unload, and troubleshoot STT and LLM models without guessing where files live.

## Current status

Implemented in core form, needs progress UX, hardware estimates, validation, and QA.

## Checklist

### LLM model management

- [x] List LLM models.
- [x] Get selected LLM model.
- [x] Select LLM model.
- [x] Download LLM model.
- [x] Delete LLM model.
- [x] Show download state.
- [x] Add Linux `llama-server` setup/status UI.
- [x] Add diagnostics for:
  - `BETTERFINGERS_LLAMA_SERVER`
  - `BETTERFINGERS_MODEL_PATH`
- [x] Preserve Windows model download behavior.
- [x] Keep Linux from downloading Windows CUDA assets.
- [ ] Needs QA: Windows model download flow.
- [ ] Needs QA: Linux model path override.
- [ ] Needs QA: repo-local Linux llama-server path.
- [ ] Needs robustness pass: add download cancellation.
- [ ] Needs robustness pass: add checksum/hash validation for downloaded models where possible.
- [ ] Needs robustness pass: add partial download cleanup.
- [ ] Needs robustness pass: add disk-space check before download.
- [ ] Needs robustness pass: add "open model folder."
- [ ] Needs robustness pass: add "repair model install."
- [ ] Needs robustness pass: add update/migration behavior for renamed models.
- [ ] Needs tests: selected model persists to profile.
- [ ] Needs tests: missing model shows clear status.
- [ ] Needs tests: invalid model ID fails safely.

### Whisper/STT model management

- [x] List Whisper models.
- [x] Download Whisper model.
- [x] Remove Whisper model.
- [x] Test Whisper model.
- [x] Unload STT.
- [ ] Needs QA: test each supported Whisper model size.
- [ ] Needs QA: verify GPU/CPU fallback behavior.
- [ ] Needs robustness pass: show installed size and path.
- [ ] Needs robustness pass: add disk-space warning.
- [ ] Needs robustness pass: show current active STT model clearly.
- [ ] Needs robustness pass: add "test transcription" with sample audio or mic test.
- [ ] Needs tests: unsupported model size fails clearly.
- [ ] Needs tests: remove active model unloads or switches safely.

### Runtime/memory estimates

- [x] Basic selected model size summary exists.
- [ ] Needs robustness pass: replace simple model-size display with real estimate fields:
  - LLM disk size
  - estimated RAM usage
  - estimated VRAM usage
  - STT estimated RAM/VRAM
  - combined estimated load
  - recommended minimum system memory
- [ ] Needs robustness pass: detect available system RAM.
- [ ] Needs robustness pass: detect GPU/VRAM where possible.
- [ ] Needs robustness pass: show CPU-only warning if GPU runtime is not available.
- [ ] Needs robustness pass: show "safe/default/recommended" model choice.
- [ ] Needs UX pass: present model status as cards instead of dense text.

## Done when

- [ ] Fresh Linux user can understand what local LLM runtime is missing and how to configure it.
- [ ] Windows user can still use the existing model download flow.
- [ ] User can test STT and LLM readiness from the UI.
- [ ] Model download/install/delete failures are recoverable.
- [ ] Model status is understandable without opening logs.

---

# Phase 6: Preview, Review, Rewrite, And Draft UX

## Goal

The Electron review workflow should match or exceed the old preview overlay while feeling comfortable for everyday writing.

## Current status

Mostly implemented, needs UX polish and failure handling.

## Checklist

- [x] Expand Electron Latest Draft into a Review panel.
- [x] Add editable cleaned output.
- [x] Add rewrite actions:
  - [x] make shorter
  - [x] make clearer
  - [x] change tone
  - [x] custom instruction
- [x] Add selected-text-aware draft TTS request.
  - Current detail: UI and endpoint shape exist.
  - Limitation: real TTS playback is Phase 7 and is not done.
- [x] Add token count and long-text warning.
  - Current limitation: current token count appears approximate and should not be treated as true tokenizer count.
- [x] Add review state WebSocket updates.
- [x] Add keyboard shortcuts for:
  - accept
  - decline
  - copy
  - send
  - save
- [ ] Needs UX pass: add a visible shortcut help menu.
- [ ] Needs UX pass: add undo/redo for draft edits and rewrites.
- [ ] Needs UX pass: add before/after diff for rewrite results.
- [ ] Needs UX pass: add preset selector in the Review panel.
- [ ] Needs UX pass: add custom preset manager later.
- [ ] Needs UX pass: show rewrite in progress clearly and prevent double-click duplicate rewrites.
- [ ] Needs UX pass: add empty-state messaging that tells the user how to create a draft.
- [ ] Needs UX pass: make draft history easier to browse.
  - time
  - status
  - preset
  - short preview
  - action buttons
- [ ] Needs UX pass: add "copy raw transcript" in addition to cleaned output.
- [ ] Needs UX pass: add "restore raw transcript as output."
- [ ] Needs robustness pass: if LLM is unavailable, disable rewrite with clear reason.
- [ ] Needs robustness pass: if selected text is too long, warn before TTS/rewrite.
- [ ] Needs robustness pass: failed rewrite should keep prior text untouched.
- [ ] Needs robustness pass: long-text warning should use a better tokenizer or clearly say approximate.
- [ ] Needs QA: edit -> save -> accept -> send.
- [ ] Needs QA: rewrite -> accept -> send.
- [ ] Needs QA: failed rewrite.
- [ ] Needs QA: keyboard shortcuts.
- [ ] Needs tests: edit draft.
- [ ] Needs tests: rewrite draft success.
- [ ] Needs tests: rewrite draft failure.
- [ ] Needs tests: accepted/sent draft edited back to pending.

## Done when

- [ ] Electron review flow matches or exceeds the old preview overlay behavior.
- [ ] A user can comfortably review, rewrite, edit, copy, accept, decline, retry, and send.
- [ ] Draft interactions feel safe and reversible.
- [ ] LLM and TTS failures do not destroy user text.

---

# Phase 7: TTS And Read-Aloud

## Goal

Restore real review TTS, selected-text read-aloud, sample playback, stop playback, and voice handling.

## Current status

Not complete. Mock endpoint/UI wiring exists, but real playback needs implementation.

## Checklist

### Backend TTS

- [x] Mock `/tts/speak` endpoint exists.
- [x] Mock `/drafts/{id}/tts` endpoint exists.
- [x] `/tts/voices` endpoint exists.
- [ ] Replace mock `/tts/speak` behavior with real backend playback or generated audio response.
- [ ] Add TTS provider abstraction.
  - Kokoro or current intended engine
  - fallback provider
  - no-op/missing-provider status
- [ ] Add generated audio file handling:
  - temp path
  - cleanup policy
  - content type
  - duration
  - voice metadata
- [ ] Add direct playback backend path or Electron audio playback path.
- [ ] Add TTS runtime status endpoint.
- [ ] Add TTS warmup endpoint.
- [x] Add TTS unload endpoint shape through model unload.
- [ ] Add dedicated TTS unload behavior if needed.
- [ ] Add stop TTS endpoint.
- [ ] Add TTS queue/cancel behavior.
- [ ] Add selected-text read-aloud from primary/review hotkey.
- [ ] Linux-check TTS dependencies.
- [ ] Windows-check TTS dependencies.
- [ ] Add clear fallback/error if TTS backend is missing.

### Electron TTS UI

- [x] Read selected draft text button exists.
- [x] Read full draft button exists.
- [ ] Wire buttons to real playback.
- [ ] Add voice list UI in settings.
- [ ] Add TTS sample playback controls.
- [ ] Add stop playback button.
- [ ] Add selected/current voice display.
- [ ] Add TTS speed control.
- [ ] Add TTS pitch control if supported.
- [ ] Add loading state during synthesis.
- [ ] Add error state for missing voice/dependency.
- [ ] Add "read selected text from active app" flow after selected-text capture works reliably.
- [ ] Add option to auto-read accepted/cleaned draft if user enables it.

### QA and tests

- [ ] Needs QA: speak full draft on Linux.
- [ ] Needs QA: speak selected draft text on Linux.
- [ ] Needs QA: stop playback on Linux.
- [ ] Needs QA: speak full draft on Windows.
- [ ] Needs QA: speak selected draft text on Windows.
- [ ] Needs QA: stop playback on Windows.
- [ ] Needs tests: missing TTS backend returns clear status.
- [ ] Needs tests: empty TTS text returns clean error.
- [ ] Needs tests: stop TTS is safe when nothing is playing.
- [ ] Needs tests: voice list endpoint returns expected structure.

## Done when

- [ ] Review TTS and selected-text read-aloud work from Electron.
- [ ] Missing TTS backend shows a clear fallback/error.
- [ ] User can test voices in settings.
- [ ] User can stop playback instantly.
- [ ] TTS failures never block draft review or send.

---

# Phase 8: Notifications, Status UI, Overlays, And Onboarding

## Goal

BetterFingers should provide clear non-dashboard feedback during normal use.

A dashboard is useful for diagnostics, but users need lightweight state feedback while working in other apps.

## Current status

Mostly not implemented.

## Checklist

### Strategy

- [ ] Decide replacement strategy:
  - [ ] dashboard-only status for development
  - [ ] Electron always-on-top mini status window
  - [ ] Electron toast window
  - [ ] native OS notifications
  - [ ] tray status
- [ ] Decide what must be visible outside the dashboard:
  - idle
  - listening
  - recording
  - processing
  - draft ready
  - copied
  - sent
  - error
  - TTS playing
  - emergency stopped
- [ ] Define platform behavior:
  - Windows
  - Linux X11
  - Linux Wayland
- [ ] Decide whether mini windows are optional and user-positioned.

### Implementation

- [ ] Add recording/listening/processing/idle visual state outside dashboard.
- [ ] Add toast notifications for important events.
- [ ] Add notification preferences:
  - enabled/disabled
  - sound/no sound
  - duration
  - position
  - quiet mode
- [ ] Add draggable mini status window if retained.
- [ ] Add mini-window position persistence.
- [ ] Add native notifications where appropriate.
- [ ] Add tray menu status and quick actions:
  - show app
  - start/stop hotkeys
  - emergency stop
  - open settings
  - quit
- [ ] Add startup splash/loading screen only if startup becomes slow.
- [ ] Port guided tour/onboarding into Electron.
- [ ] Add first-run setup:
  - choose microphone
  - choose model/runtime
  - test recording
  - test cleanup
  - test send mode
  - explain Linux limitations
- [ ] Add "what just happened?" mini log for recent user-facing events.

### QA and tests

- [ ] Needs QA: notifications on Linux X11.
- [ ] Needs QA: notifications on Linux Wayland.
- [ ] Needs QA: notifications on Windows.
- [ ] Needs QA: mini window does not steal focus unexpectedly.
- [ ] Needs QA: notification settings persist.
- [ ] Needs tests: notification preference state.
- [ ] Needs tests: event-to-notification mapping.

## Done when

- [ ] User gets clear non-dashboard feedback during normal use.
- [ ] Overlay behavior is safe and Linux/Wayland limitations are clearly handled.
- [ ] First-run user can understand how to use BetterFingers without reading docs.
- [ ] Status feedback does not interrupt the user's workflow.

---

# Phase 9: Audio And Device Controls

## Goal

Users should be able to select, test, and diagnose microphone input before relying on BetterFingers.

## Current status

Not complete. Recording metadata exists, but user-facing audio device controls are missing.

## Checklist

### Device control

- [ ] Expose microphone/input device listing endpoint.
- [ ] Add selected input device setting.
- [ ] Persist selected input device in profile.
- [ ] Handle missing device after unplug/reboot.
- [ ] Add default system input option.
- [ ] Show current active input device.
- [ ] Show sample rate/channel info if available.
- [ ] Add platform-specific backend:
  - Windows input devices
  - Linux PipeWire/PulseAudio/ALSA awareness
  - fallback generic device list

### Recording diagnostics

- [ ] Add recording test endpoint.
- [ ] Add recording test UI.
- [ ] Add live audio level meter during recording.
- [ ] Add pre-recording mic level meter in settings.
- [ ] Add audio gate diagnostics:
  - duration
  - RMS
  - peak
  - gate threshold
  - pass/fail reason
- [ ] Add "why was this blocked?" explanation for silent drafts.
- [ ] Add input clipping warning.
- [ ] Add low-volume warning.
- [ ] Add "no input detected" warning.
- [ ] Add "wrong mic?" hint when input stays silent.

### Audio ducking

- [ ] Add audio ducking status display.
- [ ] Add Linux capability messaging for unsupported ducking.
- [ ] Preserve Windows ducking behavior.
- [ ] Add setting tooltip explaining ducking limitations.
- [ ] Add fallback behavior if ducking fails.

### QA and tests

- [ ] Needs QA: mic listing on Linux.
- [ ] Needs QA: mic listing on Windows.
- [ ] Needs QA: selected device persists.
- [ ] Needs QA: unplugged selected device recovers clearly.
- [ ] Needs QA: live meter updates.
- [ ] Needs QA: recording test creates useful result.
- [ ] Needs tests: device list response structure.
- [ ] Needs tests: invalid selected device falls back safely.
- [ ] Needs tests: audio gate diagnostic shape.

## Done when

- [ ] User can select/test microphone and understand whether audio is being captured.
- [ ] Silent/failed recordings are diagnosable from the UI.
- [ ] BetterFingers does not feel broken when the wrong microphone is selected.

---

# Phase 10: Backend Robustness, API Contracts, And Runtime Safety

## Goal

Make the backend strong enough to support future planner/agent systems without becoming fragile.

The backend must become a stable local service with clear contracts, predictable state, safe concurrency, structured errors, and recoverable failure modes.

## Current status

Partially implemented through existing endpoints, but needs deliberate hardening.

## Checklist

### API contracts

- [ ] Add API version endpoint.
- [ ] Add schema/config version endpoint.
- [ ] Add structured response models for core endpoints.
- [ ] Add consistent response format:
  - `ok`
  - `status`
  - `message`
  - `data`
  - `error`
  - `details`
- [ ] Add consistent error model:
  - error code
  - user message
  - developer details
  - recovery hint
- [ ] Add endpoint documentation for Electron-facing routes.
- [ ] Add route grouping:
  - `/runtime`
  - `/drafts`
  - `/profiles`
  - `/models`
  - `/audio`
  - `/tts`
  - `/diagnostics`
  - `/capabilities`
  - `/planner` later
  - `/agent` later, if approved

### State management

- [ ] Audit global state:
  - transcriber
  - LLM engine
  - hotkey manager
  - recorder
  - output injector
  - TTS engine
  - active WebSockets
  - draft queue
  - pending send queue
- [ ] Add safe locking around shared mutable state.
- [ ] Avoid blocking event loop during heavyweight operations.
- [ ] Move long-running tasks into background workers where needed.
- [ ] Add operation IDs for:
  - recording
  - transcription
  - rewrite
  - TTS
  - model download
  - warmup
- [ ] Add cancellation support for long-running tasks.
- [ ] Add timeout handling for:
  - STT
  - LLM cleanup
  - rewrite
  - TTS
  - downloads
  - send/injection

### Reliability

- [ ] Add startup self-check.
- [ ] Add runtime self-check.
- [ ] Add automatic recovery where safe:
  - reload profile
  - reconnect WebSocket
  - reinitialize clipboard
  - reset hotkey manager
- [ ] Add "safe mode" startup.
  - disables hotkeys
  - disables injection
  - disables TTS
  - loads diagnostics only
- [ ] Add crash-safe config writes.
  - write temp file
  - validate
  - atomic replace
- [ ] Add log rotation.
- [ ] Add debug bundle export:
  - logs
  - config summary
  - diagnostics
  - platform info
  - no secrets/API keys
- [ ] Add privacy scrubber for logs and debug bundle.
- [ ] Add guardrails for future agent features:
  - explicit permissions
  - audit log
  - user confirmation for actions
  - no broad file/system access by default
  - no uncontrolled remote command execution

### Security and privacy

- [ ] Ensure Electron only talks to localhost backend.
- [ ] Decide if local backend needs auth token from Electron.
- [ ] Prevent other local processes from easily controlling BetterFingers if endpoints become powerful.
- [ ] Add CORS tightening for production.
- [ ] Add local API token for packaged app if needed.
- [ ] Avoid logging raw user text by default.
- [ ] Add privacy mode:
  - no draft persistence
  - minimal logs
  - no text in debug bundle
- [ ] Add user-facing data location page.
- [ ] Add "clear app data" action.
- [ ] Add "open config folder" action.

### Tests

- [ ] Needs tests: consistent error response.
- [ ] Needs tests: config write/rollback.
- [ ] Needs tests: operation cancellation.
- [ ] Needs tests: simultaneous draft operations.
- [ ] Needs tests: WebSocket reconnect behavior.
- [ ] Needs tests: safe-mode startup.
- [ ] Needs tests: debug bundle excludes sensitive text.

## Done when

- [ ] Backend can be treated as a stable local service.
- [ ] Electron can rely on consistent contracts.
- [ ] Future planner/agent systems have safe runtime foundations.
- [ ] Failures are recoverable and diagnosable.
- [ ] Sensitive user text is protected by default.

---

# Phase 11: App UI/UX System, Layout, Themes, And Responsiveness

## Goal

Move the Electron UI from a functional dashboard into a polished app shell that can grow.

This phase is separate from settings because the whole app needs design structure, not just the settings page.

## Current status

Functional but visually basic.

## Checklist

### Navigation and layout

- [ ] Add app-level navigation.
  - Dashboard
  - Review
  - Settings
  - Models
  - Audio
  - Diagnostics
  - Planner later
  - Advanced later
- [ ] Decide layout style:
  - sidebar navigation
  - top tabs
  - command palette
  - hybrid
- [ ] Split massive dashboard into focused pages/panels.
- [ ] Keep diagnostics available but do not make normal users live in diagnostics.
- [ ] Add responsive layout rules for:
  - narrow screens
  - medium laptop screens
  - ultrawide screens
- [ ] Add consistent spacing, cards, headers, and status components.
- [ ] Add reusable empty states.
- [ ] Add loading skeletons or clear loading states.
- [ ] Add error boundaries for renderer failures.

### Theme system

- [ ] Add CSS variables for:
  - background
  - surface
  - text
  - muted text
  - border
  - accent
  - warning
  - danger
  - success
- [ ] Add light/dark/system theme.
- [ ] Add accent color options.
- [ ] Add high contrast option.
- [ ] Add compact/comfortable density.
- [ ] Add reduced motion support.
- [ ] Store UI preferences.
- [ ] Add theme preview.

### Accessibility

- [ ] Add keyboard navigation audit.
- [ ] Add focus states.
- [ ] Add ARIA labels where needed.
- [ ] Add screen-reader-friendly status updates.
- [ ] Add color contrast audit.
- [ ] Add font scaling.
- [ ] Ensure buttons and inputs have clear disabled reasons.
- [ ] Ensure text areas are usable with keyboard-only flow.

### UX polish

- [ ] Add onboarding.
- [ ] Add first-run checklist.
- [ ] Add quick actions:
  - Start hotkeys
  - Record test
  - Open Review
  - Open Settings
  - Open Diagnostics
- [ ] Add command palette later.
- [ ] Add "recent events" activity feed.
- [ ] Add friendly recovery copy for common errors.
- [ ] Replace raw JSON where possible with readable UI.
- [ ] Keep raw JSON available in developer/advanced mode.

### Tests

- [ ] Needs renderer tests: dashboard renders.
- [ ] Needs renderer tests: settings navigation renders.
- [ ] Needs renderer tests: review panel renders draft states.
- [ ] Needs renderer tests: model panel renders missing/installed states.
- [ ] Needs renderer tests: theme switch persists.
- [ ] Needs renderer tests: disabled buttons include reason or message.

## Done when

- [ ] BetterFingers feels like a coherent app instead of a collection of debug panels.
- [ ] UI is responsive, themeable, and navigable.
- [ ] Normal users see simple workflows.
- [ ] Advanced users can still reach diagnostics and raw details.

---

# Phase 12: Project, Graph, Intent, Planner, And Agent Readiness

## Goal

Decide which existing advanced backend endpoints are core product features, developer tools, or deferred experiments.

This phase should not become full agent implementation yet.

## Current status

Backend exposes some graph, plan, profile, and intent endpoints, but product direction is not finalized.

## Checklist

### Existing advanced endpoints

- [ ] Inventory graph endpoints.
- [ ] Inventory project generator endpoints.
- [ ] Inventory intent endpoints.
- [ ] Decide for each endpoint:
  - core feature
  - advanced/developer feature
  - internal-only
  - remove
  - defer
- [ ] Add UI only for endpoints that still match product direction.
- [ ] Document endpoints that remain API-only.
- [ ] Remove or hide endpoints that are not part of near-term BetterFingers.

### Planner foundation

Do not build this until Electron parity and release stability are complete.

- [ ] Define planner MVP:
  - daily plan
  - weekly plan
  - monthly goals
  - goal breakdown
  - reminders
  - progress check-ins
- [ ] Define planner data model.
  - tasks
  - goals
  - habits
  - reminders
  - notes
  - schedule blocks
  - recurrence
  - priority
  - status
- [ ] Define storage strategy:
  - local JSON
  - SQLite
  - encrypted local store later
- [ ] Define reminder strategy:
  - Electron notification
  - tray
  - OS notification
  - mobile bridge later
- [ ] Define permissions:
  - what the planner can read
  - what the planner can write
  - what actions require confirmation
- [ ] Build planner only after:
  - packaging works
  - notifications work
  - backend contracts are stable
  - settings are redesigned
  - audio/TTS are reliable

### Agent-readiness foundation

- [ ] Define local assistant permission model.
- [ ] Define action registry.
- [ ] Define tool/action audit log.
- [ ] Define user approval flow.
- [ ] Define "allowed folders/apps/actions" model.
- [ ] Define "ask before doing" rules.
- [ ] Define safe fallback if the agent is uncertain.
- [ ] Define local-only/offline mode.
- [ ] Define remote/mobile tunnel security model before implementing it.
- [ ] Defer OpenClaw-style agent behavior until the core app is stable.

## Done when

- [ ] Every existing advanced backend endpoint has a UI, documented API role, or remove/defer decision.
- [ ] Planner is designed but not allowed to destabilize Electron parity.
- [ ] Future agent behavior has a safety and permission model before implementation begins.

---

# Phase 13: Packaging And Distribution

## Goal

Produce usable Linux and Windows builds that include the Electron shell, Python backend sidecar, assets, config paths, and safe shutdown behavior.

## Current status

Build scaffolding exists, but release packaging is not proven.

## Checklist

### Build configuration

- [x] Electron Builder config exists.
- [x] Linux AppImage target exists.
- [x] Windows NSIS target exists.
- [x] Backend resources path is configured.
- [x] Build scripts exist:
  - `npm run build`
  - `npm run build:backend`
  - `npm run dist:linux`
  - `npm run dist:win`
- [ ] Package Python backend sidecar for Linux.
- [ ] Package Python backend sidecar for Windows.
- [ ] Include backend executable under Electron resources.
- [ ] Confirm packaged backend receives host/port args.
- [ ] Confirm packaged backend uses correct config/model directories.
- [ ] Decide whether repo-local `llama-server` is:
  - dev-only
  - user-installed
  - bundled
  - downloaded by setup wizard
- [ ] Include tray icon/assets reliably.
- [ ] Preserve legacy PyInstaller package until cutover.

### Smoke tests

- [ ] Linux: run `npm run build`.
- [ ] Linux: run `npm run build:backend`.
- [ ] Linux: run `npm run dist:linux`.
- [ ] Linux: launch AppImage.
- [ ] Linux: verify backend starts.
- [ ] Linux: verify health card becomes active.
- [ ] Linux: verify hotkeys or clear limitation.
- [ ] Linux: verify recording/draft/copy flow.
- [ ] Linux: verify quit kills backend if Electron owns it.
- [ ] Windows: run `npm run build`.
- [ ] Windows: run `npm run build:backend`.
- [ ] Windows: run `npm run dist:win`.
- [ ] Windows: install NSIS build.
- [ ] Windows: verify backend starts.
- [ ] Windows: verify model download behavior.
- [ ] Windows: verify hotkeys.
- [ ] Windows: verify recording/draft/copy/send flow.
- [ ] Windows: verify quit kills backend.
- [ ] Windows: verify legacy PyInstaller build still works.

### Installer/user experience

- [ ] Add first-run setup flow.
- [ ] Add missing dependency detection.
- [ ] Add install location guidance.
- [ ] Add app data/config path display.
- [ ] Add uninstall cleanup notes.
- [ ] Add portable build decision later if needed.
- [ ] Add code signing decision later.
- [ ] Add update mechanism decision later.

## Done when

- [ ] `npm run dist:linux` produces a usable Linux build.
- [ ] `npm run dist:win` produces a usable Windows build.
- [ ] Packaged app can find assets, tray icon, backend, models, config dirs, and diagnostics paths.
- [ ] Packaged app shuts down cleanly.
- [ ] Legacy build still works unchanged.

---

# Phase 14: Automated Test Coverage

## Goal

Create enough automated coverage that Electron migration work does not constantly break working features.

## Current status

Mostly not started.

## Checklist

### Backend tests

- [ ] Test `/health`.
- [ ] Test `/runtime/status`.
- [ ] Test `/runtime/warmup` with mocked STT/LLM/hotkeys.
- [ ] Test `/runtime/output-settings`.
- [ ] Test `/capabilities`.
- [ ] Test `/diagnostics/paths`.
- [ ] Test `/diagnostics/logs`.
- [ ] Test `/runtime/errors`.
- [ ] Test draft creation.
- [ ] Test draft accept.
- [ ] Test draft decline.
- [ ] Test draft retry.
- [ ] Test draft edit.
- [ ] Test draft rewrite.
- [ ] Test draft send.
- [ ] Test no-audio gate.
- [ ] Test model list/select/delete with mocks.
- [ ] Test Whisper list/download/remove/test with mocks.
- [ ] Test profile list/get/save/switch/create/delete.
- [ ] Test profile migration/defaults.
- [ ] Test platform capability decisions.
- [ ] Test model path/runtime resolution.
- [ ] Test TTS missing backend once implemented.
- [ ] Test audio device endpoints once implemented.

### Electron tests

- [ ] Renderer test: dashboard loads.
- [ ] Renderer test: review panel empty state.
- [ ] Renderer test: review panel with draft.
- [ ] Renderer test: settings sections render.
- [ ] Renderer test: profile dirty-state.
- [ ] Renderer test: save/discard behavior.
- [ ] Renderer test: model panel states.
- [ ] Renderer test: diagnostics panel.
- [ ] Renderer test: theme switching.
- [ ] Renderer test: responsive layout snapshots where practical.
- [ ] IPC test: clipboard bridge.
- [ ] IPC test: app quit.
- [ ] IPC test: sidecar status.
- [ ] Main process test: sidecar port conflict if practical.
- [ ] Main process test: sidecar shutdown if practical.

### End-to-end smoke script

- [ ] Start Electron in dev mode.
- [ ] Wait for backend.
- [ ] Confirm `/health`.
- [ ] Warm up STT.
- [ ] Warm up LLM.
- [ ] Start hotkeys or mock hotkeys.
- [ ] Create test draft.
- [ ] Accept draft.
- [ ] Copy draft.
- [ ] Send draft with copy-only fallback.
- [ ] Quit Electron.
- [ ] Verify backend exits.

### CI

- [ ] Add backend test command.
- [ ] Add renderer test command.
- [ ] Add lint command.
- [ ] Add build command.
- [ ] Add Linux CI smoke where feasible.
- [ ] Add artifact build later if useful.
- [ ] Keep heavyweight model downloads mocked in CI.

## Done when

- [ ] Core functionality is covered by automated tests plus repeatable manual QA.
- [ ] Most regressions are caught before manual testing.
- [ ] Heavy local model behavior is mocked in tests but manually verified in QA.

---

# Phase 15: Manual QA, Cutover Readiness, And Release Criteria

## Goal

Prove that Electron is ready to replace the old Python desktop UI.

## Current status

Not ready.

## Checklist

### Manual QA

- [ ] Run Linux QA.
- [ ] Run Linux X11-specific QA.
- [ ] Run Linux Wayland-specific QA.
- [ ] Run Windows QA.
- [ ] Run packaging QA.
- [ ] Run legacy PyInstaller QA.
- [ ] Run first-run setup QA once onboarding exists.
- [ ] Run microphone failure QA.
- [ ] Run missing model QA.
- [ ] Run missing llama-server QA.
- [ ] Run TTS missing dependency QA.
- [ ] Run clipboard failure QA where possible.
- [ ] Run port conflict QA.
- [ ] Run long session QA.
  - app open for hours
  - repeated recordings
  - repeated rewrites
  - repeated sends
  - quit/restart

### Performance criteria

- [ ] Measure cold start.
- [ ] Measure warm start.
- [ ] Measure backend health response.
- [ ] Measure STT warmup.
- [ ] Measure LLM warmup.
- [ ] Measure recording-to-draft latency.
- [ ] Measure rewrite latency.
- [ ] Measure TTS latency after Phase 7.
- [ ] Measure memory after startup.
- [ ] Measure memory after repeated drafts.
- [ ] Measure shutdown cleanup.
- [ ] Define acceptable thresholds.

### Release blockers

- [ ] Close all P0 issues.
- [ ] Close or document all P1 issues.
- [ ] Confirm no known data-loss bug.
- [ ] Confirm no known clipboard-corruption bug.
- [ ] Confirm no known runaway backend process bug.
- [ ] Confirm no known profile-corruption bug.
- [ ] Confirm no known broken first-run path.
- [ ] Confirm no known misleading Linux capability messaging.

### Cutover

- [ ] Run feature parity checklist against original Python app.
- [ ] Write cutover plan for replacing legacy desktop shell.
- [ ] Write rollback plan.
- [ ] Define release channel:
  - dev build
  - alpha
  - beta
  - stable
- [ ] Keep legacy Python UI available until explicit cutover approval.
- [ ] Archive old UI only after Electron has stable release history.

## Done when

- [ ] Electron is the recommended app shell.
- [ ] Legacy Python UI can be deprecated only after explicit approval.
- [ ] Linux and Windows paths are verified.
- [ ] Core workflows are fast, stable, and recoverable.

---

# Phase 16: Future Mobile Bridge, Planner Agent, And Controlled Local Assistant

## Goal

Define the future direction without letting it invade the Electron parity milestone.

This phase is intentionally future-facing. It should remain deferred until the core desktop app is stable.

## Future concept

BetterFingers eventually becomes an easy-to-use local assistant that can:

- help plan daily/weekly/monthly goals
- ask follow-up questions about schedule or progress
- send reminders
- rewrite or organize user thoughts
- work beside the user on a PC
- expose only user-approved tools/actions
- optionally connect to a mobile app while the PC is running

## Checklist

### Mobile bridge planning

- [ ] Define mobile bridge architecture.
  - local network only
  - tunnel option
  - relay option
  - no remote access by default
- [ ] Define authentication.
- [ ] Define encryption.
- [ ] Define pairing flow.
- [ ] Define device revocation.
- [ ] Define rate limits.
- [ ] Define notification flow.
- [ ] Define what mobile can do:
  - view reminders
  - add tasks
  - answer planner questions
  - trigger safe text rewrite
  - receive status
- [ ] Define what mobile cannot do without explicit approval:
  - run system commands
  - access arbitrary files
  - send messages
  - type/paste into active PC apps
  - change sensitive settings

### Planner assistant

- [ ] Build after Phase 15, not before.
- [ ] Add local planner store.
- [ ] Add planner UI.
- [ ] Add reminder scheduling.
- [ ] Add daily check-in.
- [ ] Add weekly review.
- [ ] Add monthly goal review.
- [ ] Add "break this goal into steps."
- [ ] Add "what should I do next?" helper.
- [ ] Add "capture random thought into task/note/goal."
- [ ] Add notification integration.
- [ ] Add TTS readout integration if useful.
- [ ] Add privacy controls.

### Local agent permissions

- [ ] Define tool registry.
- [ ] Define permission scopes.
- [ ] Define audit log.
- [ ] Define approval prompts.
- [ ] Define safe command execution policy.
- [ ] Define file access restrictions.
- [ ] Define app access restrictions.
- [ ] Define "ask user when uncertain" behavior.
- [ ] Define failure rollback where possible.
- [ ] Define user-facing "what did the assistant do?" log.

## Done when

- [ ] Future planner/agent/mobile work has a safe architecture plan.
- [ ] No agent-like behavior is added before the core desktop app is stable.
- [ ] The user controls what BetterFingers can access and do.
