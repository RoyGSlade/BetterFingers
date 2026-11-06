// Round 3, items 1 and 2 (Codex re-check 2, findings 1 and 2), end to end through ipc.js with the
// PRODUCTION approval broker, the PRODUCTION workflow executor and the PRODUCTION application
// registry (in a temporary data folder). Only Electron, the backend proxy and the process
// launcher are stand-ins. Run with: node --test app/tests/workflowRunAuthorization.test.mjs
//
// Finding 1: a preview that said "not runnable" let the run through with no dialog, and the
// workflow could be enabled between that answer and the executor's own gate check.
// Finding 2: the executor resolved each application again at step time, so replacing a registry
// entry during a preceding wait launched a target nobody had been shown.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const { linesDigest } = require('../src/main/approvalBroker.js');

const OBSIDIAN = {
  id: 'obsidian', display_name: 'Obsidian', launch_method: 'executable', executable: '/opt/obsidian/obsidian',
};
const WAIT_THEN_LAUNCH = [
  { action: 'wait_for_process', app_id: 'obsidian', timeout_ms: 40 },
  { action: 'launch_app', app_id: 'obsidian' },
];

// The backend's preview of WAIT_THEN_LAUNCH for whatever registry main sent (it echoes the target,
// like action_validator.describe_launch does).
function previewLinesFor(registry) {
  const entry = (registry || []).find((e) => e && e.id === 'obsidian' && e.confirmed);
  if (!entry) return null;
  return ['1. Wait for Obsidian to be running (up to 0.04s)', `2. Launch Obsidian (program ${entry.executable})`];
}

// Captured ONCE: a test that calls setup() several times must not chain the patches.
const Module = require('node:module');
const ORIGINAL_LOAD = Module._load;

