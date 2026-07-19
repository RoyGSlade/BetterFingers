// Phase 1.2 (remediation): a DOM-free helper that turns a truthful privacy-wipe
// payload into a human summary. The renderer must never claim success unless
// result.ok === true; when a wipe fails or only partly succeeds, the user
// should see what did not verify and whether it is safe to retry.
//
// Pure and Electron-free so it can be unit-tested on any Node runtime — the
// same pattern as lib/draftSummary.mjs.

// Errors the backend raises BEFORE any deletion happens (see server.py
// _perform_privacy_wipe). In these cases nothing was removed, so a retry is
// always safe and loses nothing.
export const WIPE_PRE_DELETE_ABORTS = new Set([
  'wipe_already_running',
  'pipeline_did_not_quiesce',
  'output_did_not_quiesce',
]);

// Postcondition entries that are not booleans and must not be listed as
// failed checks (e.g. the array of leftover recording filenames).
const NON_BOOLEAN_POSTCONDITIONS = new Set(['leftover_recordings']);

// The names of every postcondition that did not hold (value === false).
export function failedPostconditions(payload) {
  const post = (payload && payload.postconditions) || {};
  const failed = [];
  for (const [name, value] of Object.entries(post)) {
    if (NON_BOOLEAN_POSTCONDITIONS.has(name)) continue;
    if (value === false) failed.push(name);
  }
  return failed;
}

// A pre-deletion abort means nothing was touched.
export function isPreDeleteAbort(payload) {
  return Boolean(payload && payload.error && WIPE_PRE_DELETE_ABORTS.has(payload.error));
}

// A cleared{} entry describes something actually deleted (not a quiesce/state
// step like recorder_stopped or pipeline_quiesced). Numbers are counts;
// booleans only count when the key names a removal (_removed/_wiped/_cleared).
function isDeletionOutcome(key, value) {
  if (typeof value === 'number') return value > 0;
  if (typeof value === 'boolean') return value && /_(removed|wiped|cleared)$/.test(key);
  return false;
}

// "What WAS deleted" — the positive side of a partial wipe, drawn from the
// backend's cleared{} map. Returns a list of human-readable items.
export function summarizeWipeCleared(payload) {
  const cleared = (payload && payload.cleared) || {};
  const done = [];
  for (const [key, value] of Object.entries(cleared)) {
    if (!isDeletionOutcome(key, value)) continue;
    done.push(typeof value === 'number' ? `${key}: ${value}` : key);
  }
  return done;
}

// A plain-text, injection-safe (used with textContent) summary of a failed or
// partial wipe: what did not verify, what remains, and whether retry is safe.
export function summarizeWipeFailure(payload) {
  const parts = [];
  const abort = isPreDeleteAbort(payload);

  if (abort) {
    parts.push('Nothing was deleted.');
    // output_did_not_quiesce carries the in-flight sends that would not finish.
    const stuck = payload && payload.stuck_sends;
    if (Array.isArray(stuck) && stuck.length) {
      parts.push(`${stuck.length} in-flight draft send(s) would not finish (${stuck.join(', ')}).`);
    }
    parts.push('Safe to retry.');
    return parts.join(' ');
  }

  const failed = failedPostconditions(payload);
  if (failed.length) {
    parts.push(`These checks did not verify: ${failed.join(', ')}.`);
  }
  const post = (payload && payload.postconditions) || {};
  const leftovers = post.leftover_recordings;
  if (Array.isArray(leftovers) && leftovers.length) {
    parts.push(`${leftovers.length} recording file(s) still remain.`);
  }
  // Show what WAS deleted (plan 1.2), not just a drafts count.
  const clearedItems = summarizeWipeCleared(payload);
  if (clearedItems.length) {
    parts.push(`Already cleared before the failure: ${clearedItems.join(', ')}.`);
  }
  parts.push('Some data may remain — retrying is safe and may clear the rest.');
  return parts.join(' ');
}
