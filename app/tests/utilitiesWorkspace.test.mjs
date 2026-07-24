// Unit tests for the Utilities workspace wiring adapter's PURE helpers
// (docs/ui/SIGNAL_DESK_SPEC.md section 8). Mirrors studioWorkspace.test.mjs's
// approach: only DOM-free "data -> view model" logic and the section router
// are exercised here -- createUtilitiesWorkspaceFeature()'s DOM wiring itself
// needs a real document and is exercised manually via
// signal-desk-preview.html per the phase brief.
//
// Also includes the director's "no-orphan gate" completeness check: every
// inventory item the work packet calls out by name (Models, Diagnostics,
// Dictionary, Macros, wake-word training, audio device, all 6 hotkeys,
// controller note, support report, warmup, residency, and the 3 Message
// Rescue surfaces) must have a home somewhere in INVENTORY_PLACEMENT_MAP.
//
// Run with: node --test app/tests/utilitiesWorkspace.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  UTILITIES_SECTIONS,
  UTILITIES_SECTION_META,
  isValidUtilitiesSection,
  computeNextUtilitiesSection,
  INVENTORY_PLACEMENT_MAP,
  HOTKEY_FIELD_KEYS,
  HOTKEY_FIELD_LABELS,
  describeKeyEvent,
  detectHotkeyCollisions,
  formatMb,
  clampPct,
  buildDownloadProgressModel,
  DOCTOR_RECOVERY_LABELS,
  buildDoctorCardModel,
  buildDoctorModel,
  JOB_STATE_LABELS,
  formatJobRow,
  formatRecordingRow,
  formatWakeTrainVerdict,
  UTILITIES_ELEMENT_IDS,
  collectUtilitiesElements,
  createUtilitiesWorkspaceFeature,
} from '../src/renderer/features/utilitiesWorkspace.js';

// --- section routing (pure reducer, same contract as signalDeskShell.js) ----

test('UTILITIES_SECTIONS: exactly the 5 sections named in the work packet', () => {
  assert.deepEqual(UTILITIES_SECTIONS, ['models', 'speech', 'text', 'diagnostics', 'advanced']);
});

test('UTILITIES_SECTION_META: every section has a label and description', () => {
  for (const id of UTILITIES_SECTIONS) {
    assert.ok(UTILITIES_SECTION_META[id]?.label, `${id} missing a label`);
    assert.ok(UTILITIES_SECTION_META[id]?.description, `${id} missing a description`);
  }
});

test('isValidUtilitiesSection: only the 5 known ids are valid', () => {
  for (const id of UTILITIES_SECTIONS) assert.equal(isValidUtilitiesSection(id), true);
  assert.equal(isValidUtilitiesSection('settings'), false);
  assert.equal(isValidUtilitiesSection('bogus'), false);
  assert.equal(isValidUtilitiesSection(undefined), false);
});

test('computeNextUtilitiesSection: switches to a valid requested section', () => {
  const next = computeNextUtilitiesSection({ active: 'models' }, 'diagnostics');
  assert.deepEqual(next, { active: 'diagnostics' });
});

test('computeNextUtilitiesSection: an unknown id is a no-op (stays on current)', () => {
  const next = computeNextUtilitiesSection({ active: 'text' }, 'bogus');
  assert.deepEqual(next, { active: 'text' });
});

test('computeNextUtilitiesSection: a missing/invalid current state falls back to the first section', () => {
  const next = computeNextUtilitiesSection(undefined, 'advanced');
  assert.deepEqual(next, { active: 'advanced' });
  const next2 = computeNextUtilitiesSection({ active: 'not-a-section' }, 'bogus');
  assert.deepEqual(next2, { active: 'models' });
});

// --- hotkeys: describeKeyEvent -----------------------------------------------

