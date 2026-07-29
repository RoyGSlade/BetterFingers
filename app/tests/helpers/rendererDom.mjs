// A very small DOM good enough to run the real renderer feature modules.
//
// The Signal Desk feature modules (features/settingsWorkspace.js,
// features/utilitiesWorkspace.js, ...) are written against a browser
// document: they call getElementById, toggle classes, set `hidden`, append
// nodes and read `value`/`checked`. There is no jsdom in this repo's
// devDependencies and the unit suite is plain `node --test`, so up to now
// those modules were only ever exercised through hand-rolled per-test object
// literals -- which meant the DOM WIRING (which id maps to which control,
// which listener the button really gets) was never executed by a test.
//
// That gap is exactly what the Wave 11 parity ledger reports as a missing
// evidence leg. This module closes it without pulling in a DOM library: it
// implements the handful of interfaces the feature modules actually touch,
// and nothing else. It is deliberately not a DOM emulator -- if a module
// starts needing layout, ranges or event bubbling, add it here on purpose
// rather than widening this into a fake that quietly disagrees with a
// browser.
//
// Not exercised here and not pretended: CSS, layout, focus order, real event
// propagation. Those are the QA suite's job against the real page.

/** One element. Only the surface the renderer modules use. */
class FakeElement {
  constructor(tagName = 'div', id = '') {
    this.tagName = String(tagName).toUpperCase();
    this.id = id;
    this.children = [];
    this.parentNode = null;
    this.attributes = new Map();
    this.dataset = {};
    // Both spellings the renderer uses: `style.width = '40%'` and
    // `style.setProperty('--sd-meter-level', '40%')`. Custom properties are
    // kept in the same bag so a test can read either back.
    this.style = {
      setProperty(name, value) { this[name] = String(value); },
      getPropertyValue(name) { return this[name] ?? ''; },
      removeProperty(name) { delete this[name]; },
    };
    this.hidden = false;
    this.disabled = false;
    this.title = '';
    this.value = '';
    this.checked = false;
    this.type = '';
    this.files = null;
    this._text = '';
    this._html = '';
    this._classes = new Set();
    this._listeners = new Map();
    this.clickCount = 0;

    const classes = this._classes;
    this.classList = {
      add: (...names) => names.forEach((n) => classes.add(n)),
      remove: (...names) => names.forEach((n) => classes.delete(n)),
      contains: (name) => classes.has(name),
      toggle: (name, force) => {
        const want = force === undefined ? !classes.has(name) : Boolean(force);
        if (want) classes.add(name);
        else classes.delete(name);
        return want;
      },
    };
  }

  get className() {
    return [...this._classes].join(' ');
  }

  set className(value) {
    this._classes.clear();
    String(value || '').split(/\s+/).filter(Boolean).forEach((n) => this._classes.add(n));
  }

  // Text set on this node PLUS every descendant's text, in that order -- the
  // same concatenation a browser performs. Modelling them as alternatives
  // instead (own text OR children) would have quietly hidden the "×" a chip
  // appends after its label.
  get textContent() {
    return this._text + this.children.map((c) => c.textContent).join('');
  }

  set textContent(value) {
    this.children.forEach((c) => { c.parentNode = null; });
    this.children = [];
    this._text = value === null || value === undefined ? '' : String(value);
  }

  // Assigning innerHTML always clears children, which is the behaviour every
  // caller in the renderer relies on (`list.innerHTML = ''` before a re-render).
  // The markup itself is kept verbatim as a string rather than parsed: the
  // renderer only ever assigns tiny static fragments like the empty-state
  // span, and a half-working parser would be worse than an honest opaque one.
  get innerHTML() {
    if (this.children.length || this._text) return this.textContent;
    return this._html;
  }

  set innerHTML(value) {
    this.children.forEach((c) => { c.parentNode = null; });
    this.children = [];
    this._text = '';
    this._html = value === null || value === undefined ? '' : String(value);
  }

  get outerText() {
    return this.textContent;
  }

  appendChild(child) {
    this._html = '';
    child.parentNode = this;
    this.children.push(child);
    return child;
  }

  /** append(...nodes) -- strings become text, elements become children. */
  append(...nodes) {
    for (const node of nodes) {
      if (node instanceof FakeElement) this.appendChild(node);
      else this._text += String(node);
    }
  }