function setup(t, { answers = [], preview = {}, gate = {}, onGate = null } = {}) {
  const original = ORIGINAL_LOAD;
  const handlers = new Map();
  const dialogs = [];
  const spawned = [];
  const queue = [...answers];
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'bf-runauth-'));
  const savedDataDir = process.env.BETTERFINGERS_DATA_DIR;
  process.env.BETTERFINGERS_DATA_DIR = dataDir;
  const electron = {
    app: { getPath: () => dataDir, getVersion: () => '0' }, clipboard: {}, session: {}, shell: {}, webContents: {},
    Notification: { isSupported: () => false },
    dialog: {
      showMessageBox: async (...args) => {
        const options = args[args.length - 1];
        dialogs.push(options);
        return { response: queue.length ? queue.shift() : 1 };
      },
    },
    ipcMain: { handle: (c, fn) => handlers.set(c, fn), on() {} },
  };
  const approvedLines = { current: null };
  const backendProxy = {
    init() {},
    onBackendEvent: () => () => {},
    // The broker's main-only route to the backend.
    sendTrusted: async (method, route, body) => {
      if (route !== '/workflows/preview') return { ok: true, status: 200, body: {} };
      const lines = previewLinesFor(body.context.registry);
      return {
        ok: true, status: 200,
        body: {
          ok: Boolean(lines), workflow_id: 'studio_setup', name: 'Studio', preview_lines: lines || [],
          preview_sha256: linesDigest(lines || []), steps_sha256: 'a'.repeat(64), steps: WAIT_THEN_LAUNCH,
          outward: true, runnable: true, refusals: [], ...preview,
        },
      };
    },
    // The executor's route: the run gate and the run record.
    request: async ({ path: route, body }) => {
      if (route === '/workflows/run') {
        if (onGate) onGate();
        const lines = previewLinesFor(body.context.registry);
        approvedLines.current = lines;
        return {
          ok: true, status: 200,
          body: { ok: true, workflow: { id: 'studio_setup', steps: WAIT_THEN_LAUNCH }, preview_lines: lines, ...gate },
        };
      }
      if (route === '/workflows/run/record') {
        return { ok: true, status: 200, body: { ok: true, summary: { ok: body.results.every((r) => r.status === 'ok') } } };
      }
      return { ok: true, status: 200, body: {} };
    },
  };
  const fakeSpawn = (command, args) => { spawned.push([command, ...args]); return { unref() {}, on() {} }; };
  Module._load = function patched(request, parent, isMain) {
    if (request === 'electron') return electron;
    if (request === './backendProxy') return backendProxy;
    if (request === './hotkeys') return { setPrimaryActionHandler() {}, registerHotkeys() {} };
    if (request === './applicationLauncher') {
      const real = original.call(this, request, parent, isMain);
      return { ...real, createApplicationLauncher: (opts) => real.createApplicationLauncher({ ...opts, spawn: fakeSpawn, platform: 'linux' }) };
    }
    return original.call(this, request, parent, isMain);
  };
  t.after(() => {
    Module._load = original;
    if (savedDataDir === undefined) delete process.env.BETTERFINGERS_DATA_DIR; else process.env.BETTERFINGERS_DATA_DIR = savedDataDir;
    fs.rmSync(dataDir, { recursive: true, force: true });
  });
  for (const name of ['ipc.js', 'workflowExecutor.js', 'approvalBroker.js', 'applicationRegistry.js', 'applicationLauncher.js', 'runAuthorization.js']) {
    try { delete require.cache[require.resolve(`../src/main/${name}`)]; } catch { /* not present yet */ }
  }
  require('../src/main/ipc.js').registerIpc({ getMainWindow: () => null, getApprovalKey: () => '00'.repeat(32) });
  const dir = path.join(HERE, '..', 'src', 'renderer');
  const from = (page) => { const frame = { url: `file://${dir}/${page}` }; return { senderFrame: frame, sender: { mainFrame: frame } }; };
  const call = (channel, payload, page = 'signal-desk.html') => handlers.get(channel)(from(page), payload);
  // Write the registry directly (the file main owns), as a prior confirmation would have.
  const writeRegistry = (entries) => {
    const body = { schema_version: 1, entries: Object.fromEntries(entries.map((e) => [e.id, { schema_version: 1, confirmed: true, desktop_entry: '', flatpak_id: '', uri: '', steam_uri: '', profile_id: '', uri_scheme: '', ...e }])) };
    fs.writeFileSync(path.join(dataDir, 'application_registry.json'), JSON.stringify(body));
  };
  writeRegistry([OBSIDIAN]);
  return { handlers, dialogs, spawned, call, writeRegistry, dataDir };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 600)); // past the broker's re-ask gap

// ---- finding 1: confirmation fails closed ----------------------------------------------------

test('finding 1: a preview that says "not runnable" runs nothing, even if the workflow is enabled before the gate', async (t) => {
  // Codex's sequence: the workflow is disabled when main asks for the preview (runnable:false),
  // then it is enabled through /workflows/enable before the executor's own gate check, which passes.
  const ctx = setup(t, { answers: [0], preview: { runnable: false } });
  const result = await ctx.call('workflows:execute', { workflowId: 'studio_setup' });
  assert.equal(result.ok, false);
  assert.equal(ctx.dialogs.filter((d) => d.buttons && d.buttons.length > 1).length, 0, 'no approval dialog was offered');
  assert.deepEqual(ctx.spawned, [], 'zero launches');
});

test('finding 1: an unavailable or invalid preview runs nothing', async (t) => {
  for (const preview of [{ ok: false }, { preview_sha256: 'f'.repeat(64) }, { preview_lines: [] }, { steps: undefined }, { workflow_id: 'other' }]) {
    const ctx = setup(t, { answers: [0], preview });
    const result = await ctx.call('workflows:execute', { workflowId: 'studio_setup' });
    assert.equal(result.ok, false, JSON.stringify(preview));
    assert.deepEqual(ctx.spawned, [], JSON.stringify(preview));
  }
});

test('finding 1: a run with no outward step still needs the dialog (every run is confirmed)', async (t) => {
  const ctx = setup(t, { answers: [1], preview: { outward: false } });
  const result = await ctx.call('workflows:execute', { workflowId: 'studio_setup' });
  assert.equal(result.ok, false);
  assert.equal(ctx.dialogs.length, 1);
  assert.deepEqual(ctx.spawned, []);
});

