const { app } = require('electron');

// Single source of truth for how the Electron main process reaches the sidecar
// backend. Everything (main bootstrap, sidecar lifecycle, global hotkeys) reads
// host/port/origin from here so there is exactly one place to change them.

const BACKEND_HOST = process.env.BETTERFINGERS_HOST || '127.0.0.1';
const BACKEND_PORT = Number(process.env.BETTERFINGERS_PORT || 8000);
const BACKEND_ORIGIN = `http://${BACKEND_HOST}:${BACKEND_PORT}`;

// The backend contract this client speaks. Must match server.py's
// /runtime/version `schema_version`. Bump both together on a breaking API change.
const EXPECTED_API_SCHEMA_VERSION = 1;

module.exports = {
  BACKEND_HOST,
  BACKEND_PORT,
  BACKEND_ORIGIN,
  EXPECTED_API_SCHEMA_VERSION,
};

// The app (marketing) version. Bumping this must NOT trip the compatibility
// banner on its own — only the API schema above gates client/backend compat.
// A lazy getter (not a value computed at module load) so this module can be
// required outside a running Electron app (e.g. `node --test`, where
// require('electron') resolves to the CLI binary path rather than the app
// module and `app` is undefined) without throwing before anything even reads
// APP_VERSION.
Object.defineProperty(module.exports, 'APP_VERSION', {
  enumerable: true,
  get() {
    return app.getVersion();
  },
});
