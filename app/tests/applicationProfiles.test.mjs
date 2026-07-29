// Application profiles feature (features/applicationProfiles.js) — Wave 7.
//
// Three failure modes these tests exist to catch, all of which look fine in a
// screenshot:
//
//   1. an UNAVAILABLE feature rendering as an empty profile list -- "you have
//      no profiles" and "this build cannot reach profiles" are completely
//      different statements and identical pixels;
//   2. a pin that pins the ACTIVE profile rather than the SELECTED one, which
//      silently writes the wrong durable decision;
//   3. anything about a recipient leaking into the rendered output.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  createApplicationProfilesFeature,
  computeAvailability,
  computePinAction,
  describeSource,
  describeDetected,
  describeProfile,
  describeMatch,
  profileLabel,
} from '../src/renderer/features/applicationProfiles.js';

const PROFILES = [
  {
    schema_version: 1,
    id: 'default',
    match: { process_names: [], window_patterns: [] },
    writing_preset: null,
    performance_preset: 'balanced',
    injection_policy: 'auto',
    tts: { announce_activation: false },
    bindings: {},
  },
  {
    schema_version: 1,
    id: 'discord',
    match: { process_names: ['discord', 'discord.exe'], window_patterns: ['^discord'] },
    writing_preset: null,
    performance_preset: 'low_latency',
    injection_policy: 'auto',
    tts: { announce_activation: false },
    bindings: {},
  },
  {
    schema_version: 1,
    id: 'rocket_league',
    match: { process_names: ['rocketleague.exe'], window_patterns: ['rocketleague'] },
    writing_preset: null,
    performance_preset: 'minimal',
    injection_policy: 'review_only',
    tts: { announce_activation: true },
    bindings: {},
  },
];

function ctx(extra = {}) {
  return {
    app_key: 'discord',
    detected: true,
    profile_id: 'discord',
    source: 'matched',
    override_active: false,
    pinned: false,
    deferred: false,
    pending_profile_id: null,
    announcement: '',
    writing_preset: null,
    performance_preset: 'low_latency',
    injection_policy: 'auto',
    tts: { announce_activation: false },
    bindings: {},
    gaming_policy: { active: false },
    ...extra,
  };
}

function fakeApi(overrides = {}) {
  const calls = [];
  return {
    calls,
    fetchAppContextStatus: async () => ({ ok: true, context: ctx() }),
    fetchAppProfiles: async () => ({ ok: true, profiles: PROFILES }),
    overrideAppProfile: async (id) => {
      calls.push({ kind: 'override', id });
      return { ok: true, context: ctx({ profile_id: id || 'discord', override_active: Boolean(id), source: id ? 'override' : 'matched' }) };
    },
    pinAppProfile: async (id) => {
      calls.push({ kind: 'pin', id });
      return { ok: true, context: ctx({ profile_id: id || 'discord', pinned: Boolean(id), source: id ? 'pinned' : 'matched' }) };
    },
    ...overrides,
  };
}

function mkEl() {
  const listeners = {};
  return {
    textContent: '',
    innerHTML: '',
    value: '',
    hidden: false,
    disabled: false,
    dataset: {},
    addEventListener: (name, fn) => { listeners[name] = fn; },
    fire: (name, event) => listeners[name]?.(event),
  };
}

function harness(api = fakeApi(), hooksOverride = {}) {
  const elements = {
    section: mkEl(),
    currentValue: mkEl(),
    currentSource: mkEl(),
    detectedValue: mkEl(),
    list: mkEl(),
    overrideSelect: mkEl(),
    overrideClear: mkEl(),
    pinButton: mkEl(),
    pinNote: mkEl(),
    announceNote: mkEl(),
    unavailable: mkEl(),
  };
  const changes = [];
  const toasts = [];
  const feature = createApplicationProfilesFeature({
    elements,
    api,
    hooks: {
      onContextChanged: (c) => changes.push(c),
      showToast: (msg, tone) => toasts.push({ msg, tone }),
      ...hooksOverride,
    },
    pollMs: 0, // no timers in unit tests
  });
  return { elements, feature, changes, toasts, api };
}

// --- pure display rules -------------------------------------------------------

test('every source has its own honest sentence', () => {
  assert.match(describeSource({ source: 'override' }), /override/i);
  assert.match(describeSource({ source: 'pinned' }), /pinned/i);
  assert.match(describeSource({ source: 'matched' }), /rules/i);
  assert.match(describeSource({ source: 'default' }), /No profile matches/i);
  assert.match(describeSource({ source: 'unknown' }), /could not be identified/i);
});

test('an unidentified application says so rather than showing a dash', () => {
  // Wayland has no portable focused-window query, so this is a routine state
  // on a large fraction of Linux desktops -- it deserves a sentence.
  assert.match(describeDetected({ app_key: '' }), /Not identified/i);
  assert.equal(describeDetected({ app_key: 'discord' }), 'discord');
});

