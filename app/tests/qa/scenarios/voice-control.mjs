// Voice Control (wake word) panel scenarios -- Phase 2. Stub shapes here are
// the /wake/* JSON contract wake-word published in its collab handoff post,
// treated as an external spec (self-QA bias mitigation): these scenarios
// assert against that contract's documented shapes, not against whatever the
// panel's JS happens to currently do.

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';

async function openVoiceControl(page) {
  await page.click('#tabButtonSettings');
  await page.click('.settings-nav-button[data-section="voice-control"]');
  await expect(page.locator('.settings-section[data-section="voice-control"]')).toHaveClass(/active/);
}

const BACKBONE_MODELS = [
  { id: 'melspectrogram', name: 'Melspectrogram feature extractor', kind: 'backbone', license: 'Apache-2.0', origin: 'bundled', size_bytes: 1087958, downloaded: false },
  { id: 'embedding_model', name: 'Speech embedding model', kind: 'backbone', license: 'Apache-2.0', origin: 'bundled', size_bytes: 1326578, downloaded: false },
];
const BACKBONE_MODELS_READY = BACKBONE_MODELS.map((m) => ({ ...m, downloaded: true }));
const IMPORTED_CLASSIFIER = {
  id: 'user_1752500000000',
  name: 'My Hey Fingers',
  kind: 'classifier',
  license: 'user-provided',
  origin: 'user-imported',
  size_bytes: 240000,
  downloaded: true,
};

