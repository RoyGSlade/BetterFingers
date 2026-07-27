// Guided-flow step model (features/guidedFlow.js).
//
// The shell exists so onboarding, the persona builder and the contact wizard
// stop reimplementing stepping. These tests pin the rules most likely to be got
// wrong when a fourth flow is added: what gates advancement, what the primary
// button says, and that a gate cannot be walked past.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  FIRST_STEP,
  canAdvanceFrom,
  createGuidedFlow,
  isFirstStep,
  isLastStep,
  nextIndex,
  prevIndex,
  primaryLabelFor,
  progressStates,
} from '../src/renderer/features/guidedFlow.js';

const STEPS = [
  { id: 'welcome', title: 'Welcome', primaryLabel: 'Get started' },
  { id: 'consent', title: 'Your data stays here', primaryLabel: 'Accept & continue' },
  { id: 'how', title: 'How it works' },
  { id: 'models', title: 'Speech models', primaryLabel: 'Finish' },
];

test('a step with no gate is always advanceable', () => {
  assert.equal(canAdvanceFrom(0, STEPS), true);
  assert.equal(canAdvanceFrom(2, STEPS), true);
});

test('a gated step blocks until its condition holds', () => {
  let consented = false;
  const gated = [{ id: 'c', title: 'Consent', canAdvance: () => consented }];
  assert.equal(canAdvanceFrom(0, gated), false);
  consented = true;
  assert.equal(canAdvanceFrom(0, gated), true);
});

test('a gate cannot be walked past by advancing', () => {
  // The failure this prevents: consent skipped by a stray Enter.
  const gated = [
    { id: 'c', title: 'Consent', canAdvance: () => false },
    { id: 'next', title: 'Next' },
  ];
  assert.equal(nextIndex(0, gated), 0);
});

test('a throwing gate closes rather than strands', () => {
  // A gate that raises must not leave a permanently dead button with no
  // explanation -- treat it as "not yet", which is recoverable.
  const broken = [{ id: 'x', title: 'X', canAdvance: () => { throw new Error('boom'); } }];
  assert.equal(canAdvanceFrom(0, broken), false);
});

test('an unknown index cannot advance', () => {
  assert.equal(canAdvanceFrom(99, STEPS), false);
});

test('primary label is per-step, falling back to Next then Finish', () => {
  assert.equal(primaryLabelFor(0, STEPS), 'Get started');
  assert.equal(primaryLabelFor(1, STEPS), 'Accept & continue');
  assert.equal(primaryLabelFor(2, STEPS), 'Next');
  assert.equal(primaryLabelFor(3, STEPS), 'Finish');
});

test('an unlabelled last step says Finish, not Next', () => {
  const two = [{ id: 'a', title: 'A' }, { id: 'b', title: 'B' }];
  assert.equal(primaryLabelFor(1, two), 'Finish');
});

test('first/last detection', () => {
  assert.equal(isFirstStep(FIRST_STEP), true);
  assert.equal(isFirstStep(1), false);
  assert.equal(isLastStep(3, STEPS), true);
  assert.equal(isLastStep(2, STEPS), false);
});

test('indices clamp at both ends', () => {
  assert.equal(prevIndex(0), 0);
  assert.equal(nextIndex(3, STEPS), 3);
});

test('progress marks done/current/upcoming', () => {
  assert.deepEqual(progressStates(1, STEPS), ['done', 'current', 'upcoming', 'upcoming']);
});

// --- shell behaviour ---------------------------------------------------------

function makeEl(extra = {}) {
  const listeners = {};
  return {
    hidden: false,
    disabled: false,
    textContent: '',
    dataset: {},
    focused: false,
    offsetParent: {},
    addEventListener: (evt, fn) => { listeners[evt] = fn; },
    removeEventListener: (evt) => { delete listeners[evt]; },
    focus() { this.focused = true; },
    fire: (evt) => listeners[evt]?.(),
    ...extra,
  };
}