test('a profile summary lists only slots a profile may set', () => {
  const summary = describeProfile(PROFILES[2]);
  assert.match(summary, /Performance: minimal/);
  assert.match(summary, /Delivery: review_only/);
  assert.match(summary, /Announces activation/);
  for (const word of ['recipient', 'contact', 'conversation', 'who']) {
    assert.ok(!summary.toLowerCase().includes(word), `summary must not mention ${word}`);
  }
});

test('a profile that matches nothing says so instead of showing an empty list', () => {
  assert.match(describeMatch(PROFILES[0]), /Matches nothing automatically/);
  assert.match(describeMatch(PROFILES[1]), /discord/);
});

test('profile labels use the real product names', () => {
  assert.equal(profileLabel('world_of_warcraft'), 'World of Warcraft');
  assert.equal(profileLabel('game_generic'), 'Game (generic)');
  assert.equal(profileLabel('my_editor'), 'My Editor');
});

// --- availability -------------------------------------------------------------

test('a build without the application-context api is UNAVAILABLE, not empty', () => {
  const result = computeAvailability({});
  assert.equal(result.available, false);
  assert.match(result.reason, /not reachable/i);
});

test('unavailable renders a sentence and disables every control', () => {
  const h = harness({});
  h.feature.init();
  assert.equal(h.elements.unavailable.hidden, false);
  assert.match(h.elements.unavailable.textContent, /not reachable/i);
  assert.equal(h.elements.list.innerHTML, '', 'no rows -- and no pretence of rows');
  assert.equal(h.elements.overrideSelect.disabled, true);
  assert.equal(h.elements.pinButton.disabled, true);
  assert.equal(h.feature.isAvailable(), false);
});

test('an unavailable feature performs no backend calls at all', async () => {
  let called = 0;
  const h = harness({ fetchAppContextStatus: async () => { called += 1; } });
  h.feature.init();
  await h.feature.refreshStatus();
  assert.equal(called, 0);
});

// --- rendering ----------------------------------------------------------------

test('init lists the profiles and paints the current resolution', async () => {
  const h = harness();
  h.feature.init();
  await h.feature.refreshProfiles();
  await h.feature.refreshStatus();

  assert.equal(h.elements.unavailable.hidden, true);
  assert.equal(h.elements.currentValue.textContent, 'Discord');
  assert.match(h.elements.currentSource.textContent, /rules/i);
  assert.equal(h.elements.detectedValue.textContent, 'discord');
  assert.equal(h.feature.getProfiles().length, 3);
  for (const id of ['default', 'discord', 'rocket_league']) {
    assert.ok(h.elements.list.innerHTML.includes(`data-app-profile="${id}"`), id);
  }
});

// --- Wave 12 collab task A: refreshProfiles() retry-once + keep-last-good --

test('refreshProfiles retries once before giving up on a slow/failed first response', async () => {
  let attempts = 0;
  const api = fakeApi({
    fetchAppProfiles: async () => {
      attempts += 1;
      if (attempts === 1) throw new Error('socket hang up');
      return { ok: true, profiles: PROFILES };
    },
  });
  const h = harness(api);
  await h.feature.refreshProfiles();
  assert.equal(attempts, 2, 'a slow first response must be retried once, not treated as a dead endpoint');
  assert.equal(h.feature.getProfiles().length, 3);
});

test('a refreshProfiles failure AFTER profiles were already loaded keeps them on screen', async () => {
  let call = 0;
  const api = fakeApi({
    fetchAppProfiles: async () => {
      call += 1;
      if (call <= 1) return { ok: true, profiles: PROFILES };
      throw new Error('backend down');
    },
  });
  const h = harness(api);
  await h.feature.refreshProfiles();
  assert.equal(h.feature.getProfiles().length, 3, 'sanity: the first refresh succeeded');

  await h.feature.refreshProfiles();
  assert.equal(
    h.feature.getProfiles().length, 3,
    'a later failed refresh must not blank a profile list that was already populated',
  );
  assert.ok(
    h.toasts.some((t) => /Could not refresh application profiles/.test(t.msg)),
    'a total failure must be reported honestly, not silently swallowed',
  );
  assert.ok(
    h.elements.list.innerHTML.includes('data-app-profile="discord"'),
    'the rendered rows must still reflect the last known list, not be wiped',
  );
});

test('a genuinely empty (but available) profile list renders an honest empty state, not a silent blank', async () => {
  const api = fakeApi({ fetchAppProfiles: async () => ({ ok: true, profiles: [] }) });
  const h = harness(api);
  h.feature.init();
  await h.feature.refreshProfiles();
  assert.match(h.elements.list.innerHTML, /No application profiles are configured/);
});

