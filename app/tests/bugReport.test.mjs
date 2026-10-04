import test from 'node:test';
import assert from 'node:assert/strict';

import {
  BUG_REPORT_ELEMENT_IDS,
  collectBugReportElements,
  createBugReportFeature,
} from '../src/renderer/features/bugReport.js';

class FakeElement {
  constructor(id, document) {
    this.id = id;
    this.ownerDocument = document;
    this.value = '';
    this.checked = false;
    this.disabled = false;
    this.hidden = false;
    this.textContent = '';
    this.dataset = {};
    this.attributes = {};
    this.children = [];
    this.listeners = new Map();
  }

  addEventListener(name, handler) {
    if (!this.listeners.has(name)) this.listeners.set(name, new Set());
    this.listeners.get(name).add(handler);
  }

  removeEventListener(name, handler) {
    this.listeners.get(name)?.delete(handler);
  }

  async emit(name, extra = {}) {
    const event = {
      key: undefined,
      shiftKey: false,
      currentTarget: this,
      target: this,
      defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; },
      ...extra,
    };
    for (const handler of this.listeners.get(name) || []) await handler(event);
    return event;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  appendChild(child) {
    this.children.push(child);
    if (!this.value) this.value = child.value;
    return child;
  }

  focus() {
    this.ownerDocument.activeElement = this;
  }

  querySelectorAll() {
    return this.focusables || [];
  }
}

function harness({ config = {}, prepareImpl, submitImpl } = {}) {
  const document = {
    activeElement: null,
    nodes: {},
    createElement(tag) { return new FakeElement(tag, this); },
    getElementById(id) { return this.nodes[id] || null; },
  };
  const elements = {};
  for (const [name, id] of Object.entries(BUG_REPORT_ELEMENT_IDS)) {
    elements[name] = new FakeElement(id, document);
    document.nodes[id] = elements[name];
  }
  elements.dialog.focusables = [elements.close, elements.summary, elements.actual, elements.previewButton, elements.consent, elements.destination, elements.submit];
  const calls = { config: 0, prepare: [], submit: [], statuses: [] };
  const bridge = {
    async getBugReportConfig() { calls.config += 1; return config; },
    async prepareBugReport(form) {
      calls.prepare.push(form);
      return prepareImpl ? prepareImpl(form) : { previewId: 'preview-1', previewText: '{"safe":true}' };
    },
    async submitBugReport(payload) {
      calls.submit.push(payload);
      return submitImpl ? submitImpl(payload) : { delivered: true, status: 'delivered' };
    },
  };
  const feature = createBugReportFeature({
    elements,
    bridge,
    hooks: { onStatus: (message, meta) => calls.statuses.push({ message, ...meta }) },
  });
  return { document, elements, calls, bridge, feature };
}

test('collector and initialization use the canonical ids and exact field bounds', () => {
  const ctx = harness();
  const collected = collectBugReportElements(ctx.document);
  assert.equal(collected.open, ctx.elements.open);
  assert.equal(collected.status.id, 'sdBugReportStatus');
  assert.equal(ctx.elements.summary.maxLength, 160);
  assert.equal(ctx.elements.steps.maxLength, 4000);
  assert.equal(ctx.elements.expected.maxLength, 4000);
  assert.equal(ctx.elements.actual.maxLength, 4000);
  assert.equal(ctx.elements.contact.maxLength, 254);
  assert.equal(ctx.elements.dialog.hidden, true);
  assert.equal(ctx.elements.submit.disabled, true);
});

test('open loads only configured direct choices, focuses the form, and Escape restores focus', async () => {
  const ctx = harness({ config: { directDiscord: true, directEmail: false } });
  await ctx.elements.open.emit('click');
  assert.equal(ctx.elements.dialog.hidden, false);
  assert.equal(ctx.document.activeElement, ctx.elements.summary);
  assert.deepEqual(
    ctx.elements.destination.children.map((option) => option.value),
    ['direct-discord', 'email', 'discord'],
  );
  const event = await ctx.elements.dialog.emit('keydown', { key: 'Escape' });
  assert.equal(event.defaultPrevented, true);
  assert.equal(ctx.elements.dialog.hidden, true);
  assert.equal(ctx.document.activeElement, ctx.elements.open);
});

