// Unit tests for the review-overlay draft summary formatter.
// Run with: node --test app/tests/draft-summary.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { formatDraftSummary } from '../src/renderer/lib/draftSummary.mjs';

test('counts words in the final text', () => {
  assert.equal(formatDraftSummary('Mock cleaned and polished output.'), '5 words');
});

test('singular for one word', () => {
  assert.equal(formatDraftSummary('Hello'), '1 word');
});

test('empty / whitespace / non-string is zero words', () => {
  assert.equal(formatDraftSummary(''), '0 words');
  assert.equal(formatDraftSummary('   '), '0 words');
  assert.equal(formatDraftSummary(undefined), '0 words');
  assert.equal(formatDraftSummary(null), '0 words');
  assert.equal(formatDraftSummary(42), '0 words');
});

test('collapses irregular whitespace and newlines', () => {
  assert.equal(formatDraftSummary('  one\t two \n three  '), '3 words');
});

test('flags a long draft when over the warning threshold', () => {
  const text = Array.from({ length: 5 }, () => 'word').join(' ');
  assert.equal(formatDraftSummary(text, 3), '5 words · long draft (over 3 words)');
});

test('does not flag when at or under the threshold', () => {
  const text = Array.from({ length: 3 }, () => 'word').join(' ');
  assert.equal(formatDraftSummary(text, 3), '3 words');
});

test('ignores a missing, zero, or non-numeric threshold', () => {
  const text = Array.from({ length: 5 }, () => 'word').join(' ');
  assert.equal(formatDraftSummary(text), '5 words');
  assert.equal(formatDraftSummary(text, 0), '5 words');
  assert.equal(formatDraftSummary(text, 'nope'), '5 words');
});
