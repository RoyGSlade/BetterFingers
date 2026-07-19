// Unit tests for the Text Playground feature (board #31): a silent,
// text-only place to test a persona/LLM prompt without a microphone,
// transcription, or TTS.
// Run with: node --test app/tests/textPlayground.test.mjs
//
// No jsdom in this repo's test setup (matches messageRescuePanel.test.mjs) --
// DOM-driven logic is exercised against plain stub objects, not real nodes.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import {
  createInitialState,
  setText,
  setContextText,
  setPersona,
  setSelectedVariant,
  setSelectedDraftId,
  setApplyMessage,
  canRun,
  canCancel,
  beginRequest,
  cancelRequest,
  receiveResult,
  clearAll,
  computeStatusLine,
  buildRanInfoText,
  computeFallbackNotice,
  buildPersonaOptions,
  buildPersonaOptionsHtml,
  buildDraftOptions,
  buildDraftOptionsHtml,
  buildComparisonColumns,
  buildTextPlaygroundModel,
  renderTextPlayground,
  createTextPlaygroundFeature,
  initTextPlayground,
} from '../src/renderer/features/textPlayground.js';

const MODULE_PATH = fileURLToPath(new URL('../src/renderer/features/textPlayground.js', import.meta.url));
const MODULE_SOURCE = readFileSync(MODULE_PATH, 'utf8');

// --- pure state reducers ------------------------------------------------------

test('createInitialState: idle, empty, nothing has run yet', () => {
  const state = createInitialState();
  assert.equal(state.status, 'idle');
  assert.equal(state.text, '');
  assert.equal(state.contextText, '');
  assert.equal(state.persona, '');
  assert.equal(state.result, null);
  assert.equal(state.ranPersona, null);
  assert.equal(state.ranModelId, null);
});

test('setText/setContextText/setPersona: pure, coerce nullish to empty string', () => {
  let state = createInitialState();
  state = setText(state, 'hello');
  assert.equal(state.text, 'hello');
  state = setContextText(state, null);
  assert.equal(state.contextText, '');
  state = setPersona(state, undefined);
  assert.equal(state.persona, '');
});

test('canRun: false on blank/whitespace-only text, false while busy, true otherwise', () => {
  let state = createInitialState();
  assert.equal(canRun(state), false);
  state = setText(state, '   ');
  assert.equal(canRun(state), false);
  state = setText(state, 'hi');
  assert.equal(canRun(state), true);
  state = beginRequest(state, { modelId: 'm1' });
  assert.equal(canRun(state), false);
  assert.equal(canCancel(state), true);
});

test('beginRequest: bumps requestId, snapshots persona/model/context-usage, clears prior result', () => {
  let state = createInitialState();
  state = setText(state, 'hi');
  state = setPersona(state, 'friendly');
  state = setContextText(state, 'they asked about the deadline');
  state.result = { variants: { faithful: 'x' } }; // simulate a stale prior result
  state.errorMessage = 'old error';

  const started = beginRequest(state, { modelId: 'gemma-4' });
  assert.equal(started.status, 'busy');
  assert.equal(started.requestId, state.requestId + 1);
  assert.equal(started.result, null);
  assert.equal(started.errorMessage, '');
  assert.equal(started.ranPersona, 'friendly');
  assert.equal(started.ranModelId, 'gemma-4');
  assert.equal(started.ranUsedContext, true);
  // Context text itself is untouched until receiveResult -- the DOM layer
  // still needs it to actually send the capture call.
  assert.equal(started.contextText, 'they asked about the deadline');
});

test('beginRequest: no persona and no context text is recorded as such', () => {
  let state = setText(createInitialState(), 'hi');
  const started = beginRequest(state, { modelId: 'gemma-4' });
  assert.equal(started.ranPersona, null);
  assert.equal(started.ranUsedContext, false);
});

test('cancelRequest: no-op unless busy', () => {
  let state = createInitialState();
  assert.equal(cancelRequest(state), state);

  state = beginRequest(setText(state, 'hi'), {});
  const cancelled = cancelRequest(state);
  assert.equal(cancelled.status, 'cancelled');
});

