// Contacts in the renderer (Stage 11 §6): the recipient picker and the
// model-run creation wizard.
//
// Design: docs/CONTACT_WIZARD_DESIGN.md. The rules that shape this one are §10
// (friction is a design constraint) and ACCOMPLISH.md §3 rule 2's audience
// clarification, and both mostly show up here as things the UI must NOT do:
//
//   * "None" is a first-class state, not an empty slot to be filled. It is the
//     default and always fine -- most dictation has no particular audience, and
//     a picker that nags for one trains people to pick wrong.
//   * The picker never blocks, never modals, never gates dictating.
//   * Selection is sticky (profile-level, like the active persona), because
//     re-confirming a standing choice is friction with no safety benefit.
//   * Nothing here infers a recipient. Every function takes a contact the user
//     picked or typed.
//
// Pure helpers are exported separately from the DOM wiring, as elsewhere in
// this repo, so the list/label rules are testable without a document.

import * as backendApi from '../api/backend.js';

/** The "no particular audience" option. A real choice, not a placeholder. */
export const NO_CONTACT = { id: '', name: 'No one in particular' };

/**
 * Options for the picker: "none" first, then contacts by name.
 *
 * None leads deliberately. It is the default, and putting it at the top makes
 * clearing a selection as cheap as making one.
 */
export function buildPickerOptions(contacts) {
  const list = Array.isArray(contacts) ? contacts : [];
  return [
    { ...NO_CONTACT },
    ...list
      .filter((c) => c && c.id && c.name)
      .map((c) => ({ id: c.id, name: c.name, relationship: c.relationship || '' })),
  ];
}

/** Secondary line under a contact's name, or '' when there is nothing to add. */
export function describeContact(contact) {
  if (!contact || !contact.id) return '';
  const parts = [];
  if (contact.relationship) parts.push(contact.relationship);
  if (contact.preferred_persona) parts.push(`persona: ${contact.preferred_persona}`);
  return parts.join(' · ');
}

/**
 * What the status bar shows.
 *
 * Returns null when nothing is applied, so the caller renders no cell at all
 * rather than a cell reading "none" — an empty state that takes up permanent
 * space is a slot asking to be filled.
 */
export function statusLabelFor(contact) {
  if (!contact || !contact.id || !contact.name) return null;
  return contact.name;
}

/**
 * Resolve a stored id against the current list.
 *
 * A dangling id — the contact was deleted while it was selected — resolves to
 * null rather than throwing or inventing a placeholder. The draft that recorded
 * it keeps the id; the UI simply shows nothing applied.
 */
export function resolveSelected(contacts, selectedId) {
  if (!selectedId) return null;
  const list = Array.isArray(contacts) ? contacts : [];
  return list.find((c) => c && c.id === selectedId) || null;
}

/** Whether a compiled/edited contact can be saved. A name alone is enough. */
export function canSaveContact(fields) {
  return Boolean(fields && String(fields.name || '').trim());
}

/**
 * Summary of what applying a contact does, for the confirmation surfaces.
 *
 * Deliberately mentions the toggle. A user who applies a contact while
 * `use_audience_context` is off must not believe they have changed how their
 * words are cleaned up -- the selection is recorded on the draft either way
 * (that is what lets Library filter by contact), but it reaches the PROMPT only
 * when the disclosed Settings toggle is on, which D-0005 keeps off.
 */
export function describeApplyEffect(contact, { audienceEnabled = false } = {}) {
  if (!contact || !contact.id) {
    return 'Drafts will record no contact.';
  }
  return audienceEnabled
    ? `Drafts will record ${contact.name}, and cleanup will be told who you are writing to.`
    : `Drafts will record ${contact.name}. Cleanup is not told who you are writing to — that is off in Settings.`;
}

