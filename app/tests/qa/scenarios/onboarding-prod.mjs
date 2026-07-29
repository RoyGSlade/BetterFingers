// Durable-consent onboarding on the PRODUCTION Signal Desk composition root
// (signal-desk.html), as distinct from onboarding.mjs's preview-page
// scenarios (docs/ui/SIGNAL_DESK_GUIDED_FLOWS.md stage 13 §4a).
//
// Run with (BETTERFINGERS_DATA_DIR is not optional -- see below):
//   BETTERFINGERS_DATA_DIR=/tmp/some-throwaway-dir \
//     BF_QA_UI=signal-desk-prod node tests/qa/run.mjs onboarding-prod
//
// Why this file exists alongside onboarding.mjs, not instead of it: the
// preview page opens the flow through a debug handle (window.__onboarding),
// which does not exist on the production page and must not be added to it --
// see harness.mjs's UI_TARGETS comment and the rule this task was given.
// signal-desk.html's real gate (bootstrap/signalDeskApp.js, "Onboarding +
// first-run panel") is wired to the ACTUAL durable record in
// app/src/main/onboardingStore.js, read only through IPC
// (onboarding:get-state / onboarding:migrate-legacy). There is no seam to
// call into from here except the one a real user has: the file on disk and
// the legacy localStorage flag. harness.mjs's enterFirstRunState() and
// enterCompletedProfileState() drive exactly those two -- deleting or writing
// <BETTERFINGERS_DATA_DIR>/onboarding.json and toggling
// bf_onboarding_complete -- which is why every scenario below needs
// BETTERFINGERS_DATA_DIR set: without it those helpers refuse outright rather
// than risk operating on a developer's real profile (see their comments in
// harness.mjs).
//
// What is genuinely different from the preview suite, not just relocated:
// scenario 2 asserts the gate is visible WITHOUT ANYONE HAVING OPENED IT --
// on the preview page every scenario calls window.__onboarding.flow.open()
// itself, so "the dialog is visible" only ever proves the debug hook works.
// Here nothing opens anything; the dialog is visible because
// resolveOnboardingGate() read an empty durable record and decided to show
// it, which is the actual first-run behaviour a real user hits. Scenario 1b
// proves the OTHER real path to a closed gate -- the one-shot legacy-flag
// migration -- which the preview suite has no way to exercise at all (it has
// no durable record to migrate away from).
//
// Stranding the shared Electron window: every scenario here calls
// enterFirstRunState() or enterCompletedProfileState() as the FIRST thing in
// its own navigate(), and both of those helpers reload the page themselves
// before returning. run.mjs's runScenario() also reloads (resetBackendState)
// before every scenario's navigate() runs at all. A reload is a real
// navigation -- it discards the previous scenario's JS/DOM state outright,
// including any open dialog, checked checkbox, or focus trap -- so no
// scenario below needs to explicitly close the modal or restore a completed
// profile before finishing for the run to survive. The one thing that would
// actually break this: if some future scenario's readiness wait (attachedSelector
// '.sd-shell', readyTextSelector '#sdStatusSttValue') lived INSIDE the
// #sdOnboarding subtree, a stuck-open modal could plausibly block it. It does
// not -- .sd-shell and the status bar are siblings of the dialog, not
// descendants, so a modal left open by a prior scenario cannot hang the next
// one's reload-and-wait.
//
// #sdOnboardDecline is never clicked anywhere in this file: it calls
// consent.decline(), which quits the running Electron app outright (see
// onboardingConsent.js's header comment) and would kill the rest of the QA
// run, not just this scenario.

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';
import { enterFirstRunState, enterCompletedProfileState } from '../harness.mjs';

