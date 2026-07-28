// First-run onboarding on the guided-flow shell (stage 13, §4a of
// docs/ui/SIGNAL_DESK_GUIDED_FLOWS.md).
//
// Run with:  BF_QA_UI=signal-desk node tests/qa/run.mjs onboarding
//
// The QA harness has skipped onboarding since it was written, because the
// shipping overlay only appears on a profile that has never completed it and
// there was no way to ask for it. The flow now mounts behind an explicit
// request (`#onboarding`, or window.__onboarding), so it can be driven
// deterministically without touching the real bf_onboarding_complete key.
//
// What these assert is the part that is genuinely visual and genuinely
// dangerous: that the consent gate holds on screen, and that "Decline & quit"
// -- which exits the application -- is nowhere near the button a user is
// repeatedly clicking. Both are claims about pixels, which is what this suite
// is for; the state machine underneath is unit-tested in
// tests/onboardingFlow.test.mjs.
//
// Not asserted here: the speech-models step's data. The preview page hands the
// flow stub hooks rather than the real fetchWhisperModels()/
// fetchModelRecommendation(), so a QA assertion on that content would be
// checking the fixture, not the wiring.

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';

/** Open the flow and step forward `steps` times. */
async function openOnboarding(page, steps = 0) {
  await page.evaluate((n) => {
    window.__onboarding.flow.open();
    for (let i = 0; i < n; i += 1) window.__onboarding.flow.goNext();
  }, steps);
  await expect(page.locator('#sdOnboarding')).toBeVisible();
}

export const onboardingScenarios = [
  {
    area: 'onboarding',
    ui: 'signal-desk',
    name: 'does-not-open-on-a-completed-profile',
    kind: 'standard',
    description:
      'On an ordinary load the onboarding modal is mounted but not shown. This is the regression that ' +
      'would be most expensive to miss: a flow that opens unconditionally would cover every workspace ' +
      'behind a modal on every launch, and would do it to returning users who already gave consent. The ' +
      'assertion checks both halves -- that the module actually mounted (so a silently dead script is not ' +
      'mistaken for correct behaviour) and that the dialog is hidden.',
    backendState: coldBoot,
    async navigate(_page) {},
    async expects(page) {
      const mounted = await page.evaluate(() => typeof window.__onboarding === 'object');
      expect(mounted, 'onboarding module did not mount -- "hidden" would pass vacuously').toBe(true);
      await expect(page.locator('#sdOnboarding')).toBeHidden();
      await expect(page.locator('.sd-shell')).toBeVisible();
    },
    screenshots: [{ name: 'does-not-open-on-a-completed-profile' }],
  },
  {
    area: 'onboarding',
    ui: 'signal-desk',
    name: 'consent-gates-the-forward-action',
    kind: 'standard',
    description:
      'Step 2 is the consent gate. The forward button renders visibly disabled until the checkbox is ' +
      'ticked, and ticking it enables the button without a re-render. Visibility is asserted explicitly ' +
      'rather than relying on toBeDisabled(), which is satisfied by a hidden element and would let a gate ' +
      'that never painted pass this scenario.',
    backendState: coldBoot,
    async navigate(page) {
      await openOnboarding(page, 1);
    },
    async expects(page) {
      const primary = page.locator('#sdOnboarding [data-flow-primary]');
      const consent = page.locator('#sdOnboardConsent');

      await expect(page.locator('#sdOnboarding [data-flow-title]')).toHaveText('Your data stays on this device');
      await expect(consent).toBeVisible();
      await expect(primary).toBeVisible();
      await expect(primary).toHaveText('Accept & continue');
      await expect(primary).toBeDisabled();

      // Back appears from step 2 onward; it is hidden on step 1.
      await expect(page.locator('#sdOnboarding [data-flow-back]')).toBeVisible();

      await consent.check();
      await expect(primary).toBeEnabled();
    },
    screenshots: [{ name: 'consent-gates-the-forward-action' }],
  },
  {
    area: 'onboarding',
    ui: 'signal-desk',
    name: 'decline-and-quit-is-separated-from-next',
    kind: 'standard',
    description:
      '"Decline & quit" exits the application. It sits hard left in the footer, a full spacer away from the ' +
      'forward button that a user clicks four times in a row, so a mis-click cannot land on it. This is a ' +
      'geometric claim, so it is measured rather than eyeballed: the gap between the two controls is ' +
      'asserted to be a substantial fraction of the card, which a future footer reflow would break loudly ' +
      'instead of silently.',
    backendState: coldBoot,
    async navigate(page) {
      await openOnboarding(page, 0);
    },
    async expects(page) {
      const quit = page.locator('#sdOnboardDecline');
      const primary = page.locator('#sdOnboarding [data-flow-primary]');
      await expect(quit).toBeVisible();
      await expect(quit).toHaveText('Decline & quit');

      const [quitBox, primaryBox, cardBox] = await Promise.all([
        quit.boundingBox(),
        primary.boundingBox(),
        page.locator('#sdOnboarding .sd-flow__card').boundingBox(),
      ]);

      const gap = primaryBox.x - (quitBox.x + quitBox.width);
      expect(gap, 'Decline & quit is adjacent to the forward button').toBeGreaterThan(cardBox.width * 0.3);
      // Same row, so this is genuinely a horizontal separation and not two
      // buttons that merely happen to be far apart on different lines.
      expect(Math.abs(quitBox.y - primaryBox.y)).toBeLessThan(8);
    },
    screenshots: [{ name: 'decline-and-quit-is-separated-from-next' }],
  },
  {
    area: 'onboarding',
    ui: 'signal-desk',
    name: 'escape-cannot-dismiss-the-consent-gate',
    kind: 'standard',
    description:
      'Onboarding is the one flow declared non-dismissible, and there is deliberately no close button in ' +
      'its markup. Escape is swallowed rather than passed through, so the keystroke neither closes this ' +
      'dialog nor reaches whatever is behind it. Without this, consent would have a back door that no ' +
      'amount of correct button wiring would close.',
    backendState: coldBoot,
    async navigate(page) {
      await openOnboarding(page, 1);
    },
    async expects(page) {
      await page.keyboard.press('Escape');
      await expect(page.locator('#sdOnboarding')).toBeVisible();
      await expect(page.locator('#sdOnboarding [data-flow-close]')).toHaveCount(0);
    },
    screenshots: [{ name: 'escape-cannot-dismiss-the-consent-gate' }],
  },
];
