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
  MAX_BLEND_LAYERS,
  normalizeBlendForSend,
  normalizeCustomVoiceSources,
  buildCustomVoicePayload,
  resolveAvailableVoiceId,
  filterAvailableBlendLayers,
  computeEffectiveMix,
  gatherVoiceStudioSettingsFromInputs,
  buildPersistableVoiceStudioSettings,
  extractVoiceStudioStateFromProfile,
  formatVoiceSampleDuration,
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

test('custom voice accepts one to four unique sources and normalizes exactly to one', () => {
  const sources = normalizeCustomVoiceSources('heart', [
    { voiceId: 'bella', weight: 0.6 },
    { voiceId: 'adam', weight: 0.3 },
    { voiceId: 'george', weight: 0.1 },
  ], ['heart', 'bella', 'adam', 'george']);
  assert.equal(sources.length, 4);
  assert.equal(sources.reduce((sum, source) => sum + source.weight, 0), 1);
  assert.throws(() => normalizeCustomVoiceSources('heart', [{ voiceId: 'heart', weight: 1 }]), /more than once/);
  assert.throws(() => normalizeCustomVoiceSources('heart', [
    { voiceId: 'a', weight: 1 }, { voiceId: 'b', weight: 1 },
    { voiceId: 'c', weight: 1 }, { voiceId: 'd', weight: 1 },
  ]), /at most four/);
});

test('custom voice payload stores only engine-supported modulation fields', () => {
  const payload = buildCustomVoicePayload('Calm Narrator', {
    base: 'heart', blendLayers: [{ voiceId: 'bella', weight: 0.5 }],
    speed: 0.9, pitch: -1, energy: 0.4, warmth: 0.2, brightness: 0.1, pause_style: 'natural',
    stability: 0.99, expressiveness: 0.8,
  }, { availableIds: ['heart', 'bella'], sourcePresetId: 'quiet' });
  assert.equal(payload.sources.length, 2);
  assert.equal(payload.source_preset_id, 'quiet');
  assert.equal('stability' in payload.modulation, false);
  assert.equal('expressiveness' in payload.modulation, false);
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
    children: [],
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute(k, v) { this._attrs[k] = v; },
    appendChild(child) { this.children.push(child); return child; },
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
    // Wave 12A finding (3): the active-voice readout beside the base select.
    voiceActiveVoiceName: makeStubElement(),
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
    stopTts: async () => ({ ok: true }),
    ...overrides,
  };
}

test('formatVoiceSampleDuration: records a real duration and rejects unknown metadata honestly', () => {
  assert.equal(formatVoiceSampleDuration(3.25), '3.3s');
  assert.equal(formatVoiceSampleDuration(65), '1:05');
  assert.equal(formatVoiceSampleDuration(NaN), 'duration unavailable');
});

test('read-aloud transport exposes Play/Pause/Stop/Restart and always sends current voice blend settings', async () => {
  const fakeDoc = makeFakeDoc({
    readAloudPlayButton: makeStubElement(),
    readAloudPauseButton: makeStubElement(),
    readAloudStopButton: makeStubElement(),
    readAloudRestartButton: makeStubElement(),
    readAloudPlaybackState: makeStubElement(),
  });
  const calls = [];
  const stops = [];
  const feature = createVoiceStudioFeature({
    ui: { setMessage() {}, showToast() {} },
    hooks: {},
    api: makeApiStub({
      speakTts: async (...args) => { calls.push(args); return { ok: true, message: 'played' }; },
      stopTts: async () => { stops.push(1); return { ok: true }; },
    }),
  });
  await feature.refreshVoices(fakeDoc);
  feature.init({ doc: fakeDoc });
  fireClick(fakeDoc.elements.addVoiceLayerButton);
  fakeDoc.elements.voicePreviewText.value = 'Current sample text';
  fakeDoc.elements.settingReviewTtsVoiceHint.value = 'af_nicole';
  fireClick(fakeDoc.elements.readAloudPlayButton);
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(calls[0][0], 'Current sample text');
  assert.equal(calls[0][1], 'af_nicole');
  assert.ok(calls[0][4].blend, 'Play sends the live blend, not a cached preset');
  assert.equal(fakeDoc.elements.readAloudPlaybackState.textContent, 'Ready — playback complete');

  fireClick(fakeDoc.elements.readAloudPauseButton);
  fireClick(fakeDoc.elements.readAloudStopButton);
  fireClick(fakeDoc.elements.readAloudRestartButton);
  await new Promise((resolve) => setImmediate(resolve));
  assert.ok(stops.length >= 3, 'Pause, Stop, and Restart each reach the TTS stop route');
  assert.equal(calls.length, 2, 'Restart starts the same read-aloud request again');
});

