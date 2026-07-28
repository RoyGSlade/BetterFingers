// Persona creation in the guided-flow dialog (stage 13 §4c).
//
// Run with:  BF_QA_UI=signal-desk node tests/qa/run.mjs persona-flow
//
// Studio's "+ New Persona" and "Build with AI" were both `wired: false` in
// STUDIO_PLACEMENT_MAP with the same note: the wizard and the Foundry existed
// only on the old dashboard, so Studio reached across the document for their
// ids and fell back to a toast. These scenarios are the evidence for flipping
// those entries, and they assert the two failure modes that would otherwise
// look identical in a screenshot:
//
//   - a dialog that opens but is inert (a mockup with the right ids), and
//   - a dialog whose header says one thing while its body shows another,
//     which is the specific risk of chrome that FOLLOWS stepping it does not
//     own.
//
// The Foundry path is asserted only as far as opening on the Interview screen.
// Going further needs POST /personas/interview/start to return a real question,
// and a stub that answers it would be testing the fixture.

import { expect } from '@playwright/test';
import { readyProfile } from './fixtures/cold-boot.mjs';

async function openStudio(page) {
  await page.click('.sd-nav__button[data-nav="studio"]');
  await expect(page.locator('#workspace-studio')).toBeVisible();
}

export const personaFlowScenarios = [
  {
    area: 'persona-flow',
    ui: 'signal-desk',
    name: 'new-persona-opens-the-wizard',
    kind: 'standard',
    description:
      'Studio\'s "+ New Persona" opens the guided-flow dialog on the manual wizard\'s first step, with the ' +
      'wizard\'s own Back/Next footer. Previously this button reached across the document for #wizardStep1 ' +
      'and showed a toast when it could not find it. The role select and its custom-role reveal are ' +
      'exercised rather than merely located, because a ported control that renders but is unbound looks ' +
      'exactly the same in a screenshot.',
    backendState: readyProfile,
    async navigate(page) {
      await openStudio(page);
      await page.click('#sdNewPersonaButton');
      await expect(page.locator('#foundryOverlay')).toBeVisible();
    },
    async expects(page) {
      await expect(page.locator('#foundryOverlay [data-flow-title]')).toHaveText('Goal & role');
      await expect(page.locator('#sdPersonaFlowFooter')).toBeVisible();
      await expect(page.locator('#wizardPrevButton')).toBeDisabled();
      await expect(page.locator('#wizardNextButton')).toHaveText('Next');

      // Bound, not just present: choosing "custom" must reveal its textarea.
      await expect(page.locator('#wizardCustomRoleLabel')).toBeHidden();
      await page.selectOption('#wizardRole', 'custom');
      await expect(page.locator('#wizardCustomRoleLabel')).toBeVisible();
    },
    screenshots: [{ name: 'new-persona-opens-the-wizard' }],
  },
  {
    area: 'persona-flow',
    ui: 'signal-desk',
    name: 'wizard-steps-and-generates-a-prompt',
    kind: 'standard',
    description:
      'Stepping through the wizard reaches Review & save with a prompt the wizard actually generated from ' +
      'the earlier selections, and the footer button relabels to "Save Persona". The dialog header and ' +
      'progress dots follow along -- they are driven by an observer on personas.js\'s own showStep(), not ' +
      'by the shell, so header and body drifting apart is a real failure mode and is asserted at every ' +
      'step rather than only at the end.',
    backendState: readyProfile,
    async navigate(page) {
      await openStudio(page);
      await page.click('#sdNewPersonaButton');
      await expect(page.locator('#foundryOverlay')).toBeVisible();
    },
    async expects(page) {
      const title = page.locator('#foundryOverlay [data-flow-title]');
      const progress = page.locator('#foundryOverlay [data-flow-progress]');

      for (const [step, heading] of [[2, 'Tone'], [3, 'Rules'], [4, 'Review & save']]) {
        await page.click('#wizardNextButton');
        await expect(title).toHaveText(heading);
        await expect(progress).toHaveAttribute('aria-label', `Step ${step} of 4`);
        // The body must be showing the section the header names.
        await expect(page.locator(`[data-flow-step="wizard${step}"]`)).toBeVisible();
        await expect(page.locator('[data-flow-step="wizard1"]')).toBeHidden();
      }

      await expect(page.locator('#wizardNextButton')).toHaveText('Save Persona');
      const prompt = await page.locator('#wizardPromptPreview').inputValue();
      expect(prompt.length, 'the wizard produced no prompt from its own selections').toBeGreaterThan(40);

      // Back walks it out again, and the chrome follows in reverse too.
      await page.click('#wizardPrevButton');
      await expect(title).toHaveText('Rules');
      await expect(progress).toHaveAttribute('aria-label', 'Step 3 of 4');
    },
    screenshots: [{ name: 'wizard-steps-and-generates-a-prompt' }],
  },
  {
    area: 'persona-flow',
    ui: 'signal-desk',
    name: 'build-with-ai-opens-the-foundry-path',
    kind: 'standard',
    description:
      '"Build with AI" opens the same dialog on the Foundry\'s Interview screen, with the wizard footer ' +
      'hidden -- every Foundry advance is a Continue button inside the screen that produced the thing being ' +
      'continued from, so a footer Next would be a control with nothing to do. This also covers the bug ' +
      'this port surfaced: studioWorkspace preferred its cross-document fallback over the injected hook, ' +
      'so once #openFoundryButton existed it clicked that directly and started an interview inside a ' +
      'dialog nothing had opened. The dialog being VISIBLE here is what catches that.',
    backendState: readyProfile,
    async navigate(page) {
      await openStudio(page);
      await page.click('#sdOpenFoundryButton');
      await expect(page.locator('#foundryOverlay')).toBeVisible();
    },
    async expects(page) {
      await expect(page.locator('#foundryOverlay [data-flow-title]')).toHaveText('Interview');
      await expect(page.locator('[data-flow-step="interview"]')).toBeVisible();
      await expect(page.locator('[data-flow-step="wizard1"]')).toBeHidden();
      await expect(page.locator('#sdPersonaFlowFooter')).toBeHidden();
      await expect(page.locator('#foundryChatLog')).toBeVisible();
    },
    screenshots: [{ name: 'build-with-ai-opens-the-foundry-path' }],
  },
  {
    area: 'persona-flow',
    ui: 'signal-desk',
    name: 'closing-releases-the-dialog-for-either-path',
    kind: 'standard',
    description:
      'The close button hides the dialog and lets the other entry point reopen it cleanly. Worth asserting ' +
      'because the two paths share one root and two hiding mechanisms: personas.js toggles a `.hidden` ' +
      'class, the shell sets the `hidden` property, and a close that clears only one leaves a dialog that ' +
      'is shut to one of them and open to the other.',
    backendState: readyProfile,
    async navigate(page) {
      await openStudio(page);
      await page.click('#sdOpenFoundryButton');
      await expect(page.locator('#foundryOverlay')).toBeVisible();
      await page.click('#foundryCloseButton');
    },
    async expects(page) {
      await expect(page.locator('#foundryOverlay')).toBeHidden();

      await page.click('#sdNewPersonaButton');
      await expect(page.locator('#foundryOverlay')).toBeVisible();
      await expect(page.locator('#foundryOverlay [data-flow-title]')).toHaveText('Goal & role');
      await expect(page.locator('#sdPersonaFlowFooter')).toBeVisible();
    },
    screenshots: [{ name: 'closing-releases-the-dialog-for-either-path' }],
  },
];
