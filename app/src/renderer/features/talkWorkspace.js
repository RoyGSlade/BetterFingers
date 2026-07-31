// talkWorkspace.js — thin wiring adapter for the Talk workspace (Phase 2 of
// the Signal Desk redesign, docs/ui/SIGNAL_DESK_SPEC.md section 4).
//
// This module does NOT reimplement recording/transcription/send logic -- it
// binds the new Talk markup (signal-desk.css / signal-desk-preview.html) to
// the EXISTING pipeline: features/drafts.js (draft state + accept/decline/
// send/rewrite/TTS) and the voice-status websocket already wired in main.js
// (see main.js's `updateVoiceStatus`, and the same status vocabulary
// glitch-ring.js/overlay.html's `interpret()` already speaks). It also owns
// mounting signalCore.js into the Talk workspace's ring mount point.
//
// additive / non-breaking: index.html and main.js are NOT touched this
// phase (per the phase plan, the swap-in is a later integration step). This
// file is fully usable today against a test DOM or the QA preview page, and
// documents exactly what main.js needs to hand it once that phase lands --
// see the `hooks` contract below and the TODO(phase-integration) markers.
//
// ---------------------------------------------------------------------------
// hooks contract (all optional; every call is optional-chained so a missing
// hook is a safe no-op, never a throw):
//
//   hooks.drafts             The object createDraftsFeature({...}) returns in
//                            main.js (getLatestDraft, refreshLatestDraft,
//                            runDraftTts, handleSendClick, handleAcceptClick,
//                            handleDeclineClick, ...). TODO(phase-integration):
//                            main.js constructs exactly one drafts feature
//                            today, bound to the OLD `.stream-panel` markup's
//                            elements (see CURRENT_UI_INVENTORY.md §6.3) --
//                            handleSendClick()/runDraftTts() etc. only touch
//                            `els.draftMessageEl`-style status text (not
//                            button-specific DOM) so calling them from Talk's
//                            NEW buttons is safe and triggers the real network
//                            calls; this adapter re-renders ITS OWN refined
//                            card afterward via getLatestDraft().
//   hooks.showToast(msg, tone, duration)   Optional user feedback (same shared
//                            helper signature as ui.showToast elsewhere).
//   hooks.writeClipboardText(text)         Defaults to
//                            window.betterFingers?.writeClipboardText.
//   hooks.onReviseRequested(draft)         TODO(phase-integration): SPEC 4's
//                            "Revise" button has no 1:1 existing handler --
//                            the closest analog is the old panel's rewrite
//                            tools row (Make Shorter/Clearer/Tone/Custom) +
//                            editable textarea, which Talk's new markup
//                            doesn't have a slot for yet. Stubbed until that
//                            editor surface is designed.
//   hooks.onDeliverySelectionChanged(selection)   Fired whenever the context
//                            panel's Type/Paste/Copy segmented control
//                            changes (see bindDeliverySegmented() below), so
//                            the composition root can feed the same choice
//                            into drafts.js's hooks.getSelectedSendAction
//                            (this module's own getSelectedSendAction()
//                            reproduces the same resolution via the exported
//                            resolveSendAction() pure helper).
//   hooks.onOpenConfidenceSettings()       Fired by the confidence-threshold
//                            summary's "Settings" link. Talk only displays
//                            the thresholds (owned by Settings, see
//                            deriveConfidenceThresholdSummary()) -- this hook
//                            is how the composition root navigates there.
//
// DIRECTOR RULING (Wave 2 Gate 2): Talk had two competing delivery controls
// plus a decorative send-chevron with no popover component anywhere in the
// repo. Exactly ONE segmented delivery selector survives -- the context
// panel's #sdDeliverySegmented, relabelled Type/Paste/Copy. The old
// #sdDeliveryType dropdown and #sdSendChevronButton (and its
// handleSendChevronClick stub / hooks.onSendVariantsRequested contract) are
// removed outright, not stubbed -- see TALK_PLACEMENT_MAP's
// 'delivery.sendVariants' entry.
//
// D-0036 (docs/release/DECISIONS.md): for v0.2.0-alpha.1, #sdDeliverySegmented
// itself is further reduced to a single Paste button -- Type and Copy are no
// longer offered as user choices on the shipping page (UI-06-038 is
// `intentional_cut`). The mapping/resolution functions below (DELIVERY_OPTIONS,
// deliveryOptionToSendAction, resolveSendAction, primaryActionLabel,
// activeDeliverySegment) deliberately still speak the full type/paste/copy
// vocabulary -- they read whatever `[data-delivery-option]` buttons actually
// exist in the DOM, so re-offering Type/Copy later is a markup change, not a
// rebuild of this module.
//
// To mount for real (a later phase): pass `elements` from collectTalkElements()
// (or an equivalent object) plus `hooks.drafts` = the live drafts feature
// instance, call `init()`, and forward main.js's voice-status messages into
// `handleVoiceStatusMessage()` in addition to (not instead of) its existing
// `updateVoiceStatus()` handling.
// ---------------------------------------------------------------------------

