// Utilities -> Speech Input: the session/capability readout, the audio device
// picker and the whole wake-word group, driven through the real DOM wiring.
//
// CURRENT_UI_INVENTORY.md sections 7.3/7.9 and 8 (parity rows UI-07-026,
// UI-07-100, UI-07-103, UI-07-107, UI-07-108, UI-08-018, UI-14-012, UI-15-003,
// UI-15-010). utilitiesWorkspace.test.mjs covers the pure view-model helpers;
// the wake group's actual behaviour -- enable/disable round trip, the import
// status line, the training poll that drives the progress bar, and the verdict
// wording -- only exists inside createUtilitiesWorkspaceFeature() and needs a
// document to reach.
//
// The training poll is a real setInterval. It is driven here with node:test's
// mock timers rather than by sleeping, so the test asserts the poll's actual
// cadence and terminal states instead of racing them.
//
// Run with: node --test app/tests/utilitiesInputWake.test.mjs
import { test, mock } from 'node:test';
import assert from 'node:assert/strict';

import {
  UTILITIES_ELEMENT_IDS,
  collectUtilitiesElements,
  createUtilitiesWorkspaceFeature,
} from '../src/renderer/features/utilitiesWorkspace.js';
import { makeDocument, makeBackendBridge, installDomGlobals } from './helpers/rendererDom.mjs';

const INPUT_IDS = {
  audioDeviceSelect: 'sdUtilAudioDeviceSelect',
  audioMessage: 'sdUtilAudioMessage',
  hotkeySessionIndicator: 'sdUtilHotkeySessionIndicator',
  hotkeyWaylandWarning: 'sdUtilHotkeyWaylandWarning',
  hotkeyMessage: 'sdUtilHotkeyMessage',
};

const WAKE_IDS = {
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
  wakeEngineBadge: 'sdUtilWakeEngineBadge',
  wakeBackboneList: 'sdUtilWakeBackboneList',
  wakeMessage: 'sdUtilWakeMessage',
  modelsMessage: 'sdUtilModelsMessage',
};

test('the Speech Input ids this file drives are the ids the Utilities module ships', () => {
  for (const [key, id] of Object.entries({ ...INPUT_IDS, ...WAKE_IDS })) {
    assert.equal(UTILITIES_ELEMENT_IDS[key], id, `${key} is not ${id} any more`);
  }
});

const CAPABILITIES = {
  platform: 'linux', session_type: 'wayland', is_wayland: true, is_x11: false,
  supports_input_injection: true, supports_audio_ducking: true,
};

function mount({ routes = {}, uploadWakeModel, confirmFn } = {}) {
  const doc = makeDocument([...Object.values(INPUT_IDS), ...Object.values(WAKE_IDS)], {
    sdUtilAudioDeviceSelect: { tagName: 'select' },
    sdUtilWakeEnabledToggle: { tagName: 'input', type: 'checkbox' },
    sdUtilWakeModelSelect: { tagName: 'select' },
    sdUtilWakeImportFile: { tagName: 'input', type: 'file' },
    sdUtilWakeTrainPhrase: { tagName: 'input', type: 'text' },
    sdUtilWakeTrainButton: { tagName: 'button' },
  });
  const bridge = makeBackendBridge({ 'GET /capabilities': CAPABILITIES, ...routes });
  const toasts = [];
  const betterFingers = { backendRequest: bridge.request, uploadWakeModel };
  const restore = installDomGlobals({ document: doc, betterFingers });
  const feature = createUtilitiesWorkspaceFeature({
    elements: collectUtilitiesElements(doc),
    hooks: { showToast: (message, tone) => toasts.push({ message, tone }), ...(confirmFn ? { confirmFn } : {}) },
  });
  return { doc, feature, bridge, toasts, restore, el: (id) => doc.getElementById(id) };
}

// --- UI-07-026: the platform/session readout ---------------------------------

test('#sdUtilHotkeySessionIndicator reports platform and session type from GET /capabilities', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshHotkeyCapabilities();
  assert.ok(ctx.bridge.find('GET', '/capabilities'), 'the readout must come from the capabilities probe');
  assert.equal(ctx.el('sdUtilHotkeySessionIndicator').textContent, 'linux (wayland)');
  assert.equal(ctx.el('sdUtilHotkeyWaylandWarning').hidden, false, 'a Wayland session must raise the hotkey warning');
});

