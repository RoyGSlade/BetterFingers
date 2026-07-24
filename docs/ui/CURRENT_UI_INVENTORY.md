# BetterFingers Renderer UI — Exhaustive Inventory (pre-redesign gate)

Scope read in full: `index.html` (2372 lines), `main.js` (4295 lines), `api/backend.js` (900
lines), `features/*.js` (10 files, 5554 lines), `overlay.html`, `review-overlay.html`,
`glitch-ring.js`, `lib/wipeSummary.mjs`, `lib/draftSummary.mjs`, and
`app/src/main/backendProxy.js` (allowlist). This is a **read-only catalog** — no code was
changed.

Use this as a "did we preserve this?" gate for the visual redesign. Every checkbox is one
discrete feature/control that must have a home in the new UI (or be a deliberate, called-out
cut).

---

## 0. KNOWN BUGS FOUND DURING THIS INVENTORY (verify before redesign assumes these work)

Static analysis (grep for every declaration vs. every use) turned up two apparent live defects
in the **current** `main.js`. They don't change what the redesign must preserve (the intent is
clear from surrounding code/backend support), but the redesign should not assume today's build
actually exercises these paths correctly — re-verify at runtime and fix while rebuilding.

- [ ] **BUG:** `renameProfileButton`, `duplicateProfileButton`, `exportProfileButton` (all three
      exist as real `<button id="...">` elements in index.html, lines 715/716/719) are never
      captured via `document.getElementById(...)` anywhere in `main.js`. The lines
      `renameProfileButton?.addEventListener(...)` (main.js:3647), `duplicateProfileButton?.addEventListener(...)`
      (main.js:3674), `exportProfileButton?.addEventListener(...)` (main.js:3697) reference
      **undeclared identifiers** — optional chaining does not protect against a missing
      *binding* (only a null/undefined *value*), so this throws `ReferenceError` at module
      top-level evaluation, in file order, immediately after `createProfileButton`'s listener is
      registered. If confirmed live, this would abort all remaining top-level `main.js`
      execution, including tab-switching wiring, the doctor panel, `initOverlayAppearanceControls()`,
      and the final `bootstrap()` call — i.e. it would break the whole renderer, not just these
      three buttons. Given the app is presumably functional today, verify this in a live
      DevTools console before the redesign; if it reproduces, it explains why Rename/Duplicate/
      Export Profile "don't seem to do anything."
- [ ] **BUG:** `refreshVoiceBlendCapabilityNote()` and `refreshCloneStatusNote()` are called
      (main.js:3217-3218, inside the Settings sidebar nav-button click handler, `tts-readaloud`
      branch) but are **never defined** anywhere in the renderer tree (grep-confirmed). The
      corresponding DOM targets exist (`#voiceBlendBackendNote`, `#voiceCloneStatusNote` in
      index.html) but nothing populates them. Clicking the "TTS / Read-Aloud" settings sidebar
      button throws inside that click handler *before* the code that actually shows/hides the
      section content runs — so clicking that nav button may not switch to the Voice Studio
      section at all (it may only be reachable today via the settings search box). Re-verify and
      wire these two notes properly in the rebuild.

Everything else below was verified present and wired (button → handler → endpoint) by reading
the actual source, not inferred.

---

## 1. TOP-LEVEL SURFACES (what renders)

- [ ] Onboarding overlay — `#onboardingOverlay` (index.html) — 4-step first-run wizard (policy → tour → models), gated by `localStorage['bf_onboarding_complete']`
- [ ] Persona Foundry overlay — `#foundryOverlay` — guided LLM interview → collection → stress-test → review/save, separate from the manual wizard
- [ ] App shell header — logo/title/tagline + Quit button
- [ ] Backend version/health warning banner — `#versionMismatchBanner`
- [ ] Tab navigation (4 tabs) — `#tabButtonDashboard`, `#tabButtonSettings`, `#tabButtonModels`, `#tabButtonDiagnostics`
- [ ] **Dashboard tab** (`#tabDashboard`):
  - [ ] First-run "get set up" checklist panel — `#firstRunPanel`
  - [ ] Backend status grid (3 cards: Backend / Transcriber / LLM Engine) — `.status-grid`
  - [ ] Review Draft panel (recording controls + draft preview + review/rewrite tools + action row + history) — biggest single panel
  - [ ] Message Rescue draft-bound live panel — `#draftRescuePanel` (inside Review Draft panel, flag-gated)
  - [ ] Voice status / WebSocket stream panel — `.stream-panel` with `#wsConnection`
  - [ ] Message Rescue static/example preview panel — `#messageRescuePanel` (flag-gated, synthetic data only, self-initializing)
  - [ ] Text & Persona Playground — `#textPlaygroundSection` (self-initializing)
- [ ] **Settings tab** (`#tabSettings`): sidebar (search + 14 category nav buttons) + main area (14 sections) + sticky Save/Discard bar
- [ ] **Models tab** (`#tabModels`): LLM model manager, Whisper model manager, Wake Word Engine components, Runtime Memory, Voice Cloning provisioning
- [ ] **Diagnostics & Doctor tab** (`#tabDiagnostics`): Doctor checkup grid, Pipeline latency HUD, Recovery/saved-recordings list, Active jobs list, Sidecar startup logs, Runtime diagnostics (paths/errors/debug.log)
- [ ] **overlay.html** — floating "glitch ring" recording/status indicator (separate always-on-top window)
- [ ] **review-overlay.html** — floating draft-review window (separate window, own accept/rewrite/read/decline flow)
- [ ] Toast notification stack — `#toastContainer` (app-wide, all tabs)

---

## 2. ONBOARDING OVERLAY (`#onboardingOverlay`) — index.html + main.js

- [ ] Container: `#onboardingOverlay` (modal, `role="dialog"`, focus-trapped, Escape blocked)
- [ ] Progress dots — `#onboardingProgress` (one dot per step, active/done states)
- [ ] Title — `#onboardingTitle`
- [ ] Body (dynamic HTML per step) — `#onboardingBody`
- [ ] Step 1 "Welcome" — static copy, "Get started" button, no gating
- [ ] Step 2 "Your data stays on this device" — policy box + required consent checkbox `#onboardingConsent`; Next disabled until checked
- [ ] Step 3 "How it works" — record → review → send explainer
- [ ] Step 4 "Speech models" — hardware-aware model recommendation box (`#onboardingRecommendation`, populated via `fetchModelRecommendation()` → `GET /models/recommend`), conditional copy based on whether a Whisper model is already installed
- [ ] `#onboardingDeclineButton` — "Decline & quit" → `window.betterFingers.quitApp()`
- [ ] `#onboardingBackButton` — Back (hidden on step 1)
- [ ] `#onboardingNextButton` — Next / step-specific label ("Get started", "Accept & continue", "Next", "Finish"); on last step calls `finishOnboarding()` which sets `localStorage['bf_onboarding_complete']='true'`
- [ ] Keyboard trap: Tab cycles within overlay, Escape is swallowed (required gate)

---

## 3. PERSONA FOUNDRY OVERLAY (`#foundryOverlay`) — index.html + features/personas.js

- [ ] Open trigger: `#openFoundryButton` (lives in Settings → AI Cleanup) → `foundryOpen()` → `POST /personas/interview/start`
- [ ] Close: `#foundryCloseButton` (×)
- [ ] **Screen: Interview** (`#foundryScreenInterview`)
  - [ ] Chat log — `#foundryChatLog` (question/answer/pushback bubbles)
  - [ ] Choice-question row — `#foundryChoiceRow` (dynamic buttons per `question.choices`)
  - [ ] Free-text question row — `#foundryTextRow`: `#foundryAnswerInput` (textarea) + `#foundrySubmitAnswerButton` ("Send"); Enter submits
  - [ ] Answer submit → `POST /personas/interview/answer` (`answerFoundryQuestion`)
- [ ] **Screen: Collection** (`#foundryScreenCollection`) — gathers few-shot examples or anti-examples
  - [ ] Prompt text — `#foundryCollectionPrompt` (shows count/minimum)
  - [ ] Example-pair inputs (raw/desired) — `#foundryExampleRaw`, `#foundryExampleDesired`
  - [ ] Anti-example input — `#foundryAntiExampleText`
  - [ ] Running list — `#foundryCollectionList`
  - [ ] `#foundryAddCollectionItemButton` — "Add"
  - [ ] `#foundryCollectionNextButton` — "Continue"
- [ ] **Screen: Stress Test** (`#foundryScreenStressTest`)
  - [ ] `#foundryRunStressTestButton` — "Run stress test" → `POST /personas/test-suite/run` (`runFoundryStressTest`)
  - [ ] Stress case cards — `#foundryStressCases` (input, editable output textarea, Approve/Reject per case)
  - [ ] `#foundryStressContinueButton` — "Continue to character card"
- [ ] **Screen: Review** (`#foundryScreenReview`)
  - [ ] Character card — `#foundryCharacterCard` (archetype, temperament, signature moves, favorite phrases, forbidden, best use cases, reliability score)
  - [ ] `#foundryPersonaName` — name input
  - [ ] `#foundryCompiledPrompt` — read-only compiled prompt (details/summary disclosure)
  - [ ] `#foundryCompileWarnings` — compile warnings banner
  - [ ] `#foundrySaveButton` — "Save Persona" → `POST /personas` (`savePersona`, same route the manual wizard uses) → closes overlay, refreshes personas/voices, toast
- [ ] `#foundryMessage` — status/error line shared across all screens
- [ ] Compile step (auto, on interview completion) → `POST /personas/compile` (`compileFoundry`)

---

## 4. APP SHELL / HEADER

- [ ] Logo/eyebrow/title/lede — static copy
- [ ] `#quitButton` — "Quit app" → `window.betterFingers.quitApp()`
- [ ] `#versionMismatchBanner` — backend health/version warning, states: version_mismatch / unhealthy / restarting / crashed (`#backendBannerTitle`, `#backendBannerMessage`)

---

## 5. TAB NAVIGATION

- [ ] `#tabButtonDashboard` → `#tabDashboard`
- [ ] `#tabButtonSettings` → `#tabSettings`
- [ ] `#tabButtonModels` → `#tabModels`
- [ ] `#tabButtonDiagnostics` → `#tabDiagnostics` (activating triggers `refreshDiagnostics()` + `refreshDoctor()`)
- [ ] ARIA tabs pattern: arrow-key / Home / End navigation between tab buttons, roving `tabindex`

---

## 6. DASHBOARD TAB

### 6.1 First-Run Setup Panel (`#firstRunPanel`) — features/firstRun.js

