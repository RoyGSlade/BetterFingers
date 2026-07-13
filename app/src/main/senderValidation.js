const path = require('node:path');
const url = require('node:url');

// --- Pure sender / navigation validation -----------------------------------
// These helpers decide whether a URL belongs to one of our own renderer pages.
// They are deliberately free of any Electron dependency so the privilege
// boundary can be unit-tested without launching a browser window. ipc.js and
// windows.js pass in the concrete renderer directory / dev origin at call time.

// The exact set of pages the app ships. A sender frame that has navigated to
// anything else — even another file under the same directory — is untrusted.
const RENDERER_PAGES = new Set(['index.html', 'overlay.html', 'review-overlay.html']);

// A file URL is Windows-flavoured when its pathname starts with a drive letter
// (e.g. file:///C:/... -> "/C:/..."). Detecting the flavour from the URL lets
// us pick the matching path implementation (path.win32 vs path.posix) and
// interpret fileURLToPath consistently on any host OS — which is what makes the
// Windows cases testable on Linux.
function isWindowsFileUrl(parsed) {
  const stripped = parsed.pathname.replace(/^\//, '');
  return /^[a-zA-Z]:/.test(stripped);
}

// Uppercase a leading drive letter so "c:\\..." and "C:\\..." compare equal.
// path.win32.relative already treats the drive case-insensitively, but we
// normalize the caller-supplied directory too so nothing downstream is
// surprised by mixed casing.
function normalizeDriveLetter(p) {
  if (/^[a-zA-Z]:/.test(p)) {
    return p[0].toUpperCase() + p.slice(1);
  }
  return p;
}

// True only when `fileUrl` names one of RENDERER_PAGES sitting directly inside
// `rendererDir`. Uses fileURLToPath (handles %20 / spaces / encoded chars) and
// path.relative for containment, so sibling directories with a shared string
// prefix (/a/app vs /a/app-evil) and "../" traversal are both rejected.
function isTrustedFileUrl(fileUrl, rendererDir) {
  if (typeof fileUrl !== 'string' || !fileUrl || !rendererDir) {
    return false;
  }

  let parsed;
  try {
    parsed = new URL(fileUrl);
  } catch {
    return false;
  }
  if (parsed.protocol !== 'file:') {
    return false;
  }

  const windows = isWindowsFileUrl(parsed);
  const pathImpl = windows ? path.win32 : path.posix;

  let filePath;
  try {
    filePath = url.fileURLToPath(fileUrl, { windows });
  } catch {
    return false;
  }

  const normalizedDir = normalizeDriveLetter(pathImpl.normalize(rendererDir));
  const normalizedFile = normalizeDriveLetter(pathImpl.normalize(filePath));

  const rel = pathImpl.relative(normalizedDir, normalizedFile);
  // Reject anything that escapes the directory ("..") or is not contained in it
  // (an absolute relative path means the two live on different roots/drives).
  if (!rel || rel.startsWith('..') || pathImpl.isAbsolute(rel)) {
    return false;
  }
  // The page must sit *directly* in the renderer directory: a single path
  // segment, not a nested subdirectory.
  if (rel.split(pathImpl.sep).length !== 1) {
    return false;
  }
  return RENDERER_PAGES.has(rel);
}

// True only when `candidateUrl` shares an exact origin with the dev server.
// Compares parsed origins rather than string prefixes, so lookalikes such as
// http://localhost:5173.evil.example are rejected.
function isTrustedDevOrigin(candidateUrl, devOrigin) {
  if (typeof candidateUrl !== 'string' || !candidateUrl || !devOrigin) {
    return false;
  }
  let candidateOrigin;
  let expectedOrigin;
  try {
    candidateOrigin = new URL(candidateUrl).origin;
    expectedOrigin = new URL(devOrigin).origin;
  } catch {
    return false;
  }
  // URL.origin is "null" (a string) for opaque origins; never trust those.
  if (candidateOrigin === 'null' || expectedOrigin === 'null') {
    return false;
  }
  return candidateOrigin === expectedOrigin;
}

// Convenience: a URL is trusted if it is one of our packaged pages OR served by
// the exact dev-server origin. Callers pass the concrete rendererDir/devOrigin.
function isTrustedRendererUrl(candidateUrl, { rendererDir, devOrigin } = {}) {
  if (rendererDir && isTrustedFileUrl(candidateUrl, rendererDir)) {
    return true;
  }
  if (devOrigin && isTrustedDevOrigin(candidateUrl, devOrigin)) {
    return true;
  }
  return false;
}

module.exports = {
  RENDERER_PAGES,
  isTrustedFileUrl,
  isTrustedDevOrigin,
  isTrustedRendererUrl,
};
