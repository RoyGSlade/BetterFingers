// The workflow run executor (Wave 10 / D-0027).
//
// The properties under test are the ones that make it safe to put a workflow on
// a controller button: the channel carries an id, the gate is consulted on
// EVERY run, no step runs on a bad verdict, and this module is the only thing
// that reaches the launcher.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = path.resolve(HERE, '..');
const MAIN_DIR = path.join(APP, 'src', 'main');
const require = createRequire(import.meta.url);

const { createWorkflowExecutor, MAX_WAIT_MS } = require(path.join(MAIN_DIR, 'workflowExecutor.js'));

const REGISTRY = [{
  id: 'obsidian',
  display_name: 'Obsidian',
  launch_method: 'flatpak',
  flatpak_id: 'md.obsidian.Obsidian',
  confirmed: true,
}];

const WORKFLOW = {
  id: 'studio_setup',
  name: 'Studio setup',
  steps: [
    { action: 'launch_app', app_id: 'obsidian' },
    { action: 'activate_application_profile', profile_id: 'writing_app' },
  ],
};

/** A backendProxy stand-in with a scripted reply per path. */
function fakeProxy(replies = {}) {
  const calls = [];
  return {
    calls,
    request: async ({ method, path: routePath, body }) => {
      calls.push({ method, path: routePath, body });
      const reply = replies[routePath];
      if (typeof reply === 'function') return reply(body);
      if (reply === undefined) return { ok: true, status: 200, body: { ok: true } };
      return reply;
    },
  };
}

function fakeLauncher() {
  const launched = [];
  return {
    launched,
    launch: (entry) => { launched.push(['launch', entry.id]); return { status: 'ok' }; },
    focus: (entry) => { launched.push(['focus', entry.id]); return { status: 'ok' }; },
    open: (target) => { launched.push(['open', target]); return { status: 'ok' }; },
  };
}

function gateOk(workflow = WORKFLOW) {
  return {
    ok: true,
    status: 200,
    body: { ok: true, workflow, preview_lines: ['1. Launch Obsidian'] },
  };
}

/** Stands in for summarize_run: success only when every step reported ok. */
function recordEcho() {
  return (body) => {
    const completed = body.results.filter((r) => r.status === 'ok').length;
    const total = body.results.length;
    const ok = total > 0 && completed === total;
    return {
      ok: true,
      status: 200,
      body: {
        ok: true,
        summary: { ok, status: ok ? 'success' : 'partial', total, completed },
      },
    };
  };
}

function build({ replies = {}, ...rest } = {}) {
  const backendProxy = fakeProxy({
    '/workflows/run': gateOk(),
    '/workflows/run/record': recordEcho(),
    ...replies,
  });
  const launcher = fakeLauncher();
  const executor = createWorkflowExecutor({
    backendProxy, launcher, listApplications: () => REGISTRY, ...rest,
  });
  return { executor, backendProxy, launcher };
}

// --- the id-only channel ----------------------------------------------------

test('a malformed workflow id is refused before anything is asked of the backend', async () => {
  const { executor, backendProxy } = build();
  for (const bad of ['', '   ', '../../etc/passwd', 'Has Spaces', 'a'.repeat(200), null]) {
    const result = await executor.execute(bad);
    assert.equal(result.ok, false);
    assert.equal(result.error, 'invalid_id');
  }
  assert.equal(backendProxy.calls.length, 0);
});

test('execute takes an id and nothing else — steps are read from the gate reply', async () => {
  // The renderer cannot describe work. Even if it could reach `execute` with a
  // second argument, the steps that run come from the backend's reply.
  const { executor, launcher, backendProxy } = build();
  await executor.execute('studio_setup', { steps: [{ action: 'open_uri', uri: 'evil://' }] });
  assert.deepEqual(launcher.launched, [['launch', 'obsidian']]);
  assert.equal(backendProxy.calls[0].body.workflow_id, 'studio_setup');
});

// --- the gate ---------------------------------------------------------------