import { createSignalCore } from '../signalCore.js';

// --- Pure helpers (no DOM) --------------------------------------------------

// Mirrors overlay.html's `interpret()` / glitch-ring.js's state vocabulary so
// the Signal Core ring in Talk reacts to the exact same voice-status message
// shape the floating capture overlay already does.
export function interpretVoiceStatus(status, payload = {}) {
  switch (status) {
    case 'recording_started':
    case 'recording':
      return {
        ringState: 'recording',
        label: 'Recording',
        detail: payload.message || 'Capturing audio…',
        amplitude: typeof payload.amplitude === 'number' ? payload.amplitude : null,
      };
    case 'listening':
    case 'recording_armed':
      return { ringState: 'listening', label: 'Listening', detail: payload.message || 'Voice input detected', amplitude: null };
    case 'transcribing':
    case 'rewriting':
    case 'processing':
      return { ringState: 'transcribing', label: 'Processing', detail: payload.message || 'Transcribing…', amplitude: null };
    case 'long_recording_detected':
    case 'chunking_started':
    case 'chunking_progress':
      return { ringState: 'transcribing', label: 'Processing', detail: payload.message || 'Processing long recording…', amplitude: null };
    case 'chunking_stitching':
      return { ringState: 'transcribing', label: 'Processing', detail: payload.message || 'Stitching…', amplitude: null };
    case 'preview_ready':
      return { ringState: 'ready', label: 'Ready', detail: payload.message || 'Draft ready', amplitude: null };
    case 'draft_sent':
      return payload.fallback
        ? { ringState: 'error', label: 'Fallback', detail: payload.message || 'Copied as fallback', amplitude: null }
        : { ringState: 'ready', label: 'Sent', detail: payload.message || 'Sent', amplitude: null };
    case 'selection_captured':
      return { ringState: 'ready', label: 'Ready', detail: payload.message || 'Selection captured', amplitude: null };
    case 'emergency_stop':
      return { ringState: 'error', label: 'Stopped', detail: payload.message || 'Stopped', amplitude: null };
    case 'draft_blocked':
    case 'draft_error':
    case 'draft_send_error':
    case 'selection_capture_failed':
      return { ringState: 'error', label: 'Needs Attention', detail: payload.message || 'Needs attention', amplitude: null };
    case 'idle':
    case undefined:
    case null:
      return { ringState: 'idle', label: 'Idle', detail: payload.message || 'Waiting for input', amplitude: null };
    default:
      return { ringState: 'idle', label: 'Idle', detail: payload.message || String(status), amplitude: null };
  }
}

// SPEC 2's confidence-color rule ("color encodes STATUS more than raw
// number"): >=85 always green; 70-84 is green UNLESS the item is still an
// unsent draft (then blue, per the mock); 60-69 amber; <60 red. The spec
// doesn't enumerate the exact draft.status vocabulary this should key off --
// 'pending' (the only "still being worked on" status drafts.js renders) is
// treated as draft-like here; anything else (sent/accepted/blocked/error)
// is not. Flagged for the director to confirm once send/accept states are
// wired for real.
export function mapConfidenceBand(score, status) {
  const pct = formatConfidencePercent(score);
  if (pct === null) return null;
  const isDraftLike = !status || status === 'pending';
  if (pct >= 85) return 'high';
  if (pct >= 70) return isDraftLike ? 'draft' : 'high';
  if (pct >= 60) return 'mid';
  return 'low';
}

/** 0..1 confidence score -> an integer percent, or null if the score is missing. */
export function formatConfidencePercent(score) {
  if (score === null || score === undefined || Number.isNaN(Number(score))) return null;
  return Math.round(Math.max(0, Math.min(1, Number(score))) * 100);
}

const CONFIDENCE_BAND_CSS_VAR = {
  high: 'var(--sd-confidence-high)',
  draft: 'var(--sd-confidence-draft)',
  mid: 'var(--sd-confidence-mid)',
  low: 'var(--sd-confidence-low)',
};

/** confidence band ('high'|'draft'|'mid'|'low') -> the signal-desk.css var() string to apply inline. */
export function confidenceBandToCssVar(band) {
  return CONFIDENCE_BAND_CSS_VAR[band] || CONFIDENCE_BAND_CSS_VAR.high;
}

// Rough RMS-amplitude -> dBFS approximation for the vertical level meter
// (SPEC 4 shows a static "-18 dB" sample reading; the exact scale/floor
// isn't specified, so this is a reasonable placeholder formula + floor).
export function amplitudeToApproxDb(amplitude, floorDb = -60) {
  const a = Math.max(1e-6, Math.min(1, Number(amplitude) || 0));
  const db = 20 * Math.log10(a);
  return Math.max(floorDb, db);
}

/** dB reading -> 0..100 meter-fill percent, for the CSS --sd-meter-level custom property. */
export function dbToMeterPercent(db, floorDb = -60, ceilDb = 0) {
  const range = (ceilDb - floorDb) || 1;
  const numericDb = Number(db);
  const value = Number.isFinite(numericDb) ? numericDb : floorDb;
  const pct = (value - floorDb) / range;
  return Math.max(0, Math.min(100, pct * 100));
}

