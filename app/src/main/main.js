const path = require('node:path');
const fs = require('node:fs');
const { randomUUID } = require('node:crypto');
const { app } = require('electron');
const {
  createMainWindow,
  getMainWindow,
  focusMainWindow,
  createSplashWindow,
  getSplashWindow,
  closeSplashWindow,
  createOverlayWindow,
} = require('./windows');
const { createSidecar } = require('./sidecar');
const { createTray } = require('./tray');
const { registerIpc } = require('./ipc');
const backendProxy = require('./backendProxy');
const { unregisterAllHotkeys, triggerBackendAction } = require('./hotkeys');
const { BACKEND_HOST, BACKEND_PORT, BACKEND_ORIGIN } = require('./config');
const { derivePhase, deriveServices, describeHardware } = require('./bootPhases');

// Adopt an inherited token when the backend is managed by something else (the
// Linux launcher starts it before us, so sidecar.js finds it already listening
// and treats it as "external"). Minting a fresh token unconditionally meant
// that in external mode we authenticated against a backend holding a DIFFERENT
// token, so every request 401'd — external-backend support existed in
// sidecar.js but could never actually work. When we spawn the backend
// ourselves, nothing is inherited and we generate one as before, which stays
// the normal path.
const authToken = process.env.BETTERFINGERS_AUTH_TOKEN || randomUUID();
// The token lives only in the main process (Phase 3c). The renderer reaches the
// backend exclusively through the validated proxy, which holds these.
backendProxy.init({ origin: BACKEND_ORIGIN, token: authToken });

let tray = null;
let sidecar = null;
let isQuitting = false;

// The hidden overlay window keeps Electron alive after the dashboard is
// closed, so `mainWindow` can be destroyed (null via windows.js) while the
// app keeps running. Anything that wants to show the dashboard must go
// through this so tray/second-instance can always bring it back.
function ensureMainWindow() {
  let win = getMainWindow();
  if (!win || win.isDestroyed()) {
    win = createMainWindow();
  }
  return win;
}

// OR-02 boot-phase state. bootSidecarOutcome is the ONE thing that may set
// phase 'failed' (see bootPhases.derivePhase) and it is set exclusively from
// sidecar.start()'s own resolution/rejection below -- never from a timer in
// this file or in the splash renderer.
let bootStartedAt = null;
let bootSidecarOutcome = 'pending'; // 'pending' | 'ready' | 'failed'
let bootLastError = null;
let bootLastDoctor = null;
let bootTicker = null;
let bootDoctorTimer = null;
let bootFinished = false; // true once the main dashboard window has been revealed

function currentBootSnapshot() {
  const elapsedMs = bootStartedAt ? Date.now() - bootStartedAt : 0;
  const phase = derivePhase({ elapsedMs, doctor: bootLastDoctor, sidecarOutcome: bootSidecarOutcome });
  return {
    phase,
    elapsedMs,
    services: deriveServices(bootLastDoctor),
    hardware: describeHardware(bootLastDoctor),
    error: phase === 'failed'
      ? { message: bootLastError || 'The backend did not start.' }
      : null,
  };
}

function pushBootSnapshot() {
  const win = getSplashWindow();
  const snapshot = currentBootSnapshot();
  if (win && !win.isDestroyed()) {
    win.webContents.send('splash:boot', snapshot);
  }
  if (snapshot.phase === 'ready') {
    revealMainWindow();
  }
}

async function pollDoctorForBoot() {
  if (bootFinished) {
    return;
  }
  try {
    const result = await backendProxy.request({ method: 'GET', path: '/doctor', timeoutMs: 2500 });
    if (result && result.ok) {
      bootLastDoctor = result.body;
      pushBootSnapshot();
    }
  } catch (error) {
    // The backend isn't answering yet -- waitForHealthy is still the source
    // of truth for booting vs. failed; this poll only enriches the display.
  }
}

