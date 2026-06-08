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
const DRAFTS_URL = `${BACKEND_ORIGIN}/drafts`;
const RUNTIME_ERRORS_URL = `${BACKEND_ORIGIN}/runtime/errors`;
const SETTINGS_PROFILES_URL = `${BACKEND_ORIGIN}/settings/profiles`;
const MODELS_LLM_URL = `${BACKEND_ORIGIN}/models/llm`;
const MODELS_WHISPER_URL = `${BACKEND_ORIGIN}/models/whisper`;
const MODELS_UNLOAD_URL = `${BACKEND_ORIGIN}/models/unload`;
const VOICE_STATUS_WS_URL = 'ws://127.0.0.1:8000/ws/voice_status';
const DOCTOR_URL = `${BACKEND_ORIGIN}/doctor`;
const REFRESH_AUDIO_DEVICES_URL = `${BACKEND_ORIGIN}/runtime/audio-devices/refresh`;
const RUNTIME_VERSION_URL = `${BACKEND_ORIGIN}/runtime/version`;
const PERSONAS_URL = `${BACKEND_ORIGIN}/personas`;
const TTS_VOICES_URL = `${BACKEND_ORIGIN}/tts/voices`;
const AUTH_TOKEN = window.betterFingers?.authToken || '';

function getHeaders() {
  const headers = { 'Content-Type': 'application/json' };
  if (AUTH_TOKEN) {
    headers['Authorization'] = `Bearer ${AUTH_TOKEN}`;
  }
  return headers;
}

function getAuthHeaders() {
  const headers = {};
  if (AUTH_TOKEN) {
    headers['Authorization'] = `Bearer ${AUTH_TOKEN}`;
  }
  return headers;
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
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(HEALTH_URL, {
      cache: 'no-store',
      headers: getHeaders(),
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
      headers: getHeaders(),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(await getResponseErrorMessage(response, url));
    }

    return await response.json();
  } catch (error) {
    throw normalizeFetchError(error, timeoutMs);
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

async function downloadLlmModel(modelId, timeoutMs = 10000) {
  return postJson(`${MODELS_LLM_URL}/${encodeURIComponent(modelId)}/download`, {}, timeoutMs);
}

async function fetchLlmDownloadState(modelId, timeoutMs = 2500) {
  return fetchJson(`${MODELS_LLM_URL}/${encodeURIComponent(modelId)}/download-state`, timeoutMs);
}

async function deleteLlmModel(modelId, timeoutMs = 10000) {
  return deleteJson(`${MODELS_LLM_URL}/${encodeURIComponent(modelId)}`, timeoutMs);
}

async function fetchWhisperModels(timeoutMs = 2500) {
  return fetchJson(MODELS_WHISPER_URL, timeoutMs);
}

async function downloadWhisperModel(modelSize, preferGpu = true, timeoutMs = 1800000) {
  return postJson(`${MODELS_WHISPER_URL}/download`, { model_size: modelSize, prefer_gpu: preferGpu }, timeoutMs);
}

async function testWhisperModel(modelSize, preferGpu = true, timeoutMs = 300000) {
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
      headers: getHeaders(),
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(await getResponseErrorMessage(response, url));
    }

    return await response.json();
  } catch (error) {
    throw normalizeFetchError(error, timeoutMs);
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
      headers: getHeaders(),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(await getResponseErrorMessage(response, url));
    }

    return await response.json();
  } catch (error) {
    throw normalizeFetchError(error, timeoutMs);
  } finally {
    clearTimeout(timeoutId);
  }
}

function normalizeFetchError(error, timeoutMs) {
  const message = String(error?.message || error || '');
  if (error?.name === 'AbortError' || message.toLowerCase().includes('aborted')) {
    return new Error(`Request timed out after ${Math.round(timeoutMs / 1000)} seconds. The local model may still be loading or generating.`);
  }
  return error;
}

