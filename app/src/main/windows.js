const path = require('node:path');
const fs = require('node:fs');
const { BrowserWindow, app } = require('electron');

let mainWindow = null;

const OVERLAY_SIZE = { width: 220, height: 54 };

function overlayPositionFile() {
  return path.join(app.getPath('userData'), 'overlay-position.json');
}

function readSavedOverlayPosition() {
  try {
    const raw = fs.readFileSync(overlayPositionFile(), 'utf8');
    const pos = JSON.parse(raw);
    if (Number.isFinite(pos?.x) && Number.isFinite(pos?.y)) {
      return { x: Math.round(pos.x), y: Math.round(pos.y) };
    }
  } catch (error) {
    // No saved position yet, or it's unreadable — fall back to the default.
  }
  return null;
}

function saveOverlayPosition(x, y) {
  try {
    fs.writeFileSync(overlayPositionFile(), JSON.stringify({ x, y }));
  } catch (error) {
    // Non-fatal: the overlay just won't remember its spot this run.
  }
}

// True only if the point sits inside some display's work area (so a saved
// position on a since-disconnected monitor doesn't strand the overlay offscreen).
function isPositionOnScreen(x, y) {
  const { screen } = require('electron');
  return screen.getAllDisplays().some((display) => {
    const { x: dx, y: dy, width, height } = display.workArea;
    return x >= dx && y >= dy && x + OVERLAY_SIZE.width <= dx + width + 1 && y + OVERLAY_SIZE.height <= dy + height + 1;
  });
}

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

  // Restore the last dragged position if it's still on a connected display;
  // otherwise default to the bottom-right corner of the primary display.
  const { screen } = require('electron');
  const saved = readSavedOverlayPosition();
  if (saved && isPositionOnScreen(saved.x, saved.y)) {
    overlayWindow.setPosition(saved.x, saved.y);
  } else {
    const primaryDisplay = screen.getPrimaryDisplay();
    const { width, height } = primaryDisplay.workAreaSize;
    overlayWindow.setPosition(width - 240, height - 74);
  }

  // Persist the position when the user drags the overlay (debounced).
  let moveSaveTimer = null;
  overlayWindow.on('moved', () => {
    if (moveSaveTimer) clearTimeout(moveSaveTimer);
    moveSaveTimer = setTimeout(() => {
      if (overlayWindow && !overlayWindow.isDestroyed()) {
        const [x, y] = overlayWindow.getPosition();
        saveOverlayPosition(x, y);
      }
    }, 400);
  });

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
