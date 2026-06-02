# Electron Full Functionality TODO

## Goal

Bring the Electron shell to full BetterFingers functionality while keeping the Python FastAPI backend as the source of truth during the migration. The legacy Python/PyInstaller desktop app remains available until Electron reaches parity and passes release QA.

## Guiding Rules

- Keep backend behavior shared wherever possible instead of duplicating desktop logic in Electron.
- Prefer FastAPI endpoints and WebSocket events for UI state.
- Preserve secure Electron defaults: `contextIsolation: true`, `nodeIntegration: false`, preload bridge only.
- Keep Linux support explicit: show unsupported capabilities clearly instead of pretending every Windows-only workflow works.
- Do not remove the legacy Python desktop app until a separate cutover plan is approved.

## Phase 0: Baseline Inventory And Parity Map

- [ ] Create a feature inventory from the original Python desktop app.
- [ ] Mark each feature as one of: `portable`, `Windows-only`, `Linux-ready`, `needs abstraction`, `defer`.
- [ ] Define Electron route/panel structure for all major workflows.
- [ ] Decide which old overlays become Electron windows and which become backend-only services.
- [ ] Add a manual QA checklist for Linux and Windows.

Done when:

- [ ] Every original BetterFingers feature has a migration destination.
- [ ] Linux limitations are documented in user-facing language.

## Phase 1: Core Runtime And Diagnostics

Current status: mostly started.

- [x] Electron shell starts the Python FastAPI backend.
- [x] Lazy backend startup allows `/health` to respond quickly.
- [x] Runtime warmup supports STT, LLM, and hotkeys.
- [x] Dashboard shows health, runtime status, capabilities, and WebSocket status.
- [x] Linux `llama-server` can be configured through repo-local path or env override.
- [ ] Add backend log tail endpoint or IPC-backed log viewer.
- [ ] Add runtime error history panel.
- [ ] Add model/runtime path diagnostics.
- [ ] Add port conflict detection and helpful recovery message.

Done when:

- [ ] A user can see exactly why STT, LLM, hotkeys, TTS, or llama-server is not ready.
- [ ] Warmup failures never appear as unexplained generic 500s in the Electron UI.

## Phase 2: Recording To Draft Pipeline

Current status: first slice started.

- [x] Hotkey recording result can create an in-memory draft.
- [x] Drafts expose `GET /drafts`, `GET /drafts/latest`, accept, and decline endpoints.
- [x] Electron dashboard previews latest raw and cleaned draft.
- [x] Electron can copy cleaned output to clipboard.
- [ ] Add no-audio gate parity using `audio_gate.py`.
- [ ] Include recording metadata in draft: duration, sample count, RMS, max amplitude, stop reason.
- [ ] Add draft error state for transcription/LLM failures.
- [ ] Add draft retry action.
- [ ] Add draft history panel with last 20 drafts.
- [ ] Persist drafts optionally, or explicitly keep them session-only with UI messaging.
- [ ] Add WebSocket events for `recording_started`, `recording_complete`, `transcribing`, `rewriting`, `preview_ready`, `draft_accepted`, `draft_declined`, `error`, `idle`.

Done when:

- [ ] Recording with hotkeys produces a draft reliably.
- [ ] Empty/silent recordings do not trigger unwanted LLM cleanup.
- [ ] User can inspect, copy, accept, decline, and retry drafts.

## Phase 3: Send Modes, Injection, And Clipboard Safety

Original functionality includes review mode, send behavior, chat opening, typing/paste injection, mute-key handling, and clipboard-safe selected-text capture.

- [ ] Add backend abstraction for output actions: `copy_only`, `paste`, `type`, `open_chat_then_send`.
- [ ] Expose `/drafts/{id}/send` endpoint.
- [ ] Wire accepted draft to pending-send queue.
- [ ] Implement primary action hotkey behavior:
  - [ ] If accepted draft is pending, send it.
  - [ ] If no draft is pending, capture selected text for TTS/review.
- [ ] Port send mode settings: review, auto-send, manual-send/copy-only.
- [ ] Preserve clipboard snapshot/restore behavior from `clipboard_capture.py`.
- [ ] Add Linux-aware input capability checks:
  - [ ] X11 paste/type support.
  - [ ] Wayland limitations and fallback to clipboard copy.
  - [ ] Windows existing behavior.
- [ ] Add emergency stop/cancel for recording, typing, and TTS.

Done when:

