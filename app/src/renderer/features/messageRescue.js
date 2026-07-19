// Pure, dependency-free view-model formatting for the Message Rescue feature
// (ACCOMPLISH.md F2.3). No DOM, no imports, no backend calls — every function
// here takes plain data shaped like the frozen contracts in
// backend/domain/contracts.py (ContextEnvelope, SpeechSignals,
// MessageRescueResult) and returns plain data (strings/arrays/booleans).
//
// Raw vs label fields: every returned object documents which string fields
// are "raw" (sourced from user speech, backend evidence, or model output —
// UNESCAPED, must be HTML-escaped by the DOM layer before insertion, see
// escapeHtml in app/src/renderer/main.js) versus "label" (authored in this
// module, static and safe to insert directly). This module never escapes
// anything itself — that responsibility belongs to whichever feature module
// wires this into the DOM (F2.8).
//
// Defensive by design: input may be null, partial, or malformed (wrong
// types, missing keys) if a request failed or the model output didn't parse.
// Every function degrades to empty/neutral output rather than fabricating
// content that wasn't in the payload.

const SOURCE_LABELS = {
  selection: 'from selection',
  clipboard_fallback: 'from clipboard',
  manual: 'entered manually',
};

const AXIS_LABELS = {
  arousal: 'Energy',
  urgency: 'Urgency',
  hesitation: 'Hesitation',
};

const VARIANT_LABELS = {
  faithful: 'Faithful',
  clearer: 'Clearer',
  alternate: 'Alternate',
};
const VARIANT_KEYS = Object.keys(VARIANT_LABELS);

function clampConfidence(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.min(1, Math.max(0, n));
}

function toPercentLabel(value) {
  return `${Math.round(clampConfidence(value) * 100)}%`;
}

function confidenceTone(value) {
  const c = clampConfidence(value);
  if (c >= 0.65) return 'success';
  if (c >= 0.4) return 'warning';
  return 'danger';
}

function isFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function stringOrEmpty(value) {
  return typeof value === 'string' ? value : '';
}

function filterStrings(list) {
  return Array.isArray(list) ? list.filter((item) => typeof item === 'string' && item.length > 0) : [];
}

// --- ContextEnvelope -----------------------------------------------------

// Formats visibility/expiry/use status for a ContextEnvelope. `nowSeconds`
// defaults to wall-clock time but should be passed explicitly by callers
// (and always in tests) for determinism.
export function formatContextStatus(context, nowSeconds = Date.now() / 1000) {
  if (!context || typeof context !== 'object') {
    return {
      active: false,
      expired: false,
      exhausted: false,
      statusLabel: 'No context captured.',
      sourceLabel: '',
      usesLabel: '',
      preview: '', // raw
    };
  }

  const expiresAt = Number(context.expires_at);
  const hasExpiry = Number.isFinite(expiresAt);
  const expired = hasExpiry && nowSeconds >= expiresAt;

  const maxUsesRaw = Number(context.max_uses);
  const maxUses = Number.isFinite(maxUsesRaw) ? maxUsesRaw : 1;
  const useCountRaw = Number(context.use_count);
  const useCount = Number.isFinite(useCountRaw) ? useCountRaw : 0;
  const exhausted = maxUses > 0 && useCount >= maxUses;

  const source = typeof context.source === 'string' ? context.source : '';
  const sourceLabel = source
    ? (SOURCE_LABELS[source] || source)
    : '';

  const preview = typeof context.visible_preview === 'string' && context.visible_preview
    ? context.visible_preview
    : stringOrEmpty(context.text);

  let statusLabel;
  if (expired) {
    statusLabel = 'Context expired.';
  } else if (exhausted) {
    statusLabel = 'Context already used.';
  } else if (hasExpiry) {
    const remaining = Math.max(0, Math.round(expiresAt - nowSeconds));
    statusLabel = `Context active · expires in ${remaining}s`;
  } else {
    statusLabel = 'Context active.';
  }

  const usesLabel = maxUses > 0 ? `${useCount}/${maxUses} uses` : '';

  return {
    active: !expired && !exhausted,
    expired,
    exhausted,
    statusLabel,
    sourceLabel,
    usesLabel,
    preview, // raw
  };
}

// --- SpeechSignals ---------------------------------------------------------

// Formats the raw SpeechSignals contract into observable, evidence-backed
// labels. Only bounded [0,1] delivery axes that are present and numeric are
// rendered — never invented for missing axes.
export function formatSpeechSignals(signals) {
  if (!signals || typeof signals !== 'object') {
    return { axisLabels: [], evidence: [], confidenceLabel: '', confidenceTone: 'danger', hasSignals: false };
  }

  const axes = signals.delivery_axes && typeof signals.delivery_axes === 'object' ? signals.delivery_axes : {};
  const axisLabels = Object.keys(AXIS_LABELS)
    .filter((key) => isFiniteNumber(axes[key]))
    .map((key) => `${AXIS_LABELS[key]}: ${toPercentLabel(axes[key])}`); // label

  return {
    axisLabels, // label
    evidence: filterStrings(signals.evidence), // raw
    confidenceLabel: toPercentLabel(signals.confidence), // label
    confidenceTone: confidenceTone(signals.confidence),
    hasSignals: true,
  };
}

