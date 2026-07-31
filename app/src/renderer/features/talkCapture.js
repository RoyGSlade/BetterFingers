// talkCapture.js — Talk workspace capture actions (Start/Stop Recording,
// Emergency Stop) for the Signal Desk redesign (docs/ui/SIGNAL_DESK_SPEC.md
// section 4 / TALK_PLACEMENT_MAP's 'capture.toggleRecording' and
// 'capture.emergencyStop' entries in features/talkWorkspace.js).
//
// This module owns the ACTION ROW only -- the ring/status/meter display is
// features/talkWorkspace.js's handleVoiceStatusMessage(); this module's own
// handleVoiceStatusMessage() should be called alongside it (both are safe,
// side-effect-isolated consumers of the same voice-status message).
//
// Convergence point: CAPTURE_STATES / reduceCaptureState() is a pure, DOM-free
// reducer. A click drives an optimistic 'intent' event; the real backend
// response drives a 'result' (or 'error') event; the voice-status websocket
// drives a 'voiceStatus' event. voiceStatus is always authoritative -- its
// branch of the reducer computes the next state from the status alone, never
// from what an intent/result already guessed, so the hotkey path (which only
// ever produces voiceStatus events) and the button path (intent -> result,
// then eventually the same voiceStatus echo) converge on identical state.
//
// hooks contract (all optional; every call is optional-chained so a missing
// hook is a safe no-op, never a throw -- same convention as talkWorkspace.js):
//
//   hooks.api             The api module from app/src/renderer/api/backend.js.
//                         Uses api.toggleRecording()/api.emergencyStop()
//                         (both exist today). Uses api.startRecording()/
//                         api.stopRecording() ONLY when present and a
//                         function (feature-detected) -- see the "not yet
//                         allowlisted" note below.
//   hooks.showToast(msg, tone, duration)   Optional user feedback.
//   hooks.onStateChange(stateSnapshot)     Called after every render with the
//                         reducer's current {state, message, canStart,
//                         canStop, canEmergencyStop} snapshot.
//   hooks.onOpenSoundSettings()            Click-through target for the
//                         no-input-signal toast (OR-06) -- navigates to
//                         Utilities / Speech Input. Optional-chained same as
//                         everything else; a missing hook just means the
//                         toast's action button is a no-op click.
//
// NOTE (integration-owned files, not touched here): as of this writing
// backendProxy.js's POST allowlist and backend.js only cover
// /runtime/recording/toggle and /runtime/emergency-stop -- start()/stop()
// below fall back to toggleRecording() (guarded so it is only ever called
// when the current state makes the direction unambiguous) until
// startRecording()/stopRecording() wrappers exist. See the handoff for the
// exact diff needed to add them.
// ---------------------------------------------------------------------------

// --- Pure helpers (no DOM) --------------------------------------------------

export const CAPTURE_STATES = ['idle', 'starting', 'recording', 'stopping', 'busy', 'downloading', 'error'];

// The status vocabulary is checked against what server.py ACTUALLY broadcasts,
// not against features/talkWorkspace.js's interpretVoiceStatus() list. Those two
// sets are not the same: interpretVoiceStatus() names several statuses the
// backend never emits ('processing', 'draft_error', 'draft_blocked',
// 'long_recording_detected', 'chunking_*', 'listening', 'recording_armed'),
// while the backend emits several it does not name. Getting this wrong is not
// cosmetic here -- an unrecognised status falls through to 'idle', which
// re-enables Start Recording in the middle of a pipeline that is still running.
//
// Emitted by server.py's broadcast_status_threadsafe (verified by enumerating
// every call site): dictation_queued, draft_accepted, draft_declined,
// draft_history_cleared, draft_rewrite_error, draft_rewriting, draft_sent,
// draft_tts_requested, draft_tts_started, draft_tts_stopped, emergency_stop,
// error, idle, preview_ready, recording, recording_complete, recording_started,
// rewriting, selection_captured, transcribing.
//
// The unlisted names are kept as accepted aliases rather than dropped: the
// overlay and glitch-ring already speak them, and a status arriving from any
// other producer should still land somewhere sensible.
function statusToState(status) {
  switch (status) {
    case 'recording_started':
    case 'recording':
      return 'recording';

    // Everything between "the user stopped talking" and "there is a draft" --
    // capture is over but the pipeline still owns the recorder, so Start must
    // stay disabled through all of it.
    case 'recording_complete':
    case 'dictation_queued':
    case 'transcribing':
    case 'rewriting':
    case 'draft_rewriting':
    case 'processing':
    case 'long_recording_detected':
    case 'chunking_started':
    case 'chunking_progress':
    case 'chunking_stitching':
      return 'busy';

    // 'error' is the plain status server.py actually broadcasts; the rest are
    // aliases from the overlay's vocabulary.
    case 'error':
    case 'draft_rewrite_error':
    case 'draft_blocked':
    case 'draft_error':
    case 'draft_send_error':
    case 'selection_capture_failed':
      return 'error';

    case 'preview_ready':
    case 'draft_sent':
    case 'idle':
    case 'emergency_stop':
    default:
      return 'idle';
  }
}

