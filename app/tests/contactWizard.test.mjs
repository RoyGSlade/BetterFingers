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
    updateContact: async (contactId, fields) => {
      calls.push(['update', contactId, fields]);
      return { ok: true, contact: { id: contactId, ...fields } };
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
      onSaved: (c, meta) => saved.push({ contact: c, meta }),
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
  assert.equal(h.saved[0].contact.name, 'Sam');
  assert.equal(h.saved[0].meta.edited, false, 'a name-only create is a create');
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

// --- Wave 5: editing an existing contact ------------------------------------
//
// The same dialog, opened at Review & save with the contact loaded. A separate
// editor would be a second thing that can write a contact; this one differs
// from creating only in which verb it sends.

const EXISTING = {
  id: 'a1',
  name: 'Priya',
  relationship: 'my manager',
  tone_guidance: 'Direct, no filler.',
  notes: 'Prefers bullet points.',
  preferred_persona: 'Formal',
};

test('Edit opens at Review & save with every field loaded', () => {
  const h = harness();
  const opened = h.wizard.openForEdit(EXISTING);

  assert.equal(opened, true);
  assert.deepEqual(h.visible(), ['contactReview']);
  assert.equal(h.elements.review.name.value, 'Priya');
  assert.equal(h.elements.review.relationship.value, 'my manager');
  assert.equal(h.elements.review.tone_guidance.value, 'Direct, no filler.');
  assert.equal(h.elements.review.notes.value, 'Prefers bullet points.');
  assert.equal(h.elements.review.preferred_persona.value, 'Formal');
});

test('Edit never starts an interview', () => {
  const h = harness();
  h.wizard.openForEdit(EXISTING);
  assert.deepEqual(h.calls, [], 'the contact already exists; there is nothing to interview about');
});

test('saving an edit updates rather than creating a duplicate', async () => {
  const h = harness();
  h.wizard.openForEdit(EXISTING);
  h.elements.review.tone_guidance.value = 'Warmer than before.';
  h.elements.saveButton.fire('click');
  await tick();

  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0][0], 'update', 'a create here would silently duplicate the contact');
  assert.equal(h.calls[0][1], 'a1');
  assert.equal(h.calls[0][2].tone_guidance, 'Warmer than before.');
  assert.equal(h.saved[0].meta.edited, true);
});

test('a contact with no id cannot be edited', () => {
  // Otherwise save() would fall through to create and quietly duplicate it.
  const h = harness();
  assert.equal(h.wizard.openForEdit({ name: 'Priya' }), false);
  assert.equal(h.wizard.openForEdit(null), false);
  assert.equal(h.wizard.getEditingId(), null);
});

test('opening for create after an edit forgets the edit', () => {
  // Shared state between two openings is how an edit of one contact ends up
  // overwriting another.
  const h = harness();
  h.wizard.openForEdit(EXISTING);
  assert.equal(h.wizard.getEditingId(), 'a1');

  h.wizard.open();

  assert.equal(h.wizard.getEditingId(), null);
  assert.deepEqual(h.visible(), ['contactIntro']);
});

test('a create after an edit posts a new contact, not a patch', async () => {
  const h = harness();
  h.wizard.openForEdit(EXISTING);
  h.wizard.open();

  h.elements.seedName.value = 'Sam';
  h.elements.saveNameOnlyButton.fire('click');
  await tick();

  assert.deepEqual(h.calls, [['save', { name: 'Sam' }]]);
});

test('an edit whose save fails keeps the dialog on review with the message', async () => {
  const h = harness({ updateContact: async () => { throw new Error('offline'); } });
  h.wizard.openForEdit(EXISTING);
  h.elements.saveButton.fire('click');
  await tick();

  assert.deepEqual(h.visible(), ['contactReview'], 'the user keeps their edits');
  assert.match(h.elements.message.textContent, /Save failed: offline/);
  assert.deepEqual(h.saved, []);
});
