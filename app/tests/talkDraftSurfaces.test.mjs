// Talk -> the draft card's read-outs and the controls beside it, driven
// through the real DOM wiring.
//
// CURRENT_UI_INVENTORY.md section 6.3 (parity rows UI-06-014, UI-06-018,
// UI-06-022, UI-06-029, UI-06-032, UI-06-037, UI-06-041 and UI-14-005). These
// are the badge, the capture status line, the token summary, the recording
// metadata, the custom-rewrite input, Read Full and Retry -- the strip a user
// reads to decide whether to trust a draft. Their view models already had unit
// coverage; what nothing exercised was that the production ids reach them.
//
// talkDrafts.js's buildTalkDrafts() is used as-is rather than re-listing the
// element map here: it is the exact call signalDeskApp.js makes, so the test
// fails if the page's ids and the drafts feature drift apart.
//
// Run with: node --test app/tests/talkDraftSurfaces.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { buildTalkDrafts, collectTalkDraftElements } from '../src/renderer/talkDrafts.js';
import {
  TALK_CAPTURE_ELEMENT_IDS,
  collectTalkCaptureElements,
  createTalkCaptureFeature,
} from '../src/renderer/features/talkCapture.js';
import {
  TALK_ELEMENT_IDS,
  collectTalkElements,
  createTalkWorkspaceFeature,
} from '../src/renderer/features/talkWorkspace.js';
import { makeDocument, makeBackendBridge, installDomGlobals } from './helpers/rendererDom.mjs';

const DRAFT_IDS = [
  'sdRefinedHero',
  'sdRawTranscriptText',
  'sdDraftMessage',
  'sdDraftMetadata',
  'sdDraftTokenSummary',
  'sdAcceptButton',
  'sdDeclineButton',
  'sdRetryButton',
  'sdCopyButton',
  'sdSaveEditButton',
  'sdRewriteShorterButton',
  'sdRewriteClearerButton',
  'sdRewriteToneButton',
  'sdRewriteCustomButton',
  'sdCustomRewriteInstruction',
  'sdReadSelectionButton',
  'sdReadFullButton',
  'sdDeliveryType',
];

const CARD_IDS = ['sdRefinedBadge', 'sdConfidenceValue', 'sdConfidenceBarFill'];
const CAPTURE_IDS = ['sdCaptureMessage', 'sdCaptureStartButton', 'sdCaptureStopButton', 'sdEmergencyStopButton'];

test('the Talk ids this file drives are the ids the shipping modules ship', () => {
  assert.equal(TALK_ELEMENT_IDS.refinedBadge, 'sdRefinedBadge');
  assert.equal(TALK_CAPTURE_ELEMENT_IDS.statusMessage, 'sdCaptureMessage');

  // The draft element map is built by production code, so assert the ids it
  // reaches for rather than a copy of them.
  const doc = makeDocument(DRAFT_IDS);
  const els = collectTalkDraftElements(doc);
  assert.equal(els.draftTokenSummaryEl, doc.getElementById('sdDraftTokenSummary'));
  assert.equal(els.draftMetadataEl, doc.getElementById('sdDraftMetadata'));
  assert.equal(els.retryDraftButton, doc.getElementById('sdRetryButton'));
  assert.equal(els.readFullDraftButton, doc.getElementById('sdReadFullButton'));
  assert.equal(els.customRewriteInstructionEl, doc.getElementById('sdCustomRewriteInstruction'));
});

const READY_DRAFT = {
  id: 'd-1',
  status: 'pending',
  final_text: 'Ship it on Thursday.',
  raw_text: 'ship it on thursday',
  confidence: { score: 0.82 },
  token_count: 120,
  token_limit: 4096,
  metadata: {
    duration_seconds: 3.4,
    stop_reason: 'silence',
    rms_amplitude: 0.02,
    max_amplitude: 0.4,
    sample_count: 54400,
    sample_rate: 16000,
  },
};

function mountDrafts({ routes = {} } = {}) {
  const doc = makeDocument(DRAFT_IDS, {
    sdRefinedHero: { tagName: 'textarea', value: '' },
    sdCustomRewriteInstruction: { tagName: 'input', type: 'text' },
    sdDeliveryType: { tagName: 'select', value: '' },
    sdToastContainer: { tagName: 'div' },
  });
  const bridge = makeBackendBridge(routes);
  const restore = installDomGlobals({ document: doc, betterFingers: { backendRequest: bridge.request } });
  const drafts = buildTalkDrafts(doc);
  return { doc, drafts, bridge, restore, el: (id) => doc.getElementById(id) };
}

