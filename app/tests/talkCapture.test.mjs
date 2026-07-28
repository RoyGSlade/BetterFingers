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
} from '../src/renderer/features/talkCapture.js';

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
  assert.deepEqual(CAPTURE_STATES, ['idle', 'starting', 'recording', 'stopping', 'busy', 'error']);
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
