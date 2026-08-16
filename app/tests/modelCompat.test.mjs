import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  SMALLEST_SUPPORTED_TTS_MODEL,
  TTS_MODEL_COMPATIBILITY,
  assessTtsCompatibility,
} from '../src/renderer/lib/modelCompat.mjs';

test('unknown runtime/model pairs remain offered with a caution', () => {
  const result = assessTtsCompatibility({
    runtime: 'future-runtime',
    model: 'user-installed-tts-model',
    voiceId: 'user_voice',
  });

  assert.equal(result.known, false);
  assert.equal(result.knownBad, false);
  assert.equal(result.offered, true, 'missing table rows must fail open');
  assert.match(result.caution, /may not be supported by the selected runtime/);
});

test('native runtime flags an ONNX model as a known-bad pairing', () => {
  const result = assessTtsCompatibility({
    runtime: 'native',
    model: 'kokoro-v1.0.int8.onnx',
  });

  assert.equal(result.known, true);
  assert.equal(result.knownBad, true);
  assert.equal(result.compatible, false);
  assert.equal(result.offered, false, 'an explicit incompatibility is not offered');
  assert.match(result.caution, /may not be supported by the selected runtime/);
});

test('loaded runtime voice capabilities reject voices absent from the backend truth', () => {
  const result = assessTtsCompatibility({
    runtime: 'onnx',
    model: 'kokoro-v1.0.onnx',
    voiceId: 'bm_george',
    runtimeCapabilities: {
      model_id: 'kokoro-v1.0.onnx',
      supported_voice_ids: ['af_heart', 'bf_emma'],
      blend_capable: true,
    },
  });

  assert.equal(result.knownBad, true);
  assert.equal(result.offered, false);
  assert.match(result.caution, /not present in the loaded TTS runtime/);
});

test('loaded runtime blend capability rejects blending when the backend says it is unavailable', () => {
  const result = assessTtsCompatibility({
    runtime: 'native',
    model: 'kokoro-v1.0.onnx',
    capability: 'blend',
    runtimeCapabilities: { blend_capable: false },
  });

  assert.equal(result.knownBad, true);
  assert.equal(result.offered, false);
  assert.match(result.caution, /blending is not supported/);
});

test('the smallest supported TTS variant is the declared int8 Kokoro artifact', () => {
  assert.equal(SMALLEST_SUPPORTED_TTS_MODEL.id, 'kokoro-v1.0.int8.onnx');
  assert.equal(SMALLEST_SUPPORTED_TTS_MODEL.quantization, 'int8');
  assert.match(SMALLEST_SUPPORTED_TTS_MODEL.evidence, /tts_engine\.py:876-882/);
  assert.ok(
    TTS_MODEL_COMPATIBILITY.some((entry) => (
      entry.runtime === 'onnx'
      && entry.model === SMALLEST_SUPPORTED_TTS_MODEL.id
      && entry.compatible === true
    )),
    'the smallest declared variant must be represented as an ONNX-compatible table row',
  );
  assert.match(SMALLEST_SUPPORTED_TTS_MODEL.basis, /byte size is not recorded/);
});
