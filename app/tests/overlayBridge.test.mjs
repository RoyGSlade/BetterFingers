// Unit tests for the production caller of the two floating windows
// (features/overlayBridge.js) -- Wave 11C's fix for the B-2/C-2 product gap:
// `overlay:update-status` and `review:show` had no caller on the shipping page.
//
// The behaviour that actually matters here is not "does it forward" but "does it
// PUT THE WINDOWS AWAY". An always-on-top surface that fails to release is worse
// than one that never appeared, so the hide paths get as much coverage as the
// show paths.
//
// Run with: node --test app/tests/overlayBridge.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  overlayPayloadFor,
  draftFromStatusMessage,
  reviewIntentFor,
  createOverlayBridgeFeature,
} from '../src/renderer/features/overlayBridge.js';

function makeBridge() {
  const calls = { status: [], show: [], hide: 0 };
  return {
    calls,
    updateOverlayStatus(payload) { calls.status.push(payload); return Promise.resolve(true); },
    showReviewOverlay(draft) { calls.show.push(draft); return Promise.resolve(true); },
    hideReviewOverlay() { calls.hide += 1; return Promise.resolve(true); },
  };
}

const PREVIEW = {
  status: 'preview_ready',
  draft_id: 7,
  raw_text: 'so uh can you look at the deploy',
  final_text: 'Could you look at the deploy?',
  confidence: { score: 0.91 },
};

// --- overlayPayloadFor -------------------------------------------------------

test('overlayPayloadFor: a bare status string is forwarded as a status', () => {
  assert.deepEqual(overlayPayloadFor('recording'), {
    status: 'recording',
    message: '',
    fallback: false,
  });
});

test('overlayPayloadFor: nothing forwardable resolves to null rather than a junk payload', () => {
  assert.equal(overlayPayloadFor(null), null);
  assert.equal(overlayPayloadFor(undefined), null);
  assert.equal(overlayPayloadFor(42), null);
});

test('overlayPayloadFor: the label vocabulary matches the legacy page exactly', () => {
  // These strings are the contract with overlay.html, which is shared by both
  // dashboards -- a drift here means the same pipeline state reads differently
  // depending on which page happens to be loaded.
  assert.equal(overlayPayloadFor({ status: 'preview_ready' }).message, 'Draft ready');
  assert.equal(overlayPayloadFor({ status: 'draft_sent' }).message, 'Sent');
  assert.equal(
    overlayPayloadFor({ status: 'draft_sent', send_result: { fallback: true } }).message,
    'Copied as fallback',
  );
  assert.equal(
    overlayPayloadFor({ status: 'draft_send_error', send_result: { message: 'no window' } }).message,
    'no window',
  );
  assert.equal(overlayPayloadFor({ status: 'draft_blocked', error: 'silence' }).message, 'silence');
  assert.equal(overlayPayloadFor({ status: 'draft_error' }).message, 'Draft failed');
  assert.equal(
    overlayPayloadFor({ status: 'draft_error', message: 'Selected-text rewrite failed. Try again.' }).message,
    'Selected-text rewrite failed. Try again.',
  );
  assert.equal(overlayPayloadFor({ status: 'long_recording_detected' }).message, 'Long recording…');
  assert.equal(overlayPayloadFor({ status: 'chunking_started', chunk_count: 5 }).message, 'Processing 5 chunks');
  assert.equal(
    overlayPayloadFor({ status: 'chunking_progress', chunk_index: 2, chunk_count: 5 }).message,
    'Chunk 2 of 5',
  );
  assert.equal(overlayPayloadFor({ status: 'chunking_stitching' }).message, 'Smoothing…');
  assert.equal(overlayPayloadFor({ status: 'emergency_stop' }).message, 'Stopped');
});

test('overlayPayloadFor: the fallback flag survives, because it changes the ring colour', () => {
  assert.equal(overlayPayloadFor({ status: 'draft_sent', send_result: { fallback: true } }).fallback, true);
  assert.equal(overlayPayloadFor({ status: 'draft_sent' }).fallback, false);
});

