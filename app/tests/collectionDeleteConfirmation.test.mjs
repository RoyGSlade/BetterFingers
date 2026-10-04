import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const proxy = require('../src/main/backendProxy.js');
const source = readFileSync(new URL('../src/renderer/api/backend.js', import.meta.url), 'utf8');
const api = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('all five explicit collection clears pass confirmation through the actual bridge', async () => {
  const calls = [];
  const previous = globalThis.window;
  globalThis.window = { betterFingers: { backendRequest: async (...args) => {
    calls.push(args);
    return { ok: true, status: 200, body: { ok: true } };
  } } };
  try {
    await api.clearRecordings();
    await api.clearHistory();
    await api.clearDrafts();
    await api.clearPersonaExamples('A B');
    await api.clearMessageRescueContext();
    assert.deepEqual(calls.map(([method, path]) => [method, path]), [
      ['DELETE', '/recordings?confirm=true'],
      ['DELETE', '/history?confirm=true'],
      ['DELETE', '/drafts?confirm=true'],
      ['DELETE', '/personas/A%20B/examples?confirm=true'],
      ['DELETE', '/message-rescue/context?confirm=true'],
    ]);
    for (const [method, path] of calls) assert.equal(proxy._validateRequest(method, path), null);
    calls.length = 0;
    await api.deleteRecording('');
    await api.deletePersonaExample('A B', '.');
    for (const [, path] of calls) assert.equal(new URL(path, 'http://local').searchParams.has('confirm'), false);
  } finally {
    globalThis.window = previous;
  }
});
