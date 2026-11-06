// Unit tests for the main-process backend proxy's route/method validation
// (Phase 3c, tightened to an exact route table + typed destructive ops).
// Pure logic — no Electron, no network.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

const require = createRequire(import.meta.url);
const proxy = require('../src/main/backendProxy.js');

test('accepts known backend routes with the right method', () => {
  const allowed = [
    ['GET', '/runtime/status'],
    ['GET', '/drafts'],
    ['GET', '/drafts/latest'],
    ['GET', '/settings/profiles'],
    ['GET', '/settings/profiles/My%20Profile'],
    ['GET', '/tts/voices'],
    ['GET', '/models/llm/qwen2.5-3b/download-state'],
    ['GET', '/wake/qwen/capability'],
    ['POST', '/drafts/1/accept'],
    ['POST', '/models/llm/select'],
    ['POST', '/personas/lint'],
    ['POST', '/personas/refine'],
    ['POST', '/personas/draft'],
    ['POST', '/recordings/abc/retranscribe'],
    ['POST', '/wake/phrase/preflight'],
    ['DELETE', '/recordings/abc'],
    ['DELETE', '/macros/hello'],
    ['GET', '/message-rescue/context'],
    ['GET', '/message-rescue/generate/job-1'],
    ['POST', '/message-rescue/context/selection'],
    ['POST', '/message-rescue/context/manual'],
    ['POST', '/message-rescue/generate'],
    ['POST', '/message-rescue/generate/job-1/cancel'],
    ['DELETE', '/message-rescue/context'],
    ['GET', '/personas/Assistant/examples'],
  ];
  for (const [method, path] of allowed) {
    assert.equal(proxy._validateRequest(method, path), null, `${method} ${path} should be allowed`);
  }
});

test('persona example id segment must be a single param, not a subpath', () => {
  assert.notEqual(proxy._validateRequest('DELETE', '/personas/Assistant/examples/abc/extra'), null);
  assert.notEqual(proxy._validateRequest('GET', '/personas/Assistant/examples/abc123'), null);
});

test('rejects an allowed route with the wrong method', () => {
  assert.notEqual(proxy._validateRequest('DELETE', '/drafts/latest'), null);
  assert.notEqual(proxy._validateRequest('POST', '/runtime/status'), null);
  assert.notEqual(proxy._validateRequest('GET', '/models/llm/select'), null);
  assert.notEqual(proxy._validateRequest('DELETE', '/message-rescue/generate/job-1'), null);
  assert.notEqual(proxy._validateRequest('GET', '/message-rescue/generate'), null);
  // Persona-example routes: DELETE (single/all) is not GET/POST, and there is
  // no DELETE-single-example without an id.
  assert.notEqual(proxy._validateRequest('PUT', '/personas/Assistant/examples'), null);
  assert.notEqual(proxy._validateRequest('DELETE', '/personas/Assistant/examples/abc123/extra'), null);
});

test('message-rescue generate id segment must be a single param, not a subpath', () => {
  assert.notEqual(proxy._validateRequest('GET', '/message-rescue/generate/job-1/extra'), null);
  assert.notEqual(proxy._validateRequest('POST', '/message-rescue/generate/job-1/cancel/extra'), null);
});

test('route match requires a path boundary, not a prefix', () => {
  // Old startsWith matching accepted these; the exact table must not.
  assert.notEqual(proxy._validateRequest('GET', '/draftsX'), null);
  assert.notEqual(proxy._validateRequest('GET', '/privacyX'), null);
  assert.notEqual(proxy._validateRequest('GET', '/healthcheck'), null);
  assert.notEqual(proxy._validateRequest('DELETE', '/recordings/a/b'), null);
});

test('wake enrollment transport exposes preflight and capability only', () => {
  assert.equal(proxy._validateRequest('POST', '/wake/phrase/preflight'), null);
  assert.equal(proxy._validateRequest('GET', '/wake/qwen/capability'), null);

  assert.notEqual(proxy._validateRequest('GET', '/wake/phrase/preflight'), null);
  assert.notEqual(proxy._validateRequest('POST', '/wake/qwen/capability'), null);
  for (const path of [
    '/wake/phrase/preflight/extra',
    '/wake/qwen/capability/extra',
    '/wake/qwen/download',
    '/wake/qwen/generate',
    '/wake/qwen/tts',
  ]) {
    assert.notEqual(proxy._validateRequest('GET', path), null, `GET ${path} should be refused`);
    assert.notEqual(proxy._validateRequest('POST', path), null, `POST ${path} should be refused`);
  }

  assert.deepEqual(
    proxy.ROUTE_ALLOWLIST.GET.filter((path) => path.startsWith('/wake/qwen/')),
    ['/wake/qwen/capability'],
  );
  assert.deepEqual(
    proxy.ROUTE_ALLOWLIST.POST.filter((path) => path.startsWith('/wake/phrase/')),
    ['/wake/phrase/preflight'],
  );
});

