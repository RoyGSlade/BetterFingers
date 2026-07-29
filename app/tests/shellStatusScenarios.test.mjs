// Shape test for the Wave 11B shell-status QA scenarios.
//
// The registry test (qaScenarioRegistry.test.mjs) checks scenarios that are
// REGISTERED in index.mjs. This file checks the module itself, so a scenario
// with a broken shape is caught even in the window before it is registered --
// which is exactly the window this module was authored in.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { shellStatusProdScenarios } from './qa/scenarios/shell-status-prod.mjs';

test('every shell-status scenario targets the PRODUCTION page', () => {
  // The whole point: these assert surfaces that exist only on signal-desk.html.
  // A scenario that silently ran against the legacy page or the preview mockup
  // would prove nothing about what ships.
  assert.ok(shellStatusProdScenarios.length > 0);
  for (const scenario of shellStatusProdScenarios) {
    assert.equal(scenario.ui, 'signal-desk-prod', scenario.name);
  }
});

test('every scenario has the fields the runner requires', () => {
  for (const scenario of shellStatusProdScenarios) {
    assert.ok(scenario.area, `${scenario.name}: area`);
    assert.ok(scenario.name, 'name');
    assert.ok(scenario.description?.length > 80, `${scenario.name}: a real description`);
    assert.ok(scenario.backendState, `${scenario.name}: backendState`);
    assert.equal(typeof scenario.navigate, 'function', `${scenario.name}: navigate`);
    assert.equal(typeof scenario.expects, 'function', `${scenario.name}: expects`);
    assert.ok(Array.isArray(scenario.screenshots) && scenario.screenshots.length, `${scenario.name}: screenshots`);
  }
});

test('scenario names are unique within their area', () => {
  const keys = shellStatusProdScenarios.map((s) => `${s.area}/${s.name}`);
  assert.equal(new Set(keys).size, keys.length);
});

test('the version-mismatch scenario really stubs a disagreeing version', () => {
  // A regression here would leave the positive half of the banner contract
  // passing vacuously against coldBoot's matching versions.
  const scenario = shellStatusProdScenarios.find((s) => s.name === 'version-banner-appears-on-a-real-disagreement');
  assert.ok(scenario, 'the scenario must exist');
  const state = scenario.backendState();
  assert.notEqual(
    state['GET /runtime/version'].expected_electron_api_version,
    '0.1.0',
    'the stub must differ from cold-boot, or the banner would never be provoked',
  );
});
