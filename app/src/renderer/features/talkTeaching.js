// talkTeaching.js — "Teach this persona from my edit" trigger for the Talk
// workspace (Wave 2 Task C, docs/release/DECISIONS.md D-0018/D-0019).
//
// D-0018 recorded that Wave 1 QA had to SUBSTITUTE the original privacy
// invariant assertion -- "editing never learns anything on its own" became
// "running Test Persona never learns anything on its own" -- because Studio's
// teach panel (features/studioWorkspace.js, reusing features/
// personaLearning.js's createPersonaLearningFeature) has no live-draft
// concept; its raw/output pair only ever comes from a Test Persona run, never
// from editing a real draft. This module IS the restoration: it watches a
// real Talk draft edit (features/drafts.js's saveCurrentDraftEdit() ->
// hooks.onDraftEdited) and offers to teach the active persona from it.
//
// Hard privacy invariant this module enforces, matching personaLearning.js's
// own contract verbatim: NOTHING is ever learned automatically. Saving an
// edit performs ZERO backend calls -- it only OFFERS (captures the
// raw/model/edited triple and shows it back). Only an explicit consent
// checkbox + "Confirm & teach" click reaches the network, and it submits the
// FINAL EDITED text as the learned output -- never the model's pre-edit
// output, even though both are shown side by side so the user can see
// exactly what changed.
//
// This module does NOT reimplement the consent-gated learning flow and does
// NOT call api.addExample anywhere -- personaLearning.js's two-step
// prepare -> consent -> confirm sequence (preparePair -> setConsentChecked ->
// canConfirmTeach -> confirmTeach, the only call site of api.addExample in
// the app) is the privacy invariant, and duplicating or bypassing it here
// would create a second path to the network that nothing gates. Instead, the
// composition root passes in the LIVE createPersonaLearningFeature instance
// (hooks.personaLearning) it already constructed for Talk -- with that
// instance's OWN hooks.getPersonaName/hooks.getDraftPair wired to read the
// current offer this module exposes via getState() -- and this module's
// confirm handler drives that instance's public prepareTeach() ->
// toggleConsent(true) -> confirmTeach() sequence. Exactly one consent-gated
// code path ever reaches the network, no matter which of Studio's or Talk's
// panels triggered it.
//
// ID-COLLISION HAZARD (see features/studioWorkspace.js lines ~91-104 for the
// original writeup): personaLearning.js self-initializes at import time
// against the canonical `personaLearning*` ids, and Studio deliberately uses
// a second, distinct `sdTeach*` prefix so that self-init IIFE never
// double-wires Studio's panel. Talk's markup (signal-desk.html) therefore
// uses a THIRD, distinct prefix, `sdTalkTeach*` -- never `personaLearning*`,
// never Studio's `sdTeach*`. Three surfaces sharing one id set would give one
// DOM element three independent writers, each with the wrong default hooks.
//
// ---------------------------------------------------------------------------
// hooks contract (all optional; every call is optional-chained so a missing
// hook is a safe no-op, never a throw -- same convention as talkWorkspace.js
// and talkCapture.js):
//
//   hooks.personaLearning        The LIVE createPersonaLearningFeature
//                                 instance the composition root already
//                                 constructed for Talk (see file header).
//                                 Only its public prepareTeach()/
//                                 toggleConsent()/confirmTeach()/getState()
//                                 are called here.
//   hooks.getActivePersonaName()  Returns the persona name to teach (e.g. the
//                                 profile's current_preset). Defaults to ''.
//   hooks.showToast(msg, tone, duration)   Optional user feedback.
//
// To mount for real: pass `elements` from collectTalkTeachingElements(), call
// init(), and forward drafts.js's hooks.onDraftEdited(rawText, editedText)
// into this feature's onDraftEdited({rawText, modelText, editedText}) --
// composed alongside (not instead of) the existing
// utilitiesWorkspace.suggestFromEdit() consumer.
//
// THE RACE THAT MATTERS: drafts.js's saveCurrentDraftEdit() re-renders
// latestDraft with the NEW (post-edit) final_text BEFORE it calls
// hooks.onDraftEdited(rawTextBefore, finalText) -- so by the time that
// callback fires, drafts.getLatestDraft()?.final_text is already the EDITED
// text, not the pre-edit model output. The composition root must snapshot
// the pre-edit model output (drafts.getLatestDraft()?.final_text) BEFORE
// calling saveCurrentDraftEdit() (e.g. at the Save Edit click handler, ahead
// of the save), then pass that snapshot through as `modelText` alongside the
// (rawText, editedText) the onDraftEdited callback already receives. See the
// handoff for the exact composition-root diff this requires.
// ---------------------------------------------------------------------------

