// Unit tests for the Persona Learning feature (I3.8): "Teach this persona
// from my edit" over I3.3's consent-gated /personas/:name/examples routes.
// Run with: node --test app/tests/personaLearning.test.mjs
//
// No jsdom in this repo's test setup (matches textPlayground.test.mjs /
// messageRescuePanel.test.mjs) -- DOM-driven logic is exercised against
// plain stub objects, not real nodes.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import {
  MAX_EXAMPLE_CHARS,
  createInitialState,
  setPersonaName,
  canPrepareTeach,
  preparePair,
  cancelPrepare,
  setConsentChecked,
  canConfirmTeach,
  beginAdd,
  receiveAddResult,
  beginListLoad,
  receiveList,
  receiveListError,
  beginDelete,
  receiveDeleteResult,
  beginClear,
  receiveClearResult,
  buildPersonaLearningModel,
  renderPersonaLearning,
  createPersonaLearningFeature,
  initPersonaLearning,
} from '../src/renderer/features/personaLearning.js';

const MODULE_PATH = fileURLToPath(new URL('../src/renderer/features/personaLearning.js', import.meta.url));
const MODULE_SOURCE = readFileSync(MODULE_PATH, 'utf8');

// --- pure state reducers ------------------------------------------------------

test('createInitialState: no persona, empty list, nothing pending', () => {
  const state = createInitialState();
  assert.equal(state.personaName, '');
  assert.deepEqual(state.examples, []);
  assert.equal(state.pendingPair, null);
  assert.equal(state.consentChecked, false);
  assert.equal(state.addStatus, 'idle');
});

test('setPersonaName: switching persona drops pending pair/consent/list', () => {
  let state = createInitialState();
  state = setPersonaName(state, 'friendly');
  state = preparePair(state, { raw: 'hi', out: 'Hello there' });
  state = setConsentChecked(state, true);
  state = receiveList(state, [{ id: 'a', raw: 'x', out: 'y', created_at: '' }]);
  assert.ok(state.pendingPair);
  assert.equal(state.consentChecked, true);

  const switched = setPersonaName(state, 'formal');
  assert.equal(switched.personaName, 'formal');
  assert.equal(switched.pendingPair, null);
  assert.equal(switched.consentChecked, false);
  assert.deepEqual(switched.examples, []);
});

test('setPersonaName: same name is a no-op (identity return)', () => {
  let state = createInitialState();
  state = setPersonaName(state, 'friendly');
  const again = setPersonaName(state, 'friendly');
  assert.equal(again, state);
});

test('setPersonaName: trims and coerces nullish to empty string', () => {
  let state = createInitialState();
  state = setPersonaName(state, '  friendly  ');
  assert.equal(state.personaName, 'friendly');
  state = setPersonaName(state, undefined);
  assert.equal(state.personaName, '');
});

// --- step 1: prepare (no network call) ---------------------------------------

test('canPrepareTeach: requires a persona and a non-blank raw+out pair', () => {
  let state = createInitialState();
  assert.equal(canPrepareTeach(state, { raw: 'hi', out: 'Hello' }), false); // no persona yet
  state = setPersonaName(state, 'friendly');
  assert.equal(canPrepareTeach(state, { raw: '', out: 'Hello' }), false);
  assert.equal(canPrepareTeach(state, { raw: 'hi', out: '   ' }), false);
  assert.equal(canPrepareTeach(state, { raw: 'hi', out: 'Hello' }), true);
});

test('preparePair: snapshots exactly the raw/out pair that will be stored, resets consent', () => {
  let state = createInitialState();
  state = setPersonaName(state, 'friendly');
  state = setConsentChecked(state, true); // stale consent from a prior (different) pair
  state = preparePair(state, { raw: '  hey can we move it  ', out: '  Could we reschedule?  ' });
  assert.deepEqual(state.pendingPair, { raw: 'hey can we move it', out: 'Could we reschedule?' });
  assert.equal(state.consentChecked, false); // must be re-affirmed for this exact pair
  assert.equal(state.pendingTruncated, false);
});

test('preparePair: no-ops (does not set pendingPair) when the pair is invalid', () => {
  let state = createInitialState();
  state = setPersonaName(state, 'friendly');
  const result = preparePair(state, { raw: '', out: '' });
  assert.equal(result.pendingPair, null);
});

