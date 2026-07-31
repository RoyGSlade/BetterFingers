// Unit tests for the Talk capture actions module (talkCapture.js) --
// docs/ui/SIGNAL_DESK_SPEC.md section 4's capture action row (Start/Stop
// Recording, Emergency Stop). Mirrors the DOM-stub style already used by
// app/tests/talkWorkspace.test.mjs.
//
// Run with: node --test app/tests/talkCapture.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  CAPTURE_STATES,
  reduceCaptureState,
  TALK_CAPTURE_ELEMENT_IDS,
  collectTalkCaptureElements,
  createTalkCaptureFeature,
  hasNoInputSignal,
} from '../src/renderer/features/talkCapture.js';
import { showToast, TOAST_CONTAINER_ID } from '../src/renderer/lib/toast.mjs';

function makeButton() {
  const listeners = {};
  return {
    disabled: false,
    addEventListener(evt, fn) { listeners[evt] = fn; },
    click() { listeners.click?.(); },
  };
}

function makeElements() {
  return {
    startButton: makeButton(),
    stopButton: makeButton(),
    emergencyButton: makeButton(),
    statusMessage: { textContent: '' },
  };
}

// --- collectTalkCaptureElements ----------------------------------------------

test('collectTalkCaptureElements: every id key present, missing ids resolve to null', () => {
  const fakeDoc = { getElementById: () => null };
  const els = collectTalkCaptureElements(fakeDoc);
  for (const key of Object.keys(TALK_CAPTURE_ELEMENT_IDS)) {
    assert.ok(key in els);
    assert.equal(els[key], null);
  }
});

test('collectTalkCaptureElements: resolves whatever the stub document returns for a given id', () => {
  const sentinel = { id: 'sentinel' };
  const fakeDoc = { getElementById: (id) => (id === TALK_CAPTURE_ELEMENT_IDS.emergencyButton ? sentinel : null) };
  const els = collectTalkCaptureElements(fakeDoc);
  assert.equal(els.emergencyButton, sentinel);
  assert.equal(els.startButton, null);
});

// --- reduceCaptureState: pure state machine -----------------------------------

test('reduceCaptureState: unknown/undefined current defaults to idle', () => {
  const next = reduceCaptureState(undefined, { type: 'noop' });
  assert.equal(next.state, 'idle');
  assert.equal(next.canStart, true);
  assert.equal(next.canStop, false);
  assert.equal(next.canEmergencyStop, true);
});

test('reduceCaptureState: intent start from idle -> starting (start disabled, stop disabled)', () => {
  const idle = reduceCaptureState(undefined, {});
  const next = reduceCaptureState(idle, { type: 'intent', intent: 'start' });
  assert.equal(next.state, 'starting');
  assert.equal(next.canStart, false);
  assert.equal(next.canStop, false);
  assert.equal(next.canEmergencyStop, true);
});

test('reduceCaptureState: result ok recording:true from starting -> recording', () => {
  const starting = reduceCaptureState(undefined, { type: 'intent', intent: 'start' });
  const next = reduceCaptureState(starting, { type: 'result', intent: 'start', ok: true, recording: true, message: 'Recording started.' });
  assert.equal(next.state, 'recording');
  assert.equal(next.message, 'Recording started.');
  assert.equal(next.canStop, true);
  assert.equal(next.canStart, false);
});

test('reduceCaptureState: intent stop from recording -> stopping; ignored from idle', () => {
  const recording = reduceCaptureState(undefined, { type: 'result', intent: 'start', ok: true, recording: true });
  const stopping = reduceCaptureState(recording, { type: 'intent', intent: 'stop' });
  assert.equal(stopping.state, 'stopping');

  const idle = reduceCaptureState(undefined, {});
  const stillIdle = reduceCaptureState(idle, { type: 'intent', intent: 'stop' });
  assert.equal(stillIdle.state, 'idle');
});

test('reduceCaptureState: result ok recording:false from stopping -> idle', () => {
  const recording = reduceCaptureState(undefined, { type: 'result', intent: 'start', ok: true, recording: true });
  const stopping = reduceCaptureState(recording, { type: 'intent', intent: 'stop' });
  const next = reduceCaptureState(stopping, { type: 'result', intent: 'stop', ok: true, recording: false, message: 'Recording stopped.' });
  assert.equal(next.state, 'idle');
  assert.equal(next.canStart, true);
});

