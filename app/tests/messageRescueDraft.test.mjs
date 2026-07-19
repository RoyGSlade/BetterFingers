// Unit tests for the live Message Rescue <-> draft review binding
// (ACCOMPLISH.md I3.5-I3.7). Run with: node --test app/tests/messageRescueDraft.test.mjs
//
// No jsdom in this repo's test setup (matches messageRescuePanel.test.mjs /
// textPlayground.test.mjs) -- DOM-driven logic is exercised against plain
// stub objects, not real nodes.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import {
  createInitialState,
  setDraft,
  setContext,
  setContextMessage,
  setCaptureBusy,
  setSelectedVariant,
  setApplyMessage,
  canRun,
  canCancel,
  beginRequest,
  cancelRequest,
  receiveResult,
  computeStatusLine,
  computeFallbackNotice,
  computeDraftLabel,
  buildMessageRescueDraftModel,
  renderMessageRescueDraft,
  createMessageRescueDraftFeature,
  initMessageRescueDraft,
} from '../src/renderer/features/messageRescueDraft.js';

const MODULE_PATH = fileURLToPath(new URL('../src/renderer/features/messageRescueDraft.js', import.meta.url));
const MODULE_SOURCE = readFileSync(MODULE_PATH, 'utf8');

// --- pure state reducers ------------------------------------------------------

test('createInitialState: idle, empty, nothing has run yet', () => {
  const state = createInitialState();
  assert.equal(state.status, 'idle');
  assert.equal(state.draft, null);
  assert.equal(state.context, null);
  assert.equal(state.result, null);
  assert.equal(state.selectedVariant, 'faithful');
});

test('canRun: false with no draft, false on a draft with blank raw_text, false while busy, true otherwise', () => {
  let state = createInitialState();
  assert.equal(canRun(state), false);
  state = setDraft(state, { id: 1, raw_text: '   ' });
  assert.equal(canRun(state), false);
  state = setDraft(state, { id: 1, raw_text: 'hey there' });
  assert.equal(canRun(state), true);
  state = beginRequest(state);
  assert.equal(canRun(state), false);
  assert.equal(canCancel(state), true);
});

test('beginRequest: bumps requestId, snapshots raw_text and context-usage, clears prior result/apply message', () => {
  let state = createInitialState();
  state = setDraft(state, { id: 7, raw_text: 'please reschedule' });
  state = setContext(state, { active: true, visible_preview: 'ctx' });
  state.result = { variants: { faithful: 'stale' } };
  state.applyMessage = 'old';

  const started = beginRequest(state);
  assert.equal(started.status, 'busy');
  assert.equal(started.requestId, state.requestId + 1);
  assert.equal(started.result, null);
  assert.equal(started.applyMessage, '');
  assert.equal(started.ranText, 'please reschedule');
  assert.equal(started.ranUsedContext, true);
});

test('cancelRequest: only takes effect while busy', () => {
  let state = createInitialState();
  assert.equal(cancelRequest(state).status, 'idle');
  state = setDraft(state, { id: 1, raw_text: 'hi' });
  state = beginRequest(state);
  state = cancelRequest(state);
  assert.equal(state.status, 'cancelled');
});

test('receiveResult: stale requestId or non-busy status is ignored (superseded response)', () => {
  let state = createInitialState();
  state = setDraft(state, { id: 1, raw_text: 'hi' });
  state = beginRequest(state);
  const requestId = state.requestId;
  state = cancelRequest(state); // now cancelled, not busy
  const unchanged = receiveResult(state, { requestId, outcome: { kind: 'done', result: { variants: {} } } });
  assert.equal(unchanged.status, 'cancelled');
  assert.equal(unchanged.result, null);
});

