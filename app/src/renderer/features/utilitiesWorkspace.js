// utilitiesWorkspace.js — thin wiring adapter for the UTILITIES workspace
// (Phase 5a of the Signal Desk redesign, docs/ui/SIGNAL_DESK_SPEC.md section 8).
//
// Utilities is the "no feature left behind" catch-all: everything from
// CURRENT_UI_INVENTORY.md that isn't Talk (capture/refine/send), Library
// (history/recovery/resend), Studio (personas/voice), or Settings (profile
// field groups) lands here. SPEC 8 is explicit: Utilities is NOT mocked
// pixel-for-pixel by the director -- this module builds in the SAME Signal
// Desk visual language (var(--sd-*) tokens, cards, section labels, the
// confidence/status color conventions) established by talkWorkspace.js /
// libraryWorkspace.js / studioWorkspace.js, and reuses their exact
// `createXFeature({elements, hooks})` / `collectXElements(root)` convention.
//
// Like those three modules, this one does NOT reimplement persistence -- it
// binds new Utilities markup (signal-desk.css / signal-desk-preview.html) to
// the EXISTING data sources: api/backend.js's already-exported functions
// (called directly here, same pattern libraryWorkspace.js/studioWorkspace.js
// use), the window.betterFingers preload bridge for the handful of
// typed-IPC-only capabilities that already exist today (writeClipboardText,
// getSidecarLogs, getSidecarStatus, getHotkeyCapabilities -- same bridge
// surface talkWorkspace.js / libraryWorkspace.js / runtime.js already read
// from), and features/messageRescueDraft.js + messageRescuePanel.js +
// textPlayground.js verbatim for the three distinct Message Rescue surfaces.
//
// index.html/main.js are NOT touched this phase (additive only) -- see the
// phase plan in the work packet.
//
// ===========================================================================
// EXHAUSTIVE INVENTORY -> UTILITIES SECTION PLACEMENT MAP
// (director's "no-orphan gate": every §8/§9/§7.3/§7.6/§7.7/§7.8/§7.12/§7.13/
// §7.16 item from docs/ui/CURRENT_UI_INVENTORY.md, plus the 3 Message Rescue
// surfaces, must appear below with the Utilities section it lives in.)
//
// Utilities has 5 internal sections (an internal sub-nav within the shared
// Signal Desk shell's center column -- see UTILITIES_SECTIONS below):
// Models · Speech Input · Text Tools · Diagnostics · Advanced.
//
// This exact map is also exported as INVENTORY_PLACEMENT_MAP (machine-
// readable) so tests/utilitiesWorkspace.test.mjs's completeness test can
// assert every required key is present with a valid section -- see that
// file for the enumerated REQUIRED_INVENTORY_KEYS list this map is checked
// against.
//
// --- MODELS section (inventory §8) ----------------------------------------
//   models.recommendation        Hardware-tier recommendation box                 -> fetchModelRecommendation()            [wired]
//   models.refresh                "Refresh Models" button                          -> fetchLlmModels()+fetchWhisperModels() [wired]
//   models.llm.select             LLM picker + "Use This LLM"                      -> fetchLlmModels(), selectLlmModel()    [wired]
//   models.llm.download           LLM download + progress                          -> downloadLlmModel(), fetchLlmDownloadState() (polled) [wired]
//   models.llm.delete             LLM delete (confirm)                             -> deleteLlmModel()                      [wired]
//   models.llm.unload             LLM unload                                       -> unloadModel('llm')                   [wired]
//   models.whisper.select         Whisper picker + "Use This"                      -> fetchWhisperModels(), selectWhisperModel() [wired]
//   models.whisper.download       Whisper download + progress                      -> downloadWhisperModel()               [wired]
//   models.whisper.delete         Whisper delete (confirm)                         -> deleteWhisperModel()                 [wired]
//   models.whisper.unload         Whisper (STT) unload                             -> unloadModel('stt')                   [wired]
//   models.wake.backbones         Wake Word Engine backbone list + per-row Download -> fetchWakeModels(), downloadWakeModel(), fetchWakeModelDownloadState() [wired]
//   models.runtimeMemory.unloadTts "Unload TTS" (Runtime Memory panel)             -> unloadModel('tts')                   [wired]
//   models.voiceCloning.provision "Install voice cloning" + status/hint            -> provisionVoiceCloning()               [wired]
//
// --- SPEECH INPUT section (audio device + hotkeys + wake word, inventory §7.7/§7.3/§7.8) ---
//   speech.audioDevice.select     Input device picker                              -> GET /runtime/audio-devices (no backend.js export -- see SPEC GAP below) [stub: TODO(phase-integration)]
//   speech.audioDevice.micTest    "Test Browser Microphone Access" + level meter    -> navigator.mediaDevices.getUserMedia (browser API, no backend/IPC needed) [wired]
//   speech.hotkeys.sessionIndicator platform/session readout                       -> fetchCapabilities()                   [wired]
//   speech.hotkeys.waylandWarning  Wayland fallback banner                         -> fetchCapabilities() (is_wayland)      [wired]
//   speech.hotkeys.controllerNote  Controller/gamepad binding note (static)        -> informational only -- see SPEC GAP below [wired, informational]
//   speech.hotkeys.recording       Recording Hotkey field + clear                  -> profile field `hotkey`                [wired]
//   speech.hotkeys.forceStop       Emergency Stop key field + clear                -> profile field `force_stop_key`        [wired]
//   speech.hotkeys.manualSend      Primary Action key field + clear                -> profile field `manual_send_hotkey`    [wired]
//   speech.hotkeys.reviewTts       Review TTS Hotkey field + clear                 -> profile field `review_tts_hotkey`     [wired]
//   speech.hotkeys.chatOpen        Open Chat Key field + clear                     -> profile field `chat_open_key`         [wired]
//   speech.hotkeys.voiceMute       Voice Mute Key field + clear                    -> profile field `voice_mute_key`        [wired]
//   speech.hotkeys.customWidget    click-to-record chord capture (all 6 fields)    -> wireHotkeyRecorder() (keydown chord accumulation, pure describeKeyEvent()) [wired]
//   speech.hotkeys.collisionDetection inline per-field collision errors           -> detectHotkeyCollisions() (pure helper) [wired]
//   speech.wake.enableToggle       Wake word enable/disable toggle                 -> enableWake()/disableWake()            [wired]
//   speech.wake.modelSelect        Imported-classifier dropdown                    -> profile field `wake_word_model`       [wired]
//   speech.wake.import             "Import model file..." (.onnx)                 -> importWakeModel() (typed IPC upload)  [wired]
//   speech.wake.training           Build-a-Wake-Phrase: phrase input + train + progress + verdict -> trainWakePhrase(), fetchWakeTrainStatus() (polled) [wired]
//   speech.wake.tuning             sensitivity / cooldown / max-recording numbers  -> profile fields `wake_word_sensitivity`/`wake_word_cooldown_s`/`wake_word_max_recording_s` [wired]
//   speech.wake.liveTest           "Test Wake Detection (10s)" + score meter       -> testWake()                            [wired]
//
// --- TEXT TOOLS section (inventory §7.12/§7.13 + §6.4/§6.6/§6.7) ----------
//   textTools.dictionary.crud      add/list/remove dictionary terms                -> fetchDictionary(), addDictionaryTerm(), deleteDictionaryTerm() [wired]
//   textTools.dictionary.suggest   auto-surfaced suggestion chips                  -> suggestDictionaryTerms() (mount point wired; caller is a draft-edit diff Utilities does not own -- see SPEC GAP) [stub: TODO(phase-integration)]
//   textTools.macros.crud          add/list/remove macros                          -> fetchMacros(), addMacro(), deleteMacro() [wired]
//   textTools.macros.enabledToggle "Macros enabled" checkbox                       -> profile field `macros_enabled`        [wired]
//   textTools.messageRescue.draftBound   #draftRescuePanel (live, latest-draft-bound) -> features/messageRescueDraft.js's initMessageRescueDraft() -- REUSED VERBATIM [wired, flag-gated pref_message_rescue_enabled]
//   textTools.messageRescue.staticPreview #messageRescuePanel (synthetic example, zero backend calls) -> features/messageRescuePanel.js's self-init -- REUSED VERBATIM [wired, flag-gated]
//   textTools.messageRescue.playground   #textPlaygroundSection (free-standing, real backend) -> features/textPlayground.js's self-init -- REUSED VERBATIM [wired]
//
// --- DIAGNOSTICS section (inventory §9) ------------------------------------
//   diagnostics.doctor             8 subsystem cards + recovery panel             -> fetchDoctor()                         [wired]
//   diagnostics.latencyHud         per-stage Last/Avg/p50/p95 table                -> fetchMetrics()                        [wired]
//   diagnostics.recordings         saved recordings list + retranscribe/discard/clear -> fetchRecordings(), retranscribeRecording(), deleteRecording(), clearRecordings() [wired]
//   diagnostics.jobs               active jobs list + cancel                       -> fetchJobs(true), cancelJob()          [wired]
//   diagnostics.sidecarLogs        sidecar startup log tail + clear (client-side)  -> window.betterFingers.getSidecarLogs() [wired]
//   diagnostics.supportReport      "Copy Support Report" -> clipboard              -> fetchSupportReport() + writeClipboardText() [wired]
//   diagnostics.sidecarStatus      sidecar process status                          -> window.betterFingers.getSidecarStatus() [wired]
//   diagnostics.paths              debug log / models dir / llama-server paths     -> fetchDiagnosticsPaths()               [wired]
//   diagnostics.runtimeErrors      last 8 runtime errors, severity-tinted          -> fetchRuntimeErrors()                  [wired]
//   diagnostics.debugLogTail       debug.log tail                                  -> fetchDiagnosticsLogs(80)              [wired]
//
// --- ADVANCED section (inventory §7.16, plus §7.6 Send & Injection -- see SPEC GAP) ---
//   advanced.warmup.stt/llm/hotkeys  3 warmup buttons                              -> warmupRuntime({stt|llm|hotkeys:true}) [wired]
//   advanced.primaryAction         "Primary Action" button                         -> runPrimaryAction()                    [wired]
//   advanced.emergencyStop         "Emergency Stop" button                         -> emergencyStop()                       [wired]
//   advanced.residency.llm/stt/tts model-keep-loaded checkboxes                    -> profile fields `model_keep_*_loaded`  [wired]
//   advanced.testModelLoad         "Test Model Load" button                        -> warmupRuntime({llm:true})             [wired]
//   advanced.capabilitiesDump      platform capability dump                        -> fetchCapabilities()                   [wired]
//   advanced.runtimeStatusDump     subsystem detail dump                           -> fetchRuntimeStatus()                  [wired]
//   advanced.outputSettingsSummary live send-mode/auto-submit/injection summary    -> fetchOutputSettings()                 [wired]
//   advanced.sendInjection.warnings injection/wayland/ducking banners              -> fetchCapabilities()                   [wired]
//   advanced.sendInjection.audioDucking  ducking checkbox                          -> profile field `audio_ducking`         [wired]
//   advanced.sendInjection.testPasteCopy "Test Paste/Copy" button                  -> window.betterFingers.writeClipboardText() [wired]
//
// ===========================================================================
// SPEC GAPS / placement decisions the director should confirm or redirect:
//
//   1. Section grouping: the work packet's own example groups Send &
//      Injection implicitly under neither "Speech Input" nor "Text Tools" --
//      it is placed under ADVANCED here (injection/ducking/paste-test read as
//      developer-adjacent settings, same shelf as warmup/residency/dumps in
//      inventory §7.16's neighbor section §7.6). Flagged, not hidden.
//   2. Audio device SELECT (`speech.audioDevice.select`): main.js populates
//      `#settingInputDevice` via a local, unexported `fetchJson('/runtime/
//      audio-devices')` helper -- api/backend.js has NO exported wrapper for
//      this route (only `refreshAudioDevices()`, the POST /refresh variant).
//      Rather than reach around backend.js's public export surface with a
//      raw `window.betterFingers.backendRequest(...)` call (a pattern none of
//      Talk/Library/Studio use), this is left a clearly-labeled
//      TODO(phase-integration) stub: the <select> markup + mount point exist,
//      wireAudioDevice() renders a "device list needs a backend.js export"
//      placeholder option, and the REAL microphone test + live level meter
//      below it (getUserMedia-based, no backend involved) is fully wired.
//   3. Dictionary auto-suggest (`textTools.dictionary.suggest`): the real
//      inventory trigger is "auto-surfaced from an edited DRAFT" (main.js's
//      `maybeLearnFromEdit` diffing raw vs. edited draft text on Save Edit) --
//      Utilities has no draft editor of its own to diff. The mount point +
//      `renderDictionarySuggestions()` + click-to-add wiring are all real and
//      exported (`suggestFromEdit(rawText, editedText)` on the returned
//      feature object), but nothing in Utilities itself calls it
//      automatically; TODO(phase-integration): main.js's draft-edit save path
//      should call it once Talk's real draft editor exists.
//   4. Hotkey "controller binding": CURRENT_UI_INVENTORY.md's orphan list
//      (§15) and SPEC §8 both mention "hotkey/controller binding" in the same
//      breath as the 6 keyboard hotkey fields, but no dedicated
//      controller/gamepad UI or backend field exists anywhere in the scoped
//      inventory -- the app's global-hotkey layer is keyboard-only today.
//      `speech.hotkeys.controllerNote` is therefore an honest, static
//      informational line (controller buttons register as keypresses via the
//      OS's own remapping tools; no separate binding surface exists), not a
//      fabricated new control.
//
// ===========================================================================
// hooks contract (all optional; every call is optional-chained so a missing
// hook is a safe no-op, never a throw -- same convention as talkWorkspace.js/
// libraryWorkspace.js/studioWorkspace.js):
//
//   hooks.showToast(msg, tone, duration)        Optional user feedback.
//   hooks.confirmFn(message)                    Injected confirm() for
//                                destructive actions (LLM/Whisper delete,
//                                clear recordings). Defaults to window.confirm.
//   hooks.applyMessageRescueToEditor(text)       Passed straight through to
//                                initMessageRescueDraft()'s `hooks.applyToEditor`
//                                -- TODO(phase-integration): needs a real
//                                draft final-text editor once Talk owns one.
//
// To mount for real: pass `elements` from collectUtilitiesElements() (or an
// equivalent object), call `init()`, then `refreshAll()`.
// ===========================================================================

