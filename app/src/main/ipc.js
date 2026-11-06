const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { app, clipboard, dialog, ipcMain, session, shell, webContents } = require('electron');
const { isTrustedRendererUrl, pageNameOf } = require('./senderValidation');
const { isPageAllowed } = require('./ipcPolicy');
const { deletionRan, finishFactoryReset } = require('./rendererState');
const { evaluateOpenTarget: evaluateOpenTargetPolicy } = require('./openPathPolicy');

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

// Trusted AND allowed for this channel: the page must be one the channel is open to
// (ipcPolicy.js), so the overlay, review window and splash cannot call the
// dashboard's channels even if they somehow held the bridge method.
function isAllowedSender(event, channel) {
  if (!isTrustedSender(event)) return false;
  // Top frame only: a subframe (which the CSP forbids anyway) is never a caller.
  const main = event?.sender?.mainFrame;
  if (main && event.senderFrame !== main) return false;
  const page = pageNameOf(event.senderFrame.url, {
    rendererDir: rendererDir(),
    devOrigin: process.env.ELECTRON_RENDERER_URL,
  });
  return isPageAllowed(channel, page);
}

function rejectUntrusted(event, channel) {
  const url = event?.senderFrame?.url || '(no frame)';
  console.warn(`[ipc] Rejected '${channel}' from untrusted sender: ${url}`);
  return { ok: false, error: 'untrusted_sender' };
}

// ipcMain.handle with a mandatory sender check.
function handleTrusted(channel, handler) {
  ipcMain.handle(channel, (event, ...args) => {
    if (!isAllowedSender(event, channel)) {
      return rejectUntrusted(event, channel);
    }
    return handler(event, ...args);
  });
}

