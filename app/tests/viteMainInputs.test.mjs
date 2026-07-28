// The Wave 1 lesson, encoded so it cannot be relearned.
//
// A main-process module that is required at runtime but missing from
// electron.vite.config.js's `main.build.rollupOptions.input` is NOT a build
// error. The build succeeds, the bundle is short one module, and the app starts
// with no window at all — a failure with no error message, discovered by
// launching the app and seeing nothing. Wave 1 shipped exactly that defect and
// the integration pass caught it; nothing in the repo stopped it happening
// again until this file.
//
// The rule asserted here is the accurate one rather than the blunt one: every
// module in the REQUIRE CLOSURE of src/main/main.js must be an input. Walking
// the closure rather than the directory listing matters in both directions — it
// catches a module that main.js reaches through two hops, and it does not
// falsely accuse a file like redact.js that no main-process module requires at
// all (it is exercised only by tests and by QA scenarios, so it is not part of
// what the main bundle has to contain).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = path.resolve(HERE, '..');
const MAIN_DIR = path.join(APP, 'src', 'main');
const require = createRequire(import.meta.url);

function mainInputs() {
  const config = require(path.join(APP, 'electron.vite.config.js'));
  const resolved = typeof config === 'function' ? config({}) : config;
  const inputs = (resolved.main || {}).build.rollupOptions.input;
  return Object.values(inputs).map((file) => path.resolve(file));
}

/** Relative require()/import targets in one file, resolved to absolute .js paths. */
function localDependencies(file) {
  const source = fs.readFileSync(file, 'utf8');
  const targets = [
    ...source.matchAll(/require\(\s*['"](\.[^'"]+)['"]\s*\)/g),
    ...source.matchAll(/from\s+['"](\.[^'"]+)['"]/g),
  ].map(([, specifier]) => specifier);

  const out = [];
  for (const specifier of targets) {
    const base = path.resolve(path.dirname(file), specifier);
    const candidate = base.endsWith('.js') ? base : `${base}.js`;
    if (fs.existsSync(candidate)) out.push(candidate);
  }
  return out;
}

/** Everything src/main/main.js reaches, transitively. */
function requireClosure() {
  const seen = new Set();
  const queue = [path.join(MAIN_DIR, 'main.js')];
  while (queue.length) {
    const file = queue.pop();
    if (seen.has(file)) continue;
    seen.add(file);
    for (const dependency of localDependencies(file)) {
      // Only main-process modules: a require reaching outside src/main is a
      // different question (and one the bundler handles the same way anyway).
      if (dependency.startsWith(MAIN_DIR + path.sep)) queue.push(dependency);
    }
  }
  return seen;
}

test('every module main.js requires, directly or transitively, is a vite input', () => {
  const inputs = new Set(mainInputs());
  const missing = [...requireClosure()].filter((file) => !inputs.has(file)).sort();
  assert.deepEqual(
    missing, [],
    'a main-process module missing from the vite inputs fails at RUNTIME as a '
    + 'silent no-window startup, not at build time — add it to '
    + 'electron.vite.config.js main.build.rollupOptions.input',
  );
});

test('every declared main input points at a file that exists', () => {
  for (const file of mainInputs()) {
    assert.ok(fs.existsSync(file), `${file} is declared as an input but does not exist`);
  }
});

test('the Wave 9 modules are declared inputs and resolve', () => {
  const inputs = mainInputs();
  const names = new Set(inputs.map((file) => path.basename(file)));
  assert.ok(names.has('applicationRegistry.js'));
  assert.ok(names.has('applicationLauncher.js'));
  for (const file of inputs) assert.ok(fs.existsSync(file), file);
});

test('applicationLauncher requires applicationRegistry, so both must be inputs together', () => {
  // Stated as a test because the pair is easy to split later: the launcher
  // reads LAUNCH_METHODS from the registry module, so shipping one without the
  // other is the exact runtime-only failure this file guards.
  const deps = localDependencies(path.join(MAIN_DIR, 'applicationLauncher.js'));
  assert.ok(deps.includes(path.join(MAIN_DIR, 'applicationRegistry.js')));
});