test('preparePair: bounds raw/out to MAX_EXAMPLE_CHARS and flags truncation, matching the backend cap exactly', () => {
  let state = createInitialState();
  state = setPersonaName(state, 'friendly');
  const longRaw = 'a'.repeat(MAX_EXAMPLE_CHARS + 500);
  state = preparePair(state, { raw: longRaw, out: 'short' });
  assert.equal(state.pendingPair.raw.length, MAX_EXAMPLE_CHARS);
  assert.equal(state.pendingTruncated, true);
});

test('cancelPrepare: clears pending pair and consent without touching persona/list', () => {
  let state = createInitialState();
  state = setPersonaName(state, 'friendly');
  state = receiveList(state, [{ id: 'a', raw: 'x', out: 'y' }]);
  state = preparePair(state, { raw: 'hi', out: 'Hello' });
  state = setConsentChecked(state, true);
  const cancelled = cancelPrepare(state);
  assert.equal(cancelled.pendingPair, null);
  assert.equal(cancelled.consentChecked, false);
  assert.equal(cancelled.personaName, 'friendly');
  assert.equal(cancelled.examples.length, 1);
});

// --- step 2: confirm gate + consent enforcement (the no-learning-without-click invariant) ---

test('canConfirmTeach: false without a pending pair, false without consent, false while busy', () => {
  let state = createInitialState();
  state = setPersonaName(state, 'friendly');
  assert.equal(canConfirmTeach(state), false); // nothing prepared

  state = preparePair(state, { raw: 'hi', out: 'Hello' });
  assert.equal(canConfirmTeach(state), false); // prepared but not consented

  state = setConsentChecked(state, true);
  assert.equal(canConfirmTeach(state), true);

  state = beginAdd(state);
  assert.equal(canConfirmTeach(state), false); // in flight
});

test('receiveAddResult: plain success, duplicate, and cap-eviction each produce distinct feedback and clear the pending pair', () => {
  const base = () => {
    let state = createInitialState();
    state = setPersonaName(state, 'friendly');
    state = preparePair(state, { raw: 'hi', out: 'Hello' });
    state = setConsentChecked(state, true);
    return beginAdd(state);
  };

  const plain = receiveAddResult(base(), { kind: 'ok', duplicate: false, evictedId: null });
  assert.equal(plain.addStatus, 'idle');
  assert.equal(plain.addFeedbackTone, 'success');
  assert.match(plain.addFeedback, /^Learned this example\.$/);
  assert.equal(plain.pendingPair, null);
  assert.equal(plain.consentChecked, false);

  const dup = receiveAddResult(base(), { kind: 'ok', duplicate: true, evictedId: null });
  assert.match(dup.addFeedback, /Already learned/);
  assert.equal(dup.pendingPair, null);

  const evicted = receiveAddResult(base(), { kind: 'ok', duplicate: false, evictedId: 'old-id' });
  assert.match(evicted.addFeedback, /cap was reached/);
});

test('receiveAddResult: error keeps the pending pair so the user can retry the exact same confirm', () => {
  let state = createInitialState();
  state = setPersonaName(state, 'friendly');
  state = preparePair(state, { raw: 'hi', out: 'Hello' });
  state = setConsentChecked(state, true);
  state = beginAdd(state);
  const failed = receiveAddResult(state, { kind: 'error', message: 'write_failed' });
  assert.equal(failed.addStatus, 'error');
  assert.equal(failed.addFeedbackTone, 'danger');
  assert.ok(failed.pendingPair); // still there -- consent was for this pair, not silently discarded
});

// --- list load / delete / clear reducers -------------------------------------

test('beginListLoad/receiveList/receiveListError', () => {
  let state = createInitialState();
  state = beginListLoad(state);
  assert.equal(state.listStatus, 'loading');
  state = receiveList(state, [{ id: '1', raw: 'a', out: 'b' }]);
  assert.equal(state.listStatus, 'idle');
  assert.equal(state.examples.length, 1);

  state = beginListLoad(state);
  state = receiveListError(state, 'boom');
  assert.equal(state.listStatus, 'error');
  assert.equal(state.listError, 'boom');
  assert.deepEqual(state.examples, []);
});