test('renderer wake helpers send the exact bounded request shapes', async (t) => {
  const source = readFileSync(new URL('../src/renderer/api/backend.js', import.meta.url), 'utf8');
  const api = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
  const calls = [];
  globalThis.window = {
    betterFingers: {
      backendRequest: async (...args) => {
        calls.push(args);
        return { ok: true, status: 200, body: { accepted: true } };
      },
    },
  };
  t.after(() => { delete globalThis.window; });

  await api.preflightWakePhrase(
    'hey betterfingers',
    ['launch rocket league'],
    ['better features'],
  );
  await api.fetchWakeQwenCapability();

  assert.deepEqual(calls, [
    [
      'POST',
      '/wake/phrase/preflight',
      {
        phrase: 'hey betterfingers',
        command_vocabulary: ['launch rocket league'],
        common_vocabulary: ['better features'],
      },
      5000,
    ],
    ['GET', '/wake/qwen/capability', undefined, 2500],
  ]);
});

test('destructive routes are refused on the generic channel', () => {
  assert.notEqual(proxy._validateRequest('POST', '/privacy/wipe'), null);
  assert.notEqual(proxy._validateRequest('POST', '/drafts/1/send'), null);
  assert.notEqual(proxy._validateRequest('POST', '/jobs/j1/cancel'), null);
  assert.notEqual(proxy._validateRequest('DELETE', '/models/llm/some-model'), null);
  assert.notEqual(proxy._validateRequest('DELETE', '/models/whisper/base'), null);
  assert.notEqual(proxy._validateRequest('DELETE', '/tts/voices/v1'), null);
});

test('selected-text rewrite stays main-process hotkey-only', () => {
  assert.notEqual(proxy._validateRequest('POST', '/runtime/rewrite-selection'), null);
});

test('route families unused by the renderer are gone', () => {
  for (const path of ['/ocr/extract', '/graph/load', '/mcp/status', '/intent/state',
                       '/llm/process', '/hardware/tier', '/project/export', '/transcribe',
                       '/voice-commands/execute', '/profile']) {
    assert.notEqual(proxy._validateRequest('GET', path), null, `GET ${path} should be refused`);
    assert.notEqual(proxy._validateRequest('POST', path), null, `POST ${path} should be refused`);
  }
});

test('accepts a query string on an allowed route', () => {
  assert.equal(proxy._validateRequest('GET', '/doctor?refresh_audio=true'), null);
  assert.equal(proxy._validateRequest('GET', '/history/search?q=hello&limit=10'), null);
});

test('rejects path traversal', () => {
  assert.notEqual(proxy._validateRequest('GET', '/drafts/../../etc/passwd'), null);
});

test('rejects an absolute URL with a scheme', () => {
  assert.notEqual(proxy._validateRequest('GET', 'http://evil.example/steal'), null);
  assert.notEqual(proxy._validateRequest('GET', '/drafts?u=http://evil.example'), null);
});

test('rejects a backslash', () => {
  assert.notEqual(proxy._validateRequest('GET', '/drafts\\..\\x'), null);
});

test('rejects protocol-relative and non-absolute paths', () => {
  assert.notEqual(proxy._validateRequest('GET', '//evil.example/x'), null);
  assert.notEqual(proxy._validateRequest('GET', 'drafts'), null);
  assert.notEqual(proxy._validateRequest('GET', ''), null);
});

test('rejects a route outside the allowlist', () => {
  assert.notEqual(proxy._validateRequest('GET', '/secret-admin'), null);
  assert.notEqual(proxy._validateRequest('GET', '/etc/passwd'), null);
});

test('rejects an over-long path', () => {
  assert.notEqual(proxy._validateRequest('GET', '/drafts/' + 'a'.repeat(2000)), null);
});

