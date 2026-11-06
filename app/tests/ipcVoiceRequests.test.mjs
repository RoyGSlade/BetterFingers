// Round 2, item 6 through ipc.js: the backend's own status events start the native dialogs;
// a page cannot start, forge or answer one. Run with: node --test app/tests/ipcVoiceRequests.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

function setup(t, { answers = [0] } = {}) {
  const Module = require('node:module');
  const original = Module._load;
  const listeners = [];
  const dialogs = [];
  const posts = [];
  const queue = [...answers];
  const electron = {
    app: { getPath: () => '/tmp/bf-vr', getVersion: () => '0' }, clipboard: {}, session: {}, shell: {}, webContents: {},
    dialog: { showMessageBox: async (...args) => { dialogs.push(args[args.length - 1]); return { response: queue.length ? queue.shift() : 1 }; } },
    ipcMain: { handle() {}, on() {} },
  };
  const backendProxy = {
    init() {}, request: async () => ({ ok: true, status: 200, body: {} }),
    onBackendEvent: (fn) => { listeners.push(fn); return () => {}; },
    sendTrusted: async (method, route, body) => {
      if (method === 'GET' && route === '/drafts') return { ok: true, status: 200, body: { drafts: [{ id: 7, final_text: 'Spoken draft text.' }] } };
      posts.push({ method, route, body });
      return { ok: true, status: 200, body: {} };
    },
  };
  Module._load = function patched(request, parent, isMain) {
    if (request === 'electron') return electron;
    if (request === './backendProxy') return backendProxy;
    if (request === './hotkeys') return { setPrimaryActionHandler() {}, registerHotkeys() {} };
    return original.call(this, request, parent, isMain);
  };
  t.after(() => { Module._load = original; });
  const modulePath = require.resolve('../src/main/ipc.js');
  delete require.cache[modulePath];
  require(modulePath).registerIpc({ getMainWindow: () => null, getApprovalKey: () => '00'.repeat(32) });
  const emit = (message) => listeners.forEach((fn) => fn(message));
  const settle = () => new Promise((resolve) => setTimeout(resolve, 30));
  return { emit, dialogs, posts, settle, listeners };
}

test('main subscribes to the backend\'s events', (t) => {
  assert.equal(setup(t).listeners.length, 1);
});

test('a spoken "send it" request opens the native dialog and places the draft only after a click', async (t) => {
  const ctx = setup(t, { answers: [0] });
  ctx.emit({ status: 'command_needs_tap', action: 'send', kind: 'draft_action', draft_id: 7 });
  await ctx.settle();
  assert.equal(ctx.dialogs.length, 1);
  assert.ok(ctx.dialogs[0].detail.includes('Spoken draft text.'));
  assert.equal(ctx.dialogs[0].defaultId, 1);
  assert.equal(ctx.posts.length, 1);
  assert.equal(ctx.posts[0].route, '/drafts/7/send');
  assert.ok(ctx.posts[0].body.approval.sig);
});

test('declining the spoken request places nothing', async (t) => {
  const ctx = setup(t, { answers: [1] });
  ctx.emit({ status: 'command_needs_tap', action: 'send', draft_id: 7 });
  await ctx.settle();
  assert.equal(ctx.dialogs.length, 1);
  assert.deepEqual(ctx.posts, []);
});

test('a confirmation-gated command asks in a dialog and is replayed with a signed ticket', async (t) => {
  const ctx = setup(t, { answers: [0] });
  ctx.emit({ status: 'command_needs_confirmation', action: 'delete_history', kind: 'app_action', draft_id: null });
  await ctx.settle();
  assert.equal(ctx.dialogs.length, 1);
  assert.equal(ctx.posts[0].route, '/voice-commands/execute');
  assert.ok(ctx.posts[0].body.approval.sig);
});

test('unrelated, malformed and unknown events open nothing', async (t) => {
  const ctx = setup(t, { answers: [0, 0, 0, 0] });
  for (const message of [
    { status: 'recording_started' }, { status: 'command_needs_tap', action: 'copy', draft_id: 7 },
    { status: 'command_needs_confirmation', action: 'rm -rf' }, { status: 'command_needs_confirmation' },
    { status: 'command_needs_tap', action: 'send', draft_id: '7' }, null, 'text', 5,
  ]) ctx.emit(message);
  await ctx.settle();
  assert.equal(ctx.dialogs.length, 0);
  assert.deepEqual(ctx.posts, []);
});