- [ ] Electron can complete record -> draft -> accept -> send/copy end to end.
- [ ] Linux users get safe fallback behavior when input injection is unsupported.
- [ ] Clipboard content is restored after selected-text capture where supported.

## Phase 4: Settings And Profiles

Original settings are extensive and profile-driven.

- [ ] Add Electron settings page.
- [ ] Expose profile endpoints:
  - [ ] List profiles.
  - [ ] Get active profile.
  - [ ] Save profile.
  - [ ] Switch profile.
  - [ ] Create/delete profile.
- [ ] Port core settings:
  - [ ] Recording hotkey.
  - [ ] Record mode: toggle / push-to-talk.
  - [ ] Emergency stop.
  - [ ] Primary action hotkey.
  - [ ] Review TTS hotkey.
  - [ ] Open chat hotkey.
  - [ ] Voice mute key.
  - [ ] Send mode and auto-submit.
  - [ ] Current cleanup preset.
  - [ ] WPM/typing behavior.
  - [ ] Audio gate thresholds.
  - [ ] Audio ducking options.
  - [ ] Overlay/notification preferences.
  - [ ] Model keep-loaded flags.
- [ ] Add dirty-state and save/discard behavior.
- [ ] Add migration/defaults validation for older profiles.

Done when:

- [ ] Electron can configure the same core behavior as the old settings window.
- [ ] Profile changes affect runtime without restarting Electron unless required.

## Phase 5: Model Management

Original app supports LLM model selection, downloads, Whisper cache status, Whisper downloads, and unload/reload controls.

- [ ] Add model management backend endpoints:
  - [ ] List LLM models.
  - [ ] Get selected LLM model.
  - [ ] Select LLM model.
  - [ ] Download LLM model.
  - [ ] Delete LLM model.
  - [ ] Show download progress.
  - [ ] List Whisper models.
  - [ ] Download Whisper model.
  - [ ] Remove Whisper model.
  - [ ] Test Whisper model.
  - [ ] Unload STT.
  - [ ] Unload LLM.
  - [ ] Unload TTS.
- [ ] Add Linux llama-server setup/status UI.
- [ ] Add `BETTERFINGERS_LLAMA_SERVER` and `BETTERFINGERS_MODEL_PATH` diagnostics.
- [ ] Preserve Windows model download behavior.
- [ ] Keep Linux from downloading Windows CUDA assets.
- [ ] Add VRAM/memory estimate UI for selected STT + LLM stack.

Done when:

- [ ] A fresh Linux user can understand what local LLM runtime is missing and how to configure it.
- [ ] A Windows user can still use the existing model download flow.

## Phase 6: Preview, Review, And Rewrite UX

Original app has a preview overlay with accept, decline, TTS, rewrite, selected text, and token handling.

- [ ] Expand Electron Latest Draft into a full Review panel.
- [ ] Add editable cleaned output.
- [ ] Add rewrite actions:
  - [ ] Make shorter.
  - [ ] Make clearer.
  - [ ] Change tone.
  - [ ] Custom instruction.
- [ ] Add selected-text-aware TTS for draft text.
- [ ] Add token count and long-text warning.
- [ ] Add review state WebSocket updates.
- [ ] Add keyboard shortcuts for accept/decline/copy/send.

Done when:

- [ ] Electron review flow matches or exceeds the old preview overlay behavior.

## Phase 7: TTS And Read-Aloud

Original app supports review TTS, sample playback, stop playback, voice hints, Kokoro/fallback behavior, and selected-text capture.

- [ ] Replace mock `/tts/speak` behavior with real backend playback or generated audio response.
- [ ] Expose TTS runtime status.
- [ ] Add TTS warmup/unload endpoint.
- [ ] Add TTS voice list endpoint parity.
- [ ] Add TTS sample playback controls in Electron settings.
- [ ] Add stop TTS endpoint.
- [ ] Add read selected draft text or full draft text.
- [ ] Add selected-text capture read-aloud from primary/review hotkey.
- [ ] Linux-check TTS dependencies and fallback options.

Done when:

- [ ] Review TTS and selected-text read-aloud work from Electron.
- [ ] Missing TTS backend shows a clear user-facing fallback/error.

## Phase 8: Notifications, Status UI, And Overlays

Original app has status overlay, notification overlay, preview overlay, splash, and guided tour.

- [ ] Decide replacement strategy:
  - [ ] In-dashboard status only.
  - [ ] Electron always-on-top mini status window.
  - [ ] Electron notification/toast window.
  - [ ] Native OS notifications.
