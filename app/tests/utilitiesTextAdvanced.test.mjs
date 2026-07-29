// Utilities -> Text Tools and Advanced: the dictionary, the macro table, the
// warm-up buttons and the capability dump with its three conditional warnings,
// driven through the real DOM wiring.
//
// CURRENT_UI_INVENTORY.md sections 7.7/7.8/7.12/7.13 and 9 (parity rows
// UI-07-091, -092, -093, -095, -165, -166, -167, -168, -170, -177, -178, -179,
// -182, -186, -187 and UI-09-011). These are chip lists, status lines and
// conditional banners: everything they do happens in the DOM, so none of it
// was reachable from the pure-helper suite.
//
// Run with: node --test app/tests/utilitiesTextAdvanced.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  UTILITIES_ELEMENT_IDS,
  collectUtilitiesElements,
  createUtilitiesWorkspaceFeature,
} from '../src/renderer/features/utilitiesWorkspace.js';
import { makeDocument, makeBackendBridge, installDomGlobals } from './helpers/rendererDom.mjs';

const TEXT_IDS = {
  dictionaryInput: 'sdUtilDictionaryInput',
  dictionaryAddButton: 'sdUtilDictionaryAddButton',
  dictionarySuggestGroup: 'sdUtilDictionarySuggestGroup',
  dictionarySuggestions: 'sdUtilDictionarySuggestions',
  dictionaryList: 'sdUtilDictionaryList',
  dictionaryMessage: 'sdUtilDictionaryMessage',
  macroTrigger: 'sdUtilMacroTrigger',
  macroExpansion: 'sdUtilMacroExpansion',
  macroAddButton: 'sdUtilMacroAddButton',
  macrosList: 'sdUtilMacrosList',
  macrosMessage: 'sdUtilMacrosMessage',
};

const ADVANCED_IDS = {
  warmupSttButton: 'sdUtilWarmupSttButton',
  warmupLlmButton: 'sdUtilWarmupLlmButton',
  startHotkeysButton: 'sdUtilStartHotkeysButton',
  testModelLoadButton: 'sdUtilTestModelLoadButton',
  warmupMessage: 'sdUtilWarmupMessage',
  outputSettingsSummary: 'sdUtilOutputSettingsSummary',
  capabilitiesList: 'sdUtilCapabilitiesList',
  runtimeStatusList: 'sdUtilRuntimeStatusList',
  waylandInjectionWarning: 'sdUtilWaylandInjectionWarning',
  injectionUnavailableWarning: 'sdUtilInjectionUnavailableWarning',
  audioDuckingWarning: 'sdUtilAudioDuckingWarning',
  audioDucking: 'sdUtilAudioDucking',
  testPasteCopyButton: 'sdUtilTestPasteCopyButton',
  sendInjectionMessage: 'sdUtilSendInjectionMessage',
};

test('the Text Tools and Advanced ids this file drives are the ids the module ships', () => {
  for (const [key, id] of Object.entries({ ...TEXT_IDS, ...ADVANCED_IDS })) {
    assert.equal(UTILITIES_ELEMENT_IDS[key], id, `${key} is not ${id} any more`);
  }
});

const FULL_CAPABILITIES = {
  platform: 'linux', session_type: 'x11', is_linux: true, is_wayland: false, is_x11: true,
  supports_basic_clipboard: true, supports_rich_clipboard_restore: true,
  supports_input_injection: true, injection_method: 'xdotool', supports_typing: true,
  supports_global_hotkeys: true, supports_audio_ducking: true,
  supports_stt: true, supports_llm: true, supports_tts: true,
};

function mount({ routes = {}, clipboard } = {}) {
  const doc = makeDocument([...Object.values(TEXT_IDS), ...Object.values(ADVANCED_IDS)], {
    sdUtilDictionaryInput: { tagName: 'input', type: 'text' },
    sdUtilMacroTrigger: { tagName: 'input', type: 'text' },
    sdUtilMacroExpansion: { tagName: 'input', type: 'text' },
    sdUtilAudioDucking: { tagName: 'input', type: 'checkbox' },
  });
  const bridge = makeBackendBridge(routes);
  const toasts = [];
  const clipboardWrites = [];
  const betterFingers = {
    backendRequest: bridge.request,
    writeClipboardText: clipboard || (async (text) => { clipboardWrites.push(text); }),
  };
  const restore = installDomGlobals({ document: doc, betterFingers });
  const feature = createUtilitiesWorkspaceFeature({
    elements: collectUtilitiesElements(doc),
    hooks: { showToast: (message, tone) => toasts.push({ message, tone }) },
  });
  return { doc, feature, bridge, toasts, clipboardWrites, restore, el: (id) => doc.getElementById(id) };
}

// --- UI-07-165 / UI-07-167: the dictionary -----------------------------------

