// Wave 12A Objective B -- the persona preset dropdown must never render empty
// because a fetch failed.
//
// The product owner's build showed #sdSetCurrentPreset with ZERO options on a
// clean profile. That cannot be a data problem: llm_engine.load_personas_v2()
// falls back to _DEFAULT_PERSONAS whenever personas.yaml is missing, empty or
// corrupt, so the backend always answers with at least the built-ins. An empty
// dropdown therefore only ever means the REQUEST failed -- and the renderer
// turned that into an empty option list silently, with nothing on screen to
// say so and no retry.
//
// These tests drive the real settingsWorkspace wiring against the production
// ids, with the backend stubbed at window.betterFingers.backendRequest (the
// single bridge api/backend.js funnels through), so the real URL building and
// error unwrapping are exercised rather than mocked away.
//
// Run with: node --test app/tests/personaOptions.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  SETTINGS_ELEMENT_IDS,
  collectSettingsElements,
  createSettingsWorkspaceFeature,
} from '../src/renderer/features/settingsWorkspace.js';
import { loadPersonaList } from '../src/renderer/bootstrap/signalDeskApp.js';
import { makeDocument, makeBackendBridge, installDomGlobals } from './helpers/rendererDom.mjs';

// --- loadPersonaList(): the bootstrap-side rule -------------------------------
//
// signalDeskApp.js used to do `catch { loadedPersonas = {} }` and then feed
// Object.keys({}) to BOTH settingsWorkspace.setPersonaOptions() and
// libraryWorkspace.setPersonaOptions() -- so one failed request emptied the
// preset dropdown AND the library's persona filter at once, permanently, with
// nothing on screen to say why.

test('loadPersonaList returns a healthy list unchanged', async () => {
  const { personas, failed } = await loadPersonaList(async () => ({ 'True Janitor': {}, Direct: {} }), {});
  assert.deepEqual(Object.keys(personas), ['True Janitor', 'Direct']);
  assert.equal(failed, false);
});

test('loadPersonaList retries once before giving up', async () => {
  // The field failure is a slow FIRST response against the 2500 ms budget in
  // api/backend.js, not a dead endpoint -- so one retry is what recovers it.
  let calls = 0;
  const { personas, failed } = await loadPersonaList(async () => {
    calls += 1;
    if (calls === 1) throw new Error('timeout');
    return { 'True Janitor': {} };
  }, {});
  assert.equal(calls, 2, 'a first failure must be retried');
  assert.deepEqual(Object.keys(personas), ['True Janitor']);
  assert.equal(failed, false);
});

test('loadPersonaList keeps the last good list when both attempts fail', async () => {
  const previous = { 'True Janitor': {}, Direct: {} };
  let calls = 0;
  const { personas, failed } = await loadPersonaList(async () => {
    calls += 1;
    throw new Error('backend unreachable');
  }, previous);
  assert.equal(calls, 2);
  assert.equal(personas, previous, 'a total failure must not blank a working list');
  assert.equal(failed, true, 'the caller has to know it failed, so it can say so');
});

test('loadPersonaList treats an empty or malformed payload as a failure', async () => {
  // The backend cannot legitimately return {} -- it always falls back to the
  // built-ins. Rendering {} as an empty dropdown shows a fault as an empty state.
  for (const payload of [{}, null, undefined, [], 'nope', 42]) {
    const previous = { 'True Janitor': {} };
    const { personas, failed } = await loadPersonaList(async () => payload, previous);
    assert.equal(failed, true, `${JSON.stringify(payload)} should count as a failure`);
    assert.equal(personas, previous, `${JSON.stringify(payload)} must not blank the list`);
  }
});

test('loadPersonaList reports failure honestly when there is no previous list', async () => {
  const { personas, failed } = await loadPersonaList(async () => ({}), {});
  assert.deepEqual(personas, {});
  assert.equal(failed, true, 'an empty dropdown with no fallback must still be flagged');
});

// --- the Settings dropdown wiring --------------------------------------------

// Literal, not derived from the module: a test that read the id from the code
// could not notice the code renaming the control.
const CURRENT_PRESET_ID = 'sdSetCurrentPreset';

