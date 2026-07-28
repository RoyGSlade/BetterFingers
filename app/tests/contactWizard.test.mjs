// The contact creation wizard (features/contactWizard.js).
//
// The owner asked for "a wizard run by the model". These pin the parts that
// keep it from becoming a gate: a name alone saves, the interview works with no
// model, and a degraded compile says so instead of passing the user's own words
// off as the model's.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { CONTACT_FLOW_STEPS } from '../src/renderer/features/contacts.js';
import {
  REVIEW_FIELD_IDS,
  createContactWizard,
} from '../src/renderer/features/contactWizard.js';

const STEP_IDS = CONTACT_FLOW_STEPS.map((s) => s.id);

function makeEl(extra = {}) {
  const listeners = {};
  return {
    value: '',
    textContent: '',
    hidden: false,
    disabled: false,
    dataset: {},
    offsetParent: {},
    addEventListener: (evt, fn) => { (listeners[evt] ||= []).push(fn); },
    removeEventListener: () => {},
    setAttribute(name, value) { this.dataset[name] = value; },
    focus() { this.focused = true; },
    fire: (evt, arg) => (listeners[evt] || []).forEach((fn) => fn(arg)),
    ...extra,
  };
}

function makeApi(overrides = {}) {
  const calls = [];
  const api = {
    startContactInterview: async () => {
      calls.push(['start']);
      return { session_id: 's1', question: { id: 'name', prompt: 'Who is this?', index: 0, total: 5 } };
    },
    answerContactInterview: async (sessionId, answer) => {
      calls.push(['answer', answer]);
      return { question: { id: 'relationship', prompt: 'How do you know them?', index: 1, total: 5 }, pushback: null, done: false };
    },
    compileContact: async () => {
      calls.push(['compile']);
      return { ok: true, contact: { name: 'Priya', relationship: 'my manager', tone_guidance: 'Direct.', notes: '', preferred_persona: null }, used_model: true, warnings: [] };
    },
    saveContact: async (fields) => {
      calls.push(['save', fields]);
      return { ok: true, contact: { id: 'new1', ...fields } };
    },
    ...overrides,
  };
  return { api, calls };
}

function harness(apiOverrides = {}) {
  const { api, calls } = makeApi(apiOverrides);
  const title = makeEl();
  const progress = makeEl();
  const stepEls = STEP_IDS.map((id) => makeEl({ dataset: { flowStep: id } }));
  const root = {
    hidden: true,
    classList: { add() {}, remove() {} },
    querySelector: (sel) => ({ '[data-flow-title]': title, '[data-flow-progress]': progress }[sel] ?? null),
    querySelectorAll: (sel) => (sel === '[data-flow-step]' ? stepEls : []),
  };
  const doc = { activeElement: null, addEventListener() {}, removeEventListener() {} };

  const review = {};
  for (const field of Object.keys(REVIEW_FIELD_IDS)) review[field] = makeEl();

  const elements = {
    root,
    seedName: makeEl(),
    startInterviewButton: makeEl(),
    saveNameOnlyButton: makeEl(),
    question: makeEl(),
    answer: makeEl(),
    sendButton: makeEl(),
    pushback: makeEl(),
    progressNote: makeEl(),
    review,
    reviewNote: makeEl(),
    saveButton: makeEl(),
    savedName: makeEl(),
    doneButton: makeEl(),
    message: makeEl(),
  };

  const saved = [];
  const wizard = createContactWizard({
    elements,
    api,
    doc,
    hooks: {
      onSaved: (c) => saved.push(c),
      setMessage: (el, text) => { if (el) el.textContent = text || ''; },
    },
  });

  const visible = () => STEP_IDS.filter((_id, i) => !stepEls[i].hidden);
  return { wizard, elements, calls, saved, visible, title, root };
}

const tick = () => new Promise((r) => setImmediate(r));

test('opening lands on the intro step with the name field focused', () => {
  const h = harness();
  h.wizard.open();
  assert.deepEqual(h.visible(), ['contactIntro']);
  assert.equal(h.title.textContent, 'Add a contact');
  assert.equal(h.elements.seedName.focused, true);
});

test('"just save the name" is on the first screen and works alone', async () => {
  // Creating a contact from a name alone is the supported path, not an escape
  // hatch: the interview is an offer to make it better (design §10).
  const h = harness();
  h.wizard.open();
  h.elements.seedName.value = 'Sam';
  h.elements.saveNameOnlyButton.fire('click');
  await tick();

  assert.deepEqual(h.calls, [['save', { name: 'Sam' }]]);
  assert.deepEqual(h.visible(), ['contactSaved']);
  assert.equal(h.saved[0].name, 'Sam');
});

