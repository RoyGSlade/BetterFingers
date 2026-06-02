const BACKEND_ORIGIN = 'http://127.0.0.1:8000';
const HEALTH_URL = `${BACKEND_ORIGIN}/health`;
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
  HEALTH_URL,
  VOICE_STATUS_WS_URL,
  connectVoiceStatus,
  fetchHealth,
  normalizeHealthPayload,
};