test('receiveResult: done/timeout/cancelled/error outcomes map to the matching status and clear context', () => {
  const base = () => {
    let state = createInitialState();
    state = setDraft(state, { id: 1, raw_text: 'hi' });
    state = setContext(state, { active: true, visible_preview: 'ctx' });
    state = beginRequest(state);
    return state;
  };

  let state = base();
  let out = receiveResult(state, { requestId: state.requestId, outcome: { kind: 'done', result: { variants: { faithful: 'f' } } } });
  assert.equal(out.status, 'done');
  assert.equal(out.result.variants.faithful, 'f');
  assert.equal(out.selectedVariant, 'faithful');
  assert.equal(out.context, null); // one-time-use, dropped locally regardless of outcome

  state = base();
  assert.equal(receiveResult(state, { requestId: state.requestId, outcome: { kind: 'timeout' } }).status, 'timeout');

  state = base();
  assert.equal(receiveResult(state, { requestId: state.requestId, outcome: { kind: 'cancelled' } }).status, 'cancelled');

  state = base();
  out = receiveResult(state, { requestId: state.requestId, outcome: { kind: 'error', message: 'boom' } });
  assert.equal(out.status, 'error');
  assert.equal(out.errorMessage, 'boom');
});

test('computeStatusLine: one line per status', () => {
  const state = createInitialState();
  assert.equal(computeStatusLine(state), 'Ready.');
  assert.equal(computeStatusLine({ ...state, status: 'busy' }), 'Running…');
  assert.equal(computeStatusLine({ ...state, status: 'done' }), 'Done.');
  assert.equal(computeStatusLine({ ...state, status: 'timeout' }), 'The model call timed out. No result was produced.');
  assert.equal(computeStatusLine({ ...state, status: 'cancelled' }), 'Cancelled.');
  assert.equal(computeStatusLine({ ...state, status: 'error', errorMessage: 'oops' }), 'oops');
});

test('computeFallbackNotice: blank when not done, or when clearer/alternate are present', () => {
  const state = createInitialState();
  assert.equal(computeFallbackNotice(state), '');
  const withVariants = { ...state, status: 'done', result: { variants: { faithful: 'f', clearer: 'c', alternate: 'a' } } };
  assert.equal(computeFallbackNotice(withVariants), '');
});

test('computeFallbackNotice: fires when only faithful came back (the safety-net fallback)', () => {
  const state = { ...createInitialState(), status: 'done', result: { variants: { faithful: 'only this' } } };
  assert.match(computeFallbackNotice(state), /Fallback/);
});

