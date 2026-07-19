// Unit tests for the Message Rescue panel DOM composition layer (Phase 2, F2.8).
// Run with: node --test app/tests/messageRescuePanel.test.mjs
//
// No jsdom in this repo's test setup (matches the rest of app/tests/*.test.mjs
// -- DOM-driven feature modules keep their testable logic in plain
// text/HTML-string builders and thin property-assignment writers, exercised
// against plain stub objects instead of real DOM nodes; real-DOM coverage is
// the Playwright QA harness's job).
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { formatMessageRescueViewModel } from '../src/renderer/features/messageRescue.js';
import {
  MESSAGE_RESCUE_FLAG_KEY,
  isMessageRescueEnabled,
  escapeHtml,
  buildMessageRescuePanelModel,
  renderMessageRescuePanel,
  buildExampleViewModel,
  initMessageRescuePanel,
} from '../src/renderer/features/messageRescuePanel.js';

// --- isMessageRescueEnabled --------------------------------------------------

test('isMessageRescueEnabled: missing/invalid storage is disabled', () => {
  assert.equal(isMessageRescueEnabled(null), false);
  assert.equal(isMessageRescueEnabled(undefined), false);
  assert.equal(isMessageRescueEnabled({}), false);
});

test('isMessageRescueEnabled: default off when key absent', () => {
  const storage = { getItem: () => null };
  assert.equal(isMessageRescueEnabled(storage), false);
});

test('isMessageRescueEnabled: only the literal string "true" enables it', () => {
  assert.equal(isMessageRescueEnabled({ getItem: () => 'true' }), true);
  assert.equal(isMessageRescueEnabled({ getItem: () => 'TRUE' }), false);
  assert.equal(isMessageRescueEnabled({ getItem: () => true }), false);
  assert.equal(isMessageRescueEnabled({ getItem: () => '1' }), false);
  assert.equal(isMessageRescueEnabled({ getItem: () => 'false' }), false);
});

test('isMessageRescueEnabled: a throwing storage is treated as disabled, not a crash', () => {
  const storage = {
    getItem() {
      throw new Error('blocked');
    },
  };
  assert.equal(isMessageRescueEnabled(storage), false);
});

test('MESSAGE_RESCUE_FLAG_KEY is a stable, non-empty string', () => {
  assert.equal(typeof MESSAGE_RESCUE_FLAG_KEY, 'string');
  assert.ok(MESSAGE_RESCUE_FLAG_KEY.length > 0);
});

// --- escapeHtml --------------------------------------------------------------

test('escapeHtml: escapes all five HTML-significant characters', () => {
  assert.equal(escapeHtml(`<img src=x onerror="alert('x')">&`), '&lt;img src=x onerror=&quot;alert(&#39;x&#39;)&quot;&gt;&amp;');
});

test('escapeHtml: passes safe text through unchanged', () => {
  assert.equal(escapeHtml('plain text 123'), 'plain text 123');
});

test('escapeHtml: null/undefined become empty string', () => {
  assert.equal(escapeHtml(null), '');
  assert.equal(escapeHtml(undefined), '');
});

// --- buildMessageRescuePanelModel: empty/error/partial/low-confidence/complete ---

test('buildMessageRescuePanelModel: null result is the empty state', () => {
  const model = buildMessageRescuePanelModel(formatMessageRescueViewModel(null));
  assert.equal(model.emptyState, true);
  assert.equal(model.contextStatusText, 'No context captured.');
  assert.equal(model.contextPreviewEmpty, true);
  assert.equal(model.hasAssessment, false);
  assert.equal(model.hasDeliverySignals, false);
  assert.equal(model.hasClarification, false);
  assert.equal(model.selectedVariantEmpty, true);
  assert.equal(model.hasPreservationChecks, false);
  assert.equal(model.hasWarnings, false);
  assert.match(model.preservationListHtml, /No preservation checks run yet\./);
});

test('buildMessageRescuePanelModel: malformed/partial parse-failure fallback (only faithful populated)', () => {
  const vm = formatMessageRescueViewModel({ variants: { faithful: 'raw fallback text' } });
  const model = buildMessageRescuePanelModel(vm);
  assert.equal(model.variantAvailability.faithful, true);
  assert.equal(model.variantAvailability.clearer, false);
  assert.equal(model.variantAvailability.alternate, false);
  assert.equal(model.selectedVariantKey, 'faithful');
  assert.equal(model.selectedVariantText, 'raw fallback text');
  assert.equal(model.selectedVariantEmpty, false);
});