async function getResponseErrorMessage(response, url) {
  try {
    const payload = await response.json();
    const detail = payload?.detail || payload?.message || payload?.error;
    if (Array.isArray(detail)) {
      return detail.map((item) => item?.msg || JSON.stringify(item)).join('; ');
    }
    if (detail) {
      return String(detail);
    }
  } catch (_error) {
    // Fall through to the generic status message.
  }
  return `${url} failed with status ${response.status}`;
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

async function speakDraft(id, { text = '', voiceId = 'standard_female', speed = 1.0, pitch = 1.0 } = {}, timeoutMs = 120000) {
  return postJson(
    `${DRAFTS_URL}/${id}/tts`,
    { text, voice_id: voiceId, speed, pitch },
    timeoutMs,
  );
}

async function speakTts(text, voiceId = 'standard_female', speed = 1.0, pitch = 1.0, timeoutMs = 120000) {
  return postJson(
    `${BACKEND_ORIGIN}/tts/speak`,
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

async function toggleRecording(timeoutMs = 120000) {
  return postJson(RUNTIME_RECORDING_TOGGLE_URL, {}, timeoutMs);
}

async function fetchPersonas(timeoutMs = 2500) {
  return fetchJson(PERSONAS_URL, timeoutMs);
}

async function fetchTtsVoices(timeoutMs = 2500) {
  return fetchJson(TTS_VOICES_URL, timeoutMs);
}

async function savePersona(name, prompt, timeoutMs = 5000) {
  return postJson(PERSONAS_URL, { name, prompt }, timeoutMs);
}

async function deletePersona(name, timeoutMs = 5000) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${PERSONAS_URL}/${encodeURIComponent(name)}`, {
      method: 'DELETE',
      headers: getHeaders(),
      cache: 'no-store',
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`DELETE ${PERSONAS_URL}/${name} failed with status ${response.status}`);
    }

    return await response.json();
  } finally {
    clearTimeout(timeoutId);
  }
}

async function warmupRuntime({ stt = false, llm = false, hotkeys = false } = {}, timeoutMs = 120000) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(RUNTIME_WARMUP_URL, {
      method: 'POST',
      headers: getHeaders(),
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

    const wsUrl = AUTH_TOKEN 
      ? `${VOICE_STATUS_WS_URL}?token=${encodeURIComponent(AUTH_TOKEN)}`
      : VOICE_STATUS_WS_URL;
    socket = new WebSocket(wsUrl);

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

// --- Studio Mode API ---
const STUDIO_URL = `${BACKEND_ORIGIN}/studio`;

// Build an HTTP URL for a file inside a project's folder. The renderer runs from an
// http:// origin, so file:// URLs are blocked; assets must be served by the backend.
// `version` cache-busts so a freshly uploaded image replaces the old one.
function studioAssetUrl(projectName, relPath, version = '') {
  if (!projectName || !relPath) {
    return '';
  }
  const encoded = String(relPath).split('/').map(encodeURIComponent).join('/');
  const base = `${STUDIO_URL}/projects/${encodeURIComponent(projectName)}/assets/${encoded}`;
  return version ? `${base}?v=${encodeURIComponent(version)}` : base;
}

async function studioCreateProject(projectName, timeoutMs = 10000) {
  return postJson(`${STUDIO_URL}/project/create`, { project_name: projectName }, timeoutMs);
}

async function studioLoadProject(projectName, timeoutMs = 10000) {
  return postJson(`${STUDIO_URL}/project/load`, { project_name: projectName }, timeoutMs);
}

async function studioListProjects(timeoutMs = 10000) {
  try {
    return await fetchJson(`${STUDIO_URL}/project/list`, timeoutMs);
  } catch (error) {
    if (!String(error.message || '').toLowerCase().includes('not found')) {
      throw error;
    }
    return fetchJson(`${STUDIO_URL}/projects`, timeoutMs);
  }
}

async function studioIntakeTurn(projectName, chatHistory, timeoutMs = 240000) {
  return postJson(`${STUDIO_URL}/workflow/intake/turn`, { project_name: projectName, chat_history: chatHistory }, timeoutMs);
}

async function studioRunWorkflow(projectName, seedText, mode = 'seed', sourceStory = null, timeoutMs = 600000) {
  const body = { project_name: projectName, seed_text: seedText, mode };
  if (sourceStory) body.source_story = sourceStory;
  return postJson(`${STUDIO_URL}/workflow/run`, body, timeoutMs);
}

async function studioBriefReview(projectName, seedText, mode = 'seed', sourceStory = null, userNotes = '', timeoutMs = 300000) {
  const body = { project_name: projectName, seed_text: seedText, mode, user_notes: userNotes };
  if (sourceStory) body.source_story = sourceStory;
  return postJson(`${STUDIO_URL}/workflow/brief`, body, timeoutMs);
}

async function studioRunStage(projectName, stage, seedText = null, timeoutMs = 240000) {
  const body = { project_name: projectName, stage };
  if (seedText) body.seed_text = seedText;
  return postJson(`${STUDIO_URL}/workflow/stage`, body, timeoutMs);
}

async function studioGetPanels(projectName, projectId, timeoutMs = 10000) {
  return fetchJson(`${STUDIO_URL}/project/${encodeURIComponent(projectName)}/${projectId}/panels`, timeoutMs);
}

// --- Cinematic scene player (Phase 4) ---
async function studioGetScenes(projectName, timeoutMs = 15000) {
  return fetchJson(`${STUDIO_URL}/projects/${encodeURIComponent(projectName)}/scenes`, timeoutMs);
}

// Write every scene (script + image) from the approved blueprint. Long-running.
async function studioRunScenes(projectName, timeoutMs = 600000) {
  return postJson(`${STUDIO_URL}/workflow/stage`,
    { project_name: projectName, stage: 'scenes' }, timeoutMs);
}

// Per-scene reject/refine. target: 'script' | 'image' | 'all'.
async function studioRegenerateScene(projectName, sceneId, target = 'all', feedback = '', timeoutMs = 240000) {
  return postJson(`${STUDIO_URL}/workflow/scene/regenerate`,
    { project_name: projectName, scene_id: sceneId, target, feedback }, timeoutMs);
}

// Cinematic stages (thin wrappers over the unified stage endpoint).
async function studioRunCinematicStage(projectName, stage, timeoutMs = 600000) {
  return postJson(`${STUDIO_URL}/workflow/stage`, { project_name: projectName, stage }, timeoutMs);
}
async function studioRenderImages(projectName, timeoutMs = 600000) {
  return studioRunCinematicStage(projectName, 'render', timeoutMs);
}
async function studioVoiceScenes(projectName, timeoutMs = 600000) {
  return studioRunCinematicStage(projectName, 'voice', timeoutMs);
}
async function studioSceneContinuity(projectName, timeoutMs = 240000) {
  return studioRunCinematicStage(projectName, 'scene_continuity', timeoutMs);
}
async function studioRenderStatus(projectName, timeoutMs = 15000) {
  return fetchJson(`${STUDIO_URL}/projects/${encodeURIComponent(projectName)}/render-status`, timeoutMs);
}

// In-process image model catalog + download (Studio downloads + runs the model itself).
async function studioListImageModels(timeoutMs = 10000) {
  return fetchJson(`${STUDIO_URL}/models/image`, timeoutMs);
}
async function studioDownloadImageModel(modelKey, timeoutMs = 15000) {
  return postJson(`${STUDIO_URL}/models/image/${encodeURIComponent(modelKey)}/download`, {}, timeoutMs);
}
async function studioImageModelDownloadState(modelKey, timeoutMs = 10000) {
  return fetchJson(`${STUDIO_URL}/models/image/${encodeURIComponent(modelKey)}/download-state`, timeoutMs);
}

async function studioCreatePage(projectName, episodeId, pageNumber, title = '', summary = '', timeoutMs = 10000) {
  return postJson(
    `${STUDIO_URL}/projects/${encodeURIComponent(projectName)}/pages`,
    { episode_id: episodeId, page_number: pageNumber, title, summary },
    timeoutMs
  );
}

async function studioCreatePanel(projectName, panel, timeoutMs = 10000) {
  return postJson(`${STUDIO_URL}/projects/${encodeURIComponent(projectName)}/panels`, panel, timeoutMs);
}

async function studioApproveItem(projectName, projectId, itemType, itemId, approved, feedback = null, timeoutMs = 20000) {
  return postJson(`${STUDIO_URL}/project/approve`, { project_name: projectName, project_id: projectId, item_type: itemType, item_id: itemId, approved, feedback }, timeoutMs);
}

async function studioDeleteProject(projectName, timeoutMs = 10000) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${STUDIO_URL}/project/${encodeURIComponent(projectName)}`, {
      method: 'DELETE',
      headers: getHeaders(),
      signal: controller.signal,
    });
    if (!response.ok) {
      const errorData = await response.json().catch(() => null);
      throw new Error(errorData?.detail || `HTTP error ${response.status}`);
    }
    return await response.json();
  } finally {
    clearTimeout(timeoutId);
  }
}

