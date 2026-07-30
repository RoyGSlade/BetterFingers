// UI-07-051: the manual Persona Wizard (`.wizard-container` in the source
// inventory, rebuilt as Signal Desk's `.sd-persona-flow` guided flow) on the
// PRODUCTION composition root (signal-desk.html, `ui: 'signal-desk-prod'`).
//
// persona-flow.mjs already proves this exact shape on the 'signal-desk'
// PREVIEW page (signal-desk-preview.html) and personas.mjs proves the
// legacy-page wizard -- neither counts as production evidence (see
// tools/parity_evidence.py's PROD_QA_TARGETS). foundry-prod.mjs covers the
// Persona Foundry path on production but explicitly does not touch the
// manual wizard (`#wizard*`) -- see that file's header comment in
// scenarios/index.mjs. This file is the missing production leg for the
// manual wizard specifically.
//
// One scenario walks the whole lifecycle end to end -- advance through all
// four steps, back up, forward again, and actually finish -- rather than
// four separate scenarios that each only prove a fragment: a wizard that
// opens step 1 and never goes further is exactly the failure mode this row
// exists to catch.

import { expect } from '@playwright/test';
import { readyProfile } from './fixtures/cold-boot.mjs';

async function openStudio(page) {
  await page.click('.sd-nav__button[data-nav="studio"]');
  await expect(page.locator('#workspace-studio')).toBeVisible();
}

let personaWrites = [];

function wizardSaveState() {
  personaWrites = [];
  return {
    ...readyProfile(),
    'POST /personas': (_req, { body }) => {
      personaWrites.push(body);
      return { ok: true, message: 'Persona saved.', name: body?.name };
    },
  };
}

export const personaWizardProdScenarios = [
  {
    area: 'persona-wizard-prod',
    ui: 'signal-desk-prod',
    name: 'wizard-advances-backs-up-and-finishes',
    kind: 'standard',
    description:
      'Studio\'s "+ New Persona" opens the guided-flow dialog on the manual wizard\'s Goal & role step, with ' +
      'its own Back/Next footer. Advancing walks Tone -> Rules -> Review & save, with the header, progress ' +
      'dots and visible body all checked at every step (these are driven by personas.js\'s own showStep(), ' +
      'not by the shell, so header/body drift is a real failure mode, not a hypothetical one). Back walks it ' +
      'out again and the chrome follows in reverse. Finally the wizard is actually FINISHED: filling the ' +
      'persona name and clicking through on Review & save posts the wizard-generated prompt to POST ' +
      '/personas, and the dialog resets to step 1 afterward -- proving Finish is wired end to end, not just ' +
      'that step 1 opens.',
    backendState: wizardSaveState,
    async navigate(page) {
      await openStudio(page);
      await page.click('#sdNewPersonaButton');
      await expect(page.locator('#foundryOverlay')).toBeVisible();
    },
    async expects(page) {
      const title = page.locator('#foundryOverlay [data-flow-title]');
      const progress = page.locator('#foundryOverlay [data-flow-progress]');
      const next = page.locator('#wizardNextButton');
      const prev = page.locator('#wizardPrevButton');

      // The dialog IS the guided-flow shell UI-07-051's anchor names, not a
      // one-off rebuild of its own -- same shell as onboarding/foundry/contact.
      await expect(page.locator('#foundryOverlay.sd-persona-flow')).toBeVisible();

      // Step 1: Goal & role.
      await expect(title).toHaveText('Goal & role');
      await expect(page.locator('#sdPersonaFlowFooter')).toBeVisible();
      await expect(prev).toBeDisabled();
      await expect(next).toHaveText('Next');
      await expect(page.locator('[data-flow-step="wizard1"]')).toBeVisible();

      // Bound, not just present: choosing "custom" reveals its textarea.
      await expect(page.locator('#wizardCustomRoleLabel')).toBeHidden();
      await page.selectOption('#wizardRole', 'custom');
      await expect(page.locator('#wizardCustomRoleLabel')).toBeVisible();
      await page.fill('#wizardCustomRole', 'You are a terse but kind editor.');

      // Advance through Tone -> Rules -> Review & save.
      for (const [step, heading] of [[2, 'Tone'], [3, 'Rules'], [4, 'Review & save']]) {
        await next.click();
        await expect(title, `step ${step} title`).toHaveText(heading);
        await expect(progress, `step ${step} progress`).toHaveAttribute('aria-label', `Step ${step} of 4`);
        await expect(page.locator(`[data-flow-step="wizard${step}"]`), `step ${step} body visible`).toBeVisible();
        await expect(page.locator('[data-flow-step="wizard1"]'), `step 1 body hidden by step ${step}`).toBeHidden();
      }

      await expect(next).toHaveText('Save Persona');
      const prompt = await page.locator('#wizardPromptPreview').inputValue();
      expect(prompt.length, 'the wizard produced no prompt from its own selections').toBeGreaterThan(40);

      // Back really goes back, and the chrome un-marks the step it left.
      await prev.click();
      await expect(title).toHaveText('Rules');
      await expect(progress).toHaveAttribute('aria-label', 'Step 3 of 4');
      await expect(page.locator('[data-flow-step="wizard3"]')).toBeVisible();
      await expect(page.locator('[data-flow-step="wizard4"]')).toBeHidden();

      // Forward again to Review & save, then actually FINISH the wizard.
      await next.click();
      await expect(title).toHaveText('Review & save');
      await expect(next).toHaveText('Save Persona');
      const promptOnReturn = await page.locator('#wizardPromptPreview').inputValue();

      // A nameless finish is refused locally and posts nothing.
      await page.fill('#wizardPersonaName', '');
      await next.click();
      await expect(page.locator('#wizardMessage')).toHaveText('Persona name is required.');
      expect(personaWrites, 'nameless finish posted nothing').toHaveLength(0);

      await page.fill('#wizardPersonaName', 'Terse Editor');
      await next.click();

      await expect(page.locator('#wizardMessage')).toHaveText('Persona saved.');
      expect(personaWrites, 'exactly one save').toHaveLength(1);
      expect(personaWrites[0].name).toBe('Terse Editor');
      expect(personaWrites[0].prompt).toBe(promptOnReturn);

      // The dialog resets to step 1 (1.5s after save) rather than staying
      // stuck on a stale Review & save screen for the next thing that opens it.
      await expect(title).toHaveText('Goal & role', { timeout: 3000 });
      await expect(page.locator('#wizardPersonaName')).toHaveValue('');
      await expect(prev).toBeDisabled();
    },
    screenshots: [{ name: 'wizard-advances-backs-up-and-finishes' }],
  },
];
