// First-run setup as a banner in Talk (stage 13, §4b of
// docs/ui/SIGNAL_DESK_GUIDED_FLOWS.md).
//
// Run with:  BF_QA_UI=signal-desk node tests/qa/run.mjs first-run-banner
//
// The claim under test is the one the design turns on: this is live status, so
// it is on screen exactly when something is missing and absent otherwise. Both
// directions matter and they fail in opposite ways -- a banner that never shows
// leaves a new user staring at a dead app with no next step, and a banner that
// always shows tells a fully-configured install it is broken, which is the bug
// this replaced (the old panel latched onto its first failed probe and
// advertised multi-gigabyte downloads on a machine that had everything).
//
// Both states come from the same page and the same module; only the stub's
// answers differ.

import { expect } from '@playwright/test';
// coldBoot is a pristine profile: no llama-server, no LLM, no Whisper.
// readyProfile is its opposite -- everything installed and ready. Both live in
// the shared fixture because the Talk scenarios need the second one too.
import { coldBoot, readyProfile } from './fixtures/cold-boot.mjs';

export const firstRunBannerScenarios = [
  {
    area: 'first-run-banner',
    ui: 'signal-desk',
    name: 'banner-appears-when-models-are-missing',
    kind: 'standard',
    description:
      'On a pristine profile the banner sits at the top of Talk, above the Signal Core, and names each ' +
      'missing piece: runtime, language model, speech model. Talk is where a new user starts and where a ' +
      'missing speech model actually stops them, which is why this is a banner in the workspace rather ' +
      'than a fourth modal. The per-row badges are asserted individually -- an overall "Setup needed" ' +
      'chip would still pass if the checklist underneath rendered blank.',
    backendState: coldBoot,
    async navigate(page) {
      await page.waitForFunction(() => document.getElementById('sdFirstRunPanel')?.hidden === false, null, { timeout: 15000 });
    },
    async expects(page) {
      const panel = page.locator('#sdFirstRunPanel');
      await expect(panel).toBeVisible();
      await expect(page.locator('#sdFirstRunOverallBadge')).toHaveText('Setup needed');
      await expect(page.locator('#sdFirstRunRuntimeBadge')).toHaveText('Missing');
      await expect(page.locator('#sdFirstRunLlmBadge')).toHaveText('Missing');
      await expect(page.locator('#sdFirstRunWhisperBadge')).toHaveText('Missing');

      // Both downloads must be actionable, not just described.
      await expect(page.locator('#sdFirstRunDownloadLlmButton')).toBeEnabled();
      await expect(page.locator('#sdFirstRunDownloadWhisperButton')).toBeEnabled();

      // Above the Signal Core, per the design -- not tucked below the fold.
      const [bannerBox, coreBox] = await Promise.all([
        panel.boundingBox(),
        page.locator('#workspace-talk .sd-signal-core-wrap').boundingBox(),
      ]);
      expect(bannerBox.y).toBeLessThan(coreBox.y);
    },
    screenshots: [{ name: 'banner-appears-when-models-are-missing' }],
  },
  {
    area: 'first-run-banner',
    ui: 'signal-desk',
    name: 'banner-is-absent-when-everything-is-installed',
    kind: 'standard',
    description:
      'With every model installed the banner is not rendered at all. This is the regression that shipped ' +
      'in the dashboard panel: it advertised "Get BetterFingers set up" on a working install with 150 ' +
      'drafts of history. The assertion waits for the checklist to have actually run before checking, so ' +
      'a banner that is merely slow to appear cannot pass as one that correctly stayed away.',
    backendState: readyProfile,
    async navigate(page) {
      await page.waitForFunction(
        async () => {
          const status = await window.__firstRun?.refreshStatus();
          return status?.ready === true;
        },
        null,
        { timeout: 15000 },
      );
    },
    async expects(page) {
      await expect(page.locator('#sdFirstRunPanel')).toBeHidden();
      // ...and Talk is genuinely usable, not merely uncluttered.
      await expect(page.locator('#workspace-talk .sd-signal-core-wrap')).toBeVisible();
    },
    screenshots: [{ name: 'banner-is-absent-when-everything-is-installed' }],
  },
];