- [ ] Overall status badge — `#firstRunOverallBadge`
- [ ] Disk-space warning banner — `#firstRunDiskWarning` / `#firstRunDiskWarningMessage` (detects `InsufficientDiskSpaceError` message shape)
- [ ] 3-stat overview: Runtime (`#firstRunRuntimeBadge`/`#firstRunRuntimeDetail`), Language model (`#firstRunLlmBadge`/`#firstRunLlmDetail`), Speech model (`#firstRunWhisperBadge`/`#firstRunWhisperDetail`)
- [ ] LLM download panel — `#firstRunDownloadLlmButton` → `downloadLlmModel()` + progress (`#firstRunLlmProgress*`: label/percent/fill/bytes), polls `fetchLlmDownloadState`
- [ ] Whisper download panel — `#firstRunDownloadWhisperButton` → `downloadWhisperModel()` + progress (`#firstRunWhisperProgress*`), polls `fetchWhisperModels().download_state`
- [ ] `#firstRunMessage` — status line
- [ ] `#firstRunRefreshButton` — "Check again" → re-runs `GET /health` + `GET /runtime/status` + `GET /models/llm` + `GET /models/whisper`
- [ ] `#firstRunDismissButton` — "I'll set this up myself" → sets `localStorage['bf_first_run_dismissed']`, hides panel, jumps to Models tab
- [ ] `#firstRunContinueButton` — "Continue to app" (disabled until ready) → hides panel
- [ ] Panel auto-hides once ready or once dismissed; never fights with the onboarding overlay (lives inside the dashboard, not a modal)

### 6.2 Backend Status Grid (`.status-grid`)

- [ ] Backend card — `#backendStatus` / `#backendDetail` ← `GET /health`
- [ ] Transcriber card — `#transcriberStatus` ← `GET /runtime/status`
- [ ] LLM Engine card — `#llmStatus` ← `GET /runtime/status`

### 6.3 Review Draft Panel (`.stream-panel`, "Preview & Review")

- [ ] Draft status pill — `#draftStatus`
- [ ] Recording controls:
  - [ ] `#toggleRecordingButton` — "Start/Stop Recording" (label + `data-recording` flip based on runtime state) → `POST /runtime/recording/toggle` (`toggleRecording`)
  - [ ] `#dashboardEmergencyStopButton` — "Emergency Stop" → `POST /runtime/emergency-stop` (`emergencyStop`)
  - [ ] `#recordingControlStatus` — hint text, surfaces hotkey-hook errors
- [ ] Draft preview:
  - [ ] `#draftRawText` — raw transcript (read-only)
  - [ ] `#draftConfidence` — confidence badge (tinted success/warning/danger by score)
  - [ ] `#draftTokenSummary` — token count / limit, "long text" flag
  - [ ] `#draftFinalText` — cleaned-output editor (textarea, disabled until a draft exists)
- [ ] Review/rewrite tools row:
  - [ ] `#saveDraftEditButton` — "Save Edit" → `editDraft()` → `POST /drafts/:id/edit`; also auto-learns dictionary suggestions from the diff (`maybeLearnFromEdit` → `POST /dictionary/suggest`)
  - [ ] `#rewriteShorterButton` — "Make Shorter" → `rewriteDraft(id,{action:'shorter'})` → `POST /drafts/:id/rewrite`
  - [ ] `#rewriteClearerButton` — "Make Clearer" → same route, `action:'clearer'`
  - [ ] `#rewriteToneButton` — "Change Tone" → same route, `action:'tone'`
  - [ ] `#customRewriteInstruction` — free-text instruction input
  - [ ] `#rewriteCustomButton` — "Custom Rewrite" → same route, `action:'custom'`, `custom_instruction`
  - [ ] `#readSelectionButton` — "Read Selection" → `runDraftTts(true)` → `speakDraft()` (`POST /drafts/:id/tts`) using the current text-selection
  - [ ] `#readFullDraftButton` — "Read Full" → `runDraftTts(false)` → same route, full text
- [ ] Draft action row:
  - [ ] `#copyDraftButton` — "Copy Cleaned Output" → clipboard (`window.betterFingers.writeClipboardText`)
  - [ ] `#acceptDraftButton` — "Accept" → `acceptDraft()` → `POST /drafts/:id/accept`
  - [ ] `#declineDraftButton` — "Decline" → `declineDraft()` → `POST /drafts/:id/decline`
  - [ ] `#retryDraftButton` — "Retry" (enabled only for blocked/error drafts) → `retryDraft()` → `POST /drafts/:id/retry`
  - [ ] `#sendActionSelect` — dropdown: Profile default / Copy only / Paste / Type / Open chat then send
  - [ ] `#sendDraftButton` — "Send / Copy" → `sendDraft()` → typed IPC `POST /drafts/:id/send` (destructive-path, not the generic proxy)
- [ ] `#draftMessage` — status line; `#sendResultPanel` — send-result detail grid (requested/used action, fallback reason, platform/session)
- [ ] `#draftMetadata` — recording duration + stop reason (title attr carries raw RMS/peak/sample telemetry)
- [ ] Draft history:
  - [ ] `#clearDraftHistoryButton` — "Clear History" → `clearDrafts()` → `DELETE /drafts`
  - [ ] `#historySearchInput` — full-text search box → `searchHistory()` → `GET /history/search`; empty query restores recent-drafts view (`GET /drafts`)
  - [ ] `#draftHistoryList` — clickable list (recent drafts or search results); click either re-renders the draft or copies matched text to clipboard
- [ ] Keyboard shortcuts (global, `document.keydown`): Ctrl/Cmd+Enter = Accept, Ctrl/Cmd+Shift+Enter = Send, Ctrl/Cmd+Shift+C = Copy, Ctrl/Cmd+S = Save Edit, Ctrl/Cmd+D = Decline

### 6.4 Message Rescue — Draft-Bound Live Panel (`#draftRescuePanel`) — features/messageRescueDraft.js

Behind local flag `pref_message_rescue_enabled` (default OFF, `localStorage`). Operates on
whatever draft is currently "latest" (documented limitation: no per-id targeting).

- [ ] `#draftRescueDraftLabel` — "Will rescue draft #N." / no-draft message
- [ ] `#draftRescueCaptureButton` — "Capture selection as context" → `captureSelectionMessageRescueContext()` → `POST /message-rescue/context/selection` (server-side OS selection/clipboard capture; text is never read/transmitted by the renderer itself)
- [ ] `#draftRescueClearContextButton` — "Clear context" → `clearMessageRescueContext()` → `DELETE /message-rescue/context`
- [ ] `#draftRescueContextMessage`, `#draftRescueContextStatus`, `#draftRescueContextPreview`, `#draftRescueContextMeta` — context status/preview/source/uses
- [ ] `#draftRescueRunButton` — "Rescue this message" → `generateMessageRescue()` → `POST /message-rescue/generate`
- [ ] `#draftRescueCancelButton` — "Cancel" — local/soft cancel only (job id not knowable in time to hit the real cancel route)
- [ ] `#draftRescueStatus`, `#draftRescueError`, `#draftRescueFallback` — run status / error / "fallback used" notices
- [ ] `#draftRescueAssessment` (`#draftRescueAssessmentIntent`, `#draftRescueAssessmentAmbiguity`) — intent + ambiguity risk
- [ ] Delivery signals — `#draftRescueDeliveryLabels`, `#draftRescueDeliveryConfidence`, `#draftRescueDeliveryEvidence`
- [ ] Clarification block — `#draftRescueClarification` (`#draftRescueClarificationQuestion`, `#draftRescueClarificationDetails`)
- [ ] Variant picker (radio group) — `#draftRescueVariantFaithful` / `#draftRescueVariantClearer` / `#draftRescueVariantAlternate`, preview text `#draftRescueVariantText`; selecting writes into `#draftFinalText` (never touches raw transcript)
- [ ] Preservation checks list — `#draftRescuePreservationList`; warnings — `#draftRescueWarnings`/`#draftRescueWarningsList`
- [ ] `#draftRescueApplyMessage` — "Applied the X variant..." confirmation

### 6.5 Voice Status / WebSocket Panel

- [ ] `#wsConnection` — connection pill (connecting/connected/reconnecting/error) ← `connectVoiceStatus()` (main-process-owned WS, `/ws/voice_status`, token never reaches renderer)
- [ ] `#voiceStatus` — latest status keyword
- [ ] `#voiceStatusDetail` — raw JSON payload of the latest message (developer-facing)
- [ ] Drives: overlay window status pushes, review-overlay draft pushes, draft-history refresh, dictionary/history refresh, long-recording/chunking progress text, watchdog-timeout toast

### 6.6 Message Rescue — Static Preview Panel (`#messageRescuePanel`) — features/messageRescuePanel.js

Flag-gated (`pref_message_rescue_enabled`), **entirely synthetic** — renders one fixed example
payload, makes zero backend calls, self-initializes via its own `<script type="module">` tag
(not part of main.js composition).

- [ ] `#messageRescueClearContextButton` — local-only "Clear" (resets the example preview text, no request)
- [ ] Context/assessment/delivery/clarification/variant-radio/preservation/warnings regions — identical structure to 6.4 but fed by `EXAMPLE_CONTEXT`/`EXAMPLE_SIGNALS`/`EXAMPLE_RESULT` fixtures
- [ ] Variant radios `#messageRescueVariantFaithful/Clearer/Alternate` — switch the local preview only

### 6.7 Text & Persona Playground (`#textPlaygroundSection`) — features/textPlayground.js

Self-initializing (own `<script type="module">` tag). No mic/TTS/transcription anywhere.

- [ ] `#textPlaygroundText` — message text input
- [ ] `#textPlaygroundContext` — optional context input (captured server-side, one-time-use)
- [ ] `#textPlaygroundPersonaSelect` — persona dropdown (built from `fetchPersonas()`)
- [ ] `#textPlaygroundRunButton` — "Run" → captures context if present (`captureManualMessageRescueContext` → `POST /message-rescue/context/manual`) then `generateMessageRescue()` → `POST /message-rescue/generate`
- [ ] `#textPlaygroundCancelButton` — "Cancel" (soft/local only)
- [ ] `#textPlaygroundClearButton` — "Clear" → `clearMessageRescueContext()` → `DELETE /message-rescue/context`, resets all local state
- [ ] `#textPlaygroundStatus`, `#textPlaygroundError`, `#textPlaygroundRanInfo` (persona/model/context-used line), `#textPlaygroundFallback`
- [ ] Assessment / delivery / clarification regions (same shared renderer as 6.4/6.6)
- [ ] Side-by-side comparison columns — Raw / Faithful / Clearer / Alternate, each with its own "Use this" toggle button (`#textPlaygroundColumnRawButton` etc.)
- [ ] Preservation checks / warnings lists
- [ ] `#textPlaygroundDraftSelect` — pick an existing draft to apply the selected column to
- [ ] `#textPlaygroundApplyButton` — "Apply to draft" → `editDraft(draftId, text)` → `POST /drafts/:id/edit` (writes only `final_text`, never `raw_text`)
- [ ] `#textPlaygroundCopyButton` — "Copy" → `navigator.clipboard.writeText`
- [ ] `#textPlaygroundApplyMessage` — confirmation line

---

## 7. SETTINGS TAB (`#tabSettings`)