// --- Reusable element lookup -------------------------------------------------

export const TALK_TEACHING_ELEMENT_IDS = {
  panel: 'sdTalkTeachPanel',
  rawText: 'sdTalkTeachRaw',
  modelText: 'sdTalkTeachModel',
  editedText: 'sdTalkTeachEdited',
  personaLabel: 'sdTalkTeachPersonaLabel',
  consent: 'sdTalkTeachConsent',
  confirm: 'sdTalkTeachConfirmButton',
  dismiss: 'sdTalkTeachDismissButton',
  message: 'sdTalkTeachMessage',
};

/** Looks up every TALK_TEACHING_ELEMENT_IDS entry by id from `root` (defaults to `document`). Missing ids resolve to null, never throw. */
export function collectTalkTeachingElements(root) {
  const doc = root || (typeof document !== 'undefined' ? document : null);
  const els = {};
  for (const [key, id] of Object.entries(TALK_TEACHING_ELEMENT_IDS)) {
    els[key] = doc && typeof doc.getElementById === 'function' ? doc.getElementById(id) || null : null;
  }
  return els;
}

// --- Pure state ---------------------------------------------------------------

export function createInitialTeachingState() {
  return {
    offered: false,
    rawText: '',
    modelText: '',
    editedText: '',
    personaName: '',
    consent: false,
    busy: false,
    message: '',
    messageTone: 'info',
  };
}

// A no-op edit (edited text identical to what the model produced, modulo
// surrounding whitespace -- trimmed only for THIS comparison, so a
// trailing-newline-only "edit" doesn't produce a learning offer) must never
// be offered, and neither can an edit with nothing to actually learn from
// (empty raw or empty edited text).
export function isTeachable(rawText, modelText, editedText) {
  const raw = typeof rawText === 'string' ? rawText.trim() : '';
  const model = typeof modelText === 'string' ? modelText.trim() : '';
  const edited = typeof editedText === 'string' ? editedText.trim() : '';
  if (!raw || !edited) return false;
  if (edited === model) return false;
  return true;
}

// Records the raw/model/edited triple captured at save time. Returns
// offered:false (the full initial state) whenever the edit is not teachable
// -- a no-op edit, missing text, or no target persona -- so a caller can
// never accidentally show a stale offer for an untaught edit.
export function captureEdit(state, { rawText, modelText, editedText, personaName } = {}) {
  const name = typeof personaName === 'string' ? personaName.trim() : '';
  if (!isTeachable(rawText, modelText, editedText) || !name) {
    return createInitialTeachingState();
  }
  return {
    offered: true,
    rawText: String(rawText),
    modelText: typeof modelText === 'string' ? modelText : '',
    editedText: String(editedText),
    personaName: name,
    consent: false,
    busy: false,
    message: '',
    messageTone: 'info',
  };
}

export function setTeachingConsent(state, checked) {
  if (!state.offered) return state;
  return { ...state, consent: Boolean(checked) };
}

// The ONLY conditions under which a confirm click is allowed to reach the
// network via hooks.personaLearning -- an offered pair, explicit consent, a
// target persona, and no submit already in flight.
export function canSubmitTeaching(state) {
  return Boolean(state.offered) && Boolean(state.consent) && Boolean(state.personaName) && !state.busy;
}

// --- pure DOM-ready model -----------------------------------------------------

export function buildTeachingViewModel(state) {
  return {
    visible: state.offered,
    rawText: state.rawText,
    modelText: state.modelText,
    editedText: state.editedText,
    personaLabelText: state.personaName || 'this persona',
    consentChecked: state.consent,
    confirmDisabled: !canSubmitTeaching(state),
    dismissDisabled: !state.offered,
    busy: state.busy,
    messageText: state.message,
    messageTone: state.messageTone,
  };
}

// --- DOM writer ---------------------------------------------------------------

// Same contract as personaLearning.js's renderPersonaLearning /
// talkWorkspace.js's render* helpers: every key optional, nothing queried
// here, safe against stub elements in tests.
export function renderTeaching(elements, model) {
  const els = elements || {};
  if (els.panel) els.panel.hidden = !model.visible;
  if (els.rawText) els.rawText.textContent = model.rawText;
  if (els.modelText) els.modelText.textContent = model.modelText;
  if (els.editedText) els.editedText.textContent = model.editedText;
  if (els.personaLabel) els.personaLabel.textContent = model.personaLabelText;
  if (els.consent) els.consent.checked = model.consentChecked;
  if (els.confirm) els.confirm.disabled = model.confirmDisabled;
  if (els.dismiss) els.dismiss.disabled = model.dismissDisabled;
  if (els.message) {
    els.message.textContent = model.messageText;
    if (typeof els.message.setAttribute === 'function') {
      if (model.messageText) els.message.setAttribute('data-tone', model.messageTone);
      else els.message.removeAttribute('data-tone');
    }
  }
}