import {
  fetchModelRecommendation,
  fetchLlmModels,
  selectLlmModel,
  downloadLlmModel,
  fetchLlmDownloadState,
  deleteLlmModel,
  fetchWhisperModels,
  selectWhisperModel,
  downloadWhisperModel,
  deleteWhisperModel,
  unloadModel,
  fetchWakeModels,
  downloadWakeModel,
  fetchWakeModelDownloadState,
  provisionVoiceCloning,
  fetchCapabilities,
  fetchProfiles,
  fetchProfile,
  saveProfile,
  fetchDictionary,
  addDictionaryTerm,
  deleteDictionaryTerm,
  suggestDictionaryTerms,
  fetchMacros,
  addMacro,
  deleteMacro,
  fetchWakeStatus,
  enableWake,
  disableWake,
  importWakeModel,
  trainWakePhrase,
  fetchWakeTrainStatus,
  testWake,
  fetchDoctor,
  fetchMetrics,
  fetchRecordings,
  retranscribeRecording,
  deleteRecording,
  clearRecordings,
  fetchJobs,
  cancelJob,
  fetchSupportReport,
  fetchDiagnosticsPaths,
  fetchRuntimeErrors,
  fetchDiagnosticsLogs,
  fetchRuntimeStatus,
  fetchOutputSettings,
  warmupRuntime,
  runPrimaryAction,
  emergencyStop,
} from '../api/backend.js';
import { initMessageRescueDraft } from './messageRescueDraft.js';

// Side-effect imports: both self-initialize on import by querying their own
// canonical DOM ids (`#messageRescuePanel`, `#textPlaygroundSection`) and
// no-op if that markup isn't present -- exactly the same contract they have
// today loaded via their own `<script type="module">` tags in index.html.
// Importing them here means any page that mounts utilitiesWorkspace.js gets
// all three Message Rescue surfaces for free without needing separate script
// tags of its own (see signal-desk-preview.html for the markup they bind to).
import './messageRescuePanel.js';
import './textPlayground.js';

// --- Section routing (pure) -------------------------------------------------

export const UTILITIES_SECTIONS = ['models', 'speech', 'text', 'diagnostics', 'advanced'];

export const UTILITIES_SECTION_META = {
  models: { label: 'Models', description: 'LLM, Whisper, wake-word backbones, runtime memory, and voice cloning.' },
  speech: { label: 'Speech Input', description: 'Audio device, hotkeys, and wake word.' },
  text: { label: 'Text Tools', description: 'Dictionary, macros, and the three Message Rescue surfaces.' },
  diagnostics: { label: 'Diagnostics', description: 'Doctor checkup, latency, recovery, jobs, and logs.' },
  advanced: { label: 'Advanced', description: 'Warmup, residency, send & injection, and raw dumps.' },
};

export function isValidUtilitiesSection(id) {
  return UTILITIES_SECTIONS.includes(id);
}

/** Pure reducer, same shape as signalDeskShell.js's computeNextState -- an unknown id is a no-op. */
export function computeNextUtilitiesSection(state, requestedId) {
  const current = state && isValidUtilitiesSection(state.active) ? state.active : UTILITIES_SECTIONS[0];
  if (!isValidUtilitiesSection(requestedId)) {
    return { active: current };
  }
  return { active: requestedId };
}

// --- Inventory -> section placement map (machine-readable, see file header) -

export const INVENTORY_PLACEMENT_MAP = {
  'models.recommendation': { section: 'models', control: 'Model recommendation box', wired: true },
  'models.refresh': { section: 'models', control: 'Refresh Models button', wired: true },
  'models.llm.select': { section: 'models', control: 'LLM select + Use This LLM', wired: true },
  'models.llm.download': { section: 'models', control: 'LLM download + progress', wired: true },
  'models.llm.delete': { section: 'models', control: 'LLM delete', wired: true },
  'models.llm.unload': { section: 'models', control: 'LLM unload', wired: true },
  'models.whisper.select': { section: 'models', control: 'Whisper select + Use This', wired: true },
  'models.whisper.download': { section: 'models', control: 'Whisper download + progress', wired: true },
  'models.whisper.delete': { section: 'models', control: 'Whisper delete', wired: true },
  'models.whisper.unload': { section: 'models', control: 'Whisper (STT) unload', wired: true },
  'models.wake.backbones': { section: 'models', control: 'Wake Word Engine backbone downloads', wired: true },
  'models.runtimeMemory.unloadTts': { section: 'models', control: 'Unload TTS (Runtime Memory)', wired: true },
  'models.voiceCloning.provision': { section: 'models', control: 'Voice Cloning provisioning', wired: true },

  'speech.audioDevice.select': { section: 'speech', control: 'Input device select', wired: false, note: 'TODO(phase-integration): no backend.js export for GET /runtime/audio-devices' },
  'speech.audioDevice.micTest': { section: 'speech', control: 'Mic test + live level meter', wired: true },
  'speech.hotkeys.sessionIndicator': { section: 'speech', control: 'Hotkey session indicator', wired: true },
  'speech.hotkeys.waylandWarning': { section: 'speech', control: 'Wayland hotkey warning', wired: true },
  'speech.hotkeys.controllerNote': { section: 'speech', control: 'Controller binding note', wired: true },
  'speech.hotkeys.recording': { section: 'speech', control: 'Recording Hotkey field', wired: true },
  'speech.hotkeys.forceStop': { section: 'speech', control: 'Emergency Stop key field', wired: true },
  'speech.hotkeys.manualSend': { section: 'speech', control: 'Primary Action key field', wired: true },
  'speech.hotkeys.reviewTts': { section: 'speech', control: 'Review TTS Hotkey field', wired: true },
  'speech.hotkeys.chatOpen': { section: 'speech', control: 'Open Chat Key field', wired: true },
  'speech.hotkeys.voiceMute': { section: 'speech', control: 'Voice Mute Key field', wired: true },
  'speech.hotkeys.customWidget': { section: 'speech', control: 'Click-to-record chord widget', wired: true },
  'speech.hotkeys.collisionDetection': { section: 'speech', control: 'Hotkey collision detection', wired: true },
  'speech.wake.enableToggle': { section: 'speech', control: 'Wake word enable toggle', wired: true },
  'speech.wake.modelSelect': { section: 'speech', control: 'Wake word model select', wired: true },
  'speech.wake.import': { section: 'speech', control: 'Import .onnx wake model', wired: true },
  'speech.wake.training': { section: 'speech', control: 'Build-a-Wake-Phrase training', wired: true },
  'speech.wake.tuning': { section: 'speech', control: 'Detection tuning (sensitivity/cooldown/max-recording)', wired: true },
  'speech.wake.liveTest': { section: 'speech', control: 'Live wake test + score meter', wired: true },

  'textTools.dictionary.crud': { section: 'text', control: 'Dictionary add/list/remove', wired: true },
  'textTools.dictionary.suggest': { section: 'text', control: 'Dictionary auto-suggest chips', wired: false, note: 'TODO(phase-integration): trigger lives on a draft-edit diff Utilities does not own yet' },
  'textTools.macros.crud': { section: 'text', control: 'Macros add/list/remove', wired: true },
  'textTools.macros.enabledToggle': { section: 'text', control: 'Macros enabled toggle', wired: true },
  'textTools.messageRescue.draftBound': { section: 'text', control: 'Message Rescue: draft-bound live panel', wired: true },
  'textTools.messageRescue.staticPreview': { section: 'text', control: 'Message Rescue: static/example preview', wired: true },
  'textTools.messageRescue.playground': { section: 'text', control: 'Text & Persona Playground', wired: true },

  'diagnostics.doctor': { section: 'diagnostics', control: 'Doctor checkup (8 cards + recovery)', wired: true },
  'diagnostics.latencyHud': { section: 'diagnostics', control: 'Pipeline latency HUD', wired: true },
  'diagnostics.recordings': { section: 'diagnostics', control: 'Recovery: saved recordings list', wired: true },
  'diagnostics.jobs': { section: 'diagnostics', control: 'Active jobs list + cancel', wired: true },
  'diagnostics.sidecarLogs': { section: 'diagnostics', control: 'Sidecar startup logs', wired: true },
  'diagnostics.supportReport': { section: 'diagnostics', control: 'Copy Support Report', wired: true },
  'diagnostics.sidecarStatus': { section: 'diagnostics', control: 'Sidecar process status', wired: true },
  'diagnostics.paths': { section: 'diagnostics', control: 'Diagnostics paths', wired: true },
  'diagnostics.runtimeErrors': { section: 'diagnostics', control: 'Runtime errors list', wired: true },
  'diagnostics.debugLogTail': { section: 'diagnostics', control: 'debug.log tail', wired: true },

  'advanced.warmup': { section: 'advanced', control: 'Warm Up STT/LLM/Hotkeys buttons', wired: true },
  'advanced.primaryAction': { section: 'advanced', control: 'Primary Action button', wired: true },
  'advanced.emergencyStop': { section: 'advanced', control: 'Emergency Stop button', wired: true },
  'advanced.residency': { section: 'advanced', control: 'Model residency keeps (llm/stt/tts)', wired: true },
  'advanced.testModelLoad': { section: 'advanced', control: 'Test Model Load button', wired: true },
  'advanced.capabilitiesDump': { section: 'advanced', control: 'Capabilities dump', wired: true },
  'advanced.runtimeStatusDump': { section: 'advanced', control: 'Runtime status dump', wired: true },
  'advanced.sendInjection.warnings': { section: 'advanced', control: 'Injection/Wayland/ducking warnings', wired: true },
  'advanced.sendInjection.audioDucking': { section: 'advanced', control: 'Audio ducking toggle', wired: true },
  'advanced.sendInjection.testPasteCopy': { section: 'advanced', control: 'Test Paste/Copy button', wired: true },
};

// --- Pure helpers: hotkeys ---------------------------------------------------

export const HOTKEY_FIELD_KEYS = ['hotkey', 'force_stop_key', 'manual_send_hotkey', 'review_tts_hotkey', 'chat_open_key', 'voice_mute_key'];

export const HOTKEY_FIELD_LABELS = {
  hotkey: 'Recording Hotkey',
  force_stop_key: 'Emergency Stop key',
  manual_send_hotkey: 'Primary Action key',
  review_tts_hotkey: 'Review TTS Hotkey',
  chat_open_key: 'Open Chat Key',
  voice_mute_key: 'Voice Mute Key',
};

const MODIFIER_KEY_NAMES = new Set(['Control', 'Meta', 'Alt', 'Shift']);

/** A single keydown event -> a chord string like "Ctrl+Shift+Space". Pure (no DOM mutation). */
export function describeKeyEvent(event) {
  if (!event) return '';
  const parts = [];
  if (event.ctrlKey) parts.push('Ctrl');
  if (event.metaKey) parts.push('Meta');
  if (event.altKey) parts.push('Alt');
  if (event.shiftKey) parts.push('Shift');
  const key = event.key;
  if (key && !MODIFIER_KEY_NAMES.has(key)) {
    const label = key === ' ' ? 'Space' : key.length === 1 ? key.toUpperCase() : key;
    parts.push(label);
  }
  return parts.join('+');
}

