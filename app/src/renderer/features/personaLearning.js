// Persona Learning UI (I3.8): "Teach this persona from my edit" over I3.3's
// consent-gated /personas/:name/examples routes (backend/services/persona_learning.py,
// backend/api/routes/personas.py).
//
// Hard privacy invariant this module enforces end to end: NOTHING is ever
// learned automatically. Editing, saving, or sending a draft never calls
// addExample -- the only path to a network write is two explicit user
// actions in sequence:
//   1. Click "Teach this persona from my edit" -- this only ever *reads* the
//      current persona + the current draft's raw/cleaned-output pair and
//      shows it back verbatim (no request sent yet).
//   2. Check the consent checkbox and click "Confirm & teach" -- only this
//      click ever calls the backend, and only with consent=true.
// Switching drafts, personas, or navigating away before step 2 discards the
// pending pair; nothing is stored implicitly.
//
// Reads the persona name and draft raw/final text from the app's EXISTING
// elements (#settingCurrentPreset, #draftRawText, #draftFinalText) rather
// than keeping its own copies -- this module owns zero duplicated
// persona/draft state, only its own consent/list/feedback state. The host
// page (main.js) is expected to call the returned feature's
// `syncPersonaName()` whenever the persona dropdown's value changes
// programmatically (a plain DOM `value =` assignment doesn't fire `change`),
// in addition to the `change` listener this module wires itself.
//
// Renders learned examples via escapeHtml()'d HTML strings (never
// innerHTML of raw model/user text without escaping); the raw/output
// preview before confirming is written via textContent, so no escaping is
// needed there. No example text is ever passed to console.* anywhere in
// this file.

import {
  fetchPersonaExamples,
  addPersonaExample,
  deletePersonaExample,
  clearPersonaExamples,
} from '../api/backend.js';
import { escapeHtml } from './messageRescuePanel.js';

// Mirrors backend/api/routes/personas.py's MAX_LEARNING_EXAMPLE_CHARS
// exactly -- truncating here to the same bound means the preview shown to
// the user in step 1 is always byte-for-byte what step 2 actually stores;
// the request can never come back with a 422 for size.
export const MAX_EXAMPLE_CHARS = 4000;

// --- pure state -------------------------------------------------------------

export function createInitialState() {
  return {
    personaName: '',
    examples: [],
    listStatus: 'idle', // idle | loading | error
    listError: '',
    pendingPair: null, // {raw, out} snapshot captured at step-1 click; null until then
    pendingTruncated: false,
    consentChecked: false,
    addStatus: 'idle', // idle | busy | error
    addFeedback: '',
    addFeedbackTone: 'info',
    deleteStatus: 'idle', // idle | busy | error
    deleteFeedback: '',
    clearStatus: 'idle', // idle | busy | error
    clearFeedback: '',
  };
}

// Switching the active persona drops any unconfirmed pending pair and the
// previously loaded list -- a pending "teach" is scoped to one persona and
// must never be silently re-targeted at another one.
export function setPersonaName(state, name) {
  const next = String(name ?? '').trim();
  if (next === state.personaName) return state;
  return {
    ...state,
    personaName: next,
    pendingPair: null,
    pendingTruncated: false,
    consentChecked: false,
    examples: [],
    listStatus: 'idle',
    listError: '',
    addFeedback: '',
  };
}

function nonEmpty(text) {
  return typeof text === 'string' && text.trim().length > 0;
}

export function canPrepareTeach(state, pair) {
  return Boolean(state.personaName) && Boolean(pair) && nonEmpty(pair.raw) && nonEmpty(pair.out);
}

// Step 1 (explicit click): capture exactly what will be stored. Sends
// nothing over the network -- purely a local state transition.
export function preparePair(state, pair) {
  if (!canPrepareTeach(state, pair)) return state;
  const raw = pair.raw.trim();
  const out = pair.out.trim();
  const truncated = raw.length > MAX_EXAMPLE_CHARS || out.length > MAX_EXAMPLE_CHARS;
  return {
    ...state,
    pendingPair: { raw: raw.slice(0, MAX_EXAMPLE_CHARS), out: out.slice(0, MAX_EXAMPLE_CHARS) },
    pendingTruncated: truncated,
    consentChecked: false,
    addFeedback: '',
  };
}

