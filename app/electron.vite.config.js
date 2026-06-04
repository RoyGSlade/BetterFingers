const { resolve } = require('node:path');
const { defineConfig, externalizeDepsPlugin } = require('electron-vite');

module.exports = defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: {
      rollupOptions: {
        input: {
          main: resolve(__dirname, 'src/main/main.js'),
          windows: resolve(__dirname, 'src/main/windows.js'),
          sidecar: resolve(__dirname, 'src/main/sidecar.js'),
          tray: resolve(__dirname, 'src/main/tray.js'),
          ipc: resolve(__dirname, 'src/main/ipc.js'),
        },
      },
    },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: {
      rollupOptions: {
        input: {
          preload: resolve(__dirname, 'src/preload/preload.js'),
        },
      },
    },
  },
  renderer: {
    root: resolve(__dirname, 'src/renderer'),
    build: {
      rollupOptions: {
        input: {
          index: resolve(__dirname, 'src/renderer/index.html'),
          overlay: resolve(__dirname, 'src/renderer/overlay.html'),
          reviewOverlay: resolve(__dirname, 'src/renderer/review-overlay.html'),
        },
      },
    },
  },
});
