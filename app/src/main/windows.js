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
  if (!window || window.isDestroyed()) {
    return;
  }

  if (window.isMinimized()) {
    window.restore();
  }

  window.show();
  window.focus();
}

let overlayWindow = null;
let reviewWindow = null;

function createOverlayWindow() {
  overlayWindow = new BrowserWindow({
    width: 220,
    height: 54,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: resolvePreloadPath(),
    },
  });

  const { screen } = require('electron');
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.workAreaSize;
  overlayWindow.setPosition(width - 240, height - 74);

  if (process.env.ELECTRON_RENDERER_URL) {
    overlayWindow.loadURL(`${process.env.ELECTRON_RENDERER_URL}/overlay.html`);
  } else {
    overlayWindow.loadFile(path.join(__dirname, '../renderer/overlay.html'));
  }

  overlayWindow.on('closed', () => {
    overlayWindow = null;
  });

  return overlayWindow;
}

function getOverlayWindow() {
  return overlayWindow;
}

function loadReviewOverlay(window) {
  if (process.env.ELECTRON_RENDERER_URL) {
    return window.loadURL(`${process.env.ELECTRON_RENDERER_URL}/review-overlay.html`);
  }

  return window.loadFile(path.join(__dirname, '../renderer/review-overlay.html'));
}

function createReviewWindow() {
  if (reviewWindow && !reviewWindow.isDestroyed()) {
    return reviewWindow;
  }

  reviewWindow = new BrowserWindow({
    width: 560,
    height: 520,
    minWidth: 420,
    minHeight: 360,
    frame: false,
    transparent: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: true,
    show: false,
    backgroundColor: '#0b111d',
    title: 'BetterFingers Review',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: resolvePreloadPath(),
    },
  });

  const { screen } = require('electron');
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.workAreaSize;
  reviewWindow.setPosition(Math.max(20, width - 590), Math.max(20, height - 560));

  reviewWindow.on('closed', () => {
    reviewWindow = null;
  });

  loadReviewOverlay(reviewWindow).catch((error) => {
    console.error('Failed to load Electron review overlay:', error);
  });

  return reviewWindow;
}

function showReviewWindow(draft) {
  const window = createReviewWindow();
  const sendDraft = () => {
    if (!window.isDestroyed()) {
      window.webContents.send('review:draft', draft ?? null);
    }
  };

  if (window.webContents.isLoading()) {
    window.webContents.once('did-finish-load', sendDraft);
  } else {
    sendDraft();
  }

  window.showInactive();
  return window;
}

function hideReviewWindow() {
  if (reviewWindow && !reviewWindow.isDestroyed() && reviewWindow.isVisible()) {
    reviewWindow.hide();
  }
}

function getReviewWindow() {
  return reviewWindow;
}

module.exports = {
  createMainWindow,
  focusMainWindow,
  createOverlayWindow,
  getOverlayWindow,
  createReviewWindow,
  showReviewWindow,
  hideReviewWindow,
  getReviewWindow,
};
