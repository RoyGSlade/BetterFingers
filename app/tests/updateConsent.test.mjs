import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import store from '../src/main/onboardingStore.js';
import updaterModule from '../src/main/updateController.js';
const schedulerModule = updaterModule;

function harness(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bf-update-consent-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const calls = [];
  const timers = new Map();
  let serial = 0;
  let scheduler;
  const updater = { on() {}, checkForUpdates: async () => calls.push('check'), downloadUpdate: async () => calls.push('download') };
  const controller = updaterModule.createUpdateController({
    platform: 'win32', isPackaged: true, currentVersion: '1.1.0', updater,
    consentGuard: () => !store.needsConsent(store.readState({ root })),
    automaticUpdatesGuard: () => store.readState({ root }).automatic_updates,
    saveAutomaticUpdates: (enabled) => store.recordAutomaticUpdates(enabled, { root }),
    onAutomaticUpdatesChanged: () => scheduler.refresh(),
  });
  scheduler = schedulerModule.createUpdateCheckScheduler({
    controller,
    setTimer(fn, delay) { assert.equal(delay, 15000); timers.set(++serial, fn); return serial; },
    clearTimer: (id) => timers.delete(id),
  });
  return { root, calls, timers, controller, scheduler, accept() { store.recordAcceptance({ root }); controller.refreshConsent(); scheduler.refresh(); },
    fire() { const [id, fn] = timers.entries().next().value; timers.delete(id); fn(); },
    legacy(overrides = {}) { fs.writeFileSync(path.join(root, 'onboarding.json'), JSON.stringify({ schema_version: 1, consent_version: 1, accepted: true, ...overrides })); },
  };
}

test('pre-consent schedules no timer and all check/download entry points fail closed', async (t) => {
  const h = harness(t);
  h.scheduler.ready();
  assert.equal(h.timers.size, 0);
  await h.controller.check(); await h.controller.download();
  h.controller.setAutomaticUpdates(true);
  assert.equal(h.controller.getState().errorCode, 'CONSENT_REQUIRED');
  assert.deepEqual(h.calls, []);
  assert.equal(fs.existsSync(path.join(h.root, 'onboarding.json')), false);
});

test('fresh acceptance stays off across restart; manual check works without opting in', async (t) => {
  const h = harness(t); h.scheduler.ready(); h.accept();
  assert.equal(h.timers.size, 0);
  assert.equal(store.readState({ root: h.root }).automatic_updates, false);
  assert.equal(h.controller.getState().automaticUpdates, false);
  await h.controller.check(); assert.deepEqual(h.calls, ['check']);
  assert.equal(h.timers.size, 0);
});

test('opting in persists and schedules once; opt-out cancels; opt-in schedules again', (t) => {
  const h = harness(t); h.scheduler.ready(); h.accept();
  h.controller.setAutomaticUpdates(true);
  assert.equal(store.readState({ root: h.root }).automatic_updates, true);
  assert.equal(h.timers.size, 1);
  h.scheduler.refresh(); assert.equal(h.timers.size, 1);
  h.controller.setAutomaticUpdates(false);
  assert.equal(h.timers.size, 0);
  assert.equal(store.readState({ root: h.root }).automatic_updates, false);
  h.controller.setAutomaticUpdates(true);
  h.fire(); h.scheduler.refresh();
  assert.deepEqual(h.calls, ['check']);
  assert.equal(h.timers.size, 0);
});

test('reset or changed preference during delay cannot dispatch a check', (t) => {
  for (const reset of [true, false]) {
    const h = harness(t); h.scheduler.ready(); h.accept(); h.controller.setAutomaticUpdates(true);
    if (reset) store.clearForFactoryReset({ root: h.root });
    else store.recordAutomaticUpdates(false, { root: h.root });
    h.fire(); assert.deepEqual(h.calls, []);
  }
});

test('legacy accepted v1 records retain checks, explicit preferences win, corrupt/future fail closed', (t) => {
  for (const [overrides, expected] of [
    [{}, true], [{ automatic_updates: false }, false], [{ automatic_updates: true }, true],
    [{ automatic_updates: 'true' }, false], [{ accepted: false }, false],
    [{ schema_version: 0 }, false], [{ schema_version: -1 }, false], [{ schema_version: 1.5 }, false], [{ schema_version: undefined }, false],
    [{ consent_version: 2 }, false], [{ consent_version: 1.5 }, false], [{ consent_version: null }, false], [{ schema_version: 2 }, false],
  ]) {
    const h = harness(t); h.legacy(overrides); h.scheduler.ready();
    assert.equal(h.timers.size, expected ? 1 : 0, JSON.stringify(overrides));
    assert.equal(h.controller.getState().automaticUpdates, expected);
    if (expected) { h.fire(); assert.deepEqual(h.calls, ['check']); }
  }
  const h = harness(t);
  fs.writeFileSync(path.join(h.root, 'onboarding.json'), '{broken');
  h.scheduler.ready(); assert.equal(h.timers.size, 0);
});

test('legacy renderer completion preserves previous checks after durable migration only', (t) => {
  const h = harness(t); h.scheduler.ready();
  assert.equal(h.timers.size, 0);
  store.migrateLegacyCompletion({ root: h.root, legacyComplete: true });
  h.scheduler.refresh(); assert.equal(h.timers.size, 1);
  h.controller.setAutomaticUpdates(false);
  store.migrateLegacyCompletion({ root: h.root, legacyComplete: true });
  assert.equal(store.readState({ root: h.root }).automatic_updates, false);
});

