const path = require('node:path');
const fs = require('node:fs');
const { app } = require('electron');
const { Tray, Menu, nativeImage } = require('electron');

let tray = null;
let iconCache = {};
let currentState = 'idle';

// Map a pipeline state to a tray icon file. Active states share the "active"
// tray art; everything else uses the idle art.
const STATE_ICON_FILES = {
  idle: ['assets/indicator_idle.png', 'images/InactiveTray.png'],
  recording: ['assets/indicator_recording.png', 'images/activetray.png'],
  processing: ['assets/indicator_processing.png', 'images/activetray.png'],
  listening: ['assets/indicator_listening.png', 'images/activetray.png'],
};

function resolveResourceCandidates(relPaths) {
  const roots = app.isPackaged
    ? [process.resourcesPath]
    : [path.resolve(__dirname, '../../../')];
  const candidates = [];
  for (const root of roots) {
    for (const rel of relPaths) {
      candidates.push(path.join(root, rel));
    }
  }
  return candidates;
}

function loadIconForState(state) {
  if (iconCache[state]) {
    return iconCache[state];
  }
  const relPaths = STATE_ICON_FILES[state] || STATE_ICON_FILES.idle;
  for (const candidate of resolveResourceCandidates(relPaths)) {
    if (fs.existsSync(candidate)) {
      const image = nativeImage.createFromPath(candidate);
      if (!image.isEmpty()) {
        iconCache[state] = image;
        return image;
      }
    }
  }
  return null;
}

// Collapse the many backend status strings into one of our icon states.
function normalizeTrayState(status) {
  const s = String(status || '').toLowerCase();
  if (s.includes('recording')) return 'recording';
  if (s === 'transcribing' || s === 'rewriting' || s === 'processing') return 'processing';
  if (s === 'listening') return 'listening';
  return 'idle';
}

function buildMenu({ getMainWindow, onShow, onQuit, onToggleRecording }) {
  return Menu.buildFromTemplate([
    {
      label: currentState === 'recording' ? 'Stop Recording' : 'Start Recording',
      click: () => {
        if (onToggleRecording) onToggleRecording();
      },
    },
    { type: 'separator' },
    {
      label: 'Open Dashboard',
      click: () => {
        // onShow recreates the dashboard when it has been closed, so call it
        // unconditionally rather than gating on getMainWindow() being non-null.
        if (onShow) {
          onShow();
        }
      },
    },
    { type: 'separator' },
    {
      label: 'Quit BetterFingers',
      click: () => {
        if (onQuit) onQuit();
      },
    },
  ]);
}

function createTray({ getMainWindow, onShow, onQuit, onToggleRecording }) {
  const image = loadIconForState('idle');
  tray = new Tray(image || nativeImage.createEmpty());
  tray.setToolTip('BetterFingers');

  const rebuildMenu = () => {
    tray.setContextMenu(buildMenu({ getMainWindow, onShow, onQuit, onToggleRecording }));
  };
  rebuildMenu();

  tray.on('click', () => {
    if (onShow) {
      onShow();
    }
  });

  // Reflect pipeline state in the tray icon + tooltip + menu label.
  tray.setState = (status) => {
    const nextState = normalizeTrayState(status);
    if (nextState === currentState) {
      return;
    }
    currentState = nextState;
    const nextImage = loadIconForState(nextState);
    if (nextImage) {
      tray.setImage(nextImage);
    }
    tray.setToolTip(nextState === 'idle' ? 'BetterFingers' : `BetterFingers — ${nextState}`);
    rebuildMenu();
  };

  return tray;
}

function getTray() {
  return tray;
}

module.exports = {
  createTray,
  getTray,
};
