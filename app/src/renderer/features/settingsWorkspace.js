// settingsWorkspace.js — thin wiring adapter for the SETTINGS workspace
// (Phase 5b of the Signal Desk redesign, docs/ui/SIGNAL_DESK_SPEC.md section
// 8, worked from docs/ui/CURRENT_UI_INVENTORY.md section 7).
//
// Like studioWorkspace.js/libraryWorkspace.js/utilitiesWorkspace.js, this
// module does NOT reimplement persistence — it binds new Settings markup
// (signal-desk.css / signal-desk-preview.html) to the EXISTING data sources:
// api/backend.js's profile + privacy routes (fetchProfiles/fetchProfile/
// saveProfile/createProfile/activateProfile/renameProfile/duplicateProfile/
// exportProfile/importProfile/deleteProfile/fetchPrivacy/wipeData/
// fetchPersonas — the last one only to populate the "current_preset"
// dropdown's option list), called directly here (same convention every
// other workspace module uses: feature modules call backend.js directly for
// their OWN data), lib/wipeSummary.mjs's summarizeWipeFailure/
// isPreDeleteAbort (REUSED, not reimplemented, for truthful wipe reporting —
// see the work packet's explicit "do NOT downgrade to a generic confirm"
// instruction), and window.betterFingers.*OverlayAppearance for the Floating
// Overlay group (Electron-main-owned, no backend round-trip, same as
// main.js's initOverlayAppearanceControls()).
//
// index.html/main.js are NOT touched this phase (additive only).
//
// ===========================================================================
// INVENTORY -> SETTINGS SECTION PLACEMENT MAP
// (CURRENT_UI_INVENTORY.md section 7's "every checkbox needs a home" gate.
// Settings has 7 internal sections — an internal sub-nav within the shared
// Signal Desk shell's center column, same pattern utilitiesWorkspace.js
// established: Profile · Recording · Review & Drafts · AI Cleanup ·
// Notifications · Appearance · Privacy — see SETTINGS_SECTIONS below.)
//
// This exact map is also exported as INVENTORY_PLACEMENT_MAP (machine-
// readable) so tests/settingsWorkspace.test.mjs's completeness test can
// assert every required key names a valid Settings section.
//
// --- PROFILE section (inventory §7.0 sticky bar + §7.1 profile mgmt) ------
//   profile.select              Active-profile dropdown                    -> fetchProfile(name)                    [wired]
//   profile.newName             Shared name/target input                   -> local state, read by ops below        [wired]
//   profile.activate            "Activate"                                 -> activateProfile()                     [wired]
//   profile.create               "Create New"                              -> createProfile()                       [wired]
//   profile.rename                "Rename Profile"                         -> renameProfile()  **BUG #1 FIX: see below** [wired]
//   profile.duplicate             "Duplicate Profile"                      -> duplicateProfile() **BUG #1 FIX**      [wired]
//   profile.export                "Export Profile" (Blob + anchor download) -> exportProfile()  **BUG #1 FIX**       [wired]
//   profile.import                "Import Profile" (.json, legacy upgrade) -> importProfile()                       [wired]
//   profile.delete                "Delete Profile" (blocks Default)        -> deleteProfile()                       [wired]
//   profile.saveBar               sticky Save/Discard bar + #profileMessage -> saveProfile()/fetchProfile()          [wired]
//   profile.validation             live client-side range validation        -> runSettingsValidation() (pure)        [wired]
//
//   *** BUG #1 FIX (CURRENT_UI_INVENTORY.md §0): today's main.js declares
//   `renameProfileButton`/`duplicateProfileButton`/`exportProfileButton` as
//   bare identifiers that are NEVER bound via getElementById — a
//   ReferenceError at module top-level evaluation. This adapter is written
//   from scratch against SETTINGS_ELEMENT_IDS (below), which DOES include
//   all three (renameButton/duplicateButton/exportButton), captured for real
//   by collectSettingsElements() and wired for real in
//   createSettingsWorkspaceFeature()'s bindProfileButtons(). The bug cannot
//   reproduce here because there is no bare-identifier reference anywhere in
//   this file — every element access goes through `els.*`. ***
//
// --- RECORDING section (inventory §7.2) ------------------------------------
//   recording.mode                 recording_mode select                   -> profile field `recording_mode`        [wired]
//   recording.pttNote               PTT availability note                  -> window.betterFingers.getHotkeyCapabilities() (best-effort) [wired, informational]
//   recording.autoStopSilence       auto_stop_after_silence_enabled + ms + min_ms -> profile fields                  [wired]
//   recording.voiceCommands         voice_commands_enabled (default ON)    -> profile field                          [wired]
//   recording.noAudioGate           no_audio_min_duration_sec/rms/peak     -> profile fields                          [wired]
//
// --- REVIEW & DRAFTS section (inventory §7.4) ------------------------------
//   review.sendMode                 send_mode select                        -> profile field                          [wired]
//   review.confidenceGate           confidence_force_review_* + auto_send_above -> profile fields                    [wired]
//   review.autoSubmit               auto_submit                              -> profile field                          [wired]
//   review.instantTyping            instant_typing                           -> profile field                          [wired]
//   review.restoreClipboard         restore_clipboard_after_paste (default ON) -> profile field                       [wired]
//   review.draftHistoryLimit        draft_history_limit (10-500)             -> profile field  **WIRING FIX: see below** [wired]
//
//   *** draft_history_limit FIX (CURRENT_UI_INVENTORY.md §7.4/§13): today's
//   `#settingDraftHistoryLimit` exists in index.html but is absent from
//   main.js's `settingEls` map, so it is never collected on Save nor
//   restored on profile load — edits to it are silently discarded. This
//   adapter includes `draft_history_limit` in SETTINGS_FIELD_KEYS/
//   SETTINGS_FIELD_TYPES (type: number) and SETTINGS_VALIDATION_RULES
//   (10-500, matching the HTML's own min/max attributes), so it round-trips
//   through collect/restore/save exactly like every other numeric field. ***
//
// --- AI CLEANUP section (inventory §7.5, numeric knobs only — the persona
//     wizard/Foundry themselves are Studio's, per the work packet) ---------
//   aicleanup.currentPreset          current_preset select (persona names)   -> profile field, options from fetchPersonas() [wired]
//   aicleanup.maxCompletionTokens    max_completion_tokens (512-4096)        -> profile field                          [wired]
//   aicleanup.longDraftWarningWords  long_draft_warning_words (300-10000)    -> profile field                          [wired]
//   aicleanup.llmChunkSize           llm_chunk_size (50-5000)                -> profile field                          [wired]
//   aicleanup.whisperChunkSize       whisper_chunk_size (50-5000)            -> profile field                          [wired]
//   aicleanup.stitchPass             long_recording_stitch_pass_enabled      -> profile field                          [wired]
//
// --- NOTIFICATIONS & STATUS section (inventory §7.10) ----------------------
//   notifications.statusIndicator    status_indicator_enabled                -> profile field                          [wired]
//   notifications.notificationOverlay notification_overlay_enabled          -> profile field                          [wired]
//   notifications.previewOverlay     preview_overlay_enabled                 -> profile field                          [wired]
//
// --- APPEARANCE section (inventory §7.11) -----------------------------------
//   appearance.theme/accent/density/fontSize/highContrast  client-localStorage, applied live -> computeAppearanceClasses() (pure) [wired]
//   appearance.overlayGroup          Floating Overlay size/placement/opacity/vibrancy/labelPos/alwaysOn -> window.betterFingers.*OverlayAppearance [wired]
//
// --- PRIVACY section (inventory §7.14) --------------------------------------
//   privacy.networkList              network touchpoints                     -> fetchPrivacy()                         [wired]
//   privacy.dataList                 on-device data locations                -> fetchPrivacy()                         [wired]
//   privacy.wakeListenerStatus       wake-listener active/inactive note      -> fetchPrivacy()                         [wired]
//   privacy.wipe                     "Wipe my data…" + "also delete cloned voices" -> wipeData() + lib/wipeSummary.mjs's summarizeWipeFailure() (REUSED, truthful postcondition reporting — never claims success unless every postcondition held; NOT downgraded to a generic confirm() message, matches main.js's handleWipeData() wording) [wired]
//
// --- INTENTIONALLY NOT DUPLICATED (already homed elsewhere; see that
//     module's own placement map) -------------------------------------------
//   §7.3 Hotkeys (all 6 fields + click-to-record widget + collision detection + Wayland banner)  -> Utilities / Speech Input (utilitiesWorkspace.js `speech.hotkeys.*`)
//   §7.6 Send & Injection (audio_ducking + warnings + Test Paste/Copy)                             -> Utilities / Advanced (`advanced.sendInjection.*`)
//   §7.7 Audio Devices (input_device_index select + mic test)                                      -> Utilities / Speech Input (`speech.audioDevice.*`)
//   §7.8 Voice Control / Wake Word (enable + model + import + training + tuning + live test)        -> Utilities / Speech Input (`speech.wake.*`)
//   §7.9 TTS / Read-Aloud (Voice Studio: base voice, blend, modulation, presets, cloning)            -> Studio (studioWorkspace.js's VOICE & DELIVERY strip; review_tts_voice_hint/review_tts_speed are voiceStudio.js's persistable state, not settingEls)
//   §7.5.1 Persona Wizard + Persona Foundry (the guided builders themselves) -> Studio (studioWorkspace.js SPEC GAP 7 — "＋ New Persona"/"Build with AI")
//   §7.12 Personal Dictionary                                                                       -> Utilities / Text Tools (`textTools.dictionary.*`)
//   §7.13 Voice Macros                                                                              -> Utilities / Text Tools (`textTools.macros.*`)
//   §7.16 Advanced & Developer (warmup, primary action, emergency stop, model residency keeps,      -> Utilities / Advanced (`advanced.*`) — model residency
//         test model load, capabilities/runtime dumps)                                                 explicitly called out in the work packet as "keep in Utilities,
//                                                                                                        do not repeat in Settings."
//
// ===========================================================================
// SPEC GAPS / placement decisions the director should confirm or redirect:
//
//   1. `#pttAvailabilityNote` (§7.2): main.js populates this from
//      `window.betterFingers.getHotkeyCapabilities()` even though the 6
//      hotkey FIELDS themselves live in Utilities. Kept here (best-effort,
//      optional-chained) because it is directly about `recording_mode`
//      (Settings-owned), not about a specific hotkey binding.
//   2. `current_preset`'s option list needs the set of persona NAMES.
//      Rather than depend on Studio's live persona state (cross-workspace
//      coupling none of the other adapters use), this calls
//      `fetchPersonas()` directly — same "call backend.js directly for your
//      own data" convention studioWorkspace.js/libraryWorkspace.js already
//      use — and exposes `setPersonaOptions(names)` for preview/test mocking
//      (mirrors utilitiesWorkspace.js's `setModelPayloads`/
//      `setAudioDevices` mock-seam convention).
//   3. Search (§7.0 `#settingsSearchInput`): main.js's `filterSettings()`
//      matches row textContent + input id/name/placeholder and, while
//      searching, shows every section with a match (not just the active
//      one), same as this adapter's `filterByQuery()` — see that function's
//      comment for the exact behavior it mirrors.
//   4. Privacy network/data lists are rendered via safe DOM construction
//      (createElement + textContent) rather than main.js's innerHTML
//      template-string approach — same visual output, defense-in-depth only
//      (the underlying data is backend-controlled, not attacker input, but
//      there is no reason to prefer innerHTML here).
//
// ---------------------------------------------------------------------------
// hooks contract (all optional; every call is optional-chained so a missing
// hook is a safe no-op, never a throw):
//
//   hooks.showToast(msg, tone, duration)      Optional user feedback (same
//                              shared helper signature as ui.showToast
//                              elsewhere).
//   hooks.confirmFn(message)   Defaults to window.confirm. Overridable for
//                              tests / non-browser hosts. Used ONLY for the
//                              privacy wipe's destructive-action confirmation
//                              (same gate main.js's handleWipeData() has
//                              today — NOT downgraded, per the work packet).
//   hooks.overlayBridge        Defaults to window.betterFingers. Overridable
//                              so the Floating Overlay group can be tested
//                              without a real Electron preload bridge.
//   hooks.onProfileChanged(payload)   TODO(phase-integration): called after
//                              any op that changes the profile LIST or the
//                              ACTIVE profile (activate/create/rename/
//                              duplicate/delete/import) — main.js's real
//                              composition should use this to refresh
//                              cross-cutting state the same way today's
//                              activateProfileButton/deleteProfileButton
//                              handlers call `refreshRuntime()`/
//                              `refreshOutputSettings()`/`refreshModels()`.
//                              Safe no-op until wired.
//   hooks.onProfileSaved(payload)     TODO(phase-integration): called after
//                              a successful Save. Same composition gap as
//                              above (main.js's saveProfileButton handler
//                              also calls refreshRuntime/refreshOutputSettings/
//                              refreshModels after a save).
//
// To mount for real: pass `elements` from collectSettingsElements() (or an
// equivalent object), call `init()`, then `refreshAll()`.
// ===========================================================================

