// The QA cold-boot fixture must cover every route the production page calls on
// startup — or the walkbook photographs a partly-404 backend.
//
// Wave 12. Eight routes were missing from the stub (/app-context/status,
// /app-context/profiles, /contacts, /contacts/active, /workflows,
// /workflows/history, /settings/profiles/Default, /drafts/latest). On every
// production-target scenario the composition root's cold-start population hit
// them, failed, and — correctly, after this wave's resilient-loading work —
// reported the failure to the user. The board still passed 97/97, because every
// assertion targets specific elements and none asks whether the screen is
// legible; but the screenshots showed a stack of honest error toasts over a
// backend that was 404ing. An accurate photograph of the stub and a misleading
// one of the product.
//
// The QA harness itself cannot be run from `node --test` (it launches Electron),
// so this is the cheap guard that keeps the fixture honest between board runs:
// it proves the fixture parses, and that it answers the startup routes.
//
// Run with: node --test app/tests/qaColdBootFixture.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { coldBoot } from './qa/scenarios/fixtures/cold-boot.mjs';

// Routes the production composition root reaches during populateInitialData()
// and its /health-gated re-population. A miss here is a 404 in the walkbook.
const STARTUP_ROUTES = [
  'GET /health',
  'GET /runtime/status',
  'GET /runtime/output-settings',
  'GET /settings/profiles',
  'GET /settings/profiles/Default',
  'GET /drafts',
  'GET /drafts/latest',
  'GET /app-context/status',
  'GET /app-context/profiles',
  'GET /contacts',
  'GET /contacts/active',
  'GET /workflows',
  'GET /workflows/history',
];

test('the cold-boot fixture answers every startup route', () => {
  const state = coldBoot();
  const missing = STARTUP_ROUTES.filter((route) => !(route in state));
  assert.deepEqual(
    missing,
    [],
    'a startup route with no stub entry becomes a 404 the renderer reports to the user, '
      + 'and the QA walkbook then photographs that error as if it were the product',
  );
});

test('the fixture is a fresh object per call, so one scenario cannot leak into the next', () => {
  const first = coldBoot();
  first['GET /drafts'] = { drafts: [{ id: 999 }] };
  assert.deepEqual(coldBoot()['GET /drafts'], { drafts: [] });
});

test('the two profile routes describe the SAME profile', () => {
  // `GET /settings/profiles` carries the active profile's settings inline and
  // `GET /settings/profiles/Default` is the per-profile read. If they drift,
  // Settings renders a profile whose fields do not match the one it believes is
  // selected -- which looks like a data bug and is really a fixture bug.
  const state = coldBoot();
  const list = state['GET /settings/profiles'];
  const single = state['GET /settings/profiles/Default'];

  assert.equal(single.profile, list.active_profile);
  assert.equal(single.active, true, 'the profile the list calls active must report itself active');
  assert.deepEqual(single.settings, list.settings);
});

test('the persona list is a healthy one, not the shape that means "request failed"', () => {
  // `GET /personas: {}` was the FAILURE shape, not a healthy empty state.
  // loadPersonaList() treats an empty or non-object payload as a failed request
  // deliberately: llm_engine.load_personas_v2() falls back to _DEFAULT_PERSONAS
  // whenever personas.yaml is missing, empty or corrupt, so a healthy backend
  // always answers with at least the built-ins — an empty map can only mean the
  // request failed. The stub was handing every scenario that response, and the
  // walkbook photographed the resulting honest warnings as the normal cold
  // start.
  const state = coldBoot();
  const personas = state['GET /personas'];

  assert.ok(personas && typeof personas === 'object' && !Array.isArray(personas));
  assert.ok(
    Object.keys(personas).length > 0,
    'an empty persona map is indistinguishable from a failed fetch by design — the stub must '
      + 'return the built-ins a real backend always falls back to',
  );

  // The built-in NAMES must agree with the persona map, or Studio renders a
  // built-in badge for a persona that is not in the list it was given.
  const builtins = state['GET /personas-builtins'].builtins;
  assert.ok(Array.isArray(builtins) && builtins.length > 0);
  for (const name of builtins) {
    assert.ok(name in personas, `built-in "${name}" is not present in GET /personas`);
  }

  // Well-formed enough to render: the renderer reads .prompt and .voice.
  for (const [name, persona] of Object.entries(personas)) {
    assert.equal(typeof persona.prompt, 'string', `${name} must carry a prompt`);
    assert.ok(persona.voice && typeof persona.voice === 'object', `${name} must carry a voice block`);
  }
});

test('empty startup payloads are well-formed envelopes, not bare nulls', () => {
  // The distinction this wave is built on: a panel must be able to tell "the
  // backend truthfully has none of these" from "the request failed". A stub
  // that answered with a malformed body would drive the error state and the
  // walkbook would show errors on a healthy backend all over again.
  const state = coldBoot();
  assert.deepEqual(state['GET /contacts'], { ok: true, contacts: [] });
  assert.deepEqual(state['GET /workflows'], { ok: true, workflows: [] });
  assert.deepEqual(state['GET /workflows/history'], { ok: true, history: [] });
  assert.equal(state['GET /contacts/active'].ok, true);
  assert.equal(state['GET /contacts/active'].contact_id, null, 'no selection is a state, not an absence');
  assert.equal(state['GET /app-context/profiles'].ok, true);
  assert.ok(Array.isArray(state['GET /app-context/profiles'].profiles));
  assert.equal(state['GET /drafts/latest'].draft, null);
});