test('reduceCaptureState: toggle intent picks direction from current state', () => {
  const idle = reduceCaptureState(undefined, {});
  assert.equal(reduceCaptureState(idle, { type: 'intent', intent: 'toggle' }).state, 'starting');

  const recording = reduceCaptureState(undefined, { type: 'result', intent: 'start', ok: true, recording: true });
  assert.equal(reduceCaptureState(recording, { type: 'intent', intent: 'toggle' }).state, 'stopping');
});

test('reduceCaptureState: result ok:false -> error, with server message surfaced', () => {
  const idle = reduceCaptureState(undefined, {});
  const starting = reduceCaptureState(idle, { type: 'intent', intent: 'start' });
  const next = reduceCaptureState(starting, { type: 'result', intent: 'start', ok: false, recording: false, message: 'Mic unavailable.' });
  assert.equal(next.state, 'error');
  assert.equal(next.message, 'Mic unavailable.');
  assert.equal(next.canStart, true);
  assert.equal(next.canEmergencyStop, true);
});

test('reduceCaptureState: error event -> error state with message', () => {
  const idle = reduceCaptureState(undefined, {});
  const next = reduceCaptureState(idle, { type: 'error', message: 'Request failed.' });
  assert.equal(next.state, 'error');
  assert.equal(next.message, 'Request failed.');
});

test('reduceCaptureState: emergencyStop intent -> stopping; result ok -> idle regardless of prior state', () => {
  const recording = reduceCaptureState(undefined, { type: 'result', intent: 'start', ok: true, recording: true });
  const stopping = reduceCaptureState(recording, { type: 'intent', intent: 'emergencyStop' });
  assert.equal(stopping.state, 'stopping');
  const next = reduceCaptureState(stopping, { type: 'result', intent: 'emergencyStop', ok: true, message: 'Emergency stop completed.' });
  assert.equal(next.state, 'idle');
  assert.equal(next.message, 'Emergency stop completed.');
});

test('reduceCaptureState: canEmergencyStop is true in every reachable state', () => {
  const idle = reduceCaptureState(undefined, {});
  const starting = reduceCaptureState(idle, { type: 'intent', intent: 'start' });
  const recording = reduceCaptureState(starting, { type: 'result', intent: 'start', ok: true, recording: true });
  const stopping = reduceCaptureState(recording, { type: 'intent', intent: 'stop' });
  const busy = reduceCaptureState(stopping, { type: 'voiceStatus', status: 'transcribing', payload: {} });
  const error = reduceCaptureState(busy, { type: 'error', message: 'boom' });
  for (const snapshot of [idle, starting, recording, stopping, busy, error]) {
    assert.equal(snapshot.canEmergencyStop, true, `expected canEmergencyStop in state ${snapshot.state}`);
  }
});

// --- voiceStatus vocabulary ----------------------------------------------------

test('reduceCaptureState: voiceStatus recording_started/recording -> recording', () => {
  const idle = reduceCaptureState(undefined, {});
  assert.equal(reduceCaptureState(idle, { type: 'voiceStatus', status: 'recording_started', payload: {} }).state, 'recording');
  assert.equal(reduceCaptureState(idle, { type: 'voiceStatus', status: 'recording', payload: {} }).state, 'recording');
});

test('reduceCaptureState: voiceStatus transcribing/processing/chunking_* -> busy', () => {
  const idle = reduceCaptureState(undefined, {});
  for (const status of ['transcribing', 'processing', 'chunking_started', 'chunking_progress', 'chunking_stitching']) {
    assert.equal(reduceCaptureState(idle, { type: 'voiceStatus', status, payload: {} }).state, 'busy', status);
  }
});

test('reduceCaptureState: voiceStatus preview_ready/draft_sent/idle/emergency_stop -> idle', () => {
  const recording = reduceCaptureState(undefined, { type: 'result', intent: 'start', ok: true, recording: true });
  for (const status of ['preview_ready', 'draft_sent', 'idle', 'emergency_stop']) {
    assert.equal(reduceCaptureState(recording, { type: 'voiceStatus', status, payload: {} }).state, 'idle', status);
  }
});

