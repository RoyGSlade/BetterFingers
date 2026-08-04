// Shell chrome and the app-wide status surfaces: the header copy, the toast
// stack, the first-run panel's sticky dismissal and the Text Playground's
// status lines -- driven through the real DOM wiring.
//
// CURRENT_UI_INVENTORY.md sections 1, 4, 6.7 and 14 (parity rows UI-01-019,
// UI-04-001, UI-06-073, UI-06-080, UI-14-001, UI-15-025). Each of these is a
// piece of chrome whose whole job is to say something; a view-model test can
// assert the sentence, but only a document can assert that the sentence lands
// in the element the page actually shows.
//
// Run with: node --test app/tests/shellHeaderCopy.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  WORKSPACES,
  ROUTABLE_WORKSPACES,
  collectShellElements,
  createSignalDeskShellFeature,
  getWorkspaceMeta,
} from '../src/renderer/features/signalDeskShell.js';
import { showToast, TOAST_CONTAINER_ID } from '../src/renderer/lib/toast.mjs';
import { collectFirstRunElements, createFirstRunFeature } from '../src/renderer/features/firstRun.js';
import { initTextPlayground } from '../src/renderer/features/textPlayground.js';
import { makeDocument, makeLocalStorage, makeBackendBridge, installDomGlobals } from './helpers/rendererDom.mjs';

// --- UI-04-001: the header's breadcrumb / title / lede -----------------------

function mountShell() {
  const doc = makeDocument([
    'sdHeaderTitle', 'sdHeaderSubtitle', 'sdHeaderPillLabel', 'sdHeaderBreadcrumb',
    'sdShell', 'sdContextPanel', 'sdContextCollapseBtn', 'sdContextHideBtn',
    ...ROUTABLE_WORKSPACES.map((id) => `workspace-${id}`),
  ]);
  // The nav rail is addressed by [data-nav], not by id -- build it the way the
  // page does so collectShellElements() finds it the way it does in production.
  const rail = doc.createElement('div');
  for (const id of WORKSPACES) {
    const button = doc.createElement('button');
    button.setAttribute('data-nav', id);
    rail.appendChild(button);
  }
  doc.body.appendChild(rail);

  const restore = installDomGlobals({ document: doc, betterFingers: {} });
  const shell = createSignalDeskShellFeature({ elements: collectShellElements(doc) });
  return { doc, shell, restore, el: (id) => doc.getElementById(id) };
}

test('#sdHeaderTitle and #sdHeaderSubtitle are repainted from the workspace being shown', async (t) => {
  const ctx = mountShell();
  t.after(ctx.restore);
  ctx.shell.init();

  for (const id of ROUTABLE_WORKSPACES) {
    ctx.shell.goTo(id);
    const meta = getWorkspaceMeta(id);
    assert.equal(ctx.el('sdHeaderTitle').textContent, meta.title, `${id} did not repaint the header title`);
    assert.equal(ctx.el('sdHeaderSubtitle').textContent, meta.subtitle, `${id} did not repaint the lede`);
  }
});

test('#sdHeaderBreadcrumb is hidden and emptied when the workspace has no breadcrumb', async (t) => {
  const ctx = mountShell();
  t.after(ctx.restore);
  ctx.shell.init();

  ctx.shell.goTo('settings');
  const breadcrumb = ctx.el('sdHeaderBreadcrumb');
  assert.equal(breadcrumb.hidden, true, 'an absent breadcrumb must not leave an empty crumb on screen');
  assert.equal(breadcrumb.textContent, '');
});

test('the nav rail announces the active workspace with aria-current', async (t) => {
  const ctx = mountShell();
  t.after(ctx.restore);
  ctx.shell.init();
  ctx.shell.goTo('scribe');

  const els = collectShellElements(ctx.doc);
  assert.equal(els.navButtons.scribe.getAttribute('aria-current'), 'page');
  assert.notEqual(els.navButtons.settings.getAttribute('aria-current'), 'page');
  assert.equal(els.workspaces.scribe.hidden, false);
  assert.equal(els.workspaces.settings.hidden, true);
});

// --- UI-01-019 / UI-14-001: the toast stack ----------------------------------

test('#toastContainer is where every toast lands, and each one is dismissible', async (t) => {
  assert.equal(TOAST_CONTAINER_ID, 'toastContainer');
  const doc = makeDocument(['toastContainer']);
  const restore = installDomGlobals({ document: doc, betterFingers: {} });
  t.after(restore);

  const container = doc.getElementById('toastContainer');
  const toast = showToast('Data wiped.', 'success', 0, doc);
  assert.equal(container.children.length, 1);
  assert.match(toast.textContent, /Data wiped\./);
  assert.equal(toast.dataset.tone, 'success');

  const close = toast.querySelectorAll('.toast-close')[0];
  assert.equal(close.getAttribute('aria-label'), 'Dismiss notification', 'the dismiss control must be reachable by name');
  close.click();
  assert.equal(toast.classList.contains('leaving'), true, 'dismissing must start the removal, not do nothing');
});