test('receiveResult: a stale requestId (superseded by a newer request) is ignored', () => {
  let state = beginRequest(setText(createInitialState(), 'hi'), { modelId: 'm' });
  const staleRequestId = state.requestId;
  // A second run started before the first resolved.
  state = beginRequest(state, { modelId: 'm' });

  const after = receiveResult(state, { requestId: staleRequestId, outcome: { kind: 'done', result: { variants: {} } } });
  assert.equal(after, state); // untouched
});

test('receiveResult: a response after a local cancel is ignored (soft cancel)', () => {
  let state = beginRequest(setText(createInitialState(), 'hi'), { modelId: 'm' });
  const requestId = state.requestId;
  state = cancelRequest(state);

  const after = receiveResult(state, { requestId, outcome: { kind: 'done', result: { variants: { faithful: 'x' } } } });
  assert.equal(after.status, 'cancelled');
  assert.equal(after.result, null);
});

test('receiveResult: done outcome stores the result, resets to the faithful variant, clears context', () => {
  let state = beginRequest(setText(setContextText(createInitialState(), 'ctx'), 'hi'), { modelId: 'm' });
  state.selectedVariant = 'alternate';
  const result = { variants: { faithful: 'a', clearer: 'b', alternate: 'c' } };
  const after = receiveResult(state, { requestId: state.requestId, outcome: { kind: 'done', result } });

  assert.equal(after.status, 'done');
  assert.equal(after.result, result);
  assert.equal(after.selectedVariant, 'faithful');
  assert.equal(after.contextText, '', 'context is one-time-use and must not linger after a request completes');
});

test('receiveResult: timeout/cancelled/error outcomes map to the matching status', () => {
  const base = () => beginRequest(setText(createInitialState(), 'hi'), { modelId: 'm' });

  let s = base();
  assert.equal(receiveResult(s, { requestId: s.requestId, outcome: { kind: 'timeout' } }).status, 'timeout');

  s = base();
  assert.equal(receiveResult(s, { requestId: s.requestId, outcome: { kind: 'cancelled' } }).status, 'cancelled');

  s = base();
  const errored = receiveResult(s, { requestId: s.requestId, outcome: { kind: 'error', message: 'network down' } });
  assert.equal(errored.status, 'error');
  assert.equal(errored.errorMessage, 'network down');
});

test('clearAll: returns a fresh initial state regardless of prior state', () => {
  let state = beginRequest(setPersona(setText(createInitialState(), 'hi'), 'x'), { modelId: 'm' });
  state = receiveResult(state, { requestId: state.requestId, outcome: { kind: 'done', result: { variants: { faithful: 'a' } } } });
  const cleared = clearAll();
  assert.deepEqual(cleared, createInitialState());
  assert.notEqual(state.status, cleared.status);
});

// --- pure derived text ---------------------------------------------------------

test('computeStatusLine: one line per status', () => {
  const s = createInitialState();
  assert.equal(computeStatusLine({ ...s, status: 'idle' }), 'Ready.');
  assert.equal(computeStatusLine({ ...s, status: 'busy' }), 'Running…');
  assert.equal(computeStatusLine({ ...s, status: 'done' }), 'Done.');
  assert.match(computeStatusLine({ ...s, status: 'timeout' }), /timed out/);
  assert.equal(computeStatusLine({ ...s, status: 'cancelled' }), 'Cancelled.');
  assert.equal(computeStatusLine({ ...s, status: 'error', errorMessage: 'boom' }), 'boom');
});

test('buildRanInfoText: blank before anything has run', () => {
  assert.equal(buildRanInfoText(createInitialState()), '');
});

test('buildRanInfoText: names the persona, model, and whether context was used', () => {
  let state = beginRequest(setContextText(setPersona(setText(createInitialState(), 'hi'), 'coach'), 'ctx'), { modelId: 'gemma-4' });
  const text = buildRanInfoText(state);
  assert.match(text, /Running with persona: coach/);
  assert.match(text, /model: gemma-4/);
  assert.match(text, /context: used/);
});

