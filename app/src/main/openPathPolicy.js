// What `shell:open-path` may hand to the operating system (Phase 0 item 8).
//
// shell.openPath() does not "show" a file, it LAUNCHES it with whatever the OS
// associates with it: on Windows that is an .exe, .bat, .cmd, .lnk, .hta, .js or
// .vbs running with the user's rights; on Linux an executable .desktop or script
// can do the same. Downloads and the app's own data folder are exactly where an
// attacker-supplied file would land, so "inside an allowed root" is not enough.
// This sits next to the workflow gate's "no shell, ever" rule (D-0011) and has to
// hold to the same standard.
//
// The policy: the target must exist and, after symlinks are resolved, sit inside
// an allowed root; then it is either
//   * a directory (opens the file manager, runs nothing), or
//   * a regular file whose RESOLVED name ends in an allowlisted document
//     extension. The allowlist is closed: anything not on it, including every
//     executable, script, shortcut and installer type, is refused.
// Pure apart from the injected fs, so it is tested with real temp directories.

const fs = require('node:fs');
const path = require('node:path');

// Documents and media main itself exports or a person would expect to open.
const OPENABLE_EXTENSIONS = new Set([
  '.html', '.htm', '.txt', '.md', '.json', '.csv', '.log',
  '.zip', '.wav', '.mp3', '.png', '.jpg', '.jpeg',
]);

const MAX_PATH_LEN = 4096;

function isInside(root, target, pathImpl) {
  return target === root || target.startsWith(root + pathImpl.sep);
}

function evaluateOpenTarget(targetPath, { roots = [], fsImpl = fs, platform = process.platform } = {}) {
  const pathImpl = platform === 'win32' ? path.win32 : path.posix;
  if (typeof targetPath !== 'string' || !targetPath || targetPath.length > MAX_PATH_LEN) {
    return { ok: false, reason: 'No path provided' };
  }
  if (targetPath.includes('\0')) return { ok: false, reason: 'Invalid path' };

  let resolved;
  try {
    resolved = fsImpl.realpathSync(pathImpl.resolve(targetPath)); // must exist
  } catch {
    return { ok: false, reason: 'Path does not exist' };
  }
  const normalizedRoots = roots.map((root) => pathImpl.resolve(String(root)));
  if (!normalizedRoots.some((root) => isInside(root, resolved, pathImpl))) {
    return { ok: false, reason: 'Path is outside the allowed export locations.' };
  }

  let stat;
  try {
    stat = fsImpl.statSync(resolved);
  } catch {
    return { ok: false, reason: 'Path does not exist' };
  }
  if (stat.isDirectory()) return { ok: true, kind: 'folder', resolved };
  if (!stat.isFile()) return { ok: false, reason: 'Only folders and ordinary files can be opened.' };

  const base = pathImpl.basename(resolved);
  // Windows quirks that make "name.txt" mean something else: alternate data
  // streams ("a.txt:evil.exe") and trailing dots/spaces that the OS strips.
  if (platform === 'win32' && (base.includes(':') || /[. ]$/.test(base))) {
    return { ok: false, reason: 'That file name is not allowed.' };
  }
  const extension = pathImpl.extname(base).toLowerCase();
  if (!OPENABLE_EXTENSIONS.has(extension)) {
    return { ok: false, reason: 'BetterFingers will not open that kind of file. Use "Show in folder" instead.' };
  }
  return { ok: true, kind: 'document', resolved };
}

module.exports = { OPENABLE_EXTENSIONS, evaluateOpenTarget };
