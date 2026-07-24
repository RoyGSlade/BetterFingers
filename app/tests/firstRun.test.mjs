// Unit tests for the first-run "get set up" checklist (W8).
// Run with: node --test app/tests/firstRun.test.mjs
//
// No jsdom in this repo's test setup (see messageRescuePanel.test.mjs) -- the
// pure "what's missing" computation is exercised directly with plain data,
// and the DOM-wiring feature is exercised against small stub elements with
// network calls injected via the `api` override (same pattern as
// voiceStudio.test.mjs's makeApiStub), so nothing here touches a real
// backend or Electron bridge.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  formatBytes,
  summarizeLlmState,
  summarizeWhisperState,
  computeFirstRunStatus,
  formatDownloadOutcomeMessage,
  isDiskSpaceMessage,
  createFirstRunFeature,
} from '../src/renderer/features/firstRun.js';

// --- formatBytes --------------------------------------------------------------

test('formatBytes: non-finite/zero/negative values are empty', () => {
  assert.equal(formatBytes(0), '');
  assert.equal(formatBytes(-5), '');
  assert.equal(formatBytes(NaN), '');
  assert.equal(formatBytes(undefined), '');
});

test('formatBytes: scales through units', () => {
  assert.equal(formatBytes(512), '512 B');
  assert.equal(formatBytes(2048), '2.0 KB');
  assert.equal(formatBytes(5 * 1024 * 1024), '5.0 MB');
  assert.equal(formatBytes(3 * 1024 * 1024 * 1024), '3.0 GB');
});

// --- summarizeLlmState ---------------------------------------------------------

test('summarizeLlmState: no models payload is all-false, not a throw', () => {
  const state = summarizeLlmState(null);
  assert.equal(state.installed, false);
  assert.equal(state.ready, false);
  assert.equal(state.runtimeExists, false);
  assert.equal(state.selectedId, null);
  assert.equal(state.name, null);
});

test('summarizeLlmState: installed and ready', () => {
  const state = summarizeLlmState({
    models: [{ id: 'gemma', name: 'Gemma', installed: true, ready: true, size_mb: 4000 }],
    selected_model_id: 'gemma',
    llama_server_exists: true,
  });
  assert.equal(state.installed, true);
  assert.equal(state.ready, true);
  assert.equal(state.runtimeExists, true);
  assert.equal(state.name, 'Gemma');
  assert.equal(state.sizeMb, 4000);
});

test('summarizeLlmState: installed but not ready (runtime outdated/incompatible)', () => {
  const state = summarizeLlmState({
    models: [{ id: 'gemma', name: 'Gemma', installed: true, ready: false }],
    selected_model_id: 'gemma',
    llama_server_exists: true,
  });
  assert.equal(state.installed, true);
  assert.equal(state.ready, false);
});

// --- summarizeWhisperState -----------------------------------------------------

test('summarizeWhisperState: none installed', () => {
  const state = summarizeWhisperState({
    models: [{ model_size: 'base.en', installed: false }],
    selected_model_size: 'base.en',
  });
  assert.equal(state.selectedInstalled, false);
  assert.equal(state.anyInstalled, false);
  assert.equal(state.installedCount, 0);
});

test('summarizeWhisperState: a different model is installed than the selected one -- still counts as ready material', () => {
  const state = summarizeWhisperState({
    models: [
      { model_size: 'base.en', installed: false },
      { model_size: 'small.en', installed: true },
    ],
    selected_model_size: 'base.en',
  });
  assert.equal(state.selectedInstalled, false);
  assert.equal(state.anyInstalled, true);
  assert.equal(state.installedCount, 1);
});

// --- computeFirstRunStatus -----------------------------------------------------

test('computeFirstRunStatus: everything null -- backend unreachable, not ready, missing lists "backend"', () => {
  const status = computeFirstRunStatus({});
  assert.equal(status.backendReachable, false);
  assert.equal(status.ready, false);
  assert.ok(status.missing.some((m) => m.key === 'backend'));
});