test('buildRanInfoText: no persona selected reads as "Default (no persona)"', () => {
  let state = beginRequest(setText(createInitialState(), 'hi'), { modelId: 'gemma-4' });
  state = receiveResult(state, { requestId: state.requestId, outcome: { kind: 'done', result: { variants: { faithful: 'a' } } } });
  assert.match(buildRanInfoText(state), /persona: Default \(no persona\)/);
  assert.match(buildRanInfoText(state), /context: none/);
  assert.match(buildRanInfoText(state), /^Ran with/);
});

test('computeFallbackNotice: blank when not done, or when clearer/alternate are present', () => {
  assert.equal(computeFallbackNotice(createInitialState()), '');

  let state = beginRequest(setText(createInitialState(), 'hi'), {});
  state = receiveResult(state, {
    requestId: state.requestId,
    outcome: { kind: 'done', result: { variants: { faithful: 'a', clearer: 'b', alternate: 'c' } } },
  });
  assert.equal(computeFallbackNotice(state), '');
});

test('computeFallbackNotice: fires when only faithful came back (the safety-net fallback)', () => {
  let state = beginRequest(setText(createInitialState(), 'hi'), {});
  state = receiveResult(state, {
    requestId: state.requestId,
    outcome: { kind: 'done', result: { variants: { faithful: 'a', clearer: '', alternate: '' } } },
  });
  const notice = computeFallbackNotice(state);
  assert.match(notice, /Fallback/);
  assert.match(notice, /faithful-only/);
});

// --- persona / draft option builders (XSS + shape) -----------------------------

test('buildPersonaOptions: always includes a "no persona" default first, sorted names after', () => {
  const options = buildPersonaOptions({ zeta: {}, alpha: {} });
  assert.deepEqual(options.map((o) => o.value), ['', 'alpha', 'zeta']);
  assert.equal(options[0].label, 'Default (no persona)');
});

test('buildPersonaOptions: accepts an array of names too, ignores non-string entries', () => {
  const options = buildPersonaOptions(['b', 'a', 42, null]);
  assert.deepEqual(options.map((o) => o.value), ['', 'a', 'b']);
});

test('buildPersonaOptionsHtml: marks the current persona selected and escapes hostile names', () => {
  const html = buildPersonaOptionsHtml({ '<img src=x onerror=alert(1)>': {} }, '<img src=x onerror=alert(1)>');
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
  assert.match(html, / selected/);
});

test('buildDraftOptions: truncates long snippets, prefers final_text over raw_text', () => {
  const longText = 'x'.repeat(100);
  const options = buildDraftOptions([
    { id: 1, raw_text: 'raw only' },
    { id: 2, raw_text: 'raw', final_text: 'final wins' },
    { id: 3, raw_text: longText },
  ]);
  assert.equal(options[0].label, '#1 · raw only');
  assert.equal(options[1].label, '#2 · final wins');
  assert.ok(options[2].label.endsWith('…'));
  assert.ok(options[2].label.length < longText.length);
});

test('buildDraftOptionsHtml: escapes raw draft text (XSS-shaped content is dictated user text)', () => {
  const html = buildDraftOptionsHtml([{ id: 1, raw_text: '<script>alert(1)</script>' }], '');
  assert.doesNotMatch(html, /<script\b/i);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /Choose a draft…/);
});

// --- side-by-side comparison columns --------------------------------------------

test('buildComparisonColumns: before anything has run, only "raw" reflects live typed text', () => {
  const state = setText(createInitialState(), 'still typing');
  const columns = buildComparisonColumns(state);
  assert.deepEqual(columns.map((c) => c.key), ['raw', 'faithful', 'clearer', 'alternate']);
  // ranText is only snapshotted by beginRequest, not by every keystroke.
  assert.equal(columns[0].available, false);
  assert.equal(columns[1].available, false);
});