test('buildMessageRescuePanelModel: requested variant unavailable falls back to first available', () => {
  const vm = formatMessageRescueViewModel({ variants: { faithful: 'only this one' } });
  const model = buildMessageRescuePanelModel(vm, { selectedVariant: 'clearer' });
  assert.equal(model.selectedVariantKey, 'faithful');
  assert.equal(model.selectedVariantText, 'only this one');
});

test('buildMessageRescuePanelModel: requested variant honored when available', () => {
  const vm = formatMessageRescueViewModel({
    variants: { faithful: 'f', clearer: 'c', alternate: 'a' },
  });
  const model = buildMessageRescuePanelModel(vm, { selectedVariant: 'alternate' });
  assert.equal(model.selectedVariantKey, 'alternate');
  assert.equal(model.selectedVariantText, 'a');
});

test('buildMessageRescuePanelModel: low-confidence delivery propagates danger tone', () => {
  const vm = formatMessageRescueViewModel({
    delivery: { labels: ['flat'], evidence: [], confidence: 0.1 },
  });
  const model = buildMessageRescuePanelModel(vm);
  assert.equal(model.hasDeliverySignals, true);
  assert.equal(model.deliveryConfidenceTone, 'danger');
  assert.equal(model.deliveryConfidenceText, '10%');
});

test('buildMessageRescuePanelModel: mixed preservation checks report pass/fail correctly', () => {
  const vm = formatMessageRescueViewModel({
    preservation_checks: [
      { name: 'Names preserved', passed: true },
      { name: 'Dates preserved', passed: false, detail: 'relative date not resolved' },
    ],
  });
  const model = buildMessageRescuePanelModel(vm);
  assert.equal(model.hasPreservationChecks, true);
  assert.equal(model.preservationAllPassed, false);
  assert.match(model.preservationListHtml, /message-rescue-check--pass/);
  assert.match(model.preservationListHtml, /message-rescue-check--fail/);
  assert.match(model.preservationListHtml, /relative date not resolved/);
});

test('buildMessageRescuePanelModel: complete/happy-path result populates every region', () => {
  const vm = formatMessageRescueViewModel(
    {
      assessment: {
        intent: 'Reschedule a meeting',
        ambiguity_risk: 'medium',
        missing_details: ['which day'],
        clarification_question: 'Which day do you mean?',
      },
      delivery: { labels: ['rushed'], evidence: ['fast rate'], confidence: 0.8 },
      variants: { faithful: 'f', clearer: 'c', alternate: 'a' },
      preservation_checks: [{ name: 'ok', passed: true }],
      warnings: ['double check the date'],
    },
    {
      context: {
        text: 'full', source: 'manual', expires_at: 2000, use_count: 0, max_uses: 1,
        visible_preview: 'preview text',
      },
      now: 1000,
    },
  );
  const model = buildMessageRescuePanelModel(vm);
  assert.equal(model.emptyState, false);
  assert.equal(model.contextPreviewText, 'preview text');
  assert.equal(model.hasAssessment, true);
  assert.equal(model.assessmentIntentText, 'Reschedule a meeting');
  assert.equal(model.hasClarification, true);
  assert.equal(model.clarificationQuestionText, 'Which day do you mean?');
  assert.equal(model.hasWarnings, true);
  assert.match(model.warningsHtml, /double check the date/);
});

test('buildMessageRescuePanelModel: every raw field is escaped, never inserted verbatim', () => {
  const evil = '<script>alert(1)</script>';
  const vm = formatMessageRescueViewModel({
    assessment: { clarification_question: evil, missing_details: [evil] },
    delivery: { labels: [evil], evidence: [evil], confidence: 0.5 },
    variants: { faithful: evil },
    preservation_checks: [{ name: evil, passed: false, detail: evil }],
    warnings: [evil],
  });
  const model = buildMessageRescuePanelModel(vm);
  const haystacks = [
    model.deliveryLabelsHtml,
    model.deliveryEvidenceHtml,
    model.clarificationDetailsHtml,
    model.preservationListHtml,
    model.warningsHtml,
  ];
  for (const html of haystacks) {
    assert.ok(!html.includes('<script>'), `unescaped script tag leaked into: ${html}`);
    assert.match(html, /&lt;script&gt;/);
  }
  // clarificationQuestionText/selectedVariantText are plain text fields --
  // callers must assign them via textContent (never innerHTML), so they are
  // deliberately left un-escaped here; renderMessageRescuePanel below proves
  // that's exactly how they get written.
  assert.equal(model.clarificationQuestionText, evil);
  assert.equal(model.selectedVariantText, evil);
});

