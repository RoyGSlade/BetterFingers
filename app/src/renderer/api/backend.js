// Only used to build the URL constants below and to derive the request path;
// the renderer no longer knows the real backend origin — the main-process proxy
// holds it. A different backend port still works because only the path is sent.
const BACKEND_ORIGIN = 'http://127.0.0.1:8000';
const HEALTH_URL = `${BACKEND_ORIGIN}/health`;
const RUNTIME_STATUS_URL = `${BACKEND_ORIGIN}/runtime/status`;
const RUNTIME_WARMUP_URL = `${BACKEND_ORIGIN}/runtime/warmup`;
const RUNTIME_OUTPUT_SETTINGS_URL = `${BACKEND_ORIGIN}/runtime/output-settings`;
const RUNTIME_PRIMARY_ACTION_URL = `${BACKEND_ORIGIN}/runtime/primary-action`;
const RUNTIME_EMERGENCY_STOP_URL = `${BACKEND_ORIGIN}/runtime/emergency-stop`;
const RUNTIME_RECORDING_TOGGLE_URL = `${BACKEND_ORIGIN}/runtime/recording/toggle`;
const CAPABILITIES_URL = `${BACKEND_ORIGIN}/capabilities`;
const DIAGNOSTICS_LOGS_URL = `${BACKEND_ORIGIN}/diagnostics/logs`;
const DIAGNOSTICS_PATHS_URL = `${BACKEND_ORIGIN}/diagnostics/paths`;
const SUPPORT_REPORT_URL = `${BACKEND_ORIGIN}/diagnostics/support-report`;
const DRAFTS_URL = `${BACKEND_ORIGIN}/drafts`;
const RUNTIME_ERRORS_URL = `${BACKEND_ORIGIN}/runtime/errors`;
const SETTINGS_PROFILES_URL = `${BACKEND_ORIGIN}/settings/profiles`;
const MODELS_LLM_URL = `${BACKEND_ORIGIN}/models/llm`;
const MODELS_WHISPER_URL = `${BACKEND_ORIGIN}/models/whisper`;
const MODELS_UNLOAD_URL = `${BACKEND_ORIGIN}/models/unload`;
const VOICE_STATUS_WS_URL = `${BACKEND_ORIGIN.replace(/^http/, 'ws')}/ws/voice_status`;
const DOCTOR_URL = `${BACKEND_ORIGIN}/doctor`;
const REFRESH_AUDIO_DEVICES_URL = `${BACKEND_ORIGIN}/runtime/audio-devices/refresh`;
const RUNTIME_VERSION_URL = `${BACKEND_ORIGIN}/runtime/version`;
const PERSONAS_URL = `${BACKEND_ORIGIN}/personas`;
const TTS_VOICES_URL = `${BACKEND_ORIGIN}/tts/voices`;
const VOICE_PRESETS_URL = `${BACKEND_ORIGIN}/voice-presets`;
const WAKE_URL = `${BACKEND_ORIGIN}/wake`;
// Phase 3c: no token in the renderer. Every backend call goes through the
// main-process proxy, which attaches the credential and enforces the route
// allowlist. These helpers translate a full URL into the proxy's (method,
// path, body) shape and reproduce the previous throw-on-error contract.

function pathOf(url) {
  return String(url).startsWith(BACKEND_ORIGIN) ? String(url).slice(BACKEND_ORIGIN.length) : String(url);
}

function errorMessageFromBody(body, url, status) {
  const detail = body && (body.detail || body.message || body.error);
  if (Array.isArray(detail)) {
    return detail.map((item) => (item && item.msg) || JSON.stringify(item)).join('; ');
  }
  if (detail) {
    return String(detail);
  }
  return `${url} failed with status ${status}`;
}