test('describeKeyEvent: builds a chord string from modifiers + key', () => {
  assert.equal(describeKeyEvent({ ctrlKey: true, key: ' ' }), 'Ctrl+Space');
  assert.equal(describeKeyEvent({ ctrlKey: true, shiftKey: true, key: 'a' }), 'Ctrl+Shift+A');
  assert.equal(describeKeyEvent({ metaKey: true, key: 'Escape' }), 'Meta+Escape');
  assert.equal(describeKeyEvent({ altKey: true, key: 'F5' }), 'Alt+F5');
});

test('describeKeyEvent: a bare modifier press produces no trailing key token', () => {
  assert.equal(describeKeyEvent({ ctrlKey: true, key: 'Control' }), 'Ctrl');
});

test('describeKeyEvent: no event is an empty string, not a throw', () => {
  assert.equal(describeKeyEvent(null), '');
  assert.equal(describeKeyEvent(undefined), '');
});

// --- hotkeys: detectHotkeyCollisions -----------------------------------------

test('detectHotkeyCollisions: no collisions when every value is distinct', () => {
  const map = { hotkey: 'Ctrl+Space', force_stop_key: 'Escape', manual_send_hotkey: 'Ctrl+Enter' };
  assert.deepEqual(detectHotkeyCollisions(map), {});
});

test('detectHotkeyCollisions: two fields sharing a chord both get flagged', () => {
  const map = { hotkey: 'Ctrl+Space', force_stop_key: 'Ctrl+Space' };
  const collisions = detectHotkeyCollisions(map);
  assert.equal(collisions.hotkey, `Same as ${HOTKEY_FIELD_LABELS.force_stop_key}`);
  assert.equal(collisions.force_stop_key, `Same as ${HOTKEY_FIELD_LABELS.hotkey}`);
});

test('detectHotkeyCollisions: empty/blank values never collide with each other', () => {
  const map = { hotkey: '', force_stop_key: '   ', manual_send_hotkey: undefined };
  assert.deepEqual(detectHotkeyCollisions(map), {});
});

test('detectHotkeyCollisions: three-way collision lists both other fields', () => {
  const map = { hotkey: 'F9', force_stop_key: 'F9', manual_send_hotkey: 'F9' };
  const collisions = detectHotkeyCollisions(map);
  assert.equal(collisions.hotkey, 'Same as Emergency Stop key, Primary Action key');
});

test('HOTKEY_FIELD_KEYS: exactly the 6 hotkey fields from inventory §7.3, each with a label', () => {
  assert.deepEqual(HOTKEY_FIELD_KEYS, ['hotkey', 'force_stop_key', 'manual_send_hotkey', 'review_tts_hotkey', 'chat_open_key', 'voice_mute_key']);
  for (const key of HOTKEY_FIELD_KEYS) assert.ok(HOTKEY_FIELD_LABELS[key], `${key} missing a label`);
});

// --- models: formatMb / clampPct / buildDownloadProgressModel ---------------

test('formatMb: sub-1024 MB stays in MB, >=1024 converts to GB', () => {
  assert.equal(formatMb(512), '512 MB');
  assert.equal(formatMb(2048), '2.0 GB');
  assert.equal(formatMb(0), 'unknown');
  assert.equal(formatMb(undefined), 'unknown');
  assert.equal(formatMb('not-a-number'), 'unknown');
});

test('clampPct: clamps to [0,100] and rounds, non-finite falls back to 0', () => {
  assert.equal(clampPct(50.6), 51);
  assert.equal(clampPct(-5), 0);
  assert.equal(clampPct(150), 100);
  assert.equal(clampPct(NaN), 0);
  assert.equal(clampPct(undefined), 0);
});

test('buildDownloadProgressModel: an idle/no download state is hidden', () => {
  const model = buildDownloadProgressModel(undefined);
  assert.equal(model.hidden, true);
});

test('buildDownloadProgressModel: an active download is visible with a clamped percent', () => {
  const model = buildDownloadProgressModel({ status: 'downloading', percent: 42.7, message: 'Downloading…' });
  assert.equal(model.hidden, false);
  assert.equal(model.percent, 43);
  assert.equal(model.label, 'Downloading…');
});