// Turns a drafts.js-shaped draft object into a plain view model, with no DOM
// involved -- the DOM-wiring renderRefinedCard() below just applies this.
export function deriveRefinedViewModel(draft) {
  if (!draft) {
    return {
      hasDraft: false,
      hero: 'Nothing captured yet. Hold Ctrl + Space and speak naturally.',
      badgeText: 'Waiting',
      badgeVariant: 'pending',
      rawQuote: '',
      confidencePct: null,
      confidenceBand: null,
    };
  }

  const status = draft.status || 'pending';
  const isErrorLike = status === 'blocked' || status === 'error';
  const score = draft?.confidence?.score;
  const confidencePct = formatConfidencePercent(score);
  const confidenceBand = confidencePct === null ? null : mapConfidenceBand(score, status);

  return {
    hasDraft: true,
    hero: draft.final_text || draft.raw_text || '(empty transcript)',
    badgeText: isErrorLike ? 'Needs Review' : status === 'pending' ? 'Ready' : 'Sent',
    badgeVariant: isErrorLike ? 'error' : 'ready',
    rawQuote: draft.raw_text || '',
    confidencePct,
    confidenceBand,
  };
}

// --- Delivery selector (Paste only on the shipping page, D-0036) ------------
//
// The backend's perform_output_action (server.py ~line 999) accepts exactly
// 'copy_only' | 'paste' | 'type' | 'open_chat_then_send' -- anything else is
// silently coerced to 'copy_only'. DELIVERY_OPTIONS is the full vocabulary the
// context panel's segmented control CAN carry; D-0036 narrows which of these
// the shipping markup actually offers a button for (paste only) without
// touching this mapping -- see the header comment above.

export const DELIVERY_OPTIONS = ['type', 'paste', 'copy'];

/** Segmented-control option -> the send action vocabulary perform_output_action accepts, or null for an unrecognised option. */
export function deliveryOptionToSendAction(option) {
  switch (option) {
    case 'type': return 'type';
    case 'paste': return 'paste';
    case 'copy': return 'copy_only';
    default: return null;
  }
}

/**
 * Resolve the send action to actually use. An explicit segmented `selection`
 * overrides the profile-derived default; with no selection this reproduces
 * today's bootstrap/signalDeskApp.js getSelectedSendAction() default exactly
 * (no injection support => 'copy_only'; send_mode === 'auto_send' =>
 * 'open_chat_then_send'; else 'paste'; no settings at all => 'copy_only').
 * If the user explicitly picked type/paste but injection isn't supported,
 * this degrades to 'copy_only' -- the degradation is made visible via
 * primaryActionLabel(), never silent.
 */
export function resolveSendAction(selection, outputSettings) {
  const supportsInjection = Boolean(outputSettings?.capabilities?.supports_input_injection);

  if (DELIVERY_OPTIONS.includes(selection)) {
    const mapped = deliveryOptionToSendAction(selection);
    if (mapped === 'type' || mapped === 'paste') {
      return supportsInjection ? mapped : 'copy_only';
    }
    return mapped;
  }

  if (!outputSettings) return 'copy_only';
  if (!supportsInjection) return 'copy_only';
  return outputSettings.send_mode === 'auto_send' ? 'open_chat_then_send' : 'paste';
}

/** The label the primary send button shows -- must always name what the button will ACTUALLY do. */
export function primaryActionLabel(selection, outputSettings) {
  const supportsInjection = Boolean(outputSettings?.capabilities?.supports_input_injection);

  if (DELIVERY_OPTIONS.includes(selection)) {
    if (selection === 'type') {
      return supportsInjection ? 'Type at Cursor' : 'Copy to Clipboard (injection unavailable)';
    }
    if (selection === 'paste') {
      return supportsInjection ? 'Paste at Cursor' : 'Copy to Clipboard (injection unavailable)';
    }
    return 'Copy to Clipboard';
  }

  if (!outputSettings || !supportsInjection) return 'Copy to Clipboard';
  return outputSettings.send_mode === 'auto_send' ? 'Send to Chat' : 'Paste at Cursor';
}

/**
 * Which segment should read as active given the current selection and settings.
 *
 * With no explicit selection the control must still show the method that is
 * actually in force, or the user is looking at three equal-looking buttons
 * while the Send button quietly does something none of them names. Returns
 * null when the resolved action has no segment ('open_chat_then_send' -- there
 * is deliberately no "Send to chat" segment, because that action is a profile
 * mode rather than an insertion method), in which case no segment is active
 * and the button label alone carries the meaning.
 */
export function activeDeliverySegment(selection, outputSettings) {
  if (DELIVERY_OPTIONS.includes(selection)) return selection;
  switch (resolveSendAction(selection, outputSettings)) {
    case 'type': return 'type';
    case 'paste': return 'paste';
    case 'copy_only': return 'copy';
    default: return null;
  }
}

const FALLBACK_REASON_TEXT = {
  '': '',
  input_injection_unsupported: 'Input injection unavailable on this system',
  injection_failed: 'Input injection failed',
};

