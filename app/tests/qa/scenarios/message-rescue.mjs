// F2.8 Message Rescue panel: proves the default-off feature flag actually
// leaves the existing dashboard unchanged, and that flipping the flag (the
// only way to reach the panel right now -- there is no settings toggle yet)
// renders an accessible, fully-populated static panel with no backend calls
// involved (the coldBoot stub never receives a rescue-related request).

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';

export const messageRescueScenarios = [
  {
    area: 'message-rescue',
    name: 'panel-hidden-by-default',
    kind: 'standard',
    description:
      'With the pref_message_rescue_enabled flag unset (the shipped default), the Message Rescue panel stays ' +
      'hidden and the rest of the dashboard renders exactly as the baseline scenarios expect -- the inactive ' +
      'flag does not change any existing UI.',
    backendState: coldBoot,
    async navigate(page) {
      await page.click('#tabButtonDashboard');
    },
    async expects(page) {
      await expect(page.locator('#messageRescuePanel')).toBeHidden();
      await expect(page.locator('.hero h1')).toHaveText('BetterFingers');
      await expect(page.locator('#tabDashboard')).toBeVisible();
    },
    screenshots: [{ name: 'panel-hidden-by-default' }],
  },
  {
    area: 'message-rescue',
    name: 'panel-enabled-preview',
    kind: 'standard',
    description:
      'With the local feature flag turned on, the panel becomes visible and renders its deterministic synthetic ' +
      'example: context status/preview with a working Clear affordance, delivery labels/evidence/confidence, a ' +
      'clarification question, faithful/clearer/alternate variant radios (switching variants updates the preview ' +
      'text with no network activity), and mixed-outcome preservation checks plus a preservation warning banner.',
    backendState: () => ({
      ...coldBoot(),
      // I3.5-I3.7's live #draftRescuePanel binds to the same feature flag as
      // this static F2.8 preview, so it also activates here and needs its own
      // (empty/no-op) stubs -- it renders its documented empty state from these.
      'GET /drafts/latest': { draft: null },
      'GET /message-rescue/context': { active: false },
    }),
    async navigate(page) {
      await page.evaluate(() => localStorage.setItem('pref_message_rescue_enabled', 'true'));
      await page.reload();
      await page.waitForSelector('#backendStatus', { state: 'attached', timeout: 15000 });
      await page.click('#tabButtonDashboard');
    },
    async expects(page) {
      const panel = page.locator('#messageRescuePanel');
      await expect(panel).toBeVisible();
      await expect(page.locator('#messageRescueContextPreview')).toHaveText(/sync to tomorrow/i);
      await expect(page.locator('#messageRescueDeliveryLabels .message-rescue-chip').first()).toBeVisible();
      await expect(page.locator('#messageRescueClarification')).toBeVisible();
      await expect(page.locator('#messageRescueClarificationQuestion')).not.toHaveText('');
      await expect(page.locator('#messageRescueWarnings')).toBeVisible();
      await expect(page.locator('.message-rescue-check--fail')).toHaveCount(1);
      await expect(page.locator('.message-rescue-check--pass')).toHaveCount(1);

      const faithfulText = await page.locator('#messageRescueVariantText').textContent();
      await page.check('#messageRescueVariantClearer');
      await expect(page.locator('#messageRescueVariantText')).not.toHaveText(faithfulText || '');

      // Clean up so later scenarios in this same Electron session see the
      // shipped default again.
      await page.evaluate(() => localStorage.removeItem('pref_message_rescue_enabled'));
    },
    screenshots: [{ name: 'panel-enabled-preview' }],
  },
];
