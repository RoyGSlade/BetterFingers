// Message Rescue panel — DOM composition layer (ACCOMPLISH.md F2.8).
//
// Wires the pure view-model formatting from ./messageRescue.js (F2.3) into a
// static, accessible panel that lives entirely behind a default-off local
// feature flag. This module is intentionally independent of main.js's
// composition root: it is loaded via its own <script type="module"> tag in
// index.html and self-initializes on import, so it never needs main.js (or
// any backend.js call) to exist or be edited. There is no fetch/IPC anywhere
// in this file — the panel only ever renders a fixed, synthetic example
// payload (never real user speech) for design/QA purposes, exactly like the
// deterministic fixtures used elsewhere in Phase 2.
//
// escapeHtml here is a deliberate, self-contained duplicate of main.js's
// helper (not imported) — this module must keep working even if main.js is
// absent or fails to load, since the two scripts are independent entries.

import { formatMessageRescueViewModel } from './messageRescue.js';

export const MESSAGE_RESCUE_FLAG_KEY = 'pref_message_rescue_enabled';

// --- feature flag ------------------------------------------------------------

// Default OFF: any value other than the literal string 'true' (including a
// missing key, a storage that throws, or a stray non-boolean value) counts as
// disabled. This is the "inactive by default" contract F2.8 must satisfy.
export function isMessageRescueEnabled(storage) {
  if (!storage || typeof storage.getItem !== 'function') return false;
  try {
    return storage.getItem(MESSAGE_RESCUE_FLAG_KEY) === 'true';
  } catch (_e) {
    return false;
  }
}

// --- escaping ------------------------------------------------------------

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]),
  );
}

function listHtml(items, { emptyMessage }) {
  if (!items.length) {
    return `<li class="empty-state">${escapeHtml(emptyMessage)}</li>`;
  }
  return items.map((item) => `<li>${escapeHtml(item)}</li>`).join('');
}

const VARIANT_ORDER = ['faithful', 'clearer', 'alternate'];

// --- pure DOM-ready model ------------------------------------------------

// Translates a formatMessageRescueViewModel() result into plain
// text/HTML-string fields, applying escaping to every raw field. This is the
// only place responsible for that escaping — renderMessageRescuePanel below
// just assigns these already-safe values, never raw view-model text.
export function buildMessageRescuePanelModel(viewModel, { selectedVariant } = {}) {
  const vm = viewModel || formatMessageRescueViewModel(null);

  const variantsByKey = new Map(vm.variants.map((v) => [v.key, v]));
  const firstAvailable = vm.variants.find((v) => v.available);
  const requested = selectedVariant && variantsByKey.get(selectedVariant);
  const activeVariant = (requested && requested.available && requested) || firstAvailable || variantsByKey.get('faithful');

  const hasAssessment = Boolean(vm.assessment.intent || vm.assessment.ambiguityRisk);

  return {
    emptyState: !vm.hasResult,

    contextStatusText: vm.context.statusLabel,
    contextPreviewText: vm.context.preview || 'No preview captured yet.',
    contextPreviewEmpty: !vm.context.preview,
    contextMetaText: [vm.context.sourceLabel, vm.context.usesLabel].filter(Boolean).join(' · '),
    contextClearDisabled: !vm.context.active,

    hasAssessment,
    assessmentIntentText: vm.assessment.intent,
    assessmentAmbiguityText: vm.assessment.ambiguityRisk,

    hasDeliverySignals: vm.delivery.labels.length > 0 || vm.delivery.evidence.length > 0,
    deliveryLabelsHtml: vm.delivery.labels.length
      ? vm.delivery.labels.map((l) => `<span class="message-rescue-chip">${escapeHtml(l)}</span>`).join('')
      : '<span class="empty-state">No delivery signals yet.</span>',
    deliveryConfidenceText: vm.delivery.labels.length || vm.delivery.evidence.length ? vm.delivery.confidenceLabel : '',
    deliveryConfidenceTone: vm.delivery.confidenceTone,
    deliveryEvidenceHtml: listHtml(vm.delivery.evidence, { emptyMessage: 'No supporting evidence yet.' }),

    hasClarification: Boolean(vm.clarification),
    clarificationQuestionText: vm.clarification ? vm.clarification.question : '',
    clarificationDetailsHtml: vm.clarification
      ? listHtml(vm.clarification.missingDetails, { emptyMessage: 'No specific missing details listed.' })
      : '',

    variantKeys: VARIANT_ORDER,
    variantAvailability: Object.fromEntries(vm.variants.map((v) => [v.key, v.available])),
    variantLabels: Object.fromEntries(vm.variants.map((v) => [v.key, v.label])),
    selectedVariantKey: activeVariant ? activeVariant.key : 'faithful',
    selectedVariantText: activeVariant && activeVariant.available ? activeVariant.text : '',
    selectedVariantEmpty: !(activeVariant && activeVariant.available),

    hasPreservationChecks: vm.preservation.items.length > 0,
    preservationAllPassed: vm.preservation.allPassed,
    preservationListHtml: vm.preservation.items.length
      ? vm.preservation.items
          .map(
            (item) =>
              `<li class="message-rescue-check message-rescue-check--${item.passed ? 'pass' : 'fail'}">` +
              `<span class="message-rescue-check-icon" aria-hidden="true">${item.passed ? '✓' : '✕'}</span>` +
              `<span class="visually-hidden">${item.passed ? 'Passed:' : 'Failed:'}</span> ` +
              `<span class="message-rescue-check-name">${escapeHtml(item.name)}</span>` +
              (item.detail ? `<span class="message-rescue-check-detail">${escapeHtml(item.detail)}</span>` : '') +
              `</li>`,
          )
          .join('')
      : '<li class="empty-state">No preservation checks run yet.</li>',

    hasWarnings: vm.warnings.length > 0,
    warningsHtml: vm.warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join(''),
  };
}

