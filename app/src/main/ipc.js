const { ipcMain } = require('electron');

function registerIpc({ getMainWindow, onQuit, onShow } = {}) {
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
}

module.exports = {
  registerIpc,
};
