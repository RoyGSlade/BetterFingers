const path = require('node:path');
const fs = require('node:fs');
const { randomUUID } = require('node:crypto');
const { app } = require('electron');
const { createMainWindow, getMainWindow, focusMainWindow, createOverlayWindow } = require('./windows');
const { createSidecar } = require('./sidecar');
const { createTray } = require('./tray');
const { registerIpc } = require('./ipc');
const backendProxy = require('./backendProxy');
const { unregisterAllHotkeys, triggerBackendAction } = require('./hotkeys');
const { BACKEND_HOST, BACKEND_PORT, BACKEND_ORIGIN } = require('./config');

const authToken = randomUUID();
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
    onShow: () => focusMainWindow(ensureMainWindow()),
  });

  createMainWindow();
  createOverlayWindow();
  tray = createTray({
    getMainWindow: () => getMainWindow(),
    onShow: () => focusMainWindow(ensureMainWindow()),
    onQuit: requestQuit,
    onToggleRecording: () => triggerBackendAction('/runtime/recording/toggle'),
  });

  sidecar.start().catch((error) => {
    console.error('Failed to start BetterFingers backend:', error);
  });
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
    focusMainWindow(ensureMainWindow());
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