test('exactly one row is marked active, and it is the resolved one', async () => {
  const h = harness();
  h.feature.init();
  await h.feature.refreshProfiles();
  await h.feature.refreshStatus();
  const active = h.elements.list.innerHTML.match(/data-active="true"/g) || [];
  assert.equal(active.length, 1);
  assert.ok(h.elements.list.innerHTML.includes('data-app-profile="discord" data-active="true"'));
});

test('a context change is pushed to the status bar', async () => {
  const h = harness();
  h.feature.init();
  await h.feature.refreshStatus();
  assert.equal(h.changes.length, 1);
  assert.equal(h.changes[0].profile_id, 'discord');
});

test('an unchanged poll does not re-notify the status bar', async () => {
  const h = harness();
  h.feature.init();
  await h.feature.refreshStatus();
  await h.feature.refreshStatus();
  assert.equal(h.changes.length, 1);
});

test('a failed poll keeps the last known context rather than blanking it', async () => {
  let first = true;
  const api = fakeApi({
    fetchAppContextStatus: async () => {
      if (first) { first = false; return { ok: true, context: ctx() }; }
      throw new Error('backend down');
    },
  });
  const h = harness(api);
  h.feature.init();
  await h.feature.refreshStatus();
  await h.feature.refreshStatus();
  assert.equal(h.feature.getContext().profile_id, 'discord');
  assert.equal(h.elements.currentValue.textContent, 'Discord');
});

// --- override -----------------------------------------------------------------

test('choosing an override sends it and reflects the held state', async () => {
  const h = harness();
  h.feature.init();
  await h.feature.refreshProfiles();
  await h.feature.setOverride('rocket_league');

  assert.deepEqual(h.api.calls, [{ kind: 'override', id: 'rocket_league' }]);
  assert.equal(h.feature.getContext().override_active, true);
  assert.equal(h.elements.overrideClear.disabled, false);
});

test('clearing the override sends an empty id, not the current profile', async () => {
  const h = harness();
  h.feature.init();
  await h.feature.setOverride('rocket_league');
  h.api.calls.length = 0;
  h.elements.overrideClear.fire('click');
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(h.api.calls, [{ kind: 'override', id: '' }]);
});

// --- pinning ------------------------------------------------------------------

test('pin action is disabled and explains itself when nothing is detected', () => {
  const action = computePinAction(ctx({ detected: false, app_key: '' }));
  assert.equal(action.disabled, true);
  assert.match(action.note, /could not be identified/i);
});

test('pin pins the SELECTED profile, not the active one', async () => {
  // The bug this catches writes a durable decision about the wrong profile and
  // looks completely correct until the next time that app is focused.
  const h = harness();
  h.feature.init();
  await h.feature.refreshProfiles();
  await h.feature.refreshStatus();
  h.feature.selectProfile('rocket_league');
  h.api.calls.length = 0;

  await h.feature.togglePin();
  assert.deepEqual(h.api.calls, [{ kind: 'pin', id: 'rocket_league' }]);
});

test('a pinned context offers to REMOVE the pin, and unpin sends an empty id', async () => {
  const api = fakeApi({
    fetchAppContextStatus: async () => ({ ok: true, context: ctx({ pinned: true, source: 'pinned' }) }),
  });
  const h = harness(api);
  h.feature.init();
  await h.feature.refreshStatus();

  assert.equal(h.elements.pinButton.textContent, 'Remove pin');
  h.api.calls.length = 0;
  await h.feature.togglePin();
  assert.deepEqual(h.api.calls, [{ kind: 'pin', id: '' }]);
});

// --- the Wave 7 hard rule -----------------------------------------------------

test('nothing rendered names a recipient, a contact or a conversation', async () => {
  // Even if a snapshot ever carried such a field, this module must not surface
  // it: the rule is about what the UI can say, not only about what the backend
  // happens to send today.
  const api = fakeApi({
    fetchAppContextStatus: async () => ({
      ok: true,
      context: { ...ctx(), recipient: 'Priya', conversation_topic: 'the trip' },
    }),
  });
  const h = harness(api);
  h.feature.init();
  await h.feature.refreshProfiles();
  await h.feature.refreshStatus();

  const rendered = [
    h.elements.currentValue.textContent,
    h.elements.currentSource.textContent,
    h.elements.detectedValue.textContent,
    h.elements.pinNote.textContent,
    h.elements.list.innerHTML,
    h.elements.overrideSelect.innerHTML,
  ].join(' ');
  assert.ok(!rendered.includes('Priya'), 'a person must never appear here');
  assert.ok(!rendered.includes('the trip'), 'a conversation must never appear here');
});

test('the announcement note discloses that spoken activation is off', () => {
  const h = harness();
  h.feature.init();
  assert.match(h.elements.announceNote.textContent, /off/i);
  assert.match(h.elements.announceNote.textContent, /one short sentence/i);
  assert.match(h.elements.announceNote.textContent, /never queued/i);
});
