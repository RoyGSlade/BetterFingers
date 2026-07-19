// Message Rescue bound to the real draft review path (ACCOMPLISH.md I3.5-I3.7).
//
// F2.8's #messageRescuePanel (features/messageRescuePanel.js) is a static,
// synthetic-example-only preview that never calls the backend -- it stays
// exactly as shipped. This module is the live counterpart: it lives inside
// the existing "Review Draft" panel, operates on whatever draft is currently
// the *latest* one (documented limitation, not hidden: a historical draft
// picked from the list below is not rescued -- there is no per-id "current
// selection" endpoint to target one), and reuses F2.3's pure view-model
// (./messageRescue.js) plus F2.8's own escaped model-builder/renderer
// (./messageRescuePanel.js) wholesale for the assessment/delivery/
// clarification/variants/preservation/warnings region.
//
// Behind the same default-off `pref_message_rescue_enabled` local flag as
// F2.8: when the flag is off, this module makes no backend calls and renders
// nothing (matches F2.8's "inactive by default" contract). Independent of
// main.js's composition for its own rendering; main.js only wires the
// draft-editor write-back (see initMessageRescueDraft's `hooks` param) since
// that is the one piece of state this module does not own.
//
// Privacy/preservation invariants:
// - Selecting a variant writes only into the existing final_text editor
//   (#draftFinalText) -- the raw transcript display element and the
//   underlying draft's raw_text are never touched or even referenced by this
//   module. The existing Save Edit/Accept/Send path is what persists the
//   change; this module never calls a drafts endpoint itself.
// - Context capture is server-side selection/clipboard capture (I3.6) --
//   this module never reads or transmits clipboard contents itself, only
//   triggers the capture and displays the returned status/preview.
// - Nothing is sent, learned, or spoken automatically. No mic/TTS anywhere
//   in this file.

import {
  fetchLatestDraft,
  fetchMessageRescueContext,
  captureSelectionMessageRescueContext,
  clearMessageRescueContext,
  generateMessageRescue,
} from '../api/backend.js';
import { formatMessageRescueViewModel, formatContextStatus, formatVariants } from './messageRescue.js';
import {
  buildMessageRescuePanelModel,
  renderMessageRescuePanel,
  isMessageRescueEnabled,
} from './messageRescuePanel.js';

const STATUS = {
  IDLE: 'idle',
  BUSY: 'busy',
  DONE: 'done',
  ERROR: 'error',
  CANCELLED: 'cancelled',
  TIMEOUT: 'timeout',
};

const CAPTURE_ERROR_MESSAGES = {
  capture_empty: 'No text was found to capture. Select some text, then try again.',
  capture_unsupported: "Selection capture isn't available on this system.",
};

// --- pure state --------------------------------------------------------------

export function createInitialState() {
  return {
    status: STATUS.IDLE,
    requestId: 0,
    result: null,
    errorMessage: '',
    context: null, // last known context status payload from the backend (or null)
    contextMessage: '',
    captureBusy: false,
    draft: null, // { id, raw_text, speech_signals } snapshot at last refresh
    ranText: '',
    ranUsedContext: false,
    selectedVariant: 'faithful',
    applyMessage: '',
  };
}

export function setDraft(state, draft) {
  return { ...state, draft: draft || null };
}

export function setContext(state, context) {
  return { ...state, context: context || null };
}

export function setContextMessage(state, message) {
  return { ...state, contextMessage: String(message || '') };
}

export function setCaptureBusy(state, busy) {
  return { ...state, captureBusy: Boolean(busy) };
}

export function setSelectedVariant(state, variantKey) {
  return { ...state, selectedVariant: variantKey, applyMessage: '' };
}

// Single source of truth for "is this context still usable" -- reuses F2.3's
// own expiry/use-count math (the same function the rendered status text is
// built from) rather than trusting the backend's `active` flag as of capture
// time, so the Clear button/useContext decision can never disagree with what
// is actually on screen.
function isContextActive(context) {
  return formatContextStatus(context).active;
}

