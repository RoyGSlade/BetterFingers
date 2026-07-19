// Unit tests for the pure Message Rescue view-model module (Phase 2, F2.3).
// Run with: node --test app/tests/messageRescue.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  formatAssessmentSummary,
  formatClarification,
  formatContextStatus,
  formatDeliverySignals,
  formatMessageRescueViewModel,
  formatPreservationChecks,
  formatSpeechSignals,
  formatVariants,
  formatWarnings,
} from '../src/renderer/features/messageRescue.js';

// --- formatContextStatus ----------------------------------------------------

test('formatContextStatus: null/undefined context', () => {
  for (const value of [null, undefined]) {
    const status = formatContextStatus(value, 1000);
    assert.equal(status.active, false);
    assert.equal(status.expired, false);
    assert.equal(status.exhausted, false);
    assert.equal(status.statusLabel, 'No context captured.');
    assert.equal(status.preview, '');
    assert.equal(status.sourceLabel, '');
    assert.equal(status.usesLabel, '');
  }
});

test('formatContextStatus: active with expiry countdown and known source label', () => {
  const context = {
    id: 'ctx-1', text: 'full text', source: 'selection',
    captured_at: 900, expires_at: 1030, use_count: 0, max_uses: 1,
    visible_preview: 'full…',
  };
  const status = formatContextStatus(context, 1000);
  assert.equal(status.active, true);
  assert.equal(status.expired, false);
  assert.equal(status.exhausted, false);
  assert.equal(status.statusLabel, 'Context active · expires in 30s');
  assert.equal(status.sourceLabel, 'from selection');
  assert.equal(status.usesLabel, '0/1 uses');
  assert.equal(status.preview, 'full…');
});

test('formatContextStatus: expired takes precedence over exhausted', () => {
  const status = formatContextStatus(
    { text: 't', source: 'manual', expires_at: 500, use_count: 0, max_uses: 3 },
    1000,
  );
  assert.equal(status.expired, true);
  assert.equal(status.active, false);
  assert.equal(status.statusLabel, 'Context expired.');
});

test('formatContextStatus: exhausted (use_count >= max_uses) while not expired', () => {
  const status = formatContextStatus(
    { text: 't', source: 'clipboard_fallback', expires_at: 2000, use_count: 2, max_uses: 2 },
    1000,
  );
  assert.equal(status.expired, false);
  assert.equal(status.exhausted, true);
  assert.equal(status.active, false);
  assert.equal(status.statusLabel, 'Context already used.');
  assert.equal(status.sourceLabel, 'from clipboard');
});

test('formatContextStatus: missing visible_preview falls back to raw text', () => {
  const status = formatContextStatus({ text: 'raw fallback text', source: 'manual', expires_at: 2000 }, 1000);
  assert.equal(status.preview, 'raw fallback text');
});

test('formatContextStatus: unknown source falls back to raw value, no expiry omits countdown', () => {
  const status = formatContextStatus({ text: 't', source: 'weird_source' }, 1000);
  assert.equal(status.sourceLabel, 'weird_source');
  assert.equal(status.statusLabel, 'Context active.');
});

test('formatContextStatus: special characters in preview pass through unescaped (raw)', () => {
  const dangerous = '<script>alert(1)</script> & "quotes" \'apostrophes\'';
  const status = formatContextStatus({ text: dangerous, source: 'manual', expires_at: 2000 }, 1000);
  assert.equal(status.preview, dangerous);
});

test('formatContextStatus: malformed expires_at/use_count are treated as absent', () => {
  const status = formatContextStatus({ text: 't', source: 'manual', expires_at: 'soon', use_count: 'many', max_uses: 1 }, 1000);
  assert.equal(status.statusLabel, 'Context active.');
  assert.equal(status.usesLabel, '0/1 uses');
});

// --- formatSpeechSignals -----------------------------------------------------

test('formatSpeechSignals: null/empty signals', () => {
  for (const value of [null, undefined, {}]) {
    const formatted = formatSpeechSignals(value);
    assert.deepEqual(formatted.axisLabels, []);
    assert.deepEqual(formatted.evidence, []);
  }
  assert.equal(formatSpeechSignals(null).hasSignals, false);
  assert.equal(formatSpeechSignals({}).hasSignals, true);
});

test('formatSpeechSignals: partial axes only render present numeric axes', () => {
  const formatted = formatSpeechSignals({ delivery_axes: { arousal: 0.5, hesitation: 'bad' } });
  assert.deepEqual(formatted.axisLabels, ['Energy: 50%']);
});

