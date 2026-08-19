'use strict';

const STATUSES = Object.freeze([
  'unsupported', 'idle', 'checking', 'up_to_date', 'available',
  'downloading', 'ready', 'installing', 'error',
]);
const ALLOWED_CHECK = new Set(['idle', 'up_to_date', 'error']);
const ACTIVE_STATUSES = new Set([
  'recording_started', 'recording', 'transcribing', 'rewriting', 'processing',
  'long_recording_detected', 'chunking_started', 'chunking_progress', 'chunking_stitching',
]);

function finiteNonnegative(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : 0;
}

function decodeEntities(text) {
  const named = { amp: '&', apos: "'", gt: '>', lt: '<', nbsp: ' ', quot: '"' };
  return text.replace(/&(#x[0-9a-f]+|#\d+|amp|apos|gt|lt|nbsp|quot);/gi, (match, entity) => {
    const lower = entity.toLowerCase();
    if (Object.hasOwn(named, lower)) return named[lower];
    const radix = lower.startsWith('#x') ? 16 : 10;
    const digits = lower.replace(/^#x?/, '');
    const codePoint = Number.parseInt(digits, radix);
    if (!Number.isFinite(codePoint) || codePoint < 0 || codePoint > 0x10ffff) return '';
    try { return String.fromCodePoint(codePoint); } catch { return ''; }
  });
}

function safeNotes(notes) {
  const parts = Array.isArray(notes) ? notes : [notes];
  const combined = parts.map((part) => {
    if (part && typeof part === 'object') return part.note || part.body || part.releaseNotes || '';
    return part || '';
  }).join('\n');
  return decodeEntities(String(combined))
    .replace(/<script\b[^>]*>[\s\S]*?<\/script\s*>/gi, '')
    .replace(/<style\b[^>]*>[\s\S]*?<\/style\s*>/gi, '')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p\s*>/gi, '\n')
    .replace(/<[^>]*>/g, '')
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '')
    .replace(/\r\n?/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
    .slice(0, 12000);
}

function safeError(error) {
  const raw = `${error?.code || ''} ${error?.name || ''} ${error?.message || ''}`.toLowerCase();
  if (/enospc|disk.?full|not enough space|insufficient space/.test(raw)) return 'INSUFFICIENT_DISK';
  if (/signature|publisher|authenticode|not signed|code.?sign/.test(raw)) return 'INVALID_SIGNER';
  if (/checksum|sha(?:256|512)|hash mismatch|integrity/.test(raw)) return 'HASH_MISMATCH';
  if (/ya?ml|metadata|invalid update|parse/.test(raw)) return 'INVALID_METADATA';
  if (/enet|eai_again|econn|etimedout|timeout|offline|network|http/.test(raw)) return 'NETWORK_UNAVAILABLE';
  if (/cancel/.test(raw)) return 'DOWNLOAD_INTERRUPTED';
  return 'UPDATE_FAILED';
}

function parseSemver(value) {
  const match = String(value || '').trim().match(/^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/);
  if (!match) return null;
  return { core: match.slice(1, 4).map(Number), prerelease: match[4] ? match[4].split('.') : [] };
}

function compareSemver(leftValue, rightValue) {
  const left = parseSemver(leftValue);
  const right = parseSemver(rightValue);
  if (!left || !right) return null;
  for (let index = 0; index < 3; index += 1) {
    if (left.core[index] !== right.core[index]) return left.core[index] > right.core[index] ? 1 : -1;
  }
  if (!left.prerelease.length || !right.prerelease.length) {
    if (left.prerelease.length === right.prerelease.length) return 0;
    return left.prerelease.length ? -1 : 1;
  }
  const length = Math.max(left.prerelease.length, right.prerelease.length);
  for (let index = 0; index < length; index += 1) {
    const leftPart = left.prerelease[index];
    const rightPart = right.prerelease[index];
    if (leftPart === undefined) return -1;
    if (rightPart === undefined) return 1;
    if (leftPart === rightPart) continue;
    const leftNumeric = /^\d+$/.test(leftPart);
    const rightNumeric = /^\d+$/.test(rightPart);
    if (leftNumeric && rightNumeric) return Number(leftPart) > Number(rightPart) ? 1 : -1;
    if (leftNumeric !== rightNumeric) return leftNumeric ? -1 : 1;
    return leftPart > rightPart ? 1 : -1;
  }
  return 0;
}