function makeHarness(steps = STEPS, { dismissible = true } = {}) {
  const primary = makeEl();
  const back = makeEl();
  const closeBtn = makeEl();
  const title = makeEl();
  const stepEls = steps.map(() => makeEl());
  const dots = steps.map(() => makeEl());

  const root = {
    hidden: true,
    querySelector: (sel) => ({
      '[data-flow-primary]': primary,
      '[data-flow-back]': back,
      '[data-flow-close]': closeBtn,
      '[data-flow-title]': title,
    }[sel] ?? null),
    querySelectorAll: (sel) => ({
      '[data-flow-step]': stepEls,
      '[data-flow-dot]': dots,
    }[sel] ?? []),
  };

  const docListeners = {};
  const doc = {
    activeElement: null,
    addEventListener: (evt, fn) => { docListeners[evt] = fn; },
    removeEventListener: (evt) => { delete docListeners[evt]; },
    press: (key, extra = {}) => {
      let prevented = false;
      docListeners.keydown?.({ key, preventDefault: () => { prevented = true; }, ...extra });
      return prevented;
    },
    hasKeydown: () => Boolean(docListeners.keydown),
  };

  const flow = createGuidedFlow({ root, steps, dismissible, doc });
  return { flow, root, primary, back, title, stepEls, dots, doc, closeBtn };
}

test('opening shows only the current step and hides Back on the first', () => {
  const h = makeHarness();
  h.flow.open();
  assert.equal(h.root.hidden, false);
  assert.deepEqual(h.stepEls.map((e) => e.hidden), [false, true, true, true]);
  assert.equal(h.back.hidden, true);
  assert.equal(h.primary.textContent, 'Get started');
});

test('the heading takes focus on each step, not the first input', () => {
  // Tells a screen-reader user WHICH step they are on before what they can type.
  const h = makeHarness();
  h.flow.open();
  assert.equal(h.title.focused, true);
});

test('advancing moves one step and reveals Back', () => {
  const h = makeHarness();
  h.flow.open();
  h.primary.fire('click');
  assert.equal(h.flow.getIndex(), 1);
  assert.equal(h.back.hidden, false);
  assert.deepEqual(h.stepEls.map((e) => e.hidden), [true, false, true, true]);
});

test('a gated step disables the primary button until refresh sees it satisfied', () => {
  let ok = false;
  const steps = [{ id: 'c', title: 'Consent', canAdvance: () => ok }, { id: 'b', title: 'B' }];
  const h = makeHarness(steps);
  h.flow.open();
  assert.equal(h.primary.disabled, true);

  ok = true;
  h.flow.refresh();
  assert.equal(h.primary.disabled, false, 'gate satisfied but button still dead');
});

test('finishing calls onFinish instead of advancing off the end', () => {
  const calls = [];
  const root = makeHarness().root;
  const flow = createGuidedFlow({
    root,
    steps: [{ id: 'only', title: 'Only' }],
    onFinish: () => calls.push('finish'),
    doc: { addEventListener() {}, removeEventListener() {}, activeElement: null },
  });
  flow.open();
  flow.goNext();
  assert.deepEqual(calls, ['finish']);
});

test('Escape closes a dismissible flow', () => {
  const h = makeHarness();
  h.flow.open();
  h.doc.press('Escape');
  assert.equal(h.root.hidden, true);
});

test('Escape is swallowed by a gating flow', () => {
  // Onboarding's consent is a legal gate, not a preference: there must be no
  // back door out of it.
  const h = makeHarness(STEPS, { dismissible: false });
  h.flow.open();
  const prevented = h.doc.press('Escape');
  assert.equal(prevented, true, 'Escape should be consumed, not passed through');
  assert.equal(h.root.hidden, false, 'a gating flow must not close on Escape');
});

test('the close button does nothing on a gating flow', () => {
  const h = makeHarness(STEPS, { dismissible: false });
  h.flow.open();
  h.closeBtn.fire('click');
  assert.equal(h.root.hidden, false);
});

test('closing unbinds the key handler', () => {
  const h = makeHarness();
  h.flow.open();
  assert.equal(h.doc.hasKeydown(), true);
  h.flow.close();
  assert.equal(h.doc.hasKeydown(), false);
});

test('opening at a later step is clamped to the available range', () => {
  // "+ New Persona" opens the same flow further in; a bad index must not
  // produce an empty dialog.
  const h = makeHarness();
  h.flow.open(99);
  assert.equal(h.flow.getIndex(), STEPS.length - 1);
  h.flow.close();
  h.flow.open(-5);
  assert.equal(h.flow.getIndex(), FIRST_STEP);
});
