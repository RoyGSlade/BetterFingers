const { contextBridge, ipcRenderer } = require('electron');

// The DASHBOARD's bridge (signal-desk.html, its preview and the legacy index.html).
// The overlay, review window and splash each have their own minimal preload
// (preload-overlay.js, preload-review.js, preload-splash.js) and receive none of
// this: Phase 0 item 7. Main also refuses every channel below from any page that
// is not the dashboard (ipcPolicy.js), so the two layers fail independently.

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
  // Placing a draft into another application. Main shows a native dialog with the
  // exact text and signs the approval the backend requires; this call only asks.
  sendDraft: (id, { action, openChat, allowResend } = {}, timeoutMs) =>
    ipcRenderer.invoke('backend:send-draft', { id, action, openChat, allowResend, timeoutMs }),
  // The Primary Action button: the backend picks the draft, main shows it and asks.
  runPrimaryAction: (timeoutMs) => ipcRenderer.invoke('backend:primary-action', { timeoutMs }),
  // Approvals. The renderer names WHAT to approve (a workflow id, a persona and the
  // example text); main fetches the rest from the backend, shows the person a native
  // dialog and only on their click signs the proof the backend demands. Nothing
  // returned here is, or can be turned into, an approval.
  approveWorkflow: (workflowId, timeoutMs) =>
    ipcRenderer.invoke('approvals:workflow', { workflowId, timeoutMs }),
  addPersonaExample: ({ persona, raw, out } = {}, timeoutMs) =>
    ipcRenderer.invoke('approvals:persona-example', { persona, raw, out, timeoutMs }),
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
  // Bug-report diagnostics never cross this bridge from the renderer. Main
  // gathers and curates them, returns an immutable preview, then accepts only
  // that preview id plus a fixed destination for the final confirmed action.
  getBugReportConfig: () => ipcRenderer.invoke('bug-report:get-config'),
  prepareBugReport: ({ summary, steps, expected, actual, contact } = {}) =>
    ipcRenderer.invoke('bug-report:prepare', { summary, steps, expected, actual, contact }),
  submitBugReport: ({ previewId, destination } = {}) =>
    ipcRenderer.invoke('bug-report:submit', { previewId, destination }),
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
    setAutomatic: (enabled) => ipcRenderer.invoke('updates:set-automatic', enabled),
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
