// Status bar display rules (features/statusBar.js).
//
// The rail used to be hard-coded markup that read "Live / Ready / Local /
// Natural / Discord / 1.2 sec" no matter what the app was doing. These tests
// pin the replacement contract: report real state, and render "—" rather than
// invent a value.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  UNKNOWN,
  computeStatusBar,
  formatLatency,
  mapLlm,
  mapMic,
  mapPersona,
  mapStt,
  mapTargetApp,
  mapContact,
  createStatusBarFeature,
} from '../src/renderer/features/statusBar.js';

// --- mic ---------------------------------------------------------------------

test('mic reports Idle when nothing is recording, never "Live"', () => {
  // The privacy-sensitive one: claiming a live mic while idle misrepresents
  // whether the app is listening.
  assert.equal(mapMic({ recording_active: false }).text, 'Idle');
});

test('mic reports Recording only while recording', () => {
  assert.equal(mapMic({ recording_active: true }).text, 'Recording');
});

test('mic is unknown without runtime data', () => {
  assert.equal(mapMic(null).text, UNKNOWN);
});

// --- stt / llm ---------------------------------------------------------------

test('stt prefers the runtime probe over /health', () => {
  assert.equal(mapStt({ transcriber: false }, { transcriber_loaded: true }).text, 'Loaded');
});

test('stt falls back to /health when runtime is absent', () => {
  assert.equal(mapStt({ transcriber: true }, null).text, 'Loaded');
});

test('stt distinguishes not-loaded from unknown', () => {
  assert.equal(mapStt({ transcriber: false }, null).text, 'Not loaded');
  assert.equal(mapStt(null, null).text, UNKNOWN);
});

test('llm reports readiness, not "Local"', () => {
  // "Local" described where the model runs, which never changes and so told
  // the user nothing.
  assert.equal(mapLlm(null, { llm_ready: true }).text, 'Ready');
  assert.equal(mapLlm(null, { llm_ready: false }).text, 'Not ready');
  assert.equal(mapLlm(null, null).text, UNKNOWN);
});

test('a false reading is not mistaken for a missing one', () => {
  // `false ?? x` must not fall through to the next source.
  assert.equal(mapLlm({ llm_engine: true }, { llm_ready: false }).text, 'Not ready');
});

// --- persona -----------------------------------------------------------------

test('persona comes from the profile, not a hard-coded name', () => {
  assert.equal(mapPersona({ current_preset: 'Polished' }).text, 'Polished');
});

test('persona is unknown when unset or blank', () => {
  assert.equal(mapPersona({ current_preset: '   ' }).text, UNKNOWN);
  assert.equal(mapPersona(null).text, UNKNOWN);
});

// --- latency -----------------------------------------------------------------

test('latency is unknown before any dictation has run', () => {
  // The common case on a fresh launch: total.last_ms is null. The mockup
  // showed "1.2 sec" here regardless.
  assert.equal(formatLatency({ total: { last_ms: null } }).text, UNKNOWN);
  assert.equal(formatLatency(null).text, UNKNOWN);
});

test('latency renders sub-second times in ms and longer ones in seconds', () => {
  assert.equal(formatLatency({ total: { last_ms: 420 } }).text, '420 ms');
  assert.equal(formatLatency({ total: { last_ms: 1234 } }).text, '1.2 sec');
});

test('latency rejects non-finite values instead of printing NaN', () => {
  assert.equal(formatLatency({ total: { last_ms: NaN } }).text, UNKNOWN);
  assert.equal(formatLatency({ total: { last_ms: Infinity } }).text, UNKNOWN);
  assert.equal(formatLatency({ total: { last_ms: '900' } }).text, UNKNOWN);
});

// --- target app --------------------------------------------------------------

test('target app is unknown by default and never invents a recipient', () => {
  // Replaces the mockup's "Destination: Discord". Nothing in the app knows a
  // channel or a person; detect_active_app_key() is app-level, never reaches
  // the renderer, and is empty on Wayland.
  assert.equal(mapTargetApp(undefined).text, UNKNOWN);
  assert.equal(mapTargetApp('').text, UNKNOWN);
  assert.equal(mapTargetApp('   ').text, UNKNOWN);
});

test('target app shows an application name when one is supplied', () => {
  assert.equal(mapTargetApp('discord').text, 'discord');
});

// --- whole snapshot ----------------------------------------------------------

test('an entirely absent backend degrades every always-present cell to unknown', () => {
  const values = computeStatusBar({});
  for (const [key, cell] of Object.entries(values)) {
    // `contact` is the one cell that can be genuinely ABSENT rather than
    // unknown -- see the mapContact tests below. Every other cell describes
    // something that always has a state, so `—` is the honest reading.
    if (key === 'contact') continue;
    assert.equal(cell.text, UNKNOWN, `${key} should be unknown, saw "${cell.text}"`);
  }
});