// OR-06: "no input signal" detection lives entirely on the backend already --
// audio_gate.py's should_block_for_no_audio() runs at record-stop time (not
// boot time) over the WHOLE clip the user just recorded, using the same
// no_audio_min_rms/no_audio_min_peak thresholds the trailing-silence auto-stop
// already trusts. A near-silent clip broadcasts 'draft_blocked' with a
// gate_reasons entry that starts with "near_silent(" (see should_block_for_no_audio).
// Checking the FULL clip (not just its first N ms) is what keeps this from
// crying wolf: a user who pauses before speaking still has real signal
// somewhere in the recording, so only a clip with NO signal anywhere in it
// trips this -- an honestly-quiet-so-far mic never does.
//
// 'clip_too_short' and 'empty_transcript' are deliberately NOT treated as "no
// signal": a short-but-loud tap (e.g. a cough) or a clip Whisper simply
// couldn't transcribe are different problems from an inaudible mic, and
// telling the user "I can't hear you" for either would be misleading.
export function hasNoInputSignal(payload) {
  const reasons = Array.isArray(payload?.gate_reasons) ? payload.gate_reasons : [];
  return reasons.some((reason) => typeof reason === 'string' && reason.startsWith('near_silent'));
}

function defaultMessageForState(state) {
  switch (state) {
    case 'recording':
      return 'Recording…';
    case 'busy':
      return 'Processing…';
    case 'downloading':
      return "Downloading the speech model (first use only, this can take a few minutes)…";
    case 'error':
      return 'Needs attention.';
    case 'starting':
      return 'Starting…';
    case 'stopping':
      return 'Stopping…';
    default:
      return 'Idle.';
  }
}

function snapshotFor(state, message) {
  return {
    state,
    message,
    canStart: state === 'idle' || state === 'error',
    canStop: state === 'recording',
    // The emergency stop control must never be the thing standing between a
    // user and killing a stuck pipeline -- it stays actionable in every state.
    canEmergencyStop: true,
  };
}

const INITIAL_SNAPSHOT = snapshotFor('idle', defaultMessageForState('idle'));

/**
 * Pure reducer: (current snapshot, event) -> next snapshot.
 *
 * event is one of:
 *   {type:'voiceStatus', status, payload}
 *   {type:'intent', intent:'start'|'stop'|'toggle'|'emergencyStop'}
 *   {type:'result', intent, ok, recording, message}
 *   {type:'error', message}
 *   {type:'modelDownload', active, message}   QA-FR-002: client-side-only
 *     enrichment, never something server.py broadcasts over the voice-status
 *     socket. Driven by createTalkCaptureFeature() polling GET /models/whisper
 *     while 'busy' (see pollModelDownload() below) -- it only ever narrows
 *     the generic 'busy'/"Processing…" span into a distinct, explained
 *     'downloading' state. A real voiceStatus event stays authoritative and
 *     can override it at any time, same as every other state here.
 *   {type:'guidance', text}   QA-FR-003: appends the backend's Doctor
 *     recovery guidance to an already-shown error message; never changes
 *     the state itself.
 */