function unwrapProxyResult(res, label, timeoutMs) {
  if (!res) {
    throw new Error('Backend request returned no result.');
  }
  // Transport/validation faults surface as status 0 with an error string.
  if (res.status === 0 && res.ok === false) {
    if (res.error === 'timeout') {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)} seconds. The local model may still be loading or generating.`);
    }
    throw new Error(res.error || 'Backend request failed.');
  }
  if (!res.ok) {
    const error = new Error(errorMessageFromBody(res.body, label, res.status));
    error.status = res.status;
    error.detail = res.body && res.body.detail;
    throw error;
  }
  return res.body;
}

async function proxyRequest(method, url, body, timeoutMs = 2500) {
  const bridge = window.betterFingers && window.betterFingers.backendRequest;
  if (typeof bridge !== 'function') {
    throw new Error('Backend bridge is unavailable.');
  }
  return unwrapProxyResult(await bridge(method, pathOf(url), body, timeoutMs), url, timeoutMs);
}

// Destructive/sensitive operations don't go through the generic proxy at all:
// each calls a dedicated typed IPC method on the preload bridge (exact route,
// exact HTTP method, validated payload in the main process).
async function typedRequest(name, label, timeoutMs, ...args) {
  const bridge = window.betterFingers && window.betterFingers[name];
  if (typeof bridge !== 'function') {
    throw new Error('Backend bridge is unavailable.');
  }
  return unwrapProxyResult(await bridge(...args, timeoutMs), label, timeoutMs);
}

async function fetchDoctor(refreshAudio = false, timeoutMs = 5000) {
  return fetchJson(`${DOCTOR_URL}?refresh_audio=${refreshAudio}`, timeoutMs);
}

async function refreshAudioDevices(timeoutMs = 5000) {
  return postJson(REFRESH_AUDIO_DEVICES_URL, {}, timeoutMs);
}

async function fetchVersion(timeoutMs = 2500) {
  return fetchJson(RUNTIME_VERSION_URL, timeoutMs);
}

async function fetchHealth(timeoutMs = 2500) {
  return typedRequest('fetchHealth', HEALTH_URL, timeoutMs);
}

async function fetchJson(url, timeoutMs = 2500) {
  return proxyRequest('GET', url, undefined, timeoutMs);
}

async function fetchRuntimeStatus(timeoutMs = 2500) {
  return fetchJson(RUNTIME_STATUS_URL, timeoutMs);
}

async function fetchOutputSettings(timeoutMs = 2500) {
  return fetchJson(RUNTIME_OUTPUT_SETTINGS_URL, timeoutMs);
}

async function fetchProfiles(timeoutMs = 2500) {
  return fetchJson(SETTINGS_PROFILES_URL, timeoutMs);
}

async function fetchProfile(name, timeoutMs = 2500) {
  const data = await fetchJson(`${SETTINGS_PROFILES_URL}/${encodeURIComponent(name)}`, timeoutMs);
  if (data && data.active && data.settings && typeof window !== 'undefined' && window.betterFingers?.updateHotkeys) {
    window.betterFingers.updateHotkeys(data.settings);
  }
  return data;
}

async function saveProfile(name, settings, timeoutMs = 10000) {
  const data = await postJson(`${SETTINGS_PROFILES_URL}/${encodeURIComponent(name)}`, { settings }, timeoutMs);
  if (data && data.active && data.settings && typeof window !== 'undefined' && window.betterFingers?.updateHotkeys) {
    window.betterFingers.updateHotkeys(data.settings);
  }
  return data;
}

async function createProfile(name, settings = {}, timeoutMs = 10000) {
  return postJson(SETTINGS_PROFILES_URL, { name, settings }, timeoutMs);
}

async function activateProfile(name, timeoutMs = 10000) {
  return postJson(`${SETTINGS_PROFILES_URL}/${encodeURIComponent(name)}/activate`, {}, timeoutMs);
}

async function deleteProfile(name, timeoutMs = 10000) {
  return deleteJson(`${SETTINGS_PROFILES_URL}/${encodeURIComponent(name)}`, timeoutMs);
}

async function renameProfile(oldName, newName, timeoutMs = 10000) {
  return postJson(`${SETTINGS_PROFILES_URL}/${encodeURIComponent(oldName)}/rename`, { new_name: newName }, timeoutMs);
}

async function duplicateProfile(oldName, newName, timeoutMs = 10000) {
  return postJson(`${SETTINGS_PROFILES_URL}/${encodeURIComponent(oldName)}/duplicate`, { new_name: newName }, timeoutMs);
}

async function exportProfile(name, timeoutMs = 10000) {
  return fetchJson(`${SETTINGS_PROFILES_URL}/${encodeURIComponent(name)}/export`, timeoutMs);
}

async function importProfile(payload, timeoutMs = 10000) {
  return postJson(`${SETTINGS_PROFILES_URL}/import`, payload, timeoutMs);
}

async function fetchCapabilities(timeoutMs = 2500) {
  return fetchJson(CAPABILITIES_URL, timeoutMs);
}

async function fetchDiagnosticsLogs(lines = 80, timeoutMs = 2500) {
  return fetchJson(`${DIAGNOSTICS_LOGS_URL}?lines=${encodeURIComponent(lines)}`, timeoutMs);
}

async function fetchDiagnosticsPaths(timeoutMs = 2500) {
  return fetchJson(DIAGNOSTICS_PATHS_URL, timeoutMs);
}

async function fetchSupportReport(timeoutMs = 15000) {
  // Longer timeout: the report may shell out to `llama-server --version`.
  return fetchJson(SUPPORT_REPORT_URL, timeoutMs);
}

async function fetchMetrics(timeoutMs = 2500) {
  return fetchJson(`${BACKEND_ORIGIN}/metrics`, timeoutMs);
}

async function fetchPrivacy(timeoutMs = 2500) {
  return fetchJson(`${BACKEND_ORIGIN}/privacy`, timeoutMs);
}

async function wipeData(wipeVoices = false, timeoutMs = 10000, { confirmed = false } = {}) {
  return typedRequest('wipePrivacyData', '/privacy/wipe', timeoutMs, {
    wipeVoices,
    confirm: confirmed === true,
  });
}

async function fetchRecordings(timeoutMs = 2500) {
  return fetchJson(`${BACKEND_ORIGIN}/recordings`, timeoutMs);
}

async function retranscribeRecording(recId, timeoutMs = 120000) {
  return postJson(`${BACKEND_ORIGIN}/recordings/${encodeURIComponent(recId)}/retranscribe`, {}, timeoutMs);
}

async function deleteRecording(recId, timeoutMs = 10000) {
  return deleteJson(`${BACKEND_ORIGIN}/recordings/${encodeURIComponent(recId)}`, timeoutMs);
}

async function fetchJobs(activeOnly = false, timeoutMs = 2500) {
  const query = activeOnly ? '?active=1' : '';
  return fetchJson(`${BACKEND_ORIGIN}/jobs${query}`, timeoutMs);
}

async function cancelJob(jobId, timeoutMs = 5000) {
  return typedRequest('cancelJob', '/jobs/cancel', timeoutMs, String(jobId));
}

async function clearRecordings(timeoutMs = 10000) {
  return deleteJson(`${BACKEND_ORIGIN}/recordings`, timeoutMs);
}

async function fetchDictionary(timeoutMs = 2500) {
  return fetchJson(`${BACKEND_ORIGIN}/dictionary`, timeoutMs);
}

async function addDictionaryTerm(term, timeoutMs = 10000) {
  return postJson(`${BACKEND_ORIGIN}/dictionary`, { term }, timeoutMs);
}

async function deleteDictionaryTerm(term, timeoutMs = 10000) {
  return deleteJson(`${BACKEND_ORIGIN}/dictionary/${encodeURIComponent(term)}`, timeoutMs);
}

async function suggestDictionaryTerms(rawText, editedText, timeoutMs = 5000) {
  return postJson(`${BACKEND_ORIGIN}/dictionary/suggest`, { raw_text: rawText, edited_text: editedText }, timeoutMs);
}

async function searchHistory(query, limit = 50, timeoutMs = 5000) {
  const params = new URLSearchParams({ q: query ?? '', limit: String(limit) });
  return fetchJson(`${BACKEND_ORIGIN}/history/search?${params.toString()}`, timeoutMs);
}

async function fetchHistoryRecent(limit = 50, timeoutMs = 5000) {
  return fetchJson(`${BACKEND_ORIGIN}/history?limit=${encodeURIComponent(limit)}`, timeoutMs);
}

async function clearHistory(timeoutMs = 10000) {
  return deleteJson(`${BACKEND_ORIGIN}/history`, timeoutMs);
}

async function fetchModelRecommendation(timeoutMs = 5000) {
  return fetchJson(`${BACKEND_ORIGIN}/models/recommend`, timeoutMs);
}

async function fetchMacros(timeoutMs = 2500) {
  return fetchJson(`${BACKEND_ORIGIN}/macros`, timeoutMs);
}

async function addMacro(trigger, expansion, timeoutMs = 10000) {
  return postJson(`${BACKEND_ORIGIN}/macros`, { trigger, expansion }, timeoutMs);
}

async function deleteMacro(trigger, timeoutMs = 10000) {
  return deleteJson(`${BACKEND_ORIGIN}/macros/${encodeURIComponent(trigger)}`, timeoutMs);
}

async function fetchRuntimeErrors(timeoutMs = 2500) {
  return fetchJson(RUNTIME_ERRORS_URL, timeoutMs);
}

async function fetchDrafts(timeoutMs = 2500) {
  return fetchJson(DRAFTS_URL, timeoutMs);
}

async function fetchLlmModels(timeoutMs = 2500) {
  return fetchJson(MODELS_LLM_URL, timeoutMs);
}

async function selectLlmModel(modelId, timeoutMs = 10000) {
  return postJson(`${MODELS_LLM_URL}/select`, { model_id: modelId }, timeoutMs);
}

async function downloadLlmModel(modelId, timeoutMs = 1800000) {
  return postJson(`${MODELS_LLM_URL}/${encodeURIComponent(modelId)}/download`, {}, timeoutMs);
}

async function fetchLlmDownloadState(modelId, timeoutMs = 2500) {
  return fetchJson(`${MODELS_LLM_URL}/${encodeURIComponent(modelId)}/download-state`, timeoutMs);
}

async function deleteLlmModel(modelId, timeoutMs = 10000, { confirmed = false } = {}) {
  return typedRequest('deleteLlmModel', `${MODELS_LLM_URL}/${modelId}`, timeoutMs, String(modelId), {
    confirm: confirmed === true,
  });
}

async function fetchWhisperModels(timeoutMs = 2500) {
  return fetchJson(MODELS_WHISPER_URL, timeoutMs);
}

async function downloadWhisperModel(modelSize, preferGpu = true, timeoutMs = 1800000) {
  return postJson(`${MODELS_WHISPER_URL}/download`, { model_size: modelSize, prefer_gpu: preferGpu }, timeoutMs);
}

async function deleteWhisperModel(modelSize, timeoutMs = 10000, { confirmed = false } = {}) {
  return typedRequest('deleteWhisperModel', `${MODELS_WHISPER_URL}/${modelSize}`, timeoutMs, String(modelSize), {
    confirm: confirmed === true,
  });
}

async function selectWhisperModel(modelSize, timeoutMs = 15000) {
  return postJson(`${MODELS_WHISPER_URL}/select`, { model_size: modelSize }, timeoutMs);
}

async function unloadModel(component, timeoutMs = 10000) {
  return postJson(`${MODELS_UNLOAD_URL}/${encodeURIComponent(component)}`, {}, timeoutMs);
}

async function fetchLatestDraft(timeoutMs = 2500) {
  return fetchJson(`${DRAFTS_URL}/latest`, timeoutMs);
}

async function postJson(url, payload = {}, timeoutMs = 2500) {
  return proxyRequest('POST', url, payload, timeoutMs);
}

async function deleteJson(url, timeoutMs = 2500) {
  return proxyRequest('DELETE', url, undefined, timeoutMs);
}

async function acceptDraft(id, timeoutMs = 2500) {
  return postJson(`${DRAFTS_URL}/${id}/accept`, {}, timeoutMs);
}

async function declineDraft(id, timeoutMs = 2500) {
  return postJson(`${DRAFTS_URL}/${id}/decline`, {}, timeoutMs);
}

async function clearDrafts(timeoutMs = 2500) {
  return deleteJson(DRAFTS_URL, timeoutMs);
}

async function retryDraft(id, timeoutMs = 120000) {
  return postJson(`${DRAFTS_URL}/${id}/retry`, {}, timeoutMs);
}

async function editDraft(id, finalText, timeoutMs = 10000) {
  return postJson(`${DRAFTS_URL}/${id}/edit`, { final_text: finalText }, timeoutMs);
}

async function rewriteDraft(id, { action = 'clearer', customInstruction = '' } = {}, timeoutMs = 120000) {
  return postJson(`${DRAFTS_URL}/${id}/rewrite`, { action, custom_instruction: customInstruction }, timeoutMs);
}

function _mergeExtraFields(body, extra) {
  if (extra && typeof extra === 'object') {
    for (const [key, value] of Object.entries(extra)) {
      if (value !== null && value !== undefined) {
        body[key] = value;
      }
    }
  }
  return body;
}

async function speakDraft(
  id,
  { text = '', voiceId = 'standard_female', speed = 1.0, pitch = 1.0, extra = {} } = {},
  timeoutMs = 120000,
) {
  const body = _mergeExtraFields({ text, voice_id: voiceId, speed, pitch }, extra);
  return postJson(`${DRAFTS_URL}/${id}/tts`, body, timeoutMs);
}

// `extra` accepts Voice Studio fields keyed exactly as the backend expects:
// blend ({name: weight}), energy, warmth, brightness, pause_style,
// preset_name, persona — same merge-extra pattern as savePersona() below.
async function speakTts(text, voiceId = 'standard_female', speed = 1.0, pitch = 1.0, extra = {}, timeoutMs = 120000) {
  const body = _mergeExtraFields({ text, voice_id: voiceId, speed, pitch }, extra);
  return postJson(`${BACKEND_ORIGIN}/tts/speak`, body, timeoutMs);
}

async function sendDraft(id, { action = 'copy_only', openChat = false } = {}, timeoutMs = 120000) {
  return typedRequest('sendDraft', `${DRAFTS_URL}/${id}/send`, timeoutMs, Number(id), { action, openChat });
}

async function runPrimaryAction(timeoutMs = 120000) {
  return postJson(RUNTIME_PRIMARY_ACTION_URL, {}, timeoutMs);
}

async function emergencyStop(timeoutMs = 10000) {
  return postJson(RUNTIME_EMERGENCY_STOP_URL, {}, timeoutMs);
}

async function toggleRecording(timeoutMs = 120000) {
  return postJson(RUNTIME_RECORDING_TOGGLE_URL, {}, timeoutMs);
}

async function fetchPersonas(timeoutMs = 2500) {
  return fetchJson(PERSONAS_URL, timeoutMs);
}

async function fetchBuiltinPersonaNames(timeoutMs = 2500) {
  return fetchJson(`${BACKEND_ORIGIN}/personas-builtins`, timeoutMs);
}

async function fetchTtsVoices(timeoutMs = 2500) {
  return fetchJson(TTS_VOICES_URL, timeoutMs);
}

async function provisionVoiceCloning(timeoutMs = 600000) {
  // Provisioning downloads a ~1.5 GB runtime when published — allow a long
  // timeout. Returns { ok, message?, already_provisioned?, cloning }.
  return postJson(`${BACKEND_ORIGIN}/tts/clone/provision`, {}, timeoutMs);
}

async function fetchVoicePresets(timeoutMs = 2500) {
  return fetchJson(VOICE_PRESETS_URL, timeoutMs);
}

async function saveVoicePreset(name, fields = {}, timeoutMs = 5000) {
  return postJson(VOICE_PRESETS_URL, { name, ...fields }, timeoutMs);
}

async function deleteVoicePreset(name, timeoutMs = 5000) {
  return deleteJson(`${VOICE_PRESETS_URL}/${encodeURIComponent(name)}`, timeoutMs);
}

// Auditions a saved preset exactly as saved — the backend resolves base/blend/
// modulation from the preset by name, so the request carries nothing else
// that could override it (unlike speakTts, which always sends voice_id/speed/
// pitch and would win over a preset on the server).
async function speakPreset(text, presetName, timeoutMs = 120000) {
  return postJson(`${BACKEND_ORIGIN}/tts/speak`, { text, preset_name: presetName }, timeoutMs);
}

async function setDefaultVoicePreset(name, timeoutMs = 5000) {
  return postJson(`${VOICE_PRESETS_URL}/${encodeURIComponent(name)}/make-default`, {}, timeoutMs);
}

async function clearDefaultVoicePreset(timeoutMs = 5000) {
  // Flat path, NOT /voice-presets/default: that nested form is structurally
  // identical to DELETE /voice-presets/{name} with name="default", so the
  // backend gives "clear the default pointer" its own collision-free route
  // (see routes_user_config.py) — a preset literally named "default" stays
  // deletable via the parameterized route.
  return deleteJson(`${BACKEND_ORIGIN}/voice-presets-default`, timeoutMs);
}

async function fetchCloneStatus(timeoutMs = 2500) {
  return fetchJson(`${BACKEND_ORIGIN}/tts/clone/status`, timeoutMs);
}

async function fetchTtsStatus(timeoutMs = 2500) {
  return fetchJson(`${BACKEND_ORIGIN}/runtime/tts-status`, timeoutMs);
}

async function stopTts(timeoutMs = 5000) {
  return postJson(`${BACKEND_ORIGIN}/tts/stop`, {}, timeoutMs);
}

async function deleteVoice(voiceId, timeoutMs = 10000, { confirmed = false } = {}) {
  return typedRequest('deleteVoice', `${TTS_VOICES_URL}/${voiceId}`, timeoutMs, String(voiceId), {
    confirm: confirmed === true,
  });
}

async function cloneVoice(file, name, consent, timeoutMs = 30000) {
  const bridge = window.betterFingers && window.betterFingers.uploadVoiceSample;
  if (typeof bridge !== 'function') {
    throw new Error('Backend bridge is unavailable.');
  }
  // Read the file in the renderer and hand the bytes to main, which builds the
  // multipart body with the token attached (Phase 3c).
  const arrayBuffer = await file.arrayBuffer();
  const res = await bridge({
    bytes: new Uint8Array(arrayBuffer),
    filename: file.name,
    name,
    consent: Boolean(consent),
    timeoutMs,
  });
  if (!res) {
    throw new Error('Clone upload returned no result.');
  }
  if (res.status === 0 && res.ok === false) {
    if (res.error === 'timeout') {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)} seconds. The local model may still be loading or generating.`);
    }
    throw new Error(res.error || 'Clone upload failed.');
  }
  if (!res.ok) {
    // /tts/clone's QA-rejection detail is a structured {message, warnings}
    // object; surface it so callers can show individual warnings.
    const detail = res.body && res.body.detail;
    const message = (detail && typeof detail === 'object' ? detail.message : detail) || `Clone upload failed with status ${res.status}`;
    const error = new Error(message);
    error.detail = detail;
    throw error;
  }
  return res.body;
}

