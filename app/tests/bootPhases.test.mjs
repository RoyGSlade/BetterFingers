// OR-02: pins the one rule the splash screen exists to enforce -- 'failed' is
// a pass-through of sidecarOutcome (main's own truth about waitForHealthy),
// never something derivePhase infers from elapsed time. Also pins the
// services-list rule: a subsystem /doctor didn't mention gets no row, ever.
//
// See SPLASH_SPEC.md §7 for the four behaviors these tests assert.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { derivePhase, deriveServices, describeHardware, SLOW_THRESHOLD_MS } from '../src/main/bootPhases.js';

test("'failed' never appears while sidecarOutcome is 'pending', no matter how long boot has been running", () => {
  const longRunning = derivePhase({ elapsedMs: 29999, doctor: null, sidecarOutcome: 'pending' });
  assert.notEqual(longRunning, 'failed');
  assert.equal(longRunning, 'slow'); // > SLOW_THRESHOLD_MS, but honestly 'slow', not 'failed'
});

test("'failed' appears exactly when sidecarOutcome is 'failed', even moments after boot started", () => {
  const phase = derivePhase({ elapsedMs: 50, doctor: null, sidecarOutcome: 'failed' });
  assert.equal(phase, 'failed');
});

test("'failed' is never produced by derivePhase's own logic -- only passed through from sidecarOutcome", () => {
  // Every doctor shape that could plausibly look like a failure (missing
  // model, runtime failure) must NOT flip the top-level phase to 'failed' on
  // its own -- only per-service status does that. sidecarOutcome is what main
  // sets from waitForHealthy, and it stays 'pending' here.
  const doctorWithFailures = {
    llm: { initialized: true, runtime_status: 'missing_llama_server' },
    models: { models_dir_exists: false, default_model_exists: false },
    audio: { devices: [], error: 'no devices' },
  };
  const phase = derivePhase({ elapsedMs: 1000, doctor: doctorWithFailures, sidecarOutcome: 'pending' });
  assert.notEqual(phase, 'failed');
});

test('slow appears once elapsed passes the 7s threshold and not a moment before', () => {
  const justUnder = derivePhase({ elapsedMs: SLOW_THRESHOLD_MS, doctor: null, sidecarOutcome: 'pending' });
  const justOver = derivePhase({ elapsedMs: SLOW_THRESHOLD_MS + 1, doctor: null, sidecarOutcome: 'pending' });
  assert.notEqual(justUnder, 'slow');
  assert.equal(justOver, 'slow');
});

test('ready requires both a healthy sidecar AND doctor reporting nothing still pending/starting', () => {
  const doctorStillLoading = {
    stt: { initialized: true, loaded: false },
    tts: { initialized: true, loaded: true },
  };
  const phase = derivePhase({ elapsedMs: 500, doctor: doctorStillLoading, sidecarOutcome: 'ready' });
  assert.notEqual(phase, 'ready'); // stt still 'starting' -- do not declare ready on a technicality
});

test('ready is trusted when sidecar is healthy and doctor has nothing further to add', () => {
  const phase = derivePhase({ elapsedMs: 500, doctor: null, sidecarOutcome: 'ready' });
  assert.equal(phase, 'ready');
});

test('deriveServices renders a row only for subsystems /doctor actually mentioned', () => {
  const doctor = { stt: { initialized: true, loaded: true }, llm: { runtime_status: 'ready' } };
  const services = deriveServices(doctor);
  const keys = services.map((s) => s.key);
  assert.deepEqual(keys.sort(), ['llm', 'stt']);
  // tts/hotkeys/models/audio/platform/hardware were never in the doctor
  // payload -- no row invents a status for them.
  for (const missingKey of ['tts', 'hotkeys', 'models', 'audio', 'platform', 'hardware']) {
    assert.ok(!keys.includes(missingKey), `unexpected row for ${missingKey}`);
  }
});

test('deriveServices renders nothing at all when doctor has not answered yet', () => {
  assert.deepEqual(deriveServices(null), []);
});

test('an llm runtime_status of a named failure produces a failed row, not a guessed pending/starting one', () => {
  const services = deriveServices({ llm: { initialized: true, runtime_status: 'missing_model', runtime_message: 'model file missing' } });
  const llmRow = services.find((s) => s.key === 'llm');
  assert.equal(llmRow.status, 'failed');
  assert.equal(llmRow.message, 'model file missing');
});

test('describeHardware never claims a dedicated GPU when the tier says integrated', () => {
  const doctor = { hardware_tier: { label: 'Integrated GPU', guidance: 'A 4B Q4 model is the sweet spot.' } };
  const text = describeHardware(doctor);
  assert.match(text, /Integrated GPU/);
  assert.doesNotMatch(text, /CUDA|[Dd]iscrete/);
});

test('describeHardware degrades honestly when doctor has not reported hardware yet', () => {
  assert.equal(describeHardware(null), 'Checking your hardware…');
});
