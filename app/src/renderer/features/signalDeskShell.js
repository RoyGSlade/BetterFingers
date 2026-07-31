// Signal Desk workspace router (Phase 1: foundation / static shell only).
//
// This is a pure, framework-free show/hide router for the 5 top-level
// Signal Desk workspaces (Talk/Scribe/Studio/Utilities/Settings) described
// in docs/ui/SIGNAL_DESK_SPEC.md section 3. It has NO backend calls and no
// feature logic -- this phase only wires the nav rail to workspace
// visibility, the center header copy, and the right context-panel collapse
// state. Later phases mount real feature modules (drafts.js, personas.js,
// voiceStudio.js, ...) behind these same workspace containers.
//
// Follows this repo's `createXFeature({ elements })` convention (see
// features/firstRun.js): pure helpers (no DOM) are exported separately for
// unit testing, and the DOM-wiring factory only ever touches elements that
// were handed to it -- every access is optional-chained so a missing
// element (or a stub in tests) never throws.

export const WORKSPACES = ['talk', 'library', 'studio', 'utilities', 'settings'];

// Per-workspace header copy (SPEC 3b, 4-6). Utilities/Settings copy is a
// reasonable placeholder -- SPEC 8 notes the director will spec those two
// in the same visual language once their content is designed; this phase
// only needs a title/subtitle/pill so the header never renders blank.
const WORKSPACE_META = {
  talk: {
    title: 'TALK',
    subtitle: 'Capture, refine, and send in one motion.',
    pill: 'Signal Core',
    breadcrumb: 'Capture → Refine → Send',
  },
  library: {
    title: 'LIBRARY',
    subtitle: 'Search, revisit, and recover speech.',
    pill: 'Signal Core',
    breadcrumb: null,
  },
  studio: {
    title: 'STUDIO',
    subtitle: 'Design how BetterFingers sounds and behaves.',
    pill: 'Persona Foundry',
    breadcrumb: null,
  },
  utilities: {
    title: 'UTILITIES',
    subtitle: 'Dictionary, macros, devices, and diagnostics.',
    pill: 'Signal Core',
    breadcrumb: null,
  },
  settings: {
    title: 'SETTINGS',
    subtitle: 'Profile, hotkeys, and everything else.',
    pill: 'Signal Core',
    breadcrumb: null,
  },
};

// --- Pure helpers (no DOM, no network) --------------------------------------

/** True if `id` is one of the 5 known Signal Desk workspaces. */
export function isValidWorkspace(id) {
  return WORKSPACES.includes(id);
}

/** Header copy for a workspace id, or null if the id is unknown. */
export function getWorkspaceMeta(id) {
  return WORKSPACE_META[id] || null;
}

/**
 * Pure reducer: given the current router state and a requested workspace
 * id, returns the next state. An invalid/unknown id is a no-op (returns
 * state with the same active workspace) rather than throwing or blanking
 * the shell -- a stray click or bad id should never leave no workspace
 * visible.
 */
export function computeNextState(state, requestedId) {
  const current = state && isValidWorkspace(state.active) ? state.active : WORKSPACES[0];
  const contextCollapsed = Boolean(state && state.contextCollapsed);
  if (!isValidWorkspace(requestedId)) {
    return { active: current, contextCollapsed };
  }
  return { active: requestedId, contextCollapsed };
}

/** Pure reducer for the context-panel collapse toggle. */
export function computeCollapsed(state, collapsed) {
  const current = state && isValidWorkspace(state.active) ? state.active : WORKSPACES[0];
  return { active: current, contextCollapsed: Boolean(collapsed) };
}

// --- DOM-wiring feature ------------------------------------------------------

/**
 * Build the nested `elements` shape from a document.
 *
 * Follows the `collectXElements(root)` convention the workspace modules use.
 * Without it every caller hand-assembles a five-key nested object, and a typo
 * in one nav id degrades silently to a dead button (every access in this module
 * is optional-chained, by design, so nothing throws).
 */
