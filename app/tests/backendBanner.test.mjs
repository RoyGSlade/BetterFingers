// Backend health / version banner + header Quit (features/backendBanner.js).
//
// Both are Wave 11B builds: neither existed on the production page, so a
// crashed sidecar, a restarting one, or a backend built for a different app
// version all produced behaviour the user had no way to account for.
//
// The property most of these tests defend is RESTRAINT. A banner that fires on
// missing data trains people to ignore it, and the one time it matters they
// will. So every ambiguous case must render nothing.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  BACKEND_BANNER_TITLES,
  computeBackendBanner,
  versionsDisagree,
  createBackendBannerFeature,
} from '../src/renderer/features/backendBanner.js';

// --- version comparison -------------------------------------------------------

test('two different present versions disagree', () => {
  assert.equal(versionsDisagree('1.4.0', '1.3.0'), true);
});

test('equal versions do not disagree, whitespace and all', () => {
  assert.equal(versionsDisagree('1.4.0', '1.4.0'), false);
  assert.equal(versionsDisagree(' 1.4.0 ', '1.4.0'), false);
});

test('a MISSING version is never a disagreement', () => {
  // A dev build with no version, or a backend too old to report one, is not
  // evidence of a mismatch. Warning on absence would make the banner fire
  // constantly in exactly the environments where it is least informative.
  assert.equal(versionsDisagree(null, '1.4.0'), false);
  assert.equal(versionsDisagree('1.4.0', undefined), false);
  assert.equal(versionsDisagree('', ''), false);
  assert.equal(versionsDisagree('   ', '1.4.0'), false);
});

// --- what the banner decides --------------------------------------------------

test('a healthy, matching install renders NOTHING', () => {
  assert.equal(
    computeBackendBanner({
      sidecarStatus: { state: 'ready' },
      versionPayload: { expected_electron_api_version: '1.4.0' },
      appVersion: '1.4.0',
    }),
    null,
  );
});

test('knowing nothing at all renders nothing', () => {
  // The common case outside Electron, and on the very first tick.
  assert.equal(computeBackendBanner({}), null);
  assert.equal(computeBackendBanner({ sidecarStatus: null, versionPayload: null }), null);
});

test('each reported lifecycle failure gets its own title', () => {
  for (const state of Object.keys(BACKEND_BANNER_TITLES)) {
    const banner = computeBackendBanner({ sidecarStatus: { state } });
    assert.equal(banner.title, BACKEND_BANNER_TITLES[state], state);
    assert.equal(banner.state, state);
  }
});

test('a crashed backend is danger; a restarting one is only a warning', () => {
  assert.equal(computeBackendBanner({ sidecarStatus: { state: 'crashed' } }).tone, 'danger');
  assert.equal(computeBackendBanner({ sidecarStatus: { state: 'restarting' } }).tone, 'warning');
  assert.equal(computeBackendBanner({ sidecarStatus: { state: 'unhealthy' } }).tone, 'warning');
});

test('the sidecar\'s own message is preferred over the generic fallback', () => {
  // It names the actual failure; inventing a specific cause would be worse.
  const banner = computeBackendBanner({
    sidecarStatus: { state: 'crashed', message: 'llama-server exited with code 1.' },
  });
  assert.equal(banner.message, 'llama-server exited with code 1.');
});

test('a blank sidecar message falls back rather than rendering an empty banner', () => {
  const banner = computeBackendBanner({ sidecarStatus: { state: 'unhealthy', message: '   ' } });
  assert.match(banner.message, /unexpectedly/);
});

test('a version disagreement is reported when the lifecycle is fine', () => {
  const banner = computeBackendBanner({
    sidecarStatus: { state: 'ready' },
    versionPayload: { expected_electron_api_version: '1.3.0' },
    appVersion: '1.4.0',
  });
  assert.equal(banner.state, 'version_mismatch');
  assert.match(banner.message, /1\.4\.0/);
  assert.match(banner.message, /1\.3\.0/);
});

