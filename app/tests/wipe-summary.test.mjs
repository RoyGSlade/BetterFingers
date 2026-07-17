// Unit tests for the pure privacy-wipe summary helper (Phase 1.2).
// Run with: node --test app/tests/wipe-summary.test.mjs
//
// The renderer must never claim success unless result.ok === true, and a
// failed/partial wipe must be summarized truthfully — what did not verify and
// whether retry is safe. summarizeWipeFailure is DOM-free and Electron-free.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  summarizeWipeFailure,
  failedPostconditions,
  isPreDeleteAbort,
  WIPE_PRE_DELETE_ABORTS,
} from '../src/renderer/lib/wipeSummary.mjs';

test('pre-delete aborts are recognized and reported as nothing-deleted', () => {
  for (const error of WIPE_PRE_DELETE_ABORTS) {
    const payload = { ok: false, error, cleared: {}, postconditions: {} };
    assert.equal(isPreDeleteAbort(payload), true);
    const summary = summarizeWipeFailure(payload);
    assert.match(summary, /Nothing was deleted\./);
    assert.match(summary, /Safe to retry\./);
  }
});

test('postcondition failures are listed by name', () => {
  const payload = {
    ok: false,
    cleared: { drafts: 2 },
    postconditions: {
      draft_queue_empty: true,
      history_db_wiped: false,
      recordings_dir_empty: false,
      leftover_recordings: ['stubborn.wav', 'a.wav'],
    },
  };
  assert.deepEqual(
    failedPostconditions(payload),
    ['history_db_wiped', 'recordings_dir_empty'],
  );
  const summary = summarizeWipeFailure(payload);
  assert.match(summary, /history_db_wiped/);
  assert.match(summary, /recordings_dir_empty/);
  assert.match(summary, /2 recording file\(s\) still remain\./);
  assert.match(summary, /2 draft\(s\) were cleared before the failure\./);
  assert.match(summary, /retrying is safe/);
});

test('leftover_recordings is never treated as a failed boolean check', () => {
  const payload = {
    ok: false,
    postconditions: { recordings_dir_empty: false, leftover_recordings: ['x.wav'] },
  };
  assert.ok(!failedPostconditions(payload).includes('leftover_recordings'));
});

test('a null / undefined payload still yields a safe, non-empty summary', () => {
  for (const payload of [null, undefined, {}]) {
    const summary = summarizeWipeFailure(payload);
    assert.equal(typeof summary, 'string');
    assert.ok(summary.length > 0);
    assert.match(summary, /retrying is safe/);
  }
});

test('output_did_not_quiesce is a pre-delete abort (subsystem could not drain)', () => {
  assert.equal(isPreDeleteAbort({ error: 'output_did_not_quiesce' }), true);
  assert.equal(isPreDeleteAbort({ error: 'unrecognized_error' }), false);
});
