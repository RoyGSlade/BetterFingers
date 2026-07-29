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
  mapBackend,
  mapStream,
  mapTargetApp,
  mapContact,
  mapAppProfile,
  appProfileLabel,
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
    // `contact` and `appProfile` are the two cells that can be genuinely
    // ABSENT rather than unknown -- see their own tests below. Every other cell
    // describes something that always has a state, so `—` is the honest
    // reading.
    if (key === 'contact' || key === 'appProfile') continue;
    assert.equal(cell.text, UNKNOWN, `${key} should be unknown, saw "${cell.text}"`);
  }
  assert.equal(values.contact, null);
  assert.equal(values.appProfile, null);
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

// `removeAttribute` is real rather than a stub because Wave 11B's paint()
// CLEARS a stale title, and a no-op fake would let that regress silently.
function railHarness({ api = null } = {}) {
  const mk = () => ({
    textContent: '',
    dataset: {},
    hidden: false,
    removeAttribute(name) { delete this[name]; },
  });
  const elements = {
    backendValue: mk(), backendDot: mk(), streamValue: mk(), streamDot: mk(),
    micValue: mk(), sttValue: mk(), sttDot: mk(), llmValue: mk(), llmDot: mk(),
    personaValue: mk(), targetAppValue: mk(), latencyValue: mk(),
    contactCell: mk(), contactValue: mk(),
    appProfileCell: mk(), appProfileValue: mk(),
  };
  return { elements, feature: createStatusBarFeature({ elements, api }) };
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

// --- application profile cell (Wave 7) ---------------------------------------

test('the Default profile yields NO cell, not an em dash', () => {
  // Default is also what an unidentified application resolves to. Both mean
  // "behaving normally"; a permanent cell reading "Default" would claim
  // activity where there is none.
  assert.equal(mapAppProfile({ profile_id: 'default', detected: false }), null);
  assert.equal(mapAppProfile({ profile_id: 'default', detected: true }), null);
});

test('an absent or empty context yields no cell', () => {
  assert.equal(mapAppProfile(null), null);
  assert.equal(mapAppProfile({}), null);
  assert.equal(mapAppProfile({ profile_id: '   ' }), null);
});

test('a real profile names itself', () => {
  assert.equal(mapAppProfile({ profile_id: 'rocket_league' }).text, 'Rocket League');
  assert.equal(mapAppProfile({ profile_id: 'discord' }).text, 'Discord');
});

test('a held override reads differently from an automatic match', () => {
  // An override the user forgot they set is exactly the thing the rail has to
  // remind them about, so it cannot look identical to a normal match.
  const matched = mapAppProfile({ profile_id: 'discord', source: 'matched' });
  const held = mapAppProfile({ profile_id: 'discord', source: 'override', override_active: true });
  assert.equal(matched.text, 'Discord');
  assert.equal(held.text, 'Discord (held)');
  assert.notEqual(held.tone, matched.tone);
});

test('an unknown profile id is word-cased rather than dropped', () => {
  // A profile the user created; the id is the only name it has.
  assert.equal(appProfileLabel('my_editor'), 'My Editor');
  assert.equal(mapAppProfile({ profile_id: 'my_editor' }).text, 'My Editor');
});

test('built-in labels are spelled the way the products are', () => {
  assert.equal(appProfileLabel('world_of_warcraft'), 'World of Warcraft');
});

test('the app-profile cell is hidden until a non-default profile applies', () => {
  const h = railHarness();
  h.feature.render({});
  assert.equal(h.elements.appProfileCell.hidden, true);
  assert.equal(h.elements.appProfileValue.textContent, '');
});

test('setAppContext shows the cell immediately', () => {
  const h = railHarness();
  h.feature.render({});
  h.feature.setAppContext({ profile_id: 'discord', source: 'matched', detected: true });
  assert.equal(h.elements.appProfileCell.hidden, false);
  assert.equal(h.elements.appProfileValue.textContent, 'Discord');
});

test('returning to Default hides the cell again', () => {
  const h = railHarness();
  h.feature.setAppContext({ profile_id: 'discord' });
  h.feature.setAppContext({ profile_id: 'default', source: 'unknown' });
  assert.equal(h.elements.appProfileCell.hidden, true);
  assert.equal(h.elements.appProfileValue.textContent, '');
});

test('a later health poll does not silently clear the application profile', () => {
  // Same held-state contract as the contact cell: the context is pushed in by
  // applicationProfiles.js, not fetched by refresh().
  const h = railHarness();
  h.feature.setAppContext({ profile_id: 'rocket_league' });
  h.feature.render({ runtime: { recording_active: true } });
  assert.equal(h.elements.appProfileCell.hidden, false);
  assert.equal(h.elements.appProfileValue.textContent, 'Rocket League');
  assert.equal(h.elements.micValue.textContent, 'Recording');
});

test('the rail never renders anything about a recipient', () => {
  // The cell is fed the backend snapshot verbatim. If a recipient-ish field
  // ever appeared in it, the mapper must still ignore it.
  const cell = mapAppProfile({
    profile_id: 'discord',
    recipient: 'Priya',
    conversation: 'about the trip',
  });
  assert.equal(cell.text, 'Discord');
});

test('a rail with no app-profile elements still renders everything else', () => {
  const elements = { micValue: { textContent: '', dataset: {} } };
  const feature = createStatusBarFeature({ elements });
  feature.setAppContext({ profile_id: 'discord' });
  feature.render({ runtime: { recording_active: false } });
  assert.equal(elements.micValue.textContent, 'Idle');
});

// --- backend cell (Wave 11B) -------------------------------------------------
//
// Replaces the legacy dashboard's three-card status grid. The whole point of
// this cell is the distinction the tests below pin: "we asked and it did not
// answer" must not read the same as "we have not asked yet".

test('an unreachable backend says so rather than showing a dash', () => {
  const cell = mapBackend(null, false);
  assert.equal(cell.text, 'Unreachable');
  assert.equal(cell.tone, 'warning');
  assert.match(cell.detail, /health/);
});

test('a backend that has not been asked yet is unknown, not unreachable', () => {
  // A fresh launch must not accuse the backend of being down before the first
  // poll returns.
  assert.equal(mapBackend(null, null).text, UNKNOWN);
  assert.equal(mapBackend(null, null).tone, 'muted');
});

test('an active backend reads Active', () => {
  const cell = mapBackend({ status: 'active', active_job_count: 0 }, true);
  assert.equal(cell.text, 'Active');
  assert.equal(cell.tone, 'success');
});

test('a busy backend is still Active, and says how busy in its detail', () => {
  // A backend running jobs is not a degraded backend -- the legacy card made
  // the same distinction, and /health carries active_job_count for it.
  const cell = mapBackend({ status: 'active', active_job_count: 3 }, true);
  assert.equal(cell.text, 'Active');
  assert.equal(cell.tone, 'success');
  assert.match(cell.detail, /3 jobs/);
  assert.match(mapBackend({ status: 'active', active_job_count: 1 }, true).detail, /1 job\b/);
});

test('any status other than active is reported verbatim as a warning', () => {
  // Reporting the backend's own word beats mapping it to a friendlier one we
  // then have to keep in sync.
  const cell = mapBackend({ status: 'degraded' }, true);
  assert.equal(cell.text, 'degraded');
  assert.equal(cell.tone, 'warning');
});

test('a reachable backend with no status field is unknown, not Active', () => {
  assert.equal(mapBackend({}, true).text, UNKNOWN);
});

// --- stream cell (Wave 11B) --------------------------------------------------

test('no stream state yet reads as unknown', () => {
  assert.equal(mapStream(null).text, UNKNOWN);
  assert.equal(mapStream('').text, UNKNOWN);
});

test('the four documented connection states map to their own labels', () => {
  assert.equal(mapStream('connecting').text, 'Connecting');
  assert.equal(mapStream('connected').text, 'Connected');
  assert.equal(mapStream('reconnecting').text, 'Reconnecting');
  assert.equal(mapStream('error').text, 'Error');
});

test('only a connected stream is a success tone', () => {
  // Reconnecting is recoverable, but while it lasts the meter and the capture
  // controls are showing stale truth -- that is worth a warning.
  assert.equal(mapStream('connected').tone, 'success');
  assert.equal(mapStream('reconnecting').tone, 'warning');
  assert.equal(mapStream('error').tone, 'warning');
  assert.equal(mapStream('connecting').tone, 'muted');
});

test('an unrecognised state is surfaced as a warning rather than swallowed', () => {
  const cell = mapStream('quiesced');
  assert.equal(cell.text, 'quiesced');
  assert.equal(cell.tone, 'warning');
});

test('a detail rides along for the cell title', () => {
  assert.equal(mapStream('error', 'socket closed').detail, 'socket closed');
  assert.equal(mapStream('connected').detail, undefined);
});

test('setStreamState paints immediately and survives the next poll', () => {
  // The regression this pins: the stream state is PUSHED in by the main-process
  // bridge and is not part of the snapshot refresh() fetches, so a render()
  // triggered by the 3s health poll must not wipe a live "Reconnecting".
  const h = railHarness();
  h.feature.setStreamState('reconnecting', 'retrying in 2s');
  assert.equal(h.elements.streamValue.textContent, 'Reconnecting');
  assert.equal(h.elements.streamValue.title, 'retrying in 2s');
  assert.equal(h.elements.streamDot.dataset.tone, 'warning');

  h.feature.render({ runtime: { recording_active: false } });
  assert.equal(h.elements.streamValue.textContent, 'Reconnecting', 'a health poll must not clear it');
});

test('an explicit stream in a snapshot still wins', () => {
  const h = railHarness();
  h.feature.setStreamState('connected');
  h.feature.render({ stream: { state: 'error', detail: 'bridge unavailable' } });
  assert.equal(h.elements.streamValue.textContent, 'Error');
});

test('a stale title is cleared when the cell no longer has a detail', () => {
  // Otherwise a recovered connection keeps hovering the reason it once failed.
  const h = railHarness();
  h.feature.setStreamState('error', 'socket closed');
  assert.equal(h.elements.streamValue.title, 'socket closed');
  h.feature.setStreamState('connected');
  assert.equal(h.elements.streamValue.title, undefined);
});

test('refresh reports a throwing /health as Unreachable, not as unknown', async () => {
  // The wiring half of mapBackend()'s contract: refresh() must catch /health
  // SEPARATELY from the other probes, because its failure is itself the value
  // the Backend cell reports. Folding it into the shared catch-to-null would
  // erase the difference this whole cell exists to draw.
  const h = railHarness({ api: { fetchHealth: async () => { throw new Error('ECONNREFUSED'); } } });
  await h.feature.refresh();
  assert.equal(h.elements.backendValue.textContent, 'Unreachable');
});

test('refresh reports a healthy backend as Active', async () => {
  const h = railHarness({ api: { fetchHealth: async () => ({ status: 'active', active_job_count: 0 }) } });
  await h.feature.refresh();
  assert.equal(h.elements.backendValue.textContent, 'Active');
  assert.equal(h.elements.backendDot.dataset.tone, 'success');
});

test('one dead probe does not blank the cells whose data arrived', async () => {
  const h = railHarness({
    api: {
      fetchHealth: async () => ({ status: 'active' }),
      fetchRuntimeStatus: async () => { throw new Error('down'); },
      fetchMetrics: async () => ({ total: { last_ms: 900 } }),
    },
  });
  await h.feature.refresh();
  assert.equal(h.elements.backendValue.textContent, 'Active');
  assert.equal(h.elements.micValue.textContent, UNKNOWN, 'the probe that died degrades its own cell');
  assert.equal(h.elements.latencyValue.textContent, '900 ms');
});
