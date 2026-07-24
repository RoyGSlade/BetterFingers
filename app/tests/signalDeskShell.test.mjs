// Unit tests for the Signal Desk workspace router (Phase 1 foundation).
// Run with: node --test app/tests/signalDeskShell.test.mjs
//
// No jsdom in this repo's test setup (see messageRescuePanel.test.mjs /
// firstRun.test.mjs) -- the pure reducers are exercised directly with plain
// data, and the DOM-wiring feature is exercised against small stub elements
// (classList backed by a real Set so assertions are meaningful, plain
// objects otherwise), same pattern as voiceStudio.test.mjs's element stubs.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  WORKSPACES,
  isValidWorkspace,
  getWorkspaceMeta,
  computeNextState,
  computeCollapsed,
  createSignalDeskShellFeature,
} from '../src/renderer/features/signalDeskShell.js';

// --- test doubles ------------------------------------------------------------

function makeClassList(initial = []) {
  const set = new Set(initial);
  return {
    add: (c) => set.add(c),
    remove: (c) => set.delete(c),
    toggle(c, force) {
      if (force === undefined) {
        if (set.has(c)) {
          set.delete(c);
          return false;
        }
        set.add(c);
        return true;
      }
      if (force) {
        set.add(c);
        return true;
      }
      set.delete(c);
      return false;
    },
    contains: (c) => set.has(c),
  };
}

function makeButton() {
  const listeners = {};
  const attrs = {};
  return {
    classList: makeClassList(),
    dataset: {},
    addEventListener(evt, fn) {
      listeners[evt] = fn;
    },
    setAttribute(k, v) {
      attrs[k] = v;
    },
    getAttribute(k) {
      return attrs[k];
    },
    click() {
      listeners.click?.();
    },
  };
}

function makeContainer() {
  return { hidden: false, classList: makeClassList() };
}

function makeTextEl() {
  return { textContent: '' };
}

function makeShellElements() {
  const navButtons = {};
  const workspaces = {};
  WORKSPACES.forEach((id) => {
    navButtons[id] = makeButton();
    workspaces[id] = makeContainer();
  });
  return {
    navButtons,
    workspaces,
    headerTitle: makeTextEl(),
    headerSubtitle: makeTextEl(),
    headerPillLabel: makeTextEl(),
    headerBreadcrumb: { ...makeTextEl(), hidden: false },
    shellRoot: makeContainer(),
    contextPanel: makeContainer(),
    contextCollapseButton: makeButton(),
    contextHideButton: makeButton(),
  };
}

// --- isValidWorkspace / getWorkspaceMeta --------------------------------------

test('isValidWorkspace: accepts exactly the 5 known workspaces', () => {
  for (const id of WORKSPACES) {
    assert.equal(isValidWorkspace(id), true);
  }
  assert.equal(isValidWorkspace('nope'), false);
  assert.equal(isValidWorkspace(''), false);
  assert.equal(isValidWorkspace(undefined), false);
  assert.equal(isValidWorkspace(null), false);
});

test('getWorkspaceMeta: every known workspace has a title/subtitle/pill', () => {
  for (const id of WORKSPACES) {
    const meta = getWorkspaceMeta(id);
    assert.ok(meta, `expected meta for ${id}`);
    assert.equal(typeof meta.title, 'string');
    assert.ok(meta.title.length > 0);
    assert.equal(typeof meta.subtitle, 'string');
    assert.equal(typeof meta.pill, 'string');
  }
});

test('getWorkspaceMeta: only Talk carries a breadcrumb (SPEC 3b)', () => {
  assert.equal(getWorkspaceMeta('talk').breadcrumb, 'Capture → Refine → Send');
  for (const id of WORKSPACES.filter((w) => w !== 'talk')) {
    assert.equal(getWorkspaceMeta(id).breadcrumb, null);
  }
});

