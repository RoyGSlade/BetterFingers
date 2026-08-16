// OR-07/OR-18 regression tests for the Utilities operator surfaces.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  UTILITIES_ELEMENT_IDS,
  buildWhisperModelDetails,
  buildSignalBackedDoctorModel,
  collectUtilitiesElements,
  createUtilitiesWorkspaceFeature,
  formatBytes,
} from '../src/renderer/features/utilitiesWorkspace.js';
import { installDomGlobals, makeBackendBridge, makeDocument } from './helpers/rendererDom.mjs';

const MODEL_IDS = {
  modelsMessage: 'sdUtilModelsMessage',
  modelsStatusSummary: 'sdUtilModelsStatusSummary',
  llmSelect: 'sdUtilLlmSelect',
  llmDownloadButton: 'sdUtilLlmDownloadButton',
  llmBadge: 'sdUtilLlmBadge',
  llmDetails: 'sdUtilLlmDetails',
  llmProgress: 'sdUtilLlmProgress',
  llmProgressLabel: 'sdUtilLlmProgressLabel',
  llmProgressPercent: 'sdUtilLlmProgressPercent',
  llmProgressFill: 'sdUtilLlmProgressFill',
};

function mountModels(routes) {
  const doc = makeDocument(Object.values(MODEL_IDS), {
    sdUtilLlmSelect: { tagName: 'select' },
    sdUtilLlmDownloadButton: { tagName: 'button' },
  });
  const bridge = makeBackendBridge(routes);
  const restore = installDomGlobals({ document: doc, betterFingers: { backendRequest: bridge.request } });
  const feature = createUtilitiesWorkspaceFeature({ elements: collectUtilitiesElements(doc) });
  feature.init();
  feature.setModelPayloads({
    selected_model_id: 'gemma',
    models: [{ id: 'gemma', name: 'Gemma', installed: false }],
  }, { selected_model_size: 'base.en', models: [] });
  return { bridge, feature, restore, el: (id) => doc.getElementById(id) };
}

async function flushAsyncWork() {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
}

test('the model download test ids match the Utilities module contract', () => {
  for (const [key, id] of Object.entries(MODEL_IDS)) {
    assert.equal(UTILITIES_ELEMENT_IDS[key], id);
  }
});

test('a background LLM download reaches a terminal state before inventory verification', async (t) => {
  let terminalStateRead = false;
  const ctx = mountModels({
    'POST /models/llm/gemma/download': { ok: true, background: true, message: 'Started background download.' },
    'GET /models/llm/gemma/download-state': () => {
      terminalStateRead = true;
      return { status: 'ready', active: false, installed: true, percent: 100, message: 'Gemma and runtime are ready.' };
    },
    'GET /models/llm': () => ({
      selected_model_id: 'gemma',
      models: [{ id: 'gemma', name: 'Gemma', installed: terminalStateRead }],
    }),
    'GET /models/whisper': { selected_model_size: 'base.en', models: [] },
  });
  t.after(ctx.restore);

  ctx.el('sdUtilLlmDownloadButton').click();
  await flushAsyncWork();

  assert.ok(ctx.bridge.find('GET', '/models/llm/gemma/download-state'), 'the background job was never followed');
  assert.equal(ctx.el('sdUtilModelsMessage').textContent, 'Verified by the model inventory; Installed and Ready.');
  assert.equal(ctx.el('sdUtilModelsMessage').dataset.tone, 'success');
});

test('a failed background LLM download reports the backend failure instead of an inventory race', async (t) => {
  const ctx = mountModels({
    'POST /models/llm/gemma/download': { ok: true, background: true, message: 'Started background download.' },
    'GET /models/llm/gemma/download-state': {
      status: 'error', active: false, installed: false, message: 'Not enough disk space.',
    },
    'GET /models/llm': {
      selected_model_id: 'gemma', models: [{ id: 'gemma', name: 'Gemma', installed: false }],
    },
    'GET /models/whisper': { selected_model_size: 'base.en', models: [] },
  });
  t.after(ctx.restore);

  ctx.el('sdUtilLlmDownloadButton').click();
  await flushAsyncWork();

  assert.equal(ctx.el('sdUtilModelsMessage').textContent, 'Not enough disk space.');
  assert.equal(ctx.el('sdUtilModelsMessage').dataset.tone, 'danger');
  assert.doesNotMatch(ctx.el('sdUtilModelsMessage').textContent, /inventory did not confirm/);
});

test('Whisper details explain the choice and show an explicit ready state after inventory confirmation', () => {
  const details = buildWhisperModelDetails(
    { model_size: 'tiny.en', installed: true, size_bytes: 157286400 },
    { selected_model_size: 'tiny.en' },
    { status: 'complete', percent: 100, message: 'Download complete.' },
    { status: 'verified', message: 'Verified by the model inventory; Installed and Ready.' },
  );
  const values = Object.fromEntries(details.rows.map(({ label, value }) => [label, value]));
  assert.equal(details.state, 'Installed and Ready');
  assert.equal(values.Name, 'tiny.en');
  assert.match(values.Type, /Whisper/);
  assert.match(values['Download size'], /estimated/);
  assert.equal(values['Installed size'], '150 MB');
  assert.match(values.Purpose, /Transcribes/);
  assert.match(values['Quality / speed'], /Fastest/);
  assert.match(values['Recommended hardware'], /CPU/);
  assert.match(values.Verification, /Installed and Ready/);
});

test('Whisper details do not claim verification before a model is installed', () => {
  const details = buildWhisperModelDetails(
    { model_size: 'base.en', installed: false, size_bytes: 0 },
    { selected_model_size: 'base.en' },
    { status: 'downloading', percent: 20, message: 'Downloading Whisper.' },
  );
  const values = Object.fromEntries(details.rows.map(({ label, value }) => [label, value]));
  assert.equal(details.state, 'Downloading');
  assert.match(values.Verification, /Not verified/);
  assert.match(values.Progress, /Downloading/);
});

test('Doctor rendering model only includes subsystem keys backed by the response', () => {
  const model = buildSignalBackedDoctorModel({
    stt: { initialized: true, loaded: true, model_size: 'tiny.en' },
    errors: [{ message: 'ignored here; runtime errors have their own panel' }],
  });
  assert.deepEqual(model.cards.map((card) => card.id), ['stt']);
});

test('formatBytes converts measured installed bytes and rejects unknown values', () => {
  assert.equal(formatBytes(1024 * 1024 * 1024), '1.0 GB');
  assert.equal(formatBytes(0), 'unknown');
});
