import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  ALPHA_CAPABILITIES,
  ALPHA_CAPABILITY_SELECTORS,
  applyAlphaCapabilities,
} from '../src/renderer/config/alphaCapabilities.js';

function element() {
  return {
    hidden: false,
    dataset: {},
    attrs: {},
    setAttribute(name, value) { this.attrs[name] = value; },
  };
}

test('alpha-disabled controls are hidden and inert from one centralized map', () => {
  const elements = new Map();
  for (const selectors of Object.values(ALPHA_CAPABILITY_SELECTORS)) {
    for (const selector of selectors) elements.set(selector, element());
  }
  const root = { querySelectorAll: (selector) => elements.has(selector) ? [elements.get(selector)] : [] };
  const changed = applyAlphaCapabilities(root);
  assert.ok(changed.length >= 8);
  for (const [capability, selectors] of Object.entries(ALPHA_CAPABILITY_SELECTORS)) {
    assert.equal(ALPHA_CAPABILITIES[capability], false);
    for (const selector of selectors) {
      const target = elements.get(selector);
      assert.equal(target.hidden, true);
      assert.equal(target.attrs.inert, '');
      assert.equal(target.dataset.alphaCapability, capability);
    }
  }
});