test('#sdUtilDictionaryAddButton POSTs the trimmed term to /dictionary and empties the input', async (t) => {
  const ctx = mount({ routes: { 'POST /dictionary': { terms: ['kubectl'] } } });
  t.after(ctx.restore);
  ctx.feature.init();

  const input = ctx.el('sdUtilDictionaryInput');
  input.value = '  kubectl  ';
  const addButton = ctx.el('sdUtilDictionaryAddButton');
  assert.ok(addButton.listenerCount('click') > 0, 'the dictionary Add button was never bound');
  addButton.click();
  await new Promise((resolve) => setImmediate(resolve));

  const call = ctx.bridge.find('POST', '/dictionary');
  assert.ok(call);
  assert.deepEqual(call.body, { term: 'kubectl' });
  assert.equal(input.value, '');
  assert.match(ctx.el('sdUtilDictionaryList').textContent, /kubectl/);
});

test('#sdUtilDictionaryInput submits on Enter as well as on the button', async (t) => {
  const ctx = mount({ routes: { 'POST /dictionary': { terms: ['systemd'] } } });
  t.after(ctx.restore);
  ctx.feature.init();

  const input = ctx.el('sdUtilDictionaryInput');
  input.value = 'systemd';
  input.emit('keydown', { key: 'Enter' });
  await new Promise((resolve) => setImmediate(resolve));
  assert.ok(ctx.bridge.find('POST', '/dictionary'), 'Enter must submit the term');

  input.value = 'ignored';
  input.emit('keydown', { key: 'a' });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ctx.bridge.calls.length, 1, 'an ordinary keystroke must not submit');
});