// --- DOM writer ------------------------------------------------------------

// Assigns panelModel fields onto a plain map of element-like objects (each
// only needs whichever of textContent/innerHTML/hidden/disabled it's given
// below — real DOM nodes and simple test stubs both satisfy that). No
// element is ever queried here; the caller (initMessageRescuePanel) owns
// that, so this function is exercisable in tests without a real DOM.
export function renderMessageRescuePanel(elements, panelModel) {
  const m = panelModel;

  if (elements.contextStatus) elements.contextStatus.textContent = m.contextStatusText;
  if (elements.contextPreview) {
    elements.contextPreview.textContent = m.contextPreviewText;
    elements.contextPreview.className = m.contextPreviewEmpty
      ? 'draft-text message-rescue-context-preview empty-state'
      : 'draft-text message-rescue-context-preview';
  }
  if (elements.contextMeta) elements.contextMeta.textContent = m.contextMetaText;
  if (elements.contextClearButton) elements.contextClearButton.disabled = m.contextClearDisabled;

  if (elements.assessment) elements.assessment.hidden = !m.hasAssessment;
  if (elements.assessmentIntent) elements.assessmentIntent.textContent = m.assessmentIntentText;
  if (elements.assessmentAmbiguity) elements.assessmentAmbiguity.textContent = m.assessmentAmbiguityText;

  if (elements.deliveryLabels) elements.deliveryLabels.innerHTML = m.deliveryLabelsHtml;
  if (elements.deliveryConfidence) {
    elements.deliveryConfidence.textContent = m.deliveryConfidenceText;
    elements.deliveryConfidence.hidden = !m.hasDeliverySignals;
    if (typeof elements.deliveryConfidence.setAttribute === 'function') {
      elements.deliveryConfidence.setAttribute('data-tone', m.deliveryConfidenceTone);
    }
  }
  if (elements.deliveryEvidence) elements.deliveryEvidence.innerHTML = m.deliveryEvidenceHtml;

  if (elements.clarification) elements.clarification.hidden = !m.hasClarification;
  if (elements.clarificationQuestion) elements.clarificationQuestion.textContent = m.clarificationQuestionText;
  if (elements.clarificationDetails) elements.clarificationDetails.innerHTML = m.clarificationDetailsHtml;

  for (const key of m.variantKeys) {
    const input = elements.variantInputs && elements.variantInputs[key];
    if (input) input.disabled = !m.variantAvailability[key];
  }
  if (elements.variantText) {
    elements.variantText.textContent = m.selectedVariantEmpty
      ? `No ${(m.variantLabels[m.selectedVariantKey] || 'this').toLowerCase()} variant available yet.`
      : m.selectedVariantText;
  }

  if (elements.preservationList) elements.preservationList.innerHTML = m.preservationListHtml;

  if (elements.warnings) {
    elements.warnings.hidden = !m.hasWarnings;
    if (elements.warningsList) elements.warningsList.innerHTML = m.warningsHtml;
  }
}

// --- example fixture (synthetic, never real user data) ---------------------
//
// Deterministic placeholder so the panel has something representative to
// show when the flag is on. Mirrors the shape of the frozen backend
// contracts (ContextEnvelope / SpeechSignals / MessageRescueResult) but is
// entirely authored text, not a real capture.

const EXAMPLE_NOW = 1_800_000_000;

export const EXAMPLE_CONTEXT = {
  id: 'example-context',
  text: 'Hey, can we push the sync to tomorrow? Something came up.',
  source: 'selection',
  captured_at: EXAMPLE_NOW - 20,
  expires_at: EXAMPLE_NOW + 100,
  use_count: 0,
  max_uses: 1,
  visible_preview: 'Hey, can we push the sync to tomorrow? Something came up.',
};

export const EXAMPLE_SIGNALS = {
  delivery_axes: { arousal: 0.62, urgency: 0.71, hesitation: 0.34 },
  evidence: ['fast speaking rate', 'two short pauses before the ask'],
  confidence: 0.58,
};

