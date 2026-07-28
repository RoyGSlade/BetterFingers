const { resolve } = require('node:path');
const { defineConfig, externalizeDepsPlugin } = require('electron-vite');

module.exports = defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: {
      rollupOptions: {
        input: {
          main: resolve(__dirname, 'src/main/main.js'),
          config: resolve(__dirname, 'src/main/config.js'),
          windows: resolve(__dirname, 'src/main/windows.js'),
          sidecar: resolve(__dirname, 'src/main/sidecar.js'),
          tray: resolve(__dirname, 'src/main/tray.js'),
          ipc: resolve(__dirname, 'src/main/ipc.js'),
          hotkeys: resolve(__dirname, 'src/main/hotkeys.js'),
          senderValidation: resolve(__dirname, 'src/main/senderValidation.js'),
          backendProxy: resolve(__dirname, 'src/main/backendProxy.js'),
          userDataRoot: resolve(__dirname, 'src/main/userDataRoot.js'),
          onboardingStore: resolve(__dirname, 'src/main/onboardingStore.js'),
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
          // Signal Desk (DESIGN.md §11) behind BF_UI=signal-desk — see
          // windows.js loadDashboard(). Built but not default: without this
          // entry the page only ever ran over file://, where its own header
          // documents that type="module" fetches are CORS-blocked, so the
          // real feature modules never mounted and nothing could be verified
          // against the actual Electron bridge.
          signalDeskPreview: resolve(__dirname, 'src/renderer/signal-desk-preview.html'),
          // Production Signal Desk build (binding decision D-0007: the
          // preview stays untouched and keeps shipping as its own entry
          // above; this is the real single-script page, opt-in behind a
          // separate BF_UI value once main/windows.js and
          // main/senderValidation.js are updated to route/allowlist it — see
          // the W1-COMP-ROOT handoff for that exact diff).
          signalDesk: resolve(__dirname, 'src/renderer/signal-desk.html'),
        },
      },
    },
  },
});
