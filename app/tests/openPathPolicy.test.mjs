// Phase 0 item 8: shell:open-path must never hand an executable to the OS.
// Run with: node --test app/tests/openPathPolicy.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { evaluateOpenTarget, OPENABLE_EXTENSIONS } = require('../src/main/openPathPolicy.js');

function sandbox(t) {
  const base = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'bf-open-')));
  t.after(() => fs.rmSync(base, { recursive: true, force: true }));
  const downloads = path.join(base, 'Downloads');
  const outside = path.join(base, 'elsewhere');
  fs.mkdirSync(downloads);
  fs.mkdirSync(outside);
  return { base, downloads, outside, roots: [downloads] };
}

test('a directory under an allowed root opens (it runs nothing)', (t) => {
  const { downloads, roots } = sandbox(t);
  const folder = path.join(downloads, 'exports');
  fs.mkdirSync(folder);
  const verdict = evaluateOpenTarget(folder, { roots });
  assert.equal(verdict.ok, true);
  assert.equal(verdict.kind, 'folder');
  assert.equal(evaluateOpenTarget(downloads, { roots }).ok, true, 'the root itself');
});

test('allowlisted document types open', (t) => {
  const { downloads, roots } = sandbox(t);
  for (const extension of ['.html', '.TXT', '.zip', '.json', '.wav']) {
    const file = path.join(downloads, `reel${extension}`);
    fs.writeFileSync(file, 'x');
    const verdict = evaluateOpenTarget(file, { roots });
    assert.equal(verdict.ok, true, extension);
    assert.equal(verdict.kind, 'document');
  }
});

test('executables, scripts, shortcuts and installers in Downloads are refused', (t) => {
  const { downloads, roots } = sandbox(t);
  const names = [
    'setup.exe', 'run.bat', 'run.cmd', 'x.lnk', 'x.hta', 'x.js', 'x.vbs', 'x.ps1', 'x.msi', 'x.scr',
    'x.com', 'x.jar', 'x.sh', 'x.desktop', 'x.AppImage', 'x.deb', 'x.py', 'x.reg', 'x.dll', 'noextension',
    'report.txt.exe', 'archive.zip.lnk',
  ];
  for (const name of names) {
    const file = path.join(downloads, name);
    fs.writeFileSync(file, 'x', { mode: 0o755 });
    const verdict = evaluateOpenTarget(file, { roots });
    assert.equal(verdict.ok, false, `${name} must be refused`);
    assert.match(verdict.reason, /will not open that kind of file/);
  }
});

test('the extension is judged on the symlink TARGET, not the link name', (t) => {
  const { downloads, roots } = sandbox(t);
  const exe = path.join(downloads, 'payload.exe');
  fs.writeFileSync(exe, 'x');
  const link = path.join(downloads, 'innocent.txt');
  try {
    fs.symlinkSync(exe, link);
  } catch {
    t.skip('symlinks unavailable');
    return;
  }
  assert.equal(evaluateOpenTarget(link, { roots }).ok, false);
});

test('a symlink out of the allowed root, a traversal path and a missing path are refused', (t) => {
  const { downloads, outside, roots } = sandbox(t);
  const secret = path.join(outside, 'notes.txt');
  fs.writeFileSync(secret, 'x');
  assert.equal(evaluateOpenTarget(secret, { roots }).ok, false, 'outside the root');
  assert.equal(evaluateOpenTarget(path.join(downloads, '..', 'elsewhere', 'notes.txt'), { roots }).ok, false, 'traversal');
  assert.equal(evaluateOpenTarget(path.join(downloads, 'missing.txt'), { roots }).ok, false, 'missing');
  try {
    fs.symlinkSync(secret, path.join(downloads, 'escape.txt'));
    assert.equal(evaluateOpenTarget(path.join(downloads, 'escape.txt'), { roots }).ok, false, 'symlink escape');
  } catch { /* symlinks unavailable */ }
});

test('non-string, empty, oversized and NUL-containing paths are refused', (t) => {
  const { roots } = sandbox(t);
  for (const bad of [undefined, null, 42, {}, '', 'a'.repeat(5000), 'a\0b']) {
    assert.equal(evaluateOpenTarget(bad, { roots }).ok, false);
  }
});

test('Windows-only tricks: alternate data streams and trailing dots/spaces are refused', () => {
  const winRoot = 'C:\\Users\\u\\Downloads';
  const fakeFs = {
    realpathSync: (p) => p,
    statSync: () => ({ isDirectory: () => false, isFile: () => true }),
  };
  const options = { roots: [winRoot], fsImpl: fakeFs, platform: 'win32' };
  assert.equal(evaluateOpenTarget(`${winRoot}\\notes.txt`, options).ok, true);
  assert.equal(evaluateOpenTarget(`${winRoot}\\notes.txt:evil.exe`, options).ok, false);
  assert.equal(evaluateOpenTarget(`${winRoot}\\notes.txt.`, options).ok, false);
  assert.equal(evaluateOpenTarget(`${winRoot}\\notes.txt `, options).ok, false);
  assert.equal(evaluateOpenTarget(`${winRoot}\\setup.EXE`, options).ok, false);
  assert.equal(evaluateOpenTarget('C:\\Windows\\notepad.txt', options).ok, false, 'outside the root');
});

test('the allowlist contains no executable-capable extension', () => {
  for (const dangerous of ['.exe', '.bat', '.cmd', '.com', '.lnk', '.hta', '.js', '.vbs', '.ps1', '.msi', '.scr', '.jar', '.sh', '.desktop', '.appimage', '.reg', '.dll', '.svg']) {
    assert.ok(!OPENABLE_EXTENSIONS.has(dangerous), dangerous);
  }
});