test('saved voice presets render the backend default as Active', async () => {
  const fakeDoc = makeFakeDoc();
  const rows = [];
  fakeDoc.elements.voicePresetList.appendChild = (child) => { rows.push(child); return child; };
  const feature = createVoiceStudioFeature({
    ui: {},
    hooks: {},
    api: makeApiStub({
      fetchVoicePresets: async () => ({
        presets: [{ name: 'Warm', base: 'af_heart', blend: {} }, { name: 'Crisp', base: 'af_nicole', blend: {} }],
        default: 'Crisp',
      }),
    }),
  });
  await feature.refreshVoices(fakeDoc);

  const activeRow = rows.find((row) => row._attrs['data-active'] === 'true');
  assert.ok(activeRow, 'the globally active preset is marked in the saved list');
  const controls = activeRow.children.find((child) => child.className === 'sd-actions-row');
  assert.deepEqual(
    controls.children.filter((child) => child.className.includes('sd-btn')).map((child) => child.textContent),
    ['Active', 'Apply', 'Rename', 'Duplicate', 'Delete'],
    'saved presets expose active/apply/rename/duplicate/delete actions',
  );
});

test('recorded voice samples use their own audio preview and expose discard/re-record controls', async () => {
  const created = {};
  const fakeDoc = makeFakeDoc({
    voiceCloneConsent: makeStubElement(),
    voiceCloneName: makeStubElement(),
    voiceCloneFile: makeStubElement(),
    voiceCloneUploadButton: makeStubElement(),
    voiceCloneResult: makeStubElement(),
  });
  fakeDoc.elements.voiceCloneUploadButton.appendChild = (child) => { created[child.id] = child; return child; };
  fakeDoc.elements.voiceCloneConsent.checked = true;
  fakeDoc.elements.voiceCloneFile.files = [{ name: 'my-recording.wav', duration: 4.2 }];
  const uploads = [];
  const feature = createVoiceStudioFeature({
    ui: {},
    hooks: {},
    api: makeApiStub({ cloneVoice: async (file) => { uploads.push(file); return { warnings: [] }; } }),
  });
  feature.init({ doc: fakeDoc });

  fireInput(fakeDoc.elements.voiceCloneFile, 'change');
  assert.equal(created.voiceClonePreviewButton.disabled, false, 'the preview action is enabled for the selected recording');
  assert.equal(created.voiceCloneDiscardButton.disabled, false, 'discard/re-record is offered for the selected recording');
  assert.match(created.voiceClonePlaybackState.textContent, /my-recording\.wav · 4\.2s/);
  fakeDoc.elements.voiceCloneName.value = 'My recorded voice';
  fireClick(fakeDoc.elements.voiceCloneUploadButton);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(uploads[0].name, 'my-recording.wav', 'upload uses the user sample, never synthesized preview text');
});

// --- Wave 12A: selected-voice visibility (product-owner finding 3) ----------
//
// "The user cannot SEE which voice is selected, nor what voices exist to
// blend." The select always HELD the answer; nothing rendered it as text. The
// three tests below pin the three ways that could regress: the readout not
// being filled at all, the readout not following the control, and the empty
// blend state going back to saying nothing useful.

