// Structural test for the QA scenario registry (app/tests/qa/scenarios/index.mjs).
//
// The visual QA suite only runs under Electron, which means a scenario file
// with a syntax error, a missing export, a mistyped `ui:` target or a duplicated
// name is not discovered until someone launches the whole app -- and a scenario
// silently filtered out by a bad target looks exactly like a scenario that
// passed, because run.mjs reports on what it selected, not on what it skipped.
// This test is the cheap half of that: it imports the registry under plain Node
// and asserts the shape every scenario has to have.
//
// Deliberately names NO element ids, endpoints or selectors. Files matching
// app/tests/*.test.mjs are read by tools/parity_evidence.py as unit coverage for
// whatever handles they mention, so a structural test that happened to quote a
// production id would credit a parity row with coverage it does not have.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { scenarios } from './qa/scenarios/index.mjs';
import { UI_TARGETS, DEFAULT_SCENARIO_UI } from './qa/harness.mjs';

test('every registered scenario has the shape run.mjs requires', () => {
  assert.ok(scenarios.length > 0, 'registry is empty');
  for (const scenario of scenarios) {
    const label = `${scenario.area}/${scenario.name}`;
    assert.equal(typeof scenario.area, 'string', `${label}: area must be a string`);
    assert.ok(scenario.area, `${label}: area must be non-empty`);
    assert.ok(scenario.name, `${label}: name must be non-empty`);
    assert.equal(typeof scenario.description, 'string', `${label}: description must be a string`);
    assert.ok(scenario.description.length > 40, `${label}: description is the walkbook caption`);
    assert.equal(typeof scenario.navigate, 'function', `${label}: navigate must be a function`);
    assert.equal(typeof scenario.expects, 'function', `${label}: expects must be a function`);
    assert.ok(
      scenario.kind === undefined
        || scenario.kind === 'standard'
        || scenario.kind === 'negative-control',
      `${label}: unknown kind ${scenario.kind}`,
    );
  }
});

test('every scenario declares a UI target run.mjs can select', () => {
  for (const scenario of scenarios) {
    const target = scenario.ui ?? DEFAULT_SCENARIO_UI;
    assert.ok(
      Object.hasOwn(UI_TARGETS, target),
      `${scenario.area}/${scenario.name}: ui "${target}" is not a known target `
        + `(${Object.keys(UI_TARGETS).join(', ')}) -- run.mjs would silently never select it`,
    );
  }
});

test('scenario names are unique within their area', () => {
  const seen = new Set();
  for (const scenario of scenarios) {
    const key = `${scenario.area}/${scenario.name}`;
    assert.ok(!seen.has(key), `duplicate scenario ${key} -- the later one overwrites the earlier screenshot`);
    seen.add(key);
  }
});

test('backendState resolves to a route map keyed by "METHOD /path"', () => {
  for (const scenario of scenarios) {
    const label = `${scenario.area}/${scenario.name}`;
    const state = typeof scenario.backendState === 'function'
      ? scenario.backendState()
      : scenario.backendState;
    assert.equal(typeof state, 'object', `${label}: backendState must resolve to an object`);
    assert.ok(state !== null, `${label}: backendState must not be null`);
    for (const key of Object.keys(state)) {
      assert.match(
        key,
        /^(GET|POST|PUT|PATCH|DELETE|WS) \//,
        `${label}: stub key "${key}" is not "METHOD /path", so matchRoute can never hit it`,
      );
    }
  }
});
