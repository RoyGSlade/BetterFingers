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
  DELIVERY_OPTIONS,
  deliveryOptionToSendAction,
  resolveSendAction,
  primaryActionLabel,
  activeDeliverySegment,
  deriveSendResultViewModel,
  deriveConfidenceThresholdSummary,
  deriveForceReviewNotice,
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

test('formatConfidencePercent: out-of-contract percentage values stay unknown', () => {
  assert.equal(formatConfidencePercent(35), null);
  assert.equal(formatConfidencePercent(-0.1), null);
  assert.equal(formatConfidencePercent(1.1), null);
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

// --- deliveryOptionToSendAction / resolveSendAction --------------------------------

test('deliveryOptionToSendAction: maps the three segmented options to the backend vocabulary', () => {
  assert.equal(deliveryOptionToSendAction('type'), 'type');
  assert.equal(deliveryOptionToSendAction('paste'), 'paste');
  assert.equal(deliveryOptionToSendAction('copy'), 'copy_only');
});

test('deliveryOptionToSendAction: unrecognised option maps to null', () => {
  assert.equal(deliveryOptionToSendAction('send'), null);
  assert.equal(deliveryOptionToSendAction(undefined), null);
});

test('resolveSendAction: no explicit selection reproduces the profile-derived default (no settings => copy_only)', () => {
  assert.equal(resolveSendAction(null, null), 'copy_only');
});

test('resolveSendAction: no selection, injection unsupported => copy_only', () => {
  const settings = { send_mode: 'review_first', capabilities: { supports_input_injection: false } };
  assert.equal(resolveSendAction(null, settings), 'copy_only');
});

test('resolveSendAction: no selection, auto_send + injection supported => open_chat_then_send', () => {
  const settings = { send_mode: 'auto_send', capabilities: { supports_input_injection: true } };
  assert.equal(resolveSendAction(null, settings), 'open_chat_then_send');
});

test('resolveSendAction: no selection, review_first + injection supported => paste', () => {
  const settings = { send_mode: 'review_first', capabilities: { supports_input_injection: true } };
  assert.equal(resolveSendAction(null, settings), 'paste');
});

test('resolveSendAction: explicit "copy" always wins regardless of injection support', () => {
  assert.equal(resolveSendAction('copy', { capabilities: { supports_input_injection: true } }), 'copy_only');
  assert.equal(resolveSendAction('copy', null), 'copy_only');
});

test('resolveSendAction: explicit type/paste pass through when injection is supported', () => {
  const settings = { capabilities: { supports_input_injection: true } };
  assert.equal(resolveSendAction('type', settings), 'type');
  assert.equal(resolveSendAction('paste', settings), 'paste');
});

test('resolveSendAction: explicit type/paste degrade to copy_only when injection is unsupported', () => {
  const settings = { capabilities: { supports_input_injection: false } };
  assert.equal(resolveSendAction('type', settings), 'copy_only');
  assert.equal(resolveSendAction('paste', settings), 'copy_only');
});

// --- primaryActionLabel -------------------------------------------------------------

test('primaryActionLabel: names the real action for each explicit selection when injection is supported', () => {
  const settings = { capabilities: { supports_input_injection: true } };
  assert.equal(primaryActionLabel('type', settings), 'Type at Cursor');
  assert.equal(primaryActionLabel('paste', settings), 'Paste at Cursor');
  assert.equal(primaryActionLabel('copy', settings), 'Copy to Clipboard');
});

test('primaryActionLabel: visibly names the degradation when type/paste is selected but injection is unavailable', () => {
  const settings = { capabilities: { supports_input_injection: false } };
  assert.equal(primaryActionLabel('type', settings), 'Copy to Clipboard (injection unavailable)');
  assert.equal(primaryActionLabel('paste', settings), 'Copy to Clipboard (injection unavailable)');
});

test('primaryActionLabel: changes when the segmented selection changes', () => {
  const settings = { capabilities: { supports_input_injection: true } };
  const typeLabel = primaryActionLabel('type', settings);
  const pasteLabel = primaryActionLabel('paste', settings);
  const copyLabel = primaryActionLabel('copy', settings);
  assert.notEqual(typeLabel, pasteLabel);
  assert.notEqual(pasteLabel, copyLabel);
  assert.notEqual(typeLabel, copyLabel);
});

test('primaryActionLabel: no selection falls back to the profile-derived default label', () => {
  assert.equal(primaryActionLabel(null, null), 'Copy to Clipboard');
  assert.equal(primaryActionLabel(null, { send_mode: 'auto_send', capabilities: { supports_input_injection: true } }), 'Send to Chat');
  assert.equal(primaryActionLabel(null, { send_mode: 'review_first', capabilities: { supports_input_injection: true } }), 'Paste at Cursor');
});

// --- deriveSendResultViewModel -------------------------------------------------------

test('deriveSendResultViewModel: no send_result yields hasResult=false but still derives submissionState', () => {
  const vm = deriveSendResultViewModel(null, { status: 'pending' });
  assert.equal(vm.hasResult, false);
  assert.equal(vm.submissionState, 'not submitted');
  assert.equal(vm.clipboardState, 'not used');
});

test('deriveSendResultViewModel: clipboard_result null reads "not used"', () => {
  const vm = deriveSendResultViewModel({ requested_action: 'type', actual_action: 'type', clipboard_result: null }, { status: 'sent' });
  assert.equal(vm.clipboardState, 'not used');
});

test('deriveSendResultViewModel: clipboard_result ok:true reads "text copied"', () => {
  const vm = deriveSendResultViewModel({ clipboard_result: { ok: true } }, {});
  assert.equal(vm.clipboardState, 'text copied');
});

test('deriveSendResultViewModel: clipboard_result ok:false surfaces the failure message', () => {
  const vm = deriveSendResultViewModel({ clipboard_result: { ok: false, message: 'clipboard locked' } }, {});
  assert.equal(vm.clipboardState, 'copy failed: clipboard locked');
});

test('deriveSendResultViewModel: known fallback_reason maps to human text', () => {
  const vm = deriveSendResultViewModel({ fallback: true, fallback_reason: 'input_injection_unsupported' }, {});
  assert.equal(vm.fallbackUsed, true);
  assert.equal(vm.fallbackReasonText, 'Input injection unavailable on this system');
});

test('deriveSendResultViewModel: an unrecognised fallback_reason passes through verbatim, never swallowed', () => {
  const vm = deriveSendResultViewModel({ fallback: true, fallback_reason: 'some_future_reason' }, {});
  assert.equal(vm.fallbackReason, 'some_future_reason');
  assert.equal(vm.fallbackReasonText, 'some_future_reason');
});

test('deriveSendResultViewModel: submissionState reflects sent/failed/interrupted from the draft', () => {
  assert.equal(deriveSendResultViewModel({}, { status: 'sent' }).submissionState, 'sent');
  assert.equal(deriveSendResultViewModel({}, { status: 'send_error' }).submissionState, 'send failed');
  assert.equal(deriveSendResultViewModel({}, { status: 'send_interrupted' }).submissionState, 'interrupted — outcome unknown');
});

test('deriveSendResultViewModel: submissionState also reads send_outcome when status is absent', () => {
  assert.equal(deriveSendResultViewModel({}, { send_outcome: 'interrupted' }).submissionState, 'interrupted — outcome unknown');
});

test('deriveSendResultViewModel: requested/actual/ok/message pass through from the raw send_result', () => {
  const sendResult = { requested_action: 'paste', actual_action: 'copy_only', ok: false, message: 'Copied as fallback.' };
  const vm = deriveSendResultViewModel(sendResult, { status: 'sent' });
  assert.equal(vm.hasResult, true);
  assert.equal(vm.requested, 'paste');
  assert.equal(vm.actual, 'copy_only');
  assert.equal(vm.ok, false);
  assert.equal(vm.message, 'Copied as fallback.');
});

// --- deriveConfidenceThresholdSummary -------------------------------------------------

test('deriveConfidenceThresholdSummary: missing settings returns null (honest empty state)', () => {
  assert.equal(deriveConfidenceThresholdSummary(null), null);
  assert.equal(deriveConfidenceThresholdSummary(undefined), null);
  assert.equal(deriveConfidenceThresholdSummary({}), null);
});

test('deriveConfidenceThresholdSummary: gate disabled reads "Confidence gate off"', () => {
  const summary = deriveConfidenceThresholdSummary({ confidence_force_review_enabled: false });
  assert.equal(summary, 'Confidence gate off');
});

test('deriveConfidenceThresholdSummary: enabled with thresholds renders both percentages', () => {
  const summary = deriveConfidenceThresholdSummary({
    confidence_force_review_enabled: true,
    confidence_force_review_below: 0.55,
    confidence_auto_send_above: 0.85,
  });
  assert.equal(summary, 'Review below 55% · auto-send above 85%');
});

test('deriveConfidenceThresholdSummary: enabled but thresholds missing still returns null rather than fabricating numbers', () => {
  const summary = deriveConfidenceThresholdSummary({ confidence_force_review_enabled: true });
  assert.equal(summary, null);
});

// --- deriveForceReviewNotice ---------------------------------------------------------

test('deriveForceReviewNotice: force_review=false yields null', () => {
  assert.equal(deriveForceReviewNotice({ force_review: false, force_review_reason: 'low_confidence' }), null);
  assert.equal(deriveForceReviewNotice(null), null);
});

test('deriveForceReviewNotice: known reasons surface their own text without inventing gate logic', () => {
  const notice = deriveForceReviewNotice({ force_review: true, force_review_reason: 'low_confidence' });
  assert.equal(notice.reason, 'low_confidence');
  assert.match(notice.text, /below the review threshold/);
});

test('deriveForceReviewNotice: an unrecognised reason is still surfaced verbatim via .reason', () => {
  const notice = deriveForceReviewNotice({ force_review: true, force_review_reason: 'future_reason' });
  assert.equal(notice.reason, 'future_reason');
  assert.match(notice.text, /future_reason/);
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
    attrs: {},
    setAttribute(name, value) { this.attrs[name] = value; },
    getAttribute(name) { return Object.hasOwn(this.attrs, name) ? this.attrs[name] : null; },
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

// --- createTalkWorkspaceFeature: delivery segmented / send action ----------------

function makeSegmentedContainer(optionNames) {
  const buttons = optionNames.map((name) => {
    const btn = makeButton();
    btn.dataset = { deliveryOption: name };
    return btn;
  });
  return {
    querySelectorAll: () => buttons,
    _buttons: buttons,
  };
}

test('createTalkWorkspaceFeature: getSelectedSendAction defaults to the profile-derived action with no explicit selection', () => {
  const feature = createTalkWorkspaceFeature({ elements: {} });
  feature.init();
  feature.setOutputSettings({ send_mode: 'review_first', capabilities: { supports_input_injection: true } });
  assert.equal(feature.getSelectedSendAction(), 'paste');
});

test('createTalkWorkspaceFeature: clicking a segmented option overrides getSelectedSendAction and notifies onDeliverySelectionChanged', () => {
  const container = makeSegmentedContainer(DELIVERY_OPTIONS);
  const els = { deliverySegmented: container, sendButtonLabel: { textContent: '' } };
  let notified = null;
  const feature = createTalkWorkspaceFeature({ elements: els, hooks: { onDeliverySelectionChanged: (s) => { notified = s; } } });
  feature.init();
  feature.setOutputSettings({ send_mode: 'review_first', capabilities: { supports_input_injection: true } });

  container._buttons[0].click(); // 'type'
  assert.equal(feature.getSelectedSendAction(), 'type');
  assert.equal(notified, 'type');
  assert.equal(els.sendButtonLabel.textContent, 'Type at Cursor');

  container._buttons[1].click(); // 'paste'
  assert.equal(feature.getSelectedSendAction(), 'paste');
  assert.equal(els.sendButtonLabel.textContent, 'Paste at Cursor');
  assert.notEqual(els.sendButtonLabel.textContent, 'Type at Cursor');
});

test('createTalkWorkspaceFeature: explicit type selection with unsupported injection degrades getSelectedSendAction and label together', () => {
  const container = makeSegmentedContainer(DELIVERY_OPTIONS);
  const els = { deliverySegmented: container, sendButtonLabel: { textContent: '' } };
  const feature = createTalkWorkspaceFeature({ elements: els });
  feature.init();
  feature.setOutputSettings({ send_mode: 'review_first', capabilities: { supports_input_injection: false } });

  container._buttons[0].click(); // 'type'
  assert.equal(feature.getSelectedSendAction(), 'copy_only');
  assert.equal(els.sendButtonLabel.textContent, 'Copy to Clipboard (injection unavailable)');
});

// The segmented control must never advertise a method the Send button will not
// use. These cover the case the markup alone cannot: no explicit selection, so
// the active segment has to come from the RESOLVED profile default.

test('activeDeliverySegment: with no selection it follows the resolved profile default', () => {
  assert.equal(activeDeliverySegment(null, { send_mode: 'review_first', capabilities: { supports_input_injection: true } }), 'paste');
  assert.equal(activeDeliverySegment(null, { send_mode: 'review_first', capabilities: { supports_input_injection: false } }), 'copy');
  assert.equal(activeDeliverySegment(null, null), 'copy');
  // 'open_chat_then_send' is a profile mode, not an insertion method: no
  // segment represents it, so none is active and the label carries the meaning.
  assert.equal(activeDeliverySegment(null, { send_mode: 'auto_send', capabilities: { supports_input_injection: true } }), null);
});

test('activeDeliverySegment: an explicit selection wins over the profile default, even when it degrades', () => {
  const noInjection = { send_mode: 'review_first', capabilities: { supports_input_injection: false } };
  assert.equal(activeDeliverySegment('type', noInjection), 'type');
  assert.equal(activeDeliverySegment('copy', { send_mode: 'auto_send', capabilities: { supports_input_injection: true } }), 'copy');
});

test('createTalkWorkspaceFeature: setOutputSettings paints the active segment from the resolved default', () => {
  const container = makeSegmentedContainer(DELIVERY_OPTIONS);
  const els = { deliverySegmented: container, sendButtonLabel: { textContent: '' } };
  const feature = createTalkWorkspaceFeature({ elements: els });
  feature.init();
  feature.setOutputSettings({ send_mode: 'review_first', capabilities: { supports_input_injection: true } });

  const [typeBtn, pasteBtn, copyBtn] = container._buttons;
  assert.equal(pasteBtn.classList.contains('is-active'), true, 'resolved default (paste) must read as active');
  assert.equal(typeBtn.classList.contains('is-active'), false);
  assert.equal(copyBtn.classList.contains('is-active'), false);
  assert.equal(pasteBtn.getAttribute('aria-pressed'), 'true');
  assert.equal(typeBtn.getAttribute('aria-pressed'), 'false');

  // Settings change with no user selection => the active segment follows.
  feature.setOutputSettings({ send_mode: 'review_first', capabilities: { supports_input_injection: false } });
  assert.equal(copyBtn.classList.contains('is-active'), true, 'losing injection support must move the active segment to Copy');
  assert.equal(pasteBtn.classList.contains('is-active'), false);
  assert.equal(els.sendButtonLabel.textContent, 'Copy to Clipboard');
});

test('createTalkWorkspaceFeature: an explicit selection is not overwritten by a later setOutputSettings', () => {
  const container = makeSegmentedContainer(DELIVERY_OPTIONS);
  const els = { deliverySegmented: container, sendButtonLabel: { textContent: '' } };
  const feature = createTalkWorkspaceFeature({ elements: els });
  feature.init();
  feature.setOutputSettings({ send_mode: 'review_first', capabilities: { supports_input_injection: true } });

  container._buttons[2].click(); // explicit 'copy'
  feature.setOutputSettings({ send_mode: 'auto_send', capabilities: { supports_input_injection: true } });

  assert.equal(feature.getSelectedSendAction(), 'copy_only', 'the user’s explicit choice must survive a settings refresh');
  assert.equal(container._buttons[2].classList.contains('is-active'), true);
});

// --- createTalkWorkspaceFeature: send-result panel -------------------------------

test('createTalkWorkspaceFeature: renderSendResult hides the panel when there is no result', () => {
  const els = { sendResult: { hidden: false } };
  const feature = createTalkWorkspaceFeature({ elements: els });
  feature.renderSendResult(null, null);
  assert.equal(els.sendResult.hidden, true);
});

test('createTalkWorkspaceFeature: renderSendResult paints all six fields and unhides the panel', () => {
  const els = {
    sendResult: { hidden: true },
    sendResultRequested: { textContent: '' },
    sendResultActual: { textContent: '' },
    sendResultFallback: { textContent: '' },
    sendResultFallbackReason: { textContent: '' },
    sendResultClipboard: { textContent: '' },
    sendResultSubmission: { textContent: '' },
  };
  const feature = createTalkWorkspaceFeature({ elements: els });
  feature.renderSendResult(
    {
      requested_action: 'type',
      actual_action: 'copy_only',
      fallback: true,
      fallback_reason: 'input_injection_unsupported',
      clipboard_result: { ok: true },
    },
    { status: 'sent' },
  );
  assert.equal(els.sendResult.hidden, false);
  assert.equal(els.sendResultRequested.textContent, 'type');
  assert.equal(els.sendResultActual.textContent, 'copy_only');
  assert.equal(els.sendResultFallback.textContent, 'Yes');
  assert.equal(els.sendResultFallbackReason.textContent, 'Input injection unavailable on this system');
  assert.equal(els.sendResultClipboard.textContent, 'text copied');
  assert.equal(els.sendResultSubmission.textContent, 'sent');
});

test('createTalkWorkspaceFeature: Send button click renders the send result from the fresh draft afterward', async () => {
  const latest = {
    status: 'sent',
    final_text: 'sent text',
    raw_text: 'raw',
    confidence: { score: 0.9 },
    send_result: { requested_action: 'paste', actual_action: 'paste', clipboard_result: null },
  };
  const els = {
    sendButton: makeButton(),
    refinedHero: { textContent: '' },
    refinedBadge: { classList: makeClassList() },
    rawTranscriptText: { textContent: '' },
    confidenceValue: { textContent: '', style: { setProperty() {} } },
    confidenceBarFill: { style: { width: '', setProperty() {} } },
    sendResult: { hidden: true },
    sendResultRequested: { textContent: '' },
    sendResultActual: { textContent: '' },
    sendResultFallback: { textContent: '' },
    sendResultFallbackReason: { textContent: '' },
    sendResultClipboard: { textContent: '' },
    sendResultSubmission: { textContent: '' },
  };
  const hooks = {
    drafts: {
      handleSendClick: async () => {},
      getLatestDraft: () => latest,
    },
  };
  const feature = createTalkWorkspaceFeature({ elements: els, hooks });
  feature.init();
  els.sendButton.click();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(els.sendResult.hidden, false);
  assert.equal(els.sendResultRequested.textContent, 'paste');
  assert.equal(els.sendResultClipboard.textContent, 'not used');
  assert.equal(els.sendResultSubmission.textContent, 'sent');
});

// --- createTalkWorkspaceFeature: confidence summary / force-review notice / settings link --

test('createTalkWorkspaceFeature: renderRefinedCard renders the confidence threshold summary from setOutputSettings', () => {
  const els = { confidenceThresholds: { textContent: '' } };
  const feature = createTalkWorkspaceFeature({ elements: els });
  feature.setOutputSettings({
    confidence_force_review_enabled: true,
    confidence_force_review_below: 0.55,
    confidence_auto_send_above: 0.85,
  });
  feature.renderRefinedCard(null);
  assert.equal(els.confidenceThresholds.textContent, 'Review below 55% · auto-send above 85%');
});

test('createTalkWorkspaceFeature: renderRefinedCard shows the force-review notice from the draft', () => {
  const els = { forceReviewNotice: { hidden: false, textContent: '' } };
  const feature = createTalkWorkspaceFeature({ elements: els });
  feature.renderRefinedCard({ status: 'pending', force_review: true, force_review_reason: 'low_confidence' });
  assert.equal(els.forceReviewNotice.hidden, false);
  assert.match(els.forceReviewNotice.textContent, /below the review threshold/);
});

test('createTalkWorkspaceFeature: renderRefinedCard hides the force-review notice when the draft is not flagged', () => {
  const els = { forceReviewNotice: { hidden: false, textContent: 'stale' } };
  const feature = createTalkWorkspaceFeature({ elements: els });
  feature.renderRefinedCard({ status: 'pending', force_review: false, force_review_reason: '' });
  assert.equal(els.forceReviewNotice.hidden, true);
});

test('createTalkWorkspaceFeature: clicking the confidence settings link calls hooks.onOpenConfidenceSettings', () => {
  const link = makeButton();
  const els = { confidenceSettingsLink: link };
  let called = 0;
  const feature = createTalkWorkspaceFeature({ elements: els, hooks: { onOpenConfidenceSettings: () => { called += 1; } } });
  feature.init();
  link.click();
  assert.equal(called, 1);
});