export function canRun(state) {
  return Boolean(state.draft && String(state.draft.raw_text || '').trim()) && state.status !== STATUS.BUSY;
}

export function canCancel(state) {
  return state.status === STATUS.BUSY;
}

// Mirrors board #31's text-playground beginRequest/receiveResult shape:
// bumps requestId (a stale-response guard), snapshots what actually ran, and
// clears any prior result/error/apply feedback.
export function beginRequest(state) {
  const requestId = state.requestId + 1;
  return {
    ...state,
    status: STATUS.BUSY,
    requestId,
    result: null,
    errorMessage: '',
    applyMessage: '',
    ranText: String((state.draft && state.draft.raw_text) || ''),
    ranUsedContext: isContextActive(state.context),
  };
}

// Soft/local cancel only -- I3.2's generate route is a single synchronous
// round trip whose job id is only revealed in its own response, so there is
// no way to learn the id in time to call the cancel route while the request
// is still in flight (documented, not hidden -- same limitation textPlayground.js
// records for board #31). Cancelling here just marks the request abandoned so
// a late response is discarded by receiveResult's requestId+status guard.
export function cancelRequest(state) {
  if (state.status !== STATUS.BUSY) return state;
  return { ...state, status: STATUS.CANCELLED, errorMessage: '' };
}

// outcome: {kind:'done', result} | {kind:'timeout'} | {kind:'cancelled'} | {kind:'error', message}
export function receiveResult(state, { requestId, outcome }) {
  if (requestId !== state.requestId || state.status !== STATUS.BUSY) {
    return state; // superseded by a newer request, or already cancelled locally
  }
  // Context is one-time-use once a request is sent; drop the stale local copy
  // regardless of outcome so the UI doesn't show a context that the backend
  // may already have consumed or exhausted.
  const cleared = { ...state, context: null, contextMessage: '' };
  switch (outcome.kind) {
    case 'done':
      return { ...cleared, status: STATUS.DONE, result: outcome.result, selectedVariant: 'faithful' };
    case 'timeout':
      return { ...cleared, status: STATUS.TIMEOUT };
    case 'cancelled':
      return { ...cleared, status: STATUS.CANCELLED };
    default:
      return { ...cleared, status: STATUS.ERROR, errorMessage: String(outcome.message || 'Request failed.') };
  }
}

export function setApplyMessage(state, message) {
  return { ...state, applyMessage: String(message || '') };
}

// --- pure derived text ---------------------------------------------------

export function computeStatusLine(state) {
  switch (state.status) {
    case STATUS.IDLE:
      return 'Ready.';
    case STATUS.BUSY:
      return 'Running…';
    case STATUS.DONE:
      return 'Done.';
    case STATUS.TIMEOUT:
      return 'The model call timed out. No result was produced.';
    case STATUS.CANCELLED:
      return 'Cancelled.';
    case STATUS.ERROR:
      return state.errorMessage || 'Something went wrong.';
    default:
      return '';
  }
}

// A "done" result with only `faithful` populated means the safety-net
// fallback fired server-side (parse failure, oversize output, or a
// preservation/context-leak check) -- surface that rather than letting a
// thin result look like a deliberate two-variant rewrite.
export function computeFallbackNotice(state) {
  if (state.status !== STATUS.DONE || !state.result) return '';
  const variants = formatVariants(state.result.variants);
  const byKey = Object.fromEntries(variants.map((v) => [v.key, v]));
  const onlyFaithful = byKey.faithful && byKey.faithful.available && !(byKey.clearer && byKey.clearer.available) && !(byKey.alternate && byKey.alternate.available);
  return onlyFaithful
    ? 'Fallback: only a safe, faithful-only result was produced. The model output could not be used for Clearer/Alternate.'
    : '';
}