test('#sdUtilHotkeySessionIndicator says "unknown" rather than blank when the backend omits a field', async (t) => {
  const ctx = mount({ routes: { 'GET /capabilities': { is_wayland: false } } });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshHotkeyCapabilities();
  assert.equal(ctx.el('sdUtilHotkeySessionIndicator').textContent, 'unknown (unknown)');
  assert.equal(ctx.el('sdUtilHotkeyWaylandWarning').hidden, true);
});

test('a failed capabilities probe is reported, not silently absorbed', async (t) => {
  const ctx = mount({ routes: { 'GET /capabilities': { ok: false, status: 500, body: { detail: 'probe crashed' } } } });
  t.after(ctx.restore);
  ctx.feature.init();

  assert.equal(await ctx.feature.refreshHotkeyCapabilities(), null);
  assert.equal(ctx.el('sdUtilHotkeyMessage').textContent, 'Capabilities unavailable: probe crashed');
});

// --- UI-15-003: the audio device picker --------------------------------------

test('#sdUtilAudioDeviceSelect lists the reported input devices with a system-default entry', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();

  ctx.feature.setAudioDevices([{ index: 1, name: 'Yeti' }, { index: 2, name: 'Webcam mic' }], 1);
  const options = ctx.el('sdUtilAudioDeviceSelect').children.map((o) => o.textContent);
  assert.deepEqual(options, ['System default', 'Yeti (default)', 'Webcam mic']);
  assert.equal(ctx.el('sdUtilAudioDeviceSelect').children[1].value, '1', 'the option value is the device index the backend uses');
});

// --- UI-07-100: the live wake status -----------------------------------------

test('#sdUtilWakeStatusDetail shows the backend detail line and the toggle follows the real state', async (t) => {
  const ctx = mount({ routes: { 'GET /wake/status': { enabled: true, detail: 'Listening for "hey desk".' } } });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshWakeStatus();
  assert.ok(ctx.bridge.find('GET', '/wake/status'));
  assert.equal(ctx.el('sdUtilWakeStatusDetail').textContent, 'Listening for "hey desk".');
  assert.equal(ctx.el('sdUtilWakeEnabledToggle').checked, true);
});

test('#sdUtilWakeStatusDetail falls back to a plain on/off sentence when the backend sends no detail', async (t) => {
  const ctx = mount({ routes: { 'GET /wake/status': { enabled: false } } });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshWakeStatus();
  assert.equal(ctx.el('sdUtilWakeStatusDetail').textContent, 'Wake word is off.');
});

