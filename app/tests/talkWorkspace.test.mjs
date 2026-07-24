// Unit tests for the Talk workspace wiring adapter's PURE helpers
// (docs/ui/SIGNAL_DESK_SPEC.md section 4). Not part of the director's
// required test list (signalCore.test.mjs / signalDeskShell.test.mjs) --
// added as a bonus since these are cheap, DOM-free pure functions that
// isolate the "draft -> view" and "voice-status -> ring" mapping logic
// exercised by createTalkWorkspaceFeature().
//
// Run with: node --test app/tests/talkWorkspace.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  interpretVoiceStatus,
  mapConfidenceBand,
  formatConfidencePercent,
  confidenceBandToCssVar,
  amplitudeToApproxDb,
  dbToMeterPercent,
  deriveRefinedViewModel,
  TALK_ELEMENT_IDS,
  collectTalkElements,
  createTalkWorkspaceFeature,
} from '../src/renderer/features/talkWorkspace.js';

// --- interpretVoiceStatus ----------------------------------------------------

test('interpretVoiceStatus: recording carries amplitude through when numeric', () => {
  const result = interpretVoiceStatus('recording', { amplitude: 0.42 });
  assert.equal(result.ringState, 'recording');
  assert.equal(result.amplitude, 0.42);
});

test('interpretVoiceStatus: recording with no amplitude field yields null amplitude', () => {
  const result = interpretVoiceStatus('recording', {});
  assert.equal(result.amplitude, null);
});

test('interpretVoiceStatus: preview_ready maps to ready state', () => {
  assert.equal(interpretVoiceStatus('preview_ready', {}).ringState, 'ready');
});

test('interpretVoiceStatus: draft_blocked/draft_error map to error state', () => {
  assert.equal(interpretVoiceStatus('draft_blocked', {}).ringState, 'error');
  assert.equal(interpretVoiceStatus('draft_error', {}).ringState, 'error');
});

test('interpretVoiceStatus: draft_sent with fallback=true is treated as an error/fallback state', () => {
  assert.equal(interpretVoiceStatus('draft_sent', { fallback: true }).ringState, 'error');
  assert.equal(interpretVoiceStatus('draft_sent', {}).ringState, 'ready');
});

test('interpretVoiceStatus: unknown status falls back to idle without throwing', () => {
  assert.equal(interpretVoiceStatus('some_future_status', {}).ringState, 'idle');
  assert.equal(interpretVoiceStatus(undefined, {}).ringState, 'idle');
});

// --- confidence mapping -------------------------------------------------------

test('formatConfidencePercent: converts 0..1 score to an integer percent', () => {
  assert.equal(formatConfidencePercent(0.94), 94);
  assert.equal(formatConfidencePercent(0), 0);
  assert.equal(formatConfidencePercent(1), 100);
});

test('formatConfidencePercent: missing/NaN score returns null', () => {
  assert.equal(formatConfidencePercent(null), null);
  assert.equal(formatConfidencePercent(undefined), null);
  assert.equal(formatConfidencePercent(NaN), null);
});

test('mapConfidenceBand: >=85 is always high', () => {
  assert.equal(mapConfidenceBand(0.9, 'pending'), 'high');
  assert.equal(mapConfidenceBand(0.9, 'sent'), 'high');
});

test('mapConfidenceBand: 70-84 is draft(blue) while pending, high(green) once sent', () => {
  assert.equal(mapConfidenceBand(0.75, 'pending'), 'draft');
  assert.equal(mapConfidenceBand(0.75, 'sent'), 'high');
});

test('mapConfidenceBand: 60-69 is mid regardless of status', () => {
  assert.equal(mapConfidenceBand(0.65, 'pending'), 'mid');
  assert.equal(mapConfidenceBand(0.65, 'sent'), 'mid');
});

test('mapConfidenceBand: below 60 is low', () => {
  assert.equal(mapConfidenceBand(0.4, 'pending'), 'low');
});

test('confidenceBandToCssVar: known bands map to their signal-desk.css var()', () => {
  assert.equal(confidenceBandToCssVar('high'), 'var(--sd-confidence-high)');
  assert.equal(confidenceBandToCssVar('draft'), 'var(--sd-confidence-draft)');
  assert.equal(confidenceBandToCssVar('mid'), 'var(--sd-confidence-mid)');
  assert.equal(confidenceBandToCssVar('low'), 'var(--sd-confidence-low)');
  assert.equal(confidenceBandToCssVar('unknown'), 'var(--sd-confidence-high)');
});

// --- dB meter mapping ----------------------------------------------------------

test('amplitudeToApproxDb: amplitude 1 is ~0 dB, amplitude 0 clamps to the floor', () => {
  assert.ok(Math.abs(amplitudeToApproxDb(1) - 0) < 1e-6);
  assert.equal(amplitudeToApproxDb(0, -60), -60);
});

test('dbToMeterPercent: floor -> 0%, ceiling -> 100%', () => {
  assert.equal(dbToMeterPercent(-60, -60, 0), 0);
  assert.equal(dbToMeterPercent(0, -60, 0), 100);
});

// --- deriveRefinedViewModel ------------------------------------------------------

test('deriveRefinedViewModel: null draft yields the empty/waiting view model', () => {
  const vm = deriveRefinedViewModel(null);
  assert.equal(vm.hasDraft, false);
  assert.equal(vm.badgeVariant, 'pending');
  assert.equal(vm.confidencePct, null);
});

