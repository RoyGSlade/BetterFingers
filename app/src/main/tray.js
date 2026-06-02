const path = require('node:path');
const fs = require('node:fs');
const { app } = require('electron');
const { Tray, Menu, nativeImage } = require('electron');

let tray = null;

function resolveTrayIconPath() {
  const candidates = app.isPackaged
    ? [
        path.join(process.resourcesPath, 'assets', 'indicator_idle.png'),
        path.join(process.resourcesPath, 'images', 'InactiveTray.png'),
        path.join(process.resourcesPath, 'images', 'activetray.png'),
      ]
    : [
        path.resolve(__dirname, '../../../assets/indicator_idle.png'),
        path.resolve(__dirname, '../../../images/InactiveTray.png'),
        path.resolve(__dirname, '../../../images/activetray.png'),
      ];

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  return null;
}

function createTray({ getMainWindow, onShow, onQuit }) {
  const iconPath = resolveTrayIconPath();
  const trayImage = iconPath ? nativeImage.createFromPath(iconPath) : nativeImage.createEmpty();
  tray = new Tray(trayImage);
  tray.setToolTip('BetterFingers');

  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Show Dashboard',
      click: () => {
        const window = getMainWindow?.();
        if (window && onShow) {
          onShow(window);
        }
      },
    },
    {
      label: 'Quit BetterFingers',
      click: () => {
        if (onQuit) {
          onQuit();
        }
      },
    },
  ]);

  tray.setContextMenu(contextMenu);
  tray.on('click', () => {
    const window = getMainWindow?.();
    if (window && onShow) {
      onShow(window);
    }
  });

  return tray;
}

module.exports = {
  createTray,
};