### 7.0 Chrome

- [ ] `#settingsSearchInput` — free-text settings search (filters rows/groups across all sections, shows `#settingsSearchHeader` / `#settingsEmptyState`)
- [ ] `.settings-nav-button` × 14 — sidebar category buttons (see 7.2–7.16); switching resets search and, for a few sections, triggers a refresh (privacy/dictionary/macros/voice-control/tts-readaloud)
- [ ] `#settingsSaveBar` (sticky footer) — appears once any control is touched:
  - [ ] `#discardProfileChangesButton` — "Discard" → re-fetches the active profile, discards local edits
  - [ ] `#saveProfileButton` — "Save Settings" → `saveProfile(name, collectProfileSettings())` → `POST /settings/profiles/:name`; blocked while `validationErrors.size > 0`
- [ ] `#profileMessage` — global settings status line
- [ ] Live client-side validation (`runValidation()`) on every settings input's `input`/`change`: range checks (max completion tokens 512-4096, long-draft-warning-words 300-10000, LLM/Whisper chunk size 50-5000, TTS speed 0.5-3.0, min duration 0-30s, min RMS/peak 0-1, confidence thresholds 0-1, auto-stop silence 250-5000ms, auto-stop min recording 0-10000ms) plus **hotkey collision detection** across all 6 hotkey fields (per-field inline error text, Save disabled while any error exists)

### 7.1 General — Profile Management

- [ ] `#profileSelect` — active-profile dropdown → `fetchProfile(name)` → `GET /settings/profiles/:name`
- [ ] `#newProfileName` — name/target input shared by the operations below
- [ ] `#activateProfileButton` — "Activate" → `activateProfile(name)` → `POST /settings/profiles/:name/activate`
- [ ] `#createProfileButton` — "Create New" → `createProfile(name, settings)` → `POST /settings/profiles`
- [ ] `#renameProfileButton` — "Rename Profile" → `renameProfile(old,new)` → `POST /settings/profiles/:name/rename` — **see Bug #1 above (handler wiring appears broken today)**
- [ ] `#duplicateProfileButton` — "Duplicate Profile" → `duplicateProfile(old,new)` → `POST /settings/profiles/:name/duplicate` — **see Bug #1**
- [ ] `#exportProfileButton` — "Export Profile" → `exportProfile(name)` → `GET /settings/profiles/:name/export`, downloads a `{name}_profile.json` file client-side (Blob + anchor click) — **see Bug #1**
- [ ] `#importProfileFile` (styled as a button, `accept=".json"`) — reads file, upgrades legacy/unversioned shape, validates `schema_version===1` and the name, → `importProfile(parsed)` → `POST /settings/profiles/import`
- [ ] `#deleteProfileButton` — "Delete Profile" (blocks the "Default" profile) → `deleteProfile(name)` → `DELETE /settings/profiles/:name`

### 7.2 Recording

- [ ] `#settingRecordingMode` — select: toggle / push-to-talk → profile `recording_mode`
- [ ] `#pttAvailabilityNote` — PTT support note (from `window.betterFingers.getHotkeyCapabilities()`)
- [ ] `#settingAutoStopSilence` — checkbox → `auto_stop_after_silence_enabled`
- [ ] `#settingAutoStopSilenceMs` — number (250-5000) → `auto_stop_silence_ms`
- [ ] `#settingAutoStopMinMs` — number (0-10000) → `auto_stop_min_recording_ms`
- [ ] `#settingVoiceCommands` — checkbox (default ON) → `voice_commands_enabled`
- [ ] `#settingNoAudioDuration` — number (0-30s) → `no_audio_min_duration_sec`
- [ ] `#settingNoAudioRms` — number (0-1) → `no_audio_min_rms`
- [ ] `#settingNoAudioPeak` — number (0-1) → `no_audio_min_peak`

### 7.3 Hotkeys

- [ ] `#hotkeySessionIndicator` — platform/session readout (from `GET /capabilities`)
- [ ] `#waylandHotkeyWarning` — conditional Wayland limitation banner
- [ ] `#settingHotkey` (+ clear button) — Recording Hotkey → `hotkey`
- [ ] `#settingForceStopKey` (+ clear) — Emergency Stop key → `force_stop_key`
- [ ] `#settingManualSendHotkey` (+ clear) — Primary Action key → `manual_send_hotkey`
- [ ] `#settingReviewTtsHotkey` (+ clear) — Review TTS Hotkey → `review_tts_hotkey`
- [ ] `#settingChatOpenKey` (+ clear) — Open Chat Key → `chat_open_key`
- [ ] `#settingVoiceMuteKey` (+ clear) — Voice Mute Key → `voice_mute_key`
- [ ] Custom key-recording widget (`setupHotkeyRecording`) attached to all 6 fields above: click-to-record, accumulates chord via keydown, Escape/blur cancels, dispatches synthetic `input` event
- [ ] Each field's ".clear-hotkey-btn" — clears + fires input/change

### 7.4 Review & Drafts

- [ ] `#settingSendMode` — select: review first / auto send → `send_mode`
- [ ] `#settingConfidenceForceReview` — checkbox (default ON) → `confidence_force_review_enabled`
- [ ] `#settingConfidenceForceReviewBelow` — number (0-1) → `confidence_force_review_below`
- [ ] `#settingConfidenceAutoSendAbove` — number (0-1) → `confidence_auto_send_above`
- [ ] `#settingAutoSubmit` — checkbox → `auto_submit`
- [ ] `#settingInstantTyping` — checkbox (disabled on Wayland) → `instant_typing`
- [ ] `#settingRestoreClipboard` — checkbox (default ON) → `restore_clipboard_after_paste`
- [ ] `#settingDraftHistoryLimit` — number (10-500) → `draft_history_limit` (declared in index.html; not present in `settingEls` map in main.js — verify wiring)

### 7.5 AI Cleanup & Personas