// --- UI-06-022: the token summary --------------------------------------------

test('#sdDraftTokenSummary reports the count against the limit, and warns as it approaches it', async (t) => {
  const ctx = mountDrafts();
  t.after(ctx.restore);
  const summary = ctx.el('sdDraftTokenSummary');

  ctx.drafts.renderTokenSummary({ token_count: 120, token_limit: 4096 });
  assert.equal(summary.textContent, '120 / 4096 tokens');
  assert.equal(summary.dataset.state, undefined, 'a draft inside the limit carries no warning state');

  ctx.drafts.renderTokenSummary({ token_count: 5000, token_limit: 4096 });
  assert.equal(summary.textContent, '5000 / 4096 tokens · long text');
  assert.equal(summary.dataset.state, 'warning', 'a draft over the limit must say so before the send fails');
});

test('#sdDraftTokenSummary shows a real zero rather than going blank with no draft', async (t) => {
  const ctx = mountDrafts();
  t.after(ctx.restore);
  ctx.drafts.renderTokenSummary(null);
  assert.equal(ctx.el('sdDraftTokenSummary').textContent, '0 tokens');
});

// --- UI-06-041: the recording metadata line ----------------------------------

test('#sdDraftMetadata states the recording duration and stop reason, with the raw telemetry in its title', async (t) => {
  const ctx = mountDrafts();
  t.after(ctx.restore);
  ctx.drafts.renderDraft(READY_DRAFT);

  const metadata = ctx.el('sdDraftMetadata');
  assert.match(metadata.textContent, /^3\.4s recording · /);
  assert.match(
    metadata.getAttribute('title'),
    /samples 54400 @ 16000 Hz/,
    'the raw acoustic telemetry belongs in the tooltip, not in the visible line',
  );
});

test('#sdDraftMetadata says there is no recording metadata rather than leaving a stale line', async (t) => {
  const ctx = mountDrafts();
  t.after(ctx.restore);
  ctx.drafts.renderDraft(READY_DRAFT);
  ctx.drafts.renderDraft(null);
  assert.equal(ctx.el('sdDraftMetadata').textContent, 'No recording metadata yet.');
  assert.equal(ctx.el('sdDraftMetadata').getAttribute('title'), null, 'the stale telemetry tooltip must be removed too');
});

// --- UI-06-029 / UI-06-032: the revise drawer's input and Read Full ----------

test('#sdCustomRewriteInstruction and #sdReadFullButton are disabled until there is a draft to act on', async (t) => {
  const ctx = mountDrafts();
  t.after(ctx.restore);

  ctx.drafts.renderDraft(null);
  assert.equal(ctx.el('sdCustomRewriteInstruction').disabled, true);
  assert.equal(ctx.el('sdReadFullButton').disabled, true);

  ctx.drafts.renderDraft(READY_DRAFT);
  ctx.drafts.setDraftControlsEnabled(true);
  assert.equal(ctx.el('sdCustomRewriteInstruction').disabled, false);
  assert.equal(ctx.el('sdReadFullButton').disabled, false, 'Read Full is available once there is text to read');
});

test('#sdReadFullButton stays disabled on an empty draft even when controls are enabled', async (t) => {
  const ctx = mountDrafts();
  t.after(ctx.restore);
  ctx.drafts.renderDraft({ ...READY_DRAFT, final_text: '' });
  ctx.drafts.setDraftControlsEnabled(true);
  assert.equal(ctx.el('sdReadFullButton').disabled, true, 'there is nothing to read aloud');
  assert.equal(ctx.el('sdCustomRewriteInstruction').disabled, false, 'but an empty draft can still be given an instruction');
});

// --- UI-06-037: Retry -> POST /drafts/:id/retry ------------------------------

test('#sdRetryButton retries the current draft by id and reports the outcome', async (t) => {
  const ctx = mountDrafts({
    routes: {
      'POST /drafts/d-1/retry': { id: 'd-2', status: 'pending', final_text: '' },
      'GET /drafts': { drafts: [] },
    },
  });
  t.after(ctx.restore);
  ctx.drafts.renderDraft({ ...READY_DRAFT, status: 'error' });

  await ctx.drafts.handleRetryClick();

  assert.ok(ctx.bridge.find('POST', '/drafts/d-1/retry'), 'Retry must name the draft it is retrying');
  assert.equal(ctx.el('sdRetryButton').textContent, 'Retry', 'the button label must be restored, not left on "Retrying..."');
  assert.equal(ctx.el('sdDraftMessage').textContent, 'Retry created a new draft.');
});

