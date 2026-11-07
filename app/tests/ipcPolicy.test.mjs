// Phase 0 item 7: each window gets a minimal bridge, and main refuses a channel from
// any page that is not listed for it. Run with: node --test app/tests/ipcPolicy.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = (rel) => fs.readFileSync(path.join(HERE, '..', 'src', rel), 'utf8');
const {
  DASHBOARD_PAGES, OVERLAY_PAGES, REVIEW_PAGES, SPLASH_PAGES, CHANNEL_PAGES, allowedPagesFor, isPageAllowed,
} = require('../src/main/ipcPolicy.js');
const { pageNameOf, RENDERER_PAGES } = require('../src/main/senderValidation.js');

const RENDERER_DIR = '/opt/app/resources/app.asar/out/renderer';
const OPTIONS = { rendererDir: RENDERER_DIR, devOrigin: 'http://localhost:5173' };

// ---- page names ------------------------------------------------------------------

test('pageNameOf names the shipped page behind a trusted URL', () => {
  for (const page of RENDERER_PAGES) {
    assert.equal(pageNameOf(`file://${RENDERER_DIR}/${page}`, OPTIONS), page);
    assert.equal(pageNameOf(`file://${RENDERER_DIR}/${page}?x=1#y`, OPTIONS), page);
  }
  assert.equal(pageNameOf('http://localhost:5173/overlay.html', OPTIONS), 'overlay.html');
  assert.equal(pageNameOf('http://localhost:5173/', OPTIONS), 'index.html', 'the dev server root is the legacy dashboard');
  assert.equal(pageNameOf('http://localhost:5173', OPTIONS), 'index.html');
});

test('pageNameOf names nothing for untrusted or unknown pages', () => {
  for (const url of [
    'https://evil.example/overlay.html', 'file:///tmp/overlay.html', `file://${RENDERER_DIR}/evil.html`,
    'http://localhost:5173/evil.html', 'http://localhost:5173.evil.example/overlay.html', '', null, undefined, 'about:blank',
    `file://${RENDERER_DIR}/sub/overlay.html`,
  ]) {
    assert.equal(pageNameOf(url, OPTIONS), null, String(url));
  }
});

// ---- the policy table ----------------------------------------------------------------

