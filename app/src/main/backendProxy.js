// Main-process proxy for all backend HTTP + the voice-status WebSocket.
//
// Phase 3c: the bearer token used to be handed to the renderer (via preload) so
// the renderer could call the local API directly. That means a renderer XSS
// could exfiltrate the local API credential. Now the token lives ONLY in the
// main process: the renderer asks main to make requests on its behalf through a
// narrow, validated channel, and never sees the token or the real origin.
//
// The proxy is not an open relay — it only reaches the backend origin, only via
// an allowlisted method + path prefix, with bounded body size.

let _origin = 'http://127.0.0.1:8000';
let _token = '';

// Backend API surface the renderer is allowed to reach. A request whose path
// does not start with one of these is refused — the renderer can never be
// tricked into driving an arbitrary URL.
const ALLOWED_PREFIXES = [
  '/health', '/runtime/', '/capabilities', '/diagnostics/', '/doctor',
  '/drafts', '/settings/', '/models/', '/personas', '/recordings',
  '/dictionary', '/macros', '/voice-presets', '/voice-commands', '/tts/',
  '/privacy', '/jobs', '/metrics', '/ocr/', '/graph/', '/mcp/', '/intent/',
  '/llm/', '/hardware/', '/project/', '/transcribe',
];
const ALLOWED_METHODS = new Set(['GET', 'POST', 'PUT', 'DELETE']);
const MAX_BODY_BYTES = 8 * 1024 * 1024; // 8 MB (covers voice-sample uploads)
const MAX_PATH_LEN = 1024;

function init({ origin, token }) {
  if (origin) _origin = String(origin);
  if (token) _token = String(token);
}

function _authHeaders(extra = {}) {
  const headers = { ...extra };
  if (_token) {
    headers.Authorization = `Bearer ${_token}`;
  }
  return headers;
}

function _validatePath(path) {
  if (typeof path !== 'string' || path.length === 0 || path.length > MAX_PATH_LEN) {
    return 'invalid path';
  }
  if (!path.startsWith('/') || path.startsWith('//')) {
    return 'path must be an absolute backend path';
  }
  if (path.includes('://') || path.includes('..') || path.includes('\\')) {
    return 'path must not contain a scheme, traversal, or backslash';
  }
  const routePart = path.split('?', 1)[0];
  if (!ALLOWED_PREFIXES.some((p) => routePart === p || routePart.startsWith(p))) {
    return `path ${routePart} is not an allowed backend route`;
  }
  return null;
}

// JSON request. Returns { ok, status, body } where body is parsed JSON (or the
// raw text if not JSON). Never throws for HTTP errors — the renderer inspects
// ok/status — but returns { ok:false, error } for validation/transport faults.
async function request({ method, path, body, timeoutMs } = {}) {
  const upperMethod = String(method || 'GET').toUpperCase();
  if (!ALLOWED_METHODS.has(upperMethod)) {
    return { ok: false, status: 0, error: `method ${upperMethod} not allowed` };
  }
  const pathError = _validatePath(path);
  if (pathError) {
    return { ok: false, status: 0, error: pathError };
  }

  let serialized;
  if (body !== undefined && body !== null) {
    try {
      serialized = JSON.stringify(body);
    } catch (err) {
      return { ok: false, status: 0, error: 'body is not JSON-serializable' };
    }
    if (Buffer.byteLength(serialized) > MAX_BODY_BYTES) {
      return { ok: false, status: 0, error: 'request body too large' };
    }
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Math.max(1, Number(timeoutMs) || 2500));
  try {
    const init = {
      method: upperMethod,
      cache: 'no-store',
      headers: _authHeaders(serialized !== undefined ? { 'Content-Type': 'application/json' } : {}),
      signal: controller.signal,
    };
    if (serialized !== undefined) {
      init.body = serialized;
    }
    const response = await fetch(`${_origin}${path}`, init);
    const text = await response.text();
    let parsed = text;
    try {
      parsed = text ? JSON.parse(text) : null;
    } catch (_e) {
      // Non-JSON response — return the raw text.
    }
    return { ok: response.ok, status: response.status, body: parsed };
  } catch (err) {
    const aborted = err && (err.name === 'AbortError' || String(err.message || '').includes('aborted'));
    return { ok: false, status: 0, error: aborted ? 'timeout' : String(err && err.message || err) };
  } finally {
    clearTimeout(timer);
  }
}