test('#sdRetryButton reports a failed retry and does not claim a new draft', async (t) => {
  const ctx = mountDrafts({
    routes: { 'POST /drafts/d-1/retry': { ok: false, status: 500, body: { detail: 'the model is unavailable' } } },
  });
  t.after(ctx.restore);
  ctx.drafts.renderDraft({ ...READY_DRAFT, status: 'error' });

  await ctx.drafts.handleRetryClick();
  assert.equal(ctx.el('sdDraftMessage').textContent, 'Retry failed: the model is unavailable');
  assert.equal(ctx.el('sdRetryButton').textContent, 'Retry');
});

test('#sdRetryButton does nothing at all when there is no draft', async (t) => {
  const ctx = mountDrafts();
  t.after(ctx.restore);
  await ctx.drafts.handleRetryClick();
  assert.deepEqual(ctx.bridge.signatures(), []);
});

// --- UI-06-014 / UI-14-005: the refined-message badge ------------------------

test('#sdRefinedBadge carries the draft state as both text and a single variant class', async (t) => {
  const doc = makeDocument([...DRAFT_IDS, ...CARD_IDS], { sdRefinedHero: { tagName: 'div' } });
  const restore = installDomGlobals({ document: doc, betterFingers: {} });
  t.after(restore);
  const talk = createTalkWorkspaceFeature({ elements: collectTalkElements(doc), hooks: {} });

  const badge = doc.getElementById('sdRefinedBadge');
  talk.renderRefinedCard(READY_DRAFT);
  const readyClasses = badge.className.split(' ').filter((c) => c.startsWith('sd-badge--'));
  assert.equal(readyClasses.length, 1, 'exactly one state class at a time, or the badge shows two states at once');
  assert.notEqual(badge.textContent, '');

  talk.renderRefinedCard({ ...READY_DRAFT, status: 'error' });
  const errorClasses = badge.className.split(' ').filter((c) => c.startsWith('sd-badge--'));
  assert.equal(errorClasses.length, 1);
  assert.notDeepEqual(errorClasses, readyClasses, 'an errored draft must not look like a ready one');
});

test('#sdConfidenceValue is the production home of the confidence read-out', async (t) => {
  // The legacy #draftConfidence badge has no element on the shipping page; the
  // meta strip's value and bar are what a user actually sees. Asserted here so
  // the replacement is evidenced rather than assumed -- see WAVE11_BLOCKERS.md.
  const doc = makeDocument([...DRAFT_IDS, ...CARD_IDS], { sdRefinedHero: { tagName: 'div' } });
  const restore = installDomGlobals({ document: doc, betterFingers: {} });
  t.after(restore);
  const talk = createTalkWorkspaceFeature({ elements: collectTalkElements(doc), hooks: {} });

  talk.renderRefinedCard(READY_DRAFT);
  assert.equal(doc.getElementById('sdConfidenceValue').textContent, '82%');
  assert.equal(doc.getElementById('sdConfidenceBarFill').style.width, '82%');

  talk.renderRefinedCard({ ...READY_DRAFT, confidence: null });
  assert.equal(doc.getElementById('sdConfidenceValue').textContent, '—', 'an unknown score must read as unknown, not as zero');
  assert.equal(doc.getElementById('sdConfidenceBarFill').style.width, '0%');
});

// --- UI-06-018: the capture status line --------------------------------------

test('#sdCaptureMessage tracks the capture state machine and surfaces its hints', async (t) => {
  const doc = makeDocument(CAPTURE_IDS);
  const restore = installDomGlobals({ document: doc, betterFingers: {} });
  t.after(restore);
  const capture = createTalkCaptureFeature({ elements: collectTalkCaptureElements(doc), hooks: {} });
  capture.init?.();

  const message = doc.getElementById('sdCaptureMessage');
  const idle = message.textContent;

  capture.handleVoiceStatusMessage({ status: 'recording' });
  assert.notEqual(message.textContent, idle, 'the status line must change when recording starts');
  const recording = message.textContent;

  capture.handleVoiceStatusMessage({ status: 'error', message: 'Hotkey hook failed to register.' });
  assert.notEqual(message.textContent, recording);
  assert.notEqual(message.textContent, '', 'an error state must never leave the line blank');
});