  /** replaceChildren(...nodes) -- the "empty this list first" call the renderer uses. */
  replaceChildren(...nodes) {
    this.children.forEach((c) => { c.parentNode = null; });
    this.children = [];
    this._text = '';
    this._html = '';
    this.append(...nodes);
  }

  removeChild(child) {
    const index = this.children.indexOf(child);
    if (index >= 0) this.children.splice(index, 1);
    child.parentNode = null;
    return child;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === 'class') this.className = value;
    if (name === 'hidden') this.hidden = true;
    // `title` and `value` are reflected between property and attribute in a
    // real DOM; the renderer sets the property and clears the attribute, so a
    // fake that kept them apart would report a tooltip that is still on screen.
    if (name === 'title') this.title = String(value);
    if (name.startsWith('data-')) this.dataset[dataKey(name)] = String(value);
  }

  getAttribute(name) {
    if (name === 'class') return this.className;
    if (name === 'title') return this.title === '' ? null : this.title;
    if (name.startsWith('data-') && dataKey(name) in this.dataset) return this.dataset[dataKey(name)];
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  removeAttribute(name) {
    this.attributes.delete(name);
    if (name === 'title') this.title = '';
    if (name.startsWith('data-')) delete this.dataset[dataKey(name)];
  }

  hasAttribute(name) {
    return this.getAttribute(name) !== null;
  }

  /** Descendants matching `[attr]`, `[attr="value"]`, `.class`, `#id` or a tag name. */
  querySelectorAll(selector) {
    const out = [];
    const match = matcherFor(selector);
    const walk = (node) => {
      for (const child of node.children) {
        if (match(child)) out.push(child);
        walk(child);
      }
    };
    walk(this);
    return out;
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  addEventListener(type, handler) {
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push(handler);
  }

  removeEventListener(type, handler) {
    const list = this._listeners.get(type) || [];
    const index = list.indexOf(handler);
    if (index >= 0) list.splice(index, 1);
  }

  /** Fires every listener registered for `type`. Returns the number that ran. */
  emit(type, event = {}) {
    const list = this._listeners.get(type) || [];
    const payload = { type, target: this, preventDefault() {}, stopPropagation() {}, ...event };
    for (const handler of [...list]) handler(payload);
    return list.length;
  }

  /** How many listeners this element carries for `type` (0 means "never bound"). */
  listenerCount(type) {
    return (this._listeners.get(type) || []).length;
  }

  click() {
    this.clickCount += 1;
    this.emit('click');
  }

  /** Detach from the parent, the way Element.remove() does. */
  remove() {
    this.parentNode?.removeChild(this);
  }

  focus() {
    if (this.ownerDocument) this.ownerDocument.activeElement = this;
  }
}

function dataKey(attributeName) {
  return attributeName.slice(5).replace(/-([a-z])/g, (_m, c) => c.toUpperCase());
}

function matcherFor(selector) {
  const trimmed = String(selector).trim();
  const attrWithValue = /^\[([A-Za-z0-9_:-]+)=["']?([^\]"']*)["']?\]$/.exec(trimmed);
  if (attrWithValue) {
    return (el) => el.getAttribute(attrWithValue[1]) === attrWithValue[2];
  }
  const attrOnly = /^\[([A-Za-z0-9_:-]+)\]$/.exec(trimmed);
  if (attrOnly) {
    return (el) => el.getAttribute(attrOnly[1]) !== null;
  }
  if (trimmed.startsWith('.')) {
    return (el) => el.classList.contains(trimmed.slice(1));
  }
  if (trimmed.startsWith('#')) {
    return (el) => el.id === trimmed.slice(1);
  }
  return (el) => el.tagName === trimmed.toUpperCase();
}

/** A document whose getElementById knows exactly the ids you named. */
class FakeDocument {
  constructor() {
    this.byId = new Map();
    this.body = new FakeElement('body');
    this.body.ownerDocument = this;
    this.documentElement = new FakeElement('html');
    this.documentElement.ownerDocument = this;
    this.activeElement = null;
  }

  createElement(tagName) {
    const el = new FakeElement(tagName);
    el.ownerDocument = this;
    return el;
  }

  getElementById(id) {
    return this.byId.get(id) || null;
  }

  // Document-level selector queries search the attached tree only. Elements
  // registered with add() are reachable by id but are not in <body> unless a
  // test appends them, which matches how these tests are written: id lookups
  // are the contract under test, selector sweeps are not.
  querySelectorAll(selector) {
    return this.body.querySelectorAll(selector);
  }

  querySelector(selector) {
    return this.body.querySelector(selector);
  }

  /** Registers an element under `id` (created if absent) and returns it. */
  add(id, { tagName = 'div', ...props } = {}) {
    const el = new FakeElement(tagName, id);
    el.ownerDocument = this;
    Object.assign(el, props);
    this.byId.set(id, el);
    return el;
  }

  /** Registers every id in `ids`, optionally with per-id property overrides. */
  addAll(ids, overrides = {}) {
    const out = {};
    for (const id of ids) out[id] = this.add(id, overrides[id]);
    return out;
  }
}

/** A fresh document with `ids` registered. */
export function makeDocument(ids = [], overrides = {}) {
  const doc = new FakeDocument();
  doc.addAll(ids, overrides);
  return doc;
}

export { FakeElement, FakeDocument };

/** A localStorage good enough for the appearance preferences. */
export function makeLocalStorage(initial = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => { map.set(key, String(value)); },
    removeItem: (key) => { map.delete(key); },
    clear: () => { map.clear(); },
    get size() { return map.size; },
    snapshot: () => Object.fromEntries(map),
  };
}

