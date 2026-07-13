// Unit tests for the main-process backend proxy's path/method validation
// (Phase 3c). Pure logic — no Electron, no network.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const proxy = require('../src/main/backendProxy.js');

test('accepts known backend routes', () => {
  for (const path of ['/health', '/drafts', '/drafts/1/send', '/settings/profiles',
                       '/models/llm/select', '/personas/lint', '/runtime/status',
                       '/tts/voices', '/privacy/wipe', '/recordings/abc']) {
    assert.equal(proxy._validatePath(path), null, `${path} should be allowed`);
  }
});

test('accepts a query string on an allowed route', () => {
  assert.equal(proxy._validatePath('/doctor?refresh_audio=true'), null);
});

test('rejects path traversal', () => {
  assert.notEqual(proxy._validatePath('/drafts/../../etc/passwd'), null);
});

test('rejects an absolute URL with a scheme', () => {
  assert.notEqual(proxy._validatePath('http://evil.example/steal'), null);
  assert.notEqual(proxy._validatePath('/redirect?u=http://evil.example'), null);
});

test('rejects a backslash', () => {
  assert.notEqual(proxy._validatePath('/drafts\\..\\x'), null);
});

test('rejects protocol-relative and non-absolute paths', () => {
  assert.notEqual(proxy._validatePath('//evil.example/x'), null);
  assert.notEqual(proxy._validatePath('drafts'), null);
  assert.notEqual(proxy._validatePath(''), null);
});

test('rejects a route outside the allowlist', () => {
  assert.notEqual(proxy._validatePath('/secret-admin'), null);
  assert.notEqual(proxy._validatePath('/etc/passwd'), null);
});

test('rejects an over-long path', () => {
  assert.notEqual(proxy._validatePath('/drafts/' + 'a'.repeat(2000)), null);
});

test('method allowlist is exactly the CRUD verbs', () => {
  assert.ok(proxy.ALLOWED_METHODS.has('GET'));
  assert.ok(proxy.ALLOWED_METHODS.has('POST'));
  assert.ok(proxy.ALLOWED_METHODS.has('PUT'));
  assert.ok(proxy.ALLOWED_METHODS.has('DELETE'));
  assert.ok(!proxy.ALLOWED_METHODS.has('CONNECT'));
  assert.ok(!proxy.ALLOWED_METHODS.has('TRACE'));
});
