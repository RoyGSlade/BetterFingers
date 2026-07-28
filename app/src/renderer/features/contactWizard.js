// The contact creation wizard on the guided-flow shell (Stage 11 §6, and the
// fifth flow docs/ui/SIGNAL_DESK_GUIDED_FLOWS.md §4d reserved the shell for).
//
// The owner's direction was "a wizard run by the model". The backend does the
// interviewing; this drives the dialog around it and, crucially, keeps the
// whole thing optional:
//
//   * "Just save the name" is on the FIRST screen, not buried as a skip link.
//     A contact can be created from a name alone, and the interview is an offer
//     to make it better (design §10).
//   * Quitting halfway still saves what exists. Closing on the review step
//     keeps nothing (nothing was written yet), but nothing was lost either --
//     the compiled result is handed back editable, and Save is one click.
//   * The interview runs without a model. Navigation is deterministic
//     server-side, so an unloaded model costs the polish at the end, not the
//     feature. When that happens the review step says so rather than pretending
//     the model wrote the prose.
//
// Unlike the persona flow, this one DOES own its stepping: there is no existing
// step machine to defer to, and the phases map one-to-one onto the shell.

import { createGuidedFlow } from './guidedFlow.js';
import { CONTACT_FLOW_STEPS, canSaveContact, contactStepIdFor } from './contacts.js';

export const REVIEW_FIELD_IDS = {
  name: 'sdContactName',
  relationship: 'sdContactRelationship',
  tone_guidance: 'sdContactTone',
  notes: 'sdContactNotes',
  preferred_persona: 'sdContactPersona',
};

export function collectContactWizardElements(doc = globalThis.document) {
  const $ = (id) => doc.getElementById(id);
  const review = {};
  for (const [field, id] of Object.entries(REVIEW_FIELD_IDS)) {
    review[field] = $(id);
  }
  return {
    root: $('sdContactFlow'),
    seedName: $('sdContactSeedName'),
    startInterviewButton: $('sdContactStartInterview'),
    saveNameOnlyButton: $('sdContactSaveNameOnly'),
    question: $('sdContactQuestion'),
    answer: $('sdContactAnswer'),
    sendButton: $('sdContactSendAnswer'),
    pushback: $('sdContactPushback'),
    progressNote: $('sdContactProgressNote'),
    review,
    reviewNote: $('sdContactReviewNote'),
    saveButton: $('sdContactSave'),
    savedName: $('sdContactSavedName'),
    doneButton: $('sdContactDone'),
    message: $('sdContactMessage'),
  };
}

/**
 * @param {object} opts
 * @param {ReturnType<typeof collectContactWizardElements>} opts.elements
 * @param {object} opts.api  backend.js (or a stub)
 * @param {object} [opts.hooks]  onSaved(contact), showToast(msg, tone), setMessage(el, text, tone)
 */
