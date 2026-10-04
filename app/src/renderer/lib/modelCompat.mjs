// TTS model/runtime compatibility guidance.
//
// IMPORTANT: this table remains a fallback for unknown runtimes and model
// selections. When /runtime/tts-status reports a loaded model or voice table,
// callers pass that backend truth to assessTtsCompatibility below. Unknown
// pairs still fail OPEN: callers must continue to offer them and show caution.

const STATIC_KOKORO_VOICE_IDS = Object.freeze([
  'af_heart', 'af_bella', 'af_nicole', 'af_sarah',
  'am_puck', 'am_michael', 'bf_emma', 'bm_george',
  'standard_female', 'standard_male',
]);

// The three ONNX artifact names are selected explicitly by the loader.
// backend/tts/tts_engine.py::ReviewTTSEngine._load_kokoro_onnx_backend.
// The voice IDs are only the server's static offerings (server.py::list_voices);
// the ONNX voice pack is checked dynamically by
// backend/tts/tts_engine.py::ReviewTTSEngine._onnx_voice_exists. They are marked
// assumptions below rather than being presented as runtime proof.
export const TTS_MODEL_COMPATIBILITY = Object.freeze([
  // DERIVED: backend/tts/tts_engine.py::ReviewTTSEngine._load_kokoro_onnx_backend
  // selects this exact artifact for fp32 and downloads it for the ONNX runtime.
  {
    runtime: 'onnx',
    model: 'kokoro-v1.0.onnx',
    compatible: true,
    supportedVoiceIds: STATIC_KOKORO_VOICE_IDS,
    voiceSupport: 'assumption',
    evidence: 'backend/tts/tts_engine.py::ReviewTTSEngine._load_kokoro_onnx_backend; server.py::list_voices',
  },
  // DERIVED: backend/tts/tts_engine.py::ReviewTTSEngine._load_kokoro_onnx_backend
  // selects this exact artifact for fp16 and downloads it for the ONNX runtime.
  {
    runtime: 'onnx',
    model: 'kokoro-v1.0.fp16.onnx',
    compatible: true,
    supportedVoiceIds: STATIC_KOKORO_VOICE_IDS,
    voiceSupport: 'assumption',
    evidence: 'backend/tts/tts_engine.py::ReviewTTSEngine._load_kokoro_onnx_backend; server.py::list_voices',
  },
  // DERIVED: backend/tts/tts_engine.py::ReviewTTSEngine._load_kokoro_onnx_backend
  // selects this exact artifact for int8 and downloads it for the ONNX runtime.
  {
    runtime: 'onnx',
    model: 'kokoro-v1.0.int8.onnx',
    compatible: true,
    supportedVoiceIds: STATIC_KOKORO_VOICE_IDS,
    voiceSupport: 'assumption',
    evidence: 'backend/tts/tts_engine.py::ReviewTTSEngine._load_kokoro_onnx_backend; server.py::list_voices',
  },
  // DERIVED KNOWN-BAD: the native path constructs KPipeline
  // (backend/tts/tts_engine.py::ReviewTTSEngine._load_kokoro_backend), while ONNX
  // artifacts use backend/tts/tts_engine.py::ReviewTTSEngine._load_kokoro_onnx_backend.
  {
    runtime: 'native',
    model: 'kokoro-v1.0.onnx',
    compatible: false,
    evidence: 'backend/tts/tts_engine.py::ReviewTTSEngine._load_kokoro_backend; backend/tts/tts_engine.py::ReviewTTSEngine._load_kokoro_onnx_backend',
  },
  // DERIVED KNOWN-BAD: same native-vs-ONNX loader boundary as above.
  {
    runtime: 'native',
    model: 'kokoro-v1.0.fp16.onnx',
    compatible: false,
    evidence: 'backend/tts/tts_engine.py::ReviewTTSEngine._load_kokoro_backend; backend/tts/tts_engine.py::ReviewTTSEngine._load_kokoro_onnx_backend',
  },
  // DERIVED KNOWN-BAD: same native-vs-ONNX loader boundary as above.
  {
    runtime: 'native',
    model: 'kokoro-v1.0.int8.onnx',
    compatible: false,
    evidence: 'backend/tts/tts_engine.py::ReviewTTSEngine._load_kokoro_backend; backend/tts/tts_engine.py::ReviewTTSEngine._load_kokoro_onnx_backend',
  },
  // DERIVED KNOWN-BAD: blending is explicitly gated to ONNX by
  // backend/tts/tts_engine.py::ReviewTTSEngine._resolve_voice_spec;
  // keep this capability row separate from model
  // rows so a missing model identifier cannot turn a known runtime limitation
  // into an unknown/quiet state.
  {
    runtime: 'native',
    model: '*',
    capability: 'blend',
    compatible: false,
    evidence: 'backend/tts/tts_engine.py::ReviewTTSEngine._resolve_voice_spec',
  },
]);

// “Smallest” is proved here in the only sense the repository currently
// records: the loader exposes fp32, fp16, and int8 variants, and int8 is the
// lowest declared quantization. The repo does not record artifact byte sizes,
// so this must not be described as a measured smallest-file claim.
// DERIVED: backend/tts/tts_engine.py::ReviewTTSEngine._load_kokoro_onnx_backend;
// default quantization is surfaced at server.py::get_profile_output_settings
// and applied at server.py::speak_text_aloud.
export const SMALLEST_SUPPORTED_TTS_MODEL = Object.freeze({
  id: 'kokoro-v1.0.int8.onnx',
  runtime: 'onnx',
  quantization: 'int8',
  basis: 'lowest declared Kokoro quantization variant; artifact byte size is not recorded in this repo',
  evidence: 'backend/tts/tts_engine.py::ReviewTTSEngine._load_kokoro_onnx_backend; server.py::get_profile_output_settings; server.py::speak_text_aloud',
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
export function assessTtsCompatibility({ runtime, model, voiceId, capability, runtimeCapabilities } = {}) {
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

  const backendVoiceIds = Array.isArray(runtimeCapabilities?.supported_voice_ids)
    ? runtimeCapabilities.supported_voice_ids.map((id) => String(id).trim().toLowerCase()).filter(Boolean)
    : [];
  const backendKnowsVoice = backendVoiceIds.length > 0;
  const backendVoiceUnsupported = backendKnowsVoice && voice && !backendVoiceIds.includes(voice.toLowerCase());
  const backendBlendUnsupported = capability === 'blend'
    && runtimeCapabilities
    && runtimeCapabilities.blend_capable === false;

  if (backendVoiceUnsupported || backendBlendUnsupported) {
    return {
      runtime: normalizedRuntime,
      model: normalizedModel,
      voiceId: voice,
      known: true,
      knownBad: true,
      compatible: false,
      assumption: false,
      offered: false,
      caution: backendVoiceUnsupported
        ? 'This voice is not present in the loaded TTS runtime.'
        : 'Voice blending is not supported by the loaded TTS runtime.',
      entry: entry || null,
    };
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
