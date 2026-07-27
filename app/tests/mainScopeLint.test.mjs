// Static scope check for the renderer composition root.
//
// Motivated by a real, long-lived bug: main.js called `fetchJson(...)`, a
// function defined inside api/backend.js but never exported and never
// imported. Every call threw ReferenceError, the surrounding try/catch logged
// it, and the microphone picker silently rendered an empty device list. It
// looked like "no devices found" rather than a crash, so it survived.
//
// main.js is ~4,300 lines with ~60 named imports; nothing else in the toolchain
// catches a call to a name that is not in scope, because it only fails at
// runtime on a code path a test never takes. This lints the specific shape:
// API-style calls (fetchX/postX/updateX/...) must resolve to something main.js
// can actually see.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const MAIN = join(HERE, '..', 'src', 'renderer', 'main.js');
const rawSource = readFileSync(MAIN, 'utf8');

/**
 * Comments routinely quote code ("was `fetchJson(...)`"), and a prose mention
 * is not a call. Strip them, or the check flags its own documentation.
 */
function stripComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');
}

const source = stripComments(rawSource);

// Bare browser/host globals that are always in scope.
const HOST_GLOBALS = new Set([
  'clearInterval', 'clearTimeout', 'cancelAnimationFrame', 'fetch',
  'createImageBitmap', 'postMessage', 'clearImmediate',
]);

/** Names main.js pulls in from any module. */
function importedNames(src) {
  const names = new Set();
  const importBlocks = src.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"][^'"]+['"]/g);
  for (const [, body] of importBlocks) {
    for (const raw of body.split(',')) {
      const name = raw.trim().split(/\s+as\s+/).pop().trim();
      if (name) names.add(name);
    }
  }
  const defaults = src.matchAll(/import\s+([A-Za-z_$][\w$]*)\s+from/g);
  for (const [, name] of defaults) names.add(name);
  const namespaces = src.matchAll(/import\s*\*\s*as\s+([A-Za-z_$][\w$]*)/g);
  for (const [, name] of namespaces) names.add(name);
  return names;
}

/** Names main.js declares itself (function/const/let/var/class). */
function declaredNames(src) {
  const names = new Set();
  for (const [, name] of src.matchAll(/(?:^|\n)\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)/g)) {
    names.add(name);
  }
  for (const [, name] of src.matchAll(/(?:^|\n)\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)/g)) {
    names.add(name);
  }
  for (const [, name] of src.matchAll(/(?:^|\n)\s*class\s+([A-Za-z_$][\w$]*)/g)) {
    names.add(name);
  }
  // Destructured bindings, e.g. `const { a, b } = feature;`
  for (const [, body] of src.matchAll(/(?:const|let|var)\s*\{([^}]*)\}\s*=/g)) {
    for (const raw of body.split(',')) {
      const name = raw.trim().split(':').pop().trim().split('=')[0].trim();
      if (/^[A-Za-z_$][\w$]*$/.test(name)) names.add(name);
    }
  }
  return names;
}

// Calls that look like this app's backend API surface. Deliberately narrow:
// the goal is a high-signal guard, not a general linter.
// The negative lookbehind matters: without it `document.createElement(` and
// `firstRun.refreshStatus()` match as bare calls, and the check drowns in
// member expressions that are obviously in scope.
const API_CALL =
  /(?<![.\w$])((?:fetch|post|update|delete|create|refresh|clear|cancel|retranscribe)[A-Z][\w$]*)\s*\(/g;

test('every API-style call in main.js resolves to an import or a local declaration', () => {
  const available = new Set([
    ...importedNames(source),
    ...declaredNames(source),
    ...HOST_GLOBALS,
  ]);
  const unresolved = new Set();

  for (const [, name] of source.matchAll(API_CALL)) {
    if (available.has(name)) continue;
    unresolved.add(name);
  }

  assert.deepEqual(
    [...unresolved],
    [],
    `main.js calls ${[...unresolved].join(', ')} but neither imports nor declares them — ` +
      'this is exactly how the audio-devices picker broke silently',
  );
});

test('the lint would actually catch the original bug', () => {
  // Negative control: prove the check is not vacuous. A synthetic source that
  // calls an unimported API function must be flagged.
  const synthetic = `
    import { fetchHealth } from './api/backend.js';
    async function boom() {
      const info = await fetchJson('/runtime/audio-devices');
      return info;
    }
  `;
  const available = new Set([...importedNames(synthetic), ...declaredNames(synthetic)]);
  const found = [...synthetic.matchAll(API_CALL)]
    .map(([, name]) => name)
    .filter((name) => !available.has(name));

  assert.deepEqual(found, ['fetchJson'], 'the lint failed to catch a known-bad call');
});

test('the lint does not flag names that are legitimately in scope', () => {
  const synthetic = `
    import { fetchHealth, postDraft as createDraft } from './api/backend.js';
    async function refreshThings() { await fetchHealth(); await createDraft(); }
    const deleteLocal = () => {};
    function run() { deleteLocal(); refreshThings(); }
  `;
  const available = new Set([...importedNames(synthetic), ...declaredNames(synthetic)]);
  const found = [...synthetic.matchAll(API_CALL)]
    .map(([, name]) => name)
    .filter((name) => !available.has(name));

  assert.deepEqual(found, [], `false positives: ${found.join(', ')}`);
});
