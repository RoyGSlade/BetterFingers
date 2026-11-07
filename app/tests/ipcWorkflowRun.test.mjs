// Round 2, item 5 and round 3, item 1, through ipc.js: EVERY run needs a fresh native
// confirmation, the executor is only ever called with the single-use authorization that click
// produced, and there is no dialog-free entry point at all (the old physical-trigger path is
// gone). Run with: node --test app/tests/ipcWorkflowRun.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const { linesDigest } = require('../src/main/approvalBroker.js');

const LINES = ['1. Launch Obsidian (flatpak run md.obsidian.Obsidian)'];
const STEPS = [{ action: 'launch_app', app_id: 'obsidian' }];
const REGISTRY = [{ id: 'obsidian', display_name: 'Obsidian', launch_method: 'flatpak', flatpak_id: 'md.obsidian.Obsidian', confirmed: true }];

function setup(t, { outward = true, runnable = true, answers = [0] } = {}) {
  const Module = require('node:module');
  const original = Module._load;
  const handlers = new Map();
  const executed = [];
  const authorizations = [];
  const dialogs = [];
  const queue = [...answers];
  const electron = {
    app: { getPath: () => '/tmp/bf-wr', getVersion: () => '0' }, clipboard: {}, session: {}, shell: {}, webContents: {},
    dialog: { showMessageBox: async (...args) => { dialogs.push(args[args.length - 1]); return { response: queue.length ? queue.shift() : 1 }; } },
    ipcMain: { handle: (c, fn) => handlers.set(c, fn), on() {} },
  };
  const backendProxy = {
    init() {}, request: async () => ({ ok: true, status: 200, body: {} }), onBackendEvent: () => () => {},
    sendTrusted: async (method, route) => (route === '/workflows/preview'
      ? { ok: true, status: 200, body: { ok: true, workflow_id: 'studio_setup', name: 'Studio', preview_lines: LINES, preview_sha256: linesDigest(LINES), steps_sha256: 'a'.repeat(64), steps: STEPS, outward, runnable, refusals: [] } }
      : { ok: true, status: 200, body: {} }),
  };
  Module._load = function patched(request, parent, isMain) {
    if (request === 'electron') return electron;
    if (request === './backendProxy') return backendProxy;
    if (request === './workflowExecutor') {
      return { createWorkflowExecutor: () => ({ execute: async (id, opts) => { executed.push(id); authorizations.push(opts && opts.authorization); return { ok: true, workflow_id: id }; } }) };
    }
    if (request === './applicationLauncher') return { createApplicationLauncher: () => ({ planFor: () => ({ ok: true, command: 'flatpak', args: ['run', 'md.obsidian.Obsidian'] }) }) };
    if (request === './applicationRegistry') return { createApplicationRegistry: () => ({ list: () => REGISTRY, discover: async () => [], confirm() {}, remove() {} }) };
    if (request === './hotkeys') return { setPrimaryActionHandler() {}, registerHotkeys() {} };
    return original.call(this, request, parent, isMain);
  };
  t.after(() => { Module._load = original; });
  const modulePath = require.resolve('../src/main/ipc.js');
  delete require.cache[modulePath];
  const api = require(modulePath).registerIpc({ getMainWindow: () => null, getApprovalKey: () => '00'.repeat(32) });
  const dir = path.join(HERE, '..', 'src', 'renderer');
  const from = (page) => { const frame = { url: `file://${dir}/${page}` }; return { senderFrame: frame, sender: { mainFrame: frame } }; };
  return { handlers, executed, authorizations, dialogs, api, from };
}

test('a renderer run asks first and runs only after a click, with a fresh authorization', async (t) => {
  const ctx = setup(t, { answers: [0] });
  const result = await ctx.handlers.get('workflows:execute')(ctx.from('signal-desk.html'), { workflowId: 'studio_setup' });
  assert.equal(result.ok, true);
  assert.equal(ctx.dialogs.length, 1);
  assert.ok(ctx.dialogs[0].detail.includes('flatpak'), 'the dialog shows the exact program that will start');
  assert.deepEqual(ctx.executed, ['studio_setup']);
  assert.match(ctx.authorizations[0], /^[0-9a-f]{48}$/);
});

test('declining the confirmation means the executor is never called', async (t) => {
  const ctx = setup(t, { answers: [1] });
  const result = await ctx.handlers.get('workflows:execute')(ctx.from('signal-desk.html'), { workflowId: 'studio_setup' });
  assert.equal(result.ok, false);
  assert.deepEqual(ctx.executed, []);
});

test('repeating the run needs a fresh confirmation each time, and gets a different authorization', async (t) => {
  const ctx = setup(t, { answers: [0, 0] });
  await ctx.handlers.get('workflows:execute')(ctx.from('signal-desk.html'), { workflowId: 'studio_setup' });
  await new Promise((resolve) => setTimeout(resolve, 520)); // past the re-ask delay
  await ctx.handlers.get('workflows:execute')(ctx.from('signal-desk.html'), { workflowId: 'studio_setup' });
  assert.equal(ctx.dialogs.length, 2);
  assert.equal(ctx.executed.length, 2);
  assert.notEqual(ctx.authorizations[0], ctx.authorizations[1]);
});

test('a workflow with no outward action still asks (round 3: every run is confirmed)', async (t) => {
  const ctx = setup(t, { outward: false, answers: [1] });
  await ctx.handlers.get('workflows:execute')(ctx.from('signal-desk.html'), { workflowId: 'studio_setup' });
  assert.equal(ctx.dialogs.length, 1);
  assert.deepEqual(ctx.executed, []);
});

test('a workflow the gate would refuse never reaches the executor and shows no dialog', async (t) => {
  const ctx = setup(t, { runnable: false, answers: [0] });
  const result = await ctx.handlers.get('workflows:execute')(ctx.from('signal-desk.html'), { workflowId: 'studio_setup' });
  assert.equal(result.ok, false);
  assert.equal(result.error, 'not_runnable');
  assert.equal(ctx.dialogs.length, 0);
  assert.deepEqual(ctx.executed, []);
});

test('there is no dialog-free entry point: the only run function main gets also asks', async (t) => {
  const ctx = setup(t, { answers: [1] });
  assert.deepEqual(Object.keys(ctx.api), ['runWorkflowConfirmed']);
  assert.ok(![...ctx.handlers.keys()].some((channel) => /physical|trigger/i.test(channel)));
  const result = await ctx.api.runWorkflowConfirmed('studio_setup');
  assert.equal(result.ok, false);
  assert.equal(ctx.dialogs.length, 1);
  assert.deepEqual(ctx.executed, []);
});

test('the overlay, review and splash windows cannot run workflows at all', async (t) => {
  const ctx = setup(t);
  for (const page of ['overlay.html', 'review-overlay.html', 'splash.html']) {
    assert.deepEqual(await ctx.handlers.get('workflows:execute')(ctx.from(page), { workflowId: 'studio_setup' }), { ok: false, error: 'untrusted_sender' });
  }
  assert.deepEqual(ctx.executed, []);
});
