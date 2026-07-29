// Utilities -> Diagnostics and the Models panel's remaining controls, driven
// through the real DOM wiring.
//
// CURRENT_UI_INVENTORY.md sections 8 and 9 (parity rows UI-01-016, UI-08-019,
// UI-08-021, UI-09-002, UI-09-006, UI-09-010, UI-09-012, UI-09-013, UI-09-015,
// UI-09-016, UI-14-013, UI-14-014, UI-15-008, UI-15-016, UI-15-017, UI-15-018).
//
// Diagnostics is where a lie is cheapest: every panel here is a read-out, and
// a read-out that silently renders empty on a failed fetch looks exactly like a
// healthy system. So each panel is asserted twice -- once on real data, once on
// a backend that refuses -- and the failing case has to SAY it failed.
//
// Run with: node --test app/tests/utilitiesDiagnosticsPanels.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  UTILITIES_ELEMENT_IDS,
  collectUtilitiesElements,
  createUtilitiesWorkspaceFeature,
} from '../src/renderer/features/utilitiesWorkspace.js';
import { makeDocument, makeBackendBridge, installDomGlobals } from './helpers/rendererDom.mjs';

const SHELL_IDS = {
  navModels: 'sdUtilNavModels',
  navDiagnostics: 'sdUtilNavDiagnostics',
  sectionModels: 'sdUtilSectionModels',
  sectionDiagnostics: 'sdUtilSectionDiagnostics',
};

const MODELS_IDS = {
  modelsMessage: 'sdUtilModelsMessage',
  unloadTtsButton: 'sdUtilUnloadTtsButton',
  llmSelect: 'sdUtilLlmSelect',
  llmDetails: 'sdUtilLlmDetails',
  llmProgress: 'sdUtilLlmProgress',
  llmProgressLabel: 'sdUtilLlmProgressLabel',
  llmProgressPercent: 'sdUtilLlmProgressPercent',
  llmProgressFill: 'sdUtilLlmProgressFill',
};

const DIAGNOSTICS_IDS = {
  doctorRefreshButton: 'sdUtilDoctorRefreshButton',
  doctorCardsGrid: 'sdUtilDoctorCardsGrid',
  doctorRecoveryPanel: 'sdUtilDoctorRecoveryPanel',
  doctorRecoveryList: 'sdUtilDoctorRecoveryList',
  metricsHud: 'sdUtilMetricsHud',
  recordingsList: 'sdUtilRecordingsList',
  recordingsMessage: 'sdUtilRecordingsMessage',
  jobsList: 'sdUtilJobsList',
  sidecarLogsTail: 'sdUtilSidecarLogsTail',
  sidecarLogsClearButton: 'sdUtilSidecarLogsClearButton',
  copySupportReportButton: 'sdUtilCopySupportReportButton',
  refreshDiagnosticsButton: 'sdUtilRefreshDiagnosticsButton',
  sidecarStatus: 'sdUtilSidecarStatus',
  diagnosticsPathsList: 'sdUtilDiagnosticsPathsList',
  runtimeErrorsList: 'sdUtilRuntimeErrorsList',
  debugLogTail: 'sdUtilDebugLogTail',
  diagnosticsMessage: 'sdUtilDiagnosticsMessage',
};

test('the Diagnostics and Models ids this file drives are the ids the module ships', () => {
  for (const [key, id] of Object.entries({ ...SHELL_IDS, ...MODELS_IDS, ...DIAGNOSTICS_IDS })) {
    assert.equal(UTILITIES_ELEMENT_IDS[key], id, `${key} is not ${id} any more`);
  }
});

const DOCTOR_PAYLOAD = {
  stt: { loaded: false, initialized: false },
  models: { default_model_exists: false },
  recovery: { missing_model: 'Download a model from the Models section.' },
};

