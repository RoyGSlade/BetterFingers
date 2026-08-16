import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  createNotificationState,
  dismissOperation,
  upsertOperation,
} from '../src/renderer/features/appNotificationCenter.js';

test('active operation updates replace in place and cannot be dismissed mid-run', () => {
  let state = createNotificationState();
  state = upsertOperation(state, { id: 'scribe', title: 'Processing text', state: 'processing', current: 1, total: 3 });
  state = upsertOperation(state, { id: 'scribe', state: 'processing', current: 2, total: 3 });
  assert.equal(state.operations.size, 1);
  assert.equal(state.operations.get('scribe').current, 2);
  assert.equal(dismissOperation(state, 'scribe').operations.size, 1);
});

test('completed and error operations remain visible until explicitly dismissed', () => {
  let state = upsertOperation(createNotificationState(), { id: 'scribe', state: 'completed', detail: 'Done' });
  assert.equal(state.operations.size, 1);
  state = dismissOperation(state, 'scribe');
  assert.equal(state.operations.size, 0);
});