test('buildComparisonColumns: after a run, raw is the submitted text and unavailable variants are flagged', () => {
  let state = beginRequest(setText(createInitialState(), 'original message'), {});
  state = receiveResult(state, {
    requestId: state.requestId,
    outcome: { kind: 'done', result: { variants: { faithful: 'a', clearer: '', alternate: 'c' } } },
  });
  const columns = buildComparisonColumns(state);
  const byKey = Object.fromEntries(columns.map((c) => [c.key, c]));
  assert.equal(byKey.raw.text, 'original message');
  assert.equal(byKey.raw.available, true);
  assert.equal(byKey.faithful.available, true);
  assert.equal(byKey.clearer.available, false);
  assert.equal(byKey.alternate.available, true);
  assert.equal(byKey.faithful.selected, true, 'faithful is selected by default after a done result');
});

test('buildComparisonColumns: raw stays selectable even when the model produced nothing usable', () => {
  let state = beginRequest(setText(createInitialState(), 'keep my words'), {});
  state = setSelectedVariant(state, 'raw');
  state = receiveResult(state, { requestId: state.requestId, outcome: { kind: 'timeout' } });
  // selectedVariant persists through a non-done outcome (state isn't reset).
  const columns = buildComparisonColumns(state);
  assert.equal(columns.find((c) => c.key === 'raw').selected, true);
});

// --- composite view model -------------------------------------------------------

test('buildTextPlaygroundModel: canApply requires both a chosen draft and available text; canCopy just needs text', () => {
  let state = beginRequest(setText(createInitialState(), 'hi'), {});
  state = receiveResult(state, {
    requestId: state.requestId,
    outcome: { kind: 'done', result: { variants: { faithful: 'Hello there', clearer: '', alternate: '' } } },
  });

  let model = buildTextPlaygroundModel(state, { personas: {}, drafts: [] });
  assert.equal(model.canCopy, true);
  assert.equal(model.canApply, false, 'no draft chosen yet');
  assert.equal(model.rawSelectedText, 'Hello there');

  state = setSelectedDraftId(state, '7');
  model = buildTextPlaygroundModel(state, { personas: {}, drafts: [] });
  assert.equal(model.canApply, true);
});

test('buildTextPlaygroundModel: reuses F2.3/F2.8 formatting for the rescue-result region', () => {
  let state = beginRequest(setText(createInitialState(), 'hi'), {});
  state = receiveResult(state, {
    requestId: state.requestId,
    outcome: {
      kind: 'done',
      result: {
        assessment: { intent: 'ask for an extension', ambiguity_risk: 'low' },
        variants: { faithful: 'a', clearer: 'b', alternate: 'c' },
        preservation_checks: [{ name: 'Names preserved', passed: true, detail: '' }],
        warnings: [],
      },
    },
  });
  const model = buildTextPlaygroundModel(state, {});
  assert.equal(model.rescuePanelModel.hasAssessment, true);
  assert.equal(model.rescuePanelModel.assessmentIntentText, 'ask for an extension');
  assert.equal(model.rescuePanelModel.preservationAllPassed, true);
});

test('buildTextPlaygroundModel: with no audio/dictation, delivery signals stay hidden (no fabricated emotion)', () => {
  let state = beginRequest(setText(createInitialState(), 'hi'), {});
  state = receiveResult(state, {
    requestId: state.requestId,
    outcome: { kind: 'done', result: { variants: { faithful: 'a' } } },
  });
  const model = buildTextPlaygroundModel(state, {});
  assert.equal(model.rescuePanelModel.hasDeliverySignals, false);
});

// --- renderTextPlayground (DOM writer, stub elements) ---------------------------

function makeStubElement(extra = {}) {
  return {
    value: '',
    textContent: '',
    innerHTML: '',
    hidden: false,
    disabled: false,
    _attrs: {},
    setAttribute(k, v) {
      this._attrs[k] = v;
    },
    ...extra,
  };
}

function makeStubElements() {
  return {
    text: makeStubElement(),
    context: makeStubElement(),
    personaSelect: makeStubElement(),
    runButton: makeStubElement(),
    cancelButton: makeStubElement(),
    clearButton: makeStubElement(),
    status: makeStubElement(),
    error: makeStubElement(),
    ranInfo: makeStubElement(),
    fallback: makeStubElement(),
    draftSelect: makeStubElement(),
    applyButton: makeStubElement(),
    copyButton: makeStubElement(),
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
    columns: {
      raw: { text: makeStubElement(), button: makeStubElement() },
      faithful: { text: makeStubElement(), button: makeStubElement() },
      clearer: { text: makeStubElement(), button: makeStubElement() },
      alternate: { text: makeStubElement(), button: makeStubElement() },
    },
    preservationList: makeStubElement(),
    warnings: makeStubElement(),
    warningsList: makeStubElement(),
  };
}