// Regression guard for the mapping gap found in review: the reducer's status
// list was derived from talkWorkspace.js's interpretVoiceStatus(), which names
// statuses the backend never sends and omits several it does. An omitted status
// falls through to 'idle' and re-enables Start Recording mid-pipeline.
test('reduceCaptureState: every status server.py actually broadcasts maps to a deliberate state', () => {
  const idle = reduceCaptureState(undefined, {});
  const expected = {
    // capture in progress
    recording: 'recording',
    recording_started: 'recording',
    // pipeline still owns the recorder -- Start must stay disabled
    recording_complete: 'busy',
    dictation_queued: 'busy',
    transcribing: 'busy',
    rewriting: 'busy',
    draft_rewriting: 'busy',
    // failures
    error: 'error',
    draft_rewrite_error: 'error',
    // capture finished / draft lifecycle
    preview_ready: 'idle',
    draft_sent: 'idle',
    draft_accepted: 'idle',
    draft_declined: 'idle',
    draft_history_cleared: 'idle',
    draft_tts_requested: 'idle',
    draft_tts_started: 'idle',
    draft_tts_stopped: 'idle',
    selection_captured: 'idle',
    emergency_stop: 'idle',
    idle: 'idle',
  };
  for (const [status, state] of Object.entries(expected)) {
    assert.equal(reduceCaptureState(idle, { type: 'voiceStatus', status, payload: {} }).state, state, status);
  }
});

test('reduceCaptureState: mid-pipeline statuses keep Start disabled and Emergency Stop enabled', () => {
  const recording = reduceCaptureState(undefined, { type: 'result', intent: 'start', ok: true, recording: true });
  for (const status of ['recording_complete', 'dictation_queued', 'transcribing', 'draft_rewriting']) {
    const next = reduceCaptureState(recording, { type: 'voiceStatus', status, payload: {} });
    assert.equal(next.canStart, false, `Start must stay disabled during '${status}'`);
    assert.equal(next.canEmergencyStop, true, `Emergency Stop must stay enabled during '${status}'`);
  }
});

test('reduceCaptureState: voiceStatus is authoritative over a preceding optimistic intent', () => {
  const idle = reduceCaptureState(undefined, {});
  const starting = reduceCaptureState(idle, { type: 'intent', intent: 'start' });
  assert.equal(starting.state, 'starting');
  // The real backend never confirmed recording (e.g. mic permission denied
  // upstream and the hotkey manager never actually started) -- the socket
  // says idle, and that must win over the optimistic 'starting' guess.
  const next = reduceCaptureState(starting, { type: 'voiceStatus', status: 'idle', payload: {} });
  assert.equal(next.state, 'idle');
});

test('reduceCaptureState: voiceStatus is authoritative over a preceding optimistic error', () => {
  const idle = reduceCaptureState(undefined, {});
  const starting = reduceCaptureState(idle, { type: 'intent', intent: 'start' });
  const errored = reduceCaptureState(starting, { type: 'result', intent: 'start', ok: false, message: 'timeout' });
  assert.equal(errored.state, 'error');
  const next = reduceCaptureState(errored, { type: 'voiceStatus', status: 'recording', payload: {} });
  assert.equal(next.state, 'recording');
});

test('reduceCaptureState: hotkey path (voiceStatus only) and button path (intent+result then same voiceStatus) converge', () => {
  const sequence = [
    { type: 'voiceStatus', status: 'recording', payload: {} },
    { type: 'voiceStatus', status: 'transcribing', payload: {} },
    { type: 'voiceStatus', status: 'preview_ready', payload: {} },
  ];

  let hotkeyOnly = undefined;
  for (const event of sequence) hotkeyOnly = reduceCaptureState(hotkeyOnly, event);

  let viaButton = reduceCaptureState(undefined, { type: 'intent', intent: 'start' });
  viaButton = reduceCaptureState(viaButton, { type: 'result', intent: 'start', ok: true, recording: true, message: 'Recording started.' });
  for (const event of sequence) viaButton = reduceCaptureState(viaButton, event);

  assert.equal(hotkeyOnly.state, viaButton.state);
  assert.equal(hotkeyOnly.message, viaButton.message);
  assert.equal(hotkeyOnly.canStart, viaButton.canStart);
  assert.equal(hotkeyOnly.canStop, viaButton.canStop);
});

