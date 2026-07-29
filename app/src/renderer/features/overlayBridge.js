// overlayBridge.js — the production page's caller for the two floating windows.
//
// WHY THIS FILE EXISTS
// --------------------
// `overlay.html` (the always-on-top capture ring) and `review-overlay.html` (the
// Review Deck) are real production windows created by `app/src/main/windows.js`.
// Until Wave 11C nothing on the SHIPPING page ever reached them: the only
// renderer-side caller of `overlay:update-status` and `review:show` anywhere in
// the repository was `app/src/renderer/main.js`, the LEGACY page. Signal Desk
// consumed the same voice-status stream itself (features/talkCapture.js and
// features/talkWorkspace.js) to drive its in-page ring and never forwarded it.
//
// Since the Wave 11 default flip, `signal-desk.html` is what every user loads.
// So the practical effect was a regression against legacy that no test could
// see, because the windows and their QA both worked: while dictating, a user got
// no floating overlay, and the Review Deck could not be opened at all. Wave 11B
// recorded that as `blocked (product)` for 21 parity rows and said the fix was a
// production caller rather than more QA. This is that caller.
//
// WHAT IT DELIBERATELY DOES NOT DO
// --------------------------------
// It owns no policy. Every show/hide decision for the capture overlay already
// lives in the main process (`ipc.js`'s `overlay:update-status`: interesting
// statuses show the window, transient ones auto-settle after `durationMs`, and
// idle with always-on off hides it). Duplicating any of that here would give the
// two pages two different overlay behaviours, which is exactly the drift this
// module exists to end. It forwards, and it forwards EVERY message — including
// the quiet ones — because the put-away path is driven by the statuses a
// "only forward the interesting ones" filter would drop.
//
// The label mapping below is copied from `main.js`'s `sendOverlayUpdate()`
// rather than reinvented, for the same reason: the overlay window is shared, so
// the two pages must speak to it in one vocabulary.

/** Statuses whose arrival means the Review Deck should be on screen with a draft. */
const REVIEW_SHOW_STATUSES = new Set(['preview_ready']);

/** Statuses after which the Review Deck must be re-pushed with the updated draft. */
const REVIEW_REFRESH_STATUSES = new Set(['draft_rewritten', 'draft_updated']);

/**
 * Statuses that end the review interaction. The Deck must come DOWN on these:
 * a draft-review window still floating on top after the draft was sent is worse
 * than one that never opened, because the user has to dismiss a surface that no
 * longer describes anything true.
 */
const REVIEW_HIDE_STATUSES = new Set(['draft_sent', 'emergency_stop']);

/**
 * The overlay-window payload for a voice-status message.
 *
 * Pure. Mirrors `app/src/renderer/main.js`'s `sendOverlayUpdate()` exactly --
 * same statuses, same labels -- so the capture overlay reads identically
 * whichever dashboard is loaded.
 *
 * @param {object|string} message A voice-status message, or a bare status string.
 * @returns {object|null} `{status, message, fallback}` (+ `amplitude` when the
 *   payload carried one), or null when there is nothing to forward.
 */
export function overlayPayloadFor(message) {
  if (typeof message === 'string') {
    return { status: message, message: '', fallback: false };
  }
  if (!message || typeof message !== 'object') {
    return null;
  }

  const status = message.status || 'unknown';
  const sendResult = message.send_result;
  const payload = {
    status,
    message: message.message || sendResult?.message || message.error || '',
    fallback: Boolean(sendResult?.fallback),
  };

  if (status === 'preview_ready') {
    payload.message = 'Draft ready';
  } else if (status === 'draft_sent' && sendResult?.fallback) {
    payload.message = 'Copied as fallback';
  } else if (status === 'draft_sent') {
    payload.message = 'Sent';
  } else if (status === 'draft_send_error') {
    payload.message = sendResult?.message || 'Send failed';
  } else if (status === 'draft_blocked') {
    payload.message = message.error || 'No usable audio';
  } else if (status === 'draft_error') {
    payload.message = message.error || 'Draft failed';
  } else if (status === 'long_recording_detected') {
    payload.message = 'Long recording…';
  } else if (status === 'chunking_started') {
    payload.message = message.chunk_count ? `Processing ${message.chunk_count} chunks` : 'Processing…';
  } else if (status === 'chunking_progress') {
    payload.message = `Chunk ${message.chunk_index} of ${message.chunk_count}`;
  } else if (status === 'chunking_stitching') {
    payload.message = 'Smoothing…';
  } else if (status === 'selection_capture_failed') {
    payload.message = message.message || 'Selection unavailable';
  } else if (status === 'emergency_stop') {
    payload.message = message.message || 'Stopped';
  }

  // Live mic amplitude rides along on the recording payload; the main process
  // clamps it, but dropping it here would silently kill the ring's pulse.
  if (typeof message.amplitude === 'number' && Number.isFinite(message.amplitude)) {
    payload.amplitude = message.amplitude;
  }

  return payload;
}

/**
 * The draft object a `preview_ready` message describes.
 *
 * Pure. Same field set `main.js` builds before calling `showReviewOverlay`, so
 * the Deck receives the same shape on both pages. Returns null when the message
 * carries no draft id -- the Deck renders "Waiting for draft" for a null draft,
 * and opening a window to show that is worse than not opening it.
 */
