// The game setup wizard (Wave 10, deliverable 3).
//
// The assertion this file exists for is "the test can never fire a real send —
// enforce by test". Everything else here is the ordering that gets a user to
// that step without having skipped the anti-cheat warning.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  ANTI_CHEAT_WARNING,
  DEFAULT_DELIVERY,
  DELIVERY_MODES,
  REHEARSAL_FORBIDDEN_ACTIONS,
  STEPS,
  WIZARD_ELEMENT_IDS,
  bindingsAreDistinct,
  buildProfile,
  computeAvailability,
  computeWizardState,
  createGameSetupWizardFeature,
  deliveryNeedsWarning,
  describeRehearsal,
  recommendedDelivery,
} from '../src/renderer/features/gameSetupWizard.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = path.resolve(HERE, '..');

const DICTATION = { mode: 'hold', param: '', input: { style: 'single', events: ['button:4'] } };
const COMMAND = { mode: 'hold', param: '', input: { style: 'single', events: ['button:5'] } };

function ready(extra = {}) {
  return {
    deviceKey: 'controller:pad',
    dictationBinding: DICTATION,
    commandBinding: COMMAND,
    chatKey: 'Enter',
    delivery: DEFAULT_DELIVERY,
    ...extra,
  };
}

// --- the seven steps ---------------------------------------------------------

test('the wizard has exactly the seven steps the wave asks for, in order', () => {
  assert.deepEqual(STEPS, [
    'detect', 'dictation', 'command', 'chat_key', 'delivery',
    'warning', 'rehearsal', 'saved',
  ]);
});

test('the step advances only when the previous one is genuinely done', () => {
  assert.equal(computeWizardState({}).step, 'detect');
  assert.equal(computeWizardState({ deviceKey: 'controller:pad' }).step, 'dictation');
  assert.equal(computeWizardState({
    deviceKey: 'controller:pad', dictationBinding: DICTATION,
  }).step, 'command');
  assert.equal(computeWizardState({
    deviceKey: 'controller:pad', dictationBinding: DICTATION, commandBinding: COMMAND,
  }).step, 'chat_key');
  assert.equal(computeWizardState(ready()).step, 'rehearsal');
});

test('the command binding cannot be recorded before the dictation one', () => {
  // Deliverable 1's "separate bindings at minimum", as a UI rule: you cannot
  // finish having bound only one.
  const flow = computeWizardState({ deviceKey: 'controller:pad' });
  assert.equal(flow.canRecordDictation, true);
  assert.equal(flow.canRecordCommand, false);
});

test('two bindings on the same button are reported as not distinct', () => {
  assert.equal(bindingsAreDistinct(DICTATION, COMMAND), true);
  assert.equal(bindingsAreDistinct(DICTATION, { ...DICTATION }), false);
  // Order within a chord does not make two bindings different.
  const chordA = { input: { style: 'chord', events: ['button:4', 'button:5'] } };
  const chordB = { input: { style: 'chord', events: ['button:5', 'button:4'] } };
  assert.equal(bindingsAreDistinct(chordA, chordB), false);
});

// --- delivery and the anti-cheat warning -------------------------------------

test('only the three modes that make sense in a game are offered', () => {
  // `auto` is absent because "let BetterFingers decide" is not something a user
  // can weigh against a ban risk; `paste` is a synthesised keystroke with extra
  // steps.
  assert.deepEqual(Object.keys(DELIVERY_MODES).sort(),
    ['clipboard_only', 'review_only', 'type']);
});

test('only the typing mode synthesises input, and only it requires the warning', () => {
  assert.equal(DELIVERY_MODES.review_only.synthesises_input, false);
  assert.equal(DELIVERY_MODES.clipboard_only.synthesises_input, false);
  assert.equal(DELIVERY_MODES.type.synthesises_input, true);

  assert.equal(deliveryNeedsWarning('review_only'), false);
  assert.equal(deliveryNeedsWarning('clipboard_only'), false);
  assert.equal(deliveryNeedsWarning('type'), true);
});

test('the recommendation is a mode that cannot be detected as automation', () => {
  assert.equal(recommendedDelivery(), DEFAULT_DELIVERY);
  assert.equal(DELIVERY_MODES[recommendedDelivery()].synthesises_input, false);
});

test('the warning names the risk plainly and offers no workaround', () => {
  assert.match(ANTI_CHEAT_WARNING, /ban/i);
  assert.match(ANTI_CHEAT_WARNING, /input automation/i);
  // No "you can avoid detection by..." — that would be the product helping
  // somebody get banned more quietly.
  assert.ok(!/avoid detection|undetect|bypass|hide/i.test(ANTI_CHEAT_WARNING));
});

test('typing cannot be reached without acknowledging the warning', () => {
  const risky = computeWizardState(ready({ delivery: 'type' }));
  assert.equal(risky.step, 'warning');
  assert.equal(risky.canRehearse, false);

  const acknowledged = computeWizardState(ready({ delivery: 'type', acknowledged: true }));
  assert.equal(acknowledged.step, 'rehearsal');
});