test('CAPTURE_STATES lists every state the reducer can produce', () => {
  assert.deepEqual(CAPTURE_STATES, ['idle', 'starting', 'recording', 'stopping', 'busy', 'downloading', 'error']);
});

// --- modelDownload / guidance: QA-FR-002 / QA-FR-003 --------------------------

test('reduceCaptureState: modelDownload active narrows busy into an explained downloading state', () => {
  const busy = reduceCaptureState(undefined, { type: 'voiceStatus', status: 'transcribing', payload: {} });
  assert.equal(busy.state, 'busy');
  const next = reduceCaptureState(busy, { type: 'modelDownload', active: true, message: "Downloading Whisper 'base.en'. This can take a few minutes." });
  assert.equal(next.state, 'downloading');
  assert.equal(next.message, "Downloading Whisper 'base.en'. This can take a few minutes.");
  assert.equal(next.canStart, false);
  assert.equal(next.canStop, false);
  assert.equal(next.canEmergencyStop, true);
});

test('reduceCaptureState: modelDownload never fires outside busy/downloading', () => {
  for (const status of ['recording', 'idle']) {
    const state = reduceCaptureState(undefined, { type: 'voiceStatus', status, payload: {} });
    const next = reduceCaptureState(state, { type: 'modelDownload', active: true, message: 'Downloading…' });
    assert.equal(next, state, `modelDownload must be a no-op from '${status}'`);
  }
});

test('reduceCaptureState: a real voiceStatus overrides a prior downloading state', () => {
  const busy = reduceCaptureState(undefined, { type: 'voiceStatus', status: 'transcribing', payload: {} });
  const downloading = reduceCaptureState(busy, { type: 'modelDownload', active: true, message: 'Downloading…' });
  assert.equal(downloading.state, 'downloading');
  const next = reduceCaptureState(downloading, { type: 'voiceStatus', status: 'preview_ready', payload: {} });
  assert.equal(next.state, 'idle');
});

test('reduceCaptureState: guidance appends to an existing error message and only fires from error', () => {
  const idle = reduceCaptureState(undefined, {});
  const noop = reduceCaptureState(idle, { type: 'guidance', text: 'Go to the Models screen.' });
  assert.equal(noop, idle, 'guidance must be a no-op outside the error state');

  const errored = reduceCaptureState(idle, { type: 'error', message: 'Whisper download failed: network unreachable' });
  const next = reduceCaptureState(errored, { type: 'guidance', text: 'Go to the Models screen to download the recommended LLM or Whisper models.' });
  assert.equal(next.state, 'error');
  assert.equal(next.message, 'Whisper download failed: network unreachable Go to the Models screen to download the recommended LLM or Whisper models.');
});

// --- createTalkCaptureFeature: DOM-wiring + api guard behavior ----------------

test('createTalkCaptureFeature: init() with no elements/hooks never throws', () => {
  const feature = createTalkCaptureFeature({});
  assert.doesNotThrow(() => feature.init());
  assert.doesNotThrow(() => feature.handleVoiceStatusMessage({ status: 'recording' }));
  assert.doesNotThrow(() => feature.destroy());
});

test('createTalkCaptureFeature: start()/stop()/emergencyStop() with no hooks.api never throw', async () => {
  const feature = createTalkCaptureFeature({});
  feature.init();
  await assert.doesNotReject(() => feature.start());
  await assert.doesNotReject(() => feature.emergencyStop());
  // stop() is a guarded no-op from idle (never recording), so it resolves immediately.
  await assert.doesNotReject(() => feature.stop());
});

test('createTalkCaptureFeature: start() never calls toggleRecording while already recording', async () => {
  const calls = { toggle: 0 };
  const els = makeElements();
  const api = { toggleRecording: async () => { calls.toggle += 1; return { ok: true, recording: false, message: 'stopped' }; } };
  const feature = createTalkCaptureFeature({ elements: els, hooks: { api } });
  feature.init();
  feature.handleVoiceStatusMessage({ status: 'recording' });
  assert.equal(feature.getState().state, 'recording');

  await feature.start();
  assert.equal(calls.toggle, 0, 'start() must not call toggleRecording while recording is already true');
});

