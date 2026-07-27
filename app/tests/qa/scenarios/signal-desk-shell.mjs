// Signal Desk shell scenarios -- the first QA coverage of the workspace UI
// (DESIGN.md §11), reachable via BF_UI=signal-desk.
//
// Run with:  BF_QA_UI=signal-desk node tests/qa/run.mjs signal-desk-shell
//
// These deliberately assert only what the shell genuinely owns today: that
// the page mounts inside the real Electron shell, that the nav rail routes
// between all five workspaces, and that exactly one workspace is visible at a
// time. Feature-level assertions belong with the phases that wire those
// features up -- asserting them now would either fail or, worse, pass
// vacuously against markup nothing is reading.
//
// Vacuity note: Playwright's text/enabled assertions do NOT require
// visibility, so a hidden element still satisfies toHaveText(). Every
// assertion below that is meant to prove routing therefore checks
// visibility explicitly. (This is exactly how three voice-control scenarios
// silently passed against a hidden tab for weeks.)

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';

const WORKSPACES = ['talk', 'library', 'studio', 'utilities', 'settings'];

async function expectOnlyWorkspaceVisible(page, active) {
  for (const id of WORKSPACES) {
    const panel = page.locator(`#workspace-${id}`);
    if (id === active) {
      await expect(panel, `#workspace-${id} should be visible`).toBeVisible();
    } else {
      await expect(panel, `#workspace-${id} should be hidden`).toBeHidden();
    }
  }
}

