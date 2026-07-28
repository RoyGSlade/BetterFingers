// Durable-consent QA harness seam (D-durable-consent-qa), the parts that are
// honestly testable without Electron: seededAcceptedRecord()'s shape and its
// round trip through the REAL onboardingStore, and qaDataRoot()'s override
// resolution. What this file does NOT and cannot cover: that
// enterFirstRunState/enterCompletedProfileState actually drive a live page
// correctly, or that the onboarding-prod scenarios pass against the real
// Electron app -- that only happens inside app/tests/qa/run.mjs, which needs
// a display and is not exercised by `node --test`.
//
// harness.mjs imports 'playwright' at module scope. Importing it directly
// here (rather than re-exporting the pure helpers from a second module) was
// verified NOT to be too heavy: the import below succeeds under plain
// `node --test`, so there is no separate pure-helpers module to claim.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import store from '../src/main/onboardingStore.js';
import { qaDataRoot, seededAcceptedRecord } from './qa/harness.mjs';

const { readState, needsConsent } = store;

function tempRoot(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bf-qa-onboarding-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

// --- seededAcceptedRecord() ---------------------------------------------------

test('seededAcceptedRecord has the exact shape a real accepted profile has', () => {
  const record = seededAcceptedRecord({ now: () => new Date('2026-03-01T00:00:00.000Z') });
  assert.deepEqual(record, {
    schema_version: 1,
    consent_version: 1,
    accepted: true,
    accepted_at: '2026-03-01T00:00:00.000Z',
    completed_steps: [],
  });
});

test('seededAcceptedRecord defaults `now` to an actual ISO timestamp', () => {
  const record = seededAcceptedRecord();
  assert.equal(typeof record.accepted_at, 'string');
  assert.doesNotThrow(() => new Date(record.accepted_at).toISOString());
  assert.equal(new Date(record.accepted_at).toISOString(), record.accepted_at);
});

test('seededAcceptedRecord satisfies onboardingStore.needsConsent() === false', () => {
  const record = seededAcceptedRecord();
  assert.equal(needsConsent(record), false);
});

test('a file written with seededAcceptedRecord round-trips through onboardingStore.readState as accepted', (t) => {
  const root = tempRoot(t);
  const record = seededAcceptedRecord({ now: () => new Date('2026-03-01T00:00:00.000Z') });
  fs.mkdirSync(root, { recursive: true });
  fs.writeFileSync(path.join(root, 'onboarding.json'), JSON.stringify(record, null, 2));

  // Explicit root, no BETTERFINGERS_DATA_DIR involved -- this is the same
  // read path the main process's onboarding:get-state IPC handler uses (see
  // ipc.js), just pointed at a throwaway directory instead of the real root.
  const state = readState({ root });
  assert.deepEqual(state, record);
  assert.equal(needsConsent(state), false);
});

// --- qaDataRoot() --------------------------------------------------------------

test('qaDataRoot', async (t) => {
  const original = process.env.BETTERFINGERS_DATA_DIR;
  t.after(() => {
    if (original === undefined) delete process.env.BETTERFINGERS_DATA_DIR;
    else process.env.BETTERFINGERS_DATA_DIR = original;
  });

  await t.test('is null when BETTERFINGERS_DATA_DIR is unset', () => {
    delete process.env.BETTERFINGERS_DATA_DIR;
    assert.equal(qaDataRoot(), null);
  });

  await t.test('returns an absolute override unchanged', () => {
    process.env.BETTERFINGERS_DATA_DIR = '/tmp/bf-qa-fixture-root';
    assert.equal(qaDataRoot(), '/tmp/bf-qa-fixture-root');
  });

  await t.test('expands a bare ~ to the home directory', () => {
    process.env.BETTERFINGERS_DATA_DIR = '~';
    assert.equal(qaDataRoot(), os.homedir());
  });

  await t.test('expands a ~/-prefixed override under the home directory', () => {
    process.env.BETTERFINGERS_DATA_DIR = '~/bf-qa-fixture-root';
    assert.equal(qaDataRoot(), path.join(os.homedir(), 'bf-qa-fixture-root'));
  });
});

// --- static import smoke -------------------------------------------------------
//
// The task brief's prescribed smoke check was a one-off `node -e
// "import(...)"` invocation; this worker's sandboxed permission grant only
// allows `Bash(node --test *)` / `Bash(npm run test:*)`, not arbitrary `node
// -e`, so the equivalent check is folded in here instead of run separately.
// It proves the same thing: the scenario module imports cleanly (including
// its `../harness.mjs` import) and exports the expected scenario count.

test('onboarding-prod.mjs imports cleanly and exports 5 scenarios', async () => {
  const mod = await import('./qa/scenarios/onboarding-prod.mjs');
  assert.equal(mod.onboardingProdScenarios.length, 5);
  for (const scenario of mod.onboardingProdScenarios) {
    assert.equal(scenario.ui, 'signal-desk-prod');
    assert.equal(scenario.area, 'onboarding-prod');
    assert.equal(scenario.kind, 'standard');
    assert.equal(typeof scenario.description, 'string');
    assert.ok(scenario.description.length > 0);
  }
});