function mount({ routes = {}, sidecarLogs, clipboard, cancelledJobs = [] } = {}) {
  const doc = makeDocument([...Object.values(SHELL_IDS), ...Object.values(MODELS_IDS), ...Object.values(DIAGNOSTICS_IDS)], {
    sdUtilLlmSelect: { tagName: 'select' },
    sdUtilDoctorRefreshButton: { tagName: 'button' },
  });
  const bridge = makeBackendBridge(routes);
  const toasts = [];
  const clipboardWrites = [];
  const betterFingers = {
    backendRequest: bridge.request,
    writeClipboardText: clipboard || (async (text) => { clipboardWrites.push(text); }),
    getSidecarLogs: sidecarLogs === undefined ? async () => [] : sidecarLogs,
    getSidecarStatus: async () => ({ running: true, pid: 4242 }),
    // Cancelling a job is a typed IPC method, not a proxied route -- the main
    // process owns the exact path and validates the id.
    cancelJob: async (jobId) => { cancelledJobs.push(jobId); return { ok: true, status: 200, body: { cancelled: jobId } }; },
  };
  const restore = installDomGlobals({ document: doc, betterFingers });
  const feature = createUtilitiesWorkspaceFeature({
    elements: collectUtilitiesElements(doc),
    hooks: { showToast: (message, tone) => toasts.push({ message, tone }) },
  });
  return { doc, feature, bridge, toasts, clipboardWrites, cancelledJobs, restore, el: (id) => doc.getElementById(id) };
}

// --- UI-01-016: the Diagnostics section is reachable from the sub-nav --------

test('#sdUtilSectionDiagnostics is revealed by its nav button and the others are hidden', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();

  const nav = ctx.el('sdUtilNavDiagnostics');
  assert.ok(nav.listenerCount('click') > 0, 'the Diagnostics nav button was never bound');
  nav.click();

  assert.equal(ctx.feature.getSectionState().active, 'diagnostics');
  assert.equal(ctx.el('sdUtilSectionDiagnostics').hidden, false);
  assert.equal(ctx.el('sdUtilSectionModels').hidden, true);
  assert.equal(nav.getAttribute('aria-current'), 'page', 'the active section must be announced, not just styled');
});

// --- UI-09-002 / UI-14-014: the Doctor grid and its recovery panel -----------

test('#sdUtilDoctorCardsGrid renders the eight subsystem cards from GET /doctor', async (t) => {
  const ctx = mount({ routes: { 'GET /doctor?refresh_audio=true': DOCTOR_PAYLOAD } });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshDoctor();
  assert.ok(ctx.bridge.find('GET', '/doctor?refresh_audio=true'), 'the Doctor must re-probe audio when it runs');
  assert.equal(ctx.el('sdUtilDoctorCardsGrid').children.length, 8);
  assert.equal(ctx.el('sdUtilDoctorRefreshButton').disabled, false, 'the button must not stay stuck on "Running check…"');
});

test('#sdUtilDoctorRecoveryPanel appears only when the Doctor has something actionable to say', async (t) => {
  const ctx = mount({ routes: { 'GET /doctor?refresh_audio=true': DOCTOR_PAYLOAD } });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshDoctor();
  const panel = ctx.el('sdUtilDoctorRecoveryPanel');
  assert.equal(panel.hidden, false);
  assert.match(ctx.el('sdUtilDoctorRecoveryList').textContent, /Download a model from the Models section\./);

  // A healthy install has no recovery advice, and must not show an empty panel.
  ctx.feature.renderDoctorCards({
    stt: { loaded: true, initialized: true },
    llm: { loaded: true },
    models: { default_model_exists: true, llama_server_exists: true },
  });
  assert.equal(panel.hidden, true);
});

test('#sdUtilDoctorCardsGrid states the failure rather than rendering an empty grid', async (t) => {
  const ctx = mount({ routes: { 'GET /doctor?refresh_audio=true': { ok: false, status: 500, body: { detail: 'doctor crashed' } } } });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshDoctor();
  assert.match(ctx.el('sdUtilDoctorCardsGrid').textContent, /doctor crashed/);
  assert.equal(ctx.el('sdUtilDoctorRefreshButton').disabled, false);
});

// --- UI-15-017: the pipeline latency HUD -------------------------------------