test('formatSpeechSignals: full axes at boundaries 0 and 1', () => {
  const formatted = formatSpeechSignals({ delivery_axes: { arousal: 0, urgency: 1, hesitation: 0.5 } });
  assert.deepEqual(formatted.axisLabels, ['Energy: 0%', 'Urgency: 100%', 'Hesitation: 50%']);
});

test('formatSpeechSignals: evidence filters non-string entries, confidence tone thresholds', () => {
  const formatted = formatSpeechSignals({ evidence: ['142 wpm', 42, null, ''], confidence: 0.7 });
  assert.deepEqual(formatted.evidence, ['142 wpm']);
  assert.equal(formatted.confidenceLabel, '70%');
  assert.equal(formatted.confidenceTone, 'success');

  assert.equal(formatSpeechSignals({ confidence: 0.5 }).confidenceTone, 'warning');
  assert.equal(formatSpeechSignals({ confidence: 0.1 }).confidenceTone, 'danger');
  assert.equal(formatSpeechSignals({ confidence: undefined }).confidenceLabel, '0%');
});

// --- formatAssessmentSummary / formatClarification ---------------------------

test('formatAssessmentSummary: null/empty assessment', () => {
  assert.deepEqual(formatAssessmentSummary(null), { intent: '', ambiguityRisk: '' });
  assert.deepEqual(formatAssessmentSummary({}), { intent: '', ambiguityRisk: '' });
});

test('formatAssessmentSummary: string ambiguity_risk passes through raw', () => {
  const summary = formatAssessmentSummary({ intent: 'ask a favor', ambiguity_risk: 'high' });
  assert.equal(summary.intent, 'ask a favor');
  assert.equal(summary.ambiguityRisk, 'high');
});

test('formatAssessmentSummary: numeric ambiguity_risk formats as percentage', () => {
  assert.equal(formatAssessmentSummary({ ambiguity_risk: 0.33 }).ambiguityRisk, '33%');
});

test('formatAssessmentSummary: malformed ambiguity_risk yields empty string, not a guess', () => {
  assert.equal(formatAssessmentSummary({ ambiguity_risk: {} }).ambiguityRisk, '');
  assert.equal(formatAssessmentSummary({ ambiguity_risk: null }).ambiguityRisk, '');
});

test('formatClarification: absent assessment or missing question is null', () => {
  assert.equal(formatClarification(null), null);
  assert.equal(formatClarification({}), null);
  assert.equal(formatClarification({ clarification_question: '' }), null);
  assert.equal(formatClarification({ clarification_question: '   ' }), null);
});

test('formatClarification: present question with special characters and missing_details filtering', () => {
  const clarification = formatClarification({
    clarification_question: 'Which "Friday" — this week or next? <b>bold</b>',
    missing_details: ['date', 42, null, 'recipient'],
  });
  assert.deepEqual(clarification, {
    question: 'Which "Friday" — this week or next? <b>bold</b>',
    missingDetails: ['date', 'recipient'],
  });
});

// --- formatDeliverySignals ----------------------------------------------------

test('formatDeliverySignals: null/malformed delivery', () => {
  const formatted = formatDeliverySignals(null);
  assert.deepEqual(formatted.labels, []);
  assert.deepEqual(formatted.evidence, []);
  assert.equal(formatted.confidenceLabel, '');
  assert.equal(formatted.confidenceTone, 'danger');
});

test('formatDeliverySignals: filters non-string labels/evidence entries', () => {
  const formatted = formatDeliverySignals({ labels: ['urgent', 7, null], evidence: ['fast pace', {}], confidence: 0.9 });
  assert.deepEqual(formatted.labels, ['urgent']);
  assert.deepEqual(formatted.evidence, ['fast pace']);
  assert.equal(formatted.confidenceLabel, '90%');
  assert.equal(formatted.confidenceTone, 'success');
});

// --- formatVariants ------------------------------------------------------------

test('formatVariants: null/empty variants — all three slots present but unavailable', () => {
  for (const value of [null, undefined, {}]) {
    const variants = formatVariants(value);
    assert.equal(variants.length, 3);
    assert.deepEqual(variants.map((v) => v.key), ['faithful', 'clearer', 'alternate']);
    for (const v of variants) {
      assert.equal(v.text, '');
      assert.equal(v.available, false);
    }
  }
});