test('with no contact applied the cell is absent, not unknown', () => {
  // The distinction is the point. "No one in particular" is the default and a
  // real choice; a permanent rail cell reading `—` beside it would turn that
  // default into a gap the user feels invited to fill.
  assert.equal(computeStatusBar({}).contact, null);
});

test('a healthy snapshot reports real values', () => {
  const values = computeStatusBar({
    health: { transcriber: true, llm_engine: true },
    runtime: { transcriber_loaded: true, llm_ready: true, recording_active: false },
    profile: { current_preset: 'Polished' },
    metrics: { total: { last_ms: 1800 } },
  });
  assert.equal(values.stt.text, 'Loaded');
  assert.equal(values.llm.text, 'Ready');
  assert.equal(values.persona.text, 'Polished');
  assert.equal(values.mic.text, 'Idle');
  assert.equal(values.latency.text, '1.8 sec');
  assert.equal(values.targetApp.text, UNKNOWN);
});

test('one dead endpoint does not blank the cells that did resolve', () => {
  const values = computeStatusBar({
    health: null,
    runtime: { transcriber_loaded: true, llm_ready: true, recording_active: false },
    profile: null,
    metrics: null,
  });
  assert.equal(values.stt.text, 'Loaded');
  assert.equal(values.persona.text, UNKNOWN);
});

// --- Wave 5: the applied-contact cell ---------------------------------------

test('an applied contact is named in the rail', () => {
  assert.deepEqual(mapContact({ id: 'a1', name: 'Priya' }), { text: 'Priya', tone: 'muted' });
});

test('a contact with no id or no name yields no cell', () => {
  // A dangling id -- the contact was deleted while applied -- must show
  // nothing rather than a bare identifier.
  assert.equal(mapContact({ id: 'a1', name: '' }), null);
  assert.equal(mapContact({ id: '', name: 'Priya' }), null);
  assert.equal(mapContact(null), null);
  assert.equal(mapContact({ id: 'a1', name: '   ' }), null);
});

function railHarness() {
  const mk = () => ({ textContent: '', dataset: {}, hidden: false });
  const elements = {
    micValue: mk(), sttValue: mk(), sttDot: mk(), llmValue: mk(), llmDot: mk(),
    personaValue: mk(), targetAppValue: mk(), latencyValue: mk(),
    contactCell: mk(), contactValue: mk(),
  };
  return { elements, feature: createStatusBarFeature({ elements }) };
}

test('the cell is hidden until a contact is applied', () => {
  const h = railHarness();
  h.feature.render({});
  assert.equal(h.elements.contactCell.hidden, true);
  assert.equal(h.elements.contactValue.textContent, '');
});

test('setContact shows the cell immediately', () => {
  const h = railHarness();
  h.feature.render({});
  h.feature.setContact({ id: 'a1', name: 'Priya' });

  assert.equal(h.elements.contactCell.hidden, false);
  assert.equal(h.elements.contactValue.textContent, 'Priya');
});

test('clearing the contact hides the cell again', () => {
  const h = railHarness();
  h.feature.setContact({ id: 'a1', name: 'Priya' });
  h.feature.setContact(null);

  assert.equal(h.elements.contactCell.hidden, true);
  assert.equal(h.elements.contactValue.textContent, '');
});

test('a later health poll does not silently clear the applied contact', () => {
  // The applied contact is pushed in by the contacts feature, not fetched by
  // refresh(). Without the held state the next poll would blank the cell.
  const h = railHarness();
  h.feature.setContact({ id: 'a1', name: 'Priya' });

  h.feature.render({ runtime: { recording_active: true } });

  assert.equal(h.elements.contactCell.hidden, false);
  assert.equal(h.elements.contactValue.textContent, 'Priya');
  assert.equal(h.elements.micValue.textContent, 'Recording', 'the rest of the rail still updates');
});

test('an explicit contact in a snapshot still wins', () => {
  const h = railHarness();
  h.feature.setContact({ id: 'a1', name: 'Priya' });
  h.feature.render({ contact: { id: 'b2', name: 'Sam' } });
  assert.equal(h.elements.contactValue.textContent, 'Sam');
});

test('a rail with no contact elements still renders everything else', () => {
  const elements = { micValue: { textContent: '', dataset: {} } };
  const feature = createStatusBarFeature({ elements });
  feature.setContact({ id: 'a1', name: 'Priya' });
  feature.render({ runtime: { recording_active: false } });
  assert.equal(elements.micValue.textContent, 'Idle');
});
