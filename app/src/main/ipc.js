const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { app, clipboard, ipcMain, shell } = require('electron');
const { isTrustedRendererUrl } = require('./senderValidation');

let overlayHideTimer = null;

// --- Renderer privilege boundary -------------------------------------------
// Every IPC handler validates the sender frame before doing privileged work.
// The preload bridge hands the renderer real powers (quit, clipboard, hotkeys,
// overlay control, shell open); a compromised or navigated-away frame must not
// keep them. Trusted senders are exactly our own pages: one of the packaged
// renderer HTML files in the app's renderer directory, or the electron-vite
// dev-server origin (exact origin) in development.

// The packaged renderer pages live beside the compiled main scripts
// (out/main/ipc.js -> out/renderer/index.html), matching how windows.js loads
// them via loadFile('../renderer/*.html').
function rendererDir() {
  return path.resolve(__dirname, '..', 'renderer');
}

function isTrustedSender(event) {
  const url = event?.senderFrame?.url || '';
  if (!url) return false;
  return isTrustedRendererUrl(url, {
    rendererDir: rendererDir(),
    devOrigin: process.env.ELECTRON_RENDERER_URL,
  });
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
  const backendProxy = require('./backendProxy');

  // Phase 3c: the token is never exposed to the renderer. All backend HTTP
  // goes through this validated proxy (origin-locked, method/path allowlisted,
  // body-size capped); the credential stays in the main process.
  handleTrusted('backend:request', (_event, req) => {
    const { method, path, body, timeoutMs } = req || {};
    return backendProxy.request({ method, path, body, timeoutMs });
  });

  // Typed channels for destructive/sensitive operations. Each maps to exactly
  // one HTTP method + route with a schema-validated payload (enforced in
  // backendProxy); the generic channel above refuses these routes outright.
  handleTrusted('backend:fetch-health', (_event, req) => {
    const { timeoutMs } = req || {};
    return backendProxy.fetchHealth({ timeoutMs });
  });

  handleTrusted('backend:send-draft', (_event, req) => {
    const { id, action, openChat, allowResend, timeoutMs } = req || {};
    return backendProxy.sendDraft({ id, action, openChat, allowResend, timeoutMs });
  });

  handleTrusted('backend:wipe-privacy', (_event, req) => {
    const { wipeVoices, confirm, mode, timeoutMs } = req || {};
    return backendProxy.wipePrivacyData({ wipeVoices, confirm, mode, timeoutMs });
  });

  // Wave 6: the factory-reset executor. Its own channel rather than a mode on
  // the wipe above, because it takes a different gate (an exact phrase, not a
  // boolean) and erases settings and the consent record too.
  handleTrusted('backend:factory-reset', (_event, req) => {
    const { confirm, deleteDownloadedModels, timeoutMs } = req || {};
    return backendProxy.factoryReset({ confirm, deleteDownloadedModels, timeoutMs });
  });

  handleTrusted('backend:clear-persona-learning', (_event, req) => {
    const { confirm, timeoutMs } = req || {};
    return backendProxy.clearPersonaLearning({ confirm, timeoutMs });
  });

  handleTrusted('backend:delete-llm-model', (_event, req) => {
    const { modelId, confirm, timeoutMs } = req || {};
    return backendProxy.deleteLlmModel({ modelId, confirm, timeoutMs });
  });

  handleTrusted('backend:delete-whisper-model', (_event, req) => {
    const { modelSize, confirm, timeoutMs } = req || {};
    return backendProxy.deleteWhisperModel({ modelSize, confirm, timeoutMs });
  });

  handleTrusted('backend:delete-voice', (_event, req) => {
    const { voiceId, confirm, timeoutMs } = req || {};
    return backendProxy.deleteVoice({ voiceId, confirm, timeoutMs });
  });

  handleTrusted('backend:cancel-job', (_event, req) => {
    const { jobId, timeoutMs } = req || {};
    return backendProxy.cancelJob({ jobId, timeoutMs });
  });

  handleTrusted('backend:upload-voice-sample', (_event, req) => {
    const { bytes, filename, name, consent, timeoutMs } = req || {};
    return backendProxy.uploadVoiceSample({ bytes, filename, name, consent, timeoutMs });
  });

  handleTrusted('backend:upload-wake-model', (_event, req) => {
    const { bytes, filename, name, timeoutMs } = req || {};
    return backendProxy.uploadWakeModel({ bytes, filename, name, timeoutMs });
  });

  handleTrusted('backend:voice-status:start', (event) => {
    backendProxy.startVoiceStatus(event.sender);
    return { ok: true };
  });

  handleTrusted('backend:voice-status:stop', () => {
    backendProxy.stopVoiceStatus();
    return { ok: true };
  });

  handleTrusted('app:quit', async () => {
    if (onQuit) {
      await onQuit();
    }
    return true;
  });

  // Durable onboarding consent record (unified data root, not Electron
  // userData). consentVersion is sanitized to a finite number — the renderer
  // must never write an arbitrary value into the consent record.
  const onboardingStore = require('./onboardingStore');
  handleTrusted('onboarding:get-state', () => onboardingStore.readState());
  handleTrusted('onboarding:accept', (_event, req) => onboardingStore.recordAcceptance({
    consentVersion: Number.isFinite(req?.consentVersion) ? req.consentVersion : undefined,
  }));
  handleTrusted('onboarding:complete-step', (_event, req) =>
    onboardingStore.recordStepComplete(String(req?.stepId || '')));
  handleTrusted('onboarding:migrate-legacy', (_event, req) =>
    onboardingStore.migrateLegacyCompletion({ legacyComplete: Boolean(req?.legacyComplete) }));

  handleTrusted('app:get-version', () => {
    const { APP_VERSION } = require('./config');
    return APP_VERSION;
  });

  // Wave 9 restricted actions. The registry is the ONLY thing a workflow may
  // name, so these channels are the boundary: discovery returns unconfirmed
  // candidates, and only applications:confirm writes an entry. Registered
  // through handleTrusted (not raw ipcMain.handle) so the sender-frame check
  // applies — the registry is privilege surface. There is DELIBERATELY no
  // launch channel here: execution must pass through POST /workflows/run's
  // approval gate first (see WAVE9_INTEGRATION_DIFFS §D-4).
  const { createApplicationRegistry } = require('./applicationRegistry');
  const { execFile } = require('node:child_process');

  let _applicationRegistry = null;
  function applicationRegistry() {
    if (!_applicationRegistry) {
      _applicationRegistry = createApplicationRegistry({ execFile });
    }
    return _applicationRegistry;
  }

  handleTrusted('applications:list', () => ({ ok: true, entries: applicationRegistry().list() }));
  handleTrusted('applications:discover', async () => ({
    ok: true, candidates: await applicationRegistry().discover(),
  }));
  handleTrusted('applications:confirm', (_event, payload) => applicationRegistry().confirm(payload));
  handleTrusted('applications:remove', (_event, { id } = {}) => applicationRegistry().remove(id));

  // Wave 10 / D-0027: the workflow run executor. This is the ONLY caller of
  // applicationLauncher.js and the only way to reach it is the single channel
  // below, which takes a workflow id and nothing else -- the main process
  // re-fetches, re-validates through POST /workflows/run and executes only what
  // the backend says is approved. A renderer that lies about the id can at most
  // ask for a different workflow the user already approved.
  //
  // The controller and the Stream Deck arrive here too, by the same route: their
  // `workflow.run` action reaches the renderer as a request and the renderer
  // calls this channel. There is no second path, and there must not be one.
  let _workflowExecutor = null;
  function workflowExecutor() {
    if (!_workflowExecutor) {
      const { createApplicationLauncher } = require('./applicationLauncher');
      const { createWorkflowExecutor } = require('./workflowExecutor');
      _workflowExecutor = createWorkflowExecutor({
        backendProxy,
        launcher: createApplicationLauncher({}),
        listApplications: () => applicationRegistry().list(),
        notify: (message) => {
          const { Notification } = require('electron');
          if (Notification.isSupported()) {
            new Notification({ title: 'BetterFingers', body: String(message || '') }).show();
          }
        },
      });
    }
    return _workflowExecutor;
  }

  handleTrusted('workflows:execute', (_event, payload) => {
    // Destructured to exactly one field on purpose: passing `payload` through
    // would let a future edit start honouring extra keys without anybody
    // noticing that the channel had stopped being id-only.
    const { workflowId } = payload || {};
    return workflowExecutor().execute(workflowId);
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

  handleTrusted('overlay:set-ignore-mouse-events', (_event, ignore) => {
    const { getOverlayWindow } = require('./windows');
    const overlay = getOverlayWindow();
    if (!overlay || overlay.isDestroyed()) return false;
    // Keep `forward: true` on the click-through side so hover detection in the
    // renderer keeps working even while the overlay is passing clicks through.
    const shouldIgnore = Boolean(ignore);
    overlay.setIgnoreMouseEvents(shouldIgnore, shouldIgnore ? { forward: true } : undefined);
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