export function cancelPrepare(state) {
  return { ...state, pendingPair: null, pendingTruncated: false, consentChecked: false };
}

export function setConsentChecked(state, checked) {
  return { ...state, consentChecked: Boolean(checked) };
}

// Step 2 gate: the ONLY conditions under which a confirm click is allowed to
// reach the network -- a prepared pair, explicit consent, a target persona,
// and no add already in flight.
export function canConfirmTeach(state) {
  return Boolean(state.pendingPair) && state.consentChecked && state.addStatus !== 'busy' && Boolean(state.personaName);
}

export function beginAdd(state) {
  return { ...state, addStatus: 'busy', addFeedback: '' };
}

// outcome: {kind:'ok', duplicate, evictedId} | {kind:'error', message}
export function receiveAddResult(state, outcome) {
  if (outcome.kind === 'ok') {
    const message = outcome.duplicate
      ? 'Already learned -- this exact raw/output pair was already stored, nothing new was added.'
      : outcome.evictedId
        ? 'Learned. The oldest saved example for this persona was removed to make room (the per-persona cap was reached).'
        : 'Learned this example.';
    return {
      ...state,
      addStatus: 'idle',
      addFeedback: message,
      addFeedbackTone: 'success',
      pendingPair: null,
      pendingTruncated: false,
      consentChecked: false,
    };
  }
  return { ...state, addStatus: 'error', addFeedback: outcome.message || 'Could not save this example.', addFeedbackTone: 'danger' };
}

export function beginListLoad(state) {
  return { ...state, listStatus: 'loading', listError: '' };
}

export function receiveList(state, examples) {
  return { ...state, listStatus: 'idle', listError: '', examples: Array.isArray(examples) ? examples : [] };
}

export function receiveListError(state, message) {
  return { ...state, listStatus: 'error', listError: message || 'Could not load learned examples.', examples: [] };
}

export function beginDelete(state) {
  return { ...state, deleteStatus: 'busy', deleteFeedback: '' };
}

// outcome: {kind:'ok', deleted} | {kind:'error', message}
export function receiveDeleteResult(state, outcome) {
  if (outcome.kind === 'ok') {
    return {
      ...state,
      deleteStatus: 'idle',
      deleteFeedback: outcome.deleted ? 'Deleted that example.' : 'That example was already gone.',
    };
  }
  return { ...state, deleteStatus: 'error', deleteFeedback: outcome.message || 'Could not delete this example.' };
}

export function beginClear(state) {
  return { ...state, clearStatus: 'busy', clearFeedback: '' };
}

// outcome: {kind:'ok'} | {kind:'error', message}
export function receiveClearResult(state, outcome) {
  if (outcome.kind === 'ok') {
    return {
      ...state,
      clearStatus: 'idle',
      clearFeedback: 'Cleared every learned example for this persona. This is reversible -- teaching it again (with fresh consent) starts a new list.',
    };
  }
  return { ...state, clearStatus: 'error', clearFeedback: outcome.message || 'Could not clear learned examples.' };
}

// --- pure DOM-ready model -----------------------------------------------------

