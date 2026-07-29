// Unit tests for the extracted renderer draft feature (Phase 1, A1.3), plus
// Wave 12 collab coverage for resilient list loading (Task A) and cold-start /
// health-poll repopulate safety (Task B). See loadPersonaList's doc comment in
// bootstrap/signalDeskApp.js for the house standard these mirror.
// Run with: node --test app/tests/drafts-feature.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { formatDraftMetadata, formatDraftMetadataDetail, createDraftsFeature } from '../src/renderer/features/drafts.js';
import { makeDocument, makeBackendBridge, installDomGlobals } from './helpers/rendererDom.mjs';

test('formatDraftMetadata: no metadata', () => {
  assert.equal(formatDraftMetadata(null), 'No recording metadata available.');
  assert.equal(formatDraftMetadata({}), 'No recording metadata available.');
  assert.equal(formatDraftMetadata({ metadata: {} }), 'No recording metadata available.');
});

test('formatDraftMetadata: duration + known stop reason label', () => {
  const draft = { metadata: { duration_seconds: 12.345, stop_reason: 'silence' } };
  assert.equal(formatDraftMetadata(draft), '12.3s recording · auto-stopped on silence');
});

test('formatDraftMetadata: unknown stop reason falls back to the raw value', () => {
  const draft = { metadata: { duration_seconds: 1, stop_reason: 'weird_reason' } };
  assert.equal(formatDraftMetadata(draft), '1.0s recording · weird_reason');
});

test('formatDraftMetadataDetail: no metadata is empty string', () => {
  assert.equal(formatDraftMetadataDetail(null), '');
  assert.equal(formatDraftMetadataDetail({ metadata: {} }), '');
});

test('formatDraftMetadataDetail: formats acoustic telemetry', () => {
  const draft = {
    metadata: {
      rms_amplitude: 0.012345,
      max_amplitude: 0.98765,
      sample_count: 44100,
      sample_rate: 16000,
    },
  };
  assert.equal(
    formatDraftMetadataDetail(draft),
    'samples 44100 @ 16000 Hz · peak 0.98765 · rms 0.01235',
  );
});

// --- createDraftsFeature: resilient loading (Task A) + repopulate safety (Task B) --

const ELEMENT_IDS = [
  'draftFinalText', 'draftStatus', 'draftRawText', 'draftMessage', 'draftMetadata',
  'draftTokenSummary', 'saveDraftEdit', 'rewriteShorter', 'rewriteClearer', 'rewriteTone',
  'rewriteCustom', 'customRewriteInstruction', 'readSelection', 'readFullDraft', 'copyDraft',
  'acceptDraft', 'declineDraft', 'retryDraft', 'sendDraft', 'draftHistoryList',
];

const READY_DRAFT = {
  id: 'd-1',
  status: 'pending',
  final_text: 'Ship it on Thursday.',
  raw_text: 'ship it on thursday',
  confidence: { score: 0.82 },
  token_count: 4,
  token_limit: 4096,
};