test('the run gate is consulted before any step runs', async () => {
  const { executor, backendProxy, launcher } = build();
  await executor.execute('studio_setup');
  assert.equal(backendProxy.calls[0].path, '/workflows/run');
  assert.ok(launcher.launched.length > 0);
});

test('a refusal from the gate runs nothing and passes the reason through unchanged', async () => {
  const { executor, launcher, backendProxy } = build({
    replies: {
      '/workflows/run': {
        ok: true,
        status: 200,
        body: {
          ok: false,
          error: 'not_approved',
          reason: 'You have not approved that workflow yet.',
          preview_lines: ['1. Launch Obsidian'],
        },
      },
    },
  });

  const result = await executor.execute('studio_setup');

  assert.equal(result.ok, false);
  assert.equal(result.error, 'not_approved');
  assert.equal(result.reason, 'You have not approved that workflow yet.');
  assert.deepEqual(launcher.launched, []);
  // And nothing was filed as a run, because nothing ran.
  assert.ok(!backendProxy.calls.some((c) => c.path === '/workflows/run/record'));
});

test('a validation failure from the gate runs nothing', async () => {
  const { executor, launcher } = build({
    replies: {
      '/workflows/run': {
        ok: true,
        status: 200,
        body: {
          ok: false,
          error: 'validation_failed',
          reason: 'Some steps no longer point at anything BetterFingers can open.',
          refusals: [{ step: 1, reason: 'That application is no longer confirmed.' }],
        },
      },
    },
  });
  const result = await executor.execute('studio_setup');
  assert.equal(result.ok, false);
  assert.equal(result.refusals.length, 1);
  assert.deepEqual(launcher.launched, []);
});

test('a deleted workflow is a refusal, not a crash', async () => {
  const { executor, launcher } = build({
    replies: { '/workflows/run': { ok: true, status: 404, body: { detail: 'gone' } } },
  });
  const result = await executor.execute('studio_setup');
  assert.equal(result.error, 'not_found');
  assert.deepEqual(launcher.launched, []);
});

test('an unreachable backend refuses rather than launching optimistically', async () => {
  const { executor, launcher } = build({
    replies: { '/workflows/run': { ok: false, error: 'ECONNREFUSED' } },
  });
  const result = await executor.execute('studio_setup');
  assert.equal(result.error, 'backend_unreachable');
  assert.deepEqual(launcher.launched, []);
});

// --- step execution ---------------------------------------------------------

test('every launcher-facing verb reaches the launcher with the confirmed entry', async () => {
  const workflow = {
    id: 'w', steps: [
      { action: 'launch_app', app_id: 'obsidian' },
      { action: 'focus_app', app_id: 'obsidian' },
      { action: 'open_uri', uri: 'https://example.invalid' },
      { action: 'open_folder', path: '/home/someone/Notes' },
    ],
  };
  const { executor, launcher } = build({
    replies: { '/workflows/run': gateOk(workflow) },
  });
  await executor.execute('w');
  assert.deepEqual(launcher.launched, [
    ['launch', 'obsidian'],
    ['focus', 'obsidian'],
    ['open', 'https://example.invalid'],
    ['open', '/home/someone/Notes'],
  ]);
});

test('a step naming an application that is no longer confirmed is not_found, not a guess', async () => {
  const workflow = { id: 'w', steps: [{ action: 'launch_app', app_id: 'deleted_app' }] };
  const { executor, launcher, backendProxy } = build({
    replies: { '/workflows/run': gateOk(workflow) },
  });
  await executor.execute('w');
  assert.deepEqual(launcher.launched, []);
  const recorded = backendProxy.calls.find((c) => c.path === '/workflows/run/record');
  assert.equal(recorded.body.results[0].status, 'not_found');
});

