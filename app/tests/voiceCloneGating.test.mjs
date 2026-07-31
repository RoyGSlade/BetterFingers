import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  canUploadVoiceClone,
  normalizeVoiceCloningAvailability,
} from '../src/renderer/features/voiceStudio.js';

test('voice cloning is gated when the backend explicitly reports its model missing', () => {
  const status = normalizeVoiceCloningAvailability({
    available: false,
    reason: 'voice-cloning dependencies not installed (kanade_tokenizer)',
    setup_hint: 'Install the voice-cloning runtime from the models page.',
  });

  assert.deepEqual(status, {
    known: true,
    available: false,
    message: 'Voice cloning requires its model. Install voice cloning before uploading a sample.',
  });
  assert.equal(canUploadVoiceClone(status), false);
});

test('voice cloning is enabled only after an explicit available report', () => {
  assert.equal(canUploadVoiceClone({ available: true, mechanism: 'side-runtime' }), true);
  assert.equal(canUploadVoiceClone({ installed: false }), false, 'legacy payload is unknown, not claimed ready');
  assert.equal(
    normalizeVoiceCloningAvailability({ installed: false }).message,
    'Checking whether the voice-cloning model is available…',
  );
});
