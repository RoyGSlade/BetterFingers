// Deliberate Node mirror of app_paths.resolve_base() (see repo root
// app_paths.py). The Electron main process and the Python backend must agree
// on ONE unified user-data root so the privacy/factory-reset tooling can
// reason about a single location. This file has no electron import (and does
// NOT use app.getPath('userData'), which is a different, Electron-only root)
// so it stays unit-testable without an Electron runtime.
//
// IMPORTANT: the precedence below must be changed together with
// app_paths.resolve_base() — if one changes without the other, the Electron
// main process and the Python backend will resolve to different directories.

const path = require('node:path');
const os = require('node:os');

const APP_NAME = 'BetterFingers';

function expandHome(p, homedir) {
  if (p === '~') return homedir();
  if (p.startsWith('~/') || p.startsWith('~\\')) {
    return path.join(homedir(), p.slice(2));
  }
  return p;
}

// Platform-correct default (mirrors platform_paths.get_app_data_dir()):
// Windows -> %APPDATA%/BetterFingers, else ~/AppData/Roaming/BetterFingers;
// darwin -> ~/Library/Application Support/BetterFingers;
// else -> $XDG_DATA_HOME/BetterFingers if set, else ~/.local/share/BetterFingers.
function platformDefault({ env, platform, homedir }) {
  if (platform === 'win32') {
    if (env.APPDATA) return path.join(env.APPDATA, APP_NAME);
    return path.join(homedir(), 'AppData', 'Roaming', APP_NAME);
  }
  if (platform === 'darwin') {
    return path.join(homedir(), 'Library', 'Application Support', APP_NAME);
  }
  if (env.XDG_DATA_HOME) return path.join(env.XDG_DATA_HOME, APP_NAME);
  return path.join(homedir(), '.local', 'share', APP_NAME);
}

// The original legacy location: %APPDATA%/BetterFingers on Windows (when
// APPDATA is set), else ~/BetterFingers.
function legacyHomeBase({ env, homedir }) {
  if (env.APPDATA) return path.join(env.APPDATA, APP_NAME);
  return path.join(homedir(), APP_NAME);
}

const fs = require('node:fs');

function defaultExistsWithContents(dir) {
  try {
    const entries = fs.readdirSync(dir);
    return entries.length > 0;
  } catch {
    return false;
  }
}

// Resolve the one data root, in priority order — mirrors
// app_paths.resolve_base() exactly:
//   1. BETTERFINGERS_DATA_DIR (explicit override, ~ expanded),
//   2. %APPDATA%/BetterFingers when APPDATA is set (Windows convention, and
//      how callers/tests pin the location explicitly),
//   3. an existing legacy ~/BetterFingers that already holds data,
//   4. the platform-correct default (XDG on Linux) for a fresh install.
function resolveUserDataRoot({
  env = process.env,
  platform = process.platform,
  homedir = os.homedir,
  existsWithContents = defaultExistsWithContents,
} = {}) {
  const override = env.BETTERFINGERS_DATA_DIR;
  if (override) {
    return expandHome(override, homedir);
  }
  if (env.APPDATA) {
    return legacyHomeBase({ env, homedir });
  }
  const legacy = legacyHomeBase({ env, homedir });
  if (existsWithContents(legacy)) {
    return legacy;
  }
  return platformDefault({ env, platform, homedir });
}

module.exports = {
  resolveUserDataRoot,
  platformDefault,
};