test('steps run in the order the user read in the preview', async () => {
  const workflow = {
    id: 'w', steps: [
      { action: 'launch_app', app_id: 'obsidian' },
      { action: 'wait_for_process', app_id: 'obsidian', timeout_ms: 5 },
      { action: 'focus_app', app_id: 'obsidian' },
    ],
  };
  const seen = [];
  const { executor } = build({
    replies: { '/workflows/run': gateOk(workflow) },
    wait: async (ms) => { seen.push(['wait', ms]); },
  });
  const { executor: _unused } = { executor };
  await executor.execute('w');
  assert.deepEqual(seen, [['wait', 5]]);
});

test('wait_for_process is bounded', async () => {
  const workflow = {
    id: 'w', steps: [{ action: 'wait_for_process', app_id: 'obsidian', timeout_ms: 10 ** 9 }],
  };
  const waits = [];
  const { executor } = build({
    replies: { '/workflows/run': gateOk(workflow) },
    wait: async (ms) => { waits.push(ms); },
  });
  await executor.execute('w');
  assert.deepEqual(waits, [MAX_WAIT_MS]);
});

test('an unimplemented verb is refused, not silently skipped', async () => {
  // "The plan said do this and nothing did it" has to be visible in the summary.
  const workflow = { id: 'w', steps: [{ action: 'invent_a_verb' }] };
  const { executor, backendProxy } = build({
    replies: { '/workflows/run': gateOk(workflow) },
  });
  await executor.execute('w');
  const recorded = backendProxy.calls.find((c) => c.path === '/workflows/run/record');
  assert.equal(recorded.body.results[0].status, 'refused');
});

test('a verb with no wiring reports unavailable rather than claiming success', async () => {
  const workflow = { id: 'w', steps: [{ action: 'activate_persona', persona: 'True Janitor' }] };
  const { executor, backendProxy } = build({
    replies: { '/workflows/run': gateOk(workflow) },
  });
  const result = await executor.execute('w');
  const recorded = backendProxy.calls.find((c) => c.path === '/workflows/run/record');
  assert.equal(recorded.body.results[0].status, 'unavailable');
  assert.equal(result.ok, false);
});

test('a step that throws becomes a failed code and the run continues', async () => {
  const workflow = {
    id: 'w', steps: [
      { action: 'launch_app', app_id: 'obsidian' },
      { action: 'focus_app', app_id: 'obsidian' },
    ],
  };
  const backendProxy = fakeProxy({
    '/workflows/run': gateOk(workflow),
    '/workflows/run/record': recordEcho(),
  });
  const launcher = fakeLauncher();
  launcher.launch = () => { throw new Error('spawn exploded'); };
  const executor = createWorkflowExecutor({
    backendProxy, launcher, listApplications: () => REGISTRY,
  });

  await executor.execute('w');

  const recorded = backendProxy.calls.find((c) => c.path === '/workflows/run/record');
  assert.deepEqual(recorded.body.results.map((r) => r.status), ['failed', 'ok']);
});

// --- recording --------------------------------------------------------------

test('per-step status codes are recorded, and nothing else is', async () => {
  const { executor, backendProxy } = build();
  await executor.execute('studio_setup');
  const recorded = backendProxy.calls.find((c) => c.path === '/workflows/run/record');
  assert.equal(recorded.body.workflow_id, 'studio_setup');
  for (const row of recorded.body.results) {
    assert.deepEqual(Object.keys(row).sort(), ['action', 'index', 'status']);
    assert.equal(typeof row.status, 'string');
  }
  // No path, no message, no launcher error string.
  assert.ok(!JSON.stringify(recorded.body).includes('flatpak'));
});

test('a run in which everything failed is still recorded', async () => {
  const workflow = { id: 'w', steps: [{ action: 'launch_app', app_id: 'gone' }] };
  const { executor, backendProxy } = build({
    replies: {
      '/workflows/run': gateOk(workflow),
    },
  });
  const result = await executor.execute('w');
  assert.ok(backendProxy.calls.some((c) => c.path === '/workflows/run/record'));
  assert.equal(result.ok, false);
});

// --- double-trigger ---------------------------------------------------------