export function createContactWizard({
  elements = {},
  api,
  hooks = {},
  doc = globalThis.document,
} = {}) {
  const review = elements.review || {};
  let sessionId = null;
  let compiled = null;
  let busy = false;

  const setMessage = hooks.setMessage || ((el, text) => { if (el) el.textContent = text || ''; });

  const flow = createGuidedFlow({
    root: elements.root,
    steps: CONTACT_FLOW_STEPS,
    doc,
  });

  function goToPhase(phase) {
    const id = contactStepIdFor(phase);
    if (id) flow.goTo(id);
  }

  function setBusy(value) {
    busy = Boolean(value);
    for (const button of [elements.startInterviewButton, elements.saveNameOnlyButton,
      elements.sendButton, elements.saveButton]) {
      if (button) button.disabled = busy;
    }
  }

  function renderQuestion(question) {
    if (elements.question) {
      elements.question.textContent = question?.prompt || '';
    }
    if (elements.progressNote && question) {
      const index = Number(question.index ?? 0) + 1;
      const total = Number(question.total ?? 0);
      // Question N of M, separate from the flow's own four dots: the dots track
      // the task, this tracks the conversation inside one step of it.
      elements.progressNote.textContent = total ? `Question ${index} of ${total}` : '';
    }
    if (elements.answer) {
      elements.answer.value = '';
      elements.answer.focus?.();
    }
  }

  function renderReview(contact, warnings) {
    compiled = { ...(contact || {}) };
    for (const [field, el] of Object.entries(review)) {
      if (el) el.value = compiled[field] ?? '';
    }
    if (elements.reviewNote) {
      // Say plainly when the model was not involved. Presenting the user's own
      // words back as if a model had polished them would be a small lie that
      // makes the feature look broken rather than degraded.
      elements.reviewNote.textContent = (warnings && warnings.length)
        ? warnings.join(' ')
        : '';
    }
    if (elements.saveButton) elements.saveButton.disabled = !canSaveContact(compiled);
  }

  function readReviewFields() {
    const fields = {};
    for (const [field, el] of Object.entries(review)) {
      if (el) fields[field] = el.value;
    }
    return fields;
  }

  async function startInterview() {
    if (busy) return;
    setBusy(true);
    setMessage(elements.message, '');
    try {
      const started = await api.startContactInterview();
      sessionId = started?.session_id || null;
      goToPhase('interview');
      renderQuestion(started?.question);

      // The name typed on the intro screen is the answer to question one, so
      // asking for it again would be the wizard ignoring what it was just told.
      const seed = String(elements.seedName?.value || '').trim();
      if (seed) await submitAnswer(seed);
    } catch (error) {
      setMessage(elements.message, `Could not start the interview: ${error.message}`, 'danger');
    } finally {
      setBusy(false);
    }
  }

  async function submitAnswer(answerText) {
    if (!sessionId) return;
    const answer = answerText !== undefined
      ? answerText
      : String(elements.answer?.value || '');
    setBusy(true);
    try {
      const body = await api.answerContactInterview(sessionId, answer);
      if (body?.pushback) {
        setMessage(elements.pushback, body.pushback, 'warning');
        if (elements.answer) elements.answer.focus?.();
        return;
      }
      setMessage(elements.pushback, '');
      if (body?.done) {
        await compile();
        return;
      }
      renderQuestion(body?.question);
    } catch (error) {
      setMessage(elements.message, `Failed: ${error.message}`, 'danger');
    } finally {
      setBusy(false);
    }
  }

  async function compile() {
    try {
      const body = await api.compileContact(sessionId);
      renderReview(body?.contact, body?.warnings);
      goToPhase('review');
    } catch (error) {
      setMessage(elements.message, `Could not build the contact: ${error.message}`, 'danger');
    }
  }

  async function save(fields) {
    if (busy) return null;
    const payload = fields || readReviewFields();
    if (!canSaveContact(payload)) {
      setMessage(elements.message, 'A contact needs a name.', 'danger');
      return null;
    }
    setBusy(true);
    try {
      const body = await api.saveContact(payload);
      const contact = body?.contact || null;
      if (elements.savedName) elements.savedName.textContent = contact?.name || '';
      goToPhase('saved');
      hooks.onSaved?.(contact);
      return contact;
    } catch (error) {
      setMessage(elements.message, `Save failed: ${error.message}`, 'danger');
      return null;
    } finally {
      setBusy(false);
    }
  }

  function open() {
    sessionId = null;
    compiled = null;
    setMessage(elements.message, '');
    setMessage(elements.pushback, '');
    if (elements.seedName) elements.seedName.value = '';
    for (const el of Object.values(review)) {
      if (el) el.value = '';
    }
    flow.open('contactIntro');
    elements.seedName?.focus?.();
  }

  function bind() {
    elements.startInterviewButton?.addEventListener?.('click', () => { startInterview(); });
    // First screen, not a buried skip link: creating a contact from a name
    // alone is the supported path, not the escape hatch.
    elements.saveNameOnlyButton?.addEventListener?.('click', () => {
      save({ name: elements.seedName?.value || '' });
    });
    elements.sendButton?.addEventListener?.('click', () => { submitAnswer(); });
    elements.answer?.addEventListener?.('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        submitAnswer();
      }
    });
    elements.saveButton?.addEventListener?.('click', () => { save(); });
    elements.doneButton?.addEventListener?.('click', () => flow.close());
    for (const el of Object.values(review)) {
      el?.addEventListener?.('input', () => {
        if (elements.saveButton) elements.saveButton.disabled = !canSaveContact(readReviewFields());
      });
    }
  }

  bind();

  return {
    open,
    close: () => flow.close(),
    startInterview,
    submitAnswer,
    save,
    flow,
    getSessionId: () => sessionId,
    getCompiled: () => (compiled ? { ...compiled } : null),
  };
}
