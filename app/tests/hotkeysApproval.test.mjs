// Phase 0 items 1 and 3: the send hotkey signs for the physical press. The press is the tap;
// main signs for exactly the draft and text on display (or the one the backend names in its
// challenge). Run with: node --test app/tests/hotkeysApproval.test.mjs
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);

function load({ displayedDraft = null, reviewVisible = false, replies = [] } = {}) {
  const Module = require('node:module');
  const original = Module._load;
  const requests = [];
  const queue = [...replies];
  const net = {
    request(options) {
      const record = { path: options.path, body: null };
      requests.push(record);
      const handlers = {};
      const req = {
        setHeader() {},
        on(name, fn) { handlers[name] = fn; return req; },
        write(body) { record.body = JSON.parse(body); },
        end() {
          const reply = queue.length ? queue.shift() : { status: 200, json: {} };
          setImmediate(() => {
            const dataHandlers = {};
            handlers.response({
              statusCode: reply.status,
              on(name, fn) { dataHandlers[name] = fn; },
            });
            dataHandlers.data?.(Buffer.from(JSON.stringify(reply.json)));
            dataHandlers.end?.();
          });
        },
      };
      return req;
    },
  };
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
  // hotkeys.js requires ./windows lazily on the key press, so the stubs stay installed until restore().
  return { hotkeys, requests, restore: () => { Module._load = original; } };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 30));

function press(ctx, t) {
  // unregisterAllHotkeys also stops the timers registerHotkeys starts; without it the test run never exits.
  if (t) t.after(() => { ctx.hotkeys.unregisterAllHotkeys(); ctx.restore(); });
  ctx.hotkeys.registerHotkeys({ hotkey: 'f8', manual_send_hotkey: '', recording_mode: 'toggle' }, 'fixture-token');
  ctx.hotkeys.triggerBackendAction('/runtime/primary-action');
}

test('with a draft on display the press signs for exactly that draft and text', async (t) => {
  const signed = [];
  const ctx = load({ displayedDraft: { displayed_draft_id: 7, displayed_final_text: 'shown text' }, reviewVisible: true });
  ctx.hotkeys.setApprovalSigner((request) => { signed.push(request); return { payload: 'p', sig: 's'.repeat(64) }; });
  press(ctx, t);
  await settle();
  assert.deepEqual(signed, [{ draftId: 7, text: 'shown text', action: 'paste' }]);
  assert.equal(ctx.requests.length, 1);
  assert.deepEqual(ctx.requests[0].body, {
    displayed_draft_id: 7, displayed_final_text: 'shown text', approval: { payload: 'p', sig: 's'.repeat(64) },
  });
});

test('with nothing on display the backend\'s challenge is signed on the same press and answered once', async (t) => {
  const signed = [];
  const ctx = load({
    replies: [
      { status: 200, json: { ok: false, error: 'approval_required', draft_id: 9, action: 'paste', final_text: 'queued text' } },
      { status: 200, json: { status: 'sent' } },
    ],
  });
  ctx.hotkeys.setApprovalSigner((request) => { signed.push(request); return { payload: 'p2', sig: 't'.repeat(64) }; });
  press(ctx, t);
  await settle();
  assert.deepEqual(signed, [{ draftId: 9, text: 'queued text', action: 'paste' }]);
  assert.equal(ctx.requests.length, 2);
  assert.deepEqual(ctx.requests[0].body, {});
  assert.deepEqual(ctx.requests[1].body, { approval: { payload: 'p2', sig: 't'.repeat(64) } });
});

test('a second challenge is not chased: one signed retry per press, never a loop', async (t) => {
  const challenge = { status: 200, json: { ok: false, error: 'approval_required', draft_id: 9, action: 'paste', final_text: 't' } };
  const ctx = load({ replies: [challenge, challenge, challenge, challenge] });
  ctx.hotkeys.setApprovalSigner(() => ({ payload: 'p', sig: 's'.repeat(64) }));
  press(ctx, t);
  await settle();
  assert.equal(ctx.requests.length, 2);
});

test('malformed or foreign challenges are ignored', async (t) => {
  for (const json of [
    { error: 'approval_required' }, { error: 'approval_required', draft_id: '9', final_text: 'x' },
    { error: 'approval_required', draft_id: 9 }, { error: 'approval_invalid', draft_id: 9, final_text: 'x' }, null,
  ]) {
    const ctx = load({ replies: [{ status: 200, json }] });
    let signed = 0;
    ctx.hotkeys.setApprovalSigner(() => { signed += 1; return { payload: 'p', sig: 's'.repeat(64) }; });
    press(ctx);
    await settle();
    assert.equal(signed, 0, JSON.stringify(json));
    assert.equal(ctx.requests.length, 1, JSON.stringify(json));
    ctx.hotkeys.unregisterAllHotkeys();
    ctx.restore(); // restore in LIFO order: each load() saved the loader it replaced
  }
});

test('without a signer the press sends no approval (the backend will refuse, which is the safe outcome)', async (t) => {
  const ctx = load({ displayedDraft: { displayed_draft_id: 7, displayed_final_text: 'shown text' }, reviewVisible: true });
  press(ctx, t);
  await settle();
  assert.deepEqual(ctx.requests[0].body, { displayed_draft_id: 7, displayed_final_text: 'shown text' });
});

test('a signer that declines to sign (bad input) leaves the request without an approval', async (t) => {
  const ctx = load({ displayedDraft: { displayed_draft_id: 7, displayed_final_text: 'shown text' }, reviewVisible: true });
  ctx.hotkeys.setApprovalSigner(() => null);
  press(ctx, t);
  await settle();
  assert.ok(!('approval' in ctx.requests[0].body));
});
