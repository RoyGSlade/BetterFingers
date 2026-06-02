const BACKEND_ORIGIN = 'http://127.0.0.1:8000';
const HEALTH_URL = `${BACKEND_ORIGIN}/health`;
const RUNTIME_STATUS_URL = `${BACKEND_ORIGIN}/runtime/status`;
const RUNTIME_WARMUP_URL = `${BACKEND_ORIGIN}/runtime/warmup`;
const RUNTIME_OUTPUT_SETTINGS_URL = `${BACKEND_ORIGIN}/runtime/output-settings`;
const RUNTIME_PRIMARY_ACTION_URL = `${BACKEND_ORIGIN}/runtime/primary-action`;
const RUNTIME_EMERGENCY_STOP_URL = `${BACKEND_ORIGIN}/runtime/emergency-stop`;
const CAPABILITIES_URL = `${BACKEND_ORIGIN}/capabilities`;
const DIAGNOSTICS_LOGS_URL = `${BACKEND_ORIGIN}/diagnostics/logs`;
const DIAGNOSTICS_PATHS_URL = `${BACKEND_ORIGIN}/diagnostics/paths`;
const DRAFTS_URL = `${BACKEND_ORIGIN}/drafts`;
const RUNTIME_ERRORS_URL = `${BACKEND_ORIGIN}/runtime/errors`;
const SETTINGS_PROFILES_URL = `${BACKEND_ORIGIN}/settings/profiles`;
const MODELS_LLM_URL = `${BACKEND_ORIGIN}/models/llm`;
const MODELS_WHISPER_URL = `${BACKEND_ORIGIN}/models/whisper`;
const MODELS_UNLOAD_URL = `${BACKEND_ORIGIN}/models/unload`;
const VOICE_STATUS_WS_URL = 'ws://127.0.0.1:8000/ws/voice_status';

async function fetchHealth(timeoutMs = 2500) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(HEALTH_URL, {
      cache: 'no-store',
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`Health check failed with status ${response.status}`);
    }

    return await response.json();
  } finally {
    clearTimeout(timeoutId);
  }
}

async function fetchJson(url, timeoutMs = 2500) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      cache: 'no-store',
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`${url} failed with status ${response.status}`);
    }

    return await response.json();
  } finally {
    clearTimeout(timeoutId);
  }
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
  return fetchJson(`${SETTINGS_PROFILES_URL}/${encodeURIComponent(name)}`, timeoutMs);
}

async function saveProfile(name, settings, timeoutMs = 10000) {
  return postJson(`${SETTINGS_PROFILES_URL}/${encodeURIComponent(name)}`, { settings }, timeoutMs);
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

async function fetchCapabilities(timeoutMs = 2500) {
  return fetchJson(CAPABILITIES_URL, timeoutMs);
}

async function fetchDiagnosticsLogs(lines = 80, timeoutMs = 2500) {
  return fetchJson(`${DIAGNOSTICS_LOGS_URL}?lines=${encodeURIComponent(lines)}`, timeoutMs);
}

async function fetchDiagnosticsPaths(timeoutMs = 2500) {
  return fetchJson(DIAGNOSTICS_PATHS_URL, timeoutMs);
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

async function downloadLlmModel(modelId, timeoutMs = 120000) {
  return postJson(`${MODELS_LLM_URL}/${encodeURIComponent(modelId)}/download`, {}, timeoutMs);
}

async function deleteLlmModel(modelId, timeoutMs = 10000) {
  return deleteJson(`${MODELS_LLM_URL}/${encodeURIComponent(modelId)}`, timeoutMs);
}

async function fetchWhisperModels(timeoutMs = 2500) {
  return fetchJson(MODELS_WHISPER_URL, timeoutMs);
}

async function downloadWhisperModel(modelSize, preferGpu = true, timeoutMs = 120000) {
  return postJson(`${MODELS_WHISPER_URL}/download`, { model_size: modelSize, prefer_gpu: preferGpu }, timeoutMs);
}

async function testWhisperModel(modelSize, preferGpu = true, timeoutMs = 120000) {
  return postJson(`${MODELS_WHISPER_URL}/test`, { model_size: modelSize, prefer_gpu: preferGpu }, timeoutMs);
}

async function deleteWhisperModel(modelSize, timeoutMs = 10000) {
  return deleteJson(`${MODELS_WHISPER_URL}/${encodeURIComponent(modelSize)}`, timeoutMs);
}

async function unloadModel(component, timeoutMs = 10000) {
  return postJson(`${MODELS_UNLOAD_URL}/${encodeURIComponent(component)}`, {}, timeoutMs);
}

async function fetchLatestDraft(timeoutMs = 2500) {
  return fetchJson(`${DRAFTS_URL}/latest`, timeoutMs);
}

async function postJson(url, payload = {}, timeoutMs = 2500) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`${url} failed with status ${response.status}`);
    }

    return await response.json();
  } finally {
    clearTimeout(timeoutId);
  }
}

