// Text Playground: a silent, text-only place to paste/type a message, pick a
// persona, and run the local LLM through the Message Rescue endpoint (I3.2)
// without any microphone, transcription, or TTS involved (board #31).
//
// Reuses F2.3's pure view-model (./messageRescue.js) and F2.8's escaped panel
// renderer (./messageRescuePanel.js) wholesale for the assessment/delivery/
// clarification/variants/preservation/warnings region -- this module only
// adds the playground-specific controls (text/context input, persona/draft
// pickers, run/cancel/clear, apply-to-draft, copy) around it. Independent of
// main.js: loaded via its own <script type="module"> tag and self-initializes
// on import, exactly like messageRescuePanel.js.
//
// Privacy/preservation invariants this module upholds:
// - Nothing is sent anywhere automatically; Apply/Copy are explicit user
//   actions, and applying to a draft only ever overwrites that draft's
//   final_text (server-side /drafts/:id/edit), never its raw_text.
// - The optional context field is captured server-side only at Run time and
//   is one-time-use (F2.5 ContextSession semantics); this module never
//   re-sends or displays it back after a request completes, and Clear also
//   asks the server to drop any lingering unconsumed context.
// - No microphone, transcription, playback, or TTS call exists anywhere in
//   this file (grep-verified in tests) -- `signals` is never populated,
//   since there is no dictation in this flow.

import {
  fetchPersonas,
  fetchDrafts,
  fetchLlmModels,
  editDraft,
  captureManualMessageRescueContext,
  clearMessageRescueContext,
  generateMessageRescue,
} from '../api/backend.js';
import { formatMessageRescueViewModel, formatVariants } from './messageRescue.js';
import { buildMessageRescuePanelModel, renderMessageRescuePanel, escapeHtml } from './messageRescuePanel.js';

const STATUS = {
  IDLE: 'idle',
  BUSY: 'busy',
  DONE: 'done',
  ERROR: 'error',
  CANCELLED: 'cancelled',
  TIMEOUT: 'timeout',
};

// --- pure state -------------------------------------------------------------

export function createInitialState() {
  return {
    text: '',
    contextText: '',
    persona: '',
    status: STATUS.IDLE,
    requestId: 0,
    result: null,
    errorMessage: '',
    ranPersona: null,
    ranModelId: null,
    ranUsedContext: false,
    ranText: '', // snapshot of the submitted text, for the "raw" comparison column
    selectedVariant: 'faithful', // 'raw' | 'faithful' | 'clearer' | 'alternate'
    selectedDraftId: '',
    applyMessage: '',
  };
}

export function setText(state, text) {
  return { ...state, text: String(text ?? '') };
}

export function setContextText(state, contextText) {
  return { ...state, contextText: String(contextText ?? '') };
}

export function setPersona(state, persona) {
  return { ...state, persona: String(persona ?? '') };
}

export function setSelectedVariant(state, variantKey) {
  return { ...state, selectedVariant: variantKey };
}

export function setSelectedDraftId(state, draftId) {
  return { ...state, selectedDraftId: draftId == null ? '' : String(draftId) };
}

export function setApplyMessage(state, message) {
  return { ...state, applyMessage: String(message ?? '') };
}

export function canRun(state) {
  return state.text.trim().length > 0 && state.status !== STATUS.BUSY;
}

export function canCancel(state) {
  return state.status === STATUS.BUSY;
}

// Begins a new generation attempt: bumps requestId (a stale-response guard
// for receiveResult), snapshots persona/model/context-usage for the "what
// ran" display, and clears any prior result/error/apply feedback.
export function beginRequest(state, { modelId = null } = {}) {
  const requestId = state.requestId + 1;
  return {
    ...state,
    status: STATUS.BUSY,
    requestId,
    result: null,
    errorMessage: '',
    applyMessage: '',
    ranPersona: state.persona || null,
    ranModelId: modelId,
    ranUsedContext: state.contextText.trim().length > 0,
    ranText: state.text,
  };
}

// Soft/local cancel only. I3.2's POST /message-rescue/generate is a single
// synchronous round trip whose job id is only revealed in its own response --
// there is no way for the client to learn the id in time to call the
// backend's POST /message-rescue/generate/{id}/cancel while the request is
// still in flight. Cancelling here just marks the request abandoned so a
// late response is discarded by receiveResult's requestId+status guard; it
// does not stop the model call server-side. Documented, not hidden.
export function cancelRequest(state) {
  if (state.status !== STATUS.BUSY) return state;
  return { ...state, status: STATUS.CANCELLED, errorMessage: '' };
}

