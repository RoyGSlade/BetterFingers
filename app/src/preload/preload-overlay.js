// Preload for the always-on-top status overlay (the Signal Core ring and the
// Signal Engineer face). It is DISPLAY-ONLY: it can receive status and appearance
// events and toggle click-through. It cannot reach the backend, the clipboard,
// workflows, drafts, privacy or the filesystem (Phase 0 item 7). Kept free of any
// shared module on purpose: a sandboxed preload cannot require local files.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('betterFingersOverlay', {
  onStatusUpdate: (callback) => ipcRenderer.on('overlay:update', (_event, status) => callback(status)),
  onAppearance: (callback) => ipcRenderer.on('overlay:appearance', (_event, appearance) => callback(appearance)),
  setIgnoreMouseEvents: (ignore) => ipcRenderer.invoke('overlay:set-ignore-mouse-events', ignore),
});
