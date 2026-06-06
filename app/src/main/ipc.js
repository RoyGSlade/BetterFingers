const { clipboard, ipcMain, shell } = require('electron');

let overlayHideTimer = null;

function registerIpc({ getMainWindow, getSidecarStatus, getSidecarLogs, getAuthToken, onQuit, onShow } = {}) {
  ipcMain.on('app:get-auth-token-sync', (event) => {
    event.returnValue = typeof getAuthToken === 'function' ? getAuthToken() : '';
  });

  ipcMain.handle('app:quit', async () => {
    if (onQuit) {
      await onQuit();
    }
    return true;
  });

  ipcMain.on('update-hotkeys', (_event, config) => {
    const { registerHotkeys } = require('./hotkeys');
    const token = typeof getAuthToken === 'function' ? getAuthToken() : null;
    registerHotkeys(config, token);
  });


  ipcMain.handle('shell:open-path', async (_event, targetPath) => {
    // Open an exported file/folder (e.g. the reel.html preview) in the OS default app.
    if (typeof targetPath !== 'string' || !targetPath) {
      return { ok: false, error: 'No path provided' };
    }
    const error = await shell.openPath(targetPath);
    return { ok: !error, error: error || null };
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

    if (!update || (typeof update !== 'string' && typeof update !== 'object')) {
      return false;
    }

    const payload = typeof update === 'string' ? { status: update } : { ...(update ?? {}) };
    const status = String(payload.status ?? 'unknown');
    const MAX_DURATION_MS = 30000;
    const rawDuration = payload.durationMs !== undefined ? Number(payload.durationMs) : 2600;
    const safeDuration = isNaN(rawDuration) || rawDuration < 0 || rawDuration > MAX_DURATION_MS ? 2600 : rawDuration;

    const safePayload = {
      status,
      message: payload.message ? String(payload.message) : '',
      durationMs: safeDuration,
    };

    if (review && !review.isDestroyed() && review.isVisible()) {
      review.webContents.send('review:status', safePayload);
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
      overlay.webContents.send('overlay:update', safePayload);
      if (transientStatuses.has(status)) {
        overlayHideTimer = setTimeout(() => {
          if (!overlay.isDestroyed() && overlay.isVisible()) {
            overlay.hide();
          }
          overlayHideTimer = null;
        }, safePayload.durationMs);
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
