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
//   hooks.onSendVariantsRequested(draft)   TODO(phase-integration): the
//                            Send/Insert split-button's chevron (copy/insert/
//                            send variants) has no existing popover
//                            component; SPEC 4's Delivery segmented control
//                            (context panel, already static markup from
//                            Phase 1) is the likely eventual source for this
//                            choice -- see bindDeliverySegmented() below.
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

// --- Reusable element lookup -------------------------------------------------

// The DOM ids the Talk workspace markup exposes (see signal-desk-preview.html
// and any later index.html integration). Kept as one map so a future main.js
// only needs `collectTalkElements()` rather than re-deriving every id.
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
  sendChevronButton: 'sdSendChevronButton',
  deliverySegmented: 'sdDeliverySegmented',
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
  let deliverySelection = 'send';

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

    if (els.refinedHero) els.refinedHero.textContent = vm.hero;

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

    setActionsEnabled(vm.hasDraft);
  }

  function setActionsEnabled(hasDraft) {
    for (const btn of [els.rawTranscriptButton, els.listenButton, els.reviseButton, els.sendButton, els.sendChevronButton]) {
      if (btn) btn.disabled = !hasDraft;
    }
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
    renderRefinedCard(hks.drafts.getLatestDraft?.() ?? null);
  }

  // TODO(phase-integration): the split-button chevron (copy/insert/send
  // variant picker) has no existing popover component -- see file header.
  function handleSendChevronClick() {
    const draft = hks.drafts?.getLatestDraft?.();
    if (hks.onSendVariantsRequested) {
      hks.onSendVariantsRequested(draft);
      return;
    }
    hks.showToast?.('Send variants aren’t wired up yet.', 'warning');
    if (typeof console !== 'undefined') {
      console.warn('[talkWorkspace] Send chevron clicked with no hooks.onSendVariantsRequested handler.');
    }
  }

  // --- Context panel: Delivery segmented (local-only state this phase) -------
  // TODO(phase-integration): this selection isn't fed into
  // getSelectedSendAction()/drafts.js yet -- main.js currently sources that
  // from the old #sendActionSelect dropdown. Once integrated, the segmented
  // control's choice should become (or drive) that source of truth.
  function bindDeliverySegmented() {
    const container = els.deliverySegmented;
    if (!container || typeof container.querySelectorAll !== 'function') return;
    const options = Array.from(container.querySelectorAll('[data-delivery-option]'));
    options.forEach((btn) => {
      btn.addEventListener?.('click', () => {
        deliverySelection = btn.dataset.deliveryOption || deliverySelection;
        options.forEach((other) => other.classList?.toggle?.('is-active', other === btn));
      });
    });
  }

  function getSelectedDeliveryOption() {
    return deliverySelection;
  }

  // --- lifecycle ---------------------------------------------------------------

  function bindOnce() {
    els.rawTranscriptButton?.addEventListener?.('click', () => handleRawTranscriptClick());
    els.listenButton?.addEventListener?.('click', () => handleListenClick());
    els.reviseButton?.addEventListener?.('click', () => handleReviseClick());
    els.sendButton?.addEventListener?.('click', () => handleSendClick());
    els.sendChevronButton?.addEventListener?.('click', () => handleSendChevronClick());
    bindDeliverySegmented();
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
    refresh,
    getSelectedDeliveryOption,
    destroy,
  };
}