test('computeFirstRunStatus: fully ready -- runtime + llm + whisper all installed, nothing missing', () => {
  const status = computeFirstRunStatus({
    health: { status: 'active' },
    runtime: { llm_ready: true },
    llmModels: {
      models: [{ id: 'gemma', name: 'Gemma', installed: true, ready: true }],
      selected_model_id: 'gemma',
      llama_server_exists: true,
    },
    whisperModels: {
      models: [{ model_size: 'base.en', installed: true }],
      selected_model_size: 'base.en',
    },
  });
  assert.equal(status.ready, true);
  assert.deepEqual(status.missing, []);
});

test('computeFirstRunStatus: llama-server runtime missing is flagged even if the LLM itself claims ready', () => {
  const status = computeFirstRunStatus({
    health: { status: 'active' },
    llmModels: {
      models: [{ id: 'gemma', installed: true, ready: true }],
      selected_model_id: 'gemma',
      llama_server_exists: false,
    },
    whisperModels: { models: [{ model_size: 'base.en', installed: true }], selected_model_size: 'base.en' },
  });
  assert.equal(status.ready, false);
  assert.ok(status.missing.some((m) => m.key === 'runtime'));
});

test('computeFirstRunStatus: LLM not installed', () => {
  const status = computeFirstRunStatus({
    health: { status: 'active' },
    llmModels: { models: [], selected_model_id: null, llama_server_exists: true },
    whisperModels: { models: [{ model_size: 'base.en', installed: true }], selected_model_size: 'base.en' },
  });
  assert.equal(status.ready, false);
  assert.ok(status.missing.some((m) => m.key === 'llm'));
});

test('computeFirstRunStatus: LLM installed but not ready gets its own distinct missing entry', () => {
  const status = computeFirstRunStatus({
    health: { status: 'active' },
    llmModels: {
      models: [{ id: 'gemma', name: 'Gemma', installed: true, ready: false }],
      selected_model_id: 'gemma',
      llama_server_exists: true,
    },
    whisperModels: { models: [{ model_size: 'base.en', installed: true }], selected_model_size: 'base.en' },
  });
  assert.equal(status.ready, false);
  assert.ok(status.missing.some((m) => m.key === 'llm-not-ready'));
  assert.ok(!status.missing.some((m) => m.key === 'llm'));
});

test('computeFirstRunStatus: no Whisper model installed', () => {
  const status = computeFirstRunStatus({
    health: { status: 'active' },
    llmModels: {
      models: [{ id: 'gemma', installed: true, ready: true }],
      selected_model_id: 'gemma',
      llama_server_exists: true,
    },
    whisperModels: { models: [{ model_size: 'base.en', installed: false }], selected_model_size: 'base.en' },
  });
  assert.equal(status.ready, false);
  assert.ok(status.missing.some((m) => m.key === 'whisper'));
});

// --- formatDownloadOutcomeMessage / isDiskSpaceMessage --------------------------

test('formatDownloadOutcomeMessage: prefers the backend message over the fallback', () => {
  assert.equal(
    formatDownloadOutcomeMessage({ ok: false, message: 'Not enough disk space to download this file.' }, 'Download failed.'),
    'Not enough disk space to download this file.',
  );
});

test('formatDownloadOutcomeMessage: falls back on missing/blank/non-object results', () => {
  assert.equal(formatDownloadOutcomeMessage(null, 'fallback'), 'fallback');
  assert.equal(formatDownloadOutcomeMessage({}, 'fallback'), 'fallback');
  assert.equal(formatDownloadOutcomeMessage({ message: '   ' }, 'fallback'), 'fallback');
});

test('isDiskSpaceMessage: recognizes model_manager.py\'s InsufficientDiskSpaceError wording', () => {
  const message =
    'Not enough disk space to download this file: need 4.4 GB free, only 1.2 GB available at /home/user/.betterfingers/models.';
  assert.equal(isDiskSpaceMessage(message), true);
});

test('isDiskSpaceMessage: unrelated failures are not mistaken for a disk-space error', () => {
  assert.equal(isDiskSpaceMessage('Failed to load Whisper \'base.en\'.'), false);
  assert.equal(isDiskSpaceMessage(''), false);
  assert.equal(isDiskSpaceMessage(null), false);
});

