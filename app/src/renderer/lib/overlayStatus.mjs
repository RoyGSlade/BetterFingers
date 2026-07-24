// Pure status-payload -> {ring state, label text} mapping for the Signal Core
// capture overlay (overlay.html). Extracted verbatim from overlay.html's
// former inline `interpret()` (Phase 6 restyle) so it is unit-testable with
// `node --test` (see app/tests/overlays.test.mjs) without needing a DOM/
// Electron context. Behavior is unchanged from the original inline version --
// only the location moved.
//
// The returned `ring` values are overlay.html's own long-standing 8-state
// vocabulary (idle/listening/recording/transcribing/stitching/ready/error/
// warning) -- signalCore.js's resolveSignalCoreState()/
// SIGNAL_CORE_STATE_ALIASES collapse stitching->transcribing and
// warning->error, so passing these straight into a Signal Core ring's
// setState() is safe (see signalCore.test.mjs's alias-table coverage and this
// module's own cross-check test).

/**
 * @param {string} status raw `status` field of an overlay:update IPC payload
 * @param {object} [payload] the full payload (for `.message`/`.fallback`, etc.)
 * @returns {{ring: string, text: string}}
 */
export function interpretOverlayStatus(status, payload = {}) {
  switch (status) {
    case 'recording_started':
    case 'recording':
      return { ring: 'recording', text: 'Recording...' };
    case 'listening':
    case 'recording_armed':
      return { ring: 'listening', text: payload.message || 'Listening...' };
    case 'transcribing':
    case 'rewriting':
    case 'processing':
      return { ring: 'transcribing', text: 'Processing...' };
    case 'long_recording_detected':
    case 'chunking_started':
    case 'chunking_progress':
      return { ring: 'transcribing', text: payload.message || 'Processing...' };
    case 'chunking_stitching':
      return { ring: 'stitching', text: payload.message || 'Stitching...' };
    case 'preview_ready':
      return { ring: 'ready', text: payload.message || 'Draft ready' };
    case 'draft_sent':
      return payload.fallback
        ? { ring: 'warning', text: payload.message || 'Copied as fallback' }
        : { ring: 'ready', text: payload.message || 'Sent' };
    case 'selection_captured':
      return { ring: 'ready', text: payload.message || 'Selection captured' };
    case 'emergency_stop':
      return { ring: 'warning', text: payload.message || 'Stopped' };
    case 'draft_blocked':
    case 'draft_error':
    case 'draft_send_error':
    case 'selection_capture_failed':
      return { ring: 'error', text: payload.message || 'Needs attention' };
    default:
      return { ring: 'idle', text: status };
  }
}