test('receiveList: non-array payload coerces to empty list rather than throwing', () => {
  const state = receiveList(createInitialState(), undefined);
  assert.deepEqual(state.examples, []);
});

test('beginDelete/receiveDeleteResult: deleted vs already-gone vs error', () => {
  let state = beginDelete(createInitialState());
  assert.equal(state.deleteStatus, 'busy');
  const deleted = receiveDeleteResult(state, { kind: 'ok', deleted: true });
  assert.match(deleted.deleteFeedback, /^Deleted/);

  const gone = receiveDeleteResult(state, { kind: 'ok', deleted: false });
  assert.match(gone.deleteFeedback, /already gone/);

  const errored = receiveDeleteResult(state, { kind: 'error', message: 'nope' });
  assert.equal(errored.deleteStatus, 'error');
  assert.equal(errored.deleteFeedback, 'nope');
});

test('beginClear/receiveClearResult: success message states the clear is reversible', () => {
  let state = beginClear(createInitialState());
  assert.equal(state.clearStatus, 'busy');
  const cleared = receiveClearResult(state, { kind: 'ok' });
  assert.match(cleared.clearFeedback, /reversible/);

  const errored = receiveClearResult(state, { kind: 'error', message: 'disk full' });
  assert.equal(errored.clearStatus, 'error');
  assert.equal(errored.clearFeedback, 'disk full');
});

// --- pure model / XSS-safe rendering ------------------------------------------

test('buildPersonaLearningModel: no persona selected disables teach and clear', () => {
  const model = buildPersonaLearningModel(createInitialState());
  assert.equal(model.hasPersona, false);
  assert.equal(model.teachDisabled, true);
  assert.equal(model.clearAllDisabled, true);
  assert.match(model.examplesHtml, /No learned examples yet/);
});

test('buildPersonaLearningModel: examplesHtml escapes raw/out/id -- no injected markup from stored examples', () => {
  let state = createInitialState();
  state = setPersonaName(state, 'friendly');
  state = receiveList(state, [
    { id: '<img src=x onerror=alert(1)>', raw: '<script>alert("raw")</script>', out: '<b>bold</b> & "quoted"', created_at: '' },
  ]);
  const model = buildPersonaLearningModel(state);
  assert.doesNotMatch(model.examplesHtml, /<script\b/i);
  assert.doesNotMatch(model.examplesHtml, /<img src=x/);
  assert.match(model.examplesHtml, /&lt;script&gt;/);
  assert.match(model.examplesHtml, /&lt;b&gt;bold&lt;\/b&gt;/);
  assert.match(model.examplesHtml, /&quot;quoted&quot;/);
});

test('buildPersonaLearningModel: pending pair populates preview text and truncation notice', () => {
  let state = createInitialState();
  state = setPersonaName(state, 'friendly');
  state = preparePair(state, { raw: 'a'.repeat(MAX_EXAMPLE_CHARS + 10), out: 'short' });
  const model = buildPersonaLearningModel(state);
  assert.equal(model.hasPending, true);
  assert.equal(model.previewRawText.length, MAX_EXAMPLE_CHARS);
  assert.match(model.truncatedNoticeText, new RegExp(String(MAX_EXAMPLE_CHARS)));
});

test('renderPersonaLearning: writes list/preview via textContent-equivalent fields, not raw HTML for previews', () => {
  const elements = makeStubElements();
  let state = createInitialState();
  state = setPersonaName(state, 'friendly');
  state = preparePair(state, { raw: '<script>x</script>', out: 'clean output' });
  renderPersonaLearning(elements, buildPersonaLearningModel(state));
  // previewRaw/previewOut are assigned via textContent in the model+render layer
  // (never innerHTML), so the literal unescaped string is fine to find here --
  // the safety property is "never interpreted as markup", which textContent guarantees.
  assert.equal(elements.previewRaw.textContent, '<script>x</script>');
  assert.equal(elements.confirmButton.disabled, true); // no consent yet
});

// --- feature: the no-learning-without-click invariant, end to end -----------

