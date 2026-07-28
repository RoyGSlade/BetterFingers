// I3.8: "Teach this persona from my edit" -- explicit-consent persona
// example learning over I3.3's /personas/:name/examples routes. Proves: no
// example is ever stored just from generating a preview pair (selecting a
// persona + running Test Persona) or previewing it, only the two-step
// prepare-then-confirm-with-consent flow reaches the network, duplicate and
// cap-eviction feedback render distinctly, the learned list persists across
// a reload, and delete/clear-all work and are reflected immediately.
//
// Retargeted at the production Signal Desk composition root (`ui:
// 'signal-desk-prod'`, signal-desk.html): the canonical `personaLearning*`
// ids these scenarios drove on index.html's dashboard do not exist in ANY
// shipping markup. The panel lives in Studio (features/studioWorkspace.js),
// which reuses features/personaLearning.js's createPersonaLearningFeature
// verbatim but binds it to distinct `sdTeach*` ids -- see
// studioWorkspace.js's "ID-COLLISION NOTE" (~lines 91-104) for why: reusing
// the canonical ids would let personaLearning.js's own import-time self-init
// IIFE ALSO wire the same elements with the wrong default hooks (it reads
// `#settingCurrentPreset`/`#draftRawText`/`#draftFinalText`, none of which
// exist in Studio), double-firing every click.
//
// ID / navigation mapping vs. the legacy index.html version of this file:
//   #tabButtonSettings + .settings-nav-button[data-section="ai-cleanup"]
//     + #settingCurrentPreset (persona picker)   -> .sd-nav__button[data-nav="studio"]
//                                                    + .sd-persona-card[data-persona-name="<name>"]
//   #tabButtonDashboard                           -> (n/a -- Studio itself is the destination)
//   #draftFinalText (edit the cleaned output)     -> #sdTestSampleInput + #sdTestPersonaButton
//     Studio's teach panel has no live draft to edit; it reads its raw/output
//     pair from the live "Test Persona" preview instead (studioWorkspace.js's
//     `getDraftPair` hook reads `livePreview.input`/`livePreview.output`,
//     populated only by a Test Persona run). Running Test Persona is the
//     Studio analogue of "editing the cleaned output": it is the only way to
//     produce a raw/output pair, and it reaches the network on its own (POST
//     /personas/test) without ever touching the persona-learning example
//     store -- so it still proves the same "producing the pair alone learns
//     nothing" property the original scenario proved via a plain textarea
//     edit.
//   #personaLearningSection                       -> #sdTeachSection
//   #personaLearningPersonaLabel                  -> #sdTeachPersonaLabel
//   #personaLearningTeachButton                   -> #sdTeachButton
//   #personaLearningPreviewRaw / ...PreviewOut     -> #sdTeachPreviewRaw / #sdTeachPreviewOut
//   #personaLearningConfirmButton                 -> #sdTeachConfirmButton
//   #personaLearningCancelButton                  -> #sdTeachCancelButton
//   #personaLearningConsentCheckbox               -> #sdTeachConsentCheckbox
//   #personaLearningAddFeedback                   -> #sdTeachAddFeedback
//   #personaLearningExamplesList                  -> #sdTeachExamplesList
//   #personaLearningClearAllButton                -> #sdTeachClearAllButton
//   #personaLearningClearFeedback                 -> #sdTeachClearFeedback
//   .persona-learning-example / .persona-learning-delete-button -- UNCHANGED:
//     rendered by personaLearning.js's own buildExamplesHtml(), independent
//     of whichever host page's ids the feature instance was wired to.

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';

const SAMPLE_TEXT = 'hey can we push standup back a bit';
const SECOND_SAMPLE_TEXT = 'a different cleaned output entirely';

// The stub's Test Persona output is a deterministic function of the sample
// text (never a fixed string) so re-running it with the SAME sample yields
// the SAME pair (needed for the duplicate-detection step) and a DIFFERENT
// sample yields a genuinely different pair (needed for the second
// learn-then-clear-all step) -- exactly the two cases the original scenarios
// exercised by typing different text into `#draftFinalText`.
function cleanedOutputFor(sample) {
  return `Cleaned: ${sample}`;
}