test('rejects a param segment containing a slash or empty segment', () => {
  assert.notEqual(proxy._validateRequest('DELETE', '/macros//'), null);
  assert.notEqual(proxy._validateRequest('DELETE', '/macros/'), null);
  assert.notEqual(proxy._validateRequest('POST', '/drafts//accept'), null);
});

test('method allowlist is exactly GET/POST/DELETE', () => {
  assert.ok(proxy.ALLOWED_METHODS.has('GET'));
  assert.ok(proxy.ALLOWED_METHODS.has('POST'));
  assert.ok(proxy.ALLOWED_METHODS.has('DELETE'));
  assert.ok(!proxy.ALLOWED_METHODS.has('PUT'));
  assert.ok(!proxy.ALLOWED_METHODS.has('CONNECT'));
  assert.ok(!proxy.ALLOWED_METHODS.has('TRACE'));
});

test('typed operations validate their payloads before any request', async () => {
  // Invalid params fail with status 0 and never hit the network (no origin up).
  assert.equal((await proxy.sendDraft({ id: 'x' })).status, 0);
  assert.equal((await proxy.sendDraft({ id: 1, action: 'format_disk' })).status, 0);
  assert.equal((await proxy.cancelJob({ jobId: 'a/b' })).status, 0);
  assert.equal((await proxy.deleteLlmModel({ modelId: '../x', confirm: true })).status, 0);
  assert.equal((await proxy.deleteVoice({ voiceId: '', confirm: true })).status, 0);
});

test('GET /runtime/audio-devices is reachable, not just its POST refresh sibling', () => {
  // These were asymmetric: POST .../refresh was allowed while the plain GET
  // was not, so the renderer could ask the backend to rescan devices and then
  // never read the result. The input-device picker could not be populated.
  assert.equal(proxy.isRouteAllowed?.('GET', '/runtime/audio-devices') ?? true, true);
  const { ROUTE_ALLOWLIST } = proxy;
  assert.ok(
    ROUTE_ALLOWLIST.GET.includes('/runtime/audio-devices'),
    'GET /runtime/audio-devices missing from the allowlist',
  );
  assert.ok(ROUTE_ALLOWLIST.POST.includes('/runtime/audio-devices/refresh'));
});

test('destructive typed operations require confirm: true; example-changing wipes are not here at all', async () => {
  // Round 4, item 3: the privacy wipes, the factory reset and the learned-example clear delete
  // persona examples, so they are approval-broker flows (native dialog), not renderer-boolean gates.
  for (const name of ['wipePrivacyData', 'factoryReset', 'clearPersonaLearning']) assert.equal(proxy[name], undefined, name);
  const del = await proxy.deleteWhisperModel({ modelSize: 'base' });
  assert.equal(del.ok, false);
  assert.match(del.error, /confirm/);
});

// --- Phase 0: routes that confer authority are not on the generic channel ----

test('routes that need the person\'s approval are refused on the generic proxy (Phase 0 items 1 and 3)', () => {
  const needApproval = [
    ['POST', '/workflows/approve'],
    ['POST', '/personas/Assistant/examples'],
    // Round 3, item 3: deleting one learned example is brokered too.
    ['DELETE', '/personas/Assistant/examples/abc123'],
    // Round 4, item 3: so are clearing them and deleting the persona with its few-shot list.
    ['DELETE', '/personas/Assistant/examples'],
    ['DELETE', '/personas/Assistant'],
    ['DELETE', '/privacy/persona-learning'],
    ['POST', '/privacy/wipe'],
    ['POST', '/privacy/factory-reset'],
    ['POST', '/runtime/primary-action'],
    ['POST', '/drafts/1/send'],
    ['POST', '/voice-commands/execute'],
    ['POST', '/workflows/preview'],
  ];
  for (const [method, path] of needApproval) {
    assert.notEqual(proxy._validateRequest(method, path), null, `${method} ${path} must not be reachable by a renderer`);
  }
});

