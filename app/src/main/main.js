const path = require('node:path');
const { app } = require('electron');
const { createMainWindow, focusMainWindow } = require('./windows');
const { createSidecar } = require('./sidecar');
const { createTray } = require('./tray');
const { registerIpc } = require('./ipc');

let mainWindow = null;
let tray = null;
let sidecar = null;
let isQuitting = false;

function resolveDevPythonCommand() {
  if (process.env.BETTERFINGERS_PYTHON) {
    const pythonPath = process.env.BETTERFINGERS_PYTHON;
    if (path.isAbsolute(pythonPath)) {
      return pythonPath;
    }
    if (/[\\/]/.test(pythonPath)) {
      return path.resolve(process.cwd(), pythonPath);
    }
    return pythonPath;
  }

  if (process.platform === 'win32') {
    return 'python';
  }

  return 'python3';
}

function bootstrapApp() {
  sidecar = createSidecar({
    host: '127.0.0.1',
    port: 8000,
    devCommand: resolveDevPythonCommand(),
    devArgs: [
      'server.py',
      '--host',
      '127.0.0.1',
      '--port',
      '8000',
    ],
  });

  mainWindow = createMainWindow();
  tray = createTray({
    getMainWindow: () => mainWindow,
    onShow: () => focusMainWindow(mainWindow),
    onQuit: requestQuit,
  });

  registerIpc({
    getMainWindow: () => mainWindow,
    getSidecarStatus: () => sidecar?.getStatus?.() ?? { state: 'unknown', message: 'Sidecar is unavailable.' },
    onQuit: requestQuit,
    onShow: () => focusMainWindow(mainWindow),
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
}

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
