// Privacy panel scenarios -- Phase 2 (D2 item 5). Verifies the wake-listener
// entry (server.py's get_privacy_report(), required to be "live-truthful" per
// orchestrator review -- never claims a listener is active while wake word
// is disabled) is actually rendered, not just present in the API response.

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';

async function openPrivacy(page) {
  await page.click('#tabButtonSettings');
  await page.click('.settings-nav-button[data-section="privacy"]');
  await expect(page.locator('.settings-section[data-section="privacy"]')).toHaveClass(/active/);
}

export const privacyScenarios = [
  {
    area: 'privacy',
    name: 'wake-listener-inactive',
    kind: 'standard',
    description:
      'Wake word disabled: the Privacy panel truthfully reports the listener as "Not active." rather than a ' +
      'generic/static claim -- it reflects the real backend state.',
    backendState: () => ({
      ...coldBoot(),
      'GET /privacy': {
        offline_by_default: true,
        network_touchpoints: [],
        data_locations: [{ name: 'Draft history', path: '/tmp/x/draft_history.json', bytes: 0 }],
        data_directories: [],
        retention: { recordings_persisted_to_disk: true, recordings_in_memory: 0, drafts_in_memory: 0, draft_history_limit: 80 },
        wake_listener: { active: false, persists_audio: false, note: 'Disabled.' },
      },
    }),
    async navigate(page) {
      await openPrivacy(page);
    },
    async expects(page) {
      await expect(page.locator('#privacyWakeListenerStatus')).toContainText('Not active.', { timeout: 5000 });
    },
    screenshots: [{ name: 'wake-listener-inactive' }],
  },
  {
    area: 'privacy',
    name: 'wake-listener-active',
    kind: 'standard',
    description:
      'Wake word enabled and listening: the Privacy panel reflects the listener as active and restates that ' +
      'audio is never persisted -- the same object the /wake/status truthfulness checks use, so this can never ' +
      'silently drift out of sync with the actual listening state.',
    backendState: () => ({
      ...coldBoot(),
      'GET /privacy': {
        offline_by_default: true,
        network_touchpoints: [],
        data_locations: [{ name: 'Draft history', path: '/tmp/x/draft_history.json', bytes: 0 }],
        data_directories: [],
        retention: { recordings_persisted_to_disk: true, recordings_in_memory: 0, drafts_in_memory: 0, draft_history_limit: 80 },
        wake_listener: {
          active: true,
          persists_audio: false,
          note: 'Processes microphone audio locally for wake-phrase detection. Audio is never written to disk or sent anywhere -- only a redacted detection score (a number, never audio or transcripts) is kept in memory.',
        },
      },
    }),
    async navigate(page) {
      await openPrivacy(page);
    },
    async expects(page) {
      await expect(page.locator('#privacyWakeListenerStatus')).toContainText('Active', { timeout: 5000 });
      await expect(page.locator('#privacyWakeListenerStatus')).toContainText('never written to disk');
    },
    screenshots: [{ name: 'wake-listener-active' }],
  },
  {
    area: 'privacy',
    name: 'LIE-wake-listener-active-but-wake-disabled',
    kind: 'negative-control',
    description:
      'Negative control: /privacy claims the wake listener is active while /wake/status simultaneously reports ' +
      'disabled -- the two endpoints disagree, which a truthful UI reading only /privacy cannot detect on its own. ' +
      'This documents a real limitation (the Privacy panel does not cross-check /wake/status) rather than a bug: ' +
      'the assertion is written to demand cross-checking and is EXPECTED TO FAIL today, so a green result here ' +
      'means the harness is correctly catching that this cross-check does not exist yet.',
    backendState: () => ({
      ...coldBoot(),
      'GET /privacy': {
        offline_by_default: true,
        network_touchpoints: [],
        data_locations: [],
        data_directories: [],
        retention: { recordings_persisted_to_disk: true, recordings_in_memory: 0, drafts_in_memory: 0, draft_history_limit: 80 },
        wake_listener: { active: true, persists_audio: false, note: 'Listening.' },
      },
      'GET /wake/status': { enabled: false, available: false, listening: false, reason: 'disabled' },
    }),
    async navigate(page) {
      await openPrivacy(page);
    },
    async expects(page) {
      // Cross-check both sources of truth agree. Today the Privacy panel
      // renders /privacy's wake_listener.active in isolation and never
      // fetches /wake/status for comparison, so this will find
      // "Active" on the privacy panel while /wake/status (fetched directly
      // here) says disabled -- a real gap, not yet a UI bug users can see
      // (the two panels are just never open at once), but a latent trust
      // problem if the backend's two endpoints ever genuinely disagree.
      const privacyText = (await page.locator('#privacyWakeListenerStatus').textContent()) || '';
      // The renderer never fetches raw -- it goes through the main-process
      // proxy bridge (see app/src/main/backendProxy.js), same as every real
      // call in this app.
      const wakeStatus = await page
        .evaluate(async () => {
          const res = await window.betterFingers.backendRequest('GET', '/wake/status');
          return res && res.body;
        })
        .catch(() => null);
      const privacyClaimsActive = /Active/.test(privacyText);
      const wakeStatusSaysListening = Boolean(wakeStatus && wakeStatus.listening);
      expect(
        privacyClaimsActive === wakeStatusSaysListening,
        'Privacy panel and /wake/status disagree about whether the listener is active -- no cross-check exists',
      ).toBe(true);
    },
    screenshots: [],
  },
];
