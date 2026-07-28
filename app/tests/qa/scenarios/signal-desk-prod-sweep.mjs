// Section-reachability and console-cleanliness sweep for the PRODUCTION
// Signal Desk composition root (signal-desk.html, `ui: 'signal-desk-prod'`).
//
// This is the production-page sibling of signal-desk-sections.mjs, which
// only ever drove the DESIGN/mockup preview page (signal-desk-preview.html,
// `ui: 'signal-desk'`) and is pinned there by binding decision D-0007 -- it
// says nothing about whether the composition root that actually ships
// (bootstrap/signalDeskApp.js mounted onto signal-desk.html) has the same
// five workspaces reachable, or the same Privacy wipe control live. Every
// selector below was independently re-grepped against
// app/src/renderer/signal-desk.html rather than copied from that file, per
// W1-G1-B's instruction not to trust the preview page's ids blindly --
// confirmed identical: `.sd-nav__button[data-nav=...]` for the five
// workspaces, `#workspace-<name>` panels, and the same seven
// `#sdSetSection<Name>` / `#sdSetNav<Name>` Settings ids
// (Profile/Recording/Review/AiCleanup/Notifications/Appearance/Privacy).
//
// A section that cannot be opened makes every control inside it
// unreachable, same premise as signal-desk-sections.mjs -- this file exists
// because that premise was never checked against the page real users get.

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';
import { waitForText } from '../harness.mjs';

const NAV_IDS = ['talk', 'library', 'studio', 'utilities', 'settings'];
const SET_SECTIONS = [
  'Profile', 'Recording', 'Review', 'AiCleanup', 'Notifications', 'Appearance', 'Privacy',
];

/**
 * Another worker's onboarding-prod scenarios deliberately raise the
 * `#sdOnboarding` gate this wave, and this suite reuses one shared Electron
 * window across scenarios (harness.mjs's resetBackendState reloads rather
 * than relaunching). If that gate is still up when one of these scenarios
 * starts, the shell never reached the ungated state every assertion below
 * depends on -- that is a broken precondition, not something to click
 * through silently.
 */
async function assertNoOnboardingGate(page) {
  const gate = page.locator('#sdOnboarding');
  if (await gate.isVisible().catch(() => false)) {
    throw new Error(
      '#sdOnboarding is visible at scenario start -- broken precondition (expected the ' +
        "harness's bf_onboarding_complete flag to leave the shell ungated). Refusing to " +
        'click through the gate; fix whatever left it open instead.',
    );
  }
}

/** Exactly one top-level workspace visible, and it is the requested one. */
async function expectOnlyWorkspaceVisible(page, active) {
  for (const id of NAV_IDS) {
    const workspace = page.locator(`#workspace-${id}`);
    if (id === active) {
      await expect(workspace, `#workspace-${id} should be visible once "${active}" is active`).toBeVisible();
    } else {
      await expect(workspace, `#workspace-${id} should be hidden while "${active}" is active`).toBeHidden();
    }
  }
}

// --- Scenario 3's console/pageerror collectors -----------------------------
//
// Module-scoped rather than local to the scenario object: they need to be
// written by navigate() and read (then torn down) by expects(), and this
// file's single scenario instance only ever runs once per process, so there
// is no cross-run leakage risk in keeping them here. Reset at the top of
// navigate() regardless, so a hypothetical re-run of this same scenario
// object never inherits a prior run's captures.
let consoleErrors = [];
let pageErrors = [];

function onConsoleMessage(msg) {
  if (msg.type() !== 'error') return;
  const loc = msg.location();
  consoleErrors.push(`${msg.text()} (at ${loc.url}:${loc.lineNumber}:${loc.columnNumber})`);
}

function onPageErrorEvent(err) {
  pageErrors.push(err && err.stack ? err.stack : String(err));
}