import {
  fetchProfiles,
  fetchProfile,
  saveProfile,
  createProfile,
  activateProfile,
  renameProfile,
  duplicateProfile,
  exportProfile,
  importProfile,
  deleteProfile,
  fetchPrivacy,
  wipeData,
  fetchPersonas,
  // Wave 6 privacy closure.
  factoryReset,
  verifyFactoryReset,
  clearPersonaLearning,
  verifyPersonaLearning,
  exportPrivacyData,
} from '../api/backend.js';
import { summarizeWipeFailure } from '../lib/wipeSummary.mjs';

// --- Section routing (pure, same reducer shape as signalDeskShell.js /
// utilitiesWorkspace.js's computeNextUtilitiesSection) -----------------------

export const SETTINGS_SECTIONS = ['profile', 'recording', 'review', 'aicleanup', 'notifications', 'appearance', 'privacy'];

export const SETTINGS_SECTION_META = {
  profile: { label: 'Profile', description: 'Switch, create, rename, duplicate, export/import, and delete configuration profiles.' },
  recording: { label: 'Recording', description: 'Recording mode, auto-stop on silence, voice commands, and the no-audio gate.' },
  review: { label: 'Review & Drafts', description: 'How drafts are sent, confidence gating, auto-submit, and clipboard/draft history behavior.' },
  aicleanup: { label: 'AI Cleanup', description: 'Active persona and the numeric tuning knobs for LLM cleanup and chunking.' },
  notifications: { label: 'Notifications', description: 'Status indicator, notification overlay, and preview overlay toggles.' },
  appearance: { label: 'Appearance', description: 'Theme, accent, density, font size, high contrast, and the floating overlay look.' },
  privacy: { label: 'Privacy', description: 'What touches the network, what is stored on this device, and wiping your data.' },
};

export function isValidSettingsSection(id) {
  return SETTINGS_SECTIONS.includes(id);
}

/** Pure reducer, same shape as signalDeskShell.js's computeNextState -- an unknown id is a no-op. */
export function computeNextSettingsSection(state, requestedId) {
  const current = state && isValidSettingsSection(state.active) ? state.active : SETTINGS_SECTIONS[0];
  if (!isValidSettingsSection(requestedId)) {
    return { active: current };
  }
  return { active: requestedId };
}

// --- Disclosed toggles (D-0005) ---------------------------------------------
//
// Two profile keys change what the model is told about your speech and your
// audience. Both existed in the backend with no way for an ordinary user to
// see them, which is the specific thing D-0005 forbids: a feature nobody can
// inspect is a feature nobody consented to.
//
// A plain checkbox would not have fixed that. "Use speech delivery signals"
// tells a user nothing about what is collected, what changes, or what is
// promised to survive. So each control carries six required pieces -- data
// used, what it may change, what it must preserve, its default, where to
// inspect the data, and its preservation-gate status -- and the shape is
// enforced by a test rather than by whoever writes the next one.
//
// `userEnablable` is the honest/live distinction. Delivery signals have
// retained PASS 3/3 preservation evidence and no decision blocking them, so a
// user may turn them on; they simply default off. Audience context may NOT be
// turned on here: D-0005 reserves that for a director ruling at Gate 5. Its
// control renders, discloses and reports its gate, and cannot be switched --
// and `use_audience_context` is deliberately absent from SETTINGS_FIELD_KEYS
// below, so no save path can carry it at all. A disabled checkbox is a
// promise; a key that is never collected is a guarantee.
export const DISCLOSED_TOGGLES = [
  {
    key: 'use_delivery_signals',
    label: 'Use speech delivery signals',
    summary: 'Tell the cleanup model how you said something, not just what you said.',
    dataUsed: 'Pace, pauses, emphasis and hesitation measured from the recording you just made. Derived on this device from audio that is already being transcribed; no new recording and nothing extra leaves your machine.',
    mayChange: 'Punctuation, sentence breaks and emphasis in the cleaned-up draft. A long pause may become a paragraph break; stress may become italics or a comma.',
    mustPreserve: 'Your words, their order, and their meaning. Delivery signals may change how a sentence is set, never what it says — hedges, negations and specifics stay exactly as you said them.',
    defaultOn: false,
    inspect: {
      label: 'See the signals recorded on your drafts',
      // Drafts carry `speech_signals`; the Privacy section lists where drafts
      // live on disk and is the honest "inspect the data" destination today.
      section: 'privacy',
      target: 'speech_signals',
    },
    gate: {
      status: 'qualified',
      text: 'Preservation check passed (PASS 3/3, retained Wave 0 baseline). Off by default so the change is yours to make.',
      decision: 'D-0005',
    },
    userEnablable: true,
  },
  {
    key: 'use_audience_context',
    label: 'Use selected contact/audience context',
    summary: 'Let the cleanup model know who you are writing to.',
    dataUsed: 'The contact you selected in "Writing to" — their relationship and tone notes, as a name-free summary. Never their name, and never anything you did not type into that contact yourself.',
    mayChange: 'Register and formality of the cleaned-up draft. Writing to a manager may come out less casual than writing to a sibling.',
    mustPreserve: 'Your words, their order, and their meaning. Audience context may change register, never content — it must not soften a refusal, drop a specific, or add a pleasantry you did not say.',
    defaultOn: false,
    inspect: {
      label: 'Review your contacts and what they store',
      section: 'privacy',
      target: 'contacts',
    },
    gate: {
      status: 'awaiting-ruling',
      text: 'Preservation check passed (PASS 3/3, retained Wave 0 baseline), but enabling this is a release gate decision that has not been made. The control is here so you can see what it would do; it cannot be switched on yet.',
      decision: 'D-0005',
    },
    userEnablable: false,
  },
];

/** The toggle descriptor for `key`, or null. */
export function disclosedToggleFor(key) {
  return DISCLOSED_TOGGLES.find((t) => t.key === key) || null;
}

/**
 * The disclosure a control must show, in render order.
 *
 * Returned as labelled rows rather than a paragraph so the markup cannot
 * quietly drop one: a missing "what it must preserve" line is exactly the
 * omission D-0005 exists to prevent, and a test can count these.
 */
export function disclosureRowsFor(toggle) {
  if (!toggle) return [];
  return [
    { field: 'dataUsed', label: 'Data it uses', text: toggle.dataUsed },
    { field: 'mayChange', label: 'What it may change', text: toggle.mayChange },
    { field: 'mustPreserve', label: 'What it must preserve', text: toggle.mustPreserve },
    { field: 'default', label: 'Default', text: toggle.defaultOn ? 'On' : 'Off' },
    { field: 'inspect', label: 'Inspect the data', text: toggle.inspect.label },
    { field: 'gate', label: 'Preservation gate', text: toggle.gate.text },
  ];
}

/**
 * Should this control be interactive?
 *
 * Split out from `userEnablable` because the answer is "no" for a second
 * reason too: a toggle already stored as ON stays readable but is not made
 * switchable by this function alone.
 */
export function toggleIsInteractive(toggle) {
  return Boolean(toggle && toggle.userEnablable);
}

/** What a control reports as its current state, given stored profile settings. */
export function toggleStateFrom(settings, toggle) {
  if (!toggle) return { checked: false, disabled: true };
  const stored = (settings || {})[toggle.key];
  // `undefined` means the profile has never stored it, which is the default.
  const checked = stored === undefined ? Boolean(toggle.defaultOn) : Boolean(stored);
  return { checked, disabled: !toggleIsInteractive(toggle) };
}

// --- Inventory -> section placement map (machine-readable, see file header) -