async function deleteJson(url, timeoutMs = 2500) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      method: 'DELETE',
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`${url} failed with status ${response.status}`);
    }

    return await response.json();
  } finally {
    clearTimeout(timeoutId);
  }
}

async function acceptDraft(id, timeoutMs = 2500) {
  return postJson(`${DRAFTS_URL}/${id}/accept`, {}, timeoutMs);
}

async function declineDraft(id, timeoutMs = 2500) {
  return postJson(`${DRAFTS_URL}/${id}/decline`, {}, timeoutMs);
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

async function speakDraft(id, { text = '', voiceId = 'standard_female', speed = 1.0, pitch = 1.0 } = {}, timeoutMs = 120000) {
  return postJson(
    `${DRAFTS_URL}/${id}/tts`,
    { text, voice_id: voiceId, speed, pitch },
    timeoutMs,
  );
}

async function sendDraft(id, { action = 'copy_only', openChat = false } = {}, timeoutMs = 120000) {
  return postJson(`${DRAFTS_URL}/${id}/send`, { action, open_chat: openChat }, timeoutMs);
}

async function runPrimaryAction(timeoutMs = 120000) {
  return postJson(RUNTIME_PRIMARY_ACTION_URL, {}, timeoutMs);
}

async function emergencyStop(timeoutMs = 10000) {
  return postJson(RUNTIME_EMERGENCY_STOP_URL, {}, timeoutMs);
}

async function warmupRuntime({ stt = false, llm = false, hotkeys = false } = {}, timeoutMs = 120000) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(RUNTIME_WARMUP_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ stt, llm, hotkeys }),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`Runtime warmup failed with status ${response.status}`);
    }

    return await response.json();
  } finally {
    clearTimeout(timeoutId);
  }
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
  let socket = null;
  let reconnectTimer = null;
  let closedByUser = false;
  let attempt = 0;

  function notifyConnectionChange(state, detail) {
    if (typeof onConnectionChange === 'function') {
      onConnectionChange(state, detail);
    }
  }

  function scheduleReconnect() {
    if (closedByUser) {
      return;
    }

    const delay = Math.min(1000 * (attempt + 1), 5000);
    reconnectTimer = setTimeout(() => {
      connect();
    }, delay);
  }

  function connect() {
    clearTimeout(reconnectTimer);
    attempt += 1;
    notifyConnectionChange('connecting', `Attempt ${attempt}`);

    socket = new WebSocket(VOICE_STATUS_WS_URL);

    socket.addEventListener('open', () => {
      attempt = 0;
      notifyConnectionChange('connected', VOICE_STATUS_WS_URL);
    });

    socket.addEventListener('message', (event) => {
      try {
        const data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
        if (typeof onMessage === 'function') {
          onMessage(data);
        }
      } catch (error) {
        if (typeof onError === 'function') {
          onError(error);
        }
      }
    });

    socket.addEventListener('close', () => {
      notifyConnectionChange('reconnecting', 'Socket closed');
      scheduleReconnect();
    });

    socket.addEventListener('error', () => {
      if (typeof onError === 'function') {
        onError(new Error('Voice status WebSocket error'));
      }
    });
  }

  connect();

  return {
    close() {
      closedByUser = true;
      clearTimeout(reconnectTimer);
      if (socket) {
        socket.close();
      }
    },
  };
}

export {
  BACKEND_ORIGIN,
  CAPABILITIES_URL,
  DIAGNOSTICS_LOGS_URL,
  DIAGNOSTICS_PATHS_URL,
  DRAFTS_URL,
  HEALTH_URL,
  RUNTIME_ERRORS_URL,
  RUNTIME_EMERGENCY_STOP_URL,
  RUNTIME_OUTPUT_SETTINGS_URL,
  RUNTIME_PRIMARY_ACTION_URL,
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
  downloadLlmModel,
  downloadWhisperModel,
  editDraft,
  emergencyStop,
  fetchCapabilities,
  fetchDiagnosticsLogs,
  fetchDiagnosticsPaths,
  fetchDrafts,
  fetchHealth,
  fetchLatestDraft,
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
  sendDraft,
  selectLlmModel,
  speakDraft,
  testWhisperModel,
  unloadModel,
  warmupRuntime,
  normalizeHealthPayload,
};