async function studioResolveWarning(projectName, warningId, timeoutMs = 10000) {
  return postJson(`${STUDIO_URL}/project/warning/resolve`, { project_name: projectName, warning_id: warningId }, timeoutMs);
}

async function studioRepairPropose(projectName, report, userNote = '', timeoutMs = 240000) {
  return postJson(`${STUDIO_URL}/workflow/repair/propose`, { project_name: projectName, report, user_note: userNote }, timeoutMs);
}

async function studioUpdateStoryboard(projectName, projectId, storyboard, note = '', timeoutMs = 20000) {
  return postJson(
    `${STUDIO_URL}/workflow/storyboard`,
    { project_name: projectName, project_id: projectId, storyboard, note },
    timeoutMs,
  );
}

async function studioTranscribeEdit(projectName, projectId, targetType, targetId, file, timeoutMs = 180000) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  const form = new FormData();
  form.append('project_name', projectName);
  if (projectId) form.append('project_id', String(projectId));
  form.append('target_type', targetType || 'storyboard');
  if (targetId) form.append('target_id', String(targetId));
  form.append('file', file);

  try {
    const response = await fetch(`${STUDIO_URL}/workflow/transcribe-edit`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: form,
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(await getResponseErrorMessage(response, `${STUDIO_URL}/workflow/transcribe-edit`));
    }
    return await response.json();
  } catch (error) {
    throw normalizeFetchError(error, timeoutMs);
  } finally {
    clearTimeout(timeoutId);
  }
}

