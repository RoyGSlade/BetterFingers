// OR-02: pins the one rule the splash screen exists to enforce -- 'failed' is
// a pass-through of sidecarOutcome (main's own truth about waitForHealthy),
// never something derivePhase infers from elapsed time. Also pins the
// services-list rule: a subsystem /doctor didn't mention gets no row, ever.
//
// See SPLASH_SPEC.md §7 for the four behaviors these tests assert.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';

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

// --- BF_SKIP_BOOT_GATE ------------------------------------------------------
//
// Gating the dashboard window on a healthy backend (OR-02) made the QA harness
// unrunnable: harness.mjs waits for a window whose URL is signal-desk.html and
// deliberately drives renderer scenarios with no backend, so that window never
// arrived and all ~100 checks died on a 20s timeout. BF_SKIP_BOOT_GATE is the
// documented escape hatch. These tests exist so it cannot quietly become a
// product behaviour: a shipping path that sets it, or a loosened comparison
// that lets any truthy value through, fails here.

test('the boot gate bypass requires the exact string "1", not merely a truthy value', () => {
  const mainSrc = readFileSync(new URL('../src/main/main.js', import.meta.url), 'utf8');
  assert.match(
    mainSrc,
    /process\.env\.BF_SKIP_BOOT_GATE\s*===\s*'1'/,
    'main.js must compare BF_SKIP_BOOT_GATE strictly to \'1\' -- a loose check would let '
    + 'a stray "0", "false" or "" disable the gate on a real user\'s machine',
  );
});

test('boot doctor polling fences stale retries and releases only its own request guard', async () => {
  const mainSrc = readFileSync(new URL('../src/main/main.js', import.meta.url), 'utf8');
  const functionStart = mainSrc.indexOf('function createBootDoctorPoller');
  assert.notEqual(functionStart, -1, 'main.js must expose the extracted doctor poller contract');
  const bodyStart = mainSrc.indexOf('{', mainSrc.indexOf(')', functionStart));
  let depth = 0;
  let functionEnd = -1;
  for (let index = bodyStart; index < mainSrc.length; index += 1) {
    if (mainSrc[index] === '{') depth += 1;
    if (mainSrc[index] === '}') {
      depth -= 1;
      if (depth === 0) {
        functionEnd = index + 1;
        break;
      }
    }
  }
  assert.notEqual(functionEnd, -1, 'doctor poller helper must have a complete function body');
  const createPoller = new Function(`return (${mainSrc.slice(functionStart, functionEnd)})`)();

  let generation = 1;
  const resolvers = [];
  const published = [];
  const poller = createPoller({
    requestDoctor: () => new Promise((resolve) => resolvers.push(resolve)),
    isCurrent: (requestGeneration) => requestGeneration === generation,
    publish: (doctor) => published.push(doctor),
  });

  const stalePoll = poller.poll(1);
  assert.equal(poller.isInFlight(), true);
  generation = 2;
  assert.equal(await poller.poll(2), false, 'a retry cannot overlap the old doctor request');
  resolvers.shift()({ ok: true, body: { lifecycle: 1 } });
  assert.equal(await stalePoll, false, 'the old response is ignored after retry');
  assert.deepEqual(published, []);
  assert.equal(poller.isInFlight(), false, 'the old finally releases its own active request');

  const currentPoll = poller.poll(2);
  assert.equal(poller.isInFlight(), true);
  resolvers.shift()({ ok: true, body: { lifecycle: 2 } });
  assert.equal(await currentPoll, true);
  assert.deepEqual(published, [{ lifecycle: 2 }]);

  assert.match(mainSrc, /const generation = \+\+bootGeneration/);
  assert.match(mainSrc, /bootGeneration \+= 1/);
  assert.match(mainSrc, /generation !== bootGeneration/);
  assert.match(mainSrc, /clearInterval\(bootDoctorTimer\)/);
});

test('nothing under app/src ever sets BF_SKIP_BOOT_GATE', () => {
  const srcDir = new URL('../src/', import.meta.url);
  const offenders = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const child = new URL(entry.name + (entry.isDirectory() ? '/' : ''), dir);
      if (entry.isDirectory()) {
        walk(child);
        continue;
      }
      if (!/\.(js|mjs|cjs|html)$/.test(entry.name)) continue;
      const text = readFileSync(child, 'utf8');
      // Reading the flag is the point; ASSIGNING it is what must never ship.
      if (/BF_SKIP_BOOT_GATE\s*[:=]\s*['"]/.test(text)) {
        offenders.push(entry.name);
      }
    }
  };
  walk(srcDir);
  assert.deepEqual(
    offenders, [],
    'BF_SKIP_BOOT_GATE is a test/diagnostic hatch. Only app/tests/qa/harness.mjs may set it; '
    + `these shipping files do: ${offenders.join(', ')}`,
  );
});
