// Utilities workspace -- resilient list/panel loading (the blank-on-failure
// antipattern documented by bootstrap/signalDeskApp.js's loadPersonaList()):
// a failed fetch must retry once, then either keep a previously-good render
// exactly as it was or, if nothing has ever loaded, say plainly that the
// check failed rather than rendering an empty/dishonest state. Also covers
// the cold-start / mid-session-backend-restart idempotency guarantee that a
// background refreshAll() must not blank a field the user is actively
// editing, or pin every later save to the wrong profile after one transient
// failure.
//
// Run with: node --test app/tests/utilitiesResilientLoading.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  UTILITIES_ELEMENT_IDS,
  collectUtilitiesElements,
  createUtilitiesWorkspaceFeature,
} from '../src/renderer/features/utilitiesWorkspace.js';
import { makeDocument, makeBackendBridge, installDomGlobals } from './helpers/rendererDom.mjs';

const DOCTOR_PAYLOAD = {
  stt: { loaded: true, initialized: true },
  llm: { ready: true },
  models: { default_model_exists: true, llama_server_exists: true },
};

const IDS = {
  doctorRefreshButton: 'sdUtilDoctorRefreshButton',
  doctorCardsGrid: 'sdUtilDoctorCardsGrid',
  doctorRecoveryPanel: 'sdUtilDoctorRecoveryPanel',
  doctorRecoveryList: 'sdUtilDoctorRecoveryList',
  jobsList: 'sdUtilJobsList',
  diagnosticsMessage: 'sdUtilDiagnosticsMessage',
  sidecarLogsTail: 'sdUtilSidecarLogsTail',
  runtimeErrorsList: 'sdUtilRuntimeErrorsList',
  audioDeviceSelect: 'sdUtilAudioDeviceSelect',
  audioMessage: 'sdUtilAudioMessage',
  wakeSensitivity: 'sdUtilWakeSensitivity',
  wakeMessage: 'sdUtilWakeMessage',
};

const HOTKEY_RECORDING_IDS = UTILITIES_ELEMENT_IDS.hotkeyFields.hotkey;

function mount({ routes = {}, sidecarLogs } = {}) {
  const doc = makeDocument(
    [...Object.values(IDS), HOTKEY_RECORDING_IDS.input, HOTKEY_RECORDING_IDS.clear, HOTKEY_RECORDING_IDS.error],
    {
      sdUtilDoctorRefreshButton: { tagName: 'button' },
      sdUtilAudioDeviceSelect: { tagName: 'select' },
      sdUtilWakeSensitivity: { tagName: 'input', type: 'number' },
      [HOTKEY_RECORDING_IDS.input]: { tagName: 'input', type: 'text' },
    },
  );
  const bridge = makeBackendBridge(routes);
  const betterFingers = {
    backendRequest: bridge.request,
    getSidecarLogs: sidecarLogs,
  };
  const restore = installDomGlobals({ document: doc, betterFingers });
  const feature = createUtilitiesWorkspaceFeature({ elements: collectUtilitiesElements(doc) });
  return { doc, feature, bridge, restore, el: (id) => doc.getElementById(id) };
}

// --- retry-once: proves the wrapper actually retries, not just documents it --

