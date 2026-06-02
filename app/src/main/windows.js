const path = require('node:path');
const { BrowserWindow } = require('electron');

let mainWindow = null;

function resolvePreloadPath() {
  return path.join(__dirname, '../preload/preload.js');
}

function loadDashboard(window) {
  if (process.env.ELECTRON_RENDERER_URL) {
    return window.loadURL(process.env.ELECTRON_RENDERER_URL);
  }

  return window.loadFile(path.join(__dirname, '../renderer/index.html'));
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1240,
    height: 800,
    minWidth: 960,
    minHeight: 680,
    show: false,
    backgroundColor: '#07111f',
    title: 'BetterFingers',
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: resolvePreloadPath(),
    },
  });

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  loadDashboard(mainWindow).catch((error) => {
    console.error('Failed to load Electron dashboard:', error);
  });

  return mainWindow;
}

function focusMainWindow(window = mainWindow) {
  if (!window) {
    return;
  }

  if (window.isMinimized()) {
    window.restore();
  }

  window.show();
  window.focus();
}

module.exports = {
  createMainWindow,
  focusMainWindow,
};