export function reduceCaptureState(current, event) {
  const prev = current && CAPTURE_STATES.includes(current.state) ? current : INITIAL_SNAPSHOT;
  if (!event || typeof event !== 'object') return prev;

  switch (event.type) {
    case 'voiceStatus': {
      // Deliberately ignores `prev` -- this is what makes the hotkey path
      // (voiceStatus-only) and the button path (intent/result then the same
      // voiceStatus echo) converge on the same state from the same status.
      const state = statusToState(event.status);
      const message = event.payload?.message || defaultMessageForState(state);
      return snapshotFor(state, message);
    }

    case 'intent': {
      if (event.intent === 'emergencyStop') {
        return snapshotFor('stopping', 'Stopping everything…');
      }
      if (event.intent === 'start') {
        return prev.state === 'idle' || prev.state === 'error' ? snapshotFor('starting', 'Starting…') : prev;
      }
      if (event.intent === 'stop') {
        return prev.state === 'recording' ? snapshotFor('stopping', 'Stopping…') : prev;
      }
      if (event.intent === 'toggle') {
        if (prev.state === 'recording') return snapshotFor('stopping', 'Stopping…');
        if (prev.state === 'idle' || prev.state === 'error') return snapshotFor('starting', 'Starting…');
        return prev;
      }
      return prev;
    }

    case 'result': {
      if (!event.ok) {
        return snapshotFor('error', event.message || 'Action failed.');
      }
      if (event.intent === 'emergencyStop') {
        return snapshotFor('idle', event.message || 'Emergency stop completed.');
      }
      if (typeof event.recording === 'boolean') {
        return snapshotFor(
          event.recording ? 'recording' : 'idle',
          event.message || (event.recording ? 'Recording…' : 'Stopped.'),
        );
      }
      return snapshotFor(prev.state, event.message || prev.message);
    }

    case 'error':
      return snapshotFor('error', event.message || 'Something went wrong.');

    case 'modelDownload': {
      if (!event.active) return prev;
      // Only ever narrows 'busy' (or refreshes an existing 'downloading') --
      // never fires from 'recording'/'idle'/'error'/etc., so a stale poll
      // response arriving after the pipeline has already moved on can't
      // drag the UI backward.
      if (prev.state !== 'busy' && prev.state !== 'downloading') return prev;
      return snapshotFor('downloading', event.message || defaultMessageForState('downloading'));
    }

    case 'guidance': {
      if (prev.state !== 'error' || !event.text) return prev;
      return snapshotFor('error', `${prev.message} ${event.text}`.trim());
    }

    default:
      return prev;
  }
}

// --- Reusable element lookup -------------------------------------------------

export const TALK_CAPTURE_ELEMENT_IDS = {
  startButton: 'sdCaptureStartButton',
  stopButton: 'sdCaptureStopButton',
  emergencyButton: 'sdEmergencyStopButton',
  statusMessage: 'sdCaptureMessage',
};

/** Looks up every TALK_CAPTURE_ELEMENT_IDS entry by id from `root` (defaults to `document`). Missing ids resolve to null, never throw. */
export function collectTalkCaptureElements(root) {
  const doc = root || (typeof document !== 'undefined' ? document : null);
  const els = {};
  for (const [key, id] of Object.entries(TALK_CAPTURE_ELEMENT_IDS)) {
    els[key] = doc && typeof doc.getElementById === 'function' ? doc.getElementById(id) || null : null;
  }
  return els;
}

// --- DOM-wiring feature ------------------------------------------------------

/**
 * @param {object} deps
 * @param {object} deps.elements Talk capture DOM refs -- see
 *   TALK_CAPTURE_ELEMENT_IDS (use collectTalkCaptureElements() for the common
 *   case). Every access is optional-chained.
 * @param {object} deps.hooks See the file-header contract above.
 */