export const INVENTORY_PLACEMENT_MAP = {
  'profile.select': { section: 'profile', control: 'Active profile select', wired: true },
  'profile.newName': { section: 'profile', control: 'Profile name/target input', wired: true },
  'profile.activate': { section: 'profile', control: 'Activate button', wired: true },
  'profile.create': { section: 'profile', control: 'Create New button', wired: true },
  'profile.rename': { section: 'profile', control: 'Rename Profile button', wired: true, note: 'BUG #1 fix: real element binding' },
  'profile.duplicate': { section: 'profile', control: 'Duplicate Profile button', wired: true, note: 'BUG #1 fix: real element binding' },
  'profile.export': { section: 'profile', control: 'Export Profile button (Blob download)', wired: true, note: 'BUG #1 fix: real element binding' },
  'profile.import': { section: 'profile', control: 'Import Profile file input (legacy upgrade)', wired: true },
  'profile.delete': { section: 'profile', control: 'Delete Profile button (blocks Default)', wired: true },
  'profile.saveBar': { section: 'profile', control: 'Sticky Save/Discard bar + profileMessage', wired: true },
  'profile.validation': { section: 'profile', control: 'Live range validation + save-blocked-on-error', wired: true },

  'recording.mode': { section: 'recording', control: 'Recording mode select', wired: true },
  'recording.pttNote': { section: 'recording', control: 'PTT availability note', wired: true },
  'recording.autoStopSilence': { section: 'recording', control: 'Auto-stop on silence + ms + min-ms', wired: true },
  'recording.voiceCommands': { section: 'recording', control: 'Voice commands toggle', wired: true },
  'recording.noAudioGate': { section: 'recording', control: 'No-audio duration/RMS/peak gate', wired: true },

  'review.sendMode': { section: 'review', control: 'Send mode select', wired: true },
  'review.confidenceGate': { section: 'review', control: 'Confidence-gated review/auto-send thresholds', wired: true },
  'review.autoSubmit': { section: 'review', control: 'Auto submit toggle', wired: true },
  'review.instantTyping': { section: 'review', control: 'Instant typing toggle', wired: true },
  'review.restoreClipboard': { section: 'review', control: 'Restore clipboard after paste toggle', wired: true },
  'review.draftHistoryLimit': { section: 'review', control: 'Draft history limit (10-500)', wired: true, note: 'wiring fix: was declared but never collected/restored' },

  'aicleanup.currentPreset': { section: 'aicleanup', control: 'Active persona/preset select', wired: true },
  'aicleanup.maxCompletionTokens': { section: 'aicleanup', control: 'Max completion tokens (512-4096)', wired: true },
  'aicleanup.longDraftWarningWords': { section: 'aicleanup', control: 'Long draft warning words (300-10000)', wired: true },
  'aicleanup.llmChunkSize': { section: 'aicleanup', control: 'LLM chunk size (50-5000)', wired: true },
  'aicleanup.whisperChunkSize': { section: 'aicleanup', control: 'Whisper chunk size (50-5000)', wired: true },
  'aicleanup.stitchPass': { section: 'aicleanup', control: 'Long-recording stitch pass toggle', wired: true },
  'aicleanup.deliverySignals': { section: 'aicleanup', control: 'Use speech delivery signals (disclosed toggle, default off)', wired: true },
  'aicleanup.audienceContext': { section: 'aicleanup', control: 'Use selected contact/audience context (disclosed toggle, default off)', wired: false, note: 'D-0005: the control, its disclosure and its gate status are built and rendered, but enabling it is a release gate decision that has not been made. `use_audience_context` is deliberately excluded from SETTINGS_FIELD_KEYS so no save path can set it.' },

  'notifications.statusIndicator': { section: 'notifications', control: 'Status indicator overlay toggle', wired: true },
  'notifications.notificationOverlay': { section: 'notifications', control: 'Notification overlay toggle', wired: true },
  'notifications.previewOverlay': { section: 'notifications', control: 'Preview overlay toggle', wired: true },

  'appearance.themeGroup': { section: 'appearance', control: 'Theme/accent/density/font-size/high-contrast (client localStorage, applied live)', wired: true },
  'appearance.overlayGroup': { section: 'appearance', control: 'Floating Overlay size/placement/opacity/vibrancy/labelPos/alwaysOn', wired: true },

  'privacy.networkList': { section: 'privacy', control: 'Network touchpoints list', wired: true },
  'privacy.dataList': { section: 'privacy', control: 'On-device data locations list', wired: true },
  'privacy.wakeListenerStatus': { section: 'privacy', control: 'Wake-listener status note', wired: true },
  'privacy.wipe': { section: 'privacy', control: 'Wipe my data (+ delete cloned voices) with truthful postcondition summary', wired: true },
  // --- Wave 6 (Gate 6) ---
  'privacy.storeList': { section: 'privacy', control: 'Complete store inventory (path, size, sensitivity, which clear removes it)', wired: true, note: 'Generated from the backend data registry via fetchPrivacy().stores -- NOT a hand-written renderer list, which is how a store ends up shipped, wiped, and never mentioned on the screen that claims to describe them all' },
  'privacy.unmappedWarning': { section: 'privacy', control: 'Warning when a file on disk is not covered by any declared category', wired: true, note: 'fetchPrivacy().unmapped_files -- the lie-by-omission guard surfaced to the user rather than left in a test' },
  'privacy.personaLearningDisclosure': { section: 'privacy', control: 'Learned-example disclosure with per-persona counts', wired: true, note: 'fetchPrivacy().persona_learning. Counts and paths only, never example text' },
  'privacy.wipeMode': { section: 'privacy', control: 'Wipe mode selector with a live per-mode preview', wired: true, note: 'fetchPrivacy().wipe_modes -- the confirmation and the sweep read one source, closing the gap where the old dialog named three stores and deleted five' },
  'privacy.personaLearningClear': { section: 'privacy', control: 'Delete all learned examples', wired: true, note: 'DELETE /privacy/persona-learning through a TYPED IPC operation (not an allowlisted DELETE) because it erases the user\'s own sentences. Success wording comes from the independent re-read, never from the delete call' },
  'privacy.personaLearningVerify': { section: 'privacy', control: 'Verify learned examples are gone', wired: true, note: 'GET /privacy/persona-learning/verify -- read-only by construction, so a user re-checking can never trigger a second delete' },
  'privacy.export': { section: 'privacy', control: 'Export my data', wired: true, note: 'GET /privacy/export, generated from the registry\'s included_in_export flags. Stores that cannot be inlined (the transcription DB, recordings, voices) are reported with paths and counted in `skipped` rather than silently dropped' },
  'privacy.factoryReset': { section: 'privacy', control: 'Factory reset behind a typed confirmation phrase', wired: true, note: 'POST /privacy/factory-reset via a typed IPC channel taking the exact phrase as a STRING end to end -- never a boolean, since a stray `true` would erase an install. Failure names the stores and files still present rather than claiming a clean reset' },
  'privacy.factoryResetVerify': { section: 'privacy', control: 'Check what is left after a reset', wired: true, note: 'GET /privacy/factory-reset/verify -- a separate read-only route with no deletion path' },
};

// --- Pure helpers: appearance -----------------------------------------------

export const VALID_THEMES = ['system', 'dark', 'light'];
export const VALID_ACCENTS = ['teal', 'purple', 'blue', 'gold'];
export const VALID_DENSITIES = ['comfortable', 'compact'];
export const VALID_FONT_SIZES = ['small', 'medium', 'large', 'huge'];

/**
 * Clamp raw appearance prefs to known-valid enum values, same fallback
 * behavior as main.js's applyAppearance() (invalid/missing -> a documented
 * default, never an arbitrary/attacker-controlled class name).
 */
export function normalizeAppearancePrefs(raw) {
  const r = raw || {};
  const theme = VALID_THEMES.includes(r.theme) ? r.theme : 'system';
  const accent = VALID_ACCENTS.includes(r.accent) ? r.accent : 'teal';
  const density = VALID_DENSITIES.includes(r.density) ? r.density : 'comfortable';
  const fontSize = VALID_FONT_SIZES.includes(r.fontSize) ? r.fontSize : 'medium';
  const highContrast = r.highContrast === true || r.highContrast === 'true';
  return { theme, accent, density, fontSize, highContrast };
}

/**
 * Pure "prefs -> DOM class plan" mapping (the "appearance-class mapping"
 * pure helper the work packet calls out by name). The DOM-wiring layer
 * applies `bodyRemove`/`bodyAdd` to document.body's classList and
 * `htmlClass` to document.documentElement's className, exactly mirroring
 * main.js's applyAppearance() body/html class toggling.
 */
export function computeAppearanceClasses({ theme, accent, density, fontSize, highContrast, prefersDark } = {}) {
  const normalized = normalizeAppearancePrefs({ theme, accent, density, fontSize, highContrast });
  const resolvedThemeClass = normalized.theme === 'light'
    ? 'theme-light'
    : normalized.theme === 'dark'
      ? 'theme-dark'
      : (prefersDark ? 'theme-dark' : 'theme-light');
  const bodyAdd = [resolvedThemeClass, `accent-${normalized.accent}`, `density-${normalized.density}`];
  if (normalized.highContrast) bodyAdd.push('high-contrast');
  return {
    normalized,
    resolvedThemeClass,
    bodyRemove: ['theme-light', 'theme-dark', 'accent-teal', 'accent-purple', 'accent-blue', 'accent-gold', 'density-compact', 'density-comfortable', 'high-contrast'],
    bodyAdd,
    htmlClass: `font-${normalized.fontSize}`,
  };
}

/** Renders a 0..1 fraction as a rounded percent string, e.g. 0.5 -> "50%" (overlay opacity/vibrancy readouts). */
export function formatPercentFromFraction(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '0%';
  return `${Math.round(n * 100)}%`;
}

// --- Pure helpers: profile name validation (mirrors main.js's validateProfileName exactly) ---

export function validateProfileName(name) {
  const trimmed = (name || '').trim();
  if (!trimmed) {
    return 'Profile name cannot be empty.';
  }
  if (!/^[a-zA-Z0-9_-]+$/.test(trimmed)) {
    return 'Profile name can only contain letters, numbers, underscores, and hyphens.';
  }
  const lower = trimmed.toLowerCase();
  if (lower === 'default' || lower === 'import') {
    return `"${trimmed}" is a reserved profile name.`;
  }
  return null;
}

// --- Pure helpers: range validation -----------------------------------------

// Every field Settings owns that has a documented numeric range
// (CURRENT_UI_INVENTORY.md §7.0/§7.2/§7.4/§7.5/§13). Ranges/messages mirror
// main.js's runValidation() verbatim for the fields that already had
// validation there; draft_history_limit's rule is NEW (see file header
// "draft_history_limit FIX").
export const SETTINGS_VALIDATION_RULES = {
  max_completion_tokens: { min: 512, max: 4096, parse: 'int', message: 'Max completion tokens must be between 512 and 4096.' },
  long_draft_warning_words: { min: 300, max: 10000, parse: 'int', message: 'Long draft warning must be between 300 and 10000 words.' },
  llm_chunk_size: { min: 50, max: 5000, parse: 'int', message: 'LLM chunk size must be between 50 and 5000.' },
  whisper_chunk_size: { min: 50, max: 5000, parse: 'int', message: 'Whisper chunk size must be between 50 and 5000.' },
  confidence_force_review_below: { min: 0, max: 1, parse: 'float', message: 'Confidence thresholds must be between 0.0 and 1.0.' },
  confidence_auto_send_above: { min: 0, max: 1, parse: 'float', message: 'Confidence thresholds must be between 0.0 and 1.0.' },
  auto_stop_silence_ms: { min: 250, max: 5000, parse: 'int', message: 'Auto-stop silence must be between 250 and 5000 ms.' },
  auto_stop_min_recording_ms: { min: 0, max: 10000, parse: 'int', message: 'Auto-stop minimum recording must be between 0 and 10000 ms.' },
  no_audio_min_duration_sec: { min: 0, max: 30, parse: 'float', message: 'Min duration must be between 0.0 and 30.0s.' },
  no_audio_min_rms: { min: 0, max: 1, parse: 'float', message: 'Min RMS must be between 0.0 and 1.0.' },
  no_audio_min_peak: { min: 0, max: 1, parse: 'float', message: 'Min Peak must be between 0.0 and 1.0.' },
  draft_history_limit: { min: 10, max: 500, parse: 'int', message: 'Draft history limit must be between 10 and 500.' },
};

/** Validates one field's raw (string) value against SETTINGS_VALIDATION_RULES. Returns an error message, or null if valid/unruled. */
export function validateFieldValue(key, rawValue) {
  const rule = SETTINGS_VALIDATION_RULES[key];
  if (!rule) return null;
  const val = rule.parse === 'int' ? parseInt(rawValue, 10) : parseFloat(rawValue);
  if (Number.isNaN(val) || val < rule.min || val > rule.max) {
    return rule.message;
  }
  return null;
}

/**
 * Pure validation pass over a plain `{ key: rawValue }` map (only keys
 * present are checked — matches main.js's runValidation() only checking
 * elements that actually exist in the DOM). Returns `{ errors, hasErrors }`.
 */
export function runSettingsValidation(values) {
  const vals = values || {};
  const errors = {};
  for (const key of Object.keys(SETTINGS_VALIDATION_RULES)) {
    if (!(key in vals)) continue;
    const msg = validateFieldValue(key, vals[key]);
    if (msg) errors[key] = msg;
  }
  return { errors, hasErrors: Object.keys(errors).length > 0 };
}

// --- Pure helpers: profile field collect/restore round-trip ----------------

// Every backend profile field Settings owns (CURRENT_UI_INVENTORY.md §13,
// filtered to the groups the work packet assigns to Settings — hotkeys,
// audio device, wake word, TTS, dictionary/macros, and advanced/developer
// residency are Utilities'/Studio's, see the file-header placement map).
export const SETTINGS_FIELD_KEYS = [
  'recording_mode',
  'auto_stop_after_silence_enabled',
  'auto_stop_silence_ms',
  'auto_stop_min_recording_ms',
  'voice_commands_enabled',
  'no_audio_min_duration_sec',
  'no_audio_min_rms',
  'no_audio_min_peak',
  'send_mode',
  'confidence_force_review_enabled',
  'confidence_force_review_below',
  'confidence_auto_send_above',
  'auto_submit',
  'instant_typing',
  'restore_clipboard_after_paste',
  'draft_history_limit',
  'current_preset',
  'max_completion_tokens',
  'long_draft_warning_words',
  'llm_chunk_size',
  'whisper_chunk_size',
  'long_recording_stitch_pass_enabled',
  'status_indicator_enabled',
  'notification_overlay_enabled',
  'preview_overlay_enabled',
  // D-0005 disclosed toggle. `use_audience_context` is deliberately NOT here:
  // a key that is never collected cannot be turned on by any save path,
  // including a future one written by someone who did not read D-0005.
  'use_delivery_signals',
];

