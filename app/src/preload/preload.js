const { contextBridge, ipcRenderer } = require('electron');

const authToken = ipcRenderer.sendSync('app:get-auth-token-sync');

const api = {
  authToken,
  quitApp: () => ipcRenderer.invoke('app:quit'),
  showApp: () => ipcRenderer.invoke('app:show'),
  getAppState: () => ipcRenderer.invoke('app:get-state'),
  getSidecarStatus: () => ipcRenderer.invoke('sidecar:get-status'),
  getSidecarLogs: () => ipcRenderer.invoke('sidecar:get-logs'),
  writeClipboardText: (text) => ipcRenderer.invoke('clipboard:write-text', text),
  updateOverlayStatus: (status) => ipcRenderer.invoke('overlay:update-status', status),
  showReviewOverlay: (draft) => ipcRenderer.invoke('review:show', draft),
  hideReviewOverlay: () => ipcRenderer.invoke('review:hide'),
  updateHotkeys: (config) => ipcRenderer.send('update-hotkeys', config),
};

contextBridge.exposeInMainWorld('betterFingers', api);

contextBridge.exposeInMainWorld('betterFingersOverlay', {
  onStatusUpdate: (callback) => ipcRenderer.on('overlay:update', (_event, status) => callback(status)),
});

contextBridge.exposeInMainWorld('betterFingersReview', {
  hide: () => ipcRenderer.invoke('review:hide'),
  onDraft: (callback) => ipcRenderer.on('review:draft', (_event, draft) => callback(draft)),
  onStatus: (callback) => ipcRenderer.on('review:status', (_event, status) => callback(status)),
});