export const signalDeskShellScenarios = [
  {
    area: 'signal-desk-shell',
    ui: 'signal-desk',
    name: 'shell-mounts-with-live-bridge',
    kind: 'standard',
    description:
      'The Signal Desk page loads inside the real Electron shell with a working IPC bridge. This is the ' +
      'claim that matters: the page previously only ever ran over file://, where its own module scripts are ' +
      'CORS-blocked, so the workspace feature modules never executed. A missing entry in senderValidation.js\'s ' +
      'RENDERER_PAGES would leave window.betterFingers undefined here, which the pervasively optional-chained ' +
      'renderer would surface as a silently dead UI rather than an error -- so the bridge is asserted directly.',
    backendState: coldBoot,
    async navigate(_page) {
      // Launched on this page already; nothing to navigate.
    },
    async expects(page) {
      await expect(page.locator('.sd-shell')).toBeVisible();
      await expect(page.locator('.sd-nav__button[data-nav="talk"]')).toBeVisible();

      const bridge = await page.evaluate(() => ({
        present: typeof window.betterFingers === 'object' && window.betterFingers !== null,
        methods: window.betterFingers ? Object.keys(window.betterFingers).length : 0,
      }));
      expect(bridge.present, 'window.betterFingers missing -- IPC privilege revoked').toBe(true);
      expect(bridge.methods).toBeGreaterThan(0);

      await expectOnlyWorkspaceVisible(page, 'talk');
    },
    screenshots: [{ name: 'shell-mounts-with-live-bridge' }],
  },
  {
    area: 'signal-desk-shell',
    ui: 'signal-desk',
    name: 'nav-rail-routes-all-five-workspaces',
    kind: 'standard',
    description:
      'Clicking each nav-rail button shows exactly that workspace and hides the other four, and marks the ' +
      'button as current. Proves the router is wired to real markup rather than to the preview page\'s former ' +
      'inline clone of it.',
    backendState: coldBoot,
    async navigate(_page) {},
    async expects(page) {
      for (const id of WORKSPACES) {
        await page.click(`.sd-nav__button[data-nav="${id}"]`);
        await expectOnlyWorkspaceVisible(page, id);
        await expect(page.locator(`.sd-nav__button[data-nav="${id}"]`)).toHaveAttribute(
          'aria-current',
          'page',
        );
      }
    },
    screenshots: [{ name: 'nav-rail-routes-all-five-workspaces' }],
  },
  {
    area: 'signal-desk-shell',
    ui: 'signal-desk',
    name: 'toast-host-renders-feedback',
    kind: 'standard',
    description:
      'Every workspace module calls hooks.showToast for save/delete/publish results and errors. This page had ' +
      'no #toastContainer and no toast implementation, so lib/toast.mjs\'s container-less no-op swallowed all of ' +
      'it -- a user could click Save or Delete and get no feedback either way. Asserts the container exists, a ' +
      'toast actually renders with its message and tone, and that it is VISIBLE (the styles live in base.css, ' +
      'which this page does not load, so a toast could exist in the DOM and still be invisible).',
    backendState: coldBoot,
    async navigate(_page) {},
    async expects(page) {
      await expect(page.locator('#toastContainer')).toHaveCount(1);

      // Drive the real shared implementation, not a hand-built element. The
      // page exposes it as window.__showToast for exactly this reason: the
      // bundler inlines lib/toast.mjs into the page chunk, so it cannot be
      // imported by path in the built app.
      await page.evaluate(() => window.__showToast('Persona saved.', 'success', 0));

      const toast = page.locator('#toastContainer .toast');
      await expect(toast).toHaveCount(1);
      await expect(toast).toBeVisible();
      await expect(toast).toHaveAttribute('data-tone', 'success');
      await expect(toast.locator('.toast-message')).toHaveText('Persona saved.');

      // Unstyled would mean the CSS never reached this page.
      const positioned = await page.evaluate(() => {
        const el = document.getElementById('toastContainer');
        return getComputedStyle(el).position;
      });
      expect(positioned, 'toast container is unstyled -- signal-desk.css rules missing').toBe('fixed');

      // The dismiss affordance must actually remove it.
      await page.click('#toastContainer .toast-close');
      await expect(page.locator('#toastContainer .toast')).toHaveCount(0);
    },
    screenshots: [{ name: 'toast-host-renders-feedback' }],
  },
  {
    area: 'signal-desk-shell',
    ui: 'signal-desk',
    name: 'status-bar-reports-real-state',
    kind: 'standard',
    description:
      'The status rail was hard-coded markup reading "Live / Ready / Local / Natural / Discord / 1.2 sec" ' +
      'regardless of what the app was doing. This drives it from a stub whose values differ from every one of ' +
      'those strings, so a regression to fabricated markup fails here rather than looking plausible. Also pins ' +
      'the two cells that must stay honest: Latency reads "—" before any dictation has run (total.last_ms is ' +
      'null), and Target app reads "—" because nothing in the app knows a destination.',
    backendState: () => ({
      ...coldBoot(),
      'GET /health': { status: 'active', transcriber: true, llm_engine: true, active_job_count: 0, active_jobs: [], last_progress_at: null, runtime_leases: {} },
      'GET /runtime/status': { transcriber_loaded: true, llm_ready: true, recording_active: false },
      'GET /settings/profiles/Default': { current_preset: 'Polished' },
      'GET /metrics': { total: { last_ms: null } },
    }),
    async navigate(_page) {},
    async expects(page) {
      // Values the stub implies -- none of which match the old hard-coded text.
      await expect(page.locator('#sdStatusSttValue')).toHaveText('Loaded');
      await expect(page.locator('#sdStatusLlmValue')).toHaveText('Ready');
      await expect(page.locator('#sdStatusMicValue')).toHaveText('Idle');
      await expect(page.locator('#sdStatusPersonaValue')).toHaveText('Polished');

      // Honest unknowns, not plausible-looking numbers.
      await expect(page.locator('#sdStatusLatencyValue')).toHaveText('—');
      await expect(page.locator('#sdStatusTargetAppValue')).toHaveText('—');

      // The rail must be visible, not merely present: it is chrome the spec
      // requires to be permanently glanceable.
      await expect(page.locator('.sd-statusbar')).toBeVisible();

      // Explicitly assert the fabricated strings are gone.
      const rail = await page.locator('.sd-statusbar').innerText();
      for (const ghost of ['Live', 'Local', 'Natural', 'Discord', '1.2 sec']) {
        expect(rail, `status bar still shows hard-coded "${ghost}"`).not.toContain(ghost);
      }
    },
    screenshots: [{ name: 'status-bar-reports-real-state' }],
  },
  {
    area: 'signal-desk-shell',
    ui: 'signal-desk',
    name: 'nav-rail-is-keyboard-navigable',
    kind: 'standard',
    description:
      'DESIGN.md §11 lists "accessibility as identity" -- full keyboard nav and visible focus. The rail shipped ' +
      'with neither a roving tabindex nor arrow keys, so every workspace button was its own tab stop and arrows ' +
      'were dead; the old tab bar it replaced had both. Drives the real keyboard on the real page: only one ' +
      'button is in the tab order, arrows move and wrap, and focus follows the selection (without that last ' +
      'part the next arrow press moves from the wrong place).',
    backendState: coldBoot,
    async navigate(_page) {},
    async expects(page) {
      const tabbable = page.locator('.sd-nav__button[tabindex="0"]');
      await expect(tabbable).toHaveCount(1);
      await expect(tabbable).toHaveAttribute('data-nav', 'talk');

      await page.focus('.sd-nav__button[data-nav="talk"]');
      await page.keyboard.press('ArrowDown');
      await expectOnlyWorkspaceVisible(page, 'library');

      // Focus must travel with the selection.
      const focusedAfterDown = await page.evaluate(() =>
        document.activeElement?.getAttribute('data-nav'),
      );
      expect(focusedAfterDown, 'focus did not follow the selection').toBe('library');
      await expect(page.locator('.sd-nav__button[tabindex="0"]')).toHaveCount(1);

      // Wrapping backwards off the first item lands on the last.
      await page.keyboard.press('ArrowUp');
      await page.keyboard.press('ArrowUp');
      await expectOnlyWorkspaceVisible(page, 'settings');

      await page.keyboard.press('Home');
      await expectOnlyWorkspaceVisible(page, 'talk');
      await page.keyboard.press('End');
      await expectOnlyWorkspaceVisible(page, 'settings');
    },
    screenshots: [{ name: 'nav-rail-is-keyboard-navigable' }],
  },
  {
    area: 'signal-desk-shell',
    ui: 'signal-desk',
    name: 'shortcuts-are-live-and-typing-safe',
    kind: 'standard',
    description:
      'The hybrid shortcut map (SPEC 5d) driven through the real keyboard. Single-key shortcuts navigate when ' +
      'focus is loose, and -- the property that matters -- go inert the moment focus is in a text field, so ' +
      'typing a draft cannot fire them. Also opens the shortcut sheet with "?", which is Shift+/ on most ' +
      'layouts: an early exact-shift match made that key silently dead, taking the only discoverable listing ' +
      'of every other binding with it.',
    backendState: coldBoot,
    async navigate(_page) {},
    async expects(page) {
      // Single-key navigation with focus loose.
      await page.locator('body').click();
      await page.keyboard.press('2');
      await expectOnlyWorkspaceVisible(page, 'library');
      await page.keyboard.press('1');
      await expectOnlyWorkspaceVisible(page, 'talk');

      // The safety property: the same key must do nothing from a text field.
      // Asserted unconditionally on purpose -- guarding this behind
      // `if (await search.count())` would mean a renamed id silently skips the
      // single most important check here while the scenario still reports PASS.
      const search = page.locator('#sdLibrarySearchInput');
      await expect(search, 'library search input missing -- typing-safety unverified').toHaveCount(1);

      await page.keyboard.press('2');
      await expectOnlyWorkspaceVisible(page, 'library');
      await search.click();
      await search.type('3');
      // "3" would jump to Studio if single-key shortcuts fired while typing.
      await expectOnlyWorkspaceVisible(page, 'library');
      await expect(search).toHaveValue('3');

      await page.keyboard.press('Escape');
      await page.locator('body').click();
      await page.keyboard.press('1');
      await expectOnlyWorkspaceVisible(page, 'talk');

      // The shortcut sheet: "?" reports key "?" WITH shiftKey true.
      await expect(page.locator('#sdShortcutSheet')).toBeHidden();
      await page.keyboard.press('?');
      await expect(page.locator('#sdShortcutSheet')).toBeVisible();
      await expect(page.locator('#sdShortcutSheetBody .sd-shortcut-row')).not.toHaveCount(0);

      // Escape closes the narrowest open thing.
      await page.keyboard.press('Escape');
      await expect(page.locator('#sdShortcutSheet')).toBeHidden();
    },
    screenshots: [{ name: 'shortcuts-are-live-and-typing-safe' }],
  },
  {
    area: 'signal-desk-shell',
    ui: 'signal-desk',
    name: 'library-cards-show-real-duration',
    kind: 'standard',
    description:
      'Recording duration was in the static markup and the mockup but renderCard() never emitted it, so it ' +
      'vanished the moment live data rendered -- the card lost the one field that most distinguishes it at a ' +
      'glance. Asserts durations render from item data. The mockup pairs duration with a waveform thumbnail, ' +
      'which is deliberately NOT drawn: items carry aggregate rms/peak only, never a per-time amplitude series, ' +
      'so any squiggle would be decoration implying it depicts that specific recording.',
    backendState: coldBoot,
    async navigate(page) {
      await page.click('.sd-nav__button[data-nav="library"]');
    },
    async expects(page) {
      await expectOnlyWorkspaceVisible(page, 'library');

      const durations = page.locator('#sdLibraryTimeline .sd-message-card__duration');
      await expect(durations).not.toHaveCount(0);

      // Real values from the seeded items (6s, 5s, 7s, 4s...), not placeholders.
      const texts = await durations.allTextContents();
      for (const text of texts) {
        expect(text, `"${text}" is not a m:ss duration`).toMatch(/^\d+:[0-5]\d$/);
      }
      expect(texts.some((t) => t !== texts[0]), 'every card shows an identical duration -- looks hard-coded').toBe(true);

      // No fabricated waveform crept back in alongside it.
      await expect(page.locator('#sdLibraryTimeline .sd-message-card__waveform')).toHaveCount(0);
    },
    screenshots: [{ name: 'library-cards-show-real-duration' }],
  },
];