test('missing consent callback and throwing guard never call updater', async () => {
  const calls = [];
  for (const consentGuard of [undefined, () => { throw Error('unreadable'); }]) {
    const c = updaterModule.createUpdateController({ platform: 'win32', isPackaged: true, updater: { on() {}, checkForUpdates: async () => calls.push('check') }, consentGuard });
    await c.check(); assert.equal(c.getState().consentGranted, false);
  }
  assert.deepEqual(calls, []);
});

test('invalid preferences or failed durable writes preserve effective behavior and cannot schedule', (t) => {
  const h = harness(t); h.scheduler.ready(); h.accept();
  h.controller.setAutomaticUpdates('true');
  assert.equal(h.controller.getState().errorCode, 'INVALID_PREFERENCE');
  fs.rmSync(path.join(h.root, 'onboarding.json'));
  fs.mkdirSync(path.join(h.root, 'onboarding.json'));
  h.controller.setAutomaticUpdates(true);
  assert.equal(h.controller.getState().errorCode, 'CONSENT_REQUIRED');
  assert.equal(h.timers.size, 0);
  let saved = false;
  const c = updaterModule.createUpdateController({ consentGuard: () => true, automaticUpdatesGuard: () => saved,
    saveAutomaticUpdates: () => ({ ok: false }), onAutomaticUpdatesChanged: () => { throw Error('must not schedule'); } });
  c.setAutomaticUpdates(true);
  assert.equal(c.getState().automaticUpdates, false);
  assert.equal(c.getState().errorCode, 'PREFERENCE_SAVE_FAILED');
});


test('actual store rename failure leaves fresh preference off and schedules no check', (t) => {
  const h = harness(t); h.scheduler.ready(); h.accept();
  const rename = fs.renameSync;
  const log = console.error;
  try {
    fs.renameSync = (source, destination) => {
      if (destination === path.join(h.root, 'onboarding.json')) throw Error('simulated durable write failure');
      return rename(source, destination);
    };
    console.error = () => {};
    h.controller.setAutomaticUpdates(true);
  } finally { fs.renameSync = rename; console.error = log; }
  assert.equal(h.controller.getState().errorCode, 'PREFERENCE_SAVE_FAILED');
  assert.equal(store.readState({ root: h.root }).automatic_updates, false);
  assert.equal(h.timers.size, 0);
  assert.deepEqual(h.calls, []);
});

function eventedController({ consent, automatic = true, save = () => ({ ok: true }) }) {
  const handlers = {};
  const calls = [];
  const updater = {
    on(name, fn) { handlers[name] = fn; },
    checkForUpdates: async () => calls.push('check'),
    downloadUpdate: async () => calls.push('download'),
  };
  const controller = updaterModule.createUpdateController({
    platform: 'win32', isPackaged: true, currentVersion: '1.1.0', updater,
    consentGuard: () => consent.value,
    automaticUpdatesGuard: () => automatic,
    saveAutomaticUpdates: save,
  });
  return { controller, handlers, calls };
}

test('download fails closed when consent is withdrawn after an update became available', async () => {
  const consent = { value: true };
  const h = eventedController({ consent });
  await h.controller.check();
  h.handlers['update-available']({ version: '1.2.0' });
  assert.equal(h.controller.getState().status, 'available');
  consent.value = false;
  await h.controller.download();
  assert.deepEqual(h.calls, ['check']);
  assert.equal(h.controller.getState().errorCode, 'CONSENT_REQUIRED');
});

test('automatic checks report off without consent even when the stored preference is on', () => {
  const h = eventedController({ consent: { value: false }, automatic: true });
  assert.equal(h.controller.getState().automaticUpdates, false);
  assert.equal(h.controller.getState().consentGranted, false);
});

test('the store refuses to record a preference before consent and writes nothing', (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bf-update-consent-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const result = store.recordAutomaticUpdates(true, { root });
  assert.equal(result.ok, false);
  assert.equal(result.error, 'CONSENT_REQUIRED');
  assert.equal(fs.existsSync(path.join(root, 'onboarding.json')), false);
});

test('changing the preference never clears or replaces an update lifecycle error', async () => {
  for (const save of [() => ({ ok: true }), () => ({ ok: false })]) {
    const h = eventedController({ consent: { value: true }, save });
    await h.controller.check();
    h.handlers.error(new Error('ENOSPC: disk full'));
    assert.equal(h.controller.getState().errorCode, 'INSUFFICIENT_DISK');
    h.controller.setAutomaticUpdates(true);
    assert.equal(h.controller.getState().errorCode, 'INSUFFICIENT_DISK');
  }
  // With no lifecycle error the preference result is still reported.
  const failing = eventedController({ consent: { value: true }, save: () => ({ ok: false }) });
  failing.controller.setAutomaticUpdates(true);
  assert.equal(failing.controller.getState().errorCode, 'PREFERENCE_SAVE_FAILED');
  const ok = eventedController({ consent: { value: true } });
  ok.controller.setAutomaticUpdates(true);
  assert.equal(ok.controller.getState().errorCode, null);
});