test('saving with no name is refused rather than sent', async () => {
  const h = harness();
  h.wizard.open();
  h.elements.saveNameOnlyButton.fire('click');
  await tick();

  assert.deepEqual(h.calls, [], 'an empty name must not reach the backend');
  assert.match(h.elements.message.textContent, /needs a name/i);
});

test('the typed name answers question one instead of being asked again', async () => {
  const h = harness();
  h.wizard.open();
  h.elements.seedName.value = 'Priya';
  h.elements.startInterviewButton.fire('click');
  await tick();
  await tick();

  assert.deepEqual(h.calls, [['start'], ['answer', 'Priya']]);
  assert.deepEqual(h.visible(), ['contactInterview']);
});

test('the interview shows one question at a time with its position', async () => {
  const h = harness();
  h.wizard.open();
  h.elements.startInterviewButton.fire('click');
  await tick();

  assert.equal(h.elements.question.textContent, 'Who is this?');
  assert.equal(h.elements.progressNote.textContent, 'Question 1 of 5');
});

test('pushback is shown and does not advance the question', async () => {
  const h = harness({
    answerContactInterview: async () => ({ question: null, pushback: 'I need a name.', done: false }),
  });
  h.wizard.open();
  h.elements.startInterviewButton.fire('click');
  await tick();
  h.elements.answer.value = '  ';
  h.elements.sendButton.fire('click');
  await tick();

  assert.equal(h.elements.pushback.textContent, 'I need a name.');
  assert.deepEqual(h.visible(), ['contactInterview']);
});

test('finishing the interview compiles and moves to review', async () => {
  const h = harness({
    answerContactInterview: async () => ({ question: null, pushback: null, done: true }),
  });
  h.wizard.open();
  h.elements.startInterviewButton.fire('click');
  await tick();
  h.elements.answer.value = 'my manager';
  h.elements.sendButton.fire('click');
  await tick();
  await tick();

  assert.deepEqual(h.visible(), ['contactReview']);
  assert.equal(h.elements.review.name.value, 'Priya');
  assert.equal(h.elements.review.tone_guidance.value, 'Direct.');
});

test('a degraded compile says so instead of passing words off as the model\'s', async () => {
  // Presenting the user's own answers back as polished prose would be a small
  // lie that makes the feature look broken rather than degraded.
  const h = harness({
    answerContactInterview: async () => ({ question: null, pushback: null, done: true }),
    compileContact: async () => ({
      ok: true,
      contact: { name: 'Priya', relationship: '', tone_guidance: 'Direct.', notes: '', preferred_persona: null },
      used_model: false,
      warnings: ['No language model is loaded, so your own answers were kept.'],
    }),
  });
  h.wizard.open();
  h.elements.startInterviewButton.fire('click');
  await tick();
  h.elements.sendButton.fire('click');
  await tick();
  await tick();

  assert.match(h.elements.reviewNote.textContent, /own answers were kept/);
});

test('every review field is editable and what gets saved', async () => {
  // A wizard the user cannot overrule is a wizard that guesses wrong
  // permanently.
  const h = harness({
    answerContactInterview: async () => ({ question: null, pushback: null, done: true }),
  });
  h.wizard.open();
  h.elements.startInterviewButton.fire('click');
  await tick();
  h.elements.sendButton.fire('click');
  await tick();
  await tick();

  h.elements.review.tone_guidance.value = 'Warmer than that.';
  h.elements.saveButton.fire('click');
  await tick();

  const saveCall = h.calls.find((c) => c[0] === 'save');
  assert.equal(saveCall[1].tone_guidance, 'Warmer than that.');
  assert.deepEqual(h.visible(), ['contactSaved']);
});

test('a failing save reports and stays on review', async () => {
  const h = harness({
    saveContact: async () => { throw new Error('disk full'); },
  });
  h.wizard.open();
  h.elements.seedName.value = 'Sam';
  h.elements.saveNameOnlyButton.fire('click');
  await tick();

  assert.match(h.elements.message.textContent, /disk full/);
  assert.deepEqual(h.saved, []);
});

test('a failing interview start reports rather than opening an empty step', async () => {
  const h = harness({
    startContactInterview: async () => { throw new Error('backend down'); },
  });
  h.wizard.open();
  h.elements.startInterviewButton.fire('click');
  await tick();

  assert.match(h.elements.message.textContent, /backend down/);
});

test('reopening clears the previous run', async () => {
  const h = harness();
  h.wizard.open();
  h.elements.seedName.value = 'Sam';
  h.elements.saveNameOnlyButton.fire('click');
  await tick();

  h.wizard.open();
  assert.equal(h.elements.seedName.value, '');
  assert.equal(h.elements.review.name.value, '');
  assert.deepEqual(h.visible(), ['contactIntro']);
});
