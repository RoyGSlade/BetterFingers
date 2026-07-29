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
  summarizeWipeCleared,
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
  assert.match(summary, /Already cleared before the failure:.*drafts: 2/);
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

test('summarizeWipeCleared enumerates deletions but not quiesce/state steps', () => {
  const payload = {
    cleared: {
      wake_listener_stopped: true,   // quiesce state — excluded
      recorder_stopped: true,        // quiesce state — excluded
      pipeline_quiesced: true,       // quiesce state — excluded
      drafts: 3,                     // count — included
      recordings: 0,                 // zero count — excluded
      history_file_removed: true,    // removal — included
      recordings_files_removed: 2,   // count — included
      voices_removed: false,         // false removal — excluded
    },
  };
  const items = summarizeWipeCleared(payload);
  assert.deepEqual(
    items.sort(),
    ['drafts: 3', 'history_file_removed', 'recordings_files_removed: 2'].sort(),
  );
});

// --- object-shaped outcomes (Wave 12) ----------------------------------------
//
// Routed from sup-backend: server.py sets `cleared.history_db_wiped` to a
// RESULT OBJECT `{ok, recreated}`, not a flag, because wiping the conversation
// database and rebuilding its schema are two different claims. isDeletionOutcome
// handled numbers and booleans only, so the object fell through to `false` and
// a SUCCESSFUL history wipe was silently omitted from "what was deleted".
//
// That is a privacy-honesty bug, not a formatting one: confirming the deletion
// is the entire job of this summary, and the one category a user is most likely
// to be checking on is their conversation history.

test('a successful object-shaped wipe is reported as deleted', () => {
  const items = summarizeWipeCleared({
    cleared: { history_db_wiped: { ok: true, recreated: true } },
  });
  assert.deepEqual(items, ['history_db_wiped']);
});

test('a FAILED object-shaped wipe is not claimed as deleted', () => {
  // The mirror image, and the reason `ok` is checked explicitly rather than the
  // object merely being truthy — every object is truthy, so a naive fix would
  // report a failed wipe as a success. That would be worse than the original
  // bug: silence is bad, a false all-clear on a privacy deletion is dangerous.
  const items = summarizeWipeCleared({
    cleared: { history_db_wiped: { ok: false, recreated: false } },
  });
  assert.deepEqual(items, []);
});

test('a wipe that succeeded but could not recreate the store says so', () => {
  // The half-state: the data really is gone, but the store was not rebuilt.
  // The user should hear that from the success line, not discover it later.
  const items = summarizeWipeCleared({
    cleared: { history_db_wiped: { ok: true, recreated: false } },
  });
  assert.deepEqual(items, ['history_db_wiped (store not recreated — reopen the app to rebuild it)']);
});

test('an object whose key is not a deletion verb is still excluded', () => {
  // The `_removed|_wiped|_cleared` suffix rule holds for objects exactly as it
  // does for booleans, so a future object-shaped STATE step cannot sneak into
  // the deletion list just by carrying `ok: true`.
  const items = summarizeWipeCleared({
    cleared: { pipeline_quiesced_detail: { ok: true } },
  });
  assert.deepEqual(items, []);
});

test('failure summary lists what was already cleared (plan 1.2 "what WAS deleted")', () => {
  const payload = {
    ok: false,
    cleared: { drafts: 2, history_file_removed: true },
    postconditions: { recordings_dir_empty: false },
  };
  const summary = summarizeWipeFailure(payload);
  assert.match(summary, /Already cleared before the failure:/);
  assert.match(summary, /drafts: 2/);
  assert.match(summary, /history_file_removed/);
});

test('output-drain abort surfaces the stuck sends (finding 4)', () => {
  const payload = {
    ok: false,
    error: 'output_did_not_quiesce',
    stuck_sends: ['draft-7', 'draft-9'],
    cleared: {},
    postconditions: {},
  };
  const summary = summarizeWipeFailure(payload);
  assert.match(summary, /Nothing was deleted\./);
  assert.match(summary, /2 in-flight draft send\(s\) would not finish/);
  assert.match(summary, /draft-7, draft-9/);
  assert.match(summary, /Safe to retry\./);
});