test('getWorkspaceMeta: unknown id returns null, not a throw', () => {
  assert.equal(getWorkspaceMeta('bogus'), null);
});

// --- computeNextState (pure reducer) ------------------------------------------

test('computeNextState: switches to a valid requested workspace', () => {
  const next = computeNextState({ active: 'talk', contextCollapsed: false }, 'library');
  assert.equal(next.active, 'library');
  assert.equal(next.contextCollapsed, false);
});

test('computeNextState: invalid id is a no-op on the active workspace', () => {
  const next = computeNextState({ active: 'studio', contextCollapsed: true }, 'not-a-workspace');
  assert.equal(next.active, 'studio');
  assert.equal(next.contextCollapsed, true);
});

test('computeNextState: null/undefined state defaults to the first workspace', () => {
  assert.equal(computeNextState(null, 'settings').active, 'settings');
  assert.equal(computeNextState(undefined, 'bogus').active, WORKSPACES[0]);
});

test('computeNextState: preserves contextCollapsed across a workspace switch', () => {
  const next = computeNextState({ active: 'talk', contextCollapsed: true }, 'utilities');
  assert.equal(next.contextCollapsed, true);
});

// --- computeCollapsed (pure reducer) ------------------------------------------

test('computeCollapsed: sets the flag and coerces truthy/falsy input to boolean', () => {
  assert.equal(computeCollapsed({ active: 'talk' }, true).contextCollapsed, true);
  assert.equal(computeCollapsed({ active: 'talk' }, false).contextCollapsed, false);
  assert.equal(computeCollapsed({ active: 'talk' }, 1).contextCollapsed, true);
  assert.equal(computeCollapsed({ active: 'talk' }, 0).contextCollapsed, false);
});

test('computeCollapsed: preserves the active workspace', () => {
  const next = computeCollapsed({ active: 'studio', contextCollapsed: false }, true);
  assert.equal(next.active, 'studio');
});

// --- createSignalDeskShellFeature: init ---------------------------------------

test('init: defaults to the Talk workspace active and visible, others hidden', () => {
  const els = makeShellElements();
  const feature = createSignalDeskShellFeature({ elements: els });
  const state = feature.init();

  assert.equal(state.active, 'talk');
  assert.equal(els.workspaces.talk.hidden, false);
  for (const id of WORKSPACES.filter((w) => w !== 'talk')) {
    assert.equal(els.workspaces[id].hidden, true, `${id} should be hidden`);
  }
  assert.equal(els.navButtons.talk.classList.contains('is-active'), true);
  assert.equal(els.headerTitle.textContent, 'TALK');
  assert.equal(els.headerBreadcrumb.hidden, false);
});

test('init: honors an explicit initial workspace', () => {
  const els = makeShellElements();
  const feature = createSignalDeskShellFeature({ elements: els });
  const state = feature.init('studio');

  assert.equal(state.active, 'studio');
  assert.equal(els.workspaces.studio.hidden, false);
  assert.equal(els.workspaces.talk.hidden, true);
  assert.equal(els.navButtons.studio.classList.contains('is-active'), true);
  assert.equal(els.headerTitle.textContent, 'STUDIO');
  assert.equal(els.headerPillLabel.textContent, 'Persona Foundry');
  assert.equal(els.headerBreadcrumb.hidden, true);
});

test('init: an invalid initial workspace falls back to Talk rather than throwing', () => {
  const els = makeShellElements();
  const feature = createSignalDeskShellFeature({ elements: els });
  const state = feature.init('not-a-real-workspace');
  assert.equal(state.active, 'talk');
});

test('init: works with no elements at all (never throws)', () => {
  assert.doesNotThrow(() => {
    const feature = createSignalDeskShellFeature();
    feature.init();
  });
});

// --- createSignalDeskShellFeature: goTo (workspace switching) -----------------