test('an empty dictionary term never reaches the backend', async (t) => {
  const ctx = mount({ routes: { 'POST /dictionary': { terms: [] } } });
  t.after(ctx.restore);
  ctx.feature.init();

  ctx.el('sdUtilDictionaryInput').value = '   ';
  ctx.el('sdUtilDictionaryAddButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(ctx.bridge.signatures(), []);
});

test("#sdUtilDictionaryList renders a remove control per term that DELETEs that term", async (t) => {
  const ctx = mount({
    routes: {
      'GET /dictionary': { terms: ['kubectl', 'systemd'] },
      'DELETE /dictionary/kubectl': { terms: ['systemd'] },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshDictionary();
  const list = ctx.el('sdUtilDictionaryList');
  assert.equal(list.children.length, 2, 'one chip per term');

  const removeFirst = list.children[0].children[0];
  assert.equal(removeFirst.getAttribute('aria-label'), 'Remove kubectl', 'the remove control must name what it removes');
  removeFirst.click();
  await new Promise((resolve) => setImmediate(resolve));

  assert.ok(ctx.bridge.find('DELETE', '/dictionary/kubectl'));
  assert.equal(list.children.length, 1, 'the list is re-rendered from the response, not guessed at');
});

test('#sdUtilDictionaryMessage reports a failed add instead of losing the term silently', async (t) => {
  const ctx = mount({ routes: { 'POST /dictionary': { ok: false, status: 500, body: { detail: 'dictionary is locked' } } } });
  t.after(ctx.restore);
  ctx.feature.init();

  ctx.el('sdUtilDictionaryInput').value = 'kubectl';
  ctx.el('sdUtilDictionaryAddButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ctx.el('sdUtilDictionaryMessage').textContent, 'Could not add term: dictionary is locked');
});

// --- UI-07-166: suggestions from an edited draft -----------------------------

test('#sdUtilDictionarySuggestions appears only when POST /dictionary/suggest returns something', async (t) => {
  const ctx = mount({
    routes: {
      'POST /dictionary/suggest': { suggestions: ['Kubernetes', 'Grafana'] },
      'POST /dictionary': { terms: ['Kubernetes'] },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();

  ctx.feature.renderDictionarySuggestions([]);
  assert.equal(ctx.el('sdUtilDictionarySuggestGroup').hidden, true, 'an empty suggestion set must not leave an empty group on screen');

  const suggestions = await ctx.feature.suggestFromEdit('cube control', 'Kubernetes control');
  const call = ctx.bridge.find('POST', '/dictionary/suggest');
  assert.deepEqual(call.body, { raw_text: 'cube control', edited_text: 'Kubernetes control' });
  assert.deepEqual(suggestions, ['Kubernetes', 'Grafana']);
  assert.equal(ctx.el('sdUtilDictionarySuggestGroup').hidden, false);

  const chips = ctx.el('sdUtilDictionarySuggestions').children;
  assert.deepEqual(chips.map((c) => c.textContent), ['+ Kubernetes', '+ Grafana']);

  chips[0].click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(ctx.bridge.find('POST', '/dictionary').body, { term: 'Kubernetes' }, 'accepting a suggestion adds that exact term');
});

// --- UI-07-168 / UI-07-170: macros -------------------------------------------

test('#sdUtilMacroAddButton POSTs trigger and expansion together and clears both fields', async (t) => {
  const ctx = mount({ routes: { 'POST /macros': { macros: [{ trigger: 'addr', expansion: '12 Example St' }] } } });
  t.after(ctx.restore);
  ctx.feature.init();

  ctx.el('sdUtilMacroTrigger').value = ' addr ';
  ctx.el('sdUtilMacroExpansion').value = ' 12 Example St ';
  ctx.el('sdUtilMacroAddButton').click();
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(ctx.bridge.find('POST', '/macros').body, { trigger: 'addr', expansion: '12 Example St' });
  assert.equal(ctx.el('sdUtilMacroTrigger').value, '');
  assert.equal(ctx.el('sdUtilMacroExpansion').value, '');
  assert.match(ctx.el('sdUtilMacrosList').textContent, /addr/);
});

test('a macro missing either half is refused with a reason rather than half-saved', async (t) => {
  const ctx = mount({ routes: { 'POST /macros': { macros: [] } } });
  t.after(ctx.restore);
  ctx.feature.init();

  ctx.el('sdUtilMacroTrigger').value = 'addr';
  ctx.el('sdUtilMacroExpansion').value = '';
  ctx.el('sdUtilMacroAddButton').click();
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(ctx.bridge.signatures(), []);
  assert.deepEqual(ctx.toasts, [{ message: 'A macro needs both a trigger and an expansion.', tone: 'warning' }]);
});

test('#sdUtilMacrosList shows trigger and expansion, with a remove that DELETEs the trigger', async (t) => {
  const ctx = mount({
    routes: {
      'GET /macros': { macros: [{ trigger: 'addr', expansion: '12 Example St' }] },
      'DELETE /macros/addr': { macros: [] },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshMacros();
  const list = ctx.el('sdUtilMacrosList');
  assert.match(list.textContent, /addr/);
  assert.match(list.textContent, /12 Example St/);

  const removeButtons = list.querySelectorAll('.sd-util-chip-remove');
  assert.equal(removeButtons.length, 1, 'each macro row carries exactly one remove control');
  removeButtons[0].click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.ok(ctx.bridge.find('DELETE', '/macros/addr'));
});

// --- UI-07-177 / -178 / -179 / -186 / -182: warm-up and the output summary ---

test('each warm-up button asks for exactly its own subsystem and reports through #sdUtilWarmupMessage', async (t) => {
  const warmups = [];
  const ctx = mount({ routes: { 'POST /runtime/warmup': ({ body }) => { warmups.push(body); return { ok: true }; } } });
  t.after(ctx.restore);
  ctx.feature.init();

  ctx.el('sdUtilWarmupSttButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  // The wrapper always sends all three flags, so "exactly its own subsystem"
  // means the other two arrive explicitly false rather than absent.
  assert.deepEqual(warmups.at(-1), { stt: true, llm: false, hotkeys: false });
  assert.equal(ctx.el('sdUtilWarmupMessage').textContent, 'STT warmup requested.');

  ctx.el('sdUtilWarmupLlmButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(warmups.at(-1), { stt: false, llm: true, hotkeys: false });
  assert.equal(ctx.el('sdUtilWarmupMessage').textContent, 'LLM warmup requested.');

  ctx.el('sdUtilStartHotkeysButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(warmups.at(-1), { stt: false, llm: false, hotkeys: true });
  assert.equal(ctx.el('sdUtilWarmupMessage').textContent, 'Hotkeys warmup requested.');

  ctx.el('sdUtilTestModelLoadButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(warmups.at(-1), { stt: false, llm: true, hotkeys: false }, 'the model-load test is an LLM warm-up under a different label');
  assert.equal(ctx.el('sdUtilWarmupMessage').textContent, 'Model load test warmup requested.');
  assert.equal(warmups.length, 4);
});

test('#sdUtilWarmupMessage names the subsystem that failed, not a generic error', async (t) => {
  const ctx = mount({ routes: { 'POST /runtime/warmup': { ok: false, status: 503, body: { detail: 'model file missing' } } } });
  t.after(ctx.restore);
  ctx.feature.init();

  ctx.el('sdUtilWarmupLlmButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ctx.el('sdUtilWarmupMessage').textContent, 'LLM warmup failed: model file missing');
});

test('#sdUtilOutputSettingsSummary reads the live send mode, auto-submit and pending sends', async (t) => {
  const ctx = mount({ routes: { 'GET /runtime/output-settings': { send_mode: 'paste', auto_submit: true, pending_sends: 2 } } });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshAll();
  assert.equal(ctx.el('sdUtilOutputSettingsSummary').textContent, 'Send mode: paste · Auto-submit: on · Pending sends: 2');
});

// --- UI-07-187 / UI-09-011: the capability dump ------------------------------

test('#sdUtilCapabilitiesList dumps every documented capability key as a labelled pair', async (t) => {
  const ctx = mount({ routes: { 'GET /capabilities': FULL_CAPABILITIES } });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshCapabilitiesDump();
  const text = ctx.el('sdUtilCapabilitiesList').textContent;
  for (const key of ['platform', 'session_type', 'is_wayland', 'injection_method', 'supports_global_hotkeys', 'supports_audio_ducking']) {
    assert.match(text, new RegExp(key), `${key} is missing from the dump`);
  }
  assert.match(text, /xdotool/);
});

test('#sdUtilRuntimeStatusList dumps the runtime status the same way', async (t) => {
  const ctx = mount({ routes: { 'GET /runtime/status': { llm_loaded: true, stt_loaded: false, uptime_s: 42 } } });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshRuntimeStatusDump();
  const text = ctx.el('sdUtilRuntimeStatusList').textContent;
  assert.match(text, /llm_loaded/);
  assert.match(text, /uptime_s/);
});

// --- UI-07-091 / -092 / -093: the three conditional warnings -----------------

test('#sdUtilWaylandInjectionWarning shows ONLY on Wayland without injection', async (t) => {
  const wayland = mount({ routes: { 'GET /capabilities': { ...FULL_CAPABILITIES, is_wayland: true, supports_input_injection: false } } });
  t.after(wayland.restore);
  wayland.feature.init();
  await wayland.feature.refreshCapabilitiesDump();
  assert.equal(wayland.el('sdUtilWaylandInjectionWarning').hidden, false);
  wayland.restore();

  // Wayland WITH injection is not a fallback situation, and X11 without
  // injection is a different warning -- neither may raise this banner.
  const waylandOk = mount({ routes: { 'GET /capabilities': { ...FULL_CAPABILITIES, is_wayland: true, supports_input_injection: true } } });
  t.after(waylandOk.restore);
  waylandOk.feature.init();
  await waylandOk.feature.refreshCapabilitiesDump();
  assert.equal(waylandOk.el('sdUtilWaylandInjectionWarning').hidden, true);
});

test('#sdUtilInjectionUnavailableWarning shows whenever injection is unavailable, whatever the session', async (t) => {
  const ctx = mount({ routes: { 'GET /capabilities': { ...FULL_CAPABILITIES, supports_input_injection: false } } });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshCapabilitiesDump();
  assert.equal(ctx.el('sdUtilInjectionUnavailableWarning').hidden, false);
  ctx.restore();

  const ok = mount({ routes: { 'GET /capabilities': FULL_CAPABILITIES } });
  t.after(ok.restore);
  ok.feature.init();
  await ok.feature.refreshCapabilitiesDump();
  assert.equal(ok.el('sdUtilInjectionUnavailableWarning').hidden, true);
});

test('#sdUtilAudioDuckingWarning appears with the ducking control disabled when the platform cannot duck', async (t) => {
  const ctx = mount({ routes: { 'GET /capabilities': { ...FULL_CAPABILITIES, supports_audio_ducking: false } } });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshCapabilitiesDump();

  assert.equal(ctx.el('sdUtilAudioDuckingWarning').hidden, false);
  assert.equal(ctx.el('sdUtilAudioDucking').disabled, true, 'the banner and the disabled control must arrive together');
});

test('an unknown ducking capability leaves the control enabled rather than guessing it is broken', async (t) => {
  const ctx = mount({ routes: { 'GET /capabilities': { platform: 'linux' } } });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshCapabilitiesDump();

  assert.equal(ctx.el('sdUtilAudioDuckingWarning').hidden, true);
  assert.equal(ctx.el('sdUtilAudioDucking').disabled, false);
});

// --- UI-07-095: Test Paste/Copy ----------------------------------------------

test('#sdUtilTestPasteCopyButton writes real test text to the clipboard and confirms it', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();

  const button = ctx.el('sdUtilTestPasteCopyButton');
  assert.ok(button.listenerCount('click') > 0, 'Test Paste/Copy was never bound');
  button.click();
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(ctx.clipboardWrites.length, 1);
  assert.match(ctx.clipboardWrites[0], /BetterFingers test paste/);
  assert.equal(ctx.el('sdUtilSendInjectionMessage').textContent, 'Test text copied to clipboard.');
});

test('#sdUtilTestPasteCopyButton reports a clipboard that refused the write', async (t) => {
  const ctx = mount({ clipboard: async () => { throw new Error('no clipboard backend'); } });
  t.after(ctx.restore);
  ctx.feature.init();

  ctx.el('sdUtilTestPasteCopyButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ctx.el('sdUtilSendInjectionMessage').textContent, 'Copy failed: no clipboard backend');
});
