const { clipboard, ipcMain, shell } = require('electron');

let overlayHideTimer = null;

function registerIpc({ getMainWindow, getSidecarStatus, getSidecarLogs, getAuthToken, getBackendOrigin, onQuit, onShow } = {}) {
  ipcMain.on('app:get-auth-token-sync', (event) => {
    event.returnValue = typeof getAuthToken === 'function' ? getAuthToken() : '';
  });

  ipcMain.on('app:get-backend-origin-sync', (event) => {
    event.returnValue = typeof getBackendOrigin === 'function' ? getBackendOrigin() : '';
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

  ipcMain.handle('hotkeys:get-capabilities', () => {
    const { getHotkeyCapabilities } = require('./hotkeys');
    return getHotkeyCapabilities();
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
    // Call onShow unconditionally: it recreates the dashboard window when it
    // has been closed (getMainWindow() returns null in that case).
    if (onShow) {
      onShow();
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
    const { getOverlayWindow, getReviewWindow, getOverlayAppearance } = require('./windows');
    const overlay = getOverlayWindow();
    const review = getReviewWindow();
    const alwaysOn = Boolean(getOverlayAppearance().alwaysOn);

    if (!update || (typeof update !== 'string' && typeof update !== 'object')) {
      return false;
    }

    const payload = typeof update === 'string' ? { status: update } : { ...(update ?? {}) };
    const status = String(payload.status ?? 'unknown');

    // Reflect pipeline state in the tray icon/menu too.
    const { getTray } = require('./tray');
    getTray()?.setState?.(status);
    const MAX_DURATION_MS = 30000;
    const rawDuration = payload.durationMs !== undefined ? Number(payload.durationMs) : 2600;
    const safeDuration = isNaN(rawDuration) || rawDuration < 0 || rawDuration > MAX_DURATION_MS ? 2600 : rawDuration;

    const safePayload = {
      status,
      message: payload.message ? String(payload.message) : '',
      durationMs: safeDuration,
    };
    // Pass through live mic amplitude (0..1) when present so the overlay ring can
    // pulse to the voice during recording.
    if (typeof payload.amplitude === 'number' && isFinite(payload.amplitude)) {
      safePayload.amplitude = Math.max(0, Math.min(1, payload.amplitude));
    }
    if (payload.fallback !== undefined) {
      safePayload.fallback = Boolean(payload.fallback);
    }

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
      status === 'long_recording_detected' ||
      status === 'chunking_started' ||
      status === 'chunking_progress' ||
      status === 'chunking_stitching' ||
      transientStatuses.has(status)
    ) {
      if (!overlay.isVisible()) {
        overlay.showInactive();
      }
      overlay.webContents.send('overlay:update', safePayload);
      if (transientStatuses.has(status)) {
        overlayHideTimer = setTimeout(() => {
          if (overlay.isDestroyed()) { overlayHideTimer = null; return; }
          if (alwaysOn) {
            // Keep the overlay up — just settle it back to the idle ring.
            overlay.webContents.send('overlay:update', { status: 'idle', message: '', durationMs: 0 });
          } else if (overlay.isVisible()) {
            overlay.hide();
          }
          overlayHideTimer = null;
        }, safePayload.durationMs);
      }
    } else if (alwaysOn) {
      // Idle/unknown but pinned on: keep it visible showing the idle ring.
      if (!overlay.isVisible()) {
        overlay.showInactive();
      }
      overlay.webContents.send('overlay:update', safePayload);
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

  ipcMain.handle('overlay:get-appearance', () => {
    const { getOverlayAppearance } = require('./windows');
    return getOverlayAppearance();
  });

  ipcMain.handle('overlay:set-appearance', (_event, partial) => {
    const { setOverlayAppearance, getOverlayWindow } = require('./windows');
    const applied = setOverlayAppearance(partial || {});
    // Show the overlay so the user sees the change they just made. If it's pinned
    // always-on, leave it up; otherwise auto-hide it again after a moment.
    const overlay = getOverlayWindow();
    if (overlay && !overlay.isDestroyed()) {
      overlay.webContents.send('overlay:update', { status: 'idle', message: '', durationMs: 0 });
      if (!overlay.isVisible()) overlay.showInactive();
      if (overlayHideTimer) clearTimeout(overlayHideTimer);
      if (!applied.alwaysOn) {
        overlayHideTimer = setTimeout(() => {
          if (overlay && !overlay.isDestroyed() && overlay.isVisible()) overlay.hide();
          overlayHideTimer = null;
        }, 1600);
      }
    }
    return applied;
  });
}

module.exports = {
  registerIpc,
};
