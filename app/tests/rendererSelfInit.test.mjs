// Unit tests for W2-SELFINIT: containing renderer feature modules' import-time
// self-init side effects behind one explicit opt-in.
//
// personaLearning.js, messageRescuePanel.js, and textPlayground.js each end
// with `if (shouldAutowire()) { init*(); }` (previously a bare `if (typeof
// document !== 'undefined')`), where shouldAutowire() (lib/autowire.mjs)
// only returns true when the host document's <html> carries
// `data-bf-autowire="legacy"`. index.html sets that marker so the legacy
// shipping UI keeps auto-initializing exactly as before; anything else that
// imports one of these modules -- a test, a future composition root, a page
// that happens to reuse a matching id -- binds nothing until it either
// carries the marker or calls the exported init*() itself.
//
// Run with: node --test app/tests/rendererSelfInit.test.mjs
//
// No jsdom in this repo's test setup (matches personaLearning.test.mjs /
// textPlayground.test.mjs / messageRescuePanel.test.mjs) -- DOM-driven logic
// is exercised against plain stub objects, not real nodes.
//
// Import-time side effects only run once per resolved module URL (ES module
// instances are cached by specifier), so each test that needs a *fresh*
// top-level evaluation of a module dynamically imports it with a unique
// cache-busting query string -- see importFresh() below. Modules' own
// internal relative imports (e.g. personaLearning.js importing
// './messageRescuePanel.js' for escapeHtml) are never cache-busted, so those
// stay on the single canonical module instance shared with the rest of the
// suite; that instance may or may not have already self-initialized against
// some other document by the time a given test runs. That's harmless here:
// this file's "unbound" assertions use call-count-is-zero checks, which only
// hold when the doc under test is not opted in -- and a canonical
// transitively-loaded module checks the very same shouldAutowire() gate
// against that same not-opted-in doc, so it also stays inert and adds no
// calls. The "wired" assertions use inclusion checks (`_calls.includes(...)`),
// which are unaffected by any extra calls a co-loaded module might add.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  AUTOWIRE_ATTRIBUTE,
  AUTOWIRE_LEGACY_VALUE,
  shouldAutowire,
} from '../src/renderer/lib/autowire.mjs';

const MODULE_URLS = {
  personaLearning: new URL('../src/renderer/features/personaLearning.js', import.meta.url).href,
  messageRescuePanel: new URL('../src/renderer/features/messageRescuePanel.js', import.meta.url).href,
  textPlayground: new URL('../src/renderer/features/textPlayground.js', import.meta.url).href,
};

let importCounter = 0;
function importFresh(url) {
  importCounter += 1;
  return import(`${url}?bf-selfinit-test=${importCounter}`);
}

function makeStubElement() {
  return {
    value: '',
    textContent: '',
    innerHTML: '',
    hidden: false,
    disabled: false,
    checked: false,
    _attrs: {},
    _listeners: {},
    setAttribute(k, v) {
      this._attrs[k] = v;
    },
    removeAttribute(k) {
      delete this._attrs[k];
    },
    addEventListener(evt, fn) {
      this._listeners[evt] = fn;
    },
  };
}

// Auto-vivifying stub document: getElementById always returns a stub element
// (never null) for any id queried, so a module's own "no-op if markup is
// absent" guard (`if (!elements.section) return`) never short-circuits the
// thing this file is actually testing -- whether the module queries/wires at
// all. Every getElementById call is recorded in `_calls`, in order, so tests
// can assert either "nothing was queried" (unbound) or "this specific id was
// queried" (wired) without having to enumerate every id a module happens to
// look up.
function makeStubDoc({ autowire = false } = {}) {
  const calls = [];
  const elements = new Map();
  return {
    _calls: calls,
    _elements: elements,
    documentElement: {
      getAttribute(name) {
        return autowire && name === AUTOWIRE_ATTRIBUTE ? AUTOWIRE_LEGACY_VALUE : null;
      },
    },
    getElementById(id) {
      calls.push(id);
      if (!elements.has(id)) elements.set(id, makeStubElement());
      return elements.get(id);
    },
  };
}

// fn's result is always awaited before restoring the global -- these guard a
// dynamic import(), which is asynchronous even for a module whose own body
// is fully synchronous, so a bare `try { return fn() } finally { restore }`
// would restore the global before the imported module's top-level code (and
// its shouldAutowire() check) actually runs.
async function withGlobalDocument(doc, fn) {
  const hadDocument = 'document' in globalThis;
  const previousDocument = globalThis.document;
  globalThis.document = doc;
  try {
    return await fn();
  } finally {
    if (hadDocument) globalThis.document = previousDocument;
    else delete globalThis.document;
  }
}

async function withGlobalLocalStorage(storage, fn) {
  const hadStorage = 'localStorage' in globalThis;
  const previousStorage = globalThis.localStorage;
  globalThis.localStorage = storage;
  try {
    return await fn();
  } finally {
    if (hadStorage) globalThis.localStorage = previousStorage;
    else delete globalThis.localStorage;
  }
}

const enabledMessageRescueStorage = { getItem: () => 'true' };

// --- shouldAutowire (lib/autowire.mjs) --------------------------------------

test('shouldAutowire: false with no document', () => {
  assert.equal(shouldAutowire(null), false);
  assert.equal(shouldAutowire(undefined), false);
});

