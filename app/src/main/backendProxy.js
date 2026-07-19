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

// Backend API surface the renderer is allowed to reach through the generic
// 'backend:request' channel: an EXACT (method, route) table, not prefixes.
// ':param' matches exactly one URL-encoded path segment. Anything not listed
// here is refused — including every destructive operation (privacy wipe,
// model/voice deletion, job cancel, draft send), which are only reachable
// through the dedicated typed IPC channels below with validated payloads.
const ROUTE_ALLOWLIST = {
  GET: [
    '/runtime/status', '/runtime/output-settings', '/runtime/version',
    '/runtime/errors', '/runtime/tts-status',
    '/capabilities', '/doctor', '/metrics', '/privacy',
    '/diagnostics/logs', '/diagnostics/paths',
    '/recordings', '/jobs', '/dictionary', '/macros',
    '/history', '/history/search',
    '/models/recommend', '/models/llm', '/models/llm/:id/download-state',
    '/models/whisper',
    '/settings/profiles', '/settings/profiles/:name',
    '/settings/profiles/:name/export',
    '/personas', '/personas-builtins', '/personas/:name',
    '/personas/:name/examples',
    '/tts/voices', '/voice-presets',
    '/drafts', '/drafts/latest',
    '/wake/status', '/wake/models', '/wake/models/:id/download-state',
    '/wake/train/status',
    '/message-rescue/context', '/message-rescue/generate/:id',
  ],
  POST: [
    '/runtime/audio-devices/refresh', '/runtime/warmup',
    '/runtime/primary-action', '/runtime/emergency-stop',
    '/runtime/recording/toggle',
    '/settings/profiles', '/settings/profiles/import',
    '/settings/profiles/:name', '/settings/profiles/:name/activate',
    '/settings/profiles/:name/rename', '/settings/profiles/:name/duplicate',
    '/recordings/:id/retranscribe',
    '/dictionary', '/dictionary/suggest', '/macros',
    '/models/llm/select', '/models/llm/:id/download',
    '/models/whisper/download', '/models/whisper/select',
    '/models/unload/:component',
    '/drafts/test-mock',
    '/drafts/:id/accept', '/drafts/:id/decline', '/drafts/:id/retry',
    '/drafts/:id/edit', '/drafts/:id/rewrite', '/drafts/:id/tts',
    '/tts/speak', '/tts/stop',
    '/personas', '/personas/lint', '/personas/test',
    '/personas/interview/start', '/personas/interview/answer',
    '/personas/compile', '/personas/test-suite/run',
    '/personas/:name/examples',
    '/voice-presets',
    '/wake/enable', '/wake/disable', '/wake/test', '/wake/train',
    '/wake/models/:id/download',
    '/message-rescue/context/selection', '/message-rescue/context/manual',
    '/message-rescue/generate', '/message-rescue/generate/:id/cancel',
  ],
  DELETE: [
    '/settings/profiles/:name',
    '/recordings/:id', '/recordings',
    '/history', '/drafts',
    '/dictionary/:term', '/macros/:trigger',
    '/voice-presets/:name', '/personas/:name',
    '/personas/:name/examples/:example_id', '/personas/:name/examples',
    '/wake/models/:id',
    '/message-rescue/context',
  ],
};
const ALLOWED_METHODS = new Set(Object.keys(ROUTE_ALLOWLIST));
// One URL-encoded path segment: the characters encodeURIComponent can emit.
const PARAM_SEGMENT = /^[A-Za-z0-9._~%!'()*-]{1,256}$/;
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

function _matchesRoute(pattern, routePart) {
  const patternSegments = pattern.split('/');
  const routeSegments = routePart.split('/');
  if (patternSegments.length !== routeSegments.length) {
    return false;
  }
  return patternSegments.every((seg, i) =>
    seg.startsWith(':') ? PARAM_SEGMENT.test(routeSegments[i]) : seg === routeSegments[i],
  );
}

function _validateRequest(method, path) {
  if (!ALLOWED_METHODS.has(method)) {
    return `method ${method} not allowed`;
  }
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
  if (!ROUTE_ALLOWLIST[method].some((pattern) => _matchesRoute(pattern, routePart))) {
    return `${method} ${routePart} is not an allowed backend route`;
  }
  return null;
}

// JSON request from the generic renderer channel. Returns { ok, status, body }
// where body is parsed JSON (or the raw text if not JSON). Never throws for
// HTTP errors — the renderer inspects ok/status — but returns
// { ok:false, error } for validation/transport faults.
async function request({ method, path, body, timeoutMs } = {}) {
  const upperMethod = String(method || 'GET').toUpperCase();
  const requestError = _validateRequest(upperMethod, path);
  if (requestError) {
    return { ok: false, status: 0, error: requestError };
  }
  return _send(upperMethod, path, body, timeoutMs);
}

// Transport shared by the generic channel (validated above) and the typed
// methods below (which build their own exact method + path from validated
// parameters and never accept a renderer-supplied route).
async function _send(method, path, body, timeoutMs) {
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
      method,
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

// --- Typed backend operations ----------------------------------------------
// Destructive or sensitive operations are NOT reachable through the generic
// channel: each has its own IPC method with an exact route, exact HTTP method,
// and a validated payload, so a compromised renderer cannot smuggle one
// through a broad proxy. Destructive ones additionally require an explicit
// `confirm: true`, set only after the UI's own confirmation step.

const SEND_ACTIONS = new Set(['copy_only', 'paste', 'type', 'open_chat_then_send']);
// Single path segment as the renderer would send it (model ids, job ids,
// voice ids) — never a slash, never empty.
const ID_SEGMENT = /^[A-Za-z0-9._~-]{1,128}$/;

function _fault(error) {
  return { ok: false, status: 0, error };
}

function _requireConfirm(payload) {
  return payload && payload.confirm === true
    ? null
    : _fault('destructive operation requires confirm: true');
}

function fetchHealth({ timeoutMs } = {}) {
  return _send('GET', '/health', undefined, timeoutMs);
}

function sendDraft({ id, action, openChat, allowResend, timeoutMs } = {}) {
  if (!Number.isInteger(id) || id <= 0) {
    return _fault('sendDraft: id must be a positive integer');
  }
  const sendAction = action === undefined ? 'copy_only' : action;
  if (!SEND_ACTIONS.has(sendAction)) {
    return _fault(`sendDraft: unknown action ${String(action)}`);
  }
  return _send('POST', `/drafts/${id}/send`, {
    action: sendAction,
    open_chat: Boolean(openChat),
    allow_resend: Boolean(allowResend),
  }, timeoutMs);
}

function wipePrivacyData({ wipeVoices, confirm, timeoutMs } = {}) {
  return _requireConfirm({ confirm })
    || _send('POST', '/privacy/wipe', { wipe_voices: Boolean(wipeVoices) }, timeoutMs);
}

function deleteLlmModel({ modelId, confirm, timeoutMs } = {}) {
  if (typeof modelId !== 'string' || !ID_SEGMENT.test(modelId)) {
    return _fault('deleteLlmModel: invalid model id');
  }
  return _requireConfirm({ confirm })
    || _send('DELETE', `/models/llm/${encodeURIComponent(modelId)}`, undefined, timeoutMs);
}

function deleteWhisperModel({ modelSize, confirm, timeoutMs } = {}) {
  if (typeof modelSize !== 'string' || !ID_SEGMENT.test(modelSize)) {
    return _fault('deleteWhisperModel: invalid model size');
  }
  return _requireConfirm({ confirm })
    || _send('DELETE', `/models/whisper/${encodeURIComponent(modelSize)}`, undefined, timeoutMs);
}

function deleteVoice({ voiceId, confirm, timeoutMs } = {}) {
  if (typeof voiceId !== 'string' || !ID_SEGMENT.test(voiceId)) {
    return _fault('deleteVoice: invalid voice id');
  }
  return _requireConfirm({ confirm })
    || _send('DELETE', `/tts/voices/${encodeURIComponent(voiceId)}`, undefined, timeoutMs);
}

function cancelJob({ jobId, timeoutMs } = {}) {
  if (typeof jobId !== 'string' || !ID_SEGMENT.test(jobId)) {
    return _fault('cancelJob: invalid job id');
  }
  return _send('POST', `/jobs/${encodeURIComponent(jobId)}/cancel`, {}, timeoutMs);
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

// Upload a user-supplied wake-word classifier .onnx as multipart/form-data.
// Mirrors uploadVoiceSample's shape (renderer passes bytes, main builds the
// FormData so the token is never exposed). Restricted to /wake/models/import.
async function uploadWakeModel({ bytes, filename, name, timeoutMs } = {}) {
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
    form.append('file', new Blob([buf]), String(filename || 'classifier.onnx'));
    form.append('name', String(name || 'Imported model'));
    const response = await fetch(`${_origin}/wake/models/import`, {
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
  uploadWakeModel,
  startVoiceStatus,
  stopVoiceStatus,
  // typed operations (each bound to one exact method + route)
  fetchHealth,
  sendDraft,
  wipePrivacyData,
  deleteLlmModel,
  deleteWhisperModel,
  deleteVoice,
  cancelJob,
  // exported for unit tests
  _validateRequest,
  ROUTE_ALLOWLIST,
  ALLOWED_METHODS,
};
