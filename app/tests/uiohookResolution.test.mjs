// uiohook-napi is a native (N-API) addon; app/package.json's asarUnpack
// ("**/node_modules/uiohook-napi/**") exists because native .node addons
// cannot dlopen from inside an asar archive — electron-builder physically
// copies matched files to a sibling app.asar.unpacked directory, and
// Electron's own require patch transparently redirects lookups there. This
// only works if the package resolves as a real dependency at all: these
// tests confirm resolution succeeds under plain node (the closest this
// sandbox can get to the packaged require path) and that a prebuilt binary
// exists for the current platform/arch, which a packaged Linux AppImage will
// need at runtime.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';

const require = createRequire(import.meta.url);

test('uiohook-napi resolves as a real dependency from app/', () => {
  const resolved = require.resolve('uiohook-napi');
  assert.ok(fs.existsSync(resolved), `resolved path does not exist: ${resolved}`);
});

test('uiohook-napi is a production dependency, not a devDependency', () => {
  // electron-builder only auto-includes node_modules for "dependencies" in
  // package.json when a custom `files` allowlist is set (as this project's
  // build block does) — a devDependency here would silently ship a build
  // with no uiohook-napi at all.
  const pkg = JSON.parse(fs.readFileSync(path.join(import.meta.dirname, '..', 'package.json'), 'utf8'));
  assert.ok(pkg.dependencies?.['uiohook-napi'], 'uiohook-napi must be a production dependency');
  assert.ok(!pkg.devDependencies?.['uiohook-napi'], 'uiohook-napi must not also be a devDependency');
});

test('a prebuilt binary exists for the current platform/arch', () => {
  const pkgDir = path.dirname(require.resolve('uiohook-napi/package.json'));
  const prebuildDir = path.join(pkgDir, 'prebuilds', `${process.platform}-${process.arch}`);
  assert.ok(
    fs.existsSync(path.join(prebuildDir, 'uiohook-napi.node')),
    `no prebuilt uiohook-napi.node under ${prebuildDir}`,
  );
});
