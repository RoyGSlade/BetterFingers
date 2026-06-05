const { clipboard, ipcMain } = require('electron');

let overlayHideTimer = null;

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

  ipcMain.handle('overlay:update-status', (_event, update) => {
    const { getOverlayWindow, getReviewWindow } = require('./windows');
    const overlay = getOverlayWindow();
    const review = getReviewWindow();

    const payload = typeof update === 'string' ? { status: update } : { ...(update ?? {}) };
    const status = String(payload.status ?? 'unknown');

    if (review && !review.isDestroyed() && review.isVisible()) {
      review.webContents.send('review:status', payload);
    }

    if (!overlay) return false;
    const transientStatuses = new Set([
      'preview_ready',
      'draft_blocked',
      'draft_error',
      'draft_sent',
      'draft_send_error',
      'selection_captured',
      'selection_capture_failed',
      'emergency_stop',
    ]);

    if (overlayHideTimer) {
      clearTimeout(overlayHideTimer);
      overlayHideTimer = null;
    }

    if (
      status === 'recording_started' ||
      status === 'recording' ||
      status === 'transcribing' ||
      status === 'rewriting' ||
      status === 'processing' ||
      transientStatuses.has(status)
    ) {
      if (!overlay.isVisible()) {
        overlay.showInactive();
      }
      overlay.webContents.send('overlay:update', payload);
      if (transientStatuses.has(status)) {
        overlayHideTimer = setTimeout(() => {
          if (!overlay.isDestroyed() && overlay.isVisible()) {
            overlay.hide();
          }
          overlayHideTimer = null;
        }, Number(payload.durationMs ?? 2600));
      }
    } else {
      if (overlay.isVisible()) {
        overlay.hide();
      }
    }
    return true;
  });

  ipcMain.handle('review:show', (_event, draft) => {
    const { showReviewWindow } = require('./windows');
    showReviewWindow(draft ?? null);
    return true;
  });

  ipcMain.handle('review:hide', () => {
    const { hideReviewWindow } = require('./windows');
    hideReviewWindow();
    return true;
  });
}

module.exports = {
  registerIpc,
};
