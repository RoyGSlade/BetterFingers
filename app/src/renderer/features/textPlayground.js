// Scribe: a silent, text-only place to paste/type a message, pick a
// persona, and run the local LLM through the Message Rescue endpoint (I3.2)
// without any microphone, transcription, or TTS involved (board #31).
//
// Reuses F2.3's pure view-model (./messageRescue.js) and F2.8's escaped panel
// renderer (./messageRescuePanel.js) wholesale for the assessment/delivery/
// clarification/variants/preservation/warnings region -- this module only
// adds the Scribe-specific controls (text/context input, persona/draft
// pickers, run/cancel/clear, apply-to-draft, copy) around it. Independent of
// main.js: loaded via its own <script type="module"> tag and self-initializes
// on import, exactly like messageRescuePanel.js.
//
// Privacy/preservation invariants this module upholds:
// - Nothing is sent anywhere automatically; Apply/Copy are explicit user
//   actions, and applying to a draft only ever overwrites that draft's
//   final_text (server-side /drafts/:id/edit), never its raw_text.
// - The optional context field stays visible and editable so the user can add
//   detail after a first pass. Each Run captures its current value into a new
//   server-side, one-use context envelope (F2.5 ContextSession semantics);
//   Clear removes both the local form value and any unconsumed server copy.
// - No microphone, transcription, playback, or TTS call exists anywhere in
//   this file (grep-verified in tests) -- `signals` is never populated,
//   since there is no dictation in this flow.

import {
  fetchPersonas,
  fetchDrafts,
  fetchLlmModels,
  fetchProfiles,
  editDraft,
  captureManualMessageRescueContext,
  clearMessageRescueContext,
  generateMessageRescue,
} from '../api/backend.js';
import { formatMessageRescueViewModel, formatVariants } from './messageRescue.js';
import { buildMessageRescuePanelModel, renderMessageRescuePanel, escapeHtml } from './messageRescuePanel.js';
import { shouldAutowire } from '../lib/autowire.mjs';
import {
  assembleBatchResults,
  cancelBatch,
  createBatchOperation,
  needsLongInputChoice,
  recordBatchFailure,
  recordBatchSuccess,
  resumeBatch,
  splitLongInput,
} from './scribeBatching.js';

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
    allowClarifyingQuestion: false,
    ranAllowedClarifyingQuestion: false,
    clarificationOpen: false,
    clarificationAnswer: '',
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
    batchChoiceOpen: false,
    batchPreference: '500',
    batchOperation: null,
  };
}

export function setText(state, text) {
  return { ...state, text: String(text ?? '') };
}

export function setContextText(state, contextText) {
  return { ...state, contextText: String(contextText ?? '') };
}

export function setAllowClarifyingQuestion(state, allowed) {
  return { ...state, allowClarifyingQuestion: Boolean(allowed) };
}

export function setClarificationAnswer(state, answer) {
  return { ...state, clarificationAnswer: String(answer ?? '') };
}

