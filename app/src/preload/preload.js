const { contextBridge, ipcRenderer } = require('electron');

const api = {
  quitApp: () => ipcRenderer.invoke('app:quit'),
  showApp: () => ipcRenderer.invoke('app:show'),
  getAppState: () => ipcRenderer.invoke('app:get-state'),
  writeClipboardText: (text) => ipcRenderer.invoke('clipboard:write-text', text),
};

contextBridge.exposeInMainWorld('betterFingers', api);
