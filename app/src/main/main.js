const path = require('node:path');
const fs = require('node:fs');
const { randomUUID } = require('node:crypto');
const { app } = require('electron');
const { createMainWindow, focusMainWindow, createOverlayWindow } = require('./windows');
const { createSidecar } = require('./sidecar');
const { createTray } = require('./tray');
const { registerIpc } = require('./ipc');

const authToken = randomUUID();

let mainWindow = null;
let tray = null;
let sidecar = null;
let isQuitting = false;

function getDefaultDevPythonCommand() {
  if (process.platform === 'win32') {
    return 'python';
  }

  return 'python3';
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

  return fallbackCommand;
}

function bootstrapApp() {
  sidecar = createSidecar({
    host: '127.0.0.1',
    port: 8000,
    authToken,
    devCommand: resolveDevPythonCommand(),
    devArgs: [
      'server.py',
      '--host',
      '127.0.0.1',
      '--port',
      '8000',
    ],
  });

  registerIpc({
    getMainWindow: () => mainWindow,
    getSidecarStatus: () => sidecar?.getStatus?.() ?? { state: 'unknown', message: 'Sidecar is unavailable.' },
    getSidecarLogs: () => sidecar?.getLogs?.() ?? [],
    getAuthToken: () => authToken,
    onQuit: requestQuit,
    onShow: () => focusMainWindow(mainWindow),
  });

  mainWindow = createMainWindow();
  createOverlayWindow();
  tray = createTray({
    getMainWindow: () => mainWindow,
    onShow: () => focusMainWindow(mainWindow),
    onQuit: requestQuit,
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
    focusMainWindow(mainWindow);
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
