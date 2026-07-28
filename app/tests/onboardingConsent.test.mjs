// Consent flow against durable onboarding state (features/onboardingConsent.js).
//
// The consequential rules here are fail-closed gating and fail-closed accept:
// a bug that reads an error or a malformed state as "consented" is a consent
// failure, and a bug that reports accept() success on a failed durable write
// lets a user proceed un-consented.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  needsConsent,
  resolveOnboardingGate,
  createConsentController,
} from '../src/renderer/features/onboardingConsent.js';
import {
  ONBOARDING_FLAG,
  createOnboardingFlow,
} from '../src/renderer/features/onboardingFlow.js';

function memoryStorage(initial = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
  };
}

const throwingStorage = {
  getItem() { throw new Error('storage disabled'); },
};

// A tiny in-memory fake of the durable bridge contract. Never touches real
// localStorage, the filesystem, or a user-data root.
function fakeBridge(overrides = {}) {
  let state = null;
  let migrateCalls = 0;
  const bridge = {
    async getState() { return state; },
    async accept({ consentVersion }) {
      state = {
        schema_version: 1,
        consent_version: consentVersion,
        accepted: true,
        accepted_at: 'now',
        completed_steps: state?.completed_steps ?? [],
      };
      return { ok: true, state };
    },
    async completeStep(id) {
      state = { ...(state ?? {}), completed_steps: [...(state?.completed_steps ?? []), id] };
      return { ok: true, state };
    },
    async migrateLegacy({ legacyComplete }) {
      migrateCalls += 1;
      if (state?.accepted) return { migrated: false, reason: 'already_present' };
      if (!legacyComplete) return { migrated: false, reason: 'no_legacy_flag' };
      state = {
        schema_version: 1,
        consent_version: 1,
        accepted: true,
        accepted_at: 'migrated',
        completed_steps: [],
      };
      return { migrated: true, state };
    },
    async quit() {},
    ...overrides,
    _getMigrateCalls: () => migrateCalls,
    _setState: (s) => { state = s; },
  };
  return bridge;
}

// --- needsConsent -------------------------------------------------------------

test('needsConsent is fail-closed on missing or malformed state', () => {
  assert.equal(needsConsent(null), true);
  assert.equal(needsConsent(undefined), true);
  assert.equal(needsConsent({}), true);
  assert.equal(needsConsent({ accepted: false, consent_version: 1 }), true);
  assert.equal(needsConsent({ accepted: true, consent_version: 'nope' }), true);
});

test('needsConsent is satisfied at or above the required version', () => {
  assert.equal(needsConsent({ accepted: true, consent_version: 1 }, 1), false);
  assert.equal(needsConsent({ accepted: true, consent_version: 2 }, 1), false);
  assert.equal(needsConsent({ accepted: true, consent_version: 1 }, 2), true);
});

// --- resolveOnboardingGate -----------------------------------------------------

test('fresh install with empty durable state shows the gate', async () => {
  const bridge = fakeBridge();
  const storage = memoryStorage();
  const result = await resolveOnboardingGate({ bridge, storage, consentVersion: 1 });
  assert.equal(result.show, true);
  assert.equal(result.reason, 'no_state');
  assert.equal(result.migrated, false);
});

test('accepted at the required version does not show the gate', async () => {
  const bridge = fakeBridge();
  bridge._setState({ schema_version: 1, consent_version: 1, accepted: true, accepted_at: 'now', completed_steps: [] });
  const storage = memoryStorage();
  const result = await resolveOnboardingGate({ bridge, storage, consentVersion: 1 });
  assert.equal(result.show, false);
  assert.equal(result.reason, 'accepted');
});

test('a consent version bump re-prompts an already-accepted user', async () => {
  const bridge = fakeBridge();
  bridge._setState({ schema_version: 1, consent_version: 1, accepted: true, accepted_at: 'now', completed_steps: [] });
  const storage = memoryStorage();
  const result = await resolveOnboardingGate({ bridge, storage, consentVersion: 2 });
  assert.equal(result.show, true);
  assert.equal(result.reason, 'consent_version_bumped');
  assert.equal(result.migrated, false, 'a version bump is not a legacy migration');
});

test('a legacy-complete flag migrates once into the durable store', async () => {
  const bridge = fakeBridge();
  const storage = memoryStorage({ bf_onboarding_complete: 'true' });

  const first = await resolveOnboardingGate({ bridge, storage, consentVersion: 1 });
  assert.equal(bridge._getMigrateCalls(), 1);
  assert.equal(first.migrated, true);
  assert.equal(first.show, false);
  assert.equal(first.reason, 'migrated');

  const second = await resolveOnboardingGate({ bridge, storage, consentVersion: 1 });
  assert.equal(bridge._getMigrateCalls(), 1, 'a second resolve must not migrate again');
  assert.equal(second.migrated, false);
  assert.equal(second.show, false);
  assert.equal(second.reason, 'accepted');
});

test('a throwing storage and a throwing bridge fail closed without crashing', async () => {
  const bridge = fakeBridge({
    async getState() { throw new Error('ipc down'); },
  });
  const result = await resolveOnboardingGate({ bridge, storage: throwingStorage, consentVersion: 1 });
  assert.equal(result.show, true);
});

