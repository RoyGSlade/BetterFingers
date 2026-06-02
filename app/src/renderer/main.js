import {
  connectVoiceStatus,
  fetchHealth,
  normalizeHealthPayload,
} from './api/backend.js';

const backendStatusEl = document.getElementById('backendStatus');
const backendDetailEl = document.getElementById('backendDetail');
const transcriberStatusEl = document.getElementById('transcriberStatus');
const llmStatusEl = document.getElementById('llmStatus');
const wsConnectionEl = document.getElementById('wsConnection');
const voiceStatusEl = document.getElementById('voiceStatus');
const voiceStatusDetailEl = document.getElementById('voiceStatusDetail');
const quitButton = document.getElementById('quitButton');

let healthRefreshTimer = null;
let websocketHandle = null;

function setBadgeState(el, text, tone) {
  if (!el) {
    return;
  }

  el.textContent = text;
  el.dataset.tone = tone;
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
