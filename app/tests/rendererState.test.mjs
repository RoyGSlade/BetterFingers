// Factory reset and Chromium-owned renderer state (src/main/rendererState.js).
//
// Reproduced in the packaged app (F1): a factory reset returned HTTP 200 /
// verified:true while the renderer's Local Storage (first-run + quick-setup
// flags, theme prefs, and the legacy consent flag) survived the reset AND the
// relaunch, because Electron's userData (%APPDATA%\betterfingers-electron) is a
// different folder from the backend's data root and nothing swept it.
//
// Every test works in a throwaway temp directory with injected fakes: no
// Electron runtime, no real userData, no network.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const rendererState = require('../src/main/rendererState.js');
const {
  RESET_PENDING_MARKER,
  CHROMIUM_STORAGE_ENTRIES,
  schedulePurge,
  pendingEntries,
  purgePendingReset,
  clearLiveRendererState,
  clearRendererState,
  finishFactoryReset,
} = rendererState;

function tempDir(t, prefix = 'bf-rstate-') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

function seedChromium(userData) {
  for (const name of CHROMIUM_STORAGE_ENTRIES) {
    fs.mkdirSync(path.join(userData, name), { recursive: true });
    fs.writeFileSync(path.join(userData, name, 'data'), `chromium ${name}`);
  }
}

// What else lives in Electron's userData and must survive a purge untouched.
const NOT_OURS_TO_DELETE = ['Preferences', 'Local State', 'overlay-position.json', 'sidecar_backend_raw.log'];

function seedBystanders(userData) {
  for (const name of NOT_OURS_TO_DELETE) fs.writeFileSync(path.join(userData, name), `keep ${name}`);
  fs.mkdirSync(path.join(userData, 'models'), { recursive: true });
  fs.writeFileSync(path.join(userData, 'models', 'model.gguf'), 'weights');
  fs.writeFileSync(path.join(userData, 'onboarding.json'), '{}');
}

const quiet = { warn() {} };

// --- the list ---------------------------------------------------------------------