test('goTo: switches active nav classes, visibility, and header copy', () => {
  const els = makeShellElements();
  const feature = createSignalDeskShellFeature({ elements: els });
  feature.init();

  const state = feature.goTo('library');

  assert.equal(state.active, 'library');
  assert.equal(els.navButtons.talk.classList.contains('is-active'), false);
  assert.equal(els.navButtons.library.classList.contains('is-active'), true);
  assert.equal(els.navButtons.talk.getAttribute('aria-current'), 'false');
  assert.equal(els.navButtons.library.getAttribute('aria-current'), 'page');

  assert.equal(els.workspaces.talk.hidden, true);
  assert.equal(els.workspaces.library.hidden, false);

  assert.equal(els.headerTitle.textContent, 'LIBRARY');
  assert.equal(els.headerSubtitle.textContent, getWorkspaceMeta('library').subtitle);
  assert.equal(els.headerBreadcrumb.hidden, true, 'Library has no breadcrumb');
});

test('goTo: clicking a nav button drives the same switch as calling goTo directly', () => {
  const els = makeShellElements();
  const feature = createSignalDeskShellFeature({ elements: els });
  feature.init();

  els.navButtons.utilities.click();

  assert.equal(feature.getState().active, 'utilities');
  assert.equal(els.workspaces.utilities.hidden, false);
  assert.equal(els.navButtons.utilities.classList.contains('is-active'), true);
});

test('goTo: an unknown workspace id is a no-op, not a blank shell', () => {
  const els = makeShellElements();
  const feature = createSignalDeskShellFeature({ elements: els });
  feature.init();

  const state = feature.goTo('does-not-exist');

  assert.equal(state.active, 'talk');
  assert.equal(els.workspaces.talk.hidden, false);
  assert.equal(els.navButtons.talk.classList.contains('is-active'), true);
});

// --- createSignalDeskShellFeature: context panel collapse ----------------------

test('toggleContextCollapsed: toggles both the panel and shell-root modifier classes', () => {
  const els = makeShellElements();
  const feature = createSignalDeskShellFeature({ elements: els });
  feature.init();

  assert.equal(els.contextPanel.classList.contains('is-collapsed'), false);
  assert.equal(els.shellRoot.classList.contains('is-context-collapsed'), false);

  let state = feature.toggleContextCollapsed();
  assert.equal(state.contextCollapsed, true);
  assert.equal(els.contextPanel.classList.contains('is-collapsed'), true);
  assert.equal(els.shellRoot.classList.contains('is-context-collapsed'), true);

  state = feature.toggleContextCollapsed();
  assert.equal(state.contextCollapsed, false);
  assert.equal(els.contextPanel.classList.contains('is-collapsed'), false);
  assert.equal(els.shellRoot.classList.contains('is-context-collapsed'), false);
});

test('setContextCollapsed: the header collapse chevron and footer hide button both toggle it', () => {
  const els = makeShellElements();
  const feature = createSignalDeskShellFeature({ elements: els });
  feature.init();

  els.contextCollapseButton.click();
  assert.equal(feature.getState().contextCollapsed, true);
  assert.equal(els.contextPanel.classList.contains('is-collapsed'), true);

  els.contextHideButton.click();
  assert.equal(feature.getState().contextCollapsed, false);
  assert.equal(els.contextPanel.classList.contains('is-collapsed'), false);
});

test('setContextCollapsed: collapsing does not change the active workspace', () => {
  const els = makeShellElements();
  const feature = createSignalDeskShellFeature({ elements: els });
  feature.init('library');

  feature.setContextCollapsed(true);

  assert.equal(feature.getState().active, 'library');
  assert.equal(els.workspaces.library.hidden, false);
});

test('getState: returns a shallow copy, not a live reference', () => {
  const els = makeShellElements();
  const feature = createSignalDeskShellFeature({ elements: els });
  feature.init();

  const state = feature.getState();
  state.active = 'mutated';

  assert.equal(feature.getState().active, 'talk');
});
