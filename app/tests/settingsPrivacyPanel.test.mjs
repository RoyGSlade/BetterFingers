// Settings -> Privacy: the read-out panels and the wipe confirmation,
// rendered through the real DOM wiring.
//
// CURRENT_UI_INVENTORY.md section 7.14 (parity rows UI-07-171, -172, -173,
// -174, -176). The Wave 6 store table, persona-learning disclosure and factory
// reset already have their own suites; what nothing exercised is the part this
// screen is judged on -- that the network list, the on-device data list, the
// wake-listener note and the result line are actually painted from one
// GET /privacy report, and that the wipe confirmation names the same stores
// that report says are present.
//
// The privacy wipe does NOT go through the generic proxy: api/backend.js sends
// it down a dedicated typed IPC method (`wipePrivacyData`), which is why the
// bridge here exposes both.
//
// Run with: node --test app/tests/settingsPrivacyPanel.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  SETTINGS_ELEMENT_IDS,
  collectSettingsElements,
  createSettingsWorkspaceFeature,
} from '../src/renderer/features/settingsWorkspace.js';
import { makeDocument, makeBackendBridge, installDomGlobals } from './helpers/rendererDom.mjs';

const PRIVACY_IDS = {
  privacyNetworkList: 'sdSetPrivacyNetworkList',
  privacyDataList: 'sdSetPrivacyDataList',
  privacyWakeListenerStatus: 'sdSetPrivacyWakeListenerStatus',
  privacyWipeVoices: 'sdSetPrivacyWipeVoices',
  privacyWipeButton: 'sdSetPrivacyWipeButton',
  privacyMessage: 'sdSetPrivacyMessage',
  privacyWipeMode: 'sdSetPrivacyWipeMode',
  privacyWipePreview: 'sdSetPrivacyWipePreview',
  privacyStoreList: 'sdSetPrivacyStoreList',
  privacyUnmappedWarning: 'sdSetPrivacyUnmappedWarning',
  privacyFactoryResetPreview: 'sdSetPrivacyFactoryResetPreview',
};

test('the privacy ids this file drives are the ids the module ships', () => {
  for (const [key, id] of Object.entries(PRIVACY_IDS)) {
    assert.equal(SETTINGS_ELEMENT_IDS[key], id, `${key} is not ${id} any more`);
  }
});

const PRIVACY_REPORT = {
  network_touchpoints: [
    { name: 'Local LLM', direction: 'on-device', hosts: [], purpose: 'Cleanup runs on this machine.' },
    { name: 'Model download', direction: 'outbound', hosts: ['huggingface.co'], purpose: 'Fetching a model you asked for.' },
  ],
  data_locations: [
    { name: 'Drafts', bytes: 2048, path: '/home/u/.betterfingers/drafts.db' },
    { name: 'Recordings', bytes: 5 * 1024 * 1024, path: '/home/u/.betterfingers/recordings' },
  ],
  wake_listener: { active: true, note: 'Audio never leaves the device.' },
  stores: [
    { name: 'Drafts', present: true, bytes: 2048, path: '/home/u/.betterfingers/drafts.db', wipe_modes: ['clear_conversations'], may_contain_user_text: true },
    { name: 'Cloned voices', present: false, bytes: 0, wipe_modes: ['factory_reset'], may_contain_user_text: false },
  ],
  unmapped_files: [],
  wipe_modes: {
    clear_conversations: { bytes: 2048, categories: [{ label: 'Drafts', bytes: 2048, present: true }, { label: 'Contacts', bytes: 0, present: false }] },
    factory_reset: { bytes: 4096, categories: [{ label: 'Drafts', bytes: 2048, present: true }, { label: 'Personas', bytes: 2048, present: true }] },
  },
};