// outcome: {kind:'done', result} | {kind:'timeout'} | {kind:'cancelled'} | {kind:'error', message}
export function receiveResult(state, { requestId, outcome }) {
  if (requestId !== state.requestId || state.status !== STATUS.BUSY) {
    return state; // superseded by a newer request, or already cancelled/cleared locally
  }
  const cleared = { ...state, contextText: '' }; // context is one-time-use once a request is sent
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

export function clearAll() {
  return createInitialState();
}

// --- pure derived text -------------------------------------------------------

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

// Surfaces which persona/model actually ran and whether context was used, so
// a persona test is never ambiguous about what produced the result.
export function buildRanInfoText(state) {
  if (!state.ranPersona && !state.ranModelId && state.status === STATUS.IDLE) return '';
  const personaLabel = state.ranPersona || 'Default (no persona)';
  const modelLabel = state.ranModelId || 'unknown model';
  const contextLabel = state.ranUsedContext ? 'context: used' : 'context: none';
  const prefix = state.status === STATUS.BUSY ? 'Running with' : 'Ran with';
  return `${prefix} persona: ${personaLabel} · model: ${modelLabel} · ${contextLabel}`;
}

// A "done" result with only `faithful` populated means the safety-net
// fallback fired server-side (parse failure, oversize output, a preservation
// check, or a context-leak check) -- make that obvious rather than letting a
// thin result look like a deliberate two-variant persona.
export function computeFallbackNotice(state) {
  if (state.status !== STATUS.DONE || !state.result) return '';
  const variants = formatVariants(state.result.variants);
  const byKey = Object.fromEntries(variants.map((v) => [v.key, v]));
  const onlyFaithful = byKey.faithful && byKey.faithful.available && !(byKey.clearer && byKey.clearer.available) && !(byKey.alternate && byKey.alternate.available);
  return onlyFaithful
    ? 'Fallback: only a safe, faithful-only result was produced. The model output could not be used for Clearer/Alternate (parse failure, size limit, or a preservation/context check failed).'
    : '';
}

function truncateForDisplay(text, max) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export function buildPersonaOptions(personas) {
  const names = Array.isArray(personas) ? personas : Object.keys(personas || {});
  const clean = names.filter((n) => typeof n === 'string' && n.length > 0).sort();
  return [{ value: '', label: 'Default (no persona)' }, ...clean.map((n) => ({ value: n, label: n }))];
}

export function buildPersonaOptionsHtml(personas, selectedPersona) {
  return buildPersonaOptions(personas)
    .map(
      (o) =>
        `<option value="${escapeHtml(o.value)}"${o.value === (selectedPersona || '') ? ' selected' : ''}>${escapeHtml(o.label)}</option>`,
    )
    .join('');
}

export function buildDraftOptions(drafts) {
  const list = Array.isArray(drafts) ? drafts : [];
  return list
    .filter((d) => d && d.id !== undefined && d.id !== null)
    .map((d) => {
      const snippet = truncateForDisplay(String(d.final_text || d.raw_text || '').trim(), 60) || '(empty draft)';
      return { value: String(d.id), label: `#${d.id} · ${snippet}` };
    });
}

// --- side-by-side comparison columns --------------------------------------

const COLUMN_DEFS = [
  { key: 'raw', label: 'Raw (as typed)' },
  { key: 'faithful', label: 'Faithful' },
  { key: 'clearer', label: 'Clearer' },
  { key: 'alternate', label: 'Alternate' },
];

// The literal task ask: raw/faithful/clearer/alternate, side by side, so the
// user can compare all four at once instead of toggling one at a time. `raw`
// is a client-side-only column (the text as submitted) and is a legitimate
// choice to Apply/Copy too -- sometimes none of the rewrites beat the
// original. Text fields here are RAW/unescaped; the DOM layer must write
// them via textContent, never innerHTML.
export function buildComparisonColumns(state) {
  const rawText = state.ranText || '';
  const variantsByKey = Object.fromEntries(formatVariants(state.result && state.result.variants).map((v) => [v.key, v]));
  return COLUMN_DEFS.map(({ key, label }) => {
    if (key === 'raw') {
      return { key, label, text: rawText, available: rawText.length > 0, selected: state.selectedVariant === key };
    }
    const variant = variantsByKey[key];
    return {
      key,
      label,
      text: (variant && variant.text) || '',
      available: Boolean(variant && variant.available),
      selected: state.selectedVariant === key,
    };
  });
}

export function buildDraftOptionsHtml(drafts, selectedDraftId) {
  const placeholder = `<option value="">Choose a draft…</option>`;
  const options = buildDraftOptions(drafts)
    .map(
      (o) =>
        `<option value="${escapeHtml(o.value)}"${o.value === (selectedDraftId || '') ? ' selected' : ''}>${escapeHtml(o.label)}</option>`,
    )
    .join('');
  return placeholder + options;
}

// --- composite pure model ----------------------------------------------------

// Combines this module's playground-only fields with F2.3/F2.8's own
// escaped rescue-result model (reused, not reimplemented) into one DOM-ready
// object. `rawSelectedText` is deliberately unescaped -- it is only ever
// consumed by the DOM layer's apply-to-draft/copy handlers (JSON body /
// clipboard, neither of which is an HTML sink), never written into innerHTML.
export function buildTextPlaygroundModel(state, { personas = {}, drafts = [] } = {}) {
  const viewModel = formatMessageRescueViewModel(state.result, { context: null, signals: null });
  // F2.8's own variant radio/preview elements are intentionally not wired up
  // here (this module renders its own side-by-side comparison instead) --
  // buildMessageRescuePanelModel still only needs a selectedVariant to stay
  // internally consistent, and renderMessageRescuePanel no-ops any element
  // this module doesn't pass it (see renderTextPlayground below).
  const rescuePanelModel = buildMessageRescuePanelModel(viewModel, { selectedVariant: state.selectedVariant });

  const columns = buildComparisonColumns(state);
  const selectedColumn = columns.find((c) => c.key === state.selectedVariant);
  const rawSelectedText = selectedColumn && selectedColumn.available ? selectedColumn.text : '';

  return {
    text: state.text,
    contextText: state.contextText,
    personaOptionsHtml: buildPersonaOptionsHtml(personas, state.persona),
    canRun: canRun(state),
    canCancel: canCancel(state),
    statusLine: computeStatusLine(state),
    isBusy: state.status === STATUS.BUSY,
    errorMessage: state.status === STATUS.ERROR ? state.errorMessage : '',
    ranInfoText: buildRanInfoText(state),
    fallbackNotice: computeFallbackNotice(state),
    draftOptionsHtml: buildDraftOptionsHtml(drafts, state.selectedDraftId),
    canApply: Boolean(state.selectedDraftId) && rawSelectedText.length > 0,
    canCopy: rawSelectedText.length > 0,
    applyMessage: state.applyMessage,
    rawSelectedText,
    columns,
    rescuePanelModel,
  };
}

// --- DOM writer ---------------------------------------------------------------

export function renderTextPlayground(elements, model) {
  if (elements.text && elements.text.value !== model.text) elements.text.value = model.text;
  if (elements.context && elements.context.value !== model.contextText) elements.context.value = model.contextText;
  if (elements.personaSelect) elements.personaSelect.innerHTML = model.personaOptionsHtml;
  if (elements.runButton) elements.runButton.disabled = !model.canRun;
  if (elements.cancelButton) elements.cancelButton.disabled = !model.canCancel;
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
  if (elements.ranInfo) elements.ranInfo.textContent = model.ranInfoText;
  if (elements.fallback) {
    elements.fallback.hidden = !model.fallbackNotice;
    elements.fallback.textContent = model.fallbackNotice;
  }
  if (elements.draftSelect) elements.draftSelect.innerHTML = model.draftOptionsHtml;
  if (elements.applyButton) elements.applyButton.disabled = !model.canApply;
  if (elements.copyButton) elements.copyButton.disabled = !model.canCopy;
  if (elements.applyMessage) elements.applyMessage.textContent = model.applyMessage;

  // Side-by-side raw/faithful/clearer/alternate comparison -- each column's
  // text is written via textContent (never innerHTML), so no escaping is
  // needed here even though the text is raw model/user output.
  for (const column of model.columns) {
    const columnEls = elements.columns && elements.columns[column.key];
    if (!columnEls) continue;
    if (columnEls.text) columnEls.text.textContent = column.available ? column.text : 'Not available.';
    if (columnEls.button) {
      columnEls.button.disabled = !column.available;
      columnEls.button.textContent = column.selected ? 'Selected' : 'Use this';
      if (typeof columnEls.button.setAttribute === 'function') {
        columnEls.button.setAttribute('aria-pressed', String(column.selected));
      }
    }
  }

  // Reuse F2.3/F2.8's own rescue-result renderer for assessment/delivery/
  // clarification/preservation/warnings -- same shape, same escaping. Its
  // variant radio/preview elements are deliberately not passed (this module
  // renders its own comparison columns above instead); renderMessageRescuePanel
  // no-ops any element key it doesn't find on `elements`.
  renderMessageRescuePanel(elements, model.rescuePanelModel);
}

// --- live feature (DOM composition + backend client) -------------------------

const defaultApi = {
  fetchPersonas,
  fetchDrafts,
  fetchLlmModels,
  applyToDraft: (draftId, finalText) => editDraft(draftId, finalText),
  captureManualContext: (text) => captureManualMessageRescueContext(text),
  clearContext: () => clearMessageRescueContext(),
  generate: ({ transcript, persona, useContext }) => generateMessageRescue({ transcript, persona, useContext }),
};

/**
 * @param {object} deps
 * @param {object} deps.elements DOM element references (see queryElements below)
 * @param {object} [deps.api] injected backend client (defaults to the real one)
 */
export function createTextPlaygroundFeature({ elements, api = defaultApi }) {
  let state = createInitialState();
  let personas = {};
  let drafts = [];
  let modelId = null;

  const rerender = () => {
    renderTextPlayground(elements, buildTextPlaygroundModel(state, { personas, drafts }));
  };

  async function refreshPersonas() {
    try {
      personas = (await api.fetchPersonas()) || {};
    } catch (_e) {
      personas = {};
    }
    rerender();
  }

  async function refreshDrafts() {
    try {
      const res = await api.fetchDrafts();
      drafts = (res && res.drafts) || [];
    } catch (_e) {
      drafts = [];
    }
    rerender();
  }

  async function refreshModelId() {
    try {
      const res = await api.fetchLlmModels();
      modelId = (res && res.selected_model_id) || null;
    } catch (_e) {
      modelId = null;
    }
  }

  async function run() {
    if (!canRun(state)) return;

    // Flip to busy synchronously (before any await) so Cancel is immediately
    // available and the UI never sits in a silent gap waiting on the model-id
    // lookup below.
    const pendingContextText = state.contextText.trim();
    state = beginRequest(state, { modelId });
    const myRequestId = state.requestId;
    rerender();

    await refreshModelId();
    if (state.requestId === myRequestId && state.status === STATUS.BUSY) {
      state = { ...state, ranModelId: modelId };
      rerender();
    }

    try {
      let useContext = false;
      if (pendingContextText) {
        try {
          await api.captureManualContext(pendingContextText);
          useContext = true;
        } catch (_captureErr) {
          // Best-effort: run without context rather than blocking the whole
          // request on a context-capture failure (e.g. whitespace-only text).
          useContext = false;
        }
      }
      const response = await api.generate({ transcript: state.text, persona: state.persona || null, useContext });
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

  async function clear() {
    try {
      await api.clearContext();
    } catch (_e) {
      // Best-effort privacy cleanup; local state is cleared regardless.
    }
    state = clearAll();
    rerender();
  }

  async function applyToDraft() {
    const model = buildTextPlaygroundModel(state, { personas, drafts });
    if (!model.canApply) return;
    try {
      await api.applyToDraft(Number(state.selectedDraftId), model.rawSelectedText);
      state = setApplyMessage(state, `Applied to draft #${state.selectedDraftId}.`);
      rerender();
      await refreshDrafts();
    } catch (err) {
      state = setApplyMessage(state, `Could not apply: ${(err && err.message) || 'unknown error'}`);
      rerender();
    }
  }

  async function copy() {
    const model = buildTextPlaygroundModel(state, { personas, drafts });
    if (!model.canCopy) return;
    try {
      if (typeof navigator === 'undefined' || !navigator.clipboard || typeof navigator.clipboard.writeText !== 'function') {
        throw new Error('Clipboard is unavailable.');
      }
      await navigator.clipboard.writeText(model.rawSelectedText);
      state = setApplyMessage(state, 'Copied to clipboard.');
    } catch (err) {
      state = setApplyMessage(state, `Could not copy: ${(err && err.message) || 'unknown error'}`);
    }
    rerender();
  }

  function wire() {
    if (elements.text && typeof elements.text.addEventListener === 'function') {
      elements.text.addEventListener('input', () => {
        state = setText(state, elements.text.value);
        rerender();
      });
    }
    if (elements.context && typeof elements.context.addEventListener === 'function') {
      elements.context.addEventListener('input', () => {
        state = setContextText(state, elements.context.value);
        rerender();
      });
    }
    if (elements.personaSelect && typeof elements.personaSelect.addEventListener === 'function') {
      elements.personaSelect.addEventListener('change', () => {
        state = setPersona(state, elements.personaSelect.value);
        rerender();
      });
    }
    if (elements.draftSelect && typeof elements.draftSelect.addEventListener === 'function') {
      elements.draftSelect.addEventListener('change', () => {
        state = setSelectedDraftId(state, elements.draftSelect.value);
        rerender();
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
    if (elements.clearButton && typeof elements.clearButton.addEventListener === 'function') {
      elements.clearButton.addEventListener('click', () => {
        clear();
      });
    }
    if (elements.applyButton && typeof elements.applyButton.addEventListener === 'function') {
      elements.applyButton.addEventListener('click', () => {
        applyToDraft();
      });
    }
    if (elements.copyButton && typeof elements.copyButton.addEventListener === 'function') {
      elements.copyButton.addEventListener('click', () => {
        copy();
      });
    }
    for (const [key, columnEls] of Object.entries(elements.columns || {})) {
      const button = columnEls && columnEls.button;
      if (!button || typeof button.addEventListener !== 'function') continue;
      button.addEventListener('click', () => {
        state = setSelectedVariant(state, key);
        rerender();
      });
    }
  }

  return {
    getState: () => state,
    run,
    cancel,
    clear,
    applyToDraft,
    copy,
    refreshPersonas,
    refreshDrafts,
    wire,
    rerender,
  };
}

function queryElements(doc) {
  const byId = (id) => doc.getElementById(id);
  return {
    section: byId('textPlaygroundSection'),
    text: byId('textPlaygroundText'),
    context: byId('textPlaygroundContext'),
    personaSelect: byId('textPlaygroundPersonaSelect'),
    runButton: byId('textPlaygroundRunButton'),
    cancelButton: byId('textPlaygroundCancelButton'),
    clearButton: byId('textPlaygroundClearButton'),
    status: byId('textPlaygroundStatus'),
    error: byId('textPlaygroundError'),
    ranInfo: byId('textPlaygroundRanInfo'),
    fallback: byId('textPlaygroundFallback'),
    draftSelect: byId('textPlaygroundDraftSelect'),
    applyButton: byId('textPlaygroundApplyButton'),
    copyButton: byId('textPlaygroundCopyButton'),
    applyMessage: byId('textPlaygroundApplyMessage'),
    assessment: byId('textPlaygroundAssessment'),
    assessmentIntent: byId('textPlaygroundAssessmentIntent'),
    assessmentAmbiguity: byId('textPlaygroundAssessmentAmbiguity'),
    deliveryLabels: byId('textPlaygroundDeliveryLabels'),
    deliveryConfidence: byId('textPlaygroundDeliveryConfidence'),
    deliveryEvidence: byId('textPlaygroundDeliveryEvidence'),
    clarification: byId('textPlaygroundClarification'),
    clarificationQuestion: byId('textPlaygroundClarificationQuestion'),
    clarificationDetails: byId('textPlaygroundClarificationDetails'),
    columns: {
      raw: { text: byId('textPlaygroundColumnRawText'), button: byId('textPlaygroundColumnRawButton') },
      faithful: { text: byId('textPlaygroundColumnFaithfulText'), button: byId('textPlaygroundColumnFaithfulButton') },
      clearer: { text: byId('textPlaygroundColumnClearerText'), button: byId('textPlaygroundColumnClearerButton') },
      alternate: { text: byId('textPlaygroundColumnAlternateText'), button: byId('textPlaygroundColumnAlternateButton') },
    },
    preservationList: byId('textPlaygroundPreservationList'),
    warnings: byId('textPlaygroundWarnings'),
    warningsList: byId('textPlaygroundWarningsList'),
  };
}

// Sets up the playground if its markup is present; no-ops otherwise (safe to
// call against a doc that doesn't have #textPlaygroundSection, e.g. an older
// build or a test doc). Kicks off persona/draft list loads but never touches
// audio, transcription, or TTS.
export function initTextPlayground({ doc } = {}) {
  const activeDoc = doc || (typeof document !== 'undefined' ? document : null);
  if (!activeDoc || typeof activeDoc.getElementById !== 'function') return null;

  const elements = queryElements(activeDoc);
  if (!elements.section) return null;

  const feature = createTextPlaygroundFeature({ elements, api: defaultApi });
  feature.wire();
  feature.rerender();
  feature.refreshPersonas();
  feature.refreshDrafts();
  return feature;
}

if (typeof document !== 'undefined') {
  initTextPlayground();
}
