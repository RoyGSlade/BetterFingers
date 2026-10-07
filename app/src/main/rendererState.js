// Chromium-owned state in Electron's userData folder, and how a factory reset
// clears it.
//
// Where it lives (measured on the packaged app, not assumed). electron-builder's
// `productName` names the installer and the exe; it does NOT reach the app.asar
// package.json, so at runtime Electron's app name is the package `name`
// ("betterfingers-electron") and `app.getPath('userData')` is
// %APPDATA%\betterfingers-electron -- a DIFFERENT folder from the unified data
// root %APPDATA%\BetterFingers that the backend, onboarding.json and the
// privacy inventory use (see userDataRoot.js). The Python factory reset only
// sweeps the unified root, so everything Chromium keeps for the renderer --
// Local Storage (theme/first-run flags and the LEGACY consent flag
// `bf_onboarding_complete`), Session Storage, caches -- used to survive a
// "reset to a fresh state". If the product name is ever added to package.json
// the two folders become one; everything here works the same in both layouts
// (and backend/privacy/data_paths.py declares these names so the backend's
// residual sweep tolerates them when they share the data root).
//
// Two layers, because neither is enough alone:
//   1. LIVE (clearLiveRendererState): clear the default session's storage and
//      caches through the Electron API and empty every open page's
//      localStorage/sessionStorage, then READ BACK that the pages are empty.
//      This is what makes the running app (and a page reload) fresh. Measured
//      in the real app: session.clearStorageData() with no origin also removed
//      the old values' bytes from `Local Storage/leveldb/000003.log` at once,
//      whereas a per-origin clear (CDP Storage.clearDataForOrigin, tried as a
//      stand-in) left them in the LevelDB log even after the app quit. It leaves
//      the storage folders and caches themselves in place: Chromium holds them
//      open while it runs.
//   2. DEFERRED (schedulePurge / purgePendingReset): leave a marker, and at the
//      next launch -- before Chromium has opened anything -- delete the
//      storage/cache entries. That removes what the live clear cannot (open
//      files, the caches) and finishes the job if a live step failed, so a stale
//      flag cannot outlive a reset on any path. The reset result names these
//      entries as pending_until_restart rather than claiming they are gone.
//
// No electron import: the session, webContents list and fs are injected so the
// whole module is unit-testable without an Electron runtime.

const fs = require('node:fs');
const path = require('node:path');

const RESET_PENDING_MARKER = '.factory-reset-pending';

// Exact top-level names Chromium creates for renderer-written state and caches.
// Deleted at the next launch after a reset. Keep in step with
// backend/privacy/data_paths.py ELECTRON_RUNTIME_NAMES (a Python test reads
// this list) and the uninstaller's allowlist (app/build/installer.nsh).
const CHROMIUM_STORAGE_ENTRIES = Object.freeze([
  'Local Storage',
  'Session Storage',
  'IndexedDB',
  'WebStorage',
  'SharedStorage',
  'SharedStorage-wal',
  'SharedStorage-shm',
  'SharedStorage-journal',
  'Service Worker',
  'File System',
  'databases',
  'blob_storage',
  'Network',
  'Cache',
  'Code Cache',
  'GPUCache',
  'DawnGraphiteCache',
  'DawnWebGPUCache',
  'Shared Dictionary',
]);

function errorMessage(error) {
  return String((error && error.message) || error);
}

function markerPath(userDataDir) {
  return path.join(userDataDir, RESET_PENDING_MARKER);
}

// Records that a reset happened, so the next launch finishes the job. Written
// into Electron's userData folder (never the unified root, which a reset must
// leave empty). Returns { ok, error? }.
function schedulePurge({ userDataDir, fsImpl = fs, now = () => new Date() } = {}) {
  if (!userDataDir) return { ok: false, error: 'no userData directory' };
  try {
    fsImpl.mkdirSync(userDataDir, { recursive: true });
    fsImpl.writeFileSync(
      markerPath(userDataDir),
      JSON.stringify({ requested_at: now().toISOString() }),
    );
    return { ok: true };
  } catch (error) {
    return { ok: false, error: errorMessage(error) };
  }
}

// Which purge-listed entries exist right now (what "pending until restart"
// means concretely). Never throws.
function pendingEntries({ userDataDir, fsImpl = fs } = {}) {
  if (!userDataDir) return [];
  return CHROMIUM_STORAGE_ENTRIES.filter((name) => {
    try {
      fsImpl.lstatSync(path.join(userDataDir, name));
      return true;
    } catch {
      return false;
    }
  });
}

// Run once at startup, BEFORE app 'ready' (Chromium has opened none of these
// yet). If a reset left its marker, delete the storage/cache entries and then
// the marker. A link (symlink/junction) is removed as a link and never
// followed. Any failure keeps the marker so the next launch retries; it is
// reported, never silently dropped. Never throws.
function purgePendingReset({ userDataDir, fsImpl = fs, log = console } = {}) {
  const result = { pending: false, removed: [], failed: [] };
  if (!userDataDir) return result;
  try {
    fsImpl.lstatSync(markerPath(userDataDir));
  } catch {
    return result;
  }
  result.pending = true;
  for (const name of CHROMIUM_STORAGE_ENTRIES) {
    const target = path.join(userDataDir, name);
    try {
      let stat;
      try {
        stat = fsImpl.lstatSync(target);
      } catch {
        continue; // nothing there
      }
      if (stat.isSymbolicLink()) {
        fsImpl.unlinkSync(target);
      } else {
        fsImpl.rmSync(target, { recursive: true, force: true });
      }
      result.removed.push(name);
    } catch (error) {
      result.failed.push({ name, error: errorMessage(error) });
      log.warn?.(`[rendererState] could not remove ${name}: ${errorMessage(error)}`);
    }
  }
  if (result.failed.length === 0) {
    try {
      fsImpl.rmSync(markerPath(userDataDir), { force: true });
    } catch (error) {
      result.failed.push({ name: RESET_PENDING_MARKER, error: errorMessage(error) });
    }
  }
  return result;
}