function mountDrafts({ routes = {} } = {}) {
  const doc = makeDocument(ELEMENT_IDS, {
    draftFinalText: { tagName: 'textarea', value: '' },
    draftHistoryList: { tagName: 'div' },
  });
  const bridge = makeBackendBridge(routes);
  const restore = installDomGlobals({ document: doc, betterFingers: { backendRequest: bridge.request } });
  const els = {
    draftFinalTextEl: doc.getElementById('draftFinalText'),
    draftStatusEl: doc.getElementById('draftStatus'),
    draftRawTextEl: doc.getElementById('draftRawText'),
    draftMessageEl: doc.getElementById('draftMessage'),
    draftMetadataEl: doc.getElementById('draftMetadata'),
    draftTokenSummaryEl: doc.getElementById('draftTokenSummary'),
    saveDraftEditButton: doc.getElementById('saveDraftEdit'),
    rewriteShorterButton: doc.getElementById('rewriteShorter'),
    rewriteClearerButton: doc.getElementById('rewriteClearer'),
    rewriteToneButton: doc.getElementById('rewriteTone'),
    rewriteCustomButton: doc.getElementById('rewriteCustom'),
    customRewriteInstructionEl: doc.getElementById('customRewriteInstruction'),
    readSelectionButton: doc.getElementById('readSelection'),
    readFullDraftButton: doc.getElementById('readFullDraft'),
    copyDraftButton: doc.getElementById('copyDraft'),
    acceptDraftButton: doc.getElementById('acceptDraft'),
    declineDraftButton: doc.getElementById('declineDraft'),
    retryDraftButton: doc.getElementById('retryDraft'),
    sendDraftButton: doc.getElementById('sendDraft'),
    draftHistoryListEl: doc.getElementById('draftHistoryList'),
  };
  const drafts = createDraftsFeature({
    elements: els,
    ui: {
      setMessage: (el, message = '', tone = '') => {
        if (!el) return;
        el.textContent = message;
        if (tone) el.dataset.tone = tone; else delete el.dataset.tone;
      },
      showToast: () => {},
      escapeHtml: (v) => String(v ?? ''),
      renderSendResult: () => {},
    },
    hooks: {
      getSelectedSendAction: () => 'copy_only',
      gatherVoiceStudioSettings: () => ({}),
      onDraftEdited: async () => {},
      refreshOutputSettings: async () => {},
    },
  });
  return { doc, drafts, bridge, restore, el: (id) => doc.getElementById(id) };
}

const TIMEOUT_FAILURE = { ok: false, status: 0, error: 'timeout' };

test('refreshLatestDraft retries once before giving up on a slow/failed first response', async (t) => {
  let attempts = 0;
  const ctx = mountDrafts({
    routes: {
      'GET /drafts/latest': () => {
        attempts += 1;
        return attempts === 1 ? TIMEOUT_FAILURE : { draft: READY_DRAFT };
      },
    },
  });
  t.after(ctx.restore);

  const result = await ctx.drafts.refreshLatestDraft();
  assert.equal(attempts, 2, 'a slow first response must be retried once, not surfaced as a permanent failure');
  assert.equal(result.id, READY_DRAFT.id);
  assert.equal(ctx.el('draftFinalText').value, READY_DRAFT.final_text);
});

test('refreshLatestDraft keeps the last-good draft on screen when both attempts fail', async (t) => {
  const ctx = mountDrafts({ routes: { 'GET /drafts/latest': TIMEOUT_FAILURE } });
  t.after(ctx.restore);
  ctx.drafts.renderDraft(READY_DRAFT);

  const result = await ctx.drafts.refreshLatestDraft();
  assert.equal(result.id, READY_DRAFT.id, 'the previously shown draft must be returned unchanged, not blanked');
  assert.equal(ctx.el('draftFinalText').value, READY_DRAFT.final_text, 'the editor must not be wiped by a failed refresh');
  assert.equal(ctx.el('draftStatus').textContent, 'pending', 'a fetch failure must not present as "No draft yet"');
});

test('refreshLatestDraft reports the failure honestly when nothing was loaded yet, instead of silently looking like "no draft"', async (t) => {
  const ctx = mountDrafts({ routes: { 'GET /drafts/latest': TIMEOUT_FAILURE } });
  t.after(ctx.restore);

  const result = await ctx.drafts.refreshLatestDraft();
  assert.equal(result, null);
  assert.match(ctx.el('draftMessage').textContent, /Could not load your last draft/);
});

test('refreshLatestDraft treats an explicit {draft: null} as a legitimate empty state, not a failure', async (t) => {
  const ctx = mountDrafts({ routes: { 'GET /drafts/latest': { draft: null } } });
  t.after(ctx.restore);

  const result = await ctx.drafts.refreshLatestDraft();
  assert.equal(result, null);
  assert.equal(ctx.el('draftStatus').textContent, 'No draft yet');
  assert.equal(ctx.el('draftMessage').textContent, '', 'a real empty state is not an error');
});