function truncateForDisplay(text, max) {
  const s = String(text || '');
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

// Every raw/out field here is escaped -- this is the only place responsible
// for that; renderPersonaLearning below only assigns already-safe HTML.
function buildExamplesHtml(examples) {
  if (!examples.length) {
    return '<li class="empty-state">No learned examples yet for this persona.</li>';
  }
  return examples
    .map((ex) => {
      const id = escapeHtml(ex.id);
      const raw = escapeHtml(truncateForDisplay(ex.raw, 200));
      const out = escapeHtml(truncateForDisplay(ex.out, 200));
      return (
        `<li class="persona-learning-example" data-example-id="${id}">` +
        `<div class="persona-learning-example-pair">` +
        `<span class="status-label">Raw</span><p class="draft-text">${raw}</p>` +
        `<span class="status-label">Learned output</span><p class="draft-text">${out}</p>` +
        `</div>` +
        `<button type="button" class="secondary-button danger-button compact-button persona-learning-delete-button" data-example-id="${id}">Delete</button>` +
        `</li>`
      );
    })
    .join('');
}

export function buildPersonaLearningModel(state) {
  const hasPersona = Boolean(state.personaName);
  const pending = state.pendingPair;
  return {
    hasPersona,
    personaLabelText: hasPersona ? state.personaName : 'Select a persona to teach.',
    teachDisabled: !hasPersona || state.addStatus === 'busy',

    hasPending: Boolean(pending),
    previewRawText: pending ? pending.raw : '',
    previewOutText: pending ? pending.out : '',
    truncatedNoticeText: state.pendingTruncated
      ? `Truncated to ${MAX_EXAMPLE_CHARS} characters (this is exactly what will be stored).`
      : '',

    consentChecked: state.consentChecked,
    confirmDisabled: !canConfirmTeach(state),
    cancelDisabled: !pending,
    addBusy: state.addStatus === 'busy',
    addFeedbackText: state.addFeedback,
    addFeedbackTone: state.addFeedbackTone,

    listLoadingText: state.listStatus === 'loading' ? 'Loading learned examples…' : '',
    listErrorText: state.listStatus === 'error' ? state.listError : '',
    examplesHtml: buildExamplesHtml(state.examples),
    hasExamples: state.examples.length > 0,
    exampleCount: state.examples.length,

    clearAllDisabled: !hasPersona || state.examples.length === 0 || state.clearStatus === 'busy',
    clearFeedbackText: state.clearFeedback,
    deleteFeedbackText: state.deleteFeedback,
  };
}

// --- DOM writer ---------------------------------------------------------------

// Assigns model fields onto a plain map of element-like objects, same
// contract as messageRescuePanel.js's renderMessageRescuePanel: every key is
// optional, nothing is queried here, safe to call against stubs in tests.
export function renderPersonaLearning(elements, model) {
  if (elements.personaLabel) elements.personaLabel.textContent = model.personaLabelText;
  if (elements.teachButton) elements.teachButton.disabled = model.teachDisabled;

  if (elements.previewEmpty) elements.previewEmpty.hidden = model.hasPending;
  if (elements.previewGroup) elements.previewGroup.hidden = !model.hasPending;
  if (elements.previewRaw) elements.previewRaw.textContent = model.previewRawText;
  if (elements.previewOut) elements.previewOut.textContent = model.previewOutText;
  if (elements.truncatedNotice) {
    elements.truncatedNotice.textContent = model.truncatedNoticeText;
    elements.truncatedNotice.hidden = !model.truncatedNoticeText;
  }

  if (elements.consentCheckbox) elements.consentCheckbox.checked = model.consentChecked;
  if (elements.confirmButton) elements.confirmButton.disabled = model.confirmDisabled;
  if (elements.cancelButton) elements.cancelButton.disabled = model.cancelDisabled;

  if (elements.addFeedback) {
    elements.addFeedback.textContent = model.addFeedbackText;
    if (typeof elements.addFeedback.setAttribute === 'function') {
      if (model.addFeedbackText) elements.addFeedback.setAttribute('data-tone', model.addFeedbackTone);
      else elements.addFeedback.removeAttribute('data-tone');
    }
  }

  if (elements.listStatus) elements.listStatus.textContent = model.listLoadingText || model.listErrorText;
  if (elements.examplesList) elements.examplesList.innerHTML = model.examplesHtml;
  if (elements.exampleCount) elements.exampleCount.textContent = String(model.exampleCount);
  if (elements.clearAllButton) elements.clearAllButton.disabled = model.clearAllDisabled;
  if (elements.clearFeedback) elements.clearFeedback.textContent = model.clearFeedbackText;
  if (elements.deleteFeedback) elements.deleteFeedback.textContent = model.deleteFeedbackText;
}

// --- live feature (DOM composition + backend client) -------------------------

const defaultApi = {
  listExamples: (persona) => fetchPersonaExamples(persona),
  addExample: (persona, raw, out) => addPersonaExample(persona, raw, out, true),
  deleteExample: (persona, exampleId) => deletePersonaExample(persona, exampleId),
  clearExamples: (persona) => clearPersonaExamples(persona),
};

/**
 * @param {object} deps
 * @param {object} deps.elements DOM element references (see queryElements below)
 * @param {object} [deps.api] injected backend client (defaults to the real one)
 * @param {object} [deps.hooks] optional overrides:
 *   - getPersonaName(): string -- defaults to reading elements.personaSource.value
 *   - getDraftPair(): {raw, out} -- defaults to reading elements.sourceRawText/sourceFinalText
 * @param {Function} [deps.confirmFn] injected confirm() for the destructive clear-all action
 */
export function createPersonaLearningFeature({ elements, api = defaultApi, hooks = {}, confirmFn } = {}) {
  let state = createInitialState();
  const doConfirm =
    confirmFn || (typeof window !== 'undefined' && typeof window.confirm === 'function' ? window.confirm.bind(window) : () => true);

  const getPersonaName =
    hooks.getPersonaName ||
    (() => (elements.personaSource ? String(elements.personaSource.value || '') : ''));
  const getDraftPair =
    hooks.getDraftPair ||
    (() => ({
      raw: elements.sourceRawText ? String(elements.sourceRawText.textContent ?? elements.sourceRawText.value ?? '') : '',
      out: elements.sourceFinalText ? String(elements.sourceFinalText.value ?? elements.sourceFinalText.textContent ?? '') : '',
    }));

  const rerender = () => {
    renderPersonaLearning(elements, buildPersonaLearningModel(state));
  };

  async function refreshExamples() {
    if (!state.personaName) {
      state = receiveList(state, []);
      rerender();
      return;
    }
    state = beginListLoad(state);
    rerender();
    try {
      const res = await api.listExamples(state.personaName);
      state = receiveList(state, res && res.examples);
    } catch (err) {
      state = receiveListError(state, err && err.message);
    }
    rerender();
  }

  // Public so the host composition can call this after it repopulates the
  // persona dropdown's options/value programmatically (a plain `value =`
  // assignment doesn't fire a `change` event this module could otherwise
  // catch on its own).
  function syncPersonaName() {
    const name = getPersonaName();
    const next = setPersonaName(state, name);
    if (next === state) return; // already this persona -- setPersonaName is a no-op guard
    state = next;
    rerender();
    refreshExamples();
  }

  // Step 1 (explicit click): read-only snapshot, no network call.
  function prepareTeach() {
    syncPersonaName();
    if (!state.personaName) {
      state = { ...state, addFeedback: 'Select a persona first.', addFeedbackTone: 'danger' };
      rerender();
      return;
    }
    const pair = getDraftPair();
    if (!canPrepareTeach(state, pair)) {
      state = { ...state, addFeedback: 'Nothing to teach yet -- edit the cleaned output first.', addFeedbackTone: 'danger' };
      rerender();
      return;
    }
    state = preparePair(state, pair);
    rerender();
  }

  function cancelTeach() {
    state = cancelPrepare(state);
    rerender();
  }

  function toggleConsent(checked) {
    state = setConsentChecked(state, checked);
    rerender();
  }

  // Step 2 (explicit consent-bearing click): the only call site of
  // api.addExample anywhere in this module.
  async function confirmTeach() {
    if (!canConfirmTeach(state)) return;
    const persona = state.personaName;
    const { raw, out } = state.pendingPair;
    state = beginAdd(state);
    rerender();
    try {
      const res = await api.addExample(persona, raw, out);
      state = receiveAddResult(state, {
        kind: 'ok',
        duplicate: Boolean(res && res.duplicate),
        evictedId: (res && res.evicted_id) || null,
      });
    } catch (err) {
      state = receiveAddResult(state, { kind: 'error', message: err && err.message });
    }
    rerender();
    await refreshExamples();
  }

  async function deleteOne(exampleId) {
    if (!state.personaName || !exampleId || state.deleteStatus === 'busy') return;
    state = beginDelete(state);
    rerender();
    try {
      const res = await api.deleteExample(state.personaName, exampleId);
      state = receiveDeleteResult(state, { kind: 'ok', deleted: Boolean(res && res.deleted) });
    } catch (err) {
      state = receiveDeleteResult(state, { kind: 'error', message: err && err.message });
    }
    rerender();
    await refreshExamples();
  }

  async function clearAll() {
    if (!state.personaName || state.examples.length === 0 || state.clearStatus === 'busy') return;
    const ok = doConfirm(
      `Delete all ${state.examples.length} learned example(s) for "${state.personaName}"? You can teach it again later.`,
    );
    if (!ok) return;
    state = beginClear(state);
    rerender();
    try {
      await api.clearExamples(state.personaName);
      state = receiveClearResult(state, { kind: 'ok' });
    } catch (err) {
      state = receiveClearResult(state, { kind: 'error', message: err && err.message });
    }
    rerender();
    await refreshExamples();
  }

  function wire() {
    if (elements.personaSource && typeof elements.personaSource.addEventListener === 'function') {
      elements.personaSource.addEventListener('change', syncPersonaName);
    }
    if (elements.teachButton && typeof elements.teachButton.addEventListener === 'function') {
      elements.teachButton.addEventListener('click', prepareTeach);
    }
    if (elements.cancelButton && typeof elements.cancelButton.addEventListener === 'function') {
      elements.cancelButton.addEventListener('click', cancelTeach);
    }
    if (elements.consentCheckbox && typeof elements.consentCheckbox.addEventListener === 'function') {
      elements.consentCheckbox.addEventListener('change', () => toggleConsent(elements.consentCheckbox.checked));
    }
    if (elements.confirmButton && typeof elements.confirmButton.addEventListener === 'function') {
      elements.confirmButton.addEventListener('click', () => {
        confirmTeach();
      });
    }
    if (elements.clearAllButton && typeof elements.clearAllButton.addEventListener === 'function') {
      elements.clearAllButton.addEventListener('click', () => {
        clearAll();
      });
    }
    if (elements.examplesList && typeof elements.examplesList.addEventListener === 'function') {
      elements.examplesList.addEventListener('click', (evt) => {
        const target = evt && evt.target;
        const button =
          target && typeof target.closest === 'function' ? target.closest('.persona-learning-delete-button') : null;
        const exampleId = button && button.dataset ? button.dataset.exampleId : null;
        if (exampleId) deleteOne(exampleId);
      });
    }
  }

  return {
    getState: () => state,
    wire,
    rerender,
    refreshExamples,
    syncPersonaName,
    prepareTeach,
    cancelTeach,
    toggleConsent,
    confirmTeach,
    deleteOne,
    clearAll,
  };
}

function queryElements(doc) {
  const byId = (id) => doc.getElementById(id);
  return {
    section: byId('personaLearningSection'),
    personaSource: byId('settingCurrentPreset'),
    sourceRawText: byId('draftRawText'),
    sourceFinalText: byId('draftFinalText'),
    personaLabel: byId('personaLearningPersonaLabel'),
    teachButton: byId('personaLearningTeachButton'),
    previewEmpty: byId('personaLearningPreviewEmpty'),
    previewGroup: byId('personaLearningPreviewGroup'),
    previewRaw: byId('personaLearningPreviewRaw'),
    previewOut: byId('personaLearningPreviewOut'),
    truncatedNotice: byId('personaLearningTruncatedNotice'),
    consentCheckbox: byId('personaLearningConsentCheckbox'),
    confirmButton: byId('personaLearningConfirmButton'),
    cancelButton: byId('personaLearningCancelButton'),
    addFeedback: byId('personaLearningAddFeedback'),
    listStatus: byId('personaLearningListStatus'),
    examplesList: byId('personaLearningExamplesList'),
    exampleCount: byId('personaLearningExampleCount'),
    clearAllButton: byId('personaLearningClearAllButton'),
    clearFeedback: byId('personaLearningClearFeedback'),
    deleteFeedback: byId('personaLearningDeleteFeedback'),
  };
}

// Sets up the persona learning panel if its markup is present; no-ops
// otherwise (safe against an older build or a test doc missing the section).
// Independent of main.js, exactly like textPlayground.js/messageRescuePanel.js
// -- loaded via its own <script type="module"> tag and self-initializes.
export function initPersonaLearning({ doc } = {}) {
  const activeDoc = doc || (typeof document !== 'undefined' ? document : null);
  if (!activeDoc || typeof activeDoc.getElementById !== 'function') return null;

  const elements = queryElements(activeDoc);
  if (!elements.section) return null;

  const feature = createPersonaLearningFeature({ elements });
  feature.wire();
  feature.syncPersonaName();
  feature.rerender();
  return feature;
}

if (typeof document !== 'undefined') {
  initPersonaLearning();
}