test('overlayPayloadFor: live amplitude is carried through, and only when it is a real number', () => {
  assert.equal(overlayPayloadFor({ status: 'recording', amplitude: 0.62 }).amplitude, 0.62);
  assert.equal('amplitude' in overlayPayloadFor({ status: 'recording' }), false);
  assert.equal('amplitude' in overlayPayloadFor({ status: 'recording', amplitude: 'loud' }), false);
  assert.equal('amplitude' in overlayPayloadFor({ status: 'recording', amplitude: NaN }), false);
});

// --- draftFromStatusMessage --------------------------------------------------

test('draftFromStatusMessage: a message with no draft id yields no draft', () => {
  // Opening the Deck on a null draft would show "Waiting for draft" on top of
  // everything, which is worse than not opening it.
  assert.equal(draftFromStatusMessage({ status: 'preview_ready' }), null);
  assert.equal(draftFromStatusMessage(null), null);
});

test('draftFromStatusMessage: carries the fields the Deck actually renders', () => {
  const draft = draftFromStatusMessage(PREVIEW);
  assert.equal(draft.id, 7);
  assert.equal(draft.raw_text, PREVIEW.raw_text);
  assert.equal(draft.final_text, PREVIEW.final_text);
  assert.equal(draft.status, 'pending');
  assert.deepEqual(draft.confidence, { score: 0.91 });
  assert.deepEqual(draft.gate_reasons, []);
});

// --- reviewIntentFor ---------------------------------------------------------

test('reviewIntentFor: preview_ready shows, terminal statuses hide, rewrites refresh', () => {
  assert.equal(reviewIntentFor(PREVIEW).action, 'show');
  assert.equal(reviewIntentFor({ status: 'draft_sent' }).action, 'hide');
  assert.equal(reviewIntentFor({ status: 'emergency_stop' }).action, 'hide');
  assert.equal(reviewIntentFor({ status: 'draft_rewritten' }).action, 'refresh');
  assert.equal(reviewIntentFor({ status: 'draft_updated' }).action, 'refresh');
});

test('reviewIntentFor: an ordinary pipeline status leaves the Deck alone', () => {
  assert.equal(reviewIntentFor({ status: 'recording' }), null);
  assert.equal(reviewIntentFor({ status: 'transcribing' }), null);
  assert.equal(reviewIntentFor(null), null);
});

// --- createOverlayBridgeFeature ----------------------------------------------

test('every voice-status message reaches the capture overlay, quiet ones included', async () => {
  // The put-away path is driven by exactly the statuses a "forward only the
  // interesting ones" filter would drop, so this is the assertion that stops
  // the overlay being stranded.
  const bridge = makeBridge();
  const feature = createOverlayBridgeFeature({ bridge });

  feature.handleVoiceStatusMessage({ status: 'recording' });
  feature.handleVoiceStatusMessage({ status: 'transcribing' });
  feature.handleVoiceStatusMessage({ status: 'idle' });

  assert.deepEqual(bridge.calls.status.map((p) => p.status), ['recording', 'transcribing', 'idle']);
});

test('preview_ready opens the Review Deck with the draft the message describes', async () => {
  const bridge = makeBridge();
  const feature = createOverlayBridgeFeature({ bridge });

  feature.handleVoiceStatusMessage(PREVIEW);

  assert.equal(bridge.calls.show.length, 1);
  assert.equal(bridge.calls.show[0].id, 7);
  assert.equal(feature.isReviewOpen(), true);
  // The capture overlay is told about it too -- both windows see the same stream.
  assert.equal(bridge.calls.status.at(-1).message, 'Draft ready');
});

test('preview_ready with no draft id opens nothing', async () => {
  const bridge = makeBridge();
  const feature = createOverlayBridgeFeature({ bridge });
  feature.handleVoiceStatusMessage({ status: 'preview_ready' });
  assert.equal(bridge.calls.show.length, 0);
  assert.equal(feature.isReviewOpen(), false);
});

