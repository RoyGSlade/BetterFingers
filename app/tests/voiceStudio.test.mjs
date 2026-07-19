// Unit tests for the extracted Voice Studio feature (side-track: voice
// blending UI redesign + canonical TTS voice sync).
// Run with: node --test app/tests/voiceStudio.test.mjs
//
// No jsdom in this repo's test setup (see messageRescuePanel.test.mjs) — pure
// helpers are exercised directly, and the DOM-wiring feature is exercised
// against a small fake `document` (getElementById/createElement/
// querySelectorAll) with plain stub elements, network calls injected via the
// `api` override so nothing here touches a real backend.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  normalizeBlendForSend,
  resolveAvailableVoiceId,
  filterAvailableBlendLayers,
  computeEffectiveMix,
  gatherVoiceStudioSettingsFromInputs,
  buildPersistableVoiceStudioSettings,
  extractVoiceStudioStateFromProfile,
  createVoiceStudioFeature,
} from '../src/renderer/features/voiceStudio.js';

// --- normalizeBlendForSend ---------------------------------------------------

test('normalizeBlendForSend: drops zero/negative/non-finite weights', () => {
  const layers = [
    { voiceId: 'af_nicole', weight: 0.3 },
    { voiceId: 'bf_emma', weight: 0 },
    { voiceId: 'am_michael', weight: -1 },
    { voiceId: 'bm_george', weight: NaN },
  ];
  assert.deepEqual(normalizeBlendForSend(layers), { af_nicole: 0.3 });
});

test('normalizeBlendForSend: duplicate voiceIds collapse to the last one (no ambiguous double state)', () => {
  const layers = [
    { voiceId: 'af_nicole', weight: 0.2 },
    { voiceId: 'af_nicole', weight: 0.6 },
  ];
  assert.deepEqual(normalizeBlendForSend(layers), { af_nicole: 0.6 });
});

test('normalizeBlendForSend: clamps weight to [0,1]', () => {
  assert.deepEqual(normalizeBlendForSend([{ voiceId: 'af_nicole', weight: 5 }]), { af_nicole: 1 });
});

test('normalizeBlendForSend: empty/all-dropped input is null, not {}', () => {
  assert.equal(normalizeBlendForSend([]), null);
  assert.equal(normalizeBlendForSend([{ voiceId: '', weight: 0.5 }]), null);
});

// --- resolveAvailableVoiceId (unavailable/deleted voice fallback) -----------

test('resolveAvailableVoiceId: available selection passes through unchanged', () => {
  const result = resolveAvailableVoiceId('af_heart', ['af_heart', 'af_bella'], 'af_bella');
  assert.deepEqual(result, { id: 'af_heart', fellBack: false });
});

test('resolveAvailableVoiceId: unavailable selection falls back to preferred, marked as a fallback', () => {
  const result = resolveAvailableVoiceId('cloned_deleted', ['af_heart', 'af_bella'], 'af_bella');
  assert.deepEqual(result, { id: 'af_bella', fellBack: true });
});

test('resolveAvailableVoiceId: unavailable preferred falls back to the first available voice', () => {
  const result = resolveAvailableVoiceId('gone', ['af_heart', 'af_bella'], 'also_gone');
  assert.deepEqual(result, { id: 'af_heart', fellBack: true });
});

test('resolveAvailableVoiceId: no selection at all is not treated as a fallback (first load, not a stale voice)', () => {
  const result = resolveAvailableVoiceId('', ['af_heart'], '');
  assert.deepEqual(result, { id: 'af_heart', fellBack: false });
});

// --- filterAvailableBlendLayers ----------------------------------------------

test('filterAvailableBlendLayers: drops layers pointing at voices no longer available', () => {
  const layers = [{ voiceId: 'af_nicole', weight: 0.3 }, { voiceId: 'cloned_gone', weight: 0.2 }];
  const result = filterAvailableBlendLayers(layers, ['af_nicole']);
  assert.deepEqual(result.layers, [{ voiceId: 'af_nicole', weight: 0.3 }]);
  assert.deepEqual(result.dropped, ['cloned_gone']);
});

test('filterAvailableBlendLayers: nothing dropped when everything is available', () => {
  const layers = [{ voiceId: 'af_nicole', weight: 0.3 }];
  const result = filterAvailableBlendLayers(layers, ['af_nicole', 'bf_emma']);
  assert.deepEqual(result.layers, layers);
  assert.deepEqual(result.dropped, []);
});