/** send_result.fallback_reason -> human text. An unrecognised reason is passed through verbatim, never swallowed. */
function fallbackReasonToText(reason) {
  const key = reason || '';
  return key in FALLBACK_REASON_TEXT ? FALLBACK_REASON_TEXT[key] : key;
}

/** send_result.clipboard_result -> a short human-readable clipboard state. */
function clipboardResultToState(clipboardResult) {
  if (!clipboardResult) return 'not used';
  if (clipboardResult.ok) return 'text copied';
  return `copy failed: ${clipboardResult.message || 'unknown error'}`;
}

/** draft.status/send_outcome + send_result flags -> a short human-readable submission state. */
function draftToSubmissionState(draft) {
  const status = draft?.status;
  const outcome = draft?.send_outcome;
  if (status === 'sent' || outcome === 'sent') return 'sent';
  if (status === 'send_error' || outcome === 'failed') return 'send failed';
  if (status === 'send_interrupted' || outcome === 'interrupted') return 'interrupted — outcome unknown';
  return 'not submitted';
}

// Turns server.py's send_result (perform_output_action / send_draft_by_id,
// ~line 975-1245) plus the owning draft into a plain view model -- no DOM
// involved. Every field named here is real (see file's task brief); nothing
// is invented.
export function deriveSendResultViewModel(sendResult, draft) {
  if (!sendResult) {
    return {
      hasResult: false,
      requested: null,
      actual: null,
      fallbackUsed: false,
      fallbackReason: '',
      fallbackReasonText: '',
      clipboardState: 'not used',
      submissionState: draftToSubmissionState(draft),
      ok: false,
      message: '',
    };
  }

  return {
    hasResult: true,
    requested: sendResult.requested_action ?? null,
    actual: sendResult.actual_action ?? null,
    fallbackUsed: Boolean(sendResult.fallback),
    fallbackReason: sendResult.fallback_reason || '',
    fallbackReasonText: fallbackReasonToText(sendResult.fallback_reason),
    clipboardState: clipboardResultToState(sendResult.clipboard_result),
    submissionState: draftToSubmissionState(draft),
    ok: Boolean(sendResult.ok),
    message: sendResult.message || '',
  };
}

// Confidence thresholds are owned/edited by Settings (settingsWorkspace.js's
// confidence_force_review_enabled / confidence_force_review_below /
// confidence_auto_send_above, backed by utils.py's profile defaults and
// enforced by send_policy.py's evaluate_confidence_send_policy) -- Talk only
// displays a read-only summary, never its own gate. Returns null (an honest
// empty state) when the settings aren't available yet, rather than
// fabricating numbers.
export function deriveConfidenceThresholdSummary(settings) {
  if (!settings) return null;
  const { confidence_force_review_enabled: enabled, confidence_force_review_below: below, confidence_auto_send_above: above } = settings;
  if (enabled === undefined || enabled === null) return null;
  if (enabled === false) return 'Confidence gate off';
  if (below === undefined || below === null || above === undefined || above === null) return null;

  const belowPct = Math.round(Number(below) * 100);
  const abovePct = Math.round(Number(above) * 100);
  if (!Number.isFinite(belowPct) || !Number.isFinite(abovePct)) return null;

  return `Review below ${belowPct}% · auto-send above ${abovePct}%`;
}

const FORCE_REVIEW_REASON_TEXT = {
  audio_gate: 'No audio was detected before this draft — flagged for review.',
  long_draft: 'This draft is long — flagged for review.',
  confidence_missing: 'Confidence score unavailable — flagged for review.',
  low_confidence: 'Confidence is below the review threshold — flagged for review.',
  confidence_moderate: 'Confidence is in the moderate range — flagged for review.',
};

// draft.force_review / draft.force_review_reason (server.py ~line 925,
// send_policy.py's evaluate_confidence_send_policy) -> a display-only notice.
// Surfaces the backend's own gate decision; does not invent one.
export function deriveForceReviewNotice(draft) {
  if (!draft?.force_review) return null;
  const reason = draft.force_review_reason || '';
  const text = reason in FORCE_REVIEW_REASON_TEXT
    ? FORCE_REVIEW_REASON_TEXT[reason]
    : reason ? `Flagged for review (${reason}).` : 'Flagged for review.';
  return { reason, text };
}

// --- Reusable element lookup -------------------------------------------------

// The DOM ids the Talk workspace markup exposes (see signal-desk-preview.html
// and any later index.html integration). Kept as one map so a future main.js
// only needs `collectTalkElements()` rather than re-deriving every id.
// --- Inventory -> Talk placement map (machine-readable parity gate) ---------
//
// Mirrors utilitiesWorkspace.js's INVENTORY_PLACEMENT_MAP, which is the only
// machine-checked proof that the redesign lost no feature. Utilities and
// Settings had such a gate; Talk, Library and Studio did not -- and those are
// exactly where the gaps cluster, so the surfaces most at risk were the ones
// nothing was measuring.
//
// Seeded deliberately mostly `wired: false`. Introducing the gate BEFORE the
// work makes it measure the gap instead of rubber-stamping it: each later
// phase's diff becomes `wired: false -> true` plus the code that earns it, and
// an unwired entry must say why in `note`.
//
// Keys are drawn from docs/ui/CURRENT_UI_INVENTORY.md §6.3 (Review Draft
// Panel), the surface Talk replaces.
export const TALK_SECTIONS = ['capture', 'refine', 'review', 'delivery', 'context'];