const PAGE_CLEAR_AND_COUNT = `(() => {
  try {
    localStorage.clear();
    sessionStorage.clear();
    return [localStorage.length, sessionStorage.length];
  } catch (e) {
    return [-1, -1];
  }
})()`;

function isRendererPage(contents) {
  try {
    return !contents.isDestroyed() && String(contents.getURL()).startsWith('file:');
  } catch {
    return false;
  }
}

// Clears what the running Chromium holds for the renderer and checks the pages
// really are empty. Resolves { ok, cleared, pagesChecked, pagesNotEmpty,
// errors }; ok is false if any step failed or any page still holds a key.
async function clearLiveRendererState({ session, webContents } = {}) {
  const cleared = [];
  const errors = [];
  const step = async (name, fn) => {
    try {
      await fn();
      cleared.push(name);
    } catch (error) {
      errors.push(`${name}: ${errorMessage(error)}`);
    }
  };

  if (!session) {
    return { ok: false, cleared, pagesChecked: 0, pagesNotEmpty: 0, errors: ['no session'] };
  }
  // Every storage type for every origin (localStorage, IndexedDB, caches
  // storage, service workers, cookies, ...). sessionStorage is NOT covered.
  await step('storage-data', () => session.clearStorageData());
  await step('http-cache', () => session.clearCache());
  if (typeof session.clearCodeCaches === 'function') {
    await step('code-cache', () => session.clearCodeCaches({}));
  }

  let pagesChecked = 0;
  let pagesNotEmpty = 0;
  const pages = webContents && typeof webContents.getAllWebContents === 'function'
    ? webContents.getAllWebContents()
    : [];
  for (const contents of pages) {
    if (!isRendererPage(contents)) continue;
    try {
      const counts = await contents.executeJavaScript(PAGE_CLEAR_AND_COUNT);
      pagesChecked += 1;
      if (!Array.isArray(counts) || counts.some((n) => n !== 0)) pagesNotEmpty += 1;
    } catch (error) {
      errors.push(`page-storage: ${errorMessage(error)}`);
    }
  }
  if (pagesNotEmpty > 0) errors.push(`page-storage: ${pagesNotEmpty} page(s) still hold stored keys`);
  cleared.push('page-storage');

  try {
    session.flushStorageData?.();
  } catch (error) {
    errors.push(`flush: ${errorMessage(error)}`);
  }
  return { ok: errors.length === 0, cleared, pagesChecked, pagesNotEmpty, errors };
}

// The full renderer-state half of a factory reset: live clear + deferred purge.
async function clearRendererState({ session, webContents, userDataDir, fsImpl = fs, now } = {}) {
  let live;
  try {
    live = await clearLiveRendererState({ session, webContents });
  } catch (error) {
    live = { ok: false, cleared: [], pagesChecked: 0, pagesNotEmpty: 0, errors: [errorMessage(error)] };
  }
  const scheduled = schedulePurge({ userDataDir, fsImpl, now });
  const errors = [...live.errors];
  if (!scheduled.ok) errors.push(`purge-marker: ${scheduled.error}`);
  return {
    ok: live.ok && scheduled.ok,
    cleared: live.cleared,
    pages_checked: live.pagesChecked,
    pages_not_empty: live.pagesNotEmpty,
    // On-disk Chromium files that cannot be deleted while Chromium runs: they
    // are removed at the next launch (see purgePendingReset).
    pending_until_restart: scheduled.ok ? pendingEntries({ userDataDir, fsImpl }) : [],
    purge_scheduled: scheduled.ok,
    errors,
  };
}

// True when the backend's response shows a reset that actually deleted things
// (it carries the `reset` report), as opposed to a refusal or a transport fault.
function deletionRan(result) {
  const body = result && result.body;
  return Boolean(body && typeof body === 'object' && body.reset && typeof body.reset === 'object');
}

// Folds the renderer-state outcome into the backend's factory-reset response
// WITHOUT ever making it look cleaner than it was.
//   - A response with no `reset` object means the backend refused or failed
//     before deleting anything (409/503 aborts, 400 wrong phrase, transport
//     fault): there is nothing to follow up, so it is returned untouched.
//   - If the renderer state could not be cleared, the reset is NOT ok and NOT
//     verified, whatever the backend said, and the message says why.
async function finishFactoryReset(result, deps = {}) {
  if (!deletionRan(result)) return result;
  const body = result.body;

  let rendererState;
  try {
    rendererState = await clearRendererState(deps);
  } catch (error) {
    rendererState = { ok: false, cleared: [], pending_until_restart: [], purge_scheduled: false, errors: [errorMessage(error)] };
  }
  if (rendererState.ok) {
    return { ...result, body: { ...body, renderer_state: rendererState } };
  }
  return {
    ...result,
    ok: false,
    status: result.status >= 400 ? result.status : 500,
    body: {
      ...body,
      ok: false,
      verified: false,
      renderer_state: rendererState,
      message: 'BetterFingers\' stored data was removed, but the app window\'s own stored state '
        + `(settings flags and the old first-run record) could not be cleared: ${rendererState.errors.join('; ')}. `
        + 'Restart BetterFingers and run the reset again. Nothing is being claimed that did not happen.',
    },
  };
}

module.exports = {
  RESET_PENDING_MARKER,
  CHROMIUM_STORAGE_ENTRIES,
  schedulePurge,
  pendingEntries,
  deletionRan,
  purgePendingReset,
  clearLiveRendererState,
  clearRendererState,
  finishFactoryReset,
};