function stopBootTimers() {
  if (bootTicker) {
    clearInterval(bootTicker);
    bootTicker = null;
  }
  if (bootDoctorTimer) {
    clearInterval(bootDoctorTimer);
    bootDoctorTimer = null;
  }
}

/**
 * Test/diagnostic escape hatch for the boot gate. Strict '1' only, so a stray
 * empty or truthy-looking value cannot disable the gate by accident.
 */
function shouldSkipBootGate() {
  return process.env.BF_SKIP_BOOT_GATE === '1';
}

function revealMainWindow() {
  if (bootFinished) {
    return;
  }
  bootFinished = true;
  stopBootTimers();
  const win = ensureMainWindow();
  win.once('ready-to-show', () => {
    closeSplashWindow();
  });
  if (!win.webContents.isLoading()) {
    // The renderer already finished loading before this handler was attached.
    closeSplashWindow();
  }
  focusMainWindow(win);
}

// Runs once at cold boot, and again from the splash's Retry action
// (registerIpc's onSplashRetry below) -- both paths go through the same
// sidecar.start() call, so 'failed' can only ever come from that promise
// rejecting, per SPLASH_SPEC.md's one rule.
function startBackendBoot() {
  bootStartedAt = Date.now();
  bootSidecarOutcome = 'pending';
  bootLastError = null;
  bootLastDoctor = null;
  pushBootSnapshot();

  stopBootTimers();
  bootTicker = setInterval(pushBootSnapshot, 500);
  bootDoctorTimer = setInterval(pollDoctorForBoot, 750);
  pollDoctorForBoot();

  sidecar.start().then(() => {
    bootSidecarOutcome = 'ready';
    pushBootSnapshot();
  }).catch((error) => {
    console.error('Failed to start BetterFingers backend:', error);
    bootSidecarOutcome = 'failed';
    bootLastError = error && error.message ? error.message : String(error);
    pushBootSnapshot();
  });
}

async function retryBackendBoot() {
  if (bootFinished) {
    // Retry only makes sense pre-reveal; post-reveal recovery already goes
    // through the existing sidecar health-monitor + backendBanner path.
    return;
  }
  try {
    if (sidecar) {
      await sidecar.stop();
    }
  } catch (error) {
    console.error('Error stopping backend before splash retry:', error);
  }
  startBackendBoot();
}

// Focuses the splash while boot is still in flight (so a tray click never
// summons a half-broken dashboard before the backend is real), otherwise the
// dashboard itself.
function focusAppropriateWindow() {
  if (!bootFinished) {
    const splash = getSplashWindow();
    if (splash && !splash.isDestroyed()) {
      focusMainWindow(splash);
      return;
    }
  }
  focusMainWindow(ensureMainWindow());
}

function getDefaultDevPythonCommand() {
  if (process.platform === 'win32') {
    return 'python';
  }

  return 'python3';
}

// The dev backend (server.py) needs the project's dependencies (pyperclip,
// fastapi, …). Those live in the repo virtualenv, not the system interpreter, so
// prefer .venv when it exists — otherwise a bare `python3` fails at `import
// pyperclip`. Repo root is three levels up from app/out/main (or app/src/main).
function resolveVenvPython() {
  const repoRoot = path.resolve(__dirname, '../../../');
  const relative = process.platform === 'win32'
    ? path.join('.venv', 'Scripts', 'python.exe')
    : path.join('.venv', 'bin', 'python');
  const candidate = path.join(repoRoot, relative);
  return fs.existsSync(candidate) ? candidate : null;
}