export function createTalkCaptureFeature({ elements, hooks } = {}) {
  const els = elements || {};
  const hks = hooks || {};

  let snapshot = INITIAL_SNAPSHOT;
  let bound = false;
  let startInFlight = false;
  let stopInFlight = false;
  let emergencyInFlight = false;
  let downloadPollTimer = null;
  let guidanceInFlightFor = null;

  function isFn(value) {
    return typeof value === 'function';
  }

  // --- QA-FR-002: poll the same tracked download state the Utilities
  // Download button already exposes (GET /models/whisper's download_state,
  // now also written by transcriber.ensure_loaded() for an on-demand load --
  // see transcriber.py), so the generic 'busy' span can narrow into an
  // explained, progress-bearing 'downloading' state instead of staying an
  // indefinite "Processing…". Best-effort only: any failure just stops
  // polling and leaves the ordinary 'busy' message in place.
  function stopDownloadPolling() {
    if (downloadPollTimer) {
      clearInterval(downloadPollTimer);
      downloadPollTimer = null;
    }
  }

  function formatDownloadMessage(state) {
    if (state?.message) return state.message;
    const size = state?.model_size ? ` '${state.model_size}'` : '';
    return `Downloading speech model${size} (first use only, this can take a few minutes)…`;
  }

  async function pollModelDownload() {
    const api = hks.api;
    if (!api || !isFn(api.fetchWhisperModels)) {
      stopDownloadPolling();
      return;
    }
    try {
      const result = await api.fetchWhisperModels();
      const state = result?.download_state;
      const active = Boolean(state && (state.status === 'starting' || state.status === 'downloading'));
      if (active) {
        dispatch({ type: 'modelDownload', active: true, message: formatDownloadMessage(state) });
      } else {
        stopDownloadPolling();
      }
    } catch {
      stopDownloadPolling();
    }
  }

  function startDownloadPollingIfNeeded() {
    const api = hks.api;
    if (downloadPollTimer || !api || !isFn(api.fetchWhisperModels)) return;
    downloadPollTimer = setInterval(() => { pollModelDownload(); }, 800);
    // Node's test runner would otherwise keep the process alive on a stray
    // interval; browsers/Electron have no unref() and ignore the call.
    if (typeof downloadPollTimer.unref === 'function') downloadPollTimer.unref();
    pollModelDownload();
  }

  // --- QA-FR-003: the backend already writes real Doctor recovery guidance
  // (server.py's recovery_guidelines) but Talk never read it. On the FIRST
  // tick of a genuinely new error (not a re-render caused by our own
  // 'guidance' dispatch below), fetch the existing /doctor report Utilities
  // already uses and -- only when it independently confirms STT isn't
  // loaded -- append its "missing_model" guidance to the message already
  // shown. Best-effort: a failed fetch leaves the original error untouched.
  async function maybeFetchGuidance(originalMessage) {
    const api = hks.api;
    if (!api || !isFn(api.fetchDoctor)) return;
    if (guidanceInFlightFor === originalMessage) return;
    guidanceInFlightFor = originalMessage;
    try {
      const doctor = await api.fetchDoctor();
      const text = doctor?.stt_info?.loaded === false ? doctor?.recovery?.missing_model : null;
      if (text && snapshot.state === 'error' && snapshot.message === originalMessage) {
        dispatch({ type: 'guidance', text });
      }
    } catch {
      // Diagnostic enrichment only -- the error already shown must not depend on this.
    }
  }

  function applySnapshot(next) {
    const enteringError = next.state === 'error' && snapshot.state !== 'error';
    snapshot = next;
    if (els.startButton) els.startButton.disabled = !snapshot.canStart;
    if (els.stopButton) els.stopButton.disabled = !snapshot.canStop;
    if (els.emergencyButton) els.emergencyButton.disabled = !snapshot.canEmergencyStop;
    if (els.statusMessage) els.statusMessage.textContent = snapshot.message;
    if (snapshot.state === 'busy' || snapshot.state === 'downloading') {
      startDownloadPollingIfNeeded();
    } else {
      stopDownloadPolling();
    }
    if (enteringError) {
      guidanceInFlightFor = null;
      maybeFetchGuidance(snapshot.message);
    }
    hks.onStateChange?.(snapshot);
  }

  function dispatch(event) {
    applySnapshot(reduceCaptureState(snapshot, event));
  }

  /** Feed a raw voice-status message (same shape as the WS the app already runs) into the capture action row. */
  function handleVoiceStatusMessage(message) {
    const status = typeof message === 'string' ? message : message?.status || message?.type;
    const payload = typeof message === 'string' ? {} : message || {};
    // OR-06: fires once per blocked recording attempt -- the backend only
    // broadcasts a single 'draft_blocked' per pipeline run, and toast.mjs's
    // own message+tone coalescing is the backstop against any repeat.
    if (status === 'draft_blocked' && hasNoInputSignal(payload)) {
      hks.showToast?.(
        "I can't hear you. Check your microphone in Sound settings.",
        'warning',
        undefined,
        undefined,
        { onClick: () => hks.onOpenSoundSettings?.(), actionLabel: 'Open Sound Settings' },
      );
    }
    dispatch({ type: 'voiceStatus', status, payload });
  }

  async function runAction({ intent, guard, call, successMessage, failureLabel }) {
    dispatch({ type: 'intent', intent });
    try {
      const result = await call();
      dispatch({
        type: 'result',
        intent,
        ok: result?.ok !== false,
        recording: result?.recording,
        message: result?.message,
      });
      hks.showToast?.(result?.message || successMessage, result?.ok === false ? 'warning' : 'success');
    } catch (error) {
      const message = error?.message || 'Request failed.';
      dispatch({ type: 'error', message });
      hks.showToast?.(`${failureLabel}: ${message}`, 'danger');
    }
  }

  async function start() {
    if (startInFlight) return;
    // Guarded so toggleRecording() is only ever used as a fallback when we
    // already know we're not recording -- calling it while recording would
    // stop it instead, which is exactly the bug this guard makes impossible.
    if (snapshot.state === 'recording' || !snapshot.canStart) return;
    startInFlight = true;
    try {
      const api = hks.api;
      await runAction({
        intent: 'start',
        call: () => {
          if (api && isFn(api.startRecording)) return api.startRecording();
          if (api && isFn(api.toggleRecording)) return api.toggleRecording();
          return Promise.reject(new Error('Recording start is not available.'));
        },
        successMessage: 'Recording started.',
        failureLabel: 'Recording start failed',
      });
    } finally {
      startInFlight = false;
      applySnapshot(snapshot);
    }
  }

  async function stop() {
    if (stopInFlight) return;
    // Symmetric guard: only ever call toggleRecording() as a fallback when we
    // already know we ARE recording.
    if (snapshot.state !== 'recording') return;
    stopInFlight = true;
    try {
      const api = hks.api;
      await runAction({
        intent: 'stop',
        call: () => {
          if (api && isFn(api.stopRecording)) return api.stopRecording();
          if (api && isFn(api.toggleRecording)) return api.toggleRecording();
          return Promise.reject(new Error('Recording stop is not available.'));
        },
        successMessage: 'Recording stopped.',
        failureLabel: 'Recording stop failed',
      });
    } finally {
      stopInFlight = false;
      applySnapshot(snapshot);
    }
  }

  async function toggle() {
    if (snapshot.state === 'recording') return stop();
    if (snapshot.state === 'idle' || snapshot.state === 'error') return start();
    // 'starting' / 'stopping' / 'busy': an action is already in flight or the
    // pipeline is processing -- ignore rather than fire a conflicting call.
  }

  async function emergencyStop() {
    if (emergencyInFlight) return;
    const api = hks.api;
    if (!api || !isFn(api.emergencyStop)) {
      hks.showToast?.('Emergency stop is not available.', 'danger');
      return;
    }
    emergencyInFlight = true;
    try {
      await runAction({
        intent: 'emergencyStop',
        call: () => api.emergencyStop(),
        successMessage: 'Emergency stop completed.',
        failureLabel: 'Emergency stop failed',
      });
    } finally {
      emergencyInFlight = false;
      applySnapshot(snapshot);
    }
  }

  function getState() {
    return snapshot;
  }

  function bindOnce() {
    if (bound) return;
    bound = true;
    els.startButton?.addEventListener?.('click', () => start());
    els.stopButton?.addEventListener?.('click', () => stop());
    els.emergencyButton?.addEventListener?.('click', () => emergencyStop());
  }

  function init() {
    bindOnce();
    applySnapshot(snapshot);
  }

  function destroy() {
    startInFlight = false;
    stopInFlight = false;
    emergencyInFlight = false;
    stopDownloadPolling();
    guidanceInFlightFor = null;
  }

  return {
    init,
    handleVoiceStatusMessage,
    start,
    stop,
    toggle,
    emergencyStop,
    getState,
    destroy,
  };
}