export function draftFromStatusMessage(message) {
  if (!message || typeof message !== 'object' || !message.draft_id) {
    return null;
  }
  return {
    id: message.draft_id,
    raw_text: message.raw_text,
    final_text: message.final_text,
    status: 'pending',
    error: message.error ?? '',
    gate_reasons: message.gate_reasons ?? [],
    token_count: message.token_count,
    token_limit: message.token_limit,
    long_text: message.long_text,
    confidence: message.confidence,
    auto_send_ok: message.auto_send_ok,
    force_review: message.force_review,
    force_review_reason: message.force_review_reason,
  };
}

/**
 * What the Review Deck should do about a voice-status message.
 *
 * Pure. `'show'` carries the draft built from the message; `'refresh'` means the
 * caller must fetch the current draft first (the rewrite/edit statuses do not
 * carry one); `'hide'` is the put-away path; null means leave it alone.
 *
 * @returns {{action: 'show'|'refresh'|'hide', draft?: object}|null}
 */
export function reviewIntentFor(message) {
  const status = typeof message === 'string' ? message : message?.status;
  if (!status) return null;

  if (REVIEW_SHOW_STATUSES.has(status)) {
    const draft = draftFromStatusMessage(message);
    return draft ? { action: 'show', draft } : null;
  }
  if (REVIEW_REFRESH_STATUSES.has(status)) {
    return { action: 'refresh' };
  }
  if (REVIEW_HIDE_STATUSES.has(status)) {
    return { action: 'hide' };
  }
  return null;
}

/**
 * @param {object} deps
 * @param {object} deps.bridge The preload surface -- `window.betterFingers`.
 *   Every call is optional-chained and feature-detected, so a page loaded
 *   without the bridge (unit tests, a stripped preload) degrades to a no-op
 *   instead of throwing inside the voice-status callback and taking the rest of
 *   the stream's consumers down with it.
 * @param {object} deps.hooks
 * @param {Function} [deps.hooks.getLatestDraft] `() => Promise<draft|null>` --
 *   used for the `'refresh'` intent. Supplied by the composition root from the
 *   drafts feature so this module owns no fetching of its own.
 * @param {Function} [deps.hooks.onError] Called with (error, message) when a
 *   forward rejects. Nothing user-facing: a failed forward must never surface as
 *   a toast, because the overlay is a secondary display of state the page is
 *   already showing.
 */
export function createOverlayBridgeFeature({ bridge, hooks } = {}) {
  const api = bridge || null;
  const hks = hooks || {};
  let reviewVisible = false;

  function isFn(value) {
    return typeof value === 'function';
  }

  function report(error, message) {
    try {
      hks.onError?.(error, message);
    } catch (_e) {
      /* a reporting hook must never become the failure it reports */
    }
  }

  function pushOverlayStatus(message) {
    if (!api || !isFn(api.updateOverlayStatus)) return;
    const payload = overlayPayloadFor(message);
    if (!payload) return;
    Promise.resolve(api.updateOverlayStatus(payload)).catch((error) => report(error, message));
  }

  function showReview(draft) {
    if (!api || !isFn(api.showReviewOverlay) || !draft?.id) return;
    reviewVisible = true;
    Promise.resolve(api.showReviewOverlay(draft)).catch((error) => report(error, draft));
  }

  function hideReview() {
    if (!api || !isFn(api.hideReviewOverlay)) return;
    // Unconditional, not `if (reviewVisible)`: this module's belief about
    // visibility can be wrong (the user can close the Deck from its own button,
    // which this page never hears about), and hiding an already-hidden window is
    // a no-op in the main process while failing to hide a visible one strands it.
    reviewVisible = false;
    Promise.resolve(api.hideReviewOverlay()).catch((error) => report(error, null));
  }

  async function refreshReview() {
    // Only re-push a rewrite into a Deck that is actually up. A rewrite driven
    // from the Talk workspace must not conjure a floating window the user did
    // not ask for -- they are already looking at the draft in-page.
    if (!reviewVisible || !isFn(hks.getLatestDraft)) return;
    try {
      const draft = await hks.getLatestDraft();
      if (draft?.id) showReview(draft);
    } catch (error) {
      report(error, null);
    }
  }

  /**
   * Forward one voice-status message to both windows. Never throws: it runs
   * inside the shared voice-status callback alongside talkWorkspace and
   * talkCapture, and an exception here would stop the ring and the action row
   * from updating too.
   */
  function handleVoiceStatusMessage(message) {
    try {
      pushOverlayStatus(message);
      const intent = reviewIntentFor(message);
      if (!intent) return;
      if (intent.action === 'show') showReview(intent.draft);
      else if (intent.action === 'hide') hideReview();
      else if (intent.action === 'refresh') refreshReview();
    } catch (error) {
      report(error, message);
    }
  }

  /** True when this module last asked for the Review Deck and has not put it away. */
  function isReviewOpen() {
    return reviewVisible;
  }

  function destroy() {
    // Leaving the Deck up after the page tears down would strand an always-on-top
    // window with no owner.
    hideReview();
  }

  return { handleVoiceStatusMessage, showReview, hideReview, isReviewOpen, destroy };
}