function registeredChannels() {
  const ipc = SRC('main/ipc.js');
  return [...ipc.matchAll(/(?:handleTrusted|onTrusted)\('([^']+)'/g)].map((m) => m[1]);
}

const DASHBOARD_ONLY = [
  'approvals:workflow', 'approvals:persona-example', 'workflows:execute', 'shell:open-path', 'clipboard:write-text',
  'backend:factory-reset', 'backend:wipe-privacy', 'backend:clear-persona-learning', 'backend:delete-llm-model',
  'backend:delete-whisper-model', 'backend:delete-voice', 'backend:cancel-job', 'backend:upload-voice-sample',
  'backend:upload-wake-model', 'backend:primary-action', 'backend:fetch-health', 'backend:voice-status:start',
  'applications:list', 'applications:discover', 'applications:confirm', 'applications:remove', 'app:quit', 'app:show',
  'app:get-state', 'app:get-version', 'updates:install', 'updates:download', 'updates:check', 'updates:get-state',
  'updates:set-automatic', 'bug-report:get-config', 'bug-report:prepare', 'bug-report:submit', 'onboarding:accept',
  'onboarding:get-state', 'update-hotkeys', 'hotkeys:get-capabilities', 'overlay:update-status', 'overlay:set-appearance',
  'overlay:get-appearance', 'review:show', 'sidecar:get-logs', 'sidecar:get-status',
];

test('the privileged channels are open to the dashboard only', () => {
  const known = new Set(registeredChannels());
  for (const channel of DASHBOARD_ONLY) {
    assert.ok(known.has(channel), `${channel} is not registered in ipc.js (update this list)`);
    for (const page of [...OVERLAY_PAGES, ...REVIEW_PAGES, ...SPLASH_PAGES]) {
      assert.equal(isPageAllowed(channel, page), false, `${channel} must be closed to ${page}`);
    }
    for (const page of DASHBOARD_PAGES) assert.equal(isPageAllowed(channel, page), true, `${channel} for ${page}`);
  }
});

test('each non-dashboard window is open to exactly its own channels', () => {
  const channels = registeredChannels();
  const opened = (pages) => channels.filter((c) => pages.some((p) => isPageAllowed(c, p))).sort();
  assert.deepEqual(opened(OVERLAY_PAGES), ['overlay:set-ignore-mouse-events']);
  assert.deepEqual(opened(SPLASH_PAGES), ['splash:get-state', 'splash:retry']);
  assert.deepEqual(opened(REVIEW_PAGES), ['backend:request', 'backend:send-draft', 'review:displayed', 'review:hide']);
});

test('an unlisted channel defaults to dashboard-only, never to everyone', () => {
  assert.deepEqual([...allowedPagesFor('a:channel:nobody:wrote:down')], [...DASHBOARD_PAGES]);
  assert.equal(isPageAllowed('a:channel:nobody:wrote:down', 'overlay.html'), false);
  assert.equal(isPageAllowed('backend:request', undefined), false);
  assert.equal(isPageAllowed('backend:request', null), false);
});

test('every entry of the table names a registered channel and a shipped page', () => {
  const known = new Set(registeredChannels());
  for (const [channel, pages] of Object.entries(CHANNEL_PAGES)) {
    assert.ok(known.has(channel), `${channel} is in the policy table but not registered`);
    for (const page of pages) assert.ok(RENDERER_PAGES.has(page), `${channel}: ${page}`);
  }
});

// ---- the preloads themselves ------------------------------------------------------------

// Code only: the preload headers describe what they do NOT carry, in words.
function stripComments(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');
}

function channelsUsedBy(source) {
  return [...source.matchAll(/ipcRenderer\.(?:invoke|send)\(\s*'([^']+)'/g)].map((m) => m[1]);
}
function exposedGlobals(source) {
  return [...source.matchAll(/exposeInMainWorld\(\s*'([^']+)'/g)].map((m) => m[1]);
}

const PRELOADS = {
  'preload.js': { pages: DASHBOARD_PAGES, globals: ['betterFingers'] },
  'preload-overlay.js': { pages: OVERLAY_PAGES, globals: ['betterFingersOverlay'] },
  'preload-review.js': { pages: REVIEW_PAGES, globals: ['betterFingers', 'betterFingersReview'] },
  'preload-splash.js': { pages: SPLASH_PAGES, globals: ['betterFingersSplash'] },
};

test('each preload exposes only its own globals, and only channels its page may call', () => {
  for (const [file, { pages, globals }] of Object.entries(PRELOADS)) {
    const source = SRC(`preload/${file}`);
    assert.deepEqual(exposedGlobals(source).sort(), [...globals].sort(), `${file} globals`);
    const used = channelsUsedBy(source);
    assert.ok(used.length > 0, file);
    for (const channel of used) {
      for (const page of pages) assert.ok(isPageAllowed(channel, page), `${file} calls ${channel}, which ${page} may not`);
    }
  }
});

test('the face overlay preload is display-only', () => {
  const source = stripComments(SRC('preload/preload-overlay.js'));
  assert.deepEqual(channelsUsedBy(source), ['overlay:set-ignore-mouse-events']);
  for (const forbidden of ['backend', 'workflows', 'clipboard', 'shell', 'factory', 'approvals', 'openPath', 'sendDraft', 'betterFingers\'']) {
    assert.ok(!source.includes(forbidden), `${forbidden} must not be reachable from the overlay`);
  }
});

test('the review and splash preloads do not carry the dashboard\'s powers', () => {
  const review = stripComments(SRC('preload/preload-review.js'));
  const splash = stripComments(SRC('preload/preload-splash.js'));
  for (const forbidden of ['factoryReset', 'wipePrivacyData', 'workflows', 'openPath', 'writeClipboardText', 'approveWorkflow',
    'addPersonaExample', 'applications', 'updates', 'quitApp', 'updateHotkeys', 'uploadVoiceSample']) {
    assert.ok(!review.includes(forbidden), `review: ${forbidden}`);
    assert.ok(!splash.includes(forbidden), `splash: ${forbidden}`);
  }
  assert.deepEqual(channelsUsedBy(splash).sort(), ['splash:get-state', 'splash:retry']);
});

test('the dashboard preload no longer exposes the other windows\' bridges', () => {
  const dashboard = SRC('preload/preload.js');
  for (const global of ['betterFingersOverlay', 'betterFingersSplash', 'betterFingersReview']) {
    assert.ok(!dashboard.includes(global), global);
  }
});

test('each window is created with its own preload', () => {
  const windows = SRC('main/windows.js');
  const kinds = [...windows.matchAll(/(\w+Window) = new BrowserWindow\(\{[\s\S]*?preload: resolvePreloadPath\('(\w+)'\)/g)]
    .map((m) => [m[1], m[2]]);
  assert.deepEqual(kinds, [['mainWindow', 'dashboard'], ['splashWindow', 'splash'], ['overlayWindow', 'overlay'], ['reviewWindow', 'review']]);
  assert.ok(!/preload: resolvePreloadPath\(\)/.test(windows), 'no window may fall back to the default preload');
});

test('every preload is a build input, so the packaged app ships the file windows.js asks for', () => {
  const config = require('../electron.vite.config.js');
  const inputs = (typeof config === 'function' ? config({}) : config).preload.build.rollupOptions.input;
  const built = Object.values(inputs).map((file) => path.basename(file)).sort();
  assert.deepEqual(built, Object.values(PRELOADS).length ? Object.keys(PRELOADS).sort() : []);
  for (const key of Object.keys(inputs)) assert.ok(fs.existsSync(inputs[key]), key);
});

// ---- ipc.js end to end, with a fake electron ---------------------------------------------

function loadIpc() {
  const Module = require('node:module');
  const originalLoad = Module._load;
  const handlers = new Map();
  const listeners = new Map();
  const electron = {
    app: { getPath: () => '/tmp/bf-userdata', getVersion: () => '0.0.0' },
    clipboard: { writeText() {} },
    dialog: { showMessageBox: async () => ({ response: 1 }) },
    ipcMain: {
      handle: (channel, fn) => handlers.set(channel, fn),
      on: (channel, fn) => listeners.set(channel, fn),
    },
    session: { defaultSession: {} },
    shell: { openPath: async () => '' , openExternal: async () => {} },
    webContents: {},
    Notification: class { static isSupported() { return false; } },
  };
  Module._load = function patched(request, parent, isMain) {
    if (request === 'electron') return electron;
    return originalLoad.call(this, request, parent, isMain);
  };
  const modulePath = require.resolve('../src/main/ipc.js');
  delete require.cache[modulePath];
  const ipc = require(modulePath);
  Module._load = originalLoad;
  return { ipc, handlers, listeners };
}

function eventFor(page, { main = true, dir = path.join(HERE, '..', 'src', 'renderer') } = {}) {
  const frame = { url: `file://${dir}/${page}` };
  return { senderFrame: frame, sender: { mainFrame: main ? frame : { url: 'other' } } };
}

test('ipc.js refuses a channel from a page it is not open to, and runs it for the dashboard', async () => {
  const { ipc, handlers } = loadIpc();
  ipc.registerIpc({ getMainWindow: () => null, getApprovalKey: () => '00'.repeat(32) });
  assert.ok(handlers.size > 20);

  const clipboardWrite = handlers.get('clipboard:write-text');
  assert.deepEqual(await clipboardWrite(eventFor('overlay.html'), 'x'), { ok: false, error: 'untrusted_sender' });
  assert.deepEqual(await clipboardWrite(eventFor('review-overlay.html'), 'x'), { ok: false, error: 'untrusted_sender' });
  assert.deepEqual(await clipboardWrite(eventFor('splash.html'), 'x'), { ok: false, error: 'untrusted_sender' });
  assert.equal(await clipboardWrite(eventFor('signal-desk.html'), 'x'), true);

  for (const channel of ['approvals:workflow', 'workflows:execute', 'backend:factory-reset', 'shell:open-path', 'backend:primary-action']) {
    for (const page of ['overlay.html', 'review-overlay.html', 'splash.html']) {
      assert.deepEqual(await handlers.get(channel)(eventFor(page), {}), { ok: false, error: 'untrusted_sender' }, `${channel} from ${page}`);
    }
  }
});

test('ipc.js refuses a subframe and a foreign page even on an open channel', async () => {
  const { ipc, handlers } = loadIpc();
  ipc.registerIpc({ getMainWindow: () => null, getApprovalKey: () => '00'.repeat(32) });
  const retry = handlers.get('splash:get-state');
  assert.deepEqual(await retry(eventFor('splash.html', { main: false })), { ok: false, error: 'untrusted_sender' });
  assert.deepEqual(await retry({ senderFrame: { url: 'https://evil.example/splash.html' }, sender: {} }), { ok: false, error: 'untrusted_sender' });
  assert.deepEqual(await retry({ senderFrame: { url: '' }, sender: {} }), { ok: false, error: 'untrusted_sender' });
  assert.notDeepEqual(await retry(eventFor('splash.html')), { ok: false, error: 'untrusted_sender' });
});
