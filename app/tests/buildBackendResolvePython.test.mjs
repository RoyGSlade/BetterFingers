// CONFIRMED DEFECT: resolvePython() used to return a bare `python3`/`python`
// whenever BETTERFINGERS_PYTHON was unset. This repo's runtime dependencies
// (fastapi, PyInstaller, etc.) live only in the repo-local .venv, so that bare
// interpreter lacks them — the release board recorded 72 dependency
// collection errors from exactly this. resolvePython() must now prefer, in
// order: BETTERFINGERS_PYTHON, the repo-local venv interpreter, then the
// platform default.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

import { repoRoot, repoVenvPython, resolvePython, verifyPythonEnvironment } from '../scripts/build-backend.js';

function withEnv(key, value, fn) {
  const previous = process.env[key];
  if (value === undefined) {
    delete process.env[key];
  } else {
    process.env[key] = value;
  }
  try {
    return fn();
  } finally {
    if (previous === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = previous;
    }
  }
}

test('BETTERFINGERS_PYTHON override always wins', () => {
  withEnv('BETTERFINGERS_PYTHON', '/some/explicit/python', () => {
    assert.equal(resolvePython(), '/some/explicit/python');
  });
});

test('repoVenvPython() points at the repo-local venv interpreter', () => {
  const expected = process.platform === 'win32'
    ? path.join(repoRoot, '.venv', 'Scripts', 'python.exe')
    : path.join(repoRoot, '.venv', 'bin', 'python');
  assert.equal(repoVenvPython(), fs.existsSync(expected) ? expected : null);
});

test('resolvePython() prefers the repo venv over the platform default when no override is set', () => {
  withEnv('BETTERFINGERS_PYTHON', undefined, () => {
    const venvPython = repoVenvPython();
    // This repo ships a .venv (release board: PyInstaller lives there) — if a
    // future environment genuinely lacks one, this documents the fallback
    // instead of silently asserting the wrong thing.
    if (venvPython) {
      assert.equal(resolvePython(), venvPython);
    } else {
      const platformDefault = process.platform === 'win32' ? 'python' : 'python3';
      assert.equal(resolvePython(), platformDefault);
    }
  });
});

test('verifyPythonEnvironment() passes for the repo venv (has PyInstaller + fastapi)', async (t) => {
  const venvPython = repoVenvPython();
  if (!venvPython) {
    t.skip('no repo-local .venv on this machine');
    return;
  }
  await assert.doesNotReject(() => verifyPythonEnvironment(venvPython));
});

test('verifyPythonEnvironment() fails fast with a clear message for an interpreter missing deps', async () => {
  // `python3` bare (no venv) is exactly the pre-fix behavior this defect was
  // about: it exists on this box but lacks fastapi/PyInstaller.
  await assert.rejects(
    () => verifyPythonEnvironment('python3'),
    (err) => err.message.includes('python3') && /BETTERFINGERS_PYTHON/.test(err.message),
  );
});