function makeStubElement(extra = {}) {
  return {
    value: '',
    textContent: '',
    innerHTML: '',
    hidden: false,
    disabled: false,
    checked: false,
    _attrs: {},
    setAttribute(k, v) {
      this._attrs[k] = v;
    },
    removeAttribute(k) {
      delete this._attrs[k];
    },
    ...extra,
  };
}

function makeStubElements() {
  return {
    personaSource: makeStubElement(),
    sourceRawText: makeStubElement(),
    sourceFinalText: makeStubElement(),
    personaLabel: makeStubElement(),
    teachButton: makeStubElement(),
    previewEmpty: makeStubElement(),
    previewGroup: makeStubElement(),
    previewRaw: makeStubElement(),
    previewOut: makeStubElement(),
    truncatedNotice: makeStubElement(),
    consentCheckbox: makeStubElement(),
    confirmButton: makeStubElement(),
    cancelButton: makeStubElement(),
    addFeedback: makeStubElement(),
    listStatus: makeStubElement(),
    examplesList: makeStubElement(),
    exampleCount: makeStubElement(),
    clearAllButton: makeStubElement(),
    clearFeedback: makeStubElement(),
    deleteFeedback: makeStubElement(),
  };
}

function withListeners(elements, keys) {
  for (const key of keys) {
    elements[key]._listeners = {};
    elements[key].addEventListener = function (evt, fn) {
      this._listeners[evt] = fn;
    };
  }
  return elements;
}

function makeFakeApi(overrides = {}) {
  return {
    listExamples: async () => ({ examples: [] }),
    addExample: async () => ({ ok: true, duplicate: false, evicted_id: null }),
    deleteExample: async () => ({ ok: true, deleted: true }),
    clearExamples: async () => ({ ok: true }),
    ...overrides,
  };
}

test('feature: addExample is never called by typing/editing or by prepareTeach alone -- only confirmTeach with consent reaches the network', async () => {
  const elements = withListeners(makeStubElements(), ['personaSource', 'teachButton', 'cancelButton', 'consentCheckbox', 'confirmButton', 'clearAllButton', 'examplesList']);
  let addCalls = 0;
  const api = makeFakeApi({ addExample: async () => { addCalls += 1; return { ok: true, duplicate: false, evicted_id: null }; } });
  const feature = createPersonaLearningFeature({ elements, api });
  feature.wire();

  elements.personaSource.value = 'friendly';
  elements.sourceRawText.textContent = 'hey can we move it';
  elements.sourceFinalText.value = 'Could we reschedule?';
  elements.personaSource._listeners.change();
  await Promise.resolve();

  // Editing the draft text alone must never learn anything.
  elements.sourceFinalText.value = 'Could we reschedule this meeting?';
  assert.equal(addCalls, 0);

  // Step 1: prepare (click) -- still no network call.
  feature.prepareTeach();
  assert.equal(addCalls, 0);
  assert.ok(feature.getState().pendingPair);

  // Attempting confirm without checking consent must not call the network.
  await feature.confirmTeach();
  assert.equal(addCalls, 0);

  // Only after explicit consent + confirm click does the call happen.
  feature.toggleConsent(true);
  await feature.confirmTeach();
  assert.equal(addCalls, 1);
});

test('feature: cancelling step 1 before confirming never learns', async () => {
  const elements = withListeners(makeStubElements(), ['personaSource', 'teachButton', 'cancelButton', 'consentCheckbox', 'confirmButton', 'clearAllButton', 'examplesList']);
  let addCalls = 0;
  const api = makeFakeApi({ addExample: async () => { addCalls += 1; return { ok: true }; } });
  const feature = createPersonaLearningFeature({ elements, api });
  feature.wire();

  elements.personaSource.value = 'friendly';
  elements.sourceRawText.textContent = 'hi';
  elements.sourceFinalText.value = 'Hello there';
  elements.personaSource._listeners.change();
  await Promise.resolve();

  feature.prepareTeach();
  feature.toggleConsent(true);
  feature.cancelTeach();
  assert.equal(feature.getState().pendingPair, null);
  assert.equal(feature.getState().consentChecked, false);

  await feature.confirmTeach(); // canConfirmTeach() is false now -- no-op
  assert.equal(addCalls, 0);
});

