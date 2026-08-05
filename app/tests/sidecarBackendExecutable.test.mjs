// resolveBackendExecutable() locates the PyInstaller --onefile artifact
// build-backend.js produces (see app/scripts/build-backend.js: --name
// betterfingers-backend). These tests pin two defects found by reading it:
// the preferred-name hit never checked the executable bit (a +x-stripped
// artifact failed at spawn with a confusing EACCES instead of a clear
// message), and the fallback scan would happily return the first arbitrary
// non-dot file (a README, a data file) and spawn it.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { resolveBackendExecutable, DEV_HEALTH_TIMEOUT_MS, PACKAGED_HEALTH_TIMEOUT_MS } from '../src/main/sidecar.js';

function tempResourcesDir(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bf-resources-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

function withResourcesPath(resourcesPath, fn) {
  const previous = process.resourcesPath;
  process.resourcesPath = resourcesPath;
  try {
    return fn();
  } finally {
    process.resourcesPath = previous;
  }
}

test('resolves the preferred executable name when it is executable', (t) => {
  const resourcesPath = tempResourcesDir(t);
  const backendDir = path.join(resourcesPath, 'backend');
  fs.mkdirSync(backendDir, { recursive: true });
  const exePath = path.join(backendDir, 'betterfingers-backend');
  fs.writeFileSync(exePath, '#!/bin/sh\necho hi\n', { mode: 0o755 });

  withResourcesPath(resourcesPath, () => {
    assert.equal(resolveBackendExecutable(), exePath);
  });
});

test('throws a precise error when the preferred name exists but is not executable', (t) => {
  if (process.platform === 'win32') {
    t.skip('Windows executable qualification is based on file existence, not POSIX mode bits');
    return;
  }
  const resourcesPath = tempResourcesDir(t);
  const backendDir = path.join(resourcesPath, 'backend');
  fs.mkdirSync(backendDir, { recursive: true });
  const exePath = path.join(backendDir, 'betterfingers-backend');
  fs.writeFileSync(exePath, 'not actually executable', { mode: 0o644 });

  withResourcesPath(resourcesPath, () => {
    assert.throws(
      () => resolveBackendExecutable(),
      (err) => err.message.includes(exePath) && /not marked executable/.test(err.message),
    );
  });
});

test('fallback scan skips non-executable files and does not return an arbitrary data file', (t) => {
  const resourcesPath = tempResourcesDir(t);
  const backendDir = path.join(resourcesPath, 'backend');
  fs.mkdirSync(backendDir, { recursive: true });
  // No preferred name present — only a README (non-executable) and the
  // real, differently-named, executable artifact.
  fs.writeFileSync(path.join(backendDir, 'README.txt'), 'not a binary', { mode: 0o644 });
  const realExe = path.join(backendDir, 'betterfingers-backend-linux-x64');
  fs.writeFileSync(realExe, '#!/bin/sh\necho hi\n', { mode: 0o755 });

  withResourcesPath(resourcesPath, () => {
    assert.equal(resolveBackendExecutable(), realExe);
  });
});

test('fallback scan throws rather than returning a non-executable file when nothing is executable', (t) => {
  if (process.platform === 'win32') {
    t.skip('Windows executable qualification is based on file existence, not POSIX mode bits');
    return;
  }
  const resourcesPath = tempResourcesDir(t);
  const backendDir = path.join(resourcesPath, 'backend');
  fs.mkdirSync(backendDir, { recursive: true });
  fs.writeFileSync(path.join(backendDir, 'README.txt'), 'not a binary', { mode: 0o644 });

  withResourcesPath(resourcesPath, () => {
    assert.throws(
      () => resolveBackendExecutable(),
      /No executable backend found/,
    );
  });
});

test('throws naming the exact searched path when the backend directory is missing', (t) => {
  const resourcesPath = tempResourcesDir(t);

  withResourcesPath(resourcesPath, () => {
    const backendDir = path.join(resourcesPath, 'backend');
    assert.throws(
      () => resolveBackendExecutable(),
      (err) => err.message.includes(backendDir),
    );
  });
});

test('the packaged health timeout budget is larger than the dev budget', () => {
  // A PyInstaller --onefile sidecar self-extracts before Python even starts;
  // a cold, RAM-constrained, CPU-only packaged boot needs more room than a
  // dev boot of an already-resident python process.
  assert.ok(PACKAGED_HEALTH_TIMEOUT_MS > DEV_HEALTH_TIMEOUT_MS);
});