export function collectShellElements(root = document) {
  const navButtons = {};
  const workspaces = {};
  for (const id of WORKSPACES) {
    navButtons[id] = root?.querySelector?.(`[data-nav="${id}"]`) ?? null;
    workspaces[id] = root?.getElementById?.(`workspace-${id}`) ?? null;
  }
  return {
    navButtons,
    workspaces,
    headerTitle: root?.getElementById?.('sdHeaderTitle') ?? null,
    headerSubtitle: root?.getElementById?.('sdHeaderSubtitle') ?? null,
    headerPillLabel: root?.getElementById?.('sdHeaderPillLabel') ?? null,
    headerBreadcrumb: root?.getElementById?.('sdHeaderBreadcrumb') ?? null,
    shellRoot: root?.getElementById?.('sdShell') ?? null,
    contextPanel: root?.getElementById?.('sdContextPanel') ?? null,
    contextCollapseButton: root?.getElementById?.('sdContextCollapseBtn') ?? null,
    contextHideButton: root?.getElementById?.('sdContextHideBtn') ?? null,
    contextContents: root?.querySelectorAll
      ? Array.from(root.querySelectorAll('.sd-context__content[data-context-for]'))
      : [],
    // Utilities owns the secondary links for retained material. Keep these
    // separate from the primary rail so Library/History are reachable without
    // making either one a competing top-level workspace.
    utilityLinks: root?.querySelectorAll
      ? Array.from(root.querySelectorAll('[data-shell-nav]'))
      : [],
  };
}

/**
 * @param {object} deps
 * @param {object} deps.elements DOM element references looked up by the caller (main.js in a
 *   later phase, or a test stub today). Every access below is optional-chained.
 *   Shape:
 *   - navButtons: { talk, library, studio, utilities, settings } -- nav rail buttons
 *   - utilityLinks: secondary links rendered inside Utilities
 *   - workspaces: { talk, library, studio, utilities, settings } -- center workspace containers
 *   - headerTitle, headerSubtitle, headerPillLabel, headerBreadcrumb -- center header elements
 *   - shellRoot -- the `.sd-shell` grid container (gets `.is-context-collapsed` toggled so the
 *     context column narrows; see signal-desk.css)
 *   - contextPanel -- the `.sd-context` aside (gets `.is-collapsed` toggled)
 *   - contextCollapseButton -- the header `«` chevron
 *   - contextHideButton -- the bottom `‹ Hide Panel` button
 *   - contextContents -- iterable of `.sd-context__content[data-context-for]` blocks; the one
 *     whose `data-context-for` matches the active workspace is shown (SPEC 3c: the context
 *     panel's contents are workspace-specific). Optional -- workspaces without their own
 *     context block simply show none.
 */