/**
 * hotkeyMap: {fieldKey: chordString}. Returns {fieldKey: collisionMessage}
 * for every field whose (non-empty) value is shared by another field.
 */
export function detectHotkeyCollisions(hotkeyMap) {
  const map = hotkeyMap || {};
  const seenBy = {};
  for (const [field, value] of Object.entries(map)) {
    const v = String(value || '').trim();
    if (!v) continue;
    if (!seenBy[v]) seenBy[v] = [];
    seenBy[v].push(field);
  }
  const collisions = {};
  for (const fields of Object.values(seenBy)) {
    if (fields.length < 2) continue;
    for (const field of fields) {
      const others = fields.filter((f) => f !== field).map((f) => HOTKEY_FIELD_LABELS[f] || f);
      collisions[field] = `Same as ${others.join(', ')}`;
    }
  }
  return collisions;
}

// --- Pure helpers: models / bytes / progress --------------------------------

export function formatMb(mb) {
  const n = Number(mb);
  if (!Number.isFinite(n) || n <= 0) return 'unknown';
  return n >= 1024 ? `${(n / 1024).toFixed(1)} GB` : `${Math.round(n)} MB`;
}

export function clampPct(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, Math.round(n)));
}

/** download_state payload ({status, percent, message, bytes_downloaded, bytes_total}) -> a DOM-ready view model. */
export function buildDownloadProgressModel(downloadState) {
  const ds = downloadState || {};
  const status = ds.status || 'idle';
  const active = status === 'downloading' || status === 'queued' || status === 'starting';
  const percent = clampPct(ds.percent ?? (ds.bytes_total ? (100 * (ds.bytes_downloaded || 0)) / ds.bytes_total : 0));
  const bytesLabel = ds.bytes_total ? `${formatMb((ds.bytes_downloaded || 0) / (1024 * 1024))} / ${formatMb(ds.bytes_total / (1024 * 1024))}` : '';
  return {
    hidden: !active && status !== 'error',
    label: ds.message || (status === 'error' ? 'Download failed.' : active ? 'Downloading…' : ''),
    percent,
    bytesLabel,
    tone: status === 'error' ? 'danger' : active ? 'info' : '',
  };
}

// --- Pure helpers: doctor / recovery ----------------------------------------

const DOCTOR_SUBSYSTEMS = [
  { id: 'stt', title: 'STT (Transcriber)' },
  { id: 'llm', title: 'LLM Engine' },
  { id: 'tts', title: 'TTS (Read-Aloud)' },
  { id: 'hotkeys', title: 'Hotkey Manager' },
  { id: 'models', title: 'Model Paths' },
  { id: 'audio', title: 'Audio System' },
  { id: 'platform', title: 'Platform Capabilities' },
  { id: 'hardware', title: 'Hardware & Model Fit' },
];

export const DOCTOR_RECOVERY_LABELS = {
  missing_model: 'Model Download Needed',
  missing_llama_server: 'llama-server Required',
  outdated_runtime: 'Runtime Update Needed',
  port_conflict: 'Port Conflict',
  microphone_unavailable: 'Microphone Not Found',
  unsupported_wayland_injection: 'Wayland Restriction',
  failed_clipboard: 'Clipboard Failure',
  failed_tts_dependency: 'TTS Missing',
};

/** One doctor subsystem's raw sub-payload -> {title, tone, detailLines, triggers}. Condensed, not a line-for-line port of main.js's version, but tone/detail-equivalent. */
export function buildDoctorCardModel(id, data) {
  const meta = DOCTOR_SUBSYSTEMS.find((s) => s.id === id) || { title: id };
  const d = data || {};
  const triggers = [];
  let tone = 'unknown';
  let status = 'Unknown';
  const lines = [];

  if (id === 'stt') {
    tone = d.loaded ? 'ok' : d.initialized ? 'warn' : 'error';
    status = d.loaded ? 'Loaded' : d.initialized ? 'Initialized' : 'Offline';
    lines.push(`Initialized: ${d.initialized ? 'Yes' : 'No'}`, `Loaded: ${d.loaded ? 'Yes' : 'No'}`, `Model: ${d.model_size ?? 'None'}`);
    if (!d.initialized) triggers.push('missing_model');
  } else if (id === 'llm') {
    const runtimeIncompatible = d.llama_server_exists && d.runtime_compatible === false;
    tone = d.ready ? 'ok' : runtimeIncompatible || d.initialized ? 'warn' : 'error';
    status = d.ready ? 'Ready' : runtimeIncompatible ? 'Runtime outdated' : d.initialized ? 'Warming Up' : 'Offline';
    lines.push(`Selected model: ${d.model_id ?? 'None'}`, `llama-server: ${d.llama_server_exists ? 'Found' : 'Missing'}`);
    if (runtimeIncompatible) triggers.push('outdated_runtime');
    if (!d.llama_server_exists) triggers.push('missing_llama_server');
    if (!d.initialized && d.llama_server_exists && !runtimeIncompatible && !d.model_exists) triggers.push('missing_model');
  } else if (id === 'tts') {
    tone = d.loaded ? 'ok' : d.initialized ? 'warn' : 'error';
    status = d.loaded ? 'Active' : d.initialized ? 'Offline' : 'Error';
    lines.push(`Provider: ${d.backend ?? 'unknown'}`, `Status: ${d.status_message ?? ''}`);
    if (d.backend === 'none' && d.status_message !== 'TTS is not loaded.') triggers.push('failed_tts_dependency');
  } else if (id === 'hotkeys') {
    tone = d.active ? 'ok' : d.started ? 'warn' : 'error';
    status = d.active ? 'Listening' : d.started ? 'Started' : 'Stopped';
    lines.push(`Manager started: ${d.started ? 'Yes' : 'No'}`, `Thread active: ${d.active ? 'Yes' : 'No'}`);
  } else if (id === 'models') {
    tone = d.default_model_exists ? 'ok' : 'error';
    status = d.default_model_exists ? 'Verified' : 'Missing Default';
    lines.push(`Models folder: ${d.models_dir ?? 'unknown'}`);
    if (!d.default_model_exists) triggers.push('missing_model');
  } else if (id === 'audio') {
    const hasDevices = Array.isArray(d.devices) && d.devices.length > 0;
    tone = hasDevices && !d.error ? 'ok' : 'error';
    status = hasDevices ? 'Available' : 'No Mics';
    lines.push(hasDevices ? `Devices: ${d.devices.length}` : 'No devices detected.');
    if (d.error) lines.push(`Error: ${d.error}`);
    if (!hasDevices || d.error) triggers.push('microphone_unavailable');
  } else if (id === 'platform') {
    tone = d.supports_input_injection ? 'ok' : 'warn';
    status = d.supports_input_injection ? 'Fully Supported' : 'Limited';
    lines.push(`Platform: ${d.platform ?? 'unknown'}`, `Session: ${d.session_type ?? 'unknown'}`, `Global hotkeys: ${d.supports_global_hotkeys ? 'Yes' : 'No'}`);
    if (d.is_wayland && !d.supports_input_injection) triggers.push('unsupported_wayland_injection');
  } else if (id === 'hardware') {
    const fit = d.fit || {};
    const verdictTone = { good: 'ok', tight: 'warn', insufficient: 'error', unknown: 'warn' };
    tone = verdictTone[fit.verdict] || 'unknown';
    status = { good: 'Good Fit', tight: 'Tight', insufficient: 'Insufficient', unknown: 'Unknown' }[fit.verdict] || 'Unknown';
    const hw = d.hardware || {};
    if (hw.available) {
      lines.push(`CPU: ${hw.cpu?.model ?? 'unknown'}`, `RAM: ${formatMb((hw.memory?.total_mb) || 0)}`);
    }
    if (fit.model_name) lines.push(`Model: ${fit.model_name}`);
  }

  return { id, title: meta.title, tone, status, detailLines: lines, triggers };
}

/** doctor payload -> [{id,title,tone,status,detailLines}], deduped recovery trigger list, and recovery text per trigger (backend text preferred, client fallback for outdated_runtime). */
export function buildDoctorModel(doctorPayload) {
  const doctor = doctorPayload || {};
  const cards = DOCTOR_SUBSYSTEMS.map((s) => {
    const sourceData = s.id === 'hardware' ? { hardware: doctor.hardware, fit: doctor.model_fit } : doctor[s.id];
    return buildDoctorCardModel(s.id, sourceData);
  });
  const triggers = [...new Set(cards.flatMap((c) => c.triggers))];
  const clientRecoveryFallback = {
    outdated_runtime: "Your llama-server binary is too old to run the selected model. Update llama-server to a build that meets the model's minimum.",
  };
  const recovery = triggers
    .map((trigger) => ({
      trigger,
      label: DOCTOR_RECOVERY_LABELS[trigger] || trigger,
      text: (doctor.recovery && doctor.recovery[trigger]) || clientRecoveryFallback[trigger] || '',
    }))
    .filter((r) => r.text);
  return { cards, recovery };
}

// --- Pure helpers: jobs / recordings ----------------------------------------

