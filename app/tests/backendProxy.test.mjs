// Unit tests for the main-process backend proxy's route/method validation
// (Phase 3c, tightened to an exact route table + typed destructive ops).
// Pure logic — no Electron, no network.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

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
    ['POST', '/drafts/1/accept'],
    ['POST', '/models/llm/select'],
    ['POST', '/personas/lint'],
    ['POST', '/recordings/abc/retranscribe'],
    ['DELETE', '/recordings/abc'],
    ['DELETE', '/macros/hello'],
  ];
  for (const [method, path] of allowed) {
    assert.equal(proxy._validateRequest(method, path), null, `${method} ${path} should be allowed`);
  }
});

test('rejects an allowed route with the wrong method', () => {
  assert.notEqual(proxy._validateRequest('DELETE', '/drafts/latest'), null);
  assert.notEqual(proxy._validateRequest('POST', '/runtime/status'), null);
  assert.notEqual(proxy._validateRequest('GET', '/models/llm/select'), null);
});

test('route match requires a path boundary, not a prefix', () => {
  // Old startsWith matching accepted these; the exact table must not.
  assert.notEqual(proxy._validateRequest('GET', '/draftsX'), null);
  assert.notEqual(proxy._validateRequest('GET', '/privacyX'), null);
  assert.notEqual(proxy._validateRequest('GET', '/healthcheck'), null);
  assert.notEqual(proxy._validateRequest('DELETE', '/recordings/a/b'), null);
});

test('destructive routes are refused on the generic channel', () => {
  assert.notEqual(proxy._validateRequest('POST', '/privacy/wipe'), null);
  assert.notEqual(proxy._validateRequest('POST', '/drafts/1/send'), null);
  assert.notEqual(proxy._validateRequest('POST', '/jobs/j1/cancel'), null);
  assert.notEqual(proxy._validateRequest('DELETE', '/models/llm/some-model'), null);
  assert.notEqual(proxy._validateRequest('DELETE', '/models/whisper/base'), null);
  assert.notEqual(proxy._validateRequest('DELETE', '/tts/voices/v1'), null);
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

test('destructive typed operations require confirm: true', async () => {
  const wipe = await proxy.wipePrivacyData({ wipeVoices: true });
  assert.equal(wipe.ok, false);
  assert.match(wipe.error, /confirm/);
  const del = await proxy.deleteWhisperModel({ modelSize: 'base' });
  assert.equal(del.ok, false);
  assert.match(del.error, /confirm/);
});
