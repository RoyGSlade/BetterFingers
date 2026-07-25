// Unit tests for the extracted shared toast (lib/toast.mjs).
//
// Extracted from main.js so both dashboards share one implementation. The
// container-less no-op is the important contract: it is why every Signal Desk
// workspace could call hooks.showToast for months and produce nothing.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { showToast, TOAST_CONTAINER_ID } from '../src/renderer/lib/toast.mjs';

/** Minimal DOM double — enough for the element-building path, no jsdom needed. */
function makeDoc({ withContainer = true } = {}) {
  const makeEl = () => {
    const el = {
      className: '',
      type: '',
      textContent: '',
      dataset: {},
      children: [],
      attrs: {},
      classList: { added: [], add(c) { this.added.push(c); } },
      listeners: {},
      setAttribute(k, v) { this.attrs[k] = v; },
      addEventListener(evt, fn) { (this.listeners[evt] ||= []).push(fn); },
      append(...kids) { this.children.push(...kids); },
      remove() { this.removed = true; },
    };
    return el;
  };
  const container = makeEl();
  return {
    container,
    createElement: () => makeEl(),
    getElementById: (id) => (withContainer && id === TOAST_CONTAINER_ID ? container : null),
  };
}

test('renders a toast into the container', () => {
  const doc = makeDoc();
  const toast = showToast('Saved.', 'success', 0, doc);

  assert.ok(toast, 'expected a toast element');
  assert.equal(doc.container.children.length, 1);
  assert.equal(toast.dataset.tone, 'success');

  const [message, close] = toast.children;
  assert.equal(message.textContent, 'Saved.');
  assert.equal(close.attrs['aria-label'], 'Dismiss notification');
});

test('is a silent no-op when the host page has no container', () => {
  // This is exactly the Signal Desk situation before the container was added:
  // the call must not throw, but it also must not pretend to have worked.
  const doc = makeDoc({ withContainer: false });
  assert.equal(showToast('Saved.', 'info', 0, doc), undefined);
});

test('ignores empty messages rather than rendering a blank toast', () => {
  const doc = makeDoc();
  assert.equal(showToast('', 'info', 0, doc), undefined);
  assert.equal(showToast(null, 'info', 0, doc), undefined);
  assert.equal(doc.container.children.length, 0);
});

test('defaults to the info tone', () => {
  const doc = makeDoc();
  assert.equal(showToast('Note.', undefined, 0, doc).dataset.tone, 'info');
});

test('coerces non-string messages instead of dropping them', () => {
  const doc = makeDoc();
  assert.equal(showToast(42, 'info', 0, doc).children[0].textContent, '42');
});

test('dismiss marks the toast leaving', () => {
  const doc = makeDoc();
  const toast = showToast('Bye.', 'info', 0, doc);
  const close = toast.children[1];

  close.listeners.click[0]();
  assert.ok(toast.classList.added.includes('leaving'));
});

test('does not throw when the document itself is unusable', () => {
  // Guards the optional-chaining in the container lookup.
  assert.equal(showToast('x', 'info', 0, undefined), undefined);
  assert.equal(showToast('x', 'info', 0, {}), undefined);
});