/**
 * A `window.betterFingers.backendRequest` stub that records every call.
 *
 * The renderer never talks to the backend directly -- api/backend.js funnels
 * every route through this one preload bridge as (method, path, body). Stubbing
 * it here rather than stubbing each backend.js export means the test exercises
 * the REAL request-building and error-unwrapping code, and can assert the exact
 * method and path a control reaches for.
 */
export function makeBackendBridge(routes = {}) {
  const calls = [];
  const request = async (method, path, body) => {
    calls.push({ method, path, body });
    const key = `${method} ${path}`;
    const handler = routes[key] ?? routes[path];
    if (handler === undefined) {
      return { ok: false, status: 404, body: { detail: `no stub for ${key}` } };
    }
    const value = typeof handler === 'function' ? await handler({ method, path, body }) : handler;
    if (value && typeof value === 'object' && 'ok' in value && 'status' in value) return value;
    return { ok: true, status: 200, body: value };
  };
  return {
    request,
    calls,
    /** Every recorded call as "METHOD /path", for readable assertions. */
    signatures: () => calls.map((c) => `${c.method} ${c.path}`),
    find: (method, path) => calls.find((c) => c.method === method && c.path === path) || null,
    reset: () => { calls.length = 0; },
  };
}

/**
 * Installs `document`/`window`/`localStorage` globals for the duration of a
 * test and returns a restore function.
 *
 * The renderer modules read these off the global object, so a test that wants
 * to run the real wiring has to provide them. Everything is restored on
 * teardown so tests stay order-independent.
 */
export function installDomGlobals({ document: doc, betterFingers, prefersDark = false, storage } = {}) {
  const previous = {
    document: globalThis.document,
    window: globalThis.window,
    localStorage: globalThis.localStorage,
    Blob: globalThis.Blob,
    FileReader: globalThis.FileReader,
    createObjectURL: globalThis.URL?.createObjectURL,
    revokeObjectURL: globalThis.URL?.revokeObjectURL,
    hadCreateObjectURL: Object.prototype.hasOwnProperty.call(globalThis.URL || {}, 'createObjectURL'),
  };

  const localStorageStub = storage || makeLocalStorage();
  const mediaListeners = [];
  const windowStub = {
    betterFingers,
    localStorage: localStorageStub,
    matchMedia: (query) => ({
      matches: query.includes('dark') ? prefersDark : false,
      media: query,
      addEventListener: (_type, handler) => mediaListeners.push(handler),
      removeEventListener: () => {},
    }),
    confirm: () => true,
  };

  globalThis.document = doc;
  globalThis.window = windowStub;
  globalThis.localStorage = localStorageStub;
  if (!globalThis.URL.createObjectURL) globalThis.URL.createObjectURL = () => 'blob:test';
  if (!globalThis.URL.revokeObjectURL) globalThis.URL.revokeObjectURL = () => {};

  return function restore() {
    globalThis.document = previous.document;
    globalThis.window = previous.window;
    globalThis.localStorage = previous.localStorage;
    if (!previous.hadCreateObjectURL) {
      delete globalThis.URL.createObjectURL;
      delete globalThis.URL.revokeObjectURL;
    }
  };
}
