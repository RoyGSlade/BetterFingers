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

// ---- Overlay appearance (size / placement / opacity / vibrancy / label) ----
// Persisted in the main process so it survives restarts and can be applied to
// the frameless overlay window without round-tripping through the Python profile.
const OVERLAY_SIZE_PX = { small: 46, medium: 70, large: 108, xlarge: 150 };
const OVERLAY_PLACEMENTS = new Set([
  'top-left', 'top', 'top-right',
  'left', 'center', 'right',
  'bottom-left', 'bottom', 'bottom-right',
]);
const OVERLAY_LABEL_POSITIONS = new Set(['hidden', 'beside', 'above', 'below', 'center']);
const DEFAULT_OVERLAY_APPEARANCE = {
  size: 'medium',
  placement: 'bottom-right',
  opacity: 1,
  vibrancy: 1,
  labelPos: 'hidden',
  alwaysOn: false,
};
let overlayAppearance = { ...DEFAULT_OVERLAY_APPEARANCE };

function overlayAppearanceFile() {
  return path.join(app.getPath('userData'), 'overlay-appearance.json');
}

function loadOverlayAppearance() {
  try {
    const raw = JSON.parse(fs.readFileSync(overlayAppearanceFile(), 'utf8'));
    overlayAppearance = normalizeOverlayAppearance(raw);
  } catch (error) {
    overlayAppearance = { ...DEFAULT_OVERLAY_APPEARANCE };
  }
  return overlayAppearance;
}

function normalizeOverlayAppearance(partial) {
  const base = { ...DEFAULT_OVERLAY_APPEARANCE, ...overlayAppearance, ...(partial || {}) };
  // Back-compat: an older stored `showLabel` boolean maps onto labelPos.
  let labelPos = base.labelPos;
  if (labelPos === undefined && base.showLabel !== undefined) {
    labelPos = base.showLabel ? 'beside' : 'hidden';
  }
  return {
    size: OVERLAY_SIZE_PX[base.size] ? base.size : 'medium',
    placement: OVERLAY_PLACEMENTS.has(base.placement) ? base.placement : 'bottom-right',
    opacity: Math.max(0.15, Math.min(1, Number(base.opacity) || 1)),
    vibrancy: Math.max(0.3, Math.min(2, Number(base.vibrancy) || 1)),
    labelPos: OVERLAY_LABEL_POSITIONS.has(labelPos) ? labelPos : 'hidden',
    alwaysOn: Boolean(base.alwaysOn),
  };
}

// Window pixel bounds for a given appearance (ring + padding, plus room for the
// label depending on where it sits).
function overlayWindowSize(appearance) {
  const ring = OVERLAY_SIZE_PX[appearance.size] || OVERLAY_SIZE_PX.medium;
  const pad = 20;
  const box = ring + pad;
  const pos = appearance.labelPos;
  if (pos === 'beside') return { width: box + 176, height: box };
  if (pos === 'above' || pos === 'below') return { width: Math.max(box, 190), height: box + 26 };
  return { width: box, height: box }; // hidden or center
}

// Screen position for a placement anchor, given the window size.
function overlayAnchorPosition(placement, winW, winH) {
  const { screen } = require('electron');
  const wa = screen.getPrimaryDisplay().workArea;
  const m = 20;
  const left = wa.x + m;
  const cx = Math.round(wa.x + (wa.width - winW) / 2);
  const right = wa.x + wa.width - winW - m;
  const top = wa.y + m;
  const cy = Math.round(wa.y + (wa.height - winH) / 2);
  const bottom = wa.y + wa.height - winH - m;
  const map = {
    'top-left': [left, top], 'top': [cx, top], 'top-right': [right, top],
    'left': [left, cy], 'center': [cx, cy], 'right': [right, cy],
    'bottom-left': [left, bottom], 'bottom': [cx, bottom], 'bottom-right': [right, bottom],
  };
  return map[placement] || map['bottom-right'];
}