test('#sdUtilMetricsHud renders per-stage timings, and says so when metrics are unavailable', async (t) => {
  const ctx = mount({ routes: { 'GET /metrics': { stages: { transcribe: { p50: 120, p95: 400, last: 130, avg: 150, count: 12 } } } } });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshMetrics();
  assert.match(ctx.el('sdUtilMetricsHud').textContent, /transcribe/);
  ctx.restore();

  const broken = mount({ routes: { 'GET /metrics': { ok: false, status: 503, body: { detail: 'metrics off' } } } });
  t.after(broken.restore);
  broken.feature.init();
  await broken.feature.refreshMetrics();
  assert.equal(broken.el('sdUtilMetricsHud').textContent, 'Metrics unavailable: metrics off');
});

// --- UI-09-006: per-recording Re-transcribe ----------------------------------

test('the Re-transcribe control on a saved recording POSTs that recording id', async (t) => {
  const ctx = mount({
    routes: {
      'GET /recordings': { recordings: [{ id: 'rec-77', duration_s: 4.2, created_at: '2026-07-28T10:00:00Z' }] },
      'POST /recordings/rec-77/retranscribe': { draft_id: 'd-9' },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshRecordings();
  const row = ctx.el('sdUtilRecordingsList').children[0];
  const retranscribe = row.querySelectorAll('.sd-btn').find((b) => b.textContent === 'Re-transcribe');
  assert.ok(retranscribe, 'every saved recording must offer a re-transcribe');

  retranscribe.click();
  await new Promise((resolve) => setImmediate(resolve));
  // The row is bound to backend.js's retranscribeRecording wrapper, whose whole
  // job is to turn a recording id into POST /recordings/:id/retranscribe -- so
  // the assertion is on the concrete path that wrapper produced.
  assert.ok(ctx.bridge.find('POST', '/recordings/rec-77/retranscribe'), 'retranscribeRecording must post to the id-scoped retranscribe route');
  assert.deepEqual(ctx.toasts, [{ message: 'Re-transcribed — check Library for the new draft.', tone: 'success' }]);
});

test('a failed re-transcribe is reported and does not claim a draft was made', async (t) => {
  const ctx = mount({
    routes: {
      'GET /recordings': { recordings: [{ id: 'rec-77', duration_s: 4.2 }] },
      'POST /recordings/rec-77/retranscribe': { ok: false, status: 500, body: { detail: 'audio file is gone' } },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshRecordings();
  ctx.el('sdUtilRecordingsList').children[0].querySelectorAll('.sd-btn')[0].click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(ctx.toasts, [{ message: 'Re-transcribe failed: audio file is gone', tone: 'danger' }]);
});

// --- UI-15-016: the active jobs list -----------------------------------------

test('#sdUtilJobsList lists active jobs with a cancel, and cancels the right one', async (t) => {
  const ctx = mount({
    routes: {
      'GET /jobs?active=1': { jobs: [{ id: 'job-1', kind: 'transcribe', state: 'running' }, { id: 'job-2', kind: 'tts', state: 'running', cancel_requested: true }] },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshJobsList();
  const rows = ctx.el('sdUtilJobsList').children;
  assert.equal(rows.length, 2);
  const cancel = rows[0].querySelectorAll('.sd-btn')[0];
  assert.equal(cancel.textContent, 'Cancel');
  assert.equal(rows[1].querySelectorAll('.sd-btn')[0].disabled, true, 'a job already cancelling must not offer cancel again');

  cancel.click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(ctx.cancelledJobs, ['job-1'], 'the cancel must name the job it belongs to');
});

test('#sdUtilJobsList says "no active jobs" rather than leaving an ambiguous blank', async (t) => {
  const ctx = mount({ routes: { 'GET /jobs?active=1': { jobs: [] } } });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshJobsList();
  assert.equal(ctx.el('sdUtilJobsList').textContent, 'No active jobs.');
});

// --- UI-09-010 / UI-15-018: the three distinct log surfaces ------------------

test('#sdUtilSidecarLogsTail is fed by the sidecar bridge, and its Clear is client-side only', async (t) => {
  const ctx = mount({ sidecarLogs: async () => ['sidecar: started', 'sidecar: bound :8000'] });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshSidecarLogs();
  assert.equal(ctx.el('sdUtilSidecarLogsTail').textContent, 'sidecar: started\nsidecar: bound :8000');

  ctx.el('sdUtilSidecarLogsClearButton').click();
  assert.equal(ctx.el('sdUtilSidecarLogsTail').textContent, 'No sidecar logs yet.');
  assert.deepEqual(ctx.bridge.signatures(), [], 'clearing the visible tail must not delete anything on disk');
});

test('the debug.log tail and the runtime error list are separate surfaces with separate sources', async (t) => {
  const ctx = mount({
    routes: {
      'GET /diagnostics/logs?lines=80': { lines: ['2026-07-28 boot', '2026-07-28 ready'] },
      'GET /runtime/errors': { errors: [{ severity: 'fatal', component: 'stt', message: 'model not found' }] },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshDebugLogTail();
  await ctx.feature.refreshRuntimeErrors();

  assert.equal(ctx.el('sdUtilDebugLogTail').textContent, '2026-07-28 boot\n2026-07-28 ready');
  assert.equal(ctx.el('sdUtilRuntimeErrorsList').textContent, '[fatal] stt: model not found');
  assert.ok(ctx.bridge.find('GET', '/diagnostics/logs?lines=80'));
  assert.ok(ctx.bridge.find('GET', '/runtime/errors'));
});

// --- UI-09-016: the runtime error list's own rules ---------------------------

test('#sdUtilRuntimeErrorsList shows the last eight, newest first', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();

  const errors = Array.from({ length: 12 }, (_v, i) => ({ severity: 'recoverable', component: 'runtime', message: `error ${i}` }));
  ctx.feature.renderRuntimeErrors(errors);
  const rows = ctx.el('sdUtilRuntimeErrorsList').children.map((r) => r.textContent);
  assert.equal(rows.length, 8);
  assert.match(rows[0], /error 11/, 'the newest error must be at the top');
  assert.match(rows[7], /error 4/);
});

test('#sdUtilRuntimeErrorsList states that nothing went wrong rather than rendering nothing', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();
  ctx.feature.renderRuntimeErrors([]);
  assert.equal(ctx.el('sdUtilRuntimeErrorsList').textContent, 'No runtime errors recorded.');
});

// --- UI-09-015: the paths dump ------------------------------------------------

test('#sdUtilDiagnosticsPathsList dumps GET /diagnostics/paths, and reports a failure in place', async (t) => {
  const ctx = mount({
    routes: {
      'GET /diagnostics/paths': { debug_log: '/home/u/.betterfingers/debug.log', models_dir: '/home/u/models', default_model_exists: true },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshDiagnosticsPaths();
  const text = ctx.el('sdUtilDiagnosticsPathsList').textContent;
  assert.match(text, /debug_log/);
  assert.match(text, /\/home\/u\/models/);
  ctx.restore();

  const broken = mount({ routes: { 'GET /diagnostics/paths': { ok: false, status: 500, body: { detail: 'no such user' } } } });
  t.after(broken.restore);
  broken.feature.init();
  await broken.feature.refreshDiagnosticsPaths();
  assert.equal(broken.el('sdUtilDiagnosticsPathsList').textContent, 'Paths unavailable: no such user');
});

// --- UI-09-012 / UI-15-008: the support report --------------------------------

test('#sdUtilCopySupportReportButton fetches the markdown report and puts it on the clipboard', async (t) => {
  const ctx = mount({ routes: { 'GET /diagnostics/support-report': { markdown: '# BetterFingers support report\n- platform: linux' } } });
  t.after(ctx.restore);
  ctx.feature.init();

  const button = ctx.el('sdUtilCopySupportReportButton');
  assert.ok(button.listenerCount('click') > 0, 'Copy Support Report was never bound');
  button.click();
  await new Promise((resolve) => setImmediate(resolve));

  assert.ok(ctx.bridge.find('GET', '/diagnostics/support-report'));
  assert.deepEqual(ctx.clipboardWrites, ['# BetterFingers support report\n- platform: linux']);
  assert.deepEqual(ctx.toasts, [{ message: 'Support report copied to clipboard.', tone: 'success' }]);
});

test('a failed support report does not silently copy an error object to the clipboard', async (t) => {
  const ctx = mount({ routes: { 'GET /diagnostics/support-report': { ok: false, status: 500, body: { detail: 'report generator failed' } } } });
  t.after(ctx.restore);
  ctx.feature.init();

  ctx.el('sdUtilCopySupportReportButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(ctx.clipboardWrites, []);
  assert.equal(ctx.el('sdUtilDiagnosticsMessage').textContent, 'Support report failed: report generator failed');
});

// --- UI-09-013: Refresh Diagnostics fans out ---------------------------------

test('#sdUtilRefreshDiagnosticsButton fans out to every diagnostics source in one click', async (t) => {
  const ctx = mount({
    routes: {
      'GET /doctor?refresh_audio=true': DOCTOR_PAYLOAD,
      'GET /metrics': { stages: {} },
      'GET /recordings': { recordings: [] },
      'GET /jobs?active=1': { jobs: [] },
      'GET /diagnostics/paths': { debug_log: '/tmp/x' },
      'GET /runtime/errors': { errors: [] },
      'GET /diagnostics/logs?lines=80': { lines: [] },
    },
  });
  t.after(ctx.restore);
  ctx.feature.init();

  const button = ctx.el('sdUtilRefreshDiagnosticsButton');
  assert.ok(button.listenerCount('click') > 0, 'Refresh Diagnostics was never bound');
  button.click();
  await new Promise((resolve) => setTimeout(resolve, 0));

  const reached = ctx.bridge.signatures();
  for (const route of ['GET /doctor?refresh_audio=true', 'GET /metrics', 'GET /recordings', 'GET /jobs?active=1', 'GET /diagnostics/paths', 'GET /runtime/errors', 'GET /diagnostics/logs?lines=80']) {
    assert.ok(reached.includes(route), `Refresh Diagnostics never reached ${route}`);
  }
  assert.equal(ctx.el('sdUtilSidecarStatus').textContent, '{"running":true,"pid":4242}');
});

// --- UI-08-019 / UI-08-021: Runtime Memory and the shared models status line --

test('#sdUtilUnloadTtsButton unloads only the TTS component', async (t) => {
  const ctx = mount({ routes: { 'POST /models/unload/tts': { unloaded: 'tts' } } });
  t.after(ctx.restore);
  ctx.feature.init();

  const button = ctx.el('sdUtilUnloadTtsButton');
  assert.ok(button.listenerCount('click') > 0, 'Unload TTS was never bound');
  button.click();
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(ctx.bridge.signatures(), ['POST /models/unload/tts']);
  assert.deepEqual(ctx.toasts, [{ message: 'TTS unloaded.', tone: 'success' }]);
});

test('#sdUtilModelsMessage is the one line every Models action reports through', async (t) => {
  const ctx = mount({ routes: { 'POST /models/unload/tts': { ok: false, status: 500, body: { detail: 'tts is busy' } } } });
  t.after(ctx.restore);
  ctx.feature.init();

  ctx.el('sdUtilUnloadTtsButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ctx.el('sdUtilModelsMessage').textContent, 'Unload failed: tts is busy');

  // …and the same line carries a wake-model failure, which is why it is shared.
  ctx.bridge.reset();
  await ctx.feature.refreshWakeBackbones();
  assert.match(ctx.el('sdUtilModelsMessage').textContent, /Wake models unavailable/);
});

// --- UI-14-013: the model download progress bar -------------------------------

test('#sdUtilLlmProgressFill tracks a live download and disappears when there is none', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();

  ctx.feature.setModelPayloads({
    models: [{ id: 'gemma', name: 'Gemma', installed: false }],
    download_state: { status: 'downloading', percent: 42, model_id: 'gemma' },
  }, null);
  assert.equal(ctx.el('sdUtilLlmProgress').hidden, false);
  assert.equal(ctx.el('sdUtilLlmProgressPercent').textContent, '42%');
  assert.equal(ctx.el('sdUtilLlmProgressFill').style.width, '42%');

  ctx.feature.setModelPayloads({ models: [{ id: 'gemma', name: 'Gemma', installed: true }], download_state: null }, null);
  assert.equal(ctx.el('sdUtilLlmProgress').hidden, true);
  assert.equal(ctx.el('sdUtilLlmProgressPercent').textContent, '');
});