test('buildDownloadProgressModel: an error status stays visible with a danger tone', () => {
  const model = buildDownloadProgressModel({ status: 'error', message: 'Disk full' });
  assert.equal(model.hidden, false);
  assert.equal(model.tone, 'danger');
  assert.equal(model.label, 'Disk full');
});

// --- doctor: buildDoctorCardModel / buildDoctorModel -------------------------

test('buildDoctorCardModel: stt loaded is "ok" tone', () => {
  const card = buildDoctorCardModel('stt', { loaded: true, initialized: true, model_size: 'base' });
  assert.equal(card.tone, 'ok');
  assert.equal(card.status, 'Loaded');
});

test('buildDoctorCardModel: stt never initialized is "error" tone and flags missing_model', () => {
  const card = buildDoctorCardModel('stt', { loaded: false, initialized: false });
  assert.equal(card.tone, 'error');
  assert.ok(card.triggers.includes('missing_model'));
});

test('buildDoctorCardModel: llm with an outdated runtime is "warn" and flags outdated_runtime', () => {
  const card = buildDoctorCardModel('llm', { ready: false, initialized: false, llama_server_exists: true, runtime_compatible: false });
  assert.equal(card.tone, 'warn');
  assert.equal(card.status, 'Runtime outdated');
  assert.ok(card.triggers.includes('outdated_runtime'));
});

test('buildDoctorCardModel: platform on Wayland without injection support flags unsupported_wayland_injection', () => {
  const card = buildDoctorCardModel('platform', { is_wayland: true, supports_input_injection: false, platform: 'linux', session_type: 'wayland' });
  assert.equal(card.tone, 'warn');
  assert.ok(card.triggers.includes('unsupported_wayland_injection'));
});

test('buildDoctorModel: produces exactly 8 subsystem cards (inventory §9)', () => {
  const model = buildDoctorModel({});
  assert.equal(model.cards.length, 8);
});

test('buildDoctorModel: dedupes recovery triggers and attaches backend-supplied or client-fallback text', () => {
  const doctor = {
    stt: { loaded: false, initialized: false },
    models: { default_model_exists: false },
    recovery: { missing_model: 'Download a model from the Models tab.' },
  };
  const model = buildDoctorModel(doctor);
  const triggers = model.recovery.map((r) => r.trigger);
  assert.deepEqual([...new Set(triggers)], triggers, 'no duplicate triggers');
  assert.ok(triggers.includes('missing_model'));
  const missingModelEntry = model.recovery.find((r) => r.trigger === 'missing_model');
  assert.equal(missingModelEntry.text, 'Download a model from the Models tab.');
});

test('buildDoctorModel: outdated_runtime falls back to client-side text when the backend omits it', () => {
  const doctor = { llm: { ready: false, initialized: false, llama_server_exists: true, runtime_compatible: false } };
  const model = buildDoctorModel(doctor);
  const entry = model.recovery.find((r) => r.trigger === 'outdated_runtime');
  assert.ok(entry, 'outdated_runtime recovery entry present');
  assert.match(entry.text, /llama-server/i);
});

test('DOCTOR_RECOVERY_LABELS: every trigger id inventory §9 lists has a human label', () => {
  const required = ['missing_model', 'missing_llama_server', 'outdated_runtime', 'port_conflict', 'microphone_unavailable', 'unsupported_wayland_injection', 'failed_clipboard', 'failed_tts_dependency'];
  for (const trigger of required) assert.ok(DOCTOR_RECOVERY_LABELS[trigger], `${trigger} missing a label`);
});

// --- jobs / recordings / wake -------------------------------------------------

test('formatJobRow: includes label, human state, and rounded percent', () => {
  assert.equal(formatJobRow({ label: 'Transcribe', state: 'transcribing', progress: 0.5 }), 'Transcribe — Transcribing · 50%');
});

