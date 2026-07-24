// Pure status/label helpers for the Review Deck overlay (review-overlay.html),
// extracted from its former inline module script (Phase 6 restyle) so they
// are unit-testable with `node --test` (see app/tests/overlays.test.mjs)
// without a DOM. Behavior is unchanged from the original inline versions --
// only the location moved (plus one addition, formatClockDuration, which is
// new presentation-only support for the restyled raw-transcript mini player).

// draft.status (server-shaped) -> the overlay's own state vocabulary. The
// caller applies the sent+fallback -> 'copied' special case itself (it also
// has draft.send_result on hand, which this pure mapping doesn't need).
const DRAFT_STATUS_TO_OVERLAY_STATE = {
  pending: 'pending',
  accepted: 'accepted',
  declined: 'declined',
  sent: 'sent',
  send_error: 'error',
  send_interrupted: 'interrupted',
  error: 'error',
};

/** @param {string} status draft.status @returns {string} overlay state, defaulting to 'pending' */
export function mapDraftStatusToOverlayState(status) {
  return DRAFT_STATUS_TO_OVERLAY_STATE[status] || 'pending';
}

const OVERLAY_STATE_LABELS = {
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

/** @param {string} state one of the 12 overlay states @returns {string} its badge label, or the raw state if unknown */
export function overlayStateLabelFor(state) {
  return OVERLAY_STATE_LABELS[state] || state;
}

/**
 * Default message tone for a state, when the caller doesn't pass an explicit
 * tone (mirrors the original inline ternary chain in setOverlayState()).
 * @param {string} state
 * @returns {'danger'|'warning'|'success'|''}
 */
export function overlayStateDefaultTone(state) {
  if (state === 'error' || state === 'stopped') return 'danger';
  if (state === 'rewriting' || state === 'interrupted') return 'warning';
  if (state === 'sent' || state === 'rewritten' || state === 'accepted' || state === 'copied') return 'success';
  return '';
}

// Confidence-gated send policy (Phase 12): friendly text for why an
// auto-send was withheld and the draft must be sent manually.
export function reviewReasonText(reason) {
  switch (reason) {
    case 'low_confidence': return 'low confidence';
    case 'confidence_missing': return 'confidence unknown';
    case 'confidence_moderate': return 'confidence not high enough';
    case 'long_draft': return 'long draft';
    case 'audio_gate': return 'audio check';
    default: return '';
  }
}

// The accept flow's auto-send action picker, extracted verbatim so its
// branching is unit-testable.
export function defaultSendActionFor(outputSettings) {
  if (!outputSettings?.capabilities?.supports_input_injection) {
    return 'copy_only';
  }
  return outputSettings?.send_mode === 'auto_send' ? 'open_chat_then_send' : 'paste';
}

/**
 * mm:ss clock formatting for the raw-transcript mini audio player's duration
 * readout (SPEC 7's "00:12"). Fed by the REAL draft.metadata.duration_seconds
 * field (the same one features/drafts.js's formatDraftMetadata() and the
 * Library workspace's waveform-thumbnail duration already read) -- not a
 * fabricated value. Missing/invalid input reads as '00:00' rather than
 * throwing, since the field may not be populated yet (e.g. before the first
 * draft arrives).
 * @param {number} totalSeconds
 * @returns {string} 'MM:SS'
 */
export function formatClockDuration(totalSeconds) {
  const n = Number(totalSeconds);
  if (!Number.isFinite(n) || n < 0) return '00:00';
  const s = Math.round(n);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${String(m).padStart(2, '0')}:${String(rem).padStart(2, '0')}`;
}
