// Round 2, item 2: the send hotkey signs nothing. Run with: node --test app/tests/hotkeysApproval.test.mjs
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);

function load({ displayedDraft = null, reviewVisible = false } = {}) {
  const Module = require('node:module');
  const original = Module._load;
  const requests = [];
  const net = { request(options) { requests.push(options); return { setHeader() {}, on() { return this; }, write() {}, end() {} }; } };
  const uiohook = { uIOhook: { on() {}, removeAllListeners() {}, start() { throw new Error('use globalShortcut'); }, stop() {} }, UiohookKey: {} };
  Module._load = function patched(request, parent, isMain) {
    if (request === 'electron') return { globalShortcut: { register: () => true, unregisterAll() {} }, net };
    if (request === 'uiohook-napi') return uiohook;
    if (request === './windows') return { getDisplayedReviewDraft: () => displayedDraft, isReviewWindowVisible: () => reviewVisible };
    return original.call(this, request, parent, isMain);
  };
  const modulePath = require.resolve('../src/main/hotkeys.js');
  delete require.cache[modulePath];
  const hotkeys = require(modulePath);
  return { hotkeys, requests, restore: () => { Module._load = original; } };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 20));

function press(ctx, t) {
  t.after(() => { ctx.hotkeys.unregisterAllHotkeys(); ctx.restore(); });
  ctx.hotkeys.registerHotkeys({ hotkey: 'f8', manual_send_hotkey: '', recording_mode: 'toggle' }, 'fixture-token');
  ctx.hotkeys.triggerBackendAction('/runtime/primary-action');
}

test('a press with no handler installed places nothing and contacts nothing', async (t) => {
  const ctx = load({ displayedDraft: { displayed_draft_id: 7, displayed_final_text: 'x' }, reviewVisible: true });
  press(ctx, t);
  await settle();
  assert.equal(ctx.requests.length, 0);
});

test('the press passes on the draft id the review window names, not the text it claims', async (t) => {
  const presses = [];
  const ctx = load({ displayedDraft: { displayed_draft_id: 7, displayed_final_text: 'EVIL claimed text' }, reviewVisible: true });
  ctx.hotkeys.setPrimaryActionHandler(async (p) => { presses.push(p); return { ok: false, error: 'declined' }; });
  press(ctx, t);
  await settle();
  assert.deepEqual(presses, [{ displayedDraftId: 7, reviewVisible: true }]);
  assert.ok(!JSON.stringify(presses).includes('EVIL'));
  assert.equal(ctx.requests.length, 0);
});

test('a handler that throws does not crash the hotkey path', async (t) => {
  const ctx = load();
  ctx.hotkeys.setPrimaryActionHandler(async () => { throw new Error('boom'); });
  press(ctx, t);
  await settle();
  assert.equal(ctx.requests.length, 0);
});

test('the module no longer has any way to sign', () => {
  const fs = require('node:fs');
  const source = fs.readFileSync(require.resolve('../src/main/hotkeys.js'), 'utf8');
  for (const word of ['setApprovalSigner', 'approvalSigner', 'signPhysicalPress', 'approval:']) {
    assert.ok(!source.includes(word), word);
  }
});