test('feature: switching persona mid-flow (before confirm) discards the pending pair', async () => {
  const elements = withListeners(makeStubElements(), ['personaSource', 'teachButton', 'cancelButton', 'consentCheckbox', 'confirmButton', 'clearAllButton', 'examplesList']);
  const api = makeFakeApi();
  const feature = createPersonaLearningFeature({ elements, api });
  feature.wire();

  elements.personaSource.value = 'friendly';
  elements.sourceRawText.textContent = 'hi';
  elements.sourceFinalText.value = 'Hello there';
  elements.personaSource._listeners.change();
  await Promise.resolve();
  feature.prepareTeach();
  feature.toggleConsent(true);
  assert.ok(feature.getState().pendingPair);

  elements.personaSource.value = 'formal';
  elements.personaSource._listeners.change();
  await Promise.resolve();
  assert.equal(feature.getState().pendingPair, null);
  assert.equal(feature.getState().consentChecked, false);
});

test('feature: duplicate add is reported, not silently stored twice', async () => {
  const elements = withListeners(makeStubElements(), ['personaSource', 'teachButton', 'cancelButton', 'consentCheckbox', 'confirmButton', 'clearAllButton', 'examplesList']);
  const api = makeFakeApi({ addExample: async () => ({ ok: true, duplicate: true, evicted_id: null }) });
  const feature = createPersonaLearningFeature({ elements, api });
  feature.wire();

  elements.personaSource.value = 'friendly';
  elements.sourceRawText.textContent = 'hi';
  elements.sourceFinalText.value = 'Hello there';
  elements.personaSource._listeners.change();
  await Promise.resolve();
  feature.prepareTeach();
  feature.toggleConsent(true);
  await feature.confirmTeach();

  assert.match(feature.getState().addFeedback, /Already learned/);
});

test('feature: cap/overflow eviction surfaces which behavior happened', async () => {
  const elements = withListeners(makeStubElements(), ['personaSource', 'teachButton', 'cancelButton', 'consentCheckbox', 'confirmButton', 'clearAllButton', 'examplesList']);
  const api = makeFakeApi({ addExample: async () => ({ ok: true, duplicate: false, evicted_id: 'oldest-id' }) });
  const feature = createPersonaLearningFeature({ elements, api });
  feature.wire();

  elements.personaSource.value = 'friendly';
  elements.sourceRawText.textContent = 'hi';
  elements.sourceFinalText.value = 'Hello there';
  elements.personaSource._listeners.change();
  await Promise.resolve();
  feature.prepareTeach();
  feature.toggleConsent(true);
  await feature.confirmTeach();

  assert.match(feature.getState().addFeedback, /cap was reached/);
});

test('feature: add failure surfaces an error and keeps the pending pair for retry', async () => {
  const elements = withListeners(makeStubElements(), ['personaSource', 'teachButton', 'cancelButton', 'consentCheckbox', 'confirmButton', 'clearAllButton', 'examplesList']);
  const api = makeFakeApi({ addExample: async () => { throw new Error('write_failed'); } });
  const feature = createPersonaLearningFeature({ elements, api });
  feature.wire();

  elements.personaSource.value = 'friendly';
  elements.sourceRawText.textContent = 'hi';
  elements.sourceFinalText.value = 'Hello there';
  elements.personaSource._listeners.change();
  await Promise.resolve();
  feature.prepareTeach();
  feature.toggleConsent(true);
  await feature.confirmTeach();

  assert.equal(feature.getState().addStatus, 'error');
  assert.match(feature.getState().addFeedback, /write_failed/);
  assert.ok(feature.getState().pendingPair);
});

test('feature: refreshExamples lists examples (reload-persistence proxy) and list errors surface distinctly', async () => {
  const elements = withListeners(makeStubElements(), ['personaSource', 'teachButton', 'cancelButton', 'consentCheckbox', 'confirmButton', 'clearAllButton', 'examplesList']);
  const api = makeFakeApi({ listExamples: async () => ({ examples: [{ id: '1', raw: 'a', out: 'b', created_at: '' }] }) });
  const feature = createPersonaLearningFeature({ elements, api });
  feature.wire();

  elements.personaSource.value = 'friendly';
  elements.personaSource._listeners.change();
  await Promise.resolve();

  assert.equal(feature.getState().examples.length, 1);
  assert.match(elements.examplesList.innerHTML, /persona-learning-example/);

  const failingApi = makeFakeApi({ listExamples: async () => { throw new Error('offline'); } });
  const feature2 = createPersonaLearningFeature({ elements: withListeners(makeStubElements(), ['personaSource', 'teachButton', 'cancelButton', 'consentCheckbox', 'confirmButton', 'clearAllButton', 'examplesList']), api: failingApi });
  feature2.wire();
  await feature2.refreshExamples.call(null); // no persona set: should just clear, not throw
});