export function computeDraftLabel(state) {
  if (!state.draft || !state.draft.id) return 'No draft to rescue yet.';
  const hasText = Boolean(String(state.draft.raw_text || '').trim());
  return hasText ? `Will rescue draft #${state.draft.id}.` : `Draft #${state.draft.id} has no transcript yet.`;
}

// --- composite pure model --------------------------------------------------

// Reuses F2.8's own escaped panel model wholesale for every result region;
// only the draft-specific fields (status line, run/cancel/apply gating, the
// currently-selected variant's raw text for the apply step) are added here.
export function buildMessageRescueDraftModel(state) {
  const viewModel = formatMessageRescueViewModel(state.result, { context: state.context });
  const rescuePanelModel = buildMessageRescuePanelModel(viewModel, { selectedVariant: state.selectedVariant });

  const variantsByKey = Object.fromEntries(formatVariants(state.result && state.result.variants).map((v) => [v.key, v]));
  const selected = variantsByKey[state.selectedVariant];
  const selectedVariantText = selected && selected.available ? selected.text : '';

  return {
    draftLabel: computeDraftLabel(state),
    canRun: canRun(state),
    canCancel: canCancel(state),
    canCapture: !state.captureBusy && state.status !== STATUS.BUSY,
    canClearContext: isContextActive(state.context) && !state.captureBusy,
    statusLine: computeStatusLine(state),
    isBusy: state.status === STATUS.BUSY,
    errorMessage: state.status === STATUS.ERROR ? state.errorMessage : '',
    contextMessage: state.contextMessage,
    captureBusy: state.captureBusy,
    fallbackNotice: computeFallbackNotice(state),
    applyMessage: state.applyMessage,
    selectedVariantText, // raw -- only ever written via textarea.value, never innerHTML
    rescuePanelModel,
  };
}

// --- DOM writer --------------------------------------------------------------

export function renderMessageRescueDraft(elements, model) {
  if (elements.draftLabel) elements.draftLabel.textContent = model.draftLabel;
  if (elements.runButton) elements.runButton.disabled = !model.canRun;
  if (elements.cancelButton) elements.cancelButton.disabled = !model.canCancel;
  if (elements.captureButton) {
    elements.captureButton.disabled = !model.canCapture;
    elements.captureButton.textContent = model.captureBusy ? 'Capturing…' : 'Capture selection as context';
  }
  if (elements.status) {
    elements.status.textContent = model.statusLine;
    if (typeof elements.status.setAttribute === 'function') {
      elements.status.setAttribute('data-busy', String(model.isBusy));
    }
  }
  if (elements.error) {
    elements.error.hidden = !model.errorMessage;
    elements.error.textContent = model.errorMessage;
  }
  if (elements.contextMessage) elements.contextMessage.textContent = model.contextMessage;
  if (elements.fallback) {
    elements.fallback.hidden = !model.fallbackNotice;
    elements.fallback.textContent = model.fallbackNotice;
  }
  if (elements.applyMessage) elements.applyMessage.textContent = model.applyMessage;

  // Reuse F2.8's own rescue-result renderer for context/assessment/delivery/
  // clarification/variants/preservation/warnings. It handles contextClearButton
  // itself, so pass it through only if this module isn't overriding it below.
  renderMessageRescuePanel(elements, model.rescuePanelModel);
  if (elements.contextClearButton) elements.contextClearButton.disabled = !model.canClearContext;
}

// --- live feature (DOM composition + backend client) -------------------------

const defaultApi = {
  getLatestDraft: async () => {
    const payload = await fetchLatestDraft();
    return payload && payload.draft ? payload.draft : null;
  },
  getContext: async () => fetchMessageRescueContext(),
  captureSelection: () => captureSelectionMessageRescueContext(),
  clearContext: () => clearMessageRescueContext(),
  generate: ({ transcript, useContext, signals }) => generateMessageRescue({ transcript, useContext, signals }),
};