// --- live feature (DOM composition + personaLearning composition) -----------

/**
 * @param {object} deps
 * @param {object} deps.elements Talk teaching DOM refs -- see
 *   TALK_TEACHING_ELEMENT_IDS (use collectTalkTeachingElements() for the
 *   common case). Every access is optional-chained.
 * @param {object} deps.hooks See the file-header contract above.
 */
export function createTalkTeachingFeature({ elements, hooks } = {}) {
  const els = elements || {};
  const hks = hooks || {};

  let state = createInitialTeachingState();
  let bound = false;

  function rerender() {
    renderTeaching(els, buildTeachingViewModel(state));
  }

  // Called by the composition root with drafts.js's hooks.onDraftEdited
  // payload plus the pre-edit model text it snapshotted (see the file-header
  // race note). Purely a local state transition -- no network call, ever.
  function onDraftEdited({ rawText, modelText, editedText } = {}) {
    const personaName = hks.getActivePersonaName?.() || '';
    state = captureEdit(state, { rawText, modelText, editedText, personaName });
    rerender();
    return state.offered;
  }

  function dismiss() {
    state = createInitialTeachingState();
    rerender();
  }

  function handleConsentChange(checked) {
    state = setTeachingConsent(state, checked);
    rerender();
  }

  // Step 2 (explicit consent-bearing click): the only place this module ever
  // touches hooks.personaLearning. Routes through that instance's own
  // prepare -> consent -> confirm sequence rather than calling any backend
  // client directly -- see file header for why.
  async function handleConfirmClick() {
    if (!canSubmitTeaching(state)) return;
    const learning = hks.personaLearning;
    if (!learning) {
      state = { ...state, message: 'Learning is not available right now.', messageTone: 'danger' };
      rerender();
      return;
    }

    state = { ...state, busy: true, message: '' };
    rerender();
    try {
      learning.prepareTeach?.();

      // prepareTeach() can refuse (no persona selected, or its own
      // canPrepareTeach() rejects the pair) and it signals that only by writing
      // addFeedback and leaving pendingPair null -- it does not throw and does
      // not set addStatus. Without this check the code below would sail on
      // through a confirmTeach() that early-returns, find addStatus !== 'error',
      // and report "Learned from your edit." while storing nothing. Silently
      // discarding the user's edit while telling them it was kept is the worst
      // possible failure for a consent-gated feature.
      const preparedState = learning.getState?.();
      if (preparedState && !preparedState.pendingPair) {
        state = {
          ...state,
          busy: false,
          message: preparedState.addFeedback || 'Could not prepare this edit for learning.',
          messageTone: 'danger',
        };
        rerender();
        hks.showToast?.(state.message, 'danger');
        return;
      }

      learning.toggleConsent?.(true);
      await learning.confirmTeach?.();
      const learnedState = learning.getState?.();
      // A confirmTeach() that never ran leaves pendingPair in place; treat that
      // as a failure too rather than as a silent success.
      const failed = learnedState?.addStatus === 'error' || Boolean(learnedState?.pendingPair);
      if (failed) {
        state = {
          ...state,
          busy: false,
          message: learnedState?.addFeedback || 'Could not teach this persona.',
          messageTone: 'danger',
        };
        rerender();
        hks.showToast?.(state.message, 'danger');
        return;
      }
      hks.showToast?.(learnedState?.addFeedback || 'Learned from your edit.', 'success', 2500);
      // Success clears the offer entirely -- there is nothing pending to
      // retry or re-show once the example is stored.
      state = createInitialTeachingState();
      rerender();
    } catch (err) {
      state = { ...state, busy: false, message: err?.message || 'Could not teach this persona.', messageTone: 'danger' };
      rerender();
      hks.showToast?.(state.message, 'danger');
    }
  }

  function wire() {
    if (bound) return;
    bound = true;
    els.consent?.addEventListener?.('change', () => handleConsentChange(els.consent.checked));
    els.confirm?.addEventListener?.('click', () => {
      handleConfirmClick();
    });
    els.dismiss?.addEventListener?.('click', () => dismiss());
  }

  function init() {
    wire();
    rerender();
  }

  function destroy() {
    // Nothing to tear down -- no timers, no external subscriptions.
  }

  return {
    init,
    onDraftEdited,
    getState: () => state,
    dismiss,
    destroy,
  };
}
