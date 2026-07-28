// Persona wizard trait sliders (Stage 10).
//
// The band boundaries live in two places by necessity — persona_traits.py
// renders the prompt, features/personas.js renders the label — so the whole
// point of these tests is that they agree. A UI reading "High" while the prompt
// emits the neutral (i.e. no) instruction is worse than showing no label at
// all: it invents a precision the model never sees.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  WIZARD_TRAIT_KEYS,
  traitBandLabel,
  traitElementKey,
} from '../src/renderer/features/personas.js';

test('traitBandLabel matches the backend boundaries exactly', () => {
  const cases = [
    [0, 'Very low'], [19, 'Very low'],
    [20, 'Low'], [39, 'Low'],
    [40, 'Neutral'], [50, 'Neutral'], [59, 'Neutral'],
    [60, 'High'], [79, 'High'],
    [80, 'Very high'], [100, 'Very high'],
  ];
  for (const [value, expected] of cases) {
    assert.equal(traitBandLabel(value), expected, `${value} should read ${expected}`);
  }
});

test('values inside one band read identically', () => {
  // 63 and 67 compose to the same prompt, so they must read the same too.
  assert.equal(traitBandLabel(63), traitBandLabel(67));
  assert.equal(traitBandLabel(44), traitBandLabel(56));
});

test('traitBandLabel clamps rather than inventing a sixth band', () => {
  assert.equal(traitBandLabel(-10), 'Very low');
  assert.equal(traitBandLabel(9999), 'Very high');
});

test('traitBandLabel reports nothing for a non-numeric value', () => {
  for (const junk of [null, undefined, '', 'warm', NaN]) {
    assert.equal(traitBandLabel(junk), '');
  }
});

test('traitElementKey builds the id the markup actually uses', () => {
  assert.equal(traitElementKey('warmth'), 'wizardTraitWarmth');
  assert.equal(traitElementKey('confidence'), 'wizardTraitConfidence');
});

test('all five axes are covered, in the order the prompt emits them', () => {
  assert.deepEqual(
    WIZARD_TRAIT_KEYS,
    ['warmth', 'directness', 'detail', 'formality', 'confidence'],
  );
});