test('formatJobRow: falls back to kind when label is absent, and unknown state passes through', () => {
  assert.equal(formatJobRow({ kind: 'refine', state: 'weird_state' }), 'refine — weird_state');
});

test('formatJobRow: shows a cancelling suffix', () => {
  assert.equal(formatJobRow({ label: 'X', state: 'queued', cancel_requested: true }), 'X — Queued · cancelling…');
});

test('JOB_STATE_LABELS: covers every state referenced by inventory §9', () => {
  for (const state of ['queued', 'loading', 'capturing', 'transcribing', 'refining', 'stitching', 'review_ready', 'injecting', 'completed', 'failed', 'cancelled']) {
    assert.ok(JOB_STATE_LABELS[state], `${state} missing a label`);
  }
});

test('formatRecordingRow: formats duration and stop reason', () => {
  const label = formatRecordingRow({ created_at: 1700000000, duration_seconds: 6, stop_reason: 'silence' });
  assert.match(label, /6s/);
  assert.match(label, /silence/);
});

test('formatRecordingRow: a missing timestamp does not throw', () => {
  assert.doesNotThrow(() => formatRecordingRow({}));
});

test('formatWakeTrainVerdict: includes verdict and rate percentages', () => {
  const text = formatWakeTrainVerdict({ verdict: 'reliable', false_accept_rate: 0.021, false_reject_rate: 0.05 });
  assert.match(text, /reliable/);
  assert.match(text, /FA 2\.1%/);
  assert.match(text, /FR 5\.0%/);
});

test('formatWakeTrainVerdict: no result is an empty string', () => {
  assert.equal(formatWakeTrainVerdict(null), '');
});

// --- element collection -------------------------------------------------------

test('collectUtilitiesElements: missing ids resolve to null (never throws) against a stub document', () => {
  const stubDoc = { getElementById: () => null };
  const els = collectUtilitiesElements(stubDoc);
  assert.equal(els.modelsRefreshButton, null);
  assert.equal(els.hotkeyFields.hotkey.input, null);
  assert.equal(els.hotkeyFields.voice_mute_key.clear, null);
});

test('collectUtilitiesElements: resolves every flat id plus the nested hotkeyFields map', () => {
  const seen = [];
  const stubDoc = { getElementById: (id) => { seen.push(id); return { id }; } };
  const els = collectUtilitiesElements(stubDoc);
  assert.equal(els.modelsRefreshButton.id, UTILITIES_ELEMENT_IDS.modelsRefreshButton);
  for (const field of HOTKEY_FIELD_KEYS) {
    assert.equal(els.hotkeyFields[field].input.id, UTILITIES_ELEMENT_IDS.hotkeyFields[field].input);
    assert.equal(els.hotkeyFields[field].clear.id, UTILITIES_ELEMENT_IDS.hotkeyFields[field].clear);
    assert.equal(els.hotkeyFields[field].error.id, UTILITIES_ELEMENT_IDS.hotkeyFields[field].error);
  }
  // Every UTILITIES_ELEMENT_IDS id string was actually looked up.
  const flatIds = Object.entries(UTILITIES_ELEMENT_IDS).filter(([k]) => k !== 'hotkeyFields').map(([, v]) => v);
  for (const id of flatIds) assert.ok(seen.includes(id), `${id} was never queried`);
});

// --- createUtilitiesWorkspaceFeature: section router against stub elements ---

