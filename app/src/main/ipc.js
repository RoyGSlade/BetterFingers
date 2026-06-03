const { clipboard, ipcMain } = require('electron');

function registerIpc({ getMainWindow, getSidecarStatus, getSidecarLogs, onQuit, onShow } = {}) {
  ipcMain.handle('app:quit', async () => {
    if (onQuit) {
      await onQuit();
    }
    return true;
  });

  ipcMain.handle('app:show', () => {
    const window = getMainWindow?.();
    if (window && onShow) {
      onShow(window);
    }
    return true;
  });

  ipcMain.handle('app:get-state', () => {
    const window = getMainWindow?.();
    return {
      isVisible: Boolean(window && !window.isDestroyed() && window.isVisible()),
      isFocused: Boolean(window && !window.isDestroyed() && window.isFocused()),
    };
  });

  ipcMain.handle('sidecar:get-status', () => {
    if (typeof getSidecarStatus === 'function') {
      return getSidecarStatus();
    }
    return {
      state: 'unknown',
      message: 'Sidecar status is unavailable.',
    };
  });

  ipcMain.handle('sidecar:get-logs', () => {
    if (typeof getSidecarLogs === 'function') {
      return getSidecarLogs();
    }
    return [];
  });

  ipcMain.handle('clipboard:write-text', (_event, text) => {
    clipboard.writeText(String(text ?? ''));
    return true;
  });
}

module.exports = {
  registerIpc,
};