test('the purge list is exact top-level Chromium names, never a path, never a glob', () => {
  assert.ok(CHROMIUM_STORAGE_ENTRIES.includes('Local Storage'), 'the legacy consent flag lives here');
  assert.ok(CHROMIUM_STORAGE_ENTRIES.includes('Session Storage'));
  for (const name of CHROMIUM_STORAGE_ENTRIES) {
    assert.ok(name && !/[\\/*?]/.test(name), `${JSON.stringify(name)} must be a plain top-level name`);
    assert.notEqual(name, '..');
    assert.notEqual(name, '.');
  }
  // BetterFingers's own stores must never be on a Chromium purge list.
  for (const ours of ['models', 'tts', 'runtimes', 'profiles', 'recordings', 'voices', 'onboarding.json',
    'overlay-position.json', 'overlay-appearance.json', 'sidecar_backend_raw.log', 'history.db', 'application_registry.json']) {
    assert.ok(!CHROMIUM_STORAGE_ENTRIES.includes(ours), `${ours} is BetterFingers data, not Chromium state`);
  }
  assert.ok(Object.isFrozen(CHROMIUM_STORAGE_ENTRIES));
});

// --- marker ------------------------------------------------------------------------

test('schedulePurge writes only the marker and reports success', (t) => {
  const userData = tempDir(t);
  const result = schedulePurge({ userDataDir: userData, now: () => new Date('2026-10-07T12:00:00.000Z') });
  assert.deepEqual(result, { ok: true });
  assert.deepEqual(fs.readdirSync(userData), [RESET_PENDING_MARKER]);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(userData, RESET_PENDING_MARKER), 'utf8')),
    { requested_at: '2026-10-07T12:00:00.000Z' });
});

test('schedulePurge reports a failed marker write instead of pretending', () => {
  const failing = { mkdirSync() {}, writeFileSync() { throw new Error('EACCES: denied'); } };
  const result = schedulePurge({ userDataDir: 'X:\\nowhere', fsImpl: failing });
  assert.equal(result.ok, false);
  assert.match(result.error, /EACCES/);
  assert.equal(schedulePurge({ userDataDir: '' }).ok, false);
});

// --- purge at next launch ---------------------------------------------------------

test('without a marker nothing is deleted, however much Chromium state exists', (t) => {
  const userData = tempDir(t);
  seedChromium(userData);
  seedBystanders(userData);
  const before = fs.readdirSync(userData).sort();
  const result = purgePendingReset({ userDataDir: userData, log: quiet });
  assert.equal(result.pending, false);
  assert.deepEqual(result.removed, []);
  assert.deepEqual(fs.readdirSync(userData).sort(), before, 'a normal launch must never wipe the renderer state');
});

test('with a marker, every listed entry goes, the marker goes, and nothing else is touched', (t) => {
  const userData = tempDir(t);
  seedChromium(userData);
  seedBystanders(userData);
  schedulePurge({ userDataDir: userData });

  const result = purgePendingReset({ userDataDir: userData, log: quiet });

  assert.equal(result.pending, true);
  assert.deepEqual(result.failed, []);
  assert.deepEqual([...result.removed].sort(), [...CHROMIUM_STORAGE_ENTRIES].sort());
  assert.deepEqual(fs.readdirSync(userData).sort(),
    [...NOT_OURS_TO_DELETE, 'models', 'onboarding.json'].sort());
  assert.equal(fs.readFileSync(path.join(userData, 'models', 'model.gguf'), 'utf8'), 'weights');
});

test('a second launch after a completed purge does nothing', (t) => {
  const userData = tempDir(t);
  seedChromium(userData);
  schedulePurge({ userDataDir: userData });
  purgePendingReset({ userDataDir: userData, log: quiet });
  fs.mkdirSync(path.join(userData, 'Local Storage'));
  fs.writeFileSync(path.join(userData, 'Local Storage', 'fresh'), 'written after the purge');
  const again = purgePendingReset({ userDataDir: userData, log: quiet });
  assert.equal(again.pending, false);
  assert.ok(fs.existsSync(path.join(userData, 'Local Storage', 'fresh')));
});

test('a purge that cannot remove something keeps the marker so the next launch retries, and says so', (t) => {
  const userData = tempDir(t);
  seedChromium(userData);
  schedulePurge({ userDataDir: userData });
  const stubborn = {
    ...fs,
    rmSync(target, options) {
      if (path.basename(target) === 'Local Storage') throw new Error('EBUSY: resource busy or locked');
      return fs.rmSync(target, options);
    },
  };
  const warnings = [];
  const result = purgePendingReset({ userDataDir: userData, fsImpl: stubborn, log: { warn: (m) => warnings.push(m) } });
  assert.equal(result.pending, true);
  assert.deepEqual(result.failed.map((f) => f.name), ['Local Storage']);
  assert.match(result.failed[0].error, /EBUSY/);
  assert.ok(fs.existsSync(path.join(userData, RESET_PENDING_MARKER)), 'marker stays so the purge is retried');
  assert.ok(fs.existsSync(path.join(userData, 'Local Storage')));
  assert.equal(warnings.length, 1);
  assert.ok(!fs.existsSync(path.join(userData, 'Session Storage')), 'the others still went');
});

test('a link is removed as a link and never followed out of userData', (t) => {
  const userData = tempDir(t);
  const outside = tempDir(t, 'bf-rstate-outside-');
  fs.writeFileSync(path.join(outside, 'precious.txt'), 'not chromium state');
  try {
    fs.symlinkSync(outside, path.join(userData, 'Cache'), 'junction');
  } catch (error) {
    t.skip(`cannot create a directory link here: ${error.code}`);
    return;
  }
  schedulePurge({ userDataDir: userData });
  const result = purgePendingReset({ userDataDir: userData, log: quiet });
  assert.deepEqual(result.removed, ['Cache']);
  assert.ok(!fs.existsSync(path.join(userData, 'Cache')));
  assert.equal(fs.readFileSync(path.join(outside, 'precious.txt'), 'utf8'), 'not chromium state');
});

test('pendingEntries names exactly the listed entries that exist', (t) => {
  const userData = tempDir(t);
  fs.mkdirSync(path.join(userData, 'Local Storage'));
  fs.mkdirSync(path.join(userData, 'GPUCache'));
  fs.writeFileSync(path.join(userData, 'Preferences'), '{}');
  assert.deepEqual(pendingEntries({ userDataDir: userData }).sort(), ['GPUCache', 'Local Storage']);
  assert.deepEqual(pendingEntries({ userDataDir: '' }), []);
});

// --- live clear ---------------------------------------------------------------------

function fakeSession({ failOn = [] } = {}) {
  const calls = [];
  const make = (name) => async (...args) => {
    calls.push([name, ...args]);
    if (failOn.includes(name)) throw new Error(`${name} exploded`);
  };
  return {
    calls,
    clearStorageData: make('clearStorageData'),
    clearCache: make('clearCache'),
    clearCodeCaches: make('clearCodeCaches'),
    flushStorageData: () => calls.push(['flushStorageData']),
  };
}

function fakePage(url, counts = [0, 0], { destroyed = false, throws = false } = {}) {
  const page = {
    scripts: [],
    isDestroyed: () => destroyed,
    getURL: () => url,
    async executeJavaScript(code) {
      page.scripts.push(code);
      if (throws) throw new Error('frame disposed');
      return counts;
    },
  };
  return page;
}

const webContentsOf = (...pages) => ({ getAllWebContents: () => pages });

test('the live clear empties the session AND every open app page, then reads it back', async () => {
  const session = fakeSession();
  const dashboard = fakePage('file:///app/out/renderer/signal-desk.html');
  const overlay = fakePage('file:///app/out/renderer/overlay.html');
  const devtools = fakePage('devtools://devtools/bundled/inspector.html');
  const gone = fakePage('file:///app/out/renderer/splash.html', [0, 0], { destroyed: true });

  const result = await clearLiveRendererState({ session, webContents: webContentsOf(dashboard, overlay, devtools, gone) });

  assert.equal(result.ok, true, JSON.stringify(result));
  assert.deepEqual(session.calls.map((c) => c[0]), ['clearStorageData', 'clearCache', 'clearCodeCaches', 'flushStorageData']);
  assert.equal(result.pagesChecked, 2);
  for (const page of [dashboard, overlay]) {
    assert.equal(page.scripts.length, 1);
    assert.match(page.scripts[0], /localStorage\.clear\(\)/);
    assert.match(page.scripts[0], /sessionStorage\.clear\(\)/, 'sessionStorage is not covered by clearStorageData');
  }
  assert.equal(devtools.scripts.length, 0, 'only the app\'s own file: pages are scripted');
  assert.equal(gone.scripts.length, 0);
});

test('a page that still holds keys after the clear is a failure, not a pass', async () => {
  const result = await clearLiveRendererState({
    session: fakeSession(),
    webContents: webContentsOf(fakePage('file:///a/signal-desk.html', [2, 0])),
  });
  assert.equal(result.ok, false);
  assert.equal(result.pagesNotEmpty, 1);
  assert.match(result.errors.join(), /still hold stored keys/);
});

test('storage that cannot be read back (a throwing page, or -1) is not reported clean', async () => {
  const unreadable = await clearLiveRendererState({
    session: fakeSession(),
    webContents: webContentsOf(fakePage('file:///a/signal-desk.html', [-1, -1])),
  });
  assert.equal(unreadable.ok, false);
  const throwing = await clearLiveRendererState({
    session: fakeSession(),
    webContents: webContentsOf(fakePage('file:///a/signal-desk.html', [0, 0], { throws: true })),
  });
  assert.equal(throwing.ok, false);
  assert.match(throwing.errors.join(), /frame disposed/);
});

test('one failing clear step is reported and the remaining steps still run', async () => {
  const session = fakeSession({ failOn: ['clearStorageData'] });
  const result = await clearLiveRendererState({ session, webContents: webContentsOf(fakePage('file:///a/x.html')) });
  assert.equal(result.ok, false);
  assert.match(result.errors.join(), /storage-data: clearStorageData exploded/);
  assert.deepEqual(session.calls.map((c) => c[0]), ['clearStorageData', 'clearCache', 'clearCodeCaches', 'flushStorageData']);
});

test('no session at all is a failure', async () => {
  const result = await clearLiveRendererState({ session: null, webContents: webContentsOf() });
  assert.equal(result.ok, false);
});

// --- the combined renderer-state clear ----------------------------------------------

test('clearRendererState is ok only when the live clear AND the deferred purge are both in place', async (t) => {
  const userData = tempDir(t);
  seedChromium(userData);
  const ok = await clearRendererState({
    session: fakeSession(), webContents: webContentsOf(fakePage('file:///a/x.html')), userDataDir: userData,
  });
  assert.equal(ok.ok, true, JSON.stringify(ok));
  assert.equal(ok.purge_scheduled, true);
  assert.ok(fs.existsSync(path.join(userData, RESET_PENDING_MARKER)));
  assert.deepEqual([...ok.pending_until_restart].sort(), [...CHROMIUM_STORAGE_ENTRIES].sort(),
    'the files that cannot be deleted while Chromium runs are named, not hidden');

  const noMarker = await clearRendererState({
    session: fakeSession(), webContents: webContentsOf(), userDataDir: '',
  });
  assert.equal(noMarker.ok, false);
  assert.equal(noMarker.purge_scheduled, false);
  assert.match(noMarker.errors.join(), /purge-marker/);

  const noLive = await clearRendererState({
    session: fakeSession({ failOn: ['clearCache'] }), webContents: webContentsOf(), userDataDir: userData,
  });
  assert.equal(noLive.ok, false);
});

// --- folding into the backend's response ---------------------------------------------

function deps(t, overrides = {}) {
  const userData = tempDir(t);
  return {
    session: fakeSession(), webContents: webContentsOf(fakePage('file:///a/signal-desk.html')), userDataDir: userData,
    ...overrides,
  };
}

const resetBody = (extra = {}) => ({ ok: true, verified: true, residual_files: [], wipe: { ok: true }, reset: { ok: true, failed: [] },
  message: 'This install was reset to a fresh state.', ...extra });

test('a successful reset gains a renderer_state block and keeps the backend verdict', async (t) => {
  const d = deps(t);
  const out = await finishFactoryReset({ ok: true, status: 200, body: resetBody() }, d);
  assert.equal(out.ok, true);
  assert.equal(out.status, 200);
  assert.equal(out.body.ok, true);
  assert.equal(out.body.verified, true);
  assert.equal(out.body.renderer_state.ok, true);
  assert.equal(out.body.renderer_state.purge_scheduled, true);
  assert.ok(d.session.calls.some((c) => c[0] === 'clearStorageData'));
});

test('a reset that could not clear the renderer state is neither ok nor verified, whatever the backend said', async (t) => {
  const d = deps(t, { session: fakeSession({ failOn: ['clearStorageData'] }) });
  const out = await finishFactoryReset({ ok: true, status: 200, body: resetBody() }, d);
  assert.equal(out.ok, false);
  assert.equal(out.status, 500, 'the renderer surfaces a non-ok status as a failed reset');
  assert.equal(out.body.ok, false);
  assert.equal(out.body.verified, false);
  assert.equal(out.body.renderer_state.ok, false);
  assert.match(out.body.message, /could not be cleared/);
  assert.match(out.body.message, /clearStorageData exploded/);
  assert.match(out.body.message, /Nothing is being claimed that did not happen/);
});

test('a backend verdict of failure stays a failure and still gets its renderer state cleared', async (t) => {
  const d = deps(t);
  const failing = { ok: false, status: 500, body: resetBody({ ok: false, verified: false, residual_files: ['x'], reset: { ok: false, failed: ['drafts'] } }) };
  const out = await finishFactoryReset(failing, d);
  assert.equal(out.ok, false);
  assert.equal(out.status, 500);
  assert.equal(out.body.verified, false);
  assert.deepEqual(out.body.residual_files, ['x']);
  assert.equal(out.body.renderer_state.ok, true);
  assert.ok(d.session.calls.some((c) => c[0] === 'clearStorageData'), 'a retry after a partial reset must not leave the flags behind');
});

test('responses where the backend deleted nothing are returned untouched and clear nothing', async (t) => {
  const refusals = [
    { ok: false, status: 0, error: 'timeout' },
    { ok: false, status: 400, body: { ok: false, error: 'confirmation_required' } },
    { ok: false, status: 409, body: { ok: false, error: 'pipeline_did_not_quiesce', wipe: { ok: false }, message: 'Nothing was deleted.' } },
    { ok: false, status: 503, body: { ok: false, error: 'output_did_not_quiesce', wipe: { ok: false } } },
    { ok: false, status: 500, body: { detail: 'Internal Server Error' } },
    { ok: false, status: 500, error: 'boom' },
    null,
    undefined,
  ];
  for (const refusal of refusals) {
    const d = deps(t);
    const out = await finishFactoryReset(refusal, d);
    assert.strictEqual(out, refusal);
    assert.deepEqual(d.session.calls, [], `nothing may be cleared for ${JSON.stringify(refusal)}`);
    assert.deepEqual(fs.readdirSync(d.userDataDir), [], 'no purge marker for a reset that did not run');
  }
});

test('an exception inside the clear is reported as a failed reset, never thrown into the IPC handler', async (t) => {
  const d = deps(t, { webContents: { getAllWebContents() { throw new Error('webContents unavailable'); } } });
  const out = await finishFactoryReset({ ok: true, status: 200, body: resetBody() }, d);
  assert.equal(out.ok, false);
  assert.equal(out.body.verified, false);
});

// --- wiring (source-level, in the repo's existing style) ------------------------------

const appRoot = path.resolve(import.meta.dirname, '..');
const read = (...parts) => fs.readFileSync(path.join(appRoot, ...parts), 'utf8');

test('the factory-reset IPC handler runs the renderer-state clear before answering', () => {
  const ipc = read('src', 'main', 'ipc.js');
  const handler = ipc.match(/handleTrusted\('backend:factory-reset'[\s\S]*?\n  \}\);/)?.[0] || '';
  assert.ok(handler, 'handler must be extractable');
  assert.match(ipc, /require\('\.\/rendererState'\)/);
  const order = [
    handler.indexOf('broker().factoryReset('),
    handler.indexOf('finishFactoryReset('),
    handler.indexOf('onConsentChanged'),
    handler.lastIndexOf('return '),
  ];
  assert.ok(order.every((i) => i >= 0), `all four steps must be present: ${order}`);
  assert.deepEqual([...order].sort((a, b) => a - b), order, 'backend reset, then renderer state, then consent refresh, then return');
  assert.match(handler, /session: session\.defaultSession/);
  assert.match(handler, /webContents/);
  assert.match(handler, /app\.getPath\('userData'\)/);
});

test('main purges a pending reset before the app is ready, and only in the instance that owns the lock', () => {
  const main = read('src', 'main', 'main.js');
  assert.match(main, /require\('\.\/rendererState'\)/);
  const lockBranch = main.slice(main.indexOf('requestSingleInstanceLock()'));
  const purge = lockBranch.indexOf('purgePendingReset(');
  const ready = lockBranch.indexOf('app.whenReady()');
  assert.ok(purge > 0 && ready > 0 && purge < ready, 'purge must run before app.whenReady()');
  assert.match(lockBranch.slice(purge, purge + 120), /app\.getPath\('userData'\)/);
  // A second instance that fails the lock must never touch the first one's files.
  assert.ok(lockBranch.indexOf('app.quit()') < purge);
});

test('the module is in the main bundle inputs (the Wave 1 silent no-window failure)', () => {
  const config = read('electron.vite.config.js');
  assert.match(config, /rendererState:\s*resolve\(__dirname, 'src\/main\/rendererState\.js'\)/);
});

// --- the raw sidecar log stays gone after a reset ----------------------------------------

test('deletionRan is true only for a response that carries the backend\'s reset report', () => {
  const { deletionRan } = rendererState;
  assert.equal(deletionRan({ ok: true, status: 200, body: resetBody() }), true);
  assert.equal(deletionRan({ ok: false, status: 500, body: resetBody({ ok: false }) }), true);
  for (const nothing of [
    null, undefined, {}, { ok: false, status: 0, error: 'timeout' },
    { ok: false, status: 409, body: { ok: false, error: 'pipeline_did_not_quiesce', wipe: {} } },
    { ok: false, status: 400, body: { error: 'confirmation_required' } },
    { ok: true, status: 200, body: 'not json' },
    { ok: true, status: 200, body: { reset: 'nope' } },
  ]) {
    assert.equal(deletionRan(nothing), false, JSON.stringify(nothing));
  }
});

test('the factory-reset handler switches raw-log writing off before the request and back on only if nothing was deleted', () => {
  const ipc = read('src', 'main', 'ipc.js');
  const handler = ipc.match(/handleTrusted\('backend:factory-reset'[\s\S]*?\n  \}\);/)?.[0] || '';
  assert.match(ipc, /onFactoryResetStart, onFactoryResetEnd/);
  const start = handler.indexOf('onFactoryResetStart?.()');
  const request = handler.indexOf('broker().factoryReset(');
  const end = handler.indexOf('onFactoryResetEnd?.({ deleted })');
  assert.ok(start >= 0 && request > start, 'logging must be switched off before the backend deletes the log');
  assert.ok(end > request);
  assert.match(handler, /deleted = deletionRan\(result\)/);
  assert.match(handler, /finally \{\s*onFactoryResetEnd/, 'a throw must still restore logging');
});

test('main wires the reset hooks to the sidecar', () => {
  const main = read('src', 'main', 'main.js');
  assert.match(main, /onFactoryResetStart: \(\) => sidecar\?\.setRawLogEnabled\?\.\(false\)/);
  assert.match(main, /onFactoryResetEnd: \(\{ deleted \} = \{\}\) => \{\s*if \(!deleted\) sidecar\?\.setRawLogEnabled\?\.\(true\);/);
});

test('the Settings success message names what is pending until restart instead of claiming an empty folder', () => {
  const settings = read('src', 'renderer', 'features', 'settingsWorkspace.js');
  const success = settings.match(/if \(result\?\.ok\) \{[\s\S]*?\} else \{/)?.[0] || '';
  assert.match(success, /result\?\.renderer_state\?\.pending_until_restart/);
  assert.match(success, /removed when it restarts/);
  assert.match(success, /Restart BetterFingers to begin from first run\./, 'the existing wording stays');
});