export function isValidTalkSection(id) {
  return TALK_SECTIONS.includes(id);
}

export const TALK_PLACEMENT_MAP = {
  'capture.signalCore': { section: 'capture', control: 'Signal Core ring + live amplitude', wired: true },
  'capture.statusText': { section: 'capture', control: 'Listening / voice-detected status', wired: true },
  'capture.levelMeter': { section: 'capture', control: 'dB level meter', wired: true },
  'capture.toggleRecording': { section: 'capture', control: 'Start/Stop Recording', wired: true, note: 'Wave 2: features/talkCapture.js binds #sdCaptureStartButton/#sdCaptureStopButton; the button path and the hotkey path converge on one reducer with voice-status authoritative' },
  'capture.emergencyStop': { section: 'capture', control: 'Emergency Stop', wired: true, note: 'Wave 2: #sdEmergencyStopButton via features/talkCapture.js -> POST /runtime/emergency-stop; enabled in every capture state by design' },

  'refine.refinedText': { section: 'refine', control: 'Refined message text', wired: true },
  'refine.rawTranscript': { section: 'refine', control: 'Raw transcript (collapsible)', wired: true },
  'refine.confidence': { section: 'refine', control: 'Confidence badge + band', wired: true },
  'refine.statusPill': { section: 'refine', control: 'Draft status pill', wired: true },
  'refine.tokenSummary': { section: 'refine', control: 'Token count / limit + long-text flag', wired: true },
  'refine.metadata': { section: 'refine', control: 'Recording duration + stop reason', wired: true },

  'review.editor': { section: 'review', control: 'Cleaned-output editor (textarea)', wired: true },
  'review.saveEdit': { section: 'review', control: 'Save Edit', wired: true },
  'review.rewriteShorter': { section: 'review', control: 'Make Shorter', wired: true },
  'review.rewriteClearer': { section: 'review', control: 'Make Clearer', wired: true },
  'review.rewriteTone': { section: 'review', control: 'Change Tone', wired: true },
  'review.rewriteCustom': { section: 'review', control: 'Custom rewrite instruction + run', wired: true },
  'review.revise': { section: 'review', control: 'Revise button (opens rewrite drawer)', wired: true },
  'review.listen': { section: 'review', control: 'Listen / read aloud', wired: true },
  'review.readSelection': { section: 'review', control: 'Read Selection', wired: true },

  'delivery.sendInsert': { section: 'delivery', control: 'Send / Insert primary action', wired: true },
  'delivery.sendVariants': { section: 'delivery', control: 'Send split-button variant popover', wired: false, intentional_cut: true, note: 'DIRECTOR RULING (Wave 2 Gate 2): no popover component exists anywhere in the repo; #sdSendChevronButton and hooks.onSendVariantsRequested are removed outright rather than left as a decorative stub. Exactly one delivery selector survives -- see delivery.segmented.' },
  'delivery.segmented': { section: 'delivery', control: 'Delivery selector (Paste only, D-0036) driving getSelectedSendAction()', wired: true },
  'delivery.accept': { section: 'delivery', control: 'Accept draft', wired: true },
  'delivery.decline': { section: 'delivery', control: 'Decline draft', wired: true },
  'delivery.retry': { section: 'delivery', control: 'Retry (blocked/error drafts)', wired: true },
  'delivery.copy': { section: 'delivery', control: 'Copy cleaned output', wired: true },
  'delivery.sendResult': { section: 'delivery', control: 'Send-result detail (requested/actual action, fallback reason, clipboard + submission state)', wired: true },

  'context.persona': { section: 'context', control: 'Active persona', wired: true },
  'context.processingMode': { section: 'context', control: 'Processing mode (local)', wired: true },
  'delivery.mode': { section: 'delivery', control: 'Review-first vs send-immediately', wired: false, intentional_cut: true, note: 'DIRECTOR RULING (Wave 2 Gate 2), same single-owner rule as context.confidenceSlider: this was a <select> nothing listened to. It mimed the profile field `send_mode`, which Settings > Review & Drafts already owns behind its save bar. Talk now shows the active mode read-only (#sdDeliveryModeValue) and links to that control (#sdDeliveryModeSettingsLink) rather than offering a second, non-functional writer.' },
  'context.contact': { section: 'context', control: 'Writing to (recipient picker)', wired: true },
  'context.confidenceSlider': { section: 'context', control: 'Fake <input type="range"> confidence gate control', wired: false, intentional_cut: true, note: 'DIRECTOR RULING (Wave 2 Gate 2): had no id and no handler; removed. Confidence thresholds are owned/edited by Settings (confidence_force_review_below / confidence_auto_send_above) -- Talk must not duplicate that gate. Replaced by the read-only context.confidenceThresholds + context.forceReviewNotice entries below.' },
  'context.confidenceThresholds': { section: 'context', control: 'Read-only confidence threshold summary + link to Settings', wired: true },
  'context.forceReviewNotice': { section: 'context', control: 'Force-review notice (draft.force_review / force_review_reason)', wired: true },
};