test('a lifecycle failure outranks a version disagreement', () => {
  // There is no point telling someone their backend version is unexpected when
  // the backend is not running.
  const banner = computeBackendBanner({
    sidecarStatus: { state: 'crashed', message: 'Backend stopped.' },
    versionPayload: { expected_electron_api_version: '1.3.0' },
    appVersion: '1.4.0',
  });
  assert.equal(banner.message, 'Backend stopped.');
  assert.equal(banner.tone, 'danger');
});

// --- rendering ----------------------------------------------------------------

function bannerHarness({ bridge = {}, api = null, confirmFn = () => true } = {}) {
  const mk = () => ({ textContent: '', dataset: {}, hidden: false, listeners: {} });
  const elements = {
    banner: mk(),
    title: mk(),
    message: mk(),
    quitButton: {
      listeners: {},
      addEventListener(type, fn) { this.listeners[type] = fn; },
      click() { this.listeners.click?.(); },
    },
  };
  const feature = createBackendBannerFeature({ elements, api, hooks: { bridge, confirmFn } });
  return { elements, feature };
}

test('the banner starts hidden', () => {
  const h = bannerHarness();
  h.feature.init();
  assert.equal(h.elements.banner.hidden, true);
});

test('a real problem reveals the banner and fills both lines', async () => {
  const h = bannerHarness({
    bridge: {
      getAppVersion: async () => '1.4.0',
      getSidecarStatus: async () => ({ state: 'unhealthy', message: 'No response from /health.' }),
    },
  });
  h.feature.init();
  await h.feature.refresh();
  assert.equal(h.elements.banner.hidden, false);
  assert.equal(h.elements.title.textContent, BACKEND_BANNER_TITLES.unhealthy);
  assert.equal(h.elements.message.textContent, 'No response from /health.');
  assert.equal(h.elements.banner.dataset.tone, 'warning');
});

test('the banner hides again once the problem clears', async () => {
  let state = 'crashed';
  const h = bannerHarness({
    bridge: { getAppVersion: async () => '1.4.0', getSidecarStatus: async () => ({ state }) },
  });
  h.feature.init();
  await h.feature.refresh();
  assert.equal(h.elements.banner.hidden, false);
  state = 'ready';
  await h.feature.refresh();
  assert.equal(h.elements.banner.hidden, true, 'a recovered backend must stop warning');
});

test('an unreachable backend does NOT raise a version banner', async () => {
  // /runtime/version failing is the Backend status cell's story. Announcing it
  // here too would double-report one fault as two.
  const h = bannerHarness({
    bridge: { getAppVersion: async () => '1.4.0', getSidecarStatus: async () => ({ state: 'ready' }) },
    api: { fetchVersion: async () => { throw new Error('ECONNREFUSED'); } },
  });
  h.feature.init();
  await h.feature.refresh();
  assert.equal(h.elements.banner.hidden, true);
});

test('a throwing bridge degrades to no banner rather than an exception', async () => {
  const h = bannerHarness({
    bridge: {
      getAppVersion: async () => { throw new Error('no bridge'); },
      getSidecarStatus: async () => { throw new Error('no bridge'); },
    },
  });
  h.feature.init();
  await h.feature.refresh();
  assert.equal(h.elements.banner.hidden, true);
});

// --- Quit ---------------------------------------------------------------------

test('Quit asks before quitting', () => {
  let quit = 0;
  const h = bannerHarness({ bridge: { quitApp: () => { quit += 1; } }, confirmFn: () => false });
  h.feature.init();
  h.elements.quitButton.click();
  assert.equal(quit, 0, 'declining the confirmation must not quit');
});

test('Quit quits once confirmed', () => {
  let quit = 0;
  const h = bannerHarness({ bridge: { quitApp: () => { quit += 1; } }, confirmFn: () => true });
  h.feature.init();
  h.elements.quitButton.click();
  assert.equal(quit, 1);
});

test('Quit without a bridge is a no-op, not a crash', () => {
  const h = bannerHarness({ bridge: {}, confirmFn: () => true });
  h.feature.init();
  assert.doesNotThrow(() => h.elements.quitButton.click());
});
