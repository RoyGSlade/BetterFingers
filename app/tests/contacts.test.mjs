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
  describeApplyEffect,
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
    hidden: false,
    dataset: {},
    children: [],
    addEventListener: (evt, fn) => { listeners[evt] = fn; },
    setAttribute(name, value) { this.dataset[name] = value; },
    append(...nodes) { this.children.push(...nodes); },
    replaceChildren(...nodes) { this.children = nodes; },
    focus() { this.focused = true; },
    click() { listeners.click?.(); },
    fire: (evt) => listeners[evt]?.(),
    ...extra,
  };
}

function harness({ contacts = CONTACTS, fetchImpl, confirmFn = () => true, deleteImpl, setActiveImpl } = {}) {
  const picker = makeEl();
  const pickerNote = makeEl();
  const newButton = makeEl();
  const manageButton = makeEl();
  const clearButton = makeEl();
  const manageList = makeEl();
  const manageEmpty = makeEl();
  const selected = [];
  const created = [];
  const edited = [];
  const applied = [];
  const managed = [];
  const deleted = [];
  const activeWrites = [];
  const toasts = [];

  let current = contacts;

  const doc = { createElement: () => makeEl() };
  const api = {
    fetchContacts: fetchImpl || (async () => ({ ok: true, contacts: current })),
    deleteContact: deleteImpl || (async (id) => {
      deleted.push(id);
      current = current.filter((c) => c.id !== id);
      return { ok: true };
    }),
    setActiveContact: setActiveImpl || (async (id) => { activeWrites.push(id); return { ok: true }; }),
  };

  const feature = createContactsFeature({
    elements: { picker, pickerNote, newButton, manageButton, clearButton, manageList, manageEmpty },
    api,
    doc,
    hooks: {
      onSelect: (id) => selected.push(id),
      onCreateRequested: () => created.push('open'),
      onEditRequested: (contact) => edited.push(contact),
      onManageRequested: (list) => managed.push(list),
      onApplied: (contact) => applied.push(contact),
      showToast: (msg, tone) => toasts.push({ msg, tone }),
      confirmFn,
    },
  });
  return {
    feature, picker, pickerNote, newButton, manageButton, clearButton, manageList, manageEmpty,
    selected, created, edited, applied, managed, deleted, activeWrites, toasts,
  };
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

// --- Wave 5: completing the D-0004 contract ---------------------------------
//
// Before this wave contacts were create-only: the picker could apply one and
// the wizard could make one, and that was the entire surface. Manage opened
// the create wizard, so the only thing a user could do to an existing contact
// was make another. These tests pin the rest of the contract.

test('Manage opens the list rather than the create wizard', async () => {
  const h = harness();
  await h.feature.refresh();
  h.manageButton.fire('click');

  assert.equal(h.created.length, 0, 'Manage is not a second New');
  assert.equal(h.managed.length, 1);
  assert.deepEqual(h.managed[0].map((c) => c.name), ['Priya', 'Sam']);
});

test('the manage list renders a row per contact, keyed by id', async () => {
  const h = harness();
  await h.feature.refresh();

  assert.equal(h.manageList.children.length, 2);
  assert.deepEqual(
    h.manageList.children.map((row) => row.dataset.contactId),
    ['a1', 'b2'],
    'rows carry the id so a re-render between click and handler cannot delete the wrong person',
  );
});

test('an empty contact list says so instead of rendering an empty box', async () => {
  const h = harness({ contacts: [] });
  await h.feature.refresh();
  assert.equal(h.manageList.children.length, 0);
  assert.equal(h.manageEmpty.hidden, false);
});

test('the empty note hides once a contact exists', async () => {
  const h = harness();
  await h.feature.refresh();
  assert.equal(h.manageEmpty.hidden, true);
});

test('Edit hands the whole contact to the host, not just an id', async () => {
  const h = harness();
  await h.feature.refresh();
  // children[2] is the Edit button -- name, detail, edit, delete.
  h.manageList.children[0].children[2].click();

  assert.equal(h.edited.length, 1);
  assert.equal(h.edited[0].id, 'a1');
  assert.equal(h.edited[0].name, 'Priya');
  assert.equal(h.edited[0].relationship, 'my manager');
});

test('Delete asks first, and a refusal deletes nothing', async () => {
  const asked = [];
  const h = harness({ confirmFn: (msg) => { asked.push(msg); return false; } });
  await h.feature.refresh();

  const ok = await h.feature.deleteContact('a1');

  assert.equal(ok, false);
  assert.deepEqual(h.deleted, []);
  assert.equal(asked.length, 1);
  assert.match(asked[0], /Priya/);
  assert.match(asked[0], /cannot be undone/);
});

test('Delete removes the contact and refreshes the list', async () => {
  const h = harness();
  await h.feature.refresh();

  const ok = await h.feature.deleteContact('a1');

  assert.equal(ok, true);
  assert.deepEqual(h.deleted, ['a1']);
  assert.deepEqual(h.feature.getContacts().map((c) => c.name), ['Sam']);
  assert.equal(h.manageList.children.length, 1);
  assert.equal(h.picker.children.length, 2, 'none + Sam');
});

test('deleting an unknown contact is a no-op, not a confirm prompt', async () => {
  const asked = [];
  const h = harness({ confirmFn: () => { asked.push(1); return true; } });
  await h.feature.refresh();

  assert.equal(await h.feature.deleteContact('nope'), false);
  assert.deepEqual(asked, []);
  assert.deepEqual(h.deleted, []);
});

test('deleting the APPLIED contact clears the stored selection too', async () => {
  // resolveSelected() would already render nothing, but `active_contact_id`
  // would still name a contact that no longer exists, and a later restore
  // would try to apply it.
  const h = harness();
  await h.feature.refresh();
  h.feature.setSelected('a1');
  assert.equal(h.feature.getSelectedId(), 'a1');

  await h.feature.deleteContact('a1');

  assert.equal(h.feature.getSelectedId(), null);
  assert.ok(h.activeWrites.includes(''), 'the cleared selection is persisted, not just forgotten');
  assert.equal(h.applied.at(-1), null, 'the status bar is told the contact is gone');
});

test('deleting a contact that is NOT applied leaves the selection alone', async () => {
  const h = harness();
  await h.feature.refresh();
  h.feature.setSelected('b2');

  await h.feature.deleteContact('a1');

  assert.equal(h.feature.getSelectedId(), 'b2');
});

test('a failed delete changes nothing locally', async () => {
  const h = harness({ deleteImpl: async () => { throw new Error('offline'); } });
  await h.feature.refresh();

  assert.equal(await h.feature.deleteContact('a1'), false);
  assert.deepEqual(h.feature.getContacts().map((c) => c.name), ['Priya', 'Sam']);
  assert.match(h.toasts.at(-1).msg, /Delete failed: offline/);
});

// --- clearing the applied contact -------------------------------------------

test('Clear applied resets the picker and persists the empty selection', async () => {
  const h = harness();
  await h.feature.refresh();
  h.feature.setSelected('a1');

  const ok = await h.feature.clearSelected();

  assert.equal(ok, true);
  assert.equal(h.feature.getSelectedId(), null);
  assert.equal(h.picker.value, '');
  assert.equal(h.pickerNote.textContent, '', 'no note is the none state');
  assert.deepEqual(h.activeWrites, [''], 'a sticky selection must un-stick durably');
  assert.equal(h.selected.at(-1), null);
});

test('the Clear button is wired to the same path', async () => {
  const h = harness();
  await h.feature.refresh();
  h.feature.setSelected('a1');

  h.clearButton.fire('click');
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(h.feature.getSelectedId(), null);
});

test('a clear that fails to persist says so rather than pretending', async () => {
  const h = harness({ setActiveImpl: async () => { throw new Error('offline'); } });
  await h.feature.refresh();
  h.feature.setSelected('a1');

  assert.equal(await h.feature.clearSelected(), false);
  assert.match(h.toasts.at(-1).msg, /Failed to clear the contact/);
});

// --- what applying a contact actually does ----------------------------------

test('applying a contact reports the audience toggle honestly', () => {
  // A user who applies a contact while use_audience_context is off must not
  // believe they have changed how their words are cleaned up.
  const contact = { id: 'a1', name: 'Priya' };

  assert.match(describeApplyEffect(contact, { audienceEnabled: false }), /not told who you are writing to/);
  assert.match(describeApplyEffect(contact, { audienceEnabled: false }), /off in Settings/);
  assert.match(describeApplyEffect(contact, { audienceEnabled: true }), /cleanup will be told/);
});

test('applying nobody describes recording nothing', () => {
  assert.match(describeApplyEffect(null), /record no contact/);
  assert.match(describeApplyEffect({ id: '', name: '' }), /record no contact/);
});

test('selecting through the picker notifies the status bar with the resolved contact', async () => {
  const h = harness();
  await h.feature.refresh();

  h.picker.value = 'b2';
  h.picker.fire('change');

  assert.equal(h.applied.at(-1).name, 'Sam', 'the status bar gets a contact, not an id');
  assert.deepEqual(h.selected.at(-1), 'b2');
});

test('selecting "no one in particular" clears the status bar cell', async () => {
  const h = harness();
  await h.feature.refresh();
  h.feature.setSelected('b2');

  h.picker.value = '';
  h.picker.fire('change');

  assert.equal(h.applied.at(-1), null);
});
