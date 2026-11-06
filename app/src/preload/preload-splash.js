// Preload for the startup splash. It can receive boot snapshots, pull the current
// one and ask main to retry the backend start, and nothing else (Phase 0 item 7).
const { contextBridge, ipcRenderer } = require('electron');

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
