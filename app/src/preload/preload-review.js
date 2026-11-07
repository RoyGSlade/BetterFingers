// Preload for the draft review overlay. The page reads and edits drafts through the
// validated proxy, asks to place one (main shows the native approval dialog), and
// tells main which draft it painted. It does not get the dashboard's bridge: no
// workflows, privacy deletion, clipboard, shell or hotkeys (Phase 0 item 7).
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('betterFingers', {
  backendRequest: (method, path, body, timeoutMs) =>
    ipcRenderer.invoke('backend:request', { method, path, body, timeoutMs }),
  sendDraft: (id, { action, openChat, allowResend } = {}, timeoutMs) =>
    ipcRenderer.invoke('backend:send-draft', { id, action, openChat, allowResend, timeoutMs }),
});

contextBridge.exposeInMainWorld('betterFingersReview', {
  displayed: (payload) => ipcRenderer.send('review:displayed', payload),
  hide: () => ipcRenderer.invoke('review:hide'),
  onDraft: (callback) => ipcRenderer.on('review:draft', (_event, draft) => callback(draft)),
  onStatus: (callback) => ipcRenderer.on('review:status', (_event, status) => callback(status)),
});
