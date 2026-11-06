// Round 2, item 7 through ipc.js: the proxy profile follows the PAGE main sees. Run with:
// node --test app/tests/ipcReviewProxy.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));

function setup(t) {
  const Module = require('node:module');
  const original = Module._load;
  const handlers = new Map();
  const seen = [];
  const realProxy = require('../src/main/backendProxy.js');
  const backendProxy = {
    ...realProxy,
    request: async (args) => {
      seen.push(args);
      const error = realProxy._validateRequest(String(args.method || 'GET').toUpperCase(), args.path, args.profile);
      return error ? { ok: false, status: 0, error } : { ok: true, status: 200, body: {} };
    },
    onBackendEvent: () => () => {},
  };
  Module._load = function patched(request, parent, isMain) {
    if (request === 'electron') {
      return { app: { getPath: () => '/tmp/x', getVersion: () => '0' }, clipboard: {}, dialog: {}, session: {}, shell: {}, webContents: {},
        ipcMain: { handle: (c, fn) => handlers.set(c, fn), on() {} } };
    }
    if (request === './backendProxy') return backendProxy;
    if (request === './hotkeys') return { setPrimaryActionHandler() {}, registerHotkeys() {} };
    return original.call(this, request, parent, isMain);
  };
  t.after(() => { Module._load = original; });
  const modulePath = require.resolve('../src/main/ipc.js');
  delete require.cache[modulePath];
  require(modulePath).registerIpc({ getMainWindow: () => null, getApprovalKey: () => '00'.repeat(32) });
  const dir = path.join(HERE, '..', 'src', 'renderer');
  const from = (page) => { const frame = { url: `file://${dir}/${page}` }; return { senderFrame: frame, sender: { mainFrame: frame } }; };
  return { call: (page, req) => handlers.get('backend:request')(from(page), req), seen };
}

test('the review window can reach its own routes and nothing else', async (t) => {
  const ctx = setup(t);
  assert.equal((await ctx.call('review-overlay.html', { method: 'POST', path: '/drafts/7/accept', body: {} })).ok, true);
  assert.equal((await ctx.call('review-overlay.html', { method: 'GET', path: '/runtime/output-settings' })).ok, true);
  for (const req of [
    { method: 'POST', path: '/personas', body: { name: 'x', prompt: 'y', few_shot: [{ raw: 'a', out: 'b' }] } },
    { method: 'POST', path: '/settings/profiles/x/activate' }, { method: 'POST', path: '/workflows/save', body: {} },
    { method: 'DELETE', path: '/history' }, { method: 'GET', path: '/privacy/export' },
  ]) {
    const result = await ctx.call('review-overlay.html', req);
    assert.equal(result.ok, false, `${req.method} ${req.path}`);
  }
});

test('the dashboard keeps its full table, and a page cannot choose its own profile', async (t) => {
  const ctx = setup(t);
  assert.equal((await ctx.call('signal-desk.html', { method: 'POST', path: '/personas', body: {} })).ok, true);
  // A review page that SAYS it is the dashboard still gets the review table.
  const sneaky = await ctx.call('review-overlay.html', { method: 'POST', path: '/personas', body: {}, profile: 'dashboard' });
  assert.equal(sneaky.ok, false);
  assert.equal(ctx.seen.at(-1).profile, 'review');
});