function baseState(overrides = {}) {
  return {
    ...coldBoot(),
    'GET /personas': { friendly: { prompt: 'Be warm and concise.' }, formal: { prompt: 'Be precise and businesslike.' } },
    'POST /personas/test': (_req, { body }) => ({ result: cleanedOutputFor(body?.sample || '') }),
    ...overrides,
  };
}

async function goToStudioWithPersona(page, personaName) {
  await page.click('.sd-nav__button[data-nav="studio"]');
  await expect(page.locator('#workspace-studio')).toBeVisible();
  await page.click(`.sd-persona-card[data-persona-name="${personaName}"]`);
  await expect(page.locator('#sdTeachPersonaLabel')).toHaveText(personaName);
}

async function runTestPersona(page, sample) {
  await page.fill('#sdTestSampleInput', sample);
  await page.click('#sdTestPersonaButton');
  await expect(page.locator('#sdTestOutputText')).toHaveText(cleanedOutputFor(sample));
}

export const personaLearningScenarios = [
  {
    area: 'persona-learning',
    name: 'no-learning-without-explicit-consent-click',
    kind: 'standard',
    ui: 'signal-desk-prod',
    description:
      'Selecting a persona and running Test Persona (which produces the raw/output pair the teach panel previews) ' +
      'never learns anything on their own -- only clicking "Teach this persona from my edit" (which just previews ' +
      'the exact raw/output pair, no request sent) and then checking consent and clicking Confirm actually calls ' +
      'the backend. Cancelling the preview beforehand learns nothing.',
    backendState: () => baseState({ 'GET /personas/friendly/examples': { persona: 'friendly', examples: [] } }),
    async navigate(page) {
      await goToStudioWithPersona(page, 'friendly');
    },
    async expects(page) {
      await expect(page.locator('#sdTeachPersonaLabel')).toHaveText('friendly');

      // Producing the preview pair alone (Test Persona): no confirm button
      // should even be enabled yet.
      await expect(page.locator('#sdTeachConfirmButton')).toBeDisabled();
      await runTestPersona(page, SAMPLE_TEXT);
      await expect(page.locator('#sdTeachConfirmButton')).toBeDisabled();

      await page.click('#sdTeachButton');
      await expect(page.locator('#sdTeachPreviewRaw')).toHaveText(SAMPLE_TEXT);
      await expect(page.locator('#sdTeachPreviewOut')).toHaveText(cleanedOutputFor(SAMPLE_TEXT));
      // Preview shown, but consent not yet checked -- confirm stays disabled.
      await expect(page.locator('#sdTeachConfirmButton')).toBeDisabled();

      // Cancel before consenting: nothing learned, list stays empty.
      await page.click('#sdTeachCancelButton');
      await expect(page.locator('#sdTeachExamplesList')).toContainText('No learned examples yet');
    },
    screenshots: [{ name: 'no-learning-without-explicit-consent-click' }],
  },
  {
    area: 'persona-learning',
    name: 'confirm-with-consent-then-duplicate-then-list-delete-clear',
    kind: 'standard',
    ui: 'signal-desk-prod',
    description:
      'Confirms a prepared raw/output pair with consent checked (the only path that ever stores an example), shows ' +
      'the newly learned example in the list, re-teaching the identical pair reports a duplicate (not stored twice), ' +
      'deleting one example removes it, and Clear All (after confirming the native dialog) empties the list.',
    backendState: () => {
      const stored = [];
      return baseState({
        'GET /personas/friendly/examples': () => ({ persona: 'friendly', examples: [...stored] }),
        'POST /personas/friendly/examples': (req, { body }) => {
          const isDup = stored.some((e) => e.raw === body.raw && e.out === body.out);
          if (isDup) return { ok: true, duplicate: true, id: 'dup-id', evicted_id: null };
          const entry = { id: `ex-${stored.length + 1}`, raw: body.raw, out: body.out, created_at: '2026-07-18T00:00:00Z' };
          stored.push(entry);
          return { ok: true, duplicate: false, id: entry.id, evicted_id: null };
        },
        'DELETE /personas/friendly/examples/ex-1': () => {
          const before = stored.length;
          const idx = stored.findIndex((e) => e.id === 'ex-1');
          if (idx >= 0) stored.splice(idx, 1);
          return { ok: true, deleted: stored.length < before };
        },
        'DELETE /personas/friendly/examples': () => {
          stored.length = 0;
          return { ok: true, cleared: true };
        },
      });
    },
    async navigate(page) {
      await goToStudioWithPersona(page, 'friendly');
    },
    async expects(page) {
      await runTestPersona(page, SAMPLE_TEXT);
      await page.click('#sdTeachButton');
      await page.check('#sdTeachConsentCheckbox');
      await expect(page.locator('#sdTeachConfirmButton')).toBeEnabled();
      await page.click('#sdTeachConfirmButton');

      await expect(page.locator('#sdTeachAddFeedback')).toHaveText('Learned this example.');
      await expect(page.locator('#sdTeachExamplesList')).toContainText(SAMPLE_TEXT);
      await expect(page.locator('#sdTeachExamplesList')).toContainText(cleanedOutputFor(SAMPLE_TEXT));

      // Re-teaching the exact same pair (same sample -> same Test Persona
      // output) reports a duplicate, not a second entry.
      await runTestPersona(page, SAMPLE_TEXT);
      await page.click('#sdTeachButton');
      await page.check('#sdTeachConsentCheckbox');
      await page.click('#sdTeachConfirmButton');
      await expect(page.locator('#sdTeachAddFeedback')).toContainText('Already learned');
      await expect(page.locator('.persona-learning-example')).toHaveCount(1);

      // Delete the one learned example.
      await page.click('.persona-learning-delete-button');
      await expect(page.locator('#sdTeachExamplesList')).toContainText('No learned examples yet');

      // Learn one more (a different sample -> a different output), then
      // Clear All (confirm the native dialog).
      await runTestPersona(page, SECOND_SAMPLE_TEXT);
      await page.click('#sdTeachButton');
      await page.check('#sdTeachConsentCheckbox');
      await page.click('#sdTeachConfirmButton');
      await expect(page.locator('.persona-learning-example')).toHaveCount(1);

      page.once('dialog', (dialog) => dialog.accept());
      await page.click('#sdTeachClearAllButton');
      await expect(page.locator('#sdTeachClearFeedback')).toContainText('reversible');
      await expect(page.locator('#sdTeachExamplesList')).toContainText('No learned examples yet');
    },
    screenshots: [{ name: 'confirm-with-consent-then-duplicate-then-list-delete-clear' }],
  },
  {
    area: 'persona-learning',
    name: 'reload-persists-and-cap-eviction-feedback',
    kind: 'standard',
    ui: 'signal-desk-prod',
    description:
      'Learned examples already on disk for a persona are shown after a fresh page load (reload persistence), and ' +
      'when the store reports an eviction (its per-persona cap was reached) the UI names that explicitly rather than ' +
      'silently swapping the oldest example out.',
    backendState: () =>
      baseState({
        'GET /personas/friendly/examples': {
          persona: 'friendly',
          examples: [{ id: 'ex-old', raw: 'previously learned raw', out: 'previously learned output', created_at: '2026-07-01T00:00:00Z' }],
        },
        'POST /personas/friendly/examples': { ok: true, duplicate: false, id: 'ex-new', evicted_id: 'ex-old' },
      }),
    async navigate(page) {
      await goToStudioWithPersona(page, 'friendly');
    },
    async expects(page) {
      // Reload persistence: an example stored in a prior session is visible
      // immediately, as soon as the persona is selected (the panel loads the
      // list on selection, before any Test Persona run).
      await expect(page.locator('#sdTeachExamplesList')).toContainText('previously learned raw');

      await runTestPersona(page, SAMPLE_TEXT);
      await page.click('#sdTeachButton');
      await page.check('#sdTeachConsentCheckbox');
      await page.click('#sdTeachConfirmButton');
      await expect(page.locator('#sdTeachAddFeedback')).toContainText('cap was reached');
    },
    screenshots: [{ name: 'reload-persists-and-cap-eviction-feedback' }],
  },
];
