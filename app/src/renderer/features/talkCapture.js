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

export const CAPTURE_STATES = ['idle', 'starting', 'recording', 'stopping', 'busy', 'error'];

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

function defaultMessageForState(state) {
  switch (state) {
    case 'recording':
      return 'Recording…';
    case 'busy':
      return 'Processing…';
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

  function isFn(value) {
    return typeof value === 'function';
  }

  function applySnapshot(next) {
    snapshot = next;
    if (els.startButton) els.startButton.disabled = !snapshot.canStart;
    if (els.stopButton) els.stopButton.disabled = !snapshot.canStop;
    if (els.emergencyButton) els.emergencyButton.disabled = !snapshot.canEmergencyStop;
    if (els.statusMessage) els.statusMessage.textContent = snapshot.message;
    hks.onStateChange?.(snapshot);
  }

  function dispatch(event) {
    applySnapshot(reduceCaptureState(snapshot, event));
  }

  /** Feed a raw voice-status message (same shape as the WS the app already runs) into the capture action row. */
  function handleVoiceStatusMessage(message) {
    const status = typeof message === 'string' ? message : message?.status || message?.type;
    const payload = typeof message === 'string' ? {} : message || {};
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