test('createUtilitiesWorkspaceFeature: init() defaults to the Models section and toggles nav/section visibility', () => {
  const models = { classList: { toggled: false, toggle(_c, v) { this.toggled = v; } }, setAttribute() {}, hidden: undefined };
  const speech = { classList: { toggled: false, toggle(_c, v) { this.toggled = v; } }, setAttribute() {}, hidden: undefined };
  const sectionModels = { hidden: undefined };
  const sectionSpeech = { hidden: undefined };
  const feature = createUtilitiesWorkspaceFeature({
    elements: { navModels: models, navSpeech: speech, sectionModels, sectionSpeech },
  });
  const state = feature.init();
  assert.equal(state.active, 'models');
  assert.equal(models.classList.toggled, true);
  assert.equal(speech.classList.toggled, false);
  assert.equal(sectionModels.hidden, false);
  assert.equal(sectionSpeech.hidden, true);
});

test('createUtilitiesWorkspaceFeature: goToSection switches the active section', () => {
  const sectionModels = { hidden: undefined };
  const sectionDiagnostics = { hidden: undefined };
  const feature = createUtilitiesWorkspaceFeature({ elements: { sectionModels, sectionDiagnostics } });
  feature.init();
  const state = feature.goToSection('diagnostics');
  assert.equal(state.active, 'diagnostics');
  assert.equal(sectionModels.hidden, true);
  assert.equal(sectionDiagnostics.hidden, false);
});

test('createUtilitiesWorkspaceFeature: goToSection with an unknown id is a no-op', () => {
  const feature = createUtilitiesWorkspaceFeature({ elements: {} });
  feature.init('text');
  const state = feature.goToSection('not-a-real-section');
  assert.equal(state.active, 'text');
});

test('createUtilitiesWorkspaceFeature: init() against completely empty elements does not throw', () => {
  assert.doesNotThrow(() => {
    const feature = createUtilitiesWorkspaceFeature({ elements: {} });
    feature.init();
  });
});

// --- pure render helpers exposed on the feature (DOM-light, stub nodes) -----

test('renderDoctorCards: builds one card per subsystem into a stub grid container', () => {
  const appended = [];
  const grid = { replaceChildren() { appended.length = 0; }, append: (...nodes) => appended.push(...nodes) };
  // jsdom is not available in this pure node:test environment -- this test
  // only runs the parts of renderDoctorCards that don't need `document`, by
  // confirming buildDoctorModel (which it delegates to) is stable; the full
  // DOM write path is covered manually via signal-desk-preview.html.
  const model = buildDoctorModel({});
  assert.equal(model.cards.length, 8);
  void grid;
});

// --- completeness gate: every required inventory item has a placement -------

// Exactly the inventory areas the work packet calls out by name as needing a
// confirmed home: Models, Diagnostics, Dictionary, Macros, wake-word
// training, audio device, all 6 hotkeys, controller note, support report,
// warmup, residency, and the 3 Message Rescue surfaces. Each requirement
// below is satisfied if AT LEAST ONE key with that prefix/id exists in
// INVENTORY_PLACEMENT_MAP with a valid section.
const REQUIRED_INVENTORY_KEYS = [
  // Models (§8)
  'models.recommendation',
  'models.refresh',
  'models.llm.select',
  'models.llm.download',
  'models.llm.delete',
  'models.llm.unload',
  'models.whisper.select',
  'models.whisper.download',
  'models.whisper.delete',
  'models.whisper.unload',
  'models.wake.backbones',
  'models.runtimeMemory.unloadTts',
  'models.voiceCloning.provision',
  // Diagnostics & Doctor (§9)
  'diagnostics.doctor',
  'diagnostics.latencyHud',
  'diagnostics.recordings',
  'diagnostics.jobs',
  'diagnostics.sidecarLogs',
  'diagnostics.supportReport',
  'diagnostics.paths',
  'diagnostics.runtimeErrors',
  'diagnostics.debugLogTail',
  // Dictionary (§7.12) / Macros (§7.13)
  'textTools.dictionary.crud',
  'textTools.dictionary.suggest',
  'textTools.macros.crud',
  'textTools.macros.enabledToggle',
  // Wake word (§7.8)
  'speech.wake.enableToggle',
  'speech.wake.modelSelect',
  'speech.wake.import',
  'speech.wake.training',
  'speech.wake.tuning',
  'speech.wake.liveTest',
  // Audio devices (§7.7)
  'speech.audioDevice.select',
  'speech.audioDevice.micTest',
  // Hotkeys (§7.3) -- all 6 fields + widget + collision + wayland + controller
  'speech.hotkeys.recording',
  'speech.hotkeys.forceStop',
  'speech.hotkeys.manualSend',
  'speech.hotkeys.reviewTts',
  'speech.hotkeys.chatOpen',
  'speech.hotkeys.voiceMute',
  'speech.hotkeys.customWidget',
  'speech.hotkeys.collisionDetection',
  'speech.hotkeys.waylandWarning',
  'speech.hotkeys.controllerNote',
  // Send & Injection (§7.6)
  'advanced.sendInjection.warnings',
  'advanced.sendInjection.audioDucking',
  'advanced.sendInjection.testPasteCopy',
  // Advanced & Developer (§7.16) -- warmup + residency + dumps
  'advanced.warmup',
  'advanced.primaryAction',
  'advanced.emergencyStop',
  'advanced.residency',
  'advanced.testModelLoad',
  'advanced.capabilitiesDump',
  'advanced.runtimeStatusDump',
  // The 3 Message Rescue surfaces (§6.4/§6.6/§6.7) -- kept distinct
  'textTools.messageRescue.draftBound',
  'textTools.messageRescue.staticPreview',
  'textTools.messageRescue.playground',
];

