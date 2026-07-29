// backendBanner.js — the production backend health / version-disagreement
// banner, and the header Quit button (Wave 11B).
//
// Both existed only in the legacy page. The version banner is the surface
// that explains a whole class of otherwise baffling behaviour: a sidecar that
// crashed, is restarting, is not answering, or is a DIFFERENT BUILD from the
// app talking to it. Without it the user sees features half-work and has
// nothing to read. Quit is one button on a channel that already
// exists (`window.betterFingers.quitApp()`, the same one the onboarding
// decline path uses).
//
// The rule this module follows is the same one statusBar.js states: never
// invent a value. A banner that cannot establish a real problem does not
// render at all — an always-present "everything might be fine" strip trains
// people to ignore the one time it matters.
//
// TWO INDEPENDENT SOURCES, deliberately not merged into one number:
//
//   1. The sidecar's own lifecycle state (`getSidecarStatus()`), which the
//      MAIN process already computes — including `version_mismatch`, which it
//      derives from the API *schema* version. This module does not re-derive
//      it; re-deriving a verdict its owner already publishes is how two parts
//      of an app end up disagreeing about whether there is a problem.
//   2. An app-version disagreement the sidecar does NOT check: `/runtime/version`
//      reports `expected_electron_api_version` from the single VERSION source
//      (D-0008), and the renderer can ask the main process what version it
//      actually is. A schema-compatible backend built from a different release
//      passes check 1 and fails this one.
//
// Precedence is lifecycle-first: if the backend is crashed, there is no point
// telling the user its version is unexpected.

/** Titles keyed by sidecar lifecycle state — same wording as the legacy page. */
export const BACKEND_BANNER_TITLES = {
  version_mismatch: 'Backend version mismatch:',
  unhealthy: 'Backend not responding:',
  restarting: 'Restarting backend:',
  crashed: 'Backend stopped:',
};

/** States that mean "broken now" rather than "degraded". */
const DANGER_STATES = new Set(['crashed']);

export const BACKEND_BANNER_ELEMENT_IDS = {
  banner: 'sdVersionMismatchBanner',
  title: 'sdBackendBannerTitle',
  message: 'sdBackendBannerMessage',
  quitButton: 'sdQuitButton',
};

/**
 * Are two version strings in genuine disagreement?
 *
 * Anything missing is NOT a disagreement. A dev build with no version, a
 * backend too old to report one, a bridge that is not there — none of those is
 * evidence of a mismatch, and showing a warning for them would make the banner
 * fire constantly in exactly the environments where it is least informative.
 * Only two present, non-equal strings count.
 */
export function versionsDisagree(appVersion, expectedAppVersion) {
  const a = typeof appVersion === 'string' ? appVersion.trim() : '';
  const b = typeof expectedAppVersion === 'string' ? expectedAppVersion.trim() : '';
  if (!a || !b) return false;
  return a !== b;
}

/**
 * Pure "what should the banner say", given everything known.
 *
 * Returns `null` for "render nothing", which is the common and correct case.
 *
 * @param {object} input
 * @param {object} [input.sidecarStatus] from window.betterFingers.getSidecarStatus()
 * @param {object} [input.versionPayload] from GET /runtime/version
 * @param {string} [input.appVersion]     from window.betterFingers.getAppVersion()
 */
export function computeBackendBanner({ sidecarStatus, versionPayload, appVersion } = {}) {
  const state = sidecarStatus?.state;
  const title = BACKEND_BANNER_TITLES[state];
  if (title) {
    return {
      state,
      title,
      // The sidecar's own message names the actual failure; the fallback is
      // deliberately vague because inventing a specific cause would be worse.
      message: (typeof sidecarStatus?.message === 'string' && sidecarStatus.message.trim())
        || 'Some features may behave unexpectedly.',
      tone: DANGER_STATES.has(state) ? 'danger' : 'warning',
    };
  }

  const expected = versionPayload?.expected_electron_api_version;
  if (versionsDisagree(appVersion, expected)) {
    return {
      state: 'version_mismatch',
      title: BACKEND_BANNER_TITLES.version_mismatch,
      message: `This app is version ${String(appVersion).trim()}, but the backend was built for ${String(expected).trim()}. `
        + 'Features added on either side may be missing or behave unexpectedly.',
      tone: 'warning',
    };
  }

  return null;
}

export function collectBackendBannerElements(root) {
  const doc = root || (typeof document !== 'undefined' ? document : null);
  const els = {};
  for (const [key, id] of Object.entries(BACKEND_BANNER_ELEMENT_IDS)) {
    els[key] = doc?.getElementById?.(id) ?? null;
  }
  return els;
}

/**
 * @param {object} deps
 * @param {object} deps.elements from collectBackendBannerElements()
 * @param {object} [deps.api]    backend api module (needs fetchVersion)
 * @param {object} [deps.hooks]
 * @param {object} [deps.hooks.bridge]    defaults to window.betterFingers
 * @param {Function} [deps.hooks.confirmFn] defaults to window.confirm; guards Quit
 */
export function createBackendBannerFeature({ elements = {}, api = null, hooks = {} } = {}) {
  const bridge = hooks.bridge ?? (typeof window !== 'undefined' ? window.betterFingers : undefined);
  const confirmFn = hooks.confirmFn
    || (typeof window !== 'undefined' && window.confirm ? window.confirm.bind(window) : () => true);

  let latest = null;
  // Fetched once: the app's own version cannot change while it is running, and
  // re-asking every poll would be pure noise on the IPC channel.
  let appVersion;

  function render(banner) {
    latest = banner;
    const el = elements.banner;
    if (!el) return banner;
    if (!banner) {
      el.hidden = true;
      delete el.dataset.state;
      return null;
    }
    if (elements.title) elements.title.textContent = banner.title;
    if (elements.message) elements.message.textContent = banner.message;
    el.dataset.tone = banner.tone;
    el.dataset.state = banner.state;
    el.hidden = false;
    return banner;
  }

  async function refresh() {
    if (appVersion === undefined) {
      try {
        appVersion = (await bridge?.getAppVersion?.()) ?? null;
      } catch (_e) {
        appVersion = null;
      }
    }
    let sidecarStatus = null;
    try {
      sidecarStatus = (await bridge?.getSidecarStatus?.()) ?? null;
    } catch (_e) {
      sidecarStatus = null;
    }
    let versionPayload = null;
    try {
      versionPayload = (await api?.fetchVersion?.()) ?? null;
    } catch (_e) {
      // An unreachable backend is the Backend status cell's story to tell, not
      // this banner's. Reporting it here too would double-announce one fault.
      versionPayload = null;
    }
    return render(computeBackendBanner({ sidecarStatus, versionPayload, appVersion }));
  }

  function bindQuit() {
    elements.quitButton?.addEventListener?.('click', () => {
      // Quitting mid-dictation loses the recording, so it asks first — the same
      // courtesy every other destructive action in the app extends.
      if (!confirmFn('Quit BetterFingers?')) return;
      bridge?.quitApp?.();
    });
  }

  function init() {
    bindQuit();
    render(null);
    return { refresh };
  }

  return { init, refresh, render, getState: () => latest };
}