// --- MessageRescueResult.assessment ---------------------------------------

// `ambiguityRisk` passes a string risk level through as raw text (backend
// vocabulary, not necessarily hard-coded) and formats a numeric risk as a
// percentage label; anything else is left blank rather than guessed.
export function formatAssessmentSummary(assessment) {
  if (!assessment || typeof assessment !== 'object') {
    return { intent: '', ambiguityRisk: '' };
  }

  const intent = stringOrEmpty(assessment.intent); // raw
  let ambiguityRisk = '';
  if (typeof assessment.ambiguity_risk === 'string') {
    ambiguityRisk = assessment.ambiguity_risk; // raw
  } else if (isFiniteNumber(assessment.ambiguity_risk)) {
    ambiguityRisk = toPercentLabel(assessment.ambiguity_risk); // label
  }

  return { intent, ambiguityRisk };
}

// A clarification is only surfaced when the backend actually asked one;
// blank/whitespace-only questions are treated as "no clarification" rather
// than rendered as an empty prompt.
export function formatClarification(assessment) {
  if (!assessment || typeof assessment !== 'object') {
    return null;
  }

  const question = stringOrEmpty(assessment.clarification_question).trim();
  if (!question) {
    return null;
  }

  return {
    question, // raw
    missingDetails: filterStrings(assessment.missing_details), // raw[]
  };
}

// --- MessageRescueResult.delivery ------------------------------------------

export function formatDeliverySignals(delivery) {
  if (!delivery || typeof delivery !== 'object') {
    return { labels: [], evidence: [], confidenceLabel: '', confidenceTone: 'danger' };
  }

  return {
    labels: filterStrings(delivery.labels), // raw
    evidence: filterStrings(delivery.evidence), // raw
    confidenceLabel: toPercentLabel(delivery.confidence), // label
    confidenceTone: confidenceTone(delivery.confidence),
  };
}

// --- MessageRescueResult.variants -------------------------------------------

// Always returns all three variant slots so the DOM layer can render a
// consistent panel; `available` is false (and `text` empty) rather than
// invented for any variant the backend didn't produce (e.g. a parse-failure
// fallback that only populates `faithful`).
export function formatVariants(variants) {
  const safe = variants && typeof variants === 'object' ? variants : {};
  return VARIANT_KEYS.map((key) => {
    const text = stringOrEmpty(safe[key]); // raw
    return {
      key,
      label: VARIANT_LABELS[key], // label
      text,
      available: text.length > 0,
    };
  });
}

// --- MessageRescueResult.preservation_checks / warnings ---------------------

// Accepts either `passed` or `ok` as the boolean field (backend result
// shapes are dict[str, Any], not a fixed dataclass) and defaults to failed
// rather than assuming success for a malformed entry.
export function formatPreservationChecks(checks) {
  if (!Array.isArray(checks)) {
    return { items: [], allPassed: true, failedCount: 0 };
  }

  const items = checks
    .filter((check) => check && typeof check === 'object')
    .map((check) => ({
      name: stringOrEmpty(check.name) || stringOrEmpty(check.check) || 'check', // raw/label fallback
      passed: Boolean(check.passed ?? check.ok ?? false),
      detail: stringOrEmpty(check.detail), // raw
    }));

  const failedCount = items.filter((item) => !item.passed).length;
  return { items, allPassed: failedCount === 0, failedCount };
}

export function formatWarnings(warnings) {
  return filterStrings(warnings); // raw[]
}

// --- Composite view model ---------------------------------------------------

/**
 * Formats a full Message Rescue view model from a MessageRescueResult plus
 * optional ContextEnvelope/SpeechSignals. Every input is optional and may be
 * malformed; the result always has a stable, fully-populated shape so a DOM
 * layer can render it unconditionally.
 *
 * @param {object|null} result MessageRescueResult (or null/partial/malformed)
 * @param {object} [options]
 * @param {object|null} [options.context] ContextEnvelope
 * @param {object|null} [options.signals] SpeechSignals
 * @param {number} [options.now] seconds since epoch, for deterministic context expiry
 */
export function formatMessageRescueViewModel(result, { context = null, signals = null, now } = {}) {
  const hasResult = Boolean(result && typeof result === 'object');
  const safeResult = hasResult ? result : {};
  const assessment = safeResult.assessment && typeof safeResult.assessment === 'object' ? safeResult.assessment : {};
  const delivery = safeResult.delivery && typeof safeResult.delivery === 'object' ? safeResult.delivery : {};

  return {
    hasResult,
    context: formatContextStatus(context, now),
    signals: formatSpeechSignals(signals),
    assessment: formatAssessmentSummary(assessment),
    clarification: formatClarification(assessment),
    delivery: formatDeliverySignals(delivery),
    variants: formatVariants(safeResult.variants),
    preservation: formatPreservationChecks(safeResult.preservation_checks),
    warnings: formatWarnings(safeResult.warnings),
  };
}