test('the main-only transport is not an IPC-facing function', () => {
  // sendTrusted names its own route, so it must never be handed to ipcMain.
  const ipcSource = readFileSync(new URL('../src/main/ipc.js', import.meta.url), 'utf8');
  const exposed = ipcSource.match(/backendProxy\.sendTrusted\([^)]*\)/g) || [];
  // Only the broker's fixed-shape backend client may use it, never a renderer-chosen route.
  assert.equal(exposed.length, 1);
  assert.match(ipcSource, /const trustedBackend = \{ send: \(method, path, body, timeoutMs\) => backendProxy\.sendTrusted\(method, path, body, timeoutMs\) \};/);
  assert.match(ipcSource, /backend: trustedBackend,/);
  assert.ok(!/handleTrusted\([^)]*,\s*\(_event, req\) => backendProxy\.sendTrusted/.test(ipcSource));
});

// --- Round 2, item 7: the review window's own, much smaller route table ---------

test('the review profile allows exactly the routes review-overlay.html calls', () => {
  const allowed = [
    ['GET', '/runtime/output-settings'], ['GET', '/runtime/tts-status'], ['POST', '/tts/stop'],
    ['POST', '/drafts/7/edit'], ['POST', '/drafts/7/accept'], ['POST', '/drafts/7/decline'],
    ['POST', '/drafts/7/rewrite'], ['POST', '/drafts/7/tts'],
  ];
  for (const [method, path] of allowed) assert.equal(proxy._validateRequest(method, path, 'review'), null, `${method} ${path}`);
});

test('every backend route the review page actually calls is in its profile (so the page keeps working)', () => {
  const html = readFileSync(new URL('../src/renderer/review-overlay.html', import.meta.url), 'utf8');
  const called = new Set();
  for (const m of html.matchAll(/(fetchJson|postJson)\(\s*`\$\{BACKEND_ORIGIN\}([^`]+)`/g)) {
    called.add([m[1] === 'fetchJson' ? 'GET' : 'POST', m[2].replace(/\$\{[^}]+\}/g, '7')].join(' '));
  }
  assert.ok(called.size >= 8, [...called].join(', '));
  for (const entry of called) {
    const [method, path] = entry.split(' ');
    assert.equal(proxy._validateRequest(method, path, 'review'), null, `review page calls ${entry}`);
  }
});

test('the review profile refuses profile, persona, workflow, privacy, settings, drafts-listing and every other write', () => {
  const refused = [
    ['POST', '/settings/profiles'], ['POST', '/settings/profiles/x/activate'], ['DELETE', '/settings/profiles/x'],
    ['POST', '/personas'], ['POST', '/personas/lint'], ['DELETE', '/personas/x'], ['GET', '/personas/x/examples'],
    ['POST', '/workflows/save'], ['POST', '/workflows/enable'], ['POST', '/workflows/delete'], ['POST', '/workflows/run'], ['GET', '/workflows'],
    ['GET', '/privacy/export'], ['GET', '/history'], ['GET', '/drafts'], ['DELETE', '/drafts'], ['DELETE', '/history'],
    ['POST', '/dictionary'], ['POST', '/macros'], ['POST', '/models/llm/select'], ['POST', '/app-context/override'],
    ['POST', '/stream-deck/pair'], ['POST', '/input/bindings/set'], ['POST', '/library/clear'], ['POST', '/contacts'],
    ['POST', '/drafts/7/retry'], ['POST', '/drafts/7/contact'], ['POST', '/drafts/test-mock'], ['POST', '/runtime/emergency-stop'],
    ['POST', '/runtime/warmup'], ['GET', '/diagnostics/logs'], ['GET', '/runtime/status'], ['POST', '/tts/speak'],
    ['POST', '/drafts/7/send'], ['POST', '/runtime/primary-action'], ['POST', '/drafts/7/accept/../../x'],
  ];
  for (const [method, path] of refused) {
    assert.notEqual(proxy._validateRequest(method, path, 'review'), null, `${method} ${path} must be refused for the review window`);
  }
});

test('the review profile is a strict subset of the dashboard profile, and unknown profiles are refused', () => {
  for (const [method, patterns] of Object.entries(proxy.REVIEW_ROUTE_ALLOWLIST)) {
    for (const pattern of patterns) assert.ok(proxy.ROUTE_ALLOWLIST[method].includes(pattern), `${method} ${pattern}`);
  }
  assert.notEqual(proxy._validateRequest('GET', '/runtime/status', 'admin'), null);
  assert.notEqual(proxy._validateRequest('GET', '/runtime/status', 'nope'), null);
  assert.equal(proxy._validateRequest('GET', '/runtime/status'), null, 'the default profile is still the dashboard');
});