test('changing the delivery mode retracts the acknowledgement', () => {
  // A tick made against "Review first" is not consent to type into a game.
  const feature = createGameSetupWizardFeature({ api: fakeApi() });
  feature.setDelivery('type');
  feature.acknowledge(true);
  assert.equal(feature.getState().acknowledged, true);
  feature.setDelivery('review_only');
  assert.equal(feature.getState().acknowledged, false);
});

// --- the rehearsal: the requirement --------------------------------------------

function fakeApi(overrides = {}) {
  const dispatched = [];
  const bound = [];
  const saved = [];
  return {
    dispatched, bound, saved,
    async fetchInputVocabulary() { return { ok: true, actions: [] }; },
    async fetchInputBindings() { return { ok: true, devices: ['controller:pad'] }; },
    async setInputBinding(actionId, binding, deviceKey) {
      bound.push([actionId, deviceKey]);
      return { ok: true };
    },
    async dispatchInputAction(payload) {
      dispatched.push(payload);
      // What the backend's rehearsal dispatcher actually answers: no handlers,
      // so every id is unavailable.
      return { ok: false, action_id: payload.action_id, status: 'unavailable' };
    },
    async saveAppProfile(profile) { saved.push(profile); return { ok: true, profile }; },
    ...overrides,
  };
}

async function rehearsedFeature(api = fakeApi()) {
  const feature = createGameSetupWizardFeature({ api });
  feature.init();
  await feature.detect();
  await feature.record('dictation.begin', async () => DICTATION.input);
  await feature.record('command.begin', async () => COMMAND.input);
  feature.setChatKey('Enter');
  feature.setDelivery('review_only');
  return feature;
}

test('the rehearsal never transmits an id that could have a real consequence', async () => {
  // latest.inject delivers text to whatever has focus — which during a rehearsal
  // is a game. emergency.stop would stop a recording the user never started.
  const api = fakeApi();
  const feature = await rehearsedFeature(api);
  await feature.rehearse([
    'dictation.begin', 'latest.inject', 'emergency.stop', 'command.begin',
  ]);
  const ids = api.dispatched.map((row) => row.action_id);
  assert.deepEqual(ids, ['dictation.begin', 'command.begin']);
  for (const forbidden of REHEARSAL_FORBIDDEN_ACTIONS) {
    assert.ok(!ids.includes(forbidden), forbidden);
  }
});

test('every rehearsal press is marked as a rehearsal on the wire', async () => {
  const api = fakeApi();
  const feature = await rehearsedFeature(api);
  await feature.rehearse();
  assert.ok(api.dispatched.length > 0);
  for (const row of api.dispatched) assert.equal(row.rehearsal, true);
});

test('the wizard exposes a closed surface with nothing on it that can send', () => {
  // Structural, not behavioural: the surface itself has no way to do it. An
  // exact list rather than a pattern, so ADDING a method is a failing test
  // somebody has to justify — which is the only way this stays true.
  const feature = createGameSetupWizardFeature({ api: fakeApi() });
  assert.deepEqual(Object.keys(feature).sort(), [
    'acknowledge', 'detect', 'getFlow', 'getRehearsalLog', 'getState',
    'init', 'isAvailable', 'record', 'rehearse', 'save',
    'setChatKey', 'setDelivery',
  ]);
});

test('the wizard module never names a send or inject contract', () => {
  const source = fs.readFileSync(
    path.join(APP, 'src', 'renderer', 'features', 'gameSetupWizard.js'), 'utf8',
  );
  // The api methods that actually deliver text. None of them may appear as a
  // call here — the wizard's api object is the shared adapter, so "it only has
  // what it needs" is not true by construction and has to be asserted.
  for (const forbidden of ['sendDraft', 'acceptDraft', 'writeClipboardText', 'injectText']) {
    assert.ok(!new RegExp(`api\\.${forbidden}\\s*\\(`).test(source), forbidden);
  }
});

test('a rehearsal that somehow succeeded is reported as a bug, not as success', async () => {
  // Should be unreachable — the backend rehearsal dispatcher has no handlers.
  // If it ever happens, the user is told not to use the build in a game rather
  // than being shown a cheerful tick.
  const line = describeRehearsal({ ok: true, action_id: 'dictation.begin', status: 'ok' });
  assert.match(line, /should not have/);
  assert.match(line, /Do not use this build in a game/);
});

test('an ordinary rehearsal press reads as "seen, nothing sent"', () => {
  const line = describeRehearsal({ ok: false, action_id: 'dictation.begin', status: 'unavailable' });
  assert.match(line, /saw your button/);
  assert.match(line, /Nothing was sent/);
});

// --- saving ------------------------------------------------------------------

test('nothing can be saved before the rehearsal has run', async () => {
  const api = fakeApi();
  const feature = await rehearsedFeature(api);
  assert.equal(feature.getFlow().canSave, false);
  assert.equal(await feature.save('rocket_league'), null);
  assert.deepEqual(api.saved, []);
});