// ipcMain.on (fire-and-forget) with a mandatory sender check.
function onTrusted(channel, handler) {
  ipcMain.on(channel, (event, ...args) => {
    if (!isAllowedSender(event, channel)) {
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

// Containment AND file-type policy live in openPathPolicy.js (Phase 0 item 8).
function evaluateOpenTarget(targetPath) {
  return evaluateOpenTargetPolicy(targetPath, { roots: allowedOpenRoots() });
}

function registerIpc({
  getMainWindow, getSidecarStatus, getSidecarLogs, getAuthToken, getApprovalKey, getBackendOrigin, onQuit, onShow,
  onSplashRetry, getSplashBootState, updateController, onRuntimeStatus, onConsentChanged,
  onFactoryResetStart, onFactoryResetEnd,
} = {}) {
  const backendProxy = require('./backendProxy');
  const { createBugReportController } = require('./bugReportController');
  const bugReportController = createBugReportController({
    backendProxy,
    dialog,
    shell,
    clipboard,
  });

  // Phase 3c: the token is never exposed to the renderer. All backend HTTP
  // goes through this validated proxy (origin-locked, method/path allowlisted,
  // body-size capped); the credential stays in the main process.
  handleTrusted('backend:request', (event, req) => {
    const { method, path, body, timeoutMs } = req || {};
    // The review window gets a much smaller route table than the dashboard (round 2, item 7).
    // The profile comes from the PAGE main sees, never from anything the page sends.
    const page = pageNameOf(event.senderFrame.url, { rendererDir: rendererDir(), devOrigin: process.env.ELECTRON_RENDERER_URL });
    const profile = page === 'review-overlay.html' ? 'review' : 'dashboard';
    return backendProxy.request({ method, path, body, timeoutMs, profile });
  });

  // Typed channels for destructive/sensitive operations. Each maps to exactly
  // one HTTP method + route with a schema-validated payload (enforced in
  // backendProxy); the generic channel above refuses these routes outright.
  handleTrusted('backend:fetch-health', (_event, req) => {
    const { timeoutMs } = req || {};
    return backendProxy.fetchHealth({ timeoutMs });
  });

  // The approval broker (Phase 0 items 1-3). The renderer can ASK for one of
  // these; each shows a native dialog with the exact content, and only a click on
  // Approve makes main sign the ticket the backend demands. A renderer never sees
  // the key or a ticket and cannot obtain a "yes" any other way.
  const { createApprovalBroker } = require('./approvalBroker');
  let approvalBroker = null;
  function broker() {
    if (!approvalBroker) {
      const keyHex = typeof getApprovalKey === 'function' ? getApprovalKey() : '';
      approvalBroker = createApprovalBroker({
        secret: Buffer.from(String(keyHex || ''), 'hex'),
        dialog,
        getParentWindow: () => {
          const win = getMainWindow?.();
          return win && !win.isDestroyed() ? win : null;
        },
        backend: { send: (method, path, body, timeoutMs) => backendProxy.sendTrusted(method, path, body, timeoutMs) },
        listApplications: () => applicationRegistry().list(),
        log: (line) => console.warn(line),
      });
      // The send hotkey opens the native approval dialog; it never signs by itself.
      require('./hotkeys').setPrimaryActionHandler((press) => broker().placeFromHotkey(press));
    }
    return approvalBroker;
  }
  // Create it now so the hotkey signer is installed before the first key press.
  setImmediate(() => { try { broker(); } catch (error) { console.error('[approval] broker unavailable:', error.message); } });

  // Spoken requests (round 2, item 6). The backend announces that a draft placement or a
  // confirmation-gated command was REQUESTED by voice; the native dialog is the only thing that
  // can confirm it. Main listens to the backend's own status events, so a page cannot forge or
  // suppress one by what it relays.
  backendProxy.onBackendEvent((message) => {
    if (!message || typeof message !== 'object') return;
    const draftId = Number.isInteger(message.draft_id) ? message.draft_id : null;
    if (message.status === 'command_needs_tap' && message.action === 'send') {
      broker().presentVoiceTap({ draftId }).catch(() => {});
    } else if (message.status === 'command_needs_confirmation' && typeof message.action === 'string') {
      broker().confirmVoiceCommand({ action: message.action, draftId }).catch(() => {});
    }
  });

  handleTrusted('approvals:workflow', (_event, req) => {
    const { workflowId } = req || {};
    return broker().approveWorkflow(workflowId);
  });

  handleTrusted('approvals:persona-example', (_event, req) => {
    const { persona, raw, out, timeoutMs } = req || {};
    return broker().addPersonaExample({ persona, raw, out, timeoutMs });
  });

  handleTrusted('approvals:persona-save', (_event, req) => {
    const { name, body, timeoutMs } = req || {};
    return broker().savePersona({ name, body, timeoutMs });
  });

  handleTrusted('backend:send-draft', (_event, req) => {
    const { id, action, openChat, allowResend, timeoutMs } = req || {};
    return broker().sendDraft({ id, action, openChat, allowResend, timeoutMs });
  });

  handleTrusted('backend:primary-action', (_event, req) => {
    const { timeoutMs } = req || {};
    return broker().primaryActionFromUi({ timeoutMs });
  });

  handleTrusted('backend:wipe-privacy', (_event, req) => {
    const { wipeVoices, confirm, mode, timeoutMs } = req || {};
    return backendProxy.wipePrivacyData({ wipeVoices, confirm, mode, timeoutMs });
  });

  // Wave 6: the factory-reset executor. Its own channel rather than a mode on
  // the wipe above, because it takes a different gate (an exact phrase, not a
  // boolean) and erases settings and the consent record too.
  //
  // The backend can only sweep the unified data root. What Chromium keeps for
  // the renderer (Local Storage with the first-run flags and the legacy consent
  // flag, Session Storage, caches) lives in Electron's own userData folder, so
  // main finishes the job here and folds the outcome into the response -- a
  // reset the renderer state survived is reported as failed, never as fresh.
  // See rendererState.js for the live clear and the pending-until-restart purge.
  handleTrusted('backend:factory-reset', async (_event, req) => {
    const { confirm, deleteDownloadedModels, timeoutMs } = req || {};
    // The raw sidecar log is one of the files the reset deletes, and main would
    // recreate it from the backend's own output within the second. Switch file
    // logging off BEFORE the request (so nothing can race the deletion) and back
    // on only if the reset turns out not to have deleted anything.
    onFactoryResetStart?.();
    let deleted = false;
    try {
      const result = await backendProxy.factoryReset({ confirm, deleteDownloadedModels, timeoutMs });
      deleted = deletionRan(result);
      const finished = await finishFactoryReset(result, {
        session: session.defaultSession,
        webContents,
        userDataDir: app.getPath('userData'),
      });
      onConsentChanged?.();
      return finished;
    } finally {
      onFactoryResetEnd?.({ deleted });
    }
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

  // Bug reports are privileged for two reasons: main collects the diagnostic
  // projection itself (the renderer cannot attach arbitrary logs), and only
  // main can show the final native confirmation or contact the configured
  // HTTPS relay. Destructure every renderer payload to the fixed schema.
  handleTrusted('bug-report:get-config', () => bugReportController.getConfig());

  handleTrusted('bug-report:prepare', (_event, payload) => {
    const { summary, steps, expected, actual, contact } = payload || {};
    return bugReportController.prepare({ summary, steps, expected, actual, contact });
  });

  handleTrusted('bug-report:submit', (_event, payload) => {
    const { previewId, destination } = payload || {};
    return bugReportController.submit({ previewId, destination });
  });

  // OR-02: the startup splash's own channel. splash:get-state backs a pull for
  // a page that finishes loading after boot already started (and would
  // otherwise miss the events pushed before it was listening); splash:retry is
  // the RecoveryCard's only way to ask main to try starting the backend again
  // -- the splash itself never re-derives 'failed' on its own, it only relays
  // what main decided (see bootPhases.js and main.js's startBackendBoot()).
  handleTrusted('splash:get-state', () => (getSplashBootState ? getSplashBootState() : null));
  handleTrusted('splash:retry', async () => {
    if (onSplashRetry) {
      await onSplashRetry();
    }
    return { ok: true };
  });

  handleTrusted('app:quit', async () => {
    if (onQuit) {
      await onQuit();
    }
    return true;
  });

  // Durable onboarding consent record (unified data root, not Electron
  // userData). Acceptance uses the main process current version; a renderer
  // cannot invent a future consent version.
  const onboardingStore = require('./onboardingStore');
  handleTrusted('onboarding:get-state', () => onboardingStore.readState());
  handleTrusted('onboarding:accept', () => {
    const result = onboardingStore.recordAcceptance();
    if (result.ok) onConsentChanged?.();
    return result;
  });
  handleTrusted('onboarding:complete-step', (_event, req) =>
    onboardingStore.recordStepComplete(String(req?.stepId || '')));
  handleTrusted('onboarding:migrate-legacy', (_event, req) => {
    const result = onboardingStore.migrateLegacyCompletion({ legacyComplete: Boolean(req?.legacyComplete) });
    if (result.migrated && result.ok) onConsentChanged?.();
    return result;
  });

  handleTrusted('app:get-version', () => {
    const { APP_VERSION } = require('./config');
    return APP_VERSION;
  });

  // The renderer can request fixed update actions and a boolean preference; it cannot provide a
  // feed URL, channel, executable, path, or updater options. All transition
  // checks and the recording/processing gate live in the main controller.
  const unavailableUpdateState = () => ({
    status: 'unsupported',
    currentVersion: app.getVersion?.() || '',
    availableVersion: null,
    channel: null,
    releaseDate: null,
    releaseNotes: '',
    percent: 0,
    bytesTransferred: 0,
    bytesTotal: 0,
    errorCode: null,
  });
  handleTrusted('updates:get-state', () => updateController?.getState?.() || unavailableUpdateState());
  handleTrusted('updates:set-automatic', (_event, enabled) => updateController?.setAutomaticUpdates?.(enabled) || unavailableUpdateState());
  handleTrusted('updates:check', () => updateController?.check?.() || unavailableUpdateState());
  handleTrusted('updates:download', () => updateController?.download?.() || unavailableUpdateState());
  handleTrusted('updates:install', () => updateController?.install?.() || unavailableUpdateState());

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

  handleTrusted('workflows:execute', async (_event, payload) => {
    // Destructured to exactly one field on purpose: passing `payload` through
    // would let a future edit start honouring extra keys without anybody
    // noticing that the channel had stopped being id-only.
    const { workflowId } = payload || {};
    // A renderer-triggered run with an outward effect needs a fresh native confirmation
    // (round 2, item 5; approvalBroker.confirmWorkflowRun explains the policy).
    const confirmation = await broker().confirmWorkflowRun(workflowId);
    if (!confirmation.ok) return confirmation;
    return workflowExecutor().execute(workflowId);
  });

  // The owner acting NOW, observed by main itself (a hotkey chord, a trigger phrase heard on
  // the mic): runs without a dialog. Deliberately not an IPC channel, so no page can call it;
  // registerIpc hands it to main.js, whose physical-trigger handlers are its only callers.
  const runWorkflowFromPhysicalTrigger = (workflowId) => workflowExecutor().execute(workflowId);

  // The send shortcut is gated (round 2, item 2): only a Ctrl/Alt/Meta chord or a function
  // key is accepted, and changing it from the confirmed value needs a native dialog.
  // Everything else in the config is applied as before.
  const { createSendHotkeyGate } = require('./sendHotkeyPolicy');
  const sendHotkeyFile = () => path.join(app.getPath('userData'), 'send-hotkey.json');
  const sendHotkeyGate = createSendHotkeyGate({
    load: () => {
      try { return JSON.parse(fs.readFileSync(sendHotkeyFile(), 'utf8')).key; } catch { return null; }
    },
    save: (key) => fs.writeFileSync(sendHotkeyFile(), JSON.stringify({ key })),
  });

  onTrusted('update-hotkeys', (_event, config) => {
    const { registerHotkeys } = require('./hotkeys');
    const token = typeof getAuthToken === 'function' ? getAuthToken() : null;
    if (!config || typeof config !== 'object') { registerHotkeys(config, token); return; }
    const verdict = sendHotkeyGate.evaluate(config.manual_send_hotkey);
    if (verdict.rejected) console.warn('[hotkeys] Refused a send shortcut that is not a Ctrl/Alt/Meta chord or function key.');
    registerHotkeys({ ...config, manual_send_hotkey: verdict.effective }, token);
    if (verdict.needsConfirmation) {
      const wanted = verdict.needsConfirmation;
      broker().confirmSendHotkeyChange(wanted).then((approved) => {
        if (!approved) { sendHotkeyGate.decline(wanted); return; }
        sendHotkeyGate.confirm(wanted);
        registerHotkeys({ ...config, manual_send_hotkey: wanted }, token);
      }).catch((error) => console.warn('[hotkeys] send shortcut confirmation failed:', error && error.name));
    }
  });

  handleTrusted('hotkeys:get-capabilities', () => {
    const { getHotkeyCapabilities } = require('./hotkeys');
    return getHotkeyCapabilities();
  });


  handleTrusted('shell:open-path', async (_event, targetPath) => {
    // Show an exported folder, or open an exported DOCUMENT (e.g. the reel.html
    // preview), from locations the app itself writes to. Never an executable,
    // script, shortcut or installer: shell.openPath launches what it opens, so
    // openPathPolicy.js allows directories and a closed list of document types
    // only, judged on the symlink-resolved path.
    const verdict = evaluateOpenTarget(targetPath);
    if (!verdict.ok) {
      console.warn(`[ipc] Refused shell:open-path: ${verdict.reason}`);
      return { ok: false, error: verdict.reason };
    }
    const error = await shell.openPath(verdict.resolved);
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
    onRuntimeStatus?.(status);

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
    // Signal Engineer face: read-aloud loudness (0..1 per frame, one chunk per
    // message) and an expression name chosen by the assistant.
    if (Array.isArray(payload.envelope)) {
      safePayload.envelope = payload.envelope
        .slice(0, 1800)
        .map((v) => (typeof v === 'number' && isFinite(v) ? Math.max(0, Math.min(1, v)) : 0));
      const fps = Number(payload.fps);
      safePayload.fps = fps >= 1 && fps <= 120 ? fps : 30;
    }
    if (typeof payload.emotion === 'string' && /^[a-z_]{1,20}$/.test(payload.emotion)) {
      safePayload.emotion = payload.emotion;
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

    // Read-aloud: with a Signal Engineer face selected, the overlay comes up so
    // the face can talk while the backend plays the audio, and goes back down a
    // beat after it stops. With the plain ring nothing changes (these statuses
    // fall through to the idle handling below, exactly as before).
    const face = getOverlayAppearance().face;
    const faceOn = Boolean(face && face !== 'ring');
    // Loudness frames only matter to a visible face; never change visibility.
    if (status === 'draft_tts_level') {
      if (faceOn && overlay.isVisible()) overlay.webContents.send('overlay:update', safePayload);
      return true;
    }
    // Assistant talk mode (brain session): the face shows while it listens,
    // thinks, speaks or waits for a tap.
    if (faceOn && status.startsWith('talk_')) {
      if (!overlay.isVisible()) overlay.showInactive();
      overlay.webContents.send('overlay:update', safePayload);
      return true;
    }
    if ((status === 'draft_tts_started' || status === 'draft_tts_stopped') && faceOn) {
      if (status === 'draft_tts_started' && !overlay.isVisible()) {
        overlay.showInactive();
      }
      overlay.webContents.send('overlay:update', safePayload);
      if (status === 'draft_tts_stopped' && !alwaysOn) {
        overlayHideTimer = setTimeout(() => {
          if (!overlay.isDestroyed() && overlay.isVisible()) overlay.hide();
          overlayHideTimer = null;
        }, 1500);
      }
      return true;
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

  onTrusted('review:displayed', (event, payload) => {
    if (event.senderFrame !== event.sender?.mainFrame) return;
    const { acknowledgeReviewDraft } = require('./windows');
    acknowledgeReviewDraft(event.sender, payload);
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

  return { runWorkflowFromPhysicalTrigger };
}

module.exports = {
  registerIpc,
};