export const TALK_ELEMENT_IDS = {
  signalCoreRing: 'sdSignalCoreRing',
  signalCoreContainer: 'sdSignalCoreCanvasMount',
  statusLabel: 'sdSignalCoreStatusLabel',
  statusDetail: 'sdSignalCoreStatusDetail',
  meterValue: 'sdSignalCoreMeterValue',
  meterBar: 'sdSignalCoreMeterBar',
  meterLevel: 'sdSignalCoreMeterLevel',
  refinedBadge: 'sdRefinedBadge',
  refinedHero: 'sdRefinedHero',
  rawTranscriptText: 'sdRawTranscriptText',
  confidenceValue: 'sdConfidenceValue',
  confidenceBarFill: 'sdConfidenceBarFill',
  personaLabel: 'sdPersonaLabel',
  destinationLabel: 'sdDestinationLabel',
  rawTranscriptButton: 'sdRawTranscriptButton',
  listenButton: 'sdListenButton',
  reviseButton: 'sdReviseButton',
  sendButton: 'sdSendButton',
  sendButtonLabel: 'sdSendButtonLabel',
  deliverySegmented: 'sdDeliverySegmented',
  sendResult: 'sdSendResult',
  sendResultRequested: 'sdSendResultRequested',
  sendResultActual: 'sdSendResultActual',
  sendResultFallback: 'sdSendResultFallback',
  sendResultFallbackReason: 'sdSendResultFallbackReason',
  sendResultClipboard: 'sdSendResultClipboard',
  sendResultSubmission: 'sdSendResultSubmission',
  confidenceThresholds: 'sdConfidenceThresholds',
  confidenceSettingsLink: 'sdConfidenceSettingsLink',
  forceReviewNotice: 'sdForceReviewNotice',
};

/** Looks up every TALK_ELEMENT_IDS entry by id from `root` (defaults to `document`). Missing ids resolve to null, never throw. */
export function collectTalkElements(root) {
  const doc = root || (typeof document !== 'undefined' ? document : null);
  const els = {};
  for (const [key, id] of Object.entries(TALK_ELEMENT_IDS)) {
    els[key] = doc && typeof doc.getElementById === 'function' ? doc.getElementById(id) || null : null;
  }
  return els;
}

// --- DOM-wiring feature ------------------------------------------------------

/**
 * @param {object} deps
 * @param {object} deps.elements Talk workspace DOM refs -- see TALK_ELEMENT_IDS
 *   (use collectTalkElements() for the common case). Every access is
 *   optional-chained.
 * @param {object} deps.hooks See the file-header contract above.
 */