test('refreshDoctor retries once before giving up, so a slow-then-ok backend recovers silently', async (t) => {
  let calls = 0;
  const ctx = mount({
    routes: {
      'GET /doctor?refresh_audio=true': () => {
        calls += 1;
        return calls === 1 ? { ok: false, status: 500, body: { detail: 'transient' } } : DOCTOR_PAYLOAD;
      },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshDoctor();
  assert.equal(calls, 2, 'a single failure must be retried once before the panel gives up');
  assert.equal(ctx.el('sdUtilDoctorCardsGrid').children.length, 8, 'the retry succeeded, so real cards must render');
});

// Caught in supervisor review of this lane: the rewrite that added the
// keep-last-good branches replaced refreshDoctor's `try { … } finally { … }`
// with a plain trailing re-enable block. attemptFetch() cannot reject, so the
// change looked equivalent -- but renderDoctorCards() builds the whole 8-card
// grid and CAN throw, and a trailing block is skipped when it does. The button
// then sits disabled reading "Running check…" with no way back, which is a
// worse dead control than the blank grid the rewrite was fixing. Restored to
// try/finally and pinned here, because the equivalence is tempting enough to
// be redone by the next person who touches this function.
test('the Run Doctor Check button is re-enabled even if rendering the cards throws', async (t) => {
  const ctx = mount({ routes: { 'GET /doctor?refresh_audio=true': () => DOCTOR_PAYLOAD } });
  t.after(ctx.restore);
  ctx.feature.init();

  const grid = ctx.el('sdUtilDoctorCardsGrid');
  grid.append = () => {
    throw new Error('render exploded');
  };

  await assert.rejects(() => ctx.feature.refreshDoctor(), /render exploded/);

  const button = ctx.el('sdUtilDoctorRefreshButton');
  assert.equal(button.disabled, false, 'a throw during render must not strand the button disabled');
  assert.equal(button.textContent, 'Run Doctor Check', 'the button must not be stuck reading "Running check…"');
});

// --- keep-last-good: a panel that already has real data must not be blanked -

test('a doctor re-check that fails after a previous success keeps the cards and reports through the shared message', async (t) => {
  let succeed = true;
  const ctx = mount({
    routes: { 'GET /doctor?refresh_audio=true': () => (succeed ? DOCTOR_PAYLOAD : { ok: false, status: 500, body: { detail: 'doctor timed out' } }) },
  });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshDoctor();
  assert.equal(ctx.el('sdUtilDoctorCardsGrid').children.length, 8);

  succeed = false;
  await ctx.feature.refreshDoctor();
  assert.equal(ctx.el('sdUtilDoctorCardsGrid').children.length, 8, 'a transient re-check failure must not wipe a working grid');
  assert.match(ctx.el('sdUtilDiagnosticsMessage').textContent, /doctor timed out/);
});

test('a jobs refresh that fails after a previous success keeps the list (and its live Cancel control) on screen', async (t) => {
  let succeed = true;
  const ctx = mount({
    routes: {
      'GET /jobs?active=1': () => (succeed
        ? { jobs: [{ id: 'job-1', kind: 'transcribe', state: 'running' }] }
        : { ok: false, status: 500, body: { detail: 'jobs endpoint down' } }),
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshJobsList();
  assert.equal(ctx.el('sdUtilJobsList').children.length, 1);

  succeed = false;
  await ctx.feature.refreshJobsList();
  assert.equal(ctx.el('sdUtilJobsList').children.length, 1, 'a failed refresh must not strand or lose the live Cancel control');
  assert.match(ctx.el('sdUtilDiagnosticsMessage').textContent, /jobs endpoint down/);
});

test('a failed audio-device refresh after a previous success keeps the picker populated', async (t) => {
  let succeed = true;
  const ctx = mount({
    routes: {
      'GET /runtime/audio-devices': () => (succeed
        ? { devices: [{ index: 1, name: 'Yeti', max_input_channels: 2 }], default_input_device: 1 }
        : { ok: false, status: 500, body: { detail: 'probe crashed' } }),
      'GET /settings/profiles': { ok: false, status: 404, body: { detail: 'no profile route stubbed' } },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();
  // refreshAudioDevices_ isn't exported on the feature -- drive it via refreshAll().
  await ctx.feature.refreshAll();
  const optionsAfterSuccess = ctx.el('sdUtilAudioDeviceSelect').children.map((o) => o.textContent);
  assert.deepEqual(optionsAfterSuccess, ['System default', 'Yeti (default)']);

  succeed = false;
  await ctx.feature.refreshAll();
  const optionsAfterFailure = ctx.el('sdUtilAudioDeviceSelect').children.map((o) => o.textContent);
  assert.deepEqual(optionsAfterFailure, optionsAfterSuccess, 'a transient probe failure must not blank a working device picker');
  assert.match(ctx.el('sdUtilAudioMessage').textContent, /probe crashed/);
});

// --- honest failure vs dishonest empty: a panel that has NEVER loaded must --
// --- say so, not claim the real-empty-state text for a different reason ----

test('sidecar logs that have never loaded report the failure honestly instead of claiming there are none', async (t) => {
  const ctx = mount({ sidecarLogs: async () => { throw new Error('ipc broken'); } });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshSidecarLogs();
  assert.equal(ctx.el('sdUtilSidecarLogsTail').textContent, 'Sidecar logs unavailable: ipc broken');
});

test('sidecar logs that fail after a previous successful load keep the last tail on screen', async (t) => {
  let succeed = true;
  const ctx = mount({ sidecarLogs: async () => { if (succeed) return ['line one']; throw new Error('ipc broken'); } });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshSidecarLogs();
  assert.equal(ctx.el('sdUtilSidecarLogsTail').textContent, 'line one');

  succeed = false;
  await ctx.feature.refreshSidecarLogs();
  assert.equal(ctx.el('sdUtilSidecarLogsTail').textContent, 'line one', 'a failed refresh must not blank a previously loaded tail');
});

test('runtime errors that have never loaded report the check failed instead of claiming a clean bill of health', async (t) => {
  const ctx = mount({ routes: { 'GET /runtime/errors': { ok: false, status: 500, body: { detail: 'errors endpoint down' } } } });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshRuntimeErrors();
  assert.match(ctx.el('sdUtilRuntimeErrorsList').textContent, /Could not check for runtime errors: errors endpoint down/);
});

test('runtime errors that fail after a previous successful load keep the last list on screen', async (t) => {
  let succeed = true;
  const ctx = mount({
    routes: { 'GET /runtime/errors': () => (succeed ? { errors: [{ severity: 'fatal', component: 'stt', message: 'boom' }] } : { ok: false, status: 500, body: { detail: 'down' } }) },
  });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshRuntimeErrors();
  assert.match(ctx.el('sdUtilRuntimeErrorsList').textContent, /boom/);

  succeed = false;
  await ctx.feature.refreshRuntimeErrors();
  assert.match(ctx.el('sdUtilRuntimeErrorsList').textContent, /boom/, 'a failed refresh must not blank the last known errors');
});

// --- Task B: refreshAll() must not destroy in-progress user input ----------

test('refreshHotkeys does not overwrite a hotkey field the user is actively focused on', async (t) => {
  const ctx = mount({
    routes: { 'GET /settings/profiles': { active: 'Default', profiles: ['Default'] }, 'GET /settings/profiles/Default': { settings: { hotkey: 'Ctrl+Space' } } },
  });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshHotkeys();
  assert.equal(ctx.el(HOTKEY_RECORDING_IDS.input).value, 'Ctrl+Space');

  // The user clicks in to record a new chord (click-to-record parks real DOM
  // focus on the input and shows a placeholder) exactly as a background
  // refreshAll() re-populate fires mid-session.
  const input = ctx.el(HOTKEY_RECORDING_IDS.input);
  input.value = 'Press a key…';
  input.focus();
  await ctx.feature.refreshHotkeys();
  assert.equal(input.value, 'Press a key…', 'a field the user is focused on must not be overwritten mid-interaction');
});

test('refreshWakeTuningFromProfile does not overwrite a number field the user is mid-typing', async (t) => {
  const ctx = mount({
    routes: { 'GET /settings/profiles': { active: 'Default', profiles: ['Default'] }, 'GET /settings/profiles/Default': { settings: { wake_word_sensitivity: 0.5 } } },
  });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshWakeTuningFromProfile();
  assert.equal(ctx.el('sdUtilWakeSensitivity').value, 0.5);

  const field = ctx.el('sdUtilWakeSensitivity');
  field.value = '0.9';
  field.focus();
  await ctx.feature.refreshWakeTuningFromProfile();
  assert.equal(field.value, '0.9', 'keystrokes in progress must survive a background repopulate');
});

// --- Task B: a transient profile-list failure must not pin every later save
// --- to the wrong profile forever --------------------------------------------

test('a failed profile-list fetch does not permanently pin later saves to "Default"', async (t) => {
  let profilesCallCount = 0;
  const ctx = mount({
    routes: {
      'GET /settings/profiles': () => {
        profilesCallCount += 1;
        return profilesCallCount === 1
          ? { ok: false, status: 500, body: { detail: 'down' } }
          : { active: 'Work', profiles: ['Default', 'Work'] };
      },
      'GET /settings/profiles/Work': { settings: {} },
      'GET /settings/profiles/Default': { settings: {} },
      'POST /settings/profiles/Work': ({ body }) => ({ profile: 'Work', settings: body.settings }),
      'POST /settings/profiles/Default': ({ body }) => ({ profile: 'Default', settings: body.settings }),
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();

  const field = ctx.el('sdUtilWakeSensitivity');
  field.value = '0.4';
  field.emit('change');
  await new Promise((resolve) => setImmediate(resolve));
  assert.ok(ctx.bridge.find('POST', '/settings/profiles/Default'), 'while the backend is still cold, the fallback save targets Default');

  field.value = '0.6';
  field.emit('change');
  await new Promise((resolve) => setImmediate(resolve));
  assert.ok(ctx.bridge.find('POST', '/settings/profiles/Work'), 'once the backend recovers, saves must target the REAL active profile, not stay pinned to Default');
});

test('a failed settings fetch does not blank previously-loaded hotkey/wake-tuning fields', async (t) => {
  let succeed = true;
  const ctx = mount({
    routes: {
      'GET /settings/profiles': { active: 'Default', profiles: ['Default'] },
      'GET /settings/profiles/Default': () => (succeed
        ? { settings: { hotkey: 'Ctrl+Space', wake_word_sensitivity: 0.5 } }
        : { ok: false, status: 500, body: { detail: 'backend restarting' } }),
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshHotkeys();
  await ctx.feature.refreshWakeTuningFromProfile();
  assert.equal(ctx.el(HOTKEY_RECORDING_IDS.input).value, 'Ctrl+Space');
  assert.equal(ctx.el('sdUtilWakeSensitivity').value, 0.5);

  succeed = false;
  await ctx.feature.refreshHotkeys();
  await ctx.feature.refreshWakeTuningFromProfile();
  assert.equal(ctx.el(HOTKEY_RECORDING_IDS.input).value, 'Ctrl+Space', 'a mid-session backend hiccup must not blank the hotkey field');
  assert.equal(ctx.el('sdUtilWakeSensitivity').value, 0.5, 'a mid-session backend hiccup must not blank the wake-tuning field');
});
