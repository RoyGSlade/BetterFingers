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
  wipePrivacyData: ({ wipeVoices, confirm, mode } = {}, timeoutMs) =>
    ipcRenderer.invoke('backend:wipe-privacy', { wipeVoices, confirm, mode, timeoutMs }),
  factoryReset: ({ confirm, deleteDownloadedModels } = {}, timeoutMs) =>
    ipcRenderer.invoke('backend:factory-reset', { confirm, deleteDownloadedModels, timeoutMs }),
  clearPersonaLearning: ({ confirm } = {}, timeoutMs) =>
    ipcRenderer.invoke('backend:clear-persona-learning', { confirm, timeoutMs }),
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
  getAppVersion: () => ipcRenderer.invoke('app:get-version'),
  updates: {
    getState: () => ipcRenderer.invoke('updates:get-state'),
    check: () => ipcRenderer.invoke('updates:check'),
    download: () => ipcRenderer.invoke('updates:download'),
    install: () => ipcRenderer.invoke('updates:install'),
    onState: (callback) => {
      if (typeof callback !== 'function') return () => {};
      const handler = (_event, state) => callback(state);
      ipcRenderer.on('updates:state', handler);
      return () => ipcRenderer.removeListener('updates:state', handler);
    },
  },
  // Durable onboarding consent record. quit reuses the existing app:quit
  // channel so declining consent exits through the ordinary shutdown path.
  onboarding: {
    getState: () => ipcRenderer.invoke('onboarding:get-state'),
    accept: ({ consentVersion } = {}) => ipcRenderer.invoke('onboarding:accept', { consentVersion }),
    completeStep: (stepId) => ipcRenderer.invoke('onboarding:complete-step', { stepId }),
    migrateLegacy: ({ legacyComplete } = {}) =>
      ipcRenderer.invoke('onboarding:migrate-legacy', { legacyComplete }),
    quit: () => ipcRenderer.invoke('app:quit'),
  },
  // Wave 9. Discovery returns UNCONFIRMED candidates; confirm is the only
  // writer. Nothing here launches anything.
  applications: {
    list: () => ipcRenderer.invoke('applications:list'),
    discover: () => ipcRenderer.invoke('applications:discover'),
    confirm: (entry) => ipcRenderer.invoke('applications:confirm', entry),
    remove: (id) => ipcRenderer.invoke('applications:remove', { id }),
  },
  // Wave 10 / D-0027. One channel, one argument: a workflow id. The main
  // process re-fetches and re-validates through POST /workflows/run and runs
  // only what the backend says is approved, so nothing the renderer can say
  // here describes work to the launcher. There is deliberately no channel that
  // takes steps, a plan, or a preview.
  workflows: {
    execute: (workflowId) => ipcRenderer.invoke('workflows:execute', { workflowId }),
  },
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
  setIgnoreMouseEvents: (ignore) => ipcRenderer.invoke('overlay:set-ignore-mouse-events', ignore),
});

contextBridge.exposeInMainWorld('betterFingersSplash', {
  // Pushed by main every ~500ms while booting (see main.js's pushBootSnapshot).
  onBootEvent: (callback) => {
    const handler = (_event, snapshot) => callback(snapshot);
    ipcRenderer.on('splash:boot', handler);
    return () => ipcRenderer.removeListener('splash:boot', handler);
  },
  // Pull for the first paint, in case boot started before this page attached
  // its listener.
  getState: () => ipcRenderer.invoke('splash:get-state'),
  retry: () => ipcRenderer.invoke('splash:retry'),
});

contextBridge.exposeInMainWorld('betterFingersReview', {
  hide: () => ipcRenderer.invoke('review:hide'),
  onDraft: (callback) => ipcRenderer.on('review:draft', (_event, draft) => callback(draft)),
  onStatus: (callback) => ipcRenderer.on('review:status', (_event, status) => callback(status)),
});
