// Unit tests for the pure sender / navigation validation helpers.
// Run with: node --test app/tests/senderValidation.test.mjs
//
// senderValidation is Electron-free and derives the path flavour (win32 vs
// posix) from the URL itself, so all three OS forms can be exercised on Linux
// by passing the appropriate directory string + file:/// URL.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const {
  isTrustedFileUrl,
  isTrustedDevOrigin,
  isTrustedRendererUrl,
} = require('../src/main/senderValidation.js');

// --- file:// packaged pages ------------------------------------------------

test('accepts a valid packaged page (posix)', () => {
  const dir = '/opt/app/resources/app.asar/out/renderer';
  assert.equal(isTrustedFileUrl(`file://${dir}/index.html`, dir), true);
  assert.equal(isTrustedFileUrl(`file://${dir}/overlay.html`, dir), true);
  assert.equal(isTrustedFileUrl(`file://${dir}/review-overlay.html`, dir), true);
});

test('rejects a non-renderer page that still lives under the renderer dir', () => {
  const dir = '/opt/app/out/renderer';
  assert.equal(isTrustedFileUrl(`file://${dir}/evil.html`, dir), false);
  assert.equal(isTrustedFileUrl(`file://${dir}/preload.js`, dir), false);
});

test('rejects a page in a nested subdirectory of the renderer dir', () => {
  const dir = '/opt/app/out/renderer';
  assert.equal(isTrustedFileUrl(`file://${dir}/sub/index.html`, dir), false);
});

test('rejects a sibling directory with a shared string prefix', () => {
  // The old startsWith(appRoot) check wrongly accepted /a/app-evil for /a/app.
  const dir = '/a/app';
  assert.equal(isTrustedFileUrl('file:///a/app-evil/index.html', dir), false);
  // sanity: the real dir is still accepted
  assert.equal(isTrustedFileUrl('file:///a/app/index.html', dir), true);
});

test('rejects path traversal that escapes the renderer dir', () => {
  const dir = '/opt/app/out/renderer';
  const url = `file://${dir}/../../../../etc/index.html`;
  assert.equal(isTrustedFileUrl(url, dir), false);
});

test('handles directory names containing spaces (raw and %20 encoded)', () => {
  const dir = '/home/user/My Apps/BetterFingers/out/renderer';
  // A file:// URL must percent-encode spaces; both forms should resolve equal.
  const encoded = 'file:///home/user/My%20Apps/BetterFingers/out/renderer/index.html';
  assert.equal(isTrustedFileUrl(encoded, dir), true);
  // A stray non-renderer page in the spaced dir is still rejected.
  const encodedEvil = 'file:///home/user/My%20Apps/BetterFingers/out/renderer/evil.html';
  assert.equal(isTrustedFileUrl(encodedEvil, dir), false);
});

test('normalizes Windows drive-letter casing (c:\\ vs C:\\)', () => {
  const dir = 'C:\\Program Files\\BetterFingers\\resources\\app.asar\\out\\renderer';
  // Renderer served from a lower-case drive letter must still match.
  const url = 'file:///c:/Program%20Files/BetterFingers/resources/app.asar/out/renderer/index.html';
  assert.equal(isTrustedFileUrl(url, dir), true);
});

test('accepts Windows packaged page with matching drive casing', () => {
  const dir = 'C:\\Users\\me\\AppData\\Local\\BetterFingers\\out\\renderer';
  const url = 'file:///C:/Users/me/AppData/Local/BetterFingers/out/renderer/overlay.html';
  assert.equal(isTrustedFileUrl(url, dir), true);
});

test('rejects Windows sibling-prefix directory', () => {
  const dir = 'C:\\a\\app';
  assert.equal(isTrustedFileUrl('file:///C:/a/app-evil/index.html', dir), false);
});

test('rejects a macOS bundle sibling with a shared prefix', () => {
  const dir = '/Applications/BetterFingers.app/Contents/Resources/app.asar/out/renderer';
  assert.equal(isTrustedFileUrl(`file://${dir}/index.html`, dir), true);
  const evil = '/Applications/BetterFingers.app-evil/Contents/Resources/app.asar/out/renderer';
  assert.equal(isTrustedFileUrl(`file://${evil}/index.html`, dir), false);
});

test('rejects non-file protocols and malformed input', () => {
  const dir = '/opt/app/out/renderer';
  assert.equal(isTrustedFileUrl('http://example.com/index.html', dir), false);
  assert.equal(isTrustedFileUrl('', dir), false);
  assert.equal(isTrustedFileUrl(null, dir), false);
  assert.equal(isTrustedFileUrl(undefined, dir), false);
  assert.equal(isTrustedFileUrl(`file://${dir}/index.html`, ''), false);
  assert.equal(isTrustedFileUrl('not a url', dir), false);
});

// --- dev-server origin -----------------------------------------------------

test('accepts the exact dev-server origin', () => {
  const dev = 'http://localhost:5173';
  assert.equal(isTrustedDevOrigin('http://localhost:5173/index.html', dev), true);
  assert.equal(isTrustedDevOrigin('http://localhost:5173/overlay.html?x=1', dev), true);
  // Trailing slash on the configured origin does not change the origin.
  assert.equal(isTrustedDevOrigin('http://localhost:5173/', 'http://localhost:5173'), true);
});

test('rejects a lookalike dev origin', () => {
  const dev = 'http://localhost:5173';
  assert.equal(isTrustedDevOrigin('http://localhost:5173.evil.example/index.html', dev), false);
  assert.equal(isTrustedDevOrigin('http://localhost:51730/index.html', dev), false);
  assert.equal(isTrustedDevOrigin('https://localhost:5173/index.html', dev), false);
  assert.equal(isTrustedDevOrigin('http://evil.example/localhost:5173', dev), false);
});

test('rejects dev origin checks when no dev origin is configured', () => {
  assert.equal(isTrustedDevOrigin('http://localhost:5173/index.html', ''), false);
  assert.equal(isTrustedDevOrigin('http://localhost:5173/index.html', undefined), false);
});

// --- combined helper -------------------------------------------------------

test('isTrustedRendererUrl accepts packaged page or exact dev origin', () => {
  const dir = '/opt/app/out/renderer';
  const devOrigin = 'http://localhost:5173';
  assert.equal(
    isTrustedRendererUrl(`file://${dir}/index.html`, { rendererDir: dir, devOrigin }),
    true,
  );
  assert.equal(
    isTrustedRendererUrl('http://localhost:5173/overlay.html', { rendererDir: dir, devOrigin }),
    true,
  );
  assert.equal(
    isTrustedRendererUrl('http://localhost:5173.evil.example/', { rendererDir: dir, devOrigin }),
    false,
  );
  assert.equal(
    isTrustedRendererUrl(`file://${dir}/evil.html`, { rendererDir: dir, devOrigin }),
    false,
  );
  // No options: nothing is trusted.
  assert.equal(isTrustedRendererUrl(`file://${dir}/index.html`), false);
});