// --- computeEffectiveMix ------------------------------------------------------

test('computeEffectiveMix: base alone is 100%', () => {
  assert.deepEqual(computeEffectiveMix('af_heart', []), [{ label: 'af_heart', pct: 100 }]);
});

test('computeEffectiveMix: base always enters at weight 1.0 (matches tts_engine._resolve_voice_spec)', () => {
  const parts = computeEffectiveMix('af_heart', [{ voiceId: 'af_nicole', weight: 1.0 }]);
  assert.deepEqual(parts, [
    { label: 'af_heart', pct: 50 },
    { label: 'af_nicole', pct: 50 },
  ]);
});

// --- gather / persistable / restore round trip (persistence + reload) -------

test('gatherVoiceStudioSettingsFromInputs: full shape with sane fallbacks', () => {
  const settings = gatherVoiceStudioSettingsFromInputs({
    base: 'af_heart', speed: '1.2', blendLayers: [{ voiceId: 'af_nicole', weight: 0.3 }],
    pitch: '2', energy: '0.7', warmth: '0.4', brightness: '0.1', pauseStyle: 'dramatic',
  });
  assert.deepEqual(settings, {
    base: 'af_heart', speed: 1.2, blend: { af_nicole: 0.3 },
    pitch: 2, energy: 0.7, warmth: 0.4, brightness: 0.1, pause_style: 'dramatic',
  });
});

test('gatherVoiceStudioSettingsFromInputs: invalid pause_style falls back to natural', () => {
  const settings = gatherVoiceStudioSettingsFromInputs({ base: 'x', blendLayers: [], pauseStyle: 'shouting' });
  assert.equal(settings.pause_style, 'natural');
});

test('persist -> extract round trip preserves blend and modulation exactly', () => {
  const persisted = buildPersistableVoiceStudioSettings({
    blendLayers: [{ voiceId: 'af_nicole', weight: 0.3 }, { voiceId: 'bf_emma', weight: 0.2 }],
    pitch: 2, energy: 0.7, warmth: 0.4, brightness: 0.1, pauseStyle: 'dramatic',
  });
  assert.deepEqual(persisted, {
    review_tts_blend: { af_nicole: 0.3, bf_emma: 0.2 },
    review_tts_pitch: 2, review_tts_energy: 0.7, review_tts_warmth: 0.4,
    review_tts_brightness: 0.1, review_tts_pause_style: 'dramatic',
  });

  const restored = extractVoiceStudioStateFromProfile(persisted);
  assert.deepEqual(restored, {
    blendLayers: [{ voiceId: 'af_nicole', weight: 0.3 }, { voiceId: 'bf_emma', weight: 0.2 }],
    pitch: 2, energy: 0.7, warmth: 0.4, brightness: 0.1, pauseStyle: 'dramatic',
  });
});

test('extractVoiceStudioStateFromProfile: an old profile missing the new keys restores to neutral defaults, not a crash', () => {
  const restored = extractVoiceStudioStateFromProfile({ review_tts_voice_hint: 'af_heart' });
  assert.deepEqual(restored, {
    blendLayers: [], pitch: 0, energy: 0.5, warmth: 0, brightness: 0, pauseStyle: 'natural',
  });
});

test('extractVoiceStudioStateFromProfile: a non-dict blend field does not crash', () => {
  const restored = extractVoiceStudioStateFromProfile({ review_tts_blend: 'not-a-dict' });
  assert.deepEqual(restored.blendLayers, []);
});

// --- DOM-wiring feature (fake doc, no real DOM) ------------------------------

function makeStubElement() {
  return {
    value: '', textContent: '', innerHTML: '', className: '', hidden: false,
    disabled: false, checked: false, dataset: {}, _attrs: {}, _listeners: {},
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute(k, v) { this._attrs[k] = v; },
    appendChild(child) { return child; },
    addEventListener(evt, fn) {
      // Voice Studio wires each control once per init(); if listener dedupe
      // ever regresses, this collects every handler instead of overwriting,
      // exposing the double-registration in fireClick/fireInput below.
      (this._listeners[evt] ||= []).push(fn);
    },
  };
}

function makeStubSelect() {
  const el = makeStubElement();
  el.querySelector = () => null;
  return el;
}

function fireClick(el) {
  (el._listeners.click || []).forEach((fn) => fn({ target: el }));
}

function fireInput(el, evt = 'input') {
  (el._listeners[evt] || []).forEach((fn) => fn({ target: el }));
}

