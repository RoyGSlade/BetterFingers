// Unit tests for the two floating OVERLAYS' pure helpers
// (docs/ui/SIGNAL_DESK_SPEC.md section 7), extracted from overlay.html /
// review-overlay.html's former inline scripts during the Phase 6 restyle:
//   - lib/overlayStatus.mjs        (capture overlay: status payload -> ring state/text)
//   - lib/reviewOverlayStatus.mjs  (Review Deck: draft status -> overlay state/label/tone, etc.)
// Also cross-checks that every ring state the capture overlay can produce is
// one signalCore.js actually knows how to render (SIGNAL_CORE_STATES plus
// its alias table), since overlay.html now drives a Signal Core ring instead
// of glitch-ring.js.
//
// Run with: node --test app/tests/overlays.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { interpretOverlayStatus } from '../src/renderer/lib/overlayStatus.mjs';
import {
  mapDraftStatusToOverlayState,
  overlayStateLabelFor,
  overlayStateDefaultTone,
  reviewReasonText,
  defaultSendActionFor,
  formatClockDuration,
} from '../src/renderer/lib/reviewOverlayStatus.mjs';
import { SIGNAL_CORE_STATES, SIGNAL_CORE_STATE_ALIASES, resolveSignalCoreState } from '../src/renderer/signalCore.js';

// --- interpretOverlayStatus (capture overlay) -------------------------------

test('interpretOverlayStatus: recording_started/recording map to the recording ring', () => {
  assert.deepEqual(interpretOverlayStatus('recording_started'), { ring: 'recording', text: 'Recording...' });
  assert.deepEqual(interpretOverlayStatus('recording'), { ring: 'recording', text: 'Recording...' });
});

test('interpretOverlayStatus: listening/recording_armed use payload.message when present', () => {
  assert.deepEqual(interpretOverlayStatus('listening'), { ring: 'listening', text: 'Listening...' });
  assert.deepEqual(interpretOverlayStatus('listening', { message: 'Voice input detected' }), {
    ring: 'listening',
    text: 'Voice input detected',
  });
  assert.equal(interpretOverlayStatus('recording_armed').ring, 'listening');
});

test('interpretOverlayStatus: transcribing/rewriting/processing all collapse to the transcribing ring', () => {
  for (const status of ['transcribing', 'rewriting', 'processing']) {
    assert.deepEqual(interpretOverlayStatus(status), { ring: 'transcribing', text: 'Processing...' });
  }
});

test('interpretOverlayStatus: chunking_stitching maps to the stitching ring', () => {
  assert.deepEqual(interpretOverlayStatus('chunking_stitching'), { ring: 'stitching', text: 'Stitching...' });
  assert.equal(interpretOverlayStatus('chunking_stitching', { message: 'Combining chunks' }).text, 'Combining chunks');
});

test('interpretOverlayStatus: draft_sent branches on payload.fallback', () => {
  assert.deepEqual(interpretOverlayStatus('draft_sent'), { ring: 'ready', text: 'Sent' });
  assert.deepEqual(interpretOverlayStatus('draft_sent', { fallback: true }), {
    ring: 'warning',
    text: 'Copied as fallback',
  });
});

test('interpretOverlayStatus: error-family statuses map to the error ring', () => {
  for (const status of ['draft_blocked', 'draft_error', 'draft_send_error', 'selection_capture_failed']) {
    assert.equal(interpretOverlayStatus(status).ring, 'error');
  }
});

test('interpretOverlayStatus: unknown status falls back to idle, echoing the status as text', () => {
  assert.deepEqual(interpretOverlayStatus('totally-unknown'), { ring: 'idle', text: 'totally-unknown' });
});

test('interpretOverlayStatus: every possible `ring` value resolves to a real Signal Core state', () => {
  // overlay.html passes interpretOverlayStatus()'s `ring` straight into
  // ring.setState() -- confirm signalCore.js's alias table actually covers
  // every ring name this module can emit (idle/listening/recording/
  // transcribing/stitching/ready/error/warning), so none silently no-op.
  const allStatuses = [
    'recording_started', 'recording', 'listening', 'recording_armed',
    'transcribing', 'rewriting', 'processing',
    'long_recording_detected', 'chunking_started', 'chunking_progress',
    'chunking_stitching', 'preview_ready', 'draft_sent', 'selection_captured',
    'emergency_stop', 'draft_blocked', 'draft_error', 'draft_send_error',
    'selection_capture_failed', 'unknown-status',
  ];
  for (const status of allStatuses) {
    const { ring } = interpretOverlayStatus(status, { fallback: true });
    const resolved = resolveSignalCoreState(ring);
    assert.ok(SIGNAL_CORE_STATES.includes(resolved), `ring '${ring}' (from status '${status}') resolved to '${resolved}', not a known Signal Core state`);
  }
});

// --- mapDraftStatusToOverlayState / overlayStateLabelFor (Review Deck) -----

