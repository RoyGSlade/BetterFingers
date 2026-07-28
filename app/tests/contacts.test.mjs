// Recipient picker (features/contacts.js).
//
// The rules being pinned are mostly about restraint: "no one in particular" is
// a real option and the default, the picker never nags, and a contact being
// available is never the same as it being applied (ACCOMPLISH.md §3 rule 2).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  CONTACT_FLOW_STEPS,
  NO_CONTACT,
  buildPickerOptions,
  canSaveContact,
  contactStepIdFor,
  createContactsFeature,
  describeContact,
  resolveSelected,
  statusLabelFor,
} from '../src/renderer/features/contacts.js';

const CONTACTS = [
  { id: 'a1', name: 'Priya', relationship: 'my manager' },
  { id: 'b2', name: 'Sam', relationship: 'my brother', preferred_persona: 'Warm' },
];

// --- pure helpers ------------------------------------------------------------

test('"no one in particular" leads the list and is a real option', () => {
  // Not a placeholder: it is the default, and putting it first makes clearing a
  // selection as cheap as making one.
  const options = buildPickerOptions(CONTACTS);
  assert.equal(options[0].id, NO_CONTACT.id);
  assert.equal(options[0].id, '');
  assert.equal(options.length, 3);
});

test('contacts without an id or a name are not offered', () => {
  const options = buildPickerOptions([{ id: '', name: 'Ghost' }, { id: 'x' }, null]);
  assert.deepEqual(options.map((o) => o.id), ['']);
});

test('a missing list still yields the none option', () => {
  assert.deepEqual(buildPickerOptions(undefined).map((o) => o.id), ['']);
  assert.deepEqual(buildPickerOptions('nope').map((o) => o.id), ['']);
});

test('the note describes a contact and is empty for none', () => {
  assert.equal(describeContact(CONTACTS[0]), 'my manager');
  assert.equal(describeContact(CONTACTS[1]), 'my brother · persona: Warm');
  assert.equal(describeContact(null), '');
  assert.equal(describeContact({ id: '', name: 'x' }), '');
});

test('the status bar shows nothing rather than a "none" cell', () => {
  // An empty state occupying permanent space is a slot asking to be filled.
  assert.equal(statusLabelFor(CONTACTS[0]), 'Priya');
  assert.equal(statusLabelFor(null), null);
  assert.equal(statusLabelFor({ id: '', name: '' }), null);
});

test('a dangling id resolves to null, not a placeholder', () => {
  // The contact was deleted while selected. The draft that recorded it keeps
  // the id; the UI just shows nothing applied.
  assert.equal(resolveSelected(CONTACTS, 'gone'), null);
  assert.equal(resolveSelected(CONTACTS, ''), null);
  assert.equal(resolveSelected(CONTACTS, 'a1').name, 'Priya');
});

test('a name alone is enough to save', () => {
  assert.equal(canSaveContact({ name: 'Sam' }), true);
  assert.equal(canSaveContact({ name: '   ' }), false);
  assert.equal(canSaveContact(null), false);
});

test('the wizard is four steps like every other flow', () => {
  assert.equal(CONTACT_FLOW_STEPS.length, 4);
  assert.equal(contactStepIdFor('interview'), 'contactInterview');
  assert.equal(contactStepIdFor('nonsense'), null);
});

// --- wiring ------------------------------------------------------------------

function makeEl(extra = {}) {
  const listeners = {};
  return {
    value: '',
    textContent: '',
    children: [],
    addEventListener: (evt, fn) => { listeners[evt] = fn; },
    replaceChildren(...nodes) { this.children = nodes; },
    focus() { this.focused = true; },
    fire: (evt) => listeners[evt]?.(),
    ...extra,
  };
}

function harness({ contacts = CONTACTS, fetchImpl } = {}) {
  const picker = makeEl();
  const pickerNote = makeEl();
  const newButton = makeEl();
  const selected = [];
  const created = [];

  const doc = { createElement: () => makeEl() };
  const api = {
    fetchContacts: fetchImpl || (async () => ({ ok: true, contacts })),
  };

  const feature = createContactsFeature({
    elements: { picker, pickerNote, newButton },
    api,
    doc,
    hooks: {
      onSelect: (id) => selected.push(id),
      onCreateRequested: () => created.push('open'),
    },
  });
  return { feature, picker, pickerNote, newButton, selected, created };
}

test('refresh fills the picker and defaults to none', () => {
  const h = harness();
  return h.feature.refresh().then(() => {
    assert.equal(h.picker.children.length, 3);
    assert.equal(h.picker.value, '');
    assert.equal(h.pickerNote.textContent, '', 'no note is the none state');
  });
});

test('a list that fails to load leaves the picker usable', async () => {
  // A contact list that cannot be read must not stop anyone dictating.
  const h = harness({ fetchImpl: async () => { throw new Error('backend down'); } });
  await h.feature.refresh();
  assert.equal(h.picker.children.length, 1, 'still offers "no one in particular"');
  assert.equal(h.feature.getSelectedId(), null);
});

test('selecting a contact reports it once for persisting', async () => {
  const h = harness();
  await h.feature.refresh();
  h.picker.value = 'a1';
  h.picker.fire('change');

  assert.deepEqual(h.selected, ['a1']);
  assert.equal(h.pickerNote.textContent, 'my manager');
  assert.equal(h.feature.getSelected().name, 'Priya');
});

test('clearing the selection reports null, not an empty string', async () => {
  const h = harness();
  await h.feature.refresh();
  h.picker.value = 'a1';
  h.picker.fire('change');
  h.picker.value = '';
  h.picker.fire('change');

  assert.deepEqual(h.selected, ['a1', null]);
  assert.equal(h.pickerNote.textContent, '');
});

test('a selection whose contact was deleted falls back to none', async () => {
  const h = harness();
  await h.feature.refresh();
  h.feature.setSelected('a1');

  // Priya is gone on the next load.
  h.feature.getContacts();
  const h2 = harness({ contacts: [CONTACTS[1]] });
  await h2.feature.refresh();
  h2.feature.setSelected('a1');
  await h2.feature.refresh();

  assert.equal(h2.picker.value, '');
  assert.equal(h2.pickerNote.textContent, '', 'must not keep showing a name that is gone');
});

test('setSelected does not report a selection the user did not make', async () => {
  // Restoring the sticky choice on load must not look like a fresh change and
  // write it back.
  const h = harness();
  await h.feature.refresh();
  h.feature.setSelected('a1');
  assert.deepEqual(h.selected, []);
});

test('add-a-contact asks the host to open the wizard', () => {
  const h = harness();
  h.newButton.fire('click');
  assert.deepEqual(h.created, ['open']);
});

test('getContacts returns copies', async () => {
  const h = harness();
  await h.feature.refresh();
  const list = h.feature.getContacts();
  list[0].name = 'mutated';
  assert.equal(h.feature.getContacts()[0].name, 'Priya');
});