test('formatVariants: only faithful present (parse-failure fallback shape) never invents the others', () => {
  const variants = formatVariants({ faithful: 'original raw transcript' });
  const byKey = Object.fromEntries(variants.map((v) => [v.key, v]));
  assert.equal(byKey.faithful.text, 'original raw transcript');
  assert.equal(byKey.faithful.available, true);
  assert.equal(byKey.clearer.available, false);
  assert.equal(byKey.alternate.available, false);
});

test('formatVariants: all three present, non-string values ignored rather than stringified', () => {
  const variants = formatVariants({ faithful: 'f', clearer: 'c', alternate: 123 });
  const byKey = Object.fromEntries(variants.map((v) => [v.key, v]));
  assert.equal(byKey.faithful.text, 'f');
  assert.equal(byKey.clearer.text, 'c');
  assert.equal(byKey.alternate.text, '');
  assert.equal(byKey.alternate.available, false);
});

// --- formatPreservationChecks / formatWarnings ----------------------------------

test('formatPreservationChecks: non-array input is treated as empty/passed', () => {
  for (const value of [null, undefined, 'oops', 42]) {
    assert.deepEqual(formatPreservationChecks(value), { items: [], allPassed: true, failedCount: 0 });
  }
});

test('formatPreservationChecks: mixed pass/fail with ok/passed key fallback and malformed entries dropped', () => {
  const result = formatPreservationChecks([
    { name: 'names_preserved', passed: true },
    { check: 'numbers_preserved', ok: false, detail: 'dropped "42"' },
    { passed: true },
    'not an object',
    null,
  ]);
  assert.equal(result.items.length, 3);
  assert.equal(result.items[0].name, 'names_preserved');
  assert.equal(result.items[0].passed, true);
  assert.equal(result.items[1].name, 'numbers_preserved');
  assert.equal(result.items[1].passed, false);
  assert.equal(result.items[1].detail, 'dropped "42"');
  assert.equal(result.items[2].name, 'check');
  assert.equal(result.allPassed, false);
  assert.equal(result.failedCount, 1);
});

test('formatPreservationChecks: malformed entry with no passed/ok field defaults to failed, not passed', () => {
  const result = formatPreservationChecks([{ name: 'unknown_state' }]);
  assert.equal(result.items[0].passed, false);
  assert.equal(result.allPassed, false);
  assert.equal(result.failedCount, 1);
});

test('formatWarnings: non-array and mixed-type entries', () => {
  assert.deepEqual(formatWarnings(null), []);
  assert.deepEqual(formatWarnings('not an array'), []);
  assert.deepEqual(formatWarnings(['parse_error: fallback to faithful', 7, null, 'preservation violated: "42" dropped']), [
    'parse_error: fallback to faithful',
    'preservation violated: "42" dropped',
  ]);
});

// --- formatMessageRescueViewModel (composite) -----------------------------------

test('formatMessageRescueViewModel: empty payload — stable, fully-populated shape', () => {
  const vm = formatMessageRescueViewModel(null);
  assert.equal(vm.hasResult, false);
  assert.equal(vm.context.active, false);
  assert.equal(vm.signals.hasSignals, false);
  assert.deepEqual(vm.assessment, { intent: '', ambiguityRisk: '' });
  assert.equal(vm.clarification, null);
  assert.deepEqual(vm.delivery.labels, []);
  assert.equal(vm.variants.length, 3);
  assert.equal(vm.preservation.allPassed, true);
  assert.deepEqual(vm.warnings, []);
});

test('formatMessageRescueViewModel: partial payload (assessment only) does not throw and leaves the rest empty', () => {
  const vm = formatMessageRescueViewModel({ assessment: { intent: 'reschedule' } });
  assert.equal(vm.hasResult, true);
  assert.equal(vm.assessment.intent, 'reschedule');
  assert.equal(vm.clarification, null);
  assert.deepEqual(vm.variants.map((v) => v.available), [false, false, false]);
});

test('formatMessageRescueViewModel: malformed payload (wrong field types) degrades safely', () => {
  const vm = formatMessageRescueViewModel({
    assessment: 'not an object',
    delivery: null,
    variants: 'not an object either',
    preservation_checks: { not: 'an array' },
    warnings: { also: 'not an array' },
  });
  assert.equal(vm.hasResult, true);
  assert.deepEqual(vm.assessment, { intent: '', ambiguityRisk: '' });
  assert.equal(vm.clarification, null);
  assert.deepEqual(vm.delivery.labels, []);
  assert.equal(vm.variants.length, 3);
  assert.equal(vm.preservation.allPassed, true);
  assert.deepEqual(vm.warnings, []);
});