// Apply the current appearance to the live overlay window + its renderer.
function applyOverlayAppearance() {
  if (!overlayWindow || overlayWindow.isDestroyed()) return;
  const a = overlayAppearance;
  const { width, height } = overlayWindowSize(a);
  overlayWindow.setSize(width, height);
  const [x, y] = overlayAnchorPosition(a.placement, width, height);
  overlayWindow.setPosition(x, y);
  try { overlayWindow.setOpacity(a.opacity); } catch (error) { /* WM may not support it */ }
  // Forward the renderer-side bits (ring size / vibrancy / label position) to the overlay.
  overlayWindow.webContents.send('overlay:appearance', {
    size: a.size, vibrancy: a.vibrancy, labelPos: a.labelPos,
  });
  // Pinned always-on: keep it up showing the idle ring. (When it's off, the
  // status flow in ipc.js hides it once nothing is happening.)
  if (a.alwaysOn) {
    if (!overlayWindow.isVisible()) overlayWindow.showInactive();
    overlayWindow.webContents.send('overlay:update', { status: 'idle', message: '', durationMs: 0 });
  }
}

function getOverlayAppearance() {
  return { ...overlayAppearance };
}

function setOverlayAppearance(partial) {
  overlayAppearance = normalizeOverlayAppearance(partial);
  try {
    fs.writeFileSync(overlayAppearanceFile(), JSON.stringify(overlayAppearance));
  } catch (error) {
    // Non-fatal: it just won't persist across restarts.
  }
  applyOverlayAppearance();
  return getOverlayAppearance();
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

// Lock a window to the app's own pages: deny all popups, and block any
// navigation away from our file:// pages (or the dev-server origin). The
// preload bridge grants real powers — a frame that navigated to foreign
// content must never inherit them.
function hardenWindowNavigation(window) {
  const devOrigin = process.env.ELECTRON_RENDERER_URL;
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', (event, url) => {
    const allowed =
      url.startsWith('file://') || (devOrigin && url.startsWith(devOrigin));
    if (!allowed) {
      console.warn(`[windows] Blocked navigation to ${url}`);
      event.preventDefault();
    }
  });
}

// The window/taskbar icon (glitch-ring app icon). electron-builder sets the
// packaged executable icon from build.icon; this covers the runtime BrowserWindow
// icon (notably on Linux). Returns a path if found, else undefined (Electron
// falls back to its default).
function resolveAppIcon() {
  const candidates = [
    path.join(__dirname, '../../build/icon.png'), // dev: out/main -> app/build
    path.join(__dirname, '../../../build/icon.png'),
    path.join(process.resourcesPath || '', 'build/icon.png'),
  ];
  for (const candidate of candidates) {
    try {
      if (candidate && fs.existsSync(candidate)) return candidate;
    } catch (error) {
      // ignore and try the next candidate
    }
  }
  return undefined;
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
    icon: resolveAppIcon(),
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: resolvePreloadPath(),
    },
  });

  hardenWindowNavigation(mainWindow);

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

function getMainWindow() {
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
  loadOverlayAppearance();
  const initial = overlayWindowSize(overlayAppearance);
  overlayWindow = new BrowserWindow({
    width: initial.width,
    height: initial.height,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    hasShadow: false,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: resolvePreloadPath(),
    },
  });

  // Persist the position when the user drags the overlay (debounced) — used as a
  // fallback, though the placement setting is the primary positioner.
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

  hardenWindowNavigation(overlayWindow);

  if (process.env.ELECTRON_RENDERER_URL) {
    overlayWindow.loadURL(`${process.env.ELECTRON_RENDERER_URL}/overlay.html`);
  } else {
    overlayWindow.loadFile(path.join(__dirname, '../renderer/overlay.html'));
  }

  // Once the renderer is ready, apply size/placement/opacity and push the
  // renderer-side appearance (ring size / vibrancy / label).
  overlayWindow.webContents.once('did-finish-load', () => {
    applyOverlayAppearance();
  });

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

  hardenWindowNavigation(reviewWindow);

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
  getMainWindow,
  focusMainWindow,
  createOverlayWindow,
  getOverlayWindow,
  getOverlayAppearance,
  setOverlayAppearance,
  createReviewWindow,
  showReviewWindow,
  hideReviewWindow,
  getReviewWindow,
};