async function fetchStudioBlackboard(projectName, timeoutMs = 5000) {
  return fetchJson(`${STUDIO_URL}/projects/${encodeURIComponent(projectName)}/blackboard`, timeoutMs);
}

async function studioUploadPanelImage(projectName, projectId, panelId, file, timeoutMs = 60000) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  const form = new FormData();
  form.append('project_name', projectName);
  form.append('project_id', String(projectId));
  form.append('panel_id', String(panelId));
  form.append('file', file);

  try {
    const response = await fetch(`${STUDIO_URL}/project/panel-image`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: form,
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(await getResponseErrorMessage(response, `${STUDIO_URL}/project/panel-image`));
    }
    return await response.json();
  } finally {
    clearTimeout(timeoutId);
  }
}

async function studioExportReel(projectName, projectId = null, timeoutMs = 60000) {
  return postJson(`${STUDIO_URL}/project/export-reel`, { project_name: projectName, project_id: projectId }, timeoutMs);
}

async function studioPrepareAudio(projectName, text, profileName = "default") {
  return postJson(`${STUDIO_URL}/projects/${encodeURIComponent(projectName)}/audio/prepare`, { text, profile_name: profileName });
}

async function studioRenderAudio(projectName, chunks) {
  return postJson(`${STUDIO_URL}/projects/${encodeURIComponent(projectName)}/audio/render`, { chunks });
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
  fetchPersonas,
  fetchTtsVoices,
  savePersona,
  deletePersona,
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
  speakDraft,
  speakTts,
  testWhisperModel,
  toggleRecording,
  unloadModel,
  warmupRuntime,
  normalizeHealthPayload,
  fetchDoctor,
  refreshAudioDevices,
  fetchVersion,
  studioCreateProject,
  studioListProjects,
  studioLoadProject,
  studioIntakeTurn,
  studioRunWorkflow,
  studioRunStage,
  studioGetPanels,
  studioGetScenes,
  studioRunScenes,
  studioRegenerateScene,
  studioRunCinematicStage,
  studioRenderImages,
  studioVoiceScenes,
  studioSceneContinuity,
  studioRenderStatus,
  studioListImageModels,
  studioDownloadImageModel,
  studioImageModelDownloadState,
  studioCreatePage,
  studioCreatePanel,
  studioApproveItem,
  studioBriefReview,
  studioResolveWarning,
  studioRepairPropose,
  studioUpdateStoryboard,
  studioTranscribeEdit,
  studioAssetUrl,
  fetchStudioBlackboard,
  studioUploadPanelImage,
  studioDeleteProject,
  studioExportReel,
  studioPrepareAudio,
  studioRenderAudio,
};