test('computeDraftLabel: reflects no-draft, empty-transcript, and ready states', () => {
  let state = createInitialState();
  assert.match(computeDraftLabel(state), /No draft/);
  state = setDraft(state, { id: 5, raw_text: '' });
  assert.match(computeDraftLabel(state), /#5 has no transcript/);
  state = setDraft(state, { id: 5, raw_text: 'hello' });
  assert.match(computeDraftLabel(state), /Will rescue draft #5/);
});

// --- setSelectedVariant / setContextMessage / setCaptureBusy / setApplyMessage ---

test('setSelectedVariant clears any stale apply message', () => {
  let state = createInitialState();
  state = setApplyMessage(state, 'Applied.');
  state = setSelectedVariant(state, 'clearer');
  assert.equal(state.selectedVariant, 'clearer');
  assert.equal(state.applyMessage, '');
});

test('setContextMessage/setCaptureBusy coerce and are otherwise pure', () => {
  let state = createInitialState();
  state = setContextMessage(state, null);
  assert.equal(state.contextMessage, '');
  state = setCaptureBusy(state, 1);
  assert.equal(state.captureBusy, true);
});

// --- buildMessageRescueDraftModel --------------------------------------------

test('buildMessageRescueDraftModel: idle/empty state disables run/cancel/clear-context', () => {
  const model = buildMessageRescueDraftModel(createInitialState());
  assert.equal(model.canRun, false);
  assert.equal(model.canCancel, false);
  assert.equal(model.canClearContext, false);
  assert.equal(model.statusLine, 'Ready.');
  assert.equal(model.selectedVariantText, '');
});

test('buildMessageRescueDraftModel: busy state disables capture and run, enables cancel', () => {
  let state = createInitialState();
  state = setDraft(state, { id: 1, raw_text: 'hi' });
  state = beginRequest(state);
  const model = buildMessageRescueDraftModel(state);
  assert.equal(model.canRun, false);
  assert.equal(model.canCancel, true);
  assert.equal(model.canCapture, false);
  assert.equal(model.isBusy, true);
});

test('buildMessageRescueDraftModel: active context enables clear and reuses F2.3/F2.8 formatting', () => {
  let state = createInitialState();
  state = setContext(state, {
    active: true, source: 'selection', expires_at: Date.now() / 1000 + 120, use_count: 0, max_uses: 1, visible_preview: 'hey there',
  });
  const model = buildMessageRescueDraftModel({ ...state, status: 'idle' });
  assert.equal(model.canClearContext, true);
  assert.equal(model.rescuePanelModel.contextPreviewText, 'hey there');
});

test('buildMessageRescueDraftModel: selected variant text is the raw (unescaped) result text', () => {
  const evil = '<b>bold</b> & safe';
  let state = createInitialState();
  state.status = 'done';
  state.result = { variants: { faithful: evil } };
  state.selectedVariant = 'faithful';
  const model = buildMessageRescueDraftModel(state);
  assert.equal(model.selectedVariantText, evil); // raw -- caller must use textarea.value/textContent
});

// --- renderMessageRescueDraft (plain stub elements, no real DOM) ------------

function makeStubElement() {
  return {
    textContent: '', innerHTML: '', className: '', hidden: false, disabled: false,
    _attrs: {},
    setAttribute(k, v) { this._attrs[k] = v; },
  };
}

function makeStubInput() {
  const el = makeStubElement();
  el.checked = false;
  el._listeners = {};
  el.addEventListener = (evt, fn) => { el._listeners[evt] = fn; };
  return el;
}

function makeStubElements() {
  const withListeners = (el) => {
    el._listeners = {};
    el.addEventListener = function (evt, fn) { this._listeners[evt] = fn; };
    return el;
  };
  return {
    section: makeStubElement(),
    draftLabel: makeStubElement(),
    captureButton: withListeners(makeStubElement()),
    contextMessage: makeStubElement(),
    contextStatus: makeStubElement(),
    contextPreview: makeStubElement(),
    contextMeta: makeStubElement(),
    contextClearButton: withListeners(makeStubElement()),
    runButton: withListeners(makeStubElement()),
    cancelButton: withListeners(makeStubElement()),
    status: makeStubElement(),
    error: makeStubElement(),
    fallback: makeStubElement(),
    applyMessage: makeStubElement(),
    assessment: makeStubElement(),
    assessmentIntent: makeStubElement(),
    assessmentAmbiguity: makeStubElement(),
    deliveryLabels: makeStubElement(),
    deliveryConfidence: makeStubElement(),
    deliveryEvidence: makeStubElement(),
    clarification: makeStubElement(),
    clarificationQuestion: makeStubElement(),
    clarificationDetails: makeStubElement(),
    variantInputs: { faithful: makeStubInput(), clearer: makeStubInput(), alternate: makeStubInput() },
    variantText: makeStubElement(),
    preservationList: makeStubElement(),
    warnings: makeStubElement(),
    warningsList: makeStubElement(),
  };
}

test('renderMessageRescueDraft: empty state shows "Ready." and a disabled Run button', () => {
  const elements = makeStubElements();
  renderMessageRescueDraft(elements, buildMessageRescueDraftModel(createInitialState()));
  assert.equal(elements.status.textContent, 'Ready.');
  assert.equal(elements.runButton.disabled, true);
  assert.equal(elements.contextClearButton.disabled, true);
  assert.match(elements.draftLabel.textContent, /No draft/);
});

test('renderMessageRescueDraft: error state shows the error banner with the message', () => {
  const elements = makeStubElements();
  let state = createInitialState();
  state = { ...state, status: 'error', errorMessage: 'network down' };
  renderMessageRescueDraft(elements, buildMessageRescueDraftModel(state));
  assert.equal(elements.error.hidden, false);
  assert.equal(elements.error.textContent, 'network down');
});

test('renderMessageRescueDraft: capturing shows busy label and disables the capture button', () => {
  const elements = makeStubElements();
  const state = setCaptureBusy(createInitialState(), true);
  renderMessageRescueDraft(elements, buildMessageRescueDraftModel(state));
  assert.equal(elements.captureButton.disabled, true);
  assert.equal(elements.captureButton.textContent, 'Capturing…');
});

// --- createMessageRescueDraftFeature (DI'd api, no network) ------------------

function makeFakeApi(overrides = {}) {
  return {
    getLatestDraft: async () => ({ id: 1, raw_text: 'hey can we push this', speech_signals: null }),
    getContext: async () => null,
    captureSelection: async () => ({ active: true, source: 'selection', expires_at: Date.now() / 1000 + 120, use_count: 0, max_uses: 1, visible_preview: 'hey' }),
    clearContext: async () => ({ ok: true }),
    generate: async () => ({ id: 'job-1', status: 'done', result: { variants: { faithful: 'ok' } } }),
    ...overrides,
  };
}

test('createMessageRescueDraftFeature.refreshDraft/refreshContext: populate state from the injected api', async () => {
  const elements = makeStubElements();
  const feature = createMessageRescueDraftFeature({ elements, api: makeFakeApi() });
  await feature.refreshDraft();
  assert.equal(feature.getState().draft.id, 1);
  await feature.refreshContext();
  assert.equal(feature.getState().context, null); // getContext() returned null here
});

test('createMessageRescueDraftFeature.run: sends the current draft raw_text and its speech_signals, no persona', async () => {
  const elements = makeStubElements();
  const calls = [];
  const api = makeFakeApi({
    generate: async (args) => {
      calls.push(args);
      return { id: 'j', status: 'done', result: { variants: { faithful: 'reply' } } };
    },
  });
  const feature = createMessageRescueDraftFeature({ elements, api });
  await feature.refreshDraft();

  await feature.run();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].transcript, 'hey can we push this');
  assert.equal(calls[0].useContext, false);
  assert.equal('persona' in calls[0], false);
  assert.equal(feature.getState().status, 'done');
});