// --- createFirstRunFeature (DOM wiring, stubbed api + elements) ----------------

function makeStubElement() {
  return {
    textContent: '', hidden: false, disabled: false, dataset: {}, style: {},
    _listeners: {},
    addEventListener(evt, fn) {
      (this._listeners[evt] ||= []).push(fn);
    },
  };
}

function fireClick(el) {
  (el._listeners.click || []).forEach((fn) => fn({ target: el }));
}

function makeElements() {
  return {
    panelEl: makeStubElement(),
    overallBadgeEl: makeStubElement(),
    diskWarningEl: makeStubElement(),
    diskWarningMessageEl: makeStubElement(),
    runtimeBadgeEl: makeStubElement(),
    runtimeDetailEl: makeStubElement(),
    llmBadgeEl: makeStubElement(),
    llmDetailEl: makeStubElement(),
    whisperBadgeEl: makeStubElement(),
    whisperDetailEl: makeStubElement(),
    downloadLlmButton: makeStubElement(),
    llmProgress: {
      container: makeStubElement(),
      label: makeStubElement(),
      percent: makeStubElement(),
      fill: makeStubElement(),
      bytes: makeStubElement(),
    },
    downloadWhisperButton: makeStubElement(),
    whisperProgress: {
      container: makeStubElement(),
      label: makeStubElement(),
      percent: makeStubElement(),
      fill: makeStubElement(),
      bytes: makeStubElement(),
    },
    messageEl: makeStubElement(),
    refreshButton: makeStubElement(),
    continueButton: makeStubElement(),
    dismissButton: makeStubElement(),
  };
}

function makeUi() {
  const messages = [];
  const toasts = [];
  return {
    ui: {
      setMessage(el, text, tone) {
        if (el) {
          el.textContent = text;
          el.dataset.tone = tone;
        }
        messages.push({ text, tone });
      },
      showToast(text, tone, durationMs) {
        toasts.push({ text, tone, durationMs });
      },
    },
    messages,
    toasts,
  };
}

function makeApiStub(overrides = {}) {
  return {
    fetchHealth: async () => ({ status: 'active', transcriber: true, llm_engine: true }),
    fetchRuntimeStatus: async () => ({ llm_ready: true }),
    fetchLlmModels: async () => ({
      models: [{ id: 'gemma', name: 'Gemma', installed: true, ready: true, size_mb: 4000 }],
      selected_model_id: 'gemma',
      llama_server_exists: true,
    }),
    fetchWhisperModels: async () => ({
      models: [{ model_size: 'base.en', installed: true }],
      selected_model_size: 'base.en',
    }),
    fetchLlmDownloadState: async () => ({ status: 'downloading', percent: 50, message: 'Downloading...' }),
    downloadLlmModel: async () => ({ ok: true, message: 'Language model download complete.' }),
    downloadWhisperModel: async () => ({ ok: true, message: 'Speech model download complete.' }),
    ...overrides,
  };
}

