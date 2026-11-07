import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const proxy = require('../src/main/backendProxy.js');
const source = readFileSync(new URL('../src/renderer/api/backend.js', import.meta.url), 'utf8');
const api = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('the explicit collection clears pass confirmation through the actual bridge; learned examples go through the broker', async () => {
  const calls = [];
  const previous = globalThis.window;
  const brokered = [];
  globalThis.window = { betterFingers: {
    backendRequest: async (...args) => {
      calls.push(args);
      return { ok: true, status: 200, body: { ok: true } };
    },
    // Round 3, item 3: removing one learned example goes through the approval broker.
    deleteLearnedExample: async (...args) => { brokered.push(args); return { ok: true, status: 200, body: { ok: true } }; },
    // Round 4, item 3: clearing a persona's learned examples is a native dialog in main too.
    clearLearnedExamples: async (...args) => { brokered.push(args); return { ok: true, status: 200, body: { ok: true } }; },
  } };
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
      ['DELETE', '/message-rescue/context?confirm=true'],
    ]);
    assert.deepEqual(brokered.shift()[0], { persona: 'A B' }, 'the persona clear is brokered, with no confirm flag');
    assert.notEqual(proxy._validateRequest('DELETE', '/personas/A%20B/examples?confirm=true'), null, 'the proxy refuses it');
    for (const [method, path] of calls) assert.equal(proxy._validateRequest(method, path), null);
    calls.length = 0;
    await api.deleteRecording('');
    await api.deletePersonaExample('A B', '.');
    for (const [, path] of calls) assert.equal(new URL(path, 'http://local').searchParams.has('confirm'), false);
    assert.equal(calls.filter(([, path]) => path.includes('/examples/')).length, 0, 'never through the generic proxy');
    assert.deepEqual(brokered[0][0], { persona: 'A B', exampleId: '.' });
    assert.notEqual(proxy._validateRequest('DELETE', '/personas/A%20B/examples/ex_1'), null, 'the proxy refuses it');
  } finally {
    globalThis.window = previous;
  }
});