test('prepare sends the exact bounded form, renders with textContent, and edits invalidate consent', async () => {
  const ctx = harness();
  ctx.elements.summary.value = 'broken';
  ctx.elements.steps.value = '1. click';
  ctx.elements.expected.value = 'works';
  ctx.elements.actual.value = 'freezes';
  ctx.elements.contact.value = 'tester@example.com';
  await ctx.elements.previewButton.emit('click');

  assert.deepEqual(ctx.calls.prepare, [{
    summary: 'broken', steps: '1. click', expected: 'works', actual: 'freezes', contact: 'tester@example.com',
  }]);
  assert.equal(ctx.elements.preview.textContent, '{"safe":true}');
  assert.equal(ctx.elements.preview.hidden, false);
  assert.equal(ctx.elements.submit.disabled, true);
  ctx.elements.consent.checked = true;
  await ctx.elements.consent.emit('change');
  assert.equal(ctx.elements.submit.disabled, false);

  ctx.elements.actual.value = 'different failure';
  await ctx.elements.actual.emit('input');
  assert.equal(ctx.elements.preview.textContent, '');
  assert.equal(ctx.elements.preview.hidden, true);
  assert.equal(ctx.elements.consent.checked, false);
  assert.equal(ctx.elements.submit.disabled, true);
});

test('validation blocks missing required fields and remains retryable after a preparation error', async () => {
  let attempts = 0;
  const ctx = harness({
    prepareImpl() {
      attempts += 1;
      if (attempts === 1) throw new Error('sidecar unavailable');
      return { previewId: 'preview-2', previewText: 'safe preview' };
    },
  });
  await ctx.elements.previewButton.emit('click');
  assert.equal(ctx.calls.prepare.length, 0);
  assert.equal(ctx.elements.summary.attributes['aria-invalid'], 'true');
  assert.equal(ctx.elements.actual.attributes['aria-invalid'], 'true');

  ctx.elements.summary.value = 'broken';
  ctx.elements.actual.value = 'freezes';
  await ctx.elements.previewButton.emit('click');
  assert.match(ctx.elements.status.textContent, /sidecar unavailable/);
  assert.equal(ctx.elements.summary.disabled, false);
  await ctx.elements.previewButton.emit('click');
  assert.equal(ctx.elements.preview.textContent, 'safe preview');
});

test('submit says sent only for delivered acknowledgement and uses the exact reviewed id and destination', async () => {
  const ctx = harness({
    config: { directDiscord: true },
    submitImpl: async () => ({
      delivered: true, status: 'delivered', requestId: 'relay-request-1',
    }),
  });
  await ctx.elements.open.emit('click');
  ctx.elements.summary.value = 'broken';
  ctx.elements.actual.value = 'freezes';
  await ctx.elements.previewButton.emit('click');
  ctx.elements.consent.checked = true;
  await ctx.elements.consent.emit('change');
  await ctx.elements.submit.emit('click');

  assert.deepEqual(ctx.calls.submit, [{ previewId: 'preview-1', destination: 'direct-discord' }]);
  assert.match(ctx.elements.status.textContent, /sent successfully/i);
  assert.match(ctx.elements.status.textContent, /relay-request-1/);
  assert.equal(ctx.elements.consent.checked, false);
  assert.equal(ctx.elements.submit.disabled, true);
});

test('manual handoff is honest and direct failure never claims the email client opened', async () => {
  const fallback = harness({ submitImpl: async () => ({ delivered: false, status: 'copied_opened_discord' }) });
  fallback.elements.summary.value = 'broken';
  fallback.elements.actual.value = 'freezes';
  fallback.elements.destination.value = 'discord';
  await fallback.elements.previewButton.emit('click');
  fallback.elements.consent.checked = true;
  await fallback.elements.consent.emit('change');
  await fallback.elements.submit.emit('click');
  assert.match(fallback.elements.status.textContent, /not been submitted automatically/i);

  const failure = harness({ submitImpl: async () => ({ delivered: false, status: 'delivery_failed' }) });
  failure.elements.summary.value = 'broken';
  failure.elements.actual.value = 'freezes';
  failure.elements.destination.value = 'direct-email';
  await failure.elements.previewButton.emit('click');
  failure.elements.consent.checked = true;
  await failure.elements.consent.emit('change');
  await failure.elements.submit.emit('click');
  assert.match(failure.elements.status.textContent, /nothing was confirmed sent/i);
  assert.doesNotMatch(failure.elements.status.textContent, /copied|opened/i);
});

test('busy state suppresses duplicate preparation and destroy removes event bindings', async () => {
  let resolvePrepare;
  const pending = new Promise((resolve) => { resolvePrepare = resolve; });
  const ctx = harness({ prepareImpl: () => pending });
  ctx.elements.summary.value = 'broken';
  ctx.elements.actual.value = 'freezes';
  const first = ctx.elements.previewButton.emit('click');
  const second = ctx.elements.previewButton.emit('click');
  assert.equal(ctx.calls.prepare.length, 1);
  resolvePrepare({ previewId: 'preview-1', previewText: 'safe' });
  await Promise.all([first, second]);

  ctx.feature.destroy();
  assert.equal(ctx.elements.dialog.hidden, true);
  await ctx.elements.open.emit('click');
  assert.equal(ctx.calls.config, 0);
  assert.equal(ctx.elements.dialog.hidden, true);
});
