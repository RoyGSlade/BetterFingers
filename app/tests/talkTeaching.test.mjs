// Unit tests for the Talk teaching-from-edits module (talkTeaching.js) --
// the Wave 2 restoration of D-0018's "editing never learns anything on its
// own" privacy invariant. Mirrors the DOM-stub style already used by
// app/tests/talkWorkspace.test.mjs and app/tests/talkCapture.test.mjs.
//
// Run with: node --test app/tests/talkTeaching.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  TALK_TEACHING_ELEMENT_IDS,
  collectTalkTeachingElements,
  createInitialTeachingState,
  isTeachable,
  captureEdit,
  setTeachingConsent,
  canSubmitTeaching,
  buildTeachingViewModel,
  renderTeaching,
  createTalkTeachingFeature,
} from '../src/renderer/features/talkTeaching.js';

function makeButton() {
  const listeners = {};
  return {
    disabled: false,
    addEventListener(evt, fn) { listeners[evt] = fn; },
    click() { listeners.click?.(); },
  };
}

function makeCheckbox() {
  const listeners = {};
  return {
    checked: false,
    addEventListener(evt, fn) { listeners[evt] = fn; },
    change(next) { this.checked = next; listeners.change?.(); },
  };
}

function makeElements() {
  return {
    panel: { hidden: true },
    rawText: { textContent: '' },
    modelText: { textContent: '' },
    editedText: { textContent: '' },
    personaLabel: { textContent: '' },
    consent: makeCheckbox(),
    confirm: makeButton(),
    dismiss: makeButton(),
    message: { textContent: '', dataset: {}, setAttribute(k, v) { this.dataset[k] = v; }, removeAttribute(k) { delete this.dataset[k]; } },
  };
}

// A stub personaLearning instance modelling the exact composition-root
// wiring this module documents: its own getDraftPair/getPersonaName hooks
// read live from the SAME talkTeaching feature's getState(), same as
// features/studioWorkspace.js wires features/personaLearning.js for Studio's
// panel. This lets these tests prove the "out" text sent through really is
// whatever this module currently holds as editedText, not modelText.
// `refusePrepare` models personaLearning.prepareTeach()'s real refusal
// behaviour: it does NOT throw and does NOT set addStatus -- it just writes
// addFeedback and leaves pendingPair null. The stub must expose pendingPair in
// getState() because that is the only signal distinguishing "prepared" from
// "refused", and the real module clears it on a successful add
// (receiveAddResult's ok branch).
function makeLearningStub(getTeachingState, { refusePrepare = false } = {}) {
  const calls = { prepareTeach: 0, toggleConsent: [], confirmTeach: 0 };
  let pendingPair = null;
  let consentChecked = false;
  let addStatus = 'idle';
  let addFeedback = '';
  let addExampleCalls = [];

  return {
    calls,
    addExampleCalls,
    prepareTeach() {
      calls.prepareTeach += 1;
      if (refusePrepare) {
        addFeedback = 'Nothing to teach yet -- edit the cleaned output first.';
        pendingPair = null;
        return;
      }
      const s = getTeachingState();
      pendingPair = { raw: s.rawText, out: s.editedText };
    },
    toggleConsent(checked) {
      calls.toggleConsent.push(checked);
      consentChecked = Boolean(checked);
    },
    async confirmTeach() {
      calls.confirmTeach += 1;
      if (!pendingPair || !consentChecked) return;
      addExampleCalls.push({ ...pendingPair });
      pendingPair = null;
      consentChecked = false;
      addStatus = 'idle';
      addFeedback = 'Learned this example.';
    },
    getState() {
      return { addStatus, addFeedback, pendingPair };
    },
  };
}

// --- collectTalkTeachingElements ----------------------------------------------

test('collectTalkTeachingElements: every id key present, missing ids resolve to null', () => {
  const fakeDoc = { getElementById: () => null };
  const els = collectTalkTeachingElements(fakeDoc);
  for (const key of Object.keys(TALK_TEACHING_ELEMENT_IDS)) {
    assert.ok(key in els);
    assert.equal(els[key], null);
  }
});

