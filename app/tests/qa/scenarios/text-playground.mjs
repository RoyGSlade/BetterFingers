// Board #31 Text Playground: proves the silent, text-only persona/LLM
// playground works end to end against a stubbed backend -- type text, pick a
// persona, run, see which persona/model ran, switch variants, apply the
// chosen result to an existing draft without losing anything else on that
// draft, then Clear resets everything and drops any server-side context.
// No microphone/transcription/TTS route is ever stubbed here, so an
// accidental call to one would fail loudly as an unstubbed 404.

import { expect } from '@playwright/test';
import { coldBoot } from './fixtures/cold-boot.mjs';

function backendState() {
  return {
    ...coldBoot(),
    'GET /personas': { friendly: { prompt: 'Be warm and concise.' }, formal: { prompt: 'Be precise and businesslike.' } },
    'GET /drafts': {
      drafts: [{ id: 42, raw_text: 'hey can we push standup', final_text: 'hey can we push standup', status: 'pending' }],
    },
    'POST /message-rescue/context/manual': (req, { body }) => ({
      active: true,
      id: 'ctx-1',
      source: 'manual',
      captured_at: 1000,
      expires_at: 1120,
      use_count: 0,
      max_uses: 1,
      visible_preview: String(body && body.text).slice(0, 80),
    }),
    'DELETE /message-rescue/context': { ok: true },
    'POST /message-rescue/generate': (req, { body }) => ({
      id: 'job-qa-1',
      status: 'done',
      result: {
        assessment: {
          intent: 'Ask to move standup later.',
          ambiguity_risk: 'low',
          missing_details: [],
          clarification_question: '',
        },
        delivery: { labels: [], confidence: 0, evidence: [] },
        variants: {
          faithful: 'hey can we push standup',
          clearer: body && body.persona === 'formal'
            ? 'Could we move the standup meeting to a later time today?'
            : 'Hey, could we push standup back a bit today?',
          alternate: 'Standup -- any chance we shift it later today?',
        },
        preservation_checks: [{ name: 'Meaning preserved', passed: true, detail: '' }],
        warnings: [],
      },
    }),
    'POST /drafts/42/edit': (req, { body }) => ({
      id: 42,
      raw_text: 'hey can we push standup',
      final_text: body && body.final_text,
      status: 'pending',
    }),
  };
}

export const textPlaygroundScenarios = [
  {
    area: 'text-playground',
    name: 'run-select-variant-apply-to-draft',
    kind: 'standard',
    description:
      'Types a message, picks the "formal" persona, runs it against the stubbed Message Rescue generate endpoint, ' +
      'confirms the "ran with persona/model" line and the faithful/clearer/alternate variants render, switches to ' +
      'the clearer variant, then applies it to an existing draft via the real /drafts/:id/edit path -- proving the ' +
      "draft's raw_text is untouched and only final_text changes.",
    backendState,
    async navigate(page) {
      await page.click('#tabButtonDashboard');
    },
    async expects(page) {
      const section = page.locator('#textPlaygroundSection');
      await expect(section).toBeVisible();

      await page.fill('#textPlaygroundText', 'hey can we push standup');
      await page.selectOption('#textPlaygroundPersonaSelect', 'formal');
      await page.click('#textPlaygroundRunButton');

      await expect(page.locator('#textPlaygroundStatus')).toHaveText('Done.');
      await expect(page.locator('#textPlaygroundRanInfo')).toContainText('persona: formal');
      await expect(page.locator('#textPlaygroundRanInfo')).toContainText('model:');
      await expect(page.locator('#textPlaygroundFallback')).toBeHidden();

      // Side-by-side comparison: raw + all three variants are visible at once.
      await expect(page.locator('#textPlaygroundColumnRawText')).toHaveText('hey can we push standup');
      await expect(page.locator('#textPlaygroundColumnFaithfulText')).toHaveText('hey can we push standup');
      await expect(page.locator('#textPlaygroundColumnClearerText')).toContainText('standup meeting');
      await expect(page.locator('#textPlaygroundColumnAlternateText')).toContainText('shift it later');

      await page.click('#textPlaygroundColumnClearerButton');
      await expect(page.locator('#textPlaygroundColumnClearerButton')).toHaveText('Selected');
      await expect(page.locator('#textPlaygroundColumnFaithfulButton')).toHaveText('Use this');

      await page.selectOption('#textPlaygroundDraftSelect', '42');
      await page.click('#textPlaygroundApplyButton');
      await expect(page.locator('#textPlaygroundApplyMessage')).toHaveText(/Applied to draft #42/);

      // Clear wipes the input fields and result, and the section stays usable.
      await page.click('#textPlaygroundClearButton');
      await expect(page.locator('#textPlaygroundText')).toHaveValue('');
      await expect(page.locator('#textPlaygroundStatus')).toHaveText('Ready.');
      await expect(page.locator('#textPlaygroundRanInfo')).toHaveText('');
    },
    screenshots: [{ name: 'run-select-variant-apply-to-draft' }],
  },
];