test('a completed wizard saves the profile and the device-level bindings', async () => {
  const api = fakeApi();
  const feature = await rehearsedFeature(api);
  await feature.rehearse();
  const result = await feature.save('rocket_league');

  assert.equal(result.ok, true);
  // Device-level too: a user who set up their pad here should not lose it by
  // playing a different game.
  assert.deepEqual(api.bound, [
    ['dictation.begin', 'controller:pad'],
    ['command.begin', 'controller:pad'],
  ]);
  assert.equal(api.saved.length, 1);
  assert.equal(api.saved[0].id, 'rocket_league');
});

test('the profile uses the Wave 7 bindings slot with shared action ids', () => {
  const profile = buildProfile(ready({ profileId: 'rocket_league' }));
  assert.deepEqual(Object.keys(profile.bindings).sort(), ['command.begin', 'dictation.begin']);
  assert.equal(profile.injection_policy, 'review_only');
});

test('the profile never carries a window title or a typed game name as a match rule', () => {
  // Wave 7's rule: a window TITLE routinely contains the name of the person you
  // are talking to. The wizard asks for a profile name and stores it as an id,
  // not as something to match against.
  const profile = buildProfile(ready({ profileId: 'rocket_league' }));
  assert.deepEqual(profile.match.window_patterns, []);
});

test('an unknown delivery mode falls back to the safe one rather than to typing', () => {
  const profile = buildProfile(ready({ delivery: 'sudo_type_everything' }));
  assert.equal(profile.injection_policy, DEFAULT_DELIVERY);
});

// --- availability ------------------------------------------------------------

test('a build without the input api says so instead of offering dead buttons', () => {
  const { available, reason } = computeAvailability({});
  assert.equal(available, false);
  assert.match(reason, /not reachable in this build/);

  const elements = fakeElements();
  const feature = createGameSetupWizardFeature({ elements, api: {} });
  assert.equal(feature.init().available, false);
  assert.equal(elements.unavailable.hidden, false);
  for (const key of ['detectButton', 'recordDictationButton', 'rehearseButton', 'saveButton']) {
    assert.equal(elements[key].disabled, true, key);
  }
});

test('detecting no controller says what to do rather than failing silently', async () => {
  const elements = fakeElements();
  const feature = createGameSetupWizardFeature({
    elements,
    api: fakeApi({ async fetchInputBindings() { return { ok: true, devices: [] }; } }),
  });
  feature.init();
  await feature.detect();
  assert.match(elements.message.textContent, /Plug one in/);
});

// --- markup ------------------------------------------------------------------

function fakeElements() {
  const make = () => ({
    textContent: '', value: '', checked: false, hidden: true, disabled: false,
    dataset: {},
    addEventListener() {},
  });
  const elements = {};
  for (const key of Object.keys(WIZARD_ELEMENT_IDS)) elements[key] = make();
  return elements;
}

test('every element id the wizard collects exists in the production page', () => {
  const html = fs.readFileSync(path.join(APP, 'src', 'renderer', 'signal-desk.html'), 'utf8');
  for (const id of Object.values(WIZARD_ELEMENT_IDS)) {
    assert.ok(html.includes(`id="${id}"`), `signal-desk.html is missing #${id}`);
  }
});

test('the Wave 10 scenarios are registered on the production UI target', async () => {
  // The wizard ids exist only in signal-desk.html, so a scenario registered on
  // the default UI target would fail for the wrong reason — or worse, be
  // skipped and reported as covered.
  const { scenarios } = await import('./qa/scenarios/index.mjs');
  const wave10 = scenarios.filter((s) => s.area === 'wave10-input');
  assert.ok(wave10.length >= 6, `expected the Wave 10 scenarios, found ${wave10.length}`);
  for (const scenario of wave10) {
    assert.equal(scenario.ui, 'signal-desk-prod', scenario.name);
    assert.ok(scenario.description.trim().length > 80, scenario.name);
  }
  assert.ok(wave10.some((s) => s.name === 'the-test-step-cannot-send-anything'),
    'the requirement scenario must exist');
});

test('every Wave 10 scenario uses attribute selectors, never :has-text (D-0023)', async () => {
  const source = fs.readFileSync(
    path.join(APP, 'tests', 'qa', 'scenarios', 'wave10-input.mjs'), 'utf8',
  );
  assert.ok(!source.includes(':has-text'), 'address a state by identity, not by its words');
});

test('the wizard markup states the anti-cheat position rather than only the code doing so', () => {
  const html = fs.readFileSync(path.join(APP, 'src', 'renderer', 'signal-desk.html'), 'utf8');
  const section = html.split('id="sdUtilGameSetupGroup"')[1].split('</div>\n            </div>')[0];
  assert.match(section, /anti-cheat|input automation/i);
  assert.match(section, /rehearsal|nothing is sent/i);
});