export function collectContactElements(doc = globalThis.document) {
  const $ = (id) => doc.getElementById(id);
  return {
    picker: $('sdContactPicker'),
    pickerNote: $('sdContactPickerNote'),
    manageButton: $('sdContactManageButton'),
    newButton: $('sdContactNewButton'),
    // Wave 5: clearing an applied contact and managing the list are separate
    // actions from creating one. "Manage" used to open the create wizard,
    // which meant the only thing a user could do to an existing contact was
    // make another one.
    clearButton: $('sdContactClearButton'),
    manageList: $('sdContactManageList'),
    manageEmpty: $('sdContactManageEmpty'),
  };
}

/**
 * @param {object} opts
 * @param {ReturnType<typeof collectContactElements>} opts.elements
 * @param {object} [opts.hooks]
 *   onSelect(contactId)      — persist the sticky selection (profile write)
 *   onCreateRequested()      — open the creation wizard
 *   onEditRequested(contact) — open the wizard on an existing contact
 *   onApplied(contact|null)  — the applied contact changed (status bar, etc.)
 *   confirmFn(message)       — injected confirm() for delete
 *   showToast(msg, tone)
 */
export function createContactsFeature({
  elements = {},
  hooks = {},
  api = backendApi,
  doc = globalThis.document,
} = {}) {
  let contacts = [];
  let selectedId = '';

  const confirmFn = hooks.confirmFn
    || (typeof globalThis.confirm === 'function' ? globalThis.confirm.bind(globalThis) : () => true);

  function selected() {
    return resolveSelected(contacts, selectedId);
  }

  function renderNote() {
    if (!elements.pickerNote) return;
    const contact = selected();
    // Blank rather than "no contact selected": the absence of a note IS the
    // none state, and a permanent line explaining it would be nagging.
    elements.pickerNote.textContent = contact ? describeContact(contact) : '';
  }

  function renderPicker() {
    const picker = elements.picker;
    if (!picker) return;
    const options = buildPickerOptions(contacts);
    picker.replaceChildren(...options.map((option) => {
      const el = doc.createElement('option');
      el.value = option.id;
      el.textContent = option.name;
      return el;
    }));
    // A selection whose contact no longer exists falls back to none rather
    // than leaving the picker showing a name that is gone.
    picker.value = options.some((o) => o.id === selectedId) ? selectedId : '';
    selectedId = picker.value;
    renderNote();
  }

  /**
   * The manage list: every contact, each with Edit and Delete.
   *
   * Built from the same `contacts` array the picker uses, so the two can never
   * disagree about who exists. Rows carry the id in a dataset entry rather
   * than closing over an index -- a list that re-renders between click and
   * handler would otherwise delete the wrong person.
   */
  function renderManageList() {
    const list = elements.manageList;
    if (!list || typeof list.replaceChildren !== 'function') return;

    if (elements.manageEmpty) elements.manageEmpty.hidden = contacts.length > 0;

    list.replaceChildren(...contacts.map((contact) => {
      const row = doc.createElement('li');
      row.className = 'sd-contact-row';
      row.dataset.contactId = contact.id;

      const name = doc.createElement('span');
      name.className = 'sd-contact-row__name';
      name.textContent = contact.name;

      const detail = doc.createElement('span');
      detail.className = 'sd-contact-row__detail';
      detail.textContent = describeContact(contact);

      const edit = doc.createElement('button');
      edit.type = 'button';
      edit.className = 'sd-link-btn sd-contact-row__edit';
      edit.textContent = 'Edit';
      edit.setAttribute('aria-label', `Edit ${contact.name}`);
      edit.addEventListener('click', () => hooks.onEditRequested?.({ ...contact }));

      const remove = doc.createElement('button');
      remove.type = 'button';
      remove.className = 'sd-link-btn sd-contact-row__delete';
      remove.textContent = 'Delete';
      remove.setAttribute('aria-label', `Delete ${contact.name}`);
      remove.addEventListener('click', () => { deleteContact(contact.id); });

      row.append(name, detail, edit, remove);
      return row;
    }));
  }

  function renderAll() {
    renderPicker();
    renderManageList();
  }

  async function refresh() {
    try {
      const payload = await api.fetchContacts();
      contacts = Array.isArray(payload?.contacts) ? payload.contacts : [];
    } catch (_error) {
      // A contact list that cannot be loaded must not stop anyone dictating.
      contacts = [];
    }
    renderAll();
    return contacts;
  }

  function setSelected(contactId) {
    selectedId = String(contactId || '');
    if (elements.picker) elements.picker.value = selectedId;
    renderNote();
    hooks.onApplied?.(selected());
  }

  /**
   * Clear the applied contact.
   *
   * A separate action from picking "No one in particular" only in how it is
   * reached; both end in the same state, and both persist, because a sticky
   * selection that un-sticks on clear would be sticky in one direction.
   */
  async function clearSelected() {
    selectedId = '';
    if (elements.picker) elements.picker.value = '';
    renderNote();
    hooks.onApplied?.(null);
    try {
      await api.setActiveContact('');
    } catch (error) {
      hooks.showToast?.(`Failed to clear the contact: ${error.message}`, 'danger');
      return false;
    }
    hooks.onSelect?.(null);
    return true;
  }

  /**
   * Delete a contact.
   *
   * If the deleted contact was the applied one, the selection is cleared here
   * rather than left dangling: resolveSelected() would already render nothing,
   * but the stored `active_contact_id` would still name a contact that no
   * longer exists, and a later restore would try to apply it.
   */
  async function deleteContact(contactId) {
    const contact = resolveSelected(contacts, contactId);
    if (!contact) return false;
    if (!confirmFn(`Delete contact "${contact.name}"? This cannot be undone.`)) return false;

    try {
      await api.deleteContact(contactId);
    } catch (error) {
      hooks.showToast?.(`Delete failed: ${error.message}`, 'danger');
      return false;
    }

    const wasApplied = selectedId === contactId;
    await refresh();
    if (wasApplied) await clearSelected();
    hooks.showToast?.(`Deleted contact "${contact.name}".`, 'success');
    return true;
  }

  function bind() {
    elements.picker?.addEventListener?.('change', () => {
      selectedId = elements.picker.value || '';
      renderNote();
      hooks.onApplied?.(selected());
      hooks.onSelect?.(selectedId || null);
    });
    elements.newButton?.addEventListener?.('click', () => hooks.onCreateRequested?.());
    // Manage now opens the list. It used to open the create wizard, which is
    // how contacts ended up create-only: there was no path to an existing one.
    elements.manageButton?.addEventListener?.('click', () => {
      renderManageList();
      hooks.onManageRequested?.(contacts.map((c) => ({ ...c })));
    });
    elements.clearButton?.addEventListener?.('click', () => { clearSelected(); });
  }

  bind();

  return {
    refresh,
    setSelected,
    clearSelected,
    deleteContact,
    getSelected: selected,
    getSelectedId: () => selectedId || null,
    getContacts: () => contacts.map((c) => ({ ...c })),
    renderPicker,
    renderManageList,
    renderAll,
  };
}

// --- Creation wizard ----------------------------------------------------------

/**
 * Steps for the guided-flow shell. Four, matching every other flow.
 *
 * The interview itself is server-driven — questions arrive one at a time from
 * /contacts/interview/answer — so "Interview" is one step here rather than one
 * step per question. Turning five questions into five progress dots would tell
 * the user how far through a script they are, which is not the same as how far
 * through the task.
 */
export const CONTACT_FLOW_STEPS = [
  { id: 'contactIntro', title: 'Add a contact' },
  { id: 'contactInterview', title: 'A few questions' },
  { id: 'contactReview', title: 'Review & save' },
  { id: 'contactSaved', title: 'Saved' },
];

/** Which flow step a wizard phase maps to. */
export function contactStepIdFor(phase) {
  return {
    intro: 'contactIntro',
    interview: 'contactInterview',
    review: 'contactReview',
    saved: 'contactSaved',
  }[phase] || null;
}
