// I3.8: "Teach this persona from my edit" -- explicit-consent persona
// example learning over I3.3's /personas/:name/examples routes. Proves: no
// example is ever stored just from editing/selecting (only the two-step
// prepare-then-confirm-with-consent flow reaches the network), duplicate and
// cap-eviction feedback render distinctly, the learned list persists across
// a reload, and delete/clear-all work and are reflected immediately.

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';

const DRAFT = { id: 7, raw_text: 'hey can we push standup back a bit', final_text: 'hey can we push standup back a bit', status: 'pending' };

function baseState(overrides = {}) {
  return {
    ...coldBoot(),
    'GET /personas': { friendly: { prompt: 'Be warm and concise.' }, formal: { prompt: 'Be precise and businesslike.' } },
    'GET /drafts': { drafts: [DRAFT] },
    'GET /drafts/latest': { draft: DRAFT },
    ...overrides,
  };
}

async function goToDashboardWithPersona(page, personaName) {
  await page.reload();
  await page.waitForSelector('#backendStatus', { state: 'attached', timeout: 15000 });
  await page.click('#tabButtonSettings');
  await page.selectOption('#settingCurrentPreset', personaName);
  await page.click('#tabButtonDashboard');
  await expect(page.locator('#personaLearningSection')).toBeVisible();
}

export const personaLearningScenarios = [
  {
    area: 'persona-learning',
    name: 'no-learning-without-explicit-consent-click',
    kind: 'standard',
    description:
      'Editing the cleaned output and selecting a persona never learns anything on their own -- only clicking ' +
      '"Teach this persona from my edit" (which just previews the exact raw/output pair, no request sent) and then ' +
      'checking consent and clicking Confirm actually calls the backend. Cancelling the preview beforehand learns nothing.',
    backendState: () => baseState({ 'GET /personas/friendly/examples': { persona: 'friendly', examples: [] } }),
    async navigate(page) {
      await goToDashboardWithPersona(page, 'friendly');
    },
    async expects(page) {
      await expect(page.locator('#personaLearningPersonaLabel')).toHaveText('friendly');
      await page.fill('#draftFinalText', 'Could we push standup back a bit today?');

      // Editing alone: no confirm button should even be enabled yet.
      await expect(page.locator('#personaLearningConfirmButton')).toBeDisabled();

      await page.click('#personaLearningTeachButton');
      await expect(page.locator('#personaLearningPreviewRaw')).toHaveText(DRAFT.raw_text);
      await expect(page.locator('#personaLearningPreviewOut')).toHaveText('Could we push standup back a bit today?');
      // Preview shown, but consent not yet checked -- confirm stays disabled.
      await expect(page.locator('#personaLearningConfirmButton')).toBeDisabled();

      // Cancel before consenting: nothing learned, list stays empty.
      await page.click('#personaLearningCancelButton');
      await expect(page.locator('#personaLearningExamplesList')).toContainText('No learned examples yet');
    },
    screenshots: [{ name: 'no-learning-without-explicit-consent-click' }],
  },
  {
    area: 'persona-learning',
    name: 'confirm-with-consent-then-duplicate-then-list-delete-clear',
    kind: 'standard',
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
      await goToDashboardWithPersona(page, 'friendly');
    },
    async expects(page) {
      await page.fill('#draftFinalText', 'Could we push standup back a bit today?');
      await page.click('#personaLearningTeachButton');
      await page.check('#personaLearningConsentCheckbox');
      await expect(page.locator('#personaLearningConfirmButton')).toBeEnabled();
      await page.click('#personaLearningConfirmButton');

      await expect(page.locator('#personaLearningAddFeedback')).toHaveText('Learned this example.');
      await expect(page.locator('#personaLearningExamplesList')).toContainText(DRAFT.raw_text);
      await expect(page.locator('#personaLearningExamplesList')).toContainText('Could we push standup back a bit today?');

      // Re-teaching the exact same pair reports a duplicate, not a second entry.
      await page.click('#personaLearningTeachButton');
      await page.check('#personaLearningConsentCheckbox');
      await page.click('#personaLearningConfirmButton');
      await expect(page.locator('#personaLearningAddFeedback')).toContainText('Already learned');
      await expect(page.locator('.persona-learning-example')).toHaveCount(1);

      // Delete the one learned example.
      await page.click('.persona-learning-delete-button');
      await expect(page.locator('#personaLearningExamplesList')).toContainText('No learned examples yet');

      // Learn one more, then Clear All (confirm the native dialog).
      await page.fill('#draftFinalText', 'A different cleaned output entirely');
      await page.click('#personaLearningTeachButton');
      await page.check('#personaLearningConsentCheckbox');
      await page.click('#personaLearningConfirmButton');
      await expect(page.locator('.persona-learning-example')).toHaveCount(1);

      page.once('dialog', (dialog) => dialog.accept());
      await page.click('#personaLearningClearAllButton');
      await expect(page.locator('#personaLearningClearFeedback')).toContainText('reversible');
      await expect(page.locator('#personaLearningExamplesList')).toContainText('No learned examples yet');
    },
    screenshots: [{ name: 'confirm-with-consent-then-duplicate-then-list-delete-clear' }],
  },
  {
    area: 'persona-learning',
    name: 'reload-persists-and-cap-eviction-feedback',
    kind: 'standard',
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
      await goToDashboardWithPersona(page, 'friendly');
    },
    async expects(page) {
      // Reload persistence: an example stored in a prior session is visible immediately.
      await expect(page.locator('#personaLearningExamplesList')).toContainText('previously learned raw');

      await page.fill('#draftFinalText', 'Could we push standup back a bit today?');
      await page.click('#personaLearningTeachButton');
      await page.check('#personaLearningConsentCheckbox');
      await page.click('#personaLearningConfirmButton');
      await expect(page.locator('#personaLearningAddFeedback')).toContainText('cap was reached');
    },
    screenshots: [{ name: 'reload-persists-and-cap-eviction-feedback' }],
  },
];