test('mapDraftStatusToOverlayState: known draft statuses map 1:1 or to error', () => {
  assert.equal(mapDraftStatusToOverlayState('pending'), 'pending');
  assert.equal(mapDraftStatusToOverlayState('accepted'), 'accepted');
  assert.equal(mapDraftStatusToOverlayState('declined'), 'declined');
  assert.equal(mapDraftStatusToOverlayState('sent'), 'sent');
  assert.equal(mapDraftStatusToOverlayState('send_error'), 'error');
  assert.equal(mapDraftStatusToOverlayState('send_interrupted'), 'interrupted');
  assert.equal(mapDraftStatusToOverlayState('error'), 'error');
});

test('mapDraftStatusToOverlayState: unknown/missing status defaults to pending', () => {
  assert.equal(mapDraftStatusToOverlayState('something-else'), 'pending');
  assert.equal(mapDraftStatusToOverlayState(undefined), 'pending');
});

test('overlayStateLabelFor: covers all 12 states from CURRENT_UI_INVENTORY.md §12.2', () => {
  const expected = {
    pending: 'Draft Pending',
    rewriting: 'Rewriting',
    rewritten: 'Rewritten',
    speaking: 'Speaking',
    accepted: 'Accepted',
    sent: 'Sent',
    copied: 'Copied Fallback',
    declined: 'Declined',
    error: 'Error',
    interrupted: 'Send Interrupted',
    stopped: 'Stopped',
    confirm: 'Confirm?',
  };
  for (const [state, label] of Object.entries(expected)) {
    assert.equal(overlayStateLabelFor(state), label);
  }
});

test('overlayStateLabelFor: unknown state passes through verbatim rather than throwing', () => {
  assert.equal(overlayStateLabelFor('mystery'), 'mystery');
});

test('overlayStateDefaultTone: groups states into the same three tiers the original palette used', () => {
  for (const state of ['error', 'stopped']) assert.equal(overlayStateDefaultTone(state), 'danger');
  for (const state of ['rewriting', 'interrupted']) assert.equal(overlayStateDefaultTone(state), 'warning');
  for (const state of ['sent', 'rewritten', 'accepted', 'copied']) assert.equal(overlayStateDefaultTone(state), 'success');
  for (const state of ['pending', 'declined', 'confirm', 'speaking']) assert.equal(overlayStateDefaultTone(state), '');
});

// --- reviewReasonText --------------------------------------------------------

test('reviewReasonText: maps every confidence-gate reason to friendly text', () => {
  assert.equal(reviewReasonText('low_confidence'), 'low confidence');
  assert.equal(reviewReasonText('confidence_missing'), 'confidence unknown');
  assert.equal(reviewReasonText('confidence_moderate'), 'confidence not high enough');
  assert.equal(reviewReasonText('long_draft'), 'long draft');
  assert.equal(reviewReasonText('audio_gate'), 'audio check');
});

test('reviewReasonText: unknown/missing reason is an empty string', () => {
  assert.equal(reviewReasonText('something-else'), '');
  assert.equal(reviewReasonText(undefined), '');
});

// --- defaultSendActionFor ----------------------------------------------------

test('defaultSendActionFor: no input-injection capability forces copy_only', () => {
  assert.equal(defaultSendActionFor({ capabilities: { supports_input_injection: false }, send_mode: 'auto_send' }), 'copy_only');
  assert.equal(defaultSendActionFor(null), 'copy_only');
});

test('defaultSendActionFor: auto_send profile with injection support opens chat then sends', () => {
  assert.equal(
    defaultSendActionFor({ capabilities: { supports_input_injection: true }, send_mode: 'auto_send' }),
    'open_chat_then_send',
  );
});

test('defaultSendActionFor: non-auto_send profile with injection support pastes', () => {
  assert.equal(
    defaultSendActionFor({ capabilities: { supports_input_injection: true }, send_mode: 'review_first' }),
    'paste',
  );
});

// --- formatClockDuration ------------------------------------------------------

test('formatClockDuration: formats seconds as MM:SS', () => {
  assert.equal(formatClockDuration(0), '00:00');
  assert.equal(formatClockDuration(12), '00:12');
  assert.equal(formatClockDuration(75), '01:15');
  assert.equal(formatClockDuration(3661), '61:01');
});

test('formatClockDuration: rounds fractional seconds', () => {
  assert.equal(formatClockDuration(11.6), '00:12');
});

test('formatClockDuration: missing/invalid/negative input reads as 00:00 rather than throwing', () => {
  assert.equal(formatClockDuration(undefined), '00:00');
  assert.equal(formatClockDuration(null), '00:00');
  assert.equal(formatClockDuration(NaN), '00:00');
  assert.equal(formatClockDuration(-5), '00:00');
});

// --- sanity: SIGNAL_CORE_STATE_ALIASES still covers overlay.html's full
// legacy vocabulary (guards against a future signalCore.js edit silently
// dropping 'stitching' or 'warning', which would break the ring-state
// cross-check test above) --------------------------------------------------

test('signalCore alias table still covers stitching and warning (overlay.html\'s legacy ring names)', () => {
  assert.equal(SIGNAL_CORE_STATE_ALIASES.stitching, 'transcribing');
  assert.equal(SIGNAL_CORE_STATE_ALIASES.warning, 'error');
});