test('an undefined bridge shows the gate with reason bridge_unavailable', async () => {
  const result = await resolveOnboardingGate({ bridge: undefined, storage: memoryStorage(), consentVersion: 1 });
  assert.equal(result.show, true);
  assert.equal(result.reason, 'bridge_unavailable');
});

// --- createConsentController ---------------------------------------------------

test('accept() only reports success on a confirmed durable write', async () => {
  const bridge = fakeBridge();
  const controller = createConsentController({ bridge, consentVersion: 1 });
  const result = await controller.accept();
  assert.equal(result.ok, true);
  const state = await bridge.getState();
  assert.equal(state.accepted, true);
  assert.equal(state.consent_version, 1);
});

test('accept() with a failing durable write reports failure and calls onError', async () => {
  const errors = [];
  const bridge = fakeBridge({ async accept() { return { ok: false }; } });
  const controller = createConsentController({ bridge, consentVersion: 1, onError: (e) => errors.push(e) });
  const result = await controller.accept();
  assert.equal(result.ok, false);
  assert.equal(errors.length, 1);
});

test('accept() that throws is reported as failure, not swallowed', async () => {
  const errors = [];
  const bridge = fakeBridge({ async accept() { throw new Error('write failed'); } });
  const controller = createConsentController({ bridge, consentVersion: 1, onError: (e) => errors.push(e) });
  const result = await controller.accept();
  assert.equal(result.ok, false);
  assert.equal(errors.length, 1);
});

test('decline() calls bridge.quit() exactly once', async () => {
  let quitCalls = 0;
  const bridge = fakeBridge({ async quit() { quitCalls += 1; } });
  const controller = createConsentController({ bridge, consentVersion: 1 });
  const result = await controller.decline();
  assert.equal(quitCalls, 1);
  assert.equal(result.ok, true);
});

test('a throwing quit is reported, not swallowed as success', async () => {
  const errors = [];
  let quitCalls = 0;
  const bridge = fakeBridge({
    async quit() { quitCalls += 1; throw new Error('quit failed'); },
  });
  const controller = createConsentController({ bridge, consentVersion: 1, onError: (e) => errors.push(e) });
  const result = await controller.decline();
  assert.equal(quitCalls, 1);
  assert.equal(result.ok, false);
  assert.equal(errors.length, 1);
});

test('completeStep failure is non-fatal', async () => {
  const errors = [];
  const bridge = fakeBridge({ async completeStep() { throw new Error('ipc hiccup'); } });
  const controller = createConsentController({ bridge, consentVersion: 1, onError: (e) => errors.push(e) });
  const result = await controller.completeStep('welcome');
  assert.equal(result.ok, false);
  assert.equal(errors.length, 1, 'reported, but does not throw out of completeStep');
});

test('completeStep success round-trips through the fake bridge', async () => {
  const bridge = fakeBridge();
  const controller = createConsentController({ bridge, consentVersion: 1 });
  const result = await controller.completeStep('welcome');
  assert.equal(result.ok, true);
});

// --- createOnboardingFlow's durable-consent seam (features/onboardingFlow.js) --
//
// These exercise the seam wiring itself -- finish()'s accept/close/onComplete
// contract, init()'s shouldShow predicate, and decline's routing -- as
// opposed to the controller/gate logic above, which is exercised against a
// fake bridge directly. A small DOM fake drives createOnboardingFlow the same
// way app/tests/onboardingFlow.test.mjs does.

function makeEl(extra = {}) {
  const listeners = {};
  return {
    hidden: false,
    disabled: false,
    checked: false,
    textContent: '',
    dataset: {},
    isConnected: true,
    addEventListener: (evt, fn) => { (listeners[evt] ||= []).push(fn); },
    removeEventListener: () => {},
    setAttribute() {},
    focus() {},
    fire: (evt) => (listeners[evt] || []).forEach((fn) => fn()),
    ...extra,
  };
}

function flowHarness({ storage = memoryStorage(), hooks = {}, consent, isConsented, shouldShow } = {}) {
  const primary = makeEl();
  const back = makeEl();
  const title = makeEl();
  const progress = makeEl();
  const consentEl = makeEl();
  const decline = makeEl();
  const recommendation = makeEl();
  const modelsPresent = makeEl();
  const modelsMissing = makeEl();
  const stepEls = [makeEl(), makeEl(), makeEl(), makeEl()];
  const dots = [makeEl(), makeEl(), makeEl(), makeEl()];

  const root = {
    hidden: true,
    querySelector: (sel) => ({
      '[data-flow-primary]': primary,
      '[data-flow-back]': back,
      '[data-flow-title]': title,
      '[data-flow-progress]': progress,
    }[sel] ?? null),
    querySelectorAll: (sel) => ({
      '[data-flow-step]': stepEls,
      '[data-flow-dot]': dots,
    }[sel] ?? []),
  };

  const doc = {
    activeElement: null,
    addEventListener() {},
    removeEventListener() {},
  };

  const elements = {
    root, consent: consentEl, decline, recommendation, modelsPresent, modelsMissing,
  };
  const onboarding = createOnboardingFlow({ elements, storage, hooks, doc, consent, isConsented, shouldShow });
  return { onboarding, root, primary, decline, consentEl, storage };
}