/**
 * @param {object} deps
 * @param {object} deps.elements DOM element references (see queryElements below)
 * @param {object} [deps.api] injected backend client (defaults to the real one)
 * @param {object} [deps.hooks] cross-feature callbacks
 * @param {(text: string) => void} [deps.hooks.applyToEditor] writes `text` into the
 *   existing draft final-text editor and notifies the drafts feature (main.js
 *   composition wires this to `#draftFinalText` + `drafts.handleDraftTextInput()`).
 */
export function createMessageRescueDraftFeature({ elements, api = defaultApi, hooks = {} }) {
  let state = createInitialState();
  const applyToEditor = typeof hooks.applyToEditor === 'function' ? hooks.applyToEditor : () => {};

  const rerender = () => {
    renderMessageRescueDraft(elements, buildMessageRescueDraftModel(state));
  };

  async function refreshDraft() {
    try {
      const draft = await api.getLatestDraft();
      state = setDraft(state, draft);
    } catch (_e) {
      state = setDraft(state, null);
    }
    rerender();
  }

  async function refreshContext() {
    try {
      const context = await api.getContext();
      state = setContext(state, context && context.active ? context : null);
    } catch (_e) {
      state = setContext(state, null);
    }
    rerender();
  }

  async function captureSelection() {
    if (state.captureBusy || state.status === STATUS.BUSY) return;
    state = setCaptureBusy(state, true);
    state = setContextMessage(state, '');
    rerender();
    try {
      const context = await api.captureSelection();
      state = setContext(state, context && context.active ? context : null);
      state = setContextMessage(state, 'Context captured.');
    } catch (err) {
      state = setContext(state, null);
      const reason = err && err.detail;
      state = setContextMessage(state, CAPTURE_ERROR_MESSAGES[reason] || (err && err.message) || 'Could not capture context.');
    }
    state = setCaptureBusy(state, false);
    rerender();
  }

  async function clearContext() {
    if (state.captureBusy) return;
    try {
      await api.clearContext();
    } catch (_e) {
      // Best-effort privacy cleanup; local state is cleared regardless.
    }
    state = setContext(state, null);
    state = setContextMessage(state, '');
    rerender();
  }

  async function run() {
    if (!canRun(state)) return;

    state = beginRequest(state);
    const myRequestId = state.requestId;
    rerender();

    try {
      const useContext = isContextActive(state.context);
      const signals = state.draft && state.draft.speech_signals ? state.draft.speech_signals : null;
      const response = await api.generate({ transcript: state.ranText, useContext, signals });
      const status = response && response.status;
      const outcome =
        status === 'done'
          ? { kind: 'done', result: response.result }
          : status === 'timeout'
            ? { kind: 'timeout' }
            : status === 'cancelled'
              ? { kind: 'cancelled' }
              : { kind: 'error', message: 'Unexpected response from the model.' };
      state = receiveResult(state, { requestId: myRequestId, outcome });
    } catch (err) {
      state = receiveResult(state, { requestId: myRequestId, outcome: { kind: 'error', message: err && err.message } });
    }
    rerender();
  }

  function cancel() {
    state = cancelRequest(state);
    rerender();
  }

  function selectVariant(variantKey) {
    state = setSelectedVariant(state, variantKey);
    const model = buildMessageRescueDraftModel(state);
    if (model.selectedVariantText) {
      applyToEditor(model.selectedVariantText);
      state = setApplyMessage(state, `Applied the ${variantKey} variant to the draft editor.`);
    }
    rerender();
  }

  function wire() {
    if (elements.captureButton && typeof elements.captureButton.addEventListener === 'function') {
      elements.captureButton.addEventListener('click', () => {
        captureSelection();
      });
    }
    if (elements.contextClearButton && typeof elements.contextClearButton.addEventListener === 'function') {
      elements.contextClearButton.addEventListener('click', () => {
        clearContext();
      });
    }
    if (elements.runButton && typeof elements.runButton.addEventListener === 'function') {
      elements.runButton.addEventListener('click', () => {
        run();
      });
    }
    if (elements.cancelButton && typeof elements.cancelButton.addEventListener === 'function') {
      elements.cancelButton.addEventListener('click', cancel);
    }
    for (const [key, input] of Object.entries(elements.variantInputs || {})) {
      if (!input || typeof input.addEventListener !== 'function') continue;
      input.addEventListener('change', () => {
        if (!input.checked) return;
        selectVariant(key);
      });
    }
  }

  return {
    getState: () => state,
    run,
    cancel,
    captureSelection,
    clearContext,
    selectVariant,
    refreshDraft,
    refreshContext,
    wire,
    rerender,
  };
}