test('a failed wake enable puts the toggle back where it was and says why', async (t) => {
  const ctx = mount({
    routes: {
      'GET /wake/status': { enabled: false, detail: 'Wake word is off.' },
      'POST /wake/enable': { ok: false, status: 409, body: { detail: 'no wake model installed' } },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();

  const toggle = ctx.el('sdUtilWakeEnabledToggle');
  toggle.checked = true;
  toggle.emit('change');
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(toggle.checked, false, 'a control that did not take effect must not stay flipped');
  assert.equal(ctx.el('sdUtilWakeMessage').textContent, 'Could not enable wake word: no wake model installed');
});

// --- UI-07-103 / UI-15-010: importing a .onnx wake model ---------------------

test('#sdUtilWakeImportStatus tracks an import through to success, and the model name drops the .onnx suffix', async (t) => {
  const uploads = [];
  const ctx = mount({
    uploadWakeModel: async (payload) => { uploads.push(payload); return { ok: true, status: 200, body: { name: payload.name } }; },
  });
  t.after(ctx.restore);
  ctx.feature.init();

  const importFile = ctx.el('sdUtilWakeImportFile');
  assert.ok(importFile.listenerCount('change') > 0, 'the wake import input was never bound');
  importFile.files = [{
    name: 'Hey-Desk.onnx',
    arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer,
  }];
  importFile.emit('change');
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(uploads.length, 1);
  assert.equal(uploads[0].filename, 'Hey-Desk.onnx');
  assert.equal(uploads[0].name, 'Hey-Desk', 'the display name must not carry the file extension');
  assert.equal(ctx.el('sdUtilWakeImportStatus').textContent, 'Imported.');
});

test('#sdUtilWakeImportStatus reports a rejected import rather than leaving "Importing…" on screen', async (t) => {
  const ctx = mount({
    uploadWakeModel: async () => ({ ok: false, status: 415, body: { detail: 'not a valid onnx model' } }),
  });
  t.after(ctx.restore);
  ctx.feature.init();

  const importFile = ctx.el('sdUtilWakeImportFile');
  importFile.files = [{ name: 'notamodel.onnx', arrayBuffer: async () => new Uint8Array([0]).buffer }];
  importFile.emit('change');
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(ctx.el('sdUtilWakeImportStatus').textContent, 'Import failed: not a valid onnx model');
});

test('#sdUtilWakeImportButton is the visible affordance for the hidden file input', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();

  ctx.el('sdUtilWakeImportButton').click();
  assert.equal(ctx.el('sdUtilWakeImportFile').clickCount, 1, 'the button must open the real file picker');
});

// --- UI-07-107 / UI-07-108 / UI-14-012: training progress and verdict --------

test('#sdUtilWakeTrainProgress fills from the poll and #sdUtilWakeTrainResult states the verdict', async (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  t.after(() => mock.timers.reset());
  const statuses = [
    { status: 'running', message: 'Recording samples…', percent: 20 },
    { status: 'running', message: 'Fitting model…', percent: 70 },
    { status: 'done', percent: 100, result: { verdict: 'reliable', false_accepts: 0, false_rejects: 1 } },
  ];
  let index = 0;
  const ctx = mount({
    routes: {
      'POST /wake/train': { started: true },
      'GET /wake/train/status': () => statuses[Math.min(index++, statuses.length - 1)],
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();

  ctx.el('sdUtilWakeTrainPhrase').value = 'hey desk';
  ctx.el('sdUtilWakeTrainButton').click();
  await new Promise((resolve) => setImmediate(resolve));

  const progress = ctx.el('sdUtilWakeTrainProgress');
  assert.equal(progress.hidden, false, 'the progress bar must appear as soon as training starts');
  assert.equal(ctx.el('sdUtilWakeTrainButton').disabled, true, 'the button must not accept a second run mid-train');

  t.mock.timers.tick(2000);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ctx.el('sdUtilWakeTrainProgressLabel').textContent, 'Recording samples…');
  assert.equal(ctx.el('sdUtilWakeTrainProgressPercent').textContent, '20%');
  assert.equal(ctx.el('sdUtilWakeTrainProgressFill').style.width, '20%');

  t.mock.timers.tick(2000);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ctx.el('sdUtilWakeTrainProgressPercent').textContent, '70%');

  t.mock.timers.tick(2000);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(progress.hidden, true, 'a finished train must put the progress bar away');
  assert.equal(ctx.el('sdUtilWakeTrainButton').disabled, false);
  assert.match(ctx.el('sdUtilWakeTrainResult').textContent, /reliable/i);
});

test('#sdUtilWakeTrainResult reports a training error and re-enables the button', async (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  t.after(() => mock.timers.reset());
  const ctx = mount({
    routes: {
      'POST /wake/train': { started: true },
      'GET /wake/train/status': { status: 'error', message: 'Not enough clean samples.' },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();

  ctx.el('sdUtilWakeTrainPhrase').value = 'hey desk';
  ctx.el('sdUtilWakeTrainButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  t.mock.timers.tick(2000);
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(ctx.el('sdUtilWakeTrainResult').textContent, 'Not enough clean samples.');
  assert.equal(ctx.el('sdUtilWakeTrainProgress').hidden, true);
  assert.equal(ctx.el('sdUtilWakeTrainButton').disabled, false);
});

test('training refuses to start with an empty phrase, and nothing reaches the backend', async (t) => {
  const ctx = mount({ routes: { 'POST /wake/train': { started: true } } });
  t.after(ctx.restore);
  ctx.feature.init();

  ctx.el('sdUtilWakeTrainPhrase').value = '   ';
  ctx.el('sdUtilWakeTrainButton').click();
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(ctx.bridge.signatures(), []);
  assert.deepEqual(ctx.toasts, [{ message: 'Enter a phrase to train first.', tone: 'warning' }]);
});

// --- UI-08-018: the wake engine badge and backbone list ----------------------
//
// The real /wake/models route (routes_wake.py:299-303, wake_models.py
// list_wake_models()) returns {"models": [...]}, each entry carrying
// "downloaded" (not "installed") and an "origin" of "bundled" or
// "user-imported". These tests pin that exact shape -- a prior version of
// this suite pinned the WRONG {"backbones": [...], installed} shape, which
// is what let the renderer's read bug (UI-15-014) ship and survive.

test('#sdUtilWakeBackboneList renders one row per backbone from the real {models:[...]} payload, keyed on "downloaded"', async (t) => {
  const ctx = mount({
    routes: {
      'GET /wake/models': {
        models: [
          { id: 'embedding', name: 'Embedding backbone', origin: 'bundled', downloaded: true },
          { id: 'melspectrogram', name: 'Mel spectrogram', origin: 'bundled', downloaded: false },
        ],
      },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshWakeBackbones();
  assert.ok(ctx.bridge.find('GET', '/wake/models'), 'the backbone list must come from the wake models route');
  const text = ctx.el('sdUtilWakeBackboneList').textContent;
  assert.match(text, /Embedding backbone/);
  assert.match(text, /Installed/);
  assert.match(text, /Mel spectrogram/);
  assert.match(text, /Not installed/);
  assert.equal(ctx.el('sdUtilWakeEngineBadge').textContent, 'Ready', 'one downloaded backbone is enough for the engine to be ready');
});

test('#sdUtilWakeEngineBadge reads "Not installed" when nothing in the real payload is downloaded', async (t) => {
  const ctx = mount({
    routes: {
      'GET /wake/models': { models: [{ id: 'melspectrogram', name: 'Mel spectrogram', origin: 'bundled', downloaded: false }] },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshWakeBackbones();
  assert.equal(ctx.el('sdUtilWakeEngineBadge').textContent, 'Not installed');
});

test('#sdUtilWakeBackboneList shows the empty state (not a blank list) when there truly are no entries', async (t) => {
  const ctx = mount({ routes: { 'GET /wake/models': { models: [] } } });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshWakeBackbones();
  assert.match(ctx.el('sdUtilWakeBackboneList').textContent, /No wake-word backbones listed/);
});

// --- UI-15-014: deleting an imported wake model -------------------------------

function rowFor(list, name) {
  return list.children.find((row) => row.textContent.includes(name));
}

function buttonLabelled(row, label) {
  return row.querySelectorAll('button').find((b) => b.textContent === label) || null;
}

test('Delete is offered only for origin==="user-imported" rows, never for "bundled" catalog entries', async (t) => {
  const ctx = mount({
    routes: {
      'GET /wake/models': {
        models: [
          { id: 'melspectrogram', name: 'Melspectrogram feature extractor', origin: 'bundled', downloaded: true },
          { id: 'user_123', name: 'My Custom Wake Word', origin: 'user-imported', downloaded: true },
        ],
      },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshWakeBackbones();

  const list = ctx.el('sdUtilWakeBackboneList');
  const bundledRow = rowFor(list, 'Melspectrogram feature extractor');
  const importedRow = rowFor(list, 'My Custom Wake Word');
  assert.ok(bundledRow && importedRow, 'both rows must render');
  assert.equal(buttonLabelled(bundledRow, 'Delete'), null, 'a bundled/shipped model must never offer Delete');
  assert.ok(buttonLabelled(importedRow, 'Delete'), 'a user-imported model must offer Delete');
});

test('deleting an imported model asks for confirmation, calls DELETE, and refreshes the list', async (t) => {
  let listCallCount = 0;
  const ctx = mount({
    routes: {
      'GET /wake/models': () => {
        listCallCount += 1;
        return { models: listCallCount === 1 ? [{ id: 'user_123', name: 'My Custom Wake Word', origin: 'user-imported', downloaded: true }] : [] };
      },
      'DELETE /wake/models/user_123': { ok: true },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshWakeBackbones();
  assert.equal(listCallCount, 1);

  const deleteButton = buttonLabelled(rowFor(ctx.el('sdUtilWakeBackboneList'), 'My Custom Wake Word'), 'Delete');
  deleteButton.click();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.ok(ctx.bridge.find('DELETE', '/wake/models/user_123'), 'the delete must reach the real DELETE /wake/models/:id route');
  assert.equal(listCallCount, 2, 'a successful delete must refresh the list from the backend');
  assert.doesNotMatch(ctx.el('sdUtilWakeBackboneList').textContent, /My Custom Wake Word/, 'the deleted row must be gone after refresh');
});

test('declining the confirm leaves the model in place and never reaches the backend', async (t) => {
  const asked = [];
  const ctx = mount({
    confirmFn: (message) => { asked.push(message); return false; },
    routes: {
      'GET /wake/models': { models: [{ id: 'user_123', name: 'My Custom Wake Word', origin: 'user-imported', downloaded: true }] },
      'DELETE /wake/models/user_123': { ok: true },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshWakeBackbones();

  const deleteButton = buttonLabelled(rowFor(ctx.el('sdUtilWakeBackboneList'), 'My Custom Wake Word'), 'Delete');
  deleteButton.click();
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(asked.length, 1, 'a confirm prompt must be shown before deleting');
  assert.ok(!ctx.bridge.find('DELETE', '/wake/models/user_123'), 'declining the confirm must not call DELETE');
  assert.match(ctx.el('sdUtilWakeBackboneList').textContent, /My Custom Wake Word/, 'the row must remain when the user declines');
});

test('a failed delete surfaces an error visibly and re-enables the Delete button, never a silent no-op', async (t) => {
  const ctx = mount({
    routes: {
      'GET /wake/models': { models: [{ id: 'user_123', name: 'My Custom Wake Word', origin: 'user-imported', downloaded: true }] },
      'DELETE /wake/models/user_123': { ok: false, status: 500, body: { detail: 'disk error' } },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshWakeBackbones();

  const deleteButton = buttonLabelled(rowFor(ctx.el('sdUtilWakeBackboneList'), 'My Custom Wake Word'), 'Delete');
  deleteButton.click();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(ctx.el('sdUtilModelsMessage').textContent, 'Delete failed: disk error');
  assert.equal(deleteButton.disabled, false, 'the button must re-enable so the user can retry');
  assert.match(ctx.el('sdUtilWakeBackboneList').textContent, /My Custom Wake Word/, 'a failed delete must not remove the row');
});

test('deleting the currently-active model clears the selection instead of leaving a dangling reference', async (t) => {
  let savedSettings = null;
  const ctx = mount({
    routes: {
      'GET /settings/profiles': { active: 'Default', profiles: ['Default'] },
      'GET /settings/profiles/Default': { active: true, settings: { wake_word_model: 'user_123' } },
      'POST /settings/profiles/Default': ({ body }) => {
        savedSettings = body.settings;
        return { ok: true, active: true, settings: body.settings };
      },
      'GET /wake/models': { models: [{ id: 'user_123', name: 'My Custom Wake Word', origin: 'user-imported', downloaded: true }] },
      'DELETE /wake/models/user_123': { ok: true },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshWakeTuningFromProfile();
  assert.equal(ctx.el('sdUtilWakeModelSelect').value, 'user_123', 'the select must start out showing the active model');

  await ctx.feature.refreshWakeBackbones();
  const deleteButton = buttonLabelled(rowFor(ctx.el('sdUtilWakeBackboneList'), 'My Custom Wake Word'), 'Delete');
  deleteButton.click();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(ctx.el('sdUtilWakeModelSelect').value, '', 'the UI must not keep claiming the deleted model is still selected');
  assert.equal(savedSettings?.wake_word_model, '', 'the persisted profile field must be cleared too, not just the on-screen select');
});
