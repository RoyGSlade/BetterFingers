// Unit tests for glitch-ring.js's STATE_STYLES contract (UI-12-003).
//
// Everything here is driven by enumerating STATE_STYLES/STATE_ALIASES
// themselves (Object.keys/Object.entries) rather than a hand-copied list of
// state names -- a hardcoded list would silently drift the moment a state is
// added, renamed, or removed from the source, which is exactly the failure
// this row exists to catch.
//
// Run with: node --test app/tests/glitchRingStates.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { STATE_STYLES, STATE_ALIASES, resolveState } from '../src/renderer/glitch-ring.js';

const stateNames = Object.keys(STATE_STYLES);

test('STATE_STYLES is non-empty and every state round-trips through resolveState', () => {
  assert.ok(stateNames.length > 0, 'STATE_STYLES must declare at least one state');
  for (const name of stateNames) {
    assert.equal(resolveState(name), name, `resolveState('${name}') should return '${name}' unchanged`);
  }
});

test('every state shares the same style schema (same set of style properties)', () => {
  const schemas = stateNames.map((name) => Object.keys(STATE_STYLES[name]).sort().join(','));
  const [first, ...rest] = schemas;
  rest.forEach((schema, i) => {
    assert.equal(
      schema,
      first,
      `state '${stateNames[i + 1]}' has style keys [${schema}], which differ from '${stateNames[0]}''s [${first}]`,
    );
  });
  // And no property is left undefined/null on any state.
  for (const name of stateNames) {
    for (const [prop, value] of Object.entries(STATE_STYLES[name])) {
      assert.notEqual(value, undefined, `state '${name}' has an undefined '${prop}'`);
      assert.notEqual(value, null, `state '${name}' has a null '${prop}'`);
    }
  }
});

test('every state has a visually distinct style -- no two states share an identical style object', () => {
  const seen = new Map();
  for (const name of stateNames) {
    const signature = JSON.stringify(STATE_STYLES[name]);
    assert.ok(
      !seen.has(signature),
      `states '${seen.get(signature)}' and '${name}' declare byte-for-byte identical styles`,
    );
    seen.set(signature, name);
  }
});

test('every STATE_ALIASES entry resolves to a real STATE_STYLES state', () => {
  const known = new Set(stateNames);
  for (const [alias, target] of Object.entries(STATE_ALIASES)) {
    assert.ok(known.has(target), `alias '${alias}' points at '${target}', which is not a STATE_STYLES entry`);
    assert.equal(resolveState(alias), target, `resolveState('${alias}') should resolve to its alias target '${target}'`);
  }
});

test('unknown/garbage state names fall back safely to idle rather than throwing or returning nothing', () => {
  assert.ok(stateNames.includes('idle'), 'idle must exist as the documented fallback target');
  for (const bogus of ['not-a-real-state', '', 'IDLE', 'Recording', 123, {}, [], undefined, null]) {
    assert.equal(resolveState(bogus), 'idle', `resolveState(${JSON.stringify(bogus)}) should fall back to 'idle'`);
  }
});