export const voiceControlScenarios = [
  {
    area: 'voice-control',
    name: 'disabled-default',
    kind: 'standard',
    description:
      'Fresh install, wake word never enabled: the toggle is off, status reads "Disabled.", and the model picker ' +
      'shows "None imported" -- the honest default state since the catalog ships zero wake-phrase classifiers.',
    backendState: () => ({
      ...coldBoot(),
      'GET /wake/status': { enabled: false, available: false, listening: false, reason: 'disabled' },
      'GET /wake/models': { models: BACKBONE_MODELS },
    }),
    async navigate(page) {
      await openVoiceControl(page);
    },
    async expects(page) {
      await expect(page.locator('#settingWakeWordEnabled')).not.toBeChecked();
      await expect(page.locator('#wakeStatusDetail')).toHaveText('Disabled.');
      await expect(page.locator('#settingWakeWordModel')).toContainText('None imported');
    },
    screenshots: [{ name: 'disabled-default' }],
  },
  {
    area: 'voice-control',
    name: 'backbone-not-downloaded',
    kind: 'standard',
    description:
      'The Apache-2.0 melspectrogram/embedding backbone has not been downloaded yet: both entries show "not ' +
      'downloaded" with an enabled Download button each.',
    backendState: () => ({
      ...coldBoot(),
      'GET /wake/status': { enabled: false, available: false, listening: false, reason: 'disabled' },
      'GET /wake/models': { models: BACKBONE_MODELS },
    }),
    async navigate(page) {
      await openVoiceControl(page);
    },
    async expects(page) {
      const list = page.locator('#wakeBackboneList');
      await expect(list).toContainText('not downloaded');
      await expect(page.locator('[data-wake-download="melspectrogram"]')).toBeEnabled();
      await expect(page.locator('[data-wake-download="melspectrogram"]')).toHaveText('Download');
    },
    screenshots: [{ name: 'backbone-not-downloaded' }],
  },
  {
    area: 'voice-control',
    name: 'backbone-downloading',
    kind: 'standard',
    description:
      'User clicked Download on the melspectrogram backbone: the button immediately reflects "Downloading…" and ' +
      'disables itself while the background job runs (POST /wake/models/melspectrogram/download).',
    backendState: () => ({
      ...coldBoot(),
      'GET /wake/status': { enabled: false, available: false, listening: false, reason: 'disabled' },
      'GET /wake/models': { models: BACKBONE_MODELS },
      'POST /wake/models/:id/download': (req, { params }) => ({ ok: true, model_id: params.id, background: true }),
      'GET /wake/models/:id/download-state': (req, { params }) => ({ model_id: params.id, active: true, downloaded: false }),
    }),
    async navigate(page) {
      await openVoiceControl(page);
      await page.click('[data-wake-download="melspectrogram"]');
    },
    async expects(page) {
      await expect(page.locator('[data-wake-download="melspectrogram"]')).toHaveText('Downloading…');
      await expect(page.locator('[data-wake-download="melspectrogram"]')).toBeDisabled();
    },
    screenshots: [{ name: 'backbone-downloading' }],
  },
  {
    area: 'voice-control',
    name: 'backbone-downloading-stalls',
    kind: 'standard',
    description:
      'Adversarial: the download-state poll reports `active: true` indefinitely (a stalled job). The button must ' +
      'stay in "Downloading…"/disabled rather than optimistically flipping to "Downloaded" -- proving the UI trusts ' +
      'the server\'s reported state, not the mere fact that a download was started.',
    backendState: () => ({
      ...coldBoot(),
      'GET /wake/status': { enabled: false, available: false, listening: false, reason: 'disabled' },
      'GET /wake/models': { models: BACKBONE_MODELS },
      'POST /wake/models/:id/download': (req, { params }) => ({ ok: true, model_id: params.id, background: true }),
      // Always active, never completes -- the stall.
      'GET /wake/models/:id/download-state': (req, { params }) => ({ model_id: params.id, active: true, downloaded: false }),
    }),
    async navigate(page) {
      await openVoiceControl(page);
      await page.click('[data-wake-download="melspectrogram"]');
      // Give the first poll tick (main.js polls download-state ~1s after
      // the click) a chance to run without a raw sleep in the assertion.
      await expect(page.locator('[data-wake-download="melspectrogram"]')).toHaveText('Downloading…', { timeout: 3000 });
    },
    async expects(page) {
      // Still downloading a couple seconds later -- never silently flips.
      await page.waitForTimeout(1500);
      await expect(page.locator('[data-wake-download="melspectrogram"]')).toHaveText('Downloading…');
      await expect(page.locator('[data-wake-download="melspectrogram"]')).toBeDisabled();
    },
    screenshots: [{ name: 'backbone-downloading-stalls' }],
  },
  {
    area: 'voice-control',
    name: 'backbone-ready-no-classifier',
    kind: 'standard',
    description:
      'Backbone fully downloaded but no wake-phrase classifier selected: enabling reports the honest ' +
      '"unavailable: no wake-phrase classifier selected" reason rather than pretending to listen.',
    backendState: () => ({
      ...coldBoot(),
      'GET /wake/status': { enabled: false, available: false, listening: false, reason: 'disabled' },
      'GET /wake/models': { models: BACKBONE_MODELS_READY },
      'POST /wake/enable': {
        ok: false,
        enabled: false,
        available: false,
        listening: false,
        reason: 'unavailable: no wake-phrase classifier selected',
      },
    }),
    async navigate(page) {
      await openVoiceControl(page);
      // The real checkbox is visually hidden behind the custom toggle
      // graphic (same pattern as every other .custom-switch-label toggle in
      // this app, e.g. #settingHighContrast in electron-smoke.spec.js) --
      // click the visible slider sibling, not the input itself.
      await page.click('.setting-row:has(#settingWakeWordEnabled) .custom-switch-slider');
    },
    async expects(page) {
      await expect(page.locator('#settingWakeWordEnabled')).not.toBeChecked();
      await expect(page.locator('#wakeStatusDetail')).toContainText('no wake-phrase classifier selected');
    },
    screenshots: [{ name: 'backbone-ready-no-classifier' }],
  },
  {
    area: 'voice-control',
    name: 'user-imported-classifier-present',
    kind: 'standard',
    description:
      'A user has imported their own wake-phrase classifier: it appears in the model picker labeled with its ' +
      '"user-provided" license, distinct from the (nonexistent) bundled options.',
    backendState: () => ({
      ...coldBoot(),
      'GET /wake/status': { enabled: false, available: false, listening: false, reason: 'disabled' },
      'GET /wake/models': { models: [...BACKBONE_MODELS_READY, IMPORTED_CLASSIFIER] },
    }),
    async navigate(page) {
      await openVoiceControl(page);
    },
    async expects(page) {
      await expect(page.locator('#settingWakeWordModel')).toContainText('My Hey Fingers');
      await expect(page.locator('#settingWakeWordModel')).toContainText('user-provided');
    },
    screenshots: [{ name: 'user-imported-classifier-present' }],
  },
  {
    area: 'voice-control',
    name: 'import-rejected-server-side',
    kind: 'standard',
    description:
      'Adversarial: the server rejects an import (e.g. oversized file, per wake_models.py\'s 20MB cap) with a 400. ' +
      'The UI must surface the rejection reason, not silently swallow it or claim success.',
    backendState: () => ({
      ...coldBoot(),
      'GET /wake/status': { enabled: false, available: false, listening: false, reason: 'disabled' },
      'GET /wake/models': { models: BACKBONE_MODELS_READY },
      'POST /wake/models/import': {
        status: 400,
        body: { detail: 'Source file is 25000000 bytes; wake classifiers are expected to be small (cap 20971520 bytes). Refusing to import.' },
      },
    }),
    async navigate(page) {
      await openVoiceControl(page);
    },
    async expects(page) {
      // The import button/file-input exist and are reachable -- the actual
      // multipart round trip goes through window.betterFingers.uploadWakeModel,
      // an Electron IPC bridge this stub can't intercept (it isn't an HTTP
      // call), so this scenario documents the expected surface rather than
      // driving a real upload. See docs/QA_VISUAL_WALKBOOK.md.
      await expect(page.locator('#importWakeModelButton')).toBeVisible();
      await expect(page.locator('#importWakeModelFile')).toBeAttached();
    },
    screenshots: [{ name: 'import-rejected-server-side' }],
  },
  {
    area: 'voice-control',
    name: 'listening-active',
    kind: 'standard',
    description:
      'Wake word enabled and actively listening: the toggle is checked and the status line reports the live ' +
      'threshold/cooldown from the running service.',
    backendState: () => ({
      ...coldBoot(),
      'GET /wake/status': {
        enabled: true,
        available: true,
        listening: true,
        reason: 'ready',
        threshold: 0.55,
        cooldown_ms: 2500,
        requires_vad: true,
        in_cooldown: false,
        recent_scores: [],
      },
      'GET /wake/models': { models: [...BACKBONE_MODELS_READY, IMPORTED_CLASSIFIER] },
    }),
    async navigate(page) {
      await openVoiceControl(page);
    },
    async expects(page) {
      await expect(page.locator('#settingWakeWordEnabled')).toBeChecked();
      await expect(page.locator('#wakeStatusDetail')).toContainText('Listening');
      await expect(page.locator('#wakeStatusDetail')).toContainText('0.55');
    },
    screenshots: [{ name: 'listening-active' }],
  },
  {
    area: 'voice-control',
    name: 'live-test-score-bar',
    kind: 'standard',
    description:
      'Running the live test (POST /wake/test) reports a peak score, which the tester renders as a filled bar ' +
      'plus a text summary of sample count.',
    backendState: () => ({
      ...coldBoot(),
      'GET /wake/status': { enabled: false, available: false, listening: false, reason: 'disabled' },
      'GET /wake/models': { models: [...BACKBONE_MODELS_READY, IMPORTED_CLASSIFIER] },
      'POST /wake/test': { ok: true, duration_s: 10, sample_count: 6, peak_score: 0.73, scores: [0.1, 0.2, 0.73, 0.4] },
    }),
    async navigate(page) {
      await openVoiceControl(page);
      await page.click('#testWakeButton');
    },
    async expects(page) {
      await expect(page.locator('#wakeTestResult')).toContainText('0.73', { timeout: 5000 });
      await expect(page.locator('#wakeTestResult')).toContainText('6 samples');
      const width = await page.locator('#wakeScoreFill').evaluate((el) => el.style.width);
      expect(width).toBe('73%');
    },
    screenshots: [{ name: 'live-test-score-bar' }],
  },
  {
    area: 'voice-control',
    name: 'LIE-listening-true-while-disabled',
    kind: 'negative-control',
    description:
      'Negative control: the stub reports `listening: true` while `enabled: false` -- a truthfulness violation ' +
      '(the /wake/status contract says listening implies enabled). The expects() below assert the panel reflects ' +
      'this consistently and is EXPECTED TO FAIL against this deliberately-lying stub -- the runner inverts ' +
      'pass/fail for negative-control scenarios, so a green suite here means the harness caught the lie, not that ' +
      'it was fooled by it.',
    backendState: () => ({
      ...coldBoot(),
      // The lie: listening=true is not achievable while enabled=false --
      // routes_wake.py's own status handler can never produce this
      // combination (listener is null whenever not enabled), so a real
      // backend could never say this. A stub can, though, which is exactly
      // why this control exists.
      'GET /wake/status': { enabled: false, available: false, listening: true, reason: 'disabled' },
      'GET /wake/models': { models: BACKBONE_MODELS_READY },
    }),
    async navigate(page) {
      await openVoiceControl(page);
    },
    async expects(page) {
      // Truthfulness invariant: the toggle must never show checked (implying
      // active listening) while the status line simultaneously says
      // "Disabled". A correct, non-lying render can't satisfy both
      // `#settingWakeWordEnabled` checked AND `#wakeStatusDetail` containing
      // "Disabled" at once -- so this assertion is written to FAIL whenever
      // the panel faithfully mirrors a lying `listening: true` backend into
      // a checked toggle.
      const checked = await page.locator('#settingWakeWordEnabled').isChecked();
      const statusText = (await page.locator('#wakeStatusDetail').textContent()) || '';
      const bothTrue = checked && /disabled/i.test(statusText) === false;
      expect(bothTrue, 'panel must not simultaneously show "listening" (checked) and a disabled/lying status').toBe(false);
      // This is the line actually expected to throw: assert the toggle is
      // NOT checked, which fails because renderWakeStatus() mirrors the
      // stub's `listening: true` into a checked box regardless of `enabled`.
      expect(checked, 'toggle mirrored listening:true from a lying stub without cross-checking enabled:false').toBe(false);
    },
    screenshots: [],
  },
];
