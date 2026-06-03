const { contextBridge, ipcRenderer } = require('electron');

const api = {
  quitApp: () => ipcRenderer.invoke('app:quit'),
  showApp: () => ipcRenderer.invoke('app:show'),
  getAppState: () => ipcRenderer.invoke('app:get-state'),
  getSidecarStatus: () => ipcRenderer.invoke('sidecar:get-status'),
  getSidecarLogs: () => ipcRenderer.invoke('sidecar:get-logs'),
  writeClipboardText: (text) => ipcRenderer.invoke('clipboard:write-text', text),
};

contextBridge.exposeInMainWorld('betterFingers', api);