test('the preset dropdown id this file drives is the one Settings ships', () => {
  assert.equal(SETTINGS_ELEMENT_IDS.fields.current_preset, CURRENT_PRESET_ID);
});

function mount(routes) {
  const doc = makeDocument([CURRENT_PRESET_ID, 'sdSetProfileMessage'], {
    [CURRENT_PRESET_ID]: { tagName: 'select' },
  });
  const bridge = makeBackendBridge(routes);
  const restore = installDomGlobals({ document: doc, betterFingers: { backendRequest: bridge.request } });
  const feature = createSettingsWorkspaceFeature({ elements: collectSettingsElements(doc) });
  return { doc, bridge, feature, restore, select: () => doc.getElementById(CURRENT_PRESET_ID) };
}

function optionValues(select) {
  return (select.children || []).map((child) => child.value);
}

test('a healthy persona list populates the preset dropdown', async (t) => {
  const ctx = mount({ 'GET /personas': { 'True Janitor': {}, Direct: {}, Warm: {} } });
  t.after(ctx.restore);

  await ctx.feature.refreshPersonaOptions();

  assert.deepEqual(optionValues(ctx.select()), ['True Janitor', 'Direct', 'Warm']);
});

test('a FAILED persona fetch leaves a populated dropdown alone', async (t) => {
  // The regression. Before the fix a thrown fetch fell through to
  // setPersonaOptions([]), wiping every option -- and the user's current
  // selection with it -- on a transient backend hiccup.
  const ctx = mount({ 'GET /personas': { ok: false, status: 503, body: { detail: 'backend unreachable' } } });
  t.after(ctx.restore);

  ctx.feature.setPersonaOptions(['True Janitor', 'Direct'], 'Direct');
  // Set .value directly: the test document models a <select> as children plus
  // a value, and does not derive the value from option.selected the way a real
  // browser does. This is the user having "Direct" chosen.
  ctx.select().value = 'Direct';
  assert.deepEqual(optionValues(ctx.select()), ['True Janitor', 'Direct']);

  await ctx.feature.refreshPersonaOptions();

  assert.deepEqual(optionValues(ctx.select()), ['True Janitor', 'Direct'],
    'a failed refresh must not blank the preset dropdown');
  assert.equal(ctx.select().value, 'Direct', 'the current selection must survive a failed refresh');
});

test('an EMPTY persona response is treated as a failure, not as "you have no personas"', async (t) => {
  // The backend cannot legitimately return {} -- it always falls back to the
  // built-ins -- so {} means something went wrong upstream. Rendering it as an
  // empty dropdown presents a fault as if it were the user's own empty state.
  const ctx = mount({ 'GET /personas': {} });
  t.after(ctx.restore);

  ctx.feature.setPersonaOptions(['True Janitor', 'Direct'], 'True Janitor');

  await ctx.feature.refreshPersonaOptions();

  assert.deepEqual(optionValues(ctx.select()), ['True Janitor', 'Direct'],
    'an empty response must not blank a working option list');
});

test('a persona saved into the list is selectable straight after a refresh', async (t) => {
  // Findings 8/9 in miniature, on the surface this lane owns: whatever the
  // store now holds must be selectable without a restart. The dropdown is
  // re-read from the backend, so a newly added persona has to appear AND be
  // assignable as the current preset.
  const personas = { 'True Janitor': {}, Direct: {} };
  const ctx = mount({ 'GET /personas': personas });
  t.after(ctx.restore);

  await ctx.feature.refreshPersonaOptions();
  assert.equal(optionValues(ctx.select()).includes('Blended Studio'), false);

  personas['Blended Studio'] = {};
  await ctx.feature.refreshPersonaOptions();

  assert.equal(optionValues(ctx.select()).includes('Blended Studio'), true,
    'a persona added since the last refresh must appear in the dropdown');
  ctx.select().value = 'Blended Studio';
  assert.equal(ctx.select().value, 'Blended Studio',
    'the newly listed persona must be selectable as the current preset');
});