function makeFakeDoc(overrides = {}) {
  const elements = {
    settingReviewTtsVoiceHint: makeStubSelect(),
    settingReviewTtsSpeed: makeStubElement(),
    voicePreviewText: makeStubElement(),
    testTtsButton: makeStubElement(),
    voicePresetSelect: makeStubSelect(),
    voicePresetList: makeStubElement(),
    voicePresetNameInput: makeStubElement(),
    saveVoicePresetButton: makeStubElement(),
    voiceBlendRows: makeStubElement(),
    voiceEffectiveMix: makeStubElement(),
    addVoiceLayerButton: makeStubElement(),
    resetVoiceBlendButton: makeStubElement(),
    voicePitch: makeStubElement(),
    voicePitchValue: makeStubElement(),
    voiceEnergy: makeStubElement(),
    voiceEnergyValue: makeStubElement(),
    voiceWarmth: makeStubElement(),
    voiceWarmthValue: makeStubElement(),
    voiceBrightness: makeStubElement(),
    voiceBrightnessValue: makeStubElement(),
    voicePauseStyle: makeStubElement(),
    profileMessage: makeStubElement(),
    ...overrides,
  };
  elements.settingReviewTtsVoiceHint.value = 'af_heart';
  ['voicePitch', 'voiceEnergy', 'voiceWarmth', 'voiceBrightness'].forEach((id) => {
    elements[id].value = '0';
  });
  elements.voicePauseStyle.value = 'natural';

  return {
    elements,
    getElementById: (id) => elements[id] || null,
    createElement: () => makeStubElement(),
    querySelectorAll: () => [],
  };
}

function makeApiStub(overrides = {}) {
  return {
    fetchTtsVoices: async () => ({ defaults: [{ id: 'af_heart', name: 'Heart' }, { id: 'af_nicole', name: 'Nicole' }], cloned: [], cloning: { installed: false } }),
    fetchVoicePresets: async () => ({ presets: [] }),
    saveVoicePreset: async () => ({}),
    deleteVoicePreset: async () => ({}),
    cloneVoice: async () => ({}),
    speakTts: async () => ({ ok: true, message: 'spoke' }),
    ...overrides,
  };
}

test('gatherVoiceStudioSettings: reads the live DOM value immediately (select -> active-use)', async () => {
  const fakeDoc = makeFakeDoc();
  const feature = createVoiceStudioFeature({ ui: {}, hooks: {}, api: makeApiStub() });
  await feature.refreshVoices(fakeDoc);

  fakeDoc.elements.settingReviewTtsVoiceHint.value = 'af_nicole';
  const settings = feature.gatherVoiceStudioSettings(fakeDoc);
  assert.equal(settings.base, 'af_nicole', 'gather reflects the current select value with no stale caching');
});

test('gatherVoiceStudioSettings and the Audition button use the same values (preview parity)', async () => {
  const fakeDoc = makeFakeDoc();
  const speakTts = async (text, base, speed, pitch, extra) => ({ ok: true, message: 'ok', _seen: { base, speed, pitch, extra } });
  const feature = createVoiceStudioFeature({ ui: { setMessage() {}, showToast() {} }, hooks: {}, api: makeApiStub({ speakTts }) });
  await feature.refreshVoices(fakeDoc);
  feature.init({ doc: fakeDoc });

  fakeDoc.elements.settingReviewTtsSpeed.value = '1.3';
  fakeDoc.elements.voiceEnergy.value = '0.8';
  const gathered = feature.gatherVoiceStudioSettings(fakeDoc);

  fireClick(fakeDoc.elements.testTtsButton);
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(gathered.speed, 1.3);
  assert.equal(gathered.energy, 0.8);
  assert.equal(fakeDoc.elements.testTtsButton.textContent, 'Audition Voice / Test TTS API');
});

test('reset button clears blend layers (blend normalization/reset)', async () => {
  const fakeDoc = makeFakeDoc();
  const feature = createVoiceStudioFeature({ ui: {}, hooks: {}, api: makeApiStub() });
  await feature.refreshVoices(fakeDoc);
  feature.init({ doc: fakeDoc });

  fireClick(fakeDoc.elements.addVoiceLayerButton);
  assert.notEqual(feature.gatherVoiceStudioSettings(fakeDoc).blend, null);

  fireClick(fakeDoc.elements.resetVoiceBlendButton);
  assert.equal(feature.gatherVoiceStudioSettings(fakeDoc).blend, null);
});