test('createMessageRescueDraftFeature.run: an active context is passed as useContext=true', async () => {
  const elements = makeStubElements();
  const calls = [];
  const api = makeFakeApi({
    generate: async (args) => {
      calls.push(args);
      return { id: 'j', status: 'done', result: { variants: { faithful: 'ok' } } };
    },
  });
  const feature = createMessageRescueDraftFeature({ elements, api });
  await feature.refreshDraft();
  await feature.captureSelection();

  await feature.run();
  assert.equal(calls[0].useContext, true);
  // Context is one-time-use: gone from local state once the request completes.
  assert.equal(feature.getState().context, null);
});

test('createMessageRescueDraftFeature.run: no-op when there is no usable draft', async () => {
  const elements = makeStubElements();
  const calls = [];
  const api = makeFakeApi({
    getLatestDraft: async () => null,
    generate: async (args) => { calls.push(args); return { status: 'done', result: {} }; },
  });
  const feature = createMessageRescueDraftFeature({ elements, api });
  await feature.refreshDraft();
  await feature.run();
  assert.equal(calls.length, 0);
  assert.equal(feature.getState().status, 'idle');
});

test('createMessageRescueDraftFeature.run: server "timeout" status surfaces as the timeout state', async () => {
  const elements = makeStubElements();
  const api = makeFakeApi({ generate: async () => ({ id: 'j', status: 'timeout', result: null }) });
  const feature = createMessageRescueDraftFeature({ elements, api });
  await feature.refreshDraft();
  await feature.run();
  assert.equal(feature.getState().status, 'timeout');
});

test('createMessageRescueDraftFeature.run: a thrown/network error surfaces as an error state with the message', async () => {
  const elements = makeStubElements();
  const api = makeFakeApi({ generate: async () => { throw new Error('Backend request failed.'); } });
  const feature = createMessageRescueDraftFeature({ elements, api });
  await feature.refreshDraft();
  await feature.run();
  assert.equal(feature.getState().status, 'error');
  assert.equal(feature.getState().errorMessage, 'Backend request failed.');
});

test('createMessageRescueDraftFeature.cancel: soft-cancels immediately; a late-arriving response is discarded', async () => {
  const elements = makeStubElements();
  let resolveGenerate;
  const api = makeFakeApi({
    generate: () => new Promise((resolve) => { resolveGenerate = resolve; }),
  });
  const feature = createMessageRescueDraftFeature({ elements, api });
  await feature.refreshDraft();

  const runPromise = feature.run();
  feature.cancel();
  assert.equal(feature.getState().status, 'cancelled');

  resolveGenerate({ id: 'late', status: 'done', result: { variants: { faithful: 'too late' } } });
  await runPromise;
  assert.equal(feature.getState().status, 'cancelled');
  assert.equal(feature.getState().result, null);
});

