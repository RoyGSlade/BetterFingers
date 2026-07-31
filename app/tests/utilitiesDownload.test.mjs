// OR-07/OR-18 regression tests for the Utilities operator surfaces.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  buildWhisperModelDetails,
  buildSignalBackedDoctorModel,
  formatBytes,
} from '../src/renderer/features/utilitiesWorkspace.js';

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