test('a confirmed run launches exactly the target that was shown, once', async (t) => {
  const ctx = setup(t, { answers: [0] });
  const result = await ctx.call('workflows:execute', { workflowId: 'studio_setup' });
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.equal(ctx.dialogs.length, 1);
  assert.ok(ctx.dialogs[0].detail.includes('/opt/obsidian/obsidian'), 'the dialog names the exact program');
  assert.deepEqual(ctx.spawned, [['/opt/obsidian/obsidian']]);
});

test('finding 1: an authorization is single-use; each run needs its own click', async (t) => {
  const ctx = setup(t, { answers: [0, 1] });
  assert.equal((await ctx.call('workflows:execute', { workflowId: 'studio_setup' })).ok, true);
  await settle();
  assert.equal((await ctx.call('workflows:execute', { workflowId: 'studio_setup' })).ok, false);
  assert.equal(ctx.dialogs.length, 2);
  assert.equal(ctx.spawned.length, 1);
});

test('finding 1: the confirmation result never reaches the renderer with an authorization in it', async (t) => {
  const ctx = setup(t, { answers: [1] });
  const result = await ctx.call('workflows:execute', { workflowId: 'studio_setup' });
  assert.ok(!('authorization' in result));
});

// ---- finding 2: the target is frozen at confirm time -----------------------------------------

test('finding 2: replacing the application during a preceding wait launches nothing', async (t) => {
  let ctx;
  ctx = setup(t, {
    answers: [0],
    // Right after the gate passes, during the 40 ms wait, swap the executable behind the id.
    onGate: () => setTimeout(() => ctx.writeRegistry([{ ...OBSIDIAN, executable: '/tmp/evil' }]), 5),
  });
  const result = await ctx.call('workflows:execute', { workflowId: 'studio_setup' });
  assert.equal(result.ok, false);
  assert.deepEqual(ctx.spawned, [], 'neither the old nor the replaced target ran');
  assert.ok(!JSON.stringify(ctx.spawned).includes('/tmp/evil'));
});

test('finding 2: a target changed between the dialog and the gate is refused before any step', async (t) => {
  let ctx;
  let first = true;
  ctx = setup(t, {
    answers: [0],
    onGate: () => { if (first) { first = false; ctx.writeRegistry([{ ...OBSIDIAN, executable: '/tmp/evil' }]); } },
  });
  const result = await ctx.call('workflows:execute', { workflowId: 'studio_setup' });
  assert.equal(result.ok, false);
  assert.deepEqual(ctx.spawned, []);
});

test('finding 2: applications:confirm replacing an entry needs a native dialog; declining keeps the old one', async (t) => {
  const ctx = setup(t, { answers: [1, 0] });
  const replaced = { ...OBSIDIAN, executable: '/tmp/evil' };
  const refused = await ctx.call('applications:confirm', replaced);
  assert.equal(refused.ok, false);
  assert.equal(ctx.dialogs.length, 1);
  assert.ok(ctx.dialogs[0].detail.includes('/opt/obsidian/obsidian') && ctx.dialogs[0].detail.includes('/tmp/evil'), 'before and after are shown');
  assert.equal(ctx.dialogs[0].defaultId, 1, 'Cancel is the default');
  assert.equal((await ctx.call('applications:list')).entries[0].executable, '/opt/obsidian/obsidian');
  await settle();
  const accepted = await ctx.call('applications:confirm', replaced);
  assert.equal(accepted.ok, true);
  assert.equal((await ctx.call('applications:list')).entries[0].executable, '/tmp/evil');
});

test('adding a new application, or re-confirming one unchanged, needs no dialog', async (t) => {
  const ctx = setup(t, { answers: [] });
  assert.equal((await ctx.call('applications:confirm', { id: 'notes', display_name: 'Notes', launch_method: 'executable', executable: '/usr/bin/notes' })).ok, true);
  assert.equal((await ctx.call('applications:confirm', OBSIDIAN)).ok, true);
  assert.equal(ctx.dialogs.length, 0);
});