- [ ] Add recording/listening/processing/idle visual state.
- [ ] Add toast notifications for important events.
- [ ] Add draggable position preferences if mini windows are retained.
- [ ] Add startup splash or loading screen only if startup becomes slow.
- [ ] Port guided tour/onboarding into Electron.

Done when:

- [ ] User gets clear non-dashboard feedback during normal use.
- [ ] Overlay behavior is safe and Linux/Wayland limitations are clearly handled.

## Phase 9: Audio And Device Controls

- [ ] Expose microphone/input device listing.
- [ ] Add selected input device setting.
- [ ] Add recording test endpoint and UI.
- [ ] Add live audio level meter during recording.
- [ ] Add audio gate diagnostics.
- [ ] Add audio ducking status and Linux capability messaging.
- [ ] Preserve Windows ducking behavior.

Done when:

- [ ] User can select/test microphone and understand whether audio is being captured.

## Phase 10: Project/Graph/Intent Features

Backend already exposes some graph, plan, profile, and intent endpoints.

- [ ] Add graph editor or graph load/save UI if still part of product direction.
- [ ] Add project/plan generator UI.
- [ ] Add intent state panel and controls.
- [ ] Decide whether these are core BetterFingers features or advanced/developer features.

Done when:

- [ ] Every existing backend endpoint has either a UI, a documented API role, or a decision to remove/defer.

## Phase 11: Packaging And Distribution

- [ ] Package Python backend sidecar for Linux.
- [ ] Package Python backend sidecar for Windows.
- [ ] Include backend executable under Electron resources.
- [ ] Decide whether repo-local llama-server is dev-only or packaged.
- [ ] Add Linux AppImage smoke test.
- [ ] Add Windows NSIS smoke test.
- [ ] Confirm Electron shutdown kills backend process.
- [ ] Confirm packaged app can find assets, tray icon, backend, models, and config dirs.
- [ ] Preserve legacy PyInstaller package until cutover.

Done when:

- [ ] `npm run dist:linux` produces a usable Linux build.
- [ ] `npm run dist:win` produces a usable Windows build.
- [ ] Legacy build still works unchanged.

## Phase 12: Automated Test Coverage

- [ ] Backend tests for all new endpoints.
- [ ] Unit tests for platform capability decisions.
- [ ] Unit tests for draft state transitions.
- [ ] Unit tests for profile migration/defaults.
- [ ] Unit tests for model path/runtime resolution.
- [ ] Electron renderer tests for dashboard/review/settings state.
- [ ] IPC tests for clipboard bridge and app actions.
- [ ] End-to-end dev smoke script:
  - [ ] Start Electron.
  - [ ] Wait for backend.
  - [ ] Warm up STT.
  - [ ] Warm up LLM.
  - [ ] Start hotkeys.
  - [ ] Create test draft.
  - [ ] Accept/copy/send.
  - [ ] Quit and verify backend exits.

Done when:

- [ ] Core functionality is covered by automated tests plus a repeatable manual QA script.

## Phase 13: Cutover Readiness

- [ ] Run feature parity checklist against original Python app.
- [ ] Run Linux QA.
- [ ] Run Windows QA.
- [ ] Confirm performance is acceptable for cold start, warm start, STT, LLM cleanup, TTS, and send.
- [ ] Confirm all P0/P1 issues are closed.
- [ ] Write cutover plan for replacing legacy desktop shell.
- [ ] Archive rollback plan.

Done when:

- [ ] Electron is the recommended app shell.
- [ ] Legacy Python UI can be deprecated only after explicit approval.

## Suggested Build Order

1. Finish `Phase 2` recording/draft reliability.
2. Implement `Phase 3` copy/send paths with Linux-safe fallbacks.
3. Build `Phase 4` settings/profile UI.
4. Build `Phase 5` model management, especially Linux llama-server status.
5. Expand `Phase 6` review/rewrite UX.
6. Restore `Phase 7` TTS/read-aloud.
7. Add `Phase 8` notification/status windows.
8. Complete packaging and QA.

## Immediate Next Tasks

- [ ] Add no-audio gate to `process_recording_result`.
- [ ] Add draft error state and retry.
- [ ] Add `/drafts/{id}/send` with copy-only Linux fallback.
- [ ] Add profile list/get/save/switch endpoints.
- [ ] Add Electron Settings page shell.
- [ ] Add Linux llama-server status card and setup guidance in the dashboard.
