// QA target wiring after the Wave 11 default flip.
//
// The flip changed two independent defaults that are easy to confuse, and
// getting them backwards is silent: a run that opens the production page but
// selects the ~37 legacy scenarios reports a wall of "element not found" that
// reads like a broken app, and a run that opens the legacy page while
// selecting production scenarios does the same in reverse.
//
//   DEFAULT_UI          = which PAGE a bare `node tests/qa/run.mjs` opens
//                         -> signal-desk-prod (the flip)
//   DEFAULT_SCENARIO_UI = which TARGET an untagged scenario belongs to
//                         -> legacy (unchanged: those scenarios were written
//                            against index.html's ids and still are)
//
// This also serves as a parse check on the whole scenario registry: importing
// it here means a syntax error in any scenario file fails `npm run test:unit`
// instead of waiting for someone to launch Electron.
//
// Run with:  cd app && node --test tests/qaTargets.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';

import { UI_TARGETS, DEFAULT_UI, DEFAULT_SCENARIO_UI } from './qa/harness.mjs';
import { scenarios } from './qa/scenarios/index.mjs';

test('the default QA target is the production page', () => {
  assert.equal(DEFAULT_UI, 'signal-desk-prod');
  assert.equal(UI_TARGETS[DEFAULT_UI].page, 'signal-desk.html');
  // Empty env is the assertion, not a detail: it is what makes an unqualified
  // run prove the DEFAULT route rather than the opt-in one.
  assert.deepEqual(UI_TARGETS[DEFAULT_UI].env, {});
});

test('the legacy rollback target exists and asks for index.html explicitly', () => {
  const legacy = UI_TARGETS.legacy;
  assert.ok(legacy, 'the legacy rollback target must exist');
  assert.equal(legacy.page, 'index.html');
  assert.deepEqual(legacy.env, { BF_UI: 'legacy' });
  // Its screenshots keep the historical location so committed legacy
  // baselines stay comparable across the rename.
  assert.equal(legacy.outSubdir, '');
});

test('the preview target is untouched and still points at the preview page', () => {
  // Pinned by D-0007: signal-desk-shell/-sections/-talk scenarios depend on
  // this target continuing to mean the mockup, never the composition root.
  assert.equal(UI_TARGETS['signal-desk'].page, 'signal-desk-preview.html');
  assert.deepEqual(UI_TARGETS['signal-desk'].env, { BF_UI: 'signal-desk' });
  assert.equal(UI_TARGETS['signal-desk'].outSubdir, 'signal-desk');
});

test('untagged scenarios belong to legacy, not to whatever the default run opens', () => {
  assert.equal(DEFAULT_SCENARIO_UI, 'legacy');
});

test('every scenario declares a known UI target', () => {
  const known = new Set(Object.keys(UI_TARGETS));
  const bad = scenarios
    .filter((s) => s.ui && !known.has(s.ui))
    .map((s) => `${s.area}/${s.name}: ui=${s.ui}`);
  assert.deepEqual(bad, [], `unknown UI targets: ${bad}`);
});

test('every target has at least one scenario, including the rollback path', () => {
  const counts = Object.fromEntries(Object.keys(UI_TARGETS).map((name) => [name, 0]));
  for (const scenario of scenarios) {
    counts[scenario.ui || DEFAULT_SCENARIO_UI] += 1;
  }
  for (const [name, count] of Object.entries(counts)) {
    assert.ok(count > 0, `UI target "${name}" has no scenarios`);
  }
  // The rollback path specifically: a legacy target that only carries
  // inherited untagged scenarios would still pass the loop above, so assert
  // the deliberate Wave 11 rollback scenario is there by name.
  assert.ok(
    scenarios.some((s) => s.area === 'default-flip' && s.ui === 'legacy'),
    'no legacy-target default-flip scenario -- the rollback route is unproven',
  );
  assert.ok(
    scenarios.some((s) => s.area === 'default-flip' && s.ui === 'signal-desk-prod'),
    'no production-target default-flip scenario -- the flip itself is unproven',
  );
});

test('scenario names are unique within an area', () => {
  const seen = new Set();
  const dupes = [];
  for (const scenario of scenarios) {
    const key = `${scenario.ui || DEFAULT_SCENARIO_UI}/${scenario.area}/${scenario.name}`;
    if (seen.has(key)) dupes.push(key);
    seen.add(key);
  }
  // Screenshots are written to <outSubdir>/<area>/<name>.png, so a duplicate
  // silently overwrites another scenario's evidence.
  assert.deepEqual(dupes, [], `duplicate scenario keys overwrite screenshots: ${dupes}`);
});