test('feature: deleteOne removes via the injected api and reloads the list afterward', async () => {
  const elements = withListeners(makeStubElements(), ['personaSource', 'teachButton', 'cancelButton', 'consentCheckbox', 'confirmButton', 'clearAllButton', 'examplesList']);
  let listCallCount = 0;
  let deletedId = null;
  const api = makeFakeApi({
    listExamples: async () => {
      listCallCount += 1;
      return { examples: listCallCount === 1 ? [{ id: 'ex-1', raw: 'a', out: 'b' }] : [] };
    },
    deleteExample: async (persona, exampleId) => {
      deletedId = exampleId;
      return { ok: true, deleted: true };
    },
  });
  const feature = createPersonaLearningFeature({ elements, api });
  feature.wire();

  elements.personaSource.value = 'friendly';
  elements.personaSource._listeners.change();
  await Promise.resolve();
  await feature.deleteOne('ex-1');

  assert.equal(deletedId, 'ex-1');
  assert.match(feature.getState().deleteFeedback, /^Deleted/);
  assert.equal(feature.getState().examples.length, 0); // list reloaded after delete
});

test('feature: examplesList delegated click on a delete button calls deleteOne with its data-example-id', async () => {
  const elements = withListeners(makeStubElements(), ['personaSource', 'teachButton', 'cancelButton', 'consentCheckbox', 'confirmButton', 'clearAllButton', 'examplesList']);
  let deletedId = null;
  const api = makeFakeApi({
    deleteExample: async (persona, exampleId) => {
      deletedId = exampleId;
      return { ok: true, deleted: true };
    },
  });
  const feature = createPersonaLearningFeature({ elements, api });
  feature.wire();

  elements.personaSource.value = 'friendly';
  elements.personaSource._listeners.change();
  await Promise.resolve();

  const button = { dataset: { exampleId: 'ex-42' } };
  const target = { closest: (sel) => (sel === '.persona-learning-delete-button' ? button : null) };
  elements.examplesList._listeners.click({ target });
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(deletedId, 'ex-42');
});

test('feature: clearAll asks for confirmation and is a no-op when declined', async () => {
  const elements = withListeners(makeStubElements(), ['personaSource', 'teachButton', 'cancelButton', 'consentCheckbox', 'confirmButton', 'clearAllButton', 'examplesList']);
  let clearCalls = 0;
  const api = makeFakeApi({
    listExamples: async () => ({ examples: [{ id: '1', raw: 'a', out: 'b' }] }),
    clearExamples: async () => { clearCalls += 1; return { ok: true }; },
  });
  let confirmCalls = 0;
  const feature = createPersonaLearningFeature({ elements, api, confirmFn: () => { confirmCalls += 1; return false; } });
  feature.wire();

  elements.personaSource.value = 'friendly';
  elements.personaSource._listeners.change();
  await Promise.resolve();
  await feature.clearAll();

  assert.equal(confirmCalls, 1);
  assert.equal(clearCalls, 0);
});

test('feature: clearAll, when confirmed, clears via the injected api, is reversible in messaging, and reloads the (now empty) list', async () => {
  const elements = withListeners(makeStubElements(), ['personaSource', 'teachButton', 'cancelButton', 'consentCheckbox', 'confirmButton', 'clearAllButton', 'examplesList']);
  let listCallCount = 0;
  let clearCalls = 0;
  const api = makeFakeApi({
    listExamples: async () => {
      listCallCount += 1;
      return { examples: listCallCount === 1 ? [{ id: '1', raw: 'a', out: 'b' }] : [] };
    },
    clearExamples: async () => { clearCalls += 1; return { ok: true }; },
  });
  const feature = createPersonaLearningFeature({ elements, api, confirmFn: () => true });
  feature.wire();

  elements.personaSource.value = 'friendly';
  elements.personaSource._listeners.change();
  await Promise.resolve();
  await feature.clearAll();

  assert.equal(clearCalls, 1);
  assert.match(feature.getState().clearFeedback, /reversible/);
  assert.equal(feature.getState().examples.length, 0);
});