export const JOB_STATE_LABELS = {
  queued: 'Queued',
  loading: 'Loading',
  capturing: 'Capturing',
  transcribing: 'Transcribing',
  refining: 'Refining',
  stitching: 'Stitching',
  review_ready: 'Ready for review',
  injecting: 'Injecting',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

export function formatJobRow(job) {
  const stateLabel = JOB_STATE_LABELS[job?.state] || job?.state || 'unknown';
  const pct = typeof job?.progress === 'number' ? ` · ${Math.round(job.progress * 100)}%` : '';
  const cancelling = job?.cancel_requested ? ' · cancelling…' : '';
  return `${job?.label || job?.kind || 'job'} — ${stateLabel}${pct}${cancelling}`;
}

export function formatRecordingRow(recording) {
  const when = recording?.created_at ? new Date(recording.created_at * 1000).toLocaleString() : 'unknown time';
  const dur = recording?.duration_seconds ? `${recording.duration_seconds}s` : '';
  const reason = recording?.stop_reason ? ` · ${recording.stop_reason}` : '';
  return `${when}${dur ? ` · ${dur}` : ''}${reason}`;
}

// --- Pure helpers: wake word -------------------------------------------------

export function formatWakeTrainVerdict(result) {
  if (!result) return '';
  const verdict = result.verdict || 'unknown';
  const far = result.false_accept_rate !== undefined ? `FA ${(Number(result.false_accept_rate) * 100).toFixed(1)}%` : '';
  const frr = result.false_reject_rate !== undefined ? `FR ${(Number(result.false_reject_rate) * 100).toFixed(1)}%` : '';
  const rates = [far, frr].filter(Boolean).join(' · ');
  return `${verdict}${rates ? ` (${rates})` : ''}`;
}

// --- Element ids -------------------------------------------------------------

function hotkeyFieldIds(fieldSuffix) {
  return {
    input: `sdUtilHotkey${fieldSuffix}Input`,
    clear: `sdUtilHotkey${fieldSuffix}Clear`,
    error: `sdUtilHotkey${fieldSuffix}Error`,
  };
}

export const UTILITIES_ELEMENT_IDS = {
  // --- section shell ---
  navModels: 'sdUtilNavModels',
  navSpeech: 'sdUtilNavSpeech',
  navText: 'sdUtilNavText',
  navDiagnostics: 'sdUtilNavDiagnostics',
  navAdvanced: 'sdUtilNavAdvanced',
  sectionModels: 'sdUtilSectionModels',
  sectionSpeech: 'sdUtilSectionSpeech',
  sectionText: 'sdUtilSectionText',
  sectionDiagnostics: 'sdUtilSectionDiagnostics',
  sectionAdvanced: 'sdUtilSectionAdvanced',

  // --- Models ---
  modelsRefreshButton: 'sdUtilModelsRefreshButton',
  modelsRecommendation: 'sdUtilModelsRecommendation',
  modelsStatusSummary: 'sdUtilModelsStatusSummary',
  modelsMessage: 'sdUtilModelsMessage',
  llmBadge: 'sdUtilLlmBadge',
  llmSelect: 'sdUtilLlmSelect',
  llmDetails: 'sdUtilLlmDetails',
  llmSelectButton: 'sdUtilLlmSelectButton',
  llmDownloadButton: 'sdUtilLlmDownloadButton',
  llmProgress: 'sdUtilLlmProgress',
  llmProgressLabel: 'sdUtilLlmProgressLabel',
  llmProgressPercent: 'sdUtilLlmProgressPercent',
  llmProgressFill: 'sdUtilLlmProgressFill',
  llmDeleteButton: 'sdUtilLlmDeleteButton',
  llmUnloadButton: 'sdUtilLlmUnloadButton',
  whisperBadge: 'sdUtilWhisperBadge',
  whisperSelect: 'sdUtilWhisperSelect',
  whisperDetails: 'sdUtilWhisperDetails',
  whisperSelectButton: 'sdUtilWhisperSelectButton',
  whisperDownloadButton: 'sdUtilWhisperDownloadButton',
  whisperProgress: 'sdUtilWhisperProgress',
  whisperProgressLabel: 'sdUtilWhisperProgressLabel',
  whisperProgressPercent: 'sdUtilWhisperProgressPercent',
  whisperProgressFill: 'sdUtilWhisperProgressFill',
  whisperDeleteButton: 'sdUtilWhisperDeleteButton',
  whisperUnloadButton: 'sdUtilWhisperUnloadButton',
  wakeEngineBadge: 'sdUtilWakeEngineBadge',
  wakeBackboneList: 'sdUtilWakeBackboneList',
  unloadTtsButton: 'sdUtilUnloadTtsButton',
  voiceCloningBadge: 'sdUtilVoiceCloningBadge',
  voiceCloningStatus: 'sdUtilVoiceCloningStatus',
  voiceCloningProvisionButton: 'sdUtilVoiceCloningProvisionButton',
  voiceCloningHint: 'sdUtilVoiceCloningHint',

  // --- Speech Input: audio device ---
  audioDeviceSelect: 'sdUtilAudioDeviceSelect',
  audioTestMicButton: 'sdUtilAudioTestMicButton',
  audioMeterFill: 'sdUtilAudioMeterFill',
  audioMessage: 'sdUtilAudioMessage',

  // --- Speech Input: hotkeys ---
  hotkeySessionIndicator: 'sdUtilHotkeySessionIndicator',
  hotkeyWaylandWarning: 'sdUtilHotkeyWaylandWarning',
  hotkeyControllerNote: 'sdUtilHotkeyControllerNote',
  hotkeyMessage: 'sdUtilHotkeyMessage',
  hotkeyFields: {
    hotkey: hotkeyFieldIds('Recording'),
    force_stop_key: hotkeyFieldIds('ForceStop'),
    manual_send_hotkey: hotkeyFieldIds('ManualSend'),
    review_tts_hotkey: hotkeyFieldIds('ReviewTts'),
    chat_open_key: hotkeyFieldIds('ChatOpen'),
    voice_mute_key: hotkeyFieldIds('VoiceMute'),
  },

  // --- Speech Input: wake word ---
  wakeEnabledToggle: 'sdUtilWakeEnabledToggle',
  wakeStatusDetail: 'sdUtilWakeStatusDetail',
  wakeModelSelect: 'sdUtilWakeModelSelect',
  wakeImportButton: 'sdUtilWakeImportButton',
  wakeImportFile: 'sdUtilWakeImportFile',
  wakeImportStatus: 'sdUtilWakeImportStatus',
  wakeTrainPhrase: 'sdUtilWakeTrainPhrase',
  wakeTrainButton: 'sdUtilWakeTrainButton',
  wakeTrainProgress: 'sdUtilWakeTrainProgress',
  wakeTrainProgressLabel: 'sdUtilWakeTrainProgressLabel',
  wakeTrainProgressPercent: 'sdUtilWakeTrainProgressPercent',
  wakeTrainProgressFill: 'sdUtilWakeTrainProgressFill',
  wakeTrainResult: 'sdUtilWakeTrainResult',
  wakeSensitivity: 'sdUtilWakeSensitivity',
  wakeCooldown: 'sdUtilWakeCooldown',
  wakeMaxRecording: 'sdUtilWakeMaxRecording',
  wakeTestButton: 'sdUtilWakeTestButton',
  wakeScoreFill: 'sdUtilWakeScoreFill',
  wakeTestResult: 'sdUtilWakeTestResult',
  wakeMessage: 'sdUtilWakeMessage',

  // --- Text Tools: dictionary / macros ---
  dictionaryInput: 'sdUtilDictionaryInput',
  dictionaryAddButton: 'sdUtilDictionaryAddButton',
  dictionarySuggestGroup: 'sdUtilDictionarySuggestGroup',
  dictionarySuggestions: 'sdUtilDictionarySuggestions',
  dictionaryList: 'sdUtilDictionaryList',
  dictionaryMessage: 'sdUtilDictionaryMessage',
  macroTrigger: 'sdUtilMacroTrigger',
  macroExpansion: 'sdUtilMacroExpansion',
  macroAddButton: 'sdUtilMacroAddButton',
  macrosEnabledToggle: 'sdUtilMacrosEnabledToggle',
  macrosList: 'sdUtilMacrosList',
  macrosMessage: 'sdUtilMacrosMessage',

  // --- Diagnostics ---
  doctorRefreshButton: 'sdUtilDoctorRefreshButton',
  doctorCardsGrid: 'sdUtilDoctorCardsGrid',
  doctorRecoveryPanel: 'sdUtilDoctorRecoveryPanel',
  doctorRecoveryList: 'sdUtilDoctorRecoveryList',
  metricsHud: 'sdUtilMetricsHud',
  recordingsList: 'sdUtilRecordingsList',
  recordingsClearButton: 'sdUtilRecordingsClearButton',
  recordingsMessage: 'sdUtilRecordingsMessage',
  jobsList: 'sdUtilJobsList',
  sidecarLogsTail: 'sdUtilSidecarLogsTail',
  sidecarLogsClearButton: 'sdUtilSidecarLogsClearButton',
  copySupportReportButton: 'sdUtilCopySupportReportButton',
  refreshDiagnosticsButton: 'sdUtilRefreshDiagnosticsButton',
  sidecarStatus: 'sdUtilSidecarStatus',
  diagnosticsPathsList: 'sdUtilDiagnosticsPathsList',
  runtimeErrorsList: 'sdUtilRuntimeErrorsList',
  debugLogTail: 'sdUtilDebugLogTail',
  diagnosticsMessage: 'sdUtilDiagnosticsMessage',

  // --- Advanced ---
  warmupSttButton: 'sdUtilWarmupSttButton',
  warmupLlmButton: 'sdUtilWarmupLlmButton',
  startHotkeysButton: 'sdUtilStartHotkeysButton',
  primaryActionButton: 'sdUtilPrimaryActionButton',
  emergencyStopButton: 'sdUtilEmergencyStopButton',
  warmupMessage: 'sdUtilWarmupMessage',
  outputSettingsSummary: 'sdUtilOutputSettingsSummary',
  keepLlm: 'sdUtilKeepLlm',
  keepStt: 'sdUtilKeepStt',
  keepTts: 'sdUtilKeepTts',
  testModelLoadButton: 'sdUtilTestModelLoadButton',
  capabilitiesList: 'sdUtilCapabilitiesList',
  runtimeStatusList: 'sdUtilRuntimeStatusList',
  waylandInjectionWarning: 'sdUtilWaylandInjectionWarning',
  injectionUnavailableWarning: 'sdUtilInjectionUnavailableWarning',
  audioDuckingWarning: 'sdUtilAudioDuckingWarning',
  audioDucking: 'sdUtilAudioDucking',
  testPasteCopyButton: 'sdUtilTestPasteCopyButton',
  sendInjectionMessage: 'sdUtilSendInjectionMessage',
};

/** Looks up every UTILITIES_ELEMENT_IDS entry (including the nested hotkeyFields map) by id from `root`. Missing ids resolve to null, never throw -- same contract as collectStudioElements(). */
export function collectUtilitiesElements(root) {
  const doc = root || (typeof document !== 'undefined' ? document : null);
  const byId = (id) => (doc && typeof doc.getElementById === 'function' ? doc.getElementById(id) || null : null);
  const els = {};
  for (const [key, value] of Object.entries(UTILITIES_ELEMENT_IDS)) {
    if (key === 'hotkeyFields') continue;
    els[key] = byId(value);
  }
  els.hotkeyFields = {};
  for (const [fieldKey, ids] of Object.entries(UTILITIES_ELEMENT_IDS.hotkeyFields)) {
    els.hotkeyFields[fieldKey] = { input: byId(ids.input), clear: byId(ids.clear), error: byId(ids.error) };
  }
  return els;
}

// --- DOM-wiring feature ------------------------------------------------------

/**
 * @param {object} deps
 * @param {object} deps.elements Utilities workspace DOM refs -- see
 *   UTILITIES_ELEMENT_IDS (use collectUtilitiesElements() for the common case).
 * @param {object} deps.hooks See the file-header contract above.
 */
export function createUtilitiesWorkspaceFeature({ elements, hooks } = {}) {
  const els = elements || {};
  const hks = hooks || {};
  const confirmFn = hks.confirmFn || (typeof window !== 'undefined' && window.confirm ? window.confirm.bind(window) : () => true);

  let sectionState = { active: UTILITIES_SECTIONS[0] };

  // Cached backend payloads, kept around so re-renders (e.g. after a select
  // change) don't need a fresh fetch -- mirrors main.js's llmModelsPayload/
  // whisperModelsPayload module-level cache.
  let llmPayload = null;
  let whisperPayload = null;
  let activeProfileName = null;
  let profileSettingsCache = {};
  let micStream = null;
  let micAnimationFrame = null;
  let messageRescueDraftFeature = null;

  function setMessage(el, text = '', tone = '') {
    if (!el) return;
    el.textContent = text;
    if (tone) el.dataset.tone = tone;
    else delete el.dataset.tone;
  }

  // --- section sub-nav ------------------------------------------------------

  function renderSectionNav() {
    const navEls = { models: els.navModels, speech: els.navSpeech, text: els.navText, diagnostics: els.navDiagnostics, advanced: els.navAdvanced };
    const sectionEls = { models: els.sectionModels, speech: els.sectionSpeech, text: els.sectionText, diagnostics: els.sectionDiagnostics, advanced: els.sectionAdvanced };
    UTILITIES_SECTIONS.forEach((id) => {
      const btn = navEls[id];
      if (btn) {
        const isActive = id === sectionState.active;
        btn.classList?.toggle('is-active', isActive);
        btn.setAttribute?.('aria-current', isActive ? 'page' : 'false');
      }
      const section = sectionEls[id];
      if (section) section.hidden = id !== sectionState.active;
    });
  }

  function goToSection(id) {
    sectionState = computeNextUtilitiesSection(sectionState, id);
    renderSectionNav();
    return { ...sectionState };
  }

  // --- generic profile-settings patch (Hotkeys / Wake tuning / Advanced residency / Send&Injection ducking / Macros enabled) ---

  async function ensureActiveProfile() {
    if (activeProfileName) return activeProfileName;
    try {
      const res = await fetchProfiles();
      activeProfileName = res?.active || (Array.isArray(res?.profiles) && res.profiles[0]) || 'Default';
    } catch (_e) {
      activeProfileName = 'Default';
    }
    return activeProfileName;
  }

  async function refreshProfileSettings() {
    const name = await ensureActiveProfile();
    try {
      const res = await fetchProfile(name);
      profileSettingsCache = (res && res.settings) || {};
    } catch (_e) {
      profileSettingsCache = {};
    }
    return profileSettingsCache;
  }

  async function patchProfileSetting(key, value, { messageEl } = {}) {
    const name = await ensureActiveProfile();
    profileSettingsCache = { ...profileSettingsCache, [key]: value };
    try {
      await saveProfile(name, profileSettingsCache);
      if (messageEl) setMessage(messageEl, 'Saved.', 'success');
      else hks.showToast?.('Saved.', 'success', 1200);
    } catch (error) {
      if (messageEl) setMessage(messageEl, `Save failed: ${error.message}`, 'danger');
      else hks.showToast?.(`Save failed: ${error.message}`, 'danger');
    }
  }

  // ===========================================================================
  // MODELS section
  // ===========================================================================

  function renderModelDetails(el, rows) {
    if (!el) return;
    el.replaceChildren();
    rows.forEach(({ label, value }) => {
      const dt = document.createElement('dt');
      dt.textContent = label;
      const dd = document.createElement('dd');
      dd.textContent = value;
      el.append(dt, dd);
    });
  }

  function renderDownloadProgress(containerEl, labelEl, percentEl, fillEl, model) {
    const view = buildDownloadProgressModel(model);
    if (containerEl) containerEl.hidden = view.hidden;
    if (labelEl) labelEl.textContent = view.label;
    if (percentEl) percentEl.textContent = view.hidden ? '' : `${view.percent}%`;
    if (fillEl) fillEl.style.width = `${view.percent}%`;
  }

  function renderLlmPanel() {
    if (!llmPayload) return;
    const models = Array.isArray(llmPayload.models) ? llmPayload.models : [];
    if (els.llmSelect) {
      const current = els.llmSelect.value;
      els.llmSelect.replaceChildren(
        ...models.map((m) => {
          const opt = document.createElement('option');
          opt.value = m.id;
          opt.textContent = `${m.name || m.id}${m.installed ? '' : ' (not installed)'}`;
          return opt;
        }),
      );
      if (models.some((m) => m.id === current)) els.llmSelect.value = current;
      else if (llmPayload.selected_model_id) els.llmSelect.value = llmPayload.selected_model_id;
    }
    const visible = models.find((m) => m.id === els.llmSelect?.value) || models.find((m) => m.id === llmPayload.selected_model_id);
    if (els.llmBadge) {
      els.llmBadge.textContent = !visible ? 'Missing' : visible.id === llmPayload.selected_model_id ? 'Selected' : visible.installed ? 'Installed' : 'Missing';
      els.llmBadge.dataset.tone = visible?.installed ? 'success' : 'danger';
    }
    renderModelDetails(els.llmDetails, [
      { label: 'Selected', value: llmPayload.selected_model_id || 'none' },
      { label: 'Viewing', value: visible?.name || visible?.id || 'unknown' },
      { label: 'Install state', value: visible?.installed ? 'installed' : 'missing' },
      { label: 'Approx size', value: formatMb(visible?.size_mb) },
      { label: 'Runtime', value: llmPayload.llama_server_exists ? 'found' : 'missing' },
    ]);
    renderDownloadProgress(els.llmProgress, els.llmProgressLabel, els.llmProgressPercent, els.llmProgressFill, llmPayload.download_state);
  }

  function renderWhisperPanel() {
    if (!whisperPayload) return;
    const models = Array.isArray(whisperPayload.models) ? whisperPayload.models : [];
    if (els.whisperSelect) {
      const current = els.whisperSelect.value;
      els.whisperSelect.replaceChildren(
        ...models.map((m) => {
          const opt = document.createElement('option');
          opt.value = m.model_size;
          opt.textContent = `${m.model_size}${m.installed ? '' : ' (not installed)'}`;
          return opt;
        }),
      );
      if (models.some((m) => m.model_size === current)) els.whisperSelect.value = current;
      else if (whisperPayload.selected_model_size) els.whisperSelect.value = whisperPayload.selected_model_size;
    }
    const visibleSize = els.whisperSelect?.value || whisperPayload.selected_model_size;
    const visible = models.find((m) => m.model_size === visibleSize);
    if (els.whisperBadge) {
      els.whisperBadge.textContent = !visible ? 'Missing' : visibleSize === whisperPayload.selected_model_size ? 'Selected' : visible.installed ? 'Installed' : 'Missing';
      els.whisperBadge.dataset.tone = visible?.installed ? 'success' : 'danger';
    }
    const installed = models.filter((m) => m.installed).map((m) => m.model_size);
    renderModelDetails(els.whisperDetails, [
      { label: 'Selected', value: whisperPayload.selected_model_size || 'none' },
      { label: 'Viewing', value: visibleSize || 'none' },
      { label: 'Install state', value: visible?.installed ? 'installed' : 'missing' },
      { label: 'Installed', value: installed.length ? installed.join(', ') : 'none' },
    ]);
    renderDownloadProgress(els.whisperProgress, els.whisperProgressLabel, els.whisperProgressPercent, els.whisperProgressFill, whisperPayload.download_state);
  }

  function renderModelStatusSummary() {
    if (!els.modelsStatusSummary) return;
    const llmReady = llmPayload?.models?.some((m) => m.id === llmPayload.selected_model_id && m.installed);
    const whisperReady = whisperPayload?.models?.some((m) => m.model_size === whisperPayload.selected_model_size && m.installed);
    els.modelsStatusSummary.textContent = `LLM: ${llmReady ? 'ready' : 'needs download'} · Whisper: ${whisperReady ? 'ready' : 'needs download'}`;
  }

  /** Real refresh: fetches LLM + Whisper model lists and re-renders both panels. */
  async function refreshModels() {
    try {
      [llmPayload, whisperPayload] = await Promise.all([fetchLlmModels(), fetchWhisperModels()]);
      renderLlmPanel();
      renderWhisperPanel();
      renderModelStatusSummary();
      setMessage(els.modelsMessage, '', '');
    } catch (error) {
      setMessage(els.modelsMessage, `Could not load models: ${error.message}`, 'danger');
    }
  }

  /** Preview/test seeding: sets the model payloads directly (no network) and re-renders -- mirrors studioWorkspace.js's setPersonas(). */
  function setModelPayloads(llm, whisper) {
    llmPayload = llm || null;
    whisperPayload = whisper || null;
    renderLlmPanel();
    renderWhisperPanel();
    renderModelStatusSummary();
  }

  async function refreshModelRecommendation() {
    if (!els.modelsRecommendation) return;
    try {
      const rec = await fetchModelRecommendation();
      els.modelsRecommendation.textContent = rec?.summary || rec?.tier?.label || 'Recommendation unavailable.';
    } catch (error) {
      els.modelsRecommendation.textContent = `Recommendation unavailable: ${error.message}`;
    }
  }

  function renderWakeBackbones(list) {
    if (!els.wakeBackboneList) return;
    els.wakeBackboneList.replaceChildren();
    const items = Array.isArray(list) ? list : [];
    if (!items.length) {
      const empty = document.createElement('p');
      empty.className = 'sd-util-list__empty';
      empty.textContent = 'No wake-word backbones listed.';
      els.wakeBackboneList.append(empty);
      return;
    }
    items.forEach((backbone) => {
      const row = document.createElement('div');
      row.className = 'sd-util-list-row';
      const main = document.createElement('div');
      main.className = 'sd-util-list-row__main';
      const title = document.createElement('span');
      title.className = 'sd-util-list-row__title';
      title.textContent = backbone.name || backbone.id;
      const meta = document.createElement('span');
      meta.className = 'sd-util-list-row__meta';
      meta.textContent = backbone.installed ? 'Installed' : 'Not installed';
      main.append(title, meta);
      const actions = document.createElement('div');
      actions.className = 'sd-util-list-row__actions';
      if (!backbone.installed) {
        const dl = document.createElement('button');
        dl.type = 'button';
        dl.className = 'sd-btn';
        dl.textContent = 'Download';
        dl.addEventListener('click', () => handleDownloadWakeBackbone(backbone.id, dl));
        actions.append(dl);
      }
      row.append(main, actions);
      els.wakeBackboneList.append(row);
    });
  }

  async function handleDownloadWakeBackbone(id, buttonEl) {
    if (buttonEl) {
      buttonEl.disabled = true;
      buttonEl.textContent = 'Downloading…';
    }
    try {
      await downloadWakeModel(id);
      let done = false;
      for (let i = 0; i < 60 && !done; i += 1) {
        // eslint-disable-next-line no-await-in-loop -- bounded poll loop, same pattern main.js uses for model downloads.
        const state = await fetchWakeModelDownloadState(id).catch(() => null);
        done = !state || state.status === 'done' || state.status === 'complete' || state.status === 'error';
        if (!done) {
          // eslint-disable-next-line no-await-in-loop
          await new Promise((resolve) => setTimeout(resolve, 1000));
        }
      }
      await refreshWakeBackbones();
    } catch (error) {
      hks.showToast?.(`Download failed: ${error.message}`, 'danger');
    } finally {
      if (buttonEl) buttonEl.disabled = false;
    }
  }

  async function refreshWakeBackbones() {
    try {
      const res = await fetchWakeModels();
      if (els.wakeEngineBadge) els.wakeEngineBadge.textContent = Array.isArray(res?.backbones) && res.backbones.some((b) => b.installed) ? 'Ready' : 'Not installed';
      renderWakeBackbones(res?.backbones || []);
    } catch (error) {
      setMessage(els.modelsMessage, `Wake models unavailable: ${error.message}`, 'danger');
    }
  }

  async function refreshVoiceCloning() {
    try {
      const rec = await fetchModelRecommendation().catch(() => null);
      void rec; // recommendation call is independent; voice cloning has no GET status route wired to Utilities beyond provision
    } catch (_e) {
      // best-effort only
    }
  }

  function bindModelsSection() {
    els.modelsRefreshButton?.addEventListener?.('click', () => {
      refreshModels();
      refreshModelRecommendation();
      refreshWakeBackbones();
    });
    els.llmSelect?.addEventListener?.('change', () => renderLlmPanel());
    els.whisperSelect?.addEventListener?.('change', () => renderWhisperPanel());

    els.llmSelectButton?.addEventListener?.('click', async () => {
      const id = els.llmSelect?.value;
      if (!id) return;
      try {
        await selectLlmModel(id);
        hks.showToast?.('LLM model selected.', 'success', 1500);
        await refreshModels();
      } catch (error) {
        setMessage(els.modelsMessage, `Select failed: ${error.message}`, 'danger');
      }
    });
    els.llmDownloadButton?.addEventListener?.('click', async () => {
      const id = els.llmSelect?.value;
      if (!id) return;
      try {
        await downloadLlmModel(id);
        await refreshModels();
      } catch (error) {
        setMessage(els.modelsMessage, `Download failed: ${error.message}`, 'danger');
      }
    });
    els.llmDeleteButton?.addEventListener?.('click', async () => {
      const id = els.llmSelect?.value;
      if (!id) return;
      if (!confirmFn(`Delete LLM model "${id}"? This cannot be undone.`)) return;
      try {
        await deleteLlmModel(id, undefined, { confirmed: true });
        await refreshModels();
      } catch (error) {
        setMessage(els.modelsMessage, `Delete failed: ${error.message}`, 'danger');
      }
    });
    els.llmUnloadButton?.addEventListener?.('click', async () => {
      try {
        await unloadModel('llm');
        hks.showToast?.('LLM unloaded.', 'success', 1500);
      } catch (error) {
        setMessage(els.modelsMessage, `Unload failed: ${error.message}`, 'danger');
      }
    });

    els.whisperSelectButton?.addEventListener?.('click', async () => {
      const size = els.whisperSelect?.value;
      if (!size) return;
      try {
        await selectWhisperModel(size);
        hks.showToast?.('Whisper model selected.', 'success', 1500);
        await refreshModels();
      } catch (error) {
        setMessage(els.modelsMessage, `Select failed: ${error.message}`, 'danger');
      }
    });
    els.whisperDownloadButton?.addEventListener?.('click', async () => {
      const size = els.whisperSelect?.value;
      if (!size) return;
      try {
        await downloadWhisperModel(size);
        await refreshModels();
      } catch (error) {
        setMessage(els.modelsMessage, `Download failed: ${error.message}`, 'danger');
      }
    });
    els.whisperDeleteButton?.addEventListener?.('click', async () => {
      const size = els.whisperSelect?.value;
      if (!size) return;
      if (!confirmFn(`Delete Whisper model "${size}"? This cannot be undone.`)) return;
      try {
        await deleteWhisperModel(size, undefined, { confirmed: true });
        await refreshModels();
      } catch (error) {
        setMessage(els.modelsMessage, `Delete failed: ${error.message}`, 'danger');
      }
    });
    els.whisperUnloadButton?.addEventListener?.('click', async () => {
      try {
        await unloadModel('stt');
        hks.showToast?.('Whisper (STT) unloaded.', 'success', 1500);
      } catch (error) {
        setMessage(els.modelsMessage, `Unload failed: ${error.message}`, 'danger');
      }
    });

    els.unloadTtsButton?.addEventListener?.('click', async () => {
      try {
        await unloadModel('tts');
        hks.showToast?.('TTS unloaded.', 'success', 1500);
      } catch (error) {
        setMessage(els.modelsMessage, `Unload failed: ${error.message}`, 'danger');
      }
    });

    els.voiceCloningProvisionButton?.addEventListener?.('click', async () => {
      if (els.voiceCloningProvisionButton) els.voiceCloningProvisionButton.disabled = true;
      setMessage(els.modelsMessage, 'Installing voice cloning…', 'info');
      try {
        const res = await provisionVoiceCloning();
        if (els.voiceCloningBadge) els.voiceCloningBadge.textContent = res?.cloning?.provisioned || res?.already_provisioned ? 'Installed' : 'Pending';
        if (els.voiceCloningStatus) els.voiceCloningStatus.textContent = res?.message || 'Voice cloning is ready.';
        setMessage(els.modelsMessage, '', '');
      } catch (error) {
        setMessage(els.modelsMessage, `Install failed: ${error.message}`, 'danger');
      } finally {
        if (els.voiceCloningProvisionButton) els.voiceCloningProvisionButton.disabled = false;
      }
    });
  }

  // ===========================================================================
  // SPEECH INPUT section: audio device
  // ===========================================================================

  function renderAudioDeviceStub() {
    if (!els.audioDeviceSelect) return;
    els.audioDeviceSelect.replaceChildren();
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'System default (device list needs main.js composition)';
    els.audioDeviceSelect.append(opt);
    els.audioDeviceSelect.disabled = true;
  }

  /** Preview/test seeding: populate the device select from plain data (bypasses the TODO(phase-integration) network gap above). */
  function setAudioDevices(devices) {
    if (!els.audioDeviceSelect) return;
    const list = Array.isArray(devices) ? devices : [];
    els.audioDeviceSelect.disabled = false;
    els.audioDeviceSelect.replaceChildren(
      ...list.map((d) => {
        const opt = document.createElement('option');
        opt.value = String(d.index);
        opt.textContent = d.name;
        return opt;
      }),
    );
  }

  function stopMicTest() {
    if (micAnimationFrame) cancelAnimationFrame(micAnimationFrame);
    micAnimationFrame = null;
    if (micStream) {
      micStream.getTracks().forEach((t) => t.stop());
      micStream = null;
    }
    if (els.audioMeterFill) els.audioMeterFill.style.width = '0%';
    if (els.audioTestMicButton) els.audioTestMicButton.textContent = 'Test Browser Microphone Access';
  }

  async function startMicTest() {
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setMessage(els.audioMessage, 'Microphone access is unavailable in this environment.', 'danger');
      return;
    }
    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (els.audioTestMicButton) els.audioTestMicButton.textContent = 'Stop Microphone Test';
      setMessage(els.audioMessage, 'Listening…', 'info');
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const audioCtx = new AudioCtx();
      const source = audioCtx.createMediaStreamSource(micStream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteTimeDomainData(data);
        let sumSquares = 0;
        for (let i = 0; i < data.length; i += 1) {
          const norm = (data[i] - 128) / 128;
          sumSquares += norm * norm;
        }
        const rms = Math.sqrt(sumSquares / data.length);
        if (els.audioMeterFill) els.audioMeterFill.style.width = `${clampPct(rms * 300)}%`;
        micAnimationFrame = requestAnimationFrame(tick);
      };
      tick();
    } catch (error) {
      setMessage(els.audioMessage, `Microphone access failed: ${error.message}`, 'danger');
    }
  }

  function bindAudioDeviceSection() {
    renderAudioDeviceStub();
    els.audioTestMicButton?.addEventListener?.('click', () => {
      if (micStream) stopMicTest();
      else startMicTest();
    });
  }

  // ===========================================================================
  // SPEECH INPUT section: hotkeys
  // ===========================================================================

  function currentHotkeyMap() {
    const map = {};
    for (const key of HOTKEY_FIELD_KEYS) {
      map[key] = els.hotkeyFields?.[key]?.input?.value || '';
    }
    return map;
  }

  function renderHotkeyCollisions() {
    const collisions = detectHotkeyCollisions(currentHotkeyMap());
    for (const key of HOTKEY_FIELD_KEYS) {
      const errorEl = els.hotkeyFields?.[key]?.error;
      if (errorEl) errorEl.textContent = collisions[key] || '';
    }
    return collisions;
  }

  function wireHotkeyRecorder(fieldKey) {
    const refs = els.hotkeyFields?.[fieldKey];
    if (!refs?.input) return;
    const input = refs.input;
    let recording = false;

    function stopRecording() {
      recording = false;
      input.classList?.remove('is-recording');
      document.removeEventListener('keydown', onKeyDown, true);
    }

    function onKeyDown(event) {
      if (!recording) return;
      event.preventDefault();
      if (event.key === 'Escape') {
        stopRecording();
        return;
      }
      const chord = describeKeyEvent(event);
      const isBareModifier = MODIFIER_KEY_NAMES.has(event.key);
      if (isBareModifier) return; // wait for the real key alongside the modifier
      input.value = chord;
      stopRecording();
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }

    input.addEventListener('click', () => {
      recording = true;
      input.classList?.add('is-recording');
      input.value = 'Press a key…';
      document.addEventListener('keydown', onKeyDown, true);
    });
    input.addEventListener('blur', stopRecording);

    input.addEventListener('change', () => {
      renderHotkeyCollisions();
      patchProfileSetting(fieldKey, input.value, { messageEl: els.hotkeyMessage });
    });

    refs.clear?.addEventListener?.('click', () => {
      input.value = '';
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
  }

  async function refreshHotkeys() {
    const settings = await refreshProfileSettings();
    for (const key of HOTKEY_FIELD_KEYS) {
      const input = els.hotkeyFields?.[key]?.input;
      if (input) input.value = settings[key] || '';
    }
    renderHotkeyCollisions();
  }

  async function refreshHotkeyCapabilities() {
    try {
      const capabilities = await fetchCapabilities();
      if (els.hotkeySessionIndicator) {
        els.hotkeySessionIndicator.textContent = `${capabilities.platform ?? 'unknown'} (${capabilities.session_type ?? 'unknown'})`;
      }
      if (els.hotkeyWaylandWarning) els.hotkeyWaylandWarning.hidden = !capabilities.is_wayland;
      return capabilities;
    } catch (error) {
      setMessage(els.hotkeyMessage, `Capabilities unavailable: ${error.message}`, 'danger');
      return null;
    }
  }

  function bindHotkeysSection() {
    if (els.hotkeyControllerNote) {
      els.hotkeyControllerNote.textContent =
        'Controller/gamepad buttons are not separately bindable today — remap them to a keyboard key at the OS level and they will register the same as that keypress.';
    }
    HOTKEY_FIELD_KEYS.forEach(wireHotkeyRecorder);
  }

  // ===========================================================================
  // SPEECH INPUT section: wake word
  // ===========================================================================

  async function refreshWakeStatus() {
    try {
      const status = await fetchWakeStatus();
      if (els.wakeEnabledToggle) els.wakeEnabledToggle.checked = Boolean(status?.enabled);
      if (els.wakeStatusDetail) els.wakeStatusDetail.textContent = status?.detail || (status?.enabled ? 'Wake word is active.' : 'Wake word is off.');
    } catch (error) {
      setMessage(els.wakeMessage, `Wake status unavailable: ${error.message}`, 'danger');
    }
  }

  async function refreshWakeTuningFromProfile() {
    const settings = await refreshProfileSettings();
    if (els.wakeSensitivity) els.wakeSensitivity.value = settings.wake_word_sensitivity ?? '';
    if (els.wakeCooldown) els.wakeCooldown.value = settings.wake_word_cooldown_s ?? '';
    if (els.wakeMaxRecording) els.wakeMaxRecording.value = settings.wake_word_max_recording_s ?? '';
    if (els.wakeModelSelect) els.wakeModelSelect.value = settings.wake_word_model ?? '';
  }

  let wakeTrainPollTimer = null;

  function stopWakeTrainPoll() {
    if (wakeTrainPollTimer) clearInterval(wakeTrainPollTimer);
    wakeTrainPollTimer = null;
  }

  function bindWakeWordSection() {
    els.wakeEnabledToggle?.addEventListener?.('change', async () => {
      const on = Boolean(els.wakeEnabledToggle.checked);
      try {
        if (on) await enableWake();
        else await disableWake();
        await refreshWakeStatus();
      } catch (error) {
        els.wakeEnabledToggle.checked = !on;
        setMessage(els.wakeMessage, `Could not ${on ? 'enable' : 'disable'} wake word: ${error.message}`, 'danger');
      }
    });

    els.wakeModelSelect?.addEventListener?.('change', () => {
      patchProfileSetting('wake_word_model', els.wakeModelSelect.value, { messageEl: els.wakeMessage });
    });

    els.wakeImportButton?.addEventListener?.('click', () => els.wakeImportFile?.click?.());
    els.wakeImportFile?.addEventListener?.('change', async () => {
      const file = els.wakeImportFile.files?.[0];
      if (!file) return;
      setMessage(els.wakeImportStatus, 'Importing…', 'info');
      try {
        await importWakeModel(file, file.name.replace(/\.onnx$/i, ''));
        setMessage(els.wakeImportStatus, 'Imported.', 'success');
      } catch (error) {
        setMessage(els.wakeImportStatus, `Import failed: ${error.message}`, 'danger');
      }
    });

    els.wakeTrainButton?.addEventListener?.('click', async () => {
      const phrase = els.wakeTrainPhrase?.value?.trim();
      if (!phrase) {
        hks.showToast?.('Enter a phrase to train first.', 'warning');
        return;
      }
      if (els.wakeTrainButton) els.wakeTrainButton.disabled = true;
      if (els.wakeTrainProgress) els.wakeTrainProgress.hidden = false;
      setMessage(els.wakeTrainResult, '', '');
      try {
        await trainWakePhrase(phrase);
        stopWakeTrainPoll();
        wakeTrainPollTimer = setInterval(async () => {
          try {
            const status = await fetchWakeTrainStatus();
            if (els.wakeTrainProgressLabel) els.wakeTrainProgressLabel.textContent = status?.message || status?.status || 'Training…';
            const pct = clampPct(status?.percent ?? 0);
            if (els.wakeTrainProgressPercent) els.wakeTrainProgressPercent.textContent = `${pct}%`;
            if (els.wakeTrainProgressFill) els.wakeTrainProgressFill.style.width = `${pct}%`;
            if (status?.status === 'done' || status?.status === 'complete' || status?.result) {
              stopWakeTrainPoll();
              if (els.wakeTrainProgress) els.wakeTrainProgress.hidden = true;
              if (els.wakeTrainButton) els.wakeTrainButton.disabled = false;
              setMessage(els.wakeTrainResult, formatWakeTrainVerdict(status.result) || 'Training complete.', 'success');
            } else if (status?.status === 'error') {
              stopWakeTrainPoll();
              if (els.wakeTrainProgress) els.wakeTrainProgress.hidden = true;
              if (els.wakeTrainButton) els.wakeTrainButton.disabled = false;
              setMessage(els.wakeTrainResult, status.message || 'Training failed.', 'danger');
            }
          } catch (_pollError) {
            stopWakeTrainPoll();
            if (els.wakeTrainButton) els.wakeTrainButton.disabled = false;
          }
        }, 2000);
      } catch (error) {
        if (els.wakeTrainProgress) els.wakeTrainProgress.hidden = true;
        if (els.wakeTrainButton) els.wakeTrainButton.disabled = false;
        setMessage(els.wakeTrainResult, `Training failed: ${error.message}`, 'danger');
      }
    });

    els.wakeSensitivity?.addEventListener?.('change', () => {
      patchProfileSetting('wake_word_sensitivity', Number(els.wakeSensitivity.value), { messageEl: els.wakeMessage });
    });
    els.wakeCooldown?.addEventListener?.('change', () => {
      patchProfileSetting('wake_word_cooldown_s', Number(els.wakeCooldown.value), { messageEl: els.wakeMessage });
    });
    els.wakeMaxRecording?.addEventListener?.('change', () => {
      patchProfileSetting('wake_word_max_recording_s', Number(els.wakeMaxRecording.value), { messageEl: els.wakeMessage });
    });

    els.wakeTestButton?.addEventListener?.('click', async () => {
      if (els.wakeTestButton) els.wakeTestButton.disabled = true;
      setMessage(els.wakeTestResult, 'Listening for 10s…', 'info');
      try {
        const res = await testWake(10);
        const peak = clampPct((res?.peak_score || 0) * 100);
        if (els.wakeScoreFill) els.wakeScoreFill.style.width = `${peak}%`;
        setMessage(els.wakeTestResult, `Peak score: ${peak}% over ${res?.sample_count ?? 0} samples.`, 'success');
      } catch (error) {
        setMessage(els.wakeTestResult, `Test failed: ${error.message}`, 'danger');
      } finally {
        if (els.wakeTestButton) els.wakeTestButton.disabled = false;
      }
    });
  }

  // ===========================================================================
  // TEXT TOOLS section: dictionary / macros
  // ===========================================================================

  function renderDictionaryList(terms) {
    if (!els.dictionaryList) return;
    els.dictionaryList.replaceChildren();
    const list = Array.isArray(terms) ? terms : [];
    if (!list.length) {
      const empty = document.createElement('span');
      empty.className = 'sd-util-list__empty';
      empty.textContent = 'No terms yet.';
      els.dictionaryList.append(empty);
      return;
    }
    list.forEach((term) => {
      const chip = document.createElement('span');
      chip.className = 'sd-chip';
      chip.textContent = term;
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'sd-util-chip-remove';
      remove.setAttribute('aria-label', `Remove ${term}`);
      remove.textContent = '×';
      remove.addEventListener('click', () => handleRemoveDictionaryTerm(term));
      chip.append(remove);
      els.dictionaryList.append(chip);
    });
  }

  async function handleRemoveDictionaryTerm(term) {
    try {
      const payload = await deleteDictionaryTerm(term);
      renderDictionaryList(payload?.terms || []);
    } catch (error) {
      setMessage(els.dictionaryMessage, `Could not remove term: ${error.message}`, 'danger');
    }
  }

  function renderDictionarySuggestions(suggestions) {
    if (!els.dictionarySuggestions) return;
    els.dictionarySuggestions.replaceChildren();
    const list = Array.isArray(suggestions) ? suggestions : [];
    if (els.dictionarySuggestGroup) els.dictionarySuggestGroup.hidden = list.length === 0;
    list.forEach((term) => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'sd-chip';
      chip.textContent = `+ ${term}`;
      chip.addEventListener('click', () => handleAddDictionaryTerm(term));
      els.dictionarySuggestions.append(chip);
    });
  }

  async function handleAddDictionaryTerm(term) {
    const value = (term ?? els.dictionaryInput?.value ?? '').trim();
    if (!value) return;
    try {
      const payload = await addDictionaryTerm(value);
      renderDictionaryList(payload?.terms || []);
      if (els.dictionaryInput) els.dictionaryInput.value = '';
    } catch (error) {
      setMessage(els.dictionaryMessage, `Could not add term: ${error.message}`, 'danger');
    }
  }

  async function refreshDictionary() {
    try {
      const payload = await fetchDictionary();
      renderDictionaryList(payload?.terms || []);
    } catch (error) {
      setMessage(els.dictionaryMessage, `Dictionary unavailable: ${error.message}`, 'danger');
    }
  }

  /** TODO(phase-integration): main.js's draft-edit save path should call this once Talk owns a real draft editor -- see SPEC GAP 3 in the file header. Exposed here so it is real and callable, not merely a stub. */
  async function suggestFromEdit(rawText, editedText) {
    try {
      const res = await suggestDictionaryTerms(rawText, editedText);
      renderDictionarySuggestions(res?.suggestions || []);
      return res?.suggestions || [];
    } catch (_error) {
      return [];
    }
  }

  function renderMacrosList(macros) {
    if (!els.macrosList) return;
    els.macrosList.replaceChildren();
    const list = Array.isArray(macros) ? macros : [];
    if (!list.length) {
      const empty = document.createElement('span');
      empty.className = 'sd-util-list__empty';
      empty.textContent = 'No macros yet.';
      els.macrosList.append(empty);
      return;
    }
    list.forEach((macro) => {
      const row = document.createElement('div');
      row.className = 'sd-util-list-row';
      const main = document.createElement('div');
      main.className = 'sd-util-list-row__main';
      const title = document.createElement('span');
      title.className = 'sd-util-list-row__title';
      title.textContent = `${macro.trigger} → ${macro.expansion}`;
      main.append(title);
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'sd-util-chip-remove';
      remove.setAttribute('aria-label', `Remove ${macro.trigger}`);
      remove.textContent = '×';
      remove.addEventListener('click', () => handleRemoveMacro(macro.trigger));
      row.append(main, remove);
      els.macrosList.append(row);
    });
  }

  async function handleRemoveMacro(trigger) {
    try {
      const payload = await deleteMacro(trigger);
      renderMacrosList(payload?.macros || []);
    } catch (error) {
      setMessage(els.macrosMessage, `Could not remove macro: ${error.message}`, 'danger');
    }
  }

  async function refreshMacros() {
    try {
      const payload = await fetchMacros();
      renderMacrosList(payload?.macros || []);
    } catch (error) {
      setMessage(els.macrosMessage, `Macros unavailable: ${error.message}`, 'danger');
    }
  }

  async function refreshMacrosEnabled() {
    const settings = await refreshProfileSettings();
    if (els.macrosEnabledToggle) els.macrosEnabledToggle.checked = settings.macros_enabled !== false;
  }

  function bindTextToolsSection() {
    els.dictionaryAddButton?.addEventListener?.('click', () => handleAddDictionaryTerm());
    els.dictionaryInput?.addEventListener?.('keydown', (event) => {
      if (event.key === 'Enter') handleAddDictionaryTerm();
    });

    els.macroAddButton?.addEventListener?.('click', async () => {
      const trigger = els.macroTrigger?.value?.trim();
      const expansion = els.macroExpansion?.value?.trim();
      if (!trigger || !expansion) {
        hks.showToast?.('A macro needs both a trigger and an expansion.', 'warning');
        return;
      }
      try {
        const payload = await addMacro(trigger, expansion);
        renderMacrosList(payload?.macros || []);
        if (els.macroTrigger) els.macroTrigger.value = '';
        if (els.macroExpansion) els.macroExpansion.value = '';
      } catch (error) {
        setMessage(els.macrosMessage, `Could not add macro: ${error.message}`, 'danger');
      }
    });
    els.macroExpansion?.addEventListener?.('keydown', (event) => {
      if (event.key === 'Enter') els.macroAddButton?.click?.();
    });

    els.macrosEnabledToggle?.addEventListener?.('change', () => {
      patchProfileSetting('macros_enabled', Boolean(els.macrosEnabledToggle.checked), { messageEl: els.macrosMessage });
    });

    // Message Rescue: draft-bound live panel (features/messageRescueDraft.js,
    // reused verbatim). Its own init already no-ops if #draftRescuePanel is
    // absent or the pref_message_rescue_enabled flag is off -- exactly the
    // same contract it has in main.js today.
    messageRescueDraftFeature = initMessageRescueDraft({
      hooks: {
        applyToEditor: (text) => {
          if (hks.applyMessageRescueToEditor) hks.applyMessageRescueToEditor(text);
          else hks.showToast?.('No draft editor to apply to yet in this workspace.', 'warning');
        },
      },
    });
    // messageRescuePanel.js (static preview) and textPlayground.js
    // (playground) already self-initialized via the side-effect imports at
    // the top of this file -- nothing further to wire here.
  }

  // ===========================================================================
  // DIAGNOSTICS section
  // ===========================================================================

  function renderDoctorCards(doctorPayload) {
    if (!els.doctorCardsGrid) return;
    const model = buildDoctorModel(doctorPayload);
    els.doctorCardsGrid.replaceChildren();
    model.cards.forEach((card) => {
      const el = document.createElement('div');
      el.className = 'sd-util-doctor-card';
      const title = document.createElement('span');
      title.className = 'sd-util-doctor-card__title';
      title.textContent = card.title;
      const status = document.createElement('span');
      status.className = 'sd-util-doctor-card__status';
      status.dataset.tone = card.tone;
      status.textContent = card.status;
      const detail = document.createElement('div');
      detail.className = 'sd-util-doctor-card__detail';
      detail.textContent = card.detailLines.join(' · ');
      el.append(title, status, detail);
      els.doctorCardsGrid.append(el);
    });
    if (els.doctorRecoveryPanel && els.doctorRecoveryList) {
      els.doctorRecoveryList.replaceChildren();
      els.doctorRecoveryPanel.hidden = model.recovery.length === 0;
      model.recovery.forEach((item) => {
        const row = document.createElement('div');
        row.className = 'sd-util-list-row';
        row.textContent = `[${item.label}] ${item.text}`;
        els.doctorRecoveryList.append(row);
      });
    }
  }

  async function refreshDoctor() {
    if (els.doctorRefreshButton) {
      els.doctorRefreshButton.disabled = true;
      els.doctorRefreshButton.textContent = 'Running check…';
    }
    try {
      const doctor = await fetchDoctor(true);
      renderDoctorCards(doctor);
    } catch (error) {
      if (els.doctorCardsGrid) {
        els.doctorCardsGrid.replaceChildren();
        const err = document.createElement('span');
        err.className = 'sd-util-list__empty';
        err.textContent = `Doctor check failed: ${error.message}`;
        els.doctorCardsGrid.append(err);
      }
    } finally {
      if (els.doctorRefreshButton) {
        els.doctorRefreshButton.disabled = false;
        els.doctorRefreshButton.textContent = 'Run Doctor Check';
      }
    }
  }

  function renderMetricsHud(metrics) {
    if (!els.metricsHud) return;
    els.metricsHud.replaceChildren();
    const stages = metrics?.stages || metrics || {};
    const table = document.createElement('table');
    table.className = 'sd-util-metrics-table';
    const thead = document.createElement('tr');
    ['Stage', 'Last', 'Avg', 'p50', 'p95'].forEach((h) => {
      const th = document.createElement('th');
      th.textContent = h;
      thead.append(th);
    });
    table.append(thead);
    Object.entries(stages).forEach(([name, stat]) => {
      const row = document.createElement('tr');
      [name, stat?.last, stat?.avg, stat?.p50, stat?.p95].forEach((val, i) => {
        const cell = document.createElement('td');
        cell.textContent = i === 0 ? String(val) : val === undefined || val === null ? '—' : `${Math.round(val)}ms`;
        row.append(cell);
      });
      table.append(row);
    });
    els.metricsHud.append(table);
  }

  async function refreshMetrics() {
    try {
      const metrics = await fetchMetrics();
      renderMetricsHud(metrics);
    } catch (error) {
      if (els.metricsHud) els.metricsHud.textContent = `Metrics unavailable: ${error.message}`;
    }
  }

  function renderRecordingsList(recordings) {
    if (!els.recordingsList) return;
    els.recordingsList.replaceChildren();
    const list = Array.isArray(recordings) ? recordings : [];
    if (!list.length) {
      const empty = document.createElement('p');
      empty.className = 'sd-util-list__empty';
      empty.textContent = 'No saved recordings.';
      els.recordingsList.append(empty);
      return;
    }
    list.forEach((rec) => {
      const row = document.createElement('div');
      row.className = 'sd-util-list-row';
      const main = document.createElement('div');
      main.className = 'sd-util-list-row__main';
      const meta = document.createElement('span');
      meta.className = 'sd-util-list-row__meta';
      meta.textContent = formatRecordingRow(rec);
      main.append(meta);
      const actions = document.createElement('div');
      actions.className = 'sd-util-list-row__actions';
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'sd-btn';
      retry.textContent = 'Re-transcribe';
      retry.addEventListener('click', async () => {
        try {
          await retranscribeRecording(rec.id);
          hks.showToast?.('Re-transcribed — check Library for the new draft.', 'success');
        } catch (error) {
          hks.showToast?.(`Re-transcribe failed: ${error.message}`, 'danger');
        }
      });
      const discard = document.createElement('button');
      discard.type = 'button';
      discard.className = 'sd-btn';
      discard.textContent = 'Discard';
      discard.addEventListener('click', async () => {
        try {
          await deleteRecording(rec.id);
          await refreshRecordings();
        } catch (error) {
          hks.showToast?.(`Discard failed: ${error.message}`, 'danger');
        }
      });
      actions.append(retry, discard);
      row.append(main, actions);
      els.recordingsList.append(row);
    });
  }

  async function refreshRecordings() {
    try {
      const payload = await fetchRecordings();
      renderRecordingsList(payload?.recordings || []);
    } catch (error) {
      setMessage(els.recordingsMessage, `Recordings unavailable: ${error.message}`, 'danger');
    }
  }

  function renderJobsList(jobs) {
    if (!els.jobsList) return;
    els.jobsList.replaceChildren();
    const list = Array.isArray(jobs) ? jobs : [];
    if (!list.length) {
      const empty = document.createElement('p');
      empty.className = 'sd-util-list__empty';
      empty.textContent = 'No active jobs.';
      els.jobsList.append(empty);
      return;
    }
    list.forEach((job) => {
      const row = document.createElement('div');
      row.className = 'sd-util-list-row';
      const meta = document.createElement('span');
      meta.className = 'sd-util-list-row__meta';
      meta.textContent = formatJobRow(job);
      const cancel = document.createElement('button');
      cancel.type = 'button';
      cancel.className = 'sd-btn';
      cancel.textContent = 'Cancel';
      cancel.disabled = Boolean(job.cancel_requested);
      cancel.addEventListener('click', async () => {
        try {
          await cancelJob(job.id);
          await refreshJobsList();
        } catch (error) {
          hks.showToast?.(`Cancel failed: ${error.message}`, 'danger');
        }
      });
      row.append(meta, cancel);
      els.jobsList.append(row);
    });
  }

  async function refreshJobsList() {
    try {
      const payload = await fetchJobs(true);
      renderJobsList(payload?.jobs || []);
    } catch (error) {
      if (els.jobsList) els.jobsList.textContent = `Jobs unavailable: ${error.message}`;
    }
  }

  function renderSidecarLogs(lines) {
    if (!els.sidecarLogsTail) return;
    const list = Array.isArray(lines) ? lines : [];
    els.sidecarLogsTail.textContent = list.length ? list.join('\n') : 'No sidecar logs yet.';
  }

  async function refreshSidecarLogs() {
    try {
      const logs = await window.betterFingers?.getSidecarLogs?.();
      renderSidecarLogs(Array.isArray(logs) ? logs : logs?.lines);
    } catch (_error) {
      renderSidecarLogs([]);
    }
  }

  async function refreshSidecarStatus() {
    if (!els.sidecarStatus) return;
    try {
      const status = await window.betterFingers?.getSidecarStatus?.();
      els.sidecarStatus.textContent = status ? JSON.stringify(status) : 'unavailable';
    } catch (_error) {
      els.sidecarStatus.textContent = 'unavailable';
    }
  }

  // `el` is expected to already BE the <dl class="sd-util-model-details">
  // container (see signal-desk-preview.html's Capabilities/Runtime Status/
  // Diagnostics Paths dumps) -- dt/dd pairs are appended directly into it
  // rather than nesting a second <dl>, which is both invalid HTML and would
  // silently defeat the `.sd-util-model-details dt/dd` selector.
  function renderDetailList(el, data, keys) {
    if (!el) return;
    el.replaceChildren();
    const source = data || {};
    (keys || Object.keys(source)).forEach((key) => {
      const dt = document.createElement('dt');
      dt.textContent = key;
      const dd = document.createElement('dd');
      const value = source[key];
      dd.textContent = value === undefined || value === null ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value);
      el.append(dt, dd);
    });
  }

  async function refreshDiagnosticsPaths() {
    try {
      const paths = await fetchDiagnosticsPaths();
      renderDetailList(els.diagnosticsPathsList, paths);
    } catch (error) {
      if (els.diagnosticsPathsList) els.diagnosticsPathsList.textContent = `Paths unavailable: ${error.message}`;
    }
  }

  function renderRuntimeErrors(errors) {
    if (!els.runtimeErrorsList) return;
    els.runtimeErrorsList.replaceChildren();
    const list = (Array.isArray(errors) ? errors : []).slice(-8).reverse();
    if (!list.length) {
      const empty = document.createElement('span');
      empty.className = 'sd-util-list__empty';
      empty.textContent = 'No runtime errors recorded.';
      els.runtimeErrorsList.append(empty);
      return;
    }
    list.forEach((err) => {
      const row = document.createElement('div');
      row.className = 'sd-util-list-row';
      row.textContent = `[${err.severity || 'recoverable'}] ${err.component || 'runtime'}: ${err.message || 'Unknown error'}`;
      els.runtimeErrorsList.append(row);
    });
  }

  async function refreshRuntimeErrors() {
    try {
      const payload = await fetchRuntimeErrors();
      renderRuntimeErrors(payload?.errors || []);
    } catch (_error) {
      renderRuntimeErrors([]);
    }
  }

  async function refreshDebugLogTail() {
    if (!els.debugLogTail) return;
    try {
      const payload = await fetchDiagnosticsLogs(80);
      const lines = payload?.lines || payload?.text || '';
      els.debugLogTail.textContent = Array.isArray(lines) ? lines.join('\n') : String(lines || 'No log lines.');
    } catch (error) {
      els.debugLogTail.textContent = `Log unavailable: ${error.message}`;
    }
  }

  async function refreshAllDiagnostics() {
    await Promise.all([
      refreshDoctor(),
      refreshMetrics(),
      refreshRecordings(),
      refreshJobsList(),
      refreshSidecarLogs(),
      refreshSidecarStatus(),
      refreshDiagnosticsPaths(),
      refreshRuntimeErrors(),
      refreshDebugLogTail(),
    ]);
  }

  function bindDiagnosticsSection() {
    els.doctorRefreshButton?.addEventListener?.('click', () => refreshDoctor());
    els.recordingsClearButton?.addEventListener?.('click', async () => {
      if (!confirmFn('Clear all saved recordings? This cannot be undone.')) return;
      try {
        await clearRecordings();
        await refreshRecordings();
      } catch (error) {
        setMessage(els.recordingsMessage, `Clear failed: ${error.message}`, 'danger');
      }
    });
    els.sidecarLogsClearButton?.addEventListener?.('click', () => renderSidecarLogs([]));
    els.copySupportReportButton?.addEventListener?.('click', async () => {
      try {
        const report = await fetchSupportReport();
        const markdown = report?.markdown || report?.report || JSON.stringify(report);
        await window.betterFingers?.writeClipboardText?.(markdown);
        hks.showToast?.('Support report copied to clipboard.', 'success');
      } catch (error) {
        setMessage(els.diagnosticsMessage, `Support report failed: ${error.message}`, 'danger');
      }
    });
    els.refreshDiagnosticsButton?.addEventListener?.('click', () => refreshAllDiagnostics());
  }

  // ===========================================================================
  // ADVANCED section (warmup / residency / dumps / send & injection)
  // ===========================================================================

  async function refreshResidencyFromProfile() {
    const settings = await refreshProfileSettings();
    if (els.keepLlm) els.keepLlm.checked = Boolean(settings.model_keep_llm_loaded);
    if (els.keepStt) els.keepStt.checked = Boolean(settings.model_keep_stt_loaded);
    if (els.keepTts) els.keepTts.checked = Boolean(settings.model_keep_tts_loaded);
    if (els.audioDucking) els.audioDucking.checked = Boolean(settings.audio_ducking);
  }

  async function refreshCapabilitiesDump() {
    try {
      const capabilities = await fetchCapabilities();
      renderDetailList(els.capabilitiesList, capabilities, [
        'platform', 'session_type', 'is_linux', 'is_wayland', 'is_x11',
        'supports_basic_clipboard', 'supports_rich_clipboard_restore',
        'supports_input_injection', 'injection_method', 'supports_typing',
        'supports_global_hotkeys', 'supports_audio_ducking',
        'supports_stt', 'supports_llm', 'supports_tts',
      ]);
      if (els.waylandInjectionWarning) els.waylandInjectionWarning.hidden = !(capabilities.is_wayland && !capabilities.supports_input_injection);
      if (els.injectionUnavailableWarning) els.injectionUnavailableWarning.hidden = capabilities.supports_input_injection !== false;
      if (els.audioDucking) els.audioDucking.disabled = capabilities.supports_audio_ducking === false;
      if (els.audioDuckingWarning) els.audioDuckingWarning.hidden = capabilities.supports_audio_ducking !== false;
    } catch (error) {
      if (els.capabilitiesList) els.capabilitiesList.textContent = `Capabilities unavailable: ${error.message}`;
    }
  }

  async function refreshRuntimeStatusDump() {
    try {
      const status = await fetchRuntimeStatus();
      renderDetailList(els.runtimeStatusList, status);
    } catch (error) {
      if (els.runtimeStatusList) els.runtimeStatusList.textContent = `Runtime status unavailable: ${error.message}`;
    }
  }

  async function refreshOutputSettingsSummary() {
    if (!els.outputSettingsSummary) return;
    try {
      const settings = await fetchOutputSettings();
      els.outputSettingsSummary.textContent = `Send mode: ${settings?.send_mode ?? 'unknown'} · Auto-submit: ${settings?.auto_submit ? 'on' : 'off'} · Pending sends: ${settings?.pending_sends ?? 0}`;
    } catch (error) {
      els.outputSettingsSummary.textContent = `Unavailable: ${error.message}`;
    }
  }

  function bindAdvancedSection() {
    els.warmupSttButton?.addEventListener?.('click', () => runWarmup({ stt: true }, 'STT'));
    els.warmupLlmButton?.addEventListener?.('click', () => runWarmup({ llm: true }, 'LLM'));
    els.startHotkeysButton?.addEventListener?.('click', () => runWarmup({ hotkeys: true }, 'Hotkeys'));
    els.testModelLoadButton?.addEventListener?.('click', () => runWarmup({ llm: true }, 'Model load test'));

    els.primaryActionButton?.addEventListener?.('click', async () => {
      try {
        await runPrimaryAction();
        setMessage(els.warmupMessage, 'Primary action ran.', 'success');
      } catch (error) {
        setMessage(els.warmupMessage, `Primary action failed: ${error.message}`, 'danger');
      }
    });
    els.emergencyStopButton?.addEventListener?.('click', async () => {
      try {
        await emergencyStop();
        setMessage(els.warmupMessage, 'Emergency stop sent.', 'success');
      } catch (error) {
        setMessage(els.warmupMessage, `Emergency stop failed: ${error.message}`, 'danger');
      }
    });

    els.keepLlm?.addEventListener?.('change', () => patchProfileSetting('model_keep_llm_loaded', Boolean(els.keepLlm.checked), { messageEl: els.warmupMessage }));
    els.keepStt?.addEventListener?.('change', () => patchProfileSetting('model_keep_stt_loaded', Boolean(els.keepStt.checked), { messageEl: els.warmupMessage }));
    els.keepTts?.addEventListener?.('change', () => patchProfileSetting('model_keep_tts_loaded', Boolean(els.keepTts.checked), { messageEl: els.warmupMessage }));

    els.audioDucking?.addEventListener?.('change', () => patchProfileSetting('audio_ducking', Boolean(els.audioDucking.checked), { messageEl: els.sendInjectionMessage }));
    els.testPasteCopyButton?.addEventListener?.('click', async () => {
      try {
        await window.betterFingers?.writeClipboardText?.('BetterFingers test paste — Utilities → Advanced → Test Paste/Copy.');
        setMessage(els.sendInjectionMessage, 'Test text copied to clipboard.', 'success');
      } catch (error) {
        setMessage(els.sendInjectionMessage, `Copy failed: ${error.message}`, 'danger');
      }
    });
  }

  async function runWarmup(flags, label) {
    setMessage(els.warmupMessage, `Warming up ${label}…`, 'info');
    try {
      await warmupRuntime(flags);
      setMessage(els.warmupMessage, `${label} warmup requested.`, 'success');
    } catch (error) {
      setMessage(els.warmupMessage, `${label} warmup failed: ${error.message}`, 'danger');
    }
  }

  // ===========================================================================
  // lifecycle
  // ===========================================================================

  function bindSectionNav() {
    const navEls = { models: els.navModels, speech: els.navSpeech, text: els.navText, diagnostics: els.navDiagnostics, advanced: els.navAdvanced };
    UTILITIES_SECTIONS.forEach((id) => {
      navEls[id]?.addEventListener?.('click', () => goToSection(id));
    });
  }

  function bindOnce() {
    bindSectionNav();
    bindModelsSection();
    bindAudioDeviceSection();
    bindHotkeysSection();
    bindWakeWordSection();
    bindTextToolsSection();
    bindDiagnosticsSection();
    bindAdvancedSection();
  }

  function init(initialSection) {
    bindOnce();
    if (initialSection && isValidUtilitiesSection(initialSection)) {
      sectionState = { active: initialSection };
    }
    renderSectionNav();
    return { ...sectionState };
  }

  /** Fires every section's real backend refresh -- safe to call repeatedly; every path is try/caught internally. */
  async function refreshAll() {
    await Promise.all([
      refreshModels(),
      refreshModelRecommendation(),
      refreshWakeBackbones(),
      refreshVoiceCloning(),
      refreshHotkeyCapabilities(),
      refreshHotkeys(),
      refreshWakeStatus(),
      refreshWakeTuningFromProfile(),
      refreshMacrosEnabled(),
      refreshDictionary(),
      refreshMacros(),
      refreshAllDiagnostics(),
      refreshResidencyFromProfile(),
      refreshCapabilitiesDump(),
      refreshRuntimeStatusDump(),
      refreshOutputSettingsSummary(),
    ]);
  }

  return {
    init,
    refreshAll,
    goToSection,
    getSectionState: () => ({ ...sectionState }),
    // Real per-area refreshers (also usable standalone by a caller/test).
    refreshModels,
    refreshModelRecommendation,
    refreshWakeBackbones,
    refreshHotkeys,
    refreshHotkeyCapabilities,
    refreshWakeStatus,
    refreshDictionary,
    refreshMacros,
    refreshDoctor,
    refreshMetrics,
    refreshRecordings,
    refreshJobsList,
    refreshSidecarLogs,
    refreshSidecarStatus,
    refreshDiagnosticsPaths,
    refreshRuntimeErrors,
    refreshDebugLogTail,
    refreshCapabilitiesDump,
    refreshRuntimeStatusDump,
    suggestFromEdit,
    // Preview/test seeding (no network) -- mirrors libraryWorkspace.js's
    // setItems()/studioWorkspace.js's setPersonas() convention.
    setModelPayloads,
    setAudioDevices,
    renderDoctorCards,
    renderMetricsHud,
    renderRecordingsList,
    renderJobsList,
    renderSidecarLogs,
    renderDictionaryList,
    renderDictionarySuggestions,
    renderMacrosList,
    renderWakeBackbones,
    renderDetailList,
    renderRuntimeErrors,
    getMessageRescueDraftFeature: () => messageRescueDraftFeature,
  };
}