test('a sticky toast (durationMs 0) is never auto-expired, unlike a timed one', async (t) => {
  const doc = makeDocument(['toastContainer']);
  const restore = installDomGlobals({ document: doc, betterFingers: {} });
  t.after(restore);
  t.mock.timers.enable({ apis: ['setTimeout'] });

  const sticky = showToast('Disk is full — the wipe stopped early.', 'error', 0, doc);
  const timed = showToast('Saved.', 'success', 5000, doc);

  t.mock.timers.tick(6000);
  assert.equal(sticky.classList.contains('leaving'), false, 'a 0ms toast must stay until the user dismisses it');
  assert.equal(timed.classList.contains('leaving'), true, 'a timed toast must expire on its own');
});

test('showToast with no #toastContainer is a silent no-op rather than a throw', async (t) => {
  const doc = makeDocument([]);
  const restore = installDomGlobals({ document: doc, betterFingers: {} });
  t.after(restore);
  assert.equal(showToast('anything', 'info', 1000, doc), undefined);
});

// --- UI-15-025: the first-run panel's per-device sticky dismissal -------------

const FIRST_RUN_IDS = [
  'sdFirstRunPanel', 'sdFirstRunOverallBadge', 'sdFirstRunMessage',
  'sdFirstRunRuntimeBadge', 'sdFirstRunRuntimeDetail',
  'sdFirstRunLlmBadge', 'sdFirstRunLlmDetail',
  'sdFirstRunWhisperBadge', 'sdFirstRunWhisperDetail',
  'sdFirstRunDownloadLlmButton', 'sdFirstRunDownloadWhisperButton',
  'sdFirstRunRefreshButton', 'sdFirstRunContinueButton', 'sdFirstRunDismissButton',
];

test('#sdFirstRunDismissButton hides the panel, records the choice per device, and routes to Models', async (t) => {
  const doc = makeDocument(FIRST_RUN_IDS);
  const storage = makeLocalStorage();
  const restore = installDomGlobals({ document: doc, betterFingers: {}, storage });
  t.after(restore);

  const routed = [];
  const elements = collectFirstRunElements(doc, { prefix: 'sdFirstRun' });
  assert.equal(elements.dismissButton, doc.getElementById('sdFirstRunDismissButton'), 'the prod prefix must reach the shipping id');

  const feature = createFirstRunFeature({
    elements,
    ui: { setMessage: () => {}, showToast: () => {} },
    hooks: { goToModelsTab: () => routed.push('models') },
    api: {
      fetchHealth: async () => ({ status: 'ok' }),
      fetchRuntimeStatus: async () => ({ llama_server_exists: true }),
      fetchLlmModels: async () => ({ models: [{ id: 'gemma', installed: true }] }),
      fetchWhisperModels: async () => ({ models: [{ model_size: 'base', installed: true }] }),
    },
    storage,
  });
  await feature.init();

  const dismiss = doc.getElementById('sdFirstRunDismissButton');
  assert.ok(dismiss.listenerCount('click') > 0, 'the dismiss button was never bound');
  dismiss.click();

  assert.equal(doc.getElementById('sdFirstRunPanel').hidden, true);
  assert.equal(storage.getItem('bf_first_run_dismissed'), 'true', 'the dismissal is sticky per device, not per session');
  assert.deepEqual(routed, ['models'], 'dismissing must still leave the user somewhere they can finish setup');
});

// --- UI-06-073 / UI-06-080: the Text Playground's status lines ----------------

const PLAYGROUND_IDS = [
  'textPlaygroundSection', 'textPlaygroundText', 'textPlaygroundContext',
  'textPlaygroundPersonaSelect', 'textPlaygroundRunButton', 'textPlaygroundCancelButton',
  'textPlaygroundClearButton', 'textPlaygroundStatus', 'textPlaygroundError',
  'textPlaygroundRanInfo', 'textPlaygroundFallback', 'textPlaygroundDraftSelect',
  'textPlaygroundApplyButton', 'textPlaygroundCopyButton', 'textPlaygroundApplyMessage',
  'textPlaygroundAssessment', 'textPlaygroundAssessmentIntent', 'textPlaygroundAssessmentAmbiguity',
  'textPlaygroundDeliveryLabels', 'textPlaygroundDeliveryConfidence', 'textPlaygroundDeliveryEvidence',
  'textPlaygroundClarification', 'textPlaygroundClarificationQuestion', 'textPlaygroundClarificationDetails',
  'textPlaygroundColumnRawText', 'textPlaygroundColumnRawButton',
  'textPlaygroundColumnFaithfulText', 'textPlaygroundColumnFaithfulButton',
  'textPlaygroundColumnClearerText', 'textPlaygroundColumnClearerButton',
  'textPlaygroundColumnAlternateText', 'textPlaygroundColumnAlternateButton',
  'textPlaygroundPreservationList',
];