// --- renderMessageRescuePanel (plain stub elements, no real DOM) -------------

function makeStubElement() {
  return {
    textContent: '',
    innerHTML: '',
    className: '',
    hidden: false,
    disabled: false,
    _attrs: {},
    setAttribute(k, v) {
      this._attrs[k] = v;
    },
  };
}

function makeStubElements() {
  return {
    contextStatus: makeStubElement(),
    contextPreview: makeStubElement(),
    contextMeta: makeStubElement(),
    contextClearButton: makeStubElement(),
    assessment: makeStubElement(),
    assessmentIntent: makeStubElement(),
    assessmentAmbiguity: makeStubElement(),
    deliveryLabels: makeStubElement(),
    deliveryConfidence: makeStubElement(),
    deliveryEvidence: makeStubElement(),
    clarification: makeStubElement(),
    clarificationQuestion: makeStubElement(),
    clarificationDetails: makeStubElement(),
    variantInputs: {
      faithful: makeStubElement(),
      clearer: makeStubElement(),
      alternate: makeStubElement(),
    },
    variantText: makeStubElement(),
    preservationList: makeStubElement(),
    warnings: makeStubElement(),
    warningsList: makeStubElement(),
  };
}

test('renderMessageRescuePanel: empty state hides clarification/warnings and disables clear', () => {
  const elements = makeStubElements();
  const model = buildMessageRescuePanelModel(formatMessageRescueViewModel(null));
  renderMessageRescuePanel(elements, model);

  assert.equal(elements.contextStatus.textContent, 'No context captured.');
  assert.equal(elements.contextClearButton.disabled, true);
  assert.equal(elements.assessment.hidden, true);
  assert.equal(elements.clarification.hidden, true);
  assert.equal(elements.warnings.hidden, true);
  assert.equal(elements.deliveryConfidence.hidden, true);
  assert.match(elements.variantText.textContent, /No faithful variant available yet\./);
});

test('renderMessageRescuePanel: complete result reveals every optional region and sets tone attribute', () => {
  const elements = makeStubElements();
  const vm = formatMessageRescueViewModel(
    {
      assessment: { intent: 'x', clarification_question: 'Which day?' },
      delivery: { labels: ['rushed'], evidence: ['fast'], confidence: 0.9 },
      variants: { faithful: 'f' },
      preservation_checks: [{ name: 'n', passed: true }],
      warnings: ['w'],
    },
    {},
  );
  renderMessageRescuePanel(elements, buildMessageRescuePanelModel(vm));

  assert.equal(elements.assessment.hidden, false);
  assert.equal(elements.clarification.hidden, false);
  assert.equal(elements.clarificationQuestion.textContent, 'Which day?');
  assert.equal(elements.warnings.hidden, false);
  assert.match(elements.warningsList.innerHTML, /w/);
  assert.equal(elements.deliveryConfidence.hidden, false);
  assert.equal(elements.deliveryConfidence._attrs['data-tone'], 'success');
  assert.equal(elements.variantInputs.faithful.disabled, false);
  assert.equal(elements.variantInputs.clearer.disabled, true);
  assert.equal(elements.variantText.textContent, 'f');
});

// --- buildExampleViewModel ---------------------------------------------------

test('buildExampleViewModel: deterministic synthetic fixture, fully populated, faithful text is a placeholder message', () => {
  const vm = buildExampleViewModel();
  assert.equal(vm.hasResult, true);
  assert.equal(vm.context.active, true);
  assert.equal(vm.variants.find((v) => v.key === 'faithful').available, true);
  assert.equal(vm.warnings.length > 0, true);
  // deterministic: calling it twice gives identical output (fixed `now`)
  assert.deepEqual(vm, buildExampleViewModel());
});