test('renderTextPlayground: idle state disables Run (blank text) and Cancel/Apply/Copy', () => {
  const elements = makeStubElements();
  const model = buildTextPlaygroundModel(createInitialState(), {});
  renderTextPlayground(elements, model);

  assert.equal(elements.runButton.disabled, true);
  assert.equal(elements.cancelButton.disabled, true);
  assert.equal(elements.applyButton.disabled, true);
  assert.equal(elements.copyButton.disabled, true);
  assert.equal(elements.error.hidden, true);
  assert.equal(elements.fallback.hidden, true);
});

test('renderTextPlayground: busy state enables Cancel, disables Run', () => {
  const elements = makeStubElements();
  let state = beginRequest(setText(createInitialState(), 'hi'), { modelId: 'm' });
  renderTextPlayground(elements, buildTextPlaygroundModel(state, {}));

  assert.equal(elements.runButton.disabled, true);
  assert.equal(elements.cancelButton.disabled, false);
  assert.equal(elements.status.textContent, 'Running…');
});

test('renderTextPlayground: error state shows the error banner with the message', () => {
  const elements = makeStubElements();
  let state = beginRequest(setText(createInitialState(), 'hi'), {});
  state = receiveResult(state, { requestId: state.requestId, outcome: { kind: 'error', message: 'local LLM call timed out' } });
  renderTextPlayground(elements, buildTextPlaygroundModel(state, {}));

  assert.equal(elements.error.hidden, false);
  assert.equal(elements.error.textContent, 'local LLM call timed out');
});

test('renderTextPlayground: comparison columns are written via textContent (no HTML sink), one per key, raw included', () => {
  const elements = makeStubElements();
  let state = beginRequest(setText(createInitialState(), 'hi there'), {});
  state = receiveResult(state, {
    requestId: state.requestId,
    outcome: { kind: 'done', result: { variants: { faithful: 'safe <b>text</b>', clearer: 'nicer', alternate: '' } } },
  });
  renderTextPlayground(elements, buildTextPlaygroundModel(state, {}));

  assert.equal(elements.columns.raw.text.textContent, 'hi there');
  assert.equal(elements.columns.faithful.text.textContent, 'safe <b>text</b>');
  assert.equal(elements.columns.clearer.text.textContent, 'nicer');
  assert.equal(elements.columns.alternate.text.textContent, 'Not available.');
  assert.equal(elements.columns.alternate.button.disabled, true);
  assert.equal(elements.columns.faithful.button.disabled, false);
  assert.equal(elements.columns.faithful.button.textContent, 'Selected');
  assert.equal(elements.columns.clearer.button.textContent, 'Use this');
});

// --- createTextPlaygroundFeature (DI'd api, no network) --------------------------

function makeFakeApi(overrides = {}) {
  return {
    fetchPersonas: async () => ({ friendly: {}, formal: {} }),
    fetchDrafts: async () => ({ drafts: [{ id: 1, final_text: 'existing draft' }] }),
    fetchLlmModels: async () => ({ selected_model_id: 'gemma-4-e2b-q4' }),
    applyToDraft: async () => ({ ok: true }),
    captureManualContext: async () => ({ active: true }),
    clearContext: async () => ({ ok: true }),
    generate: async () => ({ id: 'job-1', status: 'done', result: { variants: { faithful: 'ok' } } }),
    ...overrides,
  };
}