export const signalDeskProdSweepScenarios = [
  {
    area: 'signal-desk-prod-sections',
    ui: 'signal-desk-prod',
    name: 'all-five-sections-are-reachable',
    kind: 'standard',
    description:
      'The production Signal Desk shell (signal-desk.html) has five top-level workspaces on its left rail -- ' +
      'Talk, Library, Studio, Utilities and Settings -- and this is the production-page proof that every one of ' +
      'them actually opens. Clicking each nav button must reveal that workspace, hide the other four, and mark ' +
      'the clicked button aria-current="page" so assistive tech reports the same active section a sighted user ' +
      'sees. A workspace that silently fails to open makes every control inside it unreachable while looking, at ' +
      'a glance, like a perfectly normal rail -- this is the one check that would have caught that on the page ' +
      'that actually ships, not just its preview mockup.',
    backendState: coldBoot,
    async navigate(page) {
      await assertNoOnboardingGate(page);
    },
    async expects(page) {
      for (const id of NAV_IDS) {
        await page.click(`.sd-nav__button[data-nav="${id}"]`);
        await expectOnlyWorkspaceVisible(page, id);
        await expect(
          page.locator(`.sd-nav__button[data-nav="${id}"]`),
          `.sd-nav__button[data-nav="${id}"] should carry aria-current="page" once it is the active workspace`,
        ).toHaveAttribute('aria-current', 'page');
      }
    },
    screenshots: [{ name: 'all-five-sections-are-reachable' }],
  },
  {
    area: 'signal-desk-prod-sections',
    ui: 'signal-desk-prod',
    name: 'privacy-wipe-control-is-present-and-enabled',
    kind: 'standard',
    description:
      'Settings > Privacy owns the one irreversible data-destruction control on this page, "Wipe my data..." ' +
      '(#sdSetPrivacyWipeButton). This asserts it exists exactly once, is actually VISIBLE (not merely present ' +
      'in the DOM behind a hidden ancestor, which toBeEnabled() alone would happily pass), and is ENABLED so a ' +
      'real user can reach it -- a Privacy section that renders but ships its one safety-relevant control dead ' +
      'or invisible is worse than one that fails to open at all, because it looks fine in a screenshot. The ' +
      'control is asserted, never clicked: confirmed by reading settingsWorkspace.js\'s handleWipe() that a real ' +
      'click, past the native confirm() dialog, calls the backend\'s destructive wipe route against live data.',
    backendState: coldBoot,
    async navigate(page) {
      await assertNoOnboardingGate(page);
      await page.click('.sd-nav__button[data-nav="settings"]');
      await expect(page.locator('#workspace-settings')).toBeVisible();
      await page.click('#sdSetNavPrivacy');
      await expect(page.locator('#sdSetSectionPrivacy')).toBeVisible();
    },
    async expects(page) {
      const wipeButton = page.locator('#sdSetPrivacyWipeButton');
      await expect(wipeButton, '#sdSetPrivacyWipeButton must exist exactly once in the Privacy section').toHaveCount(1);
      await expect(wipeButton, '#sdSetPrivacyWipeButton must be VISIBLE, not just present in the DOM').toBeVisible();
      await expect(
        wipeButton,
        '#sdSetPrivacyWipeButton must be ENABLED on a fresh profile -- see contract note below',
      ).toBeEnabled();

      // Real contract, confirmed by reading settingsWorkspace.js's
      // bindPrivacyControls()/handleWipe() (~lines 1259-1296), not assumed
      // from the markup alone: unlike Voice Studio's clone-consent checkbox
      // (see signal-desk-sections.mjs's voice-studio-is-present-and-
      // consent-gated), there is NO consent gate on this button.
      // #sdSetPrivacyWipeVoices only controls whether cloned voices are
      // INCLUDED in the wipe once it runs -- it never toggles the button's
      // disabled state. The button starts enabled and is only ever disabled
      // transiently while a wipe request is in flight (disabled at the top
      // of handleWipe(), re-enabled in its `finally`, win or lose). So
      // "enabled on cold boot, with nothing ticked and nothing clicked" IS
      // the real contract here, not a simplified stand-in for a gate this
      // page doesn't have. NEVER click this button in this scenario.
    },
    screenshots: [{ name: 'privacy-wipe-control-is-present-and-enabled' }],
  },
  {
    area: 'signal-desk-prod-console',
    ui: 'signal-desk-prod',
    name: 'no-console-errors-during-load-and-nav-sweep',
    kind: 'standard',
    description:
      'The production shell should boot and let a user sweep every workspace and every Settings section without ' +
      'a single console.error or uncaught pageerror -- either one is a real defect even when every visible pixel ' +
      'looks correct, and neither shows up in a screenshot. The console/pageerror collectors are attached BEFORE ' +
      'this scenario\'s own reload (not relying on the reload resetBackendState() already did before navigate() ' +
      'ran, which happened before these collectors existed and so would have silently missed every boot-time ' +
      'error), so this run actually covers a full boot: attach, reload, wait for the shell and the "loaded" ready ' +
      'text, then sweep Talk, Library, Studio, Utilities, Settings, and every one of Settings\' seven sections. ' +
      'Zero exclusions: no known-noisy source was found while writing this (the WS-reconnect noise harness.mjs\'s ' +
      'stub already guards against by accepting the upgrade), so anything captured here is reported, not filtered.',
    backendState: coldBoot,
    async navigate(page) {
      consoleErrors = [];
      pageErrors = [];
      page.on('console', onConsoleMessage);
      page.on('pageerror', onPageErrorEvent);

      // Our own reload, now that both collectors are attached -- see the
      // description above for why relying on resetBackendState()'s earlier
      // reload would miss boot-time errors entirely. Same wait sequence as
      // harness.mjs's own resetBackendState()/launchApp() (reload ->
      // domcontentloaded -> shell attached -> ready text), so this reload is
      // no less reliable than the one the harness already trusts.
      await page.reload();
      await page.waitForLoadState('domcontentloaded');
      await page.waitForSelector('.sd-shell', { state: 'attached', timeout: 15000 });
      await waitForText(page.locator('#sdStatusSttValue'), /loaded/i, 15000);

      await assertNoOnboardingGate(page);

      for (const id of NAV_IDS) {
        await page.click(`.sd-nav__button[data-nav="${id}"]`);
        if (id === 'settings') {
          for (const setId of SET_SECTIONS) {
            await page.click(`#sdSetNav${setId}`);
          }
        }
      }
    },
    async expects(page) {
      try {
        await expect(
          consoleErrors,
          `console.error messages captured during boot + nav sweep (text and location):\n${consoleErrors.join('\n')}`,
        ).toEqual([]);
        await expect(
          pageErrors,
          `uncaught pageerror events captured during boot + nav sweep:\n${pageErrors.join('\n')}`,
        ).toEqual([]);
      } finally {
        // Never leak these listeners into later scenarios sharing this same
        // Electron window (run.mjs reuses one launch for the whole suite).
        page.off('console', onConsoleMessage);
        page.off('pageerror', onPageErrorEvent);
      }
    },
    screenshots: [{ name: 'no-console-errors-during-load-and-nav-sweep' }],
  },
];