// Upload a voice sample as multipart/form-data. The renderer passes the file
// bytes (ArrayBuffer) + fields; main builds the FormData so the token is never
// exposed. Restricted to /tts/clone.
async function uploadVoiceSample({ bytes, filename, name, consent, timeoutMs } = {}) {
  if (!bytes) {
    return { ok: false, status: 0, error: 'no file bytes' };
  }
  const buf = Buffer.from(bytes);
  if (buf.byteLength > MAX_BODY_BYTES) {
    return { ok: false, status: 0, error: 'file too large' };
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Math.max(1, Number(timeoutMs) || 30000));
  try {
    const form = new FormData();
    form.append('file', new Blob([buf]), String(filename || 'sample.wav'));
    form.append('name', String(name || 'My Voice'));
    form.append('consent', consent ? 'true' : 'false');
    const response = await fetch(`${_origin}/tts/clone`, {
      method: 'POST',
      headers: _authHeaders(), // fetch sets multipart boundary itself
      body: form,
      signal: controller.signal,
    });
    const text = await response.text();
    let parsed = text;
    try { parsed = text ? JSON.parse(text) : null; } catch (_e) { /* raw text */ }
    return { ok: response.ok, status: response.status, body: parsed };
  } catch (err) {
    const aborted = err && (err.name === 'AbortError' || String(err.message || '').includes('aborted'));
    return { ok: false, status: 0, error: aborted ? 'timeout' : String(err && err.message || err) };
  } finally {
    clearTimeout(timer);
  }
}

// --- Voice-status WebSocket (main-owned) ----------------------------------
// The WS also authenticated with the token; running it in main keeps the token
// out of the renderer entirely. Messages + connection-state are forwarded to
// the bound webContents; reconnect is handled here.
let _ws = null;
let _wsBoundSender = null;
let _reconnectTimer = null;
let _wsClosedByUser = false;
let _wsAttempt = 0;

function _wsUrl() {
  return `${_origin.replace(/^http/, 'ws')}/ws/voice_status`;
}

function _sendToRenderer(channel, payload) {
  if (_wsBoundSender && !_wsBoundSender.isDestroyed()) {
    _wsBoundSender.send(channel, payload);
  }
}

function _connectWs() {
  clearTimeout(_reconnectTimer);
  _wsAttempt += 1;
  _sendToRenderer('backend:voice-status:state', { state: 'connecting', detail: `Attempt ${_wsAttempt}` });
  let socket;
  try {
    socket = new WebSocket(_wsUrl());
  } catch (err) {
    _scheduleReconnect();
    return;
  }
  _ws = socket;

  socket.addEventListener('open', () => {
    _wsAttempt = 0;
    if (_token) {
      socket.send(`auth:${_token}`);
    }
    _sendToRenderer('backend:voice-status:state', { state: 'connected', detail: 'live' });
  });
  socket.addEventListener('message', (event) => {
    const data = event.data;
    if (data === 'auth_ok' || data === 'pong') {
      return;
    }
    try {
      _sendToRenderer('backend:voice-status:message', typeof data === 'string' ? JSON.parse(data) : data);
    } catch (_e) {
      // ignore unparseable frames
    }
  });
  socket.addEventListener('close', () => {
    _sendToRenderer('backend:voice-status:state', { state: 'reconnecting', detail: 'Socket closed' });
    _scheduleReconnect();
  });
  socket.addEventListener('error', () => {
    _sendToRenderer('backend:voice-status:state', { state: 'error', detail: 'WebSocket error' });
  });
}

function _scheduleReconnect() {
  if (_wsClosedByUser) return;
  clearTimeout(_reconnectTimer);
  const delay = Math.min(1000 * (_wsAttempt + 1), 5000);
  _reconnectTimer = setTimeout(_connectWs, delay);
}

function startVoiceStatus(sender) {
  stopVoiceStatus();
  _wsBoundSender = sender;
  _wsClosedByUser = false;
  _wsAttempt = 0;
  _connectWs();
}

function stopVoiceStatus() {
  _wsClosedByUser = true;
  clearTimeout(_reconnectTimer);
  if (_ws) {
    try { _ws.close(); } catch (_e) { /* already closing */ }
    _ws = null;
  }
  _wsBoundSender = null;
}

module.exports = {
  init,
  request,
  uploadVoiceSample,
  startVoiceStatus,
  stopVoiceStatus,
  // exported for unit tests
  _validatePath,
  ALLOWED_PREFIXES,
  ALLOWED_METHODS,
};