test('createTalkCaptureFeature: stop() never calls toggleRecording while not recording', async () => {
  const calls = { toggle: 0 };
  const els = makeElements();
  const api = { toggleRecording: async () => { calls.toggle += 1; return { ok: true, recording: true, message: 'started' }; } };
  const feature = createTalkCaptureFeature({ elements: els, hooks: { api } });
  feature.init();
  assert.equal(feature.getState().state, 'idle');

  await feature.stop();
  assert.equal(calls.toggle, 0, 'stop() must not call toggleRecording while not recording');
});

test('createTalkCaptureFeature: start() falls back to toggleRecording when startRecording is absent', async () => {
  const calls = { toggle: 0 };
  const els = makeElements();
  const api = { toggleRecording: async () => { calls.toggle += 1; return { ok: true, recording: true, message: 'Recording started.' }; } };
  const feature = createTalkCaptureFeature({ elements: els, hooks: { api } });
  feature.init();

  await feature.start();
  assert.equal(calls.toggle, 1);
  assert.equal(feature.getState().state, 'recording');
  assert.equal(els.statusMessage.textContent, 'Recording started.');
});

test('createTalkCaptureFeature: start() prefers startRecording and does not call toggleRecording when both exist', async () => {
  const calls = { toggle: 0, start: 0 };
  const els = makeElements();
  const api = {
    toggleRecording: async () => { calls.toggle += 1; return { ok: true, recording: true }; },
    startRecording: async () => { calls.start += 1; return { ok: true, recording: true, message: 'Recording started.' }; },
  };
  const feature = createTalkCaptureFeature({ elements: els, hooks: { api } });
  feature.init();

  await feature.start();
  assert.equal(calls.start, 1);
  assert.equal(calls.toggle, 0);
});

test('createTalkCaptureFeature: stop() prefers stopRecording and does not call toggleRecording when both exist', async () => {
  const calls = { toggle: 0, stop: 0 };
  const els = makeElements();
  const api = {
    toggleRecording: async () => { calls.toggle += 1; return { ok: true, recording: false }; },
    stopRecording: async () => { calls.stop += 1; return { ok: true, recording: false, message: 'Recording stopped.' }; },
  };
  const feature = createTalkCaptureFeature({ elements: els, hooks: { api } });
  feature.init();
  feature.handleVoiceStatusMessage({ status: 'recording' });

  await feature.stop();
  assert.equal(calls.stop, 1);
  assert.equal(calls.toggle, 0);
});

test('createTalkCaptureFeature: a rejected api call leaves the start button re-enabled and surfaces the message', async () => {
  const els = makeElements();
  const toasts = [];
  const api = { toggleRecording: async () => { throw new Error('Backend unreachable.'); } };
  const feature = createTalkCaptureFeature({ elements: els, hooks: { api, showToast: (msg, tone) => toasts.push({ msg, tone }) } });
  feature.init();

  await feature.start();
  assert.equal(feature.getState().state, 'error');
  assert.equal(els.startButton.disabled, false, 'start button must not be left stuck disabled after a failure');
  assert.equal(els.statusMessage.textContent, 'Backend unreachable.');
  assert.ok(toasts.some((t) => t.tone === 'danger' && t.msg.includes('Backend unreachable.')));
});

test('createTalkCaptureFeature: emergencyStop is callable and its button stays enabled from idle, recording, busy and error', async () => {
  for (const status of ['idle', 'recording', 'transcribing', 'draft_error']) {
    const els = makeElements();
    let calls = 0;
    const api = { emergencyStop: async () => { calls += 1; return { ok: true, message: 'Emergency stop completed.' }; } };
    const feature = createTalkCaptureFeature({ elements: els, hooks: { api } });
    feature.init();
    feature.handleVoiceStatusMessage({ status });
    assert.equal(els.emergencyButton.disabled, false, `emergency button must be enabled after voiceStatus '${status}'`);

    await feature.emergencyStop();
    assert.equal(calls, 1, `emergencyStop() should have called api.emergencyStop() from status '${status}'`);
    assert.equal(els.emergencyButton.disabled, false, 'emergency button must remain enabled after completing');
  }
});

