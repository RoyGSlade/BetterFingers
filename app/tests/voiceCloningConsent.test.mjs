// Studio -> Voice Cloning: the consent gate and the three fields it controls,
// driven through the real DOM wiring.
//
// CURRENT_UI_INVENTORY.md section 7.13 (parity rows UI-07-140, -143, -144,
// -147). This is the one control group in the product where an ungated path
// would mean uploading a recording of someone's voice without them having said
// yes, so the gate is asserted from both sides: nothing is enabled before
// consent, and nothing is uploaded if the checkbox is defeated afterwards.
//
// features/voiceStudio.js takes its backend client by injection, so the clone
// call is stubbed at `api.cloneVoice` and every upload attempt is recorded.
//
// Run with: node --test app/tests/voiceCloningConsent.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { createVoiceStudioFeature } from '../src/renderer/features/voiceStudio.js';
import { makeDocument, installDomGlobals } from './helpers/rendererDom.mjs';

const CLONE_IDS = ['voiceCloneConsent', 'voiceCloneName', 'voiceCloneFile', 'voiceCloneUploadButton', 'voiceCloneResult'];

// The rest of the Voice Studio panel init() walks. Present so the module wires
// the way it does in production rather than bailing out early.
const STUDIO_IDS = [
  'voiceBlendRows', 'voiceBlendAddButton', 'voiceBlendEffective',
  'voicePitch', 'voiceEnergy', 'voiceWarmth', 'voiceBrightness', 'voicePauseStyle',
  'voicePitchValue', 'voiceEnergyValue', 'voiceWarmthValue', 'voiceBrightnessValue',
  'voicePresetSelect', 'voicePresetName', 'voicePresetSaveButton', 'voicePresetDeleteButton',
  'profileMessage',
];

function mount({ cloneVoice } = {}) {
  const doc = makeDocument([...CLONE_IDS, ...STUDIO_IDS], {
    voiceCloneConsent: { tagName: 'input', type: 'checkbox' },
    voiceCloneName: { tagName: 'input', type: 'text', disabled: true },
    voiceCloneFile: { tagName: 'input', type: 'file', disabled: true },
    voiceCloneUploadButton: { tagName: 'button', disabled: true },
    voicePitch: { tagName: 'input', type: 'range', value: '0' },
    voiceEnergy: { tagName: 'input', type: 'range', value: '0' },
    voiceWarmth: { tagName: 'input', type: 'range', value: '0' },
    voiceBrightness: { tagName: 'input', type: 'range', value: '0' },
    voicePresetSelect: { tagName: 'select' },
    voicePresetName: { tagName: 'input', type: 'text' },
  });
  const uploads = [];
  const restore = installDomGlobals({ document: doc, betterFingers: {} });
  const feature = createVoiceStudioFeature({
    ui: { setMessage: () => {}, showToast: () => {} },
    hooks: { markProfileDirty: () => {}, renderVoiceCloningPanel: () => {} },
    api: {
      fetchTtsVoices: async () => ({ voices: [] }),
      fetchVoicePresets: async () => ({ presets: [] }),
      saveVoicePreset: async () => ({ ok: true }),
      deleteVoicePreset: async () => ({ ok: true }),
      speakTts: async () => ({ ok: true }),
      cloneVoice: cloneVoice || (async (file, name, consent) => {
        uploads.push({ filename: file?.name, name, consent });
        return { warnings: [] };
      }),
    },
  });
  feature.init({ doc });
  return { doc, feature, uploads, restore, el: (id) => doc.getElementById(id) };
}

const SAMPLE = { name: 'my-voice.wav', size: 400000 };

// --- UI-07-140 / UI-07-143: the consent checkbox gates the group -------------

test('#voiceCloneConsent starts unchecked with every field below it disabled', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);

  assert.equal(ctx.el('voiceCloneConsent').checked, false);
  assert.equal(ctx.el('voiceCloneName').disabled, true);
  assert.equal(ctx.el('voiceCloneFile').disabled, true);
  assert.equal(ctx.el('voiceCloneUploadButton').disabled, true);
  assert.ok(ctx.el('voiceCloneConsent').listenerCount('change') > 0, 'the consent checkbox was never bound');
});

test('#voiceCloneConsent enables the three fields when ticked and re-disables them when unticked', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  const consent = ctx.el('voiceCloneConsent');

  consent.checked = true;
  consent.emit('change');
  assert.equal(ctx.el('voiceCloneName').disabled, false);
  assert.equal(ctx.el('voiceCloneFile').disabled, false);
  assert.equal(ctx.el('voiceCloneUploadButton').disabled, false);

  consent.checked = false;
  consent.emit('change');
  assert.equal(ctx.el('voiceCloneName').disabled, true);
  assert.equal(ctx.el('voiceCloneFile').disabled, true);
  assert.equal(ctx.el('voiceCloneUploadButton').disabled, true);
});