export const SETTINGS_FIELD_TYPES = {
  recording_mode: 'select',
  auto_stop_after_silence_enabled: 'checkbox',
  auto_stop_silence_ms: 'number',
  auto_stop_min_recording_ms: 'number',
  voice_commands_enabled: 'checkbox',
  no_audio_min_duration_sec: 'number',
  no_audio_min_rms: 'number',
  no_audio_min_peak: 'number',
  send_mode: 'select',
  confidence_force_review_enabled: 'checkbox',
  confidence_force_review_below: 'number',
  confidence_auto_send_above: 'number',
  auto_submit: 'checkbox',
  instant_typing: 'checkbox',
  restore_clipboard_after_paste: 'checkbox',
  draft_history_limit: 'number',
  current_preset: 'select',
  max_completion_tokens: 'number',
  long_draft_warning_words: 'number',
  llm_chunk_size: 'number',
  whisper_chunk_size: 'number',
  long_recording_stitch_pass_enabled: 'checkbox',
  status_indicator_enabled: 'checkbox',
  notification_overlay_enabled: 'checkbox',
  preview_overlay_enabled: 'checkbox',
  use_delivery_signals: 'checkbox',
};

// Checkbox fields that default ON when the profile hasn't stored them yet —
// mirrors main.js's renderProfileSettings() `defaultOnKeys` set, filtered to
// the fields Settings owns (macros_enabled is Utilities' and excluded here).
export const SETTINGS_DEFAULT_ON_KEYS = new Set(['voice_commands_enabled', 'confidence_force_review_enabled', 'restore_clipboard_after_paste']);

/**
 * Pure "DOM element states -> profile patch" collector. `fieldStates` is a
 * plain `{ key: { value, checked, disabled } }` map (the DOM-wiring layer
 * builds this by reading real elements; tests pass plain objects directly).
 * Mirrors main.js's collectProfileSettings() per-field coercion exactly.
 */
export function collectPatchFromFieldStates(fieldStates, fieldTypes = SETTINGS_FIELD_TYPES) {
  const states = fieldStates || {};
  const patch = {};
  for (const [key, type] of Object.entries(fieldTypes)) {
    const state = states[key];
    if (!state) continue;
    if (type === 'checkbox') {
      patch[key] = state.disabled ? false : Boolean(state.checked);
    } else if (type === 'number') {
      patch[key] = Number(state.value);
    } else {
      patch[key] = state.value;
    }
  }
  return patch;
}

/**
 * Pure "profile settings -> DOM element states" restorer, the inverse of
 * collectPatchFromFieldStates(). Returns `{ key: { checked } | { value } }`
 * describing what each element should show; the DOM-wiring layer applies
 * this to real elements. Mirrors main.js's renderProfileSettings() exactly,
 * including the default-ON checkbox fallback.
 */
export function restoreFieldStatesFromSettings(settings, fieldTypes = SETTINGS_FIELD_TYPES, defaultOnKeys = SETTINGS_DEFAULT_ON_KEYS) {
  const src = settings || {};
  const result = {};
  for (const [key, type] of Object.entries(fieldTypes)) {
    if (type === 'checkbox') {
      const stored = src[key];
      const value = stored === undefined && defaultOnKeys.has(key) ? true : Boolean(stored);
      result[key] = { checked: value };
    } else {
      result[key] = { value: src[key] ?? '' };
    }
  }
  return result;
}

/** Trivial named helper (readability + a stable unit-test surface) for the same spread main.js's collectProfileSettings() uses: `{ ...base, ...patch }`. */
export function mergeProfilePatch(baseSettings, patch) {
  return { ...(baseSettings || {}), ...(patch || {}) };
}

// --- Pure helper: legacy profile import upgrade (mirrors main.js's inline upgrade exactly) ---

export function buildLegacyProfileImportPayload(parsed, fallbackName) {
  if (parsed && parsed.kind === 'betterfingers_profile') {
    return parsed;
  }
  const settings = (parsed && parsed.settings) || parsed || {};
  const name = (parsed && parsed.name) || fallbackName;
  return { kind: 'betterfingers_profile', schema_version: 1, name, settings };
}

// --- Pure helper: search matching ------------------------------------------

/**
 * True if `text` matches `query` (case-insensitive substring; an empty
 * query always matches). Mirrors main.js's filterSettings() row-match test
 * (`text.includes(q) || inputs.includes(q)`), applied here to a single
 * pre-joined haystack string the DOM-wiring layer builds per row (label +
 * description + input id/placeholder).
 */
export function rowMatchesQuery(text, query) {
  const q = (query || '').trim().toLowerCase();
  if (!q) return true;
  return (text || '').toLowerCase().includes(q);
}

// --- Element ids --------------------------------------------------------

export const SETTINGS_ELEMENT_IDS = {
  // --- chrome: search + sub-nav + save bar ---
  searchInput: 'sdSetSearchInput',
  searchHeader: 'sdSetSearchHeader',
  emptyState: 'sdSetEmptyState',
  saveBar: 'sdSetSaveBar',
  discardButton: 'sdSetDiscardButton',
  saveButton: 'sdSetSaveButton',
  profileMessage: 'sdSetProfileMessage',

  navProfile: 'sdSetNavProfile',
  navRecording: 'sdSetNavRecording',
  navReview: 'sdSetNavReview',
  navAiCleanup: 'sdSetNavAiCleanup',
  navNotifications: 'sdSetNavNotifications',
  navAppearance: 'sdSetNavAppearance',
  navPrivacy: 'sdSetNavPrivacy',

  sectionProfile: 'sdSetSectionProfile',
  sectionRecording: 'sdSetSectionRecording',
  sectionReview: 'sdSetSectionReview',
  sectionAiCleanup: 'sdSetSectionAiCleanup',
  sectionNotifications: 'sdSetSectionNotifications',
  sectionAppearance: 'sdSetSectionAppearance',
  sectionPrivacy: 'sdSetSectionPrivacy',

  // --- Profile management (§7.1) ---
  profileSelect: 'sdSetProfileSelect',
  newProfileName: 'sdSetNewProfileName',
  activateButton: 'sdSetActivateProfileButton',
  createButton: 'sdSetCreateProfileButton',
  renameButton: 'sdSetRenameProfileButton',
  duplicateButton: 'sdSetDuplicateProfileButton',
  exportButton: 'sdSetExportProfileButton',
  importFile: 'sdSetImportProfileFile',
  deleteButton: 'sdSetDeleteProfileButton',

  // --- Recording-only informational note ---
  pttAvailabilityNote: 'sdSetPttAvailabilityNote',

  // --- Privacy (§7.14) ---
  privacyNetworkList: 'sdSetPrivacyNetworkList',
  privacyDataList: 'sdSetPrivacyDataList',
  privacyWakeListenerStatus: 'sdSetPrivacyWakeListenerStatus',
  privacyWipeVoices: 'sdSetPrivacyWipeVoices',
  privacyWipeButton: 'sdSetPrivacyWipeButton',
  privacyMessage: 'sdSetPrivacyMessage',
  // --- Wave 6: registry-driven inventory, disclosure, modes, factory reset ---
  privacyStoreList: 'sdSetPrivacyStoreList',
  privacyUnmappedWarning: 'sdSetPrivacyUnmappedWarning',
  privacyPersonaLearningWhat: 'sdSetPrivacyPersonaLearningWhat',
  privacyPersonaLearningCounts: 'sdSetPrivacyPersonaLearningCounts',
  privacyPersonaLearningList: 'sdSetPrivacyPersonaLearningList',
  privacyPersonaLearningClearButton: 'sdSetPrivacyPersonaLearningClear',
  privacyPersonaLearningVerifyButton: 'sdSetPrivacyPersonaLearningVerify',
  privacyPersonaLearningMessage: 'sdSetPrivacyPersonaLearningMessage',
  privacyExportButton: 'sdSetPrivacyExportButton',
  privacyWipeMode: 'sdSetPrivacyWipeMode',
  privacyWipePreview: 'sdSetPrivacyWipePreview',
  privacyFactoryResetPreview: 'sdSetPrivacyFactoryResetPreview',
  privacyFactoryResetModels: 'sdSetPrivacyFactoryResetModels',
  privacyFactoryResetConfirm: 'sdSetPrivacyFactoryResetConfirm',
  privacyFactoryResetButton: 'sdSetPrivacyFactoryResetButton',
  privacyFactoryResetVerifyButton: 'sdSetPrivacyFactoryResetVerify',
  privacyFactoryResetMessage: 'sdSetPrivacyFactoryResetMessage',

  // --- Appearance (§7.11) ---
  theme: 'sdSetTheme',
  accentColor: 'sdSetAccentColor',
  density: 'sdSetDensity',
  fontSize: 'sdSetFontSize',
  highContrast: 'sdSetHighContrast',
  overlayGroup: 'sdSetOverlayAppearanceGroup',
  overlaySize: 'sdSetOverlaySize',
  overlayPlacement: 'sdSetOverlayPlacement',
  overlayOpacity: 'sdSetOverlayOpacity',
  overlayOpacityValue: 'sdSetOverlayOpacityValue',
  overlayVibrancy: 'sdSetOverlayVibrancy',
  overlayVibrancyValue: 'sdSetOverlayVibrancyValue',
  overlayLabelPos: 'sdSetOverlayLabelPos',
  overlayAlwaysOn: 'sdSetOverlayAlwaysOn',

  // --- Profile fields (SETTINGS_FIELD_KEYS -> element id) ---
  fields: {
    recording_mode: 'sdSetRecordingMode',
    auto_stop_after_silence_enabled: 'sdSetAutoStopSilence',
    auto_stop_silence_ms: 'sdSetAutoStopSilenceMs',
    auto_stop_min_recording_ms: 'sdSetAutoStopMinMs',
    voice_commands_enabled: 'sdSetVoiceCommands',
    no_audio_min_duration_sec: 'sdSetNoAudioDuration',
    no_audio_min_rms: 'sdSetNoAudioRms',
    no_audio_min_peak: 'sdSetNoAudioPeak',
    send_mode: 'sdSetSendMode',
    confidence_force_review_enabled: 'sdSetConfidenceForceReview',
    confidence_force_review_below: 'sdSetConfidenceForceReviewBelow',
    confidence_auto_send_above: 'sdSetConfidenceAutoSendAbove',
    auto_submit: 'sdSetAutoSubmit',
    instant_typing: 'sdSetInstantTyping',
    restore_clipboard_after_paste: 'sdSetRestoreClipboard',
    draft_history_limit: 'sdSetDraftHistoryLimit',
    current_preset: 'sdSetCurrentPreset',
    max_completion_tokens: 'sdSetMaxCompletionTokens',
    long_draft_warning_words: 'sdSetLongDraftWarningWords',
    llm_chunk_size: 'sdSetLlmChunkSize',
    whisper_chunk_size: 'sdSetWhisperChunkSize',
    long_recording_stitch_pass_enabled: 'sdSetStitchPass',
    status_indicator_enabled: 'sdSetStatusIndicator',
    notification_overlay_enabled: 'sdSetNotificationOverlay',
    preview_overlay_enabled: 'sdSetPreviewOverlay',
    use_delivery_signals: 'sdSetUseDeliverySignals',
  },

  // --- D-0005 disclosed toggles -------------------------------------------
  //
  // The audience input is listed here rather than under `fields` on purpose:
  // it must be rendered and read, never collected into a profile patch.
  disclosedToggles: {
    use_delivery_signals: {
      input: 'sdSetUseDeliverySignals',
      dataUsed: 'sdSetDeliverySignalsDataUsed',
      mayChange: 'sdSetDeliverySignalsMayChange',
      mustPreserve: 'sdSetDeliverySignalsMustPreserve',
      default: 'sdSetDeliverySignalsDefault',
      inspect: 'sdSetDeliverySignalsInspect',
      gate: 'sdSetDeliverySignalsGate',
    },
    use_audience_context: {
      input: 'sdSetUseAudienceContext',
      dataUsed: 'sdSetAudienceContextDataUsed',
      mayChange: 'sdSetAudienceContextMayChange',
      mustPreserve: 'sdSetAudienceContextMustPreserve',
      default: 'sdSetAudienceContextDefault',
      inspect: 'sdSetAudienceContextInspect',
      gate: 'sdSetAudienceContextGate',
    },
  },

  // --- Per-field validation error spans (only the fields with a rule) ---
  fieldErrors: {
    max_completion_tokens: 'sdSetMaxCompletionTokensError',
    long_draft_warning_words: 'sdSetLongDraftWarningWordsError',
    llm_chunk_size: 'sdSetLlmChunkSizeError',
    whisper_chunk_size: 'sdSetWhisperChunkSizeError',
    confidence_force_review_below: 'sdSetConfidenceForceReviewBelowError',
    confidence_auto_send_above: 'sdSetConfidenceAutoSendAboveError',
    auto_stop_silence_ms: 'sdSetAutoStopSilenceMsError',
    auto_stop_min_recording_ms: 'sdSetAutoStopMinMsError',
    no_audio_min_duration_sec: 'sdSetNoAudioDurationError',
    no_audio_min_rms: 'sdSetNoAudioRmsError',
    no_audio_min_peak: 'sdSetNoAudioPeakError',
    draft_history_limit: 'sdSetDraftHistoryLimitError',
  },
};