function isPrerelease(version) {
  return Boolean(parseSemver(version)?.prerelease.length);
}

function createUpdateController(options = {}) {
  const app = options.app || {};
  const updater = options.updater;
  const isPackaged = options.isPackaged !== undefined ? options.isPackaged : Boolean(app.isPackaged);
  const platform = options.platform || process.platform;
  const currentVersion = String(options.currentVersion || app.getVersion?.() || '');
  const supported = platform === 'win32' && isPackaged && Boolean(updater);
  const alpha = isPrerelease(currentVersion);
  const channel = alpha ? 'alpha' : 'latest';
  const listeners = new Set();
  let bound = false;
  let installPending = false;
  let installStarted = false;
  let state = {
    status: supported ? 'idle' : 'unsupported', currentVersion,
    availableVersion: null, channel: supported ? channel : null,
    releaseDate: null, releaseNotes: '', percent: 0, bytesTransferred: 0,
    bytesTotal: 0, errorCode: null,
  };

  function snapshot() { return Object.freeze({ ...state }); }
  function emit() {
    const value = snapshot();
    for (const listener of listeners) {
      try { listener(value); } catch {}
    }
    return value;
  }
  function set(next) { state = { ...state, ...next }; return emit(); }

  function activityBusy() {
    try {
      const activity = typeof options.activityGuard === 'function' ? options.activityGuard() : options.activityGuard;
      if (typeof activity === 'boolean') return activity;
      const status = typeof activity === 'string' ? activity : activity?.status;
      return Boolean(activity?.recording || activity?.processing || ACTIVE_STATUSES.has(String(status || '').toLowerCase()));
    } catch { return true; }
  }

  async function authoritativeActivity() {
    if (typeof options.authoritativeActivityGuard !== 'function') {
      return { known: false, busy: true };
    }
    try {
      const activity = await options.authoritativeActivityGuard();
      if (
        !activity
        || typeof activity.recording !== 'boolean'
        || typeof activity.processing !== 'boolean'
      ) {
        return { known: false, busy: true };
      }
      return { known: true, busy: activity.recording || activity.processing };
    } catch {
      return { known: false, busy: true };
    }
  }

  function setUpToDate() {
    return set({
      status: 'up_to_date', availableVersion: null, releaseDate: null,
      releaseNotes: '', percent: 0, bytesTransferred: 0, bytesTotal: 0, errorCode: null,
    });
  }

  function onUpdateAvailable(info) {
    if (['downloading', 'ready', 'installing'].includes(state.status)) return snapshot();
    const availableVersion = String(info?.version || '');
    const comparison = compareSemver(availableVersion, currentVersion);
    if (comparison === null) return set({ status: 'error', errorCode: 'INVALID_METADATA' });
    if (comparison <= 0) return setUpToDate();
    const advertisedSize = Math.max(
      finiteNonnegative(info?.size),
      ...((Array.isArray(info?.files) ? info.files : []).map((file) => finiteNonnegative(file?.size))),
    );
    return set({
      status: 'available', availableVersion,
      releaseDate: info?.releaseDate ? String(info.releaseDate).slice(0, 64) : null,
      releaseNotes: safeNotes(info?.releaseNotes), percent: 0,
      bytesTransferred: 0, bytesTotal: advertisedSize, errorCode: null,
    });
  }

  function configure() {
    if (!supported || bound) return;
    updater.autoDownload = false;
    updater.autoInstallOnAppQuit = false;
    updater.allowDowngrade = false;
    updater.channel = channel;
    updater.allowPrerelease = alpha;
    const markChecking = () => {
      if (ALLOWED_CHECK.has(state.status) || state.status === 'checking') set({ status: 'checking', errorCode: null });
    };
    updater.on?.('checking-for-update', markChecking);
    updater.on?.('checking', markChecking);
    updater.on?.('update-not-available', () => {
      if (state.status === 'checking') setUpToDate();
    });
    updater.on?.('update-available', onUpdateAvailable);
    updater.on?.('download-progress', (info) => {
      if (state.status !== 'downloading') return;
      const transferred = Math.max(state.bytesTransferred, finiteNonnegative(info?.transferred));
      const total = Math.max(state.bytesTotal, finiteNonnegative(info?.total), transferred);
      const percent = Math.max(state.percent, Math.min(100, finiteNonnegative(info?.percent)));
      set({ percent, bytesTransferred: transferred, bytesTotal: total, errorCode: null });
    });
    updater.on?.('update-downloaded', (info) => {
      if (state.status !== 'downloading' && state.status !== 'available') return;
      const transferred = Math.max(state.bytesTransferred, finiteNonnegative(info?.transferred));
      const total = Math.max(state.bytesTotal, finiteNonnegative(info?.total), transferred);
      set({
        status: 'ready', availableVersion: String(info?.version || state.availableVersion || ''),
        percent: 100, bytesTransferred: total || transferred, bytesTotal: total,
        errorCode: activityBusy() ? 'ACTIVE_DICTATION' : null,
      });
    });
    updater.on?.('error', (error) => {
      if (state.status !== 'installing') set({ status: 'error', errorCode: safeError(error) });
    });
    bound = true;
  }

  async function check() {
    if (!supported || !ALLOWED_CHECK.has(state.status)) return snapshot();
    configure();
    set({ status: 'checking', errorCode: null });
    try { await updater.checkForUpdates(); return snapshot(); }
    catch (error) { return set({ status: 'error', errorCode: safeError(error) }); }
  }

  async function download() {
    if (!supported || state.status !== 'available') return snapshot();
    configure();
    set({ status: 'downloading', percent: 0, bytesTransferred: 0, bytesTotal: 0, errorCode: null });
    try { await updater.downloadUpdate(); return snapshot(); }
    catch (error) { return set({ status: 'error', errorCode: safeError(error) }); }
  }

  function refreshInstallEligibility() {
    if (state.status !== 'ready') return snapshot();
    // A renderer activity hint cannot clear a failed authoritative backend
    // check. Only another install attempt can replace this error after it
    // successfully reaches /runtime/status.
    if (state.errorCode === 'RUNTIME_STATUS_UNAVAILABLE') return snapshot();
    const nextCode = activityBusy() ? 'ACTIVE_DICTATION' : null;
    return nextCode === state.errorCode ? snapshot() : set({ errorCode: nextCode });
  }

  async function install() {
    if (!supported || state.status !== 'ready' || installPending || installStarted) return snapshot();
    // Acquire the single-flight lock before the first await. Without this,
    // concurrent IPC calls can both pass the initial state check and each call
    // quitAndInstall after the authoritative backend request resolves.
    installPending = true;
    const activity = await authoritativeActivity();
    if (state.status !== 'ready') {
      installPending = false;
      return snapshot();
    }
    if (!activity.known) {
      installPending = false;
      return set({ errorCode: 'RUNTIME_STATUS_UNAVAILABLE' });
    }
    if (activity.busy) {
      installPending = false;
      return set({ errorCode: 'ACTIVE_DICTATION' });
    }
    installStarted = true;
    installPending = false;
    set({ status: 'installing', errorCode: null });
    try {
      await options.prepareQuit?.();
      updater.quitAndInstall?.();
      return snapshot();
    } catch (error) {
      installStarted = false;
      try { await options.recoverFromFailedInstall?.(); } catch {}
      return set({ status: 'error', errorCode: safeError(error) });
    }
  }

  configure();
  return Object.freeze({
    getState: snapshot,
    subscribe(listener) {
      if (typeof listener !== 'function') return () => {};
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    check, download, install, configure, refreshInstallEligibility,
    isSupported: () => supported, statuses: STATUSES,
  });
}

module.exports = { ACTIVE_STATUSES, STATUSES, compareSemver, createUpdateController, safeError, safeNotes };