export const onboardingProdScenarios = [
  {
    area: 'onboarding-prod',
    ui: 'signal-desk-prod',
    name: 'does-not-open-on-a-completed-profile',
    kind: 'standard',
    description:
      'On a profile with a durable, accepted onboarding.json, the modal never opens. This is the ' +
      'production equivalent of the regression the preview suite guards against, but proved against ' +
      'the real gate instead of a debug hook: resolveOnboardingGate() reads the seeded accepted record ' +
      'over IPC and reports show:false, and nothing here ever called flow.open() itself. A flow that ' +
      'opened unconditionally would cover every workspace behind a modal on every launch, including for ' +
      'returning users whose consent is already on disk.',
    backendState: coldBoot,
    async navigate(page) {
      await enterCompletedProfileState(page, { via: 'record' });
    },
    async expects(page) {
      await expect(page.locator('#sdOnboarding')).toBeHidden();
      await expect(page.locator('.sd-shell')).toBeVisible();
    },
    screenshots: [{ name: 'does-not-open-on-a-completed-profile' }],
  },
  {
    area: 'onboarding-prod',
    ui: 'signal-desk-prod',
    name: 'does-not-open-after-legacy-flag-migration',
    kind: 'standard',
    description:
      'The other real way a profile ends up "already consented": no onboarding.json exists yet, but the ' +
      'legacy bf_onboarding_complete flag is true from before the durable store existed. ' +
      'resolveOnboardingGate() runs migrateLegacyCompletion() exactly once in that situation, which durably ' +
      'writes an accepted record and reports show:false without ever showing the gate to a returning user ' +
      'who had already finished it under the old, renderer-local scheme. The preview suite cannot exercise ' +
      'this path at all -- it has no durable record to migrate away from -- so this is new coverage, not a ' +
      'relocation of an existing scenario.',
    backendState: coldBoot,
    async navigate(page) {
      await enterCompletedProfileState(page, { via: 'legacy-flag' });
    },
    async expects(page) {
      await expect(page.locator('#sdOnboarding')).toBeHidden();
      await expect(page.locator('.sd-shell')).toBeVisible();
    },
    screenshots: [{ name: 'does-not-open-after-legacy-flag-migration' }],
  },
  {
    area: 'onboarding-prod',
    ui: 'signal-desk-prod',
    name: 'consent-gates-the-forward-action',
    kind: 'standard',
    description:
      'On a genuine first run -- no durable record, no legacy flag -- the gate is visible without anyone ' +
      'having opened it: resolveOnboardingGate() read an empty record and decided to show it, which is the ' +
      'literal absence of consent driving the UI rather than a QA debug hook simulating that decision. ' +
      'From there this matches the preview scenario\'s claim about step 2: the forward button renders ' +
      'visibly disabled until the checkbox is ticked, and ticking it enables the button without a ' +
      're-render. Visibility is asserted explicitly rather than relying on toBeDisabled(), which is ' +
      'satisfied by a hidden element and would let a gate that never painted pass this scenario.',
    backendState: coldBoot,
    async navigate(page) {
      await enterFirstRunState(page);
      await expect(page.locator('#sdOnboarding'), 'the gate must show itself -- nothing here opened it').toBeVisible();
      await page.locator('#sdOnboarding [data-flow-primary]').click();
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
    area: 'onboarding-prod',
    ui: 'signal-desk-prod',
    name: 'decline-and-quit-is-separated-from-next',
    kind: 'standard',
    description:
      '"Decline & quit" exits the application -- calling it here would kill the shared Electron window and ' +
      'every scenario after this one, so this scenario only ever measures its position and never clicks it. ' +
      'It sits hard left in the footer, a full spacer away from the forward button a user clicks four times ' +
      'in a row, so a mis-click cannot land on it. This is a geometric claim, so it is measured rather than ' +
      'eyeballed: the gap between the two controls is asserted to be a substantial fraction of the card, ' +
      'which a future footer reflow would break loudly instead of silently. Measured on a genuine first ' +
      'run, at the welcome step, with nothing having opened the dialog on this scenario\'s behalf.',
    backendState: coldBoot,
    async navigate(page) {
      await enterFirstRunState(page);
      await expect(page.locator('#sdOnboarding'), 'the gate must show itself -- nothing here opened it').toBeVisible();
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
    area: 'onboarding-prod',
    ui: 'signal-desk-prod',
    name: 'escape-cannot-dismiss-the-consent-gate',
    kind: 'standard',
    description:
      'Onboarding is the one flow declared non-dismissible, and there is deliberately no close button in ' +
      'its markup. Escape is swallowed rather than passed through, so the keystroke neither closes this ' +
      'dialog nor reaches whatever is behind it -- checked on a genuine first run, at the consent step, ' +
      'reached by actually clicking the forward button once rather than jumping there through a debug ' +
      'hook. Without this, consent would have a back door that no amount of correct button wiring would ' +
      'close.',
    backendState: coldBoot,
    async navigate(page) {
      await enterFirstRunState(page);
      await expect(page.locator('#sdOnboarding'), 'the gate must show itself -- nothing here opened it').toBeVisible();
      await page.locator('#sdOnboarding [data-flow-primary]').click();
      await expect(page.locator('#sdOnboarding [data-flow-title]')).toHaveText('Your data stays on this device');
    },
    async expects(page) {
      await page.keyboard.press('Escape');
      await expect(page.locator('#sdOnboarding')).toBeVisible();
      await expect(page.locator('#sdOnboarding [data-flow-close]')).toHaveCount(0);
    },
    screenshots: [{ name: 'escape-cannot-dismiss-the-consent-gate' }],
  },
  {
    area: 'onboarding-prod',
    ui: 'signal-desk-prod',
    name: 'the-first-run-gate-is-a-four-step-wizard',
    kind: 'standard',
    description:
      'The source inventory describes onboarding as a 4-step wizard -- container, progress dots, title, a '
      + 'per-step body, Back and a Next whose label changes per step -- and a reading of the production page '
      + 'that stopped at the consent screen concluded that Signal Desk had replaced it with a single-screen '
      + 'gate. It has not: #sdOnboarding ships all four steps, and this scenario walks every one of them. '
      + 'Each step is checked on the three things that make it a wizard rather than a modal: the title '
      + '(#sdOnboardingTitle) names the step, exactly one .sd-flow__step body is visible at a time, and the '
      + '.sd-flow__dot progress row marks the current step as current and the ones behind it as done. '
      + '#sdOnboardBack is hidden on step 1 and present afterwards, and #sdOnboardNext relabels itself '
      + '"Get started" / "Accept & continue" / "Next" / "Finish". Finish is deliberately never clicked: it '
      + 'writes the durable consent record, and this scenario is about the wizard\'s shape, not its exit.',
    backendState: coldBoot,
    async navigate(page) {
      await enterFirstRunState(page);
      await expect(page.locator('#sdOnboarding'), 'the gate must show itself -- nothing here opened it').toBeVisible();
    },
    async expects(page) {
      const title = page.locator('#sdOnboardingTitle');
      const back = page.locator('#sdOnboardBack');
      const next = page.locator('#sdOnboardNext');
      const dots = page.locator('#sdOnboarding .sd-flow__dot');
      const steps = page.locator('#sdOnboarding .sd-flow__step');

      // One dot per step, and one step body per dot. If these ever disagree the
      // progress row is lying about how much is left.
      await expect(dots).toHaveCount(4);
      await expect(steps).toHaveCount(4);

      // Exactly one body visible at a time -- the property that separates a
      // wizard from four stacked sections with a scrollbar.
      const visibleBodies = async () => {
        let shown = 0;
        for (let i = 0; i < 4; i += 1) {
          if (await steps.nth(i).isVisible()) shown += 1;
        }
        return shown;
      };

      const walk = [
        { title: 'Welcome to BetterFingers', label: 'Get started', backVisible: false },
        { title: 'Your data stays on this device', label: 'Accept & continue', backVisible: true },
        { title: 'How it works', label: 'Next', backVisible: true },
        { title: 'Speech models', label: 'Finish', backVisible: true },
      ];

      for (let step = 0; step < walk.length; step += 1) {
        const expected = walk[step];
        await expect(title, `step ${step + 1} title`).toHaveText(expected.title);
        await expect(next, `step ${step + 1} forward label`).toHaveText(expected.label);
        if (expected.backVisible) {
          await expect(back, `step ${step + 1}: Back is available`).toBeVisible();
        } else {
          await expect(back, 'Back is hidden on step 1').toBeHidden();
        }
        expect(await visibleBodies(), `step ${step + 1}: exactly one body visible`).toBe(1);

        // The dots are the only thing on screen that says how far along this is,
        // so their state vocabulary is asserted rather than their mere presence.
        await expect(dots.nth(step), `dot ${step + 1} is current`).toHaveAttribute('data-state', 'current');
        for (let done = 0; done < step; done += 1) {
          await expect(dots.nth(done), `dot ${done + 1} is done`).toHaveAttribute('data-state', 'done');
        }

        if (step === 1) {
          // Step 2 gates: consent has to be given before the wizard will move on.
          await expect(next, 'the consent step holds the wizard').toBeDisabled();
          await page.locator('#sdOnboardConsent').check();
          await expect(next).toBeEnabled();
        }
        if (step < walk.length - 1) await next.click();
      }

      // Back really goes back, and un-marks the step it left.
      await back.click();
      await expect(title).toHaveText('How it works');
      await expect(dots.nth(2)).toHaveAttribute('data-state', 'current');
      await expect(dots.nth(3)).toHaveAttribute('data-state', 'upcoming');
    },
    screenshots: [{ name: 'the-first-run-gate-is-a-four-step-wizard' }],
  },
];