/** Looks up every SETTINGS_ELEMENT_IDS entry (including the nested fields/fieldErrors maps) by id from `root`. Missing ids resolve to null, never throw -- same contract as collectUtilitiesElements()/collectStudioElements(). */
export function collectSettingsElements(root) {
  const doc = root || (typeof document !== 'undefined' ? document : null);
  const byId = (id) => (doc && typeof doc.getElementById === 'function' ? doc.getElementById(id) || null : null);
  const els = {};
  for (const [key, value] of Object.entries(SETTINGS_ELEMENT_IDS)) {
    if (key === 'fields' || key === 'fieldErrors' || key === 'disclosedToggles') continue;
    els[key] = byId(value);
  }
  els.disclosedToggles = {};
  for (const [toggleKey, ids] of Object.entries(SETTINGS_ELEMENT_IDS.disclosedToggles)) {
    const group = {};
    for (const [slot, id] of Object.entries(ids)) group[slot] = byId(id);
    els.disclosedToggles[toggleKey] = group;
  }
  els.fields = {};
  for (const [fieldKey, id] of Object.entries(SETTINGS_ELEMENT_IDS.fields)) {
    els.fields[fieldKey] = byId(id);
  }
  els.fieldErrors = {};
  for (const [fieldKey, id] of Object.entries(SETTINGS_ELEMENT_IDS.fieldErrors)) {
    els.fieldErrors[fieldKey] = byId(id);
  }
  return els;
}

// --- DOM-wiring feature ------------------------------------------------------

/**
 * @param {object} deps
 * @param {object} deps.elements Settings workspace DOM refs -- see
 *   SETTINGS_ELEMENT_IDS (use collectSettingsElements() for the common case).
 * @param {object} deps.hooks See the file-header contract above.
 */