test('refreshDrafts retries once, keeps the last-good history on total failure, and reports it honestly', async (t) => {
  const failCtx = mountDrafts({ routes: { 'GET /drafts': TIMEOUT_FAILURE } });
  const result = await failCtx.drafts.refreshDrafts();
  failCtx.restore();
  assert.deepEqual(result, []);
  assert.match(failCtx.el('draftHistoryList').innerHTML, /Could not load draft history/);

  let attempts = 0;
  const okCtx = mountDrafts({
    routes: {
      'GET /drafts': () => {
        attempts += 1;
        return attempts === 1 ? TIMEOUT_FAILURE : { drafts: [READY_DRAFT] };
      },
    },
  });
  const okResult = await okCtx.drafts.refreshDrafts();
  okCtx.restore();
  assert.equal(attempts, 2);
  assert.deepEqual(okResult.map((d) => d.id), [READY_DRAFT.id]);
});

test('refreshDrafts distinguishes a malformed payload (failure) from a real empty history', async (t) => {
  const malformedCtx = mountDrafts({ routes: { 'GET /drafts': {} } });
  await malformedCtx.drafts.refreshDrafts();
  malformedCtx.restore();
  assert.match(
    malformedCtx.el('draftHistoryList').innerHTML,
    /Could not load draft history/,
    'a payload with no `drafts` array at all is a fetch failure, not "you have no drafts"',
  );

  const emptyCtx = mountDrafts({ routes: { 'GET /drafts': { drafts: [] } } });
  await emptyCtx.drafts.refreshDrafts();
  emptyCtx.restore();
  assert.match(
    emptyCtx.el('draftHistoryList').innerHTML,
    /No draft history yet/,
    'an explicit empty array is a real, honest empty state',
  );
});

test('renderDraft does not clobber an unsaved edit when the same draft repopulates mid-session', async (t) => {
  const ctx = mountDrafts();
  t.after(ctx.restore);
  ctx.drafts.renderDraft(READY_DRAFT);

  const editor = ctx.el('draftFinalText');
  editor.value = 'Ship it on Friday instead.';
  ctx.drafts.handleDraftTextInput();

  // Simulates a cold-start/health-poll repopulate re-fetching the SAME draft
  // (bootstrap/signalDeskApp.js re-calls every refresh entrypoint on every
  // backend down->up transition).
  ctx.drafts.renderDraft({ ...READY_DRAFT });

  assert.equal(editor.value, 'Ship it on Friday instead.', 'an in-progress unsaved edit must survive a repopulate of the same draft');
});

test('renderDraft still swaps in a genuinely different (or cleared) draft even mid-edit', async (t) => {
  const ctx = mountDrafts();
  t.after(ctx.restore);
  ctx.drafts.renderDraft(READY_DRAFT);

  const editor = ctx.el('draftFinalText');
  editor.value = 'unsaved scratch text';
  ctx.drafts.handleDraftTextInput();

  ctx.drafts.renderDraft({ ...READY_DRAFT, id: 'd-2', final_text: 'A brand new draft.' });
  assert.equal(editor.value, 'A brand new draft.', 'a genuinely different draft must fully replace the editor');
});

test('saving an edit clears the dirty flag so a later repopulate reflects the saved text again', async (t) => {
  const ctx = mountDrafts({
    routes: {
      'POST /drafts/d-1/edit': (call) => ({ ...READY_DRAFT, final_text: call.body.final_text }),
      'GET /drafts': { drafts: [] },
    },
  });
  t.after(ctx.restore);
  ctx.drafts.renderDraft(READY_DRAFT);

  const editor = ctx.el('draftFinalText');
  editor.value = 'Ship it Friday.';
  ctx.drafts.handleDraftTextInput();
  await ctx.drafts.saveCurrentDraftEdit({ silent: true });

  // A later repopulate for the same (now-saved) draft must be free to
  // re-render normally -- the dirty flag from the pre-save edit must not
  // still be latched, or the editor would get stuck ignoring the backend.
  ctx.drafts.renderDraft({ ...READY_DRAFT, final_text: 'Ship it Friday.', status: 'sent' });
  assert.equal(ctx.el('draftStatus').textContent, 'sent');
});