// --- initMessageRescuePanel (fake doc, no real DOM) ---------------------------

function makeFakeDoc(elements) {
  const map = { messageRescuePanel: { ...elements.section } };
  const idMap = {
    messageRescuePanel: elements.section,
    messageRescueContextStatus: elements.contextStatus,
    messageRescueContextPreview: elements.contextPreview,
    messageRescueContextMeta: elements.contextMeta,
    messageRescueClearContextButton: elements.contextClearButton,
    messageRescueAssessment: elements.assessment,
    messageRescueAssessmentIntent: elements.assessmentIntent,
    messageRescueAssessmentAmbiguity: elements.assessmentAmbiguity,
    messageRescueDeliveryLabels: elements.deliveryLabels,
    messageRescueDeliveryConfidence: elements.deliveryConfidence,
    messageRescueDeliveryEvidence: elements.deliveryEvidence,
    messageRescueClarification: elements.clarification,
    messageRescueClarificationQuestion: elements.clarificationQuestion,
    messageRescueClarificationDetails: elements.clarificationDetails,
    messageRescueVariantFaithful: elements.variantInputs.faithful,
    messageRescueVariantClearer: elements.variantInputs.clearer,
    messageRescueVariantAlternate: elements.variantInputs.alternate,
    messageRescueVariantText: elements.variantText,
    messageRescuePreservationList: elements.preservationList,
    messageRescueWarnings: elements.warnings,
    messageRescueWarningsList: elements.warningsList,
  };
  void map;
  return { getElementById: (id) => idMap[id] || null };
}

function makeStubInput() {
  const el = makeStubElement();
  el.checked = false;
  el._listeners = {};
  el.addEventListener = (evt, fn) => {
    el._listeners[evt] = fn;
  };
  return el;
}

function makeInitElements() {
  const elements = makeStubElements();
  elements.section = { ...makeStubElement() };
  elements.contextClearButton.addEventListener = function (evt, fn) {
    this._listeners = this._listeners || {};
    this._listeners[evt] = fn;
  };
  elements.variantInputs.faithful = makeStubInput();
  elements.variantInputs.clearer = makeStubInput();
  elements.variantInputs.alternate = makeStubInput();
  return elements;
}

test('initMessageRescuePanel: flag off leaves the panel hidden and untouched', () => {
  const elements = makeInitElements();
  const doc = makeFakeDoc(elements);
  initMessageRescuePanel({ doc, storage: { getItem: () => null } });

  assert.equal(elements.section.hidden, true);
  assert.equal(elements.section._attrs['aria-hidden'], 'true');
  assert.equal(elements.contextStatus.textContent, '');
});

test('initMessageRescuePanel: missing panel markup in the doc is a safe no-op', () => {
  const doc = { getElementById: () => null };
  assert.doesNotThrow(() => initMessageRescuePanel({ doc, storage: { getItem: () => 'true' } }));
});

test('initMessageRescuePanel: flag on reveals and renders the example, and switching variants is purely local', () => {
  const elements = makeInitElements();
  const doc = makeFakeDoc(elements);
  initMessageRescuePanel({ doc, storage: { getItem: () => 'true' } });

  assert.equal(elements.section.hidden, false);
  assert.equal(elements.section._attrs['aria-hidden'], 'false');
  assert.match(elements.contextStatus.textContent, /^Context active/);
  const faithfulText = elements.variantText.textContent;
  assert.ok(faithfulText.length > 0);

  // Simulate the user picking "clearer" -- purely local re-render, no fetch.
  elements.variantInputs.clearer.checked = true;
  elements.variantInputs.clearer._listeners.change();
  assert.notEqual(elements.variantText.textContent, faithfulText);
  assert.ok(elements.variantText.textContent.length > 0);
});

test('initMessageRescuePanel: the local clear affordance resets the context region without touching anything else', () => {
  const elements = makeInitElements();
  const doc = makeFakeDoc(elements);
  initMessageRescuePanel({ doc, storage: { getItem: () => 'true' } });

  assert.notEqual(elements.contextPreview.textContent, 'Context cleared.');
  elements.contextClearButton._listeners.click();
  assert.equal(elements.contextPreview.textContent, 'Context cleared.');
  assert.equal(elements.contextStatus.textContent, 'No context captured.');
  assert.equal(elements.contextClearButton.disabled, true);
});