test('shouldAutowire: false when documentElement lacks the marker', () => {
  const doc = { documentElement: { getAttribute: () => null } };
  assert.equal(shouldAutowire(doc), false);
});

test('shouldAutowire: false when the marker has the wrong value', () => {
  const doc = { documentElement: { getAttribute: () => 'yes' } };
  assert.equal(shouldAutowire(doc), false);
});

test('shouldAutowire: true only for data-bf-autowire="legacy"', () => {
  const doc = {
    documentElement: {
      getAttribute: (name) => (name === AUTOWIRE_ATTRIBUTE ? AUTOWIRE_LEGACY_VALUE : null),
    },
  };
  assert.equal(shouldAutowire(doc), true);
});

// --- personaLearning.js ------------------------------------------------------

test('personaLearning: import against a non-opted-in doc binds nothing (no queries at all)', async () => {
  const doc = makeStubDoc({ autowire: false });
  await withGlobalDocument(doc, () => importFresh(MODULE_URLS.personaLearning));
  assert.deepEqual(doc._calls, []);
});

test('personaLearning: anti-regression -- import never binds #personaLearningSection unless opted in', async () => {
  const doc = makeStubDoc({ autowire: false });
  await withGlobalDocument(doc, () => importFresh(MODULE_URLS.personaLearning));
  assert.equal(doc._calls.includes('personaLearningSection'), false);
});

test('personaLearning: import against an opted-in doc self-wires (legacy parity)', async () => {
  const doc = makeStubDoc({ autowire: true });
  await withGlobalDocument(doc, () => importFresh(MODULE_URLS.personaLearning));
  assert.ok(doc._calls.includes('personaLearningSection'));
  const teachButton = doc._elements.get('personaLearningTeachButton');
  assert.equal(typeof teachButton._listeners.click, 'function');
});

test('personaLearning: explicit initPersonaLearning({ doc }) wires regardless of the marker', async () => {
  const doc = makeStubDoc({ autowire: false });
  const mod = await importFresh(MODULE_URLS.personaLearning);
  assert.equal(doc._calls.length, 0); // import itself still bound nothing
  const feature = mod.initPersonaLearning({ doc });
  assert.ok(feature);
  assert.ok(doc._calls.includes('personaLearningSection'));
  const teachButton = doc._elements.get('personaLearningTeachButton');
  assert.equal(typeof teachButton._listeners.click, 'function');
});

// --- messageRescuePanel.js ----------------------------------------------------

test('messageRescuePanel: import against a non-opted-in doc binds nothing (no queries at all)', async () => {
  const doc = makeStubDoc({ autowire: false });
  await withGlobalDocument(doc, () => importFresh(MODULE_URLS.messageRescuePanel));
  assert.deepEqual(doc._calls, []);
});

test('messageRescuePanel: import against an opted-in doc self-wires (legacy parity)', async () => {
  const doc = makeStubDoc({ autowire: true });
  await withGlobalLocalStorage(enabledMessageRescueStorage, () =>
    withGlobalDocument(doc, () => importFresh(MODULE_URLS.messageRescuePanel)),
  );
  assert.ok(doc._calls.includes('messageRescuePanel'));
  const faithfulInput = doc._elements.get('messageRescueVariantFaithful');
  assert.equal(typeof faithfulInput._listeners.change, 'function');
});

test('messageRescuePanel: explicit initMessageRescuePanel({ doc, storage }) wires regardless of the marker', async () => {
  const doc = makeStubDoc({ autowire: false });
  const mod = await importFresh(MODULE_URLS.messageRescuePanel);
  assert.equal(doc._calls.length, 0); // import itself still bound nothing
  mod.initMessageRescuePanel({ doc, storage: enabledMessageRescueStorage });
  assert.ok(doc._calls.includes('messageRescuePanel'));
  const faithfulInput = doc._elements.get('messageRescueVariantFaithful');
  assert.equal(typeof faithfulInput._listeners.change, 'function');
});

// --- textPlayground.js --------------------------------------------------------

test('textPlayground: import against a non-opted-in doc binds nothing (no queries at all)', async () => {
  const doc = makeStubDoc({ autowire: false });
  await withGlobalDocument(doc, () => importFresh(MODULE_URLS.textPlayground));
  assert.deepEqual(doc._calls, []);
});

test('textPlayground: import against an opted-in doc self-wires (legacy parity)', async () => {
  const doc = makeStubDoc({ autowire: true });
  await withGlobalDocument(doc, () => importFresh(MODULE_URLS.textPlayground));
  assert.ok(doc._calls.includes('textPlaygroundSection'));
  const runButton = doc._elements.get('textPlaygroundRunButton');
  assert.equal(typeof runButton._listeners.click, 'function');
});

test('textPlayground: explicit initTextPlayground({ doc }) wires regardless of the marker', async () => {
  const doc = makeStubDoc({ autowire: false });
  const mod = await importFresh(MODULE_URLS.textPlayground);
  assert.equal(doc._calls.length, 0); // import itself still bound nothing
  const feature = mod.initTextPlayground({ doc });
  assert.ok(feature);
  assert.ok(doc._calls.includes('textPlaygroundSection'));
  const runButton = doc._elements.get('textPlaygroundRunButton');
  assert.equal(typeof runButton._listeners.click, 'function');
});