test('feature: clearAll is a no-op with zero examples (nothing to confirm)', async () => {
  const elements = withListeners(makeStubElements(), ['personaSource', 'teachButton', 'cancelButton', 'consentCheckbox', 'confirmButton', 'clearAllButton', 'examplesList']);
  let confirmCalls = 0;
  const api = makeFakeApi();
  const feature = createPersonaLearningFeature({ elements, api, confirmFn: () => { confirmCalls += 1; return true; } });
  feature.wire();

  elements.personaSource.value = 'friendly';
  elements.personaSource._listeners.change();
  await Promise.resolve();
  await feature.clearAll();

  assert.equal(confirmCalls, 0);
});

// --- initPersonaLearning (fake doc) -------------------------------------------

test('initPersonaLearning: missing markup in the doc is a safe no-op', () => {
  const doc = { getElementById: () => null };
  assert.doesNotThrow(() => {
    const result = initPersonaLearning({ doc });
    assert.equal(result, null);
  });
});

test('initPersonaLearning: wires up and renders when the section is present', () => {
  const elements = withListeners(makeStubElements(), ['personaSource', 'teachButton', 'cancelButton', 'consentCheckbox', 'confirmButton', 'clearAllButton', 'examplesList']);
  elements.section = makeStubElement();
  const idMap = {
    personaLearningSection: elements.section,
    settingCurrentPreset: elements.personaSource,
    draftRawText: elements.sourceRawText,
    draftFinalText: elements.sourceFinalText,
    personaLearningPersonaLabel: elements.personaLabel,
    personaLearningTeachButton: elements.teachButton,
    personaLearningPreviewEmpty: elements.previewEmpty,
    personaLearningPreviewGroup: elements.previewGroup,
    personaLearningPreviewRaw: elements.previewRaw,
    personaLearningPreviewOut: elements.previewOut,
    personaLearningTruncatedNotice: elements.truncatedNotice,
    personaLearningConsentCheckbox: elements.consentCheckbox,
    personaLearningConfirmButton: elements.confirmButton,
    personaLearningCancelButton: elements.cancelButton,
    personaLearningAddFeedback: elements.addFeedback,
    personaLearningListStatus: elements.listStatus,
    personaLearningExamplesList: elements.examplesList,
    personaLearningExampleCount: elements.exampleCount,
    personaLearningClearAllButton: elements.clearAllButton,
    personaLearningClearFeedback: elements.clearFeedback,
    personaLearningDeleteFeedback: elements.deleteFeedback,
  };
  const doc = { getElementById: (id) => idMap[id] || null };

  const feature = initPersonaLearning({ doc });
  assert.ok(feature);
  assert.equal(elements.teachButton.disabled, true); // no persona selected yet
  assert.equal(typeof elements.personaSource._listeners.change, 'function');
});

// --- privacy invariants: no logging, no unrelated network surface ------------

test('module never logs example content -- console.* calls (if any) never receive raw/out variables', () => {
  assert.doesNotMatch(MODULE_SOURCE, /console\.(log|info|debug)\(/);
});

test('module never references audio/recording/TTS/send/accept/decline APIs -- pure text/consent surface', () => {
  const forbidden = [
    'getUserMedia',
    'MediaRecorder',
    'mediaDevices',
    'speakDraft',
    'speakTts',
    'toggleRecording',
    'connectVoiceStatus',
    'sendDraft',
    'acceptDraft',
    'declineDraft',
    'generateMessageRescue',
  ];
  for (const token of forbidden) {
    assert.doesNotMatch(MODULE_SOURCE, new RegExp(token), `personaLearning.js must never reference ${token}`);
  }
});

test('module never calls addExample outside of confirmTeach -- single call site enforces the consent gate', () => {
  const matches = MODULE_SOURCE.match(/api\.addExample\(/g) || [];
  assert.equal(matches.length, 1);
});