test('deriveRefinedViewModel: pending draft with high confidence reads Ready/high', () => {
  const vm = deriveRefinedViewModel({
    status: 'pending',
    final_text: 'I should be there around six.',
    raw_text: 'i should be there around six',
    confidence: { score: 0.94 },
  });
  assert.equal(vm.hasDraft, true);
  assert.equal(vm.hero, 'I should be there around six.');
  assert.equal(vm.badgeText, 'Ready');
  assert.equal(vm.badgeVariant, 'ready');
  assert.equal(vm.confidencePct, 94);
  assert.equal(vm.confidenceBand, 'high');
});

test('deriveRefinedViewModel: blocked/error draft reads Needs Review/error', () => {
  const vm = deriveRefinedViewModel({ status: 'blocked', raw_text: 'raw text', error: 'blocked reason' });
  assert.equal(vm.badgeText, 'Needs Review');
  assert.equal(vm.badgeVariant, 'error');
});

test('deriveRefinedViewModel: falls back to raw_text when final_text is empty', () => {
  const vm = deriveRefinedViewModel({ status: 'pending', final_text: '', raw_text: 'raw only' });
  assert.equal(vm.hero, 'raw only');
});

// --- collectTalkElements -----------------------------------------------------------

test('collectTalkElements: every TALK_ELEMENT_IDS key is present, resolving missing ids to null', () => {
  const fakeDoc = { getElementById: () => null };
  const els = collectTalkElements(fakeDoc);
  for (const key of Object.keys(TALK_ELEMENT_IDS)) {
    assert.ok(key in els);
    assert.equal(els[key], null);
  }
});

test('collectTalkElements: resolves whatever the stub document returns for a given id', () => {
  const sentinel = { id: 'sentinel' };
  const fakeDoc = { getElementById: (id) => (id === TALK_ELEMENT_IDS.refinedHero ? sentinel : null) };
  const els = collectTalkElements(fakeDoc);
  assert.equal(els.refinedHero, sentinel);
  assert.equal(els.rawTranscriptText, null);
});

// --- createTalkWorkspaceFeature: DOM-wiring smoke tests (stub elements) -----------

function makeClassList() {
  const set = new Set();
  return {
    add: (...c) => c.forEach((x) => set.add(x)),
    remove: (...c) => c.forEach((x) => set.delete(x)),
    toggle(c, force) {
      if (force === undefined) {
        if (set.has(c)) { set.delete(c); return false; }
        set.add(c); return true;
      }
      if (force) { set.add(c); return true; }
      set.delete(c); return false;
    },
    contains: (c) => set.has(c),
  };
}

function makeButton() {
  const listeners = {};
  return {
    disabled: false,
    classList: makeClassList(),
    addEventListener(evt, fn) { listeners[evt] = fn; },
    click() { listeners.click?.(); },
  };
}

test('createTalkWorkspaceFeature: init() with no elements/hooks never throws (fully optional-chained)', () => {
  const feature = createTalkWorkspaceFeature({});
  assert.doesNotThrow(() => feature.init());
  assert.doesNotThrow(() => feature.handleVoiceStatusMessage({ status: 'recording', amplitude: 0.5 }));
  assert.doesNotThrow(() => feature.renderRefinedCard(null));
  assert.doesNotThrow(() => feature.destroy());
});

test('createTalkWorkspaceFeature: renderRefinedCard writes hero/badge/confidence into stub elements', () => {
  const els = {
    refinedHero: { textContent: '' },
    refinedBadge: { classList: makeClassList(), textContent: '' },
    rawTranscriptText: { textContent: '' },
    confidenceValue: { textContent: '', style: { setProperty() {} } },
    confidenceBarFill: { style: { width: '', setProperty() {} } },
  };
  const feature = createTalkWorkspaceFeature({ elements: els });
  feature.renderRefinedCard({
    status: 'pending',
    final_text: 'Hello there.',
    raw_text: 'hello there',
    confidence: { score: 0.94 },
  });
  assert.equal(els.refinedHero.textContent, 'Hello there.');
  assert.equal(els.confidenceValue.textContent, '94%');
  assert.equal(els.confidenceBarFill.style.width, '94%');
  assert.ok(els.refinedBadge.classList.contains('sd-badge--ready'));
});

test('createTalkWorkspaceFeature: Send button click calls hooks.drafts.handleSendClick and re-renders', async () => {
  let sendCalled = 0;
  let latest = { status: 'pending', final_text: 'sent text', raw_text: 'raw', confidence: { score: 0.9 } };
  const els = {
    sendButton: makeButton(),
    refinedHero: { textContent: '' },
    refinedBadge: { classList: makeClassList() },
    rawTranscriptText: { textContent: '' },
    confidenceValue: { textContent: '', style: { setProperty() {} } },
    confidenceBarFill: { style: { width: '', setProperty() {} } },
  };
  const hooks = {
    drafts: {
      handleSendClick: async () => { sendCalled += 1; },
      getLatestDraft: () => latest,
    },
  };
  const feature = createTalkWorkspaceFeature({ elements: els, hooks });
  feature.init();
  els.sendButton.click();
  // handleSendClick is async; flush microtasks.
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(sendCalled, 1);
  assert.equal(els.refinedHero.textContent, 'sent text');
});

test('createTalkWorkspaceFeature: Revise click without hooks.onReviseRequested does not throw', () => {
  const els = { reviseButton: makeButton() };
  const feature = createTalkWorkspaceFeature({ elements: els, hooks: {} });
  feature.init();
  assert.doesNotThrow(() => els.reviseButton.click());
});

test('createTalkWorkspaceFeature: mountSignalCore is safe with no signalCoreContainer/Ring elements', () => {
  const feature = createTalkWorkspaceFeature({ elements: {} });
  const ring = feature.mountSignalCore();
  assert.equal(typeof ring.setState, 'function');
  assert.doesNotThrow(() => ring.destroy());
});