test('collectTalkTeachingElements: resolves whatever the stub document returns for a given id', () => {
  const sentinel = { id: 'sentinel' };
  const fakeDoc = { getElementById: (id) => (id === TALK_TEACHING_ELEMENT_IDS.panel ? sentinel : null) };
  const els = collectTalkTeachingElements(fakeDoc);
  assert.equal(els.panel, sentinel);
  assert.equal(els.rawText, null);
});

// --- isTeachable / captureEdit: the raw/model/edited triple -------------------

test('captureEdit: a real edit with raw/model/edited/persona all present is offered, and the triple survives verbatim', () => {
  const state = createInitialTeachingState();
  const next = captureEdit(state, {
    rawText: 'okay so i should be there around six',
    modelText: 'I should be there around six.',
    editedText: "I'll be there around six sharp.",
    personaName: 'friendly',
  });
  assert.equal(next.offered, true);
  assert.equal(next.rawText, 'okay so i should be there around six');
  assert.equal(next.modelText, 'I should be there around six.');
  assert.equal(next.editedText, "I'll be there around six sharp.");
  assert.equal(next.personaName, 'friendly');
  assert.equal(next.consent, false);
});

test('isTeachable: edited identical to model (modulo surrounding whitespace) is not teachable', () => {
  assert.equal(isTeachable('raw', 'Same output.', 'Same output.'), false);
  assert.equal(isTeachable('raw', 'Same output.', '  Same output.\n'), false);
});

test('isTeachable: empty/whitespace-only raw or edited is not teachable', () => {
  assert.equal(isTeachable('', 'model out', 'edited out'), false);
  assert.equal(isTeachable('   ', 'model out', 'edited out'), false);
  assert.equal(isTeachable('raw in', 'model out', ''), false);
  assert.equal(isTeachable('raw in', 'model out', '   '), false);
});

test('isTeachable: a genuine edit (edited differs from model) is teachable', () => {
  assert.equal(isTeachable('raw in', 'model out', 'edited out'), true);
});

test('captureEdit: a no-op edit produces no offer (offered:false), regardless of persona', () => {
  const state = createInitialTeachingState();
  const next = captureEdit(state, {
    rawText: 'raw text',
    modelText: 'Same cleaned output.',
    editedText: 'Same cleaned output.',
    personaName: 'friendly',
  });
  assert.equal(next.offered, false);
  assert.deepEqual(next, createInitialTeachingState());
});

test('captureEdit: missing persona name produces no offer even for a real edit', () => {
  const state = createInitialTeachingState();
  const next = captureEdit(state, {
    rawText: 'raw text',
    modelText: 'Model output.',
    editedText: 'Edited output.',
    personaName: '',
  });
  assert.equal(next.offered, false);
});

// --- setTeachingConsent / canSubmitTeaching ------------------------------------

test('setTeachingConsent: no-op when nothing is offered', () => {
  const state = createInitialTeachingState();
  const next = setTeachingConsent(state, true);
  assert.equal(next, state);
});

test('canSubmitTeaching: requires offered + consent + personaName + not busy', () => {
  const offered = captureEdit(createInitialTeachingState(), {
    rawText: 'raw', modelText: 'model', editedText: 'edited', personaName: 'friendly',
  });
  assert.equal(canSubmitTeaching(offered), false); // no consent yet
  const consented = setTeachingConsent(offered, true);
  assert.equal(canSubmitTeaching(consented), true);
  assert.equal(canSubmitTeaching({ ...consented, busy: true }), false);
});

// --- buildTeachingViewModel / renderTeaching -----------------------------------

test('buildTeachingViewModel + renderTeaching: reflects offer state onto elements', () => {
  const state = captureEdit(createInitialTeachingState(), {
    rawText: 'raw', modelText: 'model out', editedText: 'edited out', personaName: 'friendly',
  });
  const els = makeElements();
  renderTeaching(els, buildTeachingViewModel(state));
  assert.equal(els.panel.hidden, false);
  assert.equal(els.rawText.textContent, 'raw');
  assert.equal(els.modelText.textContent, 'model out');
  assert.equal(els.editedText.textContent, 'edited out');
  assert.equal(els.personaLabel.textContent, 'friendly');
  assert.equal(els.confirm.disabled, true); // no consent yet
});