async function fetchWakeStatus(timeoutMs = 2500) {
  return fetchJson(`${WAKE_URL}/status`, timeoutMs);
}

async function fetchWakeModels(timeoutMs = 2500) {
  return fetchJson(`${WAKE_URL}/models`, timeoutMs);
}

async function enableWake(fields = {}, timeoutMs = 5000) {
  return postJson(`${WAKE_URL}/enable`, fields, timeoutMs);
}

async function disableWake(timeoutMs = 5000) {
  return postJson(`${WAKE_URL}/disable`, {}, timeoutMs);
}

async function downloadWakeModel(modelId, timeoutMs = 5000) {
  return postJson(`${WAKE_URL}/models/${encodeURIComponent(modelId)}/download`, {}, timeoutMs);
}

async function fetchWakeModelDownloadState(modelId, timeoutMs = 2500) {
  return fetchJson(`${WAKE_URL}/models/${encodeURIComponent(modelId)}/download-state`, timeoutMs);
}

async function deleteWakeModel(modelId, timeoutMs = 5000) {
  return deleteJson(`${WAKE_URL}/models/${encodeURIComponent(modelId)}`, timeoutMs);
}

async function testWake(durationS = 10.0, timeoutMs = 15000) {
  return postJson(`${WAKE_URL}/test`, { duration_s: durationS }, Math.max(timeoutMs, durationS * 1000 + 5000));
}