function queryElements(doc) {
  const byId = (id) => doc.getElementById(id);
  return {
    section: byId('draftRescuePanel'),
    draftLabel: byId('draftRescueDraftLabel'),
    captureButton: byId('draftRescueCaptureButton'),
    contextMessage: byId('draftRescueContextMessage'),
    contextStatus: byId('draftRescueContextStatus'),
    contextPreview: byId('draftRescueContextPreview'),
    contextMeta: byId('draftRescueContextMeta'),
    contextClearButton: byId('draftRescueClearContextButton'),
    runButton: byId('draftRescueRunButton'),
    cancelButton: byId('draftRescueCancelButton'),
    status: byId('draftRescueStatus'),
    error: byId('draftRescueError'),
    fallback: byId('draftRescueFallback'),
    applyMessage: byId('draftRescueApplyMessage'),
    assessment: byId('draftRescueAssessment'),
    assessmentIntent: byId('draftRescueAssessmentIntent'),
    assessmentAmbiguity: byId('draftRescueAssessmentAmbiguity'),
    deliveryLabels: byId('draftRescueDeliveryLabels'),
    deliveryConfidence: byId('draftRescueDeliveryConfidence'),
    deliveryEvidence: byId('draftRescueDeliveryEvidence'),
    clarification: byId('draftRescueClarification'),
    clarificationQuestion: byId('draftRescueClarificationQuestion'),
    clarificationDetails: byId('draftRescueClarificationDetails'),
    variantInputs: {
      faithful: byId('draftRescueVariantFaithful'),
      clearer: byId('draftRescueVariantClearer'),
      alternate: byId('draftRescueVariantAlternate'),
    },
    variantText: byId('draftRescueVariantText'),
    preservationList: byId('draftRescuePreservationList'),
    warnings: byId('draftRescueWarnings'),
    warningsList: byId('draftRescueWarningsList'),
  };
}

// Sets up the live panel if its markup and the local feature flag are both
// present/on; hidden and fully inert otherwise (matches F2.8's default-off
// contract -- no element is queried and no backend call is made when the
// flag is off). Called explicitly from main.js's composition (not a
// self-initializing script tag) because it needs `hooks.applyToEditor` to
// reach the real #draftFinalText editor that main.js/drafts.js own.
export function initMessageRescueDraft({ doc, storage, hooks = {} } = {}) {
  const activeDoc = doc || (typeof document !== 'undefined' ? document : null);
  if (!activeDoc || typeof activeDoc.getElementById !== 'function') return null;

  const section = activeDoc.getElementById('draftRescuePanel');
  if (!section) return null;

  const activeStorage = storage || (typeof localStorage !== 'undefined' ? localStorage : null);
  const enabled = isMessageRescueEnabled(activeStorage);
  section.hidden = !enabled;
  if (!enabled) return null;

  const elements = queryElements(activeDoc);
  const feature = createMessageRescueDraftFeature({ elements, hooks });
  feature.wire();
  feature.rerender();
  feature.refreshDraft();
  feature.refreshContext();
  return feature;
}