test('draft_sent and emergency_stop put the Review Deck away', async () => {
  for (const status of ['draft_sent', 'emergency_stop']) {
    const bridge = makeBridge();
    const feature = createOverlayBridgeFeature({ bridge });
    feature.handleVoiceStatusMessage(PREVIEW);
    assert.equal(feature.isReviewOpen(), true, `${status}: precondition -- Deck is up`);

    feature.handleVoiceStatusMessage({ status });
    assert.equal(bridge.calls.hide, 1, `${status} must hide the Deck`);
    assert.equal(feature.isReviewOpen(), false);
  }
});

test('hide is unconditional, because this page cannot see the Deck being closed from its own button', async () => {
  const bridge = makeBridge();
  const feature = createOverlayBridgeFeature({ bridge });
  // Never opened by us -- a stale belief must not stop the put-away.
  feature.handleVoiceStatusMessage({ status: 'draft_sent' });
  assert.equal(bridge.calls.hide, 1);
});

test('destroy() puts the Deck away so teardown cannot strand an always-on-top window', async () => {
  const bridge = makeBridge();
  const feature = createOverlayBridgeFeature({ bridge });
  feature.handleVoiceStatusMessage(PREVIEW);
  feature.destroy();
  assert.equal(bridge.calls.hide, 1);
  assert.equal(feature.isReviewOpen(), false);
});

test('a rewrite re-pushes the refreshed draft ONLY into a Deck that is already up', async () => {
  const bridge = makeBridge();
  let fetches = 0;
  const feature = createOverlayBridgeFeature({
    bridge,
    hooks: {
      getLatestDraft: async () => {
        fetches += 1;
        return { id: 7, final_text: 'Please review the deploy.' };
      },
    },
  });

  // Deck closed: a rewrite driven from the Talk workspace must not conjure a
  // floating window the user never asked for.
  feature.handleVoiceStatusMessage({ status: 'draft_rewritten' });
  await new Promise((r) => setImmediate(r));
  assert.equal(fetches, 0);
  assert.equal(bridge.calls.show.length, 0);

  // Deck open: the same status now re-renders it with the rewritten text.
  feature.handleVoiceStatusMessage(PREVIEW);
  feature.handleVoiceStatusMessage({ status: 'draft_rewritten' });
  await new Promise((r) => setImmediate(r));
  assert.equal(fetches, 1);
  assert.equal(bridge.calls.show.length, 2);
  assert.equal(bridge.calls.show[1].final_text, 'Please review the deploy.');
});

test('a missing or broken bridge degrades to a no-op instead of killing the voice stream', async () => {
  // This runs inside the shared voice-status callback alongside talkWorkspace
  // and talkCapture: a throw here would stop the in-page ring updating too.
  assert.doesNotThrow(() => {
    createOverlayBridgeFeature({}).handleVoiceStatusMessage(PREVIEW);
    createOverlayBridgeFeature({ bridge: {} }).handleVoiceStatusMessage(PREVIEW);
    createOverlayBridgeFeature({ bridge: null }).destroy();
  });
});

test('a rejected forward is reported, never thrown', async () => {
  const errors = [];
  const feature = createOverlayBridgeFeature({
    bridge: {
      updateOverlayStatus: () => Promise.reject(new Error('ipc gone')),
      showReviewOverlay: () => Promise.resolve(true),
      hideReviewOverlay: () => Promise.resolve(true),
    },
    hooks: { onError: (error) => errors.push(error.message) },
  });

  assert.doesNotThrow(() => feature.handleVoiceStatusMessage({ status: 'recording' }));
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(errors, ['ipc gone']);
});

test('a getLatestDraft that rejects is reported and does not re-push', async () => {
  const bridge = makeBridge();
  const errors = [];
  const feature = createOverlayBridgeFeature({
    bridge,
    hooks: {
      getLatestDraft: async () => { throw new Error('offline'); },
      onError: (error) => errors.push(error.message),
    },
  });

  feature.handleVoiceStatusMessage(PREVIEW);
  feature.handleVoiceStatusMessage({ status: 'draft_rewritten' });
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(errors, ['offline']);
  assert.equal(bridge.calls.show.length, 1);
});