function resolveDevPythonCommand() {
  const fallbackCommand = getDefaultDevPythonCommand();

  if (process.env.BETTERFINGERS_PYTHON) {
    const pythonPath = process.env.BETTERFINGERS_PYTHON;
    if (path.isAbsolute(pythonPath)) {
      if (!fs.existsSync(pythonPath)) {
        console.warn(`BETTERFINGERS_PYTHON points to a missing file: ${pythonPath}. Falling back to ${fallbackCommand}.`);
        return fallbackCommand;
      }
      return pythonPath;
    }
    if (/[\\/]/.test(pythonPath)) {
      const resolvedPath = path.resolve(process.cwd(), pythonPath);
      if (!fs.existsSync(resolvedPath)) {
        console.warn(`BETTERFINGERS_PYTHON points to a missing file: ${resolvedPath}. Falling back to ${fallbackCommand}.`);
        return fallbackCommand;
      }
      return resolvedPath;
    }
    return pythonPath;
  }

  // No explicit override: prefer the repo virtualenv, then the system Python.
  const venvPython = resolveVenvPython();
  if (venvPython) {
    return venvPython;
  }

  return fallbackCommand;
}

function notifyRendererSidecarStatus(status) {
  const window = getMainWindow();
  if (window && !window.isDestroyed()) {
    window.webContents.send('sidecar:status', status);
  }
}

function bootstrapApp() {
  sidecar = createSidecar({
    host: BACKEND_HOST,
    port: BACKEND_PORT,
    authToken,
    devCommand: resolveDevPythonCommand(),
    devArgs: [
      'server.py',
      '--host',
      BACKEND_HOST,
      '--port',
      String(BACKEND_PORT),
    ],
    onStatusChange: notifyRendererSidecarStatus,
  });

  registerIpc({
    getMainWindow: () => getMainWindow(),
    getSidecarStatus: () => sidecar?.getStatus?.() ?? { state: 'unknown', message: 'Sidecar is unavailable.' },
    getSidecarLogs: () => sidecar?.getLogs?.() ?? [],
    getAuthToken: () => authToken,
    getBackendOrigin: () => BACKEND_ORIGIN,
    onQuit: requestQuit,
    onShow: () => focusAppropriateWindow(),
    // OR-02: the splash's own boot-phase channel. getSplashBootState backs a
    // pull (splash:get-state) for a page that finishes loading after boot
    // already started and would otherwise miss the earlier pushed events.
    onSplashRetry: retryBackendBoot,
    getSplashBootState: () => currentBootSnapshot(),
  });

  // The dashboard window is NOT created here -- only once boot succeeds (see
  // revealMainWindow()). Only the splash is shown at cold boot.
  //
  // BF_SKIP_BOOT_GATE is the one documented way past that, and it exists
  // because gating the window on a healthy backend made the QA harness
  // unrunnable: harness.mjs waits for a window whose URL is signal-desk.html,
  // and it deliberately exercises renderer surfaces WITHOUT a backend, so that
  // window would never arrive and every scenario failed on a 20s timeout.
  //
  // This is a test/diagnostic escape hatch, not a product option. It is off
  // unless explicitly set to '1' (pinned by app/tests/bootPhases.test.mjs), it
  // is never set by any shipping path, and boot still runs normally underneath
  // -- the only thing it changes is that the dashboard is shown immediately
  // instead of waiting for readiness. Shipped behaviour is untouched.
  if (shouldSkipBootGate()) {
    revealMainWindow();
  } else {
    createSplashWindow();
  }
  createOverlayWindow();
  tray = createTray({
    getMainWindow: () => getMainWindow(),
    onShow: () => focusAppropriateWindow(),
    onQuit: requestQuit,
    onToggleRecording: () => triggerBackendAction('/runtime/recording/toggle'),
  });

  startBackendBoot();
}

async function requestQuit() {
  if (isQuitting) {
    return;
  }

  isQuitting = true;

  try {
    if (sidecar) {
      await sidecar.stop();
    }
    unregisterAllHotkeys();
  } catch (error) {
    console.error('Failed to stop backend cleanly:', error);
  } finally {
    app.exit(0);
  }
}

app.setAppUserModelId('com.betterfingers.desktop');

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.whenReady().then(bootstrapApp);

  app.on('second-instance', () => {
    focusAppropriateWindow();
  });

  app.on('window-all-closed', () => {
    requestQuit();
  });

  app.on('before-quit', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      requestQuit();
    }
  });
}
