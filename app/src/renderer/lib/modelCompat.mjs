// TTS model/runtime compatibility guidance.
//
// IMPORTANT: this is a hand-authored table. The runtime does NOT report a
// supported TTS model or voice list: /runtime/tts-status currently reports
// backend/runtime/blend_capable only (server.py:5305-5322), and /tts/voices
// returns a static default list (server.py:5418-5433). Entries below are
// therefore evidence-backed guidance, not a guarantee. Unknown pairs fail
// OPEN: callers must continue to offer them and show the caution instead of
// hiding a model or voice the user may actually have.

const STATIC_KOKORO_VOICE_IDS = Object.freeze([
  'af_heart', 'af_bella', 'af_nicole', 'af_sarah',
  'am_puck', 'am_michael', 'bf_emma', 'bm_george',
  'standard_female', 'standard_male',
]);

// The three ONNX artifact names are selected explicitly by the loader.
// tts_engine.py:876-882. The voice IDs are only the server's static offerings
// (server.py:5418-5428); the ONNX voice pack is checked dynamically by
// tts_engine.py:1124-1139 but is not exposed to this renderer. They are marked
// assumptions below rather than being presented as runtime proof.
export const TTS_MODEL_COMPATIBILITY = Object.freeze([
  // DERIVED: tts_engine.py:876-882 selects this exact artifact for fp32;
  // tts_engine.py:884-902 downloads it for the ONNX runtime.
  {
    runtime: 'onnx',
    model: 'kokoro-v1.0.onnx',
    compatible: true,
    supportedVoiceIds: STATIC_KOKORO_VOICE_IDS,
    voiceSupport: 'assumption',
    evidence: 'tts_engine.py:876-902; server.py:5418-5428',
  },
  // DERIVED: tts_engine.py:876-882 selects this exact artifact for fp16;
  // tts_engine.py:884-902 downloads it for the ONNX runtime.
  {
    runtime: 'onnx',
    model: 'kokoro-v1.0.fp16.onnx',
    compatible: true,
    supportedVoiceIds: STATIC_KOKORO_VOICE_IDS,
    voiceSupport: 'assumption',
    evidence: 'tts_engine.py:876-902; server.py:5418-5428',
  },
  // DERIVED: tts_engine.py:876-882 selects this exact artifact for int8;
  // tts_engine.py:884-902 downloads it for the ONNX runtime.
  {
    runtime: 'onnx',
    model: 'kokoro-v1.0.int8.onnx',
    compatible: true,
    supportedVoiceIds: STATIC_KOKORO_VOICE_IDS,
    voiceSupport: 'assumption',
    evidence: 'tts_engine.py:876-902; server.py:5418-5428',
  },
  // DERIVED KNOWN-BAD: the native path constructs KPipeline
  // (tts_engine.py:827-852), while ONNX artifacts are loaded only by
  // _load_kokoro_onnx_backend (tts_engine.py:861-935).
  {
    runtime: 'native',
    model: 'kokoro-v1.0.onnx',
    compatible: false,
    evidence: 'tts_engine.py:827-852,861-935',
  },
  // DERIVED KNOWN-BAD: same native-vs-ONNX loader boundary as above.
  {
    runtime: 'native',
    model: 'kokoro-v1.0.fp16.onnx',
    compatible: false,
    evidence: 'tts_engine.py:827-852,861-935',
  },
  // DERIVED KNOWN-BAD: same native-vs-ONNX loader boundary as above.
  {
    runtime: 'native',
    model: 'kokoro-v1.0.int8.onnx',
    compatible: false,
    evidence: 'tts_engine.py:827-852,861-935',
  },
  // DERIVED KNOWN-BAD: blending is explicitly gated to ONNX by
  // tts_engine.py:1057-1067; keep this capability row separate from model
  // rows so a missing model identifier cannot turn a known runtime limitation
  // into an unknown/quiet state.
  {
    runtime: 'native',
    model: '*',
    capability: 'blend',
    compatible: false,
    evidence: 'tts_engine.py:1057-1067',
  },
]);

// “Smallest” is proved here in the only sense the repository currently
// records: the loader exposes fp32, fp16, and int8 variants, and int8 is the
// lowest declared quantization. The repo does not record artifact byte sizes,
// so this must not be described as a measured smallest-file claim.
// DERIVED: tts_engine.py:876-882; default quantization is surfaced at
// server.py:1015-1017 and applied at server.py:1320-1341.
export const SMALLEST_SUPPORTED_TTS_MODEL = Object.freeze({
  id: 'kokoro-v1.0.int8.onnx',
  runtime: 'onnx',
  quantization: 'int8',
  basis: 'lowest declared Kokoro quantization variant; artifact byte size is not recorded in this repo',
  evidence: 'tts_engine.py:876-882; server.py:1015-1017,1320-1341',
});

function normalizeRuntime(runtime) {
  const value = String(runtime || '').trim().toLowerCase();
  if (value === 'kokoro_onnx' || value === 'kokoro-onnx' || value === 'onnx') return 'onnx';
  if (value === 'kokoro' || value === 'native') return 'native';
  if (value === 'sapi' || value === 'sapi fallback') return 'sapi';
  return value;
}

function normalizeModel(model) {
  const value = String(model || '').trim().toLowerCase();
  if (!value) return '';
  if (value === 'fp32' || value === '32') return 'kokoro-v1.0.onnx';
  if (value === 'fp16' || value === '16') return 'kokoro-v1.0.fp16.onnx';
  if (value === 'int8' || value === '8') return 'kokoro-v1.0.int8.onnx';
  return value;
}

function findEntry(runtime, model, capability) {
  return TTS_MODEL_COMPATIBILITY.find((entry) => (
    entry.runtime === runtime
    && (entry.model === model || entry.model === '*')
    && (!entry.capability || entry.capability === capability)
  ));
}

/**
 * Assess a runtime/model/voice selection without ever making unknown data
 * disappear. `offered` is false only for a table row explicitly marked
 * incompatible; unknown and assumption-backed rows remain offered.
 */
export function assessTtsCompatibility({ runtime, model, voiceId, capability } = {}) {
  const normalizedRuntime = normalizeRuntime(runtime);
  const normalizedModel = normalizeModel(model);
  const entry = findEntry(normalizedRuntime, normalizedModel, capability);
  const voice = String(voiceId || '').trim();
  const voiceListed = Boolean(entry?.supportedVoiceIds?.includes(voice));
  const voiceUnknown = Boolean(voice && entry?.supportedVoiceIds && !voiceListed);
  const knownBad = entry?.compatible === false;
  const known = Boolean(entry);
  const assumption = entry?.voiceSupport === 'assumption' || voiceUnknown;

  let caution = '';
  if (knownBad) {
    caution = 'This model may not be supported by the selected runtime.';
  } else if (!known || voiceUnknown || assumption) {
    caution = 'This model or voice may not be supported by the selected runtime.';
  }

  return {
    runtime: normalizedRuntime,
    model: normalizedModel,
    voiceId: voice,
    known,
    knownBad,
    compatible: known ? Boolean(entry.compatible) : null,
    assumption,
    offered: !knownBad || !known,
    caution,
    entry: entry || null,
  };
}

export const getTtsCompatibility = assessTtsCompatibility;
export const isModelSupportedByRuntime = (runtime, model) => (
  assessTtsCompatibility({ runtime, model }).compatible === true
);