function mountPlayground(routes = {}) {
  const doc = makeDocument(PLAYGROUND_IDS, {
    textPlaygroundText: { tagName: 'textarea', value: '' },
    textPlaygroundContext: { tagName: 'textarea', value: '' },
    textPlaygroundPersonaSelect: { tagName: 'select' },
    textPlaygroundDraftSelect: { tagName: 'select' },
  });
  const bridge = makeBackendBridge({ 'GET /personas': {}, 'GET /drafts': { drafts: [] }, ...routes });
  const restore = installDomGlobals({ document: doc, betterFingers: { backendRequest: bridge.request } });
  const feature = initTextPlayground({ doc });
  return { doc, feature, bridge, restore, el: (id) => doc.getElementById(id) };
}

test('#textPlaygroundStatus and #textPlaygroundError are separate lines with separate jobs', async (t) => {
  const ctx = mountPlayground();
  t.after(ctx.restore);
  assert.ok(ctx.feature, 'initTextPlayground must find its section and wire up');

  // Idle: a status line that says what to do, and no error.
  assert.notEqual(ctx.el('textPlaygroundStatus').textContent, '');
  assert.equal(ctx.el('textPlaygroundError').textContent, '');
});

test('#textPlaygroundRanInfo names what actually ran, and #textPlaygroundError carries a refusal', async (t) => {
  const ctx = mountPlayground({
    'GET /models/llm': { active_model_id: 'gemma-4-12b', models: [] },
    // Only `faithful` came back: the server-side safety net fired, which is
    // exactly the case #textPlaygroundFallback exists to make visible.
    'POST /message-rescue/generate': {
      status: 'done',
      result: { variants: { faithful: 'Dana, the build is green.' } },
    },
  });
  t.after(ctx.restore);

  const text = ctx.el('textPlaygroundText');
  text.value = 'tell dana the build is green';
  text.emit('input');
  await ctx.feature.run();

  assert.ok(ctx.bridge.find('POST', '/message-rescue/generate'), 'Run must reach the generate route');
  assert.match(ctx.el('textPlaygroundRanInfo').textContent, /^Ran with persona: .* · model: .* · context: /);
  assert.equal(ctx.el('textPlaygroundError').textContent, '', 'a successful run leaves the error line empty');
  assert.match(ctx.el('textPlaygroundFallback').textContent, /^Fallback: only a safe, faithful-only result/);
});

test('#textPlaygroundError states a failed run instead of leaving the status line reading "working"', async (t) => {
  const ctx = mountPlayground({
    'GET /models/llm': { active_model_id: 'gemma-4-12b', models: [] },
    'POST /message-rescue/generate': { ok: false, status: 503, body: { detail: 'the model is not loaded' } },
  });
  t.after(ctx.restore);

  const text = ctx.el('textPlaygroundText');
  text.value = 'tell dana the build is green';
  text.emit('input');
  await ctx.feature.run();

  assert.match(ctx.el('textPlaygroundError').textContent, /the model is not loaded/);
  assert.doesNotMatch(ctx.el('textPlaygroundStatus').textContent, /working|running/i);
});

test('#textPlaygroundApplyMessage is the confirmation line for applying a result to a draft', async (t) => {
  const ctx = mountPlayground({
    'GET /models/llm': { active_model_id: 'gemma-4-12b', models: [] },
    'GET /drafts': { drafts: [{ id: 4, final_text: 'old text', status: 'pending' }] },
    'POST /message-rescue/generate': { status: 'done', result: { variants: { faithful: 'Dana, the build is green.' } } },
    'POST /drafts/4/edit': { id: 4, final_text: 'Dana, the build is green.' },
  });
  t.after(ctx.restore);

  const applyMessage = ctx.el('textPlaygroundApplyMessage');
  assert.equal(applyMessage.textContent, '', 'nothing has been applied yet, so the line must be empty');

  const text = ctx.el('textPlaygroundText');
  text.value = 'tell dana the build is green';
  text.emit('input');
  await ctx.feature.run();
  await ctx.feature.refreshDrafts();

  const draftSelect = ctx.el('textPlaygroundDraftSelect');
  draftSelect.value = '4';
  draftSelect.emit('change');
  await ctx.feature.applyToDraft();

  assert.ok(ctx.bridge.find('POST', '/drafts/4/edit'), 'Apply must edit the draft the user picked');
  assert.equal(applyMessage.textContent, 'Applied to draft #4.');
});
