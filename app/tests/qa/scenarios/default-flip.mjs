// Wave 11 (Gate 11): the default flip itself.
//
// Every other `ui: 'signal-desk-prod'` scenario proves something ABOUT the
// production page. This file proves the thing the flip actually changed: that
// the page a user gets with NO BF_UI set at all is the production Signal Desk
// composition root, and not index.html.
//
// That property is carried by the harness, not by anything in here: the
// `signal-desk-prod` UI target's `env` is now deliberately `{}` (see
// harness.mjs), so this suite launches Electron with BF_UI genuinely unset.
// If windows.js's dashboardPage() ever goes back to defaulting to
// index.html, every assertion below fails at once -- the shell selector, the
// status-bar readiness cell, and the identity check.
//
// Run with:  cd app && node tests/qa/run.mjs default-flip
// (no BF_QA_UI: that IS the test)

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';
import { TARGET } from '../harness.mjs';

export const defaultFlipScenarios = [
  {
    area: 'default-flip',
    ui: 'signal-desk-prod',
    name: 'app-boots-to-signal-desk-with-no-bf-ui',
    kind: 'standard',
    description:
      'With BF_UI unset -- the state every shipping user is in -- the app must open the production Signal Desk ' +
      'composition root (signal-desk.html), not the legacy index.html dashboard. This is the Wave 11 default flip, ' +
      'and it is asserted three independent ways because any one of them alone could pass for the wrong reason: ' +
      'the launched target must carry an EMPTY env (so the run really did not ask for a page), the document URL ' +
      'must end in signal-desk.html, and the page must present the Signal Desk shell while presenting NONE of ' +
      "index.html's four tab buttons. The last check is the load-bearing one: the two dashboards share no element " +
      'ids, so "legacy tab buttons absent AND .sd-shell present" cannot both hold on the wrong page.',
    backendState: coldBoot,
    async navigate(page) {
      await expect(page.locator('.sd-shell')).toBeAttached();
    },
    async expects(page) {
      // 1. The run genuinely did not request a page. Without this, a harness
      //    that quietly kept BF_UI=signal-desk-prod would make the rest of
      //    this scenario pass while proving nothing about the DEFAULT.
      expect(
        TARGET.env,
        'the signal-desk-prod QA target must launch with an EMPTY env so this asserts the DEFAULT route',
      ).toEqual({});
      expect(TARGET.page).toBe('signal-desk.html');

      // 2. The document that actually loaded.
      const url = await page.evaluate(() => document.location.pathname);
      expect(url, `expected the default page to be signal-desk.html, got ${url}`).toMatch(
        /signal-desk\.html$/,
      );
      expect(url, 'the legacy page must not be what an unset BF_UI opens').not.toMatch(
        /index\.html$/,
      );

      // 3. Signal Desk is present and the legacy dashboard is not. Checked by
      //    id rather than by looks: index.html's tab buttons exist nowhere in
      //    signal-desk.html, so their absence is a real identity signal.
      await expect(page.locator('.sd-shell')).toHaveCount(1);
      for (const legacyId of [
        '#tabButtonDashboard',
        '#tabButtonSettings',
        '#tabButtonModels',
        '#tabButtonDiagnostics',
      ]) {
        await expect(
          page.locator(legacyId),
          `${legacyId} belongs to index.html and must not be on the default page`,
        ).toHaveCount(0);
      }
      // The five Signal Desk workspaces, which index.html has none of.
      for (const nav of ['talk', 'library', 'studio', 'utilities', 'settings']) {
        await expect(page.locator(`.sd-nav__button[data-nav="${nav}"]`)).toHaveCount(1);
      }
    },
    screenshots: [{ name: 'app-boots-to-signal-desk-with-no-bf-ui' }],
  },
  {
    area: 'default-flip',
    ui: 'legacy',
    name: 'legacy-page-is-still-reachable-for-rollback',
    kind: 'standard',
    description:
      'The rollback half of the flip. BF_UI=legacy must still open index.html and render a working legacy ' +
      'dashboard, because that is the revert path if Signal Desk has to be backed out in the field -- a rollback ' +
      'route that was never exercised is not a rollback route. Asserted as the mirror image of the default-flip ' +
      'scenario above: the legacy tab strip present, the Signal Desk shell absent, and the backend status cell ' +
      'reporting real backend state rather than sitting at its placeholder.',
    backendState: coldBoot,
    async navigate(page) {
      await expect(page.locator('#backendStatus')).toBeAttached();
    },
    async expects(page) {
      expect(TARGET.env, 'the legacy target must ask for index.html explicitly').toEqual({
        BF_UI: 'legacy',
      });
      const url = await page.evaluate(() => document.location.pathname);
      expect(url).toMatch(/index\.html$|\/$/);

      await expect(page.locator('.sd-shell')).toHaveCount(0);
      for (const legacyId of [
        '#tabButtonDashboard',
        '#tabButtonSettings',
        '#tabButtonModels',
        '#tabButtonDiagnostics',
      ]) {
        await expect(page.locator(legacyId)).toHaveCount(1);
      }
      await expect(page.locator('#backendStatus')).not.toHaveText('—');
    },
    screenshots: [{ name: 'legacy-page-is-still-reachable-for-rollback' }],
  },
];