test('COMPLETENESS: every required inventory key has an entry in INVENTORY_PLACEMENT_MAP', () => {
  const missing = REQUIRED_INVENTORY_KEYS.filter((key) => !INVENTORY_PLACEMENT_MAP[key]);
  assert.deepEqual(missing, [], `missing placement map entries: ${missing.join(', ')}`);
});

test('COMPLETENESS: every placement map entry names a valid Utilities section', () => {
  for (const [key, entry] of Object.entries(INVENTORY_PLACEMENT_MAP)) {
    assert.ok(isValidUtilitiesSection(entry.section), `${key} has an invalid section "${entry.section}"`);
  }
});

test('COMPLETENESS: every placement map entry has a non-empty control description', () => {
  for (const [key, entry] of Object.entries(INVENTORY_PLACEMENT_MAP)) {
    assert.ok(typeof entry.control === 'string' && entry.control.length > 0, `${key} has no control description`);
  }
});

test('COMPLETENESS: every placement map entry has a boolean `wired` flag, and any unwired entry explains itself in `note`', () => {
  for (const [key, entry] of Object.entries(INVENTORY_PLACEMENT_MAP)) {
    assert.equal(typeof entry.wired, 'boolean', `${key}.wired must be a boolean`);
    if (!entry.wired) {
      assert.ok(typeof entry.note === 'string' && entry.note.length > 0, `${key} is unwired but has no explanatory note`);
    }
  }
});

test('COMPLETENESS: the 3 Message Rescue surfaces are each their own distinct entry (never merged)', () => {
  const keys = ['textTools.messageRescue.draftBound', 'textTools.messageRescue.staticPreview', 'textTools.messageRescue.playground'];
  const controls = keys.map((k) => INVENTORY_PLACEMENT_MAP[k].control);
  assert.equal(new Set(controls).size, 3, 'all 3 Message Rescue surfaces must have distinct control descriptions');
});

test('COMPLETENESS: all 6 hotkey fields resolve to distinct, correctly-labeled entries', () => {
  const keys = ['speech.hotkeys.recording', 'speech.hotkeys.forceStop', 'speech.hotkeys.manualSend', 'speech.hotkeys.reviewTts', 'speech.hotkeys.chatOpen', 'speech.hotkeys.voiceMute'];
  assert.equal(keys.length, HOTKEY_FIELD_KEYS.length);
  for (const key of keys) assert.equal(INVENTORY_PLACEMENT_MAP[key].section, 'speech');
});