function mount({ report = PRIVACY_REPORT, wipeResult = { ok: true, cleared: { drafts: 3 } }, confirmFn = () => true } = {}) {
  const doc = makeDocument(Object.values(PRIVACY_IDS), {
    sdSetPrivacyWipeVoices: { tagName: 'input', type: 'checkbox' },
    sdSetPrivacyWipeMode: { tagName: 'select', value: 'clear_conversations' },
    sdSetPrivacyWipeButton: { tagName: 'button' },
  });
  const bridge = makeBackendBridge({ 'GET /privacy': report });
  const wipeCalls = [];
  const toasts = [];
  const betterFingers = {
    backendRequest: bridge.request,
    wipePrivacyData: async (payload) => {
      wipeCalls.push(payload);
      return typeof wipeResult === 'function' ? wipeResult(payload) : { ok: true, status: 200, body: wipeResult };
    },
  };
  const restore = installDomGlobals({ document: doc, betterFingers });
  const feature = createSettingsWorkspaceFeature({
    elements: collectSettingsElements(doc),
    hooks: { confirmFn, showToast: (message, tone) => toasts.push({ message, tone }) },
  });
  return { doc, feature, bridge, wipeCalls, toasts, restore, el: (id) => doc.getElementById(id) };
}

/** The key/value pairs a detail list ended up rendering, as "key -> value". */
function rowsOf(el) {
  return el.children.map((row) => row.children.map((cell) => cell.textContent).join(' -> '));
}

// --- UI-07-171: the network touchpoint list ----------------------------------

test('#sdSetPrivacyNetworkList is painted from GET /privacy, tagging outbound vs on-device', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshAll();
  assert.ok(ctx.bridge.find('GET', '/privacy'), 'fetchPrivacy() must be the source');

  const rows = rowsOf(ctx.el('sdSetPrivacyNetworkList'));
  assert.deepEqual(rows, [
    'Local LLM — on-device -> Cleanup runs on this machine.',
    'Model download — outbound (huggingface.co) -> Fetching a model you asked for.',
  ]);
});

test('#sdSetPrivacyNetworkList says so plainly when there is no network activity at all', async (t) => {
  const ctx = mount({ report: { ...PRIVACY_REPORT, network_touchpoints: [] } });
  t.after(ctx.restore);
  ctx.feature.renderPrivacyReport({ ...PRIVACY_REPORT, network_touchpoints: [] });
  assert.match(ctx.el('sdSetPrivacyNetworkList').innerHTML, /No network activity\./);
});

test('#sdSetPrivacyNetworkList reports a failed fetch instead of showing a reassuring empty list', async (t) => {
  const ctx = mount({ report: { ok: false, status: 503, body: { detail: 'backend is down' } } });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshAll();
  assert.match(ctx.el('sdSetPrivacyNetworkList').innerHTML, /Privacy report unavailable: backend is down/);
});

// --- UI-07-172: the on-device data list --------------------------------------

test('#sdSetPrivacyDataList lists every on-device location with a human size and its path', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.renderPrivacyReport(PRIVACY_REPORT);

  assert.deepEqual(rowsOf(ctx.el('sdSetPrivacyDataList')), [
    'Drafts -> 2.0 KB · /home/u/.betterfingers/drafts.db',
    'Recordings -> 5.0 MB · /home/u/.betterfingers/recordings',
  ]);
});

test('#sdSetPrivacyDataList is rebuilt, not appended to, on a re-render', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.renderPrivacyReport(PRIVACY_REPORT);
  ctx.feature.renderPrivacyReport(PRIVACY_REPORT);
  assert.equal(rowsOf(ctx.el('sdSetPrivacyDataList')).length, 2, 'a second report must replace the list, not double it');
});

// --- UI-07-173: the wake-listener note ---------------------------------------

test('#sdSetPrivacyWakeListenerStatus states whether the wake listener is live, with the backend note', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.renderPrivacyReport(PRIVACY_REPORT);
  assert.equal(
    ctx.el('sdSetPrivacyWakeListenerStatus').textContent,
    'Active — listening for the wake phrase. Audio never leaves the device.',
  );

  ctx.feature.renderPrivacyReport({ ...PRIVACY_REPORT, wake_listener: { active: false, note: '' } });
  assert.equal(ctx.el('sdSetPrivacyWakeListenerStatus').textContent, 'Not active.');
});

test('#sdSetPrivacyWakeListenerStatus does not guess when the backend reports nothing', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.renderPrivacyReport({ ...PRIVACY_REPORT, wake_listener: undefined });
  assert.equal(ctx.el('sdSetPrivacyWakeListenerStatus').textContent, 'Not reported by the backend.');
});

