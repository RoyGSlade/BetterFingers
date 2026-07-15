// D1 pilot scenarios: baseline settings sweep. Proves the harness end-to-end
// (stub -> real Electron -> assertions -> screenshot -> report) and gives a
// regression net against accidental renderer breakage from the other three
// tier3 sessions' edits. Expanded with the rest of the coverage matrix in
// Phase 2.

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';

export const baselineScenarios = [
  {
    area: 'baseline',
    name: 'dashboard-loads',
    kind: 'standard',
    description:
      'Fresh launch against a cold-boot stub backend: the dashboard tab is active by default, shows the ' +
      '"BetterFingers" hero header, and the backend status badge reflects the stub as ready (the app never ' +
      'spawned a real Python backend -- it detected the stub as "external" and used it directly).',
    backendState: coldBoot,
    async navigate(page) {
      await page.click('#tabButtonDashboard');
    },
    async expects(page) {
      await expect(page.locator('.hero h1')).toHaveText('BetterFingers');
      await expect(page.locator('#tabDashboard')).toBeVisible();
      await expect(page.locator('#backendStatus')).toHaveText(/ready|active|running|external/i);
    },
    screenshots: [{ name: 'dashboard-loads' }],
  },
  {
    area: 'baseline',
    name: 'settings-general-renders',
    kind: 'standard',
    description:
      'Settings tab opens with the General category active by default (every other category hidden). Confirms ' +
      'the settings-nav/settings-section wiring survives whatever the other tier3 sessions changed in main.js.',
    backendState: coldBoot,
    async navigate(page) {
      await page.click('#tabButtonSettings');
    },
    async expects(page) {
      await expect(page.locator('.settings-nav-button[data-section="general"]')).toBeVisible();
      await expect(page.locator('.settings-section[data-section="general"]')).toHaveClass(/active/);
      await expect(page.locator('.settings-section[data-section="recording"]')).toHaveClass(/hidden/);
    },
    screenshots: [{ name: 'settings-general-renders' }],
  },
  {
    area: 'baseline',
    name: 'settings-recording-renders',
    kind: 'standard',
    description:
      'Clicking the Recording nav button switches the active section and hides General -- the same interaction ' +
      'electron-smoke.spec.js exercises, re-verified here against a fully deterministic backend so a failure here ' +
      'means a real renderer regression, not stub/model flakiness.',
    backendState: coldBoot,
    async navigate(page) {
      await page.click('#tabButtonSettings');
      await page.click('.settings-nav-button[data-section="recording"]');
    },
    async expects(page) {
      await expect(page.locator('.settings-section[data-section="recording"]')).toHaveClass(/active/);
      await expect(page.locator('.settings-section[data-section="general"]')).toHaveClass(/hidden/);
    },
    screenshots: [{ name: 'settings-recording-renders' }],
  },
];