test('createMessageRescueDraftFeature.captureSelection: capture_empty/capture_unsupported map to distinct messages', async () => {
  const elements = makeStubElements();
  const empty = new Error('capture_empty');
  empty.detail = 'capture_empty';
  const feature1 = createMessageRescueDraftFeature({ elements, api: makeFakeApi({ captureSelection: async () => { throw empty; } }) });
  await feature1.captureSelection();
  assert.match(feature1.getState().contextMessage, /No text was found/);
  assert.equal(feature1.getState().context, null);

  const unsupported = new Error('capture_unsupported');
  unsupported.detail = 'capture_unsupported';
  const elements2 = makeStubElements();
  const feature2 = createMessageRescueDraftFeature({ elements: elements2, api: makeFakeApi({ captureSelection: async () => { throw unsupported; } }) });
  await feature2.captureSelection();
  assert.match(feature2.getState().contextMessage, /isn't available on this system/);
});

test('createMessageRescueDraftFeature.captureSelection: success stores the returned context and a confirmation message', async () => {
  const elements = makeStubElements();
  const feature = createMessageRescueDraftFeature({ elements, api: makeFakeApi() });
  await feature.captureSelection();
  assert.equal(feature.getState().context.source, 'selection');
  assert.equal(feature.getState().contextMessage, 'Context captured.');
});

test('createMessageRescueDraftFeature.clearContext: clears local state even if the server call fails (best-effort)', async () => {
  const elements = makeStubElements();
  const api = makeFakeApi({ clearContext: async () => { throw new Error('down'); } });
  const feature = createMessageRescueDraftFeature({ elements, api });
  await feature.captureSelection();
  assert.ok(feature.getState().context);
  await feature.clearContext();
  assert.equal(feature.getState().context, null);
});

test('createMessageRescueDraftFeature.selectVariant: applies the variant text via hooks.applyToEditor without touching raw text', async () => {
  const elements = makeStubElements();
  const applied = [];
  const feature = createMessageRescueDraftFeature({
    elements,
    api: makeFakeApi({ generate: async () => ({ status: 'done', result: { variants: { faithful: 'f', clearer: 'clearer text' } } }) }),
    hooks: { applyToEditor: (text) => applied.push(text) },
  });
  await feature.refreshDraft();
  await feature.run();

  feature.selectVariant('clearer');
  assert.deepEqual(applied, ['clearer text']);
  assert.match(feature.getState().applyMessage, /Applied the clearer variant/);
});

test('createMessageRescueDraftFeature.selectVariant: an unavailable variant does not call applyToEditor', async () => {
  const elements = makeStubElements();
  const applied = [];
  const feature = createMessageRescueDraftFeature({
    elements,
    api: makeFakeApi({ generate: async () => ({ status: 'done', result: { variants: { faithful: 'only this' } } }) }),
    hooks: { applyToEditor: (text) => applied.push(text) },
  });
  await feature.refreshDraft();
  await feature.run();

  feature.selectVariant('clearer'); // not available in this result
  assert.deepEqual(applied, []);
});

test('createMessageRescueDraftFeature: missing hooks.applyToEditor is a safe no-op, not a crash', async () => {
  const elements = makeStubElements();
  const feature = createMessageRescueDraftFeature({
    elements,
    api: makeFakeApi({ generate: async () => ({ status: 'done', result: { variants: { faithful: 'f' } } }) }),
  });
  await feature.refreshDraft();
  await feature.run();
  assert.doesNotThrow(() => feature.selectVariant('faithful'));
});

test('createMessageRescueDraftFeature.wire: clicking capture/run/cancel/clear and changing a variant radio dispatch to the right handlers', async () => {
  const elements = makeStubElements();
  const api = makeFakeApi({ generate: async () => ({ status: 'done', result: { variants: { faithful: 'f', clearer: 'c' } } }) });
  const applied = [];
  const feature = createMessageRescueDraftFeature({ elements, api, hooks: { applyToEditor: (t) => applied.push(t) } });
  feature.wire();
  await feature.refreshDraft();

  await elements.runButton._listeners.click();
  assert.equal(feature.getState().status, 'done');

  elements.variantInputs.clearer.checked = true;
  elements.variantInputs.clearer._listeners.change();
  assert.deepEqual(applied, ['c']);

  await elements.captureButton._listeners.click();
  assert.equal(feature.getState().context.source, 'selection');

  elements.contextClearButton._listeners.click();
  await Promise.resolve();
});

// --- initMessageRescueDraft (fake doc) ---------------------------------------

test('initMessageRescueDraft: missing markup in the doc is a safe no-op', () => {
  const doc = { getElementById: () => null };
  assert.equal(initMessageRescueDraft({ doc, storage: { getItem: () => 'true' } }), null);
});

test('initMessageRescueDraft: flag off hides the section and does nothing else (no elements queried, no api calls)', () => {
  const section = makeStubElement();
  const doc = { getElementById: (id) => (id === 'draftRescuePanel' ? section : null) };
  const result = initMessageRescueDraft({ doc, storage: { getItem: () => null } });
  assert.equal(result, null);
  assert.equal(section.hidden, true);
});

test('initMessageRescueDraft: flag on reveals the section and wires up the feature', () => {
  const elements = makeStubElements();
  const idMap = {
    draftRescuePanel: elements.section,
    draftRescueDraftLabel: elements.draftLabel,
    draftRescueCaptureButton: elements.captureButton,
    draftRescueContextMessage: elements.contextMessage,
    draftRescueContextStatus: elements.contextStatus,
    draftRescueContextPreview: elements.contextPreview,
    draftRescueContextMeta: elements.contextMeta,
    draftRescueClearContextButton: elements.contextClearButton,
    draftRescueRunButton: elements.runButton,
    draftRescueCancelButton: elements.cancelButton,
    draftRescueStatus: elements.status,
    draftRescueError: elements.error,
    draftRescueFallback: elements.fallback,
    draftRescueApplyMessage: elements.applyMessage,
    draftRescueAssessment: elements.assessment,
    draftRescueAssessmentIntent: elements.assessmentIntent,
    draftRescueAssessmentAmbiguity: elements.assessmentAmbiguity,
    draftRescueDeliveryLabels: elements.deliveryLabels,
    draftRescueDeliveryConfidence: elements.deliveryConfidence,
    draftRescueDeliveryEvidence: elements.deliveryEvidence,
    draftRescueClarification: elements.clarification,
    draftRescueClarificationQuestion: elements.clarificationQuestion,
    draftRescueClarificationDetails: elements.clarificationDetails,
    draftRescueVariantFaithful: elements.variantInputs.faithful,
    draftRescueVariantClearer: elements.variantInputs.clearer,
    draftRescueVariantAlternate: elements.variantInputs.alternate,
    draftRescueVariantText: elements.variantText,
    draftRescuePreservationList: elements.preservationList,
    draftRescueWarnings: elements.warnings,
    draftRescueWarningsList: elements.warningsList,
  };
  const doc = { getElementById: (id) => idMap[id] || null };

  const feature = initMessageRescueDraft({ doc, storage: { getItem: () => 'true' } });
  assert.ok(feature);
  assert.equal(elements.section.hidden, false);
  assert.equal(typeof elements.runButton._listeners.click, 'function');
});

// --- privacy / no-audio-or-automatic-send invariants -------------------------

test('module never references microphone, recording, playback, TTS, or automatic-send/learn APIs', () => {
  const forbidden = [
    'getUserMedia', 'MediaRecorder', 'mediaDevices',
    'speakDraft', 'speakTts', 'toggleRecording', 'connectVoiceStatus',
    'sendDraft', 'runPrimaryAction', 'acceptDraft', 'declineDraft',
    'personas/.*examples',
  ];
  for (const token of forbidden) {
    assert.doesNotMatch(MODULE_SOURCE, new RegExp(token), `messageRescueDraft.js must never reference ${token}`);
  }
});

test('module never reads or writes the raw transcript element -- only the final-text editor via hooks.applyToEditor', () => {
  assert.doesNotMatch(MODULE_SOURCE, /draftRawText/);
});

test('defaultApi surface exposed to the DOM layer has no audio/TTS/send methods', () => {
  const elements = makeStubElements();
  const feature = createMessageRescueDraftFeature({ elements, api: makeFakeApi() });
  const methodNames = Object.keys(feature);
  assert.deepEqual(
    methodNames.sort(),
    ['cancel', 'captureSelection', 'clearContext', 'getState', 'refreshContext', 'refreshDraft', 'rerender', 'run', 'selectVariant', 'wire'].sort(),
  );
});