// createFirstRunFeature takes an injectable `storage` (Web Storage-shaped)
// dependency for exactly this reason -- a real `localStorage`/`globalThis`
// swap is unreliable across Node versions (Node 24 ships a built-in
// `localStorage` that doesn't behave like a plain reassignable global), so
// tests pass a tiny in-memory fake directly instead of touching the global.
function makeFakeStorage() {
  const store = new Map();
  return {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
}

test('init(): fully ready -- panel stays hidden, badges read Ready/Found/Installed', async () => {
  const elements = makeElements();
  const { ui } = makeUi();
  const feature = createFirstRunFeature({ elements, ui, hooks: {}, api: makeApiStub(), storage: makeFakeStorage() });

  const status = await feature.init();

  assert.equal(status.ready, true);
  assert.equal(elements.panelEl.hidden, true);
  assert.equal(elements.overallBadgeEl.textContent, 'Ready');
  assert.equal(elements.runtimeBadgeEl.textContent, 'Found');
  assert.equal(elements.llmBadgeEl.textContent, 'Ready');
  assert.equal(elements.whisperBadgeEl.textContent, 'Installed');
  assert.equal(elements.continueButton.disabled, false);
});

test('init(): not ready -- panel shows, missing pieces render as Missing/danger', async () => {
  const elements = makeElements();
  const { ui } = makeUi();
  const api = makeApiStub({
    fetchLlmModels: async () => ({ models: [], selected_model_id: null, llama_server_exists: false }),
    fetchWhisperModels: async () => ({ models: [], selected_model_size: null }),
  });
  const feature = createFirstRunFeature({ elements, ui, hooks: {}, api, storage: makeFakeStorage() });

  const status = await feature.init();

  assert.equal(status.ready, false);
  assert.equal(elements.panelEl.hidden, false);
  assert.equal(elements.runtimeBadgeEl.textContent, 'Missing');
  assert.equal(elements.runtimeBadgeEl.dataset.tone, 'danger');
  assert.equal(elements.llmBadgeEl.textContent, 'Missing');
  assert.equal(elements.whisperBadgeEl.textContent, 'Missing');
  assert.equal(elements.continueButton.disabled, true);
  assert.equal(elements.downloadLlmButton.disabled, false);
});

test('init(): backend totally unreachable -- never blank, shows a clear "waiting" message instead', async () => {
  const elements = makeElements();
  const { ui, messages } = makeUi();
  const api = makeApiStub({
    fetchHealth: async () => { throw new Error('ECONNREFUSED'); },
    fetchRuntimeStatus: async () => { throw new Error('ECONNREFUSED'); },
    fetchLlmModels: async () => { throw new Error('ECONNREFUSED'); },
    fetchWhisperModels: async () => { throw new Error('ECONNREFUSED'); },
  });
  const feature = createFirstRunFeature({ elements, ui, hooks: {}, api, storage: makeFakeStorage() });

  const status = await feature.init();

  assert.equal(status, null);
  assert.equal(elements.panelEl.hidden, false);
  assert.equal(elements.overallBadgeEl.textContent, 'Unavailable');
  assert.ok(messages.some((m) => /backend/i.test(m.text) && m.tone === 'warning'));
});

test('init(): not ready but previously dismissed -- stays hidden', async () => {
  const elements = makeElements();
  const { ui } = makeUi();
  const storage = makeFakeStorage();
  storage.setItem('bf_first_run_dismissed', 'true');
  const api = makeApiStub({
    fetchLlmModels: async () => ({ models: [], selected_model_id: null, llama_server_exists: false }),
  });
  const feature = createFirstRunFeature({ elements, ui, hooks: {}, api, storage });

  await feature.init();

  assert.equal(elements.panelEl.hidden, true);
});

test('dismiss button: hides the panel, persists the flag, and routes to the Models tab', async () => {
  const elements = makeElements();
  const { ui } = makeUi();
  const storage = makeFakeStorage();
  let wentToModels = false;
  const api = makeApiStub({
    fetchLlmModels: async () => ({ models: [], selected_model_id: null, llama_server_exists: false }),
  });
  const feature = createFirstRunFeature({
    elements, ui, hooks: { goToModelsTab: () => { wentToModels = true; } }, api, storage,
  });

  await feature.init();
  assert.equal(elements.panelEl.hidden, false);

  fireClick(elements.dismissButton);

  assert.equal(elements.panelEl.hidden, true);
  assert.equal(wentToModels, true);
  assert.equal(storage.getItem('bf_first_run_dismissed'), 'true');
});

test('downloadLlm: success path re-enables the button, reports success, and syncs the rest of the app', async () => {
  const elements = makeElements();
  const { ui, messages, toasts } = makeUi();
  let afterModelsChangedCalls = 0;
  const api = makeApiStub({
    fetchLlmModels: async () => ({ models: [], selected_model_id: 'gemma', llama_server_exists: false }),
    downloadLlmModel: async (modelId) => {
      assert.equal(modelId, 'gemma');
      return { ok: true, message: 'Language model download complete.' };
    },
  });
  const feature = createFirstRunFeature({
    elements, ui, hooks: { afterModelsChanged: () => { afterModelsChangedCalls += 1; } }, api,
    storage: makeFakeStorage(),
  });
  await feature.init();

  fireClick(elements.downloadLlmButton);
  // Let the download's microtask chain (and the trailing refreshStatus()) settle.
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(elements.downloadLlmButton.disabled, false);
  assert.equal(elements.llmProgress.fill.dataset.tone, 'success');
  assert.ok(messages.some((m) => m.text === 'Language model download complete.' && m.tone === 'success'));
  assert.ok(toasts.some((t) => t.tone === 'success'));
  assert.equal(afterModelsChangedCalls, 1);
});

test('downloadLlm: disk-space failure surfaces the exact backend message, not a generic one', async () => {
  const elements = makeElements();
  const { ui, messages } = makeUi();
  const diskMessage = 'Not enough disk space to download this file: need 4.4 GB free, only 1.2 GB available at /models.';
  const api = makeApiStub({
    fetchLlmModels: async () => ({ models: [], selected_model_id: 'gemma', llama_server_exists: false }),
    downloadLlmModel: async () => ({ ok: false, message: diskMessage }),
  });
  const feature = createFirstRunFeature({ elements, ui, hooks: {}, api, storage: makeFakeStorage() });
  await feature.init();

  fireClick(elements.downloadLlmButton);
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(elements.diskWarningEl.hidden, false);
  assert.equal(elements.diskWarningMessageEl.textContent, diskMessage);
  assert.equal(elements.messageEl.textContent, diskMessage);
  assert.equal(elements.messageEl.dataset.tone, 'danger');
  assert.equal(elements.downloadLlmButton.disabled, false);
  assert.ok(messages.some((m) => m.text === diskMessage));
});

test('downloadLlm: a thrown transport error (e.g. bridge unavailable) still shows its own message, never a blank state', async () => {
  const elements = makeElements();
  const { ui } = makeUi();
  const api = makeApiStub({
    fetchLlmModels: async () => ({ models: [], selected_model_id: 'gemma', llama_server_exists: false }),
    downloadLlmModel: async () => { throw new Error('Backend bridge is unavailable.'); },
  });
  const feature = createFirstRunFeature({ elements, ui, hooks: {}, api, storage: makeFakeStorage() });
  await feature.init();

  fireClick(elements.downloadLlmButton);
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(elements.messageEl.textContent, 'Backend bridge is unavailable.');
  assert.equal(elements.messageEl.dataset.tone, 'danger');
  assert.equal(elements.downloadLlmButton.disabled, false);
});

test('downloadLlm: no model selected -- shows guidance and never calls the download endpoint', async () => {
  const elements = makeElements();
  const { ui } = makeUi();
  let downloadCalls = 0;
  const api = makeApiStub({
    fetchLlmModels: async () => ({ models: [], selected_model_id: null, llama_server_exists: false }),
    downloadLlmModel: async () => { downloadCalls += 1; return { ok: true }; },
  });
  const feature = createFirstRunFeature({ elements, ui, hooks: {}, api, storage: makeFakeStorage() });
  await feature.init();

  fireClick(elements.downloadLlmButton);
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(downloadCalls, 0);
  assert.match(elements.messageEl.textContent, /Models tab/);
});

test('downloadWhisper: success path polls GET /models/whisper for progress (no dedicated download-state route) and reports success', async () => {
  const elements = makeElements();
  const { ui, messages } = makeUi();
  const api = makeApiStub({
    fetchWhisperModels: async () => ({ models: [{ model_size: 'base.en', installed: false }], selected_model_size: 'base.en' }),
    downloadWhisperModel: async (modelSize) => {
      assert.equal(modelSize, 'base.en');
      return { ok: true, message: 'Speech model download complete.' };
    },
  });
  const feature = createFirstRunFeature({ elements, ui, hooks: {}, api, storage: makeFakeStorage() });
  await feature.init();

  fireClick(elements.downloadWhisperButton);
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.ok(messages.some((m) => m.text === 'Speech model download complete.' && m.tone === 'success'));
  assert.equal(elements.downloadWhisperButton.disabled, false);
});