// --- UI-07-174 / UI-07-176: the wipe checkbox, its confirmation and the result line ---

test('the wipe confirmation names the stores the preview says are present, and nothing else', async (t) => {
  const prompts = [];
  const ctx = mount({ confirmFn: (message) => { prompts.push(message); return true; } });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshAll();

  await ctx.feature.handleWipe();

  assert.equal(prompts.length, 1);
  assert.match(prompts[0], /Permanently delete Drafts\? This cannot be undone\./);
  assert.equal(prompts[0].includes('Contacts'), false, 'a store the preview reports absent must not be named');
});

test('#sdSetPrivacyWipeVoices adds the cloned voices to the confirmation and to the request', async (t) => {
  const prompts = [];
  const ctx = mount({ confirmFn: (message) => { prompts.push(message); return true; } });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshAll();

  const wipeVoices = ctx.el('sdSetPrivacyWipeVoices');
  wipeVoices.checked = true;
  await ctx.feature.handleWipe();

  assert.match(prompts[0], /plus your cloned voices/);
  assert.equal(ctx.wipeCalls.length, 1);
  assert.equal(ctx.wipeCalls[0].wipeVoices, true);
  assert.equal(ctx.wipeCalls[0].confirm, true, 'the explicit-confirmation flag must reach the backend');
  assert.equal(ctx.wipeCalls[0].mode, 'clear_conversations');
});

test('declining the confirmation performs no wipe at all', async (t) => {
  const ctx = mount({ confirmFn: () => false });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshAll();

  await ctx.feature.handleWipe();
  assert.deepEqual(ctx.wipeCalls, []);
  assert.equal(ctx.el('sdSetPrivacyMessage').textContent, '');
});

test('#sdSetPrivacyMessage reports a completed wipe and the button is re-enabled', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshAll();

  await ctx.feature.handleWipe();
  assert.equal(ctx.el('sdSetPrivacyMessage').textContent, 'Your data was wiped.');
  assert.equal(ctx.el('sdSetPrivacyWipeButton').disabled, false, 'the button must not be left stuck disabled');
  assert.deepEqual(ctx.toasts, [{ message: 'Data wiped (3 drafts cleared).', tone: 'success' }]);
});

test('#sdSetPrivacyMessage reports a PARTIAL wipe as a failure, naming what survived', async (t) => {
  // The one that matters: a backend that answers 200 with ok:false has NOT
  // deleted the data, and a screen that says "wiped" there is lying.
  const ctx = mount({
    wipeResult: {
      ok: false,
      message: 'The privacy wipe did not complete.',
      cleared: { drafts: 1 },
      failures: [{ category: 'recordings', error: 'file in use' }],
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshAll();

  await ctx.feature.handleWipe();
  const message = ctx.el('sdSetPrivacyMessage').textContent;
  assert.match(message, /did not complete/);
  assert.equal(message.length > 'The privacy wipe did not complete.'.length, true, 'the failure summary must be shown, not swallowed');
  assert.equal(ctx.toasts[0].tone, 'danger');
  assert.equal(ctx.el('sdSetPrivacyWipeButton').disabled, false);
});

test('changing #sdSetPrivacyWipeMode re-reads the preview so the list matches the button', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshAll();
  assert.deepEqual(rowsOf(ctx.el('sdSetPrivacyWipePreview')), ['Drafts -> 2.0 KB']);

  const mode = ctx.el('sdSetPrivacyWipeMode');
  assert.ok(mode.listenerCount('change') > 0, 'the wipe-mode select was never bound');
  mode.value = 'factory_reset';
  mode.emit('change');
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(rowsOf(ctx.el('sdSetPrivacyWipePreview')), ['Drafts -> 2.0 KB', 'Personas -> 2.0 KB']);
});

test('a file no category claims is surfaced as an incompleteness, not hidden', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.renderPrivacyReport({ ...PRIVACY_REPORT, unmapped_files: ['/home/u/.betterfingers/mystery.bin'] });

  const warning = ctx.el('sdSetPrivacyUnmappedWarning');
  assert.equal(warning.hidden, false);
  assert.match(warning.textContent, /1 file\(s\) on this device are not covered/);
  assert.match(warning.textContent, /mystery\.bin/);
});