test('renderTeaching: no offer hides the panel and disables confirm/dismiss', () => {
  const els = makeElements();
  renderTeaching(els, buildTeachingViewModel(createInitialTeachingState()));
  assert.equal(els.panel.hidden, true);
  assert.equal(els.confirm.disabled, true);
  assert.equal(els.dismiss.disabled, true);
});

// --- createTalkTeachingFeature: the live wiring + hard invariants -------------

test('createTalkTeachingFeature: init() on an empty element map does not throw', () => {
  assert.doesNotThrow(() => {
    const feature = createTalkTeachingFeature({});
    feature.init();
  });
});

test('onDraftEdited: the raw/model/edited triple survives the save and is what gets offered', () => {
  const els = makeElements();
  const feature = createTalkTeachingFeature({
    elements: els,
    hooks: { getActivePersonaName: () => 'friendly' },
  });
  feature.init();

  const offered = feature.onDraftEdited({
    rawText: 'okay so i should be there around six',
    modelText: 'I should be there around six.',
    editedText: "I'll be there around six sharp.",
  });

  assert.equal(offered, true);
  const state = feature.getState();
  assert.equal(state.offered, true);
  assert.equal(state.rawText, 'okay so i should be there around six');
  assert.equal(state.modelText, 'I should be there around six.');
  assert.equal(state.editedText, "I'll be there around six sharp.");
  assert.equal(state.personaName, 'friendly');
  assert.equal(els.panel.hidden, false);
  assert.equal(els.rawText.textContent, 'okay so i should be there around six');
  assert.equal(els.modelText.textContent, 'I should be there around six.');
  assert.equal(els.editedText.textContent, "I'll be there around six sharp.");
});

test('onDraftEdited: a no-op edit produces no offer and the panel stays hidden', () => {
  const els = makeElements();
  const feature = createTalkTeachingFeature({
    elements: els,
    hooks: { getActivePersonaName: () => 'friendly' },
  });
  feature.init();

  const offered = feature.onDraftEdited({
    rawText: 'raw text',
    modelText: 'Same cleaned output.',
    editedText: 'Same cleaned output.',
  });

  assert.equal(offered, false);
  assert.equal(feature.getState().offered, false);
  assert.equal(els.panel.hidden, true);
});

test('onDraftEdited (saving an edit) performs ZERO backend calls -- personaLearning is never touched', () => {
  const els = makeElements();
  const learning = makeLearningStub(() => feature.getState());
  const feature = createTalkTeachingFeature({
    elements: els,
    hooks: { getActivePersonaName: () => 'friendly', personaLearning: learning },
  });
  feature.init();

  feature.onDraftEdited({
    rawText: 'raw text',
    modelText: 'Model output.',
    editedText: 'Edited output, genuinely different.',
  });

  assert.equal(learning.calls.prepareTeach, 0);
  assert.equal(learning.calls.toggleConsent.length, 0);
  assert.equal(learning.calls.confirmTeach, 0);
  assert.equal(learning.addExampleCalls.length, 0);
});

test('confirm without consent does nothing -- personaLearning is never touched, nothing is stored', () => {
  const els = makeElements();
  const learning = makeLearningStub(() => feature.getState());
  const feature = createTalkTeachingFeature({
    elements: els,
    hooks: { getActivePersonaName: () => 'friendly', personaLearning: learning },
  });
  feature.init();

  feature.onDraftEdited({
    rawText: 'raw text',
    modelText: 'Model output.',
    editedText: 'Edited output, genuinely different.',
  });
  // Consent checkbox left unchecked -- confirm should be disabled in the DOM
  // (defense in depth) AND the click handler must still refuse to act even
  // if something clicked it anyway.
  assert.equal(els.confirm.disabled, true);
  els.confirm.click();

  assert.equal(learning.calls.prepareTeach, 0);
  assert.equal(learning.calls.confirmTeach, 0);
  assert.equal(learning.addExampleCalls.length, 0);
  // The offer is still live -- confirm without consent is a no-op, not a
  // silent dismissal.
  assert.equal(feature.getState().offered, true);
});