test('formatMessageRescueViewModel: error/parse-failure fallback shape (only faithful + warning)', () => {
  const vm = formatMessageRescueViewModel({
    assessment: {},
    delivery: {},
    variants: { faithful: 'the original dictated text, unmodified' },
    preservation_checks: [],
    warnings: ['parse_error: model output did not parse, fell back to faithful transcript'],
  });
  const byKey = Object.fromEntries(vm.variants.map((v) => [v.key, v]));
  assert.equal(byKey.faithful.available, true);
  assert.equal(byKey.faithful.text, 'the original dictated text, unmodified');
  assert.equal(byKey.clearer.available, false);
  assert.equal(byKey.alternate.available, false);
  assert.deepEqual(vm.warnings, ['parse_error: model output did not parse, fell back to faithful transcript']);
});

test('formatMessageRescueViewModel: low-confidence complete payload', () => {
  const vm = formatMessageRescueViewModel(
    {
      assessment: {
        intent: 'apologize', ambiguity_risk: 0.8,
        missing_details: ['who this is for'], clarification_question: 'Who is this message for?',
      },
      delivery: { labels: ['hesitant', 'quiet'], confidence: 0.2, evidence: ['long pauses', 'low energy'] },
      variants: { faithful: 'faithful text', clearer: 'clearer text', alternate: 'alternate text' },
      preservation_checks: [{ name: 'tone_preserved', passed: true }],
      warnings: ['low_confidence_delivery_signal'],
    },
    {
      context: { text: 'ctx', source: 'selection', expires_at: 2000, use_count: 0, max_uses: 1, visible_preview: 'ctx…' },
      signals: { delivery_axes: { arousal: 0.1, urgency: 0.1, hesitation: 0.9 }, confidence: 0.3, evidence: ['142 wpm'] },
      now: 1000,
    },
  );

  assert.equal(vm.hasResult, true);
  assert.equal(vm.context.active, true);
  assert.equal(vm.signals.confidenceTone, 'danger');
  assert.equal(vm.assessment.ambiguityRisk, '80%');
  assert.deepEqual(vm.clarification, { question: 'Who is this message for?', missingDetails: ['who this is for'] });
  assert.equal(vm.delivery.confidenceTone, 'danger');
  assert.equal(vm.variants.every((v) => v.available), true);
  assert.equal(vm.preservation.allPassed, true);
  assert.deepEqual(vm.warnings, ['low_confidence_delivery_signal']);
});

test('formatMessageRescueViewModel: complete happy-path payload matching every frozen contract field', () => {
  const vm = formatMessageRescueViewModel(
    {
      assessment: {
        intent: 'confirm plans', ambiguity_risk: 'low',
        missing_details: [], clarification_question: '',
      },
      delivery: { labels: ['confident', 'brisk'], confidence: 0.9, evidence: ['steady pace'] },
      variants: { faithful: 'f', clearer: 'c', alternate: 'a' },
      preservation_checks: [
        { name: 'names_preserved', passed: true },
        { name: 'numbers_preserved', passed: true },
      ],
      warnings: [],
    },
    {
      context: { id: 'c1', text: 'full', source: 'manual', captured_at: 900, expires_at: 1300, use_count: 0, max_uses: 2, visible_preview: 'full' },
      signals: {
        words_per_minute: 150, speaking_ratio: 0.8, pause_count: 2, pause_ratio: 0.1,
        mean_pause_s: 0.4, longest_pause_s: 1.2, filler_count: 0, self_correction_count: 0,
        energy_mean: 0.6, energy_variation: 0.1,
        delivery_axes: { arousal: 0.6, urgency: 0.5, hesitation: 0.1 },
        evidence: ['steady pace', '150 wpm'], confidence: 0.85,
      },
      now: 1000,
    },
  );

  assert.equal(vm.hasResult, true);
  assert.equal(vm.context.usesLabel, '0/2 uses');
  assert.equal(vm.signals.axisLabels.length, 3);
  assert.equal(vm.assessment.ambiguityRisk, 'low');
  assert.equal(vm.clarification, null);
  assert.deepEqual(vm.delivery.labels, ['confident', 'brisk']);
  assert.equal(vm.preservation.allPassed, true);
  assert.equal(vm.preservation.failedCount, 0);
  assert.deepEqual(vm.warnings, []);
});