test('createTalkCaptureFeature: click wiring calls the matching action exactly once, init() is idempotent', async () => {
  const els = makeElements();
  const calls = { emergency: 0 };
  const api = { emergencyStop: async () => { calls.emergency += 1; return { ok: true, message: 'stopped' }; } };
  const feature = createTalkCaptureFeature({ elements: els, hooks: { api } });
  feature.init();
  feature.init(); // idempotent: must not double-bind
  els.emergencyButton.click();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(calls.emergency, 1);
});

test('createTalkCaptureFeature: handleVoiceStatusMessage drives the status element and button enablement', () => {
  const els = makeElements();
  const feature = createTalkCaptureFeature({ elements: els });
  feature.init();
  assert.equal(els.startButton.disabled, false);
  assert.equal(els.stopButton.disabled, true);

  feature.handleVoiceStatusMessage({ status: 'recording', message: 'Capturing audio…' });
  assert.equal(els.statusMessage.textContent, 'Capturing audio…');
  assert.equal(els.startButton.disabled, true);
  assert.equal(els.stopButton.disabled, false);
});

test('createTalkCaptureFeature: onStateChange hook fires with the current snapshot', () => {
  const els = makeElements();
  const seen = [];
  const feature = createTalkCaptureFeature({ elements: els, hooks: { onStateChange: (s) => seen.push(s.state) } });
  feature.init();
  feature.handleVoiceStatusMessage({ status: 'recording' });
  assert.ok(seen.includes('recording'));
});

// --- QA-FR-002: on-demand model download surfaces as an explained state ------

test('createTalkCaptureFeature: entering busy polls the tracked download state and narrows into downloading', async () => {
  const els = makeElements();
  let calls = 0;
  const api = {
    fetchWhisperModels: async () => {
      calls += 1;
      return {
        download_state: {
          status: 'downloading',
          percent: 20,
          model_size: 'base.en',
          message: "Downloading Whisper 'base.en'. This can take a few minutes.",
        },
      };
    },
  };
  const feature = createTalkCaptureFeature({ elements: els, hooks: { api } });
  feature.init();

  feature.handleVoiceStatusMessage({ status: 'transcribing' });
  assert.equal(feature.getState().state, 'busy');

  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();

  assert.ok(calls >= 1, 'fetchWhisperModels should have been polled at least once while busy');
  assert.equal(feature.getState().state, 'downloading');
  assert.equal(els.statusMessage.textContent, "Downloading Whisper 'base.en'. This can take a few minutes.");

  feature.destroy();
});

test('createTalkCaptureFeature: no fetchWhisperModels hook never polls; stays on the generic busy message', async () => {
  const els = makeElements();
  const feature = createTalkCaptureFeature({ elements: els, hooks: {} });
  feature.init();

  feature.handleVoiceStatusMessage({ status: 'transcribing' });
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(feature.getState().state, 'busy');
  assert.equal(els.statusMessage.textContent, 'Processing…');
  feature.destroy();
});

test('createTalkCaptureFeature: a non-active download_state (cached / complete) leaves the ordinary busy message alone', async () => {
  const els = makeElements();
  const api = { fetchWhisperModels: async () => ({ download_state: { status: 'complete', percent: 100 } }) };
  const feature = createTalkCaptureFeature({ elements: els, hooks: { api } });
  feature.init();

  feature.handleVoiceStatusMessage({ status: 'transcribing' });
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(feature.getState().state, 'busy');
  feature.destroy();
});

test('createTalkCaptureFeature: leaving busy (a real voiceStatus arrives) stops the download poll', async () => {
  const els = makeElements();
  let calls = 0;
  const api = {
    fetchWhisperModels: async () => {
      calls += 1;
      return { download_state: { status: 'downloading', percent: 20 } };
    },
  };
  const feature = createTalkCaptureFeature({ elements: els, hooks: { api } });
  feature.init();
  feature.handleVoiceStatusMessage({ status: 'transcribing' });
  await Promise.resolve();
  await Promise.resolve();
  const callsWhileDownloading = calls;
  assert.ok(callsWhileDownloading >= 1);

  feature.handleVoiceStatusMessage({ status: 'idle' });
  assert.equal(feature.getState().state, 'idle');
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(calls, callsWhileDownloading, 'poll must stop once a real voiceStatus leaves busy/downloading');
  feature.destroy();
});