test('the active voice is named in text once voices load (finding 3: which voice is selected)', async () => {
  const fakeDoc = makeFakeDoc();
  const feature = createVoiceStudioFeature({ ui: {}, hooks: {}, api: makeApiStub() });
  await feature.refreshVoices(fakeDoc);

  assert.equal(
    fakeDoc.elements.voiceActiveVoiceName.textContent,
    'Heart',
    'the readout must show the voice NAME, not its id and not a placeholder',
  );
});

test('the active-voice readout follows the select, rather than being a label set once', async () => {
  const fakeDoc = makeFakeDoc();
  const feature = createVoiceStudioFeature({ ui: {}, hooks: {}, api: makeApiStub() });
  await feature.refreshVoices(fakeDoc);
  feature.init({ doc: fakeDoc });

  fakeDoc.elements.settingReviewTtsVoiceHint.value = 'af_nicole';
  fireInput(fakeDoc.elements.settingReviewTtsVoiceHint, 'change');

  assert.equal(fakeDoc.elements.voiceActiveVoiceName.textContent, 'Nicole');
});

test('the base-voice select marks the profile dirty on change (there was no listener at all)', async () => {
  const fakeDoc = makeFakeDoc();
  let dirtyCalls = 0;
  const feature = createVoiceStudioFeature({
    ui: {},
    hooks: { markProfileDirty: () => { dirtyCalls += 1; } },
    api: makeApiStub(),
  });
  await feature.refreshVoices(fakeDoc);
  feature.init({ doc: fakeDoc });

  fakeDoc.elements.settingReviewTtsVoiceHint.value = 'af_nicole';
  fireInput(fakeDoc.elements.settingReviewTtsVoiceHint, 'change');

  assert.ok(
    dirtyCalls > 0,
    'changing the read-aloud voice is an unsaved edit; before Wave 12A this select had no change handler, ' +
      'so the save bar never noticed',
  );
});

test('the empty blend state names the voices available to blend (finding 3, second half)', async () => {
  const appended = [];
  const fakeDoc = makeFakeDoc();
  fakeDoc.elements.voiceBlendRows.appendChild = (child) => { appended.push(child); return child; };
  const feature = createVoiceStudioFeature({ ui: {}, hooks: {}, api: makeApiStub() });
  await feature.refreshVoices(fakeDoc);

  const empty = appended.at(-1);
  assert.ok(empty, 'the empty state must render something into #voiceBlendRows');
  assert.match(empty.textContent, /Heart/, 'names the voices, not just "no layers"');
  assert.match(empty.textContent, /Nicole/);
  assert.match(empty.textContent, /2 voices are available to blend/);
  assert.equal(
    empty.className,
    'sd-voice-studio__hint',
    'and does so with a class styles/signal-desk.css actually defines -- it used to be base.css-only `setting-desc`',
  );
});

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

// --- Wave 12 collab task A: refreshVoices()/refreshVoicePresets() retry-once +
// keep-last-good. Unlike library/studio/persona, bootstrap/signalDeskApp.js
// only re-fires refreshVoices() on a backend DOWN->UP transition, so a
// one-off slow response while the backend was never actually down would
// otherwise get no second chance at all.

test('refreshVoices retries once before giving up on a slow/failed first response', async () => {
  const fakeDoc = makeFakeDoc();
  let attempts = 0;
  const feature = createVoiceStudioFeature({
    ui: {},
    hooks: {},
    api: makeApiStub({
      fetchTtsVoices: async () => {
        attempts += 1;
        if (attempts === 1) throw new Error('socket hang up');
        return { defaults: [{ id: 'af_heart', name: 'Heart' }], cloned: [], cloning: { installed: false } };
      },
    }),
  });
  await feature.refreshVoices(fakeDoc);
  assert.equal(attempts, 2, 'a slow first response must be retried once, not treated as a dead endpoint');
  assert.equal(fakeDoc.elements.voiceActiveVoiceName.textContent, 'Heart');
});