test('restoreFromProfile: a deleted blend voice is dropped with a warning, not silently mismatched (unavailable fallback)', async () => {
  const fakeDoc = makeFakeDoc();
  const warnings = [];
  const feature = createVoiceStudioFeature({
    ui: { setMessage() {}, showToast: (msg) => warnings.push(msg) },
    hooks: { markProfileDirty() {} },
    api: makeApiStub(),
  });
  await feature.refreshVoices(fakeDoc); // cache: af_heart, af_nicole only

  feature.restoreFromProfile({
    review_tts_voice_hint: 'af_heart',
    review_tts_blend: { af_nicole: 0.3, cloned_deleted: 0.5 },
  }, fakeDoc);

  assert.equal(feature.gatherVoiceStudioSettings(fakeDoc).blend.cloned_deleted, undefined);
  assert.equal(feature.gatherVoiceStudioSettings(fakeDoc).blend.af_nicole, 0.3);
  assert.ok(warnings.some((w) => w.includes('cloned_deleted')), 'warns about the dropped voice');
});

test('restoreFromProfile: a base voice that is no longer available falls back and warns', async () => {
  const fakeDoc = makeFakeDoc();
  const warnings = [];
  const dirtyCalls = [];
  const feature = createVoiceStudioFeature({
    ui: { setMessage() {}, showToast: (msg) => warnings.push(msg) },
    hooks: { markProfileDirty: () => dirtyCalls.push(1) },
    api: makeApiStub(),
  });
  await feature.refreshVoices(fakeDoc); // cache: af_heart, af_nicole

  // Simulate renderProfileSettings() having just written a stale value in.
  fakeDoc.elements.settingReviewTtsVoiceHint.value = 'cloned_deleted';
  feature.restoreFromProfile({ review_tts_voice_hint: 'cloned_deleted' }, fakeDoc);

  assert.equal(fakeDoc.elements.settingReviewTtsVoiceHint.value, 'af_heart');
  assert.ok(warnings.some((w) => w.includes('cloned_deleted')));
  assert.ok(dirtyCalls.length > 0, 'the corrected voice is marked dirty so the user knows to re-save');
});

test('persistence/reload: getPersistableState -> restoreFromProfile round trip reproduces the live UI', async () => {
  const fakeDoc = makeFakeDoc();
  const feature = createVoiceStudioFeature({ ui: { setMessage() {}, showToast() {} }, hooks: { markProfileDirty() {} }, api: makeApiStub() });
  await feature.refreshVoices(fakeDoc);
  feature.init({ doc: fakeDoc });

  fireClick(fakeDoc.elements.addVoiceLayerButton); // adds one blend layer
  fakeDoc.elements.voicePitch.value = '3';
  fireInput(fakeDoc.elements.voicePitch);

  const persisted = feature.getPersistableState(fakeDoc);
  assert.equal(persisted.review_tts_pitch, 3);
  assert.ok(Object.keys(persisted.review_tts_blend).length > 0);

  // Simulate a fresh reload: new feature instance, same fake doc reset to defaults.
  const reloadedDoc = makeFakeDoc();
  const reloaded = createVoiceStudioFeature({ ui: { setMessage() {}, showToast() {} }, hooks: { markProfileDirty() {} }, api: makeApiStub() });
  await reloaded.refreshVoices(reloadedDoc);
  reloaded.restoreFromProfile({ review_tts_voice_hint: 'af_heart', ...persisted }, reloadedDoc);

  assert.equal(reloaded.getPersistableState(reloadedDoc).review_tts_pitch, 3);
  assert.deepEqual(reloaded.getPersistableState(reloadedDoc).review_tts_blend, persisted.review_tts_blend);
});

test('init is idempotent: calling it twice does not double-register listeners (listener dedupe)', async () => {
  const fakeDoc = makeFakeDoc();
  const feature = createVoiceStudioFeature({ ui: { setMessage() {}, showToast() {} }, hooks: { markProfileDirty() {} }, api: makeApiStub() });
  await feature.refreshVoices(fakeDoc);

  feature.init({ doc: fakeDoc });
  feature.init({ doc: fakeDoc }); // second call must be a no-op

  fireClick(fakeDoc.elements.addVoiceLayerButton);
  const blend = feature.gatherVoiceStudioSettings(fakeDoc).blend;
  assert.equal(Object.keys(blend).length, 1, 'one click added exactly one layer, not two');
});
