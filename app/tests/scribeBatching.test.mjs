import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  BATCH_CHOICES,
  assembleBatchResults,
  cancelBatch,
  createBatchOperation,
  effectiveBatchWords,
  needsLongInputChoice,
  recordBatchFailure,
  recordBatchSuccess,
  resumeBatch,
  splitLongInput,
  validateCombinedProtectedValues,
} from '../src/renderer/features/scribeBatching.js';

test('long input choices are 250, 500 recommended, and full', () => {
  assert.deepEqual(BATCH_CHOICES.map((item) => item.id), ['250', '500', 'full']);
  assert.equal(BATCH_CHOICES.find((item) => item.recommended).id, '500');
  assert.equal(needsLongInputChoice(Array.from({ length: 501 }, () => 'word').join(' ')), true);
});

test('context limits can reduce a requested 500-word batch', () => {
  assert.ok(effectiveBatchWords(500, { contextTokens: 1500, reservedOutputTokens: 600 }) < 500);
});

test('safe splitter preserves order, paragraph/list text, and never overlaps', () => {
  const filler = Array.from({ length: 18 }, (_, index) => `detail${index}`).join(' ');
  const text = `Heading\n\nFirst sentence has several useful words ${filler}. Second sentence stays beside it ${filler}.\n\n- item one keeps 123 ${filler}\n- item two keeps https://example.test/path ${filler}\n\nFinal paragraph ends here ${filler}.`;
  const chunks = splitLongInput(text, 12);
  assert.ok(chunks.length > 1);
  const assembled = chunks.join('\n\n').replace(/\n{3,}/g, '\n\n');
  for (const token of ['Heading', 'First sentence', 'item one', '123', 'https://example.test/path', 'Final paragraph']) {
    assert.equal(chunks.filter((chunk) => chunk.includes(token)).length, 1, `${token} appears exactly once`);
  }
  assert.ok(assembled.indexOf('Heading') < assembled.indexOf('First sentence'));
  assert.ok(assembled.indexOf('item one') < assembled.indexOf('Final paragraph'));
});

test('failed chunks pause at the same index; retry does not duplicate completed output', () => {
  let operation = createBatchOperation(['one', 'two', 'three']);
  operation = recordBatchSuccess(operation, { variants: { faithful: 'ONE' } });
  operation = recordBatchFailure(operation, 'boom');
  assert.equal(operation.failedIndex, 1);
  operation = resumeBatch(operation);
  assert.equal(operation.index, 1);
  operation = recordBatchSuccess(operation, { variants: { faithful: 'TWO' } });
  operation = recordBatchSuccess(operation, { variants: { faithful: 'THREE' } });
  assert.equal(operation.completed.length, 3);
  assert.equal(assembleBatchResults(operation.completed).variants.faithful, 'ONE\n\nTWO\n\nTHREE');
  assert.equal(cancelBatch(operation).state, 'cancelled');
});

test('assembled output is validated against protected values from the full source', () => {
  const source = 'Do not send 2 files. Restart nginx using systemctl restart nginx.';
  const checks = validateCombinedProtectedValues(source, 'Do send 2 files.', 'combined/faithful');
  assert.equal(checks.find((check) => check.name.endsWith('/negation')).passed, false);
  assert.equal(checks.find((check) => check.name.endsWith('/commands')).passed, false);

  const assembled = assembleBatchResults([
    { variants: { faithful: 'Do not send 2 files.', clearer: 'Do not send 2 files.', alternate: 'Do not send 2 files.' } },
    { variants: { faithful: 'Restart nginx using systemctl restart nginx.', clearer: 'Restart nginx.', alternate: 'Restart nginx.' } },
  ], source);
  assert.equal(assembled.variants.faithful.includes('systemctl restart nginx'), true);
  assert.equal(assembled.variants.clearer, '');
  assert.ok(assembled.preservation_checks.some((check) => check.name === 'combined/clearer/commands' && !check.passed));
});