// --- QA-FR-003: Doctor's recovery guidance now reaches an error in Talk ------

test('createTalkCaptureFeature: an error confirmed STT-unloaded by Doctor gets the backend recovery guidance appended', async () => {
  const els = makeElements();
  const api = {
    toggleRecording: async () => { throw new Error("Whisper download failed: network unreachable"); },
    fetchDoctor: async () => ({
      stt_info: { loaded: false },
      recovery: { missing_model: 'Go to the Models screen to download the recommended LLM or Whisper models.' },
    }),
  };
  const feature = createTalkCaptureFeature({ elements: els, hooks: { api } });
  feature.init();

  await feature.start();
  assert.equal(feature.getState().state, 'error');
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(
    els.statusMessage.textContent,
    'Whisper download failed: network unreachable Go to the Models screen to download the recommended LLM or Whisper models.',
  );
  feature.destroy();
});

test('createTalkCaptureFeature: Doctor guidance is skipped when STT is not confirmed unloaded', async () => {
  const els = makeElements();
  const api = {
    toggleRecording: async () => { throw new Error('Mic unavailable.'); },
    fetchDoctor: async () => ({ stt_info: { loaded: true }, recovery: { missing_model: 'Go to the Models screen.' } }),
  };
  const feature = createTalkCaptureFeature({ elements: els, hooks: { api } });
  feature.init();

  await feature.start();
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(els.statusMessage.textContent, 'Mic unavailable.');
  feature.destroy();
});

test('createTalkCaptureFeature: no fetchDoctor hook never throws and leaves the plain error message', async () => {
  const els = makeElements();
  const api = { toggleRecording: async () => { throw new Error('Backend unreachable.'); } };
  const feature = createTalkCaptureFeature({ elements: els, hooks: { api } });
  feature.init();

  await feature.start();
  await Promise.resolve();

  assert.equal(els.statusMessage.textContent, 'Backend unreachable.');
  feature.destroy();
});

// --- OR-06: no-input-signal toast --------------------------------------------
//
// audio_gate.py's should_block_for_no_audio() (backend, already shipped)
// broadcasts 'draft_blocked' with gate_reasons over the SAME voice-status
// socket every other status arrives on -- detection happens at record-stop
// time, over the whole clip, using the existing no_audio_min_rms/peak
// thresholds. hasNoInputSignal() is the pure predicate that decides whether a
// given draft_blocked payload means "the mic heard nothing", and
// handleVoiceStatusMessage() is the only call site that acts on it.

test('hasNoInputSignal: true when a gate_reasons entry starts with near_silent(', () => {
  assert.equal(hasNoInputSignal({ gate_reasons: ['near_silent(peak=0.00100,rms=0.00050)'] }), true);
});

test('hasNoInputSignal: true when near_silent is combined with other reasons', () => {
  assert.equal(hasNoInputSignal({ gate_reasons: ['clip_too_short(0.100s<0.300s)', 'near_silent(peak=0.001,rms=0.0005)'] }), true);
});

test('hasNoInputSignal: false for reasons that do not include near_silent -- real audio, different problem', () => {
  assert.equal(hasNoInputSignal({ gate_reasons: ['empty_transcript'] }), false);
  assert.equal(hasNoInputSignal({ gate_reasons: ['clip_too_short(0.100s<0.300s)'] }), false);
});

test('hasNoInputSignal: false for missing/empty/malformed gate_reasons, never throws', () => {
  assert.equal(hasNoInputSignal({}), false);
  assert.equal(hasNoInputSignal({ gate_reasons: [] }), false);
  assert.equal(hasNoInputSignal({ gate_reasons: null }), false);
  assert.equal(hasNoInputSignal(undefined), false);
  assert.equal(hasNoInputSignal({ gate_reasons: [42, null, 'near_silent(x)'] }), true);
});

