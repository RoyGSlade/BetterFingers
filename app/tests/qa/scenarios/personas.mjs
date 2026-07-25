// A1.12: QA coverage for the PERSONAS feature module extracted in Phase 1
// (app/src/renderer/features/personas.js). Closes the other half of the
// docs/BUILD_WEEK_LOG.md Phase 1 gate gap: A1.7 lifted the persona wizard out
// of main.js and no tests/qa/scenarios file proved the composition root still
// hands it its element map, its ui helpers and its getLoadedPersonas() hook.
//
// Covered paths:
//   main.js refreshPersonasAndVoices() -> the persona list itself (the Cleanup
//     Preset select), populated from GET /personas with the profile's saved
//     current_preset selected -- the "active persona" a user actually sees.
//   personas.js initWizard() -> generatePromptPreview() (step 4 template
//     output), loadExistingPersonaAdvanced() (editing a saved persona pulls its
//     stored prompt + schema-v2 fields instead of silently regenerating them),
//     updateDeleteButtonVisibility() against the server-supplied builtin list,
//     the lint panel, and the pre-save validation messages.
//
// Determinism: every asserted string is either a stub payload or a hardcoded
// template inside personas.js. No model is ever invoked -- /personas/refine,
// /personas/draft and /personas/test are deliberately left unstubbed so an
// accidental call to one would 404 loudly (see harness.mjs) instead of quietly
// looking like a pass.

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';

// GET /personas returns a bare name -> persona-entry map (backend/api/routes/
// personas.py list_personas_route() -> llm_engine.load_personas()), so key
// order is the order the select renders in.
const PERSONAS = {
  'True Janitor': { prompt: 'Clean the transcript verbatim.' },
  Polished: { prompt: 'Rewrite into confident corporate tone.' },
  'Meeting Notes': { prompt: 'Turn dictation into terse bulleted notes.' },
};

// The saved schema-v2 body GET /personas/{name} returns for the editor
// (get_persona_route -> llm_engine.get_persona). Its prompt is deliberately
// unlike anything generatePromptPreview() would produce, so an assertion on it
// proves the wizard loaded the saved value rather than regenerating one.
const SAVED_POLISHED = {
  prompt: 'Rewrite the speaker into a calm, senior-engineer register. Never add new facts.',
  temperature: 0.3,
  model_hint: 'gemma-4-e2b-q4',
  format: { caps: 'sentence', punctuation: true, signoff: '' },
  output_policy: 'tighten',
  safety_mode: 'light',
  max_completion_tokens: 900,
  chunk_size: 600,
  few_shot: [
    { raw: 'gonna circle back on that', out: 'I will follow up on that.' },
    { raw: 'lets touch base tmrw', out: 'Let us reconnect tomorrow.' },
  ],
};

// Spread coldBoot() and override only the persona surface + the one profile
// setting that selects the active persona, per the walkbook's fixture rule.
function baseState(overrides = {}) {
  const cold = coldBoot();
  const profiles = cold['GET /settings/profiles'];
  return {
    ...cold,
    'GET /personas': PERSONAS,
    'GET /settings/profiles': {
      ...profiles,
      settings: { ...profiles.settings, current_preset: 'Polished' },
    },
    ...overrides,
  };
}

async function openPersonaSettings(page) {
  await page.click('#tabButtonSettings');
  await page.click('.settings-nav-button[data-section="ai-cleanup"]');
  await expect(page.locator('.settings-section[data-section="ai-cleanup"]')).toHaveClass(/active/);
}

// Walk the wizard from step 1 to step 4, where the persona name / prompt /
// advanced fields live. showStep(4) is what triggers generatePromptPreview().
async function openWizardStep4(page) {
  await openPersonaSettings(page);
  await page.click('#wizardNextButton');
  await page.click('#wizardNextButton');
  await page.click('#wizardNextButton');
  await expect(page.locator('#wizardStepProgress')).toHaveText('Step 4 of 4: Save & Preview');
}

