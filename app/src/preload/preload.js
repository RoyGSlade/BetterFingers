const { contextBridge, ipcRenderer } = require('electron');

const api = {
  quitApp: () => ipcRenderer.invoke('app:quit'),
  showApp: () => ipcRenderer.invoke('app:show'),
  getAppState: () => ipcRenderer.invoke('app:get-state'),
};

contextBridge.exposeInMainWorld('betterFingers', api);