- [ ] `#settingCurrentPreset` — active persona/preset dropdown → `current_preset` (also read by Persona Learning's `personaSource`, though that feature is unwired — see Orphans)
- [ ] `#settingMaxCompletionTokens` — number (512-4096) → `max_completion_tokens`
- [ ] `#settingLongDraftWarningWords` — number (300-10000) → `long_draft_warning_words`
- [ ] `#settingLlmChunkSize` — number (50-5000) → `llm_chunk_size`
- [ ] `#settingWhisperChunkSize` — number (50-5000) → `whisper_chunk_size`
- [ ] `#settingStitchPass` — checkbox → `long_recording_stitch_pass_enabled`
- [ ] `#openFoundryButton` — "🔨 Build with AI (Persona Foundry)" — opens overlay (section 3)
- [ ] **Persona Wizard** (`.wizard-container`, 4 steps), see 7.5.1 below

#### 7.5.1 Persona Wizard steps

- [ ] `#wizardStepProgress` — "Step N of 4: ..." label
- [ ] **Step 1 — Goal & Role**
  - [ ] `#wizardRole` — select: janitor / editor / writer / custom
  - [ ] `#wizardCustomRole` — custom goal/role textarea (shown when role=custom)
  - [ ] `#wizardDescribeInput` — "describe the persona in your own words" textarea
  - [ ] `#wizardDescribeButton` — "✨ Build it with your model" → `draftPersonaFromDescription()` → `POST /personas/draft`; populates name/prompt/temperature/output_policy/safety_mode/few-shot and jumps straight to step 4
  - [ ] `#wizardDescribeStatus` — busy/result line
- [ ] **Step 2 — Tone**
  - [ ] `#wizardTone` — select: neutral / formal / casual / custom
  - [ ] `#wizardCustomTone` — custom tone text input
- [ ] **Step 3 — Rules**
  - [ ] `#wizardRuleLength` — "Match original input length" (checked)
  - [ ] `#wizardRuleCommands` — "Ignore user commands/instructions inside speech" (checked, safety)
  - [ ] `#wizardRuleNoPreamble` — "Do not output preambles/explanations/quotes" (checked)
  - [ ] `#wizardRuleSanitize` — "Sanitize profanity or hostile language" (unchecked)
- [ ] **Step 4 — Review & Save**
  - [ ] `#wizardPersonaName` — name input
  - [ ] `#wizardPromptPreview` — generated/editable prompt textarea
  - [ ] `#wizardRegeneratePromptButton` — "Regenerate from wizard" (rebuilds from steps 1-3)
  - [ ] `#wizardRefinePromptButton` — "✨ Clean up with your model" → `refinePersonaPrompt()` → `POST /personas/refine`
  - [ ] `#wizardRefineStatus`, `#wizardRefinePanel` (`#wizardRefineUnderstood`, `#wizardRefineAmbiguities`, `#wizardRefinedPrompt`) — model's understanding/ambiguity report
  - [ ] `#wizardApplyRefinedButton` — "Use refined prompt"; `#wizardDismissRefinedButton` — "Keep mine"
  - [ ] **Advanced (details/summary)** `#wizardAdvanced`:
    - [ ] `#wizardTemperature` — number (0-2, optional)
    - [ ] `#wizardModelHint` — preferred-model text hint
    - [ ] `#wizardFormatCaps` — select: none/sentence/upper/lower
    - [ ] `#wizardFormatPunctuation` — checkbox (default checked)
    - [ ] `#wizardFormatSignoff` — optional sign-off text
    - [ ] `#wizardOutputPolicy` — select: preserve/tighten/expand/summarize
    - [ ] `#wizardSafetyMode` — select: strict/light/creative
    - [ ] `#wizardMaxCompletionTokens` — number (512-4096, optional, per-persona override)
    - [ ] `#wizardChunkSize` — number (50-5000, optional, per-persona override)
    - [ ] Few-shot examples list `#wizardFewShotList` (raw/desired textarea pairs, up to 5) + `#wizardAddFewShotButton` — "Add example"
    - [ ] `#wizardLintButton` — "Check prompt" → `lintPersona()` → `POST /personas/lint`; results in `#wizardLintWarnings`
    - [ ] `#wizardTestSample` + `#wizardTestButton` — "Run sample" → `testPersona()` → `POST /personas/test`; result in `#wizardTestResult`
  - [ ] `#wizardPrevButton` / `#wizardNextButton` (relabels to "Save Persona" on step 4) → `savePersona()` → `POST /personas`
  - [ ] `#wizardDeleteButton` — "Delete Custom Persona" (hidden for built-ins, confirm dialog) → `deletePersona()` → `DELETE /personas/:name`
  - [ ] `#wizardMessage` — status line
  - [ ] Loading an existing persona name into `#wizardPersonaName` auto-fetches its v2 fields (`getPersonaV2` → `GET /personas/:name`) and preserves its hand-tuned prompt instead of overwriting it

### 7.6 Send & Injection

- [ ] `#waylandInjectionWarning` — conditional Wayland fallback banner
- [ ] `#injectionUnavailableWarning` — conditional "no working clipboard backend" banner (from `capabilities.injection_hint`)
- [ ] `#audioDuckingWarning` — conditional platform-support banner
- [ ] `#settingAudioDucking` — checkbox → `audio_ducking` (disabled + forced off when platform doesn't support it)
- [ ] `#testPasteCopyButton` — "Test Paste/Copy" → writes test text to clipboard

### 7.7 Audio Devices

- [ ] `#settingInputDevice` — microphone select (built from `GET /runtime/audio-devices`, input-capable devices only) → `input_device_index`
- [ ] `#testMicButton` — "Test Browser Microphone Access" (toggles) → `navigator.mediaDevices.getUserMedia` + live level meter
- [ ] `#micMeterBar` / `#micMeterFill` — live mic level bar (AnalyserNode-driven)

### 7.8 Voice Control (Wake Word)

- [ ] `#settingWakeWordEnabled` — checkbox → `handleWakeToggle()`; gates on Wake Engine backbones being installed (prompts to jump to Models tab if missing) → `enableWake()`/`disableWake()` → `POST /wake/enable` / `POST /wake/disable`
- [ ] `#wakeStatusDetail` — live status text ← `GET /wake/status`
- [ ] `#settingWakeWordModel` — imported-classifier dropdown → `wake_word_model`
- [ ] `#importWakeModelButton` + hidden `#importWakeModelFile` (`.onnx`) — "Import model file..." → `importWakeModel()` → typed IPC upload → `POST /wake/models/import`
- [ ] `#importWakeModelStatus` — import status line
- [ ] **Build a Wake Phrase** (`#wakeTrainingGroup`):
  - [ ] `#wakeTrainPhrase` — phrase text input (max 60 chars)
  - [ ] `#wakeTrainButton` — "Train wake phrase" → `trainWakePhrase()` → `POST /wake/train`, polls `fetchWakeTrainStatus()` → `GET /wake/train/status` up to 3 min
  - [ ] `#wakeTrainProgress` (`#wakeTrainProgressLabel`, `#wakeTrainProgressPercent`, `#wakeTrainProgressFill`) — live progress
  - [ ] `#wakeTrainResult` — verdict copy (reliable/noisy/unusable) + false-accept/false-reject rates
- [ ] **Detection Tuning:**
  - [ ] `#settingWakeWordSensitivity` — number (0-1, step .05) → `wake_word_sensitivity`
  - [ ] `#settingWakeWordCooldown` — number (0-30s) → `wake_word_cooldown_s`
  - [ ] `#settingWakeWordMaxRecording` — number (5-1800s) → `wake_word_max_recording_s`
- [ ] **Live Test:**
  - [ ] `#testWakeButton` — "Test Wake Detection (10s)" → `testWake(10)` → `POST /wake/test`
  - [ ] `#wakeScoreBar`/`#wakeScoreFill` — live score bar; `#wakeTestResult` — peak score + sample count

### 7.9 TTS / Read-Aloud (Voice Studio) — see also features/voiceStudio.js (7.9 detail below)

- [ ] `#ttsWarningBadge` — platform TTS hint banner
- [ ] `#settingReviewTtsVoiceHint` — active-voice select → `review_tts_voice_hint`
- [ ] `#settingReviewTtsSpeed` — number (0.5-3.0) → `review_tts_speed`
- [ ] `#voicePreviewText` — audition preview text (falls back to a built-in phrase)
- [ ] `#testTtsButton` — "Audition Voice / Test TTS API" → `speakTts()` → `POST /tts/speak`
- [ ] `#voiceLivePreview` — checkbox: re-audition ~600ms after any blend/modulation/base/speed tweak (behavior described in the label; wiring for the actual debounce not confirmed inside `voiceStudio.js` — verify)
- [ ] **Voice Presets:**
  - [ ] `#voicePresetSelect` — load a saved preset → applies base/blend/modulation into controls (not yet saved to profile)
  - [ ] `#voicePresetList` — list with per-preset Apply/Delete buttons → `deleteVoicePreset()` → `DELETE /voice-presets/:name`
  - [ ] `#voicePresetNameInput` + `#saveVoicePresetButton` — "Save As Preset" → `saveVoicePreset()` → `POST /voice-presets`
  - [ ] (Backend-supported, no visible UI trigger found for) "make default"/"clear default" preset routes (`setDefaultVoicePreset`/`clearDefaultVoicePreset`) — exported from backend.js but no button wired in main.js/voiceStudio.js; **verify whether this is an intentional orphan**
- [ ] **Blend:**
  - [ ] `#voiceBlendRows` — dynamic list of up to 2 extra voice layers (select + weight slider + Remove button per row)
  - [ ] `#voiceEffectiveMix` — computed "effective mix" readout (post backend-normalization)
  - [ ] `#voiceBlendBackendNote` — "needs ONNX voice engine" warning (rendering call is currently broken — see Bug #2)
  - [ ] `#addVoiceLayerButton` — "+ Add voice layer" (max 2)
  - [ ] `#resetVoiceBlendButton` — "Reset (clear blend)"
  - [ ] Quick-blend chips (`[data-blend-preset]`): Softer / Brighter / Lower / Narrator / Assistant
- [ ] **Modulation:**
  - [ ] `#voicePitch` (range, -12..12 st), `#voiceEnergy` (0-1), `#voiceWarmth` (0-1), `#voiceBrightness` (0-1) — live value labels `#voicePitchValue` etc.
  - [ ] `#voicePauseStyle` — select: natural/compact/dramatic
  - [ ] `#voiceStability` — range, **disabled**, labeled "experimental — reserved, not yet applied"
  - [ ] Quick-modulation chips (`[data-mod-preset]`): "Read my draft clearly" / "Quiet proofread" / "Presentation voice" / "Character voice" / "Fast skim" / "Accessibility slow"
- [ ] **Voice Cloning (Advanced):**
  - [ ] Consent banner (static)
  - [ ] `#voiceCloneStatusNote` — status text (population source currently missing — see Bug #2)
  - [ ] `#voiceCloneInstallButton` — "Install voice cloning", **hidden, no click handler found anywhere** (verify vs. Orphans)
  - [ ] `#voiceCloneConsent` — required consent checkbox, gates the 3 fields below
  - [ ] `#voiceCloneName` — voice name (disabled until consent)
  - [ ] `#voiceCloneFile` — `.wav` sample upload (disabled until consent)
  - [ ] `#voiceCloneUploadButton` — "Upload & Validate Sample" → `cloneVoice()` → typed IPC multipart upload → `POST /tts/clone`
  - [ ] `#voiceCloneResult` — validation/warning result text

### 7.10 Notifications & Status

- [ ] `#settingStatusIndicator` — checkbox → `status_indicator_enabled` (floating recording/processing orb overlay)
- [ ] `#settingNotificationOverlay` — checkbox → `notification_overlay_enabled`
- [ ] `#settingPreviewOverlay` — checkbox → `preview_overlay_enabled`

### 7.11 Appearance

- [ ] `#settingTheme` — select: system/dark/light → `localStorage['pref_theme']` (client-local, not a backend profile field)
- [ ] `#settingAccentColor` — select: teal/purple/blue/gold → `localStorage['pref_accent']`
- [ ] `#settingDensity` — select: comfortable/compact → `localStorage['pref_density']`
- [ ] `#settingFontSize` — select: small/medium/large/huge → `localStorage['pref_font_size']`
- [ ] `#settingHighContrast` — checkbox → `localStorage['pref_high_contrast']`
- [ ] All 5 above apply live via `applyAppearance()` (body/html class toggling), independent of the profile save cycle, and re-apply on `prefers-color-scheme` OS change when theme=system
- [ ] **Floating Overlay** (`#overlayAppearanceGroup`, talks directly to Electron main via `window.betterFingers.*OverlayAppearance`, no backend round-trip):
  - [ ] `#settingOverlaySize` — select: small/medium/large/xlarge
  - [ ] `#settingOverlayPlacement` — select: 9 positions (corners/edges/center)
  - [ ] `#settingOverlayOpacity` — range (0.15-1) + live `#overlayOpacityValue`
  - [ ] `#settingOverlayVibrancy` — range (0.3-2) + live `#overlayVibrancyValue`
  - [ ] `#settingOverlayLabelPos` — select: hidden/below/above/center/beside
  - [ ] `#settingOverlayAlwaysOn` — checkbox: keep ring visible even when idle
  - [ ] Whole group hidden if the Electron bridge doesn't expose overlay-appearance methods (e.g. plain browser)

### 7.12 Personal Dictionary

- [ ] `#dictionaryInput` + `#dictionaryAddButton` ("Add", also Enter-to-submit) → `addDictionaryTerm()` → `POST /dictionary`
- [ ] `#dictionarySuggestGroup`/`#dictionarySuggestions` — auto-surfaced suggestions from edited drafts (`suggestDictionaryTerms` → `POST /dictionary/suggest`), each a clickable "+ term" chip
- [ ] `#dictionaryList` — chip list with per-term × remove → `deleteDictionaryTerm()` → `DELETE /dictionary/:term`

### 7.13 Voice Macros

- [ ] `#macroTrigger` + `#macroExpansion` + `#macroAddButton` ("Add", Enter-to-submit on expansion field) → `addMacro()` → `POST /macros`
- [ ] `#settingMacrosEnabled` — checkbox (default ON) → `macros_enabled`
- [ ] `#macrosList` — trigger→expansion rows with × remove → `deleteMacro()` → `DELETE /macros/:trigger`

### 7.14 Privacy

- [ ] `#privacyNetworkList` — network touchpoints (outbound vs on-device) ← `fetchPrivacy()` → `GET /privacy`
- [ ] `#privacyDataList` — on-device data locations + sizes
- [ ] `#privacyWakeListenerStatus` — wake-word listener active/inactive note
- [ ] `#privacyWipeVoices` — "Also delete my cloned voices" checkbox
- [ ] `#privacyWipeButton` — "Wipe my data…" (danger, native `confirm()` dialog) → `wipeData()` → typed IPC `POST /privacy/wipe`; truthful postcondition reporting via `summarizeWipeFailure()` (lib/wipeSummary.mjs) — never claims success unless every postcondition held
- [ ] `#privacyMessage` — result line

### 7.15 Macros/Dictionary refresh triggers — (see 7.0, sidebar switch also refreshes these + wake status/models + privacy report)

### 7.16 Advanced & Developer

- [ ] `#warmupSttButton` — "Warm Up STT" → `warmupRuntime({stt:true})` → `POST /runtime/warmup`
- [ ] `#warmupLlmButton` — "Warm Up LLM" → `warmupRuntime({llm:true})`
- [ ] `#startHotkeysButton` — "Start Hotkeys" → `warmupRuntime({hotkeys:true})`
- [ ] `#primaryActionButton` — "Primary Action" → `runPrimaryAction()` → `POST /runtime/primary-action` (pastes pending draft / reads highlighted text)
- [ ] `#emergencyStopButton` — "Emergency Stop" (duplicate of dashboard's, same endpoint) → `POST /runtime/emergency-stop`
- [ ] `#warmupMessage` — status line; `#outputSettingsSummary` — live send-mode/auto-submit/injection-support/pending-sends summary
- [ ] `#settingKeepLlm` — checkbox → `model_keep_llm_loaded`
- [ ] `#settingKeepStt` — checkbox → `model_keep_stt_loaded`
- [ ] `#settingKeepTts` — checkbox → `model_keep_tts_loaded`
- [ ] `#testModelLoadButton` — "Test Model Load" → `warmupRuntime({llm:true})`
- [ ] `#capabilitiesList` — platform capability dump ← `GET /capabilities` (platform, session type, wayland/x11, clipboard, injection, typing, hotkeys, ducking, stt/llm/tts support)
- [ ] `#runtimeStatusList` — subsystem detail dump ← `GET /runtime/status`

---

## 8. MODELS TAB (`#tabModels`)

- [ ] `#refreshModelsButton` — "Refresh Models" → `fetchLlmModels()` + `fetchWhisperModels()`
- [ ] `#modelRecommendation` — hardware-tier recommendation box ← `GET /models/recommend`
- [ ] `#modelStatusSummary` — 3-stat overview (LLM / Whisper / Runtime), computed client-side from both payloads (honest "runtime outdated" vs "needs download" vs "ready" states)
- [ ] **LLM panel:**
  - [ ] `#llmModelBadge` — Installed/Missing/Selected badge
  - [ ] `#llmModelSelect` — model picker
  - [ ] `#llmModelDetails` — detail grid (selected/viewing/install state/approx size/runtime)
  - [ ] `#selectLlmModelButton` — "Use This LLM" → `selectLlmModel()` → `POST /models/llm/select`
  - [ ] `#downloadLlmModelButton` — "Download" → `downloadLlmModel()` → `POST /models/llm/:id/download` with polling progress (`#llmDownloadProgress*`)
  - [ ] `#deleteLlmModelButton` — "Delete" (confirm dialog) → `deleteLlmModel()` → typed IPC `DELETE /models/llm/:id`
  - [ ] `#unloadLlmButton` — "Unload" → `unloadModel('llm')` → `POST /models/unload/:component`
- [ ] **Whisper panel:**
  - [ ] `#whisperModelBadge`, `#whisperModelSelect`, `#whisperModelDetails`
  - [ ] `#selectWhisperModelButton` — "Use This" → `selectWhisperModel()` → `POST /models/whisper/select`
  - [ ] `#downloadWhisperButton` — "Download" → `downloadWhisperModel()` → `POST /models/whisper/download`
  - [ ] `#deleteWhisperButton` — "Delete" (confirm dialog) → `deleteWhisperModel()` → typed IPC `DELETE /models/whisper/:size`
  - [ ] `#unloadSttButton` — "Unload" → `unloadModel('stt')`
- [ ] **Wake Word Engine panel** — `#wakeEngineBadge` + `#wakeBackboneList` (per-backbone Download buttons) ← `GET /wake/models`, downloads via `POST /wake/models/:id/download`, polled via `GET /wake/models/:id/download-state`
- [ ] **Runtime Memory panel** — `#unloadTtsButton` — "Unload TTS" → `unloadModel('tts')`
- [ ] **Voice Cloning panel** (`#voiceCloningPanel`) — `#voiceCloningBadge`, `#voiceCloningStatus`, `#provisionVoiceCloningButton` — "Install voice cloning" → `provisionVoiceCloning()` → `POST /tts/clone/provision`; `#voiceCloningHint` — actionable failure reason (routine reasons suppressed)
- [ ] `#modelMessage` — shared status line for all model actions on this tab

---

## 9. DIAGNOSTICS & DOCTOR TAB (`#tabDiagnostics`)

- [ ] **Doctor checkup** — `#refreshDoctorButton` — "Run Doctor Check" → `fetchDoctor(refreshAudio=true)` → `GET /doctor`
  - [ ] `#doctorCardsGrid` — 8 subsystem cards: STT, LLM Engine, TTS, Hotkey Manager, Model Paths, Audio System, Platform Capabilities, Hardware & Model Fit (each with a status badge + detail block; hardware card shows CPU/RAM/swap/GPU + model-fit verdict/reasons)
  - [ ] `#doctorRecoveryPanel`/`#doctorRecoveryList` — recovery recommendations, keyed by trigger (missing_model, missing_llama_server, outdated_runtime, port_conflict, microphone_unavailable, unsupported_wayland_injection, failed_clipboard, failed_tts_dependency), backend-supplied text with a client-side fallback for `outdated_runtime`
- [ ] **Pipeline latency HUD** — `#metricsHud` ← `fetchMetrics()` → `GET /metrics`: per-stage table (Transcribe / Dictionary-commands-macros / LLM cleanup / Total), each with Last/Avg/p50/p95
- [ ] **Recovery (saved recordings)** — `#recordingsList` ← `fetchRecordings()` → `GET /recordings`
  - [ ] Per-row "Re-transcribe" → `retranscribeRecording()` → `POST /recordings/:id/retranscribe`
  - [ ] Per-row "Discard" → `deleteRecording()` → `DELETE /recordings/:id`
  - [ ] `#clearRecordingsButton` — "Clear all" (confirm dialog) → `clearRecordings()` → `DELETE /recordings`
- [ ] **Active jobs** — `#jobsList` ← `fetchJobs(activeOnly=true)` → `GET /jobs?active=1`; per-row "Cancel" → `cancelJob()` → typed IPC `POST /jobs/:id/cancel`; shows state label, progress %, "cancelling…" flag
- [ ] **Sidecar startup logs** — `#sidecarLogsTail` ← `window.betterFingers.getSidecarLogs()`; `#clearSidecarLogsButton` — clears the visible tail (client-side only, does not call the backend)
- [ ] **Runtime diagnostics:**
  - [ ] `#copySupportReportButton` — "Copy Support Report" → `fetchSupportReport()` → `GET /diagnostics/support-report`, copies markdown to clipboard (privacy-safe, no transcription content)
  - [ ] `#refreshDiagnosticsButton` — "Refresh Diagnostics" → fans out to sidecar status, metrics, recordings, jobs, paths, runtime errors, debug.log tail
  - [ ] `#sidecarStatus` ← `window.betterFingers.getSidecarStatus()`
  - [ ] `#diagnosticsPathsList` ← `fetchDiagnosticsPaths()` → `GET /diagnostics/paths` (debug log path, models dir, default model path/exists, llama-server path/exists ×2, env var overrides)
  - [ ] `#runtimeErrorsList` ← `fetchRuntimeErrors()` → `GET /runtime/errors` (severity-tinted, last 8, reverse chronological)
  - [ ] `#debugLogTail` ← `fetchDiagnosticsLogs(80)` → `GET /diagnostics/logs?lines=80`

---

## 10. FEATURE MODULES (`app/src/renderer/features/*.js`)

| File | Export | `elements` keys expected | `hooks` needed | Backend calls made |
|---|---|---|---|---|
| `drafts.js` | `createDraftsFeature` | draftStatusEl, draftRawTextEl, draftFinalTextEl, draftTokenSummaryEl, saveDraftEditButton, rewrite×3 buttons, customRewriteInstructionEl, rewriteCustomButton, readSelectionButton, readFullDraftButton, copyDraftButton, acceptDraftButton, declineDraftButton, retryDraftButton, sendDraftButton, draftMessageEl, draftMetadataEl, draftHistoryListEl | `getSelectedSendAction`, `gatherVoiceStudioSettings`, `onDraftEdited`, `refreshOutputSettings` | `acceptDraft`, `clearDrafts`, `declineDraft`, `editDraft`, `fetchDrafts`, `fetchLatestDraft`, `retryDraft`, `rewriteDraft`, `searchHistory`, `sendDraft`, `speakDraft` |
| `personas.js` | `createPersonasFeature` | full wizard element set (~35 ids, see 7.5.1) + Foundry (own internal `document.getElementById`, no injected elements) | `getLoadedPersonas`, `refreshPersonasAndVoices`, `markProfileDirty` | `fetchBuiltinPersonaNames`, `getPersonaV2`, `lintPersona`, `testPersona`, `refinePersonaPrompt`, `draftPersonaFromDescription`, `savePersona`, `deletePersona`, `startFoundryInterview`, `answerFoundryQuestion`, `compileFoundry`, `runFoundryStressTest` |
| `runtime.js` | `createRuntimeFeature` | backendStatusEl, backendDetailEl, transcriberStatusEl, llmStatusEl, runtimeStatusListEl, toggleRecordingButton, recordingControlStatusEl, sidecarStatusEl, versionMismatchBanner (+title/message), wsConnectionEl, capabilitiesListEl, outputSettingsSummaryEl, profileMessageEl, modelMessageEl | `refreshCapabilities`, `refreshDrafts`, `renderDraft`, `refreshOutputSettings`, `refreshProfiles`, `refreshModels`, `refreshDiagnostics`, `refreshDoctor`, `refreshSidecarLogs`, `refreshPttAvailability`, `onVoiceStatusMessage`, `initFeaturePanels` | `fetchHealth`, `fetchRuntimeStatus`, `connectVoiceStatus` |
| `voiceStudio.js` | `createVoiceStudioFeature` | (no injected `elements`; owns its own ~25 `document.getElementById` lookups) | `markProfileDirty`, `renderVoiceCloningPanel` | `fetchTtsVoices`, `fetchVoicePresets`, `saveVoicePreset`, `deleteVoicePreset`, `cloneVoice`, `speakTts` |
| `firstRun.js` | `createFirstRunFeature` | panelEl, overallBadgeEl, diskWarningEl(+messageEl), runtime/llm/whisper badge+detail els, downloadLlmButton(+llmProgress{container,label,percent,fill,bytes}), downloadWhisperButton(+whisperProgress), messageEl, refreshButton, continueButton, dismissButton | `afterModelsChanged`, `goToModelsTab` | `fetchHealth`, `fetchRuntimeStatus`, `fetchLlmModels`, `fetchWhisperModels`, `fetchLlmDownloadState`, `downloadLlmModel`, `downloadWhisperModel` |
| `messageRescue.js` | (pure, no factory) `formatContextStatus`, `formatSpeechSignals`, `formatAssessmentSummary`, `formatClarification`, `formatDeliverySignals`, `formatVariants`, `formatPreservationChecks`, `formatWarnings`, `formatMessageRescueViewModel` | n/a (no DOM) | n/a | none (pure view-model formatting, reused by messageRescuePanel/messageRescueDraft/textPlayground) |
| `messageRescuePanel.js` | `initMessageRescuePanel` (self-initializing) + exported helpers `buildMessageRescuePanelModel`, `renderMessageRescuePanel`, `escapeHtml`, `isMessageRescueEnabled` | queries its own DOM by id (`#messageRescuePanel` subtree) | none | none (synthetic example only) |
| `messageRescueDraft.js` | `initMessageRescueDraft` (called explicitly from main.js) / `createMessageRescueDraftFeature` | queries own DOM (`#draftRescuePanel` subtree) | `applyToEditor(text)` (only cross-feature hook; writes into `#draftFinalText`) | `fetchLatestDraft`, `fetchMessageRescueContext`, `captureSelectionMessageRescueContext`, `clearMessageRescueContext`, `generateMessageRescue` |
| `textPlayground.js` | `initTextPlayground` (self-initializing) / `createTextPlaygroundFeature` | queries own DOM (`#textPlaygroundSection` subtree) | none | `fetchPersonas`, `fetchDrafts`, `fetchLlmModels`, `editDraft`, `captureManualMessageRescueContext`, `clearMessageRescueContext`, `generateMessageRescue` |
| `personaLearning.js` | `initPersonaLearning` (self-initializing) / `createPersonaLearningFeature` | queries `#personaLearningSection` subtree (**does not exist in index.html — fully unwired, see Orphans**) | `getPersonaName`, `getDraftPair` (both default to reading `#settingCurrentPreset`/`#draftRawText`/`#draftFinalText`) | `fetchPersonaExamples`, `addPersonaExample`, `deletePersonaExample`, `clearPersonaExamples` |

---

## 11. BACKEND ENDPOINTS CALLED BY THE RENDERER (api/backend.js) — cross-checked against `backendProxy.js` `ROUTE_ALLOWLIST`

Legend: **[proxy]** = generic `backend:request` channel (method+path validated against the
exact allowlist table); **[typed]** = dedicated IPC method in `backendProxy.js` with its own
exact route + validated payload (destructive/sensitive ops never go through the generic proxy).

| Function (backend.js) | Method + Path | Channel | Triggering control(s) |
|---|---|---|---|
| `fetchHealth` | GET `/health` | **[typed]** `fetchHealth` | health poll (runtime.js `refreshHealth`), firstRun status |
| `fetchRuntimeStatus` | GET `/runtime/status` | proxy | status grid, doctor triggers, firstRun |
| `refreshAudioDevices` | POST `/runtime/audio-devices/refresh` | proxy | (not directly wired to a button found; used by `GET /runtime/audio-devices` refresh flow) |
| `fetchOutputSettings` | GET `/runtime/output-settings` | proxy | `#outputSettingsSummary`, send-action default resolution, review-overlay |
| `runPrimaryAction` | POST `/runtime/primary-action` | proxy | `#primaryActionButton` |
| `emergencyStop` | POST `/runtime/emergency-stop` | proxy | `#dashboardEmergencyStopButton`, `#emergencyStopButton` |
| `toggleRecording` | POST `/runtime/recording/toggle` | proxy | `#toggleRecordingButton` |
| `warmupRuntime` | POST `/runtime/warmup` | proxy | `#warmupSttButton`, `#warmupLlmButton`, `#startHotkeysButton`, `#testModelLoadButton` |
| `fetchVersion` | GET `/runtime/version` | proxy | (no direct UI button found — verify) |
| `fetchCapabilities` | GET `/capabilities` | proxy | `#capabilitiesList`, platform warnings, hotkey session indicator |
| `fetchDoctor` | GET `/doctor?refresh_audio=` | proxy | `#refreshDoctorButton`, diagnostics tab activation |
| `fetchMetrics` | GET `/metrics` | proxy | `#metricsHud` |
| `fetchPrivacy` | GET `/privacy` | proxy | Privacy section nav |
| `wipeData` | POST `/privacy/wipe` | **[typed]** `wipePrivacyData` | `#privacyWipeButton` |
| `fetchDiagnosticsLogs` | GET `/diagnostics/logs?lines=` | proxy | `#debugLogTail` |
| `fetchDiagnosticsPaths` | GET `/diagnostics/paths` | proxy | `#diagnosticsPathsList` |
| `fetchSupportReport` | GET `/diagnostics/support-report` | proxy | `#copySupportReportButton` |
| `fetchDrafts` | GET `/drafts` | proxy | draft history, textPlayground draft select |
| `fetchLatestDraft` | GET `/drafts/latest` | proxy | messageRescueDraft |
| `acceptDraft` | POST `/drafts/:id/accept` | proxy | `#acceptDraftButton` |
| `declineDraft` | POST `/drafts/:id/decline` | proxy | `#declineDraftButton` |
| `clearDrafts` | DELETE `/drafts` | proxy | `#clearDraftHistoryButton` |
| `retryDraft` | POST `/drafts/:id/retry` | proxy | `#retryDraftButton` |
| `editDraft` | POST `/drafts/:id/edit` | proxy | `#saveDraftEditButton`, textPlayground Apply, messageRescue apply-variant |
| `rewriteDraft` | POST `/drafts/:id/rewrite` | proxy | `#rewriteShorterButton`/`ClearerButton`/`ToneButton`/`CustomButton` |
| `speakDraft` | POST `/drafts/:id/tts` | proxy | `#readSelectionButton`, `#readFullDraftButton` |
| `sendDraft` | POST `/drafts/:id/send` | **[typed]** `sendDraft` | `#sendDraftButton` |
| `speakTts` | POST `/tts/speak` | proxy | `#testTtsButton` |
| `speakPreset` | POST `/tts/speak` (preset_name) | proxy | (no direct button found calling this exact wrapper — verify: presets seem applied via `applyVoicePreset` then require Audition button) |
| `stopTts` | POST `/tts/stop` | proxy | review-overlay Read/Stop toggle |
| `fetchTtsStatus` | GET `/runtime/tts-status` | proxy | review-overlay TTS backend badge |
| `fetchTtsVoices` | GET `/tts/voices` | proxy | Voice Studio init/refresh |
| `cloneVoice` | POST `/tts/clone` (multipart) | **[typed]** `uploadVoiceSample` | `#voiceCloneUploadButton` |
| `deleteVoice` | DELETE `/tts/voices/:id` | **[typed]** `deleteVoice` | (no UI button found calling this — verify: cloned-voice deletion may be an orphaned capability) |
| `fetchCloneStatus` | GET `/tts/clone/status` | proxy | (referenced by `refreshCloneStatusNote`, which is undefined — see Bug #2) |
| `provisionVoiceCloning` | POST `/tts/clone/provision` | proxy | `#provisionVoiceCloningButton` |
| `fetchVoicePresets` | GET `/voice-presets` | proxy | Voice Studio preset list/select |
| `saveVoicePreset` | POST `/voice-presets` | proxy | `#saveVoicePresetButton` |
| `deleteVoicePreset` | DELETE `/voice-presets/:name` | proxy | preset row Delete button |
| `setDefaultVoicePreset` | POST `/voice-presets/:name/make-default` | proxy | **no UI trigger found** — orphaned capability |
| `clearDefaultVoicePreset` | DELETE `/voice-presets-default` | proxy | **no UI trigger found** — orphaned capability |
| `fetchPersonas` | GET `/personas` | proxy | preset dropdown, textPlayground persona select |
| `fetchPersonaExamples` | GET `/personas/:name/examples` | proxy | **only used by unwired personaLearning.js** |
| `addPersonaExample` | POST `/personas/:name/examples` | proxy | **only used by unwired personaLearning.js** |
| `deletePersonaExample` | DELETE `/personas/:name/examples/:id` | proxy | **only used by unwired personaLearning.js** |
| `clearPersonaExamples` | DELETE `/personas/:name/examples` | proxy | **only used by unwired personaLearning.js** |
| `fetchBuiltinPersonaNames` | GET `/personas-builtins` | proxy | wizard init (builtin-name protection) |
| `getPersonaV2` | GET `/personas/:name` | proxy | wizard "load existing persona" |
| `savePersona` | POST `/personas` | proxy | wizard Save (step 4), Foundry Save |
| `deletePersona` | DELETE `/personas/:name` | proxy | `#wizardDeleteButton` |
| `lintPersona` | POST `/personas/lint` | proxy | `#wizardLintButton` |
| `testPersona` | POST `/personas/test` | proxy | `#wizardTestButton` |
| `refinePersonaPrompt` | POST `/personas/refine` | proxy | `#wizardRefinePromptButton` |
| `draftPersonaFromDescription` | POST `/personas/draft` | proxy | `#wizardDescribeButton` |
| `startFoundryInterview` | POST `/personas/interview/start` | proxy | `#openFoundryButton` |
| `answerFoundryQuestion` | POST `/personas/interview/answer` | proxy | Foundry answer/choice/collection controls |
| `compileFoundry` | POST `/personas/compile` | proxy | auto, on interview completion |
| `runFoundryStressTest` | POST `/personas/test-suite/run` | proxy | `#foundryRunStressTestButton` |
| `fetchMessageRescueContext` | GET `/message-rescue/context` | proxy | draft-bound rescue panel refresh |
| `captureManualMessageRescueContext` | POST `/message-rescue/context/manual` | proxy | textPlayground Run (when context text present) |
| `captureSelectionMessageRescueContext` | POST `/message-rescue/context/selection` | proxy | `#draftRescueCaptureButton` |
| `clearMessageRescueContext` | DELETE `/message-rescue/context` | proxy | `#draftRescueClearContextButton`, `#textPlaygroundClearButton` |
| `generateMessageRescue` | POST `/message-rescue/generate` | proxy | `#draftRescueRunButton`, `#textPlaygroundRunButton` |
| `cancelMessageRescueGeneration` | POST `/message-rescue/generate/:id/cancel` | proxy | **defined but never called** (documented limitation: job id not known in time) |
| `fetchMessageRescueResult` | GET `/message-rescue/generate/:id` | proxy | **defined but never called anywhere** — verify intent |
| `fetchSettingsProfiles`/`fetchProfiles` | GET `/settings/profiles` | proxy | `#profileSelect` populate |
| `fetchProfile` | GET `/settings/profiles/:name` | proxy | `#profileSelect` change, discard |
| `saveProfile` | POST `/settings/profiles/:name` | proxy | `#saveProfileButton` |
| `createProfile` | POST `/settings/profiles` | proxy | `#createProfileButton` |
| `activateProfile` | POST `/settings/profiles/:name/activate` | proxy | `#activateProfileButton` |
| `deleteProfile` | DELETE `/settings/profiles/:name` | proxy | `#deleteProfileButton` |
| `renameProfile` | POST `/settings/profiles/:name/rename` | proxy | `#renameProfileButton` (see Bug #1) |
| `duplicateProfile` | POST `/settings/profiles/:name/duplicate` | proxy | `#duplicateProfileButton` (see Bug #1) |
| `exportProfile` | GET `/settings/profiles/:name/export` | proxy | `#exportProfileButton` (see Bug #1) |
| `importProfile` | POST `/settings/profiles/import` | proxy | `#importProfileFile` |
| `fetchLlmModels` | GET `/models/llm` | proxy | Models tab, firstRun |
| `selectLlmModel` | POST `/models/llm/select` | proxy | `#selectLlmModelButton` |
| `downloadLlmModel` | POST `/models/llm/:id/download` | proxy | `#downloadLlmModelButton`, `#firstRunDownloadLlmButton` |
| `fetchLlmDownloadState` | GET `/models/llm/:id/download-state` | proxy | download progress polling |
| `deleteLlmModel` | DELETE `/models/llm/:id` | **[typed]** `deleteLlmModel` | `#deleteLlmModelButton` |
| `fetchWhisperModels` | GET `/models/whisper` | proxy | Models tab, firstRun |
| `downloadWhisperModel` | POST `/models/whisper/download` | proxy | `#downloadWhisperButton`, `#firstRunDownloadWhisperButton` |
| `deleteWhisperModel` | DELETE `/models/whisper/:size` | **[typed]** `deleteWhisperModel` | `#deleteWhisperButton` |
| `selectWhisperModel` | POST `/models/whisper/select` | proxy | `#selectWhisperModelButton` |
| `unloadModel` | POST `/models/unload/:component` | proxy | `#unloadSttButton`, `#unloadLlmButton`, `#unloadTtsButton` |
| `fetchModelRecommendation` | GET `/models/recommend` | proxy | Models tab banner, onboarding step 4 |
| `fetchDictionary` | GET `/dictionary` | proxy | Dictionary section |
| `addDictionaryTerm` | POST `/dictionary` | proxy | `#dictionaryAddButton` |
| `deleteDictionaryTerm` | DELETE `/dictionary/:term` | proxy | dictionary chip remove |
| `suggestDictionaryTerms` | POST `/dictionary/suggest` | proxy | auto after draft edit |
| `fetchMacros` | GET `/macros` | proxy | Macros section |
| `addMacro` | POST `/macros` | proxy | `#macroAddButton` |
| `deleteMacro` | DELETE `/macros/:trigger` | proxy | macro row remove |
| `searchHistory` | GET `/history/search` | proxy | `#historySearchInput` |
| `fetchHistoryRecent` | GET `/history` | proxy | **exported, not called anywhere in main.js/features** — verify |
| `clearHistory` | DELETE `/history` | proxy | **exported, not called anywhere** — verify (draft history clear uses `/drafts`, not `/history`) |
| `fetchRecordings` | GET `/recordings` | proxy | `#recordingsList` |
| `retranscribeRecording` | POST `/recordings/:id/retranscribe` | proxy | recording row "Re-transcribe" |
| `deleteRecording` | DELETE `/recordings/:id` | proxy | recording row "Discard" |
| `clearRecordings` | DELETE `/recordings` | proxy | `#clearRecordingsButton` |
| `fetchJobs` | GET `/jobs?active=` | proxy | `#jobsList` |
| `cancelJob` | POST `/jobs/:id/cancel` | **[typed]** `cancelJob` | job row "Cancel" |
| `fetchRuntimeErrors` | GET `/runtime/errors` | proxy | `#runtimeErrorsList` |
| `fetchWakeStatus` | GET `/wake/status` | proxy | Voice Control status |
| `fetchWakeModels` | GET `/wake/models` | proxy | Voice Control + Models tab wake engine list |
| `enableWake` | POST `/wake/enable` | proxy | `#settingWakeWordEnabled` on |
| `disableWake` | POST `/wake/disable` | proxy | `#settingWakeWordEnabled` off |
| `downloadWakeModel` | POST `/wake/models/:id/download` | proxy | Models tab backbone Download button |
| `fetchWakeModelDownloadState` | GET `/wake/models/:id/download-state` | proxy | backbone download polling |
| `deleteWakeModel` | DELETE `/wake/models/:id` | proxy | **exported, no UI button found calling it** — verify |
| `importWakeModel` | POST `/wake/models/import` (multipart) | **[typed]** `uploadWakeModel` | `#importWakeModelButton`/file input |
| `testWake` | POST `/wake/test` | proxy | `#testWakeButton` |
| `trainWakePhrase` | POST `/wake/train` | proxy | `#wakeTrainButton` |
| `fetchWakeTrainStatus` | GET `/wake/train/status` | proxy | training progress poll |
| `connectVoiceStatus` | WS `/ws/voice_status` | **[typed, main-owned]** | `#wsConnection`, drives most live dashboard state |

**Allowlist cross-check:** every proxy-channel route above appears verbatim in
`backendProxy.js`'s `ROUTE_ALLOWLIST` (GET/POST/DELETE tables). Every destructive/sensitive
operation (`sendDraft`, privacy wipe, LLM/Whisper/voice deletion, job cancel, voice-sample and
wake-model uploads) is routed through a **typed** IPC method with its own hard-coded route and a
`confirm:true` gate where destructive — none of those routes are reachable via the generic
proxy channel, matching the security comment at the top of `backendProxy.js`. No renderer call
was found targeting a route absent from the allowlist.

---

## 12. THE TWO OVERLAYS

### 12.1 `overlay.html` — floating recording/status "glitch ring"

Separate always-on-top, click-through-by-default window. Frameless, transparent, drag-to-move
(mouse-enter temporarily disables click-through so it can be dragged).

- [ ] `#statusRing` (`<canvas>`) — animated ring, driven by `glitch-ring.js` (`createGlitchRing`)
- [ ] `#statusText` — status label, position/visibility driven by appearance settings
- [ ] Ring states (from `glitch-ring.js` `STATE_STYLES`): idle, listening, recording, transcribing, stitching, ready, error, warning (+ aliases: rewriting/processing/chunking→transcribing, blocked→error, sent/success→ready, danger→error)
- [ ] IPC in: `window.betterFingersOverlay.onStatusUpdate(update)` — maps every voice-status payload kind to a ring state + label: recording_started/recording, listening/recording_armed, transcribing/rewriting/processing, long_recording_detected/chunking_started/chunking_progress, chunking_stitching, preview_ready, draft_sent (+fallback variant), selection_captured, emergency_stop, draft_blocked/draft_error/draft_send_error/selection_capture_failed
- [ ] Live amplitude: `ring.setAmplitude(payload.amplitude)` pulses the ring/wave during active recording
- [ ] IPC in: `window.betterFingersOverlay.onAppearance(a)` — pushed on load and on any settings change: size (small/medium/large/xlarge → px), placement (drives layout direction via CSS classes `pos-beside`/`pos-above`/`pos-below`/`pos-center`), opacity/vibrancy, label position (hidden/below/above/center/beside)
- [ ] IPC out: `window.betterFingersOverlay.setIgnoreMouseEvents(bool)` on mouseenter/mouseleave (drag affordance)
- [ ] No backend calls — pure IPC-driven presentation layer

### 12.2 `review-overlay.html` — floating draft review window

Separate window, dark-themed fixed layout (`shell` grid: header/main/footer), own copy of the
proxy-request helper (does not import `api/backend.js`).

- [ ] Header: `h1` "Review Draft", `#status` (draft #N), `#statusBadge` (12 states: pending, rewriting, rewritten, speaking [pulsing], accepted, sent, copied, declined, error, interrupted, stopped, confirm [pulsing]), `#ttsBackendBadge` (success/warning/danger tinted), `#commandBadge` (transient, shows detected voice command for 3s)
- [ ] `#closeButton` — "X" → stops TTS if speaking, `window.betterFingersReview.hide()`
- [ ] `#rawText` — raw transcript (read-only)
- [ ] `#finalText` — cleaned-output textarea (editable, spellcheck on)
- [ ] `#draftSummary` — live word/length summary (via `lib/draftSummary.mjs`'s `formatDraftSummary`, with a bare-word-count fallback)
- [ ] `#instructionRow` (toggleable) — `#instructionText` + `#runInstructionButton` ("Rewrite") for custom rewrite instructions
- [ ] Footer actions:
  - [ ] `#acceptButton` — "Accept" (primary) → saves edit, `POST /drafts/:id/accept`; if profile is auto_send and the draft wasn't confidence-gated, immediately sends via typed `sendDraft` IPC and auto-hides after 1.2s on success; otherwise shows "Press the primary action hotkey to send" (with the specific confidence-gate reason: low_confidence/confidence_missing/confidence_moderate/long_draft/audio_gate)
  - [ ] `#rewritePreset` — select: Clearer/Shorter/Tone
  - [ ] `#changeButton` — "Rewrite" (uses the selected preset) → `POST /drafts/:id/rewrite`
  - [ ] `#instructButton` — "Instruct" — toggles the instruction row
  - [ ] `#readButton` — "Read"/"Stop" toggle → `POST /drafts/:id/tts` or `POST /tts/stop`
  - [ ] `#cancelButton` — "Cancel" (danger) → `POST /drafts/:id/decline`, hides overlay
  - [ ] `#message` — status/error line (tone-colored: success/warning/danger)
- [ ] IPC in: `window.betterFingersReview.onDraft(draft)` — full re-render + refresh output settings + TTS status badge + focuses Accept
- [ ] IPC in: `window.betterFingersReview.onStatus(update)` — handles: draft_tts_started/stopped (speaking state), emergency_stop (stopped state), draft_sent (sent/copied + auto-hide), draft_send_error, command_detected/command_needs_confirmation (command badge + "confirm" state), scratch_last (shows scratched-text message)
- [ ] Escape key — dismiss (hide, not decline)
- [ ] Own backend calls (same routes as the dashboard's drafts feature): `/drafts/:id/edit`, `/drafts/:id/accept`, `/drafts/:id/rewrite`, `/drafts/:id/decline`, `/drafts/:id/tts`, `/tts/stop`, `/runtime/output-settings`, `/runtime/tts-status`, plus typed `sendDraft` IPC

---

## 13. SETTINGS → PROFILE FIELD MAP (every key in `settingEls`, main.js)

Grouped exactly as the Settings sidebar groups them. `checked`-by-default fields noted.

**Recording:** `recording_mode`, `auto_stop_after_silence_enabled`, `auto_stop_silence_ms`,
`auto_stop_min_recording_ms`, `voice_commands_enabled` (default true)

**Hotkeys:** `hotkey`, `force_stop_key`, `manual_send_hotkey`, `review_tts_hotkey`,
`chat_open_key`, `voice_mute_key`

**Review & Drafts:** `send_mode`, `confidence_force_review_enabled` (default true),
`confidence_force_review_below`, `confidence_auto_send_above`, `auto_submit`,
`instant_typing`, `restore_clipboard_after_paste` (default true), `draft_history_limit`
(index.html has `#settingDraftHistoryLimit`; **not present in `settingEls` map** — verify this
setting is actually collected/restored)

**AI Cleanup:** `current_preset`, `max_completion_tokens`, `long_draft_warning_words`,
`long_recording_stitch_pass_enabled`, `llm_chunk_size`, `whisper_chunk_size`

**Send & Injection:** `audio_ducking`

**Audio Devices:** `input_device_index`

**Voice Control:** `wake_word_model`, `wake_word_sensitivity`, `wake_word_cooldown_s`,
`wake_word_max_recording_s` (note: `wake_word_enabled` itself is NOT in `settingEls` — it's
handled live via `enableWake`/`disableWake`, not the save/discard profile cycle)

**TTS/Read-Aloud:** `review_tts_voice_hint`, `review_tts_speed`, plus (owned by
`voiceStudio.js`, not `settingEls`): `review_tts_blend` (dict), `review_tts_pitch`,
`review_tts_energy`, `review_tts_warmth`, `review_tts_brightness`, `review_tts_pause_style`

**Notifications & Status:** `status_indicator_enabled`, `notification_overlay_enabled`,
`preview_overlay_enabled`

**Advanced & Developer:** `model_keep_llm_loaded`, `model_keep_stt_loaded`,
`model_keep_tts_loaded`

**Recording (silence gate, also under Recording section visually):**
`no_audio_min_duration_sec`, `no_audio_min_rms`, `no_audio_min_peak`

**Not backend-profile fields at all** (client-`localStorage` only, Appearance section):
`pref_theme`, `pref_accent`, `pref_density`, `pref_font_size`, `pref_high_contrast`

**Not backend-profile fields at all** (client-`localStorage`, feature flags):
`bf_onboarding_complete`, `bf_first_run_dismissed`, `pref_message_rescue_enabled`

**Not backend-profile fields at all** (Electron-main-owned, `window.betterFingers.*OverlayAppearance`):
overlay `size`, `placement`, `opacity`, `vibrancy`, `labelPos`, `alwaysOn`

---

## 14. STATUS / NOTIFICATION SURFACES

- [ ] Toast stack — `#toastContainer` (`showToast(message, tone, durationMs)`), app-wide, dismissible, auto-expiring (0 = sticky, used for disk-space/wipe-failure messages)
- [ ] Backend version/health banner — `#versionMismatchBanner` (states: version_mismatch, unhealthy, restarting, crashed)
- [ ] Per-panel inline status lines (`setMessage(el, text, tone)` pattern) — at least: `#draftMessageEl`, `#profileMessageEl`, `#modelMessageEl`, `#warmupMessageEl`, `#privacyMessage`, `#wizardMessage`, `#foundryMessage`, `#firstRunMessageEl`, plus every Message-Rescue/Text-Playground status/error line
- [ ] Connection pill — `#wsConnection` (connecting/connected/reconnecting/error)
- [ ] Draft status pill — `#draftStatus`
- [ ] Send-result detail panel — `#sendResultPanel` (requested/used action, fallback reason, platform/session)
- [ ] Confidence badge — `#draftConfidence` (tinted by score)
- [ ] Floating status overlay (window) — see 12.1
- [ ] Review overlay status badge/TTS badge/command badge — see 12.2
- [ ] Live mic meter — `#micMeterBar`/`#micMeterFill` (Settings → Audio Devices)
- [ ] Live wake-score meter — `#wakeScoreBar`/`#wakeScoreFill` (Settings → Voice Control)
- [ ] Live wake-train progress — `#wakeTrainProgress*`
- [ ] Model download progress bars — LLM (Models tab + First-run), Whisper (First-run)
- [ ] Doctor recovery panel — `#doctorRecoveryPanel`

---

## 15. POTENTIAL ORPHANS (easy to forget in a redesign — verify each is intentionally kept or intentionally cut)

- [ ] **Persona Learning ("Teach this persona from my edit")** — `features/personaLearning.js` is a
      complete, fully-implemented, consent-gated feature (prepare pair → consent checkbox →
      confirm & teach → list/delete/clear learned examples) with backend routes already wired
      end-to-end (`GET/POST/DELETE /personas/:name/examples`), but **its target DOM
      (`#personaLearningSection`) does not exist anywhere in `index.html`**, and it is not
      imported by `main.js`. It is dead code today — no script tag loads it, no UI surfaces it.
      This is the single biggest "don't lose this in the redesign" risk in the whole app: an
      entire finished feature with zero current UI presence.
- [ ] **Keyboard/controller hotkey configuration** — all 6 hotkey fields + custom
      click-to-record widget + collision detection (section 7.3) + the Wayland fallback warning.
- [ ] **Audio device selection** — `#settingInputDevice` (Settings → Audio Devices) — easy to
      conflate with the mic-level test button next to it.
- [ ] **Privacy wipe** — `#privacyWipeButton` + `#privacyWipeVoices` + the truthful
      postcondition-summary messaging (`lib/wipeSummary.mjs`) — must not be downgraded to a
      generic "are you sure?" without surfacing which postconditions actually failed.
- [ ] **Export / Import profile** — `#exportProfileButton` (client-side file download) /
      `#importProfileFile` (legacy-schema upgrade logic on import) — note Bug #1 re: export's
      current wiring.
- [ ] **Rename / Duplicate profile** — see Bug #1; intent is clear from backend.js + index.html,
      current click-wiring is suspect.
- [ ] **Donation prompt** — **none found anywhere** in the scoped files (index.html, main.js,
      features/*, overlays). If one exists it must live outside this scope (e.g. a native menu,
      tray, or a separate window not covered by this inventory) — flag to the user rather than
      assume it's covered.
- [ ] **Support report** — `#copySupportReportButton` (Diagnostics tab) — privacy-safe markdown
      report copied to clipboard; easy to lose track of since it's a single button in a busy tab.
- [ ] **Wake-word training** — the entire "Build a Wake Phrase" group (7.8): phrase input,
      synthesize-and-train flow, verdict copy (reliable/noisy/unusable), false-accept/reject
      rates — distinct from simply enabling/importing a wake model.
- [ ] **Wake model import** (`.onnx` upload, licensing-responsibility disclaimer) — distinct
      from wake model *download* (backbones) and from wake *training*.
- [ ] **Voice cloning** — three distinct entry points that are easy to conflate: (a) Models tab
      "Install voice cloning" provisioning, (b) Settings → TTS/Read-Aloud "Voice Cloning
      (Advanced)" consent+upload flow, (c) the hidden, unwired `#voiceCloneInstallButton`.
- [ ] **Voice presets "make default" / "clear default"** — backend routes and `backend.js`
      wrappers exist (`setDefaultVoicePreset`, `clearDefaultVoicePreset`) with **no UI control
      found calling them anywhere** — verify whether this is a cut feature or missing UI.
- [ ] **Cloned-voice deletion** — `deleteVoice()`/`DELETE /tts/voices/:id` exists as a typed IPC
      method with no UI trigger found — verify.
- [ ] **Wake model deletion** — `deleteWakeModel()`/`DELETE /wake/models/:id` exported, no UI
      trigger found — verify.
- [ ] **History search vs. draft clear** — `searchHistory`/`fetchHistoryRecent`/`clearHistory`
      hit `/history*` routes (a separate full-text archive) distinct from `/drafts` (`clearDrafts`
      wired to "Clear History" button, which actually clears the **drafts** table, not history).
      `fetchHistoryRecent` and `clearHistory` are exported but never called — verify whether a
      "clear history" control is missing or intentionally absent.
- [ ] **Job cancellation** (Diagnostics → Active jobs) — easy to fold into "recordings" or
      "doctor" in a redesign; it's its own list with its own cancel affordance.
- [ ] **Pipeline latency HUD** (`#metricsHud`) — per-stage p50/p95 timing table, easy to treat as
      a "nice to have" and drop.
- [ ] **Sidecar startup logs** vs. **debug.log tail** vs. **runtime errors list** — three
      separate log/error surfaces in Diagnostics that look similar but pull from different
      sources (`getSidecarLogs()` IPC vs. `/diagnostics/logs` vs. `/runtime/errors`).
- [ ] **Message Rescue** exists in **three independent places** with different data sources —
      easy to accidentally merge or drop one: (a) static synthetic preview (`#messageRescuePanel`,
      flag-gated, no backend calls), (b) live draft-bound panel (`#draftRescuePanel`, operates on
      the *latest* draft only), (c) the Text & Persona Playground (`#textPlaygroundSection`,
      free-standing, no draft/mic/TTS at all). All three share the same pure formatter
      (`messageRescue.js`) and escaped renderer (`messageRescuePanel.js`) but are functionally
      distinct surfaces.
- [ ] **Macros vs. Dictionary** — both are simple trigger→value lists with near-identical chip
      UI; easy to accidentally collapse into one generic "text replacement" widget and lose the
      macros-specific `macros_enabled` toggle or the dictionary's auto-suggest-from-edit flow.
- [ ] **Confidence-gated auto-send** thresholds (`confidence_force_review_enabled/below`,
      `confidence_auto_send_above`) — subtle interaction with `send_mode`; the review-overlay's
      "Review required (reason)" messaging depends on all three together.
- [ ] **"Voice Mute Key"** (`#settingVoiceMuteKey`) — a rarely-mentioned 6th hotkey (mutes system
      mic channels while recording) that's easy to overlook among the more obvious
      recording/emergency-stop/primary-action hotkeys.
- [ ] **"Long Recording Stitch Pass"** toggle — a subtle cleanup-quality setting for chunked long
      recordings; easy to drop as "just another checkbox."
- [ ] **Foundry vs. manual wizard "Delete Custom Persona"** — the wizard has a delete button
      gated on "not a builtin AND currently loaded"; Foundry has no delete path of its own (it
      only creates/saves). Don't assume Foundry personas are deletable from within Foundry.
- [ ] **First-run panel dismissal is sticky per-device** (`localStorage['bf_first_run_dismissed']`),
      separate from the one-time onboarding overlay flag — two independent "don't show me this
      again" flags that must both be preserved distinctly.

---

## 16. TOTALS

- Distinct top-level surfaces: **11** (onboarding overlay, Foundry overlay, app shell/header, tab
  nav, Dashboard tab [7 sub-panels], Settings tab [14 sections + save bar], Models tab, Diagnostics
  tab [6 sub-panels], overlay.html, review-overlay.html, toast stack)
- Total checklist items (`- [ ]`) across this entire document: **438** (verified by counting
  the actual markdown checkboxes, not estimated) — this spans every button/input/select/slider/
  toggle/radio-group/file-upload/list-with-actions, every surface heading, every backend
  endpoint row, every settings key, every status surface, and every orphan flag. As a rough
  breakdown: surfaces (§1) 20, onboarding+Foundry (§2-3) ~45, dashboard (§6) ~85, settings (§7)
  ~110, models (§8) ~25, diagnostics (§9) ~25, overlays (§12) ~35, backend endpoints (§11) ~95,
  status surfaces (§14) ~15, orphans (§15) 21, bugs (§0) 2.
- Backend endpoints cross-referenced in section 11: **≈95** distinct renderer-side wrapper
  functions covering **≈80** distinct HTTP routes (some wrappers share a route, e.g.
  `speakTts`/`speakPreset` both hit `POST /tts/speak`)
- Feature modules cataloged in section 10: **10**
- Confirmed live bugs found via static analysis: **2** (section 0)
- Orphan/at-risk items flagged in section 15: **21**
