const path = require('node:path');
const fs = require('node:fs');
const { Tray, Menu, nativeImage } = require('electron');

let tray = null;

function resolveTrayIconPath() {
  if (process.resourcesPath) {
    return path.join(process.resourcesPath, 'assets', 'indicator_idle.png');
  }

  return path.resolve(__dirname, '../../../assets/indicator_idle.png');
}

function loadTrayImage() {
  const iconPath = resolveTrayIconPath();
  if (iconPath && fs.existsSync(iconPath)) {
    return nativeImage.createFromPath(iconPath);
  }

  return nativeImage.createEmpty();
}

function createTray({ getMainWindow, onShow, onQuit }) {
  const trayImage = loadTrayImage();
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
