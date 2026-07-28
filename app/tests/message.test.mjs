// Shared inline status-message helper (lib/message.mjs).
//
// Extracted because the Signal Desk preview had grown a near-copy that set
// data-tone but never removed it. These pin the difference.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { setMessage } from '../src/renderer/lib/message.mjs';

const makeEl = () => ({ textContent: 'stale', dataset: {} });

test('writes text and sets the tone', () => {
  const el = makeEl();
  setMessage(el, 'Saved.', 'success');
  assert.equal(el.textContent, 'Saved.');
  assert.equal(el.dataset.tone, 'success');
});

test('a falsy tone REMOVES the previous one', () => {
  // The bug this exists for: an element that once showed an error kept its red
  // styling under every later neutral message.
  const el = makeEl();
  setMessage(el, 'Boom', 'danger');
  setMessage(el, 'All good');
  assert.equal(el.textContent, 'All good');
  assert.equal('tone' in el.dataset, false, 'stale tone left behind');
});

test('replacing one tone with another does not accumulate', () => {
  const el = makeEl();
  setMessage(el, 'Boom', 'danger');
  setMessage(el, 'Careful', 'warning');
  assert.equal(el.dataset.tone, 'warning');
});

test('no arguments clears the element', () => {
  const el = makeEl();
  el.dataset.tone = 'danger';
  setMessage(el);
  assert.equal(el.textContent, '');
  assert.equal('tone' in el.dataset, false);
});

test('a missing element is a no-op, not a throw', () => {
  // Every renderer call site is optional-chained on the element, not the call.
  assert.doesNotThrow(() => setMessage(null, 'x', 'success'));
  assert.doesNotThrow(() => setMessage(undefined));
});