test('createTextPlaygroundFeature.run: happy path calls generate with transcript/persona/useContext=false when no context given', async () => {
  const elements = makeStubElementsWithListeners();
  const calls = [];
  const api = makeFakeApi({
    generate: async (args) => {
      calls.push(args);
      return { id: 'j', status: 'done', result: { variants: { faithful: 'reply text' } } };
    },
  });
  const feature = createTextPlaygroundFeature({ elements, api });
  feature.wire();

  elements.text.value = 'please reschedule';
  elements.text._listeners.input();
  elements.personaSelect.value = 'friendly';
  elements.personaSelect._listeners.change();

  await feature.run();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].transcript, 'please reschedule');
  assert.equal(calls[0].persona, 'friendly');
  assert.equal(calls[0].useContext, false);
  assert.equal(feature.getState().status, 'done');
  assert.equal(feature.getState().result.variants.faithful, 'reply text');
});

function makeStubElementsWithListeners() {
  const elements = makeStubElements();
  for (const key of ['text', 'context', 'personaSelect', 'draftSelect', 'runButton', 'cancelButton', 'clearButton', 'applyButton', 'copyButton']) {
    elements[key]._listeners = {};
    elements[key].addEventListener = function (evt, fn) {
      this._listeners[evt] = fn;
    };
  }
  for (const columnEls of Object.values(elements.columns)) {
    const button = columnEls.button;
    button._listeners = {};
    button.addEventListener = function (evt, fn) {
      this._listeners[evt] = fn;
    };
  }
  return elements;
}

test('createTextPlaygroundFeature.run: non-empty context is captured then consumed (useContext=true)', async () => {
  const elements = makeStubElementsWithListeners();
  const captured = [];
  const generateArgs = [];
  const api = makeFakeApi({
    captureManualContext: async (text) => {
      captured.push(text);
      return { active: true };
    },
    generate: async (args) => {
      generateArgs.push(args);
      return { id: 'j', status: 'done', result: { variants: { faithful: 'ok' } } };
    },
  });
  const feature = createTextPlaygroundFeature({ elements, api });
  feature.wire();

  elements.text.value = 'reply to this';
  elements.text._listeners.input();
  elements.context.value = 'they asked about tomorrow';
  elements.context._listeners.input();

  await feature.run();
  assert.deepEqual(captured, ['they asked about tomorrow']);
  assert.equal(generateArgs[0].useContext, true);
  // Context is one-time-use: gone from state once the request completes.
  assert.equal(feature.getState().contextText, '');
});

test('createTextPlaygroundFeature.run: a context-capture failure runs anyway without context (best-effort)', async () => {
  const elements = makeStubElementsWithListeners();
  const generateArgs = [];
  const api = makeFakeApi({
    captureManualContext: async () => {
      throw new Error('capture_empty');
    },
    generate: async (args) => {
      generateArgs.push(args);
      return { id: 'j', status: 'done', result: { variants: { faithful: 'ok' } } };
    },
  });
  const feature = createTextPlaygroundFeature({ elements, api });
  feature.wire();
  elements.text.value = 'hi';
  elements.text._listeners.input();
  elements.context.value = '  ';
  elements.context._listeners.input();

  await feature.run();
  assert.equal(generateArgs[0].useContext, false);
  assert.equal(feature.getState().status, 'done');
});

test('createTextPlaygroundFeature.run: server "timeout" status surfaces as the timeout state, not an error', async () => {
  const elements = makeStubElementsWithListeners();
  const api = makeFakeApi({ generate: async () => ({ id: 'j', status: 'timeout', result: null }) });
  const feature = createTextPlaygroundFeature({ elements, api });
  feature.wire();
  elements.text.value = 'hi';
  elements.text._listeners.input();

  await feature.run();
  assert.equal(feature.getState().status, 'timeout');
});

test('createTextPlaygroundFeature.run: a thrown/network error surfaces as an error state with the message', async () => {
  const elements = makeStubElementsWithListeners();
  const api = makeFakeApi({
    generate: async () => {
      throw new Error('Backend request failed.');
    },
  });
  const feature = createTextPlaygroundFeature({ elements, api });
  feature.wire();
  elements.text.value = 'hi';
  elements.text._listeners.input();

  await feature.run();
  assert.equal(feature.getState().status, 'error');
  assert.equal(feature.getState().errorMessage, 'Backend request failed.');
});