export const personaScenarios = [
  {
    area: 'personas',
    name: 'persona-list-renders-with-active-selection',
    kind: 'standard',
    description:
      'The Cleanup Preset control is the persona list a user actually sees. Every persona the backend returns is ' +
      'rendered as an option, in backend order, and the profile\'s saved current_preset ("Polished") comes back ' +
      'selected -- proving main.js still loads personas before applying profile settings, so the active persona is ' +
      'not silently reset to the first entry on every boot.',
    backendState: () => baseState(),
    async navigate(page) {
      await openPersonaSettings(page);
    },
    async expects(page) {
      const select = page.locator('#settingCurrentPreset');
      await expect(select).toBeVisible();
      await expect(select.locator('option')).toHaveCount(3);
      await expect(select.locator('option')).toHaveText(['True Janitor', 'Polished', 'Meeting Notes']);
      // The active persona, not just "some persona".
      await expect(select).toHaveValue('Polished');
    },
    screenshots: [{ name: 'persona-list-renders-with-active-selection' }],
  },
  {
    area: 'personas',
    name: 'wizard-loads-existing-persona-into-editor',
    kind: 'standard',
    description:
      'Step 4 of the persona wizard first shows a prompt generated from the wizard selections (janitor role, ' +
      'neutral tone, the three default rules). Typing the name of an existing persona then loads that persona ' +
      'instead: its saved prompt replaces the generated one, its schema-v2 advanced fields and few-shot examples ' +
      'are populated, and the explanatory message says which persona was loaded -- so editing a saved persona ' +
      'cannot silently overwrite its hand-tuned prompt. The Delete button appears because the server-supplied ' +
      'builtin list does not contain this name.',
    backendState: () =>
      baseState({
        // Replaces personas.js\'s hardcoded BUILTIN_PERSONAS fallback (which
        // DOES contain "Polished"). Asserting Delete is visible therefore also
        // proves the fetched list won over the fallback.
        'GET /personas-builtins': { builtins: ['True Janitor'] },
        'GET /personas/:name': (req, { params }) =>
          params.name === 'Polished'
            ? SAVED_POLISHED
            : { status: 404, body: { detail: `Persona '${params.name}' not found.` } },
      }),
    async navigate(page) {
      await openWizardStep4(page);
    },
    async expects(page) {
      // generatePromptPreview() with the shipped step 1-3 defaults.
      const preview = page.locator('#wizardPromptPreview');
      await expect(preview).toHaveValue(/You are a verbatim text cleaning machine\./);
      await expect(preview).toHaveValue(/Tone: Neutral, direct and clear\./);
      await expect(preview).toHaveValue(/Do NOT add preambles/);
      await expect(page.locator('#wizardDeleteButton')).toBeHidden();

      // Naming an existing persona swaps the editor over to the saved one.
      // fill() alone only fires `input`; blur() is what fires the `change`
      // the wizard listens on.
      await page.fill('#wizardPersonaName', 'Polished');
      await page.locator('#wizardPersonaName').blur();

      await expect(page.locator('#wizardMessage')).toContainText('Loaded "Polished"');
      await expect(page.locator('#wizardMessage')).toContainText('Regenerate from wizard');
      // The saved prompt won -- the generated one is gone.
      await expect(preview).toHaveValue(SAVED_POLISHED.prompt);

      // The schema-v2 fields live inside the collapsed "Advanced (optional)"
      // <details>; open it so the walkbook screenshot shows what was loaded.
      await page.click('#wizardAdvanced summary');
      await expect(page.locator('#wizardTemperature')).toBeVisible();

      // populateAdvancedPersonaFields(): every schema-v2 field round-trips.
      await expect(page.locator('#wizardTemperature')).toHaveValue('0.3');
      await expect(page.locator('#wizardModelHint')).toHaveValue('gemma-4-e2b-q4');
      await expect(page.locator('#wizardFormatCaps')).toHaveValue('sentence');
      await expect(page.locator('#wizardFormatPunctuation')).toBeChecked();
      await expect(page.locator('#wizardOutputPolicy')).toHaveValue('tighten');
      await expect(page.locator('#wizardSafetyMode')).toHaveValue('light');
      await expect(page.locator('#wizardMaxCompletionTokens')).toHaveValue('900');
      await expect(page.locator('#wizardChunkSize')).toHaveValue('600');

      // renderFewShotRows(): one row per saved example, raw and desired output
      // in their own textareas.
      await expect(page.locator('#wizardFewShotList .few-shot-row')).toHaveCount(2);
      await expect(page.locator('#wizardFewShotList .few-shot-raw').first()).toHaveValue(
        'gonna circle back on that',
      );
      await expect(page.locator('#wizardFewShotList .few-shot-out').first()).toHaveValue(
        'I will follow up on that.',
      );
      await expect(page.locator('#wizardFewShotList .few-shot-out').nth(1)).toHaveValue(
        'Let us reconnect tomorrow.',
      );

      // Custom (non-builtin) persona that already exists -> deletable.
      await expect(page.locator('#wizardDeleteButton')).toBeVisible();
    },
    screenshots: [{ name: 'wizard-loads-existing-persona-into-editor' }],
  },
  {
    area: 'personas',
    name: 'wizard-lint-warnings-and-save-validation',
    kind: 'standard',
    description:
      'The wizard\'s "Check prompt" button posts the drafted persona to the lint endpoint and renders each returned ' +
      'warning as its own list item in a warning-toned panel, instead of a single blob or a silent pass. Attempting ' +
      'to save without a name, and then without a prompt, produces the two distinct blocking messages and never ' +
      'reaches the save endpoint -- POST /personas is intentionally left unstubbed here, so a regression that ' +
      'skipped validation would surface as a failed save rather than a quiet one.',
    backendState: () =>
      baseState({
        'GET /personas-builtins': { builtins: ['True Janitor'] },
        // Shape from backend/api/routes/personas.py lint_persona_route().
        'POST /personas/lint': {
          warnings: [
            'No sign-off configured, so the model may invent one.',
            'Safety mode "strict" blocks the answering behaviour this prompt asks for.',
          ],
        },
      }),
    async navigate(page) {
      await openWizardStep4(page);
    },
    async expects(page) {
      // "Check prompt" lives inside the collapsed Advanced <details>.
      await page.click('#wizardAdvanced summary');
      await expect(page.locator('#wizardLintButton')).toBeVisible();
      await page.click('#wizardLintButton');

      const warnings = page.locator('#wizardLintWarnings');
      await expect(warnings).toHaveAttribute('data-tone', 'warning');
      await expect(warnings.locator('.lint-warning-list li')).toHaveCount(2);
      await expect(warnings.locator('.lint-warning-list li')).toHaveText([
        'No sign-off configured, so the model may invent one.',
        'Safety mode "strict" blocks the answering behaviour this prompt asks for.',
      ]);

      // Save with an empty name is refused with a name-specific message.
      await expect(page.locator('#wizardPersonaName')).toHaveValue('');
      await page.click('#wizardNextButton');
      await expect(page.locator('#wizardMessage')).toHaveText('Persona name is required.');
      await expect(page.locator('#wizardMessage')).toHaveAttribute('data-tone', 'danger');
      // Still on step 4 -- a refused save must not advance or reset the wizard.
      await expect(page.locator('#wizardStepProgress')).toHaveText('Step 4 of 4: Save & Preview');

      // Named but promptless is a different refusal, not the same one.
      await page.fill('#wizardPersonaName', 'QA Scratch Persona');
      await page.fill('#wizardPromptPreview', '');
      await page.click('#wizardNextButton');
      await expect(page.locator('#wizardMessage')).toHaveText('Persona prompt cannot be empty.');
      await expect(page.locator('#wizardMessage')).toHaveAttribute('data-tone', 'danger');
    },
    screenshots: [{ name: 'wizard-lint-warnings-and-save-validation' }],
  },
];