export function createSettingsWorkspaceFeature({ elements, hooks } = {}) {
  const els = elements || {};
  const fieldEls = els.fields || {};
  const fieldErrorEls = els.fieldErrors || {};
  const hks = hooks || {};
  const confirmFn = hks.confirmFn || (typeof window !== 'undefined' && window.confirm ? window.confirm.bind(window) : () => true);
  // The most recent fetchPrivacy() payload (Wave 6), so the wipe confirmation
  // and the on-screen preview describe the same stores.
  let lastPrivacyReport = null;
  const overlayBridge = hks.overlayBridge || (typeof window !== 'undefined' ? window.betterFingers : undefined);

  let sectionState = { active: SETTINGS_SECTIONS[0] };
  let activeProfileName = null;
  let activeProfileSettings = {};
  let validationErrors = {};
  let profileDirty = false;

  function setMessage(el, text = '', tone = '') {
    if (!el) return;
    el.textContent = text;
    if (tone) el.dataset.tone = tone;
    else delete el.dataset.tone;
  }

  // --- section sub-nav --------------------------------------------------

  const NAV_EL_BY_SECTION = { profile: 'navProfile', recording: 'navRecording', review: 'navReview', aicleanup: 'navAiCleanup', notifications: 'navNotifications', appearance: 'navAppearance', privacy: 'navPrivacy' };
  const SECTION_EL_BY_SECTION = { profile: 'sectionProfile', recording: 'sectionRecording', review: 'sectionReview', aicleanup: 'sectionAiCleanup', notifications: 'sectionNotifications', appearance: 'sectionAppearance', privacy: 'sectionPrivacy' };

  function renderSectionNav() {
    SETTINGS_SECTIONS.forEach((id) => {
      const btn = els[NAV_EL_BY_SECTION[id]];
      if (btn) {
        const isActive = id === sectionState.active;
        btn.classList?.toggle('is-active', isActive);
        btn.setAttribute?.('aria-current', isActive ? 'page' : 'false');
      }
      const section = els[SECTION_EL_BY_SECTION[id]];
      if (section) section.hidden = id !== sectionState.active;
    });
  }

  function goToSection(id) {
    sectionState = computeNextSettingsSection(sectionState, id);
    renderSectionNav();
    return { ...sectionState };
  }

  function getSectionState() {
    return { ...sectionState };
  }

  function bindSectionNav() {
    SETTINGS_SECTIONS.forEach((id) => {
      els[NAV_EL_BY_SECTION[id]]?.addEventListener?.('click', () => goToSection(id));
    });
  }

  // --- profile select / persona options population -----------------------

  function fillSelect(selectEl, options, selectedValue, labelFor = (item) => item) {
    if (!selectEl) return;
    selectEl.innerHTML = '';
    for (const item of options || []) {
      const value = typeof item === 'string' ? item : item.value;
      const option = document.createElement('option');
      option.value = value;
      option.textContent = labelFor(item);
      option.selected = value === selectedValue;
      selectEl.appendChild(option);
    }
  }

  /** Populates the Active Profile dropdown. Exposed for the preview page's mock seeding and for real refreshAll(). */
  function setProfilesList(names, activeName) {
    fillSelect(els.profileSelect, names, activeName);
    if (activeName) activeProfileName = activeName;
  }

  /** Populates the current_preset dropdown's option list. Exposed for preview mocking (see SPEC GAP 2). */
  function setPersonaOptions(names, selected) {
    const el = fieldEls.current_preset;
    if (!el) return;
    const keep = selected ?? el.value;
    fillSelect(el, names, keep);
  }

  // --- collect / restore: field DOM <-> profile settings ------------------

  function readFieldStates() {
    const states = {};
    for (const [key, type] of Object.entries(SETTINGS_FIELD_TYPES)) {
      const el = fieldEls[key];
      if (!el) continue;
      states[key] = type === 'checkbox'
        ? { checked: Boolean(el.checked), disabled: Boolean(el.disabled) }
        : { value: el.value };
    }
    return states;
  }

  function applyFieldStates(states) {
    for (const [key, type] of Object.entries(SETTINGS_FIELD_TYPES)) {
      const el = fieldEls[key];
      const state = states[key];
      if (!el || !state) continue;
      if (type === 'checkbox') {
        el.checked = el.disabled ? false : Boolean(state.checked);
      } else {
        el.value = state.value ?? '';
      }
    }
  }

  /**
   * Paint the D-0005 disclosure blocks.
   *
   * Every row is written from the descriptor, never from markup, so the six
   * required pieces cannot drift apart from what the toggle actually does --
   * and a control whose gate is unresolved is disabled here rather than
   * relying on a `disabled` attribute someone remembered to type.
   */
  function renderDisclosedToggles(settings) {
    for (const toggle of DISCLOSED_TOGGLES) {
      const group = (els.disclosedToggles || {})[toggle.key];
      if (!group) continue;

      const state = toggleStateFrom(settings, toggle);
      if (group.input) {
        group.input.checked = state.checked;
        group.input.disabled = state.disabled;
        // Announced, not just greyed: a screen reader user must learn the
        // control is unavailable and why, same as a sighted one.
        group.input.setAttribute?.('aria-disabled', state.disabled ? 'true' : 'false');
        if (state.disabled) {
          group.input.title = toggle.gate.text;
        }
      }

      for (const row of disclosureRowsFor(toggle)) {
        const el = group[row.field];
        if (el) el.textContent = row.text;
      }
    }
  }

  /** Restores a full profile `settings` object into the DOM (the "restore" half of the collect/restore cycle) and clears dirty/validation state. */
  function renderSettings(settings) {
    activeProfileSettings = { ...(settings || {}) };
    profileDirty = false;
    validationErrors = {};
    applyFieldStates(restoreFieldStatesFromSettings(activeProfileSettings));
    renderDisclosedToggles(activeProfileSettings);
    for (const key of Object.keys(fieldErrorEls)) clearFieldError(key);
    hideSaveBar();
    return activeProfileSettings;
  }

  /** Reads the DOM and returns the full merged profile patch ready to POST (mirrors main.js's collectProfileSettings()). */
  function collectSettings() {
    const patch = collectPatchFromFieldStates(readFieldStates());
    return mergeProfilePatch(activeProfileSettings, patch);
  }

  // --- dirty tracking + validation -----------------------------------------

  function showSaveBar() {
    els.saveBar?.classList?.remove('hidden');
    els.saveBar?.classList?.add('visible');
  }

  function hideSaveBar() {
    els.saveBar?.classList?.remove('visible');
    els.saveBar?.classList?.add('hidden');
  }

  function markDirty() {
    profileDirty = true;
    setMessage(els.profileMessage, 'Unsaved profile changes.', 'warning');
    showSaveBar();
  }

  function updateSaveButtonState() {
    const hasErrors = Object.keys(validationErrors).length > 0;
    if (els.saveButton) {
      els.saveButton.disabled = hasErrors;
      els.saveButton.title = hasErrors ? 'Please fix validation errors before saving.' : '';
    }
  }

  function setFieldError(key, message) {
    validationErrors = { ...validationErrors, [key]: message };
    fieldEls[key]?.classList?.add('input-error');
    const errEl = fieldErrorEls[key];
    if (errEl) errEl.textContent = message;
    updateSaveButtonState();
  }

  function clearFieldError(key) {
    if (key in validationErrors) {
      const next = { ...validationErrors };
      delete next[key];
      validationErrors = next;
    }
    fieldEls[key]?.classList?.remove('input-error');
    const errEl = fieldErrorEls[key];
    if (errEl) errEl.textContent = '';
    updateSaveButtonState();
  }

  function runValidation() {
    const values = {};
    for (const key of Object.keys(SETTINGS_VALIDATION_RULES)) {
      const el = fieldEls[key];
      if (el) values[key] = el.value;
    }
    const { errors } = runSettingsValidation(values);
    for (const key of Object.keys(SETTINGS_VALIDATION_RULES)) {
      if (errors[key]) setFieldError(key, errors[key]);
      else clearFieldError(key);
    }
    return errors;
  }

  function bindFieldDirtyTracking() {
    for (const el of Object.values(fieldEls)) {
      if (!el) continue;
      el.addEventListener('input', () => {
        markDirty();
        runValidation();
      });
      el.addEventListener('change', () => {
        markDirty();
        runValidation();
      });
    }
  }

  // --- profile operations ---------------------------------------------------

  async function refreshProfilesList() {
    const payload = await fetchProfiles();
    setProfilesList(payload.profiles ?? [], payload.active_profile);
    renderSettings(payload.settings ?? {});
    setMessage(els.profileMessage, `Active profile: ${payload.active_profile}`, 'success');
    return payload;
  }

  async function refreshPersonaOptions() {
    try {
      const personas = await fetchPersonas();
      setPersonaOptions(Object.keys(personas || {}), fieldEls.current_preset?.value);
    } catch (_e) {
      // Non-fatal -- current_preset simply keeps whatever options it had.
    }
  }

  function handleProfileSelectChange() {
    const name = els.profileSelect?.value;
    if (!name) return;
    fetchProfile(name)
      .then((payload) => renderSettings(payload.settings ?? {}))
      .catch((error) => setMessage(els.profileMessage, `Load failed: ${error.message}`, 'danger'));
  }

  async function handleActivate() {
    const name = els.profileSelect?.value;
    if (!name) return;
    try {
      const payload = await activateProfile(name);
      setProfilesList(payload.profiles ?? [], payload.active_profile);
      renderSettings(payload.settings ?? {});
      setMessage(els.profileMessage, `Activated ${payload.active_profile}.`, 'success');
      hks.onProfileChanged?.(payload);
    } catch (error) {
      setMessage(els.profileMessage, `Activate failed: ${error.message}`, 'danger');
    }
  }

  async function handleCreate() {
    const name = els.newProfileName?.value?.trim();
    const nameError = validateProfileName(name);
    if (nameError) {
      setMessage(els.profileMessage, nameError, 'danger');
      return;
    }
    if (Object.keys(validationErrors).length > 0) {
      setMessage(els.profileMessage, 'Cannot create profile: please fix validation errors first.', 'danger');
      return;
    }
    try {
      const payload = await createProfile(name, collectSettings());
      setProfilesList(payload.profiles ?? [], payload.profile);
      renderSettings(payload.settings ?? {});
      setMessage(els.profileMessage, `Created ${payload.profile}. Activate it when ready.`, 'success');
      if (els.newProfileName) els.newProfileName.value = '';
      hks.onProfileChanged?.(payload);
    } catch (error) {
      setMessage(els.profileMessage, `Create failed: ${error.message}`, 'danger');
    }
  }

  async function handleRename() {
    const oldName = els.profileSelect?.value;
    const newName = els.newProfileName?.value?.trim();
    if (!oldName) {
      setMessage(els.profileMessage, 'Select a profile first.', 'warning');
      return;
    }
    if (oldName === 'Default') {
      setMessage(els.profileMessage, 'Default profile cannot be renamed.', 'warning');
      return;
    }
    const nameError = validateProfileName(newName);
    if (nameError) {
      setMessage(els.profileMessage, nameError, 'danger');
      return;
    }
    try {
      const payload = await renameProfile(oldName, newName);
      setProfilesList(payload.profiles ?? [], payload.active_profile);
      renderSettings(payload.settings ?? {});
      setMessage(els.profileMessage, `Renamed profile to ${payload.active_profile}.`, 'success');
      if (els.newProfileName) els.newProfileName.value = '';
      hks.onProfileChanged?.(payload);
    } catch (error) {
      setMessage(els.profileMessage, `Rename failed: ${error.message}`, 'danger');
    }
  }

  async function handleDuplicate() {
    const oldName = els.profileSelect?.value;
    const newName = els.newProfileName?.value?.trim();
    if (!oldName) {
      setMessage(els.profileMessage, 'Select a profile first.', 'warning');
      return;
    }
    const nameError = validateProfileName(newName);
    if (nameError) {
      setMessage(els.profileMessage, nameError, 'danger');
      return;
    }
    try {
      const payload = await duplicateProfile(oldName, newName);
      setProfilesList(payload.profiles ?? [], payload.active_profile);
      renderSettings(payload.settings ?? {});
      setMessage(els.profileMessage, `Duplicated profile as ${payload.active_profile}.`, 'success');
      if (els.newProfileName) els.newProfileName.value = '';
      hks.onProfileChanged?.(payload);
    } catch (error) {
      setMessage(els.profileMessage, `Duplicate failed: ${error.message}`, 'danger');
    }
  }

  async function handleExport() {
    const name = els.profileSelect?.value;
    if (!name) return;
    try {
      const data = await exportProfile(name);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${name}_profile.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      setMessage(els.profileMessage, `Exported profile ${name} successfully.`, 'success');
    } catch (error) {
      setMessage(els.profileMessage, `Export failed: ${error.message}`, 'danger');
    }
  }

  function handleImportFileChange(event) {
    const file = event?.target?.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async (loadEvent) => {
      try {
        const raw = JSON.parse(loadEvent.target.result);
        const fallbackName = file.name.replace('_profile.json', '').replace('.json', '');
        const parsed = buildLegacyProfileImportPayload(raw, fallbackName);
        if (parsed.schema_version !== 1) {
          throw new Error(`Unsupported profile schema version: ${parsed.schema_version}`);
        }
        const nameError = validateProfileName(parsed.name);
        if (nameError) {
          throw new Error(`Invalid imported profile name: ${nameError}`);
        }
        const payload = await importProfile(parsed);
        setProfilesList(payload.profiles ?? [], payload.active_profile);
        renderSettings(payload.settings ?? {});
        setMessage(els.profileMessage, `Imported profile ${payload.active_profile} successfully.`, 'success');
        hks.onProfileChanged?.(payload);
      } catch (error) {
        setMessage(els.profileMessage, `Import failed: ${error.message}`, 'danger');
      } finally {
        if (els.importFile) els.importFile.value = '';
      }
    };
    reader.readAsText(file);
  }

  async function handleDelete() {
    const name = els.profileSelect?.value;
    if (!name || name === 'Default') {
      setMessage(els.profileMessage, 'Default profile cannot be deleted.', 'warning');
      return;
    }
    try {
      const payload = await deleteProfile(name);
      setProfilesList(payload.profiles ?? [], payload.active_profile);
      renderSettings(payload.settings ?? {});
      setMessage(els.profileMessage, `Deleted ${name}.`, 'success');
      hks.onProfileChanged?.(payload);
    } catch (error) {
      setMessage(els.profileMessage, `Delete failed: ${error.message}`, 'danger');
    }
  }

  async function handleSave() {
    const name = els.profileSelect?.value;
    if (!name) return;
    const errors = runValidation();
    if (Object.keys(errors).length > 0) {
      setMessage(els.profileMessage, 'Cannot save settings: please fix validation errors first.', 'danger');
      return;
    }
    try {
      const payload = await saveProfile(name, collectSettings());
      renderSettings(payload.settings ?? {});
      setMessage(els.profileMessage, `Saved ${payload.profile}.`, 'success');
      hks.onProfileSaved?.(payload);
    } catch (error) {
      setMessage(els.profileMessage, `Save failed: ${error.message}`, 'danger');
    }
  }

  async function handleDiscard() {
    const name = els.profileSelect?.value;
    if (!name) return;
    try {
      const payload = await fetchProfile(name);
      renderSettings(payload.settings ?? {});
      setMessage(els.profileMessage, `Discarded changes for ${payload.profile}.`, 'success');
    } catch (error) {
      setMessage(els.profileMessage, `Discard failed: ${error.message}`, 'danger');
    }
  }

  function bindProfileButtons() {
    els.profileSelect?.addEventListener?.('change', handleProfileSelectChange);
    els.activateButton?.addEventListener?.('click', () => handleActivate());
    els.createButton?.addEventListener?.('click', () => handleCreate());
    els.renameButton?.addEventListener?.('click', () => handleRename());
    els.duplicateButton?.addEventListener?.('click', () => handleDuplicate());
    els.exportButton?.addEventListener?.('click', () => handleExport());
    els.importFile?.addEventListener?.('change', handleImportFileChange);
    els.deleteButton?.addEventListener?.('click', () => handleDelete());
    els.saveButton?.addEventListener?.('click', () => handleSave());
    els.discardButton?.addEventListener?.('click', () => handleDiscard());
  }

  // --- appearance (client localStorage, applied live) -----------------------

  function readAppearancePrefsFromStorage() {
    if (typeof localStorage === 'undefined') return {};
    return {
      theme: localStorage.getItem('pref_theme'),
      accent: localStorage.getItem('pref_accent'),
      density: localStorage.getItem('pref_density'),
      fontSize: localStorage.getItem('pref_font_size'),
      highContrast: localStorage.getItem('pref_high_contrast') === 'true',
    };
  }

  function applyAppearance() {
    const prefersDark = typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia('(prefers-color-scheme: dark)').matches
      : false;
    const plan = computeAppearanceClasses({ ...readAppearancePrefsFromStorage(), prefersDark });
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem('pref_theme', plan.normalized.theme);
      localStorage.setItem('pref_accent', plan.normalized.accent);
      localStorage.setItem('pref_density', plan.normalized.density);
      localStorage.setItem('pref_font_size', plan.normalized.fontSize);
    }
    if (typeof document !== 'undefined') {
      plan.bodyRemove.forEach((c) => document.body?.classList?.remove(c));
      plan.bodyAdd.forEach((c) => document.body?.classList?.add(c));
      if (document.documentElement) document.documentElement.className = plan.htmlClass;
    }
    if (els.theme) els.theme.value = plan.normalized.theme;
    if (els.accentColor) els.accentColor.value = plan.normalized.accent;
    if (els.density) els.density.value = plan.normalized.density;
    if (els.fontSize) els.fontSize.value = plan.normalized.fontSize;
    if (els.highContrast) els.highContrast.checked = plan.normalized.highContrast;
    return plan;
  }

  function bindAppearanceControls() {
    const persistAndReapply = (key, value) => {
      if (typeof localStorage !== 'undefined') localStorage.setItem(key, value);
      applyAppearance();
    };
    els.theme?.addEventListener?.('change', () => persistAndReapply('pref_theme', els.theme.value));
    els.accentColor?.addEventListener?.('change', () => persistAndReapply('pref_accent', els.accentColor.value));
    els.density?.addEventListener?.('change', () => persistAndReapply('pref_density', els.density.value));
    els.fontSize?.addEventListener?.('change', () => persistAndReapply('pref_font_size', els.fontSize.value));
    els.highContrast?.addEventListener?.('change', () => persistAndReapply('pref_high_contrast', els.highContrast.checked === true ? 'true' : 'false'));
    if (typeof window !== 'undefined' && window.matchMedia) {
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', () => {
        if ((localStorage.getItem('pref_theme') || 'system') === 'system') applyAppearance();
      });
    }
  }

  // --- Floating Overlay appearance (Electron-main-owned, no backend round-trip) ---

  function bindOverlayAppearanceControls() {
    if (!overlayBridge?.getOverlayAppearance || !overlayBridge?.setOverlayAppearance) {
      if (els.overlayGroup) els.overlayGroup.style.display = 'none';
      return;
    }
    const { overlaySize: sizeEl, overlayPlacement: placeEl, overlayOpacity: opacityEl, overlayOpacityValue: opacityValEl,
      overlayVibrancy: vibEl, overlayVibrancyValue: vibValEl, overlayLabelPos: labelPosEl, overlayAlwaysOn: alwaysOnEl } = els;
    if (!sizeEl || !placeEl || !opacityEl || !vibEl || !labelPosEl || !alwaysOnEl) return;

    overlayBridge.getOverlayAppearance().then((a) => {
      if (!a) return;
      sizeEl.value = a.size ?? 'medium';
      placeEl.value = a.placement ?? 'bottom-right';
      opacityEl.value = String(a.opacity ?? 1);
      if (opacityValEl) opacityValEl.textContent = formatPercentFromFraction(a.opacity ?? 1);
      vibEl.value = String(a.vibrancy ?? 1);
      if (vibValEl) vibValEl.textContent = formatPercentFromFraction(a.vibrancy ?? 1);
      labelPosEl.value = a.labelPos ?? 'hidden';
      alwaysOnEl.checked = Boolean(a.alwaysOn);
    }).catch(() => {});

    const push = (patch) => { overlayBridge.setOverlayAppearance(patch).catch(() => {}); };
    sizeEl.addEventListener('change', () => push({ size: sizeEl.value }));
    placeEl.addEventListener('change', () => push({ placement: placeEl.value }));
    opacityEl.addEventListener('input', () => { if (opacityValEl) opacityValEl.textContent = formatPercentFromFraction(opacityEl.value); });
    opacityEl.addEventListener('change', () => push({ opacity: Number(opacityEl.value) }));
    vibEl.addEventListener('input', () => { if (vibValEl) vibValEl.textContent = formatPercentFromFraction(vibEl.value); });
    vibEl.addEventListener('change', () => push({ vibrancy: Number(vibEl.value) }));
    labelPosEl.addEventListener('change', () => push({ labelPos: labelPosEl.value }));
    alwaysOnEl.addEventListener('change', () => push({ alwaysOn: alwaysOnEl.checked }));
  }

  // --- Privacy (§7.14) -------------------------------------------------------

  function appendDetailRow(container, keyText, valueText) {
    const row = document.createElement('div');
    row.className = 'sd-set-detail-row';
    const key = document.createElement('span');
    key.className = 'sd-set-detail-key';
    key.textContent = keyText;
    const value = document.createElement('span');
    value.className = 'sd-set-detail-value';
    value.textContent = valueText;
    row.appendChild(key);
    row.appendChild(value);
    container.appendChild(row);
  }

  function formatBytesShort(n) {
    const num = Number(n) || 0;
    if (num < 1024) return `${num} B`;
    if (num < 1024 * 1024) return `${(num / 1024).toFixed(1)} KB`;
    return `${(num / (1024 * 1024)).toFixed(1)} MB`;
  }

  /** Renders a fetchPrivacy()-shaped report into the network/data lists + wake-listener note. Exposed for real refreshAll() and preview mocking. */
  function renderPrivacyReport(report) {
    const r = report || {};
    // Held so the wipe confirmation can name the same stores the preview list
    // is showing, from the same fetch. Re-fetching at confirm time would open
    // a window where the dialog and the visible list disagree.
    lastPrivacyReport = r;
    if (els.privacyNetworkList) {
      els.privacyNetworkList.innerHTML = '';
      const touchpoints = r.network_touchpoints || [];
      if (!touchpoints.length) {
        els.privacyNetworkList.innerHTML = '<span class="empty-state">No network activity.</span>';
      } else {
        for (const t of touchpoints) {
          const tag = t.direction === 'outbound' ? 'outbound' : 'on-device';
          const hosts = (t.hosts || []).length ? ` (${t.hosts.join(', ')})` : '';
          appendDetailRow(els.privacyNetworkList, `${t.name} — ${tag}${hosts}`, t.purpose || '');
        }
      }
    }
    if (els.privacyDataList) {
      els.privacyDataList.innerHTML = '';
      const locations = r.data_locations || [];
      for (const d of locations) {
        appendDetailRow(els.privacyDataList, d.name, `${formatBytesShort(d.bytes)} · ${d.path}`);
      }
    }
    if (els.privacyWakeListenerStatus) {
      const wake = r.wake_listener;
      if (wake) {
        const state = wake.active ? 'Active — listening for the wake phrase.' : 'Not active.';
        els.privacyWakeListenerStatus.textContent = `${state} ${wake.note || ''}`.trim();
      } else {
        els.privacyWakeListenerStatus.textContent = 'Not reported by the backend.';
      }
    }
    renderPrivacyStores(r);
    renderPersonaLearningDisclosure(r);
    renderWipePreview(r);
  }

  /**
   * The complete store table (Wave 6 / Gate 6), generated from the backend's
   * data registry.
   *
   * `data_locations` above is a six-entry summary that predates the registry;
   * this renders every declared store. It is deliberately NOT a hand-written
   * list in the renderer — that is precisely how a store ends up shipped,
   * wiped, and never mentioned on the screen that claims to describe them all.
   */
  function renderPrivacyStores(report) {
    if (!els.privacyStoreList) return;
    els.privacyStoreList.innerHTML = '';
    const stores = report?.stores || [];
    if (!stores.length) {
      els.privacyStoreList.innerHTML = '<span class="empty-state">Store inventory unavailable.</span>';
    } else {
      for (const s of stores) {
        const where = s.present ? (s.path || 'on this device') : 'nothing stored yet';
        const size = s.present ? formatBytesShort(s.bytes) : '0 B';
        // Say plainly which clear removes it, and flag the stores that can
        // hold words the user wrote — that is the fact a reader actually
        // needs, and it is the one a size column hides.
        const modes = (s.wipe_modes || []).map(describeWipeMode).filter(Boolean);
        const removedBy = modes.length ? modes.join(' / ') : 'kept until you delete it separately';
        const text = s.may_contain_user_text ? ' · can contain text you wrote' : '';
        appendDetailRow(els.privacyStoreList, s.name,
          `${size} · ${where} · cleared by: ${removedBy}${text}`);
      }
    }
    // Lie-by-omission guard, surfaced rather than buried in a test: if the
    // backend found a file under the data root that no category declares,
    // this screen says so instead of presenting a tidy table over it.
    if (els.privacyUnmappedWarning) {
      const unmapped = report?.unmapped_files || [];
      if (unmapped.length) {
        els.privacyUnmappedWarning.hidden = false;
        els.privacyUnmappedWarning.textContent =
          `${unmapped.length} file(s) on this device are not covered by the list above, `
          + 'so this report is incomplete. Please report this: '
          + unmapped.slice(0, 3).join(', ');
      } else {
        els.privacyUnmappedWarning.hidden = true;
        els.privacyUnmappedWarning.textContent = '';
      }
    }
  }

  function describeWipeMode(mode) {
    if (mode === 'clear_conversations') return 'clearing conversations';
    if (mode === 'clear_personal_data') return 'clearing personal data';
    if (mode === 'factory_reset') return 'a factory reset';
    return '';
  }

  /**
   * The learned-examples disclosure. A table row understates this store: it
   * holds sentences the user dictated AND the rewrites they approved, which
   * is why the privacy screen states in words what ticking the "teach this
   * persona" box actually persisted.
   *
   * Counts only, never example text — the content stays behind the
   * per-persona API the user opens deliberately.
   */
  function renderPersonaLearningDisclosure(report) {
    const learning = report?.persona_learning;
    if (els.privacyPersonaLearningWhat) {
      els.privacyPersonaLearningWhat.textContent = learning?.what_is_stored
        || 'Not reported by the backend.';
    }
    if (els.privacyPersonaLearningCounts) {
      if (!learning) {
        els.privacyPersonaLearningCounts.textContent = '';
      } else if (!learning.total_examples) {
        els.privacyPersonaLearningCounts.textContent =
          'Nothing is stored right now — you have not approved any examples.';
      } else {
        els.privacyPersonaLearningCounts.textContent =
          `${learning.total_examples} example(s) across ${learning.personas} persona(s), `
          + `${formatBytesShort(learning.bytes || 0)} at ${learning.path || 'this device'}.`;
      }
    }
    if (els.privacyPersonaLearningList) {
      els.privacyPersonaLearningList.innerHTML = '';
      const perPersona = learning?.examples_per_persona || {};
      for (const [name, count] of Object.entries(perPersona)) {
        // appendDetailRow builds nodes with textContent, so a persona name
        // (user-authored) cannot inject markup here.
        appendDetailRow(els.privacyPersonaLearningList, name, `${count} example(s)`);
      }
    }
  }

  /**
   * What the selected wipe mode would actually delete, from the backend's own
   * preview of the disk right now.
   *
   * The old confirmation named three things and deleted five. Reading the
   * preview means the sentence the user agrees to and the sweep that runs come
   * from one source, which is the entire point of the registry.
   */
  function renderWipePreview(report) {
    if (!els.privacyWipePreview) return;
    const mode = els.privacyWipeMode?.value || 'clear_conversations';
    const preview = report?.wipe_modes?.[mode];
    els.privacyWipePreview.innerHTML = '';
    if (!preview) {
      els.privacyWipePreview.innerHTML = '<span class="empty-state">Preview unavailable.</span>';
      return;
    }
    const present = (preview.categories || []).filter((c) => c.present);
    if (!present.length) {
      els.privacyWipePreview.innerHTML = '<span class="empty-state">Nothing to delete — these stores are already empty.</span>';
    } else {
      for (const c of present) {
        appendDetailRow(els.privacyWipePreview, c.label, formatBytesShort(c.bytes));
      }
    }
    if (els.privacyFactoryResetPreview) {
      const factory = report?.wipe_modes?.factory_reset;
      els.privacyFactoryResetPreview.innerHTML = '';
      const all = (factory?.categories || []).filter((c) => c.present);
      if (!all.length) {
        els.privacyFactoryResetPreview.innerHTML = '<span class="empty-state">This install already looks fresh.</span>';
      } else {
        appendDetailRow(els.privacyFactoryResetPreview,
          `${all.length} store(s) would be erased`,
          `${formatBytesShort(factory.bytes || 0)} total`);
      }
    }
  }

  async function refreshPrivacyReport() {
    try {
      const report = await fetchPrivacy();
      renderPrivacyReport(report);
    } catch (error) {
      if (els.privacyNetworkList) els.privacyNetworkList.innerHTML = `<span class="empty-state">Privacy report unavailable: ${String(error.message || error)}</span>`;
    }
  }

  async function handleWipe() {
    const wipeVoices = els.privacyWipeVoices?.checked || false;
    const mode = els.privacyWipeMode?.value || 'clear_conversations';
    // Same destructive-action gate as main.js's handleWipeData(), but the list
    // is now read from the backend's own preview of the selected mode rather
    // than written out here. The old wording named three stores while the
    // endpoint deleted five -- contacts and learned persona examples went
    // without ever being mentioned. Naming them from the same source the sweep
    // uses is the only way those two can't drift apart again.
    const preview = lastPrivacyReport?.wipe_modes?.[mode];
    const names = (preview?.categories || [])
      .filter((c) => c.present)
      .map((c) => c.label);
    const list = names.length
      ? names.join(', ')
      : 'your drafts, transcription history and recordings';
    const confirmed = confirmFn(
      `Permanently delete ${list}` +
        (wipeVoices ? ', plus your cloned voices' : '') +
        '? This cannot be undone.',
    );
    if (!confirmed) return;
    if (els.privacyWipeButton) els.privacyWipeButton.disabled = true;
    try {
      const result = await wipeData(wipeVoices, undefined, { confirmed: true, mode });
      if (!result?.ok) {
        const summary = summarizeWipeFailure(result);
        throw new Error(`${result?.message || 'The privacy wipe did not complete.'} ${summary}`.trim());
      }
      const cleared = result.cleared || {};
      hks.showToast?.(`Data wiped (${cleared.drafts ?? 0} drafts cleared).`, 'success');
      setMessage(els.privacyMessage, 'Your data was wiped.', 'success');
      await refreshPrivacyReport();
    } catch (error) {
      const payload = error?.body;
      const base = error?.message || 'The privacy wipe did not complete.';
      const detail = payload ? summarizeWipeFailure(payload) : '';
      hks.showToast?.(`Wipe failed: ${base}`, 'danger');
      setMessage(els.privacyMessage, detail ? `${base} ${detail}` : base, 'danger');
      await refreshPrivacyReport().catch(() => {});
    } finally {
      if (els.privacyWipeButton) els.privacyWipeButton.disabled = false;
    }
  }

  /**
   * Delete every learned persona example, then prove it independently.
   *
   * The store's own "ok" is what it believes about its write; the verify call
   * re-reads the file. Both are reported, and the success wording is taken
   * from the verification — never from the delete.
   */
  async function handleClearPersonaLearning() {
    const ok = confirmFn(
      'Delete every learned example for every persona?\n\n'
      + 'These are the raw-and-final pairs you approved. Deleting them cannot be undone; '
      + 'personas keep working, they just stop having your examples to imitate.');
    if (!ok) return;
    setPersonaLearningMessage('Deleting…');
    try {
      const result = await clearPersonaLearning(undefined, { confirmed: true });
      if (!result?.ok) {
        throw new Error(result?.message || 'The examples were not all deleted.');
      }
      const verified = await verifyPersonaLearning();
      setPersonaLearningMessage(verified?.ok
        ? 'Deleted. Re-checked the file: no learned examples remain.'
        : `Deleted, but the re-check still found something: ${verified?.detail || 'unknown'}`);
      await refreshPrivacyReport();
    } catch (error) {
      setPersonaLearningMessage(`Could not delete: ${String(error?.message || error)}`);
    }
  }

  async function handleVerifyPersonaLearning() {
    setPersonaLearningMessage('Checking…');
    try {
      const verified = await verifyPersonaLearning();
      setPersonaLearningMessage(verified?.ok
        ? 'Checked: no learned examples are stored.'
        : `Still stored: ${verified?.detail || 'examples remain'}`);
    } catch (error) {
      setPersonaLearningMessage(`Could not check: ${String(error?.message || error)}`);
    }
  }

  async function handleExport() {
    setPersonaLearningMessage('Building your export…');
    try {
      const bundle = await exportPrivacyData();
      const count = bundle?.category_count ?? 0;
      const skipped = (bundle?.skipped || []).length;
      // Say plainly what could not be inlined rather than presenting a
      // partial bundle as complete.
      setPersonaLearningMessage(skipped
        ? `Exported ${count} store(s). ${skipped} could not be included as text `
          + '(the transcription database, recordings and voices are listed with their paths instead).'
        : `Exported ${count} store(s).`);
      return bundle;
    } catch (error) {
      setPersonaLearningMessage(`Could not export: ${String(error?.message || error)}`);
      return null;
    }
  }

  function setPersonaLearningMessage(text) {
    if (els.privacyPersonaLearningMessage) {
      els.privacyPersonaLearningMessage.textContent = text;
    }
  }

  function setFactoryResetMessage(text) {
    if (els.privacyFactoryResetMessage) {
      els.privacyFactoryResetMessage.textContent = text;
    }
  }

  /**
   * The factory reset. Two gates, deliberately: the typed phrase (which the
   * backend re-checks and is the real one) and a final confirmation naming
   * what is about to go.
   */
  async function handleFactoryReset() {
    const phrase = els.privacyFactoryResetConfirm?.value || '';
    if (phrase !== FACTORY_RESET_CONFIRMATION) {
      setFactoryResetMessage(`Type ${FACTORY_RESET_CONFIRMATION} first. Nothing was deleted.`);
      return;
    }
    const alsoModels = els.privacyFactoryResetModels?.checked || false;
    const ok = confirmFn(
      'Reset this install to a fresh state?\n\n'
      + 'This deletes your recordings, drafts, history, contacts, personas, dictionary, '
      + 'macros, settings, application profiles, workflows and the onboarding record'
      + (alsoModels ? ', and your downloaded models' : ' (downloaded models are kept)')
      + '.\n\nThis cannot be undone.');
    if (!ok) return;
    if (els.privacyFactoryResetButton) els.privacyFactoryResetButton.disabled = true;
    setFactoryResetMessage('Resetting…');
    try {
      const result = await factoryReset(phrase, { deleteDownloadedModels: alsoModels });
      if (result?.ok) {
        setFactoryResetMessage('Done. This install was reset and re-checked: nothing remains. '
          + 'Restart BetterFingers to begin from first run.');
      } else {
        // Never claim a clean reset that did not happen: name what is left.
        const residual = (result?.residual_files || []).slice(0, 3).join(', ');
        const failed = (result?.reset?.failed || []).join(', ');
        setFactoryResetMessage(
          `${result?.message || 'The reset did not fully complete.'}`
          + (failed ? ` Stores still present: ${failed}.` : '')
          + (residual ? ` Files still on disk: ${residual}.` : ''));
      }
    } catch (error) {
      setFactoryResetMessage(`The reset failed: ${String(error?.message || error)}. `
        + 'Some data may have been deleted — use "Check what\'s left".');
    } finally {
      if (els.privacyFactoryResetConfirm) els.privacyFactoryResetConfirm.value = '';
      if (els.privacyFactoryResetButton) els.privacyFactoryResetButton.disabled = true;
      await refreshPrivacyReport();
    }
  }

  async function handleVerifyFactoryReset() {
    setFactoryResetMessage('Checking…');
    try {
      const result = await verifyFactoryReset();
      if (result?.ok) {
        setFactoryResetMessage('Checked: nothing from a previous install remains.');
      } else {
        const failed = (result?.failed || []).join(', ');
        const residual = (result?.residual_files || []).slice(0, 3).join(', ');
        setFactoryResetMessage(
          `Still present${failed ? `: ${failed}` : ''}`
          + (residual ? `. Unaccounted files: ${residual}` : '.'));
      }
    } catch (error) {
      setFactoryResetMessage(`Could not check: ${String(error?.message || error)}`);
    }
  }

  function bindPrivacyControls() {
    els.privacyWipeButton?.addEventListener?.('click', () => handleWipe());
    els.privacyPersonaLearningClearButton?.addEventListener?.('click', () => handleClearPersonaLearning());
    els.privacyPersonaLearningVerifyButton?.addEventListener?.('click', () => handleVerifyPersonaLearning());
    els.privacyExportButton?.addEventListener?.('click', () => handleExport());
    els.privacyFactoryResetButton?.addEventListener?.('click', () => handleFactoryReset());
    els.privacyFactoryResetVerifyButton?.addEventListener?.('click', () => handleVerifyFactoryReset());
    // Changing the mode re-reads the preview so the list the user is looking
    // at always describes the mode the button will run.
    els.privacyWipeMode?.addEventListener?.('change', () => { refreshPrivacyReport(); });
    // The factory-reset button stays disabled until the exact phrase is typed.
    // Enforced again on the backend (which is the real gate); this is the
    // affordance, not the check.
    els.privacyFactoryResetConfirm?.addEventListener?.('input', () => {
      if (!els.privacyFactoryResetButton) return;
      els.privacyFactoryResetButton.disabled =
        (els.privacyFactoryResetConfirm.value || '') !== FACTORY_RESET_CONFIRMATION;
    });
  }

  // Must match server.FACTORY_RESET_CONFIRMATION exactly. Duplicated here only
  // to gate the button; the backend rejects anything else regardless, so a
  // drift between the two disables the button rather than erasing an install.
  const FACTORY_RESET_CONFIRMATION = 'DELETE EVERYTHING';

  // --- Recording: PTT availability note (best-effort, informational) --------

  async function refreshPttAvailabilityNote() {
    const bridge = typeof window !== 'undefined' ? window.betterFingers : undefined;
    if (!els.pttAvailabilityNote || typeof bridge?.getHotkeyCapabilities !== 'function') return;
    try {
      const caps = await bridge.getHotkeyCapabilities();
      if (caps && caps.supports_ptt === false) {
        els.pttAvailabilityNote.textContent = 'Push-to-talk is not supported in this session.';
      } else {
        els.pttAvailabilityNote.textContent = '';
      }
    } catch (_e) {
      els.pttAvailabilityNote.textContent = '';
    }
  }

  // --- search (§7.0) ----------------------------------------------------

  // Every row an element with [data-search-row] + a data-search-label (or
  // its own textContent) inside a [data-search-group] inside a
  // [data-search-section] (== one of the 7 SETTINGS_SECTIONS containers).
  // Mirrors main.js's filterSettings(): while searching, EVERY section with
  // at least one match is shown (not just the currently-active one); rows/
  // groups without a match are hidden; clearing the query reverts to the
  // normal single-active-section display.
  function filterByQuery(query) {
    const q = (query || '').trim();
    const doc = typeof document !== 'undefined' ? document : null;
    if (!doc) return;
    const sections = doc.querySelectorAll('[data-search-section]');

    if (!q) {
      els.searchHeader?.classList?.add('hidden');
      els.emptyState?.classList?.add('hidden');
      sections.forEach((section) => {
        section.hidden = section.id !== els[SECTION_EL_BY_SECTION[sectionState.active]]?.id;
        section.querySelectorAll('[data-search-group]').forEach((g) => { g.hidden = false; });
        section.querySelectorAll('[data-search-row]').forEach((r) => { r.hidden = false; });
      });
      return;
    }

    els.searchHeader?.classList?.remove('hidden');
    let totalMatches = 0;
    sections.forEach((section) => {
      let sectionMatches = 0;
      section.querySelectorAll('[data-search-group]').forEach((group) => {
        let groupMatches = 0;
        group.querySelectorAll('[data-search-row]').forEach((row) => {
          const haystack = row.getAttribute('data-search-label') || row.textContent || '';
          const isMatch = rowMatchesQuery(haystack, q);
          row.hidden = !isMatch;
          if (isMatch) {
            groupMatches += 1;
            sectionMatches += 1;
            totalMatches += 1;
          }
        });
        group.hidden = groupMatches === 0;
      });
      section.hidden = sectionMatches === 0;
    });

    if (totalMatches === 0) els.emptyState?.classList?.remove('hidden');
    else els.emptyState?.classList?.add('hidden');
  }

  function bindSearch() {
    els.searchInput?.addEventListener?.('input', (e) => filterByQuery(e.target.value));
  }

  // --- lifecycle --------------------------------------------------------

  /**
   * "Inspect the data" links, and the guard on the ungated control.
   *
   * The click guard is belt-and-braces next to `disabled` and the missing
   * SETTINGS_FIELD_KEYS entry: a checkbox can be toggled programmatically, and
   * D-0005's promise is about the stored value, not about the widget. If
   * anything does flip it, it flips straight back and the user is told why
   * rather than left with a control that appears to have worked.
   */
  function bindDisclosedToggles() {
    for (const toggle of DISCLOSED_TOGGLES) {
      const group = (els.disclosedToggles || {})[toggle.key];
      if (!group) continue;

      group.inspect?.addEventListener?.('click', (event) => {
        event?.preventDefault?.();
        if (hks.onInspectToggleData) {
          hks.onInspectToggleData(toggle.key, toggle.inspect.target);
          return;
        }
        goToSection(toggle.inspect.section);
      });

      if (!toggleIsInteractive(toggle)) {
        group.input?.addEventListener?.('change', () => {
          if (!group.input.checked) return;
          group.input.checked = false;
          setMessage(els.profileMessage, toggle.gate.text, 'warning');
        });
      }
    }
  }

  function bindOnce() {
    bindSectionNav();
    bindFieldDirtyTracking();
    bindProfileButtons();
    bindAppearanceControls();
    bindOverlayAppearanceControls();
    bindPrivacyControls();
    bindDisclosedToggles();
    bindSearch();
  }

  function init(initialSection) {
    bindOnce();
    applyAppearance();
    if (initialSection && isValidSettingsSection(initialSection)) {
      sectionState = { active: initialSection };
    }
    renderSectionNav();
    return getSectionState();
  }

  /** Real network refresh (profiles + privacy + persona options). Fails gracefully with no backend bridge, same as every other workspace's refreshAll(). */
  async function refreshAll() {
    await refreshProfilesList().catch((error) => setMessage(els.profileMessage, `Load failed: ${error.message}`, 'danger'));
    await refreshPersonaOptions();
    await refreshPrivacyReport();
    await refreshPttAvailabilityNote();
  }

  return {
    init,
    goToSection,
    getSectionState,
    refreshAll,
    setProfilesList,
    setPersonaOptions,
    renderSettings,
    renderDisclosedToggles,
    collectSettings,
    runValidation,
    renderPrivacyReport,
    handleActivate,
    handleCreate,
    handleRename,
    handleDuplicate,
    handleExport,
    handleImportFileChange,
    handleDelete,
    handleSave,
    handleDiscard,
    handleWipe,
    getValidationErrors: () => ({ ...validationErrors }),
    isDirty: () => profileDirty,
    getActiveProfileName: () => activeProfileName,
    getActiveProfileSettings: () => ({ ...activeProfileSettings }),
  };
}