// --- Defect 1: finish() must not fail open on a bad durable write ------------

test('finish() with a failing durable accept leaves the gate open and does not report completion', async () => {
  const completes = [];
  const errors = [];
  const consent = { accept: async () => ({ ok: false }) };
  const h = flowHarness({
    hooks: { onComplete: () => completes.push('done'), onConsentError: (e) => errors.push(e) },
    consent,
  });
  h.onboarding.init();
  await h.onboarding.finish();
  assert.equal(h.root.hidden, false, 'a failed durable write must not close a legal gate');
  assert.deepEqual(completes, [], 'onComplete must not fire on a failed write');
  assert.equal(errors.length, 1, 'onConsentError must report the failure');
});

test('finish() when accept() throws leaves the gate open and reports onConsentError, not onComplete', async () => {
  const completes = [];
  const errors = [];
  const consent = { accept: async () => { throw new Error('ipc down'); } };
  const h = flowHarness({
    hooks: { onComplete: () => completes.push('done'), onConsentError: (e) => errors.push(e) },
    consent,
  });
  h.onboarding.init();
  await h.onboarding.finish();
  assert.equal(h.root.hidden, false);
  assert.deepEqual(completes, []);
  assert.equal(errors.length, 1);
});

test('finish() with a confirmed durable accept closes and completes exactly once', async () => {
  const completes = [];
  const consent = { accept: async () => ({ ok: true }) };
  const h = flowHarness({
    hooks: { onComplete: () => completes.push('done') },
    consent,
  });
  h.onboarding.init();
  await h.onboarding.finish();
  assert.equal(h.root.hidden, true);
  assert.deepEqual(completes, ['done']);
});

// --- Defect 2: init() must gate on shouldShow, not just the legacy flag ------

test('shouldShow:() => false suppresses init() regardless of the legacy flag', () => {
  const h = flowHarness({ shouldShow: () => false });
  assert.equal(h.onboarding.init(), false);
  assert.equal(h.root.hidden, true);
});

test('shouldShow:() => true opens init() even when the legacy flag says complete (consent_version bump)', () => {
  const h = flowHarness({
    storage: memoryStorage({ [ONBOARDING_FLAG]: 'true' }),
    shouldShow: () => true,
  });
  assert.equal(h.onboarding.init(), true);
  assert.equal(h.root.hidden, false);
});

// --- Legacy path is untouched when the new seams are omitted -----------------

test('omitting shouldShow, consent and isConsented reproduces legacy behavior', async () => {
  const completes = [];
  const storage = memoryStorage();
  const h = flowHarness({ storage, hooks: { onComplete: () => completes.push('done') } });

  assert.equal(h.onboarding.init(), true, 'fresh profile opens onboarding');

  const maybePromise = h.onboarding.finish();
  // Legacy finish() must close synchronously, with no await required by the
  // caller -- this is what app/tests/onboardingFlow.test.mjs's
  // 'the flag is written only at the end' test relies on.
  assert.equal(storage.getItem(ONBOARDING_FLAG), 'true');
  assert.equal(h.root.hidden, true, 'legacy finish() closes synchronously');
  assert.deepEqual(completes, ['done']);
  await maybePromise;
});

// --- Defect 3: decline must route through the consent controller ------------

test('decline routes through consent.decline() when supplied, and does not call hooks.quitApp', async () => {
  const declineCalls = [];
  const quits = [];
  const consent = {
    accept: async () => ({ ok: true }),
    decline: async () => { declineCalls.push('declined'); return { ok: true }; },
  };
  const h = flowHarness({ hooks: { quitApp: () => quits.push('quit') }, consent });
  h.onboarding.init();
  h.decline.fire('click');
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(declineCalls, ['declined']);
  assert.deepEqual(quits, [], 'quitApp must not be called when consent.decline() handles it');
});

test('a failed consent.decline() is reported via onConsentError, not swallowed', async () => {
  const errors = [];
  const consent = { accept: async () => ({ ok: true }), decline: async () => ({ ok: false }) };
  const h = flowHarness({ hooks: { onConsentError: (e) => errors.push(e) }, consent });
  h.onboarding.init();
  h.decline.fire('click');
  await new Promise((r) => setImmediate(r));
  assert.equal(errors.length, 1);
});

test('decline falls back to hooks.quitApp when consent has no decline()', () => {
  const quits = [];
  const consent = { accept: async () => ({ ok: true }) };
  const h = flowHarness({ hooks: { quitApp: () => quits.push('quit') }, consent });
  h.onboarding.init();
  h.decline.fire('click');
  assert.deepEqual(quits, ['quit']);
});

test('decline falls back to hooks.quitApp in the legacy path (no consent supplied)', () => {
  const quits = [];
  const h = flowHarness({ hooks: { quitApp: () => quits.push('quit') } });
  h.onboarding.init();
  h.decline.fire('click');
  assert.deepEqual(quits, ['quit']);
});
