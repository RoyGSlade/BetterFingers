const { contextBridge, ipcRenderer } = require('electron');

// Phase 3c: the renderer never receives the bearer token or the backend origin.
// All backend access goes through the main-process proxy below.
const api = {
  // Validated backend proxy: main attaches the token and enforces the
  // method/path/size allowlist. Returns { ok, status, body } or { ok:false, error }.
  backendRequest: (method, path, body, timeoutMs) =>
    ipcRenderer.invoke('backend:request', { method, path, body, timeoutMs }),
  // Typed operations: destructive/sensitive routes are refused by the generic
  // proxy and only reachable through these fixed-shape channels.
  fetchHealth: (timeoutMs) => ipcRenderer.invoke('backend:fetch-health', { timeoutMs }),
  sendDraft: (id, { action, openChat, allowResend } = {}, timeoutMs) =>
    ipcRenderer.invoke('backend:send-draft', { id, action, openChat, allowResend, timeoutMs }),
  wipePrivacyData: ({ wipeVoices, confirm } = {}, timeoutMs) =>
    ipcRenderer.invoke('backend:wipe-privacy', { wipeVoices, confirm, timeoutMs }),
  deleteLlmModel: (modelId, { confirm } = {}, timeoutMs) =>
    ipcRenderer.invoke('backend:delete-llm-model', { modelId, confirm, timeoutMs }),
  deleteWhisperModel: (modelSize, { confirm } = {}, timeoutMs) =>
    ipcRenderer.invoke('backend:delete-whisper-model', { modelSize, confirm, timeoutMs }),
  deleteVoice: (voiceId, { confirm } = {}, timeoutMs) =>
    ipcRenderer.invoke('backend:delete-voice', { voiceId, confirm, timeoutMs }),
  cancelJob: (jobId, timeoutMs) => ipcRenderer.invoke('backend:cancel-job', { jobId, timeoutMs }),
  uploadVoiceSample: (payload) =>
    ipcRenderer.invoke('backend:upload-voice-sample', payload),
  uploadWakeModel: (payload) =>
    ipcRenderer.invoke('backend:upload-wake-model', payload),
  voiceStatus: {
    start: () => ipcRenderer.invoke('backend:voice-status:start'),
    stop: () => ipcRenderer.invoke('backend:voice-status:stop'),
    onMessage: (callback) => {
      const handler = (_event, data) => callback(data);
      ipcRenderer.on('backend:voice-status:message', handler);
      return () => ipcRenderer.removeListener('backend:voice-status:message', handler);
    },
    onState: (callback) => {
      const handler = (_event, state) => callback(state);
      ipcRenderer.on('backend:voice-status:state', handler);
      return () => ipcRenderer.removeListener('backend:voice-status:state', handler);
    },
  },
  quitApp: () => ipcRenderer.invoke('app:quit'),
  showApp: () => ipcRenderer.invoke('app:show'),
  getAppState: () => ipcRenderer.invoke('app:get-state'),
  getSidecarStatus: () => ipcRenderer.invoke('sidecar:get-status'),
  getSidecarLogs: () => ipcRenderer.invoke('sidecar:get-logs'),
  onSidecarStatus: (callback) =>
    ipcRenderer.on('sidecar:status', (_event, status) => callback(status)),
  writeClipboardText: (text) => ipcRenderer.invoke('clipboard:write-text', text),
  updateOverlayStatus: (status) => ipcRenderer.invoke('overlay:update-status', status),
  getOverlayAppearance: () => ipcRenderer.invoke('overlay:get-appearance'),
  setOverlayAppearance: (appearance) => ipcRenderer.invoke('overlay:set-appearance', appearance),
  showReviewOverlay: (draft) => ipcRenderer.invoke('review:show', draft),
  hideReviewOverlay: () => ipcRenderer.invoke('review:hide'),
  updateHotkeys: (config) => ipcRenderer.send('update-hotkeys', config),
  getHotkeyCapabilities: () => ipcRenderer.invoke('hotkeys:get-capabilities'),
  openPath: (targetPath) => ipcRenderer.invoke('shell:open-path', targetPath),
};

contextBridge.exposeInMainWorld('betterFingers', api);

contextBridge.exposeInMainWorld('betterFingersOverlay', {
  onStatusUpdate: (callback) => ipcRenderer.on('overlay:update', (_event, status) => callback(status)),
  onAppearance: (callback) => ipcRenderer.on('overlay:appearance', (_event, appearance) => callback(appearance)),
});

contextBridge.exposeInMainWorld('betterFingersReview', {
  hide: () => ipcRenderer.invoke('review:hide'),
  onDraft: (callback) => ipcRenderer.on('review:draft', (_event, draft) => callback(draft)),
  onStatus: (callback) => ipcRenderer.on('review:status', (_event, status) => callback(status)),
});