export function createSignalDeskShellFeature({ elements } = {}) {
  const els = elements || {};
  let state = { active: WORKSPACES[0], contextCollapsed: false };

  function applyActiveNav() {
    WORKSPACES.forEach((id) => {
      const btn = els.navButtons?.[id];
      if (!btn) return;
      const isActive = id === state.active;
      btn.classList?.toggle('is-active', isActive);
      btn.setAttribute?.('aria-current', isActive ? 'page' : 'false');
      // Roving tabindex: exactly one rail button is in the tab order, so Tab
      // moves past the whole rail in one press and arrow keys move within it.
      // Without this every workspace button is a separate tab stop, which the
      // old tab bar avoided (main.js's activateTab) and the rail regressed.
      btn.setAttribute?.('tabindex', isActive ? '0' : '-1');
    });
    for (const link of els.utilityLinks || []) {
      const isActive = link?.getAttribute?.('data-shell-nav') === state.active;
      link?.setAttribute?.('aria-current', isActive ? 'page' : 'false');
    }
  }

  function applyWorkspaceVisibility() {
    WORKSPACES.forEach((id) => {
      const container = els.workspaces?.[id];
      if (!container) return;
      container.hidden = id !== state.active;
    });
  }

  // SPEC 3c: the right-hand context panel's contents are workspace-specific.
  // A workspace with no matching block shows none, which is why this drives
  // hidden per block rather than assuming every workspace has one.
  function applyContextContent() {
    const blocks = els.contextContents;
    if (!blocks) return;
    for (const block of blocks) {
      if (!block) continue;
      const isActive = block.getAttribute?.('data-context-for') === state.active;
      block.classList?.toggle('is-active-context', isActive);
      block.hidden = !isActive;
    }
  }

  function applyHeader() {
    const meta = getWorkspaceMeta(state.active);
    if (!meta) return;
    if (els.headerTitle) els.headerTitle.textContent = meta.title;
    if (els.headerSubtitle) els.headerSubtitle.textContent = meta.subtitle;
    if (els.headerPillLabel) els.headerPillLabel.textContent = meta.pill;
    if (els.headerBreadcrumb) {
      els.headerBreadcrumb.hidden = !meta.breadcrumb;
      els.headerBreadcrumb.textContent = meta.breadcrumb || '';
    }
  }

  function applyContextCollapsed() {
    const collapsed = Boolean(state.contextCollapsed);
    els.contextPanel?.classList?.toggle('is-collapsed', collapsed);
    els.shellRoot?.classList?.toggle('is-context-collapsed', collapsed);
  }

  function render() {
    applyActiveNav();
    applyWorkspaceVisibility();
    applyContextContent();
    applyHeader();
    applyContextCollapsed();
    // Stamp the active workspace so per-workspace styling (e.g. Talk's blue H1)
    // can key off it without extra JS.
    els.shellRoot?.setAttribute?.('data-workspace', state.active);
  }

  /** Switch the visible workspace. No-op (but still re-renders) on an unknown id. */
  function goTo(workspaceId) {
    state = computeNextState(state, workspaceId);
    render();
    return getState();
  }

  /** Explicitly set the context panel's collapsed state. */
  function setContextCollapsed(collapsed) {
    state = computeCollapsed(state, collapsed);
    render();
    return getState();
  }

  function toggleContextCollapsed() {
    return setContextCollapsed(!state.contextCollapsed);
  }

  function bindOnce() {
    WORKSPACES.forEach((id, index) => {
      const btn = els.navButtons?.[id];
      btn?.addEventListener?.('click', () => goTo(id));
      // Arrow-key navigation within the rail. The rail is VERTICAL, so
      // Up/Down are the primary keys here (the old tab bar was horizontal and
      // used Left/Right); Left/Right are accepted too so muscle memory from
      // the tab bar still works. Wraps at both ends, matching activateTab's
      // modulo behaviour, and moves focus with the selection so the keyboard
      // user is never left focused on a button that is no longer current.
      btn?.addEventListener?.('keydown', (event) => {
        let nextIndex = null;
        const key = event?.key;
        if (key === 'ArrowDown' || key === 'ArrowRight') {
          nextIndex = (index + 1) % WORKSPACES.length;
        } else if (key === 'ArrowUp' || key === 'ArrowLeft') {
          nextIndex = (index - 1 + WORKSPACES.length) % WORKSPACES.length;
        } else if (key === 'Home') {
          nextIndex = 0;
        } else if (key === 'End') {
          nextIndex = WORKSPACES.length - 1;
        }
        if (nextIndex === null) return;
        event.preventDefault?.();
        const nextId = WORKSPACES[nextIndex];
        goTo(nextId);
        els.navButtons?.[nextId]?.focus?.();
      });
    });
    for (const link of els.utilityLinks || []) {
      const target = link?.getAttribute?.('data-shell-nav');
      if (!target) continue;
      link.addEventListener?.('click', () => goTo(target));
    }
    els.contextCollapseButton?.addEventListener?.('click', () => toggleContextCollapsed());
    els.contextHideButton?.addEventListener?.('click', () => toggleContextCollapsed());
  }

  /** A shallow copy of the current router state (active workspace + context-collapsed flag). */
  function getState() {
    return { ...state };
  }

  /**
   * Entry point: bind listeners once and render the initial state.
   * @param {string} [initialWorkspace] Optional starting workspace id (defaults to 'talk').
   */
  function init(initialWorkspace) {
    bindOnce();
    if (initialWorkspace && isValidWorkspace(initialWorkspace)) {
      state = { ...state, active: initialWorkspace };
    }
    render();
    return getState();
  }

  return { init, goTo, setContextCollapsed, toggleContextCollapsed, getState };
}
