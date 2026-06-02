import {
  connectVoiceStatus,
  fetchCapabilities,
  fetchHealth,
  fetchRuntimeStatus,
  normalizeHealthPayload,
  warmupRuntime,
} from './api/backend.js';

const backendStatusEl = document.getElementById('backendStatus');
const backendDetailEl = document.getElementById('backendDetail');
const transcriberStatusEl = document.getElementById('transcriberStatus');
const llmStatusEl = document.getElementById('llmStatus');
const wsConnectionEl = document.getElementById('wsConnection');
const voiceStatusEl = document.getElementById('voiceStatus');
const voiceStatusDetailEl = document.getElementById('voiceStatusDetail');
const quitButton = document.getElementById('quitButton');
const refreshRuntimeButton = document.getElementById('refreshRuntimeButton');
const warmupSttButton = document.getElementById('warmupSttButton');
const warmupLlmButton = document.getElementById('warmupLlmButton');
const startHotkeysButton = document.getElementById('startHotkeysButton');
const runtimeStatusListEl = document.getElementById('runtimeStatusList');
const capabilitiesListEl = document.getElementById('capabilitiesList');
const capabilitiesSummaryEl = document.getElementById('capabilitiesSummary');

let healthRefreshTimer = null;
let websocketHandle = null;

function setBadgeState(el, text, tone) {
  if (!el) {
    return;
  }

  el.textContent = text;
  el.dataset.tone = tone;
}

function formatValue(value) {
  if (typeof value === 'boolean') {
    return value ? 'yes' : 'no';
  }

  if (value === null || value === undefined || value === '') {
    return 'unknown';
  }

  return String(value);
}

function renderDetailList(container, values, preferredKeys = []) {
  if (!container) {
    return;
  }

  const keys = preferredKeys.length ? preferredKeys : Object.keys(values ?? {});
  container.innerHTML = '';

  for (const key of keys) {
    if (!Object.prototype.hasOwnProperty.call(values ?? {}, key)) {
      continue;
    }

    const row = document.createElement('div');
    row.className = 'detail-row';

    const label = document.createElement('span');
    label.className = 'detail-label';
    label.textContent = key.replaceAll('_', ' ');

    const value = document.createElement('strong');
    value.className = 'detail-value';
    value.textContent = formatValue(values[key]);
    if (typeof values[key] === 'boolean') {
      value.dataset.tone = values[key] ? 'success' : 'warning';
    }

    row.append(label, value);
    container.append(row);
  }

  if (!container.children.length) {
    container.innerHTML = '<span class="empty-state">No data available</span>';
  }
}

async function refreshHealth() {
  try {
    const payload = await fetchHealth();
    const health = normalizeHealthPayload(payload);

    setBadgeState(backendStatusEl, health.backendStatus, health.backendStatus === 'active' ? 'success' : 'warning');
    if (backendDetailEl) {
      backendDetailEl.textContent = 'FastAPI /health responded successfully';
    }

    setBadgeState(transcriberStatusEl, health.transcriberStatus, health.transcriberStatus === 'ready' ? 'success' : 'warning');
    setBadgeState(llmStatusEl, health.llmEngineStatus, health.llmEngineStatus === 'ready' ? 'success' : 'warning');
  } catch (error) {
    setBadgeState(backendStatusEl, 'offline', 'danger');
    if (backendDetailEl) {
      backendDetailEl.textContent = 'Waiting for the Python backend to start';
    }
    setBadgeState(transcriberStatusEl, 'offline', 'danger');
    setBadgeState(llmStatusEl, 'offline', 'danger');
  }
}

async function refreshRuntime() {
  const runtime = await fetchRuntimeStatus();
  renderDetailList(runtimeStatusListEl, runtime, [
    'transcriber_initialized',
    'transcriber_loaded',
    'llm_initialized',
    'llm_ready',
    'hotkey_manager_started',
  ]);
  return runtime;
}

async function refreshCapabilities() {
  const capabilities = await fetchCapabilities();
  if (capabilitiesSummaryEl) {
    const platform = capabilities.platform ?? 'unknown';
    const session = capabilities.session_type ?? 'unknown';
    capabilitiesSummaryEl.textContent = `${platform} · ${session}`;
  }
  renderDetailList(capabilitiesListEl, capabilities, [
    'platform',
    'session_type',
    'is_linux',
    'is_wayland',
    'is_x11',
    'supports_basic_clipboard',
    'supports_rich_clipboard_restore',
    'supports_input_injection',
    'supports_global_hotkeys',
    'supports_audio_ducking',
    'supports_stt',
    'supports_llm',
    'supports_tts',
  ]);
  return capabilities;
}

async function runWarmup(button, payload) {
  if (!button) {
    return;
  }

  const previousText = button.textContent;
  button.disabled = true;
  button.textContent = 'Working...';

  try {
    await warmupRuntime(payload);
    await Promise.all([refreshHealth(), refreshRuntime()]);
  } catch (error) {
    button.textContent = 'Failed';
    setTimeout(() => {
      button.textContent = previousText;
      button.disabled = false;
    }, 1400);
    return;
  }

  button.textContent = previousText;
  button.disabled = false;
}

function updateConnectionPill(state, detail) {
  if (wsConnectionEl) {
    wsConnectionEl.textContent = detail ? `${state} · ${detail}` : state;
    wsConnectionEl.dataset.state = state;
  }
}

function updateVoiceStatus(message) {
  if (!message) {
    return;
  }

  const statusText = typeof message === 'string' ? message : String(message.status ?? message.type ?? 'unknown');
  voiceStatusEl.textContent = statusText;
  voiceStatusDetailEl.textContent = JSON.stringify(message, null, 2);
}

async function bootstrap() {
  await refreshHealth();
  await Promise.all([
    refreshRuntime().catch(() => {
      renderDetailList(runtimeStatusListEl, {});
    }),
    refreshCapabilities().catch(() => {
      if (capabilitiesSummaryEl) {
        capabilitiesSummaryEl.textContent = 'Unavailable';
      }
      renderDetailList(capabilitiesListEl, {});
    }),
  ]);

  healthRefreshTimer = setInterval(() => {
    refreshHealth();
  }, 3000);

  websocketHandle = connectVoiceStatus({
    onConnectionChange: updateConnectionPill,
    onMessage: updateVoiceStatus,
    onError: (error) => {
      updateConnectionPill('error', error.message);
    },
  });
}

quitButton?.addEventListener('click', () => {
  window.betterFingers?.quitApp?.();
});

refreshRuntimeButton?.addEventListener('click', () => {
  Promise.all([refreshHealth(), refreshRuntime()]);
});

warmupSttButton?.addEventListener('click', () => {
  runWarmup(warmupSttButton, { stt: true });
});

warmupLlmButton?.addEventListener('click', () => {
  runWarmup(warmupLlmButton, { llm: true });
});

startHotkeysButton?.addEventListener('click', () => {
  runWarmup(startHotkeysButton, { hotkeys: true });
});

window.addEventListener('beforeunload', () => {
  if (healthRefreshTimer) {
    clearInterval(healthRefreshTimer);
  }

  if (websocketHandle) {
    websocketHandle.close();
  }
});

bootstrap().catch((error) => {
  setBadgeState(backendStatusEl, 'offline', 'danger');
  if (backendDetailEl) {
    backendDetailEl.textContent = error.message;
  }
  setBadgeState(transcriberStatusEl, 'offline', 'danger');
  setBadgeState(llmStatusEl, 'offline', 'danger');
});