test('a refreshVoices failure AFTER voices were already loaded keeps the picker as it was, and says so', async () => {
  const fakeDoc = makeFakeDoc();
  const toasts = [];
  let call = 0;
  const feature = createVoiceStudioFeature({
    ui: { setMessage() {}, showToast: (msg, tone) => toasts.push({ msg, tone }) },
    hooks: {},
    api: makeApiStub({
      fetchTtsVoices: async () => {
        call += 1;
        if (call <= 1) return { defaults: [{ id: 'af_heart', name: 'Heart' }], cloned: [], cloning: { installed: false } };
        throw new Error('backend down');
      },
    }),
  });
  await feature.refreshVoices(fakeDoc);
  assert.equal(fakeDoc.elements.voiceActiveVoiceName.textContent, 'Heart', 'sanity: the first refresh succeeded');

  await feature.refreshVoices(fakeDoc);
  assert.equal(
    fakeDoc.elements.voiceActiveVoiceName.textContent, 'Heart',
    'a later failed refresh must not blank a voice picker that was already populated',
  );
  assert.ok(
    toasts.some((t) => /Could not refresh voices/.test(t.msg)),
    'a total failure must be reported honestly, not silently swallowed',
  );
});

test('refreshVoicePresets retries once, and reports a total failure honestly', async () => {
  const fakeDoc = makeFakeDoc();
  const toasts = [];
  let attempts = 0;
  const feature = createVoiceStudioFeature({
    ui: { setMessage() {}, showToast: (msg, tone) => toasts.push({ msg, tone }) },
    hooks: {},
    api: makeApiStub({
      fetchVoicePresets: async () => {
        attempts += 1;
        throw new Error('backend down');
      },
    }),
  });
  await feature.refreshVoices(fakeDoc);
  assert.equal(attempts, 2, 'a slow first response must be retried once before it is treated as a failure');
  assert.ok(
    toasts.some((t) => /Could not refresh voice presets/.test(t.msg)),
    'a total presets failure must be reported honestly, separately from a voices failure',
  );
});

// --- Wave 12 collab task C: the Add-voice-layer button was a dead control --
// past the cap: its handler already refused a third layer, but nothing
// disabled the button, so a user at MAX_BLEND_LAYERS could click it forever
// with no feedback at all.

test('the Add voice layer button disables itself once MAX_BLEND_LAYERS is reached, with a reason', async () => {
  const fakeDoc = makeFakeDoc();
  const feature = createVoiceStudioFeature({ ui: {}, hooks: {}, api: makeApiStub() });
  await feature.refreshVoices(fakeDoc);
  feature.init({ doc: fakeDoc });

  assert.equal(fakeDoc.elements.addVoiceLayerButton.disabled, false, 'not at the cap yet');

  for (let i = 0; i < MAX_BLEND_LAYERS - 1; i += 1) {
    fireClick(fakeDoc.elements.addVoiceLayerButton);
    assert.equal(fakeDoc.elements.addVoiceLayerButton.disabled, false, `still under the cap after click ${i + 1}`);
  }
  fireClick(fakeDoc.elements.addVoiceLayerButton); // the MAX_BLEND_LAYERS-th layer
  assert.equal(fakeDoc.elements.addVoiceLayerButton.disabled, true, 'the button must go dead-and-honest, not dead-and-silent');
  assert.notEqual(fakeDoc.elements.addVoiceLayerButton.title, '', 'the reason must be stated, not just implied by disabled');
});

test('the Add voice layer button disables when runtime status rejects blending', async () => {
  const fakeDoc = makeFakeDoc();
  const feature = createVoiceStudioFeature({
    ui: {},
    hooks: {},
    api: makeApiStub({
      fetchTtsStatus: async () => ({
        raw_backend: 'native',
        capabilities: { runtime: 'native', blend_capable: false },
      }),
    }),
  });

  await feature.refreshVoices(fakeDoc);

  assert.equal(fakeDoc.elements.addVoiceLayerButton.disabled, true);
  assert.match(fakeDoc.elements.addVoiceLayerButton.title, /blending is not supported/);
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