test('withdrawing consent clears #voiceCloneResult so no previous outcome stands in for the new state', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  const consent = ctx.el('voiceCloneConsent');

  consent.checked = true;
  consent.emit('change');
  ctx.el('voiceCloneResult').textContent = 'Saved "old" — sample passed all quality checks.';

  consent.checked = false;
  consent.emit('change');
  assert.equal(ctx.el('voiceCloneResult').textContent, '');
});

test('an upload attempted without consent is refused and never reaches the clone call', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);

  // Stands in for anything that re-enables the button without the checkbox --
  // a stray script, an autofill, a future bug. The gate is about the upload,
  // not about the widget.
  ctx.el('voiceCloneUploadButton').disabled = false;
  ctx.el('voiceCloneFile').files = [SAMPLE];
  ctx.el('voiceCloneName').value = 'My voice';
  ctx.el('voiceCloneUploadButton').click();
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(ctx.uploads, [], 'no sample may be uploaded without consent');
  assert.equal(ctx.el('voiceCloneResult').textContent, 'Consent is required before uploading a sample.');
});

// --- UI-07-144 / UI-07-147: the name field and the result line ---------------

test('#voiceCloneName is required, and #voiceCloneResult says which piece is missing', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  const consent = ctx.el('voiceCloneConsent');
  consent.checked = true;
  consent.emit('change');

  // No file yet.
  ctx.el('voiceCloneUploadButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ctx.el('voiceCloneResult').textContent, 'Choose a WAV sample to upload.');

  // File but no name.
  ctx.el('voiceCloneFile').files = [SAMPLE];
  ctx.el('voiceCloneName').value = '   ';
  ctx.el('voiceCloneUploadButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ctx.el('voiceCloneResult').textContent, 'A voice name is required.');

  assert.deepEqual(ctx.uploads, [], 'neither incomplete attempt may reach the backend');
});

test('#voiceCloneResult reports a clean save, and the trimmed name is what gets uploaded', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  const consent = ctx.el('voiceCloneConsent');
  consent.checked = true;
  consent.emit('change');

  ctx.el('voiceCloneFile').files = [SAMPLE];
  ctx.el('voiceCloneName').value = '  My voice  ';
  ctx.el('voiceCloneUploadButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(ctx.uploads, [{ filename: 'my-voice.wav', name: 'My voice', consent: true }]);
  assert.equal(ctx.el('voiceCloneResult').textContent, 'Saved "My voice" — sample passed all quality checks.');
  assert.equal(ctx.el('voiceCloneUploadButton').disabled, false);
  assert.equal(ctx.el('voiceCloneUploadButton').textContent, 'Upload & Validate Sample');
});

test('#voiceCloneResult reports quality warnings rather than claiming a clean sample', async (t) => {
  const ctx = mount({
    cloneVoice: async () => ({ warnings: ['Background noise is high.', 'Sample is shorter than 10s.'] }),
  });
  t.after(ctx.restore);
  const consent = ctx.el('voiceCloneConsent');
  consent.checked = true;
  consent.emit('change');

  ctx.el('voiceCloneFile').files = [SAMPLE];
  ctx.el('voiceCloneName').value = 'My voice';
  ctx.el('voiceCloneUploadButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(
    ctx.el('voiceCloneResult').textContent,
    'Saved "My voice" with warnings: Background noise is high. Sample is shorter than 10s.',
  );
});

test('#voiceCloneResult carries a rejection back verbatim and leaves the button usable', async (t) => {
  const ctx = mount({
    cloneVoice: async () => {
      const error = new Error('Clone upload failed.');
      error.detail = { warnings: ['The sample is mostly silence.'] };
      throw error;
    },
  });
  t.after(ctx.restore);
  const consent = ctx.el('voiceCloneConsent');
  consent.checked = true;
  consent.emit('change');

  ctx.el('voiceCloneFile').files = [SAMPLE];
  ctx.el('voiceCloneName').value = 'My voice';
  ctx.el('voiceCloneUploadButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(ctx.el('voiceCloneResult').textContent, 'The sample is mostly silence.');
  assert.equal(ctx.el('voiceCloneUploadButton').disabled, false, 'a rejected sample must not lock the control');
});
