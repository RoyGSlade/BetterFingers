// Unit tests for the extracted renderer draft feature (Phase 1, A1.3).
// Run with: node --test app/tests/drafts-feature.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { formatDraftMetadata, formatDraftMetadataDetail } from '../src/renderer/features/drafts.js';

test('formatDraftMetadata: no metadata', () => {
  assert.equal(formatDraftMetadata(null), 'No recording metadata available.');
  assert.equal(formatDraftMetadata({}), 'No recording metadata available.');
  assert.equal(formatDraftMetadata({ metadata: {} }), 'No recording metadata available.');
});

test('formatDraftMetadata: duration + known stop reason label', () => {
  const draft = { metadata: { duration_seconds: 12.345, stop_reason: 'silence' } };
  assert.equal(formatDraftMetadata(draft), '12.3s recording · auto-stopped on silence');
});

test('formatDraftMetadata: unknown stop reason falls back to the raw value', () => {
  const draft = { metadata: { duration_seconds: 1, stop_reason: 'weird_reason' } };
  assert.equal(formatDraftMetadata(draft), '1.0s recording · weird_reason');
});

test('formatDraftMetadataDetail: no metadata is empty string', () => {
  assert.equal(formatDraftMetadataDetail(null), '');
  assert.equal(formatDraftMetadataDetail({ metadata: {} }), '');
});

test('formatDraftMetadataDetail: formats acoustic telemetry', () => {
  const draft = {
    metadata: {
      rms_amplitude: 0.012345,
      max_amplitude: 0.98765,
      sample_count: 44100,
      sample_rate: 16000,
    },
  };
  assert.equal(
    formatDraftMetadataDetail(draft),
    'samples 44100 @ 16000 Hz · peak 0.98765 · rms 0.01235',
  );
});