test('consent + confirm calls personaLearning exactly once, and sends the EDITED text as out (not the model output)', async () => {
  const els = makeElements();
  const learning = makeLearningStub(() => feature.getState());
  const feature = createTalkTeachingFeature({
    elements: els,
    hooks: { getActivePersonaName: () => 'friendly', personaLearning: learning },
  });
  feature.init();

  feature.onDraftEdited({
    rawText: 'okay so i should be there around six',
    modelText: 'I should be there around six.',
    editedText: "I'll be there around six sharp.",
  });

  els.consent.change(true);
  assert.equal(els.confirm.disabled, false);
  els.confirm.click();
  // The click handler is async -- give its microtask queue a turn.
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(learning.calls.prepareTeach, 1);
  assert.deepEqual(learning.calls.toggleConsent, [true]);
  assert.equal(learning.calls.confirmTeach, 1);
  assert.equal(learning.addExampleCalls.length, 1);
  assert.equal(learning.addExampleCalls[0].raw, 'okay so i should be there around six');
  assert.equal(learning.addExampleCalls[0].out, "I'll be there around six sharp.");
  assert.notEqual(learning.addExampleCalls[0].out, 'I should be there around six.');

  // Success clears the offer -- nothing pending to re-submit.
  assert.equal(feature.getState().offered, false);
});

// Regression guard: personaLearning.prepareTeach() refuses by writing
// addFeedback and leaving pendingPair null -- it neither throws nor sets
// addStatus. Reporting that as a success would tell the user their edit was
// learned while nothing was stored, and clear the offer so they could not
// retry. For a consent-gated feature that is the worst possible failure.
test('a refused prepareTeach reports the failure and KEEPS the offer -- never a silent false success', async () => {
  const els = makeElements();
  const learning = makeLearningStub(() => feature.getState(), { refusePrepare: true });
  const toasts = [];
  const feature = createTalkTeachingFeature({
    elements: els,
    hooks: {
      getActivePersonaName: () => 'friendly',
      personaLearning: learning,
      showToast: (msg, tone) => toasts.push({ msg, tone }),
    },
  });
  feature.init();

  feature.onDraftEdited({
    rawText: 'okay so i should be there around six',
    modelText: 'I should be there around six.',
    editedText: "I'll be there around six sharp.",
  });
  els.consent.change(true);
  els.confirm.click();
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();

  // Nothing was stored, and the sequence stopped at prepare.
  assert.equal(learning.addExampleCalls.length, 0);
  assert.equal(learning.calls.confirmTeach, 0, 'must not proceed to confirm after a refused prepare');

  // The user is told it failed, and can still retry.
  assert.equal(feature.getState().offered, true, 'the offer must survive so the edit is not lost');
  assert.equal(feature.getState().busy, false);
  assert.equal(toasts.length, 1);
  assert.equal(toasts[0].tone, 'danger');
  assert.match(feature.getState().message, /Nothing to teach yet/);
});

test('dismiss clears the offer and the retained texts', () => {
  const els = makeElements();
  const feature = createTalkTeachingFeature({
    elements: els,
    hooks: { getActivePersonaName: () => 'friendly' },
  });
  feature.init();

  feature.onDraftEdited({
    rawText: 'raw text',
    modelText: 'Model output.',
    editedText: 'Edited output, genuinely different.',
  });
  assert.equal(feature.getState().offered, true);

  feature.dismiss();

  const state = feature.getState();
  assert.equal(state.offered, false);
  assert.equal(state.rawText, '');
  assert.equal(state.modelText, '');
  assert.equal(state.editedText, '');
  assert.equal(els.panel.hidden, true);
  assert.equal(els.rawText.textContent, '');
});

test('dismiss button click also clears the offer', () => {
  const els = makeElements();
  const feature = createTalkTeachingFeature({
    elements: els,
    hooks: { getActivePersonaName: () => 'friendly' },
  });
  feature.init();

  feature.onDraftEdited({
    rawText: 'raw text',
    modelText: 'Model output.',
    editedText: 'Edited output, genuinely different.',
  });
  els.dismiss.click();
  assert.equal(feature.getState().offered, false);
});
