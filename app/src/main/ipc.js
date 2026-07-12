const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { app, clipboard, ipcMain, shell } = require('electron');

let overlayHideTimer = null;

// --- Renderer privilege boundary -------------------------------------------
// Every IPC handler validates the sender frame before doing privileged work.
// The preload bridge hands the renderer real powers (quit, clipboard, hotkeys,
// overlay control, shell open); a compromised or navigated-away frame must not
// keep them. Trusted senders are exactly our own pages: the packaged file://
// HTML under the app, or the electron-vite dev-server origin in development.

const RENDERER_PAGES = new Set(['index.html', 'overlay.html', 'review-overlay.html']);

function isTrustedSender(event) {
  const url = event?.senderFrame?.url || '';
  if (!url) return false;
  if (url.startsWith('file://')) {
    let pathname;
    try {
      pathname = decodeURIComponent(new URL(url).pathname);
    } catch {
      return false;
    }
    const base = path.basename(pathname);
    // Must be one of our pages, served from inside the app's own directory
    // (dev: <repo>/app/..., packaged: .../resources/app.asar/...).
    const appRoot = path.resolve(__dirname, '..', '..');
    const normalized = path.resolve(pathname);
    return RENDERER_PAGES.has(base) && normalized.startsWith(appRoot);
  }
  const devOrigin = process.env.ELECTRON_RENDERER_URL;
  if (devOrigin && url.startsWith(devOrigin)) {
    return true;
  }
  return false;
}

function rejectUntrusted(event, channel) {
  const url = event?.senderFrame?.url || '(no frame)';
  console.warn(`[ipc] Rejected '${channel}' from untrusted sender: ${url}`);
  return { ok: false, error: 'untrusted_sender' };
}

// ipcMain.handle with a mandatory sender check.
function handleTrusted(channel, handler) {
  ipcMain.handle(channel, (event, ...args) => {
    if (!isTrustedSender(event)) {
      return rejectUntrusted(event, channel);
    }
    return handler(event, ...args);
  });
}

// ipcMain.on (fire-and-forget) with a mandatory sender check.
function onTrusted(channel, handler) {
  ipcMain.on(channel, (event, ...args) => {
    if (!isTrustedSender(event)) {
      rejectUntrusted(event, channel);
      return;
    }
    handler(event, ...args);
  });
}

// shell:open-path may only open locations the app itself exports to.
function allowedOpenRoots() {
  const roots = [path.join(os.homedir(), 'Downloads')];
  try {
    roots.push(app.getPath('downloads'));
  } catch {}
  try {
    roots.push(app.getPath('userData'));
  } catch {}
  return roots.map((r) => path.resolve(r));
}

function isAllowedOpenTarget(targetPath) {
  let resolved;
  try {
    resolved = fs.realpathSync(path.resolve(String(targetPath)));
  } catch {
    return false; // must exist
  }
  return allowedOpenRoots().some(
    (root) => resolved === root || resolved.startsWith(root + path.sep),
  );
}

function registerIpc({ getMainWindow, getSidecarStatus, getSidecarLogs, getAuthToken, getBackendOrigin, onQuit, onShow } = {}) {
  ipcMain.on('app:get-auth-token-sync', (event) => {
    if (!isTrustedSender(event)) {
      rejectUntrusted(event, 'app:get-auth-token-sync');
      event.returnValue = '';
      return;
    }
    event.returnValue = typeof getAuthToken === 'function' ? getAuthToken() : '';
  });

  ipcMain.on('app:get-backend-origin-sync', (event) => {
    if (!isTrustedSender(event)) {
      rejectUntrusted(event, 'app:get-backend-origin-sync');
      event.returnValue = '';
      return;
    }
    event.returnValue = typeof getBackendOrigin === 'function' ? getBackendOrigin() : '';
  });

  handleTrusted('app:quit', async () => {
    if (onQuit) {
      await onQuit();
    }
    return true;
  });

  onTrusted('update-hotkeys', (_event, config) => {
    const { registerHotkeys } = require('./hotkeys');
    const token = typeof getAuthToken === 'function' ? getAuthToken() : null;
    registerHotkeys(config, token);
  });

  handleTrusted('hotkeys:get-capabilities', () => {
    const { getHotkeyCapabilities } = require('./hotkeys');
    return getHotkeyCapabilities();
  });


  handleTrusted('shell:open-path', async (_event, targetPath) => {
    // Open an exported file/folder (e.g. the reel.html preview) in the OS
    // default app. Only locations the app itself exports to are allowed —
    // Downloads and the app's own data dir — and the target must exist.
    if (typeof targetPath !== 'string' || !targetPath || targetPath.length > 4096) {
      return { ok: false, error: 'No path provided' };
    }
    if (!isAllowedOpenTarget(targetPath)) {
      console.warn(`[ipc] Refused shell:open-path outside allowed roots: ${targetPath}`);
      return { ok: false, error: 'Path is outside the allowed export locations.' };
    }
    const error = await shell.openPath(targetPath);
    return { ok: !error, error: error || null };
  });

  handleTrusted('app:show', () => {
    // Call onShow unconditionally: it recreates the dashboard window when it
    // has been closed (getMainWindow() returns null in that case).
    if (onShow) {
      onShow();
    }
    return true;
  });

  handleTrusted('app:get-state', () => {
    const window = getMainWindow?.();
    return {
      isVisible: Boolean(window && !window.isDestroyed() && window.isVisible()),
      isFocused: Boolean(window && !window.isDestroyed() && window.isFocused()),
    };
  });

  handleTrusted('sidecar:get-status', () => {
    if (typeof getSidecarStatus === 'function') {
      return getSidecarStatus();
    }
    return {
      state: 'unknown',
      message: 'Sidecar status is unavailable.',
    };
  });

  handleTrusted('sidecar:get-logs', () => {
    if (typeof getSidecarLogs === 'function') {
      return getSidecarLogs();
    }
    return [];
  });

  handleTrusted('clipboard:write-text', (_event, text) => {
    clipboard.writeText(String(text ?? ''));
    return true;
  });

  handleTrusted('overlay:update-status', (_event, update) => {
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

  handleTrusted('review:show', (_event, draft) => {
    const { showReviewWindow } = require('./windows');
    showReviewWindow(draft ?? null);
    return true;
  });

  handleTrusted('review:hide', () => {
    const { hideReviewWindow } = require('./windows');
    hideReviewWindow();
    return true;
  });

  handleTrusted('overlay:get-appearance', () => {
    const { getOverlayAppearance } = require('./windows');
    return getOverlayAppearance();
  });

  handleTrusted('overlay:set-appearance', (_event, partial) => {
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