async function trainWakePhrase(phrase, timeoutMs = 5000) {
  return postJson(`${WAKE_URL}/train`, { phrase }, timeoutMs);
}

async function fetchWakeTrainStatus(timeoutMs = 2500) {
  return fetchJson(`${WAKE_URL}/train/status`, timeoutMs);
}

async function importWakeModel(file, name, timeoutMs = 30000) {
  const bridge = window.betterFingers && window.betterFingers.uploadWakeModel;
  if (typeof bridge !== 'function') {
    throw new Error('Backend bridge is unavailable.');
  }
  const arrayBuffer = await file.arrayBuffer();
  const res = await bridge({
    bytes: new Uint8Array(arrayBuffer),
    filename: file.name,
    name,
    timeoutMs,
  });
  if (!res) {
    throw new Error('Wake model import returned no result.');
  }
  if (res.status === 0 && res.ok === false) {
    if (res.error === 'timeout') {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)} seconds.`);
    }
    throw new Error(res.error || 'Wake model import failed.');
  }
  if (!res.ok) {
    throw new Error(errorMessageFromBody(res.body, `${WAKE_URL}/models/import`, res.status));
  }
  return res.body;
}

async function lintPersona(fields = {}, timeoutMs = 5000) {
  return postJson(`${PERSONAS_URL}/lint`, fields, timeoutMs);
}

async function testPersona(fields = {}, timeoutMs = 120000) {
  return postJson(`${PERSONAS_URL}/test`, fields, timeoutMs);
}

async function refinePersonaPrompt(fields = {}, timeoutMs = 120000) {
  return postJson(`${PERSONAS_URL}/refine`, fields, timeoutMs);
}

async function draftPersonaFromDescription(description, timeoutMs = 180000) {
  return postJson(`${PERSONAS_URL}/draft`, { description }, timeoutMs);
}

async function getPersonaV2(name, timeoutMs = 2500) {
  return fetchJson(`${PERSONAS_URL}/${encodeURIComponent(name)}`, timeoutMs);
}

async function savePersona(name, prompt, extra = null, timeoutMs = 5000) {
  const body = _mergeExtraFields({ name, prompt }, extra);
  return postJson(PERSONAS_URL, body, timeoutMs);
}

async function deletePersona(name, timeoutMs = 5000) {
  return proxyRequest('DELETE', `${PERSONAS_URL}/${encodeURIComponent(name)}`, undefined, timeoutMs);
}

// --- Persona Foundry: guided interview -> compile -> stress-test. ---

async function startFoundryInterview(timeoutMs = 5000) {
  return postJson(`${PERSONAS_URL}/interview/start`, {}, timeoutMs);
}

async function answerFoundryQuestion(sessionId, answer, timeoutMs = 5000) {
  return postJson(`${PERSONAS_URL}/interview/answer`, { session_id: sessionId, answer }, timeoutMs);
}

async function compileFoundry(sessionId, timeoutMs = 60000) {
  return postJson(`${PERSONAS_URL}/compile`, { session_id: sessionId }, timeoutMs);
}

async function runFoundryStressTest(payload, timeoutMs = 120000) {
  return postJson(`${PERSONAS_URL}/test-suite/run`, payload, timeoutMs);
}

async function warmupRuntime({ stt = false, llm = false, hotkeys = false } = {}, timeoutMs = 120000) {
  return proxyRequest('POST', RUNTIME_WARMUP_URL, { stt, llm, hotkeys }, timeoutMs);
}

function normalizeBooleanStatus(value) {
  return value ? 'ready' : 'offline';
}

function normalizeHealthPayload(payload) {
  return {
    backendStatus: payload?.status ? String(payload.status) : 'offline',
    transcriberStatus: normalizeBooleanStatus(payload?.transcriber),
    llmEngineStatus: normalizeBooleanStatus(payload?.llm_engine),
    raw: payload ?? null,
  };
}

function connectVoiceStatus({
  onConnectionChange,
  onMessage,
  onError,
} = {}) {
  // Phase 3c: the voice-status WebSocket runs in the main process (it needs the
  // token). The renderer subscribes to forwarded messages + state and never
  // touches a socket or the credential. Reconnect is handled in main.
  const voiceStatus = window.betterFingers && window.betterFingers.voiceStatus;
  if (!voiceStatus) {
    if (typeof onError === 'function') {
      onError(new Error('Voice status bridge is unavailable.'));
    }
    return { close() {} };
  }

  const offMessage = voiceStatus.onMessage((data) => {
    try {
      if (typeof onMessage === 'function') {
        onMessage(data);
      }
    } catch (error) {
      if (typeof onError === 'function') {
        onError(error);
      }
    }
  });

  const offState = voiceStatus.onState(({ state, detail } = {}) => {
    if (state === 'error') {
      if (typeof onError === 'function') {
        onError(new Error(detail || 'Voice status error'));
      }
      return;
    }
    if (typeof onConnectionChange === 'function') {
      onConnectionChange(state, detail);
    }
  });

  voiceStatus.start();

  return {
    close() {
      if (typeof offMessage === 'function') offMessage();
      if (typeof offState === 'function') offState();
      voiceStatus.stop();
    },
  };
}

export {
  BACKEND_ORIGIN,
  CAPABILITIES_URL,
  DIAGNOSTICS_LOGS_URL,
  DIAGNOSTICS_PATHS_URL,
  SUPPORT_REPORT_URL,
  DRAFTS_URL,
  HEALTH_URL,
  RUNTIME_ERRORS_URL,
  RUNTIME_EMERGENCY_STOP_URL,
  RUNTIME_OUTPUT_SETTINGS_URL,
  RUNTIME_PRIMARY_ACTION_URL,
  RUNTIME_RECORDING_TOGGLE_URL,
  RUNTIME_STATUS_URL,
  RUNTIME_WARMUP_URL,
  SETTINGS_PROFILES_URL,
  VOICE_STATUS_WS_URL,
  acceptDraft,
  activateProfile,
  connectVoiceStatus,
  createProfile,
  deleteProfile,
  deleteLlmModel,
  deleteWhisperModel,
  declineDraft,
  clearDrafts,
  downloadLlmModel,
  downloadWhisperModel,
  editDraft,
  emergencyStop,
  fetchCapabilities,
  fetchDiagnosticsLogs,
  fetchDiagnosticsPaths,
  fetchSupportReport,
  fetchMetrics,
  fetchPrivacy,
  wipeData,
  fetchRecordings,
  retranscribeRecording,
  deleteRecording,
  clearRecordings,
  fetchJobs,
  cancelJob,
  fetchDictionary,
  addDictionaryTerm,
  deleteDictionaryTerm,
  suggestDictionaryTerms,
  searchHistory,
  fetchHistoryRecent,
  clearHistory,
  fetchModelRecommendation,
  fetchMacros,
  addMacro,
  deleteMacro,
  fetchPersonas,
  fetchBuiltinPersonaNames,
  getPersonaV2,
  fetchTtsVoices,
  provisionVoiceCloning,
  fetchVoicePresets,
  saveVoicePreset,
  deleteVoicePreset,
  setDefaultVoicePreset,
  clearDefaultVoicePreset,
  speakPreset,
  fetchCloneStatus,
  fetchTtsStatus,
  stopTts,
  cloneVoice,
  fetchWakeStatus,
  fetchWakeModels,
  enableWake,
  disableWake,
  downloadWakeModel,
  fetchWakeModelDownloadState,
  deleteWakeModel,
  testWake,
  trainWakePhrase,
  fetchWakeTrainStatus,
  importWakeModel,
  deleteVoice,
  lintPersona,
  testPersona,
  refinePersonaPrompt,
  draftPersonaFromDescription,
  savePersona,
  deletePersona,
  startFoundryInterview,
  answerFoundryQuestion,
  compileFoundry,
  runFoundryStressTest,
  fetchDrafts,
  fetchHealth,
  fetchLatestDraft,
  fetchLlmDownloadState,
  fetchLlmModels,
  fetchOutputSettings,
  fetchProfile,
  fetchProfiles,
  fetchRuntimeErrors,
  fetchRuntimeStatus,
  fetchWhisperModels,
  retryDraft,
  rewriteDraft,
  runPrimaryAction,
  saveProfile,
  renameProfile,
  duplicateProfile,
  exportProfile,
  importProfile,
  sendDraft,
  selectLlmModel,
  selectWhisperModel,
  speakDraft,
  speakTts,
  toggleRecording,
  unloadModel,
  warmupRuntime,
  normalizeHealthPayload,
  fetchDoctor,
  refreshAudioDevices,
  fetchVersion,
};