export function createTalkWorkspaceFeature({ elements, hooks } = {}) {
  const els = elements || {};
  const hks = hooks || {};

  let signalCore = null;
  let deliverySelection = null;
  let lastOutputSettings = null;

  function writeClipboard(text) {
    const fn = hks.writeClipboardText || (typeof window !== 'undefined' ? window.betterFingers?.writeClipboardText : null);
    return fn ? fn(text) : Promise.resolve();
  }

  // --- Signal Core ring mount ------------------------------------------------

  function mountSignalCore(config = {}) {
    if (signalCore) return signalCore;
    const canvas = els.signalCoreContainer || els.signalCoreRing;
    if (!canvas) {
      signalCore = createSignalCore({}); // safe no-op, see signalCore.js
      return signalCore;
    }
    const mountConfig = canvas.tagName === 'CANVAS' ? { canvas } : { container: canvas };
    signalCore = createSignalCore({ state: 'idle', ...config, ...mountConfig });
    els.signalCoreRing?.classList?.add?.('sd-signal-core-ring--js-mounted');
    return signalCore;
  }

  function getSignalCore() {
    return signalCore;
  }

  /** Feed a raw voice-status message (same shape as the WS the app already runs) into the ring + status label/meter. */
  function handleVoiceStatusMessage(message) {
    const status = typeof message === 'string' ? message : message?.status || message?.type;
    const payload = typeof message === 'string' ? {} : message || {};
    const { ringState, label, detail, amplitude } = interpretVoiceStatus(status, payload);

    signalCore?.setState(ringState);
    signalCore?.setAmplitude(amplitude);

    if (els.statusLabel) els.statusLabel.textContent = label;
    if (els.statusDetail) els.statusDetail.textContent = detail;

    if (amplitude != null && els.meterValue && els.meterBar) {
      const db = amplitudeToApproxDb(amplitude);
      const pct = dbToMeterPercent(db);
      els.meterValue.textContent = `${Math.round(db)} dB`;
      els.meterBar.style.setProperty('--sd-meter-level', `${pct}%`);
    }
  }

  // --- Refined Message card ---------------------------------------------------

  function renderRefinedCard(draft) {
    const vm = deriveRefinedViewModel(draft);

    // Ownership split (SPEC 6): once the hero is a real editor, drafts.js owns
    // its VALUE -- it is the module that reads .value back for Save Edit, the
    // edit diff and Read Selection. Writing textContent here as well would
    // give one element two writers, and the loser is whichever runs second.
    // This module still owns the badge, meta strip and action enablement.
    const heroIsEditor = typeof els.refinedHero?.value === 'string';
    if (els.refinedHero && !heroIsEditor) els.refinedHero.textContent = vm.hero;

    if (els.refinedBadge) {
      els.refinedBadge.classList?.remove?.('sd-badge--ready', 'sd-badge--pending', 'sd-badge--error');
      els.refinedBadge.classList?.add?.(`sd-badge--${vm.badgeVariant}`);
      const label = els.refinedBadge.querySelector ? els.refinedBadge.querySelector('[data-badge-label]') : null;
      if (label) label.textContent = vm.badgeText;
      else els.refinedBadge.textContent = vm.badgeText;
    }

    if (els.rawTranscriptText) {
      els.rawTranscriptText.textContent = vm.rawQuote ? `“${vm.rawQuote}”` : 'No transcript yet.';
    }

    if (els.confidenceValue) {
      els.confidenceValue.textContent = vm.confidencePct === null ? '—' : `${vm.confidencePct}%`;
    }
    if (els.confidenceBarFill) {
      els.confidenceBarFill.style.width = vm.confidencePct === null ? '0%' : `${vm.confidencePct}%`;
      if (vm.confidenceBand) {
        els.confidenceBarFill.style.setProperty('--sd-confidence-color', confidenceBandToCssVar(vm.confidenceBand));
        els.confidenceValue.style?.setProperty?.('--sd-confidence-color', confidenceBandToCssVar(vm.confidenceBand));
      }
    }

    // TODO(phase-integration): draft objects (features/drafts.js /
    // server.py) don't carry persona/destination fields yet -- Studio
    // (persona selection, SPEC §6) and a destination-routing concept (SPEC
    // §4's "Discord #general" is currently mockup-only; no backend models
    // it) both land in later phases per SPEC §8. When present, forward-
    // compat with a couple of plausible field names; otherwise leave
    // whatever chip text is already in the DOM rather than blanking it.
    const personaName = draft?.persona_name || draft?.persona?.name;
    if (personaName && els.personaLabel) els.personaLabel.textContent = personaName;
    const destinationName = draft?.destination_name || draft?.destination?.name;
    if (destinationName && els.destinationLabel) els.destinationLabel.textContent = destinationName;

    const thresholdSummary = deriveConfidenceThresholdSummary(lastOutputSettings);
    if (els.confidenceThresholds) {
      els.confidenceThresholds.textContent = thresholdSummary === null ? '' : thresholdSummary;
    }

    const forceReviewNotice = deriveForceReviewNotice(draft);
    if (els.forceReviewNotice) {
      els.forceReviewNotice.hidden = !forceReviewNotice;
      els.forceReviewNotice.textContent = forceReviewNotice ? forceReviewNotice.text : '';
    }

    setActionsEnabled(vm.hasDraft);
  }

  function setActionsEnabled(hasDraft) {
    for (const btn of [els.rawTranscriptButton, els.listenButton, els.reviseButton, els.sendButton]) {
      if (btn) btn.disabled = !hasDraft;
    }
  }

  // --- Send-result panel (server.py's send_result -- drafts.js's
  //     ui.renderSendResult contract, currently a documented no-op in
  //     bootstrap/signalDeskApp.js) ------------------------------------------

  function renderSendResult(sendResult, draft) {
    const vm = deriveSendResultViewModel(sendResult, draft);
    if (els.sendResult) els.sendResult.hidden = !vm.hasResult;
    if (!vm.hasResult) return vm;

    if (els.sendResultRequested) els.sendResultRequested.textContent = vm.requested || '—';
    if (els.sendResultActual) els.sendResultActual.textContent = vm.actual || '—';
    if (els.sendResultFallback) els.sendResultFallback.textContent = vm.fallbackUsed ? 'Yes' : 'No';
    if (els.sendResultFallbackReason) els.sendResultFallbackReason.textContent = vm.fallbackReasonText || '—';
    if (els.sendResultClipboard) els.sendResultClipboard.textContent = vm.clipboardState;
    if (els.sendResultSubmission) els.sendResultSubmission.textContent = vm.submissionState;
    return vm;
  }

  async function refresh() {
    const draft = hks.drafts?.refreshLatestDraft
      ? await hks.drafts.refreshLatestDraft().catch(() => hks.drafts?.getLatestDraft?.() ?? null)
      : hks.drafts?.getLatestDraft?.() ?? null;
    renderRefinedCard(draft);
    return draft;
  }

  // --- Action row --------------------------------------------------------------

  async function handleRawTranscriptClick() {
    const draft = hks.drafts?.getLatestDraft?.();
    const text = draft?.raw_text || '';
    if (!text.trim()) {
      hks.showToast?.('No raw transcript to copy yet.', 'warning');
      return;
    }
    try {
      await writeClipboard(text);
      hks.showToast?.('Raw transcript copied to clipboard.', 'success', 2000);
    } catch (error) {
      hks.showToast?.(`Copy failed: ${error.message}`, 'danger');
    }
  }

  async function handleListenClick() {
    if (!hks.drafts?.runDraftTts) {
      hks.showToast?.('Listen is not wired up yet.', 'warning');
      return;
    }
    await hks.drafts.runDraftTts(false);
  }

  // TODO(phase-integration): no existing handler maps 1:1 to "Revise" -- see
  // file header. Calls the caller-supplied hook if given, otherwise no-ops
  // with a console warning so a silent dead button is easy to spot in dev.
  function handleReviseClick() {
    const draft = hks.drafts?.getLatestDraft?.();
    if (hks.onReviseRequested) {
      hks.onReviseRequested(draft);
      return;
    }
    hks.showToast?.('Revise isn’t wired up yet.', 'warning');
    if (typeof console !== 'undefined') {
      console.warn('[talkWorkspace] Revise clicked with no hooks.onReviseRequested handler.');
    }
  }

  async function handleSendClick() {
    if (!hks.drafts?.handleSendClick) {
      hks.showToast?.('Send is not wired up yet.', 'warning');
      return;
    }
    await hks.drafts.handleSendClick();
    const draft = hks.drafts.getLatestDraft?.() ?? null;
    renderRefinedCard(draft);
    renderSendResult(draft?.send_result ?? null, draft);
  }

  // --- Context panel: Delivery segmented (Type/Paste/Copy) --------------------

  function updatePrimaryActionLabel() {
    if (els.sendButtonLabel) {
      els.sendButtonLabel.textContent = primaryActionLabel(deliverySelection, lastOutputSettings);
    }
  }

  // Repaints the segmented control from the CURRENT resolved state rather than
  // trusting whatever `is-active` the markup shipped with. Without this the
  // page's static default (Type) and the module's initial selection (none, so
  // the profile default applies) can disagree, and the control would be
  // advertising a method the Send button is not going to use.
  function syncDeliverySegmented() {
    const container = els.deliverySegmented;
    if (!container || typeof container.querySelectorAll !== 'function') return;
    const active = activeDeliverySegment(deliverySelection, lastOutputSettings);
    Array.from(container.querySelectorAll('[data-delivery-option]')).forEach((btn) => {
      const isActive = btn.dataset?.deliveryOption === active;
      btn.classList?.toggle?.('is-active', isActive);
      btn.setAttribute?.('aria-pressed', isActive ? 'true' : 'false');
    });
  }

  function bindDeliverySegmented() {
    const container = els.deliverySegmented;
    if (!container || typeof container.querySelectorAll !== 'function') return;
    const options = Array.from(container.querySelectorAll('[data-delivery-option]'));
    options.forEach((btn) => {
      btn.addEventListener?.('click', () => {
        const option = btn.dataset.deliveryOption;
        if (!DELIVERY_OPTIONS.includes(option)) return;
        deliverySelection = option;
        syncDeliverySegmented();
        updatePrimaryActionLabel();
        hks.onDeliverySelectionChanged?.(deliverySelection);
      });
    });
    syncDeliverySegmented();
  }

  function getSelectedDeliveryOption() {
    return deliverySelection;
  }

  function getSelectedSendAction() {
    return resolveSendAction(deliverySelection, lastOutputSettings);
  }

  /** Pushes the profile-derived output settings in -- this module never fetches on its own. */
  function setOutputSettings(outputSettings) {
    lastOutputSettings = outputSettings || null;
    syncDeliverySegmented();
    updatePrimaryActionLabel();
  }

  // --- lifecycle ---------------------------------------------------------------

  function bindOnce() {
    els.rawTranscriptButton?.addEventListener?.('click', () => handleRawTranscriptClick());
    els.listenButton?.addEventListener?.('click', () => handleListenClick());
    els.reviseButton?.addEventListener?.('click', () => handleReviseClick());
    els.sendButton?.addEventListener?.('click', () => handleSendClick());
    els.confidenceSettingsLink?.addEventListener?.('click', (event) => {
      event?.preventDefault?.();
      hks.onOpenConfidenceSettings?.();
    });
    bindDeliverySegmented();
    updatePrimaryActionLabel();
  }

  function init(signalCoreConfig) {
    mountSignalCore(signalCoreConfig);
    bindOnce();
    renderRefinedCard(hks.drafts?.getLatestDraft?.() ?? null);
    return { getSignalCore };
  }

  function destroy() {
    signalCore?.destroy?.();
    signalCore = null;
  }

  return {
    init,
    mountSignalCore,
    getSignalCore,
    handleVoiceStatusMessage,
    renderRefinedCard,
    renderSendResult,
    refresh,
    getSelectedDeliveryOption,
    getSelectedSendAction,
    setOutputSettings,
    destroy,
  };
}