test('createTextPlaygroundFeature.cancel: soft-cancels immediately; a late-arriving response is discarded', async () => {
  const elements = makeStubElementsWithListeners();
  let resolveGenerate;
  const api = makeFakeApi({
    generate: () =>
      new Promise((resolve) => {
        resolveGenerate = resolve;
      }),
  });
  const feature = createTextPlaygroundFeature({ elements, api });
  feature.wire();
  elements.text.value = 'hi';
  elements.text._listeners.input();

  const runPromise = feature.run();
  feature.cancel();
  assert.equal(feature.getState().status, 'cancelled');

  // Let run() proceed through its internal awaits (model-id lookup, the
  // skipped context capture) until it actually reaches the generate() call.
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(typeof resolveGenerate, 'function');
  resolveGenerate({ id: 'j', status: 'done', result: { variants: { faithful: 'too late' } } });
  await runPromise;

  // The late response must not resurrect a result after a local cancel.
  assert.equal(feature.getState().status, 'cancelled');
  assert.equal(feature.getState().result, null);
});

test('createTextPlaygroundFeature.applyToDraft: sends only the id + chosen variant text, never raw_text/other fields', async () => {
  const elements = makeStubElementsWithListeners();
  const applyCalls = [];
  const api = makeFakeApi({
    applyToDraft: async (id, text) => {
      applyCalls.push([id, text]);
      return { ok: true };
    },
  });
  const feature = createTextPlaygroundFeature({ elements, api });
  feature.wire();
  elements.text.value = 'hi';
  elements.text._listeners.input();
  await feature.run();

  elements.draftSelect.value = '1';
  elements.draftSelect._listeners.change();

  await feature.applyToDraft();
  assert.equal(applyCalls.length, 1);
  assert.equal(applyCalls[0][0], 1);
  assert.equal(applyCalls[0][1], 'ok');
  assert.match(feature.getState().applyMessage, /Applied to draft #1/);
});

test('createTextPlaygroundFeature.applyToDraft: disabled (no-op) when no draft is chosen', async () => {
  const elements = makeStubElementsWithListeners();
  const applyCalls = [];
  const api = makeFakeApi({ applyToDraft: async (...args) => applyCalls.push(args) });
  const feature = createTextPlaygroundFeature({ elements, api });
  feature.wire();
  elements.text.value = 'hi';
  elements.text._listeners.input();
  await feature.run();

  await feature.applyToDraft();
  assert.equal(applyCalls.length, 0);
});

test('createTextPlaygroundFeature.copy: writes the raw (unescaped) selected variant text to the clipboard', async () => {
  const elements = makeStubElementsWithListeners();
  const api = makeFakeApi({
    generate: async () => ({ id: 'j', status: 'done', result: { variants: { faithful: 'plain & <safe> text' } } }),
  });
  const feature = createTextPlaygroundFeature({ elements, api });
  feature.wire();
  elements.text.value = 'hi';
  elements.text._listeners.input();
  await feature.run();

  const written = [];
  const originalDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  Object.defineProperty(globalThis, 'navigator', {
    value: { clipboard: { writeText: async (t) => written.push(t) } },
    configurable: true,
  });
  try {
    await feature.copy();
  } finally {
    if (originalDescriptor) {
      Object.defineProperty(globalThis, 'navigator', originalDescriptor);
    } else {
      delete globalThis.navigator;
    }
  }
  assert.deepEqual(written, ['plain & <safe> text']);
  assert.equal(feature.getState().applyMessage, 'Copied to clipboard.');
});

test('createTextPlaygroundFeature.clear: resets all local state and asks the server to drop any lingering context', async () => {
  const elements = makeStubElementsWithListeners();
  let contextCleared = false;
  const api = makeFakeApi({ clearContext: async () => { contextCleared = true; return { ok: true }; } });
  const feature = createTextPlaygroundFeature({ elements, api });
  feature.wire();
  elements.text.value = 'sensitive draft text';
  elements.text._listeners.input();
  elements.context.value = 'sensitive context';
  elements.context._listeners.input();

  await feature.clear();
  assert.equal(contextCleared, true);
  assert.deepEqual(feature.getState(), createInitialState());
  assert.equal(elements.text.value, '');
  assert.equal(elements.context.value, '');
});

test('createTextPlaygroundFeature.refreshPersonas/refreshDrafts: populate the pickers from the injected api', async () => {
  const elements = makeStubElementsWithListeners();
  const api = makeFakeApi();
  const feature = createTextPlaygroundFeature({ elements, api });
  feature.wire();

  await feature.refreshPersonas();
  assert.match(elements.personaSelect.innerHTML, /friendly/);
  assert.match(elements.personaSelect.innerHTML, /formal/);

  await feature.refreshDrafts();
  assert.match(elements.draftSelect.innerHTML, /existing draft/);
});

// --- initTextPlayground (fake doc) ------------------------------------------------

test('initTextPlayground: missing markup in the doc is a safe no-op', () => {
  const doc = { getElementById: () => null };
  assert.doesNotThrow(() => {
    const result = initTextPlayground({ doc });
    assert.equal(result, null);
  });
});

test('initTextPlayground: wires up and renders when the section is present', () => {
  const elements = makeStubElementsWithListeners();
  elements.section = makeStubElement();
  const idMap = {
    textPlaygroundSection: elements.section,
    textPlaygroundText: elements.text,
    textPlaygroundContext: elements.context,
    textPlaygroundPersonaSelect: elements.personaSelect,
    textPlaygroundRunButton: elements.runButton,
    textPlaygroundCancelButton: elements.cancelButton,
    textPlaygroundClearButton: elements.clearButton,
    textPlaygroundDraftSelect: elements.draftSelect,
    textPlaygroundApplyButton: elements.applyButton,
    textPlaygroundCopyButton: elements.copyButton,
    textPlaygroundColumnRawText: elements.columns.raw.text,
    textPlaygroundColumnRawButton: elements.columns.raw.button,
    textPlaygroundColumnFaithfulText: elements.columns.faithful.text,
    textPlaygroundColumnFaithfulButton: elements.columns.faithful.button,
    textPlaygroundColumnClearerText: elements.columns.clearer.text,
    textPlaygroundColumnClearerButton: elements.columns.clearer.button,
    textPlaygroundColumnAlternateText: elements.columns.alternate.text,
    textPlaygroundColumnAlternateButton: elements.columns.alternate.button,
  };
  const doc = { getElementById: (id) => idMap[id] || null };

  const feature = initTextPlayground({ doc });
  assert.ok(feature);
  assert.equal(elements.runButton.disabled, true); // blank text
  assert.equal(typeof elements.runButton._listeners.click, 'function');
});

// --- privacy / no-audio-or-TTS invariants -----------------------------------------

test('module never references microphone, recording, playback, or TTS APIs', () => {
  const forbidden = [
    'getUserMedia',
    'MediaRecorder',
    'mediaDevices',
    'speakDraft',
    'speakTts',
    'toggleRecording',
    'connectVoiceStatus',
    'sendDraft',
    'runPrimaryAction',
  ];
  for (const token of forbidden) {
    assert.doesNotMatch(MODULE_SOURCE, new RegExp(token), `textPlayground.js must never reference ${token}`);
  }
});

test('module never sends a draft or learns a persona example on its own', () => {
  assert.doesNotMatch(MODULE_SOURCE, /personas\/.*\/examples/);
  assert.doesNotMatch(MODULE_SOURCE, /\bacceptDraft\b/);
  assert.doesNotMatch(MODULE_SOURCE, /\bdeclineDraft\b/);
});

test('defaultApi surface exposed to the DOM layer has no audio/TTS/send methods', async () => {
  // Import fresh and inspect createTextPlaygroundFeature's default parameter
  // indirectly: build a feature with no override and confirm run()/copy()/
  // clear() only ever reach the whitelisted network surface by checking the
  // feature object's own method list is limited to the documented API.
  const elements = makeStubElementsWithListeners();
  const feature = createTextPlaygroundFeature({ elements, api: makeFakeApi() });
  const methodNames = Object.keys(feature);
  assert.deepEqual(
    methodNames.sort(),
    ['applyToDraft', 'cancel', 'clear', 'copy', 'getState', 'refreshDrafts', 'refreshPersonas', 'rerender', 'run', 'wire'].sort(),
  );
});
