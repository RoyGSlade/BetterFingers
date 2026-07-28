// Durable onboarding/consent store. Every test gets its own throwaway temp
// root (fs.mkdtempSync under os.tmpdir()) — never the real user-data root,
// and never localStorage — since a bug that lets consent state leak between
// tests, or between test runs and a real profile, is exactly the kind of bug
// this module exists to prevent in production.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import store from '../src/main/onboardingStore.js';

const {
  SCHEMA_VERSION,
  CURRENT_CONSENT_VERSION,
  readState,
  needsConsent,
  recordAcceptance,
  recordStepComplete,
  migrateLegacyCompletion,
  clearForFactoryReset,
} = store;

function tempRoot(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bf-onboarding-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

function onboardingFile(root) {
  return path.join(root, 'onboarding.json');
}

// --- fresh install -----------------------------------------------------------

test('a fresh install needs consent', (t) => {
  const root = tempRoot(t);
  const state = readState({ root });
  assert.equal(state.accepted, false);
  assert.equal(state.accepted_at, null);
  assert.deepEqual(state.completed_steps, []);
  assert.equal(needsConsent(state), true);
});

test('a missing file is treated as needing consent, not as an error', (t) => {
  const root = tempRoot(t);
  assert.equal(fs.existsSync(onboardingFile(root)), false);
  assert.doesNotThrow(() => readState({ root }));
});

// --- acceptance ---------------------------------------------------------------

test('acceptance persists across a fresh read', (t) => {
  const root = tempRoot(t);
  const now = () => new Date('2026-01-15T12:00:00.000Z');
  const result = recordAcceptance({ root, now });
  assert.equal(result.ok, true);
  assert.equal(result.state.accepted, true);
  assert.equal(result.state.accepted_at, '2026-01-15T12:00:00.000Z');
  assert.equal(result.state.consent_version, CURRENT_CONSENT_VERSION);

  const reread = readState({ root });
  assert.deepEqual(reread, result.state);
  assert.equal(needsConsent(reread), false);

  const onDisk = JSON.parse(fs.readFileSync(onboardingFile(root), 'utf8'));
  assert.deepEqual(onDisk, {
    schema_version: SCHEMA_VERSION,
    consent_version: CURRENT_CONSENT_VERSION,
    accepted: true,
    accepted_at: '2026-01-15T12:00:00.000Z',
    completed_steps: [],
  });
});

test('a consent_version bump re-prompts everyone accepted at an older version', (t) => {
  const root = tempRoot(t);
  const written = recordAcceptance({ root, consentVersion: 1, now: () => new Date('2026-01-01T00:00:00.000Z') });
  assert.equal(written.ok, true);
  const state = readState({ root });
  assert.equal(needsConsent(state, 1), false);
  assert.equal(needsConsent(state, 2), true, 'bumping the current consent version must re-prompt');
});

// --- step completion ------------------------------------------------------

test('step completion records new steps in order', (t) => {
  const root = tempRoot(t);
  recordStepComplete('welcome', { root });
  const result = recordStepComplete('consent', { root });
  assert.equal(result.ok, true);
  assert.deepEqual(result.state.completed_steps, ['welcome', 'consent']);
});

test('step completion is idempotent', (t) => {
  const root = tempRoot(t);
  recordStepComplete('welcome', { root });
  recordStepComplete('welcome', { root });
  const result = recordStepComplete('welcome', { root });
  assert.equal(result.ok, true, 'an idempotent no-op is not a failure');
  assert.deepEqual(result.state.completed_steps, ['welcome']);
});

// --- write failures ----------------------------------------------------------
// A durable write can fail (disk full, permission denied, ...). These prove
// that failure is reported as ok:false, never silently reported as if the
// user had durably consented — the whole point of the durable store.

test('recordAcceptance on an unwritable root returns ok:false, not a false success', (t) => {
  if (process.getuid && process.getuid() === 0) {
    t.skip('running as root ignores directory permission bits');
    return;
  }
  const root = tempRoot(t);
  fs.chmodSync(root, 0o500);
  try {
    const result = recordAcceptance({ root });
    assert.equal(result.ok, false);
    assert.equal(fs.existsSync(onboardingFile(root)), false, 'no file must appear on a failed write');
  } finally {
    fs.chmodSync(root, 0o700);
  }
});

test('recordStepComplete on an unwritable root returns ok:false, not a false success', (t) => {
  if (process.getuid && process.getuid() === 0) {
    t.skip('running as root ignores directory permission bits');
    return;
  }
  const root = tempRoot(t);
  fs.chmodSync(root, 0o500);
  try {
    const result = recordStepComplete('welcome', { root });
    assert.equal(result.ok, false);
  } finally {
    fs.chmodSync(root, 0o700);
  }
});

// --- corrupt / future-versioned files --------------------------------------

test('corrupt JSON reads as needing consent, never as accepted', (t) => {
  const root = tempRoot(t);
  fs.mkdirSync(root, { recursive: true });
  fs.writeFileSync(onboardingFile(root), '{ this is not json');
  const state = readState({ root });
  assert.equal(state.accepted, false);
  assert.equal(needsConsent(state), true);
});

test('a future schema_version reads as needing consent, not silently downgraded', (t) => {
  const root = tempRoot(t);
  fs.mkdirSync(root, { recursive: true });
  fs.writeFileSync(
    onboardingFile(root),
    JSON.stringify({
      schema_version: SCHEMA_VERSION + 1,
      consent_version: 99,
      accepted: true,
      accepted_at: '2099-01-01T00:00:00.000Z',
      completed_steps: [],
    }),
  );
  const state = readState({ root });
  assert.equal(state.accepted, false, 'a newer schema must not be interpreted as acceptance');
  assert.equal(needsConsent(state), true);
});

test('an accepted record with a missing consent_version never satisfies a version bump', (t) => {
  // The fail-open this guards against: if a missing consent_version fell
  // back to CURRENT_CONSENT_VERSION, bumping CURRENT_CONSENT_VERSION later
  // would make this record satisfy needsConsent(state, newVersion) by
  // accident, silently skipping the re-prompt it exists to force.
  const root = tempRoot(t);
  fs.mkdirSync(root, { recursive: true });
  fs.writeFileSync(
    onboardingFile(root),
    JSON.stringify({ accepted: true, accepted_at: '2026-01-01T00:00:00.000Z' }),
  );
  const state = readState({ root });
  assert.equal(state.consent_version, 0);
  assert.equal(needsConsent(state, 1), true);
});

test('unknown/extra keys are dropped on normalize', (t) => {
  const root = tempRoot(t);
  fs.mkdirSync(root, { recursive: true });
  fs.writeFileSync(
    onboardingFile(root),
    JSON.stringify({
      schema_version: SCHEMA_VERSION,
      consent_version: 1,
      accepted: true,
      accepted_at: '2026-01-01T00:00:00.000Z',
      completed_steps: ['welcome'],
      totally_unknown_field: 'should be dropped',
    }),
  );
  const state = readState({ root });
  assert.deepEqual(Object.keys(state).sort(), [
    'accepted',
    'accepted_at',
    'completed_steps',
    'consent_version',
    'schema_version',
  ]);
});

// --- legacy migration -------------------------------------------------------

test('legacy migration writes acceptance when the legacy flag was true and no durable file exists', (t) => {
  const root = tempRoot(t);
  const now = () => new Date('2026-02-01T00:00:00.000Z');
  const result = migrateLegacyCompletion({ legacyComplete: true, root, now });
  assert.equal(result.migrated, true);
  assert.equal(result.ok, true);
  assert.equal(result.state.accepted, true);
  assert.equal(result.state.accepted_at, '2026-02-01T00:00:00.000Z');
  assert.equal(needsConsent(readState({ root })), false);
});

test('legacy migration is a no-op when the legacy value is absent/falsy', (t) => {
  const root = tempRoot(t);
  const result = migrateLegacyCompletion({ legacyComplete: false, root });
  assert.deepEqual(result, { migrated: false, reason: 'no_legacy_value', ok: true });
  assert.equal(fs.existsSync(onboardingFile(root)), false);
});

test('legacy migration is a no-op when durable state already exists', (t) => {
  const root = tempRoot(t);
  recordAcceptance({ root, now: () => new Date('2026-01-01T00:00:00.000Z') });
  const before = readState({ root });

  const result = migrateLegacyCompletion({ legacyComplete: true, root, now: () => new Date('2099-01-01T00:00:00.000Z') });
  assert.deepEqual(result, { migrated: false, reason: 'already_present', ok: true });
  assert.deepEqual(readState({ root }), before, 'migration must not clobber an existing durable record');
});

test('legacy migration only runs once even across a corrupt existing file', (t) => {
  // Consequence of this fail-closed choice: a user whose file got corrupted
  // keeps their legacy localStorage completion unmigrated and simply sees
  // consent again, rather than risk migrating over unknown/damaged state.
  const root = tempRoot(t);
  fs.mkdirSync(root, { recursive: true });
  fs.writeFileSync(onboardingFile(root), 'not json at all');

  const result = migrateLegacyCompletion({ legacyComplete: true, root });
  assert.deepEqual(result, { migrated: false, reason: 'already_present', ok: true });
  // The corrupt file is left untouched, not overwritten by the migration.
  assert.equal(fs.readFileSync(onboardingFile(root), 'utf8'), 'not json at all');
});

test('a failed migration write reports migrated:false, not a false success', (t) => {
  if (process.getuid && process.getuid() === 0) {
    t.skip('running as root ignores directory permission bits');
    return;
  }
  const root = tempRoot(t);
  fs.chmodSync(root, 0o500);
  try {
    const result = migrateLegacyCompletion({ legacyComplete: true, root });
    assert.equal(result.migrated, false, 'nothing was durably migrated');
    assert.equal(result.ok, false);
  } finally {
    fs.chmodSync(root, 0o700);
  }
});

// --- factory reset ----------------------------------------------------------

test('clearForFactoryReset removes the file', (t) => {
  const root = tempRoot(t);
  recordAcceptance({ root });
  assert.equal(fs.existsSync(onboardingFile(root)), true);

  const result = clearForFactoryReset({ root });
  assert.equal(result.cleared, true);
  assert.equal(fs.existsSync(onboardingFile(root)), false);
});

test('clearForFactoryReset on a missing file is still success', (t) => {
  const root = tempRoot(t);
  assert.equal(fs.existsSync(onboardingFile(root)), false);
  const result = clearForFactoryReset({ root });
  assert.deepEqual(result, { cleared: true });
});

test('clearForFactoryReset does not affect an unrelated file in the same root', (t) => {
  const root = tempRoot(t);
  recordAcceptance({ root });
  const sentinel = path.join(root, 'draft_history.json');
  fs.writeFileSync(sentinel, '{}');

  clearForFactoryReset({ root });
  assert.equal(fs.existsSync(sentinel), true);
});

// --- atomic writes ------------------------------------------------------------

test('atomic writes leave no stray temp files in the root', (t) => {
  const root = tempRoot(t);
  recordAcceptance({ root });
  recordStepComplete('welcome', { root });
  recordStepComplete('consent', { root });

  const entries = fs.readdirSync(root);
  assert.deepEqual(entries, ['onboarding.json']);
});

test('needsConsent treats a missing/undefined state as needing consent', () => {
  assert.equal(needsConsent(undefined), true);
  assert.equal(needsConsent({}), true);
});