export function dismissClarification(state) {
  return { ...state, clarificationOpen: false, clarificationAnswer: '' };
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
export function beginRequest(state, { modelId = null, allowClarifyingQuestion = state.allowClarifyingQuestion } = {}) {
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
    ranAllowedClarifyingQuestion: Boolean(allowClarifyingQuestion),
    clarificationOpen: false,
    clarificationAnswer: '',
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
  switch (outcome.kind) {
    case 'done': {
      const result = outcome.result || null;
      return {
        ...state,
        status: STATUS.DONE,
        result,
        selectedVariant: 'faithful',
        clarificationOpen: state.ranAllowedClarifyingQuestion && clarificationGatePassed(result),
      };
    }
    case 'timeout':
      return { ...state, status: STATUS.TIMEOUT };
    case 'cancelled':
      return { ...state, status: STATUS.CANCELLED };
    default:
      return { ...state, status: STATUS.ERROR, errorMessage: String(outcome.message || 'Request failed.') };
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
  if (!onlyFaithful) return '';

  const warnings = Array.isArray(state.result.warnings) ? state.result.warnings.map((warning) => String(warning || '')) : [];
  const failedChecks = Array.isArray(state.result.preservation_checks)
    ? state.result.preservation_checks.filter((check) => check && check.passed === false)
    : [];
  const failedCategories = [...new Set(failedChecks.map((check) => String(check.name || '').split('/').pop()).filter(Boolean))];
  let reason = 'The local model did not return two additional safe variants.';
  if (warnings.some((warning) => warning.includes('not valid JSON'))) {
    reason = 'The local model response was not valid JSON.';
  } else if (warnings.some((warning) => warning.includes('exceeded size limit'))) {
    reason = 'The local model response exceeded the size limit.';
  } else if (warnings.some((warning) => warning.includes('model call timed out'))) {
    reason = 'The local model timed out.';
  } else if (warnings.some((warning) => warning.includes('model call failed'))) {
    reason = 'The local model call failed.';
  } else if (failedCategories.length > 0) {
    const labels = failedCategories.map((category) => category.replaceAll('_', ' ')).join(', ');
    reason = `Clearer/Alternate did not pass the required ${labels} preservation check${failedCategories.length === 1 ? '' : 's'}.`;
  }
  return `Fallback: only a safe, faithful-only result was produced. ${reason}`;
}

export function clarificationGatePassed(result) {
  const assessment = result && typeof result.assessment === 'object' ? result.assessment : null;
  const gate = assessment && typeof assessment.clarification_gate === 'object' ? assessment.clarification_gate : null;
  return Boolean(
    gate?.passed === true
    && String(assessment?.clarification_question || '').trim()
    && Array.isArray(assessment?.missing_details)
    && assessment.missing_details.length > 0,
  );
}

export function buildClarificationGateText(result) {
  if (!clarificationGatePassed(result)) return '';
  const gate = result.assessment.clarification_gate;
  const confidence = Math.round(Number(gate.confidence || 0) * 100);
  const threshold = Math.round(Number(gate.threshold || 0) * 100);
  return `Confidence gate passed: ${confidence}% (minimum ${threshold}%). A best-effort rewrite is already available.`;
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

export const SCRIBE_OUTPUT_CHOICES = Object.freeze([
  { key: 'faithful', label: 'Base' },
  { key: 'clearer', label: 'Alternative one' },
  { key: 'alternate', label: 'Alternative two' },
]);

// The literal task ask: raw/faithful/clearer/alternate, side by side, so the
// user can compare all four at once instead of toggling one at a time. `raw`
// is a client-side-only column (the text as submitted) and is a legitimate
// choice to Apply/Copy too -- sometimes none of the rewrites beat the
// original. Text fields here are RAW/unescaped; the DOM layer must write
// them via textContent, never innerHTML.
export function buildComparisonColumns(state) {
  const variantsByKey = Object.fromEntries(formatVariants(state.result && state.result.variants).map((v) => [v.key, v]));
  return SCRIBE_OUTPUT_CHOICES.map(({ key, label }) => {
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

// Combines this module's Scribe-only fields with F2.3/F2.8's own
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
    allowClarifyingQuestion: state.allowClarifyingQuestion,
    clarificationOpen: state.clarificationOpen && clarificationGatePassed(state.result),
    clarificationAnswer: state.clarificationAnswer,
    clarificationGateText: buildClarificationGateText(state.result),
    canSubmitClarification: state.clarificationOpen && state.clarificationAnswer.trim().length > 0 && state.status !== STATUS.BUSY,
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
    batchChoiceOpen: state.batchChoiceOpen,
    batchOperation: state.batchOperation,
    rescuePanelModel,
  };
}

// --- DOM writer ---------------------------------------------------------------

export function renderTextPlayground(elements, model) {
  if (elements.text && elements.text.value !== model.text) elements.text.value = model.text;
  if (elements.context && elements.context.value !== model.contextText) elements.context.value = model.contextText;
  if (elements.clarificationYesButton) {
    elements.clarificationYesButton.setAttribute?.('aria-pressed', String(model.allowClarifyingQuestion));
    elements.clarificationYesButton.classList?.toggle?.('is-active', model.allowClarifyingQuestion);
  }
  if (elements.clarificationNoButton) {
    elements.clarificationNoButton.setAttribute?.('aria-pressed', String(!model.allowClarifyingQuestion));
    elements.clarificationNoButton.classList?.toggle?.('is-active', !model.allowClarifyingQuestion);
  }
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
  if (elements.batchChoice) elements.batchChoice.hidden = !model.batchChoiceOpen;
  if (elements.batchProgress) {
    const operation = model.batchOperation;
    elements.batchProgress.hidden = !operation;
    const total = operation?.chunks?.length || 0;
    const current = operation?.state === 'completed' ? total : Math.min(total, (operation?.index || 0) + 1);
    if (elements.batchProgressTitle) elements.batchProgressTitle.textContent = operation?.state === 'completed' ? 'Processing complete' : 'Processing text';
    if (elements.batchProgressDetail) {
      elements.batchProgressDetail.textContent = operation
        ? `${operation.state === 'paused' ? 'Paused by error' : operation.state} · Chunk ${current} of ${total}${operation.error ? ` · ${operation.error}` : ''}`
        : '';
    }
    if (elements.batchRetryButton) elements.batchRetryButton.hidden = operation?.state !== 'paused';
    if (elements.batchContinueButton) elements.batchContinueButton.hidden = operation?.state !== 'paused';
  }

  // Side-by-side Base/Alternative one/Alternative two comparison -- each column's
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
  if (elements.clarification) {
    elements.clarification.hidden = !model.clarificationOpen;
    if (model.clarificationOpen) elements.clarificationAnswer?.focus?.();
  }
  if (elements.clarificationAnswer && elements.clarificationAnswer.value !== model.clarificationAnswer) {
    elements.clarificationAnswer.value = model.clarificationAnswer;
  }
  if (elements.clarificationGateStatus) elements.clarificationGateStatus.textContent = model.clarificationGateText;
  if (elements.clarificationSubmitButton) elements.clarificationSubmitButton.disabled = !model.canSubmitClarification;
}

// --- live feature (DOM composition + backend client) -------------------------

const defaultApi = {
  fetchPersonas,
  fetchDrafts,
  fetchLlmModels,
  fetchProfiles,
  applyToDraft: (draftId, finalText) => editDraft(draftId, finalText),
  captureManualContext: (text) => captureManualMessageRescueContext(text),
  clearContext: () => clearMessageRescueContext(),
  generate: ({ transcript, persona, useContext, allowClarifyingQuestion }) => generateMessageRescue({
    transcript, persona, useContext, allowClarifyingQuestion,
  }),
};

/**
 * @param {object} deps
 * @param {object} deps.elements DOM element references (see queryElements below)
 * @param {object} [deps.api] injected backend client (defaults to the real one)
 */
export function createTextPlaygroundFeature({ elements, api = defaultApi, notificationCenter = null, storage = globalThis.localStorage } = {}) {
  let state = createInitialState();
  let personas = {};
  let drafts = [];
  let modelId = null;
  let modelLimits = {};
  let personaExplicitlySelected = false;
  const batchOperationId = 'scribe-long-input';

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
    await applyActiveProfilePersona();
  }

  async function applyActiveProfilePersona() {
    if (personaExplicitlySelected || typeof api.fetchProfiles !== 'function') return;
    try {
      const profilePayload = await api.fetchProfiles();
      const preset = String(profilePayload?.settings?.current_preset ?? '').trim();
      const hasPreset = Array.isArray(personas)
        ? personas.some((name) => name === preset)
        : Object.prototype.hasOwnProperty.call(personas || {}, preset);
      if (!personaExplicitlySelected && hasPreset) {
        state = setPersona(state, preset);
        rerender();
      }
    } catch (_e) {
      // Profile defaults are advisory; a profile request failure must not
      // make the persona picker unavailable or replace an explicit choice.
    }
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
      const selected = (res?.models || []).find?.((item) => item.id === modelId) || {};
      modelLimits = {
        contextTokens: selected.context_tokens || selected.context_length || res?.context_tokens,
        reservedOutputTokens: selected.max_output_tokens || res?.max_output_tokens,
      };
    } catch (_e) {
      modelId = null;
      modelLimits = {};
    }
  }

  async function generateOne(transcript, { contextText, allowClarifyingQuestion }) {
    let useContext = false;
    if (contextText) {
      try {
        await api.captureManualContext(contextText);
        useContext = true;
      } catch (_captureErr) {
        useContext = false;
      }
    }
    const response = await api.generate({
      transcript,
      persona: state.persona || null,
      useContext,
      allowClarifyingQuestion,
    });
    if (response?.status !== 'done') {
      const message = response?.status === 'timeout'
        ? 'The model call timed out.'
        : `Chunk ended with status ${response?.status || 'unknown'}.`;
      throw new Error(message);
    }
    return response.result;
  }

  async function processBatch(myRequestId, pendingContextText, allowClarifyingQuestion) {
    let operation = state.batchOperation;
    while (operation && operation.index < operation.chunks.length) {
      if (state.requestId !== myRequestId || state.status !== STATUS.BUSY) return;
      operation = { ...operation, state: operation.state === 'retrying' ? 'retrying' : 'processing' };
      state = { ...state, batchOperation: operation };
      notificationCenter?.update({
        id: batchOperationId,
        title: 'Processing text',
        state: operation.state,
        detail: operation.state === 'retrying' ? 'Retrying chunk' : `Processing chunk ${operation.index + 1} of ${operation.chunks.length}`,
        current: operation.index + 1,
        total: operation.chunks.length,
        workspace: 'scribe',
      });
      rerender();
      try {
        const result = await generateOne(operation.chunks[operation.index], {
          contextText: pendingContextText,
          allowClarifyingQuestion: allowClarifyingQuestion && operation.index === 0,
        });
        operation = recordBatchSuccess(operation, result);
        state = { ...state, batchOperation: operation };
      } catch (error) {
        operation = recordBatchFailure(operation, error?.message || error);
        const partial = assembleBatchResults(operation.completed, state.ranText);
        partial.batch.complete = false;
        partial.batch.failed_chunk = operation.failedIndex;
        state = {
          ...state,
          status: STATUS.ERROR,
          result: partial,
          selectedVariant: 'faithful',
          errorMessage: `Chunk ${operation.index + 1} failed. Retry to continue; completed output is preserved. ${operation.error}`,
          batchOperation: operation,
        };
        notificationCenter?.update({
          id: batchOperationId,
          title: 'Processing text',
          state: 'error',
          detail: `Paused at chunk ${operation.index + 1}. Completed chunks were preserved.`,
          current: operation.index + 1,
          total: operation.chunks.length,
          workspace: 'scribe',
        });
        rerender();
        return;
      }
    }
    const result = assembleBatchResults(operation?.completed || [], state.ranText);
    state = receiveResult({ ...state, batchOperation: operation }, {
      requestId: myRequestId,
      outcome: { kind: 'done', result },
    });
    notificationCenter?.update({
      id: batchOperationId,
      title: 'Processing text',
      state: 'completed',
      detail: 'All chunks completed and were assembled in order.',
      current: operation?.chunks?.length || 0,
      total: operation?.chunks?.length || 0,
      workspace: 'scribe',
    });
    rerender();
  }

  async function run({ allowClarifyingQuestion = state.allowClarifyingQuestion, batchMode = null } = {}) {
    if (!canRun(state)) return;

    if (!batchMode && needsLongInputChoice(state.text)) {
      state = { ...state, batchChoiceOpen: true };
      notificationCenter?.update({
        id: batchOperationId,
        title: 'Large Scribe input',
        state: 'preparing',
        detail: 'Choose a batch size before generation.',
        workspace: 'scribe',
      });
      rerender();
      return;
    }

    // Flip to busy synchronously (before any await) so Cancel is immediately
    // available and the UI never sits in a silent gap waiting on the model-id
    // lookup below.
    const pendingContextText = state.contextText.trim();
    state = { ...beginRequest(state, { modelId, allowClarifyingQuestion }), batchChoiceOpen: false };
    const myRequestId = state.requestId;
    if (batchMode && batchMode !== 'full') {
      const chunks = splitLongInput(state.ranText, Number(batchMode), modelLimits);
      state = { ...state, batchPreference: String(batchMode), batchOperation: createBatchOperation(chunks) };
      try { storage?.setItem?.('betterfingers.scribe.batchPreference', String(batchMode)); } catch (_error) { /* best effort */ }
    } else {
      state = { ...state, batchOperation: null };
      if (batchMode === 'full') {
        try { storage?.setItem?.('betterfingers.scribe.batchPreference', 'full'); } catch (_error) { /* best effort */ }
      }
    }
    rerender();

    await refreshModelId();
    if (state.requestId === myRequestId && state.status === STATUS.BUSY) {
      state = { ...state, ranModelId: modelId };
      if (batchMode && batchMode !== 'full') {
        state = { ...state, batchOperation: createBatchOperation(splitLongInput(state.ranText, Number(batchMode), modelLimits)) };
      }
      rerender();
    }

    try {
      if (state.batchOperation) {
        await processBatch(myRequestId, pendingContextText, allowClarifyingQuestion);
        return;
      }
      const result = await generateOne(state.ranText, { contextText: pendingContextText, allowClarifyingQuestion });
      state = receiveResult(state, { requestId: myRequestId, outcome: { kind: 'done', result } });
    } catch (err) {
      const timedOut = String(err?.message || '').toLowerCase().includes('timed out');
      state = receiveResult(state, {
        requestId: myRequestId,
        outcome: timedOut ? { kind: 'timeout' } : { kind: 'error', message: err && err.message },
      });
    }
    rerender();
  }

  function cancel() {
    state = cancelRequest(state);
    if (state.batchOperation) state = { ...state, batchOperation: cancelBatch(state.batchOperation) };
    notificationCenter?.update({
      id: batchOperationId,
      title: 'Processing text',
      state: 'cancelled',
      detail: 'Remaining chunks were cancelled.',
      workspace: 'scribe',
    });
    rerender();
  }

  async function retryBatch() {
    if (state.batchOperation?.state !== 'paused') return;
    state = {
      ...state,
      status: STATUS.BUSY,
      errorMessage: '',
      batchOperation: resumeBatch(state.batchOperation),
    };
    const myRequestId = state.requestId;
    rerender();
    await processBatch(myRequestId, state.contextText.trim(), false);
  }

  function setClarificationPermission(allowed) {
    state = setAllowClarifyingQuestion(state, allowed);
    rerender();
  }

  function dismissClarificationPopup() {
    state = dismissClarification(state);
    rerender();
  }

  async function submitClarification() {
    if (!state.clarificationOpen || !clarificationGatePassed(state.result)) return;
    const answer = state.clarificationAnswer.trim();
    if (!answer) return;
    const question = String(state.result?.assessment?.clarification_question || '').trim();
    const clarificationContext = `Clarification question: ${question}\nAnswer: ${answer}`;
    const existingContext = state.contextText.trim();
    state = {
      ...dismissClarification(state),
      contextText: existingContext ? `${existingContext}\n\n${clarificationContext}` : clarificationContext,
    };
    rerender();
    // The answer is context for one best-effort rerun. Suppress a second
    // popup in the same clarification round even when the user's general
    // permission remains Yes for future manual runs.
    await run({ allowClarifyingQuestion: false });
  }

  async function clear() {
    try {
      await api.clearContext();
    } catch (_e) {
      // Best-effort privacy cleanup; local state is cleared regardless.
    }
    state = clearAll();
    personaExplicitlySelected = false;
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
    elements.clarificationYesButton?.addEventListener?.('click', () => setClarificationPermission(true));
    elements.clarificationNoButton?.addEventListener?.('click', () => setClarificationPermission(false));
    elements.clarificationAnswer?.addEventListener?.('input', () => {
      state = setClarificationAnswer(state, elements.clarificationAnswer.value);
      rerender();
    });
    elements.clarificationSubmitButton?.addEventListener?.('click', () => { submitClarification(); });
    elements.clarificationDismissButton?.addEventListener?.('click', dismissClarificationPopup);
    if (elements.personaSelect && typeof elements.personaSelect.addEventListener === 'function') {
      elements.personaSelect.addEventListener('change', () => {
        personaExplicitlySelected = true;
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
    for (const button of elements.batchChoiceButtons || []) {
      button?.addEventListener?.('click', () => run({ batchMode: button.dataset.scribeBatch }));
    }
    elements.batchRetryButton?.addEventListener?.('click', () => retryBatch());
    elements.batchContinueButton?.addEventListener?.('click', () => retryBatch());
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
    setClarificationPermission,
    submitClarification,
    dismissClarification: dismissClarificationPopup,
    retryBatch,
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
    clarificationYesButton: byId('textPlaygroundClarificationYes'),
    clarificationNoButton: byId('textPlaygroundClarificationNo'),
    personaSelect: byId('textPlaygroundPersonaSelect'),
    runButton: byId('textPlaygroundRunButton'),
    cancelButton: byId('textPlaygroundCancelButton'),
    clearButton: byId('textPlaygroundClearButton'),
    status: byId('textPlaygroundStatus'),
    error: byId('textPlaygroundError'),
    ranInfo: byId('textPlaygroundRanInfo'),
    fallback: byId('textPlaygroundFallback'),
    batchChoice: byId('textPlaygroundBatchChoice'),
    batchChoiceButtons: Array.from(doc.querySelectorAll?.('[data-scribe-batch]') || []),
    batchProgress: byId('textPlaygroundBatchProgress'),
    batchProgressTitle: byId('textPlaygroundBatchProgressTitle'),
    batchProgressDetail: byId('textPlaygroundBatchProgressDetail'),
    batchRetryButton: byId('textPlaygroundBatchRetry'),
    batchContinueButton: byId('textPlaygroundBatchContinue'),
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
    clarificationAnswer: byId('textPlaygroundClarificationAnswer'),
    clarificationGateStatus: byId('textPlaygroundClarificationGateStatus'),
    clarificationSubmitButton: byId('textPlaygroundClarificationSubmit'),
    clarificationDismissButton: byId('textPlaygroundClarificationDismiss'),
    columns: {
      faithful: { text: byId('textPlaygroundColumnFaithfulText'), button: byId('textPlaygroundColumnFaithfulButton') },
      clearer: { text: byId('textPlaygroundColumnClearerText'), button: byId('textPlaygroundColumnClearerButton') },
      alternate: { text: byId('textPlaygroundColumnAlternateText'), button: byId('textPlaygroundColumnAlternateButton') },
    },
    preservationList: byId('textPlaygroundPreservationList'),
    warnings: byId('textPlaygroundWarnings'),
    warningsList: byId('textPlaygroundWarningsList'),
  };
}

// Sets up Scribe if its markup is present; no-ops otherwise (safe to
// call against a doc that doesn't have #textPlaygroundSection, e.g. an older
// build or a test doc). Kicks off persona/draft list loads but never touches
// audio, transcription, or TTS.
export function initTextPlayground({ doc, notificationCenter } = {}) {
  const activeDoc = doc || (typeof document !== 'undefined' ? document : null);
  if (!activeDoc || typeof activeDoc.getElementById !== 'function') return null;

  const elements = queryElements(activeDoc);
  if (!elements.section) return null;

  const feature = createTextPlaygroundFeature({ elements, api: defaultApi, notificationCenter });
  feature.wire();
  feature.rerender();
  feature.refreshPersonas();
  feature.refreshDrafts();
  return feature;
}

// Import-time self-init is opt-in only: see lib/autowire.mjs. This keeps
// importing this module (e.g. from a test, or from a page that hasn't
// opted in) from binding controls it doesn't own.
if (shouldAutowire()) {
  initTextPlayground();
}

// Scribe is the user-facing name. Keep the old export names as compatibility
// aliases because bootstrap and existing renderer tests still import the
// canonical textPlayground module path during this IA-only migration.
export const buildScribeModel = buildTextPlaygroundModel;
export const renderScribe = renderTextPlayground;
export const createScribeFeature = createTextPlaygroundFeature;
export const initScribe = initTextPlayground;