export const EXAMPLE_RESULT = {
  assessment: {
    intent: 'Reschedule a meeting and explain why.',
    ambiguity_risk: 'medium',
    missing_details: ['which day "tomorrow" refers to'],
    clarification_question: 'Do you mean tomorrow, or the day after?',
  },
  delivery: {
    labels: ['rushed', 'apologetic'],
    evidence: ['fast speaking rate', 'trailing "sorry" tone'],
    confidence: 0.58,
  },
  variants: {
    faithful: 'Hey, can we push the sync to tomorrow? Something came up.',
    clearer: 'Could we move our sync to tomorrow? Something came up on my end.',
    alternate: 'Sorry for the short notice — can we reschedule the sync to tomorrow?',
  },
  preservation_checks: [
    { name: 'Names preserved', passed: true, detail: 'No names present in the source.' },
    { name: 'Dates preserved', passed: false, detail: '"tomorrow" is relative and was not resolved to a date.' },
  ],
  warnings: ['Clarify which day "tomorrow" means before sending.'],
};

export function buildExampleViewModel() {
  return formatMessageRescueViewModel(EXAMPLE_RESULT, {
    context: EXAMPLE_CONTEXT,
    signals: EXAMPLE_SIGNALS,
    now: EXAMPLE_NOW - 5,
  });
}

// --- init --------------------------------------------------------------

function queryElements(doc) {
  const byId = (id) => doc.getElementById(id);
  return {
    section: byId('messageRescuePanel'),
    contextStatus: byId('messageRescueContextStatus'),
    contextPreview: byId('messageRescueContextPreview'),
    contextMeta: byId('messageRescueContextMeta'),
    contextClearButton: byId('messageRescueClearContextButton'),
    assessment: byId('messageRescueAssessment'),
    assessmentIntent: byId('messageRescueAssessmentIntent'),
    assessmentAmbiguity: byId('messageRescueAssessmentAmbiguity'),
    deliveryLabels: byId('messageRescueDeliveryLabels'),
    deliveryConfidence: byId('messageRescueDeliveryConfidence'),
    deliveryEvidence: byId('messageRescueDeliveryEvidence'),
    clarification: byId('messageRescueClarification'),
    clarificationQuestion: byId('messageRescueClarificationQuestion'),
    clarificationDetails: byId('messageRescueClarificationDetails'),
    variantInputs: {
      faithful: byId('messageRescueVariantFaithful'),
      clearer: byId('messageRescueVariantClearer'),
      alternate: byId('messageRescueVariantAlternate'),
    },
    variantText: byId('messageRescueVariantText'),
    preservationList: byId('messageRescuePreservationList'),
    warnings: byId('messageRescueWarnings'),
    warningsList: byId('messageRescueWarningsList'),
  };
}

// Sets up the panel: hides it unless the flag is on, and — only when on —
// renders the deterministic example and wires purely local interactions
// (switching the previewed variant, clearing the example context). Neither
// interaction ever calls a backend; both just re-render already-formatted
// local data. Safe to call multiple times or against a doc missing the
// panel markup (no-ops if #messageRescuePanel isn't present).
export function initMessageRescuePanel({ doc, storage } = {}) {
  const activeDoc = doc || (typeof document !== 'undefined' ? document : null);
  if (!activeDoc || typeof activeDoc.getElementById !== 'function') return;

  const elements = queryElements(activeDoc);
  if (!elements.section) return;

  const activeStorage = storage || (typeof localStorage !== 'undefined' ? localStorage : null);
  const enabled = isMessageRescueEnabled(activeStorage);

  elements.section.hidden = !enabled;
  if (typeof elements.section.setAttribute === 'function') {
    elements.section.setAttribute('aria-hidden', enabled ? 'false' : 'true');
  }
  if (!enabled) return;

  let selectedVariant = 'faithful';
  const viewModel = buildExampleViewModel();

  const rerender = () => {
    renderMessageRescuePanel(elements, buildMessageRescuePanelModel(viewModel, { selectedVariant }));
  };
  rerender();

  for (const [key, input] of Object.entries(elements.variantInputs)) {
    if (!input || typeof input.addEventListener !== 'function') continue;
    input.addEventListener('change', () => {
      if (!input.checked) return;
      selectedVariant = key;
      rerender();
    });
  }

  if (elements.contextClearButton && typeof elements.contextClearButton.addEventListener === 'function') {
    elements.contextClearButton.addEventListener('click', () => {
      if (elements.contextPreview) {
        elements.contextPreview.textContent = 'Context cleared.';
        elements.contextPreview.className = 'draft-text message-rescue-context-preview empty-state';
      }
      if (elements.contextStatus) elements.contextStatus.textContent = 'No context captured.';
      if (elements.contextMeta) elements.contextMeta.textContent = '';
      elements.contextClearButton.disabled = true;
    });
  }
}

if (typeof document !== 'undefined') {
  initMessageRescuePanel();
}