test('createTalkCaptureFeature: draft_blocked with near_silent shows the no-input toast with a working click-through', () => {
  const els = makeElements();
  const toasts = [];
  let opened = 0;
  const feature = createTalkCaptureFeature({
    elements: els,
    hooks: {
      showToast: (msg, tone, duration, doc, options) => toasts.push({ msg, tone, options }),
      onOpenSoundSettings: () => { opened += 1; },
    },
  });
  feature.init();

  feature.handleVoiceStatusMessage({
    status: 'draft_blocked',
    gate_reasons: ['near_silent(peak=0.00100,rms=0.00050)'],
    error: 'No usable audio was recorded.',
  });

  assert.equal(toasts.length, 1);
  assert.match(toasts[0].msg, /can't hear you/i);
  assert.equal(toasts[0].tone, 'warning');
  assert.equal(typeof toasts[0].options.onClick, 'function');

  toasts[0].options.onClick();
  assert.equal(opened, 1, 'the toast action must call hooks.onOpenSoundSettings');
});

test('createTalkCaptureFeature: draft_blocked WITHOUT near_silent (real audio, e.g. empty transcript) does not fire the no-input toast', () => {
  const els = makeElements();
  const toasts = [];
  const feature = createTalkCaptureFeature({
    elements: els,
    hooks: { showToast: (msg, tone) => toasts.push({ msg, tone }) },
  });
  feature.init();

  feature.handleVoiceStatusMessage({ status: 'draft_blocked', gate_reasons: ['empty_transcript'] });

  assert.equal(toasts.length, 0, 'a blocked draft with real audio must not claim the mic heard nothing');
});

test('createTalkCaptureFeature: an ordinary recording (real input, never blocked) never fires the no-input toast', () => {
  const els = makeElements();
  const toasts = [];
  const feature = createTalkCaptureFeature({
    elements: els,
    hooks: { showToast: (msg, tone) => toasts.push({ msg, tone }) },
  });
  feature.init();

  for (const status of ['recording_started', 'recording', 'transcribing', 'preview_ready', 'draft_sent']) {
    feature.handleVoiceStatusMessage({ status });
  }

  assert.equal(toasts.length, 0);
});

test('createTalkCaptureFeature: missing onOpenSoundSettings hook leaves the toast action a safe no-op', () => {
  const els = makeElements();
  const toasts = [];
  const feature = createTalkCaptureFeature({
    elements: els,
    hooks: { showToast: (msg, tone, duration, doc, options) => toasts.push(options) },
  });
  feature.init();

  feature.handleVoiceStatusMessage({ status: 'draft_blocked', gate_reasons: ['near_silent(x)'] });
  assert.doesNotThrow(() => toasts[0].onClick());
});

/** Minimal DOM double for toast.mjs's element-building path, mirroring toast.test.mjs. */
function makeToastDoc() {
  const makeEl = () => {
    const el = {
      className: '', textContent: '', dataset: {}, children: [], attrs: {},
      classList: { added: [], add(c) { this.added.push(c); } },
      listeners: {},
      setAttribute(k, v) { this.attrs[k] = v; },
      addEventListener(evt, fn) { (this.listeners[evt] ||= []).push(fn); },
      append(...kids) { for (const kid of kids) { kid.parent = this; this.children.push(kid); } },
      remove() {
        this.removed = true;
        const siblings = this.parent?.children;
        if (siblings) { const at = siblings.indexOf(this); if (at !== -1) siblings.splice(at, 1); }
      },
      querySelector(selector) {
        const wanted = selector.replace(/^\./, '');
        return this.children.find((kid) => kid.className === wanted) || null;
      },
    };
    return el;
  };
  const container = makeEl();
  return { container, createElement: () => makeEl(), getElementById: (id) => (id === TOAST_CONTAINER_ID ? container : null) };
}

test('createTalkCaptureFeature + real showToast: two near_silent draft_blocked events (e.g. a duplicated socket message) still show only ONE toast', () => {
  const els = makeElements();
  const doc = makeToastDoc();
  const feature = createTalkCaptureFeature({
    elements: els,
    hooks: { showToast: (msg, tone, duration, _doc, options) => showToast(msg, tone, duration, doc, options) },
  });
  feature.init();

  const payload = { status: 'draft_blocked', gate_reasons: ['near_silent(peak=0.001,rms=0.0005)'] };
  feature.handleVoiceStatusMessage(payload);
  feature.handleVoiceStatusMessage(payload);

  assert.equal(doc.container.children.length, 1, 'the toast idiom must coalesce a repeat into the SAME toast, not stack a second one');
});