test('two presses of the same button do not run the workflow twice', async () => {
  // A controller with a bouncy shoulder button, or a user pressing again
  // because nothing visible happened yet.
  const { executor, launcher } = build();
  const [a, b] = await Promise.all([
    executor.execute('studio_setup'),
    executor.execute('studio_setup'),
  ]);
  assert.deepEqual(launcher.launched, [['launch', 'obsidian']]);
  assert.deepEqual(a, b);
});

test('a different workflow is not blocked by one already running', async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const backendProxy = fakeProxy({
    '/workflows/run': async (body) => {
      if (body.workflow_id === 'slow_one') await gate;
      return gateOk({ id: body.workflow_id, steps: [] });
    },
    '/workflows/run/record': recordEcho(),
  });
  const executor = createWorkflowExecutor({
    backendProxy, launcher: fakeLauncher(), listApplications: () => REGISTRY,
  });

  const slow = executor.execute('slow_one');
  const fast = await executor.execute('fast_one');
  assert.ok(fast.summary);
  release();
  await slow;
});

test('the lock is released so the same workflow can run again later', async () => {
  const { executor, launcher } = build();
  await executor.execute('studio_setup');
  assert.equal(executor.isRunning('studio_setup'), false);
  await executor.execute('studio_setup');
  assert.equal(launcher.launched.length, 2);
});

// --- the structural rule ----------------------------------------------------

test('the executor is the only main-process module that reaches the launcher', async () => {
  // D-0027: "No bare launch IPC may exist; the executor is the ONLY caller of
  // the launcher." A second caller would be a second place the approval gate
  // could be skipped, and it is the one nobody tests.
  //
  // Exactly one file names the launcher: ipc.js, and only to CONSTRUCT it and
  // hand it to the executor. The executor itself takes the launcher as an
  // injected dependency and never requires it, which is why it does not appear
  // in this list -- and is also why it is testable without spawning anything.
  const callers = fs.readdirSync(MAIN_DIR)
    .filter((name) => name.endsWith('.js'))
    .filter((name) => /require\(\s*['"]\.\/applicationLauncher['"]\s*\)/
      .test(fs.readFileSync(path.join(MAIN_DIR, name), 'utf8')));

  assert.deepEqual(callers.sort(), ['ipc.js'],
    'only ipc.js may require applicationLauncher, and only to hand it to the executor');

  // And ipc.js only constructs it to hand to the executor -- it never calls
  // launch/focus/open itself.
  const ipcSource = fs.readFileSync(path.join(MAIN_DIR, 'ipc.js'), 'utf8');
  for (const method of ['.launch(', '.focus(', '.open(']) {
    assert.ok(!ipcSource.includes(`launcher${method}`),
      `ipc.js must not call the launcher directly (${method})`);
  }
});

test('there is exactly one IPC channel that can reach the executor, and it takes an id', () => {
  const ipcSource = fs.readFileSync(path.join(MAIN_DIR, 'ipc.js'), 'utf8');
  const channels = [...ipcSource.matchAll(/handleTrusted\('([^']+)'/g)]
    .map(([, name]) => name)
    .filter((name) => name.startsWith('workflows:'));
  assert.deepEqual(channels, ['workflows:execute']);
  assert.match(ipcSource, /const \{ workflowId \} = payload \|\| \{\};/);
});

test('the executor channel is registered through handleTrusted, not raw ipcMain.handle', () => {
  const ipcSource = fs.readFileSync(path.join(MAIN_DIR, 'ipc.js'), 'utf8');
  assert.ok(!/ipcMain\.handle\('workflows:/.test(ipcSource));
  assert.ok(/handleTrusted\('workflows:execute'/.test(ipcSource));
});

test('the preload bridge exposes execute with an id and nothing that carries steps', () => {
  const preload = fs.readFileSync(path.join(APP, 'src', 'preload', 'preload.js'), 'utf8');
  assert.match(preload, /execute:\s*\(workflowId\)\s*=>\s*ipcRenderer\.invoke\('workflows:execute',\s*\{\s*workflowId\s*\}\)/);
  assert.ok(!/workflows:run|workflows:launch|applications:launch/.test(preload));
});
